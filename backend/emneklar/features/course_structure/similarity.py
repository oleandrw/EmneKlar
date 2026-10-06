"""Small, dependency-free text similarity (TF-IDF cosine, shingle Jaccard)."""

from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS = set(
    "og i er det som en et på til av for med at ikke de den har jeg vi kan skal om fra eller men så også hvis når hva "
    "hvordan alle denne dette disse deg du dere seg sin sitt sine være blir ble vil må ved etter under mellom uten "
    "både bare mer mange hver ikkje eg me dei korleis kva frå berre mykje vil vi oss din ditt dine sin side sider "
    "the and of to is in that it for on with as are this be by was from or an which at have not can will you your "
    "modul uke emnet emne les oppgave innlevering".split())
WORD = re.compile(r"[a-zæøåA-ZÆØÅ]{3,}")


def tokens(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text or "") if w.lower() not in STOPWORDS]


class TfIdf:
    def __init__(self, documents: dict[str, str]) -> None:
        self.tf = {key: Counter(tokens(text)) for key, text in documents.items()}
        df: Counter[str] = Counter()
        for counts in self.tf.values():
            df.update(counts.keys())
        n = max(1, len(self.tf))
        self.idf = {term: math.log((1 + n) / (1 + d)) + 1 for term, d in df.items()}
        self.vectors = {key: self._vector(counts) for key, counts in self.tf.items()}

    def _vector(self, counts: Counter[str]) -> dict[str, float]:
        total = sum(counts.values()) or 1
        vec = {t: (c / total) * self.idf.get(t, 1.0) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())

    @staticmethod
    def centroid(vectors: list[dict[str, float]]) -> dict[str, float]:
        acc: Counter[str] = Counter()
        for vec in vectors:
            for t, v in vec.items():
                acc[t] += v
        norm = math.sqrt(sum(v * v for v in acc.values())) or 1.0
        return {t: v / norm for t, v in acc.items()}

    @staticmethod
    def shared_terms(a: dict[str, float], b: dict[str, float], k: int = 5) -> list[str]:
        common = sorted(((a[t] * b[t], t) for t in a.keys() & b.keys()), reverse=True)
        return [t for _, t in common[:k]]


def shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    words = tokens(text)
    return {tuple(words[i:i + size]) for i in range(max(0, len(words) - size + 1))}


def jaccard(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
