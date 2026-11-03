"""Tiny, valid PDF/DOCX/PPTX files built in memory for tests (no binary fixtures in git)."""

from __future__ import annotations

import io
import zipfile


def minimal_pdf(*, text: str | None = "Pensumliste for emnet", tagged: bool = False, title: str | None = None,
                lang: str | None = None) -> bytes:
    """Build a one-page PDF. ``text=None`` gives a page without any text (looks scanned)."""
    objects: list[bytes] = []
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if tagged:
        catalog += b" /MarkInfo << /Marked true >> /StructTreeRoot 6 0 R"
    if lang:
        catalog += b" /Lang (" + lang.encode() + b")"
    catalog += b" >>"
    objects.append(catalog)
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >>"
    page += b" /Contents 5 0 R >>"
    objects.append(page)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    stream = f"BT /F1 14 Tf 72 760 Td ({text}) Tj ET".encode("latin-1") if text else b""
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /StructTreeRoot >>")
    info_index = None
    if title:
        objects.append(b"<< /Title (" + title.encode("latin-1") + b") >>")
        info_index = len(objects)

    out = io.BytesIO()
    out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R"
    if info_index:
        trailer += f" /Info {info_index} 0 R"
    trailer += f" >>\nstartxref\n{xref}\n%%EOF\n"
    out.write(trailer.encode())
    return out.getvalue()


_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""


def minimal_docx(*, paragraphs: int = 3, heading: bool = False, image_alt: str | None = None, with_image: bool = True,
                 title: str | None = None, lang: str | None = None, table_header: bool = False,
                 with_table: bool = False) -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    wp = 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    body = []
    if heading:
        body.append('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Innledning</w:t></w:r></w:p>')
    lang_xml = f'<w:rPr><w:lang w:val="{lang}"/></w:rPr>' if lang else ""
    for i in range(paragraphs):
        words = " ".join(["tekst"] * 40)
        body.append(f"<w:p><w:r>{lang_xml}<w:t>Avsnitt {i} {words}</w:t></w:r></w:p>")
    if with_image:
        descr = f' descr="{image_alt}"' if image_alt is not None else ""
        body.append(f'<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Bilde 1"{descr}/></wp:inline>'
                    "</w:drawing></w:r></w:p>")
    if with_table:
        header = "<w:trPr><w:tblHeader/></w:trPr>" if table_header else ""
        body.append(f"<w:tbl><w:tr>{header}<w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc></w:tr>"
                    "<w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {w} {wp}><w:body>{"".join(body)}</w:body></w:document>'
    core_title = f"<dc:title>{title}</dc:title>" if title else ""
    core = ('<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/">{core_title}</cp:coreProperties>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CT)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", document)
        zf.writestr("docProps/core.xml", core)
    return buf.getvalue()


def minimal_pptx(*, slides: list[dict] | None = None, title: str | None = None) -> bytes:
    """slides: [{"title": "…" or None, "image_alt": None|"…"|"" , "image": bool}]"""
    slides = slides or [{"title": "Velkommen", "image": True, "image_alt": None}, {"title": None, "image": False}]
    p = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        zf.writestr("ppt/presentation.xml", f'<?xml version="1.0"?><p:presentation {p}/>')
        for index, slide in enumerate(slides, start=1):
            shapes = []
            if slide.get("title"):
                shapes.append('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Tittel"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/>'
                              f'</p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{slide["title"]}</a:t></a:r></a:p>'
                              "</p:txBody></p:sp>")
            if slide.get("image"):
                alt = slide.get("image_alt")
                descr = f' descr="{alt}"' if alt is not None else ""
                shapes.append(f'<p:pic><p:nvPicPr><p:cNvPr id="3" name="Bilde"{descr}/></p:nvPicPr></p:pic>')
            zf.writestr(f"ppt/slides/slide{index}.xml",
                        f'<?xml version="1.0"?><p:sld {p} {a}><p:cSld><p:spTree>{"".join(shapes)}</p:spTree>'
                        "</p:cSld></p:sld>")
        core_title = f"<dc:title>{title}</dc:title>" if title else ""
        zf.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties '
                    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    f'xmlns:dc="http://purl.org/dc/elements/1.1/">{core_title}</cp:coreProperties>')
    return buf.getvalue()
