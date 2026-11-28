"""The model registry (table ``ai_models``) – the one source of truth for AI models in EmneKlar.

Every model a feature can use is a row here: text models (the router), image generation models (KI-bildeassistent),
transcription models and embedding models at a provider (Emnets kunnskapsbase). A row says what the model is
(``kind``), what it can do (capabilities), which request parameters it supports (``params``), how it is classified
(quality, speed, cost, context), whether it is enabled, and the teacher's own preference (``priority``,
``is_default``). Model selectors and automatic choices read only this registry.

Seeded from ``model_catalog.json`` (dated, curated, checked against the providers' documentation). The user can change
every value. Models found via provider discovery are added *disabled* with unknown quality/speed/cost – they are never
used until the user classifies them, because model-list endpoints do not tell what a model is good at or costs. The
kind of a discovered model is only *suggested* from its name (``kind_hints``); nothing is assumed from a version number.
"""

from __future__ import annotations

import builtins
import json
import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from sqlalchemy import select

from emneklar.core.ai.base import DiscoveredModel
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import AIModel

CATALOG_PATH = Path(__file__).parent / "model_catalog.json"
CLASS_FIELDS = {"context_class": (1, 4), "quality_class": (1, 4), "speed_class": (1, 3), "cost_class": (0, 4)}
EDITABLE = {"display_name", "text", "vision", "structured_output", "enabled", "notes", "kind", "priority", "is_default",
            "description", "params", *CLASS_FIELDS}
#: What a model is. A model has one kind; what it can do within the kind are its capabilities.
KIND_LABELS = {"text": "Tekst", "image": "Bildegenerering", "transcription": "Transkripsjon", "embedding": "Embedding"}
CAPABILITY_LABELS = {"text": "Tekst", "vision": "Bildeanalyse", "structured_output": "Strukturert svar",
                     "image_generation": "Bildegenerering", "reference_images": "Referansebilder",
                     "transcription": "Transkripsjon", "timestamps": "Tidsstempler per setning",
                     "embedding": "Embedding"}
MAX_PRIORITY = 3
IMAGE_QUALITIES = ("low", "medium", "high", "xhigh", "max")
IMAGE_COMPLEXITIES = ("low", "medium", "high")
STANDARD_SIZES = ("1536x1024", "1024x1024", "1024x1536")
ASPECT_RATIOS = ("16:9", "3:2", "4:3", "1:1", "2:3")
_SIZE = re.compile(r"^\d{2,5}x\d{2,5}$")
#: A model whose parameters nobody has described (a typed deployment name, a model added by hand): only what every
#: OpenAI-compatible image API has – standard sizes, low/medium/high, no reference images.
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "text": {},
    "embedding": {},
    "transcription": {"segments": None},
    "image": {"qualities": ["low", "medium", "high"], "sizes": list(STANDARD_SIZES), "aspect_sizes": {},
              "reference_images": False, "max_reference_images": 0, "complexities": [], "input_fidelity": False},
}


def load_catalog() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data


def suggested_kind(model_id: str, catalog: dict[str, Any] | None = None) -> str:
    """The kind a model's name suggests (``kind_hints``), ``text`` when nothing matches. A suggestion for the
    classification dialog – a discovered model stays switched off until the teacher has classified it."""
    name = model_id.lower()
    for hint in (catalog or load_catalog()).get("kind_hints") or []:
        if fnmatchcase(name, str(hint["pattern"]).lower()) and hint.get("kind") in KIND_LABELS:
            return str(hint["kind"])
    return "text"


def clean_params(kind: str, raw: Any) -> dict[str, Any]:
    """The parameters a model of ``kind`` supports, with unknown keys dropped and invalid values refused."""
    base = dict(DEFAULT_PARAMS.get(kind, {}))
    if not isinstance(raw, dict):
        return base
    if kind == "transcription":
        segments = raw.get("segments", base["segments"])
        if segments is not None and not isinstance(segments, bool):
            raise AppError("validation_error", detail="segments må være sann, usann eller ukjent")
        return {"segments": segments}
    if kind != "image":
        return base

    def chosen(key: str, allowed: Iterable[str]) -> builtins.list[str]:
        values = raw.get(key, base[key])
        allowed = tuple(allowed)
        if not isinstance(values, builtins.list) or any(v not in allowed for v in values):
            raise AppError("validation_error", detail=f"Ugyldig verdi i {key}")
        return [v for v in allowed if v in values]  # canonical order, no duplicates

    out = dict(base)
    out["qualities"] = chosen("qualities", IMAGE_QUALITIES) or list(base["qualities"])
    out["complexities"] = chosen("complexities", IMAGE_COMPLEXITIES)
    sizes = raw.get("sizes", base["sizes"])
    if not isinstance(sizes, builtins.list) or not sizes or any(not _SIZE.match(str(s)) for s in sizes):
        raise AppError("validation_error", detail="Ugyldig bildestørrelse")
    out["sizes"] = [str(s) for s in sizes][:12]
    aspects = raw.get("aspect_sizes", base["aspect_sizes"])
    if not isinstance(aspects, dict) or any(k not in ASPECT_RATIOS or not _SIZE.match(str(v))
                                           for k, v in aspects.items()):
        raise AppError("validation_error", detail="Ugyldig størrelse for et bildeformat")
    out["aspect_sizes"] = {k: str(aspects[k]) for k in ASPECT_RATIOS if k in aspects}
    out["reference_images"] = bool(raw.get("reference_images", base["reference_images"]))
    count = raw.get("max_reference_images", base["max_reference_images"])
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 16:
        raise AppError("validation_error", detail="Antall referansebilder må være mellom 0 og 16")
    out["max_reference_images"] = (count or 1) if out["reference_images"] else 0
    out["input_fidelity"] = bool(raw.get("input_fidelity", base["input_fidelity"]))
    return out


def capabilities(kind: str, *, vision: bool = False, structured_output: bool = False,
                 params: dict[str, Any] | None = None) -> builtins.list[str]:
    params = params or {}
    if kind == "image":
        return ["image_generation", *(["reference_images"] if params.get("reference_images") else [])]
    if kind == "transcription":
        return ["transcription", *(["timestamps"] if params.get("segments") else [])]
    if kind == "embedding":
        return ["embedding"]
    return ["text", *(["vision"] if vision else []), *(["structured_output"] if structured_output else [])]


def model_dict(m: AIModel) -> dict[str, Any]:
    kind = m.kind if m.kind in KIND_LABELS else "text"
    try:
        params = clean_params(kind, m.params)
    except AppError:  # a stored value from an older version: fall back to what every model of the kind supports
        params = dict(DEFAULT_PARAMS[kind])
    return {"id": m.id, "provider_id": m.provider_id, "model_id": m.model_id, "display_name": m.display_name or m.model_id,
            "ref": f"{m.provider_id}/{m.model_id}", "kind": kind, "kind_label": KIND_LABELS[kind],
            "text": kind == "text", "vision": m.vision, "structured_output": m.structured_output,
            "capabilities": capabilities(kind, vision=m.vision, structured_output=m.structured_output, params=params),
            "params": params, "description": m.description or "",
            "context_class": m.context_class, "quality_class": m.quality_class, "speed_class": m.speed_class,
            "cost_class": m.cost_class, "priority": m.priority or 0, "is_default": bool(m.is_default),
            "enabled": m.enabled, "source": m.source,
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


def preference(m: dict[str, Any]) -> tuple[int, int]:
    """The teacher's own preference: the default model of its kind first, then higher priority. Sorts ascending."""
    return (0 if m.get("is_default") else 1, -int(m.get("priority") or 0))


def preferred_by_user(m: dict[str, Any]) -> bool:
    return bool(m.get("is_default")) or int(m.get("priority") or 0) > 0


def ordered(models: Iterable[dict[str, Any]], strategy: str = "auto") -> builtins.list[dict[str, Any]]:
    """Models of one kind in the order an automatic choice tries them. The strategy decides what counts first
    (``quality``, ``speed``, ``low_cost``); within it – and for ``auto`` before anything else – the teacher's default
    and priority decide, then the classes. Never the version number in a model's name."""
    def quality(m: dict[str, Any]) -> int:
        return -int(m.get("quality_class") or 0)

    def speed(m: dict[str, Any]) -> int:
        return -int(m.get("speed_class") or 0)

    def cost(m: dict[str, Any]) -> int:
        return int(m.get("cost_class") or 0)

    keys = {
        "quality": lambda m: (quality(m), *preference(m), cost(m), m.get("id") or 0),
        "speed": lambda m: (speed(m), *preference(m), cost(m), m.get("id") or 0),
        "low_cost": lambda m: (cost(m), *preference(m), quality(m), m.get("id") or 0),
        "auto": lambda m: (*preference(m), quality(m), cost(m), m.get("id") or 0),
    }
    return sorted(models, key=keys.get(strategy, keys["auto"]))


def usable(models: Iterable[dict[str, Any]], *, kind: str | None = None, provider_id: str | None = None,
           requires: Iterable[str] = (), ready: dict[str, bool] | None = None) -> builtins.list[dict[str, Any]]:
    """The models a selector or an automatic choice may offer: enabled, classified, of the right kind, with every
    required capability – and, with ``ready``, at a provider that may be used now."""
    needed = set(requires)
    return [m for m in models
            if m["enabled"] and m["capabilities_known"]
            and (kind is None or m.get("kind", "text") == kind)
            and (provider_id is None or m["provider_id"] == provider_id)
            and needed <= set(m.get("capabilities") or ())
            and (ready is None or ready.get(m["provider_id"]))]


class ModelRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_seeded(self) -> int:
        """Add catalog models that are missing. A model the teacher (or discovery) added before it came into the
        catalog is adopted: it gets the catalog's kind, parameters and classes. A model the teacher has classified
        keeps its on/off switch. An unclassified discovery was off only because nobody had looked at it – and image
        and transcription models were used from their own lists whatever that switch said – so it is switched on,
        as a newly seeded catalog model is: an update must not take away a model that worked before it."""
        catalog = load_catalog()
        added = 0
        with self.db.session() as session:
            rows = {(m.provider_id, m.model_id): m for m in session.scalars(select(AIModel)).all()}
            defaults = {m.kind for m in rows.values() if m.is_default}
            for entry in catalog["models"]:
                kind = entry.get("kind", "text")
                key = (entry["provider"], entry["model_id"])
                row = rows.get(key)
                values = {"display_name": entry["display_name"], "kind": kind, "text": kind == "text",
                          "vision": bool(entry.get("vision")), "structured_output": bool(entry.get("structured_output")),
                          "context_class": entry.get("context_class", 1), "quality_class": entry["quality_class"],
                          "speed_class": entry["speed_class"], "cost_class": entry["cost_class"],
                          "description": entry.get("description", ""), "params": clean_params(kind, entry.get("params")),
                          "source": "catalog", "capabilities_known": True,
                          "notes": f"Fra startlisten {catalog['version']}"}
                if row is None:
                    is_default = bool(entry.get("default")) and kind not in defaults
                    session.add(AIModel(provider_id=key[0], model_id=key[1], enabled=True, is_default=is_default,
                                        **values))
                    if is_default:
                        defaults.add(kind)
                    added += 1
                elif row.source != "catalog" and kind != "text" and not row.params:
                    if not row.capabilities_known:
                        row.enabled = True
                    if entry.get("default") and kind not in defaults and row.enabled:
                        row.is_default = True
                        defaults.add(kind)
                    for name, value in values.items():
                        setattr(row, name, value)
        return added

    def list(self, provider_id: str | None = None, *, kind: str | None = None) -> list[dict[str, Any]]:
        self.ensure_seeded()
        with self.db.session() as session:
            query = select(AIModel).order_by(AIModel.provider_id, AIModel.quality_class, AIModel.model_id)
            if provider_id:
                query = query.where(AIModel.provider_id == provider_id)
            if kind:
                query = query.where(AIModel.kind == kind)
            return [model_dict(m) for m in session.scalars(query).all()]

    def usable(self, *, kind: str | None = None, provider_id: str | None = None, requires: Iterable[str] = (),
               ready: dict[str, bool] | None = None) -> builtins.list[dict[str, Any]]:
        return usable(self.list(), kind=kind, provider_id=provider_id, requires=requires, ready=ready)

    def _validate(self, fields: dict[str, Any], *, kind: str) -> dict[str, Any]:
        clean = {k: v for k, v in fields.items() if k in EDITABLE}
        for key, (low, high) in CLASS_FIELDS.items():
            if key in clean and not (isinstance(clean[key], int) and low <= clean[key] <= high):
                raise AppError("validation_error", detail=f"{key} må være mellom {low} og {high}")
        if "kind" in clean and clean["kind"] not in KIND_LABELS:
            raise AppError("validation_error", detail="Ukjent modelltype")
        if "priority" in clean and not (isinstance(clean["priority"], int) and 0 <= clean["priority"] <= MAX_PRIORITY):
            raise AppError("validation_error", detail=f"Prioritet må være mellom 0 og {MAX_PRIORITY}")
        final = clean.get("kind", kind)
        if "params" in clean:
            clean["params"] = clean_params(final, clean["params"])
        elif final != kind:
            clean["params"] = clean_params(final, None)  # a reclassified model starts with the new kind's defaults
        if "kind" in clean:
            clean["text"] = final == "text"
        return clean

    @staticmethod
    def _one_default(session: Any, row: AIModel) -> None:
        """One default model per kind: choosing a new one takes the mark from the previous."""
        for other in session.scalars(select(AIModel).where(AIModel.kind == row.kind, AIModel.is_default.is_(True))):
            if other is not row:
                other.is_default = False

    def update(self, model_pk: int, fields: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(AIModel, model_pk)
            if row is None:
                raise NotFoundError("not_found", detail="modell")
            clean = self._validate(fields, kind=row.kind)
            for key, value in clean.items():
                setattr(row, key, value)
            if set(clean) & (set(CLASS_FIELDS) | {"kind"}):
                row.capabilities_known = True
            if row.is_default and {"is_default", "kind"} & set(clean):
                self._one_default(session, row)
            return model_dict(row)

    def add(self, provider_id: str, model_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        model_id = model_id.strip()
        if not model_id or len(model_id) > 200:
            raise AppError("validation_error", detail="Ugyldig modellnavn")
        kind = fields.get("kind") or "text"
        clean = self._validate({**fields, "kind": kind}, kind=kind)
        clean.setdefault("params", clean_params(kind, None))
        with self.db.session() as session:
            if session.scalars(select(AIModel).where(AIModel.provider_id == provider_id,
                                                     AIModel.model_id == model_id)).first():
                raise AppError("conflict", status=409, detail="Modellen finnes allerede")
            row = AIModel(provider_id=provider_id, model_id=model_id, display_name=clean.pop("display_name", model_id),
                          source="user", capabilities_known=True, enabled=clean.pop("enabled", True), **clean)
            session.add(row)
            session.flush()
            if row.is_default:
                self._one_default(session, row)
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
        catalog = load_catalog()
        with self.db.session() as session:
            existing = {m.model_id for m in session.scalars(select(AIModel).where(AIModel.provider_id == provider_id))}
            for model in models:
                if model.id in existing:
                    continue
                kind = suggested_kind(model.id, catalog)
                session.add(AIModel(
                    provider_id=provider_id, model_id=model.id, display_name=model.name, kind=kind,
                    text=kind == "text", vision=bool(model.vision) and kind == "text",
                    structured_output=bool(model.structured_output) and kind == "text",
                    context_class=context_class_from_tokens(model.context_tokens), quality_class=1, speed_class=2,
                    cost_class=0 if local else 2, enabled=False, source="discovered", capabilities_known=False,
                    params=clean_params(kind, None),
                    notes="Hentet fra leverandøren. Angi type, kvalitet, hastighet og kostnad før modellen kan "
                          "brukes."))
                added += 1
        return added
