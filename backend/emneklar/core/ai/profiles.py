"""Quality profiles («Maksimal kvalitet», «Balansert», «Rask») – model preferences per role, as data.

A profile lists, per role, models in order of preference (``provider_id/model_id``). Only models that are enabled and
classified in the registry, at a provider that may be used now, are chosen; the first usable one wins and the others
become fallbacks. A model the teacher has made the default or given priority comes before the profile's list when it
is good enough for the role. When none is usable, the router picks one with the profile's fallback strategy, so the
feature keeps working with whatever models the user has set up.

Image models are not listed by name: a profile says what counts (``image.strategy``: quality, speed or the teacher's
default) and the registry's enabled image models are ordered by it (:func:`emneklar.core.ai.catalog.ordered`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from emneklar.core.ai.catalog import ordered, preferred_by_user

PROFILES_PATH = Path(__file__).resolve().parent / "model_profiles.json"


@dataclass(frozen=True)
class QualityProfile:
    id: str
    label: str
    description: str
    default: bool
    fallback_strategy: str
    roles: dict[str, tuple[str, ...]]
    image_strategy: str
    image_quality: str
    review_rounds: int
    page_chars: int
    module_page_chars: int
    course_chars: int
    reference_images: int
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "description": self.description, "default": self.default,
                "fallback_strategy": self.fallback_strategy, "roles": {k: list(v) for k, v in self.roles.items()},
                "image_strategy": self.image_strategy, "image_quality": self.image_quality,
                "review_rounds": self.review_rounds, "reference_images": self.reference_images}


@cache
def data() -> dict[str, Any]:
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


@cache
def profiles() -> tuple[QualityProfile, ...]:
    out = []
    for p in data()["profiles"]:
        out.append(QualityProfile(
            id=p["id"], label=p["label"], description=p["description"], default=bool(p.get("default")),
            fallback_strategy=p.get("fallback_strategy", "auto"),
            roles={k: tuple(v) for k, v in (p.get("roles") or {}).items()},
            image_strategy=str((p.get("image") or {}).get("strategy") or "auto"),
            image_quality=str((p.get("image") or {}).get("quality") or "high"),
            review_rounds=int(p.get("review_rounds", 1)), page_chars=int(p.get("page_chars", 40000)),
            module_page_chars=int(p.get("module_page_chars", 1200)), course_chars=int(p.get("course_chars", 16000)),
            reference_images=int(p.get("reference_images", 2))))
    return tuple(out)


def role_labels() -> dict[str, str]:
    return dict(data().get("roles") or {})


def get(profile_id: str | None) -> QualityProfile:
    items = profiles()
    return next((p for p in items if p.id == profile_id), None) or next((p for p in items if p.default), items[0])


def split(ref: str) -> tuple[str, str]:
    provider_id, _, model_id = (ref or "").partition("/")
    return provider_id, model_id


def usable(models: list[dict[str, Any]], ready: dict[str, bool], ref: str, *, vision: bool) -> dict[str, Any] | None:
    provider_id, model_id = split(ref)
    for m in models:
        if m["provider_id"] == provider_id and m["model_id"] == model_id:
            if not (m["enabled"] and m["capabilities_known"] and ready.get(provider_id)):
                return None
            if m.get("kind", "text") != "text":
                return None
            if vision and not m["vision"]:
                return None
            return m
    return None


def preferred_models(profile: QualityProfile, role: str, models: list[dict[str, Any]], ready: dict[str, bool], *,
                     vision: bool, override: str | None = None, min_quality: int = 1) -> list[dict[str, Any]]:
    """Usable models for a role in order: the user's own choice for the role first, then the models the teacher has
    made the default or given priority (when good enough for the role), then the profile's list."""
    out: list[dict[str, Any]] = []
    chosen = usable(models, ready, override, vision=vision) if override else None
    if chosen is not None:
        out.append(chosen)
    boosted = [m for m in models if preferred_by_user(m) and m["quality_class"] >= min_quality
               and usable(models, ready, f"{m['provider_id']}/{m['model_id']}", vision=vision) is not None]
    for m in ordered(boosted, "auto"):
        if m not in out:
            out.append(m)
    for ref in profile.roles.get(role, ()):
        listed = usable(models, ready, ref, vision=vision)
        if listed is not None and listed not in out:
            out.append(listed)
    return out
