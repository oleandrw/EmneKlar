"""Grounding: split course content into citable chunks and retrieve relevant ones (BM25).

AI checks and question generation receive only these chunks, each with a
stable id. Answers must cite chunk ids and quote supporting text verbatim;
:func:`quote_supported` verifies the quotes, so the model cannot invent
sources.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from emneklar.core.canvas.html import norm_text, parse_html
from emneklar.core.canvas.snapshot import SnapshotView
from emneklar.features.course_structure.similarity import tokens

CHUNK_WORDS = 220


@dataclass(frozen=True)
class Chunk:
    id: str  # «K12»
    object_ref: str
    title: str
    module: str | None
    text: str

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "object_ref": self.object_ref, "title": self.title, "module": self.module}


def build_chunks(view: SnapshotView, *, module_ids: list[str] | None = None) -> list[Chunk]:
    """Chunks from pages, assignment descriptions and discussions (optionally limited to modules)."""
    wanted: set[str] | None = None
    if module_ids:
        wanted = set()
        for module in view.get("module"):
            if module.canvas_id in module_ids:
                for item in view.items_of(module.canvas_id):
                    ref = view.item_content_ref(item)
                    if ref:
                        wanted.add(ref)
    chunks: list[Chunk] = []
    counter = 0
    for kind in ("page", "assignment", "discussion"):
        for obj in view.get(kind):
            if not obj.body or (wanted is not None and obj.ref not in wanted):
                continue
            if obj.meta.get("published") is False:
                continue
            soup = parse_html(obj.body)
            paragraphs = [norm_text(el.get_text(" ")) for el in soup.find_all(["p", "li", "h2", "h3", "h4", "td"])]
            text = " ".join(p for p in paragraphs if p) or norm_text(soup.get_text(" "))
            words = text.split()
            if len(words) < 15:
                continue
            modules = view.module_of.get(obj.ref)
            for start in range(0, len(words), CHUNK_WORDS):
                piece = " ".join(words[start:start + CHUNK_WORDS])
                if len(piece.split()) < 15 and start > 0:
                    continue
                counter += 1
                chunks.append(Chunk(id=f"K{counter}", object_ref=obj.ref, title=obj.title,
                                    module=modules[0] if modules else None, text=piece))
    return chunks


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75) -> None:
        self.chunks = chunks
        self.docs = [Counter(tokens(c.text + " " + c.title)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        terms = tokens(query)
        scores = []
        for index, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.lengths[index] / (self.avg or 1))
                score += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            if score > 0:
                scores.append((score, index))
        return [self.chunks[i] for _, i in sorted(scores, reverse=True)[:k]]


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9æøå]+", " ", text.lower()).strip()


def quote_supported(quote: str, chunk: Chunk | None) -> bool:
    """A quote counts as supported when (almost) all of it appears verbatim in the cited chunk."""
    if chunk is None:
        return False
    q = _squash(quote)
    if len(q.split()) < 3:
        return False
    if q in _squash(chunk.text):
        return True
    words = q.split()
    target = _squash(chunk.text)
    # Allow small deviations: 85 % of 4-word windows must occur in the chunk.
    windows = [" ".join(words[i:i + 4]) for i in range(max(1, len(words) - 3))]
    hits = sum(1 for w in windows if w in target)
    return hits / len(windows) >= 0.85
