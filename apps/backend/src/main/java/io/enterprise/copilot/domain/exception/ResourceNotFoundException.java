/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.domain.exception;

/**
 * Thrown when a requested resource does not exist in the system.
 *
 * <p>Maps to HTTP 404 Not Found.
 */
public class ResourceNotFoundException extends RuntimeException {

  public ResourceNotFoundException(String message) {
    super(message);
  }

  public ResourceNotFoundException(String resourceType, String id) {
    super(resourceType + " with id '" + id + "' not found");
  }
}
