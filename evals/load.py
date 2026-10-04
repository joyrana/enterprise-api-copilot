"""Load benchmark for the platform API (local reference implementation or the backend).

    python -m evals.load --base-url http://127.0.0.1:8080 --user alice \
        --requests 400 --concurrency 8 --out evals/reports/load

Workload (read-only, safe to run against the sandbox): a fixed, seeded mix of catalog
searches, operation descriptions and discovery runs (the full agent path: intent →
plan → skill runtime). Reports throughput, latency percentiles per operation (only
where the sample supports them) and error counts, plus provenance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from evals import metrics as m
from evals.provenance import collect

QUERIES = [
    "refund a payment",
    "list orders that were shipped",
    "create a customer payment",
    "track a shipment",
    "fetch a customer profile",
    "cancel an authorized payment",
]
OPERATIONS = ["createPayment", "refundPayment", "listOrders", "getShipmentTracking", "getCustomer"]
RUN_QUERIES = [
    "Which API refunds a payment?",
    "Which endpoint tracks a shipment?",
    "What API lists customers?",
]


def workload(n: int, seed: int) -> list[tuple[str, str, dict[str, Any]]]:
    rng = random.Random(seed)
    items: list[tuple[str, str, dict[str, Any]]] = []
    for _ in range(n):
        roll = rng.random()
        if roll < 0.5:
            items.append(
                (
                    "search",
                    "GET",
                    {
                        "url": "/api/v1/apis/search",
                        "params": {"q": rng.choice(QUERIES), "limit": 5},
                    },
                )
            )
        elif roll < 0.8:
            items.append(("describe", "GET", {"url": f"/api/v1/apis/{rng.choice(OPERATIONS)}"}))
        else:
            items.append(
                ("run", "POST", {"url": "/api/v1/runs", "json": {"query": rng.choice(RUN_QUERIES)}})
            )
    return items


async def run(
    base_url: str, token: str, requests: int, concurrency: int, seed: int
) -> dict[str, Any]:
    items = workload(requests, seed)
    latencies: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    queue: asyncio.Queue[tuple[str, str, dict[str, Any]]] = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)

    async def worker(client: httpx.AsyncClient) -> None:
        while True:
            try:
                name, method, kwargs = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started = time.perf_counter()
            try:
                response = await client.request(method, **kwargs)
                ok = response.status_code < 400
            except httpx.HTTPError:
                ok = False
            elapsed = (time.perf_counter() - started) * 1000
            latencies[name].append(elapsed)
            if not ok:
                errors[name] += 1

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=30, trust_env=False
    ) as client:
        started = time.perf_counter()
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
        wall = time.perf_counter() - started

    def stats(values: list[float]) -> dict[str, Any]:
        return {
            "n": len(values),
            "mean_ms": m.mean(values),
            "p50_ms": m.percentile(values, 50),
            "p95_ms": m.percentile(values, 95),
            "p99_ms": m.percentile(values, 99),
        }

    every = [v for vs in latencies.values() for v in vs]
    return {
        "requests": requests,
        "concurrency": concurrency,
        "wall_s": round(wall, 3),
        "throughput_rps": round(requests / wall, 2),
        "errors": dict(errors),
        "overall": stats(every),
        "by_operation": {k: stats(v) for k, v in sorted(latencies.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.load")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--user", default="alice", help="dev user (local reference implementation)")
    parser.add_argument(
        "--token", default=None, help="bearer token (otherwise a dev token is requested)"
    )
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--out", type=Path, default=Path("evals/reports/load"))
    args = parser.parse_args(argv)

    token = args.token
    if token is None:
        response = httpx.post(
            f"{args.base_url}/api/v1/auth/dev-token", json={"subject": args.user}, trust_env=False
        )
        response.raise_for_status()
        token = response.json()["access_token"]
    result = asyncio.run(run(args.base_url, token, args.requests, args.concurrency, args.seed))
    report = {
        "provenance": collect(
            dataset_version="v1",
            config={
                "base_url": args.base_url,
                "workload": "50% search / 30% describe / 20% discovery runs",
                "server": "single uvicorn worker",
            },
            seeds={"workload": args.seed},
        ),
        "result": result,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "load.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if sum(result["errors"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
