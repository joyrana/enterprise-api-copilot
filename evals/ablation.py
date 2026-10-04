"""Retrieval / selection ablation with paired comparisons (dev for choosing, test for reporting).

    python -m evals.ablation --split dev  --out evals/reports/ablation-dev
    python -m evals.ablation --split test --out evals/reports/ablation-test

Grid: retrieval mode {keyword, dense, hybrid} x index {hashing, lsa} x analyzer {plain, stem},
on corpus v2 (120 docs, paraphrased questions) and API-selection v2. Every configuration is
compared with the baseline (hybrid + hashing + plain) on the same examples. Defaults should
only change when the *test* split agrees with dev — choosing on test would leak.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

from ai.knowledge.chunking import ChunkingConfig
from ai.knowledge.retrieval import RetrievalMode
from evals import metrics as m
from evals.provenance import collect
from evals.suites import BASELINE_INDEX, IndexConfig, run_api_selection, run_retrieval

DATASETS = Path(__file__).resolve().parent / "datasets" / "v2"
CORPUS = Path(__file__).resolve().parent / "corpora" / "v2" / "docs"
MODES: tuple[RetrievalMode, ...] = ("keyword", "dense", "hybrid")
INDEXES = [IndexConfig(e, a) for e, a in product(("hashing", "lsa"), ("plain", "stem"))]
BASELINE = ("hybrid", BASELINE_INDEX.label())


def _load(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (DATASETS / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


def _vector(run: dict[str, Any], key: str) -> list[float]:
    return [float(e[key] or 0.0) for e in run["examples"]]


def run(split: str) -> dict[str, Any]:
    rag = [r for r in _load(f"retrieval_{split}.jsonl") if not r["should_abstain"]]
    abstain = [r for r in _load(f"retrieval_{split}.jsonl") if r["should_abstain"]]
    sel = _load(f"api_selection_{split}.jsonl")
    chunking = ChunkingConfig()
    configs: list[dict[str, Any]] = []
    for mode, idx in product(MODES, INDEXES):
        retrieval = run_retrieval(
            rag, mode=mode, chunking=chunking, index_config=idx, corpus=CORPUS
        )
        abst = (
            run_retrieval(abstain, mode=mode, chunking=chunking, index_config=idx, corpus=CORPUS)
            if abstain
            else None
        )
        selection = run_api_selection(sel, mode=mode, index_config=idx)
        configs.append(
            {
                "mode": mode,
                "index": idx.label(),
                "retrieval": retrieval,
                "abstain": abst,
                "selection": selection,
            }
        )

    base = next(c for c in configs if (c["mode"], c["index"]) == BASELINE)
    rows = []
    for c in configs:
        r, s = c["retrieval"]["aggregates"], c["selection"]["aggregates"]
        rows.append(
            {
                "mode": c["mode"],
                "index": c["index"],
                "recall@5": r["recall@5"],
                "mrr": r["mrr"],
                "ndcg@5": r["ndcg@5"],
                "answered": r["answered_when_answerable"],
                "fact_inclusion": r["fact_inclusion"],
                "abstained_unanswerable": c["abstain"]["aggregates"]["abstained_when_unanswerable"]
                if c["abstain"]
                else None,
                "selection_top1": s["top1_accuracy"],
                "selection_mrr": s["mrr"],
                "vs_baseline": {
                    "mrr": m.paired_bootstrap_diff(
                        _vector(c["retrieval"], "mrr"), _vector(base["retrieval"], "mrr")
                    ),
                    "recall@5": m.paired_bootstrap_diff(
                        _vector(c["retrieval"], "recall@5"), _vector(base["retrieval"], "recall@5")
                    ),
                    "selection_top1": m.paired_bootstrap_diff(
                        [1.0 if e["top1_correct"] else 0.0 for e in c["selection"]["examples"]],
                        [1.0 if e["top1_correct"] else 0.0 for e in base["selection"]["examples"]],
                    ),
                },
            }
        )
    return {
        "split": split,
        "provenance": collect(
            dataset_version="v2",
            config={
                "corpus": "evals/corpora/v2 (120 docs)",
                "chunking": chunking.label(),
                "baseline": "hybrid+hashing+plain",
                "k": 5,
            },
            seeds={"bootstrap": 20261004, "corpus": 20261004},
        ),
        "counts": {
            "rag_answerable": len(rag),
            "rag_unanswerable": len(abstain),
            "api_selection": len(sel),
        },
        "results": rows,
        "raw": configs,
    }


def _fmt(s: dict[str, Any]) -> str:
    ci = s.get("ci95")
    return (
        f"{s['mean']:.3f}" + (f" [{ci[0]:.2f},{ci[1]:.2f}]" if ci else "")
        if s.get("mean") is not None
        else "n/a"
    )


def _diff(d: dict[str, Any]) -> str:
    ci = d.get("ci95")
    sign = "+" if (d["mean_diff"] or 0) >= 0 else ""
    return (
        f"{sign}{d['mean_diff']:.3f}"
        + (f" [{ci[0]:+.2f},{ci[1]:+.2f}]" if ci else "")
        + f" ({d['wins']}W/{d['losses']}L)"
    )


def render(report: dict[str, Any]) -> str:
    p = report["provenance"]
    lines = [
        f"# Retrieval ablation — {report['split']} split",
        "",
        f"- Run {p['run_at']} · commit `{p['git']['commit']}` (dirty {p['git']['dirty']}) · dataset v2 sha256 `{p['dataset']['sha256'][:16]}…`",
        f"- Examples: {report['counts']}",
        "- Paired differences vs baseline (hybrid + hashing + plain) with 95% paired-bootstrap CIs; W/L = per-example wins/losses.",
        "",
        "| Mode | Index | Recall@5 | MRR | ΔMRR vs baseline | Selection top-1 | Δ top-1 vs baseline | Abstain (unanswerable) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['mode']} | {r['index']} | {_fmt(r['recall@5'])} | {_fmt(r['mrr'])} | {_diff(r['vs_baseline']['mrr'])} | "
            f"{_fmt(r['selection_top1'])} | {_diff(r['vs_baseline']['selection_top1'])} | {r['abstained_unanswerable']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.ablation")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run(args.split)
    out = (
        args.out
        or Path("evals/reports")
        / f"ablation-{args.split}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "ablation.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "ablation.md").write_text(render(report), encoding="utf-8")
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
