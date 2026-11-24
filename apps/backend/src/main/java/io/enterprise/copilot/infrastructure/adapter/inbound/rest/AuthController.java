/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import io.enterprise.copilot.application.ApiException;
import io.enterprise.copilot.application.Caller;
import io.enterprise.copilot.application.TokenService;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.Requests;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import jakarta.validation.Valid;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Local-mode sign-in and caller identity. */
@RestController
@RequestMapping("/api/v1")
public class AuthController {

  private final TokenService tokens;
  private final CopilotProperties properties;
  private final Map<String, Caller> devUsers = new LinkedHashMap<>();

  /**
   * Creates the controller.
   *
   * @param tokens issues platform tokens
   * @param properties the configuration (dev users and whether dev sign-in is enabled)
   */
  public AuthController(TokenService tokens, CopilotProperties properties) {
    this.tokens = tokens;
    this.properties = properties;
    for (String entry : properties.auth().devUsers().split(",")) {
      String[] parts = entry.trim().split(":", 3);
      if (parts.length == 3) {
        devUsers.put(parts[0], new Caller(parts[0], parts[1], Set.of(parts[2].split("\\+"))));
      }
    }
  }

  /**
   * Issues a token for a synthetic user. Disabled outside local mode (404), where tokens come from
   * the identity provider.
   *
   * @param request the user to sign in as
   * @return the token response
   */
  @PostMapping("/auth/dev-token")
  public Map<String, Object> devToken(@Valid @RequestBody Requests.DevToken request) {
    if (!properties.auth().devTokenEnabled()) {
      throw new ApiException(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", "not found");
    }
    Caller user = devUsers.get(request.subject());
    if (user == null) {
      throw new ApiException(HttpStatus.FORBIDDEN, "ACCESS_DENIED", "unknown development user");
    }
    return Map.of(
        "access_token",
        tokens.issuePlatformToken(user),
        "token_type",
        "Bearer",
        "expires_in",
        properties.auth().maxTtlSeconds());
  }

  /**
   * The authenticated caller.
   *
   * @param jwt the verified token
   * @return subject, tenant and roles
   */
  @GetMapping("/me")
  public Map<String, Object> me(@AuthenticationPrincipal Jwt jwt) {
    Caller caller = Caller.of(jwt);
    return Map.of(
        "subject",
        caller.subject(),
        "tenant_id",
        caller.tenantId(),
        "roles",
        caller.roles().stream().sorted().toList());
  }
}
