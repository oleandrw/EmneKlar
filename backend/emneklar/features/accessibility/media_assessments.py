"""The teacher's statement of what a recording is (audio only, video with sound, video without sound).

Stored per course and media key (see media_kinds.media_keys) and used by later analyses before Canvas' metadata. It
only steers which requirement EmneKlar checks (WCAG 1.2.1 or 1.2.2); nothing is written to Canvas.
"""

from __future__ import annotations

from sqlalchemy import select

from emneklar.core.errors import AppError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import MediaAssessment
from emneklar.features.accessibility.media_kinds import USER_KINDS


def load_assessments(db: Database, course_id: str) -> dict[str, str]:
    with db.session() as session:
        rows = session.scalars(select(MediaAssessment).where(MediaAssessment.course_id == course_id)).all()
        return {row.media_key: row.kind for row in rows}


def save_assessment(db: Database, course_id: str, media_key: str, kind: str | None) -> None:
    """Store the kind (``None`` removes the statement, so Canvas' metadata applies again)."""
    if kind is not None and kind not in USER_KINDS:
        raise AppError("validation_error", status=422, detail=f"Ukjent medietype: {kind}")
    with db.session() as session:
        row = session.get(MediaAssessment, (course_id, media_key))
        if kind is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(MediaAssessment(course_id=course_id, media_key=media_key, kind=kind))
        else:
            row.kind = kind
