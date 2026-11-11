"""Emneoversikt: figures that do not overlap, recommendations in a sound order that open exactly what they count, one
event per published change, and one time basis for the analysis."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from emneklar.core.storage.models import Finding
from emneklar.features.overview.api import activity, next_steps, num
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID

PAGES = {"/universell-utforming": "accessibility", "/innholdskvalitet": "content_quality", "/emnestruktur": "structure"}


def finding(cls: str, severity: str = "serious", rule: str = "UU-X", n: int = 0, category: str = "images") -> Finding:
    return Finding(classification=cls, severity=severity, rule_id=rule, object_type="page", object_id=f"p{n}",
                   status="open", category=category)


def rows(**domains: list[Finding]) -> dict[str, list[Finding]]:
    return {d: domains.get(d, []) for d in ("accessibility", "content_quality", "structure", "quiz", "quiz_ai")}


def test_numbers_use_norwegian_thousands() -> None:
    assert num(1110) == "1 110" and num(958) == "958"


def test_confirmed_problems_come_before_many_uncertain_ones() -> None:
    uncertain = [finding("likely_violation", n=i) for i in range(900)]
    steps = next_steps(rows(accessibility=[finding("violation"), *uncertain, finding("manual_check", "moderate")],
                            content_quality=[finding("violation", rule="CQ-LINK-DEAD", category="links")]),
                       {"pending": 0, "approved": 0}, dead_links=1)
    assert [s["key"] for s in steps] == ["uu-violations", "dead-links", "uu-likely", "uu-manual"]
    by_key = {s["key"]: s for s in steps}
    assert by_key["uu-violations"]["title"] == "1 avvik med høy alvorlighet"
    assert by_key["uu-likely"]["title"].startswith("900 sannsynlige avvik"), "never called «avvik» or «alvorlige UU-funn»"
    assert "ikke bekreftet" in by_key["uu-likely"]["description"]
    assert by_key["uu-violations"]["action"] == "Se alvorlige avvik"
    many = next_steps(rows(accessibility=[finding("likely_violation", n=i) for i in range(1110)]), {"pending": 0})
    assert many[0]["title"].startswith("1 110 sannsynlige avvik")


def test_approved_changes_are_a_concrete_step_after_confirmed_problems() -> None:
    steps = next_steps(rows(accessibility=[finding("violation"), finding("likely_violation")]),
                       {"pending": 2, "approved": 2})
    assert [s["key"] for s in steps] == ["uu-violations", "changes", "uu-likely"]
    assert steps[1]["title"] == "2 godkjente endringer er klare til publisering" and steps[1]["path"] is None


def test_activity_shows_one_post_per_published_change() -> None:
    publish = {"kind": "apply_changes", "title": "Publiserer endring", "status": "completed", "params": {"change_ids": [7]},
               "finished_at": "2026-11-06T13:05:01+00:00", "created_at": "2026-11-06T13:05:00+00:00",
               "result": {"results": [{"change_id": 7, "status": "applied", "log_id": 31}]}}
    analysis = {"kind": "analysis", "title": "Analyse av hele emnet", "status": "completed",
                "params": {"scope": "course", "domains": ["accessibility", "content_quality"]},
                "finished_at": "2026-11-06T12:00:00+00:00", "created_at": "2026-11-06T11:58:00+00:00", "result": {}}
    failed = {**publish, "status": "failed", "result": {}, "finished_at": "2026-11-06T14:00:00+00:00"}
    log = [{"id": 31, "timestamp": "2026-11-06T13:05:01+00:00", "object_title": "Pensum", "object_type": "page",
            "summary": "Lenketekst oppdatert", "action": "apply"}]
    items = activity([failed, publish, analysis], log)
    assert [(i["type"], i["title"]) for i in items] == [
        ("job", "Publisering av 1 endring"), ("change", "Pensum"), ("analysis", "Hele emnet analysert")]
    assert items[0]["detail"] == "Feilet", "a publish job without entries is still shown"
    assert items[1]["summary"] == "Lenketekst oppdatert" and items[1]["status"] == "apply"
    assert items[2]["detail"] == "Universell utforming og innholdskvalitet"


def analyse(client: TestClient, domains: list[str], items: list[dict[str, str]] | None = None) -> None:
    body: dict[str, Any] = {"course_id": COURSE_ID, "domains": domains}
    if items:
        body |= {"scope": "items", "items": items}
    job = client.post("/api/analysis", json=body).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"


def test_figures_add_up_and_every_step_opens_what_it_counts(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["accessibility", "content_quality", "structure"])
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()
    for card in data["cards"].values():
        if card["analyzed"]:
            assert sum(card["by_classification"].values()) == card["total"], "classes never overlap"
            assert sum(card["by_category"].values()) == card["total"]
    assert data["next_steps"], "the fake course has findings"
    links = canvas_client.get(f"/api/courses/{COURSE_ID}/links").json()
    assert data["cards"]["content_quality"]["dead_links"] == links["summary"]["broken"], "one definition of dead links"
    for step in data["next_steps"]:
        if not step["path"] or step["path"] == "/quizassistent":
            continue
        url = urlsplit(step["path"])
        query = parse_qs(url.query)
        if query.get("fane") == ["lenker"]:
            # The dead links step opens Innholdskvalitet → Lenker, «Fungerer ikke»: exactly the rows it counts.
            assert query["lenker"] == ["broken"]
            assert step["count"] == sum(1 for row in links["links"] if row["category"] == query["lenker"][0])
            continue
        params: dict[str, Any] = {"domain": PAGES[url.path], "page_size": 200}
        if "klasse" in query:
            params["classification"] = query["klasse"][0].split(",")
        if "alvorlighet" in query:
            params["severity"] = query["alvorlighet"][0].split(",")
        if "regel" in query:
            params["rule"] = query["regel"][0].split(",")
        listed = canvas_client.get(f"/api/courses/{COURSE_ID}/findings", params=params).json()
        assert listed["total"] == step["count"], f"{step['key']}: the list opened shows the number the step says"
        assert query.get("utvalg"), "the list says what the selection is"

    # One time basis: the content statistics belong to the newest analysis shown at the top.
    assert data["stats"]["run_id"] == data["analysis"]["id"]
    assert all(card["run_id"] == data["analysis"]["id"] for card in data["cards"].values() if card["analyzed"])
    assert data["analysis"]["time"] == data["stats"]["analysed_at"]


def test_a_partial_analysis_is_marked_and_older_areas_keep_their_time(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["accessibility", "content_quality"])
    first = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()
    page = next(f for f in canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility").json()["items"])
    analyse(canvas_client, ["accessibility"], [{"object_type": page["object_type"], "object_id": page["object_id"]}])
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()
    assert data["analysis"]["scope_type"] == "items"
    uu = data["cards"]["accessibility"]
    assert len(uu["runs"]) == 2 and uu["runs"][-1]["scope_type"] == "course", "the area combines two analyses"
    cq = data["cards"]["content_quality"]
    assert cq["run_id"] == first["analysis"]["id"] != data["analysis"]["id"], "content quality is from the older one"


def test_publishing_is_one_activity_post_with_what_was_changed(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["accessibility"])
    missing = next(f for f in canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200")
                   .json()["items"] if f["rule_id"] == "UU-IMG-MISSING-ALT")
    change = canvas_client.post(f"/api/findings/{missing['id']}/fix/approve", json={"text": "Skjermbilde"}).json()
    job = approve_and_apply(canvas_client, [change["id"]]).json()
    assert wait_for_job(canvas_client, job["id"])["status"] == "completed"
    items = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()["activity"]
    changes = [i for i in items if i["type"] == "change"]
    assert [(i["title"], i["summary"], i["status"]) for i in changes] == [
        (missing["object_title"], "Alt-tekst oppdatert", "apply")]
    assert not [i for i in items if i["title"].startswith(("Publiser", "Publisering"))], "the publish job is not repeated"
    assert any(i["type"] == "analysis" and i["title"] == "Hele emnet analysert" for i in items)


def test_a_partial_analysis_is_told_apart_from_the_last_full_one(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["accessibility", "content_quality"])
    page = next(f for f in canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility").json()["items"])
    analyse(canvas_client, ["accessibility"], [{"object_type": page["object_type"], "object_id": page["object_id"]}])
    data = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()
    assert data["analysis"]["scope_type"] == "items" and data["analysis"]["domains"] == ["accessibility"]
    full = data["full_analysis"]
    assert full["scope_type"] == "course" and sorted(full["domains"]) == ["accessibility", "content_quality"]
    assert full["time"] < data["analysis"]["time"], "the last full analysis is older than the partial one"
    # Each card says which runs (and areas) its findings come from.
    assert [r["scope_type"] for r in data["cards"]["accessibility"]["runs"]] == ["items", "course"]


def test_quiz_findings_are_counted_by_quiz_and_by_question(canvas_client: TestClient) -> None:
    analyse(canvas_client, ["quiz"])
    quiz = canvas_client.get(f"/api/courses/{COURSE_ID}/overview").json()["cards"]["quiz"]
    findings = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=quiz&page_size=200").json()["items"]
    questions = {f["object_id"] for f in findings if f["object_type"] == "quiz_question"}
    quizzes = {str(f["evidence"].get("quiz_id") or f["object_id"]) for f in findings}
    assert quiz["questions_affected"] == len(questions)
    assert quiz["quizzes_affected"] == len(quizzes) and quiz["quizzes_affected"] >= 1
    assert quiz["objects"] >= quiz["questions_affected"]


def test_titles_with_emoji_come_through_unchanged(canvas_client: TestClient, fake_state: Any) -> None:
    """«??? Bildenotater»: EmneKlar must never turn characters into question marks on the way from Canvas to the page."""
    course = fake_state.courses[COURSE_ID]
    page = course.pages["oppsummering"]
    page["title"] = "🖼️ Bildenotater – «æøå»"
    page["body"] = '<h2>Notater</h2><p><img src="/x.png"></p>'
    analyse(canvas_client, ["accessibility"])
    items = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]
    titles = {f["object_title"] for f in items if f["object_id"] == "oppsummering"}
    assert any("🖼️ Bildenotater – «æøå»" in (t or "") for t in titles), titles
    assert not any("?" in (t or "") for t in titles)
