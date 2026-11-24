/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.inbound.rest.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/** Request bodies of platform-api.yaml. Unknown fields are rejected (400). */
public final class Requests {

  private Requests() {}

  /**
   * {@code DevTokenRequest}.
   *
   * @param subject the synthetic user to sign in as
   */
  public record DevToken(@NotBlank @Size(max = 128) String subject) {}

  /**
   * {@code RunCreate}.
   *
   * @param query what the user asks
   * @param environment the target environment (default sandbox)
   * @param conversationId the conversation to continue, if any
   */
  public record RunCreate(
      @NotBlank @Size(min = 1, max = 4000) String query,
      @Size(min = 1, max = 64) String environment,
      @Pattern(regexp = "^conv_[0-9a-f]{16}$") String conversationId) {

    /**
     * Binds the JSON name {@code conversation_id}.
     *
     * @param query what the user asks
     * @param environment the target environment
     * @param conversationId the conversation id
     * @return the request
     */
    @com.fasterxml.jackson.annotation.JsonCreator
    public static RunCreate of(
        @com.fasterxml.jackson.annotation.JsonProperty("query") String query,
        @com.fasterxml.jackson.annotation.JsonProperty("environment") String environment,
        @com.fasterxml.jackson.annotation.JsonProperty("conversation_id") String conversationId) {
      return new RunCreate(query, environment, conversationId);
    }
  }

  /**
   * {@code ApproveRequest}.
   *
   * @param actionHash the hash of the action the approver saw
   */
  public record Approve(
      @com.fasterxml.jackson.annotation.JsonProperty("action_hash")
          @NotBlank
          @Pattern(regexp = "^[0-9a-f]{64}$")
          String actionHash) {}

  /**
   * {@code RejectRequest}.
   *
   * @param reason why, if the approver says
   */
  public record Reject(@Size(max = 500) String reason) {}

  /**
   * {@code ClarifyRequest}.
   *
   * @param message the user's answer
   */
  public record Clarify(@NotBlank @Size(min = 1, max = 4000) String message) {}
}
