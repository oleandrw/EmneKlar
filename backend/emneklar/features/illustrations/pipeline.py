"""The assistant's background job: kartlegging → kontekst → bildeplan → generering og kontroll → (automatisk innsetting).

* Queue-based: pages and images are tasks with bounded concurrency (modules in parallel, pages in a module in order,
  so each page's plan knows what earlier pages in the module got – that avoids repeating motifs).
* Every intermediate result is stored as it happens (analyses, proposals, images, reviews, usage), so a cancelled,
  interrupted or cost-limited run can be continued: finished work is skipped, unchanged analyses are reused from the
  cache (no new AI calls), and only what is missing is done.
* Pause/cancel at checkpoints between tasks. Rate limits, timeouts and temporary errors are retried by the shared AI
  and Canvas clients; an image that still fails is marked «Feilet» and the run continues.
* Nothing is written to Canvas here, except in «Automatisk innsetting» – and then only through the change engine.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

from emneklar.core.ai import pricing
from emneklar.core.ai.base import AIError, AIMessage, AIRequest, ImageGenerationRequest, ImagePart, TextPart
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import JobCancelled, JobContext
from emneklar.core.storage.settings import IllustrationSettings
from emneklar.features.illustrations import prompts
from emneklar.features.illustrations.assets import AssetStore
from emneklar.features.illustrations.choices import Choices, resolve
from emneklar.features.illustrations.context import (
    clip,
    context_package,
    course_input,
    digest,
    language_of,
    module_input,
    outside_module_input,
    page_input,
    section_context,
)
from emneklar.features.illustrations.costs import CostLimitReached, CostMeter, image_call_cost, text_call_cost
from emneklar.features.illustrations.design import DesignData, DesignProfiles, style_block
from emneklar.features.illustrations.inventory import OUTSIDE_MODULES, Inventory, Scope, build_inventory
from emneklar.features.illustrations.placement import PLACEMENTS, anchor_for, candidate_anchors
from emneklar.features.illustrations.privacy import wrap
from emneklar.features.illustrations.store import EXISTING, Store, fingerprint
from emneklar.features.illustrations.structure import parse_page

log = logging.getLogger(__name__)
JOB_KIND = "illustrations"
STAGES = ("inventory", "context", "plan", "generate", "publish")


class RunOptions(BaseModel):
    """Snapshot of the settings a run uses (the defaults come from Innstillinger, the teacher can change them)."""

    mode: str = Field("full", pattern=r"^(full|plan)$")  # full = analyse, plan, generate and review; plan = stop
    settings: IllustrationSettings = Field(default_factory=IllustrationSettings)
    auto_insert: bool = False
    usage_rights: dict[str, Any] | None = None


@dataclass
class RunState:
    c: AppContainer
    run_id: int
    course_id: str
    options: RunOptions
    choices: Choices
    meter: CostMeter
    confirmed: bool
    store: Store
    assets: AssetStore
    design: dict[str, Any]
    inv: Inventory | None = None
    contexts: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def profile(self) -> Any:
        return self.choices.profile

    def save_usage(self) -> None:
        self.store.update_run(self.run_id, usage=self.meter.as_dict())


# ----------------------------------------------------------------------------------------- AI calls


async def ask(state: RunState, role: str, *, system: str, text: str, schema: dict[str, Any], schema_name: str,
              max_tokens: int, summary: str, images: list[ImagePart] | None = None) -> tuple[dict[str, Any], str]:
    choice = state.choices.roles[role]
    images = images or []
    estimate = text_call_cost(state.c, choice.primary, len(text) + len(system), max_tokens // 2, images=len(images))
    state.meter.check(estimate)

    def build(model: str) -> AIRequest:
        return AIRequest(model=model, system=system, schema_name=schema_name, json_schema=schema,
                         max_output_tokens=max_tokens,
                         messages=[AIMessage(parts=[*images, TextPart(text=text)])])

    result, _decision = await state.c.ai.run(role, build, input_chars=len(text) + len(system), images=len(images),
                                             summary=summary, confirmed=state.confirmed, course_id=state.course_id,
                                             preferred=choice.models or None, preferred_reason=choice.reason)
    config = state.c.settings.get().provider(result.provider)
    ptype = config.type if config else result.provider
    reported = bool(result.usage.input_tokens or result.usage.output_tokens)
    model_id = next((m["model_id"] for m in choice.models if result.model.startswith(m["model_id"])), result.model)
    cost = pricing.text_cost(ptype, model_id, result.usage.input_tokens, result.usage.output_tokens) if reported else None
    async with state.lock:
        state.meter.charge(role, cost, reported=reported, fallback=estimate)
        state.save_usage()
    if result.data is None:
        raise AIError("ai_bad_response", status=502, detail="Tomt svar")
    return result.data, f"{result.provider}/{result.model}"


# ----------------------------------------------------------------------------------------- level 1 + 2


async def course_context(state: RunState) -> dict[str, Any]:
    assert state.inv is not None
    data = course_input(state.inv, limit=state.profile.course_chars)
    key = digest([data, prompts.ANALYSIS_VERSION])
    cached = state.store.cached(state.course_id, "course", key, prompts.ANALYSIS_VERSION)
    if cached is not None:
        return cached
    text = wrap("EMNET", json.dumps(data, ensure_ascii=False, indent=1)) + \
        "\n\nAnalyser emnet. Svar på norsk bokmål (content_language: språkkoden for innholdet, f.eks. nb, nn eller en)."
    result, model = await ask(state, "illustration_analysis", system=prompts.COURSE_SYSTEM, text=text,
                              schema=prompts.COURSE_SCHEMA, schema_name="emnekontekst", max_tokens=3000,
                              summary=f"Emneanalyse: emnebeskrivelse, emneplan og modulstruktur ({len(text)} tegn)")
    result = {**result, "name": data["name"], "course_code": data["course_code"],
              "modules": [{"position": m["position"], "name": m["name"]} for m in data["modules"]]}
    state.store.cache(state.course_id, "course", key, prompts.ANALYSIS_VERSION, result, model)
    return result


async def module_context(state: RunState, module_id: str, previous: list[dict[str, Any]]) -> dict[str, Any]:
    assert state.inv is not None
    if module_id == OUTSIDE_MODULES:
        return {**outside_module_input(state.inv), "module_summary": "Sider som ikke ligger i en modul.",
                "main_theme": "", "learning_objectives": [], "key_concepts": [], "page_relations": []}
    module = state.inv.module(module_id)
    assert module is not None
    data = module_input(state.inv, module, page_chars=state.profile.module_page_chars, previous=previous)
    course = state.contexts.get("course") or {}
    key = digest([data, course.get("course_summary"), prompts.ANALYSIS_VERSION])
    cached = state.store.cached(state.course_id, f"module:{module_id}", key, prompts.ANALYSIS_VERSION)
    if cached is not None:
        return cached
    text = (wrap("EMNEKONTEKST (oppsummert)", json.dumps(_course_summary(course), ensure_ascii=False)) + "\n\n"
            + wrap("MODULEN", json.dumps(data, ensure_ascii=False, indent=1))
            + "\n\nAnalyser modulen og dens rolle i emnet. Svar på norsk bokmål.")
    result, model = await ask(state, "illustration_analysis", system=prompts.MODULE_SYSTEM, text=text,
                              schema=prompts.MODULE_SCHEMA, schema_name="modulkontekst", max_tokens=3000,
                              summary=f"Modulanalyse «{module.name}» ({len(text)} tegn)")
    result = {**result, "name": module.name, "position": module.position, "module_id": module_id}
    state.store.cache(state.course_id, f"module:{module_id}", key, prompts.ANALYSIS_VERSION, result, model)
    return result


def _course_summary(course: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "subject_area", "audience", "level", "course_summary", "learning_objectives", "key_concepts",
            "main_themes", "pedagogical_tone", "visual_direction", "content_language", "modules")
    return {k: course.get(k) for k in keys if course.get(k)}


def _module_summary(module: dict[str, Any] | None) -> dict[str, Any] | None:
    if not module:
        return None
    keys = ("name", "position", "module_summary", "main_theme", "learning_objectives", "what_students_learn",
            "builds_on", "key_concepts", "page_relations")
    return {k: module.get(k) for k in keys if module.get(k) not in (None, "", [])}


# ----------------------------------------------------------------------------------------- level 3 + 4


async def plan_page(state: RunState, url: str, module_id: str, planned_in_module: list[dict[str, Any]]) -> int:
    """Analyse one page (full content) and create its proposals. Returns the number of proposals."""
    assert state.inv is not None
    page = state.inv.pages[url]
    structure = parse_page(page.body)
    module = state.contexts.get("modules", {}).get(module_id)
    course = state.contexts.get("course") or {}
    data = page_input(page, structure, page_chars=state.profile.page_chars)
    if not structure.reliable:
        state.store.set_page_state(state.run_id, url, {"status": "skipped", "proposals": 0, "title": page.title,
                                                       "reason": "Sidens HTML er for uryddig for trygg innsetting."})
        return 0
    key = digest([data, course.get("course_summary"), (module or {}).get("module_summary"), prompts.ANALYSIS_VERSION])
    analysis = state.store.cached(state.course_id, f"page:{url}", key, prompts.ANALYSIS_VERSION)
    if analysis is None:
        text = (wrap("EMNEKONTEKST", json.dumps(_course_summary(course), ensure_ascii=False)) + "\n\n"
                + wrap("MODULKONTEKST", json.dumps(_module_summary(module), ensure_ascii=False)) + "\n\n"
                + wrap("HELE SIDEN, SEKSJON FOR SEKSJON", json.dumps(data, ensure_ascii=False, indent=1))
                + "\n\nAnalyser hele siden. Svar på norsk bokmål; content_language er språkkoden for sidens innhold.")
        analysis, model = await ask(state, "illustration_analysis", system=prompts.PAGE_SYSTEM, text=text,
                                    schema=prompts.PAGE_SCHEMA, schema_name="sidekontekst", max_tokens=5000,
                                    summary=f"Sideanalyse «{page.title}» ({len(text)} tegn)")
        analysis["_page_hash"] = page.content_hash
        state.store.cache(state.course_id, f"page:{url}", key, prompts.ANALYSIS_VERSION, analysis, model)

    existing = state.store.for_page(state.course_id, url)
    elsewhere = [{"page": i["page_title"], "concept": i["plan"].get("concept"), "motif": i["plan"].get("motif")}
                 for i in planned_in_module[-30:]]
    amount = state.options.settings.amount
    language = language_of(course, analysis)
    page_context = {**{k: v for k, v in analysis.items() if not k.startswith("_")}, "title": page.title,
                    "existing_images": data["existing_images"]}
    package = context_package(
        course=_course_summary(course), module=_module_summary(module), page=page_context, section=None,
        design={"name": state.design["name"], "style": state.design["data"].get("illustration_style"),
                "people": state.design["data"].get("people")},
        placement=None,
        requirements={"amount": amount, "max_per_page": prompts.AMOUNT_CAP[amount], "text_free": True,
                      "placements": list(PLACEMENTS)},
        language=language)
    text = (wrap("KONTEKSTPAKKE (emne, modul, side)", json.dumps(package, ensure_ascii=False, indent=1)) + "\n\n"
            + wrap("SIDENS SEKSJONER (fulltekst)", json.dumps(data["sections"], ensure_ascii=False, indent=1)) + "\n\n"
            + wrap("ILLUSTRASJONER SOM ALLEREDE FINNES PÅ SIDEN (fra EmneKlar)", json.dumps(
                [{"section": i["section"].get("title"), "concept": i["plan"].get("concept"),
                  "status": i["status_label"]} for i in existing], ensure_ascii=False)) + "\n\n"
            + wrap("ILLUSTRASJONER PLANLAGT PÅ ANDRE SIDER I MODULEN", json.dumps(elsewhere, ensure_ascii=False))
            + f"\n\nMengde: {prompts.AMOUNT_RULES[amount]}\nLag bildeplanen. Feltene skrives på norsk bokmål, "
              "unntatt image_prompt (engelsk).")
    plan, _model = await ask(state, "illustration_planning", system=prompts.PLANNING_SYSTEM, text=text,
                             schema=prompts.PLANNING_SCHEMA, schema_name="bildeplan", max_tokens=8000,
                             summary=f"Bildeplan «{page.title}» ({len(text)} tegn)")
    proposals = list(plan.get("illustrations") or [])[: prompts.AMOUNT_CAP[amount]]
    known = {i["fingerprint"] for i in state.store.for_page(state.course_id, url, statuses=(
        *EXISTING, "proposed", "queued", "generating", "failed", "rejected", "skipped"))}
    created = 0
    module_info = state.inv.module_of(url) if module_id == OUTSIDE_MODULES else state.inv.module(module_id)
    for index, proposal in enumerate(proposals):
        section_id = str(proposal.get("section_id") or "")
        if structure.section(section_id) is None:
            section_id = structure.sections[0].id if structure.sections else "s0"
        anchor = anchor_for(structure, section_id, str(proposal.get("placement") or "end_of_section"))
        section = section_context(structure, section_id)
        fp = fingerprint(state.course_id, url, section["title"], str(proposal.get("concept") or ""))
        if fp in known:
            continue  # the same illustration already exists or was rejected before – no duplicates on re-runs
        known.add(fp)
        needs_text = bool(proposal.get("needs_text_in_image"))
        status = "skipped" if needs_text else "proposed"
        plan_data = {k: proposal.get(k) for k in (
            "placement_reason", "pedagogical_purpose", "concept", "learning_goal", "motif", "composition",
            "relevant_context", "must_show", "must_not_show", "accuracy_risk", "accuracy_notes", "adds_value",
            "needs_text_in_image", "text_alternative", "decorative")}
        plan_data["page_summary"] = analysis.get("page_summary")
        plan_data["content_language"] = language
        if needs_text:
            plan_data["skip_reason"] = ("Innholdet krever tekst i bildet. Lag heller diagrammet med redigerbar HTML/"
                                        "SVG-tekst: " + str(proposal.get("text_alternative") or ""))
        row = state.store.add(
            run_id=state.run_id, course_id=state.course_id, fingerprint=fp, status=status,
            module_id=module_info.id if module_info else None,
            module_name=module_info.name if module_info else "Sider utenfor moduler", page_url=url,
            page_id=state.inv.pages[url].page_id, page_title=page.title, page_hash=page.content_hash,
            position=_position(state.inv, url) * 10 + index, section=section, anchor=anchor.as_dict(),
            plan=plan_data, prompt=str(proposal.get("image_prompt") or "")[:6000],
            decorative=bool(proposal.get("decorative")), caption_enabled=state.options.settings.captions)
        planned_in_module.append(row)
        created += 1
    state.store.set_page_state(state.run_id, url, {
        "status": "planned", "proposals": created, "title": page.title, "module_id": module_id,
        "needs_illustrations": bool(plan.get("needs_illustrations")) and created > 0,
        "reason": str(plan.get("reason") or "")[:1000], "summary": str(analysis.get("page_summary") or "")[:1000],
        "page_hash": page.content_hash, "anchors": len(candidate_anchors(structure))})
    return created


def _position(inv: Inventory, url: str) -> int:
    try:
        return inv.targets.index(url)
    except ValueError:
        return 9999


# ----------------------------------------------------------------------------------------- generation + review


def _review_copy(data: bytes, max_side: int = 1280) -> ImagePart:
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=85)
    return ImagePart.from_bytes(buffer.getvalue(), "image/jpeg")


def compose_prompt(ill: dict[str, Any], design: dict[str, Any], *, extra: str = "") -> str:
    plan = ill.get("plan") or {}
    data = DesignData.model_validate(design["data"])
    if ill.get("style_override"):
        from emneklar.features.illustrations.design import from_style

        data = from_style(str(ill["style_override"]))
    parts = [ill.get("prompt") or plan.get("motif") or ""]
    if plan.get("relevant_context"):
        parts.append(f"Educational context the image must reflect accurately: {clip(str(plan['relevant_context']), 1500)}")
    if plan.get("composition"):
        parts.append(f"Composition: {plan['composition']}")
    if plan.get("must_show"):
        parts.append("Must show: " + "; ".join(str(x) for x in plan["must_show"]))
    if plan.get("must_not_show"):
        parts.append("Must not show or misrepresent: " + "; ".join(str(x) for x in plan["must_not_show"]))
    if extra:
        parts.append(extra)
    parts.append(style_block(data, version=design.get("version")))
    parts.append(prompts.IMAGE_RULES)
    return "\n\n".join(p for p in parts if p)[:30_000]


def _references(state: RunState) -> list[tuple[str, bytes, str]]:
    image = state.choices.image.model or {}
    if not (state.options.settings.use_reference_images and image.get("reference_images")):
        return []
    out = []
    for asset_id in (state.design.get("reference_assets") or [])[: state.profile.reference_images]:
        try:
            data, media_type = state.assets.read(asset_id)
        except AppError:
            continue
        out.append((asset_id, data, media_type))
    return out


def _decide(review: dict[str, Any], plan: dict[str, Any]) -> tuple[str, list[str]]:
    scores = [int(review.get(k) or 0) for k in ("relevance", "content_alignment", "visual_quality",
                                                 "style_consistency", "supports_learning_goal")]
    issues = [str(x) for x in (review.get("issues") or [])] + [f"Feil detalj: {x}" for x in
                                                              review.get("incorrect_details") or []]
    verdict = str(review.get("verdict") or "manual_check")
    if review.get("text_in_image") == "significant":
        issues.append("Bildet inneholder tekst.")
        verdict = "revise" if verdict == "pass" else verdict
    if scores and min(scores) <= 2 and verdict == "pass":
        verdict = "revise"
    if review.get("incorrect_details") and verdict == "pass":
        verdict = "revise"
    if plan.get("accuracy_risk") == "high" and verdict == "pass":
        verdict = "manual_check"
    return verdict, issues


async def generate_one(state: RunState, ill: dict[str, Any]) -> None:
    image = state.choices.image
    if not image.available or not image.model:
        raise AppError("ai_not_configured", status=409, message=image.unavailable_reason or "Ingen bildemodell valgt.")
    references = _references(state)
    rounds = state.profile.review_rounds
    prompt = compose_prompt(ill, state.design)
    versions = list(ill.get("versions") or [])
    best: dict[str, Any] | None = None
    final_review: dict[str, Any] = {}
    verdict, issues = "manual_check", list[str]()
    state.store.update(ill["id"], status="generating", error=None)
    for attempt in range(rounds + 1):
        estimate = image_call_cost(state.c, state.choices, prompt_chars=len(prompt), references=len(references))
        state.meter.check(estimate)
        request = ImageGenerationRequest(model=image.model["id"], prompt=prompt, size=image.size, quality=image.quality,
                                         reference_images=[ImagePart.from_bytes(d, t) for _, d, t in references])
        result = await state.c.ai.generate_image(
            image.provider_id, image.model["id"], request, confirmed=state.confirmed, course_id=state.course_id,
            summary=f"Bildeprompt for «{ill['page_title']}» ({len(prompt)} tegn)"
                    + (f" og {len(references)} referansebilder fra emnet" if references else ""))
        config = state.c.settings.get().provider(image.provider_id)
        ptype = config.type if config else image.provider_id
        cost = pricing.image_cost(ptype, image.model["id"], quality=image.quality, size=image.size,
                                  prompt_tokens=result.usage.input_tokens - result.usage.input_image_tokens,
                                  output_tokens=result.usage.output_tokens,
                                  input_image_tokens=result.usage.input_image_tokens) if result.usage.reported else None
        async with state.lock:
            state.meter.charge("illustration_image", cost, reported=result.usage.reported, fallback=estimate)
            state.save_usage()
        generated = result.images[0]
        asset = state.assets.save(course_id=state.course_id, data=generated.data, media_type=generated.media_type,
                                  kind="generated", model=f"{result.provider}/{result.model}", prompt=prompt,
                                  illustration_id=ill["id"])
        review = await review_one(state, ill, generated.data, references)
        verdict, issues = _decide(review, ill.get("plan") or {})
        version = {"asset_id": asset["id"], "prompt": prompt, "attempt": attempt + 1, "verdict": verdict,
                   "scores": {k: review.get(k) for k in ("relevance", "content_alignment", "visual_quality",
                                                         "style_consistency", "supports_learning_goal")},
                   "issues": issues, "model": f"{result.provider}/{result.model}",
                   "design_version": state.design.get("version")}
        versions.append(version)
        if best is None or _score(version) >= _score(best):
            best, final_review = version, review
        state.store.update(ill["id"], versions=versions)
        if verdict != "revise" or attempt == rounds:
            break
        revised = str(review.get("revised_prompt") or "").strip()
        ill = {**ill, "prompt": revised or ill.get("prompt") or ""}
        prompt = compose_prompt(ill, state.design, extra=("Fix these problems from the previous attempt: "
                                                          + "; ".join(issues))[:1500] if issues else "")
    assert best is not None
    flagged = best["verdict"] != "pass"
    reason = str(final_review.get("manual_check_reason") or "")
    if (ill.get("plan") or {}).get("accuracy_risk") == "high":
        reason = reason or "Komplekst faglig innhold – bør kontrolleres av en fagperson."
    state.store.update(
        ill["id"], asset_id=best["asset_id"], status="flagged" if flagged else "generated",
        alt_text=str(final_review.get("alt_text") or "")[:600], caption=str(final_review.get("caption") or "")[:600],
        decorative=bool(final_review.get("decorative")), versions=versions,
        review={**{k: final_review.get(k) for k in (
            "relevance", "content_alignment", "visual_quality", "style_consistency", "supports_learning_goal",
            "text_in_image", "incorrect_details", "issues", "image_description")},
            "verdict": best["verdict"], "issues": best["issues"], "manual_check": flagged, "manual_check_reason": reason,
            "attempts": len([v for v in versions if v["prompt"]]), "label": "KI-forslag – må vurderes"})


def _score(version: dict[str, Any]) -> float:
    scores = [v for v in (version.get("scores") or {}).values() if isinstance(v, int)]
    bonus = {"pass": 10, "manual_check": 5, "revise": 0, "reject": -10}.get(version.get("verdict", ""), 0)
    return bonus + (sum(scores) / len(scores) if scores else 0)


async def review_one(state: RunState, ill: dict[str, Any], data: bytes,
                     references: list[tuple[str, bytes, str]]) -> dict[str, Any]:
    plan = ill.get("plan") or {}
    images = [_review_copy(data)]
    if references:
        images.append(_review_copy(references[0][1], 768))
    package = {
        "page_title": ill["page_title"], "module": ill.get("module_name"), "section_context": ill.get("section"),
        "pedagogical_purpose": plan.get("pedagogical_purpose"), "concept": plan.get("concept"),
        "learning_goal": plan.get("learning_goal"), "must_show": plan.get("must_show"),
        "must_not_show": plan.get("must_not_show"), "accuracy_risk": plan.get("accuracy_risk"),
        "accuracy_notes": plan.get("accuracy_notes"), "page_summary": plan.get("page_summary"),
        "visual_style_guide": state.design.get("style_prompt"), "content_language": plan.get("content_language") or "nb",
    }
    text = (("Bilde 1 er illustrasjonen som skal vurderes."
             + (" Bilde 2 er et godkjent referansebilde fra emnet (stilgrunnlag)." if references else "")) + "\n\n"
            + wrap("KRAV OG KONTEKST", json.dumps(package, ensure_ascii=False, indent=1))
            + "\n\nVurder bildet. alt_text og caption skrives på innholdets språk; øvrige felt på norsk bokmål, "
              "revised_prompt på engelsk.")
    review, _model = await ask(state, "illustration_review", system=prompts.REVIEW_SYSTEM, text=text,
                               schema=prompts.REVIEW_SCHEMA, schema_name="kvalitetskontroll", max_tokens=2500,
                               summary=f"Kvalitetskontroll av 1 generert bilde for «{ill['page_title']}»",
                               images=images)
    return review


# ----------------------------------------------------------------------------------------- the job


def _progress_label(state: RunState, url: str) -> str:
    assert state.inv is not None
    module = state.inv.module_of(url)
    return f"{module.name} › {state.inv.pages[url].title}" if module else state.inv.pages[url].title


async def run_job(ctx: JobContext, c: AppContainer, run_id: int, *, stages: tuple[str, ...], confirmed: bool,
                  illustration_ids: list[int] | None = None) -> dict[str, Any]:
    store = Store(c.db)
    run = store.run(run_id)
    options = RunOptions.model_validate(run["options"])
    choices = resolve(c, options.settings)
    profiles = DesignProfiles(c.db)
    design = profiles.get(run["profile_id"]) if run["profile_id"] else profiles.ensure(run["course_id"])
    state = RunState(c=c, run_id=run_id, course_id=run["course_id"], options=options, choices=choices,
                     meter=CostMeter.from_usage(run["usage"], options.settings.cost_limit_usd), confirmed=confirmed,
                     store=store, assets=AssetStore(c.db, c.config.illustrations_dir), design=design,
                     contexts=store.run_contexts(run_id))
    progress = ctx.progress
    phases = [s for s in STAGES if s in stages]
    try:
        if {"inventory", "context", "plan"} & set(stages):
            store.update_run(run_id, status="analyzing", job_id=ctx.job_id, error=None)
            await _analyse(ctx, state, phases)
            if options.mode == "plan" or "generate" not in stages:
                store.update_run(run_id, status="planned")
                return {"run_id": run_id, "status": "planned", "usage": state.meter.as_dict()}
        if "generate" in stages:
            store.update_run(run_id, status="generating", job_id=ctx.job_id, error=None)
            await _generate(ctx, state, phases, illustration_ids)
        if "publish" in stages and options.auto_insert:
            await _auto_insert(ctx, state, phases)
        store.update_run(run_id, status="review")
        return {"run_id": run_id, "status": "review", "usage": state.meter.as_dict()}
    except CostLimitReached as exc:
        store.update_run(run_id, status="cost_limit", error=exc.message, usage=state.meter.as_dict())
        progress.note(exc.message)
        return {"run_id": run_id, "status": "cost_limit", "message": exc.message, "usage": state.meter.as_dict()}
    except (JobCancelled, asyncio.CancelledError):
        store.update_run(run_id, status="cancelled", usage=state.meter.as_dict())
        raise
    except AppError as exc:
        store.update_run(run_id, status="failed", error=exc.message, usage=state.meter.as_dict())
        raise


async def _analyse(ctx: JobContext, state: RunState, phases: list[str]) -> None:
    progress = ctx.progress
    total = len(phases)
    progress.set_phase("inventory", "Kartlegger emnet i Canvas", index=1, count=total, determinate=False)
    run = state.store.run(state.run_id)
    scope = Scope.model_validate(run["scope"])
    api = CanvasAPI(state.c.canvas())
    t0 = progress.start("list", item="Moduler og sider", operation="Henter fra Canvas")
    state.inv = await build_inventory(api, state.course_id, scope)
    progress.finish("list", t0)
    inv = state.inv
    pages_state = (run["stats"] or {}).get("pages") or {}
    targets = list(inv.targets)
    if scope.only_missing:
        published = {i["page_url"]: i["published"].get("page_hash") for i in state.store.for_course(
            state.course_id, statuses=("published",))}
        targets = [u for u in targets if not (u in published and published[u] == inv.pages[u].content_hash)]
    state.store.merge_run_stats(state.run_id, inventory=inv.stats(), skipped=inv.skipped, targets=targets,
                                modules=[{"id": m, "name": _module_name(inv, m)} for m in inv.target_modules])
    state.store.update_run(state.run_id, limitations=inv.limitations)
    await ctx.checkpoint()

    progress.set_phase("context", "Forstår emnet og modulene", index=2, count=total, determinate=True)
    module_ids = [m for m in inv.target_modules if any(_module_key(inv, u) == m for u in targets)]
    progress.add_tasks("ai", 1)
    t0 = progress.start("ai", item=inv.course.get("name") or "Emnet", operation="Emneanalyse")
    state.contexts["course"] = await course_context(state)
    progress.finish("ai", t0)
    state.store.update_run(state.run_id, contexts=state.contexts)
    # Module context: every module in scope, in course order, each knowing the previous modules (progression).
    modules_ctx = dict(state.contexts.get("modules") or {})
    previous: list[dict[str, Any]] = []
    for module in inv.modules:
        if module.id in module_ids:
            await ctx.checkpoint()
            progress.add_tasks("module", 1)
            t0 = progress.start("module", item=module.name, operation="Modulanalyse")
            modules_ctx[module.id] = await module_context(state, module.id, previous[-4:])
            progress.finish("module", t0)
            state.contexts["modules"] = modules_ctx
            state.store.update_run(state.run_id, contexts=state.contexts)
        summary = modules_ctx.get(module.id)
        previous.append({"name": module.name, "summary": (summary or {}).get("module_summary") or ""})
    if OUTSIDE_MODULES in module_ids:
        modules_ctx[OUTSIDE_MODULES] = await module_context(state, OUTSIDE_MODULES, [])
        state.contexts["modules"] = modules_ctx
        state.store.update_run(state.run_id, contexts=state.contexts)

    progress.set_phase("plan", "Analyserer sidene og lager bildeplan", index=3, count=total, determinate=True)
    todo = [u for u in targets if (pages_state.get(u) or {}).get("status") not in ("planned", "skipped")]
    progress.add_tasks("page", len(todo))
    by_module: dict[str, list[str]] = {}
    for url in todo:
        by_module.setdefault(_module_key(inv, url), []).append(url)
    semaphore = asyncio.Semaphore(state.options.settings.concurrency)

    async def module_worker(module_id: str, urls: list[str]) -> None:
        planned = [i for i in state.store.for_run(state.run_id) if i["module_id"] == module_id]
        for url in urls:
            await ctx.checkpoint()
            async with semaphore:
                t0 = progress.start("page", item=_progress_label(state, url), operation="Sideanalyse og bildeplan")
                failed = False
                try:
                    count = await plan_page(state, url, module_id, planned)
                    if count:
                        progress.note(f"{inv.pages[url].title}: {count} foreslått")
                except CostLimitReached:
                    raise
                except AppError as exc:
                    if exc.code in ("ai_consent_required", "ai_not_configured", "ai_key_invalid"):
                        raise
                    failed = True
                    log.info("Bildeplan for %s feilet: %s", url, exc.code)
                    state.store.set_page_state(state.run_id, url, {"status": "failed", "title": inv.pages[url].title,
                                                                   "reason": exc.message})
                progress.finish("page", t0, failed=failed)

    await _gather([module_worker(m, urls) for m, urls in by_module.items()])


def _module_name(inv: Inventory, module_id: str) -> str:
    module = inv.module(module_id)
    return module.name if module else "Sider utenfor moduler"


def _module_key(inv: Inventory, url: str) -> str:
    module = inv.module_of(url)
    return module.id if module else OUTSIDE_MODULES


async def _gather(tasks: list[Any]) -> None:
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def _generate(ctx: JobContext, state: RunState, phases: list[str], ids: list[int] | None) -> None:
    progress = ctx.progress
    index = phases.index("generate") + 1 if "generate" in phases else 1
    progress.set_phase("generate", "Lager og kontrollerer bilder", index=index, count=len(phases), determinate=True)
    items = state.store.for_run(state.run_id)
    if ids is not None:
        wanted = set(ids)
        todo = [i for i in items if i["id"] in wanted]
    else:
        todo = [i for i in items if i["status"] in ("proposed", "queued", "generating", "failed") and not i["asset_id"]]
    for item in todo:
        state.store.update(item["id"], status="queued", error=None)
    progress.add_tasks("image", len(todo))
    semaphore = asyncio.Semaphore(state.options.settings.concurrency)

    async def worker(item: dict[str, Any]) -> None:
        await ctx.checkpoint()
        async with semaphore:
            await ctx.checkpoint()
            label = f"{item.get('module_name') or ''} › {item['page_title']}".strip(" ›")
            t0 = progress.start("image", item=label, operation="Bildegenerering og kvalitetskontroll")
            failed = False
            try:
                await generate_one(state, state.store.get(item["id"]))
            except CostLimitReached:
                state.store.update(item["id"], status="queued")
                raise
            except AppError as exc:
                if exc.code in ("ai_consent_required", "ai_not_configured", "ai_key_invalid"):
                    state.store.update(item["id"], status="queued")
                    raise
                failed = True
                current = state.store.get(item["id"])
                state.store.update(item["id"], status="failed" if not current["asset_id"] else "flagged",
                                   error=exc.message)
            progress.finish("image", t0, failed=failed)

    await _gather([worker(i) for i in todo])


async def _auto_insert(ctx: JobContext, state: RunState, phases: list[str]) -> None:
    """«Automatisk innsetting» (explicitly enabled for this run): images that passed the review are published via
    the change engine. Flagged images (manual check) always wait for the teacher."""
    from emneklar.features.illustrations.publish import stage_page

    ready = [i for i in state.store.for_run(state.run_id) if i["status"] == "generated" and not i["manual_check"]]
    by_page: dict[str, list[dict[str, Any]]] = {}
    for item in ready:
        state.store.update(item["id"], status="approved")
        by_page.setdefault(item["page_url"], []).append(state.store.get(item["id"]))
    change_ids = []
    for url, items in by_page.items():
        await ctx.checkpoint()
        try:
            change = await stage_page(state.c, state.course_id, url, items, usage_rights=state.options.usage_rights,
                                      folder=state.options.settings.folder)
        except AppError as exc:
            for item in items:
                state.store.update(item["id"], status="approved", error=exc.message)
            continue
        change_ids.append(change["id"])
    if change_ids:
        state.c.changes.approve(change_ids)
        await state.c.changes.apply_many(ctx, change_ids)
    state.store.refresh_from_changes(run_id=state.run_id)


def sample_prompt(course: dict[str, Any], design: dict[str, Any]) -> str:
    """A representative example image for the design step (one call, only on request)."""
    subject = course.get("subject_area") or course.get("name") or "higher education"
    themes = ", ".join((course.get("main_themes") or [])[:3])
    return compose_prompt({"prompt": f"A representative teaching illustration for a university course in {subject}"
                                     + (f", touching on {themes}" if themes else "")
                                     + ": students and a teacher engaged in a relevant learning activity.",
                           "plan": {}}, design)

