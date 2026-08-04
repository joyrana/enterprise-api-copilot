# Security Architecture

> Enterprise API Copilot — Security Reference

**Version**: 0.1  
**Classification**: Public  
**Last Updated**: August 2026

---

## Threat Model Summary

| Threat | Mitigation |
|---|---|
| Unauthorized API access | Apigee OAuth 2.0, JWT validation on every request |
| Secret leakage | No secrets in code, Vault/k8s secrets, .gitignore |
| Prompt injection | Input validation, system prompt hardening, output sanitization |
| SSRF via API executor | Allow-list for external URLs, request validation |
| Token theft | Short-lived tokens, refresh rotation, HTTPS-only |
| Data exfiltration | RBAC, audit logging, egress policies |
| Supply chain attacks | SBOM generation, dependency scanning, Sigstore signing |

---

## Authentication & Authorization

### External Authentication (End Users)

All external requests must carry a valid JWT issued by Apigee.

```
Client ──► Apigee (token validation) ──► Backend (JWT re-validation) ──► Agent Service
```

- **OAuth 2.0 Authorization Code** for frontend
- **Client Credentials** for CLI and service-to-service
- **JWT expiry**: 1 hour (access token), 7 days (refresh token)

### Internal Service Authentication

- Agent service is deployed in a Kubernetes-internal namespace
- mTLS between backend and agent service in production
- Service account tokens for Kubernetes workloads

---

## Secrets Management

### Development

- Use `.env` files (never committed, see `.gitignore`)
- `.env.example` documents all required variables

### Production (Kubernetes)

- Secrets injected as environment variables from Kubernetes Secrets
- Kubernetes Secrets encrypted at rest with KMS
- HashiCorp Vault for dynamic secrets (database credentials)

### Secret Rotation

- Database passwords: rotated every 90 days
- JWT signing keys: rotated every 30 days
- API keys: rotated on demand or on employee offboarding

---

## Input Validation

### API Input Validation

```java
// Every inbound DTO must use Bean Validation
public record CreateConversationRequest(
    @NotBlank @Size(max = 4096) String message,
    @Valid ConversationContext context
) {}
```

### Prompt Injection Mitigation

- System prompts are hardcoded and not user-configurable
- User input is sanitized before inclusion in prompts
- Agent output is validated against expected schema before forwarding

### API Executor Allow-listing

```yaml
# TODO(#45): Implement URL allow-list in api-executor skill
# Only registered API hosts may be invoked
allowed_hosts:
  - api.example.com
  - sandbox.example.com
```

---

## Audit Logging

Every action that changes state or accesses sensitive data generates an audit log entry:

```json
{
  "timestamp": "2026-08-04T10:30:00Z",
  "traceId": "abc123",
  "userId": "usr_xyz",
  "action": "API_EXECUTED",
  "resource": "POST /v1/payments",
  "outcome": "SUCCESS",
  "clientIp": "10.0.0.1",
  "userAgent": "copilot-cli/0.1.0"
}
```

Audit logs are:
- Immutable (append-only)
- Shipped to a separate log storage (not deletable by application)
- Retained for 12 months minimum

---

## Network Security

### Production

- All traffic terminates TLS at Apigee edge
- Internal k8s services use ClusterIP (not exposed externally)
- Network policies enforce least-privilege pod communication
- No direct pod-to-pod communication outside defined policies

### Development

- All services accessible on localhost only
- Docker network isolation between compose services

---

## Vulnerability Management

### Dependency Scanning

- **OWASP Dependency Check** in Maven build
- **npm audit** in frontend CI
- **govulncheck** in Go CI
- **Trivy** for container image scanning
- **Dependabot** for automated PRs

### Container Security

- Non-root user in all Dockerfiles (`USER 10001`)
- Read-only root filesystem where possible
- No privileged containers
- Minimal base images (distroless or alpine)

---

## Incident Response

For security incidents:

1. Immediately notify `security@enterprise-api-copilot.io`
2. Do not attempt to fix without notifying the team
3. Preserve logs and evidence
4. Follow the [SECURITY.md](../SECURITY.md) disclosure process
