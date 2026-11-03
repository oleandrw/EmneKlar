"""Citation labels: [Sidetittel – Modul], [Video «…» – 12:34], [Fil.pdf s. 4], [Bilde på «Sidetittel»]."""

from __future__ import annotations

from typing import Any

from emneklar.features.course_rag.store import ChunkRecord


def timestamp(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def citation(chunk: ChunkRecord | Any) -> str:
    meta = chunk.meta or {}
    if chunk.type == "transcript" or (chunk.type == "image" and chunk.start is not None):
        title = meta.get("video_title") or chunk.title
        label = f"Video «{title}»" if title else "Video"
        return f"{label} – {timestamp(chunk.start)}"
    if chunk.type == "image":
        page = meta.get("page_title") or chunk.title
        return f"Bilde på «{page}»"
    if chunk.item_kind == "file":
        name = chunk.title
        fmt = meta.get("format")
        if chunk.page:
            if fmt in ("pptx", "odp"):
                return f"{name} lysbilde {chunk.page}"
            if fmt == "pdf":
                pages = f"{chunk.page}–{chunk.page_end}" if chunk.page_end and chunk.page_end != chunk.page else \
                    str(chunk.page)
                return f"{name} s. {pages}"
        sheet = meta.get("sheet")
        return f"{name}, {sheet}" if sheet else name
    return f"{chunk.title} – {chunk.module_name}" if chunk.module_name else chunk.title
