"""Content quality: SSRF guard, link states, HTML hygiene and conservative cleanup."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.security.ssrf import UrlBlocked, is_public_ip, validate_url
from emneklar.features.content_quality.hygiene import CLEANUP_OPTIONS, check_hygiene, cleanup, protected_signature
from emneklar.features.content_quality.linkcheck import LinkChecker
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

# ------------------------------------------------------------------------------------- SSRF


@pytest.mark.invariant
@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fe80::1]/", "http://[::ffff:127.0.0.1]/",
    "file:///C:/Windows/win.ini", "ftp://example.org/x", "javascript:alert(1)", "http://user:pw@example.org/",
    "http://example.org:8080/", "http://intranet/", "http://printer.local/", "http://2130706433/",
    "http://metadata.google.internal/",
])
def test_ssrf_guard_blocks_internal_targets(url: str) -> None:
    with pytest.raises(UrlBlocked):
        validate_url(url)


def test_ssrf_guard_allows_public_urls() -> None:
    assert validate_url("https://www.uutilsynet.no/").host == "www.uutilsynet.no"
    assert is_public_ip("8.8.8.8") and not is_public_ip("100.64.0.1")


# ------------------------------------------------------------------------------------ links


def checker(handler) -> LinkChecker:  # type: ignore[no-untyped-def]
    return LinkChecker(httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False), timeout=2)


@pytest.mark.parametrize(("status", "state"), [(200, "WORKING"), (404, "DEAD"), (410, "DEAD"), (401, "AUTH_REQUIRED"),
                                              (403, "UNKNOWN"), (500, "UNKNOWN"), (429, "UNKNOWN")])
async def test_link_states(status: int, state: str) -> None:
    result = await checker(lambda r: httpx.Response(status)).check("https://www.example.org/x")
    assert result.state == state


async def test_403_and_timeout_are_not_dead() -> None:
    forbidden = await checker(lambda r: httpx.Response(403)).check("https://www.example.org/x")
    assert forbidden.state != "DEAD" and "ikke nødvendigvis død" in forbidden.detail

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timeout = await checker(slow).check("https://www.example.org/x")
    assert timeout.state == "TIMEOUT"


async def test_redirects_and_login_detection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        if request.url.path == "/private":
            return httpx.Response(302, headers={"Location": "https://idp.feide.no/login?x=1"})
        return httpx.Response(200)

    c = checker(handler)
    redirect = await c.check("https://www.example.org/old")
    assert redirect.state == "REDIRECT" and redirect.permanent_redirect and redirect.final_url.endswith("/new")
    login = await c.check("https://www.example.org/private")
    assert login.state == "AUTH_REQUIRED"


@pytest.mark.invariant
async def test_redirect_to_internal_address_is_not_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    result = await checker(handler).check("https://www.example.org/x")
    assert result.state == "UNKNOWN"
    assert all("169.254" not in u for u in seen)


async def test_head_not_allowed_falls_back_to_get() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(405 if request.method == "HEAD" else 200)

    assert (await checker(handler).check("https://www.example.org/x")).state == "WORKING"


async def test_link_results_are_cached(container) -> None:  # type: ignore[no-untyped-def]
    container.migrate()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    c = LinkChecker(httpx.AsyncClient(transport=httpx.MockTransport(handler)), db=container.db, cache_hours=24)
    first = await c.check("https://www.example.org/x")
    second = await c.check("https://www.example.org/x")
    assert first.state == second.state == "DEAD" and second.from_cache
    assert calls["n"] == 2  # HEAD + confirming GET, then served from cache


# ---------------------------------------------------------------------------------- hygiene

DIRTY = """<p class="MsoNormal" style="mso-line-height:normal;color:#333">Tekst<o:p></o:p></p>
<p>&nbsp;</p><p> </p><p><br></p><p><span>Hei</span> og <span style="">hopp</span></p>
<font>Gammel</font><center>Midt</center>
<p>A<br><br><br><br>B</p>
<p><a href="https://www.example.org/x" data-api-endpoint="https://c/api">Lenke</a></p>
<iframe title="Video" src="https://www.youtube.com/embed/abc123xyz"></iframe>
<p><img src="/courses/1/files/2/preview" alt="Diagram" data-api-returntype="File"></p>
<div><p>Blokk</div>"""


def test_hygiene_findings() -> None:
    rules = {i.rule_id for i in check_hygiene(DIRTY)}
    assert {"CQ-HTML-EMPTY-PARAGRAPHS", "CQ-HTML-REDUNDANT-SPANS", "CQ-HTML-WORD", "CQ-HTML-DEPRECATED",
            "CQ-HTML-BR-SPACING"} <= rules
    assert {i.rule_id for i in check_hygiene("")} == {"CQ-CONTENT-EMPTY"}
    assert {i.rule_id for i in check_hygiene("<p>Ryddig innhold.</p>")} == set()


def test_structure_validation_finds_block_in_paragraph() -> None:
    issues = check_hygiene("<p>Start <div>blokk</div> slutt</p><ul><li>x</ul></b>")
    invalid = next(i for i in issues if i.rule_id == "CQ-HTML-INVALID")
    assert invalid.count >= 2


@pytest.mark.invariant
def test_cleanup_is_conservative() -> None:
    soup, counts = cleanup(DIRTY, set(CLEANUP_OPTIONS))
    after = str(soup)
    assert protected_signature(DIRTY) == protected_signature(after), "URLs, embeds, Canvas attributes and text intact"
    assert "Mso" not in after and "mso-" not in after and "o:p" not in after
    assert "color:#333" in after, "non-Word inline styles are never removed"
    assert "<center>" in after, "elements with layout effect are never removed automatically"
    assert counts["empty_paragraphs"] == 3 and counts["redundant_spans"] == 2


# ----------------------------------------------------------------------------- end to end


def analyse(client: TestClient) -> dict:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["content_quality"]}).json()
    done = wait_for_job(client, job["id"])
    assert done["status"] == "completed", done
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=content_quality&page_size=200").json()


def test_content_quality_analysis(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    data = analyse(canvas_client)
    by_rule: dict[str, list[dict]] = {}
    for f in data["items"]:
        by_rule.setdefault(f["rule_id"], []).append(f)
    assert "CQ-LINK-DEAD" in by_rule and by_rule["CQ-LINK-DEAD"][0]["evidence"]["http_status"] == 404
    assert "CQ-LINK-INTERNAL-MISSING" in by_rule
    assert "CQ-LINK-REDIRECT" in by_rule
    assert "CQ-LINK-UNKNOWN" in by_rule, "403 is reported as «could not verify», not as dead"
    assert "CQ-MEDIA-UNAVAILABLE" in by_rule
    assert all(f["category_label"] for f in data["items"])
    links = canvas_client.get(f"/api/courses/{COURSE_ID}/links").json()
    states = {link["url"]: link["state"] for link in links["links"]}
    assert states["https://www.example.org/plan"] == "WORKING"
    assert states["https://www.example.org/missing"] == "DEAD"
    assert fake_state.writes == []


def test_dead_link_fix_replace_and_unlink(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    data = analyse(canvas_client)
    dead = next(f for f in data["items"] if f["rule_id"] == "CQ-LINK-DEAD")
    bad = canvas_client.post(f"/api/findings/{dead['id']}/fix/preview", json={"url": "javascript:alert(1)"})
    assert bad.status_code == 400
    unlink = canvas_client.post(f"/api/findings/{dead['id']}/fix/preview", json={"unlink": True}).json()
    assert "https://www.example.org/missing" not in unlink["after_display"]
    staged = canvas_client.post(f"/api/findings/{dead['id']}/fix/stage",
                                json={"url": "https://www.example.org/ny-adresse"}).json()
    assert staged["domain"] == "content_quality"
    assert "https://www.example.org/ny-adresse" in staged["proposed"]["body"]
    assert fake_state.writes == [], "staging never writes"


def test_cleanup_fix_through_change_engine(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    page = fake_state.courses[COURSE_ID].pages["oppsummering"]
    page["body"] = "<h2>Oppsummering</h2><p>&nbsp;</p><p> </p><p><br></p><p><span>Takk</span> for nå.</p>"
    data = analyse(canvas_client)
    empty = next(f for f in data["items"] if f["rule_id"] == "CQ-HTML-EMPTY-PARAGRAPHS")
    preview = canvas_client.post(f"/api/findings/{empty['id']}/fix/preview",
                                 json={"options": ["empty_paragraphs", "redundant_spans"]}).json()
    assert "&nbsp;" not in preview["after_display"] and "<span>" not in preview["after_display"]
    assert "Takk" in preview["after_display"]


def test_recheck_single_link(canvas_client: TestClient) -> None:
    result = canvas_client.post("/api/content-quality/recheck", json={"url": "https://www.example.org/missing"}).json()
    assert result["state"] == "DEAD" and result["from_cache"] is False
    blocked = canvas_client.post("/api/content-quality/recheck", json={"url": "http://127.0.0.1:8765/api/session"}).json()
    assert blocked["state"] == "UNKNOWN"
