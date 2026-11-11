"""Rapporter: create, list, view, download and delete reports (stored under %LOCALAPPDATA%\\EmneKlar\\reports)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.models import Report
from emneklar.features.findings.store import FindingStore
from emneklar.features.reporting.data import REPORT_TYPES, collect
from emneklar.features.reporting.render import render_csv, render_html

router = APIRouter(prefix="/api")
FORMATS = {"html": ("text/html; charset=utf-8", "html"), "csv": ("text/csv; charset=utf-8", "csv")}


def report_dict(row: Report) -> dict[str, Any]:
    return {"id": row.id, "course_id": row.course_id, "report_type": row.report_type,
            "type_label": REPORT_TYPES.get(row.report_type, (row.report_type,))[0], "format": row.fmt,
            "title": row.title, "filename": row.filename, "size": row.size,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _path(c: AppContainer, row: Report) -> Path:
    root = c.config.reports_dir.resolve()
    path = (root / row.course_id / row.filename).resolve()
    if root not in path.parents:
        raise NotFoundError("report_not_found")
    return path


def _get(c: AppContainer, report_id: int) -> Report:
    with c.db.session() as session:
        row = session.get(Report, report_id)
        if row is None:
            raise NotFoundError("report_not_found")
        session.expunge(row)
        return row


@router.get("/courses/{course_id}/reports/types")
async def report_types(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    store = FindingStore(c.db)
    analysed = {d: bool(store.runs_for(course_id, d)) for d in ("accessibility", "content_quality", "structure", "quiz")}
    return {"types": [{"value": key, "label": label,
                       "analysed": any(analysed.get(d, False) for d in domains if d != "quiz_ai")}
                      for key, (label, domains) in REPORT_TYPES.items()],
            "formats": [{"value": "html", "label": "HTML (kan skrives ut eller lagres som PDF)"},
                        {"value": "csv", "label": "CSV (for Excel)"}]}


class ReportRequest(BaseModel):
    report_type: Literal["full", "accessibility", "content_quality", "structure", "quiz"]
    format: Literal["html", "csv"] = "html"


@router.post("/courses/{course_id}/reports")
async def create_report(course_id: str, body: ReportRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    course_id = require_course_id(course_id)
    data = collect(c, course_id, body.report_type)
    if not any(d.analysed for d in data.domains):
        raise AppError("validation_error", message="Det finnes ingen analyse for dette området ennå. Kjør en analyse "
                                                   "først.")
    content = render_html(data).encode("utf-8") if body.format == "html" else render_csv(data)
    slug = re.sub(r"[^a-z0-9]+", "-", data.title.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a"))
    filename = f"{slug.strip('-')}-{course_id}-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.{body.format}"
    folder = c.config.reports_dir / course_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(content)
    with c.db.session() as session:
        row = Report(course_id=course_id, report_type=body.report_type, fmt=body.format,
                     title=f"{data.title} – {data.course_name}", filename=filename, size=len(content),
                     run_ids=data.run_ids)
        session.add(row)
        session.flush()
        session.expunge(row)
    return report_dict(row)


@router.get("/reports")
async def list_reports(course_id: str | None = None, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    with c.db.session() as session:
        query = select(Report).order_by(Report.created_at.desc()).limit(100)
        if course_id:
            query = query.where(Report.course_id == require_course_id(course_id))
        return {"items": [report_dict(r) for r in session.scalars(query).all()]}


@router.get("/reports/{report_id}/download")
async def download(report_id: int, c: AppContainer = Depends(get_container)) -> FileResponse:
    row = _get(c, report_id)
    path = _path(c, row)
    if not path.is_file():
        raise NotFoundError("report_not_found")
    media_type = FORMATS[row.fmt][0]
    return FileResponse(path, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename=\"{row.filename}\"; filename*=UTF-8''{quote(row.filename)}"})


@router.get("/reports/{report_id}/view", response_class=HTMLResponse)
async def view(report_id: int, c: AppContainer = Depends(get_container)) -> HTMLResponse:
    """The HTML report in its own tab – print it from there, or «Lagre som PDF»."""
    row = _get(c, report_id)
    if row.fmt != "html":
        raise AppError("unsupported", message="Bare HTML-rapporter kan vises.")
    path = _path(c, row)
    if not path.is_file():
        raise NotFoundError("report_not_found")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.delete("/reports/{report_id}")
async def delete_report(report_id: int, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    row = _get(c, report_id)
    path = _path(c, row)
    path.unlink(missing_ok=True)
    with c.db.session() as session:
        stored = session.get(Report, report_id)
        if stored is not None:
            session.delete(stored)
    return {"ok": True}
