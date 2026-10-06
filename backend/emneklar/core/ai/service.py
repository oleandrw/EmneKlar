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

from emneklar.core.ai.base import AIError, AIProvider, AIRequest, AIResult
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
    ) -> tuple[AIResult, RouteDecision]:
        if task not in TASKS:
            raise AIError("validation_error", detail=f"Ukjent oppgavetype {task}")
        settings = self.c.settings.get()
        reason = self.unavailable_reason(settings)
        if reason:
            raise AIError("ai_not_configured", status=409, message=reason)
        decision = self.decide(task, input_chars=input_chars, images=images)
        candidates = [m for m in [decision.primary, *decision.fallbacks] if m is not None]
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
