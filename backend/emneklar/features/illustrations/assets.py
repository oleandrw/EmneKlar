"""Generated images on disk (data folder ``illustrations/<course>/``), with thumbnails for the overview."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select

from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.db import Database
from emneklar.core.storage.models import IllustrationAsset

MAX_BYTES = 25 * 1024 * 1024
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
THUMB_SIZE = (360, 240)


def asset_dict(row: IllustrationAsset) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "media_type": row.media_type, "size": row.size, "width": row.width,
            "height": row.height, "model": row.model, "illustration_id": row.illustration_id,
            "canvas_file_id": row.canvas_file_id, "url": f"/api/illustrations/assets/{row.id}",
            "thumb_url": f"/api/illustrations/assets/{row.id}?size=thumb",
            "created_at": row.created_at.isoformat() if row.created_at else None}


class AssetStore:
    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root

    def _path(self, course_id: str, filename: str) -> Path:
        if not course_id.isdigit():
            raise AppError("validation_error", detail="Ugyldig emne-id")
        return self.root / course_id / filename

    def save(self, *, course_id: str, data: bytes, media_type: str, kind: str, model: str, prompt: str,
             illustration_id: int | None) -> dict[str, Any]:
        if len(data) > MAX_BYTES:
            raise AppError("file_too_large", detail="Bildet er for stort")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                actual = Image.MIME.get(image.format or "", media_type)
        except Exception as exc:
            raise AppError("ai_bad_response", status=502, detail="Leverandøren returnerte ikke et gyldig bilde") from exc
        if actual not in EXT:
            raise AppError("ai_bad_response", status=502, detail=f"Uventet bildeformat {actual}")
        asset_id = uuid.uuid4().hex
        filename = f"{asset_id}.{EXT[actual]}"
        path = self._path(course_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        with self.db.session() as session:
            row = IllustrationAsset(id=asset_id, course_id=course_id, illustration_id=illustration_id, kind=kind,
                                    filename=filename, sha256=hashlib.sha256(data).hexdigest(), media_type=actual,
                                    size=len(data), width=width, height=height, model=model[:200],
                                    prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest())
            session.add(row)
            session.flush()
            return asset_dict(row)

    def get(self, asset_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(IllustrationAsset, asset_id)
            if row is None:
                raise NotFoundError("not_found", detail="bilde")
            return {**asset_dict(row), "course_id": row.course_id, "filename": row.filename, "sha256": row.sha256}

    def path(self, asset_id: str) -> Path:
        info = self.get(asset_id)
        path = self._path(info["course_id"], info["filename"])
        if not path.is_file():
            raise NotFoundError("not_found", detail="Bildefilen finnes ikke lenger i datamappen")
        return path

    def read(self, asset_id: str) -> tuple[bytes, str]:
        info = self.get(asset_id)
        data = self.path(asset_id).read_bytes()
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise AppError("file_parse_failed", message="Bildefilen er endret eller skadet i datamappen.")
        return data, info["media_type"]

    def thumbnail(self, asset_id: str) -> Path:
        source = self.path(asset_id)
        thumb = source.with_name(f"{source.stem}.thumb.webp")
        if not thumb.is_file():
            with Image.open(source) as image:
                image.thumbnail(THUMB_SIZE)
                image.convert("RGB").save(thumb, "WEBP", quality=80)
        return thumb

    def display_data_url(self, asset_id: str, max_side: int = 1200) -> str:
        """A smaller WebP copy as a data URL (for the sandboxed page preview, which cannot use the session)."""
        import base64

        source = self.path(asset_id)
        copy = source.with_name(f"{source.stem}.display.webp")
        if not copy.is_file():
            with Image.open(source) as image:
                image.thumbnail((max_side, max_side))
                image.convert("RGB").save(copy, "WEBP", quality=82)
        return "data:image/webp;base64," + base64.b64encode(copy.read_bytes()).decode("ascii")

    def set_canvas_file(self, asset_id: str, file_id: str) -> None:
        with self.db.session() as session:
            row = session.get(IllustrationAsset, asset_id)
            if row is not None:
                row.canvas_file_id = file_id

    def for_illustration(self, illustration_id: int) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(select(IllustrationAsset).where(IllustrationAsset.illustration_id == illustration_id)
                                   .order_by(IllustrationAsset.created_at)).all()
            return [asset_dict(r) for r in rows]
