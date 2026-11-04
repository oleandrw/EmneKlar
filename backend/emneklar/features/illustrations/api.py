"""KI-bildeassistent API (Canvas-verktøy → KI-bildeassistent).

Reads from Canvas freely; every write goes through the change engine (publish.py). AI calls are privacy-gated by
core/ai (external AI must be allowed; with «Bekreft før innhold sendes» the teacher confirms the payload summary).
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core import flags
from emneklar.core.ai import images as image_catalog
from emneklar.core.ai import pricing, profiles
from emneklar.core.ai.base import ImageGenerationRequest
from emneklar.core.canvas.api import USE_JUSTIFICATIONS, CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.jobs.manager import ACTIVE, JobContext
from emneklar.core.storage.models import ChangeLogEntry
from emneklar.core.storage.settings import AppSettings, IllustrationSettings
from emneklar.features.illustrations import design as design_mod
from emneklar.features.illustrations import prompts
from emneklar.features.illustrations.assets import AssetStore
from emneklar.features.illustrations.choices import image_providers, resolve
from emneklar.features.illustrations.costs import estimate as estimate_costs
from emneklar.features.illustrations.design import DesignData, DesignProfiles
from emneklar.features.illustrations.inventory import OUTSIDE_MODULES, Scope, build_inventory, html_text
from emneklar.features.illustrations.pipeline import JOB_KIND, RunOptions, compose_prompt, run_job, sample_prompt
from emneklar.features.illustrations.placement import PLACEMENTS, Anchor, candidate_anchors
from emneklar.features.illustrations.privacy import wrap
from emneklar.features.illustrations.publish import build_page_change, stage_page
from emneklar.features.illustrations.store import RUN_STATUS_LABELS, STATUS_LABELS, Store
from emneklar.features.illustrations.structure import parse_page

router = APIRouter(prefix="/api")

USAGE_RIGHT_LABELS = {"own_copyright": "Jeg har opphavsretten", "used_by_permission": "Brukt med tillatelse",
                      "fair_use": "Rimelig bruk / sitatrett", "public_domain": "Fritt tilgjengelig (public domain)",
                      "creative_commons": "Creative Commons-lisens"}
AMOUNT_LABELS = {"low": "Lav", "balanced": "Balansert", "high": "Høy"}


def _flag(c: AppContainer) -> None:
    flags.require(c.settings.get(), "illustration_assistant")


def _busy(c: AppContainer, course_id: str) -> dict[str, Any] | None:
    for job in c.jobs.list(course_id=course_id, active_only=True):
        if job.kind == JOB_KIND:
            return {"id": job.id, "title": job.title, "status": job.status}
    return None


def _store(c: AppContainer) -> Store:
    return Store(c.db)


def _assets(c: AppContainer) -> AssetStore:
    return AssetStore(c.db, c.config.illustrations_dir)


# ------------------------------------------------------------------------------------- catalog and status


@router.get("/illustrations/catalog")
async def catalog(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    return {
        "styles": [{"key": s["key"], "label": s["label"], "description": s["description"]} for s in design_mod.styles()],
        "quality_profiles": [p.as_dict() for p in profiles.profiles()], "roles": profiles.role_labels(),
        "image_models": [m.as_dict() for m in image_catalog.catalog()], "image_catalog_note":
            image_catalog.catalog_data()["note"],
        "placements": PLACEMENTS, "amounts": AMOUNT_LABELS, "statuses": STATUS_LABELS,
        "run_statuses": RUN_STATUS_LABELS, "pricing": pricing.summary(),
        "usage_rights": [{"id": k, "label": USAGE_RIGHT_LABELS[k]} for k in USE_JUSTIFICATIONS],
    }


@router.get("/courses/{course_id}/illustrations")
async def status(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    settings = c.settings.get()
    profiles_store = DesignProfiles(c.db)
    choices = resolve(c, settings.illustrations)
    reason = c.ai.unavailable_reason(settings)
    return {
        "settings": settings.illustrations.model_dump(mode="json"), "choices": choices.as_dict(),
        "ai": {"available": reason is None, "reason": reason, "external_allowed": settings.privacy.allow_external_ai,
               "confirm_before_send": settings.privacy.confirm_before_send},
        "image_providers": image_providers(c),
        "design": profiles_store.active(course_id), "design_versions": profiles_store.versions(course_id)[:10],
        "runs": _store(c).runs(course_id, limit=10), "busy_job": _busy(c, course_id), "dry_run": c.is_dry_run(),
        "text_models": [{"ref": f"{m['provider_id']}/{m['model_id']}", "display_name": m["display_name"],
                         "provider_id": m["provider_id"], "vision": m["vision"]}
                        for m in c.ai.registry.list() if m["enabled"] and m["capabilities_known"]],
    }


@router.put("/illustrations/settings")
async def update_settings(body: IllustrationSettings, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)

    def mutate(s: AppSettings) -> None:
        s.illustrations = body

    updated = c.settings.update(mutate)
    return {"settings": updated.illustrations.model_dump(mode="json"),
            "choices": resolve(c, updated.illustrations).as_dict()}


@router.get("/courses/{course_id}/illustrations/scope-index")
async def scope_index(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Modules and pages for choosing the scope (live from Canvas, without page bodies)."""
    _flag(c)
    course_id = require_course_id(course_id)
    api = CanvasAPI(c.canvas())
    modules, pages = await asyncio.gather(api.list_modules(course_id), api.list_pages(course_id, include_body=False))
    in_module: set[str] = set()
    out_modules = []
    for module in modules:
        items = module.get("items") or []
        page_items = [{"page_url": i.get("page_url"), "title": i.get("title") or ""} for i in items
                      if i.get("type") == "Page" and i.get("page_url")]
        in_module.update(p["page_url"] for p in page_items)
        out_modules.append({"id": str(module["id"]), "name": module.get("name") or "", "items_count": len(items),
                            "pages": page_items, "other_items": len(items) - len(page_items),
                            "published": module.get("published") is not False})
    titles = {str(p.get("url")): p for p in pages if isinstance(p, dict)}
    return {"modules": out_modules,
            "pages": [{"url": url, "title": p.get("title") or url, "published": p.get("published") is not False,
                       "in_module": url in in_module, "front_page": bool(p.get("front_page"))}
                      for url, p in sorted(titles.items(), key=lambda kv: str(kv[1].get("title") or "").lower())]}


# ------------------------------------------------------------------------------------- design profile


class DesignBody(BaseModel):
    data: DesignData
    origin: Literal["preset", "ai", "custom"] = "custom"


@router.put("/courses/{course_id}/illustrations/design")
async def save_design(course_id: str, body: DesignBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    return DesignProfiles(c.db).save(require_course_id(course_id), body.data, origin=body.origin)


class StyleBody(BaseModel):
    style_key: str


@router.post("/courses/{course_id}/illustrations/design/from-style")
async def design_from_style(course_id: str, body: StyleBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    require_course_id(course_id)
    data = design_mod.from_style(body.style_key)
    return {"data": data.model_dump(), "style_prompt": design_mod.style_block(data)}


class ReferencesBody(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=design_mod.MAX_REFERENCES)


@router.put("/courses/{course_id}/illustrations/design/references")
async def set_references(course_id: str, body: ReferencesBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    for asset_id in body.asset_ids:
        if _assets(c).get(asset_id)["course_id"] != course_id:
            raise AppError("validation_error", detail="Bildet hører til et annet emne")
    DesignProfiles(c.db).ensure(course_id)
    return DesignProfiles(c.db).set_references(course_id, body.asset_ids)


class ConsentBody(BaseModel):
    confirmed: bool = False


async def _course_context_for_design(c: AppContainer, course_id: str) -> dict[str, Any]:
    api = CanvasAPI(c.canvas())
    course, modules = await asyncio.gather(api.get_course(course_id, include=("syllabus_body", "public_description")),
                                           api.list_modules(course_id))
    return {"name": course.get("name") or "", "description": html_text(course.get("public_description"), 1500),
            "syllabus": html_text(course.get("syllabus_body"), 5000),
            "modules": [{"name": m.get("name") or "", "items": [i.get("title") or "" for i in m.get("items") or []][:15]}
                        for m in modules][:40]}


@router.post("/courses/{course_id}/illustrations/design/suggest/prepare")
async def prepare_suggest(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    require_course_id(course_id)
    summary = ("Emnets navn, beskrivelse, emneplan (inntil 5000 tegn) og modul- og elementtitler sendes til "
               "KI-leverandøren for å foreslå en designprofil. Ingen studentdata sendes.")
    return c.ai.plan("illustration_design", input_chars=9000, images=0, summary=summary)


@router.post("/courses/{course_id}/illustrations/design/suggest")
async def suggest_design(course_id: str, body: ConsentBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    import json

    from emneklar.core.ai.base import AIMessage, AIRequest, TextPart

    context = await _course_context_for_design(c, course_id)
    text = wrap("EMNET", json.dumps(context, ensure_ascii=False, indent=1)) + "\n\nForeslå en designprofil."
    choice = resolve(c, c.settings.get().illustrations).roles["illustration_design"]

    def build(model: str) -> AIRequest:
        return AIRequest(model=model, system=prompts.DESIGN_SYSTEM, schema_name="designprofil",
                         json_schema=prompts.DESIGN_SCHEMA, max_output_tokens=2500,
                         messages=[AIMessage(parts=[TextPart(text=text)])])

    result, decision = await c.ai.run("illustration_design", build, input_chars=len(text), summary=(
        f"Forslag til designprofil ({len(text)} tegn)"), confirmed=body.confirmed, course_id=course_id,
        preferred=choice.models or None, preferred_reason=choice.reason)
    answer = result.data or {}
    base = design_mod.from_style(str(answer.get("style_key") or "modern_3d")).model_dump()
    merged = {**base, **{k: v for k, v in answer.items() if k in DesignData.model_fields and v not in ("", [], None)}}
    data = DesignData.model_validate(merged)
    return {"data": data.model_dump(), "style_prompt": design_mod.style_block(data), "label": "KI-forslag – må vurderes",
            "model": result.model, "route_reason": decision.reason}


@router.post("/courses/{course_id}/illustrations/design/sample/prepare")
async def prepare_sample(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    require_course_id(course_id)
    choices = resolve(c, c.settings.get().illustrations)
    from emneklar.features.illustrations.costs import image_call_cost

    cost = image_call_cost(c, choices, prompt_chars=3000, references=0)
    plan = c.ai.image_plan(choices.image.provider_id, (choices.image.model or {}).get("id", ""), summary=(
        "En bildeprompt med emnets fagområde og designprofilen sendes til bildemodellen. Ingen sidetekst eller "
        "studentdata sendes."))
    return {**plan, "estimated_cost_usd": None if cost is None else round(cost, 3)}


@router.post("/courses/{course_id}/illustrations/design/sample")
async def design_sample(course_id: str, body: ConsentBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    choices = resolve(c, c.settings.get().illustrations)
    if not choices.image.model:
        raise AppError("illustration_image_unavailable", status=409, message=choices.image.unavailable_reason)
    design = DesignProfiles(c.db).ensure(course_id)
    context = await _course_context_for_design(c, course_id)
    prompt = sample_prompt({"name": context["name"]}, design)
    result = await c.ai.generate_image(
        choices.image.provider_id, choices.image.model["id"],
        ImageGenerationRequest(model=choices.image.model["id"], prompt=prompt, size=design["size"],
                               quality=choices.image.quality),
        summary="Eksempelbilde for designprofilen", confirmed=body.confirmed, course_id=course_id)
    image = result.images[0]
    asset = _assets(c).save(course_id=course_id, data=image.data, media_type=image.media_type, kind="sample",
                            model=f"{result.provider}/{result.model}", prompt=prompt, illustration_id=None)
    return {"asset": asset, "prompt": prompt, "label": "KI-forslag – må vurderes"}


# ------------------------------------------------------------------------------------- estimate and runs


class RunBody(BaseModel):
    scope: Scope
    settings: IllustrationSettings | None = None
    mode: Literal["full", "plan"] = "full"
    auto_insert: bool = False
    usage_rights: dict[str, Any] | None = None
    confirmed: bool = False


def _validate_scope(scope: Scope) -> None:
    if scope.type in ("module", "modules") and not scope.module_ids:
        raise AppError("illustration_nothing_selected")
    if scope.type == "page" and not scope.page_url:
        raise AppError("illustration_nothing_selected")


def _payload_summary(c: AppContainer, choices: Any, *, pages: int, chars: int, references: int,
                     generate: bool) -> dict[str, Any]:
    app = c.settings.get()

    def where(role: str) -> str:
        primary = choices.roles[role].primary
        if not primary:
            return "ingen modell tilgjengelig"
        provider = app.provider(primary["provider_id"])
        return f"{primary['display_name']} ({provider.name if provider else primary['provider_id']})"

    image_provider = app.provider(choices.image.provider_id)
    receivers = [
        {"service": where("illustration_analysis"), "role": "Innholdsanalyse",
         "content": f"Emnets navn, beskrivelse og emneplan, modulstrukturen og teksten på {pages} side(r) "
                    f"(ca. {format(chars, ',').replace(',', ' ')} tegn)."},
        {"service": where("illustration_planning"), "role": "Bildeplan",
         "content": "Oppsummert emne- og modulkontekst og sidens tekst, seksjon for seksjon."},
    ]
    if generate:
        receivers.append({"service": f"{(choices.image.model or {}).get('label', 'ingen bildemodell')} "
                                     f"({image_provider.name if image_provider else choices.image.provider_id})",
                          "role": "Bildegenerering",
                          "content": "Bildeprompter med faglig kontekst for seksjonen og designprofilen"
                                     + (f", og inntil {references} godkjente referansebilder fra emnet." if references
                                        else ".")})
        receivers.append({"service": where("illustration_review"), "role": "Kvalitetskontroll",
                          "content": "De genererte bildene og teksten i seksjonen de skal støtte."})
    text = ("Dette sendes: " + " ".join(f"{r['role']} → {r['service']}: {r['content']}" for r in receivers)
            + " Aldri: studentbesvarelser, karakterer, meldinger, diskusjonssvar, deltakerlister eller "
              "kontaktinformasjon (e-post og telefonnummer fjernes).")
    return {"receivers": receivers, "text": text}


async def _inventory_and_estimate(c: AppContainer, course_id: str, body: RunBody) -> dict[str, Any]:
    settings = body.settings or c.settings.get().illustrations
    choices = resolve(c, settings)
    inv = await build_inventory(CanvasAPI(c.canvas()), course_id, body.scope)
    chars = sum(len(html_text(inv.pages[u].body)) for u in inv.targets)
    store = _store(c)
    cached_pairs = store.cached_page_hashes(course_id, prompts.ANALYSIS_VERSION)
    cached = sum(1 for u in inv.targets if (u, inv.pages[u].content_hash) in cached_pairs)
    design = DesignProfiles(c.db).active(course_id)
    image_model = choices.image.model or {}
    references = len((design or {}).get("reference_assets") or []) if (
        settings.use_reference_images and image_model.get("reference_images")) else 0
    references = min(references, choices.profile.reference_images)
    modules = len([m for m in inv.target_modules if m != OUTSIDE_MODULES])
    cost = estimate_costs(c, choices, modules=modules, pages=len(inv.targets), cached_pages=cached, page_chars=chars,
                          amount=settings.amount, generate=body.mode == "full", references=references)
    app = c.settings.get()
    reason = c.ai.unavailable_reason(app)
    missing = [choices.roles[r].as_dict()["label"] for r in ("illustration_analysis", "illustration_planning",
                                                             "illustration_review") if not choices.roles[r].primary]
    if reason is None and missing:
        reason = "Ingen modell er tilgjengelig for: " + ", ".join(missing) + ". Se Innstillinger → KI-assistenter."
    if reason is None and body.mode == "full" and not choices.image.available:
        reason = choices.image.unavailable_reason
    used = {r.primary["provider_id"] for r in choices.roles.values() if r.primary}
    if body.mode == "full":
        used.add(choices.image.provider_id)
    external = any(not _local(c, provider_id) for provider_id in used)
    payload = _payload_summary(c, choices, pages=len(inv.targets), chars=chars, references=references,
                               generate=body.mode == "full")
    course = await CanvasAPI(c.canvas()).get_course(course_id, include=())
    usage_rights_required = bool(course.get("usage_rights_required"))
    return {"available": reason is None, "reason": reason, "stats": inv.stats(), "skipped": inv.skipped,
            "limitations": inv.limitations, "estimate": cost, "choices": choices.as_dict(),
            "payload_summary": payload["text"], "receivers": payload["receivers"], "external": external,
            "needs_confirmation": external and app.privacy.confirm_before_send,
            "usage_rights_required": usage_rights_required,
            "pages": [{"url": u, "title": inv.pages[u].title, "module": getattr(inv.module_of(u), "name",
                                                                                "Sider utenfor moduler"),
                       "published": inv.pages[u].published, "modules": [m["name"] for m in inv.pages[u].modules]}
                      for u in inv.targets]}


def _local(c: AppContainer, provider_id: str) -> bool:
    from emneklar.core.ai.service import is_local

    provider = c.settings.get().provider(provider_id)
    return provider is not None and is_local(provider)


@router.post("/courses/{course_id}/illustrations/estimate")
async def estimate(course_id: str, body: RunBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    _validate_scope(body.scope)
    return await _inventory_and_estimate(c, course_id, body)


def _submit(c: AppContainer, course_id: str, run_id: int, *, stages: tuple[str, ...], confirmed: bool, title: str,
            ids: list[int] | None = None) -> dict[str, Any]:
    if _busy(c, course_id):
        raise AppError("illustration_busy", status=409)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await run_job(ctx, c, run_id, stages=stages, confirmed=confirmed, illustration_ids=ids)

    state = c.jobs.submit(kind=JOB_KIND, title=title, runner=runner, course_id=course_id,
                          params={"run_id": run_id, "stages": list(stages)}, supports_pause=True, hard_cancel=False)
    _store(c).update_run(run_id, job_id=state.id)
    return state.public()


def _check_ready(c: AppContainer, settings: IllustrationSettings, *, generate: bool, confirmed: bool) -> None:
    app = c.settings.get()
    reason = c.ai.unavailable_reason(app)
    if reason:
        raise AppError("ai_not_configured", status=409, message=reason)
    choices = resolve(c, settings)
    if generate and not choices.image.available:
        raise AppError("illustration_image_unavailable", status=409, message=choices.image.unavailable_reason)
    if app.privacy.confirm_before_send and not confirmed:
        raise AppError("ai_consent_required", status=409)


@router.post("/courses/{course_id}/illustrations/runs")
async def start_run(course_id: str, body: RunBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    _validate_scope(body.scope)
    settings = body.settings or c.settings.get().illustrations
    _check_ready(c, settings, generate=body.mode == "full", confirmed=body.confirmed)
    if body.usage_rights and body.usage_rights.get("use_justification") not in USE_JUSTIFICATIONS:
        raise AppError("validation_error", detail="Ugyldig opphavsrettsgrunnlag")
    c.canvas()
    if _busy(c, course_id):
        raise AppError("illustration_busy", status=409)
    design = DesignProfiles(c.db).ensure(course_id)
    options = RunOptions(mode=body.mode, settings=settings, auto_insert=body.auto_insert, usage_rights=body.usage_rights)
    run = _store(c).create_run(course_id, scope=body.scope.model_dump(), options=options.model_dump(mode="json"),
                               profile_id=design["id"])
    stages = ("inventory", "context", "plan") + (("generate", "publish") if body.mode == "full" else ())
    title = f"KI-bildeassistent: {body.scope.label().lower()}"
    job = _submit(c, course_id, run["id"], stages=stages, confirmed=body.confirmed, title=title)
    return {"run": _store(c).run(run["id"]), "job": job}


def _overview(run: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Module → page → illustrations, in course order (for the course overview)."""
    stats = run.get("stats") or {}
    pages_state = stats.get("pages") or {}
    modules = stats.get("modules") or []
    by_page: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_page.setdefault(item["page_url"], []).append(item)
    module_of = {url: s.get("module_id") for url, s in pages_state.items()}
    groups = []
    for module in modules:
        urls = [u for u in stats.get("targets") or [] if module_of.get(u) == module["id"]
                or (module_of.get(u) is None and any(i["module_id"] == module["id"] for i in by_page.get(u, [])))]
        pages = []
        for url in urls:
            state = pages_state.get(url) or {}
            page_items = by_page.get(url, [])
            pages.append({"page_url": url, "title": state.get("title") or (page_items[0]["page_title"] if page_items
                                                                           else url),
                          "status": state.get("status") or "pending", "reason": state.get("reason"),
                          "summary": state.get("summary"), "illustrations": page_items,
                          "proposed": len([i for i in page_items if i["status"] != "skipped"])})
        groups.append({"module_id": module["id"], "name": module["name"], "pages": pages,
                       "proposed": sum(p["proposed"] for p in pages)})
    return groups


@router.get("/illustrations/runs/{run_id}")
async def get_run(run_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    store = _store(c)
    run = store.run(run_id)
    items = store.for_run(run_id)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    job = None
    if run["job_id"]:
        try:
            job = c.jobs.get(run["job_id"]).public()
        except NotFoundError:
            job = None
    return {"run": run, "illustrations": items, "overview": _overview(run, items), "counts": counts, "job": job,
            "can_continue": run["status"] in ("cancelled", "interrupted", "cost_limit", "failed", "analyzing",
                                              "generating") and (job is None or job["status"] not in ACTIVE)}


class ContinueBody(BaseModel):
    confirmed: bool = False
    cost_limit_usd: float | None = Field(default=None, ge=0, le=10_000)


@router.post("/illustrations/runs/{run_id}/continue")
async def continue_run(run_id: int, body: ContinueBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Continue a stopped run: pages not yet planned and images not yet made (cached analyses are reused)."""
    _flag(c)
    store = _store(c)
    run = store.run(run_id)
    options = RunOptions.model_validate(run["options"])
    if body.cost_limit_usd is not None:
        options.settings.cost_limit_usd = body.cost_limit_usd
        store.update_run(run_id, options=options.model_dump(mode="json"))
    _check_ready(c, options.settings, generate=options.mode == "full", confirmed=body.confirmed)
    stats = run.get("stats") or {}
    targets = stats.get("targets")
    pages = stats.get("pages") or {}
    planning_done = targets is not None and all((pages.get(u) or {}).get("status") in ("planned", "skipped")
                                                for u in targets)
    stages: tuple[str, ...] = () if planning_done else ("inventory", "context", "plan")
    if options.mode == "full":
        stages += ("generate", "publish")
    if not stages:
        stages = ("generate",)
    return _submit(c, run["course_id"], run_id, stages=stages, confirmed=body.confirmed,
                   title="KI-bildeassistent: fortsetter")


class GenerateBody(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=1000)
    confirmed: bool = False


@router.post("/illustrations/runs/{run_id}/generate")
async def generate(run_id: int, body: GenerateBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Generate images for the proposals of a planned run (all proposed, or the chosen ones)."""
    _flag(c)
    store = _store(c)
    run = store.run(run_id)
    options = RunOptions.model_validate(run["options"])
    _check_ready(c, options.settings, generate=True, confirmed=body.confirmed)
    ids = body.ids
    if ids is not None:
        valid = {i["id"] for i in store.for_run(run_id)}
        if not set(ids) <= valid:
            raise AppError("validation_error", detail="Ukjente illustrasjoner")
    return _submit(c, run["course_id"], run_id, stages=("generate",), confirmed=body.confirmed, ids=ids,
                   title="KI-bildeassistent: lager bilder")


# ------------------------------------------------------------------------------------- one illustration


class IllustrationPatch(BaseModel):
    prompt: str | None = Field(default=None, max_length=6000)
    alt_text: str | None = Field(default=None, max_length=600)
    caption: str | None = Field(default=None, max_length=600)
    caption_enabled: bool | None = None
    decorative: bool | None = None
    style_override: str | None = Field(default=None, max_length=32)
    anchor: dict[str, Any] | None = None
    status: Literal["approved", "rejected", "skipped", "proposed", "generated"] | None = None
    asset_id: str | None = Field(default=None, max_length=32)  # choose another generated version


@router.patch("/illustrations/{illustration_id}")
async def edit(illustration_id: int, body: IllustrationPatch, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    store = _store(c)
    current = store.get(illustration_id)
    if current["status"] in ("staged", "generating", "queued"):
        raise AppError("change_state_invalid", status=409,
                       message="Illustrasjonen ligger i endringskøen eller lages akkurat nå og kan ikke endres.")
    fields: dict[str, Any] = {k: v for k, v in body.model_dump(exclude_unset=True).items()
                              if k in ("prompt", "alt_text", "caption", "caption_enabled", "decorative")}
    if "style_override" in body.model_fields_set:
        if body.style_override and body.style_override not in {s["key"] for s in design_mod.styles()}:
            raise AppError("validation_error", detail="Ukjent stil")
        fields["style_override"] = body.style_override or None
    if body.asset_id is not None:
        if body.asset_id not in {v["asset_id"] for v in current["versions"]}:
            raise AppError("validation_error", detail="Ukjent bildeversjon")
        fields["asset_id"] = body.asset_id
    if body.anchor is not None:
        fields["anchor"] = Anchor.from_dict(body.anchor).as_dict()
    if body.status is not None:
        if body.status == "approved" and not (fields.get("asset_id") or current["asset_id"]):
            raise AppError("validation_error", message="Lag et bilde før illustrasjonen kan godkjennes.")
        if body.status == "approved":
            alt = fields.get("alt_text", current["alt_text"])
            decorative = fields.get("decorative", current["decorative"])
            if not decorative and not str(alt or "").strip():
                raise AppError("validation_error", message="Skriv alternativ tekst, eller marker bildet som dekorativt.")
        fields["status"] = body.status
    if current["status"] == "published" and set(fields) - {"status"}:
        fields.setdefault("status", "approved")  # a changed published illustration must be published again
    return store.update(illustration_id, **fields)


@router.get("/illustrations/{illustration_id}/anchors")
async def anchors(illustration_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Every placement on the live page (for «Endre plassering»)."""
    _flag(c)
    ill = _store(c).get(illustration_id)
    page = await CanvasAPI(c.canvas()).get_page(ill["course_id"], ill["page_url"])
    structure = parse_page(page.get("body") or "")
    sections = {s.id: s.title for s in structure.sections}
    return {"anchors": candidate_anchors(structure), "sections": sections, "current": ill["anchor"],
            "page_changed": bool(ill["page_hash"]) and ill["page_hash"] != _hash(page.get("body") or "")}


def _hash(body: str) -> str:
    import hashlib

    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class RegenerateBody(BaseModel):
    prompt: str | None = Field(default=None, max_length=6000)
    style_override: str | None = Field(default=None, max_length=32)
    confirmed: bool = False


@router.post("/illustrations/{illustration_id}/regenerate")
async def regenerate(illustration_id: int, body: RegenerateBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    store = _store(c)
    ill = store.get(illustration_id)
    if ill["status"] in ("staged", "generating", "queued"):
        raise AppError("change_state_invalid", status=409)
    run = store.run(ill["run_id"])
    options = RunOptions.model_validate(run["options"])
    _check_ready(c, options.settings, generate=True, confirmed=body.confirmed)
    fields: dict[str, Any] = {"asset_id": None, "status": "queued"}
    if body.prompt is not None:
        fields["prompt"] = body.prompt
    if body.style_override is not None:
        fields["style_override"] = body.style_override or None
    store.update(illustration_id, **fields)
    return _submit(c, ill["course_id"], ill["run_id"], stages=("generate",), confirmed=body.confirmed,
                   ids=[illustration_id], title=f"KI-bildeassistent: nytt bilde for «{ill['page_title']}»")


@router.get("/illustrations/{illustration_id}/prompt-preview")
async def prompt_preview(illustration_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """The complete prompt the image model gets (planning prompt + context + style + rules)."""
    _flag(c)
    store = _store(c)
    ill = store.get(illustration_id)
    run = store.run(ill["run_id"])
    profiles_store = DesignProfiles(c.db)
    design = profiles_store.get(run["profile_id"]) if run["profile_id"] else profiles_store.ensure(ill["course_id"])
    return {"prompt": compose_prompt(ill, design)}


@router.post("/illustrations/{illustration_id}/reference")
async def use_as_reference(illustration_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    ill = _store(c).get(illustration_id)
    if not ill["asset_id"]:
        raise AppError("validation_error", message="Illustrasjonen har ikke noe bilde.")
    profiles_store = DesignProfiles(c.db)
    profiles_store.ensure(ill["course_id"])
    current = profiles_store.active(ill["course_id"]) or {}
    refs = list(current.get("reference_assets") or [])
    if ill["asset_id"] not in refs:
        if len(refs) >= design_mod.MAX_REFERENCES:
            raise AppError("validation_error", message=f"Designprofilen har allerede {design_mod.MAX_REFERENCES} "
                                                       "referansebilder. Fjern ett først.")
        refs.append(ill["asset_id"])
    return profiles_store.set_references(ill["course_id"], refs)


class BulkBody(BaseModel):
    run_id: int
    level: Literal["ids", "page", "module", "course"]
    ids: list[int] = Field(default_factory=list, max_length=2000)
    page_url: str | None = None
    module_id: str | None = None
    action: Literal["approve", "reject", "skip"] = "approve"


@router.post("/illustrations/bulk")
async def bulk(body: BulkBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Approve (or reject/skip) one image, all images on a page, a whole module or the whole course."""
    _flag(c)
    store = _store(c)
    items = store.for_run(body.run_id)
    if body.level == "ids":
        chosen = [i for i in items if i["id"] in set(body.ids)]
    elif body.level == "page":
        chosen = [i for i in items if i["page_url"] == body.page_url]
    elif body.level == "module":
        chosen = [i for i in items if (i["module_id"] or OUTSIDE_MODULES) == body.module_id]
    else:
        chosen = items
    target = {"approve": "approved", "reject": "rejected", "skip": "skipped"}[body.action]
    changed, missing_alt = [], []
    for item in chosen:
        if body.action == "approve":
            if item["status"] not in ("generated", "flagged", "rejected", "conflict", "undone") or not item["asset_id"]:
                continue
            if not item["decorative"] and not item["alt_text"].strip():
                missing_alt.append(item["id"])
                continue
        elif item["status"] in ("staged", "published", "generating", "queued"):
            continue
        changed.append(store.update(item["id"], status=target)["id"])
    return {"changed": changed, "missing_alt_text": missing_alt}


# ------------------------------------------------------------------------------------- publishing


class PublishBody(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=2000)  # default: every approved illustration in the run
    usage_rights: dict[str, Any] | None = None
    apply: bool = True  # False = only put the changes in the change queue
    confirm_high_risk: bool = False


def _approved(store: Store, run_id: int, ids: list[int] | None) -> dict[str, list[dict[str, Any]]]:
    """Approved illustrations per page. A page's change replaces its open change in the queue, so illustrations of
    the page that are already queued go into the new change too (nothing queued is dropped)."""
    items = [i for i in store.for_run(run_id) if i["asset_id"] and i["status"] in ("approved", "staged")]
    if ids is not None:
        chosen = {i["page_url"] for i in items if i["id"] in set(ids) and i["status"] == "approved"}
        items = [i for i in items if i["page_url"] in chosen and (i["id"] in set(ids) or i["status"] == "staged")]
    by_page: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_page.setdefault(item["page_url"], []).append(item)
    return {url: page for url, page in by_page.items() if any(i["status"] == "approved" for i in page)}


def _rights(body: PublishBody) -> dict[str, Any] | None:
    rights = body.usage_rights or None
    if rights:
        if rights.get("use_justification") not in USE_JUSTIFICATIONS:
            raise AppError("validation_error", detail="Ugyldig opphavsrettsgrunnlag")
        rights = {"use_justification": rights["use_justification"],
                  "legal_copyright": str(rights.get("legal_copyright") or "")[:200] or None}
    return rights


@router.post("/illustrations/runs/{run_id}/publish/preview")
async def publish_preview(run_id: int, body: PublishBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Exactly what publishing changes, per page – before anything is staged or written."""
    _flag(c)
    store = _store(c)
    run = store.run(run_id)
    folder = c.settings.get().illustrations.folder
    pages = []
    for url, items in _approved(store, run_id, body.ids).items():
        try:
            built = await build_page_change(c, run["course_id"], url, items, usage_rights=_rights(body), folder=folder)
        except AppError as exc:
            pages.append({"page_url": url, "title": items[0]["page_title"], "ok": False, "error": exc.message,
                          "illustrations": [{"id": i["id"]} for i in items]})
            continue
        page = built["page"]
        pages.append({"page_url": url, "title": page.get("title") or url, "ok": True,
                      "published": page.get("published"), "replaces": built["replaces"],
                      "already_on_page": built["already_on_page"],
                      "illustrations": [{"id": i["id"], "placement": i["anchor"].get("placement"),
                                         "placement_label": PLACEMENTS.get(i["anchor"].get("placement", ""), ""),
                                         "section": i["anchor"].get("section_title"), "alt_text": i["alt_text"],
                                         "decorative": i["decorative"],
                                         "caption": i["caption"] if i["caption_enabled"] else None,
                                         "thumb_url": i["thumb_url"]} for i in items]})
    course = await CanvasAPI(c.canvas()).get_course(run["course_id"], include=())
    return {"pages": pages, "folder": folder, "dry_run": c.is_dry_run(),
            "usage_rights_required": bool(course.get("usage_rights_required")),
            "note": ("Bildene lastes opp til Canvas-filene i mappen «" + folder + "», og figurene settes inn mellom "
                     "avsnittene. Eksisterende tekst endres ikke, og sidens publiseringsstatus beholdes.")}


@router.post("/illustrations/runs/{run_id}/publish")
async def publish(run_id: int, body: PublishBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    store = _store(c)
    run = store.run(run_id)
    by_page = _approved(store, run_id, body.ids)
    if not by_page:
        raise AppError("validation_error", message="Ingen godkjente illustrasjoner å publisere.")
    rights = _rights(body)
    course = await CanvasAPI(c.canvas()).get_course(run["course_id"], include=())
    if course.get("usage_rights_required") and not rights:
        raise AppError("illustration_file_locked", status=409)
    folder = c.settings.get().illustrations.folder
    changes, errors = [], []
    for url, items in by_page.items():
        try:
            changes.append(await stage_page(c, run["course_id"], url, items, usage_rights=rights, folder=folder))
        except AppError as exc:
            errors.append({"page_url": url, "title": items[0]["page_title"], "message": exc.message})
    job = None
    if body.apply and changes:
        ids = [ch["id"] for ch in changes]
        c.changes.approve(ids)
        job = c.changes.submit_apply(ids, confirm_high_risk=body.confirm_high_risk, course_id=run["course_id"]).public()
    return {"changes": changes, "errors": errors, "job": job, "dry_run": c.is_dry_run()}


class UndoBody(BaseModel):
    page_url: str = Field(max_length=500)


@router.post("/illustrations/runs/{run_id}/undo")
async def undo_page(run_id: int, body: UndoBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Undo EmneKlar's illustrations on one page (only its own figures are removed)."""
    _flag(c)
    store = _store(c)
    items = [i for i in store.for_run(run_id) if i["page_url"] == body.page_url and i["status"] == "published"]
    change_ids = {i["change_id"] for i in items if i["change_id"]}
    if not change_ids:
        raise AppError("undo_not_possible", status=409)
    results = []
    with c.db.session() as session:
        entries = session.scalars(select(ChangeLogEntry).where(
            ChangeLogEntry.change_id.in_(change_ids), ChangeLogEntry.action == "apply",
            ChangeLogEntry.undone_by.is_(None))).all()
        log_ids = [e.id for e in entries]
    for log_id in log_ids:
        results.append(await c.changes.undo(log_id))
    store.refresh_from_changes(run_id=run_id)
    return {"results": results}


# ------------------------------------------------------------------------------------- images


@router.get("/illustrations/assets/{asset_id}")
async def asset(asset_id: str, size: str | None = None, c: AppContainer = Depends(get_container)) -> FileResponse:
    _flag(c)
    if not asset_id.isalnum() or len(asset_id) > 32:
        raise NotFoundError("not_found")
    store = _assets(c)
    if size == "thumb":
        return FileResponse(store.thumbnail(asset_id), media_type="image/webp",
                            headers={"Cache-Control": "private, max-age=86400"})
    info = store.get(asset_id)
    return FileResponse(store.path(asset_id), media_type=info["media_type"],
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/courses/{course_id}/illustrations/assets")
async def course_assets(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """Approved and published images of the course (candidates for reference images)."""
    _flag(c)
    course_id = require_course_id(course_id)
    items = _store(c).for_course(course_id, statuses=("approved", "staged", "published"))
    return {"items": [{"asset_id": i["asset_id"], "thumb_url": i["thumb_url"], "page_title": i["page_title"],
                       "illustration_id": i["id"]} for i in items if i["asset_id"]]}
