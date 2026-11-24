/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import com.fasterxml.jackson.databind.JsonNode;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.ApiException;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/** Shared helpers for controllers that relay agent responses. */
final class AgentSupport {

  private AgentSupport() {}

  /**
   * Relays an agent response unchanged (status and JSON body) when it succeeded; otherwise raises
   * the error in the platform shape, keeping the agent's status, code and message.
   *
   * @param response the agent response
   * @return the relayed response
   */
  static ResponseEntity<JsonNode> relay(AgentGateway.Response response) {
    if (response.ok()) {
      return ResponseEntity.status(response.status()).body(response.body());
    }
    throw asException(response);
  }

  /**
   * Converts a failed agent response to an {@link ApiException}.
   *
   * @param response the failed response
   * @return the exception
   */
  static ApiException asException(AgentGateway.Response response) {
    JsonNode body = response.body();
    String code =
        body != null && body.hasNonNull("code") ? body.get("code").asText() : "AGENT_ERROR";
    String message =
        body != null && body.hasNonNull("message")
            ? body.get("message").asText()
            : "The agent service reported an error.";
    HttpStatus status = HttpStatus.resolve(response.status());
    return new ApiException(
        status != null ? status : HttpStatus.BAD_GATEWAY,
        code,
        message,
        response.retryAfterSeconds());
  }

  /**
   * Query parameters present in a request, for relaying.
   *
   * @param pairs name/value pairs; null values are dropped
   * @return the map
   */
  static Map<String, String> query(String... pairs) {
    java.util.LinkedHashMap<String, String> out = new java.util.LinkedHashMap<>();
    for (int i = 0; i + 1 < pairs.length; i += 2) {
      if (pairs[i + 1] != null) {
        out.put(pairs[i], pairs[i + 1]);
      }
    }
    return out;
  }
}
