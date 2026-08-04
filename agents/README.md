# Enterprise API Copilot — AI Agents

This directory contains all LangGraph agent implementations.

## Structure

```
agents/
├── supervisor/     # Intent classification and routing
├── planner/        # Execution plan generation
├── reflection/     # Error analysis and retry
├── memory/         # Conversation memory management
└── shared/         # Shared types, state, utilities
```

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running Tests

```bash
pytest --cov=. -v
```

## Architecture

Agents form a LangGraph state machine:

```
START → [supervisor] → [planner] → [executor] → [memory] → END
                ↑           ↓           ↓
                └─[reflection]←─────────┘
```

See [docs/architecture.md](../docs/architecture.md) for full details.
