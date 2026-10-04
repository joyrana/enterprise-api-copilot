from __future__ import annotations

import numpy as np
import pytest

from ai.knowledge.retrieval import LSAEmbedder
from ai.knowledge.text import light_stem, tokenize_stemmed
from evals.metrics import paired_bootstrap_diff


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("refunding", "refund"),
        ("captured", "capture"),
        ("creating", "create"),
        ("charges", "charge"),
        ("cancelled", "cancel"),
        ("shipped", "ship"),
        ("currencies", "currency"),
        ("tracking", "track"),
    ],
)
def test_word_families_share_a_stem(a: str, b: str) -> None:
    assert light_stem(a) == light_stem(b)


def test_stemmer_leaves_protected_and_short_tokens() -> None:
    assert [light_stem(t) for t in ["status", "access", "is", "429", "pass", "api"]] == [
        "status",
        "access",
        "is",
        "429",
        "pass",
        "api",
    ]
    assert tokenize_stemmed("Refunding captured payments") == ["refund", "captur", "payment"]


def test_lsa_truncates_rank_and_learns_cooccurrence() -> None:
    corpus = [
        "charge customer card payment",
        "payment charge authorize card",
        "ship parcel carrier tracking",
        "carrier tracking parcel delivery",
        "invoice tax pdf billing",
        "billing invoice pdf tax",
    ]
    emb = LSAEmbedder(dimensions=128, rank_fraction=0.5)
    emb.fit(corpus)
    assert emb.components == 3  # truncated: < corpus rank, otherwise LSA == TF-IDF cosine
    vectors = emb.embed([*corpus, "authorize card", "unknownword"])
    assert np.allclose(np.linalg.norm(vectors[:-1], axis=1), 1.0, atol=1e-5)
    assert not vectors[-1].any()  # out-of-vocabulary query embeds to zero
    query = vectors[6]
    # "authorize card" never co-occurs with "charge customer" verbatim beyond "card", but the
    # latent payment topic ranks both payment docs above shipping/billing docs.
    sims = vectors[:6] @ query
    assert set(np.argsort(-sims)[:2]) == {0, 1}


def test_paired_bootstrap_diff() -> None:
    result = paired_bootstrap_diff([1, 1, 1, 0, 1, 1], [0, 1, 0, 0, 1, 0])
    assert (
        result["mean_diff"] == 0.5
        and result["wins"] == 3
        and result["losses"] == 0
        and result["ties"] == 3
    )
    lo, hi = result["ci95"]  # type: ignore[misc]
    assert 0 < lo <= 0.5 <= hi
    assert paired_bootstrap_diff([1, 0], [0, 1])["ci95"] is None  # too few pairs for an interval
    with pytest.raises(ValueError):
        paired_bootstrap_diff([1], [1, 2])
