"""Catalog of transcription models at AI providers (``transcription_models.json``) – no model names in features."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "transcription_models.json"


@dataclass(frozen=True)
class TranscriptionModel:
    id: str
    label: str
    provider_type: str
    segments: bool | None  # None = unknown (tried with timestamps first)
    default: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "provider_type": self.provider_type, "segments": self.segments,
                "default": self.default}


@cache
def catalog() -> tuple[TranscriptionModel, ...]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return tuple(TranscriptionModel(id=m["id"], label=m["label"], provider_type=m["provider_type"],
                                    segments=m.get("segments"), default=bool(m.get("default"))) for m in data["models"])


def resolve(provider_type: str, model_id: str) -> TranscriptionModel | None:
    """The chosen model, or the catalog default for the provider type. None when no model is known or chosen."""
    options = [m for m in catalog() if m.provider_type == provider_type]
    if model_id:
        return next((m for m in options if m.id == model_id), None) or TranscriptionModel(
            id=model_id, label=model_id, provider_type=provider_type, segments=None)
    return next((m for m in options if m.default), None)
