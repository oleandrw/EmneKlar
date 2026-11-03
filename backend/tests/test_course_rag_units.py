"""Emne-RAG building blocks: text, Markdown, HTML and document conversion, chunking, store, search, citations."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import numpy as np
import pytest

from emneklar.core.errors import AppError
from emneklar.features.course_rag.answer import clean_answer
from emneklar.features.course_rag.chunking import MAX_TOKENS, TARGET_TOKENS, chunk_blocks, chunk_units, split_long
from emneklar.features.course_rag.citations import citation, timestamp
from emneklar.features.course_rag.convert.documents import convert_document, file_format, rtf_to_text, text_to_blocks
from emneklar.features.course_rag.convert.html_md import html_to_blocks
from emneklar.features.course_rag.markdown import Block, parse_markdown, table_markdown, to_markdown
from emneklar.features.course_rag.search import needs_rewrite, rrf, search
from emneklar.features.course_rag.store import APPLICATION_ID, ChunkRecord, IndexStore, ItemRecord
from emneklar.features.course_rag.text import estimate_tokens, fts_query, stem, stems
from tests.fakes.documents import minimal_pdf
from tests.fakes.rag import FakeSentenceTransformer, rich_docx, rich_odt, rich_pptx, rich_xlsx, rtf_bytes

# ------------------------------------------------------------------------------------------------- text


def test_norwegian_stemming_groups_inflections() -> None:
    assert stem("bildeformater") == stem("bildeformatet") == stem("bildeformatene") == "bildeformat"
    assert stem("innleveringen") == stem("innleveringer") == "innlevering"
    assert stem("studentene") == "student"
    assert stem("2026") == "2026"


def test_stopwords_and_fts_query_are_safe() -> None:
    assert "og" not in stems("Hva er forskjellen på raster og vektor?")
    query = fts_query('Hva er "raster" OR vektor) NEAR*?')
    assert query is not None
    assert query.count('"') % 2 == 0 and "NEAR" not in query.upper().replace('"NEAR"', "")
    assert fts_query("og i er det") is None


def test_token_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(" ".join(["ord"] * 100)) == 140


# --------------------------------------------------------------------------------------------- Markdown


def test_markdown_round_trip_keeps_structure() -> None:
    text = "# Tittel\n\nAvsnitt med *vekt*.\n\n- punkt en\n- punkt to\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n> sitat"
    blocks = parse_markdown(text)
    assert [b.kind for b in blocks] == ["heading", "paragraph", "list", "table", "quote"]
    assert blocks[3].rows == [["A", "B"], ["1", "2"]]
    assert to_markdown(blocks).startswith("# Tittel")
    assert "| 1 | 2 |" in table_markdown([["A", "B"], ["1", "2"]])


def test_plain_text_paragraphs() -> None:
    blocks = parse_markdown("Linje en\nfortsetter\n\n# ikke overskrift", plain=True)
    assert [b.text for b in blocks] == ["Linje en fortsetter", "# ikke overskrift"]


# ------------------------------------------------------------------------------------------------- HTML


def test_html_to_blocks_keeps_headings_lists_tables_and_collects_refs() -> None:
    html = ("<h2>Rasterbilder</h2><p>Bygd av <strong>piksler</strong>. <a href='/courses/1/files/55/download'>Notater</a>"
            "</p><ul><li>JPEG<ul><li>tapsbasert</li></ul></li><li>PNG</li></ul>"
            "<table><tr><th>Format</th><th>Type</th></tr><tr><td>SVG</td><td>Vektor</td></tr></table>"
            "<p><img src='/courses/1/files/56/preview' alt='Diagram over piksler' width='400'></p>"
            "<p><img src='/equation_images/x' alt='E=mc^2'></p>"
            "<iframe title='Forelesning' src='https://www.youtube.com/embed/abcdefghijk'></iframe>"
            "<p style='display:none'>Skjult</p><script>alert(1)</script><div>Løs tekst</div>")
    result = html_to_blocks(html, base_url="https://canvas.test", canvas_host="canvas.test")
    kinds = [b.kind for b in result.blocks]
    assert kinds[:4] == ["heading", "paragraph", "list", "table"]
    md = to_markdown(result.blocks)
    assert "**piksler**" in md and "  - tapsbasert" in md and "| SVG | Vektor |" in md
    assert "$E=mc^2$" in md and "Skjult" not in md and "alert" not in md and "Løs tekst" in md
    assert result.file_ids == ["55"]
    assert [i.file_id for i in result.images] == ["56"]
    assert result.images[0].heading == "Rasterbilder" and result.images[0].alt == "Diagram over piksler"
    assert [m.kind for m in result.media] == ["youtube"]


def test_layout_table_becomes_text() -> None:
    result = html_to_blocks("<table><tr><td>Bare én kolonne med tekst</td></tr></table>", base_url="")
    assert [b.kind for b in result.blocks] == ["paragraph"]


# -------------------------------------------------------------------------------------------- documents


def _convert(tmp_path: Path, name: str, data: bytes, fmt: str, **kwargs: object) -> dict:
    path = tmp_path / name
    path.write_bytes(data)
    return convert_document(str(path), fmt, **kwargs)  # type: ignore[arg-type]


def test_docx_headings_lists_tables_images(tmp_path: Path) -> None:
    result = _convert(tmp_path, "a.docx", rich_docx(), "docx", out_dir=str(tmp_path / "img"))
    blocks = [Block.from_dict(b) for b in result["units"][0]["blocks"]]
    kinds = [(b.kind, b.level) for b in blocks]
    assert ("heading", 1) in kinds
    assert any(b.kind == "list" and "  - Tapsfri komprimering" in b.text for b in blocks)
    assert any(b.kind == "table" and b.rows[1] == ["SVG", "Vektor"] for b in blocks)
    assert "slettet tekst" not in to_markdown(blocks)
    assert result["images"] and result["images"][0]["alt"] == "Diagram over piksler"
    assert Path(result["images"][0]["path"]).is_file()


def test_pptx_one_unit_per_slide_with_notes_and_tables(tmp_path: Path) -> None:
    result = _convert(tmp_path, "a.pptx", rich_pptx(), "pptx")
    units = result["units"]
    assert [u["number"] for u in units] == [1, 2]
    assert units[0]["title"] == "Fargemodeller" and "komplementærfarger" in units[0]["notes"]
    chunks = chunk_units(units, title="Fargemodeller.pptx")
    slides = [c for c in chunks if c.type == "slide"]
    assert len(slides) == 2 and "Notater:" in slides[0].text and "  - Additiv fargeblanding" in slides[0].text
    assert any(c.type == "table" and "#ff0000" in c.text and c.page == 2 for c in chunks)


def test_xlsx_and_odf_and_rtf_csv_txt(tmp_path: Path) -> None:
    sheets = _convert(tmp_path, "a.xlsx", rich_xlsx(), "xlsx")["units"]
    assert [u["title"] for u in sheets] == ["Plan"]  # hidden sheets are skipped
    rows = Block.from_dict(sheets[0]["blocks"][0]).rows
    assert rows == [["Aktivitet", "Uke"], ["Innlevering 1", "15"], ["Eksamen", "4.5"]]
    odt = [Block.from_dict(b) for b in _convert(tmp_path, "a.odt", rich_odt(), "odt")["units"][0]["blocks"]]
    assert [b.kind for b in odt] == ["heading", "paragraph", "list", "table"]
    assert odt[1].text == "Les kapittel 1 og 2."
    assert "Fargelære er læren om farger." in rtf_to_text(rtf_bytes()) and "Blå og grønn" in rtf_to_text(rtf_bytes())
    assert "Skjult" not in rtf_to_text(rtf_bytes())
    csv_rows = Block.from_dict(_convert(tmp_path, "a.csv", b"Uke;Tema\n34;Farger\n", "csv")
                               ["units"][0]["blocks"][0]).rows
    assert csv_rows == [["Uke", "Tema"], ["34", "Farger"]]
    txt = _convert(tmp_path, "a.txt", "Første avsnitt.\n\nAndre avsnitt.".encode("cp1252"), "txt")
    assert len(txt["units"][0]["blocks"]) == 2


def test_pdf_pages_and_scanned_detection(tmp_path: Path) -> None:
    result = _convert(tmp_path, "a.pdf", minimal_pdf(text="Pensum for emnet om fargerom"), "pdf")
    assert result["pages"] == 1 and result["units"][0]["number"] == 1 and not result["needs_ocr"]
    assert _convert(tmp_path, "b.pdf", minimal_pdf(text=None), "pdf")["needs_ocr"] is True


def test_pdf_text_heuristics() -> None:
    blocks = text_to_blocks("1. INNLEDNING\nDette er en lang linje med tekst som fortsetter\npå neste linje.\n"
                            "• første punkt\n• andre punkt\n", page=3)
    assert blocks[0].kind == "heading" and blocks[0].page == 3
    assert any(b.kind == "list" and "- andre punkt" in b.text for b in blocks)


def test_file_formats() -> None:
    assert file_format("Notater.DOCX") == "docx"
    assert file_format("uten-endelse", "application/pdf") == "pdf"
    assert file_format("bilde.jpeg") == "jpg"
    assert file_format("gammel.doc") == "doc"
    assert file_format("arkiv.zip") is None


# --------------------------------------------------------------------------------------------- chunking


def _long(n: int) -> str:
    return " ".join(f"Setning {i} handler om farger og bildeformater i emnet." for i in range(n))


def test_chunks_follow_structure_size_and_overlap() -> None:
    blocks = [Block("heading", "Intro", level=2), Block("paragraph", "Kort."), Block("heading", "Detaljer", level=2),
              Block("paragraph", _long(150)), Block("table", rows=[["A", "B"], ["1", "2"]]),
              Block("heading", "Under", level=3), Block("paragraph", "Litt mer.")]
    chunks = chunk_blocks(blocks)
    text_chunks = [c for c in chunks if c.type == "text"]
    assert all(c.tokens <= MAX_TOKENS + 60 for c in text_chunks)
    assert any(abs(c.tokens - TARGET_TOKENS) < 100 for c in text_chunks)
    assert text_chunks[0].text.startswith("## Intro")  # short section merged into the next one
    first, second = text_chunks[0].text, text_chunks[1].text
    overlap = second.split(". ")[0]
    assert overlap in first  # overlapping sentences
    tables = [c for c in chunks if c.type == "table"]
    assert len(tables) == 1 and tables[0].heading_path == ["Detaljer"]
    assert "Litt mer." in text_chunks[-1].text


def test_long_tables_repeat_header() -> None:
    rows = [["Uke", "Tema"]] + [[str(i), _long(3)] for i in range(40)]
    chunks = chunk_blocks([Block("table", rows=rows)])
    assert len(chunks) > 1 and all(c.text.startswith("| Uke | Tema |") for c in chunks)


def test_split_long_falls_back_to_words() -> None:
    pieces = split_long(" ".join(["ord"] * 2000), limit=300)
    assert len(pieces) > 5 and all(estimate_tokens(p) <= 300 for p in pieces)


# ------------------------------------------------------------------------------------------------ store


def _record(i: int, text: str, *, module: str = "1", type_: str = "text") -> ChunkRecord:
    return ChunkRecord(uid=f"page:p{i}#0", item_key=f"page:p{i}", type=type_, item_kind="page", title=f"Side {i}",
                       text=text, module_ids=[module], module_name=f"Modul {module}", url=f"https://c/p{i}")


def _vectors(records: list[ChunkRecord]) -> np.ndarray:
    from emneklar.core.ai.local.embedding import normalise

    return normalise(FakeSentenceTransformer().encode([r.search_text() for r in records]))


@pytest.mark.parametrize("python_bm25", [False, True])
def test_store_keyword_vector_filters_and_delete(tmp_path: Path, python_bm25: bool) -> None:
    store = IndexStore(tmp_path / "i.sqlite", force_python_bm25=python_bm25)
    store.reset("test:model")
    texts = ["Rasterbilder består av piksler.", "Vektorgrafikk skaleres uten tap.", "Fargehjulet viser komplementærfarger."]
    for i, text in enumerate(texts):
        record = _record(i, text, module="1" if i < 2 else "2", type_="table" if i == 2 else "text")
        store.put_item(ItemRecord(key=record.item_key, kind="page", title=record.title), [record], _vectors([record]))
    assert store.fts is (not python_bm25)
    hits = store.keyword_search("Hva består rasterbildene av?")
    assert hits and store.get_chunks([hits[0][0]])[hits[0][0]].text == texts[0]
    assert store.keyword_search("piksler", module_ids=["2"]) == []
    assert [store.get_chunks([cid])[cid].type for cid, _ in store.keyword_search("komplementærfarger",
                                                                                   types=["table"])] == ["table"]
    query = _vectors([_record(9, "vektorgrafikk skaleres")])[0]
    best = store.vector_search(query, limit=1)
    assert store.get_chunks([best[0][0]])[best[0][0]].text == texts[1]
    assert store.vector_search(query, module_ids=["2"], limit=3)[0][0] != best[0][0]
    store.delete_items(["page:p0"])
    assert store.keyword_search("piksler") == [] and store.stats()["chunks"] == 2
    store.close()


def test_store_refuses_foreign_and_outdated_files(tmp_path: Path) -> None:
    import sqlite3

    foreign = tmp_path / "foreign.sqlite"
    conn = sqlite3.connect(foreign)
    conn.execute("PRAGMA application_id = 1234")
    conn.execute("CREATE TABLE x(a)")
    conn.commit()
    conn.close()
    with pytest.raises(AppError) as exc:
        IndexStore(foreign)
    assert exc.value.code == "rag_index_foreign"
    store = IndexStore(tmp_path / "ok.sqlite")
    store.set_meta("schema_version", "999")
    store.close()
    with pytest.raises(AppError) as exc:
        IndexStore(tmp_path / "ok.sqlite")
    assert exc.value.code == "rag_index_outdated"
    with (tmp_path / "ok.sqlite").open("rb") as fh:
        assert int.from_bytes(fh.read(100)[68:72], "big") == APPLICATION_ID


# ----------------------------------------------------------------------------------------------- search


def test_rrf_rewards_agreement() -> None:
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    assert [cid for cid, _ in fused][:2] == [1, 3]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_query_rewrite_only_for_long_vague_questions() -> None:
    assert not needs_rewrite("Hva er RGB?")
    assert not needs_rewrite("frist innlevering 1")
    assert needs_rewrite("Kan du forklare hva det er vi egentlig skal gjøre med dette her?")


class _Embedder:
    identity = "test:model"

    async def embed_documents(self, texts: list[str]) -> np.ndarray:
        from emneklar.core.ai.local.embedding import normalise

        return normalise(FakeSentenceTransformer().encode(texts))

    async def embed_query(self, text: str) -> np.ndarray:
        return (await self.embed_documents([text]))[0]


class _Reranker:
    identity = "test:reranker"

    async def score(self, query: str, passages: list[str]) -> list[float]:
        return [1.0 if "Vektorgrafikk" in p else 0.0 for p in passages]


def test_hybrid_search_fuses_and_reranks(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "i.sqlite")
    store.reset("test:model")
    records = [_record(i, t) for i, t in enumerate(["Rasterbilder består av piksler.",
                                                     "Vektorgrafikk skaleres uten tap av kvalitet.",
                                                     "Piksler og vektorer sammenlignes."])]
    for record in records:
        store.put_item(ItemRecord(key=record.item_key, kind="page", title=record.title), [record], _vectors([record]))
    outcome = asyncio.run(search(store, "piksler", embedder=_Embedder(), reranker=None, top_k=2))
    assert outcome.modes == {"keyword": True, "vector": True, "rerank": False, "rewritten": False}
    assert all(h.keyword_rank or h.vector_rank for h in outcome.hits)
    reranked = asyncio.run(search(store, "piksler", embedder=_Embedder(), reranker=_Reranker(), top_k=3))
    assert reranked.modes["rerank"] and reranked.hits[0].chunk.text.startswith("Vektorgrafikk")
    debug = reranked.as_dict(debug=True)["debug"]
    assert len(debug["before_rerank"]) == len(debug["after_rerank"]) and "rerank_score" in debug["after_rerank"][0][
        "scores"]

    class Other(_Embedder):
        identity = "other:model"

    mismatch = asyncio.run(search(store, "piksler", embedder=Other(), reranker=None))
    assert not mismatch.modes["vector"] and mismatch.notes
    store.close()


# ------------------------------------------------------------------------------------------- citations


def test_citation_labels() -> None:
    page = _record(1, "x")
    assert citation(page) == "Side 1 – Modul 1"
    pdf = ChunkRecord(uid="f#0", item_key="file:1", type="text", item_kind="file", title="Pensum.pdf", text="x",
                      page=4, meta={"format": "pdf"})
    assert citation(pdf) == "Pensum.pdf s. 4"
    pdf.page_end = 5
    assert citation(pdf) == "Pensum.pdf s. 4–5"
    slide = ChunkRecord(uid="f#1", item_key="file:2", type="slide", item_kind="file", title="F.pptx", text="x", page=3,
                        meta={"format": "pptx"})
    assert citation(slide) == "F.pptx lysbilde 3"
    video = ChunkRecord(uid="m#0", item_key="media:1", type="transcript", item_kind="media", title="Forelesning 1",
                        text="x", start=754)
    assert citation(video) == "Video «Forelesning 1» – 12:34"
    image = ChunkRecord(uid="i#0", item_key="image:1", type="image", item_kind="image", title="Bilde",
                        text="x", meta={"page_title": "Fargelære"})
    assert citation(image) == "Bilde på «Fargelære»"
    assert timestamp(3725) == "1:02:05"


def test_answer_citations_to_unknown_sources_are_removed() -> None:
    text, cited = clean_answer("RGB brukes på skjerm [S1]. CMYK på trykk [S9][S2].", {"S1", "S2"})
    assert text == "RGB brukes på skjerm [S1]. CMYK på trykk [S2]."
    assert cited == ["S1", "S2"]


# ------------------------------------------------------------------------------------------ video/audio


def test_parse_webvtt_and_srt_captions() -> None:
    from emneklar.features.course_rag.media import parse_captions

    vtt = ("WEBVTT\n\nNOTE en kommentar\n\nSTYLE\n::cue { color: red }\n\n00:01.000 --> 00:03.500 align:start\n"
           "<v Kari>Hei og <b>velkommen</b></v>\n\n00:03.500 --> 00:05.000\nHei og velkommen til emnet\n\n"
           "01:02:03.250 --> 01:02:05.000\nSiste &amp; beste\n")
    segments = parse_captions(vtt)
    assert [(s.start, s.text) for s in segments] == [(1.0, "Hei og velkommen til emnet"), (3723.25, "Siste & beste")]
    srt = "1\n00:00:01,000 --> 00:00:02,500\nFørste linje\nandre linje\n\n2\n00:00:03,000 --> 00:00:04,000\nNeste\n"
    assert [(s.end, s.text) for s in parse_captions(srt)] == [(2.5, "Første linje andre linje"), (4.0, "Neste")]
    assert parse_captions("ikke teksting") == []


def test_transcript_chunks_cut_at_sentences_with_overlap() -> None:
    from emneklar.core.ai.local.whisper import Segment
    from emneklar.features.course_rag.media import chunk_transcript

    segments = [Segment(i * 8.0, i * 8.0 + 7.5, f"Setning {i}{'.' if i % 3 == 2 else ''}") for i in range(60)]
    chunks = chunk_transcript(segments, title="Forelesning")
    assert all(c.type == "transcript" and c.heading_path == ["Forelesning"] for c in chunks)
    assert all(60 <= (c.end or 0) - (c.start or 0) <= 130 for c in chunks[:-1])
    assert all(c.text.rstrip().endswith(".") or (c.end or 0) - (c.start or 0) >= 120 for c in chunks[:-1])
    assert chunks[1].start is not None and chunks[0].end is not None and chunks[1].start < chunks[0].end  # overlap
    assert chunks[-1].end == segments[-1].end


def test_track_choice_timestamps_and_duration() -> None:
    from emneklar.features.course_rag.media import choose_track, timestamp_url
    from emneklar.features.course_rag.sources import SourceItem, media_duration

    tracks = [{"kind": "subtitles", "locale": "en", "workflow_state": "ready"},
              {"kind": "captions", "locale": "nb", "workflow_state": "ready", "asr": True},
              {"kind": "subtitles", "locale": "nb", "workflow_state": "ready"},
              {"kind": "descriptions", "locale": "nb"}, {"kind": "subtitles", "locale": "nn", "workflow_state": "pending"}]
    assert choose_track(tracks) == tracks[2]
    youtube = SourceItem("youtube:abc", "youtube", "abc", "Video", "https://www.youtube.com/watch?v=abc", None)
    assert timestamp_url(youtube, 754.6) == "https://www.youtube.com/watch?v=abc&t=754s"
    canvas = SourceItem("media:m1", "media", "m1", "Video", "https://c/courses/1/pages/p", None,
                        meta={"sources": [{"size": "204", "bitrate": "382"}]})
    assert timestamp_url(canvas, 10) == "https://c/courses/1/pages/p"
    assert media_duration(canvas) == pytest.approx(204 * 8 / 382)


def test_whisper_model_size_follows_hardware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from emneklar.core.ai.local import LocalModels, whisper

    local = LocalModels(tmp_path)
    assert whisper.auto_size("cuda") == "large"
    monkeypatch.setattr(whisper, "memory_gb", lambda: 8.0)
    assert whisper.auto_size("cpu") == "small"
    nb, other = whisper.choose_models(local, "auto", "", "cuda")
    assert nb.id == "NbAiLab/nb-whisper-large" and other.id == "Systran/faster-whisper-large-v3"
    nb, _ = whisper.choose_models(local, "medium", "", "cpu")
    assert nb.id == "NbAiLab/nb-whisper-medium"


# ----------------------------------------------------------------------------------------------- images


def test_decorative_images_are_filtered_from_metadata() -> None:
    from emneklar.features.course_rag.images import metadata_reason

    assert metadata_reason({"src": "/courses/1/files/2/preview", "alt": "Diagram"}) is None
    assert "dekorativt" in (metadata_reason({"src": "/x.png", "alt": ""}) or "")
    assert "dekorativt" in (metadata_reason({"src": "/x.png", "alt": None, "role": "presentation"}) or "")
    assert "lite" in (metadata_reason({"src": "/x.png", "alt": "i", "width": 24, "height": 24}) or "")
    assert "SVG" in (metadata_reason({"src": "https://cdn/figur.svg", "alt": "Figur"}) or "")
    assert "pynt" in (metadata_reason({"src": "/files/hvl-logo.png", "alt": "Logo"}) or "")
    assert "pynt" in (metadata_reason({"src": "/files/3/preview", "alt": "x", "classes": "icon-small"}) or "")
    assert "Canvas" in (metadata_reason({"src": "/images/svg-icons/x.png", "alt": "x"}) or "")


def test_image_preparation_pixels_and_duplicates(tmp_path: Path) -> None:
    from emneklar.features.course_rag.convert.imageprep import prepare_image
    from emneklar.features.course_rag.images import Deduplicator, pixel_reason
    from tests.fakes.rag import diagram_png

    def prep(name: str, data: bytes) -> dict:
        (tmp_path / name).write_bytes(data)
        return prepare_image(str(tmp_path / name), str(tmp_path / f"{name}-klar"))

    big = prep("a.png", diagram_png((2400, 1800)))
    assert big["width"] == 2400 and Path(big["path"]).is_file() and big["media_type"] == "image/jpeg"
    from PIL import Image

    with Image.open(big["path"]) as resized:
        assert max(resized.size) == 1568
    assert pixel_reason(prep("b.png", diagram_png())) is None
    assert "lite" in (pixel_reason(prep("c.png", diagram_png((40, 40)))) or "")
    assert "banner" in (pixel_reason(prep("d.png", diagram_png((1200, 100)))) or "").lower()
    plain = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(plain, format="PNG")
    assert "ensfarget" in (pixel_reason(prep("e.png", plain.getvalue())) or "")
    assert prep("f.png", b"not an image")["error"] == "not_image"
    dedupe = Deduplicator()
    first, again = prep("g.png", diagram_png()), prep("h.png", diagram_png((420, 315)))
    dedupe.add(first["dhash"], "«Side A»")
    assert dedupe.duplicate_of(again["dhash"]) == "«Side A»"
    other = Image.new("RGB", (400, 300), (255, 255, 255))
    other.paste((0, 0, 0), (0, 0, 200, 300))
    buf = io.BytesIO()
    other.save(buf, format="PNG")
    assert dedupe.duplicate_of(prep("i.png", buf.getvalue())["dhash"]) is None
