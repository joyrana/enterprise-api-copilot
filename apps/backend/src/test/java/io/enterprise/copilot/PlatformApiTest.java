/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.Caller;
import io.enterprise.copilot.application.TokenService;
import io.enterprise.copilot.infrastructure.adapter.outbound.persistence.PlatformStore;
import io.enterprise.copilot.support.FakeAgent;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;

/** The platform API against a scripted agent service, with the real security chain and H2. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class PlatformApiTest {

  private static final String HASH = "b".repeat(64);
  private static final String RUN = "run_0123456789abcdef";
  private static final String PLATFORM_KEY = "test-only-platform-token-key-0123456789abcdef";

  /** Replaces the HTTP agent client with a scripted one. */
  @TestConfiguration
  static class Config {
    @Bean
    @Primary
    FakeAgent fakeAgent() {
      return new FakeAgent();
    }
  }

  @Autowired private MockMvc mvc;
  @Autowired private FakeAgent agent;
  @Autowired private TokenService tokens;
  @Autowired private PlatformStore store;
  @Autowired private ObjectMapper mapper;

  @BeforeEach
  void reset() {
    agent.calls.clear();
    agent.handler = call -> FakeAgent.json(200, "{}");
  }

  private String bearer(String subject, String tenant, String... roles) {
    return "Bearer " + tokens.issuePlatformToken(new Caller(subject, tenant, Set.of(roles)));
  }

  private String alice() {
    return bearer("alice", "acme", "developer");
  }

  private String priya() {
    return bearer("priya", "acme", "approver");
  }

  private static String awaiting() {
    return "{\"run_id\":\""
        + RUN
        + "\",\"status\":\"AWAITING_APPROVAL\",\"pending_approval\":"
        + "{\"action_hash\":\""
        + HASH
        + "\",\"step_id\":\"call\"}}";
  }

  // ── authentication ────────────────────────────────────────────────────────

  @Test
  void healthIsPublicAndMatchesTheContract() throws Exception {
    mvc.perform(get("/api/v1/health"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("UP"))
        .andExpect(jsonPath("$.service").value("copilot-platform-spring"))
        .andExpect(jsonPath("$.version").exists());
  }

  @Test
  void aRequestWithoutCredentialsIs401WithTheErrorShape() throws Exception {
    mvc.perform(get("/api/v1/me"))
        .andExpect(status().isUnauthorized())
        .andExpect(header().string("WWW-Authenticate", "Bearer"))
        .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"))
        .andExpect(jsonPath("$.requestId").exists())
        .andExpect(jsonPath("$.path").value("/api/v1/me"));
  }

  private String token(
      String key, String audience, String issuer, Instant iat, Instant exp, boolean tenant)
      throws Exception {
    JwtClaimsSet.Builder claims =
        JwtClaimsSet.builder()
            .issuer(issuer)
            .audience(List.of(audience))
            .subject("alice")
            .issuedAt(iat)
            .expiresAt(exp)
            .claim("roles", List.of("developer"));
    if (tenant) {
      claims.claim("tenant_id", "acme");
    }
    NimbusJwtEncoder encoder =
        new NimbusJwtEncoder(
            new ImmutableSecret<>(
                new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256")));
    return encoder
        .encode(
            JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims.build()))
        .getTokenValue();
  }

  @Test
  void badTokensAreRejected() throws Exception {
    Instant now = Instant.now();
    List<String> bad =
        List.of(
            token(
                "forged-key-forged-key-forged-key-12345",
                "copilot-platform",
                "copilot-platform",
                now,
                now.plusSeconds(60),
                true),
            token(
                PLATFORM_KEY,
                "copilot-platform",
                "copilot-platform",
                now.minusSeconds(7200),
                now.minusSeconds(3600),
                true),
            token(PLATFORM_KEY, "someone-else", "copilot-platform", now, now.plusSeconds(60), true),
            token(PLATFORM_KEY, "copilot-platform", "evil-issuer", now, now.plusSeconds(60), true),
            token(
                PLATFORM_KEY,
                "copilot-platform",
                "copilot-platform",
                now,
                now.plusSeconds(60),
                false),
            token(
                PLATFORM_KEY,
                "copilot-platform",
                "copilot-platform",
                now,
                now.plusSeconds(999_999),
                true),
            "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhbGljZSJ9.",
            "not-a-jwt");
    for (String token : bad) {
      mvc.perform(get("/api/v1/me").header("Authorization", "Bearer " + token))
          .andExpect(status().isUnauthorized());
    }
  }

  @Test
  void devTokenSignsInKnownUsersOnly() throws Exception {
    MvcResult result =
        mvc.perform(
                post("/api/v1/auth/dev-token")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subject\":\"priya\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.token_type").value("Bearer"))
            .andReturn();
    String token =
        mapper.readTree(result.getResponse().getContentAsString()).get("access_token").asText();
    mvc.perform(get("/api/v1/me").header("Authorization", "Bearer " + token))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.subject").value("priya"))
        .andExpect(jsonPath("$.tenant_id").value("acme"))
        .andExpect(jsonPath("$.roles[0]").value("approver"));
    mvc.perform(
            post("/api/v1/auth/dev-token")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"subject\":\"mallory\"}"))
        .andExpect(status().isForbidden())
        .andExpect(jsonPath("$.code").value("ACCESS_DENIED"));
  }

  @Test
  void requestIdsAreEchoedWhenWellFormedAndReplacedOtherwise() throws Exception {
    mvc.perform(get("/api/v1/health").header("X-Request-Id", "req-abcdef123"))
        .andExpect(header().string("X-Request-Id", "req-abcdef123"));
    MvcResult bad = mvc.perform(get("/api/v1/me").header("X-Request-Id", "<script>")).andReturn();
    String generated = bad.getResponse().getHeader("X-Request-Id");
    assertThat(generated).startsWith("req_");
    assertThat(mapper.readTree(bad.getResponse().getContentAsString()).get("requestId").asText())
        .isEqualTo(generated);
  }

  // ── runs ──────────────────────────────────────────────────────────────────

  @Test
  void aRunIsRelayedWithTheCallersIdentityNotTheBodys() throws Exception {
    agent.handler =
        call -> FakeAgent.json(201, "{\"run_id\":\"" + RUN + "\",\"status\":\"COMPLETED\"}");
    mvc.perform(
            post("/api/v1/runs")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"query\":\"which API lists customers?\"}"))
        .andExpect(status().isCreated())
        .andExpect(jsonPath("$.run_id").value(RUN));
    FakeAgent.Call call = agent.calls.get(0);
    assertThat(call.path()).isEqualTo("/internal/v1/runs");
    assertThat(call.query()).containsEntry("mode", "sync");
    assertThat(call.caller()).isEqualTo(new Caller("alice", "acme", Set.of("developer")));
    assertThat(call.body().get("environment").asText()).isEqualTo("sandbox");
    assertThat(call.body().has("principal")).isFalse();
    assertThat(store.auditCount("acme", "run.create")).isGreaterThan(0);
  }

  @Test
  void asyncModeAndBusyModelAreRelayed() throws Exception {
    agent.handler =
        call -> FakeAgent.json(202, "{\"run_id\":\"" + RUN + "\",\"status\":\"RUNNING\"}");
    mvc.perform(
            post("/api/v1/runs?mode=async")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"query\":\"x\",\"conversation_id\":\"conv_0123456789abcdef\"}"))
        .andExpect(status().isAccepted());
    assertThat(agent.calls.get(0).body().get("conversation_id").asText())
        .isEqualTo("conv_0123456789abcdef");

    agent.handler =
        call ->
            new AgentGateway.Response(
                429,
                FakeAgent.json(429, "{\"code\":\"MODEL_BUSY\",\"message\":\"busy\"}").body(),
                7);
    mvc.perform(
            post("/api/v1/runs?mode=async")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"query\":\"x\"}"))
        .andExpect(status().isTooManyRequests())
        .andExpect(header().string("Retry-After", "7"))
        .andExpect(jsonPath("$.code").value("MODEL_BUSY"))
        .andExpect(jsonPath("$.path").value("/api/v1/runs"));
  }

  @Test
  void invalidRunRequestsAre400OrTooLarge413() throws Exception {
    for (String body :
        List.of(
            "{\"query\":\"\"}",
            "{\"query\":\"x\",\"principal\":{\"roles\":[\"admin\"]}}",
            "{\"query\":\"x\",\"conversation_id\":\"bogus\"}",
            "not json")) {
      mvc.perform(
              post("/api/v1/runs")
                  .header("Authorization", alice())
                  .contentType(MediaType.APPLICATION_JSON)
                  .content(body))
          .andExpect(status().isBadRequest())
          .andExpect(jsonPath("$.code").value("VALIDATION_ERROR"));
    }
    mvc.perform(
            post("/api/v1/runs?mode=bogus")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"query\":\"x\"}"))
        .andExpect(status().isBadRequest());
    mvc.perform(
            post("/api/v1/runs")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"query\":\"" + "a".repeat(70_000) + "\"}"))
        .andExpect(status().isPayloadTooLarge())
        .andExpect(jsonPath("$.code").value("PAYLOAD_TOO_LARGE"));
    assertThat(agent.calls).isEmpty();
  }

  @Test
  void listGetAndClarifyAreRelayedAndMissingRunsAre404() throws Exception {
    agent.handler =
        call ->
            call.path().endsWith("nothere")
                ? FakeAgent.json(
                    404, "{\"code\":\"RESOURCE_NOT_FOUND\",\"message\":\"run not found\"}")
                : FakeAgent.json(200, "{\"runs\":[]}");
    mvc.perform(get("/api/v1/runs?status=COMPLETED&limit=5").header("Authorization", alice()))
        .andExpect(status().isOk());
    assertThat(agent.calls.get(0).query())
        .containsEntry("status", "COMPLETED")
        .containsEntry("limit", "5");
    mvc.perform(get("/api/v1/runs/run_nothere").header("Authorization", alice()))
        .andExpect(status().isNotFound())
        .andExpect(jsonPath("$.code").value("RESOURCE_NOT_FOUND"));
    mvc.perform(get("/api/v1/runs/bad!id").header("Authorization", alice()))
        .andExpect(status().isNotFound());
    mvc.perform(
            post("/api/v1/runs/" + RUN + "/clarify")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"message\":\"₹500\"}"))
        .andExpect(status().isOk());
    assertThat(agent.calls.get(agent.calls.size() - 1).body().get("message").asText())
        .isEqualTo("₹500");
    mvc.perform(
            post("/api/v1/runs/" + RUN + "/clarify")
                .header("Authorization", alice())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isBadRequest());
  }

  // ── approvals ─────────────────────────────────────────────────────────────

  private ResultActions approve(String auth, String hash) throws Exception {
    return mvc.perform(
        post("/api/v1/runs/" + RUN + "/approve")
            .header("Authorization", auth)
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"action_hash\":\"" + hash + "\"}"));
  }

  @Test
  void onlyAnApproverWhoSawTheExactActionCanApprove() throws Exception {
    agent.handler =
        call ->
            call.method().equals("GET")
                ? FakeAgent.json(200, awaiting())
                : FakeAgent.json(200, "{\"run_id\":\"" + RUN + "\",\"status\":\"COMPLETED\"}");
    approve(alice(), HASH)
        .andExpect(status().isForbidden())
        .andExpect(jsonPath("$.code").value("ACCESS_DENIED"));
    approve(priya(), "c".repeat(64)).andExpect(status().isConflict());
    approve(priya(), "not-a-hash").andExpect(status().isBadRequest());
    assertThat(agent.calls.stream().noneMatch(c -> c.path().endsWith("/resume"))).isTrue();

    approve(priya(), HASH)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("COMPLETED"));
    FakeAgent.Call resume = agent.calls.get(agent.calls.size() - 1);
    assertThat(resume.path()).isEqualTo("/internal/v1/runs/" + RUN + "/resume");
    assertThat(resume.caller().subject()).isEqualTo("priya");
    assertThat(resume.body().get("approver").asText()).isEqualTo("priya");
    assertThat(resume.body().get("approval_token").asText()).startsWith("v1.");
    List<java.util.Map<String, Object>> decisions = store.decisions(RUN, "acme");
    assertThat(decisions).hasSize(1);
    assertThat(decisions.get(0))
        .containsEntry("decision", "APPROVED")
        .containsEntry("decided_by", "priya");
    assertThat(store.decisions(RUN, "globex")).isEmpty();
  }

  @Test
  void aRunThatIsNotAwaitingApprovalIsAConflict() throws Exception {
    agent.handler =
        call ->
            FakeAgent.json(
                200,
                "{\"run_id\":\"" + RUN + "\",\"status\":\"COMPLETED\",\"pending_approval\":null}");
    approve(priya(), HASH)
        .andExpect(status().isConflict())
        .andExpect(jsonPath("$.code").value("CONFLICT"));
  }

  @Test
  void rejectNeedsAnApproverAndRecordsTheDecision() throws Exception {
    String run = "run_fedcba9876543210";
    agent.handler =
        call ->
            call.method().equals("GET")
                ? FakeAgent.json(200, awaiting().replace(RUN, run))
                : FakeAgent.json(200, "{\"run_id\":\"" + run + "\",\"status\":\"REJECTED\"}");
    mvc.perform(
            post("/api/v1/runs/" + run + "/reject")
                .header("Authorization", bearer("vic", "acme", "viewer"))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isForbidden());
    mvc.perform(
            post("/api/v1/runs/" + run + "/reject")
                .header("Authorization", priya())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"reason\":\"not today\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("REJECTED"));
    FakeAgent.Call call = agent.calls.get(agent.calls.size() - 1);
    assertThat(call.path()).endsWith("/reject");
    assertThat(call.body().get("reason").asText()).isEqualTo("not today");
    assertThat(store.decisions(run, "acme"))
        .extracting(row -> row.get("decision"))
        .containsExactly("REJECTED");
  }

  // ── events, catalog, conversations ───────────────────────────────────────

  @Test
  void eventsAreStreamedAndResumable() throws Exception {
    agent.handler = call -> FakeAgent.json(200, "{\"run_id\":\"" + RUN + "\"}");
    MvcResult started =
        mvc.perform(
                get("/api/v1/runs/" + RUN + "/events")
                    .header("Authorization", alice())
                    .header("Last-Event-ID", "3"))
            .andExpect(request().asyncStarted())
            .andReturn();
    mvc.perform(asyncDispatch(started))
        .andExpect(status().isOk())
        .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
        .andExpect(content().string(agent.stream));
    assertThat(agent.lastEventIdSeen).isEqualTo("3");

    agent.handler =
        call ->
            FakeAgent.json(404, "{\"code\":\"RESOURCE_NOT_FOUND\",\"message\":\"run not found\"}");
    mvc.perform(
            get("/api/v1/runs/" + RUN + "/events")
                .header("Authorization", bearer("gina", "globex", "developer")))
        .andExpect(status().isNotFound());
  }

  @Test
  void catalogCallsAreRelayedWithTheirQuery() throws Exception {
    agent.handler = call -> FakeAgent.json(200, "{\"skills\":[],\"results\":[]}");
    mvc.perform(get("/api/v1/skills").header("Authorization", alice())).andExpect(status().isOk());
    mvc.perform(
            get("/api/v1/apis/search")
                .param("q", "refund a payment")
                .param("limit", "3")
                .header("Authorization", alice()))
        .andExpect(status().isOk());
    FakeAgent.Call search = agent.calls.get(agent.calls.size() - 1);
    assertThat(search.query()).containsEntry("q", "refund a payment").containsEntry("limit", "3");
    mvc.perform(get("/api/v1/apis/search").header("Authorization", alice()))
        .andExpect(status().isOk());
    assertThat(agent.calls.get(agent.calls.size() - 1).query()).containsEntry("q", "");
    mvc.perform(get("/api/v1/apis/createPayment").header("Authorization", alice()))
        .andExpect(status().isOk());
    assertThat(agent.calls.get(agent.calls.size() - 1).path())
        .isEqualTo("/internal/v1/apis/createPayment");
  }

  @Test
  void conversationsAreRelayedAndMalformedIdsAre404() throws Exception {
    agent.handler =
        call -> FakeAgent.json(201, "{\"conversation_id\":\"conv_0123456789abcdef\",\"runs\":[]}");
    mvc.perform(post("/api/v1/conversations").header("Authorization", alice()))
        .andExpect(status().isCreated());
    mvc.perform(get("/api/v1/conversations/conv_0123456789abcdef").header("Authorization", alice()))
        .andExpect(status().isCreated());
    mvc.perform(get("/api/v1/conversations/nope").header("Authorization", alice()))
        .andExpect(status().isNotFound());
  }

  @Test
  void unknownPathsAre404InThePlatformShape() throws Exception {
    mvc.perform(get("/api/v1/nope").header("Authorization", alice()))
        .andExpect(status().isNotFound())
        .andExpect(jsonPath("$.code").value("RESOURCE_NOT_FOUND"));
    JsonNode unused = mapper.createObjectNode();
    assertThat(unused).isNotNull();
  }
}
