"""AI providers, model registry, routing and usage (Innstillinger → KI-assistenter)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container
from emneklar.core import flags
from emneklar.core.ai.base import AIError
from emneklar.core.ai.router import STRATEGY_LABEL, TASKS, USAGE_LABELS
from emneklar.core.ai.service import is_local
from emneklar.core.auth.secrets import ai_key_name
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.security.redaction import register_secret, unregister_secret
from emneklar.core.storage.models import AIUsage
from emneklar.core.storage.settings import AppSettings, ProviderConfig

router = APIRouter(prefix="/api/ai")


#: The provider's own page where the teacher creates or finds an API key (linked next to the key field).
KEY_PAGES = {"openai": "https://platform.openai.com/api-keys",
             "anthropic": "https://platform.claude.com/settings/keys"}
#: How the start of a key from each provider looks (named when a key is rejected or pasted under the wrong provider).
KEY_PREFIXES = {"openai": "sk-", "anthropic": "sk-ant-"}
#: The model list is fetched again in the background when it is older than this.
MODEL_REFRESH = timedelta(hours=24)


def provider_dict(c: AppContainer, p: ProviderConfig) -> dict[str, Any]:
    local = is_local(p)
    key_configured = c.secrets.has(ai_key_name(p.id))
    fetched = p.models_fetched_at
    stale = p.enabled and key_configured and p.type in KEY_PAGES and (
        fetched is None or datetime.now(UTC) - fetched > MODEL_REFRESH)
    return {**p.model_dump(mode="json"), "key_configured": key_configured, "local": local,
            "data_leaves_machine": not local, "needs_key": p.type != "openai_compatible",
            "key_page": KEY_PAGES.get(p.type), "models_stale": stale}


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
    new_key = bool(body.api_key and body.api_key.strip())
    if new_key:
        c.secrets.set(ai_key_name(provider_id), (body.api_key or "").strip())

    def mutate(s: AppSettings) -> None:
        p = _find(s, provider_id)
        if body.enabled is not None:
            p.enabled = body.enabled
        elif new_key:
            # Saving a key means «use this provider» – the switch is turned on with it (it can be turned off again).
            # Sending course content to external AI still needs its own privacy setting.
            p.enabled = True
        changed = new_key
        if endpoint and endpoint != p.endpoint:
            p.endpoint = endpoint
            changed = True
        if body.api_version is not None and (body.api_version.strip() or None) != p.api_version:
            p.api_version = body.api_version.strip() or None
            changed = True
        if changed:
            # Only a new key, endpoint or version makes the last check out of date – not the on/off switch.
            p.last_status = "unknown"
            p.last_message = None

    updated = c.settings.update(mutate)
    return provider_dict(c, _find(updated, provider_id))


@router.delete("/providers/{provider_id}/key")
async def delete_key(provider_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _find(c.settings.get(), provider_id)
    c.secrets.delete(ai_key_name(provider_id))

    def mutate(s: AppSettings) -> None:
        # Without a key the provider cannot be used: switched off, and no old status that says «Tilkoblet».
        p = _find(s, provider_id)
        if p.type != "openai_compatible":
            p.enabled = False
        p.last_status = "unknown"
        p.last_message = None
        p.last_checked_at = None

    c.settings.update(mutate)
    return {"ok": True}


# -- «Koble til»: check a key with the provider before it is stored ----------------------------------------------------



class ConnectBody(BaseModel):
    #: A new key to check and store. None = check the stored key again («Kontroller tilkoblingen»).
    api_key: str | None = Field(default=None, max_length=2000)


def key_problem(provider: ProviderConfig, key: str) -> str | None:
    """A concrete reason a pasted key cannot be right – found before anything is sent (and before a key from one
    provider is sent to the other). The key itself is never part of the message."""
    name = provider.name
    if not key:
        return "Lim inn API-nøkkelen først."
    if any(ch.isspace() for ch in key):
        return f"Nøkkelen inneholder mellomrom eller linjeskift. Kopier den på nytt fra {name}."
    if not key.isascii() or not key.isprintable():
        return f"Nøkkelen inneholder tegn som ikke finnes i en API-nøkkel. Kopier den på nytt fra {name}."
    if provider.type == "openai" and key.startswith("sk-ant-"):
        return "Dette er en nøkkel fra Anthropic. Lim den inn under Anthropic."
    if provider.type == "anthropic" and key.startswith("sk-") and not key.startswith("sk-ant-"):
        return "Dette ser ut som en nøkkel fra OpenAI. Nøkler fra Anthropic starter med «sk-ant-»."
    if len(key) < 20:
        return f"Nøkkelen er for kort til å være en API-nøkkel. Kopier hele nøkkelen fra {name}."
    return None


def connect_message(provider: ProviderConfig, exc: AIError) -> str:
    """What went wrong when the provider was asked, in words the teacher can act on. Never the key, and never the
    provider's raw response (it may repeat part of the key)."""
    name = provider.name
    detail = (exc.detail or "").lower()
    if exc.code == "ai_key_invalid":
        prefix = KEY_PREFIXES.get(provider.type)
        return (f"{name} avviste nøkkelen. Kontroller at hele nøkkelen er kopiert, og at den ikke er slettet eller "
                f"utløpt hos {name}." + (f" Nøkler fra {name} starter med «{prefix}»." if prefix else ""))
    if exc.code == "ai_key_missing":
        return "Lim inn API-nøkkelen først."
    if exc.code == "ai_rate_limited":
        if "kvoten" in detail or "kostnadsgrensen" in detail:
            return (f"Kontoen hos {name} har ikke mer kreditt, eller kostnadsgrensen er nådd. Legg inn betaling eller "
                    f"øk grensen hos {name}, og prøv igjen.")
        return f"{name} ber EmneKlar vente litt (for mange forespørsler). Prøv igjen om et minutt."
    if exc.code == "ai_timeout":
        return f"{name} svarte ikke i tide. Kontroller nettverket og prøv igjen."
    if exc.code == "ai_unavailable":
        if detail.startswith("http"):
            return f"{name} er midlertidig utilgjengelig. Prøv igjen om litt."
        return (f"Fikk ikke kontakt med {name}. Kontroller at maskinen er på nett (og eventuell proxy eller "
                "brannmur), og prøv igjen.")
    if exc.code in ("ai_model_missing", "ai_bad_response"):
        return (f"Endepunktet svarte ikke som {name}s API. Kontroller endepunktet under «Avansert», eller tilbakestill "
                "det til standardadressen.")
    if exc.code == "ai_not_configured":
        return exc.message
    return f"Tilkoblingen til {name} feilet: {exc.message}"


def _connected(c: AppContainer, provider_id: str, *, switch_on: bool) -> None:
    def mutate(s: AppSettings) -> None:
        p = _find(s, provider_id)
        now = datetime.now(UTC)
        if switch_on:
            p.enabled = True  # connecting means «use this provider»; the switch can turn it off again
        p.last_status = "ok"
        p.last_message = "Tilkoblet."
        p.last_checked_at = now
        p.models_fetched_at = now

    c.settings.update(mutate)


@router.post("/providers/{provider_id}/connect")
async def connect(provider_id: str, body: ConnectBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Check the key with the provider and store it in the OS credential store only when the check succeeds. A key that
    fails is never stored, and an earlier key is kept. The model list from the check is cached in the registry."""
    settings = c.settings.get()
    provider = _find(settings, provider_id)
    stored = c.ai.key_for(provider_id)
    new_key = body.api_key is not None
    key = (body.api_key or "").strip() if new_key else (stored or "")
    if new_key or provider.type != "openai_compatible":
        problem = key_problem(provider, key) if new_key else (None if key else "Lim inn API-nøkkelen først.")
        if problem:
            raise AppError("validation_error", status=422, message=problem)
    if key and key != stored:
        register_secret(key)  # redacted wherever it could show up while it is checked
    try:
        models = await c.ai.check_key(provider, key or None)
    except AIError as exc:
        if key and key != stored:
            unregister_secret(key)
        message = connect_message(provider, exc)
        if not new_key:
            _record_status(c, provider_id, False, message)
        elif stored:
            message += " Den lagrede nøkkelen er beholdt."
        else:
            message += " Nøkkelen er ikke lagret."
        # A wrong key or endpoint is the teacher's input (400); an unreachable or busy provider keeps its own status.
        status = 400 if exc.code in ("ai_key_invalid", "ai_key_missing", "ai_model_missing", "ai_bad_response") \
            else exc.status
        raise AppError(exc.code, status=status, message=message) from None
    if new_key:
        c.secrets.set(ai_key_name(provider_id), key)
    if flags.is_enabled(c.settings.get(), "ai_model_discovery"):
        c.ai.registry.merge_discovered(provider_id, models, local=is_local(provider))
    _connected(c, provider_id, switch_on=new_key)
    return provider_dict(c, _find(c.settings.get(), provider_id))


@router.post("/providers/{provider_id}/refresh-models")
async def refresh_models(provider_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Fetch the model list again in the background (the settings page asks when it is older than a day). A key the
    provider no longer accepts is shown as an error on the card; other failures are left for the next time."""
    settings = c.settings.get()
    provider = _find(settings, provider_id)
    if not flags.is_enabled(settings, "ai_model_discovery") or not c.ai.configured(provider):
        return {"refreshed": False, "added": 0}
    try:
        models = await c.ai.check_key(provider, c.ai.key_for(provider_id))
    except AIError as exc:
        if exc.code == "ai_key_invalid":
            _record_status(c, provider_id, False, connect_message(provider, exc))
        return {"refreshed": False, "added": 0}
    added = c.ai.registry.merge_discovered(provider_id, models, local=is_local(provider))

    def mutate(s: AppSettings) -> None:
        _find(s, provider_id).models_fetched_at = datetime.now(UTC)

    c.settings.update(mutate)
    return {"refreshed": True, "added": added}


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
                           "task_label": TASKS[r.task_type].label if r.task_type in TASKS
                           else USAGE_LABELS.get(r.task_type, r.task_type),
                           "provider_id": r.provider_id, "model_id": r.model_id, "strategy": r.strategy,
                           "reason": r.reason, "fallback_used": r.fallback_used, "success": r.success,
                           "error_code": r.error_code, "input_tokens": r.input_tokens,
                           "output_tokens": r.output_tokens, "summary": (r.payload_summary or {}).get("summary")}
                          for r in rows]}
