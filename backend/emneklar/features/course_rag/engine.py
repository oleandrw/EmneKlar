"""Glue between Emne-RAG and the shared core: index files, the register in the main database, model choices."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from emneklar.core.ai.local.embedding import (
    Embedder,
    EmbeddingChoice,
    Reranker,
    RerankerChoice,
    embedding_choice,
    open_embedder,
    open_reranker,
    reranker_choice,
)
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import ACTIVE
from emneklar.core.storage.models import RagIndex
from emneklar.features.course_rag.store import IndexStore, index_path

JOB_KIND = "rag_build"


def store_for(c: AppContainer, course_id: str, *, create: bool = True) -> IndexStore:
    return IndexStore(index_path(c.config.rag_dir, course_id), create=create)


def has_index(c: AppContainer, course_id: str) -> bool:
    return index_path(c.config.rag_dir, course_id).exists()


def busy_job(c: AppContainer, course_id: str) -> str | None:
    for job in c.jobs.list(course_id=course_id, active_only=True):
        if job.kind == JOB_KIND and job.status in ACTIVE:
            return job.id
    return None


def registry(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    with c.db.session() as session:
        row = session.get(RagIndex, course_id)
        if row is None:
            return None
        return {"course_id": row.course_id, "status": row.status, "options": row.options, "embedding": row.embedding,
                "stats": row.stats, "skipped": row.skipped, "limitations": row.limitations,
                "evaluation": row.evaluation, "last_job_id": row.last_job_id,
                "built_at": row.built_at.isoformat() if row.built_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def update_registry(c: AppContainer, course_id: str, **fields: Any) -> None:
    with c.db.session() as session:
        row = session.get(RagIndex, course_id)
        if row is None:
            row = RagIndex(course_id=course_id)
            session.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)


def delete_index(c: AppContainer, course_id: str) -> None:
    if busy_job(c, course_id):
        raise AppError("rag_index_busy", status=409)
    path = index_path(c.config.rag_dir, course_id)
    IndexStore._vector_cache.pop(str(path), None)
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists():
            candidate.unlink()
    with c.db.session() as session:
        row = session.get(RagIndex, course_id)
        if row is not None:
            session.delete(row)


def choices(c: AppContainer) -> tuple[EmbeddingChoice, RerankerChoice, str]:
    settings = c.settings.get()
    local = c.local_models
    embedding = embedding_choice(settings, local, c.ai)
    reranker = reranker_choice(settings, local)
    device = local.device(settings.rag.device) if (embedding.backend == "local" and embedding.available) or \
        reranker.available else "cpu"
    return embedding, reranker, device


async def load_search_models(c: AppContainer, *, course_id: str, confirmed: bool,
                             allow_download: bool = False) -> tuple[Embedder | None, Reranker | None, list[str]]:
    """Models for answering a query. Never downloads silently: a missing local model is skipped with a note."""
    embedding, reranker_def, device = choices(c)
    notes: list[str] = []
    embedder: Embedder | None = None
    if embedding.available and (allow_download or not embedding.needs_download):
        embedder = await open_embedder(embedding, c.local_models, c.ai, device=device, confirmed=confirmed,
                                       course_id=course_id)
    elif embedding.available:
        notes.append("Embedding-modellen er ikke lastet ned ennå. Bare nøkkelordsøk er brukt.")
    reranker: Reranker | None = None
    if reranker_def.available and (allow_download or not reranker_def.needs_download):
        reranker = await open_reranker(reranker_def, c.local_models, device=device)
    elif reranker_def.available:
        notes.append("Rerangeringsmodellen er ikke lastet ned ennå. Treffene er sortert med RRF.")
    return embedder, reranker, notes
