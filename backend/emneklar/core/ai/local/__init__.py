"""Local models (embedding, reranking, speech-to-text) for Emne-RAG – shared infrastructure in the AI layer.

* Model names live in the versioned catalog ``core/ai/local_models.json``, never in feature code.
* The heavy libraries (sentence-transformers/PyTorch, faster-whisper/CTranslate2) are an optional install
  (``backend[rag]``). Nothing here imports them until a model is actually used, so EmneKlar starts fast and
  works without them.
* Models are downloaded from Hugging Face the first time they are used, into ``<data>/models`` – never a
  folder shared with other programs. Whether a model is already downloaded is checked on disk without
  network access, so the UI can show the download size before the first use.
* CUDA is detected automatically (``device="auto"``); everything also works on CPU.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from emneklar.core.errors import AppError

log = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "local_models.json"
ModelKind = Literal["embedding", "reranker", "whisper", "whisper_other"]
PACKAGES = {"sentence_transformers": "sentence-transformers", "faster_whisper": "faster-whisper",
            "youtube_transcript_api": "youtube-transcript-api", "ctranslate2": "ctranslate2",
            "transformers": "transformers"}


@dataclass(frozen=True)
class LocalModelDef:
    id: str
    kind: ModelKind
    label: str
    size_mb: int
    default: bool = False
    dim: int | None = None
    max_tokens: int | None = None
    size: str | None = None  # whisper size class (tiny … large)
    format: str = "transformers"  # transformers | ct2
    license: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "size_mb": self.size_mb,
                "default": self.default, "dim": self.dim, "max_tokens": self.max_tokens, "size": self.size,
                "format": self.format, "license": self.license, "notes": self.notes}


@cache
def load_catalog() -> tuple[LocalModelDef, ...]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return tuple(LocalModelDef(**m) for m in data["models"])


def catalog_version() -> str:
    return str(json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("version") or "")


@dataclass
class LocalModels:
    """Status and lazy loading of local models. One instance per application (see AppContainer)."""

    models_dir: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _loaded: dict[tuple[str, str, str], Any] = field(default_factory=dict, repr=False)
    _cuda: bool | None = field(default=None, repr=False)
    _cuda_checked: bool = field(default=False, repr=False)

    @property
    def hub_dir(self) -> Path:
        return self.models_dir / "hub"

    @property
    def converted_dir(self) -> Path:
        return self.models_dir / "ct2"

    # -- catalog ---------------------------------------------------------------------------------------

    def catalog(self, kind: ModelKind | None = None) -> list[LocalModelDef]:
        return [m for m in load_catalog() if kind is None or m.kind == kind]

    def model(self, kind: ModelKind, model_id: str = "") -> LocalModelDef:
        """The chosen model, or the catalog default. A model id that is not in the catalog is allowed
        (advanced users); its size is then unknown."""
        options = self.catalog(kind)
        if model_id:
            known = next((m for m in options if m.id == model_id), None)
            return known or LocalModelDef(id=model_id, kind=kind, label=model_id, size_mb=0)
        return next(m for m in options if m.default)

    # -- environment -----------------------------------------------------------------------------------

    def packages(self) -> dict[str, bool]:
        return {name: importlib.util.find_spec(name) is not None for name in PACKAGES}

    def cuda_available(self) -> bool | None:
        """True/False when it could be determined, None when no local runtime is installed."""
        if self._cuda_checked:
            return self._cuda
        self._cuda_checked = True
        try:
            if importlib.util.find_spec("torch") is not None:
                import torch

                self._cuda = bool(torch.cuda.is_available())
            elif importlib.util.find_spec("ctranslate2") is not None:
                import ctranslate2

                self._cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:  # noqa: BLE001 - a broken driver must not break the app
            log.info("Kunne ikke undersøke CUDA – bruker CPU")
            self._cuda = False
        return self._cuda

    def device(self, preference: str = "auto") -> str:
        if preference == "cpu":
            return "cpu"
        if preference == "cuda":
            return "cuda" if self.cuda_available() else "cpu"
        return "cuda" if self.cuda_available() else "cpu"

    def prepare_environment(self) -> None:
        """Point the Hugging Face libraries at EmneKlar's own model folder (before they are imported)."""
        self.models_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(self.models_dir)
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    # -- downloads -------------------------------------------------------------------------------------

    def snapshot_dir(self, model_id: str) -> Path:
        return self.hub_dir / ("models--" + model_id.replace("/", "--")) / "snapshots"

    def is_downloaded(self, model_id: str) -> bool:
        snapshots = self.snapshot_dir(model_id)
        if not snapshots.is_dir():
            return False
        return any(child.is_dir() and any(child.iterdir()) for child in snapshots.iterdir())

    def status(self, preference: str = "auto") -> dict[str, Any]:
        packages = self.packages()
        return {
            "installed": {"embedding": packages["sentence_transformers"], "reranker": packages["sentence_transformers"],
                          "whisper": packages["faster_whisper"], "youtube": packages["youtube_transcript_api"]},
            "device": self.device(preference) if packages["sentence_transformers"] or packages["faster_whisper"]
            else None,
            "cuda": self.cuda_available() if packages["sentence_transformers"] or packages["faster_whisper"] else None,
            "models_dir": str(self.models_dir),
            "catalog_version": catalog_version(),
            "models": [{**m.as_dict(), "downloaded": self.is_downloaded(m.id)} for m in load_catalog()],
        }

    # -- loading (blocking – call from a worker thread) ------------------------------------------------

    def _cached(self, key: tuple[str, str, str], factory: Any) -> Any:
        with self._lock:
            if key not in self._loaded:
                self.prepare_environment()
                log.info("Laster lokal modell %s (%s) på %s", key[1], key[0], key[2])
                self._loaded[key] = factory()
            return self._loaded[key]

    def load_embedder(self, model: LocalModelDef, device: str) -> Any:
        if not self.packages()["sentence_transformers"]:
            raise AppError("rag_local_models_missing", status=409)

        def factory() -> Any:
            from sentence_transformers import SentenceTransformer

            st = SentenceTransformer(model.id, device=device, cache_folder=str(self.hub_dir))
            if model.max_tokens:
                st.max_seq_length = min(model.max_tokens, 1024)  # chunks are short; this bounds memory on CPU
            return st

        return self._cached(("embedding", model.id, device), factory)

    def load_reranker(self, model: LocalModelDef, device: str) -> Any:
        if not self.packages()["sentence_transformers"]:
            raise AppError("rag_local_models_missing", status=409)

        def factory() -> Any:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(model.id, device=device, cache_folder=str(self.hub_dir), max_length=1024)

        return self._cached(("reranker", model.id, device), factory)

    def unload(self) -> None:
        with self._lock:
            self._loaded.clear()
