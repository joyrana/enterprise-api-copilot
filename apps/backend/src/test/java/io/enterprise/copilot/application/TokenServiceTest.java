/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

/** Service tokens are what the Python agent service verifies; check the claims it requires. */
class TokenServiceTest {

  private static final String PLATFORM_KEY = "test-only-platform-token-key-0123456789abcdef";
  private static final String SERVICE_KEY = "test-only-service-token-key-0123456789abcdef";

  private static CopilotProperties props(String serviceKey) {
    return new CopilotProperties(
        new CopilotProperties.Auth(
            PLATFORM_KEY, "copilot-platform", "copilot-platform", 3600, true, "", null),
        new CopilotProperties.Agent("http://x", serviceKey, 120, 10),
        new CopilotProperties.Approval("a".repeat(32), 600),
        "sandbox");
  }

  private static Jwt decode(String token, String key) {
    return NimbusJwtDecoder.withSecretKey(
            new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256"))
        .macAlgorithm(MacAlgorithm.HS256)
        .build()
        .decode(token);
  }

  @Test
  void serviceTokenCarriesTheActingUserForTheAgent() {
    Caller caller = new Caller("priya", "acme", Set.of("approver", "developer"));
    Jwt jwt = decode(new TokenService(props(SERVICE_KEY)).issueServiceToken(caller), SERVICE_KEY);
    assertThat(jwt.getClaimAsString("iss")).isEqualTo("copilot-platform");
    assertThat(jwt.getAudience()).containsExactly("copilot-agent");
    assertThat(jwt.getSubject()).isEqualTo("priya");
    assertThat(jwt.getClaimAsString("tenant_id")).isEqualTo("acme");
    assertThat(jwt.getClaimAsStringList("roles")).containsExactly("approver", "developer");
    assertThat(jwt.getExpiresAt().getEpochSecond() - jwt.getIssuedAt().getEpochSecond())
        .isLessThanOrEqualTo(300); // the agent refuses longer-lived service tokens
    assertThat(Caller.of(jwt)).isEqualTo(caller);
    assertThat(Caller.of(jwt).canApprove()).isTrue();
    assertThat(new Caller("a", "t", Set.of("developer")).canApprove()).isFalse();
  }

  @Test
  void platformTokenUsesThePlatformAudience() {
    Jwt jwt =
        decode(
            new TokenService(props(SERVICE_KEY))
                .issuePlatformToken(new Caller("alice", "acme", Set.of("developer"))),
            PLATFORM_KEY);
    assertThat(jwt.getAudience()).containsExactly("copilot-platform");
  }

  @Test
  void aMissingOrShortKeyIsRefusedAtStartup() {
    assertThatThrownBy(() -> new TokenService(props(""))).hasMessageContaining("service-key");
    assertThatThrownBy(() -> new TokenService(props(null))).hasMessageContaining("service-key");
  }
}
