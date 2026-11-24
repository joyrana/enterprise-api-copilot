/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Map;

/**
 * Port to the agent service ({@code contracts/openapi/agent-service.yaml}). Every call carries a
 * short-lived service token naming the acting user; the agent derives tenant and principal from it,
 * never from the body.
 */
public interface AgentGateway {

  /**
   * One agent response.
   *
   * @param status the HTTP status
   * @param body the JSON body, or null when empty
   * @param retryAfterSeconds the {@code Retry-After} value, or null
   */
  record Response(int status, JsonNode body, Integer retryAfterSeconds) {

    /**
     * Whether the status is 2xx.
     *
     * @return true on success
     */
    public boolean ok() {
      return status >= 200 && status < 300;
    }
  }

  /**
   * Calls an agent endpoint.
   *
   * @param method the HTTP method
   * @param path the path below the agent base URL (for example {@code /internal/v1/runs})
   * @param query query parameters (may be empty)
   * @param caller the acting user
   * @param body the JSON body, or null
   * @return the response (also for 4xx/5xx; transport failures raise {@link ApiException})
   */
  Response send(
      String method, String path, Map<String, String> query, Caller caller, JsonNode body);

  /**
   * Copies an agent Server-Sent Events stream to {@code out} until the agent closes it.
   *
   * @param path the events path
   * @param caller the acting user
   * @param lastEventId the {@code Last-Event-ID} to resume from, or null
   * @param out the destination (flushed after each chunk)
   * @throws IOException if the stream breaks
   */
  void stream(String path, Caller caller, String lastEventId, OutputStream out) throws IOException;
}
