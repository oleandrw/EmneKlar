"""Course files → structured Markdown blocks, one unit per page / slide / sheet.

Runs inside an isolated worker process (``core/security/isolation.py``, job ``rag_convert``): course files are
untrusted. Office and OpenDocument files are read with the same hardened ZIP reader and ``defusedxml`` as the
accessibility document checks – no macro, external entity or embedded object is ever executed or followed.

Formats: PDF (pypdf; scanned PDFs are reported as ``needs_ocr``), DOCX, PPTX (incl. speaker notes), XLSX,
ODT, ODP, ODS, RTF, CSV, TXT, Markdown, HTML and subtitle files (WebVTT/SRT). The old binary formats DOC/PPT/XLS
cannot be read safely without Office or LibreOffice and are reported as unsupported.
"""

from __future__ import annotations

import csv
import io
import logging
import posixpath
import re
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET

from emneklar.core.security.safe_zip import SafeZip, ZipLimits
from emneklar.features.course_rag.markdown import Block, parse_markdown

log = logging.getLogger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODF_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
ODF_PRES = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"

#: Format groups the user can choose between (Emne-RAG → Kildetyper).
FILE_GROUPS: dict[str, tuple[str, ...]] = {
    "pdf": ("pdf",),
    "word": ("docx", "odt", "rtf"),
    "powerpoint": ("pptx", "odp"),
    "excel": ("xlsx", "ods", "csv"),
    "text": ("txt", "md", "html", "htm"),
}
GROUP_LABELS = {"pdf": "PDF", "word": "Word og tekstdokumenter (DOCX, ODT, RTF)",
                "powerpoint": "Presentasjoner (PPTX, ODP)", "excel": "Regneark (XLSX, ODS, CSV)",
                "text": "Tekstfiler (TXT, Markdown, HTML)"}
DOCUMENT_FORMATS = {fmt for group in FILE_GROUPS.values() for fmt in group}
SUBTITLE_FORMATS = {"vtt", "srt"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_FORMATS = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}
AUDIO_FORMATS = {"mp3", "m4a", "wav", "ogg", "aac", "flac"}
LEGACY_FORMATS = {"doc": "Word 97–2003 (.doc)", "ppt": "PowerPoint 97–2003 (.ppt)", "xls": "Excel 97–2003 (.xls)"}
CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/rtf": "rtf", "text/rtf": "rtf", "text/plain": "txt", "text/markdown": "md", "text/csv": "csv",
    "text/html": "html", "text/vtt": "vtt", "application/x-subrip": "srt",
    "application/msword": "doc", "application/vnd.ms-powerpoint": "ppt", "application/vnd.ms-excel": "xls",
}
MAX_CHARS = 3_000_000
MAX_UNITS = 3000
MAX_SHEET_ROWS = 1000
MAX_SHEET_COLS = 40
MAX_REPEAT = 50
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def file_format(name: str, content_type: str | None = None) -> str | None:
    ext = name.lower().rsplit(".", 1)[-1] if "." in (name or "") else ""
    if ext == "jpeg":
        return "jpg"
    if ext in DOCUMENT_FORMATS | SUBTITLE_FORMATS | IMAGE_FORMATS | VIDEO_FORMATS | AUDIO_FORMATS | set(LEGACY_FORMATS):
        return ext
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in CONTENT_TYPES:
        return CONTENT_TYPES[ct]
    if ct.startswith("image/"):
        sub = ct.split("/", 1)[1]
        return "jpg" if sub == "jpeg" else sub if sub in IMAGE_FORMATS else None
    if ct.startswith("video/"):
        return "mp4"
    if ct.startswith("audio/"):
        return "mp3"
    return None


def group_of(fmt: str) -> str | None:
    return next((group for group, formats in FILE_GROUPS.items() if fmt in formats), None)


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _norm(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", text or "").strip()


class _Out:
    """Collects units and extracted images within the limits."""

    def __init__(self, fmt: str, out_dir: str | None, max_images: int) -> None:
        self.fmt = fmt
        self.units: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.chars = 0
        self.out_dir = Path(out_dir) if out_dir else None
        self.max_images = max_images
        self.title: str | None = None
        self.needs_ocr = False
        self.pages: int | None = None

    def unit(self, kind: str, number: int | None, blocks: list[Block], *, title: str | None = None,
             notes: str | None = None) -> None:
        if len(self.units) >= MAX_UNITS:
            if "units" not in self.warnings:
                self.warnings.append("units")
            return
        size = sum(len(b.text) + sum(len(c) for r in b.rows for c in r) for b in blocks) + len(notes or "")
        if self.chars + size > MAX_CHARS:
            if "truncated" not in self.warnings:
                self.warnings.append("truncated")
            return
        self.chars += size
        self.units.append({"kind": kind, "number": number, "title": title, "notes": notes,
                           "blocks": [b.as_dict() for b in blocks]})

    def image(self, data: bytes, name: str, *, alt: str | None, unit: int | None) -> None:
        if self.out_dir is None or len(self.images) >= self.max_images or len(data) > MAX_IMAGE_BYTES:
            return
        ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
            return  # EMF/WMF/SVG and other vector formats cannot be described by an image model
        self.out_dir.mkdir(parents=True, exist_ok=True)
        target = self.out_dir / f"bilde-{len(self.images) + 1}.{ext}"
        target.write_bytes(data)
        self.images.append({"path": str(target), "name": posixpath.basename(name), "alt": alt, "unit": unit})

    def result(self) -> dict[str, Any]:
        return {"format": self.fmt, "units": self.units, "images": self.images, "warnings": self.warnings,
                "title": self.title, "needs_ocr": self.needs_ocr, "pages": self.pages}


# ------------------------------------------------------------------------------------------------- PDF

_BULLET = re.compile(r"^\s*(?:[•▪◦‣∙·●○■□–\-*]|\d{1,2}[.)])\s+")
_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+){0,3}\.?|[IVX]+\.)\s+[A-ZÆØÅ]")


def _looks_like_heading(line: str) -> bool:
    """Conservative: short lines in capitals («1. INNLEDNING») or with section numbers («2.3 Fargerom»)."""
    words = line.split()
    if not words or len(words) > 10 or len(line) > 90 or line.endswith((".", ",", ";", ":", "?", "!")):
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters):
        return True
    return bool(_NUMBERED_HEADING.match(line)) and bool(re.match(r"^\d+\.\d+", line))


def text_to_blocks(text: str, *, page: int | None = None) -> list[Block]:
    """Plain text extracted from a PDF page → paragraphs, lists and (conservatively detected) headings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # words hyphenated across lines
    lines = [_norm(line) for line in text.split("\n")]
    blocks: list[Block] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block("paragraph", " ".join(para), page=page))
            para.clear()
        if items:
            blocks.append(Block("list", "\n".join(f"- {i}" for i in items), page=page))
            items.clear()

    widths = [len(line) for line in lines if line]
    typical = sorted(widths)[len(widths) // 2] if widths else 0
    for line in lines:
        if not line:
            flush()
            continue
        if _looks_like_heading(line):
            flush()
            blocks.append(Block("heading", line.title() if line.isupper() else line, level=2, page=page))
            continue
        if _BULLET.match(line):
            if para:
                flush()
            items.append(_BULLET.sub("", line, count=1))
            continue
        if items and not para and len(line) < typical * 1.1 and not line[:1].isupper():
            items[-1] += " " + line  # continuation of a list item
            continue
        if items:
            flush()
        para.append(line)
        # A short line ending a sentence usually ends a paragraph.
        if typical and len(line) < typical * 0.7 and line.endswith((".", "?", "!", ":")):
            flush()
    flush()
    return blocks


def convert_pdf(path: Path, out: _Out) -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                out.warnings.append("encrypted")
                return
        except Exception:  # noqa: BLE001 - any failure means we cannot read it
            out.warnings.append("encrypted")
            return
    metadata = reader.metadata
    out.title = (metadata.title or "").strip() or None if metadata and metadata.title else None
    out.pages = len(reader.pages)
    total = 0
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - broken content streams are skipped page by page
            text = ""
        total += len(re.sub(r"\s+", "", text))
        blocks = text_to_blocks(text, page=number)
        if blocks:
            out.unit("page", number, blocks)
    if out.pages and total < 10 * out.pages:
        out.needs_ocr = True


# ----------------------------------------------------------------------------------------- OOXML helpers


def _rels(zf: SafeZip, part: str) -> dict[str, str]:
    """Relationship id → target path (resolved relative to the part)."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if not zf.has(rels_name):
        return {}
    root = SafeET.fromstring(zf.read(rels_name))
    result = {}
    for rel in root.iter(f"{REL}Relationship"):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            continue
        result[rel.get("Id") or ""] = posixpath.normpath(posixpath.join(folder, target)) if not target.startswith(
            "/") else target.lstrip("/")
    return result


def _rel_types(zf: SafeZip, part: str) -> dict[str, str]:
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if not zf.has(rels_name):
        return {}
    root = SafeET.fromstring(zf.read(rels_name))
    return {rel.get("Id") or "": rel.get("Type") or "" for rel in root.iter(f"{REL}Relationship")}


def _core_title(zf: SafeZip) -> str | None:
    if not zf.has("docProps/core.xml"):
        return None
    root = SafeET.fromstring(zf.read("docProps/core.xml"))
    title = root.find("{http://purl.org/dc/elements/1.1/}title")
    return ((title.text or "").strip() or None) if title is not None else None


# ------------------------------------------------------------------------------------------------- DOCX


def _docx_styles(zf: SafeZip) -> dict[str, int]:
    """Paragraph style id → heading level (1–6) for heading/title styles."""
    if not zf.has("word/styles.xml"):
        return {}
    root = SafeET.fromstring(zf.read("word/styles.xml"))
    levels: dict[str, int] = {}
    for style in root.iter(f"{W}style"):
        sid = style.get(f"{W}styleId") or ""
        name_el = style.find(f"{W}name")
        name = (name_el.get(f"{W}val") if name_el is not None else "") or sid
        outline = style.find(f"{W}pPr/{W}outlineLvl")
        match = re.match(r"(?i)^(?:heading|overskrift|rubrik)\s*(\d)", name) or re.match(r"(?i)^heading(\d)$", sid)
        if match:
            levels[sid] = min(6, int(match.group(1)))
        elif re.match(r"(?i)^(title|tittel)$", name):
            levels[sid] = 1
        elif outline is not None and (outline.get(f"{W}val") or "").isdigit():
            levels[sid] = min(6, int(outline.get(f"{W}val") or "0") + 1)
    return levels


def _docx_par_text(p: Any) -> str:
    parts: list[str] = []
    for el in p.iter():
        tag = el.tag
        if tag == f"{W}t":
            parts.append(el.text or "")
        elif tag in (f"{W}tab", f"{W}ptab"):
            parts.append(" ")
        elif tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "\n".join(_norm(line) for line in "".join(parts).split("\n")).strip()


def convert_docx(path: Path, out: _Out) -> None:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        out.title = _core_title(zf)
        root = SafeET.fromstring(zf.read("word/document.xml"))
        styles = _docx_styles(zf)
        rels = _rels(zf, "word/document.xml")
        body = root.find(f"{W}body")
        blocks: list[Block] = []
        list_lines: list[str] = []

        def flush_list() -> None:
            if list_lines:
                blocks.append(Block("list", "\n".join(list_lines)))
                list_lines.clear()

        def images_in(el: Any) -> None:
            for drawing in el.iter():
                if drawing.tag not in (f"{WP}inline", f"{WP}anchor"):
                    continue
                doc_pr = drawing.find(f"{WP}docPr")
                alt = (doc_pr.get("descr") or doc_pr.get("title") or "").strip() if doc_pr is not None else ""
                blip = drawing.find(f".//{A}blip")
                rid = blip.get(f"{R}embed") if blip is not None else None
                target = rels.get(rid or "")
                if target and zf.has(target):
                    try:
                        out.image(zf.read(target, max_bytes=MAX_IMAGE_BYTES), target, alt=alt or None, unit=1)
                    except Exception:  # noqa: BLE001, S112 - an unreadable image is skipped
                        continue

        def walk(container: Any) -> None:
            for el in list(container):
                if el.tag == f"{W}p":
                    images_in(el)
                    text = _docx_par_text(el)
                    if not text:
                        continue
                    ppr = el.find(f"{W}pPr")
                    style = ppr.find(f"{W}pStyle") if ppr is not None else None
                    sid = (style.get(f"{W}val") if style is not None else "") or ""
                    outline = ppr.find(f"{W}outlineLvl") if ppr is not None else None
                    level = styles.get(sid)
                    if level is None and outline is not None and (outline.get(f"{W}val") or "").isdigit():
                        level = min(6, int(outline.get(f"{W}val") or "0") + 1)
                    numbered = ppr is not None and ppr.find(f"{W}numPr") is not None
                    if level and len(text) <= 200:
                        flush_list()
                        blocks.append(Block("heading", text.replace("\n", " "), level=level))
                    elif numbered or re.match(r"(?i)^list", sid):
                        ilvl = ppr.find(f"{W}numPr/{W}ilvl") if ppr is not None else None
                        depth = int(ilvl.get(f"{W}val") or "0") if ilvl is not None and (
                            ilvl.get(f"{W}val") or "").isdigit() else 0
                        list_lines.append(f"{'  ' * min(depth, 6)}- {text.replace(chr(10), ' ')}")
                    else:
                        flush_list()
                        blocks.append(Block("paragraph", text))
                elif el.tag == f"{W}tbl":
                    flush_list()
                    images_in(el)
                    rows = []
                    for tr in el.findall(f"{W}tr"):
                        cells = [" ".join(_docx_par_text(p) for p in tc.iter(f"{W}p")).strip()
                                 for tc in tr.findall(f"{W}tc")]
                        rows.append(cells)
                    width = max((len(r) for r in rows), default=0)
                    if width <= 1:
                        for row in rows:
                            for cell in row:
                                if cell:
                                    blocks.append(Block("paragraph", cell))
                    elif rows:
                        blocks.append(Block("table", rows=rows))
                elif el.tag == f"{W}sdt":
                    content = el.find(f"{W}sdtContent")
                    if content is not None:
                        walk(content)
            flush_list()

        if body is not None:
            walk(body)
        out.unit("document", None, blocks)


# ------------------------------------------------------------------------------------------------- PPTX


def _a_par_text(p: Any) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el.tag == f"{A}t":
            parts.append(el.text or "")
        elif el.tag == f"{A}br":
            parts.append(" ")
    return _norm("".join(parts))


def _shape_blocks(shape: Any, blocks: list[Block], state: dict[str, Any], *, notes: bool = False) -> None:
    tag = shape.tag
    if tag == f"{P}grpSp":
        for child in shape:
            _shape_blocks(child, blocks, state, notes=notes)
        return
    if tag == f"{P}graphicFrame":
        table = shape.find(f".//{A}tbl")
        if table is not None:
            rows = [[" ".join(_a_par_text(p) for p in tc.iter(f"{A}p")).strip() for tc in tr.findall(f"{A}tc")]
                    for tr in table.findall(f"{A}tr")]
            if rows:
                blocks.append(Block("table", rows=rows))
        return
    if tag == f"{P}pic":
        state.setdefault("pics", []).append(shape)
        return
    if tag != f"{P}sp":
        return
    ph = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
    ph_type = (ph.get("type") if ph is not None else None) or ("body" if ph is not None else "")
    if ph_type in ("sldNum", "dt", "ftr", "hdr", "sldImg"):
        return
    body = shape.find(f"{P}txBody")
    if body is None:
        return
    paragraphs = []
    for p in body.findall(f"{A}p"):
        text = _a_par_text(p)
        if text:
            ppr = p.find(f"{A}pPr")
            lvl = int(ppr.get("lvl") or 0) if ppr is not None and (ppr.get("lvl") or "0").isdigit() else 0
            paragraphs.append((lvl, text))
    if not paragraphs:
        return
    if not notes and ph_type in ("title", "ctrTitle") and not state.get("title"):
        state["title"] = " ".join(t for _, t in paragraphs)
        return
    if len(paragraphs) == 1:
        blocks.append(Block("paragraph", paragraphs[0][1]))
    else:
        blocks.append(Block("list", "\n".join(f"{'  ' * min(lvl, 6)}- {t}" for lvl, t in paragraphs)))


def convert_pptx(path: Path, out: _Out) -> None:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        out.title = _core_title(zf)
        pres = SafeET.fromstring(zf.read("ppt/presentation.xml"))
        rels = _rels(zf, "ppt/presentation.xml")
        slide_parts: list[str | None] = [rels.get(s.get(f"{R}id") or "") for s in pres.iter(f"{P}sldId")]
        if not slide_parts:  # no slide list (unusual files): take the slide parts in numeric order
            found: list[str] = [n for n in zf.names() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            found.sort(key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1]) or 0))
            slide_parts = [*found]
        out.pages = len(slide_parts)
        for number, part in enumerate(slide_parts, start=1):
            if not part or not zf.has(part):
                continue
            root = SafeET.fromstring(zf.read(part))
            tree = root.find(f"{P}cSld/{P}spTree")
            blocks: list[Block] = []
            state: dict[str, Any] = {}
            if tree is not None:
                for shape in tree:
                    _shape_blocks(shape, blocks, state)
            slide_rels = _rels(zf, part)
            for pic in state.get("pics", []):
                c_nv = pic.find(f"{P}nvPicPr/{P}cNvPr")
                alt = (c_nv.get("descr") or "").strip() if c_nv is not None else ""
                blip = pic.find(f".//{A}blip")
                target = slide_rels.get(blip.get(f"{R}embed") or "") if blip is not None else None
                if target and zf.has(target):
                    try:
                        out.image(zf.read(target, max_bytes=MAX_IMAGE_BYTES), target, alt=alt or None, unit=number)
                    except Exception:  # noqa: BLE001, S112
                        continue
            notes_text = None
            types = _rel_types(zf, part)
            for rid, target in slide_rels.items():
                if types.get(rid, "").endswith("/notesSlide") and zf.has(target):
                    notes_root = SafeET.fromstring(zf.read(target))
                    notes_blocks: list[Block] = []
                    notes_tree = notes_root.find(f"{P}cSld/{P}spTree")
                    if notes_tree is not None:
                        for shape in notes_tree:
                            _shape_blocks(shape, notes_blocks, {}, notes=True)
                    notes_text = "\n".join(b.markdown() for b in notes_blocks).strip() or None
            if blocks or state.get("title") or notes_text:
                out.unit("slide", number, blocks, title=state.get("title"), notes=notes_text)


# ------------------------------------------------------------------------------------------------- XLSX


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return 0
    index = 0
    for ch in letters.group(0):
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    return str(int(number)) if number.is_integer() and abs(number) < 1e15 else f"{number:g}"


def convert_xlsx(path: Path, out: _Out) -> None:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        out.title = _core_title(zf)
        shared: list[str] = []
        if zf.has("xl/sharedStrings.xml"):
            for si in SafeET.fromstring(zf.read("xl/sharedStrings.xml")).iter(f"{S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
        workbook = SafeET.fromstring(zf.read("xl/workbook.xml"))
        rels = _rels(zf, "xl/workbook.xml")
        for number, sheet in enumerate(workbook.iter(f"{S}sheet"), start=1):
            if (sheet.get("state") or "") in ("hidden", "veryHidden"):
                continue
            part = rels.get(sheet.get(f"{R}id") or "")
            if not part or not zf.has(part):
                continue
            grid: dict[int, dict[int, str]] = {}
            for row in SafeET.fromstring(zf.read(part)).iter(f"{S}row"):
                r_index = int(row.get("r") or len(grid) + 1) - 1
                if r_index >= MAX_SHEET_ROWS:
                    out.warnings.append("sheet_rows")
                    break
                for cell in row.findall(f"{S}c"):
                    col = _col_index(cell.get("r") or "")
                    if col >= MAX_SHEET_COLS:
                        continue
                    kind = cell.get("t")
                    value_el = cell.find(f"{S}v")
                    raw = value_el.text if value_el is not None and value_el.text else ""
                    if kind == "s" and raw.isdigit():
                        value = shared[int(raw)] if int(raw) < len(shared) else ""
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(f"{S}t"))
                    elif kind == "b":
                        value = "SANN" if raw == "1" else "USANN"
                    elif kind in ("str", "e"):
                        value = raw
                    else:
                        value = _number(raw) if raw else ""
                    if value.strip():
                        grid.setdefault(r_index, {})[col] = _norm(value)
            rows = _grid_rows(grid)
            if rows:
                out.unit("sheet", number, [Block("table", rows=rows)], title=sheet.get("name") or f"Ark {number}")


def _grid_rows(grid: dict[int, dict[int, str]]) -> list[list[str]]:
    if not grid:
        return []
    width = max(max(cols) for cols in grid.values() if cols) + 1
    used_cols = sorted({c for cols in grid.values() for c in cols})
    return [[grid[r].get(c, "") for c in used_cols] for r in sorted(grid)][:MAX_SHEET_ROWS] if width else []


# -------------------------------------------------------------------------------------------- OpenDocument


def _odf_text(el: Any) -> str:
    parts: list[str] = []

    def visit(node: Any) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            tag = child.tag
            if tag == f"{ODF_TEXT}s":
                parts.append(" " * int(child.get(f"{ODF_TEXT}c") or 1))
            elif tag == f"{ODF_TEXT}tab" or tag == f"{ODF_TEXT}line-break":
                parts.append(" ")
            elif tag in (f"{ODF_TEXT}note", f"{ODF_OFFICE}annotation"):
                pass
            else:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(el)
    return _norm("".join(parts))


def _odf_list(el: Any, depth: int = 0) -> list[str]:
    lines: list[str] = []
    for item in el.findall(f"{ODF_TEXT}list-item"):
        for child in item:
            if child.tag in (f"{ODF_TEXT}p", f"{ODF_TEXT}h"):
                text = _odf_text(child)
                if text:
                    lines.append(f"{'  ' * min(depth, 6)}- {text}")
            elif child.tag == f"{ODF_TEXT}list":
                lines.extend(_odf_list(child, depth + 1))
    return lines


def _odf_table(el: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in el.iter(f"{ODF_TABLE}table-row"):
        repeat_rows = min(MAX_REPEAT, int(row.get(f"{ODF_TABLE}number-rows-repeated") or 1))
        cells: list[str] = []
        for cell in row:
            if cell.tag not in (f"{ODF_TABLE}table-cell", f"{ODF_TABLE}covered-table-cell"):
                continue
            text = " ".join(_odf_text(p) for p in cell.iter(f"{ODF_TEXT}p")).strip()
            repeat = int(cell.get(f"{ODF_TABLE}number-columns-repeated") or 1)
            cells.extend([text] * (min(repeat, MAX_REPEAT) if text else min(repeat, MAX_SHEET_COLS)))
        while cells and not cells[-1]:
            cells.pop()
        if any(cells):
            rows.extend([cells[:MAX_SHEET_COLS]] * repeat_rows)
        if len(rows) >= MAX_SHEET_ROWS:
            break
    return rows


def _odf_blocks(container: Any) -> list[Block]:
    blocks: list[Block] = []
    for el in container:
        tag = el.tag
        if tag == f"{ODF_TEXT}h":
            text = _odf_text(el)
            if text:
                blocks.append(Block("heading", text, level=min(6, int(el.get(f"{ODF_TEXT}outline-level") or 1))))
        elif tag == f"{ODF_TEXT}p":
            text = _odf_text(el)
            if text:
                blocks.append(Block("paragraph", text))
        elif tag == f"{ODF_TEXT}list":
            lines = _odf_list(el)
            if lines:
                blocks.append(Block("list", "\n".join(lines)))
        elif tag == f"{ODF_TABLE}table":
            rows = _odf_table(el)
            if rows:
                blocks.append(Block("table", rows=rows))
        elif tag in (f"{ODF_TEXT}section", f"{ODF_DRAW}frame", f"{ODF_DRAW}text-box", f"{ODF_TEXT}index-body"):
            blocks.extend(_odf_blocks(el))
    return blocks


def convert_odf(path: Path, fmt: str, out: _Out) -> None:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        root = SafeET.fromstring(zf.read("content.xml"))
        body = root.find(f"{ODF_OFFICE}body")
        if body is None:
            return
        if fmt == "odt":
            text = body.find(f"{ODF_OFFICE}text")
            if text is not None:
                out.unit("document", None, _odf_blocks(text))
        elif fmt == "odp":
            pres = body.find(f"{ODF_OFFICE}presentation")
            pages = pres.findall(f"{ODF_DRAW}page") if pres is not None else []
            out.pages = len(pages)
            for number, page in enumerate(pages, start=1):
                title = None
                blocks: list[Block] = []
                for frame in page.findall(f"{ODF_DRAW}frame"):
                    frame_blocks = _odf_blocks(frame)
                    if frame.get(f"{ODF_PRES}class") == "title" and frame_blocks and title is None:
                        title = " ".join(b.text for b in frame_blocks)
                    else:
                        blocks.extend(frame_blocks)
                notes_el = page.find(f"{ODF_PRES}notes")
                notes = None
                if notes_el is not None:
                    notes = "\n".join(_odf_text(p) for p in notes_el.iter(f"{ODF_TEXT}p") if _odf_text(p)) or None
                if blocks or title or notes:
                    out.unit("slide", number, blocks, title=title, notes=notes)
        else:
            sheet_root = body.find(f"{ODF_OFFICE}spreadsheet")
            tables = sheet_root.findall(f"{ODF_TABLE}table") if sheet_root is not None else []
            for number, table in enumerate(tables, start=1):
                rows = _odf_table(table)
                if rows:
                    out.unit("sheet", number, [Block("table", rows=rows)],
                             title=table.get(f"{ODF_TABLE}name") or f"Ark {number}")


# --------------------------------------------------------------------------------------- RTF, CSV, text

_RTF_TOKEN = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)",
                        re.IGNORECASE | re.DOTALL)
_RTF_SKIP = frozenset(
    "aftncn aftnsep aftnsepc annotation atnauthor atndate atnicn atnid atnparent atnref atntime atrfend atrfstart "
    "author background bkmkend bkmkstart blipuid buptim category colorschememapping colortbl comment company "
    "creatim datafield datastore defchp defpap do doccomm docvar dptxbxtext ebcend ebcstart factoidname falt "
    "fchars ffdeftext ffentrymcr ffexitmcr ffformat ffhelptext ffl ffname ffstattext field file filetbl fldinst "
    "fldtype fname fontemb fontfile fonttbl footer footerf footerl footerr footnote formfield ftncn ftnsep ftnsepc "
    "g generator gridtbl header headerf headerl headerr hl hlfr hlinkbase hlloc hlsrc hsv htmltag info keycode "
    "keywords latentstyles lchars levelnumbers leveltext lfolevel linkval list listlevel listname listoverride "
    "listoverridetable listpicture liststylename listtable listtext lsdlockedexcept macc maccPr mailmerge maln "
    "malnScr manager margPr mbar mbarPr mbaseJc mbegChr mborderBox mborderBoxPr mbox mboxPr mchr mcount mctrlPr "
    "md mdeg mdegHide mden mdiff mdPr me mendChr meqArr meqArrPr mf mfName mfPr mfunc mfuncPr mgroupChr "
    "mgroupChrPr mgrow mhideBot mhideLeft mhideRight mhideTop mhtmltag mlim mlimloc mlimlow mlimlowPr mlimupp "
    "mlimuppPr mm mmaddfieldname mmath mmathPict mmathPr mmaxdist mmc mmcJc mmconnectstr mmconnectstrdata mmcPr "
    "mmcs mmdatasource mmheadersource mmmailsubject mmodso mmodsofilter mmodsofldmpdata mmodsomappedname "
    "mmodsoname mmodsorecipdata mmodsosort mmodsosrc mmodsotable mmodsoudl mmodsoudldata mmodsouniquetag "
    "mmPr mmquery mmr mnary mnaryPr mnoBreak mnum mobjDist moMath moMathPara moMathParaPr mopEmu mphant mphantPr "
    "mplcHide mpos mr mrad mradPr mrPr msepChr mshow mshp msPre msPrePr msSub msSubPr msSubSup msSubSupPr msSup "
    "msSupPr mstrikeBLTR mstrikeH mstrikeTLBR mstrikeV msub msubHide msup msupHide mtransp mtype mvertJc "
    "mvfmf mvfml mvtof mvtol mzeroAsc mzeroDesc mzeroWid nesttableprops nextfile nonesttables objalias objclass "
    "objdata object objname objsect objtime oldcprops oldpprops oldsprops oldtprops oleclsid operator panose "
    "password passwordhash pgp pgptbl picprop pict pn pnseclvl pntext pntxta pntxtb printim private propname "
    "protend protstart protusertbl pxe result revtbl revtim rsidtbl rxe shp shpgrp shpinst shppict shprslt "
    "shptxt sn sp staticval stylesheet subject sv svb tc template themedata title txe ud upr userprops "
    "wgrffmtfilter windowcaption writereservation writereservhash xe xform xmlattrname xmlattrvalue xmlclose "
    "xmlname xmlnstbl xmlopen".split())
_RTF_SPECIAL = {"par": "\n", "sect": "\n\n", "page": "\n\n", "line": "\n", "tab": "\t", "emdash": "—",
                "endash": "–", "emspace": " ", "enspace": " ", "qmspace": " ", "bullet": "•", "lquote": "‘",
                "rquote": "’", "ldblquote": "“", "rdblquote": "”", "row": "\n", "cell": " | "}


def rtf_to_text(data: bytes) -> str:
    text = data.decode("latin-1")
    stack: list[tuple[int, bool]] = []
    ignorable = False
    ucskip = 1
    curskip = 0
    out: list[str] = []
    for match in _RTF_TOKEN.finditer(text):
        word, arg, hexcode, char, brace, tchar = match.groups()
        if brace:
            curskip = 0
            if brace == "{":
                stack.append((ucskip, ignorable))
            elif stack:
                ucskip, ignorable = stack.pop()
        elif char:
            curskip = 0
            if char == "~":
                if not ignorable:
                    out.append("\xa0")
            elif char in "{}\\":
                if not ignorable:
                    out.append(char)
            elif char == "*":
                ignorable = True
        elif word:
            curskip = 0
            if word in _RTF_SKIP:
                ignorable = True
            elif ignorable:
                pass
            elif word in _RTF_SPECIAL:
                out.append(_RTF_SPECIAL[word])
            elif word == "uc":
                ucskip = int(arg or 1)
            elif word == "u":
                value = int(arg or 0)
                out.append(chr(value + 0x10000 if value < 0 else value))
                curskip = ucskip
        elif hexcode:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(bytes([int(hexcode, 16)]).decode("cp1252", errors="replace"))
        elif tchar:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(tchar)
    return "".join(out)


def csv_rows(text: str) -> list[list[str]]:
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        if any(c.strip() for c in row):
            rows.append([_norm(c) for c in row[:MAX_SHEET_COLS]])
        if len(rows) >= MAX_SHEET_ROWS:
            break
    return rows


# ------------------------------------------------------------------------------------------- entry point


def convert_document(path: str, fmt: str, out_dir: str | None = None, max_images: int = 50) -> dict[str, Any]:
    """Worker job ``rag_convert``: one course file → units of Markdown blocks (JSON-serialisable)."""
    file = Path(path)
    out = _Out(fmt, out_dir, max_images)
    if fmt == "pdf":
        convert_pdf(file, out)
    elif fmt == "docx":
        convert_docx(file, out)
    elif fmt == "pptx":
        convert_pptx(file, out)
    elif fmt == "xlsx":
        convert_xlsx(file, out)
    elif fmt in ("odt", "odp", "ods"):
        convert_odf(file, fmt, out)
    elif fmt == "rtf":
        out.unit("document", None, parse_markdown(rtf_to_text(file.read_bytes()), plain=True))
    elif fmt == "csv":
        rows = csv_rows(decode_text(file.read_bytes()))
        if rows:
            out.unit("sheet", 1, [Block("table", rows=rows)])
    elif fmt == "txt":
        out.unit("document", None, parse_markdown(decode_text(file.read_bytes()), plain=True))
    elif fmt == "md":
        out.unit("document", None, parse_markdown(decode_text(file.read_bytes())))
    elif fmt in ("html", "htm"):
        from emneklar.features.course_rag.convert.html_md import html_to_blocks

        out.unit("document", None, html_to_blocks(decode_text(file.read_bytes()), base_url="").blocks)
    else:
        return {"error": "unsupported", "format": fmt}
    return out.result()
