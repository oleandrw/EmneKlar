"""Test helpers for Emne-RAG: realistic Office/OpenDocument files, deterministic local models and a small course."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from emneklar.core.ai.local import LocalModelDef, LocalModels
from emneklar.features.course_rag.text import stems
from tests.fakes.documents import minimal_pdf
from tests.fakes.fake_canvas import CourseData, FakeCanvasState

RAG_COURSE = "104"
VTT_FARGE = ("WEBVTT\n\nNOTE generert\n\n1\n00:00:00.000 --> 00:00:04.000\nVelkommen til forelesningen om fargerom.\n\n"
             + "".join(f"{i + 2}\n00:{(i * 10 + 5) // 60:02d}:{(i * 10 + 5) % 60:02d}.000 --> "
                       f"00:{(i * 10 + 14) // 60:02d}:{(i * 10 + 14) % 60:02d}.000\n"
                       f"<v Lærer>Del {i}: sRGB og Adobe RGB har ulike fargerom og gamma.</v>\n\n" for i in range(20)))
VTT_LAB = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nI laben viser vi hvitbalanse.\n"
PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' \
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMG_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _wp(text: str, style: str | None = None, *, numbered: int | None = None) -> str:
    ppr = ""
    if style or numbered is not None:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        if numbered is not None:
            ppr += f'<w:numPr><w:ilvl w:val="{numbered}"/><w:numId w:val="1"/></w:numPr>'
        ppr += "</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def diagram_png(size: tuple[int, int] = (400, 300), *, seed: int = 0) -> bytes:
    """A small but «informative» test image (shapes and a gradient), made with Pillow."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (250, 250, 250))
    draw = ImageDraw.Draw(image)
    width, height = size
    for x in range(width):
        draw.line([(x, 0), (x, height // 4)], fill=(x * 255 // width, 80 + seed, 160))
    if width >= 120 and height >= 120:
        draw.ellipse([width // 4, height // 3, width // 2, height - 20], fill=(220, 40, 40))
        draw.rectangle([width // 2 + 20, height // 3, width - 30, height - 40], fill=(30, 90, 200))
        draw.text((10, height - 18), "ROD GUL BLA", fill=(0, 0, 0))
    else:
        draw.rectangle([0, height // 2, width - 1, height - 1], fill=(30, 90, 200))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def rich_docx() -> bytes:
    body = [
        _wp("Forelesningsnotater om bildebehandling", "Title"),
        _wp("Rasterbilder", "Heading1"),
        _wp("Et rasterbilde består av piksler. Oppløsningen avgjør hvor skarpt bildet blir når det forstørres."),
        _wp("JPEG passer for fotografier", numbered=0),
        _wp("PNG støtter gjennomsiktighet", numbered=0),
        _wp("Tapsfri komprimering", numbered=1),
        _wp("Vektorgrafikk", "Heading1"),
        _wp("Vektorgrafikk beskrives med matematiske kurver og kan skaleres uten tap av kvalitet."),
        "<w:tbl><w:tr><w:tc>" + _wp("Format") + "</w:tc><w:tc>" + _wp("Type") + "</w:tc></w:tr>"
        "<w:tr><w:tc>" + _wp("SVG") + "</w:tc><w:tc>" + _wp("Vektor") + "</w:tc></w:tr>"
        "<w:tr><w:tc>" + _wp("PNG") + "</w:tc><w:tc>" + _wp("Raster") + "</w:tc></w:tr></w:tbl>",
        '<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Bilde 1" descr="Diagram over piksler"/>'
        '<a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>",
        "<w:p><w:r><w:delText>slettet tekst</w:delText></w:r></w:p>",
    ]
    styles = (f'<?xml version="1.0"?><w:styles {W_NS}>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>')
    return _zip({
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                               'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        "word/document.xml": f'<?xml version="1.0"?><w:document {W_NS}><w:body>{"".join(body)}</w:body></w:document>',
        "word/styles.xml": styles,
        "word/_rels/document.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">'
                                        f'<Relationship Id="rId5" Type="{IMG_REL}" Target="media/image1.png"/>'
                                        "</Relationships>",
        "word/media/image1.png": PNG_1X1,
    })


def rich_pptx() -> bytes:
    p = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

    def title(text: str) -> str:
        return ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Tittel"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr>'
                f"</p:nvSpPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>")

    def body(lines: list[tuple[int, str]]) -> str:
        paras = "".join(f'<a:p><a:pPr lvl="{lvl}"/><a:r><a:t>{t}</a:t></a:r></a:p>' for lvl, t in lines)
        return ('<p:sp><p:nvSpPr><p:cNvPr id="3" name="Innhold"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr>'
                f"</p:nvSpPr><p:txBody>{paras}</p:txBody></p:sp>")

    table = ('<p:graphicFrame><a:graphic><a:graphicData><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Farge</a:t>'
             "</a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Hex</a:t></a:r></a:p></a:txBody></a:tc>"
             "</a:tr><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Rød</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody>"
             "<a:p><a:r><a:t>#ff0000</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic>"
             "</p:graphicFrame>")
    slide1 = f'<?xml version="1.0"?><p:sld {p} {a} {r}><p:cSld><p:spTree>{title("Fargemodeller")}' \
             f'{body([(0, "RGB brukes på skjerm"), (1, "Additiv fargeblanding"), (0, "CMYK brukes på trykk")])}' \
             "</p:spTree></p:cSld></p:sld>"
    slide2 = f'<?xml version="1.0"?><p:sld {p} {a} {r}><p:cSld><p:spTree>{title("Fargetabell")}{table}' \
             "</p:spTree></p:cSld></p:sld>"
    notes = f'<?xml version="1.0"?><p:notes {p} {a}><p:cSld><p:spTree>' \
            f'{body([(0, "Husk å vise fargehjulet og forklare komplementærfarger.")])}</p:spTree></p:cSld></p:notes>'
    notes_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
    slide_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
    return _zip({
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                               'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        "ppt/presentation.xml": f'<?xml version="1.0"?><p:presentation {p} {r}><p:sldIdLst>'
                                '<p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
                                "</p:presentation>",
        "ppt/_rels/presentation.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">'
                                           f'<Relationship Id="rId2" Type="{slide_rel}" Target="slides/slide1.xml"/>'
                                           f'<Relationship Id="rId3" Type="{slide_rel}" Target="slides/slide2.xml"/>'
                                           "</Relationships>",
        "ppt/slides/slide1.xml": slide1,
        "ppt/slides/slide2.xml": slide2,
        "ppt/slides/_rels/slide1.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">'
                                            f'<Relationship Id="rId9" Type="{notes_rel}" '
                                            'Target="../notesSlides/notesSlide1.xml"/></Relationships>',
        "ppt/notesSlides/notesSlide1.xml": notes,
    })


def rich_xlsx() -> bytes:
    s = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sheet = (f'<?xml version="1.0"?><worksheet {s}><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>15</v></c></row>'
             '<row r="3"><c r="A3" t="inlineStr"><is><t>Eksamen</t></is></c><c r="B3"><v>4.5</v></c></row>'
             "</sheetData></worksheet>")
    shared = (f'<?xml version="1.0"?><sst {s}><si><t>Aktivitet</t></si><si><t>Uke</t></si>'
              "<si><t>Innlevering 1</t></si></sst>")
    ws_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    return _zip({
        "xl/workbook.xml": f'<?xml version="1.0"?><workbook {s}><sheets><sheet name="Plan" sheetId="1" r:id="rId1"/>'
                           '<sheet name="Skjult" sheetId="2" state="hidden" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0"?><Relationships xmlns="{REL_NS}">'
                                      f'<Relationship Id="rId1" Type="{ws_rel}" Target="worksheets/sheet1.xml"/>'
                                      f'<Relationship Id="rId2" Type="{ws_rel}" Target="worksheets/sheet2.xml"/>'
                                      "</Relationships>",
        "xl/worksheets/sheet1.xml": sheet,
        "xl/worksheets/sheet2.xml": sheet.replace("Eksamen", "Hemmelig"),
        "xl/sharedStrings.xml": shared,
    })


def rich_odt() -> bytes:
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')
    content = (f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:text>'
               '<text:h text:outline-level="1">Pensum</text:h><text:p>Les kapittel 1<text:s/>og 2.</text:p>'
               "<text:list><text:list-item><text:p>Kapittel 1</text:p></text:list-item></text:list>"
               "<table:table><table:table-row><table:table-cell><text:p>Uke</text:p></table:table-cell>"
               "<table:table-cell><text:p>Tema</text:p></table:table-cell></table:table-row><table:table-row>"
               "<table:table-cell><text:p>34</text:p></table:table-cell><table:table-cell><text:p>Farger</text:p>"
               "</table:table-cell></table:table-row></table:table></office:text></office:body>"
               "</office:document-content>")
    return _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})


def rtf_bytes() -> bytes:
    return (rb"{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}{\info{\title Skjult}}"
            rb"\f0 Fargel\'e6re er l\'e6ren om farger.\par Bl\u229? og gr\'f8nn.\par}")


class FakeSentenceTransformer:
    """Deterministic stand-in for a sentence-transformers model: hashed bag of Norwegian stems."""

    dim = 64
    max_seq_length = 512

    def encode(self, texts: list[str], **_kwargs: Any) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in stems(text):
                digest = hashlib.sha1(token.encode()).digest()
                out[row, digest[0] % self.dim] += 1.0 + digest[1] / 255
        return out


class FakeCrossEncoder:
    """Lexical overlap between query and passage stems (enough to test the reranking wiring)."""

    def predict(self, pairs: list[tuple[str, str]], **_kwargs: Any) -> list[float]:
        scores = []
        for query, passage in pairs:
            q, p = set(stems(query)), set(stems(passage))
            scores.append(len(q & p) / (len(q) or 1))
        return scores


class FakeLocalModels(LocalModels):
    def __init__(self, models_dir: Path, *, installed: bool = True, downloaded: bool = True) -> None:
        super().__init__(models_dir)
        self.installed = installed
        self.downloaded = downloaded
        self.loads: list[str] = []

    def packages(self) -> dict[str, bool]:
        return {"sentence_transformers": self.installed, "faster_whisper": self.installed,
                "youtube_transcript_api": False, "ctranslate2": self.installed, "transformers": self.installed}

    def cuda_available(self) -> bool | None:
        return False

    def is_downloaded(self, model_id: str) -> bool:
        return self.downloaded

    def load_embedder(self, model: LocalModelDef, device: str) -> Any:
        self.loads.append(f"embedding:{model.id}")
        self.downloaded = True
        return FakeSentenceTransformer()

    def load_reranker(self, model: LocalModelDef, device: str) -> Any:
        self.loads.append(f"reranker:{model.id}")
        return FakeCrossEncoder()


def _page(slug: str, title: str, body: str | None, *, published: bool = True, updated: str = "2026-09-01T10:00:00Z",
          editor: str = "rce") -> dict[str, Any]:
    return {"page_id": f"9{abs(hash(slug)) % 10000}", "url": slug, "title": title, "body": body,
            "published": published, "front_page": slug == "forside", "editing_roles": "teachers",
            "updated_at": updated, "editor": editor, "html_url": f"/courses/{RAG_COURSE}/pages/{slug}"}


def seed_rag_course(state: FakeCanvasState) -> CourseData:
    """A small course with teacher and student content, documents and a module structure."""
    origin = state.origin
    c = CourseData(course={
        "id": RAG_COURSE, "name": "Bildebehandling 1", "course_code": "BIB1 26H", "workflow_state": "available",
        "default_view": "modules", "time_zone": "Europe/Oslo", "term": {"id": "7", "name": "Høst 2026"},
        "enrollments": [{"type": "teacher", "role": "TeacherEnrollment", "enrollment_state": "active"}],
        "syllabus_body": "<h2>Emneplan</h2><p>Emnet gir en innføring i digital bildebehandling og fargelære.</p>",
    })
    c.permissions = {"manage": True, "update": True, "read_as_admin": True}
    c.users = [{"id": "42", "name": "Kari Lærer", "enrollment": "teacher"},
               {"id": "43", "name": "Ola Assistent", "enrollment": "ta"},
               {"id": "77", "name": "Siri Student", "enrollment": "student"}]
    pages = [
        _page("forside", "Velkommen til Bildebehandling 1",
              "<h1>Velkommen</h1><p>I dette emnet lærer du om <strong>digitale bilder</strong>.</p>"
              "<p>Undervisningen er på tirsdager kl. 10 i rom A101.</p>"),
        _page("raster-og-vektor", "Raster og vektor",
              "<h2>Rasterbilder</h2><p>Et rasterbilde er bygd opp av piksler i et rutenett.</p>"
              "<h2>Vektorbilder</h2><p>Vektorbilder lagres som matematiske former og kan skaleres fritt.</p>"
              "<table><tr><th>Format</th><th>Type</th></tr><tr><td>JPEG</td><td>Raster</td></tr>"
              "<tr><td>SVG</td><td>Vektor</td></tr></table>"
              f'<p>Les mer i <a href="/courses/{RAG_COURSE}/files/7001">forelesningsnotatene</a>.</p>'),
        _page("fargelaere", "Fargelære",
              "<h2>Fargemodeller</h2><ul><li>RGB for skjerm</li><li>CMYK for trykk</li></ul>"
              "<p>Komplementærfarger ligger rett overfor hverandre i fargehjulet.</p>"),
        _page("utkast", "Utkast til eksamen", "<p>Eksamensoppgaven er hemmelig.</p>", published=False),
        _page("blokk", "Blokkside", None, editor="block_editor"),
        _page("bilder", "Bilder i emnet",
              "<h2>Fargehjulet</h2><p>Fargehjulet viser primærfarger og sekundærfarger.</p>"
              f'<p><img src="/courses/{RAG_COURSE}/files/7201/preview" alt="Fargehjul"></p>'
              f'<p><img src="/courses/{RAG_COURSE}/files/7202/preview" width="16" height="16" alt="info"></p>'
              f'<p><img src="/courses/{RAG_COURSE}/files/7203/preview" alt="Høgskolens logo"></p>'
              f'<p><img src="/courses/{RAG_COURSE}/files/7204/preview" alt="Fargehjul igjen"></p>'
              f'<p><img src="/courses/{RAG_COURSE}/files/7205/preview" alt=""></p>'
              '<p><img src="https://cdn.example.org/figur.svg" alt="Figur"></p>'),
        _page("forelesninger", "Forelesninger på video",
              "<h2>Opptak</h2><p>Se forelesningen om fargerom.</p>"
              '<iframe title="Forelesning om fargerom" data-media-id="m-farge1" '
              'src="/media_objects_iframe/m-farge1?type=video"></iframe>'
              '<iframe title="Lab-demo" src="/media_attachments_iframe/7101?type=video&amp;embedded=true"></iframe>'
              '<iframe title="Gjesteforelesning" src="https://www.youtube.com/embed/abcdefghijk"></iframe>'
              '<iframe title="Opptak" src="https://hvl.cloud.panopto.eu/Panopto/Pages/Embed.aspx?id=1"></iframe>'),
    ]
    c.pages = {p["url"]: p for p in pages}
    c.assignments = {
        "8001": {"id": "8001", "name": "Innlevering 1: Fargekorrigering",
                 "description": "<p>Korriger fargene i tre bilder og forklar valgene dine.</p>",
                 "html_url": f"/courses/{RAG_COURSE}/assignments/8001", "published": True, "points_possible": 10,
                 "due_at": "2026-09-15T21:59:00Z", "submission_types": ["online_upload"],
                 "updated_at": "2026-09-01T10:00:00Z"},
    }
    c.discussions = {
        "8101": {"id": "8101", "title": "Spørsmål om pensum", "message": "<p>Still spørsmål om pensum her.</p>",
                 "html_url": f"/courses/{RAG_COURSE}/discussion_topics/8101", "published": True,
                 "author": {"id": "42", "display_name": "Kari Lærer"}, "updated_at": "2026-09-01T10:00:00Z"},
        "8102": {"id": "8102", "title": "Mitt hemmelige studentinnlegg",
                 "message": "<p>Personlig studentinnhold som aldri skal indekseres.</p>",
                 "html_url": f"/courses/{RAG_COURSE}/discussion_topics/8102", "published": True,
                 "author": {"id": "77", "display_name": "Siri Student"}, "updated_at": "2026-09-01T10:00:00Z"},
    }
    c.quizzes = {
        "8201": {"id": "8201", "title": "Øvingsquiz om farger", "description": "<p>Test deg selv på fargelære.</p>",
                 "quiz_type": "practice_quiz", "question_count": 5, "allowed_attempts": -1, "published": True,
                 "html_url": f"/courses/{RAG_COURSE}/quizzes/8201", "updated_at": "2026-09-01T10:00:00Z"},
    }
    files = {
        "7001": ("Forelesningsnotater.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 rich_docx(), "42"),
        "7002": ("Fargemodeller.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                 rich_pptx(), "42"),
        "7003": ("Pensumliste.pdf", "application/pdf", minimal_pdf(text="Pensum: Kapittel 1 om fargerom og gamma"), "42"),
        "7004": ("Studentrapport.pdf", "application/pdf", minimal_pdf(text="Studentens egen rapport"), "77"),
        "7005": ("Gammel.doc", "application/msword", b"\xd0\xcf\x11\xe0", "42"),
        "7006": ("Plan.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", rich_xlsx(), "42"),
        "7007": ("Skannet.pdf", "application/pdf", minimal_pdf(text=None), "42"),
        "7101": ("Lab-demo.mp4", "video/mp4", b"\x00\x00\x00\x18ftypmp42fakevideo", "42"),
        "7201": ("fargehjul.png", "image/png", diagram_png(), "42"),
        "7202": ("lite.png", "image/png", diagram_png((16, 16)), "42"),
        "7203": ("hvl-logo.png", "image/png", diagram_png((300, 200), seed=40), "42"),
        "7204": ("fargehjul-kopi.png", "image/png", diagram_png(), "42"),
        "7205": ("pynt.png", "image/png", diagram_png((300, 200), seed=80), "42"),
        "7102": ("Lab-demo.vtt", "text/vtt", VTT_LAB.encode(), "42"),
    }
    for fid, (name, ctype, data, uploader) in files.items():
        c.files[fid] = {"id": fid, "display_name": name, "filename": name, "content-type": ctype, "size": len(data),
                        "url": f"{origin}/files/{fid}/download?download_frd=1", "updated_at": "2026-09-01T10:00:00Z",
                        "folder_id": "1", "user": {"id": uploader, "display_name": "x"}}
        state.file_bytes[fid] = (data, ctype)

    c.media_objects = [
        {"media_id": "m-farge1", "title": "fargerom.mp4", "media_type": "video",
         "media_tracks": [{"id": "11", "kind": "subtitles", "locale": "nb", "workflow_state": "ready", "asr": False,
                           "url": f"{origin}/media_objects/m-farge1/media_tracks/11", "webvtt_content": VTT_FARGE}],
         "media_sources": [{"url": f"{origin}/files/7101/download", "content_type": "video/mp4", "bitrate": "800",
                            "size": "30000"}]},
        {"media_id": "m-student", "title": "Studentopptak", "media_type": "video", "media_tracks": [],
         "media_sources": []},
    ]
    state.attachment_tracks["7101"] = []

    def item(item_id: str, title: str, type_: str, **extra: Any) -> dict[str, Any]:
        return {"id": item_id, "title": title, "type": type_, "position": int(item_id[-1]), "indent": 0,
                "published": True, "html_url": f"/courses/{RAG_COURSE}/modules/items/{item_id}", **extra}

    c.modules = [
        {"id": "301", "name": "Modul 1 – Grunnlag", "position": 1, "published": True,
         "items": [item("3011", "Raster og vektor", "Page", page_url="raster-og-vektor"),
                   item("3012", "Forelesningsnotater", "File", content_id="7001"),
                   item("3013", "Ekstern ressurs", "ExternalUrl", external_url="https://www.example.org/ressurs"),
                   item("3014", "Panopto-opptak", "ExternalTool", content_id="5")]},
        {"id": "303", "name": "Modul 3 – Video", "position": 3, "published": True,
         "items": [item("3031", "Forelesninger på video", "Page", page_url="forelesninger"),
                   item("3033", "Bilder i emnet", "Page", page_url="bilder"),
                   item("3032", "Ekstra video", "ExternalUrl", external_url="https://youtu.be/zyxwvutsrqp")]},
        {"id": "302", "name": "Modul 2 – Farger", "position": 2, "published": True,
         "items": [item("3021", "Fargelære", "Page", page_url="fargelaere"),
                   item("3022", "Fargemodeller", "File", content_id="7002"),
                   item("3023", "Innlevering 1: Fargekorrigering", "Assignment", content_id="8001"),
                   item("3024", "Øvingsquiz om farger", "Quiz", content_id="8201")]},
    ]
    state.courses[RAG_COURSE] = c
    return c
