"""Versioned regulatory profiles (data files in ./profiles).

A profile says, per WCAG success criterion, whether it is a legal requirement
(and under which condition) for a given sector. Legal status of a finding is
always computed from the profile selected by the user – never hard-coded in
rules or UI text.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

PROFILE_DIR = Path(__file__).parent / "profiles"
Status = Literal["required", "conditional", "best_practice", "not_required"]
_STRENGTH = {"required": 3, "conditional": 2, "best_practice": 1, "not_required": 0}


class Source(BaseModel):
    title: str
    url: str


class CriterionStatus(BaseModel):
    status: Status
    note: str | None = None


class Profile(BaseModel):
    id: str
    version: str
    title: str
    short_title: str
    description: str
    jurisdiction: str | None = None
    sector: str
    is_legal_requirement: bool
    wcag_version: str
    standard: str
    verified_at: str
    legal_basis: list[Source]
    criteria: dict[str, CriterionStatus]
    document_exclusions: list[str] = []
    exemptions: list[str] = []
    notes: list[str] = []

    def criterion(self, number: str, *, document: bool = False) -> CriterionStatus:
        if document and number in self.document_exclusions:
            return CriterionStatus(status="not_required", note="Gjelder ikke dokumenter i denne profilen.")
        return self.criteria.get(number) or CriterionStatus(status="not_required")

    def required_count(self, *, document: bool = False) -> int:
        return sum(1 for k, v in self.criteria.items()
                   if v.status in ("required", "conditional", "best_practice")
                   and not (document and k in self.document_exclusions))


@lru_cache(maxsize=1)
def wcag_catalog() -> dict[str, dict[str, str]]:
    data = json.loads((PROFILE_DIR / "wcag.json").read_text(encoding="utf-8"))
    base = data["understanding_base"]
    return {k: {**v, "url": f"{base}{v['slug']}.html"} for k, v in data["criteria"].items()}


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, Profile]:
    profiles = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        if path.name == "wcag.json":
            continue
        profile = Profile.model_validate_json(path.read_text(encoding="utf-8"))
        profiles[profile.id] = profile
    return profiles


def get_profile(profile_id: str | None) -> Profile:
    profiles = load_profiles()
    return profiles.get(profile_id or "") or profiles["no-offentlig-2023"]


def legal_status(profile: Profile, criteria: list[str], *, document: bool = False) -> dict[str, object]:
    """Legal status of a rule (its criteria) under ``profile``."""
    if not criteria:
        return {"status": "none", "note": None, "profile_id": profile.id, "profile_title": profile.title,
                "profile_version": profile.version}
    best = max((profile.criterion(c, document=document) for c in criteria), key=lambda s: _STRENGTH[s.status])
    return {"status": best.status, "note": best.note, "profile_id": profile.id, "profile_title": profile.title,
            "profile_version": profile.version}


def describe_profile(profile: Profile) -> dict[str, object]:
    catalog = wcag_catalog()
    return {
        **profile.model_dump(exclude={"criteria"}),
        "criteria_count": profile.required_count(),
        "document_criteria_count": profile.required_count(document=True),
        "criteria": [
            {"number": number, "title": catalog.get(number, {}).get("title", ""),
             "level": catalog.get(number, {}).get("level"), "status": status.status, "note": status.note,
             "url": catalog.get(number, {}).get("url")}
            for number, status in sorted(profile.criteria.items(), key=lambda kv: [int(x) for x in kv[0].split(".")])
        ],
    }
