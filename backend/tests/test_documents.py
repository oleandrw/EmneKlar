"""Document checks: only defensible automated checks; tagged PDFs are never declared accessible."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from emneklar.core.security.isolation import InlineRunner, execute_job
from emneklar.features.accessibility.documents import document_format, document_issues, inspect_document
from tests.fakes.documents import minimal_docx, minimal_pdf, minimal_pptx


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def rules(result: dict, created: str | None = "2026-08-01T00:00:00Z") -> list[str]:
    return [i.rule_id for i in document_issues(result, name="fil", created_at=created)]


def test_scanned_untagged_pdf(tmp_path: Path) -> None:
    result = inspect_document(str(write(tmp_path, "a.pdf", minimal_pdf(text=None))), "pdf")
    assert result["has_text"] is False and result["tagged"] is False
    found = rules(result)
    assert {"UU-DOC-PDF-NO-TEXT", "UU-DOC-PDF-UNTAGGED", "UU-DOC-NO-TITLE", "UU-DOC-NO-LANG",
            "UU-DOC-MANUAL"} <= set(found)


def test_tagged_pdf_still_requires_manual_check(tmp_path: Path) -> None:
    pdf = minimal_pdf(text="Pensumliste med tekst som kan leses av skjermleser", tagged=True, title="Pensum", lang="nb")
    result = inspect_document(str(write(tmp_path, "b.pdf", pdf)), "pdf")
    assert result["tagged"] is True and result["has_text"] is True and result["lang"] == "nb"
    found = rules(result)
    assert found == ["UU-DOC-MANUAL"], "a tagged PDF is never declared accessible"
    manual = document_issues(result, name="b.pdf", created_at=None)[0]
    assert manual.evidence["requires_manual_check"]
    assert manual.evidence["automatically_checked"]


def test_docx_checks(tmp_path: Path) -> None:
    bad = inspect_document(str(write(tmp_path, "a.docx", minimal_docx(paragraphs=20, image_alt=None,
                                                                         with_table=True))), "docx")
    assert bad["images_without_alt"] == 1 and bad["headings"] == 0
    assert {"UU-DOC-IMG-ALT", "UU-DOC-NO-HEADINGS", "UU-DOC-TABLE-HEADER", "UU-DOC-NO-TITLE",
            "UU-DOC-NO-LANG"} <= set(rules(bad))
    good = inspect_document(str(write(tmp_path, "b.docx", minimal_docx(
        paragraphs=20, heading=True, image_alt="Graf over karakterfordeling", title="Notat", lang="nb-NO",
        with_table=True, table_header=True))), "docx")
    assert rules(good) == ["UU-DOC-MANUAL"]


def test_pptx_slide_titles_and_alt(tmp_path: Path) -> None:
    result = inspect_document(str(write(tmp_path, "a.pptx", minimal_pptx())), "pptx")
    assert result["slides_without_title"] == [2]
    assert result["images_without_alt"] == 1
    assert {"UU-DOC-SLIDE-TITLES", "UU-DOC-IMG-ALT"} <= set(rules(result))


def test_legacy_and_broken_files(tmp_path: Path) -> None:
    assert rules({"format": "doc"}) == ["UU-DOC-UNREADABLE"]
    broken = inspect_document(str(write(tmp_path, "x.docx", b"not a zip")), "docx")
    assert rules(broken) == ["UU-DOC-UNREADABLE"]


def test_zip_bomb_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"0" * (70 * 1024 * 1024))
    result = inspect_document(str(write(tmp_path, "bomb.docx", buf.getvalue())), "docx")
    assert result["error"] == "limits"


def test_old_document_gets_exemption_hint(tmp_path: Path) -> None:
    result = inspect_document(str(write(tmp_path, "old.pdf", minimal_pdf(text=None))), "pdf")
    issues = document_issues(result, name="old.pdf", created_at="2021-08-01T10:00:00Z")
    assert all("exemption_hint" in i.evidence for i in issues)


def test_format_detection() -> None:
    assert document_format("Notat.DOCX") == "docx"
    assert document_format("x", "application/pdf") == "pdf"
    assert document_format("bilde.png") is None


async def test_worker_only_runs_allowlisted_jobs(tmp_path: Path) -> None:
    assert execute_job({"job": "os.system", "args": {"command": "echo hacked"}}) == {"error": "unknown_job"}
    path = write(tmp_path, "c.pdf", minimal_pdf())
    result = await InlineRunner().run({"job": "inspect_document", "args": {"path": str(path), "fmt": "pdf"}}, 30)
    assert result["format"] == "pdf"


@pytest.mark.slow
async def test_isolated_worker_process(tmp_path: Path) -> None:
    from emneklar.core.security.isolation import IsolatedWorkerPool

    pool = IsolatedWorkerPool(size=1)
    try:
        path = write(tmp_path, "d.pdf", minimal_pdf(text="Dette er en PDF med nok tekst til at den kan leses"))
        result = await pool.run({"job": "inspect_document", "args": {"path": str(path), "fmt": "pdf"}}, 60)
        assert result["format"] == "pdf" and result["has_text"] is True
    finally:
        await pool.close()
