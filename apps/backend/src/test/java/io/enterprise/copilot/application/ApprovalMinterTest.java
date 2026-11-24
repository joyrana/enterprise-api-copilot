/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.time.Instant;
import java.util.Base64;
import org.junit.jupiter.api.Test;

/** The token format is the contract with the agent's skill runtime (ADR-0006). */
class ApprovalMinterTest {

  private static final String KEY = "test-only-approval-key-0123456789abcdef0123";
  private static final ObjectMapper MAPPER = new ObjectMapper();

  private static ApprovalMinter minter(String key) {
    return new ApprovalMinter(
        new CopilotProperties(
            new CopilotProperties.Auth("k", "i", "a", 3600, false, "", null),
            new CopilotProperties.Agent("http://x", "k", 120, 10),
            new CopilotProperties.Approval(key, 600),
            "sandbox"),
        MAPPER);
  }

  @Test
  void signatureMatchesTheRuntimeKnownAnswer() {
    // Computed with skills.runtime.approvals.ApprovalSigner's algorithm in Python:
    // HMAC-SHA256(key, "v1." + body), base64url without padding.
    assertThat(minter(KEY).sign("eyJhIjoxfQ"))
        .isEqualTo("YUfA7qzsijE_z4IXJmn2eM_EiJgVPil1uCLgcJF2Br8");
  }

  @Test
  void tokenCarriesTheGrantTheRuntimeExpects() throws Exception {
    String hash = "a".repeat(64);
    String token = minter(KEY).mint(hash, "priya", "acme", Instant.ofEpochSecond(1_700_000_000L));
    String[] parts = token.split("\\.");
    assertThat(parts).hasSize(3).startsWith("v1");
    assertThat(parts[2]).isEqualTo(minter(KEY).sign(parts[1]));
    JsonNode grant = MAPPER.readTree(Base64.getUrlDecoder().decode(parts[1]));
    assertThat(grant.get("action_hash").asText()).isEqualTo(hash);
    assertThat(grant.get("approver").asText()).isEqualTo("priya");
    assertThat(grant.get("tenant_id").asText()).isEqualTo("acme");
    assertThat(grant.get("issued_at").asDouble()).isEqualTo(1_700_000_000.0);
    assertThat(grant.get("expires_at").asDouble()).isEqualTo(1_700_000_600.0);
    assertThat(grant.get("approval_id").asText()).hasSizeGreaterThan(16);
    assertThat(minter(KEY).mint(hash, "priya", "acme"))
        .isNotEqualTo(minter(KEY).mint(hash, "priya", "acme"));
  }

  @Test
  void aShortKeyIsRefused() {
    assertThatThrownBy(() -> minter("short")).hasMessageContaining("at least 32 bytes");
  }
}
