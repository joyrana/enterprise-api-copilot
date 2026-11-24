/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.outbound;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.ApiException;
import io.enterprise.copilot.application.Caller;
import io.enterprise.copilot.application.TokenService;
import io.enterprise.copilot.infrastructure.adapter.outbound.agent.HttpAgentGateway;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.io.ByteArrayOutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** The real HTTP client against a local stub of the agent service. */
class HttpAgentGatewayTest {

  private static final Caller CALLER = new Caller("alice", "acme", Set.of("developer"));
  private HttpServer server;
  private final AtomicReference<String> seenAuth = new AtomicReference<>();
  private final AtomicReference<String> seenUri = new AtomicReference<>();
  private final AtomicReference<String> seenBody = new AtomicReference<>();
  private final AtomicReference<String> seenLastEventId = new AtomicReference<>();

  @BeforeEach
  void start() throws Exception {
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext(
        "/",
        exchange -> {
          seenAuth.set(exchange.getRequestHeaders().getFirst("Authorization"));
          seenUri.set(exchange.getRequestURI().toString());
          seenBody.set(
              new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
          seenLastEventId.set(exchange.getRequestHeaders().getFirst("Last-Event-ID"));
          String path = exchange.getRequestURI().getPath();
          byte[] body;
          int status = 200;
          if (path.endsWith("/busy")) {
            status = 429;
            exchange.getResponseHeaders().add("Retry-After", "9");
            body = "{\"code\":\"MODEL_BUSY\"}".getBytes(StandardCharsets.UTF_8);
          } else if (path.endsWith("/garbage")) {
            body = "<html>".getBytes(StandardCharsets.UTF_8);
          } else if (path.endsWith("/empty")) {
            status = 204;
            body = new byte[0];
          } else if (path.endsWith("/events")) {
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            body = "id: 1\nevent: created\ndata: {}\n\n".getBytes(StandardCharsets.UTF_8);
          } else if (path.endsWith("/nostream")) {
            status = 404;
            body = "{}".getBytes(StandardCharsets.UTF_8);
          } else {
            body = "{\"ok\":true}".getBytes(StandardCharsets.UTF_8);
          }
          exchange.sendResponseHeaders(status, status == 204 ? -1 : body.length);
          if (status != 204) {
            exchange.getResponseBody().write(body);
          }
          exchange.close();
        });
    server.start();
  }

  @AfterEach
  void stop() {
    server.stop(0);
  }

  private HttpAgentGateway gateway(String baseUrl) {
    CopilotProperties props =
        new CopilotProperties(
            new CopilotProperties.Auth(
                "k".repeat(40), "copilot-platform", "copilot-platform", 3600, false, "", null),
            new CopilotProperties.Agent(baseUrl, "s".repeat(40), 120, 5),
            new CopilotProperties.Approval("a".repeat(40), 600),
            "sandbox");
    return new HttpAgentGateway(props, new ObjectMapper(), new TokenService(props));
  }

  private HttpAgentGateway gateway() {
    return gateway("http://127.0.0.1:" + server.getAddress().getPort() + "/");
  }

  @Test
  void requestsCarryAServiceTokenQueryAndBody() throws Exception {
    Map<String, String> query = new LinkedHashMap<>();
    query.put("q", "refund a payment & more");
    query.put("limit", "3");
    AgentGateway.Response response =
        gateway()
            .send(
                "POST", "/internal/v1/x", query, CALLER, new ObjectMapper().readTree("{\"a\":1}"));
    assertThat(response.ok()).isTrue();
    assertThat(response.body().get("ok").asBoolean()).isTrue();
    assertThat(seenAuth.get()).startsWith("Bearer ey");
    assertThat(seenUri.get())
        .isEqualTo("/internal/v1/x?q=refund%20a%20payment%20%26%20more&limit=3");
    assertThat(seenBody.get()).isEqualTo("{\"a\":1}");
  }

  @Test
  void aBodylessPostSendsAnEmptyObjectAndGetSendsNothing() {
    gateway().send("POST", "/internal/v1/x", Map.of(), CALLER, null);
    assertThat(seenBody.get()).isEqualTo("{}");
    gateway().send("GET", "/internal/v1/x", Map.of(), CALLER, null);
    assertThat(seenBody.get()).isEmpty();
  }

  @Test
  void retryAfterAndEmptyBodiesAreParsed() {
    AgentGateway.Response busy = gateway().send("GET", "/busy", Map.of(), CALLER, null);
    assertThat(busy.status()).isEqualTo(429);
    assertThat(busy.retryAfterSeconds()).isEqualTo(9);
    assertThat(busy.ok()).isFalse();
    AgentGateway.Response empty = gateway().send("GET", "/empty", Map.of(), CALLER, null);
    assertThat(empty.body()).isNull();
  }

  @Test
  void anInvalidAgentBodyAndAnUnreachableAgentAreBadGateway() {
    assertThatThrownBy(() -> gateway().send("GET", "/garbage", Map.of(), CALLER, null))
        .isInstanceOfSatisfying(
            ApiException.class, e -> assertThat(e.getCode()).isEqualTo("AGENT_INVALID_RESPONSE"));
    assertThatThrownBy(
            () -> gateway("http://127.0.0.1:1").send("GET", "/x", Map.of(), CALLER, null))
        .isInstanceOfSatisfying(
            ApiException.class, e -> assertThat(e.getCode()).isEqualTo("AGENT_UNAVAILABLE"));
  }

  @Test
  void eventStreamsAreCopiedAndResumed() throws Exception {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    gateway().stream("/internal/v1/runs/run_0/events", CALLER, "4", out);
    assertThat(out.toString(StandardCharsets.UTF_8))
        .isEqualTo("id: 1\nevent: created\ndata: {}\n\n");
    assertThat(seenLastEventId.get()).isEqualTo("4");
    assertThatThrownBy(
            () -> gateway().stream("/nostream", CALLER, null, new ByteArrayOutputStream()))
        .hasMessageContaining("HTTP 404");
  }
}
