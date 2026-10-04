"""Generate retrieval corpus v2 and its dev/test question sets (deterministic, seeded).

    python -m evals.corpora.generate_v2        # rewrites evals/corpora/v2 and datasets/v2

Design (why it is harder than v1):
* 8 fictional products x 12 topics = 96 documents plus 24 distractor notes. Documents on the
  same topic share structure and vocabulary across products, so retrieval must use the
  product name and the specific facts, not just the topic words.
* Each document carries product-specific facts (limits, scopes, windows) drawn from a seeded
  RNG, so answers cannot be guessed from the topic alone.
* Questions are phrased with synonyms and paraphrases instead of the document's own wording
  (e.g. "throttling ceiling" for "rate limit"), which penalises purely lexical matching.
* Questions are split 50/50 into ``dev`` (for choosing settings) and ``test`` (held out, for
  reporting). Generated output is committed so runs are reproducible without regeneration.

All names and values are synthetic.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import cast

SEED = 20261004
DATASET_VERSION = "2.0.0"
ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "v2" / "docs"
DATASETS = ROOT.parent / "datasets" / "v2"

PRODUCTS = [
    "Ledger",
    "Payouts",
    "Invoicing",
    "Subscriptions",
    "Disputes",
    "Identity",
    "Shipping",
    "Loyalty",
]

# topic -> (title, body template, fact generator, question paraphrases, answer key)
TOPICS: dict[str, dict[str, object]] = {
    "rate-limits": {
        "title": "Rate limits",
        "body": "The {p} API enforces a rate limit of {n} requests per minute per client application. "
        "Requests above the limit receive HTTP 429 with a Retry-After header. Burst traffic is smoothed by a spike arrest policy at the gateway.",
        "facts": lambda r: {"n": r.choice([30, 45, 60, 90, 120, 240, 300, 600])},
        "questions": [
            "What is the throttling ceiling for {p} calls each minute?",
            "How many {p} requests can one app send per minute before being throttled?",
        ],
        "answer": "{n}",
    },
    "auth-scopes": {
        "title": "Authentication and scopes",
        "body": "{p} uses OAuth 2.0 client credentials. Read operations need the {s}:read scope and changes need {s}:write. Tokens are valid for {m} minutes.",
        "facts": lambda r: {"m": r.choice([5, 10, 15, 30, 60]), "s": None},
        "questions": [
            "How long does a {p} access token stay usable?",
            "After how many minutes must a {p} bearer credential be renewed?",
        ],
        "answer": "{m} minutes",
    },
    "webhooks": {
        "title": "Webhooks",
        "body": "{p} sends webhook events signed with HMAC-SHA256 in the X-Signature header. Failed deliveries are retried {k} times with exponential backoff over {h} hours.",
        "facts": lambda r: {"k": r.choice([3, 5, 8, 10, 12]), "h": r.choice([6, 12, 24, 48, 72])},
        "questions": [
            "How many redelivery attempts does {p} make for a callback that fails?",
            "If my {p} event endpoint is down, how often will notifications be re-sent?",
        ],
        "answer": "{k} times",
    },
    "pagination": {
        "title": "Pagination",
        "body": "List endpoints in the {p} API use cursor pagination. The page size defaults to {d} and cannot exceed {x}. Pass the next_cursor value to fetch the following page.",
        "facts": lambda r: {"d": r.choice([10, 20, 25, 50]), "x": r.choice([100, 200, 250, 500])},
        "questions": [
            "What is the biggest page I can request from {p} list calls?",
            "Maximum number of items per page for {p} listings?",
        ],
        "answer": "{x}",
    },
    "idempotency": {
        "title": "Idempotency",
        "body": "{p} write requests accept an Idempotency-Key header. Keys are remembered for {h} hours; reusing a key with a different body returns HTTP 409.",
        "facts": lambda r: {"h": r.choice([12, 24, 48, 72, 168])},
        "questions": [
            "For how long does {p} remember a duplicate-protection key?",
            "How many hours is a {p} retry-safety key retained?",
        ],
        "answer": "{h} hours",
    },
    "errors": {
        "title": "Error codes",
        "body": "{p} returns error code {c} when a request is valid JSON but violates a business rule. Every error body includes a correlation identifier for support.",
        "facts": lambda r: {
            "c": r.choice(
                [
                    "E-RULE-12",
                    "E-RULE-31",
                    "E-RULE-44",
                    "E-RULE-57",
                    "E-RULE-68",
                    "E-RULE-73",
                    "E-RULE-85",
                    "E-RULE-96",
                ]
            )
        },
        "questions": [
            "Which error identifier signals a broken business rule in {p}?",
            "What code does {p} use when my payload is well-formed but not allowed?",
        ],
        "answer": "{c}",
    },
    "versioning": {
        "title": "Versioning",
        "body": "The current {p} API version is {v}. Older versions remain supported for {mo} months after a new version is released; send the API-Version header to pin one.",
        "facts": lambda r: {
            "v": r.choice(["2025-11", "2026-01", "2026-03", "2026-05", "2026-07"]),
            "mo": r.choice([6, 9, 12, 18, 24]),
        },
        "questions": [
            "How long are superseded {p} releases kept alive?",
            "After a new {p} version ships, for how many months does the old one keep working?",
        ],
        "answer": "{mo} months",
    },
    "sandbox": {
        "title": "Sandbox",
        "body": "The {p} sandbox resets all test data every {r} days. Sandbox credentials start with the prefix {pre} and never work in production.",
        "facts": lambda r: {
            "r": r.choice([1, 7, 14, 30]),
            "pre": r.choice(["tst_", "sbx_", "dev_", "demo_"]),
        },
        "questions": [
            "How frequently is the {p} test environment wiped?",
            "Every how many days does {p} clear its practice data?",
        ],
        "answer": "{r} days",
    },
    "regions": {
        "title": "Data residency",
        "body": "{p} stores customer data in the {reg} region by default. Cross-region replication is available on request and takes up to {t} business days to enable.",
        "facts": lambda r: {
            "reg": r.choice(["ap-south", "eu-west", "us-east", "ap-southeast"]),
            "t": r.choice([3, 5, 10]),
        },
        "questions": [
            "Where does {p} keep customer records unless told otherwise?",
            "Which geography hosts {p} data by default?",
        ],
        "answer": "{reg}",
    },
    "limits": {
        "title": "Object limits",
        "body": "A single {p} request body may not exceed {kb} kilobytes, and each object can hold at most {meta} metadata keys.",
        "facts": lambda r: {
            "kb": r.choice([64, 128, 256, 512]),
            "meta": r.choice([20, 40, 50, 100]),
        },
        "questions": [
            "How large may a {p} payload be?",
            "What is the size cap on a {p} request body?",
        ],
        "answer": "{kb} kilobytes",
    },
    "sdks": {
        "title": "SDKs",
        "body": "Official {p} SDKs are published for {langs}. Community libraries exist for other languages but are not supported by the {p} team.",
        "facts": lambda r: {
            "langs": r.choice(
                [
                    "Java and Python",
                    "Go and TypeScript",
                    "Python and TypeScript",
                    "Java, Go and Python",
                ]
            )
        },
        "questions": [
            "In which programming languages does {p} ship supported client libraries?",
            "Which official client packages exist for {p}?",
        ],
        "answer": "{langs}",
    },
    "support": {
        "title": "Support and status",
        "body": "{p} incidents are posted on the status page within {sla} minutes of detection. Priority support is reachable through the {ch} channel.",
        "facts": lambda r: {
            "sla": r.choice([5, 10, 15, 30]),
            "ch": r.choice(["#api-help", "#platform-support", "#oncall-api"]),
        },
        "questions": [
            "How soon after detection is a {p} outage announced?",
            "Within how many minutes does {p} publish an incident notice?",
        ],
        "answer": "{sla} minutes",
    },
}

DISTRACTORS = [
    "Release notes for the internal design system: new button variants and colour tokens.",
    "Office relocation FAQ: parking permits, desk booking and the new cafeteria hours.",
    "Quarterly engineering all-hands agenda and the slides from the roadmap session.",
    "How to request a laptop replacement and what to do with the old device.",
    "Guidelines for writing post-incident reviews: blameless language and timelines.",
    "The data team's dashboard naming convention and folder structure.",
]


def build() -> tuple[list[tuple[str, str]], list[dict[str, object]]]:
    rng = random.Random(SEED)
    docs: list[tuple[str, str]] = []
    questions: list[dict[str, object]] = []
    for product in PRODUCTS:
        slug = product.lower()
        for topic, spec in TOPICS.items():
            facts = spec["facts"](rng)  # type: ignore[operator]
            facts["p"] = product
            facts["s"] = slug
            body = str(spec["body"]).format(**facts)
            doc_id = f"docs/{slug}-{topic}.md"
            docs.append((doc_id, f"# {product}: {spec['title']}\n\n{body}\n"))
            template = rng.choice(cast(list[str], spec["questions"]))
            questions.append(
                {
                    "category": "rag",
                    "tenant": "acme",
                    "input": str(template).format(**facts),
                    "relevant_doc_ids": [doc_id],
                    "must_include": [str(spec["answer"]).format(**facts)],
                    "should_abstain": False,
                    "difficulty": "hard",
                }
            )
    for i, text in enumerate(DISTRACTORS * 4):
        docs.append((f"docs/notes-{i:02d}.md", f"# Internal note {i}\n\n{text}\n"))
    for q in [
        "What is the cafeteria menu on Fridays?",
        "Which Kubernetes version runs the Ledger cluster?",
        "Who is the on-call manager for Loyalty this week?",
        "What was Payouts revenue last quarter?",
        "How do I reset my VPN password?",
        "What is the SLA uptime percentage for Identity?",
    ]:
        questions.append(
            {
                "category": "rag",
                "tenant": "acme",
                "input": q,
                "relevant_doc_ids": [],
                "must_include": [],
                "should_abstain": True,
                "difficulty": "hard",
            }
        )
    rng.shuffle(questions)
    for i, row in enumerate(questions):
        row["id"] = f"v2-rag-{i:03d}"
        row["dataset_version"] = DATASET_VERSION
        row["split"] = "dev" if i % 2 == 0 else "test"
    return docs, questions


def main() -> None:
    docs, questions = build()
    if CORPUS.exists():
        shutil.rmtree(CORPUS)
    CORPUS.mkdir(parents=True)
    for doc_id, text in docs:
        (CORPUS / doc_id.removeprefix("docs/")).write_text(text, encoding="utf-8")
    DATASETS.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        rows = [q for q in questions if q["split"] == split]
        with (DATASETS / f"retrieval_{split}.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                ordered = {
                    k: row[k]
                    for k in (
                        "dataset_version",
                        "id",
                        "split",
                        "category",
                        "tenant",
                        "input",
                        "relevant_doc_ids",
                        "must_include",
                        "should_abstain",
                        "difficulty",
                    )
                }
                fh.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    print(f"{len(docs)} documents, {len(questions)} questions")


if __name__ == "__main__":
    main()
