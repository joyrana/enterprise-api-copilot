/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import java.util.Set;
import org.springframework.security.oauth2.jwt.Jwt;

/**
 * The authenticated user, taken only from a verified token (never from a request body).
 *
 * @param subject the user id
 * @param tenantId the tenant every read and write is scoped to
 * @param roles the user's roles
 */
public record Caller(String subject, String tenantId, Set<String> roles) {

  /**
   * Builds the caller from a verified JWT.
   *
   * @param jwt the verified token
   * @return the caller
   */
  public static Caller of(Jwt jwt) {
    return new Caller(
        jwt.getSubject(),
        jwt.getClaimAsString("tenant_id"),
        Set.copyOf(jwt.getClaimAsStringList("roles")));
  }

  /**
   * Whether this caller may approve or reject side-effecting actions.
   *
   * @return true for approvers and admins
   */
  public boolean canApprove() {
    return roles.contains("approver") || roles.contains("admin");
  }
}
