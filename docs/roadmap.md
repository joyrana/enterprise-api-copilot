# Roadmap

> Enterprise API Copilot — Product Roadmap

**Last Updated**: August 2026

---

## Vision

Make every enterprise API accessible through natural language. Eliminate the gap between API documentation and API execution.

---

## Current State

The project is in **Phase 1: Foundation**. The repository structure, skeleton code, and CI/CD pipelines are being established.

---

## Phase 1 — Foundation (Q3 2026)

**Goal**: Establish the production-grade repository skeleton. All services compile and health checks pass.

| Item | Status | Owner |
|---|---|---|
| Repository structure and documentation | ✅ Done | Core Team |
| Backend Spring Boot skeleton with health endpoint | 🚧 In Progress | Backend |
| Frontend React/Vite skeleton with routing | 🚧 In Progress | Frontend |
| Go CLI scaffold with all command stubs | 🚧 In Progress | CLI |
| CI/CD pipelines (Java, Go, Frontend) | 🚧 In Progress | Platform |
| Docker Compose for local development | 🚧 In Progress | Platform |
| Helm chart skeleton for Kubernetes | 📋 Planned | Platform |
| Code quality gates (Checkstyle, ESLint, golangci-lint) | 🚧 In Progress | Platform |

---

## Phase 2 — Core Capabilities (Q3–Q4 2026)

**Goal**: A working end-to-end demo with API discovery and execution.

| Item | Status | Owner |
|---|---|---|
| OpenAPI spec ingestion and indexing | 📋 Planned | Backend + AI |
| `api-discovery` MCP skill | 📋 Planned | AI |
| `api-executor` MCP skill | 📋 Planned | AI |
| Supervisor + Planner LangGraph agents | 📋 Planned | AI |
| Apigee OAuth 2.0 authentication integration | 📋 Planned | Backend |
| `copilot ask` CLI command (end-to-end) | 📋 Planned | CLI |
| Chat page with streaming response | 📋 Planned | Frontend |
| PostgreSQL schema + Flyway migrations | 📋 Planned | Backend |

---

## Phase 3 — Intelligence (Q4 2026)

**Goal**: Self-reflecting agent with memory, retry, and multi-turn conversations.

| Item | Status | Owner |
|---|---|---|
| Reflection agent for error recovery | 📋 Planned | AI |
| Conversation memory with vector store | 📋 Planned | AI |
| Multi-turn conversation context | 📋 Planned | AI + Backend |
| `sdk-generator` skill (curl + Java + Python) | 📋 Planned | AI |
| Execution history storage and replay | 📋 Planned | Backend |
| History page in frontend | 📋 Planned | Frontend |
| OpenTelemetry full trace propagation | 📋 Planned | Platform |

---

## Phase 4 — Developer Experience (Q1 2027)

**Goal**: Polish the developer experience; SDK generation; multi-gateway support.

| Item | Status | Owner |
|---|---|---|
| `documentation` skill (auto-generate API docs) | 📋 Planned | AI |
| Interactive TUI for `copilot ask` (BubbleTea) | 📋 Planned | CLI |
| Multi-gateway support (Kong, AWS API Gateway) | 📋 Planned | Backend |
| Homebrew tap for CLI distribution | 📋 Planned | CLI |
| API catalog browsing UI | 📋 Planned | Frontend |
| Export to Postman collection | 📋 Planned | Backend |

---

## Phase 5 — Enterprise Features (Q2 2027)

**Goal**: Production-ready for enterprise adoption.

| Item | Status | Owner |
|---|---|---|
| Enterprise SSO (SAML, OIDC) | 📋 Planned | Backend |
| RBAC (role-based access control) | 📋 Planned | Backend |
| Immutable audit log | 📋 Planned | Backend |
| Rate limiting and quota enforcement | 📋 Planned | Platform |
| Admin dashboard | 📋 Planned | Frontend |
| Compliance mode (PII masking, GDPR) | 📋 Planned | Backend |
| Helm chart production hardening | 📋 Planned | Platform |
| SLO / SLA monitoring dashboards | 📋 Planned | Platform |

---

## Icebox (Future Consideration)

- VS Code extension
- JetBrains plugin
- Slack / Teams bot integration
- GitHub Copilot integration
- Self-hosted LLM support (Ollama)
- GraphQL API support
- AsyncAPI / event-driven API support

---

## How to Influence the Roadmap

Open a [GitHub Discussion](https://github.com/your-org/enterprise-api-copilot/discussions) or vote on existing [Feature Requests](https://github.com/your-org/enterprise-api-copilot/issues?q=label%3Aenhancement). Roadmap items with significant community interest are prioritized.
