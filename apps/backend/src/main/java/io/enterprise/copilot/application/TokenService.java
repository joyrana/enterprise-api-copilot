/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.stereotype.Service;

/**
 * Issues the tokens this service signs: platform tokens for synthetic users in local mode, and
 * short-lived service tokens that carry the acting user to the agent service.
 */
@Service
public class TokenService {

  /** Audience of service tokens (the agent service). */
  public static final String AGENT_AUDIENCE = "copilot-agent";

  /** Issuer of every token this service signs. */
  public static final String ISSUER = "copilot-platform";

  private static final int MIN_KEY_BYTES = 32;

  private final CopilotProperties properties;
  private final JwtEncoder platformEncoder;
  private final JwtEncoder serviceEncoder;

  /**
   * Creates the service.
   *
   * @param properties the configuration
   */
  public TokenService(CopilotProperties properties) {
    this.properties = properties;
    this.platformEncoder = encoder(properties.auth().tokenKey(), "copilot.auth.token-key");
    this.serviceEncoder = encoder(properties.agent().serviceKey(), "copilot.agent.service-key");
  }

  private static JwtEncoder encoder(String key, String name) {
    if (key == null || key.getBytes(StandardCharsets.UTF_8).length < MIN_KEY_BYTES) {
      throw new IllegalStateException(
          name + " must be set to at least " + MIN_KEY_BYTES + " bytes");
    }
    SecretKey secret = new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    return new NimbusJwtEncoder(new ImmutableSecret<>(secret));
  }

  /**
   * Issues a platform token for a (synthetic, local-mode) user.
   *
   * @param caller the user
   * @return the signed token
   */
  public String issuePlatformToken(Caller caller) {
    return sign(
        platformEncoder, caller, properties.auth().audience(), properties.auth().maxTtlSeconds());
  }

  /**
   * Issues a short-lived service token for the agent service, carrying the acting user.
   *
   * @param caller the user the platform is acting for
   * @return the signed token
   */
  public String issueServiceToken(Caller caller) {
    return sign(
        serviceEncoder, caller, AGENT_AUDIENCE, properties.agent().serviceTokenTtlSeconds());
  }

  private static String sign(JwtEncoder encoder, Caller caller, String audience, int ttlSeconds) {
    Instant now = Instant.now();
    JwtClaimsSet claims =
        JwtClaimsSet.builder()
            .issuer(ISSUER)
            .audience(List.of(audience))
            .subject(caller.subject())
            .issuedAt(now)
            .expiresAt(now.plusSeconds(ttlSeconds))
            .claim("tenant_id", caller.tenantId())
            .claim("roles", caller.roles().stream().sorted().toList())
            .build();
    JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
    return encoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue();
  }
}
