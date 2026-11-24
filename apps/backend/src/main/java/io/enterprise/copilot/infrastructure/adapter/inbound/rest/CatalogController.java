/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import com.fasterxml.jackson.databind.JsonNode;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.Caller;
import java.nio.charset.StandardCharsets;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriUtils;

/** Skills and API catalog reads, served by the agent service's skill runtime. */
@RestController
@RequestMapping("/api/v1")
public class CatalogController {

  private final AgentGateway agent;

  /**
   * Creates the controller.
   *
   * @param agent the agent service
   */
  public CatalogController(AgentGateway agent) {
    this.agent = agent;
  }

  /**
   * Lists registered skills.
   *
   * @param jwt the verified token
   * @return the skills
   */
  @GetMapping("/skills")
  public ResponseEntity<JsonNode> skills(@AuthenticationPrincipal Jwt jwt) {
    return AgentSupport.relay(
        agent.send("GET", "/internal/v1/skills", AgentSupport.query(), Caller.of(jwt), null));
  }

  /**
   * Searches the API catalog.
   *
   * @param jwt the verified token
   * @param q the natural-language query
   * @param limit the maximum number of hits
   * @return ranked operations
   */
  @GetMapping("/apis/search")
  public ResponseEntity<JsonNode> search(
      @AuthenticationPrincipal Jwt jwt,
      @RequestParam(name = "q", required = false) String q,
      @RequestParam(name = "limit", required = false) String limit) {
    return AgentSupport.relay(
        agent.send(
            "GET",
            "/internal/v1/apis/search",
            AgentSupport.query("q", q == null ? "" : q, "limit", limit),
            Caller.of(jwt),
            null));
  }

  /**
   * Describes one operation.
   *
   * @param jwt the verified token
   * @param operationId the operation id
   * @return the operation contract
   */
  @GetMapping("/apis/{operationId}")
  public ResponseEntity<JsonNode> describe(
      @AuthenticationPrincipal Jwt jwt, @PathVariable String operationId) {
    return AgentSupport.relay(
        agent.send(
            "GET",
            "/internal/v1/apis/" + UriUtils.encodePathSegment(operationId, StandardCharsets.UTF_8),
            AgentSupport.query(),
            Caller.of(jwt),
            null));
  }
}
