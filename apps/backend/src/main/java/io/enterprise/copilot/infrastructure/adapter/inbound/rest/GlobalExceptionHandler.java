/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
import io.enterprise.copilot.domain.exception.ResourceNotFoundException;
import io.enterprise.copilot.domain.exception.ValidationException;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.UUID;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Global exception handler for all REST controllers.
 *
 * <p>Translates domain and infrastructure exceptions into standardized {@link ApiErrorResponse}
 * responses. Never exposes internal stack traces or implementation details to callers.
 */
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

  @ExceptionHandler(ResourceNotFoundException.class)
  public ResponseEntity<ApiErrorResponse> handleNotFound(
      ResourceNotFoundException ex, HttpServletRequest request) {
    return buildError(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", ex.getMessage(), request);
  }

  @ExceptionHandler(ValidationException.class)
  public ResponseEntity<ApiErrorResponse> handleValidation(
      ValidationException ex, HttpServletRequest request) {
    return buildError(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", ex.getMessage(), request);
  }

  @ExceptionHandler(MethodArgumentNotValidException.class)
  public ResponseEntity<ApiErrorResponse> handleMethodArgumentNotValid(
      MethodArgumentNotValidException ex, HttpServletRequest request) {
    String message =
        ex.getBindingResult().getAllErrors().stream()
            .map(
                error -> {
                  if (error instanceof FieldError fieldError) {
                    return fieldError.getField() + ": " + fieldError.getDefaultMessage();
                  }
                  return error.getDefaultMessage();
                })
            .reduce((a, b) -> a + "; " + b)
            .orElse("Validation failed");
    return buildError(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", message, request);
  }

  @ExceptionHandler(AuthenticationException.class)
  public ResponseEntity<ApiErrorResponse> handleAuthentication(
      AuthenticationException ex, HttpServletRequest request) {
    return buildError(HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required",
        request);
  }

  @ExceptionHandler(AccessDeniedException.class)
  public ResponseEntity<ApiErrorResponse> handleAccessDenied(
      AccessDeniedException ex, HttpServletRequest request) {
    return buildError(HttpStatus.FORBIDDEN, "ACCESS_DENIED",
        "You do not have permission to perform this action", request);
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<ApiErrorResponse> handleGeneric(
      Exception ex, HttpServletRequest request) {
    log.error("Unhandled exception on request {} {}", request.getMethod(),
        request.getRequestURI(), ex);
    return buildError(
        HttpStatus.INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred. Please try again or contact support.",
        request);
  }

  private ResponseEntity<ApiErrorResponse> buildError(
      HttpStatus status, String code, String message, HttpServletRequest request) {
    String requestId = UUID.randomUUID().toString();
    log.warn("Returning error: status={} code={} requestId={} path={}",
        status.value(), code, requestId, request.getRequestURI());

    return ResponseEntity.status(status).body(
        ApiErrorResponse.builder()
            .code(code)
            .message(message)
            .requestId(requestId)
            .path(request.getRequestURI())
            .timestamp(Instant.now())
            .build());
  }
}
