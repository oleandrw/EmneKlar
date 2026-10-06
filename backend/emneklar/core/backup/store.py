"""Backups of Canvas objects taken immediately before EmneKlar changes them.

Stored as JSON files under ``%LOCALAPPDATA%\\EmneKlar\\backups\\objects`` with
random file names (never derived from user/Canvas input) and a SHA-256 in the
database. Backups are read back only by database id.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from emneklar.core.errors import NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import Backup


class BackupStore:
    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root / "objects"

    def save(self, *, course_id: str | None, object_type: str, object_id: str, title: str, state: dict[str, Any],
             change_id: int | None) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"saved_at": datetime.now(UTC).isoformat(), "course_id": course_id,
                              "object_type": object_type, "object_id": object_id, "title": title, "state": state},
                             ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(6)}.json"
        (self.root / filename).write_bytes(payload)
        with self.db.session() as session:
            row = Backup(course_id=course_id, object_type=object_type, object_id=object_id, title=title[:1000],
                         filename=filename, sha256=hashlib.sha256(payload).hexdigest(), size=len(payload),
                         change_id=change_id)
            session.add(row)
            session.flush()
            return row.id

    def load(self, backup_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(Backup, backup_id)
            if row is None:
                raise NotFoundError("not_found", detail="sikkerhetskopi")
            filename, digest = row.filename, row.sha256
        path = self.root / filename
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise NotFoundError("not_found", detail="Sikkerhetskopien er endret eller skadet")
        return json.loads(data)

    def list(self, course_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            query = select(Backup).order_by(Backup.created_at.desc()).limit(limit)
            if course_id:
                query = query.where(Backup.course_id == course_id)
            return [{"id": r.id, "created_at": r.created_at.isoformat(), "course_id": r.course_id,
                     "object_type": r.object_type, "object_id": r.object_id, "title": r.title, "size": r.size,
                     "change_id": r.change_id} for r in session.scalars(query).all()]
