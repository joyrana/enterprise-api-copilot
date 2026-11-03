# ai — Python AI service core

| Package | Responsibility |
|---|---|
| `agent/` | Deterministic intent + entity extraction, template planner, argument binding (never invents values), bounded orchestrator with approval pause/resume and checkpoints. With a model configured: LLM intent, intent resolver, ReAct step planner, responder and UI component registry, failing the run (no rules fallback) when the model is unavailable |
| `knowledge/` | Document model with stable IDs, chunking, OpenAPI/Markdown ingestion, tenant-filtered BM25 / dense / RRF retrieval, context assembly with injection flags and token budgets, extractive grounded answers, PostgreSQL schema + hybrid SQL (`sql/`) |
| `models/` | Provider-neutral `ModelProvider`, structured-output validation, usage and cost accounting |
| `bootstrap.py` | Composition root: settings from env → gateway → catalog/knowledge → skills → runtime |
| `telemetry.py` | Span facade over the OpenTelemetry API; the only place `gen_ai.*` names live |

The orchestration and HTTP adapters (LangGraph, FastAPI) are not built yet — see
`docs/implementation/STATUS.md`.
