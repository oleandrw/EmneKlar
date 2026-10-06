"""SQLAlchemy ORM models (SQLite).

Schema changes ALWAYS go through an Alembic migration in ``backend/migrations``.
JSON columns hold structured data whose shape is defined by Pydantic models in
the owning module; every row that stores Canvas content is scoped to a course.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)


class Course(Base):
    """Cached course metadata from Canvas (refreshed when the course list is loaded)."""

    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # Canvas course id
    name: Mapped[str] = mapped_column(String(500))
    course_code: Mapped[str | None] = mapped_column(String(255))
    term_name: Mapped[str | None] = mapped_column(String(255))
    workflow_state: Mapped[str | None] = mapped_column(String(32))
    is_blueprint: Mapped[bool] = mapped_column(Boolean, default=False)
    default_view: Mapped[str | None] = mapped_column(String(32))
    enrollment_roles: Mapped[list[Any]] = mapped_column(JSON, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Snapshot(Base):
    """A normalized download of (part of) a course, shared by all analyzers in a run."""

    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="building")  # building|complete|partial|failed
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list)


class SnapshotObject(Base):
    __tablename__ = "snapshot_objects"
    __table_args__ = (
        Index("ix_snapobj_snapshot_type", "snapshot_id", "object_type"),
        Index("ix_snapobj_snapshot_canvas", "snapshot_id", "object_type", "canvas_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    object_type: Mapped[str] = mapped_column(String(32))
    canvas_id: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(1000), default="")
    html_url: Mapped[str | None] = mapped_column(String(2000))
    body: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    canvas_updated_at: Mapped[str | None] = mapped_column(String(40))
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    course_id: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id", ondelete="SET NULL"))
    domains: Mapped[list[Any]] = mapped_column(JSON, default=list)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ruleset_version: Mapped[str | None] = mapped_column(String(32))
    profile_id: Mapped[str | None] = mapped_column(String(64))
    profile_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|complete|partial|cancelled|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_course_domain", "course_id", "domain"),
        Index("ix_findings_fingerprint", "fingerprint"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str] = mapped_column(String(32))  # accessibility|content_quality|structure|quiz
    rule_id: Mapped[str] = mapped_column(String(64))
    ruleset_version: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(48))
    classification: Mapped[str] = mapped_column(String(32))
    test_method: Mapped[str] = mapped_column(String(16))  # deterministic|heuristic|ai|manual
    severity: Mapped[str] = mapped_column(String(16))  # critical|serious|moderate|minor|info
    confidence: Mapped[str] = mapped_column(String(8), default="high")  # high|medium|low
    title: Mapped[str] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text, default="")
    object_type: Mapped[str | None] = mapped_column(String(32))
    object_id: Mapped[str | None] = mapped_column(String(64))
    object_title: Mapped[str | None] = mapped_column(String(1000))
    object_url: Mapped[str | None] = mapped_column(String(2000))
    location: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    remediation: Mapped[str] = mapped_column(Text, default="")
    fix: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|ignored|staged|fixed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FindingDecision(Base):
    """A user decision that survives re-analysis (e.g. «Ignorer»)."""

    __tablename__ = "finding_decisions"
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(16))  # ignored
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LinkCheck(Base):
    __tablename__ = "link_checks"
    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(2000))
    state: Mapped[str] = mapped_column(String(16))  # WORKING|REDIRECT|DEAD|TIMEOUT|AUTH_REQUIRED|UNKNOWN
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(String(2000))
    detail: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StagedChange(Base):
    __tablename__ = "staged_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    target: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String(8), default="low")  # low|medium|high
    undo_capability: Mapped[str] = mapped_column(String(8), default="none")  # full|partial|none
    undo_note: Mapped[str] = mapped_column(Text, default="")
    conflict_status: Mapped[str] = mapped_column(String(16), default="not_checked")  # not_checked|ok|conflict
    status: Mapped[str] = mapped_column(String(16), default="staged")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    editable: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeLogEntry(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    course_id: Mapped[str | None] = mapped_column(String(32), index=True)
    change_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str | None] = mapped_column(String(32))
    object_id: Mapped[str | None] = mapped_column(String(64))
    object_title: Mapped[str | None] = mapped_column(String(1000))
    action: Mapped[str] = mapped_column(String(32))  # apply|undo|dry_run|failed|conflict
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    api_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_action: Mapped[str] = mapped_column(String(64), default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_id: Mapped[int | None] = mapped_column(Integer)
    undo_of: Mapped[int | None] = mapped_column(Integer)
    undoable: Mapped[bool] = mapped_column(Boolean, default=False)
    undone_by: Mapped[int | None] = mapped_column(Integer)


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    course_id: Mapped[str | None] = mapped_column(String(32), index=True)
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(1000), default="")
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    change_id: Mapped[int | None] = mapped_column(Integer)


class AIModel(Base):
    """Capability registry entry. Seeded from model_catalog.json; user-editable."""

    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_ai_models_provider_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[bool] = mapped_column(Boolean, default=True)
    vision: Mapped[bool] = mapped_column(Boolean, default=False)
    structured_output: Mapped[bool] = mapped_column(Boolean, default=False)
    context_class: Mapped[int] = mapped_column(Integer, default=1)  # 1 small … 4 very large
    quality_class: Mapped[int] = mapped_column(Integer, default=1)  # 1 basic … 4 frontier
    speed_class: Mapped[int] = mapped_column(Integer, default=2)  # 1 slow … 3 fast
    cost_class: Mapped[int] = mapped_column(Integer, default=2)  # 0 local/free … 4 premium
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="catalog")  # catalog|discovered|user
    capabilities_known: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AIUsage(Base):
    """What was sent where – metadata only, never content."""

    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    course_id: Mapped[str | None] = mapped_column(String(32))
    task_type: Mapped[str] = mapped_column(String(48))
    provider_id: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    strategy: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text, default="")
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(48))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    payload_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class QuestionBankItem(Base):
    """EmneKlar's own question workspace («KI-spørsmålsbank») – not Canvas question banks."""

    __tablename__ = "question_bank"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    question_type: Mapped[str] = mapped_column(String(32))  # single_choice|multiple_answers|true_false
    stem: Mapped[str] = mapped_column(Text)
    answers: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{id, text, correct}]
    explanation: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{object_type, object_id, title, quote}]
    module_id: Mapped[str | None] = mapped_column(String(64))
    module_name: Mapped[str | None] = mapped_column(String(500))
    topic: Mapped[str] = mapped_column(String(300), default="")
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")  # easy|medium|hard
    review_status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|rejected
    origin: Mapped[str] = mapped_column(String(16), default="manual")  # ai|manual
    grounding: Mapped[str] = mapped_column(String(16), default="verified")  # verified|partial|unverified
    generator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    used_in: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QuizPreset(Base):
    __tablename__ = "quiz_presets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HomepageDraft(Base):
    __tablename__ = "homepage_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(24))  # design|design_content|improve
    style: Mapped[str] = mapped_column(String(24))
    sections: Mapped[list[Any]] = mapped_column(JSON, default=list)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    html: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String(32), index=True)
    report_type: Mapped[str] = mapped_column(String(32))
    fmt: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    run_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
