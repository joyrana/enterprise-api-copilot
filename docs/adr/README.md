# Architecture Decision Records (ADR)

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001.md) | Core Technology Stack Selection | Accepted; Spring AI and Qdrant aspects superseded by ADR-0005 / ADR-0007 |
| [ADR-0002](ADR-0002.md) | LangGraph as Agent Orchestration Runtime | Accepted |
| [ADR-0003](ADR-0003.md) | Go CLI for Developer Interface | Accepted; Cobra/BubbleTea dropped by ADR-0009 |
| [ADR-0004](ADR-0004.md) | Spring Boot, MCP, Apigee, and Hexagonal Boundaries | Accepted; MCP role refined by ADR-0006 |
| [ADR-0005](ADR-0005.md) | Canonical Layout and Service Boundaries | Accepted |
| [ADR-0006](ADR-0006.md) | Skill Contract, Policy Enforcement and Action-Bound Approvals | Accepted |
| [ADR-0007](ADR-0007.md) | PostgreSQL + pgvector as the Single Data Foundation | Accepted |
| [ADR-0008](ADR-0008.md) | Offline-First, Deterministic-First Evaluation | Accepted |
| [ADR-0009](ADR-0009.md) | Contract-First Platform API with a Local Reference Implementation; Standard-Library CLI | Accepted |
| [ADR-0010](ADR-0010.md) | Durable Runtime State via Portable SQL (SQLite Now, PostgreSQL Twin) | Accepted |

Each ADR records context, decision, alternatives, trade-offs and consequences. To change a
decision, add a new ADR that supersedes the old one; do not rewrite history.
