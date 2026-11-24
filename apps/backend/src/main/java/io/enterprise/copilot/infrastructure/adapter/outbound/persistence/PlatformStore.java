/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.infrastructure.adapter.outbound.persistence;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Durable platform records in PostgreSQL (Flyway-managed): who decided which approval, and an audit
 * trail of platform actions. Run state itself lives in the agent service.
 */
@Repository
public class PlatformStore {

  private final JdbcClient jdbc;

  /**
   * Creates the store.
   *
   * @param jdbc the JDBC client
   */
  public PlatformStore(JdbcClient jdbc) {
    this.jdbc = jdbc;
  }

  /**
   * Records an approval decision. A run's action can be decided once.
   *
   * @param runId the run
   * @param tenantId the tenant
   * @param actionHash the hash the approver saw
   * @param decision {@code APPROVED} or {@code REJECTED}
   * @param decidedBy the deciding subject
   * @param reason an optional reason
   * @return false if a decision for this run and action already exists
   */
  public boolean recordDecision(
      String runId,
      String tenantId,
      String actionHash,
      String decision,
      String decidedBy,
      String reason) {
    try {
      jdbc.sql(
              "INSERT INTO platform_approval_decisions (id, run_id, tenant_id, action_hash, "
                  + "decision, decided_by, reason, decided_at) "
                  + "VALUES (:id, :run, :tenant, :hash, :decision, :by, :reason, :at)")
          .param("id", UUID.randomUUID().toString())
          .param("run", runId)
          .param("tenant", tenantId)
          .param("hash", actionHash)
          .param("decision", decision)
          .param("by", decidedBy)
          .param("reason", reason)
          .param("at", OffsetDateTime.now(ZoneOffset.UTC))
          .update();
      return true;
    } catch (DuplicateKeyException e) {
      return false;
    }
  }

  /**
   * Decisions recorded for a run, oldest first.
   *
   * @param runId the run
   * @param tenantId the tenant (decisions of other tenants are never returned)
   * @return rows with decision, decided_by and action_hash
   */
  public List<Map<String, Object>> decisions(String runId, String tenantId) {
    return jdbc.sql(
            "SELECT decision, decided_by, action_hash FROM platform_approval_decisions "
                + "WHERE run_id = :run AND tenant_id = :tenant ORDER BY decided_at")
        .param("run", runId)
        .param("tenant", tenantId)
        .query()
        .listOfRows();
  }

  /**
   * Appends an audit record.
   *
   * @param tenantId the tenant
   * @param subject the acting user
   * @param action what was attempted (for example {@code run.create})
   * @param resource what it was attempted on
   * @param outcome the HTTP status or result label
   * @param requestId the request id for correlation
   */
  public void audit(
      String tenantId,
      String subject,
      String action,
      String resource,
      String outcome,
      String requestId) {
    jdbc.sql(
            "INSERT INTO platform_audit_log (occurred_at, tenant_id, subject, action, resource, "
                + "outcome, request_id) VALUES (:at, :tenant, :subject, :action, :resource, "
                + ":outcome, :rid)")
        .param("at", OffsetDateTime.now(ZoneOffset.UTC))
        .param("tenant", tenantId)
        .param("subject", subject)
        .param("action", action)
        .param("resource", resource)
        .param("outcome", outcome)
        .param("rid", requestId)
        .update();
  }

  /**
   * Counts audit records for a tenant (used by tests and diagnostics).
   *
   * @param tenantId the tenant
   * @param action the action to count
   * @return the number of records
   */
  public long auditCount(String tenantId, String action) {
    return jdbc.sql(
            "SELECT COUNT(*) FROM platform_audit_log WHERE tenant_id = :tenant AND action = :action")
        .param("tenant", tenantId)
        .param("action", action)
        .query(Long.class)
        .single();
  }
}
