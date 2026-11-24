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
import io.enterprise.copilot.application.Caller;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Conversations (memory for follow-up turns), owned by the agent service per tenant. */
@RestController
@RequestMapping("/api/v1/conversations")
public class ConversationController {

  private static final Pattern ID = Pattern.compile("^conv_[0-9a-f]{16}$");

  private final AgentGateway agent;

  /**
   * Creates the controller.
   *
   * @param agent the agent service
   */
  public ConversationController(AgentGateway agent) {
    this.agent = agent;
  }

  /**
   * Starts an empty conversation for the caller's tenant.
   *
   * @param jwt the verified token
   * @return the conversation (201)
   */
  @PostMapping
  public ResponseEntity<JsonNode> create(@AuthenticationPrincipal Jwt jwt) {
    return AgentSupport.relay(
        agent.send(
            "POST", "/internal/v1/conversations", AgentSupport.query(), Caller.of(jwt), null));
  }

  /**
   * Fetches a conversation and its runs. Another tenant's conversation is a 404.
   *
   * @param jwt the verified token
   * @param conversationId the conversation id
   * @return the conversation
   */
  @GetMapping("/{conversationId}")
  public ResponseEntity<JsonNode> get(
      @AuthenticationPrincipal Jwt jwt, @PathVariable String conversationId) {
    if (!ID.matcher(conversationId).matches()) {
      throw new ApiException(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", "conversation not found");
    }
    return AgentSupport.relay(
        agent.send(
            "GET",
            "/internal/v1/conversations/" + conversationId,
            AgentSupport.query(),
            Caller.of(jwt),
            null));
  }
}
