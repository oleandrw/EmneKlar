"""Caption checks of video: no false «mangler teksting» for Canvas media and YouTube videos that have captions.

Background (a real Blueprint course): the course's media list showed ``media_tracks: []`` for all 170 media objects
although most were captioned – Canvas keeps the tracks on the file (attachment). Canvas media rendered as <video> were
taken for plain HTML5 players. And every YouTube embed was a manual check although YouTube knows which have captions.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from emneklar.core.canvas.html import find_media, parse_html
from emneklar.features.accessibility.checks import ContentDoc, run_html_checks
from emneklar.features.accessibility.youtube_captions import MAX_LOOKUPS, CaptionInfo, YoutubeBlocked
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState, _page

MEDIA_COMMENT = ('<video class="instructure_inline_media_comment" controls="controls" data-media_comment_id="m-2Pwiz" '
                 'data-media_comment_type="video" poster="/media_objects/m-2Pwiz/thumbnail"></video>')
FILE_VIDEO = ('<video controls="controls"><source class="instructure_file_link instructure_video_link" '
              'src="/courses/547/files/602521/download?verifier=abc" type="video/mp4"></video>')


def kinds(html: str) -> list[tuple[str, str | None]]:
    return [(ref.kind, ref.ident) for _el, ref in find_media(parse_html(html))]


def rule_ids(html: str, captions: dict[str, bool | None] | None = None,
             youtube: dict[str, str | None] | None = None) -> list[str]:
    doc = ContentDoc(object_type="page", object_id="p", title="T", html=html, canvas_host="canvas.test")
    return [i.rule_id for i in run_html_checks(doc, captions, youtube)]


def test_canvas_media_in_a_video_tag_is_canvas_media() -> None:
    assert kinds(MEDIA_COMMENT) == [("canvas_media", "m-2Pwiz")]
    assert kinds(FILE_VIDEO) == [("canvas_attachment", "602521")]
    assert kinds('<video src="https://cdn.example.org/klipp.mp4"></video>') == [("html5_video", None)]
    assert kinds('<video src="https://andre.example/files/12/download"></video>') == [("html5_video", None)]
    assert "UU-MEDIA-HTML5-TRACK" not in rule_ids(MEDIA_COMMENT, {"m-2Pwiz": True})
    assert "UU-MEDIA-HTML5-TRACK" not in rule_ids(FILE_VIDEO, {"602521": True})
    assert rule_ids(MEDIA_COMMENT, {}) == ["UU-MEDIA-EXTERNAL-CAPTIONS"], "unknown is never «missing»"
    assert "UU-MEDIA-HTML5-TRACK" in rule_ids('<video src="https://cdn.example.org/klipp.mp4" controls></video>')


def test_youtube_caption_states() -> None:
    frame = '<iframe title="Video: Intro" src="https://www.youtube.com/embed/abcdefghijk"></iframe>'
    assert "UU-MEDIA-EXTERNAL-CAPTIONS" in rule_ids(frame), "not checked → manual check, as before"
    assert not [r for r in rule_ids(frame, youtube={"abcdefghijk": "manual"}) if r.startswith("UU-MEDIA-")]
    assert "UU-MEDIA-YOUTUBE-AUTO-CAPTIONS" in rule_ids(frame, youtube={"abcdefghijk": "auto"})
    assert "UU-MEDIA-YOUTUBE-NO-CAPTIONS" in rule_ids(frame, youtube={"abcdefghijk": "none"})
    assert not [r for r in rule_ids(frame, youtube={"abcdefghijk": "unavailable"}) if r.startswith("UU-MEDIA-")]


def analyse(client: TestClient) -> list[dict[str, Any]]:
    job = client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]


def media_findings(items: list[dict[str, Any]], page: str) -> list[str]:
    return sorted(f["rule_id"] for f in items if f["object_id"] == page and f["category"] == "media")


def test_canvas_tracks_are_read_from_the_file(canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    course = fake_state.courses[COURSE_ID]
    # The media list says «no tracks» for everything (as on the real course) …
    assert all(not m["media_tracks"] for m in course.media_objects if m["media_id"] == "m-abc123")
    course.media_objects.append({"media_id": "m-film", "title": "Film", "media_type": "video", "media_tracks": []})
    course.media_objects.append({"media_id": "m-lyd", "title": "Lyd", "media_type": "audio", "media_tracks": []})
    # … while the files carry them: the embedded attachment, and the file whose media_entry_id is the media id.
    fake_state.attachment_tracks["9010"] = [{"id": "1", "kind": "subtitles", "locale": "nb", "workflow_state": "ready"}]
    course.files["9020"] = {"id": "9020", "display_name": "film.mp4", "filename": "film.mp4",
                            "content-type": "video/mp4", "size": 10, "media_entry_id": "m-film",
                            "url": "http://canvas.test/files/9020/download", "folder_id": "1"}
    fake_state.attachment_tracks["9020"] = [{"id": "2", "kind": "captions", "locale": "nb", "workflow_state": "ready"}]
    course.pages["medier"] = _page("medier", "Medier", (
        '<p><iframe title="Film" data-media-id="m-film" data-media-type="video" '
        'src="/media_objects_iframe/m-film?type=video"></iframe></p>'
        '<p><video class="instructure_inline_media_comment" data-media_comment_id="m-lyd" '
        'data-media_comment_type="audio" controls></video></p>'))
    items = analyse(canvas_client)
    assert media_findings(items, "video-og-medier").count("UU-MEDIA-CANVAS-CAPTIONS") == 0, \
        "captions on the attachment count, although the media list shows none"
    medier = media_findings(items, "medier")
    assert "UU-MEDIA-HTML5-TRACK" not in medier, "a Canvas media comment is not a plain HTML5 player"
    assert medier == ["UU-MEDIA-AUDIO-ALT"], "m-lyd is audio (Canvas' media list): a 1.2.1 check, never captions"

    # A file that really has no tracks is still reported.
    fake_state.attachment_tracks["9020"] = []
    items = analyse(canvas_client)
    assert "UU-MEDIA-CANVAS-CAPTIONS" in media_findings(items, "medier")


class Lookups:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def __call__(self, video_id: str) -> CaptionInfo:
        self.calls.append(video_id)
        answer = self.answers.get(video_id, "manual")
        if isinstance(answer, Exception):
            raise answer
        return CaptionInfo(answer, ["nb"])


def youtube_page(state: FakeCanvasState, ids: list[str]) -> None:
    body = "".join(f'<p><iframe title="Video {i}" src="https://www.youtube.com/embed/{i}"></iframe></p>' for i in ids)
    state.courses[COURSE_ID].pages["youtube"] = _page("youtube", "YouTube", body)


def test_youtube_captions_are_checked_and_cached(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                 fake_state: FakeCanvasState) -> None:
    ids = ["MANUALvid01", "AUTOvid0002", "NONEvid0003", "GONEvid0004"]
    youtube_page(fake_state, ids)
    lookups = Lookups({"AUTOvid0002": "auto", "NONEvid0003": "none", "GONEvid0004": "unavailable"})
    canvas_container._youtube_lookup = lookups
    items = analyse(canvas_client)
    found = {f["evidence"].get("video_id"): f for f in items if f["object_id"] == "youtube" and f["category"] == "media"}
    assert set(found) == {"AUTOvid0002", "NONEvid0003"}, "captioned and unavailable videos are not reported here"
    assert found["AUTOvid0002"]["rule_id"] == "UU-MEDIA-YOUTUBE-AUTO-CAPTIONS"
    assert found["AUTOvid0002"]["classification"] == "should_review"
    assert found["NONEvid0003"]["rule_id"] == "UU-MEDIA-YOUTUBE-NO-CAPTIONS"
    assert found["NONEvid0003"]["classification"] == "likely_violation"
    assert sorted(set(lookups.calls)) == sorted([*ids, "dQw4w9WgXcQ"]) and len(lookups.calls) == len(set(lookups.calls))

    analyse(canvas_client)
    assert len(lookups.calls) == len(ids) + 1, "the second analysis uses the cache – YouTube is not asked again"


def test_youtube_block_stops_politely(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                      fake_state: FakeCanvasState) -> None:
    ids = [f"vid{n:08d}" for n in range(6)]
    youtube_page(fake_state, ids)
    lookups = Lookups({i: YoutubeBlocked("RequestBlocked") for i in ids} | {"dQw4w9WgXcQ": YoutubeBlocked("IpBlocked")})
    canvas_container._youtube_lookup = lookups
    items = analyse(canvas_client)
    rules = [f["rule_id"] for f in items if f["object_id"] == "youtube" and f["category"] == "media"]
    assert rules == ["UU-MEDIA-EXTERNAL-CAPTIONS"] * len(ids), "not checked → manual check, never «missing»"
    assert len(lookups.calls) <= 2, "after YouTube refuses, nothing more is asked in this analysis"
    run = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility").json()["runs"][0]
    assert any("YouTube avviste kontroll av teksting" in note for note in run["limitations"])


def test_youtube_lookups_are_capped_per_analysis(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                 fake_state: FakeCanvasState, monkeypatch: pytest.MonkeyPatch) -> None:
    import emneklar.features.accessibility.youtube_captions as module

    monkeypatch.setattr(module, "MAX_LOOKUPS", 3)
    monkeypatch.setattr(module, "PAUSE_SECONDS", 0)
    youtube_page(fake_state, [f"cap{n:08d}" for n in range(5)])
    lookups = Lookups({})
    canvas_container._youtube_lookup = lookups
    analyse(canvas_client)
    assert len(lookups.calls) == 3
    run = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility").json()["runs"][0]
    assert any("kontrolleres ved neste analyse" in note for note in run["limitations"])
    assert MAX_LOOKUPS >= 100, "the real cap leaves room for a normal course"
