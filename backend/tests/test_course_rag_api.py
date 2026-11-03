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
from tests.fakes.rag import RAG_COURSE, FakeLocalModels, seed_rag_course

BASE_OPTIONS: dict[str, Any] = {"scope": "course", "text": True, "documents": True}


@pytest.fixture
def rag_state(fake_state: FakeCanvasState) -> FakeCanvasState:
    seed_rag_course(fake_state)
    return fake_state


@pytest.fixture
def rag_container(config: RuntimeConfig, rag_state: FakeCanvasState) -> AppContainer:
    return AppContainer(config, secret_store=MemorySecretStore(),
                        canvas_transport=httpx.ASGITransport(app=create_fake_canvas(rag_state)),
                        link_transport=httpx.MockTransport(fake_internet),
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
    assert counts["page"] == 4  # unpublished page and block-editor page are not counted
    assert counts["discussion"] == 1 and counts["assignment"] == 1 and counts["quiz"] == 1 and counts["syllabus"] == 1
    assert counts["file_word"] == 1 and counts["file_powerpoint"] == 1 and counts["file_excel"] == 1
    assert counts["file_pdf"] == 2  # the student's PDF is not included
    reasons = " ".join(s["reason"] for s in data["skipped"])
    assert "blokkredigering" in reasons and "gammelt binærformat" in reasons and "LTI" in reasons
    assert all("hemmelige" not in s["title"] for s in data["skipped"])  # student titles are not shown
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
    assert "Panopto" in reasons and "YouTube" in reasons
    assert status["stats"]["video_minutes"] > 1
    assert not any("m-student" in s["key"] for s in status["index"]["skipped"])
    assert search(rag, "Studentopptak")["hits"] == [] or all(
        h["title"] != "Studentopptak" for h in search(rag, "Studentopptak")["hits"])
    # A full rebuild uses the transcript cache (keyed by the file's SHA-256), not the model.
    build(rag, video=True, documents=False, mode="full")
    assert len(FakeTranscriber.calls) == 1
