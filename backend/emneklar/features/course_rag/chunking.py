"""Structure-based chunking.

1. Split on headings first; every chunk carries its heading path (``Modul › Side › Overskrift``).
2. Within a section, paragraphs and lists are packed up to ~450 tokens (300–600); only a block that is longer
   than the maximum is split further (sentences, then words) – recursive splitting is the exception.
3. Consecutive chunks of the same section overlap by ~12 % (whole sentences).
4. Very short sections are merged with the next one instead of becoming tiny chunks; the merged chunk keeps the
   sub-headings in its text and the common part of the heading path.
5. Tables are their own chunks (``type: table``) in Markdown; long tables are split by rows with the header
   repeated. Slides are one chunk each (``type: slide``) including speaker notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from emneklar.features.course_rag.markdown import Block, table_markdown
from emneklar.features.course_rag.text import estimate_tokens

CHUNKER_VERSION = "1"
TARGET_TOKENS = 450
MAX_TOKENS = 600
MIN_TOKENS = 80
OVERLAP_TOKENS = 55  # ≈ 12 % of the target
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÆØÅ0-9«\"(])")


@dataclass
class ChunkDraft:
    type: str  # text | table | image | transcript | slide
    text: str
    heading_path: list[str] = field(default_factory=list)
    page: int | None = None
    page_end: int | None = None
    start: float | None = None  # seconds (video)
    end: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text.strip()) if s]


def split_long(text: str, limit: int = TARGET_TOKENS) -> list[str]:
    """Split one over-long block into pieces of at most ``limit`` tokens: list items, sentences, then words."""
    lines = text.split("\n")
    units = lines if len(lines) > 1 else sentences(text)
    if len(units) <= 1:
        words = text.split()
        step = max(1, int(limit / 1.4))
        return [" ".join(words[i:i + step]) for i in range(0, len(words), step)]
    pieces: list[str] = []
    current: list[str] = []
    tokens = 0
    joiner = "\n" if len(lines) > 1 else " "
    for unit in units:
        size = estimate_tokens(unit)
        if size > limit:
            if current:
                pieces.append(joiner.join(current))
                current, tokens = [], 0
            pieces.extend(split_long(unit, limit) if unit != text else [unit])
            continue
        if current and tokens + size > limit:
            pieces.append(joiner.join(current))
            current, tokens = [], 0
        current.append(unit)
        tokens += size
    if current:
        pieces.append(joiner.join(current))
    return pieces


def _tail(text: str, tokens: int = OVERLAP_TOKENS) -> str:
    """The last whole sentences of ``text`` amounting to about ``tokens`` tokens (the overlap)."""
    picked: list[str] = []
    total = 0
    for sentence in reversed(sentences(text.replace("\n", " "))):
        size = estimate_tokens(sentence)
        if picked and total + size > tokens * 2:
            break
        picked.insert(0, sentence)
        total += size
        if total >= tokens:
            break
    tail = " ".join(picked)
    return tail if estimate_tokens(tail) < estimate_tokens(text) else ""


def _common(a: list[str], b: list[str]) -> list[str]:
    out = []
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        out.append(x)
    return out


class _Packer:
    def __init__(self, kind: str, chunks: list[ChunkDraft]) -> None:
        self.kind = kind
        self.chunks = chunks
        self.parts: list[str] = []
        self.tokens = 0
        self.path: list[str] = []  # heading path shown for the chunk (common part when sections were merged)
        self.section: list[str] = []  # the section the last added text belongs to
        self.pages: list[int] = []
        self.overlap_only = False

    def _emit(self) -> None:
        if not self.parts or self.overlap_only:
            return
        text = "\n\n".join(self.parts).strip()
        if text:
            pages = sorted(set(self.pages))
            self.chunks.append(ChunkDraft(self.kind, text, list(self.path), page=pages[0] if pages else None,
                                          page_end=pages[-1] if len(pages) > 1 else None))

    def flush(self, *, overlap: bool = False) -> None:
        last = self.parts[-1] if self.parts else ""
        self._emit()
        self.parts, self.tokens, self.pages = [], 0, []
        self.overlap_only = False
        if overlap and last:
            tail = _tail(last)
            if tail:
                self.parts, self.tokens, self.overlap_only = [tail], estimate_tokens(tail), True

    def add(self, text: str, path: list[str], page: int | None, *, heading: Block | None = None) -> None:
        size = estimate_tokens(text)
        if size > MAX_TOKENS:
            for piece in split_long(text):
                self.add(piece, path, page, heading=heading)
                heading = None
            return
        if self.parts and path != self.section:
            if self.overlap_only:  # no overlap across sections
                self.parts, self.tokens, self.overlap_only = [], 0, False
            elif self.tokens >= MIN_TOKENS or self.tokens + size > MAX_TOKENS:
                self.flush()
            else:  # merge a short section into the next one, keeping the headings in the text
                common = _common(self.path, path)
                lost = self.path[len(common):]
                if lost:
                    self.parts.insert(0, f"{'#' * min(6, len(common) + 2)} {lost[-1]}")
                self.path = common
                if heading is not None:
                    self.parts.append(heading.markdown())
                    self.tokens += estimate_tokens(heading.text)
        elif self.parts and not self.overlap_only and self.tokens + size > TARGET_TOKENS:
            self.flush(overlap=True)
        if self.overlap_only and self.tokens + size > MAX_TOKENS:
            self.parts, self.tokens, self.overlap_only = [], 0, False
        if not self.parts or self.overlap_only:
            self.path = list(path)
        self.section = list(path)
        self.parts.append(text)
        self.tokens += size
        self.overlap_only = False
        if page is not None:
            self.pages.append(page)


def table_chunks(block: Block, path: list[str]) -> list[ChunkDraft]:
    rows = [r for r in block.rows if any(c.strip() for c in r)]
    if not rows:
        return []
    header, body = rows[0], rows[1:] or []
    out: list[ChunkDraft] = []
    group: list[list[str]] = []
    for row in body:
        candidate = [header, *group, row]
        if group and estimate_tokens(table_markdown(candidate).replace("|", " ")) > MAX_TOKENS:
            out.append(ChunkDraft("table", table_markdown([header, *group]), list(path), page=block.page))
            group = []
        group.append(row)
    out.append(ChunkDraft("table", table_markdown([header, *group]) if group or not body else table_markdown([header]),
                          list(path), page=block.page, meta={"rows": len(rows)}))
    return out


def chunk_blocks(blocks: list[Block], *, base_path: list[str] | None = None, kind: str = "text") -> list[ChunkDraft]:
    base = list(base_path or [])
    chunks: list[ChunkDraft] = []
    packer = _Packer(kind, chunks)
    stack: list[tuple[int, str]] = []
    heading: Block | None = None
    for block in blocks:
        if block.kind == "heading":
            stack = [h for h in stack if h[0] < block.level] + [(block.level, block.text)]
            heading = block
            continue
        path = base + [t for _, t in stack]
        if block.kind == "table":
            packer.flush()
            chunks.extend(table_chunks(block, path))
            heading = None
            continue
        text = block.markdown().strip()
        if text:
            packer.add(text, path, block.page, heading=heading)
            heading = None
    packer.flush()
    return _merge_small(chunks)


def _merge_small(chunks: list[ChunkDraft]) -> list[ChunkDraft]:
    """A tiny trailing text chunk (e.g. a short last section after a table) joins the previous text chunk."""
    out: list[ChunkDraft] = []
    for chunk in chunks:
        prev = next((c for c in reversed(out) if c.type == chunk.type == "text"), None)
        if (chunk.type == "text" and prev is not None and out[-1] is prev and chunk.tokens < MIN_TOKENS // 2
                and prev.tokens + chunk.tokens <= MAX_TOKENS):
            extra = chunk.heading_path[len(_common(prev.heading_path, chunk.heading_path)):]
            heading = f"{'#' * min(6, 2 + len(_common(prev.heading_path, chunk.heading_path)))} {extra[-1]}\n\n" \
                if extra else ""
            prev.text = f"{prev.text}\n\n{heading}{chunk.text}"
            prev.heading_path = _common(prev.heading_path, chunk.heading_path)
            prev.page_end = chunk.page_end or chunk.page or prev.page_end
            continue
        out.append(chunk)
    return out


def chunk_units(units: list[dict[str, Any]], *, title: str) -> list[ChunkDraft]:
    """Units from the document converter (pages, slides, sheets, whole documents) → chunks."""
    chunks: list[ChunkDraft] = []
    flowing: list[Block] = []  # PDF pages and documents flow into one structure (page numbers kept per block)
    for unit in units:
        kind = unit.get("kind")
        blocks = [Block.from_dict(b) for b in unit.get("blocks") or []]
        number = unit.get("number")
        if kind == "slide":
            slide_title = unit.get("title") or f"Lysbilde {number}"
            parts = [b.markdown() for b in blocks if b.kind != "table"]
            notes = unit.get("notes")
            body = "\n\n".join(p for p in [f"## {slide_title}", *parts] if p.strip())
            if notes:
                body += f"\n\nNotater: {notes}"
            if estimate_tokens(body) > MAX_TOKENS:
                for piece in split_long(body):
                    chunks.append(ChunkDraft("slide", piece, [slide_title], page=number))
            else:
                chunks.append(ChunkDraft("slide", body, [slide_title], page=number))
            for block in blocks:
                if block.kind == "table":
                    block.page = number
                    chunks.extend(table_chunks(block, [slide_title]))
        elif kind == "sheet":
            sheet = unit.get("title") or f"Ark {number}"
            for block in blocks:
                if block.kind == "table":
                    chunks.extend(table_chunks(block, [sheet]))
        else:
            for block in blocks:
                if block.page is None and number is not None:
                    block.page = number
            flowing.extend(blocks)
    if flowing:
        chunks = chunk_blocks(flowing) + chunks
    return chunks
