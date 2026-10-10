/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.enterprise.copilot.infrastructure.config.SecurityConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer test for the health endpoint, with the real security configuration applied. */
@WebMvcTest(HealthController.class)
@Import(SecurityConfig.class)
class HealthControllerTest {

  @Autowired private MockMvc mockMvc;

  @Test
  void healthIsPublicAndReportsUp() throws Exception {
    mockMvc
        .perform(get("/api/v1/health"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("UP"))
        .andExpect(jsonPath("$.service").value("enterprise-api-copilot-backend"))
        .andExpect(jsonPath("$.timestamp").exists());
  }

  @Test
  void otherApiPathsAreRejectedWithoutCredentials() throws Exception {
    // No authentication mechanism is enabled yet (see SecurityConfig TODO), so Spring Security's
    // default entry point answers 403 rather than 401.
    mockMvc.perform(get("/api/v1/runs")).andExpect(status().isForbidden());
  }
}
