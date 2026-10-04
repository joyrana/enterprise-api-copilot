"""Evaluation runner.

    python -m evals run --suite smoke        # PR gate: small, deterministic, no credentials
    python -m evals run --suite full         # all examples + retrieval/chunking ablation
    python -m evals run --suite full --out evals/reports/local

Writes ``report.json`` (provenance, config, raw per-example results, aggregates) and
``report.md`` (human summary). Exit code 1 when a safety hard gate fails
(ADR-0008): unauthorized execution, approval bypass, injection-driven tool call,
cross-tenant leak or secret leak — in any suite. Quality thresholds are not gated until a
baseline has been agreed (``--min-task-success`` lets CI opt in explicitly).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai.knowledge.chunking import ChunkingConfig
from ai.knowledge.retrieval import RetrievalMode
from evals import provenance, suites
from evals.report import render_markdown

DATASET_VERSION = "v1"
DEFAULT_CHUNKING = ChunkingConfig()
ABLATION_CHUNKING = [
    ChunkingConfig(strategy="heading", max_tokens=220, overlap_tokens=30),
    ChunkingConfig(strategy="heading", max_tokens=120, overlap_tokens=20),
    ChunkingConfig(strategy="fixed", max_tokens=120, overlap_tokens=20),
    ChunkingConfig(strategy="heading", max_tokens=400, overlap_tokens=40),
]
MODES: tuple[RetrievalMode, ...] = ("keyword", "dense", "hybrid")
HYBRID_ONLY: tuple[RetrievalMode, ...] = ("hybrid",)


def safety_gate(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for name, count in report["agent"]["aggregates"]["safety_violations"].items():
        failures.append(f"agent: {name} x{count}")
    for run in report["retrieval"]["runs"]:
        if run["aggregates"]["cross_tenant_leaks"]:
            failures.append(
                f"retrieval[{run['config']['mode']},{run['config']['chunking']}]: "
                f"cross_tenant_leak x{run['aggregates']['cross_tenant_leaks']}"
            )
    return failures


async def run(suite: str) -> dict[str, Any]:
    smoke = suite == "smoke"
    rag_rows = suites.load(DATASET_VERSION, "retrieval", smoke=smoke)
    sel_rows = suites.load(DATASET_VERSION, "api_selection", smoke=smoke)
    agent_rows = suites.load(DATASET_VERSION, "agent", smoke=smoke)

    chunkings = [DEFAULT_CHUNKING] if smoke else ABLATION_CHUNKING
    retrieval_runs = [
        suites.run_retrieval(rag_rows, mode=mode, chunking=chunking)
        for chunking in chunkings
        for mode in (MODES if chunking == DEFAULT_CHUNKING else HYBRID_ONLY)
    ]
    selection_runs = [suites.run_api_selection(sel_rows, mode=mode) for mode in MODES]
    agent = await suites.run_agent(agent_rows)
    return {
        "suite": suite,
        "provenance": provenance.collect(
            dataset_version=DATASET_VERSION,
            config={
                "system_under_test": "deterministic offline stack",
                "intent_classifier": "rules-v1",
                "planner": "template-v1",
                "answerer": "extractive-v1",
                "embedder": {
                    "name": "hashing-lexical",
                    "version": "1",
                    "dimensions": 512,
                    "semantic": False,
                },
                "reranker": None,
                "model": None,
                "prompt_version": None,
                "default_chunking": DEFAULT_CHUNKING.label(),
                "retrieval_k": suites.K,
                "rrf_k": 60,
            },
            seeds={"bootstrap": 20261003},
        ),
        "counts": {
            "retrieval": len(rag_rows),
            "api_selection": len(sel_rows),
            "agent": len(agent_rows),
            "repetitions": 1,
        },
        "exclusions": [],
        "retrieval": {"runs": retrieval_runs},
        "api_selection": {"runs": selection_runs},
        "agent": agent,
        "cost": {
            "model_tokens": 0,
            "estimated_cost_usd": 0.0,
            "note": "no model calls in the offline stack",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    run_p.add_argument("--out", type=Path, default=None)
    run_p.add_argument("--min-task-success", type=float, default=None)
    args = parser.parse_args(argv)

    report = asyncio.run(run(args.suite))
    failures = safety_gate(report)
    report["gates"] = {"safety_failures": failures}
    success = report["agent"]["aggregates"]["task_success"]["mean"] or 0.0
    if args.min_task_success is not None and success < args.min_task_success:
        failures.append(f"task_success {success} < {args.min_task_success}")

    out = (
        args.out
        or Path("evals/reports") / f"{args.suite}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {out}/report.json and report.md")
    print(render_markdown(report, brief=True))
    if failures:
        print("GATE FAILURES:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
