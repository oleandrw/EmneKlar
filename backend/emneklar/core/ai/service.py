"""AIService – the only way features use AI.

* Builds providers from settings + keys in the OS credential store.
* Privacy gate: external providers are unusable until «Tillat sending av
  emneinnhold til ekstern KI» is on; with «Bekreft før innhold sendes» every
  external call needs explicit consent (the UI shows a payload summary first).
  A local OpenAI-compatible server on 127.0.0.1 never sends data elsewhere and
  is allowed even when external sharing is off.
* Routing + fallback via :mod:`emneklar.core.ai.router`.
* Usage is logged as metadata only (task, model, tokens, summary) – never content.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from emneklar.core.ai.base import (
    AIError,
    AIProvider,
    AIRequest,
    AIResult,
    EmbeddingResult,
    ImageGenerationRequest,
    ImageGenerationResult,
    TranscriptionResult,
)
from emneklar.core.ai.catalog import ModelRegistry
from emneklar.core.ai.providers.anthropic import AnthropicProvider
from emneklar.core.ai.providers.openai_compat import AzureOpenAIProvider, OpenAICompatibleProvider
from emneklar.core.ai.router import TASKS, RouteDecision, estimate_tokens, route
from emneklar.core.auth.secrets import ai_key_name
from emneklar.core.storage.models import AIUsage
from emneklar.core.storage.settings import AppSettings, ProviderConfig

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)
AI_LABEL = "KI-forslag – må vurderes"
MESSAGES_SHARING_OFF = ("Sending av emneinnhold til ekstern KI er slått av. Slå det på under Innstillinger → "
                        "Sikkerhet og personvern, eller bruk en lokal modell.")


def is_local(provider: ProviderConfig) -> bool:
    if provider.type != "openai_compatible":
        return False
    host = (urlsplit(provider.endpoint or "").hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AIService:
    def __init__(self, container: AppContainer) -> None:
        self.c = container
        self.registry = ModelRegistry(container.db)
        self._providers: dict[str, tuple[str, AIProvider]] = {}

    async def aclose(self) -> None:
        for _, provider in self._providers.values():
            await provider.aclose()
        self._providers.clear()

    # -- providers ------------------------------------------------------------------------------

    def key_for(self, provider_id: str) -> str | None:
        return self.c.secrets.get(ai_key_name(provider_id))

    def configured(self, p: ProviderConfig) -> bool:
        if not p.enabled:
            return False
        if p.type == "openai_compatible":
            return bool(p.endpoint)
        if p.type == "azure_openai" and not p.endpoint:
            return False
        return bool(self.key_for(p.id))

    def readiness(self, settings: AppSettings) -> dict[str, bool]:
        """Provider id → may be used now (configured and allowed by privacy settings)."""
        return {p.id: self.configured(p) and (is_local(p) or settings.privacy.allow_external_ai)
                for p in settings.ai.providers}

    def provider(self, config: ProviderConfig) -> AIProvider:
        key = self.key_for(config.id)
        cache_key = f"{config.type}|{config.endpoint}|{config.api_version}|{hash(key)}"
        cached = self._providers.get(config.id)
        if cached and cached[0] == cache_key:
            return cached[1]
        transport = self.c.ai_transport
        provider: AIProvider
        if config.type == "anthropic":
            provider = AnthropicProvider(config.id, api_key=key, base_url=config.endpoint or "https://api.anthropic.com",
                                         transport=transport)
        elif config.type == "azure_openai":
            provider = AzureOpenAIProvider(config.id, endpoint=config.endpoint or "", api_key=key,
                                           api_version=config.api_version, transport=transport)
        elif config.type == "openai":
            provider = OpenAICompatibleProvider(config.id, base_url=config.endpoint or "https://api.openai.com/v1",
                                                api_key=key, local=False, transport=transport)
        else:
            provider = OpenAICompatibleProvider(config.id, base_url=config.endpoint or "http://127.0.0.1:11434/v1",
                                                api_key=key, local=is_local(config), transport=transport)
        if cached:
            self._providers.pop(config.id, None)
        self._providers[config.id] = (cache_key, provider)
        return provider

    # -- planning --------------------------------------------------------------------------------

    def decide(self, task: str, *, input_chars: int = 0, images: int = 0) -> RouteDecision:
        settings = self.c.settings.get()
        models = self.registry.list()
        return route(task, settings, models, self.readiness(settings),
                     input_tokens=estimate_tokens(input_chars, images), needs_vision=images > 0 or None)

    def unavailable_reason(self, settings: AppSettings) -> str | None:
        if not any(p.enabled for p in settings.ai.providers):
            return "Ingen KI-leverandør er satt opp. Gå til Innstillinger → KI-assistenter."
        ready = self.readiness(settings)
        if not any(ready.values()):
            if any(self.configured(p) and not is_local(p) for p in settings.ai.providers) and \
                    not settings.privacy.allow_external_ai:
                return ("Sending av emneinnhold til ekstern KI er slått av. Slå det på under Innstillinger → "
                        "Sikkerhet og personvern, eller bruk en lokal modell.")
            return "Ingen KI-leverandør er klar. Kontroller nøkkel og endepunkt under Innstillinger → KI-assistenter."
        return None

    def plan(self, task: str, *, input_chars: int, images: int, summary: str) -> dict[str, Any]:
        settings = self.c.settings.get()
        reason = self.unavailable_reason(settings)
        decision = self.decide(task, input_chars=input_chars, images=images)
        if reason is None and decision.primary is None:
            reason = decision.reason or "Ingen aktivert modell passer for oppgaven."
        external = False
        if decision.primary is not None:
            provider = settings.provider(decision.primary["provider_id"])
            external = provider is not None and not is_local(provider)
        return {
            "available": reason is None,
            "reason": reason,
            "payload_summary": summary,
            "external": external,
            "needs_confirmation": external and settings.privacy.confirm_before_send,
            "route": None if decision.primary is None else {
                "provider": decision.primary["provider_id"], "model": decision.primary["display_name"],
                "reason": decision.reason},
        }

    # -- running ---------------------------------------------------------------------------------------

    async def run(
        self,
        task: str,
        build: Callable[[str], AIRequest],
        *,
        input_chars: int,
        images: int = 0,
        summary: str,
        confirmed: bool,
        course_id: str | None = None,
        preferred: list[dict[str, Any]] | None = None,
        preferred_reason: str | None = None,
    ) -> tuple[AIResult, RouteDecision]:
        """Run a task. ``preferred`` (registry models, already checked as usable – e.g. from a quality profile) are
        tried first, then the router's choice and fallbacks. The privacy gate and usage log apply to all of them."""
        if task not in TASKS:
            raise AIError("validation_error", detail=f"Ukjent oppgavetype {task}")
        settings = self.c.settings.get()
        reason = self.unavailable_reason(settings)
        if reason:
            raise AIError("ai_not_configured", status=409, message=reason)
        decision = self.decide(task, input_chars=input_chars, images=images)
        candidates = [m for m in [decision.primary, *decision.fallbacks] if m is not None]
        if preferred:
            keys = {(m["provider_id"], m["model_id"]) for m in preferred}
            candidates = list(preferred) + [m for m in candidates if (m["provider_id"], m["model_id"]) not in keys]
            decision = RouteDecision(task=task, strategy=decision.strategy, primary=candidates[0],
                                     fallbacks=candidates[1:4], reason=preferred_reason or decision.reason,
                                     required_quality=decision.required_quality, min_context=decision.min_context,
                                     excluded=decision.excluded)
        if not candidates:
            raise AIError("ai_no_model", status=409, detail=decision.reason)
        last: AIError | None = None
        for index, model in enumerate(candidates):
            provider_config = settings.provider(model["provider_id"])
            if provider_config is None:
                continue
            external = not is_local(provider_config)
            if external and not settings.privacy.allow_external_ai:
                continue
            if external and settings.privacy.confirm_before_send and not confirmed:
                raise AIError("ai_consent_required", status=409)
            try:
                result = await self.provider(provider_config).generate(build(model["model_id"]))
            except AIError as exc:
                last = exc
                self._log(task, model, settings, decision, fallback=index > 0, success=False, error=exc.code,
                          summary=summary, course_id=course_id)
                log.info("KI-kall feilet (%s/%s): %s", model["provider_id"], model["model_id"], exc.code)
                if exc.code in ("ai_refused", "ai_consent_required"):
                    raise
                continue
            self._log(task, model, settings, decision, fallback=index > 0, success=True, result=result,
                      summary=summary, course_id=course_id)
            if index > 0:
                decision.reason += f" Reservemodell brukt: {model['display_name']}."
            return result, decision
        raise AIError("ai_all_failed", status=502, detail=last.message if last else None)

    # -- embeddings (Emne-RAG with a provider instead of a local model) ---------------------------------

    def embedding_plan(self, provider_id: str, model: str, *, summary: str) -> dict[str, Any]:
        """Like :meth:`plan`, for an embeddings endpoint chosen in the Emne-RAG settings (not by the router)."""
        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        reason: str | None = None
        if config is None or not self.configured(config):
            reason = "Leverandøren som er valgt for embedding, er ikke satt opp. Se Innstillinger → KI-assistenter."
        elif config.type == "anthropic":
            reason = "Anthropic tilbyr ikke embedding. Velg en OpenAI-kompatibel leverandør eller lokale modeller."
        elif not model:
            reason = "Ingen embedding-modell er valgt for leverandøren."
        elif not is_local(config) and not settings.privacy.allow_external_ai:
            reason = MESSAGES_SHARING_OFF
        external = config is not None and not is_local(config)
        return {"available": reason is None, "reason": reason, "payload_summary": summary, "external": external,
                "needs_confirmation": external and settings.privacy.confirm_before_send,
                "route": None if config is None else {"provider": config.id, "model": model,
                                                      "reason": "Valgt under Emnets kunnskapsbase → Innstillinger."}}

    async def embed(self, provider_id: str, model: str, texts: list[str], *, summary: str, confirmed: bool,
                    course_id: str | None = None) -> EmbeddingResult:
        plan = self.embedding_plan(provider_id, model, summary=summary)
        if not plan["available"]:
            raise AIError("ai_not_configured", status=409, message=plan["reason"])
        if plan["needs_confirmation"] and not confirmed:
            raise AIError("ai_consent_required", status=409)
        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        assert config is not None
        try:
            result = await self.provider(config).embed(model, texts)
        except AIError as exc:
            self._log_embedding(provider_id, model, settings, success=False, error=exc.code, tokens=0,
                                summary=summary, course_id=course_id)
            raise
        self._log_embedding(provider_id, model, settings, success=True, error=None, tokens=result.input_tokens,
                            summary=summary, course_id=course_id)
        return result

    # -- transcription (Emne-RAG, when a video has no captions and local transcription is not used) -----------

    def transcription_plan(self, provider_id: str, model_id: str, *, summary: str) -> dict[str, Any]:
        from emneklar.core.ai.transcription import resolve

        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        model = resolve(config.type, model_id) if config is not None else None
        reason: str | None = None
        if config is None or not self.configured(config):
            reason = ("Leverandøren som er valgt for transkripsjon, er ikke satt opp. Se Innstillinger → "
                      "KI-assistenter.")
        elif config.type == "anthropic":
            reason = "Anthropic tilbyr ikke transkripsjon. Velg OpenAI, Azure OpenAI eller en egen server."
        elif model is None:
            reason = "Ingen transkripsjonsmodell er valgt for leverandøren (Emnets kunnskapsbase → Innstillinger)."
        elif not is_local(config) and not settings.privacy.allow_external_ai:
            reason = MESSAGES_SHARING_OFF
        external = config is not None and not is_local(config)
        return {"available": reason is None, "reason": reason, "payload_summary": summary, "external": external,
                "needs_confirmation": external and settings.privacy.confirm_before_send,
                "model": model.as_dict() if model else None,
                "route": None if config is None or model is None else {
                    "provider": config.id, "model": model.id, "reason": "Valgt under Emnets kunnskapsbase → Innstillinger."}}

    async def transcribe(self, provider_id: str, model_id: str, audio: bytes, filename: str, *, segments: bool,
                         summary: str, confirmed: bool, seconds: float, language: str | None = None,
                         prompt: str | None = None, course_id: str | None = None) -> TranscriptionResult:
        plan = self.transcription_plan(provider_id, model_id, summary=summary)
        if not plan["available"]:
            raise AIError("ai_not_configured", status=409, message=plan["reason"])
        if plan["needs_confirmation"] and not confirmed:
            raise AIError("ai_consent_required", status=409)
        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        assert config is not None and plan["model"] is not None
        model = str(plan["model"]["id"])
        try:
            result = await self.provider(config).transcribe(model, audio, filename, segments=segments,
                                                            language=language, prompt=prompt)
        except AIError as exc:
            self._log_usage("rag_transcription", provider_id, model, settings, success=False, error=exc.code,
                            tokens=0, summary=summary, course_id=course_id)
            raise
        self._log_usage("rag_transcription", provider_id, model, settings, success=True, error=None, tokens=0,
                        summary=f"{summary} ({round(seconds)} s lyd)", course_id=course_id)
        return result

    def _log_embedding(self, provider_id: str, model: str, settings: AppSettings, *, success: bool, error: str | None,
                       tokens: int, summary: str, course_id: str | None) -> None:
        self._log_usage("rag_embedding", provider_id, model, settings, success=success, error=error, tokens=tokens,
                        summary=summary, course_id=course_id)

    def _log_usage(self, task: str, provider_id: str, model: str, settings: AppSettings, *, success: bool,
                   error: str | None, tokens: int, summary: str, course_id: str | None, output_tokens: int = 0,
                   reason: str = "Valgt under Emnets kunnskapsbase → Innstillinger.") -> None:
        with self.c.db.session() as session:
            session.add(AIUsage(course_id=course_id, task_type=task, provider_id=provider_id, model_id=model,
                                strategy=settings.ai.strategy, reason=reason,
                                fallback_used=False, success=success, error_code=error, input_tokens=tokens,
                                output_tokens=output_tokens, payload_summary={"summary": summary}))

    # -- image generation (KI-bildeassistent; the model is chosen by a quality profile or the user) ------------

    def image_plan(self, provider_id: str, model_id: str, *, summary: str) -> dict[str, Any]:
        from emneklar.core.ai.images import resolve

        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        model = resolve(config.type, model_id) if config is not None else None
        reason: str | None = None
        if config is None or not self.configured(config):
            reason = "Leverandøren som er valgt for bildegenerering, er ikke satt opp. Se Innstillinger → KI-assistenter."
        elif config.type == "anthropic":
            reason = ("Anthropic-modeller kan analysere bilder, men ikke lage dem. Velg OpenAI, Azure OpenAI eller en "
                      "egen OpenAI-kompatibel server for bildegenerering.")
        elif model is None:
            reason = "Ingen bildemodell er valgt for leverandøren."
        elif not is_local(config) and not settings.privacy.allow_external_ai:
            reason = MESSAGES_SHARING_OFF
        external = config is not None and not is_local(config)
        return {"available": reason is None, "reason": reason, "payload_summary": summary, "external": external,
                "needs_confirmation": external and settings.privacy.confirm_before_send,
                "model": model.as_dict() if model else None,
                "route": None if config is None or model is None else {
                    "provider": config.id, "model": model.label, "reason": "Valgt i KI-bildeassistenten."}}

    async def generate_image(self, provider_id: str, model_id: str, request: ImageGenerationRequest, *, summary: str,
                             confirmed: bool, course_id: str | None = None, task: str = "illustration_image",
                             reason: str = "Valgt i KI-bildeassistenten.") -> ImageGenerationResult:
        plan = self.image_plan(provider_id, model_id, summary=summary)
        if not plan["available"]:
            raise AIError("ai_not_configured", status=409, message=plan["reason"])
        if plan["needs_confirmation"] and not confirmed:
            raise AIError("ai_consent_required", status=409)
        settings = self.c.settings.get()
        config = settings.provider(provider_id)
        assert config is not None and plan["model"] is not None
        model = str(plan["model"]["id"])
        try:
            result = await self.provider(config).generate_image(request.model_copy(update={"model": model}))
        except AIError as exc:
            self._log_usage(task, provider_id, model, settings, success=False, error=exc.code, tokens=0,
                            summary=summary, course_id=course_id, reason=reason)
            raise
        self._log_usage(task, provider_id, model, settings, success=True, error=None,
                        tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens, summary=summary,
                        course_id=course_id, reason=reason)
        return result

    def _log(self, task: str, model: dict[str, Any], settings: AppSettings, decision: RouteDecision, *,
             fallback: bool, success: bool, summary: str, course_id: str | None, error: str | None = None,
             result: AIResult | None = None) -> None:
        with self.c.db.session() as session:
            session.add(AIUsage(course_id=course_id, task_type=task, provider_id=model["provider_id"],
                                model_id=model["model_id"], strategy=settings.ai.strategy, reason=decision.reason,
                                fallback_used=fallback, success=success, error_code=error,
                                input_tokens=result.usage.input_tokens if result else 0,
                                output_tokens=result.usage.output_tokens if result else 0,
                                payload_summary={"summary": summary}))
