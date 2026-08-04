# Enterprise API Copilot

> **An Agentic AI Platform for Enterprise API Discovery, Testing, Troubleshooting and Automation.**

[![Java Build](https://github.com/your-org/enterprise-api-copilot/actions/workflows/java-build.yml/badge.svg)](https://github.com/your-org/enterprise-api-copilot/actions/workflows/java-build.yml)
[![Go Build](https://github.com/your-org/enterprise-api-copilot/actions/workflows/go-build.yml/badge.svg)](https://github.com/your-org/enterprise-api-copilot/actions/workflows/go-build.yml)
[![Frontend Build](https://github.com/your-org/enterprise-api-copilot/actions/workflows/frontend-build.yml/badge.svg)](https://github.com/your-org/enterprise-api-copilot/actions/workflows/frontend-build.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-enabled-blueviolet)](https://opentelemetry.io/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## Project Vision

Enterprise API Copilot transforms how developers interact with enterprise APIs. Instead of navigating complex API portals, reading sprawling documentation, or manually composing curl commands, developers can simply describe what they want in plain language — and the platform does the rest.

**Example interaction:**

```
Developer: "Create a sandbox payment worth ₹500 for customer ID cust_abc123"

Copilot:
  ✓ Understanding your request...
  ✓ Planning execution steps...
  ✓ Discovering API: POST /v1/payments
  ✓ Authenticating via Apigee (OAuth 2.0)...
  ✓ Executing API...
  ✓ Response received (HTTP 201)

Payment created successfully!
  ID:     pay_9xK2mNpQ
  Amount: ₹500.00
  Status: authorized

Equivalent curl:
  curl -X POST https://api.example.com/v1/payments \
    -H "Authorization: Bearer <token>" \
    -d '{"amount": 500, "currency": "INR", "customer": "cust_abc123"}'
```

The platform supports agentic AI workflows, Apigee-backed authentication, multi-turn conversation, execution history, and SDK generation — making it a complete API productivity suite for enterprise engineering teams.

---

## Features

| Feature | Status |
|---|---|
| Natural language API discovery | 🚧 In Progress |
| Agentic planning and execution | 🚧 In Progress |
| Apigee OAuth 2.0 / JWT authentication | 🚧 In Progress |
| Multi-turn conversational interface | 🚧 In Progress |
| Execution history and replay | 🚧 In Progress |
| curl and SDK code generation | 🚧 In Progress |
| OpenAPI spec import and indexing | 🚧 In Progress |
| CLI (`copilot ask`, `copilot api`) | 🚧 In Progress |
| OpenTelemetry tracing | 🚧 In Progress |
| Kubernetes-native deployment | 🚧 In Progress |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Enterprise API Copilot                        │
├────────────────┬─────────────────────────────┬───────────────────────┤
│   CLI (Go)     │     Frontend (React/TS)      │   External Clients    │
│  Cobra + TUI   │  Vite + TailwindCSS          │   REST / gRPC         │
└───────┬────────┴──────────────┬──────────────┴───────────┬───────────┘
        │                       │                           │
        ▼                       ▼                           ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     Backend API (Spring Boot 3 / Java 21)             │
│  ┌─────────────┐ ┌───────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │  Auth API   │ │  Copilot API  │ │  History API │ │  Health API │ │
│  └─────────────┘ └───────────────┘ └──────────────┘ └─────────────┘ │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│                          AI Agent Layer (Python / LangGraph)          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐               │
│  │  Supervisor  │→ │   Planner    │→ │  Reflection   │               │
│  └──────────────┘  └──────────────┘  └───────────────┘               │
│                            │                                          │
│                            ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                        MCP Skills                                │ │
│  │  api-discovery │ api-executor │ jwt │ sdk-generator │ docs       │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
          ┌─────────────────┐    ┌──────────────────┐
          │  Apigee Gateway │    │  Vector Database  │
          │  (Auth + Proxy) │    │  (API Knowledge)  │
          └─────────────────┘    └──────────────────┘
```

### Key Design Principles

- **Hexagonal Architecture** — Domain logic is fully isolated from infrastructure concerns.
- **Domain-Driven Design** — Each bounded context owns its domain model.
- **Agent-Skill Separation** — Agents orchestrate; Skills execute. Skills are stateless MCP tools.
- **Backend as the Single Control Plane** — CLI and Frontend communicate only with the Backend; they never directly invoke agents or external systems.
- **Observability First** — OpenTelemetry is instrumented at every layer.

---

## Repository Structure

```
enterprise-api-copilot/
├── apps/
│   ├── backend/          # Spring Boot 3 backend (Java 21)
│   ├── frontend/         # React + TypeScript + Vite frontend
│   └── cli/              # Go CLI (Cobra + BubbleTea)
├── agents/
│   ├── supervisor/       # AI Supervisor agent (LangGraph)
│   ├── planner/          # Execution planner agent
│   ├── reflection/       # Self-reflection / retry agent
│   └── memory/           # Conversation memory agent
├── skills/
│   ├── api-discovery/    # MCP skill: find APIs from natural language
│   ├── api-executor/     # MCP skill: execute API calls
│   ├── documentation/    # MCP skill: generate API documentation
│   ├── jwt/              # MCP skill: JWT generation and validation
│   └── sdk-generator/    # MCP skill: generate SDK code snippets
├── apigee/               # Apigee proxy configuration and policies
├── deployment/           # Kubernetes manifests and Helm charts
├── docker/               # Dockerfiles and compose files
├── docs/                 # Architecture, ADRs, roadmap, standards
├── examples/             # Example requests and integration demos
└── .github/              # CI/CD workflows, issue templates
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Java 21, Spring Boot 3, Spring AI, Maven |
| Database | PostgreSQL 16, Redis 7 |
| AI / Agents | Python 3.12, LangGraph, OpenAI SDK, MCP |
| Vector Store | pgvector / Qdrant |
| CLI | Go 1.22, Cobra, BubbleTea |
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| API Gateway | Apigee X |
| Observability | OpenTelemetry, Prometheus, Grafana |
| Infrastructure | Docker, Kubernetes, Helm, GitHub Actions |
| Code Quality | Checkstyle, Spotless, ESLint, Prettier, golangci-lint |

---

## Quick Start

### Prerequisites

- Java 21+
- Go 1.22+
- Node.js 20+
- Python 3.12+
- Docker & Docker Compose
- `OPENAI_API_KEY` environment variable

### Run with Docker Compose

```bash
git clone https://github.com/your-org/enterprise-api-copilot.git
cd enterprise-api-copilot

# Copy environment template
cp .env.example .env
# Edit .env with your credentials

# Start all services
docker compose -f docker/docker-compose.yml up -d

# Backend API:  http://localhost:8080
# Frontend:     http://localhost:3000
# API Docs:     http://localhost:8080/swagger-ui.html
```

### Run Backend Locally

```bash
cd apps/backend
./mvnw spring-boot:run -Dspring-boot.run.profiles=local
```

### Run Frontend Locally

```bash
cd apps/frontend
npm install
npm run dev
```

### Install CLI

```bash
cd apps/cli
go install ./cmd/copilot

# Verify installation
copilot version
copilot doctor
```

### First Interaction

```bash
# Login
copilot login --env sandbox

# Ask a question
copilot ask "List all available payment APIs"

# Execute an API
copilot api run --natural "Create a ₹500 sandbox payment"
```

---

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the full roadmap.

| Phase | Goal | Timeline |
|---|---|---|
| Phase 1 | Core infrastructure, backend skeleton, CLI scaffold | Q3 2026 |
| Phase 2 | API discovery skill, Apigee auth integration | Q3 2026 |
| Phase 3 | Full agentic loop with LangGraph | Q4 2026 |
| Phase 4 | SDK generation, multi-cloud API gateway support | Q1 2027 |
| Phase 5 | Enterprise SSO, audit logs, RBAC | Q2 2027 |

---

## Contributing

We welcome contributions from the community. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/coding-standards.md](docs/coding-standards.md) before opening a pull request.

### Good First Issues

Look for issues tagged [`good first issue`](https://github.com/your-org/enterprise-api-copilot/issues?q=label%3A%22good+first+issue%22) to get started.

---

## Security

Please review our [SECURITY.md](SECURITY.md) before reporting vulnerabilities. Do **not** open public GitHub issues for security bugs.

---

## License

Copyright 2026 Enterprise API Copilot Authors.

Licensed under the [Apache License, Version 2.0](LICENSE).
