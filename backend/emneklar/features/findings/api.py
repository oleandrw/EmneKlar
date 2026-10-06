"""Findings (all domains): filtered lists, details with rule info and legal status, «Ignorer»."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Finding
from emneklar.features.accessibility.profiles import describe_profile, get_profile, legal_status, load_profiles
from emneklar.features.accessibility.rules import CATEGORY_LABELS, load_ruleset, rule_info
from emneklar.features.analysis.api import run_dict
from emneklar.features.findings.store import FindingStore, finding_dict, summarize

router = APIRouter(prefix="/api")

CLASS_ORDER = {"violation": 0, "likely_violation": 1, "should_review": 2, "manual_check": 3, "improvement": 4}
SEVERITY_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3, "info": 4}


def enrich(row: Finding, profile_id: str | None) -> dict[str, Any]:
    data = finding_dict(row)
    if row.domain == "accessibility":
        rules = load_ruleset().rules
        rule = rules.get(row.rule_id)
        if rule is not None:
            data["rule"] = rule_info(rule)
            profile = get_profile(profile_id)
            data["legal"] = legal_status(profile, rule.wcag, document=row.category == "documents")
    data["category_label"] = CATEGORY_LABELS.get(row.category, data.get("category_label") or row.category)
    return data


@router.get("/courses/{course_id}/findings")
async def list_findings(
    course_id: str,
    domain: str = "accessibility",
    classification: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    status: str = "open",
    object_ref: str | None = None,
    q: str | None = None,
    sort: str = "priority",
    page: int = 1,
    page_size: int = 50,
    c: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    store = FindingStore(c.db)
    rows, runs = store.current(course_id, domain)
    summary = summarize(rows)
    filtered = rows
    if status == "open":
        filtered = [f for f in filtered if f.status in ("open", "staged")]
    elif status in ("ignored", "fixed", "staged"):
        filtered = [f for f in filtered if f.status == status]
    if classification:
        filtered = [f for f in filtered if f.classification in classification]
    if category:
        filtered = [f for f in filtered if f.category in category]
    if object_ref:
        filtered = [f for f in filtered if f"{f.object_type}:{f.object_id}" == object_ref]
    if q:
        needle = q.lower()
        filtered = [f for f in filtered if needle in f"{f.title} {f.message} {f.object_title}".lower()]
    if sort == "object":
        filtered.sort(key=lambda f: ((f.object_title or "").lower(), CLASS_ORDER.get(f.classification, 9)))
    else:
        filtered.sort(key=lambda f: (CLASS_ORDER.get(f.classification, 9), SEVERITY_ORDER.get(f.severity, 9),
                                     (f.object_title or "").lower()))
    page_size = min(200, max(5, page_size))
    page = max(1, page)
    start = (page - 1) * page_size
    profile_id = c.settings.get().analysis.regulatory_profile
    categories = sorted({f.category for f in rows})
    return {
        "items": [enrich(f, profile_id) for f in filtered[start:start + page_size]],
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "categories": [{"id": cat, "label": CATEGORY_LABELS.get(cat, cat)} for cat in categories],
        "runs": [run_dict(r) for r in runs],
        "profile": {"id": get_profile(profile_id).id, "title": get_profile(profile_id).title,
                    "version": get_profile(profile_id).version},
    }


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).get(finding_id)
    return enrich(row, c.settings.get().analysis.regulatory_profile)


class IgnoreBody(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


@router.post("/findings/{finding_id}/ignore")
async def ignore_finding(finding_id: int, body: IgnoreBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).set_ignored(finding_id, True, body.note)
    return enrich(row, c.settings.get().analysis.regulatory_profile) | {"status": "ignored"}


@router.post("/findings/{finding_id}/reopen")
async def reopen_finding(finding_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).set_ignored(finding_id, False)
    return enrich(row, c.settings.get().analysis.regulatory_profile) | {"status": "open"}


@router.get("/accessibility/profiles")
async def profiles(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    selected = c.settings.get().analysis.regulatory_profile
    return {"selected": get_profile(selected).id,
            "profiles": [describe_profile(p) for p in load_profiles().values()]}


@router.get("/accessibility/rules")
async def rules() -> dict[str, Any]:
    ruleset = load_ruleset()
    return {"version": ruleset.version, "verified_at": ruleset.verified_at,
            "rules": [rule_info(r) for r in ruleset.rules.values()]}
