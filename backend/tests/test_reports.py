"""Rapporter: HTML/CSV from stored results, fixed/ignored/manual sections, no certification language, safe files."""

from __future__ import annotations

from fastapi.testclient import TestClient

from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Report
from emneklar.features.reporting.render import _cell
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID


def analyse(client: TestClient, domains: list[str]) -> None:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": domains}).json()
    assert wait_for_job(client, job["id"])["status"] == "completed"


def findings(client: TestClient, domain: str) -> list[dict]:
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain={domain}&page_size=200").json()["items"]


def create(client: TestClient, report_type: str, fmt: str = "html") -> dict:
    response = client.post(f"/api/courses/{COURSE_ID}/reports", json={"report_type": report_type, "format": fmt})
    assert response.status_code == 200, response.text
    return response.json()


def test_report_requires_an_analysis(canvas_client: TestClient) -> None:
    response = canvas_client.post(f"/api/courses/{COURSE_ID}/reports", json={"report_type": "accessibility"})
    assert response.status_code == 400 and "analyse" in response.json()["error"]["message"]
    types = {t["value"]: t for t in canvas_client.get(f"/api/courses/{COURSE_ID}/reports/types").json()["types"]}
    assert types["accessibility"]["analysed"] is False


def test_accessibility_report_html(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["accessibility"])
    items = findings(canvas_client, "accessibility")
    ignored = next(f for f in items if f["classification"] in ("should_review", "improvement"))
    canvas_client.post(f"/api/findings/{ignored['id']}/ignore", json={"note": "Vurdert"})
    missing = next(f for f in items if f["rule_id"] == "UU-IMG-MISSING-ALT")
    change = canvas_client.post(f"/api/findings/{missing['id']}/fix/stage", json={"text": "Skjermbilde av verktøyet"})
    assert change.status_code == 200, change.text
    job = canvas_client.post("/api/changes/apply", json={"ids": [change.json()["id"]]}).json()
    assert wait_for_job(canvas_client, job["id"])["result"]["summary"] == {"applied": 1}

    report = create(canvas_client, "accessibility")
    assert report["type_label"] == "UU-analyse" and report["filename"].endswith(".html")
    html = canvas_client.get(f"/api/reports/{report['id']}/view").text
    assert '<html lang="nb">' in html and "<script" not in html
    assert "Digital kompetanse for lærere" in html and "Regulatorisk profil" in html
    assert "ikke en erklæring eller sertifisering" in html
    assert "100 %" not in html, "never certification-like percentages"
    assert "Manuell kontroll" in html and "Rettet (1)" in html and "Ignorert (1)" in html
    assert "Lovkrav i valgt profil" in html, "legal status follows the selected profile"
    assert '<th scope="col">' in html and "<caption>" in html, "the report itself has accessible tables"


def test_full_report_marks_unanalysed_areas_and_csv_is_excel_friendly(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["content_quality"])
    report = create(canvas_client, "full")
    html = canvas_client.get(f"/api/reports/{report['id']}/view").text
    assert "Ikke analysert ennå" in html and "Innholdskvalitet" in html
    csv_report = create(canvas_client, "content_quality", "csv")
    response = canvas_client.get(f"/api/reports/{csv_report['id']}/download")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    body = response.content
    assert body.startswith("﻿".encode()), "UTF-8 BOM so Excel shows æøå correctly"
    text = body.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Område;Status;Klasse")
    assert len(text.splitlines()) > 1


def test_csv_cells_cannot_inject_formulas() -> None:
    assert _cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert _cell("@SUM(A1)") == "'@SUM(A1)" and _cell("Vanlig tekst") == "Vanlig tekst" and _cell(None) == ""


def test_list_download_and_delete(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    analyse(canvas_client, ["structure"])
    report = create(canvas_client, "structure")
    listed = canvas_client.get(f"/api/reports?course_id={COURSE_ID}").json()["items"]
    assert [r["id"] for r in listed] == [report["id"]]
    path = canvas_container.config.reports_dir / COURSE_ID / report["filename"]
    assert path.is_file()
    assert canvas_client.delete(f"/api/reports/{report['id']}").json() == {"ok": True}
    assert not path.exists()
    assert canvas_client.get(f"/api/reports/{report['id']}/download").status_code == 404


def test_report_paths_cannot_escape_the_reports_folder(canvas_client: TestClient,
                                                       canvas_container: AppContainer) -> None:
    secret = canvas_container.config.data_dir / "hemmelig.txt"
    secret.write_text("x", encoding="utf-8")
    with canvas_container.db.session() as session:
        row = Report(course_id=COURSE_ID, report_type="full", fmt="html", title="x", filename="../../hemmelig.txt")
        session.add(row)
        session.flush()
        report_id = row.id
    assert canvas_client.get(f"/api/reports/{report_id}/download").status_code == 404
    assert canvas_client.get(f"/api/reports/{report_id}/view").status_code == 404
