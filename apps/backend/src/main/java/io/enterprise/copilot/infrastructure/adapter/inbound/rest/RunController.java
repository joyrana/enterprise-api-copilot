/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.ApiException;
import io.enterprise.copilot.application.ApprovalMinter;
import io.enterprise.copilot.application.Caller;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.Requests;
import io.enterprise.copilot.infrastructure.adapter.outbound.persistence.PlatformStore;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.regex.Pattern;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

/**
 * Run lifecycle. The agent service owns run state; this controller adds what the platform owns:
 * authentication, who may approve, approval tokens, and the durable approval/audit records.
 */
@RestController
@RequestMapping("/api/v1")
@Slf4j
public class RunController {

  private static final Pattern ID = Pattern.compile("^[A-Za-z0-9_-]{1,64}$");

  private final AgentGateway agent;
  private final ApprovalMinter minter;
  private final PlatformStore store;
  private final CopilotProperties properties;
  private final ObjectMapper mapper;

  /**
   * Creates the controller.
   *
   * @param agent the agent service
   * @param minter mints approval tokens
   * @param store durable platform records
   * @param properties the configuration
   * @param mapper the JSON mapper
   */
  public RunController(
      AgentGateway agent,
      ApprovalMinter minter,
      PlatformStore store,
      CopilotProperties properties,
      ObjectMapper mapper) {
    this.agent = agent;
    this.minter = minter;
    this.store = store;
    this.properties = properties;
    this.mapper = mapper;
  }

  /**
   * Starts a run. {@code mode=async} returns 202 with the run in RUNNING state.
   *
   * @param jwt the verified token
   * @param mode {@code sync} (default) or {@code async}
   * @param request the request body
   * @param http the servlet request (for the audit record)
   * @return the run (201 or 202); 429 with {@code Retry-After} when the model queue is full
   */
  @PostMapping("/runs")
  public ResponseEntity<JsonNode> create(
      @AuthenticationPrincipal Jwt jwt,
      @RequestParam(name = "mode", defaultValue = "sync") String mode,
      @Valid @RequestBody Requests.RunCreate request,
      HttpServletRequest http) {
    if (!"sync".equals(mode) && !"async".equals(mode)) {
      throw new ApiException(
          HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", "mode must be sync or async");
    }
    Caller caller = Caller.of(jwt);
    ObjectNode body = mapper.createObjectNode();
    body.put("query", request.query());
    body.put(
        "environment",
        request.environment() != null ? request.environment() : properties.defaultEnvironment());
    if (request.conversationId() != null) {
      body.put("conversation_id", request.conversationId());
    }
    AgentGateway.Response response =
        agent.send("POST", "/internal/v1/runs", AgentSupport.query("mode", mode), caller, body);
    audit(caller, "run.create", runIdOf(response), response.status(), http);
    return AgentSupport.relay(response);
  }

  /**
   * Lists the tenant's runs, newest first.
   *
   * @param jwt the verified token
   * @param status optional status filter
   * @param limit optional page size
   * @return the runs
   */
  @GetMapping("/runs")
  public ResponseEntity<JsonNode> list(
      @AuthenticationPrincipal Jwt jwt,
      @RequestParam(name = "status", required = false) String status,
      @RequestParam(name = "limit", required = false) String limit) {
    return AgentSupport.relay(
        agent.send(
            "GET",
            "/internal/v1/runs",
            AgentSupport.query("status", status, "limit", limit),
            Caller.of(jwt),
            null));
  }

  /**
   * Fetches one run (another tenant's run is a 404).
   *
   * @param jwt the verified token
   * @param runId the run id
   * @return the run
   */
  @GetMapping("/runs/{runId}")
  public ResponseEntity<JsonNode> get(
      @AuthenticationPrincipal Jwt jwt, @PathVariable String runId) {
    return AgentSupport.relay(fetch(runId, Caller.of(jwt)));
  }

  /**
   * Approves exactly the action the approver saw.
   *
   * @param jwt the verified token
   * @param runId the run id
   * @param request carries the action hash that was displayed
   * @param http the servlet request (for the audit record)
   * @return the run after it continues
   */
  @PostMapping("/runs/{runId}/approve")
  public ResponseEntity<JsonNode> approve(
      @AuthenticationPrincipal Jwt jwt,
      @PathVariable String runId,
      @Valid @RequestBody Requests.Approve request,
      HttpServletRequest http) {
    Caller caller = Caller.of(jwt);
    JsonNode run = AgentSupport.relay(fetch(runId, caller)).getBody();
    JsonNode pending = awaiting(run);
    if (!pending.path("action_hash").asText().equals(request.actionHash())) {
      throw new ApiException(
          HttpStatus.CONFLICT, "CONFLICT", "action hash does not match the pending action");
    }
    requireApprover(caller);
    String token = minter.mint(request.actionHash(), caller.subject(), caller.tenantId());
    ObjectNode body = mapper.createObjectNode();
    body.put("approval_token", token);
    body.put("approver", caller.subject());
    AgentGateway.Response resumed =
        agent.send(
            "POST",
            "/internal/v1/runs/" + safe(runId) + "/resume",
            AgentSupport.query(),
            caller,
            body);
    audit(caller, "run.approve", runId, resumed.status(), http);
    if (resumed.ok()) {
      decide(runId, caller, request.actionHash(), "APPROVED", null);
    }
    return AgentSupport.relay(resumed);
  }

  /**
   * Rejects the pending action; nothing is executed.
   *
   * @param jwt the verified token
   * @param runId the run id
   * @param request the optional reason
   * @param http the servlet request (for the audit record)
   * @return the rejected run
   */
  @PostMapping("/runs/{runId}/reject")
  public ResponseEntity<JsonNode> reject(
      @AuthenticationPrincipal Jwt jwt,
      @PathVariable String runId,
      @Valid @RequestBody Requests.Reject request,
      HttpServletRequest http) {
    Caller caller = Caller.of(jwt);
    JsonNode pending = awaiting(AgentSupport.relay(fetch(runId, caller)).getBody());
    requireApprover(caller);
    ObjectNode body = mapper.createObjectNode();
    if (request.reason() != null) {
      body.put("reason", request.reason());
    }
    AgentGateway.Response rejected =
        agent.send(
            "POST",
            "/internal/v1/runs/" + safe(runId) + "/reject",
            AgentSupport.query(),
            caller,
            body);
    audit(caller, "run.reject", runId, rejected.status(), http);
    if (rejected.ok()) {
      decide(runId, caller, pending.path("action_hash").asText(), "REJECTED", request.reason());
    }
    return AgentSupport.relay(rejected);
  }

  /**
   * Answers a run that is waiting for missing values; the blocked call is re-grounded.
   *
   * @param jwt the verified token
   * @param runId the run id
   * @param request the user's answer
   * @param http the servlet request (for the audit record)
   * @return the run after it continues
   */
  @PostMapping("/runs/{runId}/clarify")
  public ResponseEntity<JsonNode> clarify(
      @AuthenticationPrincipal Jwt jwt,
      @PathVariable String runId,
      @Valid @RequestBody Requests.Clarify request,
      HttpServletRequest http) {
    Caller caller = Caller.of(jwt);
    ObjectNode body = mapper.createObjectNode();
    body.put("message", request.message());
    AgentGateway.Response response =
        agent.send(
            "POST",
            "/internal/v1/runs/" + safe(runId) + "/clarify",
            AgentSupport.query(),
            caller,
            body);
    audit(caller, "run.clarify", runId, response.status(), http);
    return AgentSupport.relay(response);
  }

  /**
   * Streams run events (Server-Sent Events), resumable with {@code Last-Event-ID}.
   *
   * @param jwt the verified token
   * @param runId the run id
   * @param lastEventId where to resume from
   * @return the event stream; 404 (JSON) for a missing or foreign run
   */
  @GetMapping("/runs/{runId}/events")
  public ResponseEntity<StreamingResponseBody> events(
      @AuthenticationPrincipal Jwt jwt,
      @PathVariable String runId,
      @RequestHeader(name = "Last-Event-ID", required = false) String lastEventId) {
    Caller caller = Caller.of(jwt);
    AgentSupport.relay(fetch(runId, caller)); // 404 before any bytes are sent
    String path = "/internal/v1/runs/" + safe(runId) + "/events";
    return ResponseEntity.ok()
        .contentType(MediaType.TEXT_EVENT_STREAM)
        .header("Cache-Control", "no-cache")
        .header("X-Accel-Buffering", "no")
        .body(out -> agent.stream(path, caller, lastEventId, out));
  }

  private AgentGateway.Response fetch(String runId, Caller caller) {
    return agent.send(
        "GET", "/internal/v1/runs/" + safe(runId), AgentSupport.query(), caller, null);
  }

  private static String safe(String runId) {
    if (!ID.matcher(runId).matches()) {
      throw new ApiException(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", "run not found");
    }
    return runId;
  }

  private static JsonNode awaiting(JsonNode run) {
    JsonNode pending = run.path("pending_approval");
    if (!"AWAITING_APPROVAL".equals(run.path("status").asText())
        || pending.isMissingNode()
        || pending.isNull()) {
      throw new ApiException(HttpStatus.CONFLICT, "CONFLICT", "run is not awaiting approval");
    }
    return pending;
  }

  private static void requireApprover(Caller caller) {
    if (!caller.canApprove()) {
      throw new ApiException(
          HttpStatus.FORBIDDEN, "ACCESS_DENIED", "approver lacks approval:grant");
    }
  }

  private static String runIdOf(AgentGateway.Response response) {
    return response.body() != null && response.body().hasNonNull("run_id")
        ? response.body().get("run_id").asText()
        : "-";
  }

  // The action already happened (or was refused) upstream: a failing record must not turn that
  // into an error the client would retry.
  private void decide(String runId, Caller caller, String hash, String decision, String reason) {
    try {
      store.recordDecision(runId, caller.tenantId(), hash, decision, caller.subject(), reason);
    } catch (RuntimeException e) {
      log.error("could not record the {} decision for {}", decision, runId, e);
    }
  }

  private void audit(
      Caller caller, String action, String resource, int status, HttpServletRequest http) {
    try {
      store.audit(
          caller.tenantId(),
          caller.subject(),
          action,
          resource,
          String.valueOf(status),
          PlatformRequestFilter.idOf(http));
    } catch (RuntimeException e) {
      log.error("could not write the audit record for {}", action, e);
    }
  }
}
