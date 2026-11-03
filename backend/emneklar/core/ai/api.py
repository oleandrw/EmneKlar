"""AI providers, model registry, routing and usage (Innstillinger → KI-assistenter)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container
from emneklar.core import flags
from emneklar.core.ai.base import AIError
from emneklar.core.ai.router import STRATEGY_LABEL, TASKS
from emneklar.core.ai.service import is_local
from emneklar.core.auth.secrets import ai_key_name
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.storage.models import AIUsage
from emneklar.core.storage.settings import AppSettings, ProviderConfig

router = APIRouter(prefix="/api/ai")


def provider_dict(c: AppContainer, p: ProviderConfig) -> dict[str, Any]:
    local = is_local(p)
    return {**p.model_dump(mode="json"), "key_configured": c.secrets.has(ai_key_name(p.id)), "local": local,
            "data_leaves_machine": not local, "needs_key": p.type != "openai_compatible"}


def _find(settings: AppSettings, provider_id: str) -> ProviderConfig:
    provider = settings.provider(provider_id)
    if provider is None:
        raise NotFoundError("not_found", detail="leverandør")
    return provider


@router.get("/providers")
async def providers(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    settings = c.settings.get()
    return {"providers": [provider_dict(c, p) for p in settings.ai.providers],
            "privacy": settings.privacy.model_dump(mode="json"),
            "unavailable_reason": c.ai.unavailable_reason(settings)}


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    endpoint: str | None = Field(default=None, max_length=300)
    api_version: str | None = Field(default=None, max_length=40)
    api_key: str | None = Field(default=None, max_length=2000)


def _validate_endpoint(provider: ProviderConfig, endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise AppError("validation_error", message="Ugyldig endepunkt.")
    if parts.scheme == "http":
        probe = provider.model_copy(update={"endpoint": endpoint})
        if not is_local(probe):
            raise AppError("validation_error", message="Eksterne endepunkter må bruke https. Bare lokale servere "
                           "(127.0.0.1/localhost) kan bruke http.")
    return endpoint


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdate,
                          c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    settings = c.settings.get()
    provider = _find(settings, provider_id)
    endpoint = _validate_endpoint(provider, body.endpoint) if body.endpoint else None
    if body.api_key and body.api_key.strip():
        c.secrets.set(ai_key_name(provider_id), body.api_key.strip())

    def mutate(s: AppSettings) -> None:
        p = _find(s, provider_id)
        if body.enabled is not None:
            p.enabled = body.enabled
        if endpoint:
            p.endpoint = endpoint
        if body.api_version is not None:
            p.api_version = body.api_version.strip() or None
        p.last_status = "unknown"

    updated = c.settings.update(mutate)
    return provider_dict(c, _find(updated, provider_id))


@router.delete("/providers/{provider_id}/key")
async def delete_key(provider_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _find(c.settings.get(), provider_id)
    c.secrets.delete(ai_key_name(provider_id))
    return {"ok": True}


def _record_status(c: AppContainer, provider_id: str, ok: bool, message: str) -> None:
    def mutate(s: AppSettings) -> None:
        p = _find(s, provider_id)
        p.last_status = "ok" if ok else "error"
        p.last_message = message[:300]
        p.last_checked_at = datetime.now(UTC)

    c.settings.update(mutate)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    provider = _find(c.settings.get(), provider_id)
    try:
        status = await c.ai.provider(provider).health_check()
    except AIError as exc:
        _record_status(c, provider_id, False, exc.message)
        return {"ok": False, "message": exc.message}
    _record_status(c, provider_id, status.ok, status.message)
    return {"ok": status.ok, "message": status.message, "detail": status.detail}


@router.post("/providers/{provider_id}/discover")
async def discover(provider_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    settings = c.settings.get()
    flags.require(settings, "ai_model_discovery")
    provider = _find(settings, provider_id)
    models = await c.ai.provider(provider).list_models()
    added = c.ai.registry.merge_discovered(provider_id, models, local=is_local(provider))
    note = None
    if provider.type == "azure_openai":
        note = "Azure lar seg ikke liste deployments med API-nøkkel. Legg til deployment-navn manuelt."
    return {"found": len(models), "added": added, "note": note}


@router.get("/models")
async def models(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    from emneklar.core.ai.catalog import load_catalog

    catalog = load_catalog()
    return {"models": c.ai.registry.list(), "catalog_version": catalog["version"], "catalog_note": catalog["note"]}


class ModelBody(BaseModel):
    provider_id: str | None = Field(default=None, max_length=40)
    model_id: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    vision: bool | None = None
    structured_output: bool | None = None
    context_class: int | None = None
    quality_class: int | None = None
    speed_class: int | None = None
    cost_class: int | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


@router.post("/models")
async def add_model(body: ModelBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if not body.provider_id or not body.model_id:
        raise AppError("validation_error", message="Velg leverandør og skriv modell- eller deployment-navn.")
    _find(c.settings.get(), body.provider_id)
    fields = body.model_dump(exclude_none=True, exclude={"provider_id", "model_id"})
    return c.ai.registry.add(body.provider_id, body.model_id, fields)


@router.put("/models/{model_pk}")
async def update_model(model_pk: int, body: ModelBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return c.ai.registry.update(model_pk, body.model_dump(exclude_none=True, exclude={"provider_id", "model_id"}))


@router.delete("/models/{model_pk}")
async def delete_model(model_pk: int, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    c.ai.registry.delete(model_pk)
    return {"ok": True}


@router.get("/routing")
async def routing(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    settings = c.settings.get()
    tasks = []
    for key, task in TASKS.items():
        decision = c.ai.decide(key, input_chars=4000, images=1 if task.vision else 0)
        tasks.append({"key": key, "label": task.label, "description": task.description, "vision": task.vision,
                      "min_quality": task.min_quality, "decision": decision.as_dict(),
                      "manual_model": settings.ai.manual_models.get(key),
                      "preferred_provider": settings.ai.task_providers.get(key)})
    return {"strategy": settings.ai.strategy, "strategies": [{"id": k, "label": v} for k, v in STRATEGY_LABEL.items()],
            "tasks": tasks}


class RoutingBody(BaseModel):
    strategy: str | None = None
    manual_models: dict[str, str] | None = None
    task_providers: dict[str, str] | None = None


@router.put("/routing")
async def update_routing(body: RoutingBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if body.strategy is not None and body.strategy not in STRATEGY_LABEL:
        raise AppError("validation_error", detail="Ukjent strategi")
    for task in list((body.manual_models or {}).keys()) + list((body.task_providers or {}).keys()):
        if task not in TASKS:
            raise AppError("validation_error", detail=f"Ukjent oppgave {task}")

    def mutate(s: AppSettings) -> None:
        if body.strategy is not None:
            s.ai.strategy = body.strategy  # type: ignore[assignment]
        if body.manual_models is not None:
            s.ai.manual_models = {k: v for k, v in body.manual_models.items() if v}
        if body.task_providers is not None:
            s.ai.task_providers = {k: v for k, v in body.task_providers.items() if v}

    c.settings.update(mutate)
    return await routing(c)


@router.get("/usage")
async def usage(limit: int = 50, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    with c.db.session() as session:
        rows = session.scalars(select(AIUsage).order_by(AIUsage.created_at.desc()).limit(min(200, max(1, limit)))).all()
        return {"items": [{"id": r.id, "created_at": r.created_at.isoformat(), "task": r.task_type,
                           "task_label": TASKS[r.task_type].label if r.task_type in TASKS else r.task_type,
                           "provider_id": r.provider_id, "model_id": r.model_id, "strategy": r.strategy,
                           "reason": r.reason, "fallback_used": r.fallback_used, "success": r.success,
                           "error_code": r.error_code, "input_tokens": r.input_tokens,
                           "output_tokens": r.output_tokens, "summary": (r.payload_summary or {}).get("summary")}
                          for r in rows]}
