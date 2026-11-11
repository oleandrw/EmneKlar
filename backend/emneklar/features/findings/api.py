"""Findings (all domains): filtered lists, details with rule info and legal status, direct Canvas links,
suggestion status, the finding's image, «Ignorer», «Kontrollert» (confirmations) and the teacher's media kind."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.canvas.links import content_links, href_problem
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import Finding
from emneklar.features.accessibility.profiles import describe_profile, get_profile, legal_status, load_profiles
from emneklar.features.accessibility.rules import CATEGORY_LABELS, load_ruleset, rule_info
from emneklar.features.analysis.api import run_dict
from emneklar.features.findings.store import FindingStore, finding_dict, summarize

#: Image types shown in the review view. SVG is never served from EmneKlar's origin (it can carry scripts).
VIEWABLE_IMAGES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/avif"}

router = APIRouter(prefix="/api")

CLASS_ORDER = {"violation": 0, "likely_violation": 1, "should_review": 2, "manual_check": 3, "improvement": 4}
SEVERITY_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3, "info": 4}


def category_label(domain: str, category: str) -> str:
    if domain == "content_quality":
        from emneklar.features.content_quality.rules import CATEGORY_LABELS as CQ_LABELS

        return CQ_LABELS.get(category, category)
    if domain == "structure":
        from emneklar.features.course_structure.rules import CATEGORY_LABELS as ST_LABELS

        return ST_LABELS.get(category, category)
    if domain in ("quiz", "quiz_ai"):
        from emneklar.features.quiz_assistant.rules import CATEGORY_LABELS as QZ_LABELS

        return QZ_LABELS.get(category, category)
    return CATEGORY_LABELS.get(category, category)


CLASSIFICATIONS = ("violation", "likely_violation", "should_review", "improvement", "manual_check")


def domain_classifications(domain: str) -> list[str]:
    """The classes the domain's rules can give, in a fixed order – from the rule registries, so a page does not show a
    figure for a class its area never uses (Emnestruktur has no «feil»)."""
    rules: list[Any]
    if domain == "content_quality":
        from emneklar.features.content_quality.rules import RULES as CQ_RULES

        rules = list(CQ_RULES.values())
    elif domain == "structure":
        from emneklar.features.course_structure.rules import RULES as ST_RULES

        rules = list(ST_RULES.values())
    elif domain in ("quiz", "quiz_ai"):
        from emneklar.features.quiz_assistant.rules import RULES as QZ_RULES

        rules = list(QZ_RULES.values())
    else:
        rules = list(load_ruleset().rules.values())
    used = {str(getattr(r, "classification", "")) for r in rules}
    return [c for c in CLASSIFICATIONS if c in used]


def decision_info(row: Finding, decision: dict[str, Any] | None) -> dict[str, Any] | None:
    """The teacher's decision on the finding, with the confirmation's label for «Kontrollert»."""
    if decision is None or row.status not in ("ignored", "verified"):
        return None
    label = None
    if decision.get("decision") == "verified" and row.domain == "accessibility":
        rule = load_ruleset().rules.get(row.rule_id)
        label = next((x.label for x in rule.confirmations if x.id == decision.get("reason")), None) if rule else None
    return {**decision, "label": label}


def enrich(row: Finding, profile_id: str | None, *, base_url: str | None = None,
           suggestion: dict[str, Any] | None = None, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    from emneklar.features.accessibility.alt_suggestions import is_image_finding
    from emneklar.features.accessibility.fixes import readiness

    data = finding_dict(row)
    data["decision"] = decision_info(row, decision)
    if row.domain == "accessibility":
        rules = load_ruleset().rules
        rule = rules.get(row.rule_id)
        if rule is not None:
            data["rule"] = rule_info(rule)
            profile = get_profile(profile_id)
            data["legal"] = legal_status(profile, rule.wcag, document=row.category == "documents")
    data["category_label"] = category_label(row.domain, row.category)
    data["canvas"] = content_links(base_url, row.course_id, row.object_type, row.object_id, object_url=row.object_url,
                                   location=row.location, evidence=row.evidence)
    href = (row.evidence or {}).get("href")
    data["href_problem"] = href_problem(str(href)) if isinstance(href, str) and row.rule_id.startswith(
        ("UU-LINK", "CQ-LINK", "UU-IMG-EMPTY-ALT-LINK")) else None
    data["image"] = is_image_finding(row)
    data["alt_suggestion"] = suggestion if data["image"] else None
    data["ready"] = readiness(row, suggestion) if row.fix else None
    return data


def enrich_many(c: AppContainer, rows: list[Finding]) -> list[dict[str, Any]]:
    from emneklar.features.accessibility.alt_suggestions import suggestions_for

    settings = c.settings.get()
    by_course: dict[str, list[str]] = {}
    for row in rows:
        by_course.setdefault(row.course_id, []).append(row.fingerprint)
    suggestions: dict[str, dict[str, Any]] = {}
    for course_id, fingerprints in by_course.items():
        suggestions.update(suggestions_for(c, course_id, fingerprints))
    decisions = FindingStore(c.db).decisions(r.fingerprint for r in rows if r.status in ("ignored", "verified"))
    return [enrich(r, settings.analysis.regulatory_profile, base_url=settings.canvas.base_url,
                   suggestion=suggestions.get(r.fingerprint), decision=decisions.get(r.fingerprint)) for r in rows]


@router.get("/courses/{course_id}/findings")
async def list_findings(
    course_id: str,
    domain: str = "accessibility",
    classification: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    severity: list[str] = Query(default=[]),
    rule: list[str] = Query(default=[]),
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
    elif status in ("ignored", "verified", "fixed", "staged"):
        filtered = [f for f in filtered if f.status == status]
    if classification:
        filtered = [f for f in filtered if f.classification in classification]
    if category:
        filtered = [f for f in filtered if f.category in category]
    if severity:
        filtered = [f for f in filtered if f.severity in severity]
    if rule:
        filtered = [f for f in filtered if f.rule_id in rule]
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
    # «Godkjenn alle klare» works on the whole selection, not one page: how many of them are ready. «automatic» = the
    # fix is decided by the finding (nothing to choose); «suggestion» = a rule-based text suggestion, only included
    # when the teacher asks for it. KI-forslag are never ready (they are reviewed one by one).
    from emneklar.features.accessibility.fixes import readiness

    ready = Counter(readiness(f, None) for f in filtered if f.fix)
    return {
        "items": enrich_many(c, filtered[start:start + page_size]),
        # All ids in the current filter and order: «Godkjenn alle klare» and stepping from one finding to the next
        # work across pages without loading every finding.
        "ids": [f.id for f in filtered][:5000],
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "categories": [{"id": cat, "label": category_label(domain, cat)} for cat in categories],
        "classifications": domain_classifications(domain),
        "ready": {"automatic": ready.get("automatic", 0), "suggestion": ready.get("suggestion", 0)},
        "runs": [run_dict(r) for r in runs],
        "profile": {"id": get_profile(profile_id).id, "title": get_profile(profile_id).title,
                    "version": get_profile(profile_id).version},
    }


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).get(finding_id)
    return enrich_many(c, [row])[0]


@router.get("/findings/{finding_id}/image")
async def finding_image(finding_id: int, c: AppContainer = Depends(get_container)) -> Response:
    """The image a finding is about, for the review view. Canvas files are fetched with the token in the backend
    (it never reaches the browser); other hosts go through the SSRF guard. Only raster images are served."""
    from emneklar.features.accessibility.alt_suggestions import fetch_image

    row = FindingStore(c.db).get(finding_id)
    src = str((row.evidence or {}).get("src") or "")
    if not src:
        raise AppError("not_found", status=404, detail="Funnet gjelder ikke et bilde")
    data, content_type = await fetch_image(c, src, allowed=VIEWABLE_IMAGES, max_bytes=8 * 1024 * 1024)
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=300",
                                                            "X-Content-Type-Options": "nosniff",
                                                            "Content-Security-Policy": "default-src 'none'"})


class IgnoreBody(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class VerifyBody(BaseModel):
    confirmation: str = Field(max_length=32)
    note: str | None = Field(default=None, max_length=1000)


class MediaKindBody(BaseModel):
    kind: Literal["audio", "video", "video_no_audio"] | None


@router.post("/findings/{finding_id}/ignore")
async def ignore_finding(finding_id: int, body: IgnoreBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).set_ignored(finding_id, True, body.note)
    return enrich_many(c, [row])[0] | {"status": "ignored"}


@router.post("/findings/{finding_id}/verify")
async def verify_finding(finding_id: int, body: VerifyBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Kontrollert»: the teacher confirms what a manual check asks for (one of the rule's confirmations, e.g. «the
    transcript is on the page»). Survives re-analysis, listed in reports. Nothing is written to Canvas."""
    store = FindingStore(c.db)
    row = store.get(finding_id)
    rule = load_ruleset().rules.get(row.rule_id) if row.domain == "accessibility" else None
    confirmation = next((x for x in rule.confirmations if x.id == body.confirmation), None) if rule else None
    if confirmation is None or (confirmation.requires_evidence
                                and not (row.evidence or {}).get(confirmation.requires_evidence)):
        raise AppError("validation_error", status=422, detail="Bekreftelsen gjelder ikke dette funnet")
    row = store.set_decision(finding_id, "verified", body.note, reason=body.confirmation)
    return enrich_many(c, [row])[0] | {"status": "verified"}


@router.post("/findings/{finding_id}/reopen")
async def reopen_finding(finding_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    row = FindingStore(c.db).set_decision(finding_id, None)
    return enrich_many(c, [row])[0] | {"status": "open"}


@router.post("/findings/{finding_id}/media-kind")
async def set_media_kind(finding_id: int, body: MediaKindBody,
                         c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """The teacher states what the recording is (audio only, video with or without sound) – the requirement depends on
    it. Used by the next analysis of the content; ``reanalyse`` names the content to analyse again (the syllabus is
    only analysed with the whole course)."""
    from emneklar.features.accessibility.media_assessments import save_assessment

    row = FindingStore(c.db).get(finding_id)
    rule = load_ruleset().rules.get(row.rule_id) if row.domain == "accessibility" else None
    media_key = (row.evidence or {}).get("media_key")
    if rule is None or not rule.media_kind_choice or not isinstance(media_key, str) or not media_key:
        raise AppError("validation_error", status=422, detail="Funnet gjelder ikke et opptak EmneKlar kan identifisere")
    save_assessment(c.db, row.course_id, media_key, body.kind)
    reanalyse = ({"object_type": row.object_type, "object_id": row.object_id}
                 if row.object_type and row.object_id and row.object_type != "syllabus" else None)
    return {"media_key": media_key, "kind": body.kind, "reanalyse": reanalyse}


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
