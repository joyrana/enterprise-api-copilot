/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import static org.assertj.core.api.Assertions.assertThat;

import io.enterprise.copilot.domain.exception.ResourceNotFoundException;
import io.enterprise.copilot.domain.exception.ValidationException;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.validation.BeanPropertyBindingResult;
import org.springframework.validation.FieldError;
import org.springframework.validation.ObjectError;
import org.springframework.web.bind.MethodArgumentNotValidException;

/** Unit tests for the mapping from exceptions to {@link ApiErrorResponse}. */
class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();
  private final MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/x");

  @Test
  void notFoundMapsTo404WithMessage() {
    ResponseEntity<ApiErrorResponse> response =
        handler.handleNotFound(new ResourceNotFoundException("Run", "r-1"), request);

    assertError(response, HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND");
    assertThat(response.getBody().getMessage()).isEqualTo("Run with id 'r-1' not found");
  }

  @Test
  void domainValidationMapsTo400() {
    ResponseEntity<ApiErrorResponse> response =
        handler.handleValidation(new ValidationException("bad input"), request);

    assertError(response, HttpStatus.BAD_REQUEST, "VALIDATION_ERROR");
    assertThat(response.getBody().getMessage()).isEqualTo("bad input");
  }

  @Test
  void bodyValidationListsEveryError() throws Exception {
    BeanPropertyBindingResult result = new BeanPropertyBindingResult(new Object(), "req");
    result.addError(new FieldError("req", "name", "must not be blank"));
    result.addError(new ObjectError("req", "dates are inconsistent"));
    MethodParameter parameter =
        new MethodParameter(
            GlobalExceptionHandlerTest.class.getDeclaredMethod("sample", String.class), 0);

    ResponseEntity<ApiErrorResponse> response =
        handler.handleMethodArgumentNotValid(
            new MethodArgumentNotValidException(parameter, result), request);

    assertError(response, HttpStatus.BAD_REQUEST, "VALIDATION_ERROR");
    assertThat(response.getBody().getMessage())
        .isEqualTo("name: must not be blank; dates are inconsistent");
  }

  @Test
  void authenticationFailureMapsTo401() {
    ResponseEntity<ApiErrorResponse> response =
        handler.handleAuthentication(new BadCredentialsException("nope"), request);

    assertError(response, HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED");
  }

  @Test
  void accessDeniedMapsTo403() {
    ResponseEntity<ApiErrorResponse> response =
        handler.handleAccessDenied(new AccessDeniedException("nope"), request);

    assertError(response, HttpStatus.FORBIDDEN, "ACCESS_DENIED");
  }

  @Test
  void unexpectedErrorsDoNotLeakDetails() {
    ResponseEntity<ApiErrorResponse> response =
        handler.handleGeneric(new IllegalStateException("db password is hunter2"), request);

    assertError(response, HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
    assertThat(response.getBody().getMessage()).doesNotContain("hunter2");
  }

  private void assertError(
      ResponseEntity<ApiErrorResponse> response, HttpStatus status, String code) {
    assertThat(response.getStatusCode()).isEqualTo(status);
    ApiErrorResponse body = response.getBody();
    assertThat(body).isNotNull();
    assertThat(body.getCode()).isEqualTo(code);
    assertThat(body.getPath()).isEqualTo("/api/v1/x");
    assertThat(body.getRequestId()).isNotBlank();
    assertThat(body.getTimestamp()).isNotNull();
  }

  @SuppressWarnings("unused")
  private void sample(String body) {
    // Target for the MethodParameter required by MethodArgumentNotValidException.
  }
}
