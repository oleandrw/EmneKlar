"""Course design profiles: one visual universe for every illustration in a course – versioned.

A profile holds the style, palette, contrast, lighting, composition, background, detail level, size/format, visual
traits and what must not appear. Consistency comes from three things together, not from repeating a description:

1. the same style block in every image prompt (:func:`style_block`);
2. approved images of the course used as **reference images** when the image model supports them (the OpenAI Image
   API takes them in ``/images/edits``), so new images inherit the look;
3. a visual check of every new image against the profile and a reference image (review step).

Every saved change creates a new version; a run records which version it used, so later modules can continue the
same style, and a changed style is visible.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import IllustrationProfile

STYLES_PATH = Path(__file__).resolve().parent / "styles.json"
#: «auto» = the planner picks the best format for each illustration; the others fix the format for the course.
ASPECT_CHOICES = ("auto", "16:9", "3:2", "4:3", "1:1", "2:3")
MAX_REFERENCES = 4


@cache
def styles() -> list[dict[str, Any]]:
    return list(json.loads(STYLES_PATH.read_text(encoding="utf-8"))["styles"])


def style(key: str) -> dict[str, Any]:
    return next((s for s in styles() if s["key"] == key), styles()[-1])


class DesignData(BaseModel):
    style_key: str = "modern_3d"
    name: str = Field("", max_length=200)
    rationale: str = Field("", max_length=2000)
    illustration_style: str = Field("", max_length=1000)
    palette: list[str] = Field(default_factory=list, max_length=10)
    palette_description: str = Field("", max_length=500)
    contrast: str = Field("", max_length=500)
    lighting: str = Field("", max_length=500)
    composition: str = Field("", max_length=800)
    background: str = Field("", max_length=500)
    detail_level: str = Field("", max_length=500)
    visual_traits: str = Field("", max_length=800)
    avoid: list[str] = Field(default_factory=list, max_length=30)
    people: str = Field("", max_length=500)
    aspect_ratio: str = "auto"

    @field_validator("style_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if value not in {s["key"] for s in styles()}:
            raise ValueError("Ukjent stil")
        return value

    @field_validator("aspect_ratio")
    @classmethod
    def _ratio(cls, value: str) -> str:
        if value not in ASPECT_CHOICES:
            raise ValueError("Ukjent bildeformat")
        return value

    @field_validator("palette")
    @classmethod
    def _palette(cls, value: list[str]) -> list[str]:
        import re

        return [v.strip() for v in value if re.fullmatch(r"#[0-9A-Fa-f]{6}", v.strip())]



def from_style(key: str) -> DesignData:
    base = style(key)
    fields = {k: v for k, v in base.items() if k in DesignData.model_fields}
    return DesignData(**{**fields, "style_key": base["key"], "name": base["label"]})


def style_block(data: DesignData, *, version: int | None = None, labels: bool = False) -> str:
    """The course-wide style description added to every image prompt (English)."""
    parts = [f"Visual style (course design profile{f' v{version}' if version else ''}, keep consistent across all "
             f"images of the course): {data.illustration_style or style(data.style_key)['illustration_style']}."]
    if data.palette:
        parts.append(f"Colour palette: {', '.join(data.palette)}" + (f" ({data.palette_description})."
                                                                      if data.palette_description else "."))
    for label, value in (("Contrast", data.contrast), ("Lighting", data.lighting), ("Composition", data.composition),
                         ("Background", data.background), ("Level of detail", data.detail_level),
                         ("Recurring visual traits", data.visual_traits), ("People", data.people)):
        if value:
            parts.append(f"{label}: {value}.")
    avoid = [a for a in dict.fromkeys([*data.avoid, "text", "logos", "watermarks"])
             if not (labels and a.strip().lower() in ("text", "labels", "tekst", "numbers"))]
    parts.append(f"Never include: {', '.join(avoid)}." + (" Only the short labels listed below may appear as text."
                                                          if labels else ""))
    parts.append("Same visual universe as the other illustrations of the course, but a distinct motif – not a copy.")
    return " ".join(parts)


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
            refs = list(reference_assets if reference_assets is not None else (
                previous.reference_assets if previous else []))[:MAX_REFERENCES]
            row = IllustrationProfile(course_id=course_id, version=(previous.version + 1) if previous else 1,
                                      name=data.name or style(data.style_key)["label"], style_key=data.style_key,
                                      data=data.model_dump(), reference_assets=refs, origin=origin, active=True)
            session.add(row)
            session.flush()
            return profile_dict(row)

    def ensure(self, course_id: str) -> dict[str, Any]:
        return self.active(course_id) or self.save(course_id, from_style("modern_3d"), origin="preset")

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
