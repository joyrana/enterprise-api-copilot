/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** {@code GET /api/v1/health}. */
@RestController
@RequestMapping("/api/v1")
public class HealthController {

  private static final String SERVICE_NAME = "copilot-platform-spring";
  private static final String VERSION = "0.3.0";

  /**
   * Returns the service health.
   *
   * @return the {@code Health} body of platform-api.yaml
   */
  @GetMapping("/health")
  public Map<String, String> health() {
    return Map.of("status", "UP", "service", SERVICE_NAME, "version", VERSION, "mode", "spring");
  }
}
