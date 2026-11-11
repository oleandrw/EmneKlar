"""Emnedesign: profiles, the content-preserving transformation (both treatments), repeated use and switching,
Canvas survival, and the flow scope → preview → change queue → publish → undo against the fake Canvas."""

from __future__ import annotations

import re
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi.testclient import TestClient

from emneklar.core.canvas.blueprint import describe_selection
from emneklar.core.errors import AppError
from emneklar.core.security.sanitize import ALLOWED_CSS, canvas_safe, canvas_sanitize
from emneklar.core.storage.settings import GeneralSettings
from emneklar.features.course_design import profiles as P
from emneklar.features.course_design.transform import (
    apply_design,
    describe_blocks,
    detect,
    format_style,
    parse_style,
    preservation_problems,
    strip_design,
    validate_plan,
)
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import (
    BLUEPRINT_COURSE_ID,
    CHILD_COURSE_ID,
    COURSE_ID,
    FakeCanvasState,
    _page,
    add_blueprint_child,
)

RICH = (
    '<h2 id="mal">Læringsmål</h2><ul><li>Forstå <a href="/courses/101/pages/x">vurdering</a></li></ul>'
    '<p style="color: #c00;">Viktig: fristen er absolutt.</p>'
    '<table><caption>Nivåer</caption><thead><tr><th scope="col">Nivå</th></tr></thead><tbody><tr><td>1</td></tr>'
    '</tbody></table><figure><img src="/courses/101/files/2/preview" alt="Graf over nivåene"><figcaption>Figur 1'
    '</figcaption></figure><p><img class="equation_image" src="/equation_images/x%5E2" alt="x^2" '
    'data-equation-content="x^2"></p><pre><code>print("hei")</code></pre>'
    '<iframe src="https://www.youtube.com/embed/abc" title="Video: Intro" width="560" height="315"></iframe>'
    '<iframe src="https://tool.example.org/lti/launch" title="Verktøy"></iframe>'
    '<h3>Eksempel</h3><p>Se <a href="#mal">læringsmålene</a>.</p><p><a href="https://example.org">Les mer</a></p>'
)


def luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def roots(html: str) -> int:
    return len(BeautifulSoup(html, "html.parser").select("div.ek-design"))


# -- profiles ----------------------------------------------------------------------------------------------------


def test_four_profiles_with_academic_default_and_the_green_specification() -> None:
    assert [p.id for p in P.profiles()] == ["akademisk", "lyst-moderne", "visuelt-pedagogisk", "gronn-akademi"]
    assert P.default_profile().id == "akademisk"
    g = P.get("gronn-akademi").tokens
    assert (g["primary"], g["primary_dark"], g["heading"], g["link"], g["border"], g["info_bg"], g["text"]) == (
        "#1e7e1e", "#0f6b1e", "#0b6e0b", "#0b5e0b", "#b2d8b2", "#f0f7f0", "#1a1a1a")
    assert (g["font_family"], g["max_width"], g["line_height"], g["radius_card"], g["radius_action"], g["font_size"]) == (
        "Arial, sans-serif", "820px", "1.65", "6px", "8px", "16px")
    with pytest.raises(AppError):
        P.get("finnes-ikke")


def test_only_css_canvas_keeps_and_aa_contrast() -> None:
    assert P.all_properties() <= ALLOWED_CSS
    for p in P.profiles():
        t = p.tokens
        for fg, bg in ((t["text"], t["surface"]), (t["heading"], t["surface"]), (t["link"], t["surface"]),
                       (t["text"], t["info_bg"]), (t["link"], t["info_bg"]), (t["heading"], t["info_bg"]),
                       (t["banner_text"], t["banner_bg"]), (t["label_text"], t["label_bg"]), ("#ffffff", t["primary_dark"])):
            assert contrast(fg, bg) >= 4.5, f"{p.id}: {fg} on {bg} is {contrast(fg, bg):.2f}"


# -- keep the structure ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("profile_id", [p.id for p in P.profiles()])
def test_keep_mode_preserves_all_content_and_adds_only_style(profile_id: str) -> None:
    result = apply_design(RICH, P.get(profile_id), kind="page")
    assert preservation_problems(RICH, result.html, structure=False) == []
    soup = BeautifulSoup(result.html, "html.parser")
    assert roots(result.html) == 1 and soup.find("h1") is None, "no page title is added"
    assert soup.find("p", string=re.compile("fristen")).get("style").startswith("color: #c00"), "own colour kept"
    assert any("egen farge" in n for n in result.notes)
    lti = soup.find("iframe", src=re.compile("tool.example.org"))
    assert parse_style(lti.get("style")) == [("max-width", "100%")], "an external tool is not treated as a video"
    for a in soup.find_all("a"):
        assert ("text-decoration", "underline") in parse_style(a.get("style")), "links are identifiable without colour"
        assert "inline-block" not in str(a.get("style")), "no link becomes a button"
    assert [t.name for t in soup.select("div.ek-design > *")] == \
        [t.name for t in BeautifulSoup(RICH, "html.parser").find_all(recursive=False)], "same order, nothing added"


def test_repeated_use_and_switching_never_accumulate() -> None:
    a, g = P.get("akademisk"), P.get("gronn-akademi")
    once = apply_design(RICH, a).html
    assert apply_design(once, a).html == once
    assert apply_design(once, g).html == apply_design(RICH, g).html, "switching = applying to the original"
    assert strip_design(once) == strip_design(RICH) and detect(once) == "akademisk@2" and detect(RICH) is None
    front = apply_design(RICH, g, kind="front_page", course_name="BP_LA102IKT", course_sub="Høst 2026").html
    assert apply_design(front, a, kind="front_page", course_name="BP_LA102IKT", course_sub="Høst 2026").html.count(
        "ek-design-banner") == 1


def test_design_is_recognised_after_canvas_drops_the_markers() -> None:
    """Canvas re-serialises styles; an editor may drop classes and data attributes – no hidden marker is relied on."""
    designed = canvas_sanitize(apply_design(RICH, P.get("gronn-akademi")).html)
    soup = BeautifulSoup(designed, "html.parser")
    for el in soup.find_all(True):
        for attr in ("class", "data-ek-d", "data-ek-design"):
            if attr in el.attrs and (attr != "class" or any(c.startswith("ek-design") for c in el.get("class") or [])):
                del el[attr]
    bare = str(soup)
    assert detect(bare) == "ukjent"
    again = apply_design(bare, P.get("akademisk")).html
    assert roots(again) == 1, "no double wrapper"
    assert "#1e7e1e" not in again and "#0b6e0b" not in again, "the earlier profile's styling is gone"
    assert preservation_problems(RICH, again, structure=False) == []


def test_canvas_keeps_every_declaration() -> None:
    for p in P.profiles():
        for kind in ("page", "front_page", "module_intro"):
            html = apply_design(RICH, p, kind=kind, course_name="Emne", course_sub="Høst 2026").html
            ours = [sorted(parse_style(el.get("style"))) for el in BeautifulSoup(html, "html.parser").find_all(style=True)]
            kept = [sorted(parse_style(el.get("style"))) for el in
                    BeautifulSoup(canvas_sanitize(html), "html.parser").find_all(style=True)]
            norm = [[(k, P.norm_value(v)) for k, v in decls] for decls in ours]
            assert norm == [[(k, P.norm_value(v)) for k, v in decls] for decls in kept], f"{p.id}/{kind}"


ACTIVITY = '<h2>Aktivitet</h2><p>Skriv tre tilbakemeldinger og del dem i diskusjonen.</p>'


def activity_box(html: str) -> Tag:
    box = BeautifulSoup(html, "html.parser").select_one("div.ek-design-box--activity")
    assert box is not None
    return box


@pytest.mark.parametrize("profile_id", [p.id for p in P.profiles()])
def test_activity_boxes_are_rounded_without_a_stripe(profile_id: str) -> None:
    profile = P.get(profile_id)
    plan = validate_plan({"sections": [{"role": "activity", "label": None, "blocks": ["b1", "b2"]}]},
                         describe_blocks(ACTIVITY))
    box = activity_box(apply_design(ACTIVITY, profile, plan=plan).html)
    style = dict(parse_style(box.get("style")))
    assert "border-left" not in style and style["border-radius"] == profile.tokens["radius_card"]
    assert style["padding"].startswith("0 "), "the label sits flush with the rounded top"
    label = box.select_one(".ek-design-label")
    assert label is not None and dict(parse_style(label.get("style")))["border-radius"].startswith(
        profile.tokens["radius_card"])


def test_the_stripe_from_the_first_version_is_removed_when_the_design_is_applied_again() -> None:
    v = P.get("visuelt-pedagogisk")
    plan = validate_plan({"sections": [{"role": "activity", "label": None, "blocks": ["b1", "b2"]}]},
                         describe_blocks(ACTIVITY))
    current = apply_design(ACTIVITY, v, plan=plan).html
    soup = BeautifulSoup(current, "html.parser")
    box = soup.select_one("div.ek-design-box--activity")
    assert box is not None
    old = [("background-color", "#f4f3fc"), ("border-left", "4px solid #5a50b5"), ("padding", "8px 16px"),
           ("margin", "1.2em 0")]  # profile version 1
    box["style"], box["data-ek-d"] = format_style(old), " ".join(p for p, _ in old)
    version_1 = str(soup)
    for designed in (version_1, canvas_sanitize(version_1)):
        again = activity_box(apply_design(designed, v).html)
        assert "border-left" not in str(again.get("style")) and "8px 16px" not in str(again.get("style"))
    # Also when an editor dropped EmneKlar's classes and data attributes: the old declarations are recognised.
    bare = BeautifulSoup(version_1, "html.parser")
    for el in bare.find_all(True):
        for attr in ("data-ek-d", "data-ek-design", "data-ek-role", "class"):
            el.attrs.pop(attr, None)
    assert "border-left" not in apply_design(str(bare), P.get("akademisk")).html


def test_canvas_safe_reports_what_canvas_removes() -> None:
    clean, warnings = canvas_safe('<div style="box-shadow: 0 0 2px #000; color: #111">Hei</div><script>x()</script>'
                                  '<p style="background-image: url(https://example.org/a.png)">x</p>')
    assert "<script" not in clean and "box-shadow" not in clean and "color" in clean
    assert any("box-shadow" in w for w in warnings) and any("<script>" in w for w in warnings)
    assert not any("https" in w for w in warnings)


def test_banner_only_on_the_front_page_and_lead_on_a_module_introduction() -> None:
    g = P.get("gronn-akademi")
    front = BeautifulSoup(apply_design("<p>Hei</p>", g, kind="front_page", course_name="Vurdering").html, "html.parser")
    banner = front.select_one(".ek-design-banner")
    assert banner is not None and banner.get_text(strip=True) == "Vurdering" and banner.find(["h1", "h2"]) is None
    assert ("background-color", "#1e7e1e") in parse_style(banner.get("style"))
    page = apply_design("<p>Hei</p>", g, kind="page", course_name="Vurdering").html
    assert "ek-design-banner" not in page
    intro = BeautifulSoup(apply_design("<p>Først</p><p>Så</p>", g, kind="module_intro").html, "html.parser")
    assert "font-size: 1.125em" in str(intro.find("p").get("style"))


# -- suggest a better structure ----------------------------------------------------------------------------------


def plan_for(html: str) -> dict[str, Any]:
    ids = [b["id"] for b in describe_blocks(html)]
    return {"sections": [{"role": "goals", "label": None, "blocks": ids[:2]},
                         {"role": "content", "label": "Fagstoff", "blocks": ids[2:-2]},
                         {"role": "example", "label": None, "blocks": ids[-2:]}]}


def test_structure_mode_places_existing_content_and_shows_the_changes() -> None:
    g = P.get("gronn-akademi")
    plan = validate_plan(plan_for(RICH), describe_blocks(RICH))
    result = apply_design(RICH, g, plan=plan)
    assert preservation_problems(RICH, result.html, structure=True) == []
    assert "Ny seksjonsoverskrift: «Fagstoff»" in result.structure_changes
    soup = BeautifulSoup(result.html, "html.parser")
    boxes = soup.select("div.ek-design-box")
    assert [b.get("data-ek-role") for b in boxes] == ["goals", "example"]
    assert all(not b.select("div.ek-design-box") for b in boxes), "no nested boxes"
    assert apply_design(result.html, g, plan=plan).html == result.html, "the same plan again changes nothing"
    assert preservation_problems(RICH, apply_design(result.html, P.get("akademisk")).html, structure=True) == []


def test_invalid_plans_are_refused() -> None:
    blocks = describe_blocks(RICH)
    ids = [b["id"] for b in blocks]
    with pytest.raises(AppError, match="mangler eller gjentar"):
        validate_plan({"sections": [{"role": "content", "label": None, "blocks": ids[:-1]}]}, blocks)
    with pytest.raises(AppError, match="mangler eller gjentar"):
        validate_plan({"sections": [{"role": "content", "label": None, "blocks": [*ids, ids[0]]}]}, blocks)
    with pytest.raises(AppError, match="faste seksjonsoverskriftene"):
        validate_plan({"sections": [{"role": "goals", "label": "Du skal kunne alt om vurdering", "blocks": ids}]}, blocks)
    plan = validate_plan({"sections": [{"role": "goals", "label": "Læringsmål", "blocks": []},
                                       {"role": "content", "label": None, "blocks": ids}]}, blocks)
    assert len(plan.sections) == 1, "no empty section"


# -- the flow against the fake Canvas ----------------------------------------------------------------------------


def inventory(client: TestClient, module_id: str | None = None) -> dict[str, Any]:
    url = f"/api/courses/{COURSE_ID}/course-design/inventory" + (f"?module_id={module_id}" if module_id else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def test_inventory_shows_what_is_included_and_what_is_left_out(canvas_client: TestClient,
                                                               fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.assignments["304"] = {"id": "304", "name": "Ny quiz", "description": "<p>Ny</p>", "published": True,
                                 "is_quiz_lti_assignment": True, "submission_types": ["external_tool"]}
    course.modules[1]["items"].append({"id": "1014", "title": "Velkommen til emnet", "type": "Page",
                                       "page_url": "velkommen", "position": 5, "indent": 0, "published": True})
    data = inventory(canvas_client)
    by_key = {i["key"]: i for i in data["items"]}
    assert by_key["syllabus:101"]["kind"] == "syllabus"
    assert by_key["page:velkommen"]["kind"] == "module_intro" and by_key["page:velkommen"]["shared"] is True
    assert by_key["page:velkommen"]["modules"] == ["Modul 1 – Introduksjon", "Modul 2 – Bildebehandling"]
    assert by_key["quiz:401"]["kind"] == "quiz" and "assignment:303" not in by_key, "a quiz is listed once"
    assert "assignment:304" not in by_key
    labels = [x["label"] for x in data["not_included"]]
    assert "New Quizzes (1)" in labels and "Quizspørsmål og svar" in labels and "Diskusjoner (1)" in labels
    module = inventory(canvas_client, "202")
    assert sorted(i["key"] for i in module["items"]) == ["assignment:301", "page:bildeformater", "page:fargelaere",
                                                         "page:velkommen", "quiz:401"]


def preview(client: TestClient, keys: list[str], profile: str = "akademisk", plans: dict | None = None) -> dict:
    response = client.post(f"/api/courses/{COURSE_ID}/course-design/preview",
                           json={"profile_id": profile, "items": keys, "plans": plans or {}})
    assert response.status_code == 200, response.text
    return {i["key"]: i for i in response.json()["items"]}


def approve(client: TestClient, items: list[dict], profile: str = "akademisk") -> dict:
    response = client.post(f"/api/courses/{COURSE_ID}/course-design/approve", json={"profile_id": profile, "items": items})
    assert response.status_code == 200, response.text
    return {r["key"]: r for r in response.json()["results"]}


def test_module_counts_match_what_each_module_contains(canvas_client: TestClient) -> None:
    whole = inventory(canvas_client)
    assert whole["modules"], "the fake course has modules"
    for module in whole["modules"]:
        scoped = inventory(canvas_client, module["id"])
        assert module["count"] == len(scoped["items"]), module["name"]
        assert {m["id"]: m["count"] for m in scoped["modules"]} == {m["id"]: m["count"] for m in whole["modules"]}


def test_blueprint_is_explained_for_the_course_and_the_selection() -> None:
    blueprint = describe_selection({"is_blueprint": True, "associated_course_count": 21}, total=13, locked=3)
    assert blueprint is not None and blueprint["role"] == "blueprint" and blueprint["limitation"] is None
    assert "21 tilknyttede emner" in blueprint["summary"] and "synkroniseres" in blueprint["summary"]
    assert any("3 av 13 elementer i utvalget er låst i de tilknyttede emnene" in d for d in blueprint["details"])
    assert any("10 av 13 elementer er ikke låst" in d and "lokale endringer beholdes" in d for d in blueprint["details"])
    child = describe_selection({"is_child": True, "parent": {"name": "BP_LA102IKT"}}, total=5, locked=2)
    assert child is not None and child["summary"].endswith("2 av 5 elementer i utvalget er låst derfra.")
    assert child["limitation"] == "2 av 5 elementer er låst fra Blueprint-emnet og må trolig endres der."
    assert any("flytte den til Blueprint-emnet fra endringskøen" in d for d in child["details"])
    free = describe_selection({"is_child": True, "parent": {"name": "BP"}}, total=4, locked=0)
    assert free is not None and free["limitation"] is None and "Ingen av elementene" in free["summary"]
    assert describe_selection({}, total=4, locked=0) is None
    for text in (blueprint["summary"], *blueprint["details"], child["summary"], *child["details"]):
        assert "Elementet" not in text, "an overview never speaks of one item"


def test_inventory_explains_blueprint_with_real_counts(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    assert inventory(canvas_client)["blueprint"] is None, "an ordinary course"
    fake_state.courses[BLUEPRINT_COURSE_ID].assignments["391"]["description"] = "<p>Lever her.</p>"  # locked downstream
    template = canvas_client.get(f"/api/courses/{BLUEPRINT_COURSE_ID}/course-design/inventory").json()
    assert template["blueprint"]["role"] == "blueprint" and "3 tilknyttede emner" in template["blueprint"]["summary"]
    ready = [i for i in template["items"] if not i["empty"] and not i["excluded"]]
    locked = sum(1 for i in ready if i["locked"])
    assert locked >= 1 and template["blueprint"]["locked"] == locked and template["blueprint"]["total"] == len(ready)
    add_blueprint_child(fake_state)
    child = canvas_client.get(f"/api/courses/{CHILD_COURSE_ID}/course-design/inventory").json()
    assert child["blueprint"]["role"] == "associated" and "«Mal for digitale emner»" in child["blueprint"]["summary"]
    assert child["blueprint"]["limitation"].startswith(f"1 av {child['blueprint']['total']} elementer er låst")


def test_counts_are_unique_and_follow_the_scope(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    modules = {m["id"]: m for m in course.modules}
    # The same file and the same page in two modules; a New Quiz outside the modules.
    modules["202"]["items"].append({"id": "1014", "title": "Pensumliste", "type": "File", "content_id": "9001",
                                    "position": 5, "indent": 0, "published": True})
    modules["203"]["items"].append({"id": "1025", "title": "Velkommen til emnet", "type": "Page",
                                    "page_url": "velkommen", "position": 6, "indent": 0, "published": True})
    modules["203"]["items"].append({"id": "1026", "title": "Uke 3", "type": "SubHeader", "position": 7, "indent": 0})
    course.assignments["399"] = {"id": "399", "name": "Ny quiz", "description": "", "published": True,
                                 "is_quiz_lti_assignment": True, "submission_types": ["external_tool"],
                                 "html_url": "/courses/101/assignments/399"}
    whole = inventory(canvas_client)
    keys = [i["key"] for i in whole["items"]]
    assert len(keys) == len(set(keys)), "every content item once"
    assert keys.count("page:velkommen") == 1
    labels = {x["label"] for x in whole["not_included"]}
    assert "Filer (3)" in labels, "a file used in two modules is one file"
    assert "New Quizzes (1)" in labels
    module = {m["id"]: m for m in whole["modules"]}["203"]
    assert module["total"] == 6, "everything in the module except text headers"
    assert module["count"] == 2 and module["position"] == 3 and module["published"] is True
    scoped = inventory(canvas_client, "203")
    assert {i["key"] for i in scoped["items"]} == {"page:video-og-medier", "page:velkommen"}
    assert not any(x["label"].startswith("New Quizzes") for x in scoped["not_included"]), "not in this module"
    assert next(i for i in scoped["items"] if i["key"] == "page:velkommen")["shared"] is True


def test_preview_queue_publish_and_undo_keep_settings(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    before_assignment = dict(course.assignments["301"])
    shown = preview(canvas_client, ["page:fargelaere", "assignment:301", "quiz:401", "syllabus:101"])
    assert all(not i.get("problems") and i["after"] != i["before"] for i in shown.values())
    assert "sandbox" not in shown["page:fargelaere"]["after"] and "<script" not in shown["page:fargelaere"]["after"]
    writes = len([r for r in fake_state.requests if r[0] != "GET"])
    results = approve(canvas_client, [{"key": k, "content_hash": v["content_hash"], "kind": k.split(":")[0],
                                      "title": k} for k, v in shown.items()])
    assert {r["status"] for r in results.values()} == {"approved"}
    assert len([r for r in fake_state.requests if r[0] != "GET"]) == writes, "approving writes nothing to Canvas"
    ids = [r["change_id"] for r in results.values()]
    changes = {c["id"]: c for c in canvas_client.get("/api/changes").json()["items"]}
    assert all(changes[i]["status"] == "approved" for i in ids)
    assert set(changes[results["assignment:301"]["change_id"]]["proposed"]) == {"description"}, "only the text field"

    job = approve_and_apply(canvas_client, ids).json()
    assert wait_for_job(canvas_client, job["id"], timeout=60)["result"]["summary"] == {"applied": 4}
    assert detect(course.pages["fargelaere"]["body"]) == "akademisk@2"
    after_assignment = course.assignments["301"]
    for keep in ("points_possible", "due_at", "submission_types", "name", "published"):
        assert after_assignment[keep] == before_assignment[keep], f"{keep} unchanged"
    log = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}&limit=10").json()["items"]
    entry = next(e for e in log if e["object_id"] == "fargelaere")
    assert entry["summary"] == "Emnedesign «Akademisk» brukt"
    undone = canvas_client.post(f"/api/changelog/{entry['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert detect(course.pages["fargelaere"]["body"]) is None


def test_newer_canvas_changes_are_never_overwritten(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    shown = preview(canvas_client, ["page:bildeformater"])["page:bildeformater"]
    course.pages["bildeformater"]["body"] += "<p>Lagt til i Canvas etter forhåndsvisningen.</p>"
    result = approve(canvas_client, [{"key": "page:bildeformater", "content_hash": shown["content_hash"], "kind": "page",
                                      "title": "Bildeformater"}])["page:bildeformater"]
    assert result["status"] == "changed"

    fresh = preview(canvas_client, ["page:bildeformater"])["page:bildeformater"]
    queued = approve(canvas_client, [{"key": "page:bildeformater", "content_hash": fresh["content_hash"], "kind": "page",
                                      "title": "Bildeformater"}])["page:bildeformater"]
    course.pages["bildeformater"]["body"] += "<p>Enda en endring.</p>"
    job = approve_and_apply(canvas_client, [queued["change_id"]]).json()
    outcome = wait_for_job(canvas_client, job["id"], timeout=60)["result"]["results"][0]
    assert outcome["status"] == "conflict" and "Enda en endring" in course.pages["bildeformater"]["body"]
    rebuilt = canvas_client.post(f"/api/changes/{queued['change_id']}/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert "Enda en endring" in rebuilt.json()["proposed"]["body"], "the design is applied to the newest content"


def test_repeated_approval_and_profile_switch_on_canvas(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    course.pages["oppskrift"] = _page("oppskrift", "Oppskrift", RICH)

    def publish(profile: str) -> str:
        shown = preview(canvas_client, ["page:oppskrift"], profile)["page:oppskrift"]
        result = approve(canvas_client, [{"key": "page:oppskrift", "content_hash": shown["content_hash"], "kind": "page",
                                          "title": "Oppskrift"}], profile)["page:oppskrift"]
        if result["status"] == "approved":
            job = approve_and_apply(canvas_client, [result["change_id"]]).json()
            wait_for_job(canvas_client, job["id"], timeout=60)
        return result["status"]

    assert publish("gronn-akademi") == "approved"
    assert publish("gronn-akademi") == "unchanged", "the same design again changes nothing"
    assert publish("lyst-moderne") == "approved"
    body = course.pages["oppskrift"]["body"]
    assert roots(body) == 1 and detect(body) == "lyst-moderne@2" and "#1e7e1e" not in body
    assert preservation_problems(RICH, body, structure=False) == []


def test_structure_suggestion_is_validated(canvas_client: TestClient, canvas_container: Any,
                                           fake_state: FakeCanvasState, monkeypatch: pytest.MonkeyPatch) -> None:
    course = fake_state.courses[COURSE_ID]
    course.pages["oppskrift"] = _page("oppskrift", "Oppskrift", RICH)

    class Result:
        def __init__(self, data: dict) -> None:
            self.data = data

    answers: list[dict] = [{**plan_for(RICH), "note": "Læringsmål først."}]

    async def fake_run(task: str, request: Any, **kwargs: Any) -> tuple[Result, None]:
        assert task == "course_design_structure"
        prompt = request("modell").messages[0].parts[0].text
        assert "<<<KURSINNHOLD" in prompt and "b1 [h2]: Læringsmål" in prompt
        return Result(answers[0]), None

    monkeypatch.setattr(canvas_container.ai, "run", fake_run)
    suggested = canvas_client.post(f"/api/courses/{COURSE_ID}/course-design/structure",
                                   json={"item": "page:oppskrift", "title": "Oppskrift", "confirmed": True})
    assert suggested.status_code == 200, suggested.text
    plan = suggested.json()["plan"]
    shown = preview(canvas_client, ["page:oppskrift"], "visuelt-pedagogisk", {"page:oppskrift": plan})["page:oppskrift"]
    assert shown["structure_changes"] and not shown["problems"]
    queued = approve(canvas_client, [{"key": "page:oppskrift", "content_hash": shown["content_hash"], "kind": "page",
                                      "title": "Oppskrift", "plan": plan}], "visuelt-pedagogisk")["page:oppskrift"]
    change = next(c for c in canvas_client.get("/api/changes").json()["items"] if c["id"] == queued["change_id"])
    assert change["ai_generated"] is True and "Ny oppbygging" in change["rationale"]

    answers[0] = {"sections": [{"role": "content", "label": None, "blocks": ["b1"]}], "note": ""}
    dropped = canvas_client.post(f"/api/courses/{COURSE_ID}/course-design/structure",
                                 json={"item": "page:oppskrift", "title": "Oppskrift", "confirmed": True})
    assert dropped.status_code == 422 and "mangler eller gjentar" in dropped.json()["error"]["message"]


def test_design_choice_and_exclusions_are_saved(canvas_client: TestClient) -> None:
    saved = canvas_client.put(f"/api/courses/{COURSE_ID}/course-design",
                              json={"profile_id": "gronn-akademi", "mode": "keep"}).json()["design"]
    assert saved["profile_id"] == "gronn-akademi" and saved["profile_version"] == "2"
    canvas_client.put(f"/api/courses/{COURSE_ID}/course-design/items/page:fargelaere/exclusion", json={"excluded": True})
    state = canvas_client.get(f"/api/courses/{COURSE_ID}/course-design").json()
    assert state["excluded"] == ["page:fargelaere"]
    assert {i["key"]: i["excluded"] for i in inventory(canvas_client)["items"]}["page:fargelaere"] is True
    assert canvas_client.put(f"/api/courses/{COURSE_ID}/course-design", json={"profile_id": "x"}).status_code == 422
    profiles = canvas_client.get("/api/course-design/profiles").json()
    assert profiles["default"] == "akademisk" and len(profiles["profiles"]) == 4
    assert all("ek-design" in p["sample_keep"] and "ek-design-box" in p["sample_structure"] for p in profiles["profiles"])


# ------------------------------------------------------------------------------------- Emneforside is gone


def test_emnedesign_replaces_emneforside(canvas_client: TestClient) -> None:
    assert canvas_client.get("/api/homepage/options").status_code == 404
    assert canvas_client.post(f"/api/courses/{COURSE_ID}/homepage/drafts", json={}).status_code in (404, 405)
    flags = {f["key"] for f in canvas_client.get("/api/settings").json()["flags"]}
    assert "course_design" in flags and "homepage_builder" not in flags
    # A start page saved before the change opens Emnedesign, which took Emneforside's place in the menu.
    assert GeneralSettings.model_validate({"start_page": "emneforside"}).start_page == "emnedesign"
    saved = canvas_client.patch("/api/settings/general", json={"start_page": "emnedesign"})
    assert saved.status_code == 200 and saved.json()["settings"]["general"]["start_page"] == "emnedesign"
