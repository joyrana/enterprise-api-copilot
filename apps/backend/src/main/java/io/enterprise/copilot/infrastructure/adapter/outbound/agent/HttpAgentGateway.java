/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.outbound.agent;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.ApiException;
import io.enterprise.copilot.application.Caller;
import io.enterprise.copilot.application.TokenService;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriUtils;

/** {@link AgentGateway} over the JDK HTTP client. */
@Component
public class HttpAgentGateway implements AgentGateway {

  private final HttpClient client;
  private final ObjectMapper mapper;
  private final TokenService tokens;
  private final String baseUrl;
  private final Duration timeout;

  /**
   * Creates the gateway.
   *
   * @param properties the configuration
   * @param mapper the JSON mapper
   * @param tokens issues service tokens
   */
  public HttpAgentGateway(CopilotProperties properties, ObjectMapper mapper, TokenService tokens) {
    this.mapper = mapper;
    this.tokens = tokens;
    this.baseUrl = properties.agent().baseUrl().replaceAll("/+$", "");
    this.timeout = Duration.ofSeconds(properties.agent().timeoutSeconds());
    this.client =
        HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
  }

  @Override
  public Response send(
      String method, String path, Map<String, String> query, Caller caller, JsonNode body) {
    StringBuilder uri = new StringBuilder(baseUrl).append(path);
    String separator = "?";
    for (Map.Entry<String, String> entry : query.entrySet()) {
      uri.append(separator)
          .append(UriUtils.encodeQueryParam(entry.getKey(), StandardCharsets.UTF_8))
          .append('=')
          .append(UriUtils.encodeQueryParam(entry.getValue(), StandardCharsets.UTF_8));
      separator = "&";
    }
    HttpRequest.Builder request =
        HttpRequest.newBuilder(URI.create(uri.toString()))
            .timeout(timeout)
            .header("Authorization", "Bearer " + tokens.issueServiceToken(caller))
            .header("Accept", "application/json");
    if (body != null) {
      request.header("Content-Type", "application/json");
      request.method(method, HttpRequest.BodyPublishers.ofString(body.toString()));
    } else if ("POST".equals(method)) {
      request.method(method, HttpRequest.BodyPublishers.ofString("{}"));
      request.header("Content-Type", "application/json");
    } else {
      request.method(method, HttpRequest.BodyPublishers.noBody());
    }
    try {
      HttpResponse<String> response =
          client.send(request.build(), HttpResponse.BodyHandlers.ofString());
      JsonNode json = response.body().isBlank() ? null : mapper.readTree(response.body());
      Integer retry =
          response.headers().firstValue("Retry-After").map(HttpAgentGateway::parseInt).orElse(null);
      return new Response(response.statusCode(), json, retry);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw unavailable(e);
    } catch (JsonProcessingException e) {
      throw new ApiException(
          HttpStatus.BAD_GATEWAY,
          "AGENT_INVALID_RESPONSE",
          "The agent service sent an invalid response.");
    } catch (IOException e) {
      throw unavailable(e);
    }
  }

  private static Integer parseInt(String value) {
    try {
      return Integer.valueOf(value.trim());
    } catch (NumberFormatException e) {
      return null;
    }
  }

  private static ApiException unavailable(Exception cause) {
    return new ApiException(
        HttpStatus.BAD_GATEWAY,
        "AGENT_UNAVAILABLE",
        "The agent service is unavailable (" + cause.getClass().getSimpleName() + ").");
  }

  @Override
  public void stream(String path, Caller caller, String lastEventId, OutputStream out)
      throws IOException {
    HttpRequest.Builder request =
        HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Authorization", "Bearer " + tokens.issueServiceToken(caller))
            .header("Accept", "text/event-stream")
            .GET();
    if (lastEventId != null && !lastEventId.isBlank()) {
      request.header("Last-Event-ID", lastEventId);
    }
    try {
      HttpResponse<InputStream> response =
          client.send(request.build(), HttpResponse.BodyHandlers.ofInputStream());
      if (response.statusCode() != 200) {
        throw new IOException("agent event stream returned HTTP " + response.statusCode());
      }
      try (InputStream in = response.body()) {
        byte[] buffer = new byte[4096];
        int read;
        while ((read = in.read(buffer)) != -1) {
          out.write(buffer, 0, read);
          out.flush();
        }
      }
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IOException("interrupted while streaming", e);
    }
  }
}
