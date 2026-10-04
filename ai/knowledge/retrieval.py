"""In-process retrieval: BM25 (keyword), dense (cosine over an ``Embedder``) and hybrid (RRF).

Tenant filtering happens **before** scoring: chunks a tenant cannot see are never scored,
ranked or returned (threat model T6).

The default ``HashingEmbedder`` hashes word unigrams/bigrams and character trigrams into a
fixed-size signed vector. It is an offline, deterministic baseline that captures lexical
and sub-word overlap; it is **not** a semantic embedding model and is labelled as such in
every evaluation report. Real embedding models plug in through the ``Embedder`` protocol.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict

from ai.knowledge.documents import Chunk
from ai.knowledge.text import tokenize

Analyzer = Callable[[str], list[str]]

RetrievalMode = Literal["keyword", "dense", "hybrid"]
RRF_K = 60


class Embedder(Protocol):
    name: str
    version: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingEmbedder:
    name = "hashing-lexical"
    version = "1"

    def __init__(self, dimensions: int = 512, *, analyzer: Analyzer = tokenize) -> None:
        self.dimensions = dimensions
        self.analyzer = analyzer

    def _features(self, text: str) -> Iterable[str]:
        words = self.analyzer(text)
        yield from (f"w:{w}" for w in words)
        yield from (f"b:{a}_{b}" for a, b in itertools.pairwise(words))
        for w in words:
            padded = f"#{w}#"
            yield from (f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2))

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for feature in self._features(text):
                digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                value = int.from_bytes(digest, "little")
                index = value % self.dimensions
                sign = 1.0 if (value >> 63) & 1 else -1.0
                weight = 1.0 if feature.startswith("w:") else 0.5
                matrix[row, index] += sign * weight
            norm = float(np.linalg.norm(matrix[row]))
            if norm > 0:
                matrix[row] /= norm
        return matrix


class LSAEmbedder:
    """Latent semantic analysis: TF-IDF (sublinear tf) projected onto the top-k singular
    vectors of the corpus, L2-normalised. Captures co-occurrence ("charge" near "payment")
    that pure lexical hashing cannot. Trained on the indexed corpus only (no external
    data); numpy SVD, so no extra dependency. Out-of-vocabulary queries embed to zero.
    """

    name = "lsa-tfidf"
    version = "1"

    def __init__(
        self, dimensions: int = 128, *, analyzer: Analyzer = tokenize, rank_fraction: float = 0.3
    ) -> None:
        self.dimensions = dimensions
        self.analyzer = analyzer
        # Keep at most this fraction of the corpus rank: without truncation LSA degenerates
        # into plain TF-IDF cosine (no latent dimensions are learned).
        self.rank_fraction = rank_fraction
        self.components = 0
        self._vocab: dict[str, int] = {}
        self._idf = np.zeros(0, dtype=np.float32)
        self._projection = np.zeros((0, dimensions), dtype=np.float32)

    def _tfidf(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), len(self._vocab)), dtype=np.float32)
        for row, text in enumerate(texts):
            for term, count in Counter(self.analyzer(text)).items():
                col = self._vocab.get(term)
                if col is not None:
                    matrix[row, col] = 1.0 + math.log(count)
        return matrix * self._idf

    def fit(self, texts: Sequence[str]) -> None:
        df: Counter[str] = Counter()
        for text in texts:
            df.update(set(self.analyzer(text)))
        self._vocab = {term: i for i, term in enumerate(sorted(df))}
        n = len(texts)
        self._idf = np.array(
            [math.log((1 + n) / (1 + df[t])) + 1.0 for t in sorted(df)], dtype=np.float32
        )
        tfidf = self._tfidf(texts)
        # Right singular vectors span the term space; keep the top-k as the projection.
        _, _, vt = np.linalg.svd(tfidf, full_matrices=False)
        k = max(1, min(self.dimensions, int(vt.shape[0] * self.rank_fraction)))
        self.components = k
        projection = np.zeros((len(self._vocab), self.dimensions), dtype=np.float32)
        projection[:, :k] = vt[:k].T
        self._projection = projection

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not self._vocab:
            return np.zeros((len(texts), self.dimensions), dtype=np.float32)
        vectors = self._tfidf(texts) @ self._projection
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


class BM25:
    def __init__(self, k1: float = 1.2, b: float = 0.75, *, analyzer: Analyzer = tokenize) -> None:
        self.k1, self.b = k1, b
        self.analyzer = analyzer
        self._docs: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._df: Counter[str] = Counter()
        self._avg = 0.0

    def fit(self, texts: Sequence[str]) -> None:
        self._docs = [Counter(self.analyzer(t)) for t in texts]
        self._lengths = [sum(d.values()) for d in self._docs]
        self._df = Counter()
        for d in self._docs:
            self._df.update(d.keys())
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    def scores(self, query: str, candidates: Sequence[int]) -> dict[int, float]:
        terms = self.analyzer(query)
        n = len(self._docs)
        out: dict[int, float] = {}
        for i in candidates:
            doc, length = self._docs[i], self._lengths[i]
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self._avg or 1))
                score += idf * tf * (self.k1 + 1) / denom
            if score > 0:
                out[i] = score
        return out


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk: Chunk
    score: float
    rank: int
    keyword_rank: int | None = None
    dense_rank: int | None = None


def rrf(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i(d)), ranks starting at 1."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


class KnowledgeIndex:
    """Holds chunks plus lexical and dense indexes; rebuilt on change (small corpora)."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        dense_min_score: float = 0.05,
        analyzer: Analyzer = tokenize,
    ) -> None:
        self.embedder: Embedder = embedder or HashingEmbedder(analyzer=analyzer)
        self.dense_min_score = dense_min_score
        self.analyzer = analyzer
        self._chunks: list[Chunk] = []
        self._bm25 = BM25(analyzer=analyzer)
        self._matrix = np.zeros((0, self.embedder.dimensions), dtype=np.float32)

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> None:
        """Incremental upsert: drop every chunk of ``doc_id`` (any version), add new ones."""
        self._chunks = [c for c in self._chunks if c.doc_id != doc_id] + list(chunks)
        self._rebuild()

    def delete_document(self, doc_id: str) -> int:
        before = len(self._chunks)
        self._chunks = [c for c in self._chunks if c.doc_id != doc_id]
        self._rebuild()
        return before - len(self._chunks)

    def add(self, chunks: Sequence[Chunk]) -> None:
        by_doc: dict[str, list[Chunk]] = {}
        for c in chunks:
            by_doc.setdefault(c.doc_id, []).append(c)
        self._chunks = [c for c in self._chunks if c.doc_id not in by_doc] + list(chunks)
        self._rebuild()

    def _rebuild(self) -> None:
        texts = [f"{c.title} {c.section} {c.text}" for c in self._chunks]
        self._bm25.fit(texts)
        fit = getattr(self.embedder, "fit", None)
        if callable(fit) and texts:
            fit(texts)  # corpus-trained embedders (LSA) refit on change
        self._matrix = (
            self.embedder.embed(texts)
            if texts
            else np.zeros((0, self.embedder.dimensions), dtype=np.float32)
        )

    def _visible(self, tenant_id: str, source_types: set[str] | None) -> list[int]:
        return [
            i
            for i, c in enumerate(self._chunks)
            if c.visible_to(tenant_id) and (source_types is None or c.source_type in source_types)
        ]

    def keyword_ranking(self, query: str, candidates: Sequence[int]) -> list[tuple[int, float]]:
        scores = self._bm25.scores(query, candidates)
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))

    def dense_ranking(self, query: str, candidates: Sequence[int]) -> list[tuple[int, float]]:
        if not candidates:
            return []
        q = self.embedder.embed([query])[0]
        sims = self._matrix[list(candidates)] @ q
        pairs = [
            (i, float(s))
            for i, s in zip(candidates, sims, strict=True)
            if s >= self.dense_min_score
        ]
        return sorted(pairs, key=lambda kv: (-kv[1], kv[0]))

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        k: int = 5,
        mode: RetrievalMode = "hybrid",
        source_types: set[str] | None = None,
        candidate_pool: int = 50,
    ) -> list[RetrievedChunk]:
        candidates = self._visible(tenant_id, source_types)
        kw = self.keyword_ranking(query, candidates)[:candidate_pool] if mode != "dense" else []
        dn = self.dense_ranking(query, candidates)[:candidate_pool] if mode != "keyword" else []
        kw_rank = {i: r for r, (i, _) in enumerate(kw, start=1)}
        dn_rank = {i: r for r, (i, _) in enumerate(dn, start=1)}
        if mode == "keyword":
            ordered = kw
        elif mode == "dense":
            ordered = dn
        else:
            fused = rrf([[i for i, _ in kw], [i for i, _ in dn]])
            # Ties (common with two lists) break on keyword rank, then dense rank, then position.
            big = len(self._chunks) + 1
            ordered = sorted(
                fused.items(),
                key=lambda kv: (-kv[1], kw_rank.get(kv[0], big), dn_rank.get(kv[0], big), kv[0]),
            )
        return [
            RetrievedChunk(
                chunk=self._chunks[i],
                score=round(score, 6),
                rank=rank,
                keyword_rank=kw_rank.get(i),
                dense_rank=dn_rank.get(i),
            )
            for rank, (i, score) in enumerate(ordered[:k], start=1)
        ]
