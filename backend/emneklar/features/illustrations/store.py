"""Database helpers: runs, illustrations, the analysis cache, and status derived from the change engine."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select

from emneklar.core.errors import NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import Illustration, IllustrationAnalysis, IllustrationRun, StagedChange
from emneklar.features.illustrations.placement import PLACEMENTS

STATUS_LABELS = {
    "proposed": "Foreslått", "skipped": "Hoppet over", "queued": "Venter på generering", "generating": "Genereres",
    "generated": "Klar til gjennomgang", "flagged": "Må kontrolleres", "failed": "Feilet", "approved": "Godkjent",
    "rejected": "Forkastet", "staged": "I endringskøen", "published": "Publisert", "conflict": "Konflikt",
    "undone": "Angret",
}
RUN_STATUS_LABELS = {
    "created": "Opprettet", "analyzing": "Analyserer", "planned": "Bildeplan klar", "generating": "Lager bilder",
    "review": "Klar til gjennomgang", "completed": "Ferdig", "cancelled": "Avbrutt", "failed": "Feilet",
    "cost_limit": "Kostnadsgrense nådd", "interrupted": "Avbrutt (EmneKlar ble lukket)",
}
OPEN_FOR_REVIEW = ("generated", "flagged", "approved", "rejected", "failed")
EXISTING = ("generated", "flagged", "approved", "staged", "published")  # counted as «already exists» on re-runs


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9æøå]+", " ", (text or "").lower()).strip()


def fingerprint(course_id: str, page_url: str, section_title: str, concept: str) -> str:
    raw = f"{course_id}|{page_url}|{normalise(section_title)}|{normalise(concept)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def marker_for(ill: dict[str, Any], extra: str = "") -> str:
    """``ill-<id>-<hash of what is rendered>``: a changed image, alt text, caption or placement gives a new marker, so
    publishing again replaces EmneKlar's previous figure instead of skipping it as «already on the page»."""
    anchor = ill.get("anchor") or {}
    rendered = json.dumps([ill.get("asset_id"), "" if ill.get("decorative") else ill.get("alt_text"),
                           ill.get("caption") if ill.get("caption_enabled") else None, bool(ill.get("decorative")),
                           anchor.get("placement"), anchor.get("block_hash"), anchor.get("block_index"),
                           ill.get("credit") or "", extra], ensure_ascii=False)
    return f"ill-{ill['id']}-{hashlib.sha256(rendered.encode('utf-8')).hexdigest()[:10]}"


OPEN_CHANGE = ("staged", "approved", "conflict", "failed")


def illustration_dict(row: Illustration) -> dict[str, Any]:
    plan = row.plan or {}
    return {
        "id": row.id, "run_id": row.run_id, "course_id": row.course_id, "status": row.status,
        "fingerprint": row.fingerprint,
        "status_label": STATUS_LABELS.get(row.status, row.status), "module_id": row.module_id,
        "module_name": row.module_name, "page_url": row.page_url, "page_id": row.page_id, "page_title": row.page_title,
        "page_hash": row.page_hash, "position": row.position, "section": row.section or {}, "anchor": row.anchor or {},
        "placement_label": (row.anchor or {}).get("label") or PLACEMENTS.get((row.anchor or {}).get("placement", ""), ""),
        "plan": plan,
        "prompt": row.prompt, "style_override": row.style_override, "asset_id": row.asset_id,
        "image_url": f"/api/illustrations/assets/{row.asset_id}" if row.asset_id else None,
        "thumb_url": f"/api/illustrations/assets/{row.asset_id}?size=thumb" if row.asset_id else None,
        "versions": row.versions or [], "review": row.review or {}, "alt_text": row.alt_text,
        "decorative": row.decorative, "caption": row.caption, "caption_enabled": row.caption_enabled,
        "aspect_ratio": row.aspect_ratio, "image_type": row.image_type, "labels": list(row.labels or []),
        "credit": row.credit,
        "change_id": row.change_id, "published": row.published or {}, "error": row.error,
        "manual_check": bool((row.review or {}).get("manual_check")), "ai_label": "KI-forslag – må vurderes",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def run_dict(row: IllustrationRun) -> dict[str, Any]:
    return {"id": row.id, "course_id": row.course_id, "status": row.status,
            "status_label": RUN_STATUS_LABELS.get(row.status, row.status), "scope": row.scope, "options": row.options,
            "profile_id": row.profile_id, "job_id": row.job_id, "stats": row.stats or {}, "estimate": row.estimate or {},
            "usage": row.usage or {}, "limitations": row.limitations or [], "error": row.error,
            "contexts": {"course": (row.contexts or {}).get("course"),
                         "modules": (row.contexts or {}).get("modules") or {}},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- runs ------------------------------------------------------------------------------------

    def create_run(self, course_id: str, *, scope: dict[str, Any], options: dict[str, Any],
                   profile_id: int | None) -> dict[str, Any]:
        with self.db.session() as session:
            row = IllustrationRun(course_id=course_id, scope=scope, options=options, profile_id=profile_id)
            session.add(row)
            session.flush()
            return run_dict(row)

    def run(self, run_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(IllustrationRun, run_id)
            if row is None:
                raise NotFoundError("not_found", detail="kjøring")
            return run_dict(row)

    def run_contexts(self, run_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(IllustrationRun, run_id)
            return dict(row.contexts or {}) if row else {}

    def update_run(self, run_id: int, **fields: Any) -> None:
        with self.db.session() as session:
            row = session.get(IllustrationRun, run_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)

    def merge_run_stats(self, run_id: int, **values: Any) -> None:
        with self.db.session() as session:
            row = session.get(IllustrationRun, run_id)
            if row is not None:
                row.stats = {**(row.stats or {}), **values}

    def set_page_state(self, run_id: int, page_url: str, state: dict[str, Any]) -> None:
        with self.db.session() as session:
            row = session.get(IllustrationRun, run_id)
            if row is None:
                return
            stats = dict(row.stats or {})
            pages = dict(stats.get("pages") or {})
            pages[page_url] = {**(pages.get(page_url) or {}), **state}
            stats["pages"] = pages
            row.stats = stats

    def runs(self, course_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(select(IllustrationRun).where(IllustrationRun.course_id == course_id)
                                   .order_by(IllustrationRun.created_at.desc(), IllustrationRun.id.desc())
                                   .limit(limit)).all()
            return [run_dict(r) for r in rows]

    # -- illustrations ---------------------------------------------------------------------------

    def add(self, **fields: Any) -> dict[str, Any]:
        with self.db.session() as session:
            row = Illustration(**fields)
            session.add(row)
            session.flush()
            return illustration_dict(row)

    def get(self, illustration_id: int) -> dict[str, Any]:
        self.refresh_from_changes(illustration_id=illustration_id)
        with self.db.session() as session:
            row = session.get(Illustration, illustration_id)
            if row is None:
                raise NotFoundError("not_found", detail="illustrasjon")
            return illustration_dict(row)

    def update(self, illustration_id: int, **fields: Any) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(Illustration, illustration_id)
            if row is None:
                raise NotFoundError("not_found", detail="illustrasjon")
            for key, value in fields.items():
                setattr(row, key, value)
            session.flush()
            return illustration_dict(row)

    def for_run(self, run_id: int) -> list[dict[str, Any]]:
        self.refresh_from_changes(run_id=run_id)
        with self.db.session() as session:
            rows = session.scalars(select(Illustration).where(Illustration.run_id == run_id)
                                   .order_by(Illustration.position, Illustration.id)).all()
            return [illustration_dict(r) for r in rows]

    def for_page(self, course_id: str, page_url: str, statuses: tuple[str, ...] = EXISTING) -> list[dict[str, Any]]:
        self.refresh_from_changes(course_id=course_id)
        with self.db.session() as session:
            rows = session.scalars(select(Illustration).where(
                Illustration.course_id == course_id, Illustration.page_url == page_url,
                Illustration.status.in_(statuses))).all()
            return [illustration_dict(r) for r in rows]

    def for_course(self, course_id: str, statuses: tuple[str, ...] = EXISTING) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(select(Illustration).where(
                Illustration.course_id == course_id, Illustration.status.in_(statuses))
                .order_by(Illustration.id)).all()
            return [illustration_dict(r) for r in rows]

    def refresh_from_changes(self, *, run_id: int | None = None, course_id: str | None = None,
                             illustration_id: int | None = None) -> None:
        """Illustrations in the change queue follow their change. Only illustrations that are actually part of the
        change are affected: one that was left out when the page's change was rebuilt is released again.

        applied → published (with the inserted figure, for later replacement checks); undone → «Angret»;
        conflict → «Konflikt»; failed → approved (the change can be retried or rebuilt); discarded → approved."""
        with self.db.session() as session:
            query = select(Illustration).where(Illustration.change_id.is_not(None))
            if run_id is not None:
                query = query.where(Illustration.run_id == run_id)
            if course_id is not None:
                query = query.where(Illustration.course_id == course_id)
            if illustration_id is not None:
                query = query.where(Illustration.id == illustration_id)
            rows = session.scalars(query).all()
            changes = {r.change_id for r in rows}
            if not changes:
                return
            by_id = {c.id: c for c in session.scalars(select(StagedChange).where(StagedChange.id.in_(changes))).all()}
            for row in rows:
                change = by_id.get(row.change_id or -1)
                if change is None:
                    row.change_id = None
                    continue
                items = {i.get("illustration_id"): i for i in (change.proposed or {}).get("illustrations") or []}
                if row.id not in items:
                    row.change_id = None  # dropped when the page's change was rebuilt
                    if row.status in ("staged", "conflict"):
                        row.status = "approved"
                    continue
                if change.status == "applied":
                    if row.status in ("staged", "conflict", "approved"):
                        after = (change.result or {}).get("after") or {}
                        files = {f.get("illustration_id"): f for f in after.get("files") or []}
                        info = files.get(row.id) or {}
                        marker = info.get("marker") or items[row.id].get("marker")
                        row.status = "published"
                        row.published = {"file_id": info.get("file_id"), "marker": marker, "src": info.get("src"),
                                         "figure": (after.get("applied_figures") or {}).get(marker),
                                         "html_check": (after.get("html_check") or {}).get(marker),
                                         "page_hash": after.get("page_hash"),
                                         "log_id": (change.result or {}).get("log_id"),
                                         "at": change.applied_at.isoformat() if change.applied_at else None}
                elif change.status == "undone":
                    if row.status == "published":
                        row.status = "undone"
                        row.published = {**(row.published or {}), "figure": None, "undone": True}
                elif change.status == "conflict":
                    if row.status in ("staged", "approved"):
                        row.status = "conflict"
                        row.error = change.error
                elif change.status == "failed":
                    if row.status == "staged":
                        row.status = "approved"
                        row.error = change.error
                elif change.status == "discarded":
                    if row.status in ("staged", "conflict"):
                        row.status = "approved"
                    row.change_id = None

    def open_change_ids(self, illustration_id: int) -> list[int]:
        """The open change (if any) this illustration is part of."""
        with self.db.session() as session:
            row = session.get(Illustration, illustration_id)
            if row is None or row.change_id is None:
                return []
            change = session.get(StagedChange, row.change_id)
            if change is None or change.status not in OPEN_CHANGE:
                return []
            return [change.id]

    def release(self, change_id: int) -> None:
        """Illustrations of a withdrawn change are free again (approved, without a change)."""
        with self.db.session() as session:
            for row in session.scalars(select(Illustration).where(Illustration.change_id == change_id)).all():
                if row.status in ("staged", "conflict"):
                    row.status = "approved"
                row.change_id = None

    # -- analysis cache ----------------------------------------------------------------------------

    def cached(self, course_id: str, object_ref: str, input_hash: str, version: str) -> dict[str, Any] | None:
        with self.db.session() as session:
            row = session.scalars(select(IllustrationAnalysis).where(
                IllustrationAnalysis.course_id == course_id, IllustrationAnalysis.object_ref == object_ref,
                IllustrationAnalysis.input_hash == input_hash, IllustrationAnalysis.version == version)).first()
            return dict(row.data) if row else None

    def cache(self, course_id: str, object_ref: str, input_hash: str, version: str, data: dict[str, Any],
              model: str) -> None:
        with self.db.session() as session:
            existing = session.scalars(select(IllustrationAnalysis).where(
                IllustrationAnalysis.course_id == course_id, IllustrationAnalysis.object_ref == object_ref,
                IllustrationAnalysis.input_hash == input_hash, IllustrationAnalysis.version == version)).first()
            if existing is not None:
                existing.data, existing.model = data, model[:200]
                return
            session.add(IllustrationAnalysis(course_id=course_id, object_ref=object_ref, input_hash=input_hash,
                                             version=version, data=data, model=model[:200]))

    def cached_page_hashes(self, course_id: str, version: str) -> set[tuple[str, str]]:
        """(page url, page hash) pairs that already have a page analysis (for the estimate)."""
        with self.db.session() as session:
            rows = session.scalars(select(IllustrationAnalysis).where(
                IllustrationAnalysis.course_id == course_id, IllustrationAnalysis.object_ref.like("page:%"),
                IllustrationAnalysis.version == version)).all()
            return {(r.object_ref[5:], str((r.data or {}).get("_page_hash") or "")) for r in rows}
