"""Tokenization shared by lexical retrieval, the hashing embedder and token budgets.

``count_tokens`` is an approximation (whitespace words x 1.3, rounded up) used only for
context budgets. It is deliberately conservative; swap in a model tokenizer behind the
same function when a real provider is configured.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it me my of on or show "
    "that the this to was what when where which who why will with you your".split()
)


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    # Split camelCase (operationIds such as createPayment) before lowercasing.
    text = _CAMEL.sub(" ", text)
    tokens = _TOKEN.findall(text.lower())
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS]


def count_tokens(text: str) -> int:
    words = len(text.split())
    return math.ceil(words * 1.3)


# Ordered (suffix, replacement, minimum stem length). Deliberately small and conservative:
# it conflates inflections (refunding/refunded/refunds → refund) without Porter-style
# over-stemming. Evaluated as an ablation; see docs/evaluation/README.md.
_SUFFIXES: tuple[tuple[str, str, int], ...] = (
    ("ies", "y", 3),
    ("ing", "", 4),
    ("ed", "", 4),
    ("es", "", 4),
    ("s", "", 3),
)
_KEEP = frozenset(
    {"status", "process", "access", "address", "class", "is", "has", "was", "this", "its"}
)


def _strip_suffix(token: str) -> str:
    for suffix, replacement, min_stem in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= min_stem:
            stem = token[: -len(suffix)] + replacement
            # "shipped" → "shipp" → "ship"; "cancelled" → "cancell" → "cancel".
            if suffix in ("ed", "ing") and len(stem) > 3 and stem[-1] == stem[-2]:
                if stem[-1] not in "lsz" or (stem[-1] == "l" and len(stem) >= 6):
                    stem = stem[:-1]
            return stem
    return token


def light_stem(token: str) -> str:
    if token in _KEEP or token.isdigit() or token.endswith("ss"):
        return token
    stem = _strip_suffix(token)
    # Normalise a final "e" so capture/captured, create/creating, charge/charges agree.
    if len(stem) > 4 and stem.endswith("e"):
        stem = stem[:-1]
    return stem


def tokenize_stemmed(text: str) -> list[str]:
    return [light_stem(t) for t in tokenize(text)]
