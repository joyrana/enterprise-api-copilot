/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import io.enterprise.copilot.domain.exception.ResourceNotFoundException;
import io.enterprise.copilot.domain.exception.ValidationException;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
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

  /**
   * Maps a missing resource to 404 {@code RESOURCE_NOT_FOUND}.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(ResourceNotFoundException.class)
  public ResponseEntity<ApiErrorResponse> handleNotFound(
      ResourceNotFoundException ex, HttpServletRequest request) {
    return buildError(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", ex.getMessage(), request);
  }

  /**
   * Maps a domain validation failure to 400 {@code VALIDATION_ERROR}.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(ValidationException.class)
  public ResponseEntity<ApiErrorResponse> handleValidation(
      ValidationException ex, HttpServletRequest request) {
    return buildError(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", ex.getMessage(), request);
  }

  /**
   * Maps request-body validation errors to 400 {@code VALIDATION_ERROR}, listing each field.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
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

  /**
   * Maps a missing or invalid credential to 401 {@code UNAUTHENTICATED}.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(AuthenticationException.class)
  public ResponseEntity<ApiErrorResponse> handleAuthentication(
      AuthenticationException ex, HttpServletRequest request) {
    return buildError(
        HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required", request);
  }

  /**
   * Maps an authorization failure to 403 {@code ACCESS_DENIED}.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(AccessDeniedException.class)
  public ResponseEntity<ApiErrorResponse> handleAccessDenied(
      AccessDeniedException ex, HttpServletRequest request) {
    return buildError(
        HttpStatus.FORBIDDEN,
        "ACCESS_DENIED",
        "You do not have permission to perform this action",
        request);
  }

  /**
   * Maps any unhandled exception to 500 {@code INTERNAL_ERROR} without exposing details.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(Exception.class)
  public ResponseEntity<ApiErrorResponse> handleGeneric(Exception ex, HttpServletRequest request) {
    log.error(
        "Unhandled exception on request {} {}", request.getMethod(), request.getRequestURI(), ex);
    return buildError(
        HttpStatus.INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred. Please try again or contact support.",
        request);
  }

  private ResponseEntity<ApiErrorResponse> buildError(
      HttpStatus status, String code, String message, HttpServletRequest request) {
    String requestId = UUID.randomUUID().toString();
    log.warn(
        "Returning error: status={} code={} requestId={} path={}",
        status.value(),
        code,
        requestId,
        request.getRequestURI());

    return ResponseEntity.status(status)
        .body(
            ApiErrorResponse.builder()
                .code(code)
                .message(message)
                .requestId(requestId)
                .path(request.getRequestURI())
                .timestamp(Instant.now())
                .build());
  }
}
