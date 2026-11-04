"""OpenAI Chat Completions and OpenAI-compatible local servers (Ollama, LM Studio, vLLM).

* Structured output: ``response_format: {type: json_schema, json_schema: {name, schema, strict}}``.
* OpenAI reasoning models reject ``temperature`` → it is never sent to OpenAI.
  Local servers default to temperature 1.0 when it is omitted, so 0.2 is sent.
* Ollama ignores ``max_completion_tokens`` → local servers get ``max_tokens``.
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
    EmbeddingResult,
    ImagePart,
    TranscriptionResult,
    TranscriptionSegment,
)
from emneklar.core.ai.providers.http_common import (
    get_json,
    make_client,
    parse_json_text,
    post_json,
    post_multipart,
    rejects,
)


def chat_messages(request: AIRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
    for message in request.messages:
        content: list[dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, ImagePart):
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{part.media_type};base64,{part.data_b64}"}})
            else:
                content.append({"type": "text", "text": part.text})
        messages.append({"role": message.role, "content": content})
    return messages


def parse_embeddings(data: dict[str, Any], provider: str, model: str, count: int) -> EmbeddingResult:
    rows = [r for r in data.get("data") or [] if isinstance(r, dict) and isinstance(r.get("embedding"), list)]
    if len(rows) != count:
        raise AIError("ai_bad_response", status=502, detail="Feil antall vektorer fra embedding-modellen")
    rows.sort(key=lambda r: int(r.get("index") or 0))
    usage = data.get("usage") or {}
    return EmbeddingResult(vectors=[[float(x) for x in r["embedding"]] for r in rows],
                           input_tokens=int(usage.get("prompt_tokens") or 0), model=str(data.get("model") or model),
                           provider=provider)


def parse_transcription(data: dict[str, Any], provider: str, model: str) -> TranscriptionResult:
    segments = []
    for row in data.get("segments") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        try:
            start, end = float(row.get("start") or 0), float(row.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if text:
            segments.append(TranscriptionSegment(start=start, end=max(start, end), text=text))
    duration = data.get("duration")
    return TranscriptionResult(text=str(data.get("text") or "").strip(), segments=segments,
                               language=data.get("language"), duration=float(duration) if duration else None,
                               model=model, provider=provider)


async def post_transcription(client: httpx.AsyncClient, url: str, headers: dict[str, str], *, model: str, audio: bytes,
                             filename: str, segments: bool, language: str | None, prompt: str | None,
                             provider: str) -> TranscriptionResult:
    """POST …/audio/transcriptions. Without segment support (or when the model rejects it) plain JSON is used."""
    data: dict[str, Any] = {"model": model, "response_format": "verbose_json" if segments else "json"}
    if segments:
        data["timestamp_granularities[]"] = "segment"
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt[:800]
    files = {"file": (filename, audio, "audio/wav")}
    try:
        result = await post_multipart(client, url, data, files, headers)
    except AIError as exc:
        if segments and rejects(exc, "response_format", "verbose_json", "timestamp"):
            return await post_transcription(client, url, headers, model=model, audio=audio, filename=filename,
                                            segments=False, language=language, prompt=prompt, provider=provider)
        if prompt and rejects(exc, "prompt"):
            return await post_transcription(client, url, headers, model=model, audio=audio, filename=filename,
                                            segments=segments, language=language, prompt=None, provider=provider)
        raise
    return parse_transcription(result, provider, model)


def parse_choice(data: dict[str, Any], provider: str, model: str, structured: bool) -> AIResult:
    choices = data.get("choices") or []
    if not choices:
        raise AIError("ai_bad_response", status=502, detail="Ingen svar fra modellen")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise AIError("ai_bad_response", status=502, detail="Svaret ble avkortet (maks antall tokens)")
    if choice.get("finish_reason") == "content_filter":
        raise AIError("ai_refused", status=502, detail="Innholdsfilteret stoppet svaret")
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise AIError("ai_refused", status=502)
    content = message.get("content") or ""
    usage = data.get("usage") or {}
    return AIResult(
        data=parse_json_text(content) if structured else None, text=None if structured else content,
        usage=AIUsage(input_tokens=int(usage.get("prompt_tokens") or 0),
                      output_tokens=int(usage.get("completion_tokens") or 0)),
        model=str(data.get("model") or model), provider=provider)


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, provider_id: str, *, base_url: str, api_key: str | None, local: bool,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 180) -> None:
        self.provider_id = provider_id
        self.type = "openai_compatible" if local else "openai"
        self.base = base_url.rstrip("/")
        self.key = api_key or ""
        self.local = local
        self.data_leaves_machine = not local
        if not local and not self.key:
            raise AIError("ai_key_missing")
        self.client = make_client(timeout if not local else 600, transport)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key or 'lokal'}"}

    def payload(self, request: AIRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": request.model, "messages": chat_messages(request)}
        if self.local:
            payload["max_tokens"] = request.max_output_tokens
            payload["temperature"] = 0.2
        else:
            payload["max_completion_tokens"] = request.max_output_tokens
        if request.json_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": request.schema_name, "schema": request.json_schema, "strict": True}}
        return payload

    async def generate(self, request: AIRequest) -> AIResult:
        if not request.model:
            raise AIError("ai_model_missing")
        payload = self.payload(request)
        try:
            data = await post_json(self.client, f"{self.base}/chat/completions", payload, self.headers())
        except AIError as exc:
            if "temperature" in payload and rejects(exc, "temperature"):
                payload.pop("temperature")
                data = await post_json(self.client, f"{self.base}/chat/completions", payload, self.headers())
            elif "response_format" in payload and rejects(exc, "response_format", "json_schema"):
                # Older local servers: fall back to plain JSON mode and validate ourselves.
                payload["response_format"] = {"type": "json_object"}
                data = await post_json(self.client, f"{self.base}/chat/completions", payload, self.headers())
            else:
                raise
        return parse_choice(data, self.provider_id, request.model, request.json_schema is not None)

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        if not model:
            raise AIError("ai_model_missing")
        data = await post_json(self.client, f"{self.base}/embeddings", {"model": model, "input": texts}, self.headers())
        return parse_embeddings(data, self.provider_id, model, len(texts))

    async def transcribe(self, model: str, audio: bytes, filename: str, *, segments: bool, language: str | None = None,
                         prompt: str | None = None) -> TranscriptionResult:
        if not model:
            raise AIError("ai_model_missing")
        return await post_transcription(self.client, f"{self.base}/audio/transcriptions", self.headers(), model=model,
                                        audio=audio, filename=filename, segments=segments, language=language,
                                        prompt=prompt, provider=self.provider_id)

    async def list_models(self) -> list[DiscoveredModel]:
        data = await get_json(self.client, f"{self.base}/models", self.headers())
        rows = [m for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")] if isinstance(data, dict) \
            else []
        return sorted((DiscoveredModel(id=str(m["id"]), name=str(m["id"])) for m in rows), key=lambda m: m.id)

    async def aclose(self) -> None:
        await self.client.aclose()


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI. ``api_version`` None/"v1" → GA v1 API (model = deployment name); a dated
    version (e.g. 2024-10-21) → classic deployment URL. Deployments cannot be listed with an
    API key, so they are configured as models in the registry."""

    def __init__(self, provider_id: str, *, endpoint: str, api_key: str | None, api_version: str | None,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 180) -> None:
        if not endpoint or not endpoint.startswith("https://"):
            raise AIError("ai_not_configured", detail="Azure-endepunktet må starte med https://")
        super().__init__(provider_id, base_url=endpoint.rstrip("/"), api_key=api_key, local=False, transport=transport,
                         timeout=timeout)
        self.type = "azure_openai"
        self.api_version = (api_version or "v1").strip()

    def headers(self) -> dict[str, str]:
        return {"api-key": self.key}

    def url(self, deployment: str) -> str:
        if self.api_version in ("", "v1"):
            return f"{self.base}/openai/v1/chat/completions"
        from urllib.parse import quote

        return (f"{self.base}/openai/deployments/{quote(deployment, safe='')}/chat/completions"
                f"?api-version={quote(self.api_version, safe='')}")

    async def generate(self, request: AIRequest) -> AIResult:
        if not request.model:
            raise AIError("ai_model_missing")
        payload = self.payload(request)
        data = await post_json(self.client, self.url(request.model), payload, self.headers())
        return parse_choice(data, self.provider_id, request.model, request.json_schema is not None)

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        if not model:
            raise AIError("ai_model_missing")
        url = self.url(model).replace("/chat/completions", "/embeddings")
        data = await post_json(self.client, url, {"model": model, "input": texts}, self.headers())
        return parse_embeddings(data, self.provider_id, model, len(texts))

    async def transcribe(self, model: str, audio: bytes, filename: str, *, segments: bool, language: str | None = None,
                         prompt: str | None = None) -> TranscriptionResult:
        if not model:
            raise AIError("ai_model_missing")
        url = self.url(model).replace("/chat/completions", "/audio/transcriptions")
        return await post_transcription(self.client, url, self.headers(), model=model, audio=audio, filename=filename,
                                        segments=segments, language=language, prompt=prompt, provider=self.provider_id)

    async def list_models(self) -> list[DiscoveredModel]:
        url = f"{self.base}/openai/v1/models" if self.api_version in ("", "v1") else \
            f"{self.base}/openai/models?api-version={self.api_version}"
        await get_json(self.client, url, self.headers())  # proves the key and endpoint work
        return []
