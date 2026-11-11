"""Emnedesign profiles (profiles.json): design values (tokens) and component templates, kept apart so more profiles
can be added later. A profile resolves to inline-style declarations per element role."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from emneklar.core.errors import AppError

PROFILES_PATH = Path(__file__).parent / "profiles.json"
_TOKEN = re.compile(r"\{([a-z_]+)\}")

Declarations = list[tuple[str, str]]


@dataclass(frozen=True)
class Profile:
    id: str
    version: str
    label: str
    description: str
    default: bool
    tokens: dict[str, str]
    components: dict[str, dict[str, str]]
    #: Templates from earlier versions of this profile, per role – recognised and removed, never applied.
    retired: dict[str, tuple[dict[str, str], ...]] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def declarations(self, role: str) -> Declarations:
        """Inline-style declarations for an element role, in template order (empty token values are left out)."""
        template = self.components.get(role)
        return [] if template is None else self._resolve(template)

    def retired_declarations(self, role: str) -> Declarations:
        """Declarations earlier versions of the profile generated for the role (see ``retired_components``)."""
        return [decl for template in self.retired.get(role, ()) for decl in self._resolve(template)]

    def _resolve(self, template: dict[str, str]) -> Declarations:
        out: Declarations = []
        for prop, raw in template.items():
            value = _TOKEN.sub(lambda m: self.tokens.get(m.group(1), ""), raw).strip()
            if value and "{}" not in value and not value.startswith(" "):
                out.append((prop, value))
        return out

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "label": self.label, "description": self.description,
                "default": self.default, "tokens": dict(self.tokens)}


@lru_cache(maxsize=1)
def _load() -> dict[str, Profile]:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    shared: dict[str, dict[str, str]] = data["shared_components"]
    retired = {role: tuple(entry["template"] for entry in entries)
               for role, entries in data.get("retired_components", {}).items()}
    profiles: dict[str, Profile] = {}
    for raw in data["profiles"]:
        components = {**shared, **raw.get("components", {})}
        profiles[raw["id"]] = Profile(id=raw["id"], version=str(raw["version"]), label=raw["label"],
                                      description=raw["description"], default=bool(raw.get("default")),
                                      tokens=dict(raw["tokens"]), components=components, retired=retired)
    return profiles


def profiles() -> list[Profile]:
    return list(_load().values())


def default_profile() -> Profile:
    return next((p for p in profiles() if p.default), profiles()[0])


def get(profile_id: str) -> Profile:
    profile = _load().get(profile_id)
    if profile is None:
        raise AppError("validation_error", status=422, detail=f"Ukjent designprofil: {profile_id}")
    return profile


def norm_value(value: str) -> str:
    """A CSS value as compared when recognising EmneKlar's styling: Canvas re-serialises styles (``Arial , sans-serif``,
    no spaces, double quotes), so case, quote style, spaces around commas and repeated spaces are ignored."""
    return re.sub(r"\s*,\s*", ",", re.sub(r"\s+", " ", value.strip().lower())).replace('"', "'")


@lru_cache(maxsize=1)
def known_declarations() -> dict[str, set[tuple[str, str]]]:
    """Every declaration any profile generates, per role – to recognise EmneKlar's own styling when a design is
    applied again or replaced (also when Canvas dropped the data attribute that lists them)."""
    known: dict[str, set[tuple[str, str]]] = {}
    for profile in profiles():
        for role in {*profile.components, *profile.retired}:
            decls = [*profile.declarations(role), *profile.retired_declarations(role)]
            known.setdefault(role, set()).update((p.lower(), norm_value(v)) for p, v in decls)
    return known


def all_properties() -> set[str]:
    return {prop for profile in profiles() for role in profile.components for prop, _ in profile.declarations(role)}
