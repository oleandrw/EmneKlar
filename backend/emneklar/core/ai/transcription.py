"""Transcription models at AI providers as features see them – built from the model registry.

Transcription is a kind of model in the registry (``ai_models.kind == "transcription"``,
:mod:`emneklar.core.ai.catalog`). ``segments`` says whether the model gives timestamps per sentence; None = unknown
(tried with timestamps first).
"""

from __future__ import annotations

from typing import Any

from emneklar.core.ai.catalog import load_catalog

#: Providers where the model is a name the user decides (an Azure deployment, a model on an own server).
NAMED_PROVIDER_TYPES = ("azure_openai", "openai_compatible")


def note() -> str:
    return str(load_catalog().get("transcription_note") or "")


def describe(row: dict[str, Any] | None, *, model_id: str = "", provider_type: str = "") -> dict[str, Any]:
    name = model_id or (row["model_id"] if row else "")
    return {"id": name, "label": (row["display_name"] if row else name) or name,
            "provider_id": row["provider_id"] if row else "", "provider_type": provider_type,
            "segments": row["params"].get("segments") if row else None,
            "default": bool(row.get("is_default")) if row else False}
