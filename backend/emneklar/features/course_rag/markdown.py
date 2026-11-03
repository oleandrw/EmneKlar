"""Structured Markdown as a list of blocks – the common format every converter produces.

Converters (HTML, PDF, Office, OpenDocument …) emit :class:`Block` objects directly instead of Markdown text,
so chunking never has to re-parse Markdown. :func:`to_markdown` renders the same blocks for export, and
:func:`parse_markdown` reads Markdown/plain-text files into blocks.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

BLOCK_KINDS = ("heading", "paragraph", "list", "table", "code", "quote")
MAX_CELL = 400


@dataclass
class Block:
    kind: str  # heading | paragraph | list | table | code | quote
    text: str = ""  # Markdown for everything except tables (see rows)
    level: int = 0  # heading level 1–6
    page: int | None = None  # PDF page or slide number
    rows: list[list[str]] = field(default_factory=list)  # tables: header row first

    def markdown(self) -> str:
        if self.kind == "heading":
            return f"{'#' * max(1, min(6, self.level))} {self.text}"
        if self.kind == "table":
            return table_markdown(self.rows)
        if self.kind == "code":
            return f"```\n{self.text}\n```"
        if self.kind == "quote":
            return "\n".join(f"> {line}" for line in self.text.splitlines())
        return self.text

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Block:
        return cls(kind=str(data.get("kind") or "paragraph"), text=str(data.get("text") or ""),
                   level=int(data.get("level") or 0), page=data.get("page"),
                   rows=[[str(c) for c in row] for row in data.get("rows") or []])


def clean_cell(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")
    return text[:MAX_CELL]


def table_markdown(rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [[clean_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    header, body = padded[0], padded[1:]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def to_markdown(blocks: list[Block]) -> str:
    return "\n\n".join(m for m in (b.markdown() for b in blocks) if m.strip())


def plain_text(markdown: str) -> str:
    """Markdown without the most common markup (for snippets)."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*\|?\s*-{3,}.*$", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def parse_markdown(text: str, *, plain: bool = False) -> list[Block]:
    """Markdown (or, with ``plain``, plain text where only blank lines separate paragraphs) → blocks."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            joined = "\n".join(para).strip()
            if joined:
                is_list = not plain and all(_LIST.match(p) or p.startswith("  ") for p in para) and _LIST.match(para[0])
                blocks.append(Block("list" if is_list else "paragraph", joined if is_list else re.sub(r"\s*\n\s*", " ",
                                                                                                      joined)))
            para.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if not plain:
            heading = _HEADING.match(line)
            if heading:
                flush()
                blocks.append(Block("heading", heading.group(2).strip().rstrip("#").strip(), level=len(heading.group(1))))
                i += 1
                continue
            if line.strip().startswith("```"):
                flush()
                code: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    i += 1
                blocks.append(Block("code", "\n".join(code)))
                i += 1
                continue
            if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
                flush()
                rows = [_split_row(line)]
                i += 2
                while i < len(lines) and "|" in lines[i] and lines[i].strip():
                    rows.append(_split_row(lines[i]))
                    i += 1
                blocks.append(Block("table", rows=[[c.replace("\\|", "|") for c in r] for r in rows]))
                continue
            if line.lstrip().startswith(">"):
                flush()
                quote: list[str] = []
                while i < len(lines) and lines[i].lstrip().startswith(">"):
                    quote.append(lines[i].lstrip()[1:].strip())
                    i += 1
                blocks.append(Block("quote", "\n".join(quote)))
                continue
            if _LIST.match(line) and para and not _LIST.match(para[0]):
                flush()
        para.append(line.rstrip())
        i += 1
    flush()
    return blocks
