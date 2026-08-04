# Enterprise API Copilot — AI Agents (Legacy Compatibility)

This directory now provides compatibility shims for the new `ai/` package.
New development should target `ai/`.

## Structure

```
agents/
├── supervisor/     # Legacy import path shim
├── planner/        # Legacy import path shim
├── reflection/     # Legacy import path shim
├── memory/         # Legacy import path shim
└── shared/         # Legacy state shim
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

Canonical runtime code lives in `../ai/`.

See [docs/architecture.md](../docs/architecture.md) for full details.
