"""Text embeddings and reranking for Emne-RAG.

Three ways to embed, chosen under Emne-RAG → Innstillinger:

* ``local`` – a sentence-transformers model on this machine (default BGE-M3; nothing leaves the machine);
* ``provider`` – an OpenAI-compatible embeddings endpoint through :class:`AIService` (OpenAI, Azure OpenAI, or a
  local server such as Ollama). External providers go through the privacy gate like every other AI call;
* ``none`` – no vectors: search is keyword-only (BM25). The UI says so.

The model identity (``local:BAAI/bge-m3``, ``provider:local/bge-m3``) is stored in every index, so a changed model
is detected and the index must be re-indexed (vectors from different models cannot be compared).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from emneklar.core.ai.local import LocalModelDef, LocalModels
from emneklar.core.storage.settings import AppSettings

if TYPE_CHECKING:
    from emneklar.core.ai.service import AIService

PROVIDER_BATCH = 64
LOCAL_BATCH = 16


class Embedder(Protocol):
    identity: str  # stored in the index, e.g. "local:BAAI/bge-m3"

    async def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    async def embed_query(self, text: str) -> np.ndarray: ...


class Reranker(Protocol):
    identity: str

    async def score(self, query: str, passages: list[str]) -> list[float]: ...


def normalise(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass
class EmbeddingChoice:
    backend: str  # local | provider | none
    identity: str | None  # what the index stores; None = no vectors
    label: str
    available: bool
    reason: str | None = None
    needs_download: bool = False
    download_mb: int = 0
    external: bool = False
    needs_confirmation: bool = False
    model: LocalModelDef | None = None
    provider_id: str | None = None
    provider_model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "identity": self.identity, "label": self.label, "available": self.available,
                "reason": self.reason, "needs_download": self.needs_download, "download_mb": self.download_mb,
                "external": self.external, "needs_confirmation": self.needs_confirmation}


def embedding_choice(settings: AppSettings, local: LocalModels, ai: AIService | None) -> EmbeddingChoice:
    rag = settings.rag
    if rag.embedding_backend == "none":
        return EmbeddingChoice("none", None, "Bare nøkkelordsøk (BM25)", False,
                               "Semantisk søk er slått av under Emne-RAG → Innstillinger. Søket bruker bare nøkkelord.")
    if rag.embedding_backend == "provider":
        provider_id, provider_model = rag.embedding_provider_id, rag.embedding_provider_model
        label = f"{provider_model or '(ingen modell)'} hos {provider_id}"
        if ai is None:
            return EmbeddingChoice("provider", None, label, False, "KI-tjenesten er ikke tilgjengelig.")
        plan = ai.embedding_plan(provider_id, provider_model, summary="")
        return EmbeddingChoice("provider", f"provider:{provider_id}/{provider_model}", label, bool(plan["available"]),
                               plan["reason"], external=bool(plan["external"]),
                               needs_confirmation=bool(plan["needs_confirmation"]), provider_id=provider_id,
                               provider_model=provider_model)
    model = local.model("embedding", rag.embedding_model)
    if not local.packages()["sentence_transformers"]:
        return EmbeddingChoice("local", f"local:{model.id}", model.label, False,
                               "Lokale modeller er ikke installert. Søket bruker bare nøkkelord til de er installert "
                               "(lukk EmneKlar og kjør setup-emne-rag.bat).", model=model)
    downloaded = local.is_downloaded(model.id)
    return EmbeddingChoice("local", f"local:{model.id}", model.label, True, None, needs_download=not downloaded,
                           download_mb=0 if downloaded else model.size_mb, model=model)


class LocalEmbedder:
    def __init__(self, model: Any, identity: str) -> None:
        self._model = model
        self.identity = identity
        self._lock = threading.Lock()

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vectors = self._model.encode(texts, batch_size=LOCAL_BATCH, show_progress_bar=False, convert_to_numpy=True,
                                         normalize_embeddings=True)
        return normalise(vectors)

    async def embed_documents(self, texts: list[str]) -> np.ndarray:
        return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, text: str) -> np.ndarray:
        return (await asyncio.to_thread(self._encode, [text]))[0]


class ProviderEmbedder:
    def __init__(self, ai: AIService, provider_id: str, model: str, *, confirmed: bool, course_id: str | None) -> None:
        self._ai = ai
        self._provider_id = provider_id
        self._model = model
        self._confirmed = confirmed
        self._course_id = course_id
        self.identity = f"provider:{provider_id}/{model}"

    async def _embed(self, texts: list[str], summary: str) -> np.ndarray:
        rows: list[list[float]] = []
        for start in range(0, len(texts), PROVIDER_BATCH):
            batch = texts[start:start + PROVIDER_BATCH]
            result = await self._ai.embed(self._provider_id, self._model, batch, summary=summary,
                                          confirmed=self._confirmed, course_id=self._course_id)
            rows.extend(result.vectors)
        return normalise(np.array(rows, dtype=np.float32))

    async def embed_documents(self, texts: list[str]) -> np.ndarray:
        return await self._embed(texts, f"{len(texts)} utdrag fra emnet (lærerinnhold) for embedding")

    async def embed_query(self, text: str) -> np.ndarray:
        return (await self._embed([text], "1 søk (spørsmålet) for embedding"))[0]


class LocalReranker:
    def __init__(self, model: Any, identity: str) -> None:
        self._model = model
        self.identity = identity
        self._lock = threading.Lock()

    def _predict(self, query: str, passages: list[str]) -> list[float]:
        with self._lock:
            scores = self._model.predict([(query, p) for p in passages], batch_size=LOCAL_BATCH, show_progress_bar=False)
        return [float(s) for s in np.asarray(scores).reshape(-1)]

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return await asyncio.to_thread(self._predict, query, passages)


async def open_embedder(choice: EmbeddingChoice, local: LocalModels, ai: AIService | None, *, device: str,
                        confirmed: bool, course_id: str | None) -> Embedder | None:
    """Load the chosen embedder (downloads the model the first time). ``None`` when no vectors are used."""
    if not choice.available or choice.identity is None:
        return None
    if choice.backend == "provider":
        assert ai is not None and choice.provider_id is not None and choice.provider_model is not None
        return ProviderEmbedder(ai, choice.provider_id, choice.provider_model, confirmed=confirmed, course_id=course_id)
    assert choice.model is not None
    model = await asyncio.to_thread(local.load_embedder, choice.model, device)
    return LocalEmbedder(model, choice.identity)


@dataclass
class RerankerChoice:
    available: bool
    label: str
    reason: str | None = None
    needs_download: bool = False
    download_mb: int = 0
    model: LocalModelDef | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "label": self.label, "reason": self.reason,
                "needs_download": self.needs_download, "download_mb": self.download_mb}


def reranker_choice(settings: AppSettings, local: LocalModels) -> RerankerChoice:
    model = local.model("reranker", settings.rag.reranker_model)
    if not settings.rag.reranker_enabled:
        return RerankerChoice(False, model.label, "Rerangering er slått av. Treffene sorteres med RRF.")
    if not local.packages()["sentence_transformers"]:
        return RerankerChoice(False, model.label, "Lokale modeller er ikke installert. Treffene sorteres med RRF.")
    downloaded = local.is_downloaded(model.id)
    return RerankerChoice(True, model.label, needs_download=not downloaded, download_mb=0 if downloaded else model.size_mb,
                          model=model)


async def open_reranker(choice: RerankerChoice, local: LocalModels, *, device: str) -> Reranker | None:
    if not choice.available or choice.model is None:
        return None
    model = await asyncio.to_thread(local.load_reranker, choice.model, device)
    return LocalReranker(model, f"local:{choice.model.id}")
