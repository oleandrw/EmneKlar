"""The versioned accessibility rule registry (rules/ruleset.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from emneklar.features.accessibility.profiles import Source, wcag_catalog

RULESET_PATH = Path(__file__).parent / "rules" / "ruleset.json"

Classification = Literal["violation", "likely_violation", "should_review", "improvement", "manual_check"]
TestMethod = Literal["deterministic", "heuristic", "ai", "manual"]
Severity = Literal["critical", "serious", "moderate", "minor", "info"]

CATEGORY_LABELS = {
    "images": "Bilder",
    "headings": "Overskrifter",
    "links": "Lenker",
    "tables": "Tabeller",
    "lists": "Lister",
    "language": "Språk og instruksjoner",
    "contrast": "Kontrast",
    "iframes": "Innebygd innhold",
    "media": "Video og lyd",
    "documents": "Dokumenter",
    "markup": "Kode",
}
_LEVEL_ORDER = {"A": 0, "AA": 1, "AAA": 2}


class Rule(BaseModel):
    id: str
    category: str
    title: str
    wcag: list[str]
    testability: TestMethod
    severity: Severity
    classification: Classification
    explanation: str
    affected_users: str
    remediation: str
    sources: list[Source]
    fix_policy: Literal["auto_suggest", "user_input", "ai_suggest", "manual"]

    @property
    def wcag_version(self) -> str | None:
        catalog = wcag_catalog()
        versions = [catalog[c]["since"] for c in self.wcag if c in catalog]
        return max(versions) if versions else None

    @property
    def level(self) -> str | None:
        catalog = wcag_catalog()
        levels = [catalog[c]["level"] for c in self.wcag if c in catalog]
        return min(levels, key=lambda lv: _LEVEL_ORDER.get(lv, 9)) if levels else None


class Ruleset(BaseModel):
    version: str
    verified_at: str
    rules: dict[str, Rule]


@lru_cache(maxsize=1)
def load_ruleset() -> Ruleset:
    data = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
    rules = {r["id"]: Rule.model_validate(r) for r in data["rules"]}
    return Ruleset(version=data["version"], verified_at=data["verified_at"], rules=rules)


def get_rule(rule_id: str) -> Rule:
    return load_ruleset().rules[rule_id]


def rule_info(rule: Rule) -> dict[str, object]:
    catalog = wcag_catalog()
    return {
        "id": rule.id,
        "title": rule.title,
        "category": rule.category,
        "category_label": CATEGORY_LABELS.get(rule.category, rule.category),
        "wcag": rule.wcag,
        "wcag_titles": {c: catalog.get(c, {}).get("title") for c in rule.wcag},
        "wcag_version": rule.wcag_version,
        "level": rule.level,
        "testability": rule.testability,
        "severity": rule.severity,
        "classification": rule.classification,
        "explanation": rule.explanation,
        "affected_users": rule.affected_users,
        "remediation": rule.remediation,
        "sources": [s.model_dump() for s in rule.sources]
        + [{"title": f"WCAG {c} {catalog[c]['title']} (Understanding)", "url": catalog[c]["url"]}
           for c in rule.wcag if c in catalog],
        "fix_policy": rule.fix_policy,
        "ruleset_version": load_ruleset().version,
    }
