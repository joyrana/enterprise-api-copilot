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

/** Standardized error response returned by all REST endpoints on failure. */
@Value
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiErrorResponse {

  /** Machine-readable error code (e.g., {@code RESOURCE_NOT_FOUND}). */
  private String code;

  /** Human-readable error message safe for display to end users. */
  private String message;

  /** Unique identifier for this request — use for support correlation. */
  private String requestId;

  /** The request path that triggered the error. */
  private String path;

  /** Timestamp when the error occurred. */
  private Instant timestamp;
}
