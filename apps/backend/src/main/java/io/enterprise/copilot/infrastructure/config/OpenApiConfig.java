/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenAPI / Swagger configuration.
 *
 * <p>Accessible at {@code /swagger-ui.html} and {@code /v3/api-docs}.
 */
@Configuration
public class OpenApiConfig {

  /**
   * Describes the service for the generated OpenAPI document and Swagger UI.
   *
   * @return the OpenAPI metadata bean
   */
  @Bean
  public OpenAPI openAPI() {
    return new OpenAPI()
        .info(
            new Info()
                .title("Enterprise API Copilot")
                .description(
                    "Agentic AI Platform for Enterprise API Discovery, Testing, Troubleshooting "
                        + "and Automation. Interact with enterprise APIs using natural language.")
                .version("0.1.0")
                .contact(
                    new Contact()
                        .name("Enterprise API Copilot Team")
                        .url("https://github.com/joyrana/enterprise-api-copilot")
                        .email("team@enterprise-api-copilot.io"))
                .license(
                    new License()
                        .name("Apache 2.0")
                        .url("https://www.apache.org/licenses/LICENSE-2.0")))
        .addSecurityItem(new SecurityRequirement().addList("BearerAuth"))
        .components(
            new Components()
                .addSecuritySchemes(
                    "BearerAuth",
                    new SecurityScheme()
                        .name("BearerAuth")
                        .type(SecurityScheme.Type.HTTP)
                        .scheme("bearer")
                        .bearerFormat("JWT")
                        .description(
                            "JWT Bearer token issued by Apigee. "
                                + "Obtain via: POST /api/v1/auth/token")));
  }
}
