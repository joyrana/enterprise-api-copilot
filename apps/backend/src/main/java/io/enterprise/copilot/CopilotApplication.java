/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * Entry point for the Enterprise API Copilot backend service.
 *
 * <p>This service acts as the central control plane for the platform:
 * <ul>
 *   <li>Exposes REST APIs consumed by the CLI and Frontend</li>
 *   <li>Orchestrates AI agents for natural language API execution</li>
 *   <li>Manages conversation history and execution state</li>
 *   <li>Enforces authentication, authorization, and audit logging</li>
 * </ul>
 *
 * @see <a href="https://github.com/joyrana/enterprise-api-copilot">Project Repository</a>
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class CopilotApplication {

  public static void main(String[] args) {
    SpringApplication.run(CopilotApplication.class, args);
  }
}
