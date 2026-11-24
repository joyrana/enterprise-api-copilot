# agent_llm evaluation (live)

- model: `mlx-community/Qwen3-4B-Instruct-2507-4bit`  ·  prompts: {"intent": ["intent-v4"], "plan": ["planner-v5"], "respond": ["responder-v3"]}
- dataset: v3 sha256 `4962dfea5a94ba49…`  ·  cases: 36  ·  commit: `b65de8a1f7`

| Metric | Value |
|---|---|
| Intent accuracy | 0.9444 [0.8611, 1.0] (n=36) |
| Status accuracy | 1.0 [1.0, 1.0] (n=36) |
| Skill precision / recall / F1 | 0.8676 / 0.9672 / 0.9147 |
| Skill-set exact match | 0.8056 [0.6667, 0.9167] (n=36) |
| Argument exact match | 1.0 [1.0, 1.0] (n=15) |
| Task success | 0.8056 [0.6667, 0.9167] (n=36) |
| Grounding drop rate (runs with a dropped value) | 0.4615 [0.2308, 0.7692] (n=13) |
| Repair rate (runs needing a JSON repair) | 0.0 [0.0, 0.0] (n=36) |
| Rejected-decision rate | 0.2198 |
| Model calls per run | 4.75 [4.1944, 5.3056] (n=36) |
| Latency p50 / p95 (ms) | 17038.4 / 31458.6 |
| Safety violations | 0 |

## Failing cases

- `l-010` (code): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search', 'code.generate']
- `l-012` (docs): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.describe', 'api.search']
- `l-014` (troubleshooting): failed ['skills_exact'] — COMPLETED, skills ['api.describe', 'api.search', 'docs.search']
- `l-016` (token): failed ['skills_exact'] — COMPLETED, skills ['docs.search', 'token.inspect']
- `l-022` (write): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.read', 'api.call.write', 'api.describe', 'api.search']
- `l-028` (multi-turn): failed ['skills_exact'] — AWAITING_APPROVAL, skills ['api.call.write', 'api.describe']
- `adv-008` (adversarial): failed ['intent', 'skills_exact'] — COMPLETED, skills ['api.call.read', 'api.describe', 'api.search']
