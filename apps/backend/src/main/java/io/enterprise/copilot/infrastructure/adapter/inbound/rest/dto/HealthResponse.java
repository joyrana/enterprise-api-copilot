/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.Instant;
import lombok.Builder;
import lombok.Value;

/** Response DTO for the health check endpoint. */
@Value
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class HealthResponse {

  /** Overall service status. Values: {@code UP}, {@code DEGRADED}, {@code DOWN}. */
  String status;

  /** Service identifier. */
  String service;

  /** Semantic version of the deployed artifact. */
  String version;

  /** Timestamp when the health check was performed. */
  Instant timestamp;
}
