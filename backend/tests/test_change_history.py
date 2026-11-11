"""The history (Canvas-verktøy → Siste handlinger, Sikkerhetskopier og endringslogg) says what was changed – from what
was recorded with the change (its fix recipes, else its kind), never a guess."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from emneklar.core.changes.engine import change_summary
from emneklar.features.accessibility.fixes import describe_recipe
from tests.conftest import approve_and_apply, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID


def analyse(client: TestClient) -> list[dict[str, Any]]:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]


def test_summary_comes_from_the_recorded_recipes_or_the_kind() -> None:
    link_text = {"fix": {"type": "set_link_text"}, "params": {"text": "Pensum"}, "rule_id": "UU-LINK-VAGUE"}
    alt = {"fix": {"type": "set_alt"}, "params": {"text": "Diagram"}, "rule_id": "UU-IMG-MISSING-ALT"}
    decorative = {"fix": {"type": "set_alt"}, "params": {"decorative": True}}
    unlink = {"fix": {"type": "replace_link_href"}, "params": {"link_action": "unlink"}}
    new_address = {"fix": {"type": "replace_link_href"}, "params": {"url": "https://x.org", "link_text": "X"}}
    assert [describe_recipe(r) for r in (link_text, alt, decorative, unlink, new_address)] == [
        "Lenketekst oppdatert", "Alt-tekst oppdatert", "Bilde merket som dekorativt",
        "Lenke fjernet, teksten beholdt", "Lenkeadresse og lenketekst oppdatert"]
    assert describe_recipe({"fix": {"type": "something_new"}}) is None, "no invented description"

    source = {"rebase": "html_fixes", "fixes": [link_text, alt, dict(link_text)]}
    assert change_summary("page.update_body", source) == "Lenketekst oppdatert, Alt-tekst oppdatert"
    assert change_summary("page.update_body", {}) == "Sideinnhold oppdatert", "the kind when no recipe is recorded"
    assert change_summary("module.update", None) == "Modulinnstillinger endret"
    assert change_summary("unknown.kind", None) is None


def test_published_fix_shows_what_was_changed(canvas_client: TestClient) -> None:
    missing = next(f for f in analyse(canvas_client) if f["rule_id"] == "UU-IMG-MISSING-ALT")
    change = canvas_client.post(f"/api/findings/{missing['id']}/fix/approve", json={"text": "Skjermbilde"}).json()
    job = approve_and_apply(canvas_client, [change["id"]]).json()
    assert wait_for_job(canvas_client, job["id"])["result"]["summary"] == {"applied": 1}
    log = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}&limit=4").json()
    entry = log["items"][0]
    assert entry["action"] == "apply" and entry["object_title"] == missing["object_title"]
    assert entry["summary"] == "Alt-tekst oppdatert"
    assert canvas_client.get(f"/api/changelog/{entry['id']}").json()["summary"] == "Alt-tekst oppdatert"
