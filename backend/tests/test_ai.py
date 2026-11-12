"""AI: provider abstraction, routing strategies, vision, fallback, privacy, secrets."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from emneklar.core.ai.base import AIMessage, AIRequest, ImagePart, TextPart
from emneklar.core.ai.providers.anthropic import AnthropicProvider
from emneklar.core.ai.providers.openai_compat import AzureOpenAIProvider, OpenAICompatibleProvider
from emneklar.core.ai.router import route
from emneklar.core.storage.settings import AppSettings
from tests.conftest import wait_for_job
from tests.fakes.fake_canvas import COURSE_ID

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def model(provider: str, model_id: str, *, q: int, c: int, s: int = 2, vision: bool = True, ctx: int = 4,
          known: bool = True, enabled: bool = True) -> dict:
    return {"provider_id": provider, "model_id": model_id, "display_name": model_id, "vision": vision,
            "structured_output": True, "context_class": ctx, "quality_class": q, "cost_class": c, "speed_class": s,
            "enabled": enabled, "capabilities_known": known}


MODELS = [
    model("openai", "small", q=2, c=1, s=3),
    model("openai", "medium", q=3, c=2, s=2),
    model("anthropic", "large", q=4, c=4, s=1),
    model("anthropic", "text-only-cheap", q=2, c=1, s=3, vision=False),
    model("local", "unclassified", q=1, c=0, known=False),
]
READY = {"openai": True, "anthropic": True, "local": True}


def settings(strategy: str = "auto", **ai: object) -> AppSettings:
    s = AppSettings()
    s.ai.strategy = strategy  # type: ignore[assignment]
    for key, value in ai.items():
        setattr(s.ai, key, value)
    return s


# ------------------------------------------------------------------------------------ routing


def test_simple_task_uses_cheapest_adequate_model() -> None:
    decision = route("text_simple", settings(), MODELS, READY)
    assert decision.primary["model_id"] in ("small", "text-only-cheap")
    assert "rimeligste" in decision.reason


def test_complex_task_needs_capable_model() -> None:
    decision = route("quiz_generation", settings(), MODELS, READY, input_tokens=5000)
    assert decision.primary["model_id"] == "medium"
    big = route("quiz_generation", settings(), MODELS, READY, input_tokens=60_000)
    assert big.primary["model_id"] == "large", "large inputs raise the required quality"


def test_vision_routing_excludes_text_only_models() -> None:
    decision = route("alt_text", settings(), MODELS, READY)
    assert decision.primary["vision"] is True
    assert all(m["vision"] for m in decision.fallbacks)


def test_strategies() -> None:
    assert route("text_standard", settings("quality"), MODELS, READY).primary["model_id"] == "large"
    assert route("quiz_review", settings("low_cost"), MODELS, READY).primary["cost_class"] == 1
    assert route("text_standard", settings("speed"), MODELS, READY).primary["speed_class"] == 3


def test_manual_strategy_and_preferred_provider() -> None:
    manual = route("text_standard", settings("manual", manual_models={"text_standard": "anthropic/large"}), MODELS, READY)
    assert manual.primary["model_id"] == "large"
    missing = route("text_standard", settings("manual"), MODELS, READY)
    assert missing.primary is None and "Manuell" in missing.reason
    preferred = route("quiz_review", settings(task_providers={"quiz_review": "anthropic"}), MODELS, READY)
    assert preferred.primary["provider_id"] == "anthropic"


def test_unclassified_and_unready_models_are_never_used() -> None:
    decision = route("text_simple", settings("low_cost"), MODELS, {"openai": False, "anthropic": False, "local": True})
    assert decision.primary is None, "an unclassified discovered model must not be used"
    assert any("ikke klassifisert" in e for e in decision.excluded)


def test_fallbacks_are_ordered() -> None:
    decision = route("text_standard", settings(), MODELS, READY)
    ids = [decision.primary["model_id"]] + [m["model_id"] for m in decision.fallbacks]
    assert len(ids) == len(set(ids)) and "large" in ids


# ----------------------------------------------------------------------- provider payloads


def capture(response: dict) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response)

    return seen, httpx.MockTransport(handler)


def request_with_image() -> AIRequest:
    return AIRequest(model="m", system="sys", json_schema=SCHEMA,
                     messages=[AIMessage(parts=[TextPart(text="hei"), ImagePart.from_bytes(b"png", "image/png")])])


async def test_openai_payload() -> None:
    seen, transport = capture({"choices": [{"message": {"content": "{\"ok\": true}"}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
    provider = OpenAICompatibleProvider("openai", base_url="https://api.openai.com/v1", api_key="sk-test-123456",
                                        local=False, transport=transport)
    result = await provider.generate(request_with_image())
    body = json.loads(seen[0].content)
    assert "temperature" not in body and body["max_completion_tokens"] == 2000
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert seen[0].headers["authorization"] == "Bearer sk-test-123456"
    assert result.data == {"ok": True} and result.usage.input_tokens == 5


async def test_local_payload_uses_max_tokens_and_temperature() -> None:
    seen, transport = capture({"choices": [{"message": {"content": "{\"ok\": true}"}}]})
    provider = OpenAICompatibleProvider("local", base_url="http://127.0.0.1:11434/v1", api_key=None, local=True,
                                        transport=transport)
    await provider.generate(request_with_image())
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 2000 and body["temperature"] == 0.2 and "max_completion_tokens" not in body
    assert provider.data_leaves_machine is False


async def test_azure_v1_and_classic_urls() -> None:
    seen, transport = capture({"choices": [{"message": {"content": "{\"ok\": true}"}}]})
    v1 = AzureOpenAIProvider("azure", endpoint="https://res.openai.azure.com", api_key="k-123456", api_version=None,
                             transport=transport)
    await v1.generate(request_with_image())
    assert str(seen[0].url) == "https://res.openai.azure.com/openai/v1/chat/completions"
    assert seen[0].headers["api-key"] == "k-123456" and "authorization" not in seen[0].headers
    classic = AzureOpenAIProvider("azure", endpoint="https://res.openai.azure.com", api_key="k-123456",
                                  api_version="2024-10-21", transport=transport)
    await classic.generate(request_with_image())
    assert "/openai/deployments/m/chat/completions?api-version=2024-10-21" in str(seen[1].url)


async def test_anthropic_payload_and_legacy_fallback() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "output_config" in body and body["model"] == "old-model":
            return httpx.Response(400, json={"error": {"message": "output_config: not supported"}})
        if "tools" in body:
            return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "svar", "input": {"ok": True}}],
                                             "stop_reason": "tool_use", "usage": {}})
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": ""},
                                                     {"type": "text", "text": "{\"ok\": true}"}],
                                         "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 1}})

    provider = AnthropicProvider("anthropic", api_key="sk-ant-test-123456789", transport=httpx.MockTransport(handler))
    result = await provider.generate(request_with_image())
    body = json.loads(seen[0].content)
    assert body["output_config"]["format"]["type"] == "json_schema" and "temperature" not in body
    assert body["max_tokens"] > 2000, "headroom for adaptive thinking"
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert result.data == {"ok": True}
    legacy = await provider.generate(request_with_image().model_copy(update={"model": "old-model"}))
    assert legacy.data == {"ok": True}


# ---------------------------------------------------------------- service, privacy, secrets


def configure(client: TestClient, provider: str = "openai", key: str = "sk-proj-testkey1234567890") -> None:
    assert client.put(f"/api/ai/providers/{provider}", json={"enabled": True, "api_key": key}).status_code == 200


def test_no_ai_configured_core_still_works(canvas_client: TestClient) -> None:
    providers = canvas_client.get("/api/ai/providers").json()
    assert "Ingen KI-leverandør" in providers["unavailable_reason"]
    job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    assert wait_for_job(canvas_client, job["id"])["status"] == "completed"


def test_api_keys_are_never_returned(canvas_client: TestClient) -> None:
    configure(canvas_client)
    body = canvas_client.get("/api/ai/providers").text
    assert "sk-proj-testkey1234567890" not in body and '"key_configured":true' in body.replace(" ", "")
    container = canvas_client.app.state.container  # type: ignore[attr-defined]
    assert container.secrets.get("ai_key:openai") == "sk-proj-testkey1234567890"
    assert "sk-proj" not in json.dumps(container.settings.get().model_dump(mode="json"))


def test_reason_says_what_is_missing(canvas_client: TestClient) -> None:
    """«Ingen KI-leverandør er satt opp» was shown although keys were stored – the providers were only switched off."""
    container = canvas_client.app.state.container  # type: ignore[attr-defined]
    assert "Ingen KI-leverandør er slått på i EmneKlar" in canvas_client.get("/api/ai/providers").json()["unavailable_reason"]
    container.secrets.set("ai_key:openai", "sk-proj-testkey1234567890")
    container.secrets.set("ai_key:anthropic", "sk-ant-testkey1234567890")
    reason = canvas_client.get("/api/ai/providers").json()["unavailable_reason"]
    assert reason.startswith("OpenAI og Anthropic har lagret nøkkel, men er ikke slått på"), reason
    assert "Sikkerhet og personvern" in reason, "the privacy setting is named in the same message"
    container.settings.update(lambda s: setattr(next(p for p in s.ai.providers if p.id == "azure"), "enabled", True))
    assert "Azure OpenAI er slått på, men mangler nøkkel eller endepunkt" in \
        canvas_client.get("/api/ai/providers").json()["unavailable_reason"]


def test_saving_a_key_switches_the_provider_on(canvas_client: TestClient) -> None:
    assert canvas_client.put("/api/ai/providers/anthropic", json={"api_key": "sk-ant-testkey1234567890"}).json()["enabled"]
    reason = canvas_client.get("/api/ai/providers").json()["unavailable_reason"]
    assert "ekstern KI er slått av" in reason, "sending to external AI still needs its own setting"
    off = canvas_client.put("/api/ai/providers/anthropic", json={"enabled": False}).json()
    assert off["enabled"] is False, "the switch still turns it off"


def test_external_ai_is_off_until_enabled(canvas_client: TestClient) -> None:
    configure(canvas_client)
    reason = canvas_client.get("/api/ai/providers").json()["unavailable_reason"]
    assert "ekstern KI er slått av" in reason
    canvas_client.app.state.container.settings.update(  # type: ignore[attr-defined]
        lambda s: setattr(s.privacy, "allow_external_ai", True))
    assert canvas_client.get("/api/ai/providers").json()["unavailable_reason"] is None


def test_local_model_allowed_without_external_sharing(canvas_client: TestClient) -> None:
    container = canvas_client.app.state.container  # type: ignore[attr-defined]
    canvas_client.put("/api/ai/providers/local", json={"enabled": True})
    container.ai.registry.add("local", "llama-lokal", {"quality_class": 2, "speed_class": 2, "cost_class": 0,
                                                       "vision": True, "structured_output": True, "context_class": 2})
    decision = canvas_client.get("/api/ai/routing").json()
    alt = next(t for t in decision["tasks"] if t["key"] == "alt_text")
    assert alt["decision"]["primary"]["model_id"] == "llama-lokal"


def test_external_endpoint_must_use_https(canvas_client: TestClient) -> None:
    bad = canvas_client.put("/api/ai/providers/openai", json={"endpoint": "http://api.example.org/v1"})
    assert bad.status_code == 400
    ok = canvas_client.put("/api/ai/providers/local", json={"endpoint": "http://localhost:1234/v1"})
    assert ok.status_code == 200


def ai_transport(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


def test_alt_text_suggestion_with_consent_and_fallback(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "api.openai.com":
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(
            {"alt_text": "Diagram som sammenligner raster- og vektorgrafikk", "decorative": False,
             "confidence": "medium", "notes": ""})}], "stop_reason": "end_turn", "usage": {}})

    canvas_container.ai_transport = ai_transport(handler)
    configure(canvas_client, "openai")
    configure(canvas_client, "anthropic", "sk-ant-api-test-1234567890")
    canvas_container.settings.update(lambda s: setattr(s.privacy, "allow_external_ai", True))
    # Make the OpenAI model the first choice so the fallback is exercised.
    canvas_container.settings.update(lambda s: s.ai.task_providers.update({"alt_text": "openai"}))
    job = canvas_client.post("/api/analysis", json={"course_id": COURSE_ID, "domains": ["accessibility"]}).json()
    wait_for_job(canvas_client, job["id"])
    finding = next(f for f in canvas_client.get(f"/api/courses/{COURSE_ID}/findings?domain=accessibility&page_size=200")
                   .json()["items"] if f["rule_id"] == "UU-IMG-MISSING-ALT")
    plan = canvas_client.post("/api/ai/tasks/alt-text/prepare", json={"finding_id": finding["id"]}).json()
    assert plan["available"] and plan["needs_confirmation"] and "Ingen studentdata" in plan["payload_summary"]
    refused = canvas_client.post("/api/ai/tasks/alt-text", json={"finding_id": finding["id"], "confirmed": False})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ai_consent_required"
    assert calls == [], "nothing is sent before consent"
    ok = canvas_client.post("/api/ai/tasks/alt-text", json={"finding_id": finding["id"], "confirmed": True})
    assert ok.status_code == 200, ok.text
    answer = ok.json()
    assert answer["label"] == "KI-forslag – må vurderes" and "raster" in answer["suggestion"]
    assert "api.openai.com" in calls and "api.anthropic.com" in calls, "falls back to the next model"
    usage = canvas_client.get("/api/ai/usage").json()["items"]
    assert any(u["fallback_used"] and u["success"] for u in usage)
    assert all("Diagram" not in json.dumps(u) for u in usage), "usage log holds metadata only"


@pytest.mark.parametrize("task", ["text_simple", "alt_text", "quiz_generation", "course_structure"])
def test_routing_endpoint_explains_decisions(canvas_client: TestClient, task: str) -> None:
    configure(canvas_client, "anthropic", "sk-ant-api-test-1234567890")
    canvas_client.app.state.container.settings.update(  # type: ignore[attr-defined]
        lambda s: setattr(s.privacy, "allow_external_ai", True))
    tasks = {t["key"]: t for t in canvas_client.get("/api/ai/routing").json()["tasks"]}
    assert tasks[task]["decision"]["primary"] is not None
    assert tasks[task]["decision"]["reason"]


def test_fallbacks_include_another_provider_when_one_provider_has_many_models() -> None:
    many = [model("openai", f"o{i}", q=3, c=1 + i % 2) for i in range(5)] + [model("anthropic", "a1", q=3, c=3)]
    decision = route("text_standard", settings(), many, READY)
    assert decision.primary["provider_id"] == "openai"
    assert any(m["provider_id"] == "anthropic" for m in decision.fallbacks), "an outage at one provider is survivable"


# ---------------------------------------------------------------- «Koble til» (Innstillinger → KI-assistenter)

OPENAI_KEY = "sk-proj-connecttest1234567890"
NEW_KEY = "sk-proj-anotherkey0987654321"


def models_handler(seen: list[httpx.Request], *, status: int = 200, body: object = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json=body or {"error": {"message": "Incorrect API key provided: "
                                                                             "sk-proj-********************4321."}})
        return httpx.Response(200, json={"data": [{"id": "gpt-test-a"}, {"id": "gpt-test-b"}]})

    return handler


def test_connect_checks_the_key_then_stores_it_and_caches_the_model_list(canvas_container,  # type: ignore[no-untyped-def]
                                                                         canvas_client: TestClient) -> None:
    seen: list[httpx.Request] = []
    canvas_container.ai_transport = ai_transport(models_handler(seen))
    response = canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": f"  {OPENAI_KEY}\n"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["key_configured"] and body["enabled"] and body["last_status"] == "ok"
    assert body["last_message"] == "Tilkoblet.", "no model count on the card"
    assert body["key_page"] == "https://platform.openai.com/api-keys" and body["models_stale"] is False
    assert OPENAI_KEY not in response.text
    assert [r.url.path for r in seen] == ["/v1/models"] and seen[0].headers["authorization"] == f"Bearer {OPENAI_KEY}"
    assert canvas_container.secrets.get("ai_key:openai") == OPENAI_KEY, "stored trimmed, only after the check"
    models = {m["model_id"] for m in canvas_client.get("/api/ai/models").json()["models"] if m["provider_id"] == "openai"}
    assert {"gpt-test-a", "gpt-test-b"} <= models, "the model list from the check is cached"
    anthropic = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "anthropic")
    assert anthropic["key_page"] == "https://platform.claude.com/settings/keys"


def test_a_rejected_key_is_not_stored_and_the_old_key_is_kept(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []
    canvas_container.ai_transport = ai_transport(models_handler(seen))
    assert canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": OPENAI_KEY}).status_code == 200
    canvas_container.ai_transport = ai_transport(models_handler(seen, status=401))
    response = canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": NEW_KEY})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "ai_key_invalid"
    assert error["message"].startswith("OpenAI avviste nøkkelen.") and error["message"].endswith(
        "Den lagrede nøkkelen er beholdt."), error["message"]
    assert NEW_KEY not in response.text and "4321" not in response.text and "details" not in error, \
        "neither the key nor the provider's answer (which repeats part of it) is shown"
    assert canvas_container.secrets.get("ai_key:openai") == OPENAI_KEY
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert provider["last_status"] == "ok", "the stored key still works – its status is not changed by a failed new key"

    response = canvas_client.post("/api/ai/providers/anthropic/connect",
                                  json={"api_key": "sk-ant-api03-rejected0123456789"})
    assert response.json()["error"]["message"].endswith(
        "Nøkler fra Anthropic starter med «sk-ant-». Nøkkelen er ikke lagret."), response.json()
    assert not canvas_container.secrets.has("ai_key:anthropic")


@pytest.mark.parametrize(("provider", "key", "message"), [
    ("openai", "", "Lim inn API-nøkkelen først."),
    ("openai", "sk-proj-abc def1234567890123",
     "Nøkkelen inneholder mellomrom eller linjeskift. Kopier den på nytt fra OpenAI."),
    ("openai", "sk-ant-api03-abcdefghijklmnop", "Dette er en nøkkel fra Anthropic. Lim den inn under Anthropic."),
    ("anthropic", "sk-proj-abcdefghijklmnopqrst",
     "Dette ser ut som en nøkkel fra OpenAI. Nøkler fra Anthropic starter med «sk-ant-»."),
    ("openai", "sk-kort", "Nøkkelen er for kort til å være en API-nøkkel. Kopier hele nøkkelen fra OpenAI."),
])
def test_obvious_key_mistakes_are_named_before_anything_is_sent(canvas_container, canvas_client: TestClient,  # type: ignore[no-untyped-def]
                                                                provider: str, key: str, message: str) -> None:
    seen: list[httpx.Request] = []
    canvas_container.ai_transport = ai_transport(models_handler(seen))
    response = canvas_client.post(f"/api/ai/providers/{provider}/connect", json={"api_key": key})
    assert response.status_code == 422 and response.json()["error"]["message"] == message
    assert seen == [], "an Anthropic key is never sent to OpenAI (or the other way round)"


@pytest.mark.parametrize(("status", "body", "start"), [
    (429, {"error": {"code": "insufficient_quota"}}, "Kontoen hos OpenAI har ikke mer kreditt"),
    (503, {"error": "overloaded"}, "OpenAI er midlertidig utilgjengelig."),
    (404, {"error": "not found"}, "Endepunktet svarte ikke som OpenAIs API."),
])
def test_provider_failures_are_explained(canvas_container, canvas_client: TestClient, status: int, body: object,  # type: ignore[no-untyped-def]
                                         start: str) -> None:
    canvas_container.ai_transport = ai_transport(models_handler([], status=status, body=body))
    response = canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": OPENAI_KEY})
    assert response.json()["error"]["message"].startswith(start), response.json()
    assert not canvas_container.secrets.has("ai_key:openai")


def test_no_connection_is_explained(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    canvas_container.ai_transport = ai_transport(handler)
    response = canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": OPENAI_KEY})
    assert response.json()["error"]["message"].startswith("Fikk ikke kontakt med OpenAI."), response.json()


def test_checking_the_stored_key_again_and_removing_it(canvas_container, canvas_client: TestClient) -> None:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []
    canvas_container.ai_transport = ai_transport(models_handler(seen))
    canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": OPENAI_KEY})
    canvas_container.ai_transport = ai_transport(models_handler(seen, status=401))
    again = canvas_client.post("/api/ai/providers/openai/connect", json={})
    assert again.status_code == 400
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert provider["last_status"] == "error" and provider["last_message"].startswith("OpenAI avviste nøkkelen.")
    assert canvas_client.delete("/api/ai/providers/openai/key").json() == {"ok": True}
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert not provider["key_configured"] and not provider["enabled"] and provider["last_status"] == "unknown"
    assert provider["last_message"] is None


def test_the_model_list_is_refreshed_in_the_background_when_it_is_old(canvas_container,  # type: ignore[no-untyped-def]
                                                                      canvas_client: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    seen: list[httpx.Request] = []
    canvas_container.ai_transport = ai_transport(models_handler(seen))
    canvas_client.post("/api/ai/providers/openai/connect", json={"api_key": OPENAI_KEY})

    def age(s: AppSettings) -> None:
        provider = s.provider("openai")
        assert provider is not None
        provider.models_fetched_at = datetime.now(UTC) - timedelta(days=2)

    canvas_container.settings.update(age)
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert provider["models_stale"] is True
    assert canvas_client.post("/api/ai/providers/openai/refresh-models").json() == {"refreshed": True, "added": 0}
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert provider["models_stale"] is False
    canvas_container.ai_transport = ai_transport(models_handler(seen, status=401))
    assert canvas_client.post("/api/ai/providers/openai/refresh-models").json()["refreshed"] is False
    provider = next(p for p in canvas_client.get("/api/ai/providers").json()["providers"] if p["id"] == "openai")
    assert provider["last_status"] == "error", "a key the provider no longer accepts shows on the card"
