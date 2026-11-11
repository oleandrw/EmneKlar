"""Provider abstraction for language models.

Nothing outside ``core.ai`` knows which vendor is used. A provider receives a
fully built request (system text + user parts + optional JSON schema) and
returns parsed JSON (or text) plus token usage. Models never get tools: the
"structured output" is only a response schema, so a model cannot trigger any
action in EmneKlar. Providers only ever see their own API key.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from emneklar.core.errors import AppError


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    # Mark the end of a long, repeated prefix (e.g. one document sent with many chunks) as cacheable.
    # Anthropic gets an explicit cache breakpoint; OpenAI caches long identical prefixes automatically.
    cache: bool = False


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    media_type: str
    data_b64: str

    @classmethod
    def from_bytes(cls, data: bytes, media_type: str) -> ImagePart:
        return cls(media_type=media_type, data_b64=base64.b64encode(data).decode("ascii"))


class AIMessage(BaseModel):
    role: Literal["user", "assistant"] = "user"
    parts: list[TextPart | ImagePart]


class AIRequest(BaseModel):
    model: str
    system: str
    messages: list[AIMessage]
    schema_name: str = "svar"
    json_schema: dict[str, Any] | None = None
    max_output_tokens: int = 2000


class AIUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    input_tokens: int = 0
    model: str
    provider: str


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    text: str
    segments: list[TranscriptionSegment] = Field(default_factory=list)  # empty when the model gives no timestamps
    language: str | None = None
    duration: float | None = None
    model: str
    provider: str


class AIResult(BaseModel):
    data: dict[str, Any] | None = None
    text: str | None = None
    usage: AIUsage = Field(default_factory=AIUsage)
    model: str
    provider: str


class ImageGenerationRequest(BaseModel):
    """One image from a text prompt, optionally guided by reference images (style references).

    Only parameters that are common to image APIs are modelled; providers map them to their own names and drop what
    they do not support. Image models never get tools either."""

    model: str
    prompt: str
    size: str = "1536x1024"
    quality: str = "high"
    output_format: Literal["png", "webp", "jpeg"] = "png"
    background: Literal["opaque", "transparent", "auto"] = "opaque"
    reference_images: list[ImagePart] = Field(default_factory=list)
    input_fidelity: Literal["low", "high"] | None = None


class GeneratedImage(BaseModel):
    data: bytes
    media_type: str
    revised_prompt: str | None = None


class ImageUsage(BaseModel):
    """Usage as reported by the provider. ``reported`` is False when the provider returned no usage data."""

    input_tokens: int = 0
    input_image_tokens: int = 0
    output_tokens: int = 0
    reported: bool = False


class ImageGenerationResult(BaseModel):
    images: list[GeneratedImage]
    usage: ImageUsage = Field(default_factory=ImageUsage)
    model: str
    provider: str


class DiscoveredModel(BaseModel):
    id: str
    name: str
    vision: bool | None = None
    structured_output: bool | None = None
    context_tokens: int | None = None


class HealthStatus(BaseModel):
    ok: bool
    message: str
    detail: str | None = None


class AIError(AppError):
    pass


class SearchHit(BaseModel):
    """One result from a provider's web search – exactly as the search returned it (never written by the model)."""

    url: str
    title: str = ""
    page_age: str | None = None


class AIProvider(ABC):
    provider_id: str
    type: str
    data_leaves_machine: bool = True

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResult: ...

    @abstractmethod
    async def list_models(self) -> list[DiscoveredModel]: ...

    async def embed(self, model: str, texts: list[str]) -> EmbeddingResult:
        """Text embeddings. Only OpenAI-compatible APIs (OpenAI, Azure OpenAI, Ollama, LM Studio …) have them."""
        raise AIError("unsupported", status=409, message="Denne KI-leverandøren tilbyr ikke embedding.")

    async def transcribe(self, model: str, audio: bytes, filename: str, *, segments: bool, language: str | None = None,
                         prompt: str | None = None) -> TranscriptionResult:
        """Speech to text. Only OpenAI-compatible APIs (OpenAI, Azure OpenAI, own servers) have it."""
        raise AIError("unsupported", status=409, message="Denne KI-leverandøren tilbyr ikke transkripsjon.")

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        """Image generation. Only OpenAI-compatible image APIs have it – Anthropic models analyse images but do not
        generate them."""
        raise AIError("unsupported", status=409, message="Denne KI-leverandøren kan ikke lage bilder.")

    async def web_search(self, model: str, query: str, *, max_uses: int = 2) -> list[SearchHit]:
        """Web search through the provider's own search tool. Only the Anthropic Messages API (``web_search``) and the
        OpenAI Responses API (``web_search``) have it."""
        raise AIError("unsupported", status=409, message="Denne KI-leverandøren kan ikke søke på nettet.")

    async def health_check(self) -> HealthStatus:
        try:
            models = await self.list_models()
        except AIError as exc:
            return HealthStatus(ok=False, message=exc.message, detail=exc.detail)
        return HealthStatus(ok=True, message=f"Tilkoblet. {len(models)} modeller tilgjengelig.")

    async def aclose(self) -> None:
        return None


def status_to_error(status: int, body: str) -> AIError:
    snippet = body[:300]
    lowered = snippet.lower()
    if status in (401, 403):
        return AIError("ai_key_invalid", status=502, detail=f"HTTP {status}: {snippet}")
    if status == 404:
        return AIError("ai_model_missing", status=502, detail=f"HTTP 404: {snippet}")
    if status == 429:
        if any(code in lowered for code in ("insufficient_quota", "credit_balance", "spend_limit", "usage_limit")):
            return AIError("ai_rate_limited", status=503,
                           detail="Kvoten eller kostnadsgrensen hos leverandøren er brukt opp")
        return AIError("ai_rate_limited", status=503, detail=f"HTTP 429: {snippet}")
    if status == 400 and "content_filter" in lowered:
        return AIError("ai_refused", status=502, detail="Innholdsfilteret hos leverandøren stoppet forespørselen")
    if status >= 500 or status == 529:
        return AIError("ai_unavailable", status=503, detail=f"HTTP {status}: {snippet}")
    return AIError("ai_bad_response", status=502, detail=f"HTTP {status}: {snippet}")
