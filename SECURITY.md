# Security Policy

## Supported Versions

We provide security patches for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| latest  | ✅ Yes             |
| < 1.0   | ❌ No (pre-release) |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

If you discover a security vulnerability in Enterprise API Copilot, please report it responsibly:

1. **Email**: security@enterprise-api-copilot.io
2. **Subject**: `[SECURITY] <brief description>`
3. **PGP Key**: Available at https://enterprise-api-copilot.io/.well-known/security.txt

### What to Include

- A clear description of the vulnerability
- Steps to reproduce the issue
- The potential impact and affected components
- Any suggested mitigations (optional)

### Our Commitment

- We will acknowledge your report within **48 hours**
- We will provide a status update within **7 days**
- We will work with you to validate and patch the issue
- We will credit you in the release notes (unless you prefer to remain anonymous)
- We aim to release a patch within **30 days** for critical vulnerabilities

## Security Design Principles

Enterprise API Copilot is designed with the following security principles:

### Authentication & Authorization
- All API endpoints are authenticated via OAuth 2.0 / JWT
- Apigee handles token issuance, validation, and revocation
- RBAC is enforced at both the API Gateway and backend layers

### Secrets Management
- No secrets are stored in source code or Docker images
- Environment-specific secrets are injected via Kubernetes Secrets or Vault
- All secrets are rotated on a defined schedule

### Data Security
- All data in transit is encrypted using TLS 1.3+
- Sensitive fields in logs are masked by default
- PII is never stored in agent memory or conversation history without explicit consent

### Dependency Security
- Dependencies are scanned on every CI run using OWASP Dependency Check and Trivy
- Dependabot is enabled for automated dependency updates
- Base images are regularly updated to patch OS-level vulnerabilities

### Network Security
- All internal service communication occurs within a private Kubernetes namespace
- External access is only available through the Apigee API gateway
- Network policies restrict pod-to-pod communication to what is explicitly required

## Vulnerability Disclosure Timeline

| Day | Action |
|-----|--------|
| 0   | Vulnerability reported |
| 1-2 | Acknowledgment sent to reporter |
| 3-7 | Initial triage and validation |
| 7-14 | Fix developed and reviewed |
| 14-30 | Patch released |
| 30+ | CVE published (if applicable) |
