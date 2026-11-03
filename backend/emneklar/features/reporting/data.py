"""Collect report data from stored analysis results (no Canvas calls – reports work offline)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Finding, Snapshot, SnapshotObject
from emneklar.features.findings.api import category_label
from emneklar.features.findings.store import FindingStore

REPORT_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "full": ("Full emneanalyse", ("accessibility", "content_quality", "structure", "quiz", "quiz_ai")),
    "accessibility": ("UU-analyse", ("accessibility",)),
    "content_quality": ("Innholdskvalitet", ("content_quality",)),
    "structure": ("Struktur", ("structure",)),
    "quiz": ("Quizkvalitet", ("quiz", "quiz_ai")),
}
DOMAIN_LABELS = {"accessibility": "Universell utforming", "content_quality": "Innholdskvalitet",
                 "structure": "Emnestruktur", "quiz": "Quizkvalitet", "quiz_ai": "Quizkvalitet (KI-vurdering)"}
CLASS_LABELS = {"violation": "Avvik", "likely_violation": "Sannsynlig avvik", "should_review": "Bør vurderes",
                "improvement": "Forbedringsforslag", "manual_check": "Manuell kontroll"}
CLASS_ORDER = list(CLASS_LABELS)
METHOD_LABELS = {"deterministic": "Deterministisk", "heuristic": "Heuristisk", "ai": "KI-assistert",
                 "manual": "Manuell"}
SEVERITY_LABELS = {"critical": "Kritisk", "serious": "Alvorlig", "moderate": "Moderat", "minor": "Lav",
                   "info": "Info"}
LEGAL_LABELS = {"required": "Lovkrav i valgt profil", "conditional": "Lovkrav under vilkår",
                "not_required": "Ikke lovkrav i valgt profil", "best_practice": "Anbefalt praksis",
                "none": "Ikke knyttet til et krav"}
SCOPE_LABELS = {"course": "Hele emnet", "modules": "Valgte moduler", "items": "Enkeltelementer"}
STATUS_LABELS = {"open": "Åpen", "staged": "I endringskøen", "fixed": "Rettet", "ignored": "Ignorert"}
DISCLAIMER = ("Rapporten viser resultatet av automatiske og delvis automatiske kontroller på tidspunktet for analysen. "
              "Den er ikke en erklæring eller sertifisering av at emnet oppfyller krav til universell utforming. "
              "Funn merket «Manuell kontroll» og «Bør vurderes» må vurderes av et menneske, og mange krav kan bare "
              "kontrolleres manuelt.")


@dataclass
class DomainReport:
    domain: str
    label: str
    analysed: bool
    runs: list[dict[str, Any]] = field(default_factory=list)
    remaining: list[dict[str, Any]] = field(default_factory=list)
    manual: list[dict[str, Any]] = field(default_factory=list)
    fixed: list[dict[str, Any]] = field(default_factory=list)
    ignored: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    rulesets: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        by_class = {c: sum(1 for f in self.remaining + self.manual if f["classification"] == c) for c in CLASS_ORDER}
        return {**by_class, "fixed": len(self.fixed), "ignored": len(self.ignored)}


@dataclass
class ReportData:
    report_type: str
    title: str
    course_id: str
    course_name: str
    course_code: str | None
    created_at: datetime
    profile: dict[str, Any] | None
    domains: list[DomainReport]
    disclaimer: str = DISCLAIMER

    @property
    def run_ids(self) -> list[int]:
        return sorted({r["id"] for d in self.domains for r in d.runs})


def _finding(row: Finding, profile: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id, "domain": row.domain, "rule_id": row.rule_id, "title": row.title, "message": row.message,
        "classification": row.classification, "classification_label": CLASS_LABELS.get(row.classification, ""),
        "severity_label": SEVERITY_LABELS.get(row.severity, row.severity), "test_method": row.test_method,
        "method_label": METHOD_LABELS.get(row.test_method, row.test_method),
        "category_label": category_label(row.domain, row.category), "object_type": row.object_type,
        "object_title": row.object_title, "object_url": row.object_url,
        "module": (row.location or {}).get("module"), "remediation": row.remediation or "", "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status), "criteria": [], "legal_label": "",
        "confidence": row.confidence,
    }
    if row.domain == "accessibility" and profile is not None:
        from emneklar.features.accessibility.profiles import legal_status
        from emneklar.features.accessibility.rules import load_ruleset

        rule = load_ruleset().rules.get(row.rule_id)
        if rule is not None:
            data["criteria"] = list(rule.wcag)
            status = legal_status(profile, list(rule.wcag), document=row.category == "documents")
            data["legal_label"] = LEGAL_LABELS.get(str(status["status"]), "")
    return data


def _sort_key(f: dict[str, Any]) -> tuple[int, str, str]:
    order = CLASS_ORDER.index(f["classification"]) if f["classification"] in CLASS_ORDER else 99
    return order, f["object_title"] or "", f["title"]


def collect(c: AppContainer, course_id: str, report_type: str) -> ReportData:
    title, domains = REPORT_TYPES[report_type]
    profile = None
    profile_info = None
    if "accessibility" in domains:
        from emneklar.features.accessibility.profiles import get_profile

        profile = get_profile(c.settings.get().analysis.regulatory_profile)
        profile_info = {"id": profile.id, "title": profile.title, "version": profile.version,
                        "wcag_version": profile.wcag_version, "standard": profile.standard,
                        "is_legal_requirement": profile.is_legal_requirement}
    store = FindingStore(c.db)
    reports = []
    for domain in domains:
        rows, runs = store.current(course_id, domain)
        report = DomainReport(domain=domain, label=DOMAIN_LABELS[domain], analysed=bool(runs))
        if domain == "quiz_ai" and not runs:
            continue  # AI review is optional – only reported when it was run
        for run in runs:
            report.runs.append({"id": run.id, "scope": SCOPE_LABELS.get(str((run.scope or {}).get("type")), "Ukjent"),
                                "started_at": run.started_at, "status": run.status,
                                "ruleset_version": run.ruleset_version, "profile_id": run.profile_id,
                                "profile_version": run.profile_version})
            report.limitations.extend(str(x) for x in run.limitations or [])
            if run.status != "complete":
                report.limitations.append("En av analysene ble ikke fullført, så resultatene kan være ufullstendige.")
        report.limitations = list(dict.fromkeys(report.limitations))
        report.rulesets = sorted({str(r.ruleset_version) for r in runs if r.ruleset_version})
        for row in rows:
            item = _finding(row, profile)
            if row.status == "fixed":
                report.fixed.append(item)
            elif row.status == "ignored":
                report.ignored.append(item)
            elif row.classification == "manual_check":
                report.manual.append(item)
            else:
                report.remaining.append(item)
        for bucket in (report.remaining, report.manual, report.fixed, report.ignored):
            bucket.sort(key=_sort_key)
        reports.append(report)
    name, code = _course_name(c, course_id)
    return ReportData(report_type=report_type, title=title, course_id=course_id, course_name=name, course_code=code,
                      created_at=datetime.now().astimezone(), profile=profile_info, domains=reports)


def _course_name(c: AppContainer, course_id: str) -> tuple[str, str | None]:
    with c.db.session() as session:
        snapshot_id = session.scalars(select(Snapshot.id).where(Snapshot.course_id == course_id)
                                      .order_by(Snapshot.created_at.desc()).limit(1)).first()
        if snapshot_id is not None:
            obj = session.scalars(select(SnapshotObject).where(SnapshotObject.snapshot_id == snapshot_id,
                                                               SnapshotObject.object_type == "course")).first()
            if obj is not None:
                meta = obj.meta or {}
                return str(meta.get("name") or obj.title or f"Emne {course_id}"), meta.get("course_code")
    return f"Emne {course_id}", None
