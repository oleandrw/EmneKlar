"""The model registry is the one source of truth for AI models: kinds, capabilities, parameters, preference."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from emneklar.core.ai import images
from emneklar.core.ai.base import AIError, ImageGenerationRequest, ImagePart
from emneklar.core.ai.catalog import ModelRegistry, capabilities, clean_params, ordered, suggested_kind, usable
from emneklar.core.ai.router import TASKS, route
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import AIModel, AIUsage
from emneklar.core.storage.settings import AppSettings

READY = {"openai": True, "anthropic": True}


def _models(client: TestClient) -> list[dict]:
    return client.get("/api/ai/models").json()["models"]


def _model(client: TestClient, model_id: str) -> dict:
    return next(m for m in _models(client) if m["model_id"] == model_id)


def _connect_openai(container: AppContainer, client: TestClient, handler=None) -> list[dict]:  # type: ignore[no-untyped-def]
    """OpenAI switched on with external AI allowed. Returns the image requests the fake provider received."""
    seen: list[dict] = []

    def fake(request: httpx.Request) -> httpx.Response:
        if handler is not None:
            return handler(request)
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": "iVBORw0KGgo="}]})

    container.ai_transport = httpx.MockTransport(fake)
    assert client.put("/api/ai/providers/openai", json={"enabled": True, "api_key": "sk-proj-testkey1234567890"}
                      ).status_code == 200
    container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    container.settings.update(lambda s: setattr(s.privacy, "confirm_before_send", False))
    return seen


# ------------------------------------------------------------------------------------------------ the registry


def test_every_kind_of_model_is_in_the_one_registry(canvas_client: TestClient) -> None:
    body = canvas_client.get("/api/ai/models").json()
    kinds = {m["model_id"]: m["kind"] for m in body["models"]}
    assert kinds["claude-opus-5-5"] == "text" and kinds["gpt-image-2.5-sunburst"] == "image"
    assert kinds["gpt-image-2.6-sunburst"] == "image" and kinds["gpt-image-2.6-flare"] == "image"
    assert kinds["gpt-transcribe"] == "transcription"
    assert [k["id"] for k in body["kinds"]] == ["text", "image", "transcription", "embedding"]
    new = _model(canvas_client, "gpt-image-2.6-sunburst")
    assert new["capabilities"] == ["image_generation", "reference_images"] and new["enabled"]
    assert new["params"]["complexities"] == ["low", "medium", "high"], "documented for the 2.6 models"
    assert new["params"]["qualities"] == ["low", "medium", "high"] and new["params"]["aspect_sizes"] == {}, \
        "xhigh, max and arbitrary sizes are only documented for the 2.5 models"
    old = _model(canvas_client, "gpt-image-2.5-sunburst")
    assert old["is_default"] and old["params"]["aspect_sizes"]["16:9"] == "1536x864" and old["price"] is not None
    assert new["price"] is None, "no price is invented for a model without a published one"
    assert _model(canvas_client, "claude-opus-5-5")["capabilities"] == ["text", "vision", "structured_output"]
    assert _model(canvas_client, "whisper-1")["capabilities"] == ["transcription", "timestamps"]


def test_selectors_only_offer_models_with_the_capabilities_the_function_needs(canvas_client: TestClient) -> None:
    models = _models(canvas_client)
    image = {m["model_id"] for m in usable(models, requires=["image_generation"])}
    assert image == {"gpt-image-2.5-sunburst", "gpt-image-2.5-flare", "gpt-image-2.6-sunburst", "gpt-image-2.6-flare"}
    text_models = {m["model_id"] for m in usable(models, requires=TASKS["illustration_review"].requires)}
    assert "claude-opus-5-5" in text_models and not text_models & image, "an image model is never a text model"
    assert {m["model_id"] for m in usable(models, requires=["transcription"], provider_id="openai")} == {
        "gpt-transcribe", "gpt-4o-mini-transcribe", "whisper-1"}
    assert usable(models, requires=["image_generation"], provider_id="anthropic") == []
    routing = canvas_client.get("/api/ai/routing").json()
    assert next(t for t in routing["tasks"] if t["key"] == "alt_text")["requires"] == ["text", "vision"]


def test_the_router_never_uses_an_image_model_for_a_text_task(canvas_client: TestClient) -> None:
    # A model added by hand as an image model with the highest classes: still not a candidate for text.
    added = canvas_client.post("/api/ai/models", json={
        "provider_id": "openai", "model_id": "gpt-image-9", "kind": "image", "quality_class": 4, "speed_class": 3,
        "cost_class": 0}).json()
    assert added["kind"] == "image" and added["capabilities"] == ["image_generation"] and added["text"] is False
    settings = AppSettings()
    settings.ai.strategy = "low_cost"
    decision = route("text_simple", settings, _models(canvas_client), READY)
    chosen = [decision.primary, *decision.fallbacks]
    assert decision.primary is not None and all(m["kind"] == "text" for m in chosen if m)


def test_changes_take_effect_at_once_without_a_restart(canvas_container: AppContainer,
                                                       canvas_client: TestClient) -> None:
    _connect_openai(canvas_container, canvas_client)

    def image_model() -> str | None:
        choice = canvas_client.get("/api/courses/101/illustrations").json()["choices"]["image"]
        return choice["model"]["id"] if choice["model"] else None

    assert image_model() == "gpt-image-2.5-sunburst", "the default image model of «Balansert»"
    new = _model(canvas_client, "gpt-image-2.6-sunburst")
    # Chosen as the default model → used by the next request.
    assert canvas_client.put(f"/api/ai/models/{new['id']}", json={"is_default": True}).json()["is_default"]
    assert image_model() == "gpt-image-2.6-sunburst"
    assert not _model(canvas_client, "gpt-image-2.5-sunburst")["is_default"], "one default model per kind"
    assert _model(canvas_client, "gpt-transcribe")["is_default"], "the default of another kind is untouched"
    # Disabled → gone from every selector, and another compatible model takes over.
    canvas_client.put(f"/api/ai/models/{new['id']}", json={"enabled": False})
    assert "gpt-image-2.6-sunburst" not in {m["model_id"] for m in usable(_models(canvas_client), kind="image")}
    assert image_model() in {"gpt-image-2.5-sunburst", "gpt-image-2.6-flare", "gpt-image-2.5-flare"}
    # Reclassified as a text model → no longer an image model anywhere, and its parameters are the new kind's.
    flare = _model(canvas_client, "gpt-image-2.6-flare")
    changed = canvas_client.put(f"/api/ai/models/{flare['id']}", json={"kind": "text"}).json()
    assert changed["capabilities"] == ["text"] and changed["params"] == {}
    assert "gpt-image-2.6-flare" not in {m["model_id"] for m in usable(_models(canvas_client), kind="image")}
    # Added → offered at once; removed → gone again.
    mine = canvas_client.post("/api/ai/models", json={"provider_id": "openai", "model_id": "min-bildemodell",
                                                      "kind": "image", "priority": 3}).json()
    assert image_model() == "min-bildemodell", "a prioritised model comes first in the automatic choice"
    assert canvas_client.delete(f"/api/ai/models/{mine['id']}").status_code == 200
    assert image_model() != "min-bildemodell"


def test_automatic_choice_follows_the_profile_the_classes_and_the_teachers_preference() -> None:
    def model(model_id: str, quality: int, speed: int, cost: int, **extra: object) -> dict:
        return {"id": len(model_id), "provider_id": "openai", "model_id": model_id, "display_name": model_id,
                "kind": "image", "quality_class": quality, "speed_class": speed, "cost_class": cost, "priority": 0,
                "is_default": False, "enabled": True, "capabilities_known": True,
                "capabilities": ["image_generation"], **extra}

    a = model("image-1-sharp", 4, 1, 3, is_default=True)
    b = model("image-1-quick", 3, 3, 2)
    c = model("image-9-sharp", 4, 1, 3)  # a higher number in the name – and nothing else
    assert ordered([c, b, a], "quality")[0]["model_id"] == "image-1-sharp"
    assert ordered([c, b, a], "speed")[0]["model_id"] == "image-1-quick"
    assert ordered([c, b, a], "low_cost")[0]["model_id"] == "image-1-quick"
    assert ordered([c, b, a], "auto")[0]["model_id"] == "image-1-sharp", "the default model"
    # The version number alone never wins; the teacher's priority does.
    tie = ordered([c, {**a, "is_default": False, "id": 1}], "quality")
    assert tie[0]["model_id"] == "image-1-sharp", "equal classes: the model that was there first, not the higher number"
    assert ordered([{**c, "priority": 2}, {**a, "is_default": False}], "quality")[0]["model_id"] == "image-9-sharp"
    # A disabled or unclassified model, or one at a provider that is not ready, is never a candidate.
    assert usable([{**a, "enabled": False}, {**b, "capabilities_known": False}, c], kind="image",
                  ready={"openai": False}) == []


def test_quality_profiles_choose_image_models_from_the_registry(canvas_container: AppContainer,
                                                               canvas_client: TestClient) -> None:
    _connect_openai(canvas_container, canvas_client)

    def chosen(profile: str) -> str:
        settings = {**canvas_client.get("/api/courses/101/illustrations").json()["settings"], "quality_profile": profile}
        return canvas_client.put("/api/illustrations/settings", json=settings).json()["choices"]["image"]["model"]["id"]

    assert (chosen("max"), chosen("balanced"), chosen("fast")) == (
        "gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare")
    # Without the 2.5 models the profiles keep working with what is enabled – no model name is hard-coded.
    for model_id in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare"):
        canvas_client.put(f"/api/ai/models/{_model(canvas_client, model_id)['id']}", json={"enabled": False})
    assert (chosen("max"), chosen("fast")) == ("gpt-image-2.6-sunburst", "gpt-image-2.6-flare")
    # «Prioriter lav kostnad» also applies to the automatic choice of image model.
    canvas_client.put("/api/ai/routing", json={"strategy": "low_cost"})
    assert chosen("max") == "gpt-image-2.6-flare"


def test_the_teachers_priority_also_applies_to_text_roles(canvas_client: TestClient) -> None:
    from emneklar.core.ai import profiles

    models = _models(canvas_client)
    best = profiles.get("max")
    assert profiles.preferred_models(best, "illustration_analysis", models, READY, vision=False,
                                     min_quality=3)[0]["model_id"] == "claude-fable-5-1"
    sol = _model(canvas_client, "gpt-6.1-sol")
    canvas_client.put(f"/api/ai/models/{sol['id']}", json={"priority": 2})
    luna = _model(canvas_client, "gpt-6-luna")
    canvas_client.put(f"/api/ai/models/{luna['id']}", json={"priority": 3})
    first = profiles.preferred_models(best, "illustration_analysis", _models(canvas_client), READY, vision=False,
                                      min_quality=3)
    assert first[0]["model_id"] == "gpt-6.1-sol", "prioritised and good enough for the role"
    assert "gpt-6-luna" not in [m["model_id"] for m in first], "priority never lowers the quality a role needs"
    decision = route("text_simple", AppSettings(), _models(canvas_client), READY)
    assert decision.primary and decision.primary["model_id"] == "gpt-6-luna" and "prioritet" in decision.reason


# ---------------------------------------------------------------------------- the image assistant and parameters


def test_gpt_image_2_6_is_available_in_the_image_assistant(canvas_container: AppContainer,
                                                          canvas_client: TestClient) -> None:
    seen = _connect_openai(canvas_container, canvas_client)
    settings = canvas_client.get("/api/courses/101/illustrations").json()["settings"]
    choice = canvas_client.put("/api/illustrations/settings", json={
        **settings, "image_model": "gpt-image-2.6-sunburst", "image_quality": "max", "image_complexity": "medium",
        "image_format": "16:9"}).json()["choices"]["image"]
    assert choice["available"] and choice["model"]["id"] == "gpt-image-2.6-sunburst" and choice["note"] is None
    assert choice["model"]["label"] == "GPT-Image-2.6 Sunburst" and choice["reason"] == "Du har valgt bildemodellen selv."
    assert choice["quality"] == "high", "«max» is not a quality of this model: the best one it has is used"
    assert choice["complexity"] == "medium" and choice["size"] == "1536x1024", "nearest standard size for 16:9"
    # The same choices with a 2.5 model: its own qualities and exact 16:9, and no complexity.
    other = canvas_client.put("/api/illustrations/settings", json={
        **settings, "image_model": "gpt-image-2.5-flare", "image_quality": "max", "image_complexity": "medium",
        "image_format": "16:9"}).json()["choices"]["image"]
    assert (other["quality"], other["complexity"], other["size"]) == ("max", "", "1536x864")

    request = ImageGenerationRequest(model="x", prompt="p", size="1536x1024", quality="max", complexity="medium",
                                     input_fidelity="high",
                                     reference_images=[ImagePart.from_bytes(b"png", "image/png")] * 20)
    asyncio.run(canvas_container.ai.generate_image("openai", "gpt-image-2.6-flare", request.model_copy(
        update={"reference_images": []}), summary="test", confirmed=True))
    assert seen[-1] == {"model": "gpt-image-2.6-flare", "prompt": "p", "n": 1, "size": "1536x1024", "quality": "high",
                        "output_format": "png", "background": "opaque", "complexity": "medium"}
    asyncio.run(canvas_container.ai.generate_image("openai", "gpt-image-2.5-flare", request.model_copy(
        update={"reference_images": []}), summary="test", confirmed=True))
    assert "complexity" not in seen[-1] and seen[-1]["quality"] == "max", "never a parameter the model lacks"


def test_a_request_is_fitted_to_what_the_model_supports() -> None:
    full = images.describe({"model_id": "m", "display_name": "M", "provider_id": "openai", "quality_class": 3,
                            "speed_class": 2, "params": clean_params("image", {
                                "reference_images": True, "max_reference_images": 2, "complexities": ["low"],
                                "input_fidelity": True})})
    plain = images.describe(None, model_id="egen-modell", provider_type="openai_compatible", known=False)
    request = ImageGenerationRequest(model="m", prompt="p", quality="xhigh", complexity="low", input_fidelity="high",
                                     reference_images=[ImagePart.from_bytes(b"png", "image/png")] * 5)
    fitted = images.fit(request, full)
    assert (fitted.quality, fitted.complexity, fitted.input_fidelity, len(fitted.reference_images)) == (
        "high", "low", "high", 2)
    bare = images.fit(request, plain)
    assert (bare.quality, bare.complexity, bare.input_fidelity, bare.reference_images) == ("high", None, None, [])
    assert plain["known"] is False and images.size_for(plain, "16:9") == "1536x1024"
    with pytest.raises(AppError):
        clean_params("image", {"qualities": ["ultra"]})
    with pytest.raises(AppError):
        clean_params("image", {"aspect_sizes": {"16:9": "wide"}})
    assert clean_params("text", {"qualities": ["low"]}) == {}, "parameters of another kind are dropped"
    assert capabilities("image", params=clean_params("image", None)) == ["image_generation"]


def test_parameters_can_be_copied_from_a_known_model(canvas_client: TestClient) -> None:
    template = _model(canvas_client, "gpt-image-2.6-sunburst")
    added = canvas_client.post("/api/ai/models", json={"provider_id": "azure", "model_id": "mitt-deployment",
                                                       "params_like": template["id"]}).json()
    assert added["kind"] == "image" and added["params"] == template["params"]
    bad = canvas_client.post("/api/ai/models", json={"provider_id": "openai", "model_id": "x", "kind": "video"})
    assert bad.status_code == 400
    assert canvas_client.put(f"/api/ai/models/{added['id']}", json={"priority": 9}).status_code == 400


# ------------------------------------------------------------------ disabled and removed models, saved settings


def test_a_chosen_model_that_is_disabled_is_replaced_and_the_teacher_is_told(canvas_container: AppContainer,
                                                                            canvas_client: TestClient) -> None:
    seen = _connect_openai(canvas_container, canvas_client)
    settings = canvas_client.get("/api/courses/101/illustrations").json()["settings"]
    canvas_client.put("/api/illustrations/settings", json={**settings, "image_model": "gpt-image-2.6-flare",
                                                           "analysis_model": "openai/gpt-6-astra"})
    for model_id in ("gpt-image-2.6-flare", "gpt-6-astra"):
        canvas_client.put(f"/api/ai/models/{_model(canvas_client, model_id)['id']}", json={"enabled": False})
    status = canvas_client.get("/api/courses/101/illustrations")
    assert status.status_code == 200, "nothing crashes when a chosen model disappears"
    choices = status.json()["choices"]
    image = choices["image"]
    assert image["available"] and image["model"]["id"] == "gpt-image-2.5-sunburst"
    assert "gpt-image-2.6-flare" in image["note"] and "slått av" in image["note"] and "brukes i stedet" in image["note"]
    role = choices["roles"]["illustration_analysis"]
    assert role["primary"]["model_id"] != "gpt-6-astra" and "ikke lenger tilgjengelig" in role["note"]
    assert status.json()["settings"]["image_model"] == "gpt-image-2.6-flare", "the saved setting is kept as it was"
    # A model that is no longer available is never used unasked at the moment an image is made.
    with pytest.raises(AIError) as exc:
        asyncio.run(canvas_container.ai.generate_image(
            "openai", "gpt-image-2.6-flare", ImageGenerationRequest(model="x", prompt="p"), summary="t", confirmed=True))
    assert "slått av" in exc.value.message and seen == []
    # No enabled image model at all: unavailable, with the reason – still no crash.
    for m in usable(_models(canvas_client), kind="image"):
        canvas_client.put(f"/api/ai/models/{m['id']}", json={"enabled": False})
    image = canvas_client.get("/api/courses/101/illustrations").json()["choices"]["image"]
    assert not image["available"] and image["model"] is None and "Ingen modell for bildegenerering" in \
        image["unavailable_reason"]


def test_typed_names_and_saved_settings_from_before_keep_working(canvas_container: AppContainer,
                                                                canvas_client: TestClient) -> None:
    canvas_client.put("/api/ai/providers/azure", json={"enabled": True, "endpoint": "https://x.openai.azure.com",
                                                       "api_key": "azure-test-key-1234567890"})
    canvas_container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    # An Azure deployment is a name the teacher types. Named like a catalog model it gets that model's parameters.
    twin = canvas_container.ai.image_plan("azure", "gpt-image-2.5-sunburst", summary="")
    assert twin["available"] and twin["chosen"] == "typed" and twin["model"]["reference_images"] is True
    own = canvas_container.ai.image_plan("azure", "mitt-bilde-deployment", summary="")
    assert own["available"] and own["model"]["known"] is False and own["model"]["reference_images"] is False
    assert own["model"]["qualities"] == ["low", "medium", "high"]
    # Saved settings from an earlier version have no image_complexity and may name a transcription model.
    stored = {"quality_profile": "fast", "image_provider_id": "openai", "image_model": "gpt-image-2.5-flare"}
    assert AppSettings.model_validate({"illustrations": stored}).illustrations.image_complexity == ""
    plan = canvas_container.ai.transcription_plan("azure", "min-whisper", summary="")
    assert plan["model"]["id"] == "min-whisper" and plan["model"]["segments"] is None and plan["note"] is None


def test_transcription_models_come_from_the_registry(canvas_container: AppContainer,
                                                    canvas_client: TestClient) -> None:
    _connect_openai(canvas_container, canvas_client)
    plan = canvas_container.ai.transcription_plan("openai", "", summary="")
    assert plan["available"] and plan["model"]["id"] == "gpt-transcribe" and plan["model"]["segments"] is False
    assert canvas_container.ai.transcription_plan("openai", "whisper-1", summary="")["model"]["segments"] is True
    canvas_client.put(f"/api/ai/models/{_model(canvas_client, 'whisper-1')['id']}", json={"enabled": False})
    replaced = canvas_container.ai.transcription_plan("openai", "whisper-1", summary="")
    assert replaced["model"]["id"] == "gpt-transcribe" and "whisper-1" in replaced["note"]
    status = canvas_client.get("/api/courses/101/rag").json()
    assert "transcription_models" not in status and {p["id"] for p in status["providers"]} >= {"openai", "azure"}


def test_names_in_earlier_results_are_kept_when_a_model_is_removed(canvas_container: AppContainer,
                                                                  canvas_client: TestClient) -> None:
    mine = canvas_client.post("/api/ai/models", json={"provider_id": "openai", "model_id": "gammel-bildemodell",
                                                      "kind": "image"}).json()
    with canvas_container.db.session() as session:
        session.add(AIUsage(course_id="101", task_type="illustration_image", provider_id="openai",
                            model_id="gammel-bildemodell", strategy="auto", reason="", fallback_used=False,
                            success=True, payload_summary={"summary": "Bildeprompt"}))
    assert canvas_client.delete(f"/api/ai/models/{mine['id']}").status_code == 200
    usage = canvas_client.get("/api/ai/usage").json()["items"]
    assert usage[0]["model_id"] == "gammel-bildemodell", "the usage log still names the model that was used"
    assert canvas_client.delete(f"/api/ai/models/{_model(canvas_client, 'gpt-image-2.5-flare')['id']}").status_code == 409


# ----------------------------------------------------------------------------- earlier databases and discovery


def test_models_added_before_the_registry_had_kinds_end_up_where_they_belong(container: AppContainer) -> None:
    """The reported problem: 2.6 image models enabled under Innstillinger were stored as text models."""
    from alembic import command

    from emneklar.core.storage.db import alembic_config

    cfg = alembic_config(container.db.url)
    with container.db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0008")
        for model_id, enabled, source in (("gpt-image-2.6-sunburst", 1, "discovered"), ("gpt-image-2.6-flare", 1, "user"),
                                          ("gpt-image-7-nova", 1, "user"), ("text-embedding-3-large", 0, "discovered"),
                                          ("gpt-6.1-sol", 1, "catalog")):
            connection.execute(text(
                "INSERT INTO ai_models (provider_id, model_id, display_name, text, vision, structured_output, "
                "context_class, quality_class, speed_class, cost_class, enabled, source, capabilities_known, notes, "
                "updated_at) VALUES ('openai', :m, :m, 1, 1, 1, 2, 2, 2, 2, :e, :s, 1, '', '2026-11-20 10:00:00')"),
                {"m": model_id, "e": enabled, "s": source})
    container.db.migrate(container.config.backups_dir)
    rows = {m["model_id"]: m for m in ModelRegistry(container.db).list()}
    for model_id in ("gpt-image-2.6-sunburst", "gpt-image-2.6-flare"):
        row = rows[model_id]
        assert row["kind"] == "image" and row["enabled"] and row["source"] == "catalog"
        assert row["capabilities"] == ["image_generation", "reference_images"], "the catalog's parameters are adopted"
    assert rows["gpt-image-2.6-sunburst"]["display_name"] == "GPT-Image-2.6 Sunburst"
    unknown = rows["gpt-image-7-nova"]
    assert unknown["kind"] == "image" and unknown["enabled"] and unknown["source"] == "user"
    assert unknown["params"]["qualities"] == ["low", "medium", "high"] and not unknown["params"]["reference_images"]
    assert rows["text-embedding-3-large"]["kind"] == "embedding" and not rows["text-embedding-3-large"]["enabled"]
    assert rows["gpt-6.1-sol"]["kind"] == "text" and rows["gpt-6.1-sol"]["vision"]
    decision = route("alt_text", AppSettings(), list(rows.values()), READY)
    assert decision.primary and decision.primary["kind"] == "text"
    with container.db.session() as session:
        assert session.scalars(select(AIModel).where(AIModel.is_default.is_(True))).all(), "the seed sets defaults"


def test_an_update_does_not_take_away_image_and_transcription_models_that_worked_before(container: AppContainer) -> None:
    """Before the registry had kinds, «Hent modeller» stored every model as an unclassified text model that was off,
    while the image assistant and transcription used their own lists. Those models must still work afterwards."""
    from alembic import command

    from emneklar.core.storage.db import alembic_config

    cfg = alembic_config(container.db.url)
    with container.db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0008")
        for model_id, enabled, known in (("gpt-image-2.5-sunburst", 0, 0), ("gpt-image-2.5-flare", 0, 0),
                                         ("gpt-image-2.6-sunburst", 0, 0), ("gpt-transcribe", 0, 0),
                                         ("whisper-1", 0, 1), ("gpt-image-1.5", 0, 0)):
            connection.execute(text(
                "INSERT INTO ai_models (provider_id, model_id, display_name, text, vision, structured_output, "
                "context_class, quality_class, speed_class, cost_class, enabled, source, capabilities_known, notes, "
                "updated_at) VALUES ('openai', :m, :m, 1, 0, 0, 1, 1, 1, 1, :e, 'discovered', :k, '', "
                "'2026-11-20 10:00:00')"), {"m": model_id, "e": enabled, "k": known})
    container.db.migrate(container.config.backups_dir)
    registry = ModelRegistry(container.db)
    rows = {m["model_id"]: m for m in registry.list()}
    for model_id in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare", "gpt-image-2.6-sunburst", "gpt-transcribe"):
        assert rows[model_id]["enabled"] and rows[model_id]["capabilities_known"], model_id
    assert rows["gpt-image-2.5-sunburst"]["is_default"] and rows["gpt-transcribe"]["is_default"]
    assert not rows["whisper-1"]["enabled"], "a model the teacher had classified keeps its switch"
    assert not rows["gpt-image-1.5"]["enabled"], "a model outside the catalog stays off until it is classified"
    images_now = [m["model_id"] for m in ordered(registry.usable(kind="image", provider_id="openai", ready=READY),
                                                 "auto")]
    assert images_now[0] == "gpt-image-2.5-sunburst" and "gpt-image-2.6-sunburst" in images_now
    assert "gpt-image-1.5" not in images_now
    registry.update(rows["gpt-image-2.6-sunburst"]["id"], {"enabled": False})
    assert not {m["model_id"]: m for m in registry.list()}["gpt-image-2.6-sunburst"]["enabled"], "seeding runs once"


def test_discovered_models_get_a_suggested_kind_and_stay_off_until_classified(canvas_client: TestClient,
                                                                              canvas_container: AppContainer) -> None:
    from emneklar.core.ai.base import DiscoveredModel

    assert (suggested_kind("gpt-image-3-aurora"), suggested_kind("gpt-7-transcribe"), suggested_kind("gpt-7")) == (
        "image", "transcription", "text")
    canvas_container.ai.registry.merge_discovered("openai", [
        DiscoveredModel(id="gpt-image-3-aurora", name="gpt-image-3-aurora"), DiscoveredModel(id="gpt-7", name="gpt-7")],
        local=False)
    found = _model(canvas_client, "gpt-image-3-aurora")
    assert found["kind"] == "image" and not found["enabled"] and not found["capabilities_known"]
    assert found["model_id"] not in {m["model_id"] for m in usable(_models(canvas_client), kind="image")}
    # Classified by the teacher (the type can be changed there) → usable.
    canvas_client.put(f"/api/ai/models/{found['id']}", json={"kind": "image", "quality_class": 4, "enabled": True})
    assert found["model_id"] in {m["model_id"] for m in usable(_models(canvas_client), kind="image")}
    assert _model(canvas_client, "gpt-7")["kind"] == "text"
