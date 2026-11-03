"""Storage and querying of findings across domains.

* A finding's **fingerprint** (course, domain, rule, object, element) is stable
  across analyses, so user decisions («Ignorer») survive re-analysis.
* **Current findings** for a domain are merged per object: the newest run that
  analysed an object wins. A later analysis of a single module therefore
  replaces that module's findings without hiding the rest of the course.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from emneklar.core.errors import NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import AnalysisRun, Finding, FindingDecision

ACTIONABLE = ("violation", "likely_violation")


@dataclass
class FindingDraft:
    domain: str
    rule_id: str
    category: str
    classification: str
    test_method: str
    severity: str
    title: str
    message: str
    remediation: str
    fingerprint: str
    confidence: str = "high"
    object_type: str | None = None
    object_id: str | None = None
    object_title: str | None = None
    object_url: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    fix: dict[str, Any] | None = None
    ruleset_version: str | None = None

    @property
    def object_ref(self) -> str:
        return f"{self.object_type}:{self.object_id}"


def make_fingerprint(course_id: str, domain: str, rule_id: str, object_ref: str, identity: str) -> str:
    raw = "|".join((course_id, domain, rule_id, object_ref, identity))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finding_dict(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id, "run_id": f.run_id, "domain": f.domain, "rule_id": f.rule_id,
        "ruleset_version": f.ruleset_version, "category": f.category, "classification": f.classification,
        "test_method": f.test_method, "severity": f.severity, "confidence": f.confidence, "title": f.title,
        "message": f.message, "object_type": f.object_type, "object_id": f.object_id,
        "object_title": f.object_title, "object_url": f.object_url, "location": f.location or {},
        "evidence": f.evidence or {}, "remediation": f.remediation, "fix": f.fix, "status": f.status,
        "fingerprint": f.fingerprint, "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _covered(row: Finding, covered: set[str]) -> bool:
    """Whether a newer run analysed the finding's object (quiz questions are covered by their quiz)."""
    if f"{row.object_type}:{row.object_id}" in covered:
        return True
    quiz_id = (row.evidence or {}).get("quiz_id") if row.object_type == "quiz_question" else None
    return bool(quiz_id) and f"quiz:{quiz_id}" in covered


class FindingStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- writing -------------------------------------------------------------------------------

    def save(self, run_id: int, course_id: str, drafts: Iterable[FindingDraft]) -> int:
        drafts = list(drafts)
        if not drafts:
            return 0
        with self.db.session() as session:
            decided = {d.fingerprint: d.decision for d in session.scalars(
                select(FindingDecision).where(FindingDecision.course_id == course_id)).all()}
            seen: set[str] = set()
            rows = []
            for d in drafts:
                if d.fingerprint in seen:
                    continue
                seen.add(d.fingerprint)
                rows.append(Finding(
                    run_id=run_id, course_id=course_id, domain=d.domain, rule_id=d.rule_id,
                    ruleset_version=d.ruleset_version, category=d.category, classification=d.classification,
                    test_method=d.test_method, severity=d.severity, confidence=d.confidence, title=d.title[:500],
                    message=d.message, object_type=d.object_type, object_id=d.object_id,
                    object_title=(d.object_title or "")[:1000], object_url=d.object_url, location=d.location,
                    evidence=d.evidence, remediation=d.remediation, fix=d.fix, fingerprint=d.fingerprint,
                    status="ignored" if decided.get(d.fingerprint) == "ignored" else "open"))
            session.add_all(rows)
            return len(rows)

    # -- reading -------------------------------------------------------------------------------

    def runs_for(self, course_id: str, domain: str) -> list[AnalysisRun]:
        with self.db.session() as session:
            runs = session.scalars(select(AnalysisRun).where(AnalysisRun.course_id == course_id)
                                   .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())).all()
            return [r for r in runs if domain in (r.domains or []) and r.status in ("complete", "partial", "cancelled")]

    def current(self, course_id: str, domain: str) -> tuple[list[Finding], list[AnalysisRun]]:
        """Merged current findings for a domain and the runs that contributed."""
        runs = self.runs_for(course_id, domain)
        covered: set[str] = set()
        result: list[Finding] = []
        used: list[AnalysisRun] = []
        with self.db.session() as session:
            for run in runs:
                objects = set(((run.scope or {}).get("objects") or {}).get(domain) or [])
                rows = session.scalars(select(Finding).where(Finding.run_id == run.id, Finding.domain == domain)).all()
                contributed = False
                for row in rows:
                    if not _covered(row, covered):
                        result.append(row)
                        contributed = True
                if contributed or not used:
                    used.append(run)
                covered |= objects
                full = (run.scope or {}).get("type") == "course" and run.status == "complete"
                if full:
                    break
            session.expunge_all()
        return result, used

    def get(self, finding_id: int) -> Finding:
        with self.db.session() as session:
            row = session.get(Finding, finding_id)
            if row is None:
                raise NotFoundError("not_found", detail=f"funn {finding_id}")
            session.expunge(row)
            return row

    # -- decisions -----------------------------------------------------------------------------

    def set_ignored(self, finding_id: int, ignored: bool, note: str | None = None) -> Finding:
        with self.db.session() as session:
            row = session.get(Finding, finding_id)
            if row is None:
                raise NotFoundError("not_found")
            decision = session.get(FindingDecision, row.fingerprint)
            if ignored:
                if decision is None:
                    session.add(FindingDecision(fingerprint=row.fingerprint, course_id=row.course_id,
                                                decision="ignored", note=note))
                else:
                    decision.decision, decision.note = "ignored", note
            elif decision is not None:
                session.delete(decision)
            for same in session.scalars(select(Finding).where(Finding.fingerprint == row.fingerprint)).all():
                if same.status in ("open", "ignored"):
                    same.status = "ignored" if ignored else "open"
            session.flush()
            session.expunge(row)
            return row

    def set_status_by_fingerprint(self, fingerprint: str, status: str) -> None:
        with self.db.session() as session:
            for row in session.scalars(select(Finding).where(Finding.fingerprint == fingerprint)).all():
                row.status = status


def summarize(findings: list[Finding]) -> dict[str, Any]:
    open_findings = [f for f in findings if f.status not in ("ignored", "fixed")]
    by_class = Counter(f.classification for f in open_findings)
    by_category = Counter(f.category for f in open_findings)
    return {
        "total": len(open_findings),
        "ignored": sum(1 for f in findings if f.status == "ignored"),
        "fixed": sum(1 for f in findings if f.status == "fixed"),
        "staged": sum(1 for f in findings if f.status == "staged"),
        "by_classification": dict(by_class),
        "by_category": dict(by_category),
        "actionable": sum(by_class.get(c, 0) for c in ACTIONABLE),
    }
