"""Export of an Emne-RAG index, for use in other tools.

* ``zip`` – ``chunks.jsonl`` (one chunk per line: text, context, all metadata and the embedding vector),
  ``manifest.json`` (course, model, dimensions, counts, versions) and ``LESMEG.md`` (the format).
* ``md``, ``docx``, ``pdf``, ``txt`` – the knowledge base as a readable document, grouped by element with source
  links, for tools that take documents (for example NotebookLM or Copilot). Overlap between consecutive chunks is
  removed, so the text reads once.

Exports contain only what the index contains: teacher-produced content. AI-generated image descriptions and context
sentences are labelled.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape

from emneklar import __version__
from emneklar.features.course_rag.chunking import CHUNKER_VERSION, sentences
from emneklar.features.course_rag.citations import citation, timestamp
from emneklar.features.course_rag.markdown import Block, parse_markdown, plain_text
from emneklar.features.course_rag.sources import KIND_LABELS
from emneklar.features.course_rag.store import SCHEMA_VERSION, ChunkRecord, IndexStore

ExportFormat = Literal["zip", "md", "docx", "pdf", "txt"]
FORMATS: dict[str, tuple[str, str]] = {
    "zip": ("application/zip", "zip"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
    "txt": ("text/plain; charset=utf-8", "txt"),
}
README = """# Eksport av emnets kunnskapsbase fra EmneKlar

Denne mappen inneholder en kunnskapsbase laget av et Canvas-emne. Den inneholder bare lærerprodusert innhold.

* `chunks.jsonl` – ett utdrag per linje (UTF-8). Feltene:
  `id`, `uid`, `text` (Markdown), `context` (KI-generert kontekstsetning, kan være tom), `search_text` (det som ble
  embeddet og nøkkelordindeksert), `type` (`text | table | image | transcript | slide`), `citation`,
  `course_id`, `module_ids`, `module_name`, `item_key`, `item_kind`, `title`, `heading_path`, `url`, `page`,
  `page_end`, `start`/`end` (sekunder i video), `updated_at`, `tokens`, `meta` og `vector` (liste med tall, eller
  `null` når indeksen bare har nøkkelordsøk).
* `manifest.json` – emne, embedding-modell, antall dimensjoner, versjoner og antall utdrag.

Vektorene er normaliserte (lengde 1), så cosinuslikhet er det samme som skalarprodukt. Spørsmål må embeddes med
samme modell som står i `manifest.json`. Bildebeskrivelser og kontekstsetninger er KI-generert og må vurderes.
"""


@dataclass
class ItemGroup:
    key: str
    kind: str
    title: str
    url: str | None
    module: str | None
    chunks: list[ChunkRecord]


def groups(store: IndexStore) -> list[ItemGroup]:
    out: dict[str, ItemGroup] = {}
    items = store.items()
    for record, _ in store.iter_chunks():
        row = items.get(record.item_key) or {}
        group = out.setdefault(record.item_key, ItemGroup(record.item_key, record.item_kind, record.title,
                                                          row.get("url") or record.url, record.module_name, []))
        group.chunks.append(record)
    order = {"syllabus": 0, "page": 1, "assignment": 2, "quiz": 3, "discussion": 4, "file": 5, "media": 6,
             "youtube": 6, "image": 7}
    return sorted(out.values(), key=lambda g: (g.module or "￿", order.get(g.kind, 9), g.title.lower()))


def without_overlap(previous: str, text: str) -> str:
    """Drop the leading sentences of ``text`` that repeat the end of ``previous`` (chunk overlap)."""
    tail = previous[-1500:]
    parts = sentences(text)
    dropped = 0
    while dropped < len(parts) - 1 and parts[dropped] in tail:
        dropped += 1
    return " ".join(parts[dropped:]) if dropped else text


def readable(group: ItemGroup) -> Iterator[tuple[ChunkRecord, str]]:
    previous = ""
    for record in group.chunks:
        text = record.text
        if record.type in ("text", "transcript") and previous:
            text = without_overlap(previous, text)
        previous = record.text
        yield record, text


def manifest(store: IndexStore, course: dict[str, Any], count: int, dim: int | None) -> dict[str, Any]:
    return {"format": "emneklar-rag", "format_version": 1, "exported_at": datetime.now(UTC).isoformat(),
            "emneklar_version": __version__, "index_schema_version": SCHEMA_VERSION, "chunker_version": CHUNKER_VERSION,
            "course": course, "embedding_model": store.embedding_identity or None, "dimensions": dim, "chunks": count,
            "content": "Bare lærerprodusert innhold. Ingen studentdata."}


def export_zip(store: IndexStore, course: dict[str, Any], target: Path) -> None:
    lines: list[str] = []
    dim: int | None = None
    for record, vector in store.iter_chunks(with_vectors=True):
        if vector is not None:
            dim = int(vector.shape[0])
        lines.append(json.dumps({
            **record.as_dict(), "course_id": course.get("id"), "citation": citation(record),
            "search_text": record.search_text(),
            "vector": [round(float(x), 6) for x in vector] if vector is not None else None,
        }, ensure_ascii=False))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("chunks.jsonl", "\n".join(lines) + ("\n" if lines else ""))
        zf.writestr("manifest.json", json.dumps(manifest(store, course, len(lines), dim), ensure_ascii=False, indent=2))
        zf.writestr("LESMEG.md", README)


def _source_line(group: ItemGroup) -> str:
    parts = [KIND_LABELS.get(group.kind, group.kind)]
    if group.module:
        parts.append(group.module)
    return " · ".join(parts) + (f" · {group.url}" if group.url else "")


def _chunk_heading(record: ChunkRecord) -> str | None:
    if record.type == "transcript":
        return f"[{timestamp(record.start)}–{timestamp(record.end)}]"
    if record.type == "slide" and record.page:
        return None  # the slide text starts with its own heading
    if record.type == "image":
        return "Bildebeskrivelse (KI-generert – må vurderes)"
    if record.page and record.item_kind == "file":
        return f"Side {record.page}"
    return None


def export_markdown(store: IndexStore, course: dict[str, Any]) -> str:
    out = [f"# {course.get('name') or 'Emne'} – kunnskapsbase", "",
           f"Eksportert fra EmneKlar {datetime.now(UTC).strftime('%d.%m.%Y')}. Bare lærerprodusert innhold.", ""]
    for group in groups(store):
        out += [f"## {group.title}", "", f"*{_source_line(group)}*", ""]
        for record, text in readable(group):
            heading = _chunk_heading(record)
            if heading:
                out += [f"**{heading}**", ""]
            out += [text, ""]
    return "\n".join(out)


def export_text(store: IndexStore, course: dict[str, Any]) -> str:
    out = [f"{course.get('name') or 'Emne'} – kunnskapsbase", "=" * 40, ""]
    for group in groups(store):
        out += [group.title, "-" * min(80, max(3, len(group.title))), _source_line(group), ""]
        for record, text in readable(group):
            heading = _chunk_heading(record)
            if heading:
                out.append(heading)
            out += [plain_text(text) if record.type != "table" else text, ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------- Word

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_STYLES = "".join([
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<w:styles ' + _W + '>',
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>',
    '<w:sz w:val="22"/>',
    '<w:lang w:val="nb-NO"/></w:rPr></w:rPrDefault></w:docDefaults>',
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr>',
    '<w:spacing w:after="120"/></w:pPr></w:style>',
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>',
    '<w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>',
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>',
    '<w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360"/><w:outlineLvl w:val="0"/>',
    '</w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>',
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>',
    '<w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240"/><w:outlineLvl w:val="1"/>',
    '</w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>',
    '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>',
    '<w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/>',
    '<w:sz w:val="24"/></w:rPr></w:style>',
    '<w:style w:type="paragraph" w:styleId="Source"><w:name w:val="Kilde"/><w:basedOn w:val="Normal"/>',
    '<w:rPr><w:i/><w:color w:val="555555"/><w:sz w:val="18"/></w:rPr></w:style>',
    '<w:style w:type="table" w:styleId="Grid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>',
    '<w:top w:val="single" w:sz="4" w:color="999999"/><w:left w:val="single" w:sz="4" w:color="999999"/>',
    '<w:bottom w:val="single" w:sz="4" w:color="999999"/>',
    '<w:right w:val="single" w:sz="4" w:color="999999"/>',
    '<w:insideH w:val="single" w:sz="4" w:color="999999"/>',
    '<w:insideV w:val="single" w:sz="4" w:color="999999"/>',
    '</w:tblBorders></w:tblPr></w:style>',
    '</w:styles>',
])
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _x(text: str) -> str:
    return escape(_INVALID_XML.sub("", text))


def _para(text: str, style: str | None = None, *, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_x(text)}</w:t></w:r></w:p>'


def _table(rows: list[list[str]]) -> str:
    width = max((len(r) for r in rows), default=0)
    xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="Grid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>']
    for index, row in enumerate(rows):
        header = "<w:trPr><w:tblHeader/></w:trPr>" if index == 0 else ""
        cells = "".join(f"<w:tc>{_para(cell, bold=index == 0)}</w:tc>" for cell in row + [""] * (width - len(row)))
        xml.append(f"<w:tr>{header}{cells}</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml)


def _blocks_xml(blocks: list[Block]) -> list[str]:
    out = []
    for block in blocks:
        if block.kind == "heading":
            out.append(_para(block.text, "Heading3"))
        elif block.kind == "table":
            out.append(_table(block.rows))
            out.append(_para(""))
        elif block.kind == "list":
            out += [_para("• " + re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line).strip()) for line in block.text.split("\n")]
        else:
            out.append(_para(plain_text(block.text)))
    return out


def export_docx(store: IndexStore, course: dict[str, Any], target: Path) -> None:
    body = [_para(f"{course.get('name') or 'Emne'} – kunnskapsbase", "Title"),
            _para(f"Eksportert fra EmneKlar {datetime.now(UTC).strftime('%d.%m.%Y')}. Bare lærerprodusert innhold.",
                  "Source")]
    for group in groups(store):
        body.append(_para(group.title, "Heading1"))
        body.append(_para(_source_line(group), "Source"))
        for record, text in readable(group):
            heading = _chunk_heading(record)
            if heading:
                body.append(_para(heading, "Heading2" if record.type != "image" else None, bold=record.type == "image"))
            body += _blocks_xml(parse_markdown(text))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
                'w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats'
                     '.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
                     'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument'
                     '.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application'
                     '/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core'
                     '.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats'
            '.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
                'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
                'openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.'
            'openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{_x(str(course.get('name') or 'Emne'))} – kunnskapsbase</dc:title><dc:language>nb-NO"
            "</dc:language></cp:coreProperties>")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/styles.xml", _STYLES)
        zf.writestr("docProps/core.xml", core)


# ------------------------------------------------------------------------------------------------ PDF


def _latin(text: str) -> str:
    """The PDF uses the built-in Helvetica font (Windows-1252): replace what it cannot show."""
    replacements = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                    "…": "...", "•": "-", "›": ">", "→": "->", " ": " "}
    text = "".join(replacements.get(ch, ch) for ch in text)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def export_pdf(store: IndexStore, course: dict[str, Any], target: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.set_title(_latin(f"{course.get('name') or 'Emne'} – kunnskapsbase"))
    pdf.set_lang("nb-NO")
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def write(text: str, size: float = 10.5, style: str = "", height: float = 5.2) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, height, _latin(text))

    write(f"{course.get('name') or 'Emne'} - kunnskapsbase", 18, "B", 9)
    write(f"Eksportert fra EmneKlar {datetime.now(UTC).strftime('%d.%m.%Y')}. Bare lærerprodusert innhold.", 9, "I")
    for group in groups(store):
        pdf.ln(4)
        write(group.title, 14, "B", 7)
        write(_source_line(group), 8.5, "I", 4.5)
        for record, text in readable(group):
            heading = _chunk_heading(record)
            if heading:
                pdf.ln(1)
                write(heading, 10.5, "B")
            for block in parse_markdown(text):
                if block.kind == "heading":
                    write(block.text, 11.5, "B", 6)
                elif block.kind == "table":
                    for row in block.rows:
                        write(" | ".join(row), 9)
                else:
                    write(plain_text(block.text) if block.kind != "list" else block.text.replace("  ", "   "))
                pdf.ln(1)
    pdf.output(str(target))


def export(store: IndexStore, course: dict[str, Any], fmt: ExportFormat, target: Path) -> Path:
    if fmt == "zip":
        export_zip(store, course, target)
    elif fmt == "md":
        target.write_text(export_markdown(store, course), encoding="utf-8")
    elif fmt == "txt":
        target.write_text(export_text(store, course), encoding="utf-8")
    elif fmt == "docx":
        export_docx(store, course, target)
    else:
        export_pdf(store, course, target)
    return target


def jsonl_lines(data: bytes) -> list[dict[str, Any]]:
    """Helper for tests and tools: read chunks.jsonl from an export ZIP."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return [json.loads(line) for line in zf.read("chunks.jsonl").decode("utf-8").splitlines() if line]
