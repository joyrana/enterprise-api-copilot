/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto.ApiErrorResponse;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Gives every request an id (echoing a well-formed {@code X-Request-Id}) and rejects bodies over 64
 * KiB before they are read.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class PlatformRequestFilter extends OncePerRequestFilter {

  /** Request attribute holding the request id. */
  public static final String REQUEST_ID = "copilot.requestId";

  /** Largest accepted request body. */
  public static final long MAX_BODY_BYTES = 64L * 1024;

  private static final Pattern WELL_FORMED = Pattern.compile("^[A-Za-z0-9._-]{8,64}$");

  private final ObjectMapper mapper;

  /**
   * Creates the filter.
   *
   * @param mapper the JSON mapper
   */
  public PlatformRequestFilter(ObjectMapper mapper) {
    this.mapper = mapper;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String supplied = request.getHeader("X-Request-Id");
    String id =
        supplied != null && WELL_FORMED.matcher(supplied).matches()
            ? supplied
            : "req_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    request.setAttribute(REQUEST_ID, id);
    response.setHeader("X-Request-Id", id);
    if (request.getContentLengthLong() > MAX_BODY_BYTES) {
      response.setStatus(413);
      response.setContentType(MediaType.APPLICATION_JSON_VALUE);
      mapper.writeValue(
          response.getOutputStream(),
          ApiErrorResponse.builder()
              .code("PAYLOAD_TOO_LARGE")
              .message("request body too large")
              .requestId(id)
              .path(request.getRequestURI())
              .timestamp(Instant.now())
              .build());
      return;
    }
    chain.doFilter(request, response);
  }

  /**
   * The id of the current request.
   *
   * @param request the request
   * @return the id, or a fresh one if the filter did not run
   */
  public static String idOf(HttpServletRequest request) {
    Object id = request.getAttribute(REQUEST_ID);
    return id != null ? id.toString() : "req_" + UUID.randomUUID().toString().substring(0, 16);
  }
}
