"""Model capability registry (table ``ai_models``).

Seeded from ``model_catalog.json`` (dated, curated). The user can change every
value. Models found via provider discovery are added *disabled* with unknown
quality/speed/cost – they are never used until the user classifies them,
because model-list endpoints do not tell what a model is good at or costs.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from emneklar.core.ai.base import DiscoveredModel
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import AIModel

CATALOG_PATH = Path(__file__).parent / "model_catalog.json"
CLASS_FIELDS = {"context_class": (1, 4), "quality_class": (1, 4), "speed_class": (1, 3), "cost_class": (0, 4)}
EDITABLE = {"display_name", "text", "vision", "structured_output", "enabled", "notes", *CLASS_FIELDS}


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def model_dict(m: AIModel) -> dict[str, Any]:
    return {"id": m.id, "provider_id": m.provider_id, "model_id": m.model_id, "display_name": m.display_name or m.model_id,
            "text": m.text, "vision": m.vision, "structured_output": m.structured_output,
            "context_class": m.context_class, "quality_class": m.quality_class, "speed_class": m.speed_class,
            "cost_class": m.cost_class, "enabled": m.enabled, "source": m.source,
            "capabilities_known": m.capabilities_known, "notes": m.notes}


def context_class_from_tokens(tokens: int | None) -> int:
    if not tokens:
        return 1
    if tokens <= 32_000:
        return 1
    if tokens <= 130_000:
        return 2
    if tokens <= 400_000:
        return 3
    return 4


class ModelRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_seeded(self) -> int:
        catalog = load_catalog()
        added = 0
        with self.db.session() as session:
            existing = {(m.provider_id, m.model_id) for m in session.scalars(select(AIModel)).all()}
            for entry in catalog["models"]:
                key = (entry["provider"], entry["model_id"])
                if key in existing:
                    continue
                session.add(AIModel(provider_id=entry["provider"], model_id=entry["model_id"],
                                    display_name=entry["display_name"], text=True, vision=entry["vision"],
                                    structured_output=entry["structured_output"],
                                    context_class=entry["context_class"], quality_class=entry["quality_class"],
                                    speed_class=entry["speed_class"], cost_class=entry["cost_class"], enabled=True,
                                    source="catalog", capabilities_known=True,
                                    notes=f"Fra startlisten {catalog['version']}"))
                added += 1
        return added

    def list(self, provider_id: str | None = None) -> list[dict[str, Any]]:
        self.ensure_seeded()
        with self.db.session() as session:
            query = select(AIModel).order_by(AIModel.provider_id, AIModel.quality_class, AIModel.model_id)
            if provider_id:
                query = query.where(AIModel.provider_id == provider_id)
            return [model_dict(m) for m in session.scalars(query).all()]

    def _validate(self, fields: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in fields.items() if k in EDITABLE}
        for key, (low, high) in CLASS_FIELDS.items():
            if key in clean and not (isinstance(clean[key], int) and low <= clean[key] <= high):
                raise AppError("validation_error", detail=f"{key} må være mellom {low} og {high}")
        return clean

    def update(self, model_pk: int, fields: dict[str, Any]) -> dict[str, Any]:
        clean = self._validate(fields)
        with self.db.session() as session:
            row = session.get(AIModel, model_pk)
            if row is None:
                raise NotFoundError("not_found", detail="modell")
            for key, value in clean.items():
                setattr(row, key, value)
            if set(clean) & set(CLASS_FIELDS):
                row.capabilities_known = True
            return model_dict(row)

    def add(self, provider_id: str, model_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        model_id = model_id.strip()
        if not model_id or len(model_id) > 200:
            raise AppError("validation_error", detail="Ugyldig modellnavn")
        clean = self._validate(fields)
        with self.db.session() as session:
            if session.scalars(select(AIModel).where(AIModel.provider_id == provider_id,
                                                     AIModel.model_id == model_id)).first():
                raise AppError("conflict", status=409, detail="Modellen finnes allerede")
            row = AIModel(provider_id=provider_id, model_id=model_id, display_name=clean.pop("display_name", model_id),
                          source="user", capabilities_known=True, enabled=clean.pop("enabled", True), **clean)
            session.add(row)
            session.flush()
            return model_dict(row)

    def delete(self, model_pk: int) -> None:
        with self.db.session() as session:
            row = session.get(AIModel, model_pk)
            if row is None:
                raise NotFoundError("not_found")
            if row.source == "catalog":
                raise AppError("conflict", status=409, message="Modeller fra startlisten kan slås av, men ikke slettes.")
            session.delete(row)

    def merge_discovered(self, provider_id: str, models: builtins.list[DiscoveredModel], *, local: bool) -> int:
        added = 0
        with self.db.session() as session:
            existing = {m.model_id for m in session.scalars(select(AIModel).where(AIModel.provider_id == provider_id))}
            for model in models:
                if model.id in existing:
                    continue
                session.add(AIModel(
                    provider_id=provider_id, model_id=model.id, display_name=model.name, text=True,
                    vision=bool(model.vision), structured_output=bool(model.structured_output),
                    context_class=context_class_from_tokens(model.context_tokens), quality_class=1, speed_class=2,
                    cost_class=0 if local else 2, enabled=False, source="discovered", capabilities_known=False,
                    notes="Hentet fra leverandøren. Angi kvalitet, hastighet og kostnad før modellen kan brukes."))
                added += 1
        return added
