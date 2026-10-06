"""Document checks (PDF, Word, PowerPoint, Excel) – only defensible automated checks.

Runs inside an isolated worker process (core/security/isolation.py): files are
untrusted. Output distinguishes what was checked automatically from what
always requires manual review. A tagged PDF is never reported as accessible.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET

from emneklar.core.security.safe_zip import SafeZip, ZipLimitError, ZipLimits
from emneklar.features.accessibility.checks.base import Issue

log = logging.getLogger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
DC = "{http://purl.org/dc/elements/1.1/}"
DECORATIVE_MARK = "decorative"
SUPPORTED = {"pdf", "docx", "pptx", "xlsx"}
LEGACY = {"doc", "ppt", "xls", "odt", "odp", "ods", "rtf"}
EXEMPTION_DATE = datetime(2022, 2, 1)


def document_format(name: str, content_type: str | None = None) -> str | None:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in SUPPORTED | LEGACY:
        return ext
    ct = (content_type or "").lower()
    if ct == "application/pdf":
        return "pdf"
    if "wordprocessingml" in ct:
        return "docx"
    if "presentationml" in ct:
        return "pptx"
    if "spreadsheetml" in ct:
        return "xlsx"
    return None


# ------------------------------------------------------------------------------- inspectors


def _core_title(zf: SafeZip) -> str | None:
    if not zf.has("docProps/core.xml"):
        return None
    root = SafeET.fromstring(zf.read("docProps/core.xml"))
    title = root.find(f"{DC}title")
    return (title.text or "").strip() or None if title is not None else None


def _has_decorative_flag(element: Any) -> bool:
    return any(DECORATIVE_MARK in str(child.tag).lower() and child.get("val") in ("1", "true")
               for child in element.iter())


def inspect_pdf(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                return {"format": "pdf", "encrypted": True}
        except Exception:  # noqa: BLE001 - any failure means we cannot read it
            return {"format": "pdf", "encrypted": True}
    root = reader.trailer["/Root"]
    mark_info = root.get("/MarkInfo")
    marked = bool(mark_info.get("/Marked")) if mark_info is not None else False
    tagged = marked and "/StructTreeRoot" in root
    lang = root.get("/Lang")
    metadata = reader.metadata
    title = (metadata.title or "").strip() if metadata and metadata.title else None
    pages = len(reader.pages)
    text = ""
    for page in reader.pages[: min(5, pages)]:
        try:
            text += page.extract_text() or ""
        except Exception:  # noqa: BLE001 - broken content streams
            continue
        if len(text) > 2000:
            break
    return {"format": "pdf", "pages": pages, "tagged": tagged, "lang": str(lang) if lang else None,
            "title": title, "has_text": len(re.sub(r"\s+", "", text)) > 20}


def inspect_docx(path: Path) -> dict[str, Any]:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        root = SafeET.fromstring(zf.read("word/document.xml"))
        paragraphs = root.findall(f".//{W}p")
        words = sum(len("".join(t.text or "" for t in p.iter(f"{W}t")).split()) for p in paragraphs)
        headings = 0
        for p in paragraphs:
            style = p.find(f"{W}pPr/{W}pStyle")
            outline = p.find(f"{W}pPr/{W}outlineLvl")
            value = (style.get(f"{W}val") if style is not None else "") or ""
            if outline is not None or re.match(r"(?i)^(heading|overskrift|title|tittel)\s*\d*", value):
                headings += 1
        images = root.findall(f".//{WP}docPr")
        missing_alt = [d for d in images if not (d.get("descr") or "").strip() and not _has_decorative_flag(d)]
        tables = root.findall(f".//{W}tbl")
        tables_without_header = 0
        for table in tables:
            first = table.find(f"{W}tr")
            if first is None or first.find(f"{W}trPr/{W}tblHeader") is None:
                tables_without_header += 1
        lang = None
        for part in ("word/styles.xml", "word/document.xml", "word/settings.xml"):
            if zf.has(part):
                match = re.search(rb'w:(?:val|eastAsia|bidi)="([a-z]{2,3}(?:-[A-Za-z]{2,4})?)"',
                                  _lang_area(zf.read(part)))
                if match:
                    lang = match.group(1).decode()
                    break
        return {"format": "docx", "words": words, "headings": headings, "images_total": len(images),
                "images_without_alt": len(missing_alt), "tables_total": len(tables),
                "tables_without_header": tables_without_header, "title": _core_title(zf), "lang": lang}


def _lang_area(xml: bytes) -> bytes:
    """Only look at <w:lang …> elements when searching for a language code."""
    return b" ".join(re.findall(rb"<w:lang\b[^>]*>", xml))


def inspect_pptx(path: Path) -> dict[str, Any]:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        slides = sorted((n for n in zf.names() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        without_title = []
        images_total = 0
        images_without_alt = 0
        for index, name in enumerate(slides, start=1):
            root = SafeET.fromstring(zf.read(name))
            has_title = False
            for sp in root.iter(f"{P}sp"):
                ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                    text = "".join(t.text or "" for t in sp.iter(f"{A}t")).strip()
                    has_title = has_title or bool(text)
            if not has_title:
                without_title.append(index)
            for pic in root.iter(f"{P}pic"):
                images_total += 1
                c_nv = pic.find(f"{P}nvPicPr/{P}cNvPr")
                if c_nv is not None and not (c_nv.get("descr") or "").strip() and not _has_decorative_flag(c_nv):
                    images_without_alt += 1
        return {"format": "pptx", "slides": len(slides), "slides_without_title": without_title,
                "images_total": images_total, "images_without_alt": images_without_alt, "title": _core_title(zf)}


def inspect_xlsx(path: Path) -> dict[str, Any]:
    with SafeZip(path, ZipLimits(), container=True) as zf:
        images_total = 0
        images_without_alt = 0
        for name in zf.names():
            if re.match(r"xl/drawings/drawing\d+\.xml$", name):
                root = SafeET.fromstring(zf.read(name))
                for c_nv in root.iter(f"{XDR}cNvPr"):
                    images_total += 1
                    if not (c_nv.get("descr") or "").strip() and not _has_decorative_flag(c_nv):
                        images_without_alt += 1
        return {"format": "xlsx", "images_total": images_total, "images_without_alt": images_without_alt,
                "title": _core_title(zf)}


def inspect_document(path: str, fmt: str) -> dict[str, Any]:
    """Worker entry point (JSON in, JSON out)."""
    file_path = Path(path)
    try:
        if fmt == "pdf":
            return inspect_pdf(file_path)
        if fmt == "docx":
            return inspect_docx(file_path)
        if fmt == "pptx":
            return inspect_pptx(file_path)
        if fmt == "xlsx":
            return inspect_xlsx(file_path)
        return {"format": fmt, "error": "unsupported"}
    except ZipLimitError as exc:
        return {"format": fmt, "error": "limits", "detail": exc.code}
    except KeyError:
        return {"format": fmt, "error": "corrupt"}
    except Exception as exc:  # noqa: BLE001 - report as unreadable, never crash the analysis
        return {"format": fmt, "error": "parse", "detail": type(exc).__name__}


# ------------------------------------------------------------------------------- findings

AUTOMATIC = {
    "pdf": ["struktur (tagger)", "tekstlag (ikke skannet)", "tittel i egenskaper", "dokumentspråk"],
    "docx": ["alternativ tekst på bilder", "bruk av overskriftsstiler", "overskriftsrad i tabeller", "tittel",
             "dokumentspråk"],
    "pptx": ["lysbildetitler", "alternativ tekst på bilder", "tittel"],
    "xlsx": ["alternativ tekst på bilder", "tittel"],
}
MANUAL = {
    "pdf": ["leserekkefølge", "kvaliteten på alternativ tekst", "tabellstruktur", "kontrast", "riktige tagger"],
    "docx": ["kvaliteten på alternativ tekst", "leserekkefølge i tekstbokser", "kontrast", "lenketekster"],
    "pptx": ["leserekkefølge på lysbildene", "kvaliteten på alternativ tekst", "kontrast", "tekst i bilder"],
    "xlsx": ["arkstruktur og overskrifter", "sammenslåtte celler", "kontrast", "fargebruk"],
}


def document_issues(result: dict[str, Any], *, name: str, created_at: str | None) -> list[Issue]:
    fmt = str(result.get("format") or "")
    evidence: dict[str, Any] = {"file": name, "format": fmt}
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            if created < EXEMPTION_DATE:
                evidence["exemption_hint"] = ("Lastet opp før 1. februar 2022 – unntaket for eldre dokumenter i "
                                              "forskriften § 4c kan gjelde hvis dokumentet ikke trengs i en aktiv "
                                              "prosess.")
        except ValueError:
            pass
    issues: list[Issue] = []

    def add(rule: str, message: str, **extra: Any) -> None:
        issues.append(Issue(rule, message, snippet=name, key=f"{rule}:{name}", evidence={**evidence, **extra}))

    if fmt in LEGACY:
        add("UU-DOC-UNREADABLE", f"«{name}» er i et eldre format ({fmt}) som ikke kan kontrolleres automatisk.")
        return issues
    if result.get("encrypted"):
        add("UU-DOC-UNREADABLE", f"«{name}» er passordbeskyttet eller kryptert.")
        return issues
    if result.get("error"):
        reason = {"limits": "for stort eller mistenkelig komprimert", "corrupt": "ødelagt",
                  "timeout": "tok for lang tid å lese", "unsupported": "ikke støttet"}.get(
            str(result["error"]), "kunne ikke leses")
        add("UU-DOC-UNREADABLE", f"«{name}» kunne ikke kontrolleres ({reason}).")
        return issues
    if fmt == "pdf":
        if not result.get("has_text"):
            add("UU-DOC-PDF-NO-TEXT", f"«{name}» har ingen lesbar tekst på de første sidene.",
                pages=result.get("pages"))
        if not result.get("tagged"):
            add("UU-DOC-PDF-UNTAGGED", f"«{name}» er ikke tagget (mangler struktur).")
        if not result.get("lang"):
            add("UU-DOC-NO-LANG", f"«{name}» oppgir ikke dokumentspråk.")
    if fmt in ("docx", "pptx", "xlsx") and result.get("images_without_alt"):
        add("UU-DOC-IMG-ALT", f"«{name}»: {result['images_without_alt']} av {result.get('images_total')} bilder "
            "mangler alternativ tekst.", images_without_alt=result["images_without_alt"])
    if fmt == "docx":
        if int(result.get("words") or 0) > 500 and not result.get("headings"):
            add("UU-DOC-NO-HEADINGS", f"«{name}» har {result.get('words')} ord, men ingen overskriftsstiler.")
        if result.get("tables_without_header"):
            add("UU-DOC-TABLE-HEADER", f"«{name}»: {result['tables_without_header']} tabell(er) uten overskriftsrad.")
        if not result.get("lang"):
            add("UU-DOC-NO-LANG", f"«{name}» oppgir ikke dokumentspråk.")
    if fmt == "pptx" and result.get("slides_without_title"):
        slides = result["slides_without_title"]
        add("UU-DOC-SLIDE-TITLES", f"«{name}»: lysbilde {', '.join(str(s) for s in slides[:10])} mangler tittel.",
            slides=slides)
    if not result.get("title"):
        add("UU-DOC-NO-TITLE", f"«{name}» mangler tittel i dokumentegenskapene.")
    issues.append(Issue(
        "UU-DOC-MANUAL", f"«{name}»: deler av dokumentet må kontrolleres manuelt.", snippet=name,
        key=f"UU-DOC-MANUAL:{name}",
        evidence={**evidence, "automatically_checked": AUTOMATIC.get(fmt, []),
                  "requires_manual_check": MANUAL.get(fmt, []), "tagged": result.get("tagged")}))
    return issues
