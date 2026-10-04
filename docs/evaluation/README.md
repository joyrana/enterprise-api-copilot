# Evaluation

Evaluation is offline-first and deterministic-first (ADR-0008). Everything here runs
without credentials:

```bash
python -m evals run --suite smoke   # PR gate (13 agent, 10 RAG, 5 selection examples)
python -m evals run --suite full    # all examples + retrieval/chunking ablation
```

Each run writes `report.json` (provenance, configuration, raw per-example results,
aggregates with 95% bootstrap CIs) and `report.md` to `evals/reports/<suite>-<timestamp>/`
(git-ignored; CI uploads them as artifacts). **Exit code 1 if any safety gate fails.**

## Layout

| Path | Contents |
|---|---|
| `evals/datasets/v1/agent.jsonl` | 38 end-to-end tasks in 17 categories: discovery, explanation, read/write execution, clarification, troubleshooting, token inspection, code generation, docs, abstention, unsupported/harmful, prompt injection, cross-tenant, unauthorized, destructive, environment switching, fault injection |
| `evals/datasets/v1/retrieval.jsonl` | 24 RAG questions with relevant doc IDs, key facts, abstention labels, tenant |
| `evals/datasets/v1/api_selection.jsonl` | 20 natural-language → `operationId` cases |
| `evals/metrics.py` | Recall/Precision@k, MRR, nDCG, set P/R/F1, bootstrap CI, size-aware percentiles |
| `evals/suites.py` | Suite runners (real runtime + real sandbox, fresh state per agent task) |
| `evals/provenance.py` | Git SHA + dirty flag, dataset SHA-256 per file, environment |

Every example has a stable `id`, `category`, `input`, expected properties, `difficulty`,
`dataset_version` and a `smoke` flag. All data is synthetic.

## What is measured

**Agent** (per task, through `Orchestrator` → `SkillRuntime` → sandbox gateway):
intent, final status, exact tool set and tool P/R/F1, operation selected, argument binding /
missing-field detection, required text present / forbidden text absent (message *and*
audit log), number of executed writes, tool calls, latency. An evaluator acts as the human
approver only when a case says `approve: true`.

**Safety invariants — hard gates from day one:** unauthorized execution, approval bypass
(any executed write without an approval id), injection-driven tool call, cross-tenant leak
(foreign tenant docs or data), secret leak (credential patterns in messages or audit).

**RAG:** doc-level Recall@5, Precision@5, MRR, nDCG@5 on answerable questions; answered
rate on answerable questions; abstention rate on unanswerable ones; citation correctness;
key-fact inclusion (substring proxy, *not* a semantic judgement); cross-tenant leaks.
Retrieval and generation failures are reported separately.

**API selection:** top-1 accuracy and MRR per retrieval mode.

## Results (measured 2026-10-03)

System under test: deterministic offline stack — rule-based intent classifier (`rules-v1`),
template planner (`template-v1`), extractive answerer (`extractive-v1`), **hashing-lexical
embedder (not semantic)**, no LLM, no reranker. Dataset v1, SHA-256 `ae002bf039b76510…`.
Base commit `2e5ef5b` with uncommitted working-tree changes (the code in this change set).
Python 3.13.16, Linux x86_64, 2 vCPU. One repetition (the stack is deterministic).

### Agent (n=38)

| Metric | Baseline | After 2 bug fixes |
|---|---|---|
| Task success | 0.737 [0.605, 0.868] | **0.763 [0.632, 0.895]** |
| Intent accuracy | 0.974 | 0.974 |
| Final-status accuracy | 0.895 | 0.921 |
| Tool selection P / R / F1 | 0.959 / 0.946 / 0.952 | 0.959 / 0.946 / 0.952 |
| Argument binding / missing fields | 1.000 | 1.000 |
| Latency p50 / p95 | 2.1 ms / 607 ms | 2.1 ms / 607 ms |
| **Safety violations (all categories)** | **0** | **0** |

p95 is dominated by fault-injection cases that wait through retry backoff. p99 is not
reported (n < 100). The two fixes (code generation failing for operations with a required
body; failure messages dropping the error class) were found *by* this dataset, so the
post-fix number is optimistic for those cases; treat the baseline as the unbiased figure.

Remaining failures (9) are genuine weaknesses of the deterministic stack, not tuned away:

| Cause | Cases |
|---|---|
| Vocabulary gap — "charge" has no lexical overlap with `createPayment`; the run executed a *read* (`getCustomer`) instead | ag-008, ag-038 |
| No stemming ("refunding", "creating", "captured payments" → wrong operation) | ag-004, ag-019, ag-037 |
| Extractive answerer's 50% term-overlap threshold abstains on conversational phrasing | ag-014, ag-016, ag-020 |
| Off-topic rule suppressed when a resource word appears ("song about payments") | ag-023 |

Category success: abstention, clarification, cross-tenant, destructive, discovery,
environment, read execution, injection, token and unauthorized all 1.00; troubleshooting
0.33, codegen/docs/explanation/fault/unsupported 0.50, write execution 0.67.

### API operation selection (n=20)

| Mode | Top-1 | MRR |
|---|---|---|
| keyword (BM25) | 0.75 [0.55, 0.95] | 0.81 |
| dense (hashing) | 0.70 [0.50, 0.90] | 0.80 |
| hybrid (RRF k=60) | **0.80 [0.60, 0.95]** | **0.854** |

Hybrid is best on this set but the intervals overlap heavily; no significance is claimed.

### RAG (24 questions: 20 answerable, 4 unanswerable incl. 1 cross-tenant probe)

All six configurations (3 modes × default chunking, plus 3 alternative chunkings with
hybrid) score Recall@5 = 1.00, nDCG@5 0.98–1.00, answered 0.80, abstained 1.00, citation
correctness 0.94–0.97, key-fact inclusion 0.75, cross-tenant leaks 0.

**This ablation is inconclusive by construction:** the corpus has ~8 documents, so k=5
retrieves most of it and rank metrics saturate. It verifies the pipeline and tenant
isolation; it does **not** support choosing a mode, chunk size or overlap. Default chunking
(`heading-220-30`) remains an unvalidated placeholder (ADR-0007).

### Load (platform API over HTTP, measured 2026-10-03)

`python -m evals.load` against `python -m ai.api platform` (single uvicorn worker) with the
sandbox gateway as a separate process; 400 requests, seeded mix of 50% catalog search,
30% describe, 20% discovery runs (full agent path). 2 vCPU, loopback network, file run store.

| Run store | Concurrency | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| file (2026-10-03) | 1 | 338 req/s | 2.3 ms | 5.8 ms | 7.1 ms | 0 |
| file (2026-10-03) | 8 | 569 req/s | 12.9 ms | 21.2 ms | 28.2 ms | 0 |
| SQLite (2026-10-04) | 1 | 421 req/s | 1.9 ms | 4.3 ms | 5.4 ms | 0 |
| SQLite (2026-10-04) | 8 | 1021 req/s | 7.2 ms | 10.8 ms | 12.5 ms | 0 |

The workload is read-only and the system under test is deterministic (no LLM), so these
numbers measure the platform/agent/runtime overhead only — not model latency, and not a
production deployment. The two store rows are separate runs on different days (sandbox
fault injection was enabled in the first), so the comparison is indicative, not paired.
The bottleneck found in the first run — `GET /api/v1/runs` scanning one file per run
(~27 ms at 167 runs) — is gone with the indexed SQL store (~3 ms at 166 runs).

## Retrieval ablation v2 (measured 2026-10-04)

v1's corpus (8 docs) saturated every rank metric, so it could not choose a configuration.
v2 is generated deterministically by `python -m evals.corpora.generate_v2` (seed 20261004):
120 documents — 8 fictional products × 12 topics with near-duplicate wording across products,
plus 24 distractors — and 102 questions phrased with synonyms instead of the documents'
words, split 50/50 into **dev** (for choosing settings) and **test** (held out, reporting
only). Dataset `v2` sha256 of `retrieval_test.jsonl` starts `16020ea4…`.

Grid: mode {keyword, dense, hybrid} × embedder {hashing, LSA} × analyzer {plain, light
stemmer}. Baseline = hybrid + hashing + plain. Differences are paired per question with 95%
paired-bootstrap CIs. LSA's only tuned parameter (rank fraction 0.3) was chosen on dev.

Held-out **test** split, hybrid mode (n=47 answerable questions):

| Index | MRR | Recall@5 | ΔMRR vs baseline [95% CI] | Wins/Losses |
|---|---|---|---|---|
| hashing + plain (baseline) | 0.728 | 0.872 | — | — |
| hashing + stem | 0.781 | 0.957 | +0.054 [−0.05, +0.16] | 13/7 |
| LSA + plain | 0.771 | 0.808 | +0.044 [−0.01, +0.11] | 6/10 |
| **LSA + stem** | **0.968** | **1.000** | **+0.240 [+0.13, +0.36]** | **18/3** |

Dev split agrees in direction for LSA + stem (+0.036, CI [−0.05, +0.13]) but is far smaller,
so the size of the test gain should be read cautiously. Dense retrieval with the hashing
embedder is worse than baseline on both splits (ΔMRR −0.12, CI excludes 0). All 4
unanswerable test questions were abstained on in every configuration.

**Decision:** the documentation index now uses LSA + light stemming (`Settings.docs_embedder`
/ `docs_analyzer`). Agent suite v1 after the switch: identical per-example outcomes
(29/38, no flips) and zero safety violations.

**Not changed:** API-operation selection (n=12 per split) gave contradictory results —
stemming +0.167 on dev, −0.167 on test — so the catalog keeps the baseline. More selection
data is needed before any change there.

## LLM-as-judge (harness ready; live calibration not yet run)

`evals/judge.py` grades answer relevance on rubric `answer-relevance-v1` (0–2, explicit
criteria and four in-prompt calibration examples; sources passed as untrusted context).
It reports agreement with human labels (exact + Cohen's κ), stability over repeated runs,
parse failures, tokens, cost and latency. The calibration set (16 items, one with an
embedded injection) was labelled by the project author, not independent annotators.

Offline CI runs the harness with a scripted provider that replays the human labels (κ = 1.0
by construction): this verifies the pipeline, **not** a model. A live calibration
(`COPILOT_JUDGE_PROVIDER=anthropic`, opt-in) has not been run — no API key was available.

## Known limitations of the evaluation itself

- Small synthetic datasets → wide CIs. No paired significance tests are reported.
- The unit tests and this dataset were written by the same author in the same session;
  independent authorship and a held-out split are needed before tuning against it.
- No LLM-judge yet: answer quality is measured with deterministic proxies only.
- No human-labelled calibration subset exists yet.
- Load numbers come from one run per setting on a shared 2-vCPU sandbox; treat as indicative.

## Next evaluation work

1. Done: corpus v2 + dev/test split + paired ablation (above). Next: a pretrained semantic
   embedder behind `Embedder` (blocked: model download host) as another paired arm.
2. Grow API-selection data (≥100 queries) so catalog changes can be decided.
3. Run the live judge calibration; add independently labelled items; then use the judge
   for answer relevance on the RAG suites.
4. Independent authorship: v2 was generated from templates written by the same author as the
   system; an externally written test set is still needed.
