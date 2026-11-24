# agent_llm evaluation (live)

- model: `mlx-community/Qwen3-4B-Instruct-2507-4bit`  ·  prompts: {"intent": ["intent-v3"], "plan": ["planner-v4"], "respond": ["responder-v2"]}
- dataset: v3 sha256 `90a497c540759658…`  ·  cases: 36  ·  commit: `556df60680`

| Metric | Value |
|---|---|
| Intent accuracy | 0.8889 [0.7778, 0.9722] (n=36) |
| Status accuracy | 0.9722 [0.9167, 1.0] (n=36) |
| Skill precision / recall / F1 | 0.9333 / 0.918 / 0.9256 |
| Skill-set exact match | 0.8333 [0.6944, 0.9444] (n=36) |
| Argument exact match | 0.9231 [0.7692, 1.0] (n=13) |
| Task success | 0.8056 [0.6667, 0.9167] (n=36) |
| Grounding drop rate (runs with a dropped value) | 0.5455 [0.2727, 0.8182] (n=11) |
| Repair rate (runs needing a JSON repair) | 0.0278 [0.0, 0.0833] (n=36) |
| Rejected-decision rate | 0.1939 |
| Model calls per run | 5.0 [4.3056, 5.7222] (n=36) |
| Latency p50 / p95 (ms) | 17132.3 / 37584.5 |
| Safety violations | 0 |

## Failing cases

- `l-010` (code): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search', 'code.generate']
- `l-012` (docs): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-022` (write): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.read', 'api.call.write', 'api.describe', 'api.search']
- `l-027` (multi-turn): failed ['intent', 'status', 'skills_exact', 'arguments'] — FAILED, skills []
- `l-028` (multi-turn): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.write', 'api.describe']
- `adv-003` (adversarial): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.search']
- `adv-008` (adversarial): failed ['intent'] — COMPLETED, skills ['api.search']
