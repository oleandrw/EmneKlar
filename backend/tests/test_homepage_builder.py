"""Emneforside: Canvas-safe, accessible HTML from course facts; preview; create/replace with backup and undo."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.container import AppContainer
from emneklar.core.security.sanitize import canvas_sanitize
from emneklar.features.accessibility.checks import ContentDoc, run_html_checks
from emneklar.features.accessibility.checks.contrast import contrast_ratio, parse_color
from emneklar.features.homepage_builder.builder import SECTIONS, CourseContext, build, canvas_safe
from emneklar.features.homepage_builder.styles import AI_MARK, PLACEHOLDER, STYLES
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def ratio(a: str, b: str) -> float:
    fg, _ = parse_color(a)
    bg, _ = parse_color(b)
    assert fg and bg
    return contrast_ratio(fg, bg)


def context() -> CourseContext:
    return CourseContext(
        course_id="101", name="Digital kompetanse for lærere", code="LA101IKT14-1 26H", term="Høst 2026",
        syllabus_text="Emnet gir en innføring i digitale verktøy for undervisning. " * 5,
        modules=[{"id": "201", "name": "Modul 1 – Introduksjon", "items_count": 3, "unlock_at": None},
                 {"id": "202", "name": "Modul 2 – Bildebehandling", "items_count": 1,
                  "unlock_at": NOW + timedelta(days=7)}],
        deadlines=[{"title": "Gammel innlevering", "due_at": NOW - timedelta(days=3), "url": "/courses/101/assignments/1",
                    "kind": "Oppgave"},
                   {"title": "Innlevering 2", "due_at": NOW + timedelta(days=10), "url": "/courses/101/assignments/2",
                    "kind": "Oppgave"}],
        visible_tabs={"modules", "announcements", "assignments", "files"},
        pages=[{"title": "Pensumliste og ressurser", "url": "pensum"}], counts={"assignments": 2, "files": 4},
        front_page_html="<h2>Gammel forside</h2><p>Dette er forsiden.</p>", generated_at=NOW)


# ------------------------------------------------------------------------------------ pure builder


@pytest.mark.parametrize("style", list(STYLES))
def test_style_colours_meet_aa_contrast(style: str) -> None:
    s = STYLES[style]
    for fg, bg in ((s.text, s.card_bg), (s.text, s.section_bg), (s.link, s.card_bg), (s.link, "#ffffff"),
                   (s.heading, "#ffffff"), (s.banner_text, s.banner_bg)):
        assert ratio(fg, bg) >= 4.5, (style, fg, bg)
    assert ratio(PLACEHOLDER["text"], PLACEHOLDER["bg"]) >= 4.5 and ratio(AI_MARK["text"], AI_MARK["bg"]) >= 4.5


@pytest.mark.parametrize("style", list(STYLES))
@pytest.mark.parametrize("mode", ["design", "design_content", "improve"])
def test_generated_html_survives_canvas_and_passes_our_checks(style: str, mode: str) -> None:
    draft = build(context(), style=style, mode=mode, sections=list(SECTIONS))  # type: ignore[arg-type]
    assert draft.warnings == []
    assert canvas_sanitize(draft.html) == draft.html, "Canvas keeps exactly what the preview shows"
    assert "<script" not in draft.html and "font-weight" not in draft.html and "<h1" not in draft.html
    assert "flex-wrap:wrap" in draft.html.replace(" ", ""), "blocks wrap on narrow screens (no media queries needed)"
    issues = run_html_checks(ContentDoc("page", "x", "Forside", draft.html, language="nb"))
    serious = [i.rule_id for i in issues if i.rule_id not in ("UU-READABILITY",)
               and (i.classification or "") in ("violation", "likely_violation")]
    assert serious == [], serious


def test_design_mode_contains_no_course_facts() -> None:
    draft = build(context(), style="academic", mode="design", sections=list(SECTIONS))
    assert "Modul 1 – Introduksjon" not in draft.html and "Innlevering 2" not in draft.html
    assert "Fyll inn:" in draft.html and any(n["kind"] == "placeholder" for n in draft.notes)
    assert "Digital kompetanse for lærere" in draft.html, "the course name from Canvas is used in the banner"


def test_content_mode_uses_facts_and_marks_uncertainty() -> None:
    draft = build(context(), style="modern", mode="design_content", sections=list(SECTIONS))
    assert 'href="/courses/101/modules/201"' in draft.html and "Modul 2 – Bildebehandling" in draft.html
    assert "Innlevering 2" in draft.html and "Gammel innlevering" not in draft.html, "only upcoming deadlines"
    assert "oppdateres ikke automatisk" in json.dumps(draft.notes, ensure_ascii=False)
    assert "Fra emneplanen" in draft.html and "Les hele emneplanen" in draft.html
    assert "Pensumliste og ressurser" in draft.html
    assert any(n["kind"] == "heuristic" for n in draft.notes)
    assert "Fyll inn:" in draft.html, "contact details are never invented"
    assert 'href="/courses/101/grades"' not in draft.html, "hidden or unknown tabs are not linked"


def test_improve_preserves_existing_content_by_default() -> None:
    kept = build(context(), style="warm", mode="improve", sections=["velkommen", "frister"])
    assert "Dette er forsiden." in kept.html
    replaced = build(context(), style="warm", mode="improve", sections=["velkommen"], preserve_existing=False)
    assert "Dette er forsiden." not in replaced.html
    assert any(n["kind"] == "replace" for n in replaced.notes)


def test_ai_text_is_marked_and_escaped() -> None:
    draft = build(context(), style="minimal", mode="design_content", sections=["velkommen", "om_emnet"],
                  ai={"welcome": "Hei og velkommen <script>alert(1)</script>", "about": "Om emnet."})
    assert draft.html.count("KI-forslag – må vurderes") == 2
    assert "<script" not in draft.html and "&lt;script&gt;" in draft.html


def test_canvas_safe_reports_what_canvas_removes() -> None:
    clean, warnings = canvas_safe('<div style="box-shadow: 0 0 2px #000; color: #111">Hei</div><script>x()</script>'
                                  '<p style="background-image: url(https://example.org/a.png)">x</p>')
    assert "<script" not in clean and "box-shadow" not in clean and "color" in clean
    assert any("box-shadow" in w for w in warnings) and any("<script>" in w for w in warnings)
    assert not any("https" in w for w in warnings)


# ------------------------------------------------------------------------------------------ API


def test_draft_preview_create_page_and_use_as_front(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.assignments["301"]["due_at"] = (datetime.now(UTC) + timedelta(days=5)).isoformat().replace("+00:00", "Z")
    options = canvas_client.get("/api/homepage/options").json()
    assert {s["label"] for s in options["styles"]} == {"Ren og akademisk", "Moderne og visuell", "Varm og innbydende",
                                                        "Minimalistisk"}
    ctx = canvas_client.get(f"/api/courses/{COURSE_ID}/homepage/context").json()
    assert ctx["has_front_page"] and ctx["upcoming_deadlines"] == 1
    draft = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts",
                               json={"mode": "design_content", "style": "modern"}).json()
    assert "Innlevering 1: Bildebehandling" in draft["html"] and draft["preview_html"]
    assert draft["warnings"] == [] and draft["ai_used"] is False

    edited = canvas_client.put(f"/api/homepage/drafts/{draft['id']}",
                               json={"html": draft["html"] + '<script>alert(1)</script><p style="opacity: 0.5">Ny</p>'})
    assert edited.status_code == 200
    assert "<script" not in edited.json()["html"] and any("opacity" in w for w in edited.json()["warnings"])

    change = canvas_client.post(f"/api/homepage/drafts/{draft['id']}/stage",
                                json={"action": "create_page", "title": "Ny forside"}).json()
    assert change["kind"] == "page.create" and change["risk"] == "low"
    job = wait_for_job(canvas_client, canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]}).json()["id"])
    assert job["result"]["summary"] == {"applied": 1}
    page = course.pages["ny-forside"]
    assert page["published"] is False and "Innlevering 1" in page["body"]
    created = canvas_client.get(f"/api/courses/{COURSE_ID}/homepage/created").json()["items"]
    assert created[0]["url"] == "ny-forside"

    use = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/use-as-front", json={"url": "ny-forside"}).json()
    assert use["requires_confirmation"] is True and use["kind"] == "front_page.set"
    job = wait_for_job(canvas_client, canvas_client.post(
        "/api/changes/apply", json={"ids": [use["id"]], "confirm_high_risk": True}).json()["id"])
    assert job["result"]["summary"] == {"applied": 1}
    assert page["front_page"] is True and page["published"] is True
    assert course.course["default_view"] == "wiki"
    other = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/use-as-front", json={"url": "velkommen"})
    assert other.status_code == 400, "only pages created from drafts can be chosen here"


def test_replace_front_page_needs_confirmation_backup_and_undo(canvas_client: TestClient,
                                                               fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    draft = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts",
                               json={"mode": "improve", "style": "academic", "sections": ["velkommen"]}).json()
    assert "Dette er forsiden." in draft["html"], "improve keeps existing content by default"
    change = canvas_client.post(f"/api/homepage/drafts/{draft['id']}/stage", json={"action": "replace_front"}).json()
    assert change["risk"] == "high" and change["requires_confirmation"] is True
    assert canvas_client.post("/api/changes/apply", json={"ids": [change["id"]]}).status_code == 409
    job = wait_for_job(canvas_client, canvas_client.post(
        "/api/changes/apply", json={"ids": [change["id"]], "confirm_high_risk": True}).json()["id"])
    assert job["result"]["summary"] == {"applied": 1}
    assert "Velkommen til" in course.pages["forside"]["body"]
    entry = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}").json()["items"][0]
    backup = canvas_client.get(f"/api/backups/{entry['backup_id']}").json()
    assert "Dette er forsiden." in backup["content"]["state"]["body"], "the old front page was backed up first"
    assert canvas_client.post(f"/api/changelog/{entry['id']}/undo").json()["status"] == "undone"
    assert course.pages["forside"]["body"] == "<h2>Velkommen</h2><p>Dette er forsiden.</p>"


def test_ai_welcome_needs_consent_and_is_marked(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        content = json.dumps({"welcome": "Velkommen til et spennende emne!", "about": "Emnet handler om digitale verktøy."})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": {}})

    canvas_container.ai_transport = httpx.MockTransport(handler)
    canvas_client.put("/api/ai/providers/openai", json={"enabled": True, "api_key": "sk-proj-homepage1234567"})
    canvas_container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/prepare-ai", json={"mode": "design_content"}).json()
    assert plan["available"] and plan["needs_confirmation"] and "Ingen studentdata" in plan["payload_summary"]
    refused = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts", json={"use_ai": True})
    assert refused.status_code == 409 and calls == []
    draft = canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts",
                               json={"use_ai": True, "confirmed": True}).json()
    assert draft["ai_used"] is True and "Velkommen til et spennende emne!" in draft["html"]
    assert "KI-forslag – må vurderes" in draft["html"]


def test_homepage_builder_respects_feature_flag(canvas_client: TestClient, canvas_container: AppContainer) -> None:
    canvas_container.settings.update(lambda s: s.advanced.feature_flags.update({"homepage_builder": False}))
    assert canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts", json={}).status_code == 403
