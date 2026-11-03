"""Hybrid search: BM25 (FTS5) + vector search, fused with Reciprocal Rank Fusion, then reranked.

1. Keyword search over Norwegian stems and vector search (when the index has vectors from the same model as the
   chosen embedder) each return up to ``candidates`` chunks.
2. Reciprocal Rank Fusion: ``score = Σ 1 / (k + rank)`` with k = 60 – robust, needs no score calibration.
3. A cross-encoder (BGE reranker v2 M3) reorders the fused candidates; without one the RRF order is used.
4. Filtering on modules and chunk types happens inside both searches.

Optional query rewriting is only used for long, vague questions; short or precise questions are searched as is.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from emneklar.core.ai.local.embedding import Embedder, Reranker
from emneklar.features.course_rag.citations import citation
from emneklar.features.course_rag.markdown import plain_text
from emneklar.features.course_rag.store import ChunkRecord, IndexStore
from emneklar.features.course_rag.text import STOPWORDS, stems, words

log = logging.getLogger(__name__)

RRF_K = 60
RERANK_CHARS = 2400
VAGUE_MARKERS = {"dette", "det", "den", "denne", "sånn", "slik", "greia", "ting", "tingen", "noe", "noen", "forklar",
                 "hjelp", "skjønner", "forstår", "this", "that", "thing", "stuff", "explain"}


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def needs_rewrite(query: str) -> bool:
    """Vague, longer questions benefit from rewriting; short or precise ones do not (they are searched as is)."""
    tokens = words(query)
    if len(tokens) < 6:
        return False
    content = [t for t in tokens if t not in STOPWORDS]
    vague = any(t in VAGUE_MARKERS for t in tokens)
    return vague or len(content) / len(tokens) < 0.5


@dataclass
class Candidate:
    chunk: ChunkRecord
    keyword_rank: int | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    rrf_score: float = 0.0
    rrf_rank: int = 0
    rerank_score: float | None = None
    final_rank: int = 0

    def as_dict(self, *, debug: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chunk_id": self.chunk.id, "type": self.chunk.type, "item_kind": self.chunk.item_kind,
            "title": self.chunk.title, "heading_path": self.chunk.heading_path, "module": self.chunk.module_name,
            "url": self.chunk.url, "page": self.chunk.page, "page_end": self.chunk.page_end,
            "start": self.chunk.start, "end": self.chunk.end, "citation": citation(self.chunk),
            "snippet": plain_text(self.chunk.text)[:400], "text": self.chunk.text, "meta": self.chunk.meta,
            "rank": self.final_rank,
        }
        if debug:
            data["scores"] = {"keyword_rank": self.keyword_rank, "keyword_score": self.keyword_score,
                              "vector_rank": self.vector_rank, "vector_score": self.vector_score,
                              "rrf_score": round(self.rrf_score, 6), "rrf_rank": self.rrf_rank,
                              "rerank_score": self.rerank_score}
        return data


@dataclass
class SearchOutcome:
    hits: list[Candidate]
    candidates: list[Candidate]
    modes: dict[str, bool]
    queries: list[str]
    notes: list[str] = field(default_factory=list)

    def as_dict(self, *, debug: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"hits": [h.as_dict(debug=debug) for h in self.hits], "modes": self.modes,
                                "queries": self.queries, "notes": self.notes}
        if debug:
            by_rrf = sorted(self.candidates, key=lambda c: c.rrf_rank)
            data["debug"] = {"before_rerank": [c.as_dict(debug=True) for c in by_rrf],
                             "after_rerank": [c.as_dict(debug=True) for c in
                                              sorted(self.candidates, key=lambda c: c.final_rank)]}
        return data


async def search(store: IndexStore, query: str, *, embedder: Embedder | None, reranker: Reranker | None,
                 module_ids: list[str] | None = None, types: list[str] | None = None, candidates: int = 40,
                 top_k: int = 6, extra_queries: list[str] | None = None) -> SearchOutcome:
    queries = [query, *[q for q in (extra_queries or []) if q.strip() and q.strip() != query]]
    notes: list[str] = []
    rankings: list[list[int]] = []
    keyword: dict[int, tuple[int, float]] = {}
    vector: dict[int, tuple[int, float]] = {}
    for q in queries:
        hits = store.keyword_search(q, module_ids=module_ids, types=types, limit=candidates)
        rankings.append([cid for cid, _ in hits])
        for rank, (cid, score) in enumerate(hits, start=1):
            if cid not in keyword or rank < keyword[cid][0]:
                keyword[cid] = (rank, round(score, 4))
    use_vectors = embedder is not None and store.embedding_identity == embedder.identity
    if embedder is not None and not use_vectors:
        notes.append("Indeksen er laget med en annen embedding-modell enn den som er valgt nå. Bare nøkkelordsøk er "
                     "brukt. Bygg indeksen på nytt for semantisk søk.")
    if use_vectors and embedder is not None:
        for q in queries:
            query_vector = await embedder.embed_query(q)
            hits = store.vector_search(query_vector, module_ids=module_ids, types=types, limit=candidates)
            rankings.append([cid for cid, _ in hits])
            for rank, (cid, score) in enumerate(hits, start=1):
                if cid not in vector or rank < vector[cid][0]:
                    vector[cid] = (rank, round(score, 4))
    fused = rrf(rankings)[:candidates]
    chunks = store.get_chunks([cid for cid, _ in fused])
    pool: list[Candidate] = []
    for rank, (cid, score) in enumerate(fused, start=1):
        chunk = chunks.get(cid)
        if chunk is None:
            continue
        kw = keyword.get(cid)
        vec = vector.get(cid)
        pool.append(Candidate(chunk, keyword_rank=kw[0] if kw else None, keyword_score=kw[1] if kw else None,
                              vector_rank=vec[0] if vec else None, vector_score=vec[1] if vec else None,
                              rrf_score=score, rrf_rank=rank))
    reranked = False
    if reranker is not None and pool:
        try:
            scores = await reranker.score(query, [(c.chunk.header() + "\n" + c.chunk.text)[:RERANK_CHARS]
                                                  for c in pool])
            for candidate, score in zip(pool, scores, strict=True):
                candidate.rerank_score = round(float(score), 4)
            pool.sort(key=lambda c: (-(c.rerank_score or 0.0), c.rrf_rank))
            reranked = True
        except Exception:
            log.exception("Rerangering feilet – bruker RRF-rekkefølgen")
            notes.append("Rerangeringen feilet. Treffene er sortert med RRF.")
    for rank, candidate in enumerate(pool, start=1):
        candidate.final_rank = rank
    return SearchOutcome(hits=pool[:top_k], candidates=pool,
                         modes={"keyword": True, "vector": use_vectors, "rerank": reranked,
                                "rewritten": len(queries) > 1},
                         queries=queries, notes=notes)


def query_terms(query: str) -> list[str]:
    return stems(query)
