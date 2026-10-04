"""Secret redaction applied before logging, auditing, tracing, model submission and reports.

Two mechanisms:

* **Key-based:** values under keys whose name looks secret-bearing are replaced entirely.
* **Pattern-based:** known credential shapes inside free text are replaced.

Redaction is lossy by design. It errs on the side of hiding data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|api[-_]?key|apikey|credential|cookie|"
    r"private[-_]?key|client[-_]?secret|session[-_]?(token|cookie|secret)|signature|bearer)",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")),
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("provider_key", re.compile(r"\b(sk|rk|pk)-(live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}\b")),
    ("basic_auth_url", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
)


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY.search(key))


def redact_text(text: str) -> str:
    for _name, pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def contains_secret(text: str) -> bool:
    """True when ``text`` contains a credential-shaped substring (used by leak evaluators)."""
    return any(pattern.search(text) for _name, pattern in _PATTERNS)


def redact(value: Any, *, max_depth: int = 20) -> Any:
    """Return a redacted deep copy of ``value`` (dicts, lists, tuples, strings)."""
    if max_depth <= 0:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_secret_key(key):
                out[key] = REDACTED
            else:
                out[key] = redact(item, max_depth=max_depth - 1)
        return out
    if isinstance(value, list | tuple):
        return [redact(item, max_depth=max_depth - 1) for item in value]
    return value
