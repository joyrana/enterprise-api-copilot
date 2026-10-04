"""Markdown rendering of evaluation reports (every number comes from the JSON report)."""

from __future__ import annotations

from typing import Any


def _fmt(summary: Any) -> str:
    if isinstance(summary, dict) and "mean" in summary:
        if summary["mean"] is None:
            return "n/a"
        ci = summary.get("ci95")
        return (
            f"{summary['mean']:.3f}"
            + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")
            + f" (n={summary['n']})"
        )
    if summary is None:
        return "n/a"
    if isinstance(summary, float):
        return f"{summary:.3f}"
    return str(summary)


def render_markdown(report: dict[str, Any], *, brief: bool = False) -> str:
    prov = report["provenance"]
    lines = [
        f"# Evaluation report — {report['suite']} suite",
        "",
        f"- Run: {prov['run_at']} · commit `{prov['git']['commit']}` (dirty: {prov['git']['dirty']})",
        f"- Dataset {prov['dataset']['version']} sha256 `{prov['dataset']['sha256'][:16]}…` · examples: "
        + ", ".join(f"{k}={v}" for k, v in report["counts"].items()),
        f"- System under test: {prov['config']['system_under_test']} (embedder: hashing-lexical, **not semantic**; no LLM)",
        f"- Environment: Python {prov['environment']['python']}, {prov['environment']['platform']}, {prov['environment']['cpu_count']} CPU",
        "- Intervals are 95% percentile-bootstrap CIs of the mean; small n ⇒ wide intervals, no significance claims.",
        "",
        "## Safety gates",
        "",
    ]
    failures = report.get("gates", {}).get("safety_failures", [])
    lines.append(
        "All safety invariants held." if not failures else "**FAILED:** " + "; ".join(failures)
    )

    agent = report["agent"]["aggregates"]
    lines += [
        "",
        "## Agent (end-to-end through runtime + sandbox)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Task success | {_fmt(agent['task_success'])} |",
        f"| Intent accuracy | {_fmt(agent['intent_accuracy'])} |",
        f"| Final status accuracy | {_fmt(agent['status_accuracy'])} |",
        f"| Operation selection (where specified) | {_fmt(agent['operation_accuracy'])} |",
        f"| Argument binding / missing-field detection | {_fmt(agent['argument_binding_accuracy'])} |",
        f"| Tool selection P / R / F1 | {agent['tool_selection']['precision']:.3f} / {agent['tool_selection']['recall']:.3f} / {agent['tool_selection']['f1']:.3f} |",
        f"| Exact tool-set match | {_fmt(agent['exact_tool_set_rate'])} |",
        f"| Unnecessary tool calls (total) | {agent['unnecessary_tool_calls']} |",
        f"| Mean tool calls per task | {_fmt(agent['mean_tool_calls'])} |",
        f"| Latency p50 / p95 / p99 (ms) | {agent['latency_ms']['p50']} / {agent['latency_ms']['p95'] or 'n<20'} / {agent['latency_ms']['p99'] or 'n<100'} |",
    ]
    lines += [
        "",
        "Success by category: "
        + ", ".join(f"{k} {v:.2f}" for k, v in agent["success_by_category"].items()),
    ]
    failed = [e for e in report["agent"]["examples"] if not e["success"]]
    if failed:
        lines += ["", "Failed agent examples:", ""]
        for e in failed:
            bad = [k for k, ok in e["checks"].items() if not ok] + e["safety_violations"]
            lines.append(
                f"- `{e['id']}` ({e['category']}): failed {', '.join(bad)} — status {e['status']}, tools {e['tools']}"
            )
    if brief:
        return "\n".join(lines)

    lines += [
        "",
        "## API operation selection",
        "",
        "| Mode | Top-1 accuracy | MRR |",
        "|---|---|---|",
    ]
    for run in report["api_selection"]["runs"]:
        a = run["aggregates"]
        lines.append(f"| {run['config']['mode']} | {_fmt(a['top1_accuracy'])} | {_fmt(a['mrr'])} |")

    lines += [
        "",
        "## RAG retrieval and answers",
        "",
        "Rank metrics over answerable questions (doc-level, k=5). Abstention measured separately.",
        "",
        "| Mode | Chunking | Recall@5 | Precision@5 | MRR | nDCG@5 | Answered (answerable) | Abstained (unanswerable) | Citation correctness | Key-fact inclusion | Cross-tenant leaks |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in report["retrieval"]["runs"]:
        a = run["aggregates"]
        lines.append(
            f"| {run['config']['mode']} | {run['config']['chunking']} | {_fmt(a['recall@5'])} | {_fmt(a['precision@5'])} | "
            f"{_fmt(a['mrr'])} | {_fmt(a['ndcg@5'])} | {_fmt(a['answered_when_answerable'])} | "
            f"{_fmt(a['abstained_when_unanswerable'])} | {_fmt(a['citation_correctness'])} | {_fmt(a['fact_inclusion'])} | {a['cross_tenant_leaks']} |"
        )
    lines += [
        "",
        "Notes: Precision@5 is bounded by the number of relevant documents (usually 1-2), so its ceiling is 0.2-0.4.",
        "Key-fact inclusion is a deterministic substring proxy for answer relevance, not a semantic judgement.",
        "",
        f"Cost: {report['cost']['note']}.",
    ]
    return "\n".join(lines) + "\n"
