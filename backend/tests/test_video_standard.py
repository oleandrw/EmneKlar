"""Standardiser videoavspillere (Innholdskvalitet → Media): YouTube detection, parameters, titles and provenance,
Canvas-safe responsive markup, minimal changes, the change set and Dry run, idempotency and the metadata SSRF rules."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup, Tag
from fastapi.testclient import TestClient

from emneklar.core.canvas.html import is_generic_iframe_title
from emneklar.core.security.sanitize import ALLOWED_CSS, canvas_sanitize
from emneklar.core.security.ssrf import UrlBlocked
from emneklar.features.content_quality import video_api
from emneklar.features.content_quality.video import (
    STANDARD_ALLOW,
    STANDARD_CLASS,
    TitleSource,
    VideoContext,
    VideoOptions,
    embed_src,
    find_embeds,
    find_unsupported,
    format_video_title,
    has_autoplay,
    parse_youtube_url,
    preview_markup,
    propose,
    resolve_title,
    same_markup,
    splice,
    standard_markup,
    validate_title,
)
from tests.conftest import fake_internet, wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState

VIDEO_PAGE = "video-og-medier"  # fake Canvas: one fixed-size YouTube embed with autoplay, no title
VIDEO_ID = "dQw4w9WgXcQ"
FIXED = ('<iframe width="800" height="450" src="https://www.youtube.com/embed/ABC123" title="YouTube video player" '
         'frameborder="0" allowfullscreen></iframe>')


@pytest.fixture(autouse=True)
def _fresh_metadata_cache() -> Any:
    video_api.clear_metadata_cache()
    yield
    video_api.clear_metadata_cache()


def standardise(html: str, titles: dict[str, str] | None = None, options: VideoOptions | None = None) -> str:
    edits = []
    for embed in find_embeds(html):
        proposal = propose(embed, options or VideoOptions(), (titles or {}).get(embed.video_id))
        if proposal.markup is not None and proposal.span is not None:
            edits.append((proposal.span, proposal.markup))
    return splice(html, edits)


def css(el: Tag) -> dict[str, str]:
    props = {}
    for part in str(el.get("style") or "").split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            props[name.strip()] = value.strip()
    return props


# --------------------------------------------------------------------------------- detection


@pytest.mark.parametrize(("src", "nocookie"), [
    ("https://www.youtube.com/watch?v=ABC123", False),
    ("https://youtu.be/ABC123", False),
    ("https://www.youtube.com/embed/ABC123", False),
    ("https://www.youtube-nocookie.com/embed/ABC123", True),
    ("//www.youtube.com/embed/ABC123", False),
    ("https://m.youtube.com/watch?feature=share&v=ABC123", False),
    ("https://www.youtube.com/shorts/ABC123", False),
])
def test_youtube_urls_give_the_canonical_video_id(src: str, nocookie: bool) -> None:
    url = parse_youtube_url(src)
    assert url is not None and url.video_id == "ABC123" and url.nocookie is nocookie


@pytest.mark.parametrize("src", [
    "https://player.vimeo.com/video/123456", "https://www.youtube.com/embed/", "https://www.youtube.com/channel/UCabcdef",
    "https://youtube.com.evil.example/embed/ABC123", "https://evil.example/www.youtube.com/embed/ABC123",
    "https://www.youtube.com/embed/ABC123%2F..%2F", "javascript:alert(1)", "",
])
def test_other_addresses_are_not_youtube_videos(src: str) -> None:
    assert parse_youtube_url(src) is None


def test_existing_iframes_of_every_form_are_found() -> None:
    sources = ["https://www.youtube.com/watch?v=AAAAAA", "https://youtu.be/BBBBBB", "https://www.youtube.com/embed/CCCCCC",
               "https://www.youtube-nocookie.com/embed/DDDDDD", "https://player.vimeo.com/video/1"]
    html = "".join(f'<p>Tekst</p><iframe src="{src}"></iframe>' for src in sources)
    assert [e.video_id for e in find_embeds(html)] == ["AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD"]
    twice = find_embeds('<iframe src="https://youtu.be/AAAAAA"></iframe><iframe src="https://youtu.be/AAAAAA"></iframe>')
    assert [(e.video_id, e.occurrence) for e in twice] == [("AAAAAA", 0), ("AAAAAA", 1)]


def test_unsupported_youtube_embeds_are_listed_for_manual_control() -> None:
    html = ('<iframe src="https://www.youtube.com/embed/" title="Video"></iframe>'
            '<object><param name="movie" value="https://www.youtube.com/v/ABC123">'
            '<embed src="https://www.youtube.com/v/ABC123"></object>'
            '<iframe src="https://player.vimeo.com/video/1"></iframe>')
    found = find_unsupported(html)
    assert len(found) == 2 and "video-ID" in found[0][1] and "Flash" in found[1][1]
    assert find_embeds(html) == []


# -------------------------------------------------------------------------------- parameters


def test_video_id_and_parameters_are_preserved() -> None:
    src = "https://www.youtube.com/embed/ABC123?start=30&playlist=ABC123,DEF456&index=2&controls=0&rel=0&mute=1&loop=1"
    out = standardise(f'<iframe width="560" height="315" src="{src.replace("&", "&amp;")}"></iframe>')
    iframe = BeautifulSoup(out, "html.parser").find("iframe")
    assert isinstance(iframe, Tag) and iframe["src"] == src, "a working embed address is kept exactly"


def test_t_becomes_start_and_other_forms_become_embed_addresses() -> None:
    short = parse_youtube_url("https://youtu.be/ABC123?t=1m5s")
    assert short is not None and embed_src("https://youtu.be/ABC123?t=1m5s", short) == \
        "https://www.youtube.com/embed/ABC123?start=65"
    watch = parse_youtube_url("https://www.youtube.com/watch?v=ABC123&list=PLxyz&index=3")
    assert watch is not None and embed_src("", watch) == "https://www.youtube.com/embed/ABC123?list=PLxyz&index=3"
    private = parse_youtube_url("https://www.youtube-nocookie.com/embed/ABC123?start=10")
    assert private is not None and embed_src("https://www.youtube-nocookie.com/embed/ABC123?start=10", private) == \
        "https://www.youtube-nocookie.com/embed/ABC123?start=10"


def test_autoplay_is_neither_added_nor_silently_removed() -> None:
    html = '<iframe src="https://www.youtube.com/embed/ABC123?autoplay=1" width="560" height="315"></iframe>'
    (embed,) = find_embeds(html)
    assert has_autoplay(embed.url) and "autoplay=1" in standardise(html)
    plain = standardise('<iframe src="https://www.youtube.com/embed/ABC123" width="560" height="315"></iframe>')
    assert "autoplay" not in plain and "autoplay" not in STANDARD_ALLOW


# ------------------------------------------------------------------------------------ titles


@pytest.mark.parametrize("title", ["", "Video", "YouTube", "YouTube video", "YouTube video player", "Embedded video",
                                   "iframe", "Player", "  youtube VIDEO player: "])
def test_generic_titles_are_detected_by_the_shared_validator(title: str) -> None:
    assert is_generic_iframe_title(title)


def test_title_problems_are_reported() -> None:
    html = ('<iframe src="https://www.youtube.com/embed/AAAAAA"></iframe>'
            '<iframe title="YouTube video player" src="https://www.youtube.com/embed/BBBBBB"></iframe>'
            '<iframe title="Introduksjon til kildekritikk og Google-søk" src="https://www.youtube.com/embed/CCCCCC"></iframe>')
    missing, generic, good = find_embeds(html)
    assert "missing_title" in missing.issues and "generic_title" in generic.issues
    assert not {"missing_title", "generic_title"} & set(good.issues)


def test_good_existing_title_is_kept_even_when_metadata_differs() -> None:
    proposal = resolve_title("Introduksjon til kildekritikk og Google-søk", "Kildekritikk – del 1", VideoContext())
    assert proposal.title == "Introduksjon til kildekritikk og Google-søk"
    assert proposal.source is TitleSource.EXISTING and not proposal.needs_review
    overwrite = resolve_title("Min tittel", "Kildekritikk – del 1", VideoContext(), overwrite_existing=True)
    assert overwrite.source is TitleSource.YOUTUBE_METADATA, "only when explicitly asked for"


def test_metadata_title_is_used_in_the_standard_format() -> None:
    proposal = resolve_title("YouTube video player", "NotebookLM Audio Overview: Getting Started", VideoContext())
    assert proposal.title == "Video: NotebookLM Audio Overview: Getting Started"
    assert proposal.source is TitleSource.YOUTUBE_METADATA and not proposal.needs_review
    assert format_video_title("Video: Allerede formatert") == "Video: Allerede formatert"
    assert len(format_video_title("ord " * 100)) <= 122, "kept concise"


@pytest.mark.parametrize("metadata", [None, "Recording 27", "IMG_1234.mov", "Video"])
def test_page_context_is_the_reviewable_fallback(metadata: str | None) -> None:
    context = VideoContext(page_title="Lag KI-generert podcast", heading="Slik bruker du NotebookLM")
    proposal = resolve_title("", metadata, context)
    assert proposal.title == "Video: Slik bruker du NotebookLM (Lag KI-generert podcast)"
    assert proposal.source is TitleSource.PAGE_CONTEXT and proposal.needs_review
    nothing = resolve_title("", None, VideoContext())
    assert nothing.title is None and nothing.source is None and nothing.needs_review


def test_provenance_values_and_manual_validation() -> None:
    assert [s.value for s in TitleSource] == ["existing", "youtube_metadata", "page_context", "ai_suggestion", "manual"]
    with pytest.raises(ValueError, match="handler om"):
        validate_title("YouTube")
    assert validate_title("  Video:  Introduksjon ") == "Video: Introduksjon"


# ------------------------------------------------------------------------- responsive markup


def test_fixed_size_becomes_the_responsive_standard() -> None:
    (embed,) = find_embeds(FIXED)
    assert "fixed_size" in embed.issues and embed.size_label == "800 × 450"
    soup = BeautifulSoup(standardise(FIXED, {"ABC123": "Video: Introduksjon"}), "html.parser")
    wrapper = soup.find("div", class_=STANDARD_CLASS)
    assert isinstance(wrapper, Tag)
    box = wrapper.find("div")
    assert isinstance(box, Tag)
    iframe = box.find("iframe")
    assert isinstance(iframe, Tag)
    assert not {"width", "height", "frameborder"} & set(iframe.attrs)
    assert css(wrapper) == {"max-width": "960px", "margin": "1em auto"}
    assert css(box)["padding-bottom"] == "56.25%" and css(box)["height"] == "0"
    assert css(iframe)["width"] == "100%" and css(iframe)["height"] == "100%" and css(iframe)["border"] == "0"
    assert iframe["title"] == "Video: Introduksjon" and iframe.has_attr("allowfullscreen") and iframe["loading"] == "lazy"


@pytest.mark.parametrize(("options", "expected"), [
    (VideoOptions(max_width=800), {"max-width": "800px", "margin": "1em auto"}),
    (VideoOptions(max_width=None), {"margin": "1em auto"}),
    (VideoOptions(center=False), {"max-width": "960px", "margin": "1em 0"}),
])
def test_width_and_centering_options(options: VideoOptions, expected: dict[str, str]) -> None:
    wrapper = BeautifulSoup(standardise(FIXED, options=options), "html.parser").find("div")
    assert isinstance(wrapper, Tag) and css(wrapper) == expected


def test_16_9_by_default_or_the_existing_format() -> None:
    html = '<iframe width="640" height="480" src="https://www.youtube.com/embed/ABC123"></iframe>'
    assert "padding-bottom: 56.25%" in standardise(html)
    assert "padding-bottom: 75%" in standardise(html, options=VideoOptions(keep_ratio=True))


def test_markup_is_canvas_safe_and_never_wider_than_the_page() -> None:
    markup = standard_markup(src="https://www.youtube.com/embed/ABC123?start=30&rel=0", title="Video: «Test» & mer",
                             ratio=56.25, options=VideoOptions(), allow=STANDARD_ALLOW)
    assert same_markup(markup, canvas_sanitize(markup)), "Canvas' sanitiser keeps every attribute and style"
    for el in BeautifulSoup(markup, "html.parser").find_all(style=True):
        for name, value in css(el).items():
            assert name in ALLOWED_CSS
            assert not (name in ("width", "min-width") and value.endswith("px")), "no fixed width"
    assert "aspect-ratio" not in markup and "<script" not in markup.lower() and "javascript:" not in markup
    # The mobile preview: the standard player fills its box; only the old fixed size has a pixel width.
    def pixel_widths(html: str) -> list[str]:
        return [css(el)["width"] for el in BeautifulSoup(html, "html.parser").find_all(style=True)
                if css(el).get("width", "").endswith("px")]

    assert pixel_widths(preview_markup(markup, "Video")) == []
    assert pixel_widths(preview_markup(FIXED, "Video")) == ["800px"]


def test_existing_responsive_wrapper_is_replaced_not_nested() -> None:
    html = ('<div style="position: relative; padding-bottom: 56.25%; height: 0;"><iframe '
            'src="https://www.youtube.com/embed/ABC123" style="position:absolute;top:0;left:0;width:100%;height:100%">'
            '</iframe></div><p>Etter</p>')
    (embed,) = find_embeds(html)
    assert "old_embed" in embed.issues
    out = standardise(html, {"ABC123": "Video: Test"})
    assert out.count("<div") == 2 and out.endswith("<p>Etter</p>")


def test_video_in_running_text_needs_manual_control() -> None:
    html = '<p>Se denne: <iframe src="https://www.youtube.com/watch?v=ABC123" width="300" height="200"></iframe> nå.</p>'
    (embed,) = find_embeds(html)
    assert embed.manual_reason and embed.layout_manual and "manual" in embed.issues
    proposal = propose(embed, VideoOptions(), "Video: Test")
    assert proposal.markup is not None and not proposal.layout_changed
    assert 'width="300"' in proposal.markup and "/embed/ABC123" in proposal.markup, "only the iframe tag is adjusted"


# ------------------------------------------------------------------------ minimal HTML changes


def test_pages_without_youtube_and_other_iframes_are_untouched() -> None:
    page = ('<h2>Uten video</h2><p>Tekst</p><iframe src="https://player.vimeo.com/video/123" width="640" '
            'height="360"></iframe><iframe src="/media_attachments_iframe/9010?type=video"></iframe>')
    assert find_embeds(page) == [] and standardise(page) == page


def test_only_the_target_embed_changes() -> None:
    before = '<h2>Overskrift</h2>\n<p>Tekst  med   mellomrom og <a href="https://example.org">lenke</a>.</p>\n'
    target = '<iframe width="560" height="315" src="https://www.youtube.com/embed/ABC123"></iframe>'
    after = ('\n<p><img src="/courses/101/files/1/preview" alt="Bilde"></p>\n'
             '<iframe src="https://player.vimeo.com/video/1"></iframe>\n'
             '<iframe src="https://www.youtube.com/embed/DEF456" width="1" height="1"></iframe>')
    html = before + target + after
    first = find_embeds(html)[0]
    proposal = propose(first, VideoOptions(), "Video: Første")
    assert proposal.markup is not None and proposal.span is not None
    out = splice(html, [(proposal.span, proposal.markup)])
    assert out.startswith(before) and out.endswith(after), "everything else stays byte for byte the same"


# ----------------------------------------------------------------------------------- idempotency


def test_standard_embed_produces_no_change() -> None:
    markup = standard_markup(src="https://www.youtube.com/embed/ABC123", title="Video: Test", ratio=56.25,
                             options=VideoOptions(), allow=STANDARD_ALLOW)
    (embed,) = find_embeds(markup)
    assert embed.is_standard_layout and embed.issues == []
    assert propose(embed, VideoOptions(), None).markup is None
    assert propose(embed, VideoOptions(), "Video: Test").markup is None
    (stored,) = find_embeds(canvas_sanitize(markup))  # as Canvas stores it
    assert propose(stored, VideoOptions(), "Video: Test").markup is None


def test_standardising_twice_gives_the_same_markup() -> None:
    once = standardise(FIXED, {"ABC123": "Video: Introduksjon"})
    assert standardise(once, {"ABC123": "Video: Introduksjon"}) == once


# ------------------------------------------------------------------------------ metadata + SSRF


def oembed(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.mark.invariant
@pytest.mark.parametrize("url", [
    "https://localhost/oembed", "https://127.0.0.1/oembed", "https://10.0.0.8/oembed", "https://192.168.0.1/oembed",
    "https://[::1]/oembed", "https://[fd00::1]/oembed", "https://169.254.169.254/oembed", "file:///C:/Windows/win.ini",
    "http://www.youtube.com/oembed", "https://evil.example.org/oembed", "https://www.youtube.com.evil.example/oembed",
    "https://www.youtube.com/redirect?q=https://evil.example.org", "https://www.youtube.com:8443/oembed",
])
def test_metadata_requests_only_go_to_youtube_oembed(url: str) -> None:
    with pytest.raises(UrlBlocked):
        video_api.check_metadata_url(url)
    video_api.check_metadata_url(video_api.metadata_url("ABC123"))


@pytest.mark.invariant
def test_metadata_address_is_built_from_the_video_id_only() -> None:
    (embed,) = find_embeds('<iframe src="https://www.youtube.com/embed/ABC123?origin=http://127.0.0.1'
                           '&amp;x=https://evil.example.org/oembed"></iframe>')
    url = video_api.metadata_url(embed.video_id)
    assert urlsplit(url).hostname == "www.youtube.com" and "127.0.0.1" not in url and "evil" not in url
    assert parse_youtube_url("https://evil.example.org/embed/ABC123") is None, "iframe-supplied hosts are never used"


async def test_metadata_is_fetched_once_per_video() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"title": "Kildekritikk"})

    client = oembed(handler)
    first = await video_api.fetch_metadata(client, "ABC123")
    second = await video_api.fetch_metadata(client, "ABC123")
    assert first.title == "Kildekritikk" and second == first and len(calls) == 1
    assert calls[0] == "https://www.youtube.com/oembed?format=json&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DABC123"


@pytest.mark.parametrize(("response", "status"), [
    (httpx.Response(404), "not_found"), (httpx.Response(400), "not_found"), (httpx.Response(401), "forbidden"),
    (httpx.Response(403), "forbidden"), (httpx.Response(500), "unavailable"),
    (httpx.Response(200, text="<html>"), "unavailable"), (httpx.Response(200, json=["x"]), "ok"),
])
async def test_metadata_failures_are_statuses_not_errors(response: httpx.Response, status: str) -> None:
    result = await video_api.fetch_metadata(oembed(lambda request: response), "ABC123")
    assert result.status == status and result.title is None
    if status != "ok":
        assert result.message and "manuelt" in result.message


async def test_metadata_timeout_does_not_stop_anything() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = await video_api.fetch_metadata(oembed(slow), "ABC123")
    assert result.status == "unavailable" and result.message == video_api.UNAVAILABLE
    assert result.message == ("YouTube-metadata kunne ikke hentes. Videoen kan fortsatt standardiseres, men title må "
                              "vurderes manuelt.")


@pytest.mark.invariant
@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data/", "https://127.0.0.1/oembed", "https://localhost/oembed",
    "https://10.1.2.3/oembed", "file:///etc/passwd", "https://evil.example.org/oembed",
    "https://www.youtube.com/attribution_link?u=/oembed",
])
async def test_redirects_are_revalidated(target: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": target})

    result = await video_api.fetch_metadata(oembed(handler), "ABC123")
    assert result.status == "unavailable"
    assert len(seen) == 1 and seen[0].startswith("https://www.youtube.com/oembed"), "the redirect target is never requested"


async def test_redirect_within_youtube_oembed_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "moved" not in str(request.url):
            return httpx.Response(301, headers={"Location": "https://youtube.com/oembed?format=json&moved=1"})
        return httpx.Response(200, json={"title": "Etter omdirigering"})

    assert (await video_api.fetch_metadata(oembed(handler), "ABC123")).title == "Etter omdirigering"


async def test_playlists_need_no_metadata_request() -> None:
    calls: list[str] = []
    result = await video_api.fetch_metadata(oembed(lambda r: calls.append(str(r.url)) or httpx.Response(200)),
                                            "videoseries")
    assert result.status == "playlist" and calls == []


def test_bulk_titles_come_only_from_metadata_and_never_overwrite_by_default() -> None:
    html = ('<iframe src="https://www.youtube.com/embed/AAAAAA"></iframe>'
            '<iframe title="YouTube video player" src="https://www.youtube.com/embed/BBBBBB"></iframe>'
            '<iframe title="Introduksjon til kildekritikk" src="https://www.youtube.com/embed/CCCCCC"></iframe>')
    missing, generic, good = find_embeds(html)
    ref = {"object_type": "page", "object_id": "side", "video_id": "AAAAAA"}
    body = video_api.BulkBody(items=[video_api.ItemRef(**ref)])  # type: ignore[arg-type]
    assert body.overwrite_existing_title is False, "off by default"
    metadata = video_api.Metadata("ok", "Kildekritikk – del 1")
    assert video_api.bulk_title(missing, metadata, body) == "Video: Kildekritikk – del 1"
    assert video_api.bulk_title(generic, metadata, body) == "Video: Kildekritikk – del 1"
    assert video_api.bulk_title(good, metadata, body) is None
    overwrite = body.model_copy(update={"overwrite_existing_title": True})
    assert video_api.bulk_title(good, metadata, overwrite) == "Video: Kildekritikk – del 1"
    assert video_api.bulk_title(missing, video_api.Metadata("ok", "Recording 27"), body) is None
    assert video_api.bulk_title(missing, video_api.Metadata("not_found"), body) is None


# ------------------------------------------------------------------------------- through the app

TIMEOUT = object()


def internet(answers: dict[str, Any], calls: list[str] | None = None) -> httpx.MockTransport:
    """YouTube's oEmbed service answers from ``answers`` (title, status code or TIMEOUT); the rest as in conftest."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.youtube.com" and request.url.path == "/oembed":
            video_id = str(request.url.params.get("url", "")).rsplit("v=", 1)[-1]
            if calls is not None:
                calls.append(video_id)
            answer = answers.get(video_id, 404)
            if answer is TIMEOUT:
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, json={"title": answer}) if isinstance(answer, str) else httpx.Response(answer)
        return fake_internet(request)

    return httpx.MockTransport(handler)


def analyse(client: TestClient) -> None:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["content_quality"]}).json()
    assert wait_for_job(client, job["id"])["status"] == "completed"


def scan(client: TestClient, **options: Any) -> dict[str, Any]:
    response = client.post(f"/api/courses/{COURSE_ID}/videos/scan", json={"options": options} if options else {})
    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    latest = client.get(f"/api/courses/{COURSE_ID}/videos/latest").json()
    assert latest["job_id"] == job["id"]
    return latest["result"]


def video_item(result: dict[str, Any], page: str = VIDEO_PAGE) -> dict[str, Any]:
    (item,) = [i for i in result["items"] if i["object_id"] == page and i["supported"]]
    return item


def ref(item: dict[str, Any]) -> dict[str, Any]:
    return {k: item[k] for k in ("object_type", "object_id", "object_title", "video_id", "occurrence")}


def apply(client: TestClient, ids: list[int]) -> dict[str, Any]:
    response = client.post("/api/changes/apply", json={"ids": ids})
    assert response.status_code == 200, response.text
    return wait_for_job(client, response.json()["id"])


def test_scan_needs_an_analysis_first(canvas_client: TestClient) -> None:
    response = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/scan", json={})
    assert response.status_code == 409 and "analyse" in response.json()["error"]["message"]
    assert canvas_client.get(f"/api/courses/{COURSE_ID}/videos/latest").json()["result"] is None


@pytest.mark.invariant
def test_scan_preview_stage_dry_run_and_apply(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                             fake_state: FakeCanvasState) -> None:
    canvas_container.link_transport = internet({VIDEO_ID: "Never Gonna Give You Up"})
    analyse(canvas_client)
    original = fake_state.courses[COURSE_ID].pages[VIDEO_PAGE]["body"]
    result = scan(canvas_client)
    item = video_item(result)
    assert item["video_id"] == VIDEO_ID and item["status"] == "safe" and item["autoplay"] is True
    assert {"fixed_size", "missing_title"} <= {i["code"] for i in item["issues"]}
    assert item["current"] == {"title": "", "size": "560 × 315", "layout": "Fast størrelse"}
    assert item["proposed"]["title"] == {"title": "Video: Never Gonna Give You Up", "source": "youtube_metadata",
                                         "source_label": "YouTube-metadata", "needs_review": False}
    summary = result["summary"]
    assert summary["videos"] == len(result["items"]) == summary["standard"] + summary["safe"] + summary["needs_title"] + \
        summary["manual"], "every video is counted once"
    assert fake_state.writes == [], "scanning never writes"

    preview = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/preview", json=ref(item)).json()
    assert 'width="560"' in preview["before_display"] and STANDARD_CLASS in preview["after_display"]
    assert preview["title_source"] == "youtube_metadata" and preview["autoplay"] is True
    assert "<iframe" not in preview["after_preview"], "previews never load the player from YouTube"

    change = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage", json=ref(item)).json()
    assert change["status"] == "staged" and change["domain"] == "content_quality"
    assert change["kind"] == "page.update_body" and change["ai_generated"] is False
    body = change["proposed"]["body"]
    assert f"embed/{VIDEO_ID}?autoplay=1" in body and 'title="Video: Never Gonna Give You Up"' in body
    rest = original[original.index('<p><iframe title="Forelesning 1"'):]
    assert body.startswith("<h2>Introduksjonsvideo</h2>") and body.endswith(rest), "the rest of the page is untouched"
    assert "YouTube-metadata" in change["rationale"]
    assert fake_state.writes == [], "staging never writes"

    canvas_client.put("/api/system/dry-run", json={"enabled": True})
    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "dry_run"
    assert not [w for w in fake_state.writes if w[0] in ("PUT", "POST", "DELETE")]
    assert fake_state.courses[COURSE_ID].pages[VIDEO_PAGE]["body"] == original

    canvas_client.put("/api/system/dry-run", json={"enabled": False})
    job = apply(canvas_client, [change["id"]])
    assert job["result"]["results"][0]["status"] == "applied"
    assert fake_state.courses[COURSE_ID].pages[VIDEO_PAGE]["body"] == body
    log = canvas_client.get(f"/api/changelog?course_id={COURSE_ID}").json()["items"]
    assert log[0]["action"] == "apply" and log[0]["backup_id"]
    backup = canvas_client.get(f"/api/backups/{log[0]['backup_id']}").json()
    assert backup["content"]["state"]["body"] == original, "the existing backup keeps the page as it was"

    # Idempotent: the next scan reads the page from Canvas again and finds nothing to change.
    done = video_item(scan(canvas_client))
    assert done["status"] == "no_change" and done["status_label"] == "Ingen endring nødvendig" and done["issues"] == []
    refused = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage", json=ref(done))
    assert refused.status_code == 400 and "Ingen endring nødvendig" in refused.json()["error"]["message"]
    bulk = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage-bulk", json={"items": [ref(done)]}).json()
    assert bulk["changes"] == 0 and bulk["unchanged"] == 1


def test_bulk_stages_one_change_per_page_without_duplicates(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                           fake_state: FakeCanvasState) -> None:
    page = fake_state.courses[COURSE_ID].pages["oppsummering"]
    page["body"] = ('<h2>Oppsummering</h2><p>Se videoene.</p>'
                    '<iframe width="640" height="360" src="https://youtu.be/AAAAAAAAAAA?t=90" '
                    'title="YouTube video player"></iframe><p>Og denne:</p>'
                    '<iframe width="640" height="360" src="https://www.youtube.com/embed/BBBBBBBBBBB" '
                    'title="Introduksjon til kildekritikk"></iframe><p>Takk for nå.</p>')
    calls: list[str] = []
    canvas_container.link_transport = internet({"AAAAAAAAAAA": "Kildesøk i Oria", "BBBBBBBBBBB": "Kildekritikk 101"}, calls)
    analyse(canvas_client)
    calls.clear()
    items = [i for i in scan(canvas_client)["items"] if i["object_id"] == "oppsummering"]
    assert [i["status"] for i in items] == ["safe", "safe"]
    assert sorted(calls) == ["AAAAAAAAAAA", "BBBBBBBBBBB", VIDEO_ID], "one metadata lookup per video in the course"

    staged = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage-bulk", json={"items": [ref(i) for i in items]})
    assert staged.json() == {"changes": 1, "videos": 2, "titles": 1, "unchanged": 0, "skipped": []}
    changes = [c for c in canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"]
               if c["target"]["object_id"] == "oppsummering"]
    assert len(changes) == 1
    body = changes[0]["proposed"]["body"]
    assert 'title="Video: Kildesøk i Oria"' in body and "embed/AAAAAAAAAAA?start=90" in body
    assert 'title="Introduksjon til kildekritikk"' in body and "Kildekritikk 101" not in body, "descriptive title kept"
    assert body.startswith("<h2>Oppsummering</h2><p>Se videoene.</p>") and body.endswith("<p>Takk for nå.</p>")
    assert "<p>Og denne:</p>" in body

    again = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage-bulk", json={"items": [ref(i) for i in items]})
    assert again.json()["changes"] == 0 and again.json()["unchanged"] == 2, "no second identical change"
    assert len([c for c in canvas_client.get(f"/api/changes?course_id={COURSE_ID}").json()["items"]
                if c["target"]["object_id"] == "oppsummering"]) == 1
    assert fake_state.writes == []


def test_scan_of_selected_modules(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    canvas_container.link_transport = internet({})
    analyse(canvas_client)
    for module_ids, expected in ((["203"], [VIDEO_PAGE]), (["201", "202"], [])):
        response = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/scan", json={"module_ids": module_ids})
        job = wait_for_job(canvas_client, response.json()["id"])
        assert job["status"] == "completed", job
        assert [i["object_id"] for i in job["result"]["items"]] == expected
        assert job["result"]["scope"] == "modules"


@pytest.mark.parametrize("answer", [404, 403, TIMEOUT])
def test_metadata_failure_falls_back_to_the_page_context(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                         answer: Any) -> None:
    canvas_container.link_transport = internet({VIDEO_ID: answer})
    analyse(canvas_client)
    item = video_item(scan(canvas_client))
    assert item["metadata_status"] in ("not_found", "forbidden", "unavailable") and "manuelt" in item["metadata_message"]
    assert item["proposed"]["title"]["source"] == "page_context" and item["proposed"]["title"]["needs_review"]
    assert item["proposed"]["title"]["title"] == "Video: Introduksjonsvideo (Video og medier)"
    assert item["status"] == "needs_title"
    # The reviewed context title is staged with its provenance.
    change = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage", json={
        **ref(item), "title": item["proposed"]["title"]["title"], "title_source": "page_context"}).json()
    assert 'title="Video: Introduksjonsvideo (Video og medier)"' in change["proposed"]["body"]
    assert "Canvas-kontekst" in change["rationale"] and change["source"]["video_title_sources"] == {VIDEO_ID: "page_context"}


def test_manual_title_is_validated(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    canvas_container.link_transport = internet({})
    analyse(canvas_client)
    item = video_item(scan(canvas_client))
    bad = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/preview", json={**ref(item), "title": "YouTube"})
    assert bad.status_code == 400 and "Video" in bad.json()["error"]["message"]
    gone = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/preview", json={**ref(item), "occurrence": 5})
    assert gone.status_code == 409 and "skann" in gone.json()["error"]["message"]


def test_a_kept_existing_title_is_not_revalidated(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                  fake_state: FakeCanvasState) -> None:
    fake_state.courses[COURSE_ID].pages["oppsummering"]["body"] = (
        '<iframe width="640" height="360" title="Uke" src="https://www.youtube.com/embed/AAAAAAAAAAA"></iframe>')
    canvas_container.link_transport = internet({})
    analyse(canvas_client)
    item = video_item(scan(canvas_client), "oppsummering")
    assert item["proposed"]["title"]["source"] == "existing" and item["status"] == "safe"
    response = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/preview",
                                  json={**ref(item), "title": "Uke", "title_source": "existing"})
    assert response.status_code == 200, response.text
    assert 'title="Uke"' in response.json()["after_display"]


@pytest.mark.invariant
@pytest.mark.parametrize(("object_type", "object_id"), [
    ("assignment", "301/../../users/self"), ("quiz", "401?per_page=1"), ("discussion", "abc"),
    ("page", "../../users/self"), ("page", "side#x"), ("page", ".."),
])
def test_content_ids_cannot_change_the_canvas_path(canvas_client: TestClient, object_type: str, object_id: str) -> None:
    for path in ("preview", "stage", "title-suggestion/prepare"):
        response = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/{path}",
                                      json={"object_type": object_type, "object_id": object_id, "video_id": VIDEO_ID})
        assert response.status_code in (400, 422), response.text


def configure_ai(canvas_container, canvas_client: TestClient, handler: Any) -> None:  # type: ignore[no-untyped-def]
    canvas_container.ai_transport = httpx.MockTransport(handler)
    response = canvas_client.put("/api/ai/providers/anthropic", json={"enabled": True, "api_key": "sk-ant-api-test-1234567890"})
    assert response.status_code == 200
    canvas_container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))


def test_ai_is_not_used_when_metadata_gives_a_title(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    sent: list[httpx.Request] = []
    configure_ai(canvas_container, canvas_client, lambda request: sent.append(request) or httpx.Response(500))
    canvas_container.link_transport = internet({VIDEO_ID: "Never Gonna Give You Up"})
    analyse(canvas_client)
    item = video_item(scan(canvas_client))
    for path in ("title-suggestion/prepare", "title-suggestion"):
        response = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/{path}", json={**ref(item), "confirmed": True})
        assert response.status_code == 400 and "KI trengs ikke" in response.json()["error"]["message"]
    assert sent == [], "nothing is sent to an AI provider"


def test_ai_title_is_a_labelled_suggestion_with_minimal_context(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(
            {"title": "Introduksjon til emnet", "confidence": "medium"})}], "stop_reason": "end_turn", "usage": {}})

    configure_ai(canvas_container, canvas_client, handler)
    canvas_container.link_transport = internet({})  # no YouTube metadata
    analyse(canvas_client)
    item = video_item(scan(canvas_client))
    plan = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/title-suggestion/prepare", json=ref(item)).json()
    assert plan["available"] and plan["needs_confirmation"] and "Ingen studentdata" in plan["payload_summary"]
    refused = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/title-suggestion", json={**ref(item), "confirmed": False})
    assert refused.status_code == 409 and sent == [], "nothing is sent before consent"

    answer = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/title-suggestion",
                                json={**ref(item), "confirmed": True}).json()
    assert answer["title"] == "Video: Introduksjon til emnet" and answer["source"] == "ai_suggestion"
    assert answer["source_label"] == "KI-forslag" and answer["label"] == "KI-forslag – må vurderes"
    routing = {t["key"]: t for t in canvas_client.get("/api/ai/routing").json()["tasks"]}
    assert answer["model"] == routing["text_simple"]["decision"]["primary"]["model_id"], "the cheap text task is used"
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert "Introduksjonsvideo" in payload and "Video og medier" in payload
    assert "Velkommen" not in payload and "Bildeformater" not in payload, "no other pages are sent"

    change = canvas_client.post(f"/api/courses/{COURSE_ID}/videos/stage", json={
        **ref(item), "title": answer["title"], "title_source": "ai_suggestion"}).json()
    assert change["ai_generated"] is True and "KI-forslag" in change["rationale"]
