/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.HealthResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.Instant;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Public health check endpoint.
 *
 * <p>This endpoint is intentionally unauthenticated and is used by:
 *
 * <ul>
 *   <li>Kubernetes liveness and readiness probes
 *   <li>Load balancer health checks
 *   <li>CLI {@code copilot doctor} command
 * </ul>
 *
 * <p>For detailed health information (database, redis, agents), see Spring Actuator at {@code
 * /actuator/health}.
 */
@RestController
@RequestMapping("/api/v1")
@Tag(name = "Health", description = "Service health and version information")
public class HealthController {

  private static final String SERVICE_NAME = "enterprise-api-copilot-backend";
  private static final String VERSION = "0.1.0-SNAPSHOT";

  /**
   * Returns the service health status.
   *
   * @return 200 OK with service info
   */
  @GetMapping("/health")
  @Operation(summary = "Health check", description = "Returns service health status and version")
  public ResponseEntity<HealthResponse> health() {
    return ResponseEntity.ok(
        HealthResponse.builder()
            .status("UP")
            .service(SERVICE_NAME)
            .version(VERSION)
            .timestamp(Instant.now())
            .build());
  }
}
