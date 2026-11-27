"""Course design profiles: one visual universe for every illustration in a course – versioned.

A profile is one **prompt**: the whole style description, written by the teacher (or pasted from another tool) or
taken from a ready-made profile in ``styles.json``. Consistency comes from three things together:

1. the same prompt in every image prompt (:func:`style_block`); ``{tema}`` in the prompt is where the topic of the
   image is put – without it the topic comes before the prompt;
2. approved images of the course used as **reference images** when the image model supports them (the OpenAI Image
   API takes them in ``/images/edits``), so new images inherit the look;
3. a visual check of every new image against the profile and a reference image (review step).

Every saved change creates a new version; a run records which version it used, so later modules can continue the
same style, and a changed style is visible.

Until 0.2.0-alpha.2 a profile was a set of fields (style, palette, lighting …) and there were seven ready-made styles.
A profile saved then is read as «Egendefinert» with the same description as one prompt (:func:`legacy_prompt`);
nothing in the database is rewritten.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import IllustrationProfile

STYLES_PATH = Path(__file__).resolve().parent / "styles.json"
#: «auto» = the planner picks the best format for each illustration; the others fix the format for the course.
ASPECT_CHOICES = ("auto", "16:9", "3:2", "4:3", "1:1", "2:3")
MAX_REFERENCES = 4
MAX_PROMPT = 8000
#: Where the topic of the image is put into the prompt of a profile.
TOPIC_SLOT = "{tema}"
CUSTOM = "custom"


@cache
def styles() -> list[dict[str, Any]]:
    return list(json.loads(STYLES_PATH.read_text(encoding="utf-8"))["styles"])


def style(key: str) -> dict[str, Any]:
    return next((s for s in styles() if s["key"] == key), styles()[-1])


def default_style() -> str:
    """The profile a course gets until the teacher chooses: the first ready-made one."""
    return str(styles()[0]["key"])


def ready_made() -> set[str]:
    """The styles that carry their own prompt (everything except «Egendefinert»)."""
    return {str(s["key"]) for s in styles() if str(s.get("prompt") or "").strip()}


_LEGACY_TRAITS = (("Contrast", "contrast"), ("Lighting", "lighting"), ("Composition", "composition"),
                  ("Background", "background"), ("Level of detail", "detail_level"),
                  ("Recurring visual traits", "visual_traits"), ("People", "people"))


def legacy_prompt(raw: dict[str, Any]) -> str:
    """One prompt that says what a profile from before 0.2.0-alpha.3 said with its separate fields."""
    def text(key: str) -> str:
        return str(raw.get(key) or "").strip()

    parts: list[str] = []
    if text("illustration_style"):
        parts.append(f"Visual style: {text('illustration_style')}.")
    palette = [str(v).strip() for v in raw.get("palette") or [] if str(v).strip()]
    if palette:
        parts.append(f"Colour palette: {', '.join(palette)}"
                     + (f" ({text('palette_description')})." if text("palette_description") else "."))
    parts += [f"{label}: {text(key)}." for label, key in _LEGACY_TRAITS if text(key)]
    avoid = [str(v).strip() for v in raw.get("avoid") or [] if str(v).strip()]
    if parts and avoid:
        parts.append(f"Never include: {', '.join(dict.fromkeys(avoid))}.")
    return "\n".join(parts)


class DesignData(BaseModel):
    style_key: str = CUSTOM
    name: str = Field("", max_length=200)
    rationale: str = Field("", max_length=2000)
    prompt: str = Field("", max_length=MAX_PROMPT)
    aspect_ratio: str = "auto"

    @model_validator(mode="before")
    @classmethod
    def _earlier_profile(cls, value: Any) -> Any:
        """A style that no longer exists is «Egendefinert», and its fields become the prompt."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("style_key") not in {s["key"] for s in styles()}:
            data["style_key"] = CUSTOM
        if data["style_key"] == CUSTOM and not str(data.get("prompt") or "").strip():
            data["prompt"] = legacy_prompt(data)[:MAX_PROMPT]
        return data

    @field_validator("aspect_ratio")
    @classmethod
    def _ratio(cls, value: str) -> str:
        if value not in ASPECT_CHOICES:
            raise ValueError("Ukjent bildeformat")
        return value


def from_style(key: str) -> DesignData:
    base = style(key)
    return DesignData(style_key=base["key"], name=base["label"], prompt=str(base.get("prompt") or ""),
                      aspect_ratio=str(base.get("aspect_ratio") or "auto"))


def has_topic_slot(data: DesignData) -> bool:
    return TOPIC_SLOT in data.prompt


def style_block(data: DesignData, *, version: int | None = None, labels: bool = False, topic: str = "") -> str:
    """The profile's prompt as it is added to every image prompt, with ``topic`` where the prompt asks for it."""
    prompt = data.prompt.strip()
    if not prompt:
        return ""
    head = (f"Visual style (course design profile{f' v{version}' if version else ''}, keep consistent across all "
            "images of the course):")
    tail = "Same visual universe as the other illustrations of the course, but a distinct motif – not a copy."
    if labels:
        tail += (" The short labels listed below must appear as text, even where the style description prefers an "
                 "image without text.")
    return f"{head}\n{prompt.replace(TOPIC_SLOT, topic.strip())}\n\n{tail}"


def profile_dict(row: IllustrationProfile) -> dict[str, Any]:
    data = DesignData.model_validate(row.data or {})
    return {"id": row.id, "course_id": row.course_id, "version": row.version, "name": row.name,
            "style_key": row.style_key, "style_label": style(row.style_key)["label"], "origin": row.origin,
            "active": row.active, "data": data.model_dump(),
            "reference_assets": list(row.reference_assets or []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "style_prompt": style_block(data, version=row.version)}


class DesignProfiles:
    def __init__(self, db: Database) -> None:
        self.db = db

    def active(self, course_id: str) -> dict[str, Any] | None:
        with self.db.session() as session:
            row = session.scalars(select(IllustrationProfile).where(
                IllustrationProfile.course_id == course_id, IllustrationProfile.active.is_(True))
                .order_by(IllustrationProfile.version.desc())).first()
            return profile_dict(row) if row else None

    def get(self, profile_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(IllustrationProfile, profile_id)
            if row is None:
                raise NotFoundError("not_found", detail="designprofil")
            return profile_dict(row)

    def versions(self, course_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(select(IllustrationProfile).where(IllustrationProfile.course_id == course_id)
                                   .order_by(IllustrationProfile.version.desc())).all()
            return [profile_dict(r) for r in rows]

    def save(self, course_id: str, data: DesignData, *, origin: str,
             reference_assets: list[str] | None = None) -> dict[str, Any]:
        """A new version (the previous versions stay, inactive). Reference images carry over unless given."""
        with self.db.session() as session:
            rows = session.scalars(select(IllustrationProfile).where(IllustrationProfile.course_id == course_id)).all()
            previous = max(rows, key=lambda r: r.version) if rows else None
            for row in rows:
                row.active = False
            if not data.prompt.strip():
                raise AppError("validation_error", message="Designprofilen mangler prompt. Lim inn en prompt i "
                                                           "tekstboksen før du lagrer.")
            refs = list(reference_assets if reference_assets is not None else (
                previous.reference_assets if previous else []))[:MAX_REFERENCES]
            row = IllustrationProfile(course_id=course_id, version=(previous.version + 1) if previous else 1,
                                      name=data.name or style(data.style_key)["label"], style_key=data.style_key,
                                      data=data.model_dump(), reference_assets=refs, origin=origin, active=True)
            session.add(row)
            session.flush()
            return profile_dict(row)

    def ensure(self, course_id: str) -> dict[str, Any]:
        return self.active(course_id) or self.save(course_id, from_style(default_style()), origin="preset")

    def set_references(self, course_id: str, asset_ids: list[str]) -> dict[str, Any]:
        """Change the reference images of the active profile in place (they are not part of the style text)."""
        if len(asset_ids) > MAX_REFERENCES:
            raise AppError("validation_error", message=f"Velg høyst {MAX_REFERENCES} referansebilder.")
        with self.db.session() as session:
            row = session.scalars(select(IllustrationProfile).where(
                IllustrationProfile.course_id == course_id, IllustrationProfile.active.is_(True))).first()
            if row is None:
                raise NotFoundError("not_found", detail="designprofil")
            row.reference_assets = list(dict.fromkeys(asset_ids))
            return profile_dict(row)

    def add_reference(self, course_id: str, asset_id: str) -> None:
        current = self.active(course_id)
        if current is None or asset_id in current["reference_assets"]:
            return
        refs = current["reference_assets"]
        if len(refs) >= MAX_REFERENCES:
            return  # the teacher manages the set once it is full
        self.set_references(course_id, [*refs, asset_id])
