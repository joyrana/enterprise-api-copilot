# ai — Python AI service core

| Package | Responsibility |
|---|---|
| `agent/` | Deterministic intent + entity extraction, template planner, argument binding (never invents values), bounded orchestrator with approval pause/resume and checkpoints, optional LLM intent classifier with contract-preserving fallback |
| `knowledge/` | Document model with stable IDs, chunking, OpenAPI/Markdown ingestion, tenant-filtered BM25 / dense / RRF retrieval, context assembly with injection flags and token budgets, extractive grounded answers, PostgreSQL schema + hybrid SQL (`sql/`) |
| `models/` | Provider-neutral `ModelProvider`, structured-output validation, usage and cost accounting |
| `bootstrap.py` | Composition root: settings from env → gateway → catalog/knowledge → skills → runtime |
| `telemetry.py` | Span facade over the OpenTelemetry API; the only place `gen_ai.*` names live |

The orchestration and HTTP adapters (LangGraph, FastAPI) are not built yet — see
`docs/implementation/STATUS.md`.
