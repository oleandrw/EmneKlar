"""One search index per course: ``<data>/rag/course-<id>.sqlite``.

* ``items`` – every Canvas element that was processed (or skipped), with ``updated_at``, ``content_hash`` and a
  signature of the processing options, so updates only reprocess what changed.
* ``chunks`` – text, metadata and the embedding vector (float32 BLOB, normalised).
* ``chunks_fts`` – FTS5 over Norwegian stems (BM25). If this Python's SQLite lacks FTS5, BM25 is computed in
  Python from the same stems (same results, slower).

Vector search is exact (numpy, cosine on normalised vectors) – a course has at most some tens of thousands of
chunks, so no approximate index or SQLite extension is needed.

The file is derived data. It is marked with its own ``application_id`` (never another program's file) and a
schema version; an index from an incompatible version must be rebuilt.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from emneklar.core.errors import AppError
from emneklar.features.course_rag.text import stem_string, stems

APPLICATION_ID = 0x456B5247  # "EkRG"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
    item_key TEXT PRIMARY KEY, kind TEXT NOT NULL, canvas_id TEXT, title TEXT NOT NULL DEFAULT '', url TEXT,
    modules TEXT NOT NULL DEFAULT '[]', updated_at TEXT, content_hash TEXT, signature TEXT,
    status TEXT NOT NULL, reason TEXT, chunk_count INTEGER NOT NULL DEFAULT 0, processed_at TEXT,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, item_key TEXT NOT NULL, type TEXT NOT NULL,
    item_kind TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', heading_path TEXT NOT NULL DEFAULT '[]',
    text TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', module_ids TEXT NOT NULL DEFAULT ',',
    module_name TEXT, url TEXT, page INTEGER, page_end INTEGER, t_start REAL, t_end REAL, updated_at TEXT,
    tokens INTEGER NOT NULL DEFAULT 0, meta TEXT NOT NULL DEFAULT '{}', stems TEXT NOT NULL DEFAULT '',
    title_stems TEXT NOT NULL DEFAULT '', vector BLOB
);
CREATE INDEX IF NOT EXISTS ix_chunks_item ON chunks(item_key);
"""
FTS_SCHEMA = ("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title, body, "
              "tokenize = 'unicode61 remove_diacritics 0')")
CHUNK_TYPES = ("text", "table", "image", "transcript", "slide")
KEYWORD_SQL = ("SELECT f.rowid AS id, bm25(chunks_fts, 2.0, 1.0) AS score FROM chunks_fts f JOIN chunks c ON "
               "c.id = f.rowid WHERE chunks_fts MATCH ?{where} ORDER BY score LIMIT ?")


@dataclass
class ItemRecord:
    key: str
    kind: str  # page | assignment | discussion | quiz | syllabus | file | media | youtube | vimeo …
    title: str
    canvas_id: str | None = None
    url: str | None = None
    modules: list[dict[str, str]] = field(default_factory=list)  # [{id, name}]
    updated_at: str | None = None
    content_hash: str | None = None
    signature: str | None = None
    status: str = "done"  # done | skipped | failed
    reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkRecord:
    uid: str
    item_key: str
    type: str
    item_kind: str
    title: str
    text: str
    heading_path: list[str] = field(default_factory=list)
    context: str = ""
    module_ids: list[str] = field(default_factory=list)
    module_name: str | None = None
    url: str | None = None
    page: int | None = None
    page_end: int | None = None
    start: float | None = None
    end: float | None = None
    updated_at: str | None = None
    tokens: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def header(self) -> str:
        """Title and heading path – put in front of the text for embedding and BM25."""
        return " › ".join([p for p in [self.module_name, self.title, *self.heading_path] if p])

    def search_text(self) -> str:
        parts = [self.context, self.header(), self.text]
        return "\n\n".join(p for p in parts if p)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "uid": self.uid, "item_key": self.item_key, "type": self.type,
                "item_kind": self.item_kind, "title": self.title, "heading_path": self.heading_path,
                "text": self.text, "context": self.context, "module_ids": self.module_ids,
                "module_name": self.module_name, "url": self.url, "page": self.page, "page_end": self.page_end,
                "start": self.start, "end": self.end, "updated_at": self.updated_at, "tokens": self.tokens,
                "meta": self.meta}


def index_path(rag_dir: Path, course_id: str) -> Path:
    return rag_dir / f"course-{course_id}.sqlite"


def _row_chunk(row: sqlite3.Row) -> ChunkRecord:
    return ChunkRecord(
        id=row["id"], uid=row["uid"], item_key=row["item_key"], type=row["type"], item_kind=row["item_kind"],
        title=row["title"], text=row["text"], heading_path=json.loads(row["heading_path"] or "[]"),
        context=row["context"] or "", module_ids=[m for m in (row["module_ids"] or "").split(",") if m],
        module_name=row["module_name"], url=row["url"], page=row["page"], page_end=row["page_end"],
        start=row["t_start"], end=row["t_end"], updated_at=row["updated_at"], tokens=row["tokens"] or 0,
        meta=json.loads(row["meta"] or "{}"))


class IndexStore:
    """Thread-safe access to one course index (one connection, serialised by a lock)."""

    _vector_cache: dict[str, tuple[int, np.ndarray, np.ndarray]] = {}

    def __init__(self, path: Path, *, create: bool = True, force_python_bm25: bool = False) -> None:
        self.path = path
        if not path.exists() and not create:
            raise AppError("rag_index_missing", status=404)
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as fh:
                header = fh.read(100)
            app_id = int.from_bytes(header[68:72], "big") if len(header) >= 72 else 0
            if not header.startswith(b"SQLite format 3\x00") or app_id not in (0, APPLICATION_ID):
                raise AppError("rag_index_foreign", status=409, detail=str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        self.conn.executescript(SCHEMA)
        self.fts = False
        if not force_python_bm25:
            try:
                self.conn.execute(FTS_SCHEMA)
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
        version = self.meta("schema_version")
        if version is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        elif version != str(SCHEMA_VERSION):
            self.conn.close()
            raise AppError("rag_index_outdated", status=409)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- meta ------------------------------------------------------------------------------------------

    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = "
                              "excluded.value", (key, value))
            self.conn.commit()

    @property
    def revision(self) -> int:
        return int(self.meta("revision") or 0)

    def _bump(self) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES('revision', '1') ON CONFLICT(key) DO UPDATE SET "
                          "value = CAST(value AS INTEGER) + 1")

    @property
    def embedding_identity(self) -> str | None:
        return self.meta("embedding") or None

    def reset(self, embedding: str | None) -> None:
        """Empty the index (full rebuild) and record the embedding model it will be built with."""
        with self._lock:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM items")
            if self.fts:
                self.conn.execute("DELETE FROM chunks_fts")
            self.conn.execute("INSERT INTO meta(key, value) VALUES('embedding', ?) ON CONFLICT(key) DO UPDATE SET "
                              "value = excluded.value", (embedding or "",))
            self._bump()
            self.conn.commit()

    # -- items -----------------------------------------------------------------------------------------

    def items(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM items").fetchall()
        return {r["item_key"]: {**dict(r), "modules": json.loads(r["modules"] or "[]"),
                                "meta": json.loads(r["meta"] or "{}")} for r in rows}

    def put_item(self, item: ItemRecord, chunks: list[ChunkRecord] | None = None,
                 vectors: np.ndarray | None = None) -> None:
        """Replace an item and (when given) all its chunks in one transaction."""
        from datetime import UTC, datetime

        with self._lock:
            try:
                if chunks is not None:
                    self._delete_chunks(item.key)
                    for index, chunk in enumerate(chunks):
                        vector = None
                        if vectors is not None and index < len(vectors):
                            vector = np.asarray(vectors[index], dtype=np.float32).tobytes()
                        cursor = self.conn.execute(
                            "INSERT INTO chunks(uid, item_key, type, item_kind, title, heading_path, text, context, "
                            "module_ids, module_name, url, page, page_end, t_start, t_end, updated_at, tokens, meta, stems, "
                            "title_stems, vector) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (chunk.uid, chunk.item_key, chunk.type, chunk.item_kind, chunk.title,
                             json.dumps(chunk.heading_path, ensure_ascii=False), chunk.text, chunk.context,
                             "," + ",".join(chunk.module_ids) + ",", chunk.module_name, chunk.url, chunk.page,
                             chunk.page_end, chunk.start, chunk.end, chunk.updated_at, chunk.tokens,
                             json.dumps(chunk.meta, ensure_ascii=False), stem_string(chunk.search_text()),
                             stem_string(chunk.header()), vector))
                        chunk.id = cursor.lastrowid
                        if self.fts:
                            self.conn.execute("INSERT INTO chunks_fts(rowid, title, body) VALUES (?, ?, ?)",
                                              (chunk.id, stem_string(chunk.header()), stem_string(chunk.search_text())))
                count = len(chunks) if chunks is not None else 0
                self.conn.execute(
                    "INSERT INTO items(item_key, kind, canvas_id, title, url, modules, updated_at, content_hash, "
                    "signature, status, reason, chunk_count, processed_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(item_key) DO UPDATE SET kind=excluded.kind, canvas_id=excluded.canvas_id, "
                    "title=excluded.title, url=excluded.url, modules=excluded.modules, updated_at=excluded.updated_at, "
                    "content_hash=excluded.content_hash, signature=excluded.signature, status=excluded.status, "
                    "reason=excluded.reason, chunk_count=excluded.chunk_count, processed_at=excluded.processed_at, "
                    "meta=excluded.meta",
                    (item.key, item.kind, item.canvas_id, item.title, item.url,
                     json.dumps(item.modules, ensure_ascii=False), item.updated_at, item.content_hash, item.signature,
                     item.status, item.reason, count, datetime.now(UTC).isoformat(),
                     json.dumps(item.meta, ensure_ascii=False)))
                self._bump()
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def _delete_chunks(self, item_key: str) -> None:
        if self.fts:
            self.conn.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE item_key = ?)",
                              (item_key,))
        self.conn.execute("DELETE FROM chunks WHERE item_key = ?", (item_key,))

    def delete_items(self, keys: list[str]) -> int:
        with self._lock:
            for key in keys:
                self._delete_chunks(key)
                self.conn.execute("DELETE FROM items WHERE item_key = ?", (key,))
            if keys:
                self._bump()
            self.conn.commit()
        return len(keys)

    # -- chunks ----------------------------------------------------------------------------------------

    def chunk_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def get_chunks(self, ids: list[int]) -> dict[int, ChunkRecord]:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(f"SELECT * FROM chunks WHERE id IN ({marks})", ids).fetchall()  # noqa: S608
        return {r["id"]: _row_chunk(r) for r in rows}

    def iter_chunks(self, *, with_vectors: bool = False) -> Iterator[tuple[ChunkRecord, np.ndarray | None]]:
        for row in self.conn.execute("SELECT * FROM chunks ORDER BY item_key, id"):
            vector = np.frombuffer(row["vector"], dtype=np.float32) if with_vectors and row["vector"] else None
            yield _row_chunk(row), vector

    def stats(self) -> dict[str, Any]:
        types = dict(self.conn.execute("SELECT type, COUNT(*) FROM chunks GROUP BY type").fetchall())
        kinds = dict(self.conn.execute("SELECT kind, COUNT(*) FROM items WHERE status = 'done' GROUP BY kind").fetchall())
        status = dict(self.conn.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall())
        vectors = int(self.conn.execute("SELECT COUNT(*) FROM chunks WHERE vector IS NOT NULL").fetchone()[0])
        tokens = int(self.conn.execute("SELECT COALESCE(SUM(tokens), 0) FROM chunks").fetchone()[0])
        minutes = sum(float(r[0] or 0) for r in self.conn.execute(
            "SELECT MAX(t_end) FROM chunks WHERE type = 'transcript' GROUP BY item_key")) / 60
        return {"chunks": sum(types.values()), "chunk_types": types, "items": kinds, "item_status": status,
                "vectors": vectors, "tokens": tokens, "video_minutes": round(minutes, 1),
                "keyword_engine": "fts5" if self.fts else "python"}

    def modules(self) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for row in self.conn.execute("SELECT modules FROM items WHERE status = 'done'"):
            for module in json.loads(row[0] or "[]"):
                seen.setdefault(str(module.get("id")), str(module.get("name") or ""))
        return [{"id": k, "name": v} for k, v in seen.items()]

    # -- search ----------------------------------------------------------------------------------------

    @staticmethod
    def _filters(module_ids: list[str] | None, types: list[str] | None, alias: str = "c") -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if module_ids:
            clauses.append("(" + " OR ".join(f"instr({alias}.module_ids, ?) > 0" for _ in module_ids) + ")")
            params.extend(f",{m}," for m in module_ids)
        if types:
            clauses.append(f"{alias}.type IN ({','.join('?' for _ in types)})")
            params.extend(types)
        return (" AND " + " AND ".join(clauses)) if clauses else "", params

    def keyword_search(self, query: str, *, module_ids: list[str] | None = None, types: list[str] | None = None,
                       limit: int = 40) -> list[tuple[int, float]]:
        """BM25 over stems. Returns (chunk id, score) with the best first (higher = better)."""
        from emneklar.features.course_rag.text import fts_query

        expression = fts_query(query)
        if expression is None:
            return []
        where, params = self._filters(module_ids, types)
        if self.fts:
            # ``where`` holds only placeholders built by _filters; every value is a bound parameter.
            sql = KEYWORD_SQL.format(where=where)
            rows = self.conn.execute(sql, [expression, *params, limit]).fetchall()
            return [(int(r["id"]), -float(r["score"])) for r in rows]
        return self._python_bm25(query, where, params, limit)

    def _python_bm25(self, query: str, where: str, params: list[Any], limit: int) -> list[tuple[int, float]]:
        terms = list(dict.fromkeys(stems(query)))
        rows = self.conn.execute(f"SELECT c.id, c.stems, c.title_stems FROM chunks c WHERE 1=1{where}",  # noqa: S608
                                 params).fetchall()
        all_rows = self.conn.execute("SELECT stems FROM chunks").fetchall()
        n = max(1, len(all_rows))
        df: Counter[str] = Counter()
        lengths = []
        for (text,) in all_rows:
            tokens = set(text.split())
            df.update(t for t in terms if t in tokens)
            lengths.append(len(text.split()))
        avg = sum(lengths) / n if lengths else 1.0
        k1, b = 1.2, 0.75
        scores = []
        for row in rows:
            body = Counter(row["stems"].split())
            title = Counter(row["title_stems"].split())
            length = sum(body.values()) or 1
            score = 0.0
            for term in terms:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                for counts, weight in ((body, 1.0), (title, 2.0)):
                    tf = counts.get(term, 0)
                    if tf:
                        score += weight * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg))
            if score > 0:
                scores.append((int(row["id"]), score))
        return sorted(scores, key=lambda x: -x[1])[:limit]

    def _vectors(self) -> tuple[np.ndarray, np.ndarray]:
        key = str(self.path)
        cached = IndexStore._vector_cache.get(key)
        revision = self.revision
        if cached and cached[0] == revision:
            return cached[1], cached[2]
        rows = self.conn.execute("SELECT id, vector FROM chunks WHERE vector IS NOT NULL ORDER BY id").fetchall()
        if not rows:
            ids, matrix = np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
        else:
            ids = np.array([r[0] for r in rows], dtype=np.int64)
            matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        IndexStore._vector_cache[key] = (revision, ids, matrix)
        return ids, matrix

    def vector_search(self, query_vector: np.ndarray, *, module_ids: list[str] | None = None,
                      types: list[str] | None = None, limit: int = 40) -> list[tuple[int, float]]:
        ids, matrix = self._vectors()
        if not len(ids) or matrix.shape[1] != query_vector.shape[-1]:
            return []
        scores = matrix @ np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if module_ids or types:
            where, params = self._filters(module_ids, types)
            allowed = {int(r[0]) for r in self.conn.execute(
                f"SELECT c.id FROM chunks c WHERE c.vector IS NOT NULL{where}", params)}  # noqa: S608
            mask = np.array([int(i) in allowed for i in ids], dtype=bool)
            scores = np.where(mask, scores, -np.inf)
        order = np.argsort(-scores)[:limit]
        return [(int(ids[i]), float(scores[i])) for i in order if np.isfinite(scores[i])]

    def random_chunks(self, count: int, seed: int) -> list[ChunkRecord]:
        ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE tokens >= 25 ORDER BY id")]
        if not ids:
            return []
        rng = np.random.default_rng(seed)
        picked = rng.choice(ids, size=min(count, len(ids)), replace=False)
        found = self.get_chunks([int(i) for i in picked])
        return [found[int(i)] for i in picked if int(i) in found]
