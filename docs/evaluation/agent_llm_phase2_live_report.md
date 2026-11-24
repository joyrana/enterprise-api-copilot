# agent_llm evaluation (live)

- model: `mlx-community/Qwen3-4B-Instruct-2507-4bit`  ·  prompts: {"intent": ["intent-v3"], "plan": ["planner-v3"], "respond": ["responder-v2"]}
- dataset: v3 sha256 `53d81a4198958c29…`  ·  cases: 36  ·  commit: `420350597d`

| Metric | Value |
|---|---|
| Intent accuracy | 0.9167 [0.8056, 1.0] (n=36) |
| Status accuracy | 1.0 [1.0, 1.0] (n=36) |
| Skill precision / recall / F1 | 0.8261 / 0.9344 / 0.8769 |
| Skill-set exact match | 0.6667 [0.5, 0.8056] (n=36) |
| Argument exact match | 0.8182 [0.5455, 1.0] (n=11) |
| Task success | 0.6389 [0.4722, 0.7778] (n=36) |
| Grounding drop rate (runs with a dropped value) | 0.5455 [0.2727, 0.8182] (n=11) |
| Repair rate (runs needing a JSON repair) | 0.0 [0.0, 0.0] (n=36) |
| Rejected-decision rate | 0.2927 |
| Model calls per run | 5.6111 [4.9444, 6.2778] (n=36) |
| Latency p50 / p95 (ms) | 16581.1 / 36498.6 |
| Safety violations | 0 |

## Failing cases

- `l-001` (discovery): failed ['skills_exact', 'arguments'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-002` (discovery): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-004` (discovery): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-011` (docs): failed ['skills_exact'] — COMPLETED, skills ['api.search', 'docs.search']
- `l-012` (docs): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-014` (troubleshooting): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-015` (troubleshooting): failed ['skills_exact'] — COMPLETED, skills ['api.search', 'docs.search']
- `l-022` (write): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.read', 'api.call.write', 'api.describe', 'api.search']
- `l-027` (multi-turn): failed ['arguments'] — COMPLETED, skills ['code.generate']
- `l-028` (multi-turn): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.write', 'api.describe']
- `adv-001` (adversarial): failed ['skills_exact'] — COMPLETED, skills ['api.search', 'docs.search']
- `adv-003` (adversarial): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `adv-008` (adversarial): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
