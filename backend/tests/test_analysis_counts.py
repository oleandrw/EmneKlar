"""The figures of a finished analysis are what was stored – the same as the pages and Rapporter show."""

from __future__ import annotations

from collections import defaultdict

from fastapi.testclient import TestClient

from emneklar.core.container import AppContainer
from emneklar.core.storage.models import AnalysisRun, Finding
from emneklar.features.findings.store import FindingDraft, FindingStore, make_fingerprint
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

DOMAINS = ["accessibility", "content_quality", "structure"]


def _draft(fingerprint: str, classification: str = "manual_check") -> FindingDraft:
    return FindingDraft(domain="content_quality", rule_id="CQ-TEST", category="links", classification=classification,
                        test_method="manual", severity="minor", title="Kontroller", message="", remediation="",
                        fingerprint=fingerprint, object_type="page", object_id="side")


def _run(container: AppContainer) -> int:
    container.migrate()
    with container.db.session() as session:
        run = AnalysisRun(course_id="101", domains=["content_quality"])
        session.add(run)
        session.flush()
        return run.id


def test_equal_fingerprints_are_stored_once_per_run_also_across_tasks(container: AppContainer) -> None:
    store = FindingStore(container.db)
    run_id = _run(container)
    same = make_fingerprint("101", "content_quality", "CQ-TEST", "page:side", "a")
    other = make_fingerprint("101", "content_quality", "CQ-TEST", "page:side", "b")
    # One task reports the same element twice; another task reports it again.
    assert store.save(run_id, "101", [_draft(same), _draft(same), _draft(other)]) == 2
    assert store.save(run_id, "101", [_draft(same)]) == 0
    with container.db.session() as session:
        assert session.query(Finding).filter(Finding.run_id == run_id).count() == 2
    assert store.run_counts(run_id) == {"content_quality:manual_check": 2}


def test_run_counts_leave_out_what_is_not_open(container: AppContainer) -> None:
    store = FindingStore(container.db)
    run_id = _run(container)
    fps = [make_fingerprint("101", "content_quality", "CQ-TEST", "page:side", str(i)) for i in range(3)]
    store.save(run_id, "101", [_draft(fps[0]), _draft(fps[1], "violation"), _draft(fps[2], "violation")])
    with container.db.session() as session:
        row = session.query(Finding).filter(Finding.fingerprint == fps[2]).one()
        row.status = "ignored"
    assert store.run_counts(run_id) == {"content_quality:manual_check": 1, "content_quality:violation": 1}


def test_the_finished_job_says_what_the_pages_say(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    # The same address twice on one page gives two drafts with one fingerprint (one finding per place): the job
    # used to count both, the pages showed one.
    fake_state.courses[COURSE_ID].pages["oppsummering"]["body"] = (
        '<p>Se <a href="https://www.example.org/ressurs">ressursene</a> og <a href="https://www.example.org/ressurs">'
        'ressurslisten</a>.</p><p><a href="https://www.example.org/missing">Artikkel</a> og '
        '<a href="https://www.example.org/missing">artikkelen igjen</a>.</p>')
    started = canvas_client.post("/api/analysis", json={"course_id": "101", "domains": DOMAINS})
    job = wait_for_job(canvas_client, started.json()["id"])
    assert job["status"] == "completed", job
    counts = job["result"]["counts"]
    # The summary under Analysestatus («… · 42 funn») reads the progress figures: the same as the result.
    assert job["progress"]["findings"] == counts
    run = canvas_client.get("/api/courses/101/findings?domain=accessibility").json()["runs"][0]
    assert run["counts"] == counts
    per_domain: dict[str, dict[str, int]] = defaultdict(dict)
    for key, n in counts.items():
        domain, classification = key.split(":")
        per_domain[domain][classification] = n
    for domain in DOMAINS:
        page = canvas_client.get(f"/api/courses/101/findings?domain={domain}").json()
        assert page["summary"]["by_classification"] == per_domain.get(domain, {}), domain
        assert page["summary"]["total"] == sum(per_domain.get(domain, {}).values()), domain


def test_the_list_counts_what_is_ready_in_the_whole_selection(canvas_client: TestClient) -> None:
    """«Godkjenn alle klare» works on every page of the selection, so the list says how many are ready in all of it."""
    job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    assert wait_for_job(canvas_client, job["id"])["status"] == "completed"
    small = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=5").json()
    every = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()
    counted = {"automatic": sum(1 for f in every["items"] if f["ready"] == "automatic"),
               "suggestion": sum(1 for f in every["items"] if f["ready"] == "suggestion")}
    assert small["ready"] == every["ready"] == counted, "the same totals whatever the page size"
    assert counted["automatic"] > 0, "the fake course has ready fixes"
    assert len(small["items"]) == 5 < every["total"]
