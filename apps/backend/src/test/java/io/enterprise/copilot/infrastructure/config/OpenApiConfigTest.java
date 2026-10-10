/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.config;

import static org.assertj.core.api.Assertions.assertThat;

import io.swagger.v3.oas.models.OpenAPI;
import org.junit.jupiter.api.Test;

/** Unit test for the OpenAPI metadata bean. */
class OpenApiConfigTest {

  @Test
  void describesTheService() {
    OpenAPI openApi = new OpenApiConfig().openAPI();

    assertThat(openApi.getInfo().getTitle()).isEqualTo("Enterprise API Copilot");
    assertThat(openApi.getInfo().getVersion()).isNotBlank();
  }
}
