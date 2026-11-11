"""Audio only, video with sound, video without sound and unknown media get the right requirement.

Background: a Canvas audio recording was reported as «Video i Canvas uten tekstspor» (WCAG 1.2.2, «last opp
teksting»). Audio only is WCAG 1.2.1 – a text alternative (transcript), not captions in the player (Uutilsynet's
guidance on 1.2.1, W3C Understanding 1.2.2). A <video> element alone does not prove that a recording has a picture.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from emneklar.core.canvas.html import find_media, parse_html
from emneklar.core.container import AppContainer
from emneklar.core.storage.models import Finding
from emneklar.features.accessibility.checks import ContentDoc, Issue, run_html_checks
from emneklar.features.accessibility.media_kinds import (
    AUDIO,
    VIDEO,
    canvas_media_kind,
    media_keys,
    mime_kind,
    resolve_kind,
)
from emneklar.features.accessibility.rules import get_rule, load_ruleset
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID, FakeCanvasState, _page

AUDIO_EMBED = ('<p><iframe title="Lydopptak: Intervju" data-media-type="audio" data-media-id="m-lyd" '
               'src="/media_attachments_iframe/55?type=audio&amp;embedded=true"></iframe></p>')
VIDEO_EMBED = ('<p><iframe title="Forelesning" data-media-type="video" data-media-id="m-film" '
               'src="/media_attachments_iframe/66?type=video&amp;embedded=true"></iframe></p>')
UNTYPED_MEDIA = ('<p><video class="instructure_inline_media_comment" data-media_comment_id="m-ukjent" '
                 'controls></video></p>')
GUIDANCE = ("Kontroller at lydopptaket har en transkripsjon på siden eller via en tydelig lenke. Teksten skal gjengi "
            "tale og andre lyder som er nødvendige for å forstå innholdet.")


def media_issues(html: str, captions: dict[str, bool | None] | None = None, **kwargs: Any) -> list[Issue]:
    doc = ContentDoc(object_type="page", object_id="p", title="T", html=html, canvas_host="canvas.test")
    return [i for i in run_html_checks(doc, captions, **kwargs) if i.rule_id.startswith("UU-MEDIA-")]


def rules(html: str, captions: dict[str, bool | None] | None = None, **kwargs: Any) -> list[str]:
    return [i.rule_id for i in media_issues(html, captions, **kwargs)]


# -- the rules themselves -------------------------------------------------------------------------------------------


def test_audio_rule_is_a_manual_text_alternative_check() -> None:
    rule = get_rule("UU-MEDIA-AUDIO-ALT")
    assert rule.title == "Kontroller tekstalternativ til lydopptak"
    assert rule.wcag == ["1.2.1"]
    assert rule.classification == "manual_check", "a missing track alone is never «Sannsynlig avvik»"
    assert rule.severity not in ("serious", "critical"), "and never «Alvorlig»"
    assert rule.remediation == GUIDANCE
    assert {c.id for c in rule.confirmations} == {"transcript", "media_alternative"}
    assert "tydelig merket alternativ" in rule.explanation, "the exception for a labelled media alternative"
    assert "Synkronisert teksting eller tekstspor i avspilleren er ikke kravet" in rule.explanation
    assert any("uutilsynet.no/veiledning/121" in s.url for s in rule.sources)


def test_caption_rules_no_longer_claim_that_no_speech_means_no_captions() -> None:
    ruleset = load_ruleset()
    media = [r for r in ruleset.rules.values() if r.category == "media"]
    for rule in media:
        text = f"{rule.explanation} {rule.remediation}"
        assert "uten tale, gjelder ikke kravet" not in text, rule.id
        assert "tekstversjon rett ved videoen" not in text, f"{rule.id}: a transcript never replaces captions"
    captions = ruleset.rules["UU-MEDIA-CANVAS-CAPTIONS"]
    assert captions.wcag == ["1.2.2"] and "lydfil" not in captions.explanation
    assert "andre lyder" in captions.explanation and "transkripsjon erstatter ikke teksting" in captions.explanation
    assert ruleset.rules["UU-MEDIA-TYPE-UNKNOWN"].classification == "manual_check"
    assert ruleset.rules["UU-MEDIA-VIDEO-ONLY-ALT"].wcag == ["1.2.1"]
    assert ruleset.version >= "2026.11.2", "changed rules get a new ruleset version"


def test_mime_kinds_follow_canvas_values() -> None:
    # Canvas' media_type is «audio»/«video», «audio/*» or a MIME type (MediaObject.normalize_content_type).
    assert [mime_kind(v) for v in ("audio", "audio/*", "audio/mp4", "video/*", "video/mp4")] == \
        [AUDIO, AUDIO, AUDIO, VIDEO, VIDEO]
    assert mime_kind("image/png") is None and mime_kind(None) is None and mime_kind("unknown") is None


# -- audio only -----------------------------------------------------------------------------------------------------


def test_canvas_audio_without_track_is_a_text_alternative_check_not_missing_captions() -> None:
    found = media_issues(AUDIO_EMBED, {"55": False})
    assert [i.rule_id for i in found] == ["UU-MEDIA-AUDIO-ALT"]
    issue = found[0]
    assert "teksting" not in issue.message.lower().replace("tekstalternativ", ""), issue.message
    assert issue.evidence["media_kind"] == AUDIO and issue.evidence["kind_source"] == "markup"
    assert issue.evidence["media_key"] == "media:m-lyd"
    assert "UU-MEDIA-CANVAS-CAPTIONS" not in rules(AUDIO_EMBED, {"55": False})
    with_track = media_issues(AUDIO_EMBED, {"55": True})
    assert [i.rule_id for i in with_track] == ["UU-MEDIA-AUDIO-ALT"], "a track in the player is not the requirement"
    assert "tekstspor" in with_track[0].message


def test_text_near_the_recording_is_pointed_out_but_never_accepted() -> None:
    html = AUDIO_EMBED + '<p><a href="/courses/101/files/9/download">Transkripsjon av intervjuet (PDF)</a></p>'
    found = media_issues(html, {"55": False})
    assert [i.rule_id for i in found] == ["UU-MEDIA-AUDIO-ALT"], "a link called «transkripsjon» is not proof"
    assert found[0].evidence["text_alternative_candidates"] == ["Lenke: «Transkripsjon av intervjuet (PDF)»"]
    assert "Mulig tekstalternativ" in found[0].message
    # Plain HTML5 audio was hidden before when the page said «transkripsjon» anywhere – no longer.
    assert rules('<p>Se transkripsjon nederst.</p><audio src="/lyd/intervju.mp3" controls></audio>') == \
        ["UU-MEDIA-AUDIO-ALT"]


def test_labelled_reading_of_the_text_is_hinted_as_the_exception() -> None:
    html = "<p>Innlest versjon av teksten over:</p>" + AUDIO_EMBED
    found = media_issues(html, {"55": False})
    assert found[0].evidence["media_alternative_hint"].startswith("Innlest versjon av teksten over")
    assert found[0].rule_id == "UU-MEDIA-AUDIO-ALT", "the teacher confirms the exception – EmneKlar does not assume it"


def test_audio_files_in_players_and_links() -> None:
    assert rules('<video src="https://cdn.example.org/podkast.mp3" controls></video>') == ["UU-MEDIA-AUDIO-ALT"]
    assert rules('<video controls><source src="https://cdn.example.org/x" type="audio/mp4"></video>') == \
        ["UU-MEDIA-AUDIO-ALT"]
    assert rules('<p><a href="https://example.org/opptak.mp3">Hør opptaket</a></p>') == ["UU-MEDIA-AUDIO-ALT"]


# -- video with sound -----------------------------------------------------------------------------------------------


def test_video_with_sound_still_needs_captions_and_a_transcript_does_not_replace_them() -> None:
    assert rules(VIDEO_EMBED, {"66": False}) == ["UU-MEDIA-CANVAS-CAPTIONS"]
    assert rules(VIDEO_EMBED, {"66": True}) == []
    assert rules(VIDEO_EMBED, {}) == ["UU-MEDIA-EXTERNAL-CAPTIONS"], "unknown caption status is a manual check"
    transcript = VIDEO_EMBED + '<p><a href="/files/1">Transkripsjon av forelesningen</a></p>'
    assert rules(transcript, {"66": False}) == ["UU-MEDIA-CANVAS-CAPTIONS"]
    assert rules('<video src="https://cdn.example.org/klipp.mp4" controls></video>') == ["UU-MEDIA-HTML5-TRACK"]
    issue = media_issues(VIDEO_EMBED, {"66": False})[0]
    assert issue.evidence["media_kind"] == VIDEO


def test_canvas_metadata_wins_over_markup() -> None:
    # Canvas' data fix-up writes data-media-type="video" when it does not know the type; the file says audio.
    html = ('<p><iframe data-media-type="video" data-media-id="m-x" src="/media_attachments_iframe/77"></iframe></p>')
    kinds = {"attachment:77": canvas_media_kind("audio")}
    assert kinds["attachment:77"] is not None
    assert rules(html, {"77": False}, media_kinds=kinds) == ["UU-MEDIA-AUDIO-ALT"]  # type: ignore[arg-type]
    assert rules(html, {"77": False}) == ["UU-MEDIA-CANVAS-CAPTIONS"], "without metadata the markup is used"


# -- video without sound --------------------------------------------------------------------------------------------


def test_video_without_sound_is_not_a_captions_finding() -> None:
    assessed = {"media:m-film": "video_no_audio"}
    assert rules(VIDEO_EMBED, {"66": False}, assessed=assessed) == ["UU-MEDIA-VIDEO-ONLY-ALT"]
    youtube = '<iframe title="Video: Animasjon" src="https://www.youtube.com/embed/abcdefghijk"></iframe>'
    assert rules(youtube, youtube_captions={"abcdefghijk": "none"},
                 assessed={"youtube:abcdefghijk": "video_no_audio"}) == ["UU-MEDIA-VIDEO-ONLY-ALT"]
    assert rules(youtube, youtube_captions={"abcdefghijk": "none"}) == ["UU-MEDIA-YOUTUBE-NO-CAPTIONS"]


# -- unknown kind ---------------------------------------------------------------------------------------------------


def test_unknown_kind_is_a_manual_check_not_a_video() -> None:
    found = media_issues(UNTYPED_MEDIA, {"m-ukjent": False})
    assert [i.rule_id for i in found] == ["UU-MEDIA-TYPE-UNKNOWN"], "a <video> element alone is not proof of a picture"
    assert "videoelement kan også spille av bare lyd" in found[0].message
    assert "ikke registrert noe tekstspor" in found[0].message
    assert found[0].evidence["media_kind"] == "unknown"
    assert rules('<video src="https://cdn.example.org/strøm?id=1" controls></video>') == ["UU-MEDIA-TYPE-UNKNOWN"]
    # The teacher's statement decides.
    assert rules(UNTYPED_MEDIA, {"m-ukjent": False}, assessed={"media:m-ukjent": "audio"}) == ["UU-MEDIA-AUDIO-ALT"]
    assert rules(UNTYPED_MEDIA, {"m-ukjent": False}, assessed={"media:m-ukjent": "video"}) == \
        ["UU-MEDIA-CANVAS-CAPTIONS"]


def test_media_keys_identify_the_recording() -> None:
    soup = parse_html(AUDIO_EMBED + UNTYPED_MEDIA + '<iframe src="https://player.vimeo.com/video/123"></iframe>')
    keys = [media_keys(el, ref) for el, ref in find_media(soup)]
    assert keys == [["media:m-lyd", "attachment:55"], ["media:m-ukjent"], ["vimeo:123"]]
    el, ref = find_media(soup)[1]
    assert resolve_kind(el, ref, assessed={"media:m-ukjent": "video_no_audio"}).source == "user"


# -- through the app: analysis, confirmation, media kind, reports ---------------------------------------------------


def analyse(client: TestClient, items: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"course_id": COURSE_ID, "domains": ["accessibility"]}
    if items:
        body |= {"scope": "items", "items": items}
    job = client.post("/api/analysis", json=body).json()
    assert wait_for_job(client, job["id"], timeout=60)["status"] == "completed"
    return client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()["items"]


def on_page(items: list[dict[str, Any]], page: str) -> list[dict[str, Any]]:
    return [f for f in items if f["object_id"] == page and f["category"] == "media"]


def media_course(state: FakeCanvasState) -> None:
    course = state.courses[COURSE_ID]
    course.media_objects.append({"media_id": "m-lyd", "title": "Intervju", "media_type": "audio", "media_tracks": []})
    course.files["55"] = {"id": "55", "display_name": "intervju.m4a", "filename": "intervju.m4a",
                          "content-type": "audio/mp4", "size": 10, "media_entry_id": "m-lyd",
                          "url": "http://canvas.test/files/55/download", "folder_id": "1"}
    course.pages["lydside"] = _page("lydside", "Intervju", AUDIO_EMBED)
    course.pages["ukjent"] = _page("ukjent", "Opptak", UNTYPED_MEDIA)


def test_new_analysis_replaces_the_wrong_rule_of_an_earlier_analysis(
        canvas_container: AppContainer, canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    media_course(fake_state)
    items = analyse(canvas_client)
    [audio] = on_page(items, "lydside")
    assert audio["rule_id"] == "UU-MEDIA-AUDIO-ALT" and audio["classification"] == "manual_check"
    assert audio["title"] == "Kontroller tekstalternativ til lydopptak"
    assert audio["remediation"] == GUIDANCE
    assert audio["rule"]["media_kind_choice"] is True and audio["rule"]["confirmations"]
    # Make the stored finding look like one from an earlier version (the wrong rule, as the teacher saw it) …
    with canvas_container.db.session() as session:
        row = session.scalars(select(Finding).where(Finding.id == audio["id"])).one()
        row.rule_id, row.title, row.classification, row.severity = (
            "UU-MEDIA-CANVAS-CAPTIONS", "Video i Canvas uten tekstspor", "likely_violation", "serious")
    shown = on_page(canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200")
                    .json()["items"], "lydside")
    assert [f["rule_id"] for f in shown] == ["UU-MEDIA-CANVAS-CAPTIONS"]
    # … a new analysis shows the right rule only.
    again = on_page(analyse(canvas_client), "lydside")
    assert [f["rule_id"] for f in again] == ["UU-MEDIA-AUDIO-ALT"]
    assert [f["rule_id"] for f in on_page(analyse(canvas_client), "ukjent")] == ["UU-MEDIA-TYPE-UNKNOWN"]


def test_confirming_a_text_alternative_survives_reanalysis_and_is_reported(
        canvas_client: TestClient, fake_state: FakeCanvasState) -> None:
    media_course(fake_state)
    [audio] = on_page(analyse(canvas_client), "lydside")
    wrong = canvas_client.post(f"/api/findings/{audio['id']}/verify", json={"confirmation": "captions_present"})
    assert wrong.status_code == 422, "only the rule's own confirmations"
    done = canvas_client.post(f"/api/findings/{audio['id']}/verify",
                              json={"confirmation": "transcript", "note": "Transkripsjon under opptaket"}).json()
    assert done["status"] == "verified"
    assert done["decision"]["label"] == "Transkripsjonen finnes på siden eller via en tydelig lenke"
    listing = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200").json()
    assert audio["id"] not in [f["id"] for f in listing["items"]], "no longer open"
    assert listing["summary"]["verified"] == 1

    analyse(canvas_client)
    verified = canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&status=verified").json()
    assert [f["rule_id"] for f in verified["items"]] == ["UU-MEDIA-AUDIO-ALT"], "the confirmation survives"
    assert verified["items"][0]["decision"]["note"] == "Transkripsjon under opptaket"

    report = canvas_client.post(f"/api/courses/{COURSE_ID}/reports",
                                json={"report_type": "accessibility", "format": "html"})
    assert report.status_code == 200, report.text
    report_html = canvas_client.get(f"/api/reports/{report.json()['id']}/view").text
    assert "Kontrollert manuelt (1)" in report_html
    assert "Transkripsjonen finnes på siden eller via en tydelig lenke" in report_html
    csv_report = canvas_client.post(f"/api/courses/{COURSE_ID}/reports",
                                    json={"report_type": "accessibility", "format": "csv"}).json()
    csv_text = canvas_client.get(f"/api/reports/{csv_report['id']}/download").content.decode("utf-8-sig")
    assert csv_text.splitlines()[0].endswith(";Bekreftet av lærer")
    assert ("Kontrollert;" in csv_text
            and "Transkripsjonen finnes på siden eller via en tydelig lenke – Transkripsjon under opptaket" in csv_text)

    reopened = canvas_client.post(f"/api/findings/{verified['items'][0]['id']}/reopen").json()
    assert reopened["status"] == "open"


def test_choosing_the_media_kind_gives_the_right_requirement(canvas_client: TestClient,
                                                            fake_state: FakeCanvasState) -> None:
    media_course(fake_state)
    [unknown] = on_page(analyse(canvas_client), "ukjent")
    assert unknown["rule_id"] == "UU-MEDIA-TYPE-UNKNOWN"
    answer = canvas_client.post(f"/api/findings/{unknown['id']}/media-kind", json={"kind": "video_no_audio"}).json()
    assert answer["reanalyse"] == {"object_type": "page", "object_id": "ukjent"}
    found = on_page(analyse(canvas_client, [answer["reanalyse"]]), "ukjent")
    assert [f["rule_id"] for f in found] == ["UU-MEDIA-VIDEO-ONLY-ALT"]
    assert found[0]["evidence"]["kind_source"] == "user"

    canvas_client.post(f"/api/findings/{found[0]['id']}/media-kind", json={"kind": "audio"})
    assert [f["rule_id"] for f in on_page(analyse(canvas_client, [answer["reanalyse"]]), "ukjent")] == \
        ["UU-MEDIA-AUDIO-ALT"]
    canvas_client.post(f"/api/findings/{found[0]['id']}/media-kind", json={"kind": None})
    assert [f["rule_id"] for f in on_page(analyse(canvas_client), "ukjent")] == ["UU-MEDIA-TYPE-UNKNOWN"]

    image = next(f for f in analyse(canvas_client) if f["category"] == "images")
    refused = canvas_client.post(f"/api/findings/{image['id']}/media-kind", json={"kind": "audio"})
    assert refused.status_code == 422
