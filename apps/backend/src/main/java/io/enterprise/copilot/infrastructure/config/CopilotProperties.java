/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * Platform configuration ({@code copilot.*}).
 *
 * @param auth how callers authenticate
 * @param agent how the platform reaches the agent service
 * @param approval approval token settings
 * @param defaultEnvironment environment used when a request does not name one
 */
@ConfigurationProperties(prefix = "copilot")
public record CopilotProperties(
    @DefaultValue Auth auth,
    @DefaultValue Agent agent,
    @DefaultValue Approval approval,
    @DefaultValue("sandbox") String defaultEnvironment) {

  /**
   * Caller authentication.
   *
   * @param tokenKey HS256 secret (at least 32 bytes) for platform tokens in local mode
   * @param issuer expected token issuer
   * @param audience expected token audience
   * @param maxTtlSeconds longest accepted token lifetime
   * @param devTokenEnabled whether {@code POST /api/v1/auth/dev-token} issues tokens (local only)
   * @param devUsers synthetic users as {@code subject:tenant:role+role,...}
   * @param oidcIssuerUri when set, tokens are verified against this OIDC issuer instead of the key
   */
  public record Auth(
      String tokenKey,
      @DefaultValue("copilot-platform") String issuer,
      @DefaultValue("copilot-platform") String audience,
      @DefaultValue("3600") int maxTtlSeconds,
      @DefaultValue("false") boolean devTokenEnabled,
      @DefaultValue(
              "alice:acme:developer,priya:acme:approver,vic:acme:viewer,root:acme:admin,"
                  + "gina:globex:developer")
          String devUsers,
      String oidcIssuerUri) {}

  /**
   * Agent service connection.
   *
   * @param baseUrl root URL of the agent service
   * @param serviceKey HS256 secret shared with the agent service for service tokens
   * @param serviceTokenTtlSeconds lifetime of a service token (the agent accepts at most 300)
   * @param timeoutSeconds per-request timeout
   */
  public record Agent(
      @DefaultValue("http://127.0.0.1:8001") String baseUrl,
      String serviceKey,
      @DefaultValue("120") int serviceTokenTtlSeconds,
      @DefaultValue("180") int timeoutSeconds) {}

  /**
   * Approval tokens.
   *
   * @param key HMAC key shared with the agent's skill runtime (at least 32 bytes)
   * @param ttlSeconds lifetime of an approval token
   */
  public record Approval(String key, @DefaultValue("600") int ttlSeconds) {}
}
