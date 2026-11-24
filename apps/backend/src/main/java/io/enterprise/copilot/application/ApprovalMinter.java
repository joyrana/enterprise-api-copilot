/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.application;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.enterprise.copilot.infrastructure.config.CopilotProperties;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Service;

/**
 * Mints action-bound approval tokens in the format the agent's skill runtime verifies ({@code
 * v1.<body>.<hmac>}, ADR-0006): the platform owns approvals, the runtime verifies and consumes them
 * exactly once.
 */
@Service
public class ApprovalMinter {

  private static final String VERSION = "v1";
  private static final int MIN_KEY_BYTES = 32;

  private final byte[] key;
  private final int ttlSeconds;
  private final ObjectMapper mapper;
  private final SecureRandom random = new SecureRandom();

  /**
   * Creates the minter.
   *
   * @param properties the configuration (approval key and lifetime)
   * @param mapper the JSON mapper
   */
  public ApprovalMinter(CopilotProperties properties, ObjectMapper mapper) {
    String configured = properties.approval().key();
    if (configured == null || configured.getBytes(StandardCharsets.UTF_8).length < MIN_KEY_BYTES) {
      throw new IllegalStateException(
          "copilot.approval.key must be set to at least " + MIN_KEY_BYTES + " bytes");
    }
    this.key = configured.getBytes(StandardCharsets.UTF_8);
    this.ttlSeconds = properties.approval().ttlSeconds();
    this.mapper = mapper;
  }

  /**
   * Mints a token that authorises exactly one action.
   *
   * @param actionHash the 64-hex hash the approver saw
   * @param approver the approving subject
   * @param tenantId the tenant the action belongs to
   * @return the token
   */
  public String mint(String actionHash, String approver, String tenantId) {
    return mint(actionHash, approver, tenantId, Instant.now());
  }

  String mint(String actionHash, String approver, String tenantId, Instant now) {
    byte[] id = new byte[16];
    random.nextBytes(id);
    ObjectNode grant = mapper.createObjectNode();
    // Keys in sorted order, like the runtime's canonical JSON.
    grant.put("action_hash", actionHash);
    grant.put("approval_id", Base64.getUrlEncoder().withoutPadding().encodeToString(id));
    grant.put("approver", approver);
    grant.put("expires_at", now.plusSeconds(ttlSeconds).toEpochMilli() / 1000.0);
    grant.put("issued_at", now.toEpochMilli() / 1000.0);
    grant.put("tenant_id", tenantId);
    String body =
        Base64.getUrlEncoder()
            .withoutPadding()
            .encodeToString(grant.toString().getBytes(StandardCharsets.UTF_8));
    return VERSION + "." + body + "." + sign(body);
  }

  String sign(String body) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(key, "HmacSHA256"));
      byte[] signature = mac.doFinal((VERSION + "." + body).getBytes(StandardCharsets.UTF_8));
      return Base64.getUrlEncoder().withoutPadding().encodeToString(signature);
    } catch (GeneralSecurityException e) {
      throw new IllegalStateException("HMAC-SHA256 is unavailable", e);
    }
  }
}
