"""Anthropic Messages API.

* Structured output: ``output_config.format`` (GA JSON-schema response). Newer
  models reject forced tool use, so a forced "tool" is only a fallback for
  models that reject ``output_config``.
* ``temperature`` is not sent (current models only accept the default).
* Current models think adaptively before answering; thinking counts toward
  ``max_tokens``, so the budget gets headroom. Thinking blocks are ignored.
"""

from __future__ import annotations

from typing import Any

import httpx

from emneklar.core.ai.base import (
    AIError,
    AIProvider,
    AIRequest,
    AIResult,
    AIUsage,
    DiscoveredModel,
    ImagePart,
)
from emneklar.core.ai.providers.http_common import get_json, make_client, parse_json_text, post_json, rejects

API_VERSION = "2023-06-01"
THINKING_HEADROOM = 8000
MAX_TOKENS_CAP = 32000
_LEGACY_TOOL_MODELS: set[str] = set()


class AnthropicProvider(AIProvider):
    type = "anthropic"

    def __init__(self, provider_id: str, *, api_key: str | None, base_url: str = "https://api.anthropic.com",
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 180) -> None:
        if not api_key:
            raise AIError("ai_key_missing")
        self.provider_id = provider_id
        self.key = api_key
        self.base = base_url.rstrip("/")
        self.client = make_client(timeout, transport)

    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    @staticmethod
    def content(parts: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, ImagePart):
                out.append({"type": "image", "source": {"type": "base64", "media_type": part.media_type,
                                                         "data": part.data_b64}})
            else:
                out.append({"type": "text", "text": part.text})
        return out

    def payload(self, request: AIRequest, *, legacy_tool: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": min(MAX_TOKENS_CAP, request.max_output_tokens + THINKING_HEADROOM),
            "system": request.system,
            "messages": [{"role": m.role, "content": self.content(m.parts)} for m in request.messages],
        }
        if request.json_schema is not None:
            if legacy_tool:
                payload["tools"] = [{"name": request.schema_name, "description": "Returner svaret i dette formatet.",
                                     "input_schema": request.json_schema}]
                payload["tool_choice"] = {"type": "tool", "name": request.schema_name}
            else:
                payload["output_config"] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        return payload

    async def generate(self, request: AIRequest) -> AIResult:
        if not request.model:
            raise AIError("ai_model_missing")
        legacy = request.model in _LEGACY_TOOL_MODELS
        try:
            data = await post_json(self.client, f"{self.base}/v1/messages", self.payload(request, legacy_tool=legacy),
                                   self.headers())
        except AIError as exc:
            if request.json_schema is not None and not legacy and rejects(exc, "output_config", "structured"):
                _LEGACY_TOOL_MODELS.add(request.model)
                legacy = True
                data = await post_json(self.client, f"{self.base}/v1/messages",
                                       self.payload(request, legacy_tool=True), self.headers())
            else:
                raise
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise AIError("ai_refused", status=502)
        if stop == "max_tokens":
            raise AIError("ai_bad_response", status=502, detail="Svaret ble avkortet (maks antall tokens)")
        usage = data.get("usage") or {}
        result_usage = AIUsage(input_tokens=int(usage.get("input_tokens") or 0),
                               output_tokens=int(usage.get("output_tokens") or 0))
        blocks = [b for b in data.get("content") or [] if isinstance(b, dict)]
        if request.json_schema is not None and legacy:
            tool = next((b for b in blocks if b.get("type") == "tool_use"), None)
            if tool is None or not isinstance(tool.get("input"), dict):
                raise AIError("ai_bad_response", status=502, detail="Fant ikke strukturert svar")
            return AIResult(data=dict(tool["input"]), usage=result_usage, model=str(data.get("model") or request.model),
                            provider=self.provider_id)
        text = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
        if request.json_schema is not None:
            return AIResult(data=parse_json_text(text), usage=result_usage,
                            model=str(data.get("model") or request.model), provider=self.provider_id)
        return AIResult(text=text, usage=result_usage, model=str(data.get("model") or request.model),
                        provider=self.provider_id)

    async def list_models(self) -> list[DiscoveredModel]:
        data = await get_json(self.client, f"{self.base}/v1/models?limit=1000", self.headers())
        out = []
        for m in (data.get("data") or []) if isinstance(data, dict) else []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            caps = m.get("capabilities") or {}

            def supported(name: str, caps: dict[str, Any] = caps) -> bool | None:
                value = caps.get(name)
                return bool(value.get("supported")) if isinstance(value, dict) and "supported" in value else None

            out.append(DiscoveredModel(id=str(m["id"]), name=str(m.get("display_name") or m["id"]),
                                       vision=supported("image_input"), structured_output=supported("structured_outputs"),
                                       context_tokens=m.get("max_input_tokens")))
        return out

    async def aclose(self) -> None:
        await self.client.aclose()
