"""Emne-RAG end to end against the fake Canvas: estimate, build, privacy, search, answers, incremental updates."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.config import RuntimeConfig
from emneklar.core.auth.secrets import MemorySecretStore
from emneklar.core.container import AppContainer
from emneklar.main import create_app
from tests.conftest import CANVAS_BASE, ORIGIN, fake_internet, login, wait_for_job
from tests.fakes.fake_canvas import TOKEN as FAKE_TOKEN
from tests.fakes.fake_canvas import FakeCanvasState, create_fake_canvas, now
from tests.fakes.rag import (
    RAG_COURSE,
    FakeLocalModels,
    FakeYouTubeApi,
    FakeYouTubeSnippet,
    FakeYouTubeTranscript,
    fake_vimeo,
    seed_rag_course,
)

VIMEO_REQUESTS: list[httpx.Request] = []


def rag_internet(request: httpx.Request) -> httpx.Response:
    return fake_vimeo(request, VIMEO_REQUESTS) or fake_internet(request)

BASE_OPTIONS: dict[str, Any] = {"scope": "course", "text": True, "documents": True}


@pytest.fixture(autouse=True)
def fake_youtube(monkeypatch: pytest.MonkeyPatch) -> type[FakeYouTubeApi]:
    """YouTube captions without network: the guest lecture has automatic English captions, the extra video none."""
    import youtube_transcript_api
    from youtube_transcript_api import TranscriptsDisabled

    from emneklar.features.course_rag import media

    monkeypatch.setattr(media, "ONLINE_PAUSE_SECONDS", 0.0)
    FakeYouTubeApi.calls = []
    VIMEO_REQUESTS.clear()
    FakeYouTubeApi.videos = {
        "abcdefghijk": [FakeYouTubeTranscript("en", True, [
            FakeYouTubeSnippet("Welcome to this guest lecture on colour grading.", 0.0, 4.0),
            FakeYouTubeSnippet("Skin tones need a calibrated monitor.", 95.2, 5.0)])],
        "zyxwvutsrqp": TranscriptsDisabled("zyxwvutsrqp"),
    }
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeYouTubeApi)
    return FakeYouTubeApi


@pytest.fixture
def rag_state(fake_state: FakeCanvasState) -> FakeCanvasState:
    seed_rag_course(fake_state)
    return fake_state


@pytest.fixture
def rag_container(config: RuntimeConfig, rag_state: FakeCanvasState) -> AppContainer:
    return AppContainer(config, secret_store=MemorySecretStore(),
                        canvas_transport=httpx.ASGITransport(app=create_fake_canvas(rag_state)),
                        link_transport=httpx.MockTransport(rag_internet),
                        local_models=FakeLocalModels(config.models_dir))


@pytest.fixture
def rag(rag_container: AppContainer) -> Iterator[TestClient]:
    app = create_app(rag_container)
    with TestClient(app, base_url=ORIGIN) as raw:
        client = login(raw)
        assert client.put("/api/canvas/connection", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN}).status_code == 200
        yield client


def build(client: TestClient, **options: Any) -> dict:
    body = {**BASE_OPTIONS, "accept_downloads": True, **options}
    response = client.post(f"/api/courses/{RAG_COURSE}/rag/build", json=body)
    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["id"], timeout=60)
    assert job["status"] == "completed", job
    return job


def search(client: TestClient, query: str, **extra: Any) -> dict:
    response = client.post(f"/api/courses/{RAG_COURSE}/rag/search", json={"query": query, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_estimate_counts_and_privacy(rag: TestClient) -> None:
    response = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json=BASE_OPTIONS)
    assert response.status_code == 200, response.text
    data = response.json()
    counts = data["counts"]
    assert counts["page"] == 5  # unpublished page and block-editor page are not counted
    assert counts["discussion"] == 1 and counts["assignment"] == 1 and counts["quiz"] == 1 and counts["syllabus"] == 1
    assert counts["file_word"] == 1 and counts["file_powerpoint"] == 1 and counts["file_excel"] == 1
    assert counts["file_pdf"] == 2  # the student's PDF is not included
    reasons = " ".join(s["reason"] for s in data["skipped"])
    assert "blokkredigering" in reasons and "gammelt binærformat" in reasons and "LTI" in reasons
    assert all("hemmelige" not in s["title"] for s in data["skipped"])  # student titles are not shown
    # Unpublished content is never dropped silently: it is counted and listed with what to do.
    assert data["unpublished"] == 1
    assert any(s["title"] == "Utkast til eksamen" and "Ta med upubliserte elementer" in s["reason"]
               for s in data["skipped"])
    with_drafts = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate",
                           json={**BASE_OPTIONS, "include_unpublished": True}).json()
    assert with_drafts["counts"]["page"] == 6 and with_drafts["unpublished"] == 0
    assert data["time"]["low_seconds"] <= data["time"]["high_seconds"] and data["privacy"]
    assert data["embedding"]["available"] and data["downloads"] == []


def test_build_search_and_privacy(rag: TestClient, rag_state: FakeCanvasState) -> None:
    job = build(rag)
    assert job["result"]["chunks"] > 5
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    assert status["index"]["status"] == "ready" and status["index"]["built_at"]
    assert status["stats"]["vectors"] == status["stats"]["chunks"]
    assert status["stats"]["chunk_types"].get("table", 0) >= 3 and status["stats"]["chunk_types"].get("slide") == 2
    assert {m["name"] for m in status["modules"]} == {"Modul 1 – Grunnlag", "Modul 2 – Farger", "Modul 3 – Video"}
    skipped = status["index"]["skipped"]
    assert any("skannet" in s["reason"] for s in skipped)  # scanned PDF without an OCR route
    # Privacy: no student content, no discussion replies or submissions requested.
    for chunk_query in ("hemmelige studentinnlegg", "Studentens egen rapport", "Eksamensoppgaven er hemmelig"):
        assert all("student" not in h["text"].lower() and "hemmelig" not in h["text"].lower()
                   for h in search(rag, chunk_query)["hits"])
    paths = [path for _, path in rag_state.requests]
    assert not any("/entries" in p or "/view" in p or "submissions" in p for p in paths)
    assert not any(p.endswith("/files/7004/download") for p in paths)

    result = search(rag, "Hva er et rasterbilde?", debug=True)
    assert result["modes"]["vector"] and result["modes"]["rerank"]
    top = result["hits"][0]
    assert "piksler" in top["text"].lower()
    assert top["citation"] in ("Raster og vektor – Modul 1 – Grunnlag", "Forelesningsnotater.docx")
    assert top["url"].startswith(CANVAS_BASE)
    assert result["debug"]["before_rerank"] and result["debug"]["after_rerank"]
    slides = search(rag, "komplementærfarger fargehjulet", types=["slide"])
    assert slides["hits"] and slides["hits"][0]["citation"] == "Fargemodeller.pptx lysbilde 1"
    filtered = search(rag, "piksler", module_ids=["302"])
    assert all(h["module"] == "Modul 2 – Farger" for h in filtered["hits"])
    deadline = search(rag, "frist innlevering fargekorrigering")
    assert any("Frist: 15.09.2026" in h["text"] for h in deadline["hits"])


def test_incremental_update_only_processes_changes(rag: TestClient, rag_state: FakeCanvasState) -> None:
    build(rag)
    second = build(rag)
    assert second["result"]["items_processed"] == 0 and second["result"]["unchanged"] > 5
    course = rag_state.courses[RAG_COURSE]
    course.pages["fargelaere"]["body"] = "<h2>Fargemodeller</h2><p>HSV beskriver kulør, metning og verdi.</p>"
    course.pages["fargelaere"]["updated_at"] = now()
    del course.pages["forside"]
    third = build(rag)
    assert third["result"]["items_processed"] == 1
    assert search(rag, "metning kulør")["hits"][0]["title"] == "Fargelære"
    assert not any("A101" in h["text"] for h in search(rag, "tirsdager rom A101")["hits"])  # deleted page is gone


def test_blocked_youtube_keeps_indexed_captions(rag: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from youtube_transcript_api import IpBlocked

    from emneklar.features.course_rag import media, sources

    build(rag, video=True, documents=False)
    assert search(rag, "calibrated monitor skin tones", types=["transcript"])["hits"]
    # Later YouTube blocks the network, the cached captions are too old and the YouTube handling has changed.
    monkeypatch.setattr(media, "ONLINE_CACHE_DAYS", 0)
    monkeypatch.setitem(sources.HANDLER_VERSIONS, "youtube", sources.HANDLER_VERSIONS["youtube"] + 1)
    FakeYouTubeApi.videos["abcdefghijk"] = IpBlocked("abcdefghijk")
    FakeYouTubeApi.calls = []
    job = build(rag, video=True, documents=False)
    assert FakeYouTubeApi.calls == ["abcdefghijk"]  # blocked once: YouTube is not asked again in this build
    assert job["result"]["kept"] >= 1  # the indexed captions are kept, not replaced by nothing
    hits = search(rag, "calibrated monitor skin tones", types=["transcript"])["hits"]
    assert hits and hits[0]["title"] == "Gjesteforelesning"
    skipped = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["skipped"]
    assert any(s["title"] == "Ekstra video" and s.get("waiting") and "blokkerer" in s["reason"] for s in skipped)


def test_selected_unpublished_module_is_included(rag: TestClient, rag_state: FakeCanvasState) -> None:
    course = rag_state.courses[RAG_COURSE]
    course.modules[2]["published"] = False  # «Modul 2 – Farger», not published yet (e.g. a Blueprint template)
    course.pages["fargelaere"]["published"] = False
    # Picking the module is the choice: its content is included, published or not, and the estimate says so.
    picked = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json={**BASE_OPTIONS, "scope": "modules",
                                                                       "module_ids": ["302"]}).json()
    assert picked["counts"]["page"] == 1 and picked["counts"]["assignment"] == 1 and picked["counts"]["quiz"] == 1
    assert picked["unpublished"] == 0 and picked["unpublished_included"] >= 3
    # For the whole course, unpublished content needs the explicit option – and is listed, never dropped silently.
    whole = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json=BASE_OPTIONS).json()
    assert whole["counts"]["page"] == 4 and whole["unpublished"] == 2
    assert {"Fargelære", "Utkast til eksamen"} <= {s["title"] for s in whole["skipped"] if "upubliserte" in s["reason"]}
    drafts = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json={**BASE_OPTIONS,
                                                                       "include_unpublished": True}).json()
    assert drafts["counts"]["page"] == 6 and drafts["unpublished"] == 0 and drafts["unpublished_included"] == 2
    build(rag, scope="modules", module_ids=["302"], mode="full")
    assert search(rag, "metning kulør")["hits"][0]["title"] == "Fargelære"


def test_modules_scope(rag: TestClient) -> None:
    build(rag, scope="modules", module_ids=["301"], mode="full")
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    assert {m["id"] for m in status["modules"]} == {"301"}
    titles = {h["title"] for h in search(rag, "piksler raster vektor farger")["hits"]}
    assert titles <= {"Raster og vektor", "Forelesningsnotater.docx"}


def test_model_change_requires_reindex(rag: TestClient, rag_container: AppContainer) -> None:
    build(rag)
    rag_container.settings.update(lambda s: setattr(s.rag, "embedding_model", "NbAiLab/nb-sbert-v2-large"))
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    assert status["model_mismatch"] is True
    response = rag.post(f"/api/courses/{RAG_COURSE}/rag/build", json={**BASE_OPTIONS, "accept_downloads": True})
    job = wait_for_job(rag, response.json()["id"])
    assert job["status"] == "failed" and "annen embedding-modell" in job["error"]
    assert search(rag, "piksler")["modes"]["vector"] is False
    build(rag, mode="full")
    assert search(rag, "piksler")["modes"]["vector"] is True


def test_keyword_only_without_local_models(config: RuntimeConfig, rag_state: FakeCanvasState) -> None:
    container = AppContainer(config, secret_store=MemorySecretStore(),
                             canvas_transport=httpx.ASGITransport(app=create_fake_canvas(rag_state)),
                             local_models=FakeLocalModels(config.models_dir, installed=False))
    with TestClient(create_app(container), base_url=ORIGIN) as raw:
        client = login(raw)
        client.put("/api/canvas/connection", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN})
        status = client.get(f"/api/courses/{RAG_COURSE}/rag").json()
        assert status["embedding"]["available"] is False and "ikke installert" in status["embedding"]["reason"]
        build(client)
        result = search(client, "Hva er et rasterbilde?")
        assert result["hits"] and result["modes"] == {"keyword": True, "vector": False, "rerank": False,
                                                      "rewritten": False}


def test_download_confirmation_required(config: RuntimeConfig, rag_state: FakeCanvasState) -> None:
    container = AppContainer(config, secret_store=MemorySecretStore(),
                             canvas_transport=httpx.ASGITransport(app=create_fake_canvas(rag_state)),
                             local_models=FakeLocalModels(config.models_dir, downloaded=False))
    with TestClient(create_app(container), base_url=ORIGIN) as raw:
        client = login(raw)
        client.put("/api/canvas/connection", json={"base_url": CANVAS_BASE, "token": FAKE_TOKEN})
        estimate = client.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json=BASE_OPTIONS).json()
        assert {d["kind"] for d in estimate["downloads"]} == {"embedding", "reranker"}
        assert all(d["size_mb"] > 1000 for d in estimate["downloads"])
        refused = client.post(f"/api/courses/{RAG_COURSE}/rag/build", json=BASE_OPTIONS)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "rag_download_required"


def enable_ai(client: TestClient, container: AppContainer, answer: Callable[[dict], dict]) -> list[dict]:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer(body))},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    container.ai_transport = httpx.MockTransport(handler)
    assert client.put("/api/ai/providers/openai", json={"enabled": True, "api_key": "sk-proj-ragtest1234567"}
                      ).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    return calls


def test_answer_with_citations_needs_consent(rag: TestClient, rag_container: AppContainer) -> None:
    build(rag)
    calls = enable_ai(rag, rag_container, lambda _b: {"answer": "Et rasterbilde består av piksler [S1] [S7].",
                                                      "coverage": "full", "cited": ["S1", "S7"]})
    plan = rag.post(f"/api/courses/{RAG_COURSE}/rag/ask/prepare", json={"query": "Hva er et rasterbilde?"}).json()
    assert plan["available"] and plan["needs_confirmation"] and "Ingen studentdata" in plan["payload_summary"]
    refused = rag.post(f"/api/courses/{RAG_COURSE}/rag/ask", json={"query": "Hva er et rasterbilde?"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ai_consent_required"
    answer = rag.post(f"/api/courses/{RAG_COURSE}/rag/ask",
                      json={"query": "Hva er et rasterbilde?", "confirmed": True}).json()
    assert answer["answer"].endswith("[S1].") and "[S7]" not in answer["answer"]  # unknown source removed
    assert answer["cited"] == ["S1"] and answer["label"] == "KI-forslag – må vurderes"
    assert answer["sources"][0]["cited"] and answer["sources"][0]["url"].startswith(CANVAS_BASE)
    prompt = calls[-1]["messages"][-1]["content"][0]["text"]
    assert "[S1]" in prompt and "Spørsmål: Hva er et rasterbilde?" in prompt
    assert "Studentens egen rapport" not in prompt


def test_delete_index(rag: TestClient, rag_container: AppContainer) -> None:
    build(rag)
    assert rag.delete(f"/api/courses/{RAG_COURSE}/rag").json() == {"ok": True}
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    assert status["index"] is None and status["stats"] is None
    missing = rag.post(f"/api/courses/{RAG_COURSE}/rag/search", json={"query": "piksler"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "rag_index_missing"


def test_flag_and_validation(rag: TestClient, rag_container: AppContainer) -> None:
    nothing = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json={"scope": "modules", "module_ids": []})
    assert nothing.status_code == 400 and nothing.json()["error"]["code"] == "rag_nothing_selected"
    rag_container.settings.update(lambda s: s.advanced.feature_flags.__setitem__("course_rag", False))
    assert rag.get(f"/api/courses/{RAG_COURSE}/rag").status_code == 403


class FakeTranscriber:
    calls: list[str] = []

    def available(self) -> bool:
        return True

    def downloads_needed(self) -> list:
        return []

    def transcribe(self, path: Any, *, stop: Any, progress: Any) -> Any:
        from emneklar.core.ai.local.whisper import Segment, Transcript

        FakeTranscriber.calls.append(str(path))
        progress(1.0)
        return Transcript([Segment(0.0, 6.0, "I laben viser vi hvordan hvitbalansen justeres."),
                           Segment(70.0, 75.0, "Til slutt eksporterer vi bildet.")], "no", "NbAiLab/nb-whisper-small",
                          "whisper", 75.0)


def test_video_captions_transcription_cache_and_privacy(rag: TestClient, rag_state: FakeCanvasState,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from emneklar.features.course_rag import media

    FakeTranscriber.calls = []
    monkeypatch.setattr(media, "transcriber", lambda _state: FakeTranscriber())
    estimate = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json={**BASE_OPTIONS, "video": True}).json()
    assert estimate["video"]["with_captions"] >= 2 and estimate["video"]["to_transcribe"] == 1
    assert estimate["video"]["youtube"] == 2
    job = build(rag, video=True, documents=False)
    assert job["status"] == "completed"
    farge = search(rag, "sRGB Adobe RGB gamma", types=["transcript"])["hits"]
    assert farge and farge[0]["citation"].startswith("Video «Forelesning om fargerom» – ")
    assert {h["start"] for h in farge if h["title"] == "Forelesning om fargerom"} >= {0.0, 55.0}
    assert farge[0]["url"].endswith("/courses/104/pages/forelesninger")
    assert farge[0]["module"] == "Modul 3 – Video"
    lab = search(rag, "hvitbalanse", types=["transcript"])["hits"]
    assert {"Lab-demo.mp4", "Lab-demo.vtt"} <= {h["title"] for h in lab} and len(FakeTranscriber.calls) == 1
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    reasons = " ".join(s["reason"] for s in status["index"]["skipped"])
    assert "Panopto" in reasons and "YouTube-videoen har ingen teksting" in reasons
    youtube = search(rag, "calibrated monitor skin tones", types=["transcript"])["hits"]
    assert youtube and youtube[0]["title"] == "Gjesteforelesning" and youtube[0]["item_kind"] == "youtube"
    assert youtube[0]["url"].startswith("https://www.youtube.com/watch?v=abcdefghijk&t=")
    assert sorted(FakeYouTubeApi.calls) == ["abcdefghijk", "zyxwvutsrqp"]  # only the video ids are sent
    waiting = {s["title"]: s for s in status["index"]["skipped"] if s.get("waiting")}
    assert "ingen teksting ennå" in waiting["Ekstra video"]["reason"]  # tried again: captions can be added later
    # Vimeo: the Norwegian uploaded track (not the automatic English one), cited with the unlisted link and time.
    vimeo = search(rag, "gamut kartlegging målrommet", types=["transcript"])["hits"]
    assert vimeo and vimeo[0]["title"] == "Fargerom på Vimeo" and vimeo[0]["item_kind"] == "vimeo"
    assert vimeo[0]["url"].startswith("https://vimeo.com/123456789/abc123def4#t=")
    assert "Vimeo-videoen har ingen teksting ennå" in waiting["Vimeo uten teksting"]["reason"]
    sent = [str(r.url) for r in VIMEO_REQUESTS]
    assert "https://player.vimeo.com/video/123456789/config?h=abc123def4" in sent
    assert not any("texttrack/1.vtt" in u for u in sent)  # only the chosen track is downloaded
    assert all("referer" not in r.headers and "cookie" not in r.headers for r in VIMEO_REQUESTS)
    assert any("Vimeo" in p and "Video-id-en" in p for p in estimate["privacy"])
    assert status["stats"]["video_minutes"] > 1
    assert not any("m-student" in s["key"] for s in status["index"]["skipped"])
    assert search(rag, "Studentopptak")["hits"] == [] or all(
        h["title"] != "Studentopptak" for h in search(rag, "Studentopptak")["hits"])
    # A full rebuild uses the transcript cache (keyed by the file's SHA-256), not the model.
    build(rag, video=True, documents=False, mode="full")
    assert len(FakeTranscriber.calls) == 1


def image_answers(body: dict) -> dict:
    name = (body.get("response_format") or {}).get("json_schema", {}).get("name")
    if name == "bildebeskrivelse":
        return {"relevant": True, "kind": "diagram", "description": "Et fargehjul med primærfarger og sekundærfarger.",
                "text_in_image": "ROD GUL BLA"}
    return {"answer": "Fargehjulet viser primærfargene [S1].", "coverage": "full", "cited": ["S1"]}


def test_images_filtered_described_and_cited(rag: TestClient, rag_container: AppContainer) -> None:
    calls = enable_ai(rag, rag_container, image_answers)
    options = {**BASE_OPTIONS, "images": True}
    estimate = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json=options).json()
    assert estimate["images"]["candidates"] == 6 and estimate["images"]["after_filter"] == 2
    image_ai = next(a for a in estimate["ai"] if a["task"] == "rag_image")
    assert image_ai["available"] and image_ai["external"] and any("bilder fra emnet" in p for p in estimate["privacy"])
    refused = rag.post(f"/api/courses/{RAG_COURSE}/rag/build", json={**options, "accept_downloads": True})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ai_consent_required"
    build(rag, images=True, confirmed=True)
    vision_calls = [c for c in calls if (c.get("response_format") or {}).get("json_schema", {}).get("name")
                    == "bildebeskrivelse"]
    assert len(vision_calls) == 1  # icon, logo, decorative, SVG, duplicate and the 1×1 image in the docx are filtered
    prompt = vision_calls[0]["messages"][-1]["content"][1]["text"]
    assert "Bilder i emnet" in prompt and "Fargehjul" in prompt and "Fargehjulet viser primærfarger" in prompt
    assert vision_calls[0]["messages"][-1]["content"][0]["type"] == "image_url"
    hits = search(rag, "fargehjul primærfarger", types=["image"])["hits"]
    assert hits and hits[0]["citation"] == "Bilde på «Bilder i emnet»" and "ROD GUL BLA" in hits[0]["text"]
    assert hits[0]["meta"]["ai_label"].startswith("KI-generert") and hits[0]["url"].endswith("/pages/bilder")
    reasons = " ".join(s["reason"] for s in rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["skipped"]
                       if s["kind"] == "image")
    assert "Samme bilde som på «Bilder i emnet»" in reasons
    assert "Samme bilde" in reasons and "dekorativt" in reasons and "lite" in reasons and "SVG" in reasons
    assert "pynt" in reasons
    # Unchanged images are not described again on update (and the description cache would be used anyway).
    build(rag, images=True, confirmed=True)
    assert len([c for c in calls if (c.get("response_format") or {}).get("json_schema", {}).get("name")
                == "bildebeskrivelse"]) == 1


def test_images_without_ai_are_skipped_with_reason(rag: TestClient) -> None:
    build(rag, images=True, text=True, documents=False)
    skipped = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["skipped"]
    assert any(s["kind"] == "image" and "krever en bildemodell" in s["reason"] for s in skipped)


def test_evaluation_runs_after_build_and_on_demand(rag: TestClient) -> None:
    build(rag)
    evaluation = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["evaluation"]
    # 15–20 questions in a normal course; this tiny test course has fewer chunks that qualify.
    assert evaluation["method"] == "keywords" and 5 <= len(evaluation["questions"]) <= 18
    assert 0 <= evaluation["health"] <= 100 and evaluation["health_label"] in ("God", "Middels", "Svak")
    assert evaluation["recall_at_5"] >= 0.5  # keyword questions from the chunk itself are usually found
    assert "gjenfinning" in evaluation["explanation"]
    job = rag.post(f"/api/courses/{RAG_COURSE}/rag/evaluate", json={}).json()
    assert wait_for_job(rag, job["id"])["status"] == "completed"
    refused = rag.post(f"/api/courses/{RAG_COURSE}/rag/evaluate", json={"use_ai": True})
    assert refused.status_code == 409


def test_export_endpoints(rag: TestClient) -> None:
    from emneklar.features.course_rag.export import jsonl_lines

    build(rag)
    response = rag.get(f"/api/courses/{RAG_COURSE}/rag/export?format=zip")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    lines = jsonl_lines(response.content)
    assert lines and all(line["vector"] is not None for line in lines)
    assert not any("Studentens egen rapport" in line["text"] for line in lines)
    for fmt, kind in (("md", "text/markdown"), ("docx", "officedocument"), ("pdf", "application/pdf"),
                      ("txt", "text/plain")):
        exported = rag.get(f"/api/courses/{RAG_COURSE}/rag/export?format={fmt}")
        assert exported.status_code == 200 and kind in exported.headers["content-type"], fmt
        assert len(exported.content) > 200
    assert rag.get(f"/api/courses/{RAG_COURSE}/rag/export?format=exe").status_code == 400


def test_contextual_enrichment_is_cached(rag: TestClient, rag_container: AppContainer) -> None:
    def answers(body: dict) -> dict:
        name = (body.get("response_format") or {}).get("json_schema", {}).get("name")
        if name == "kontekst":
            listing = body["messages"][-1]["content"][1]["text"]
            ids = [line.strip("[]") for line in listing.splitlines() if line.startswith("[U")]
            return {"contexts": [{"id": i, "context": "Dette er fra emnet om fargelære."} for i in ids]}
        if name == "testsporsmal":
            listing = body["messages"][-1]["content"][0]["text"]
            ids = [line.split("]")[0].strip("[") for line in listing.splitlines() if line.startswith("[U")]
            return {"questions": [{"id": i, "question": "Hva handler dette om?"} for i in ids]}
        return {}

    calls = enable_ai(rag, rag_container, answers)
    build(rag, contextual_enrichment=True, documents=False, confirmed=True)
    context_calls = [c for c in calls if c["response_format"]["json_schema"]["name"] == "kontekst"]
    assert context_calls and "Dokument (data)" in context_calls[0]["messages"][-1]["content"][0]["text"]
    hits = search(rag, "fargelære")["hits"]
    status = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()
    assert status["index"]["evaluation"]["method"] == "ai"  # consented build that already uses AI
    assert hits
    before = len(context_calls)
    build(rag, contextual_enrichment=True, documents=False, confirmed=True, mode="full")
    assert len([c for c in calls if c["response_format"]["json_schema"]["name"] == "kontekst"]) == before


def test_video_transcribed_by_openai_with_consent_and_cache(rag: TestClient, rag_container: AppContainer,
                                                            rag_state: FakeCanvasState) -> None:
    from tests.test_course_rag_units import speech_like_wav

    rag_state.file_bytes["7101"] = (speech_like_wav(150), "video/mp4")  # the lab video now has real audio
    rag_state.courses[RAG_COURSE].files["7101"]["size"] = len(rag_state.file_bytes["7101"][0])
    uploads: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/audio/transcriptions"):
            uploads.append(request.content)
            return httpx.Response(200, json={"text": f"Lydbit {len(uploads)}: vi justerer hvitbalansen i laben."})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    rag_container.ai_transport = httpx.MockTransport(handler)
    assert rag.put("/api/ai/providers/openai", json={"enabled": True, "api_key": "sk-proj-ragtest1234567"}
                   ).status_code == 200
    rag_container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    assert rag.patch("/api/settings/rag", json={"transcription": "provider"}).status_code == 200
    options = {**BASE_OPTIONS, "documents": False, "video": True}
    estimate = rag.post(f"/api/courses/{RAG_COURSE}/rag/estimate", json=options).json()
    entry = next(a for a in estimate["ai"] if a["task"] == "rag_transcription")
    assert entry["available"] and entry["external"] and entry["route"]["model"] == "gpt-transcribe"
    assert any("bare lyden" in p for p in estimate["privacy"]) and estimate["video"]["transcription"] == "provider"
    # Without consent the video is skipped with an explanation – nothing is sent.
    build(rag, video=True, documents=False)
    waiting = [s for s in rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["skipped"]
               if s["key"] == "file:7101"]
    assert waiting and "samtykke" in waiting[0]["reason"] and waiting[0]["waiting"] and uploads == []
    # The pending video is tried again by an ordinary update once the user has consented.
    build(rag, video=True, documents=False, confirmed=True)
    assert len(uploads) == 2 and all(b"RIFF" in u and b"gpt-transcribe" in u for u in uploads)
    # Only audio: no video title or course text; the second piece gets the first piece's returned text as hint.
    assert not any(b"Lab-demo" in u for u in uploads) and b'name="prompt"' not in uploads[0]
    assert b"Lydbit 1: vi justerer" in uploads[1]
    hits = search(rag, "hvitbalansen laben", types=["transcript"])["hits"]
    lab = sorted((h for h in hits if h["title"] == "Lab-demo.mp4"), key=lambda h: h["start"])
    assert [h["start"] for h in lab] == [0.0, lab[1]["start"]] and 60 <= lab[1]["start"] <= 120
    assert lab[0]["citation"] == "Video «Lab-demo.mp4» – 0:00"
    usage = rag.get("/api/ai/usage").json()
    transcribed = [u for u in usage["items"] if u["task"] == "rag_transcription"]
    assert transcribed and transcribed[0]["task_label"] == "Emnets kunnskapsbase: transkripsjon"
    assert all(u["success"] for u in transcribed)
    build(rag, video=True, documents=False, confirmed=True, mode="full")
    assert len(uploads) == 2  # cached by the file's SHA-256: never transcribed twice


def test_transcription_off_skips_videos_without_captions(rag: TestClient) -> None:
    assert rag.patch("/api/settings/rag", json={"transcription": "off"}).status_code == 200
    build(rag, video=True, documents=False)
    skipped = rag.get(f"/api/courses/{RAG_COURSE}/rag").json()["index"]["skipped"]
    assert any(s["key"] == "file:7101" and "slått av" in s["reason"] for s in skipped)
    assert search(rag, "sRGB Adobe RGB", types=["transcript"])["hits"]  # captions are still used
