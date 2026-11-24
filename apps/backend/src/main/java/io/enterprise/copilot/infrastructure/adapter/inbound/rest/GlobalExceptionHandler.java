/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import io.enterprise.copilot.application.ApiException;
import io.enterprise.copilot.domain.exception.ResourceNotFoundException;
import io.enterprise.copilot.domain.exception.ValidationException;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** Maps every failure to the platform {@code ApiError} body. */
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

  /**
   * Maps a platform error (including errors relayed from the agent service).
   *
   * @param ex the error
   * @param request the request that failed
   * @return the error response, with {@code Retry-After} when the error carries one
   */
  @ExceptionHandler(ApiException.class)
  public ResponseEntity<ApiErrorResponse> handleApi(ApiException ex, HttpServletRequest request) {
    ResponseEntity.BodyBuilder builder = ResponseEntity.status(ex.getStatus());
    if (ex.getRetryAfterSeconds() != null) {
      builder.header(HttpHeaders.RETRY_AFTER, String.valueOf(ex.getRetryAfterSeconds()));
    }
    return builder.body(body(ex.getCode(), ex.getMessage(), request));
  }

  /**
   * Maps a missing resource to 404 {@code RESOURCE_NOT_FOUND}.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler({ResourceNotFoundException.class, NoResourceFoundException.class})
  public ResponseEntity<ApiErrorResponse> handleNotFound(Exception ex, HttpServletRequest request) {
    String message = ex instanceof ResourceNotFoundException ? ex.getMessage() : "not found";
    return build(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", message, request);
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
    return build(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", ex.getMessage(), request);
  }

  /**
   * Maps request-body validation errors to 400, listing each field.
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
                error ->
                    error instanceof FieldError field
                        ? field.getField() + ": " + field.getDefaultMessage()
                        : error.getDefaultMessage())
            .reduce((a, b) -> a + "; " + b)
            .orElse("Validation failed");
    return build(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", message, request);
  }

  /**
   * Maps malformed or unexpected input (bad JSON, unknown fields, bad parameter) to 400.
   *
   * @param ex the exception raised while binding the request
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler({
    HttpMessageNotReadableException.class,
    MissingServletRequestParameterException.class,
    MethodArgumentTypeMismatchException.class
  })
  public ResponseEntity<ApiErrorResponse> handleBadInput(Exception ex, HttpServletRequest request) {
    return build(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", "invalid request", request);
  }

  /**
   * Maps a missing or invalid credential to 401.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(AuthenticationException.class)
  public ResponseEntity<ApiErrorResponse> handleAuthentication(
      AuthenticationException ex, HttpServletRequest request) {
    return build(HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "Authentication required", request);
  }

  /**
   * Maps an authorization failure to 403.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(AccessDeniedException.class)
  public ResponseEntity<ApiErrorResponse> handleAccessDenied(
      AccessDeniedException ex, HttpServletRequest request) {
    return build(
        HttpStatus.FORBIDDEN,
        "ACCESS_DENIED",
        "You do not have permission to perform this action",
        request);
  }

  /**
   * Maps any unhandled exception to 500 without exposing details.
   *
   * @param ex the exception raised by the controller
   * @param request the request that failed
   * @return the error response
   */
  @ExceptionHandler(Exception.class)
  public ResponseEntity<ApiErrorResponse> handleGeneric(Exception ex, HttpServletRequest request) {
    log.error(
        "Unhandled exception on request {} {}", request.getMethod(), request.getRequestURI(), ex);
    return build(
        HttpStatus.INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
        request);
  }

  private ResponseEntity<ApiErrorResponse> build(
      HttpStatus status, String code, String message, HttpServletRequest request) {
    return ResponseEntity.status(status).body(body(code, message, request));
  }

  private ApiErrorResponse body(String code, String message, HttpServletRequest request) {
    String requestId = PlatformRequestFilter.idOf(request);
    log.warn("error code={} requestId={} path={}", code, requestId, request.getRequestURI());
    return ApiErrorResponse.builder()
        .code(code)
        .message(message)
        .requestId(requestId)
        .path(request.getRequestURI())
        .timestamp(Instant.now())
        .build();
  }
}
