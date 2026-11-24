/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import org.springframework.http.HttpStatus;

/** An error that maps directly to the platform {@code ApiError} response. */
public class ApiException extends RuntimeException {

  private static final long serialVersionUID = 1L;

  private final transient HttpStatus status;
  private final String code;
  private final Integer retryAfterSeconds;

  /**
   * Creates an error.
   *
   * @param status the HTTP status
   * @param code the machine-readable code
   * @param message the message safe to show a user
   */
  public ApiException(HttpStatus status, String code, String message) {
    this(status, code, message, null);
  }

  /**
   * Creates an error with a {@code Retry-After} hint.
   *
   * @param status the HTTP status
   * @param code the machine-readable code
   * @param message the message safe to show a user
   * @param retryAfterSeconds seconds to wait before retrying, or null
   */
  public ApiException(HttpStatus status, String code, String message, Integer retryAfterSeconds) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /**
   * The HTTP status.
   *
   * @return the status
   */
  public HttpStatus getStatus() {
    return status;
  }

  /**
   * The machine-readable code.
   *
   * @return the code
   */
  public String getCode() {
    return code;
  }

  /**
   * Seconds the client should wait before retrying.
   *
   * @return the hint, or null
   */
  public Integer getRetryAfterSeconds() {
    return retryAfterSeconds;
  }
}
