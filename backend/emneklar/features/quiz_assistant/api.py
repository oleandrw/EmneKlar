"""Quiz Assistant API: existing quizzes, KI-spørsmålsbank and building new Classic Quizzes."""

from __future__ import annotations

import asyncio
from html import escape
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from emneklar.api.deps import get_container, require_course_id
from emneklar.core import flags
from emneklar.core.ai.base import AIMessage, AIRequest, TextPart
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.html import norm_text, parse_html
from emneklar.core.changes.appliers import ChangeData, get_applier
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError, NotFoundError
from emneklar.core.jobs.manager import JobContext
from emneklar.core.storage.models import AnalysisRun, QuizPreset
from emneklar.features.course_structure.api import latest_snapshot
from emneklar.features.findings.api import enrich
from emneklar.features.findings.store import FindingStore
from emneklar.features.quiz_assistant import ai_review
from emneklar.features.quiz_assistant.analyzer import quiz_draft
from emneklar.features.quiz_assistant.bank import (
    AnswerIn,
    BankItemIn,
    QuestionBank,
    QuestionType,
    generation_plan,
    plan_summary,
)
from emneklar.features.quiz_assistant.builder import (
    BUILTIN_PRESETS,
    BuildRequest,
    QuizSettings,
    build_plan,
    ensure_presets,
    preset_dict,
    settings_from_quiz,
)
from emneklar.features.quiz_assistant.checks import check_quiz
from emneklar.features.quiz_assistant.classic import load_quiz
from emneklar.features.quiz_assistant.retrieval import BM25, build_chunks
from emneklar.features.quiz_assistant.rules import RULESET_VERSION

router = APIRouter(prefix="/api")


def _flag(c: AppContainer) -> None:
    flags.require(c.settings.get(), "quiz_assistant")


def _quiz_findings(c: AppContainer, course_id: str) -> list[Any]:
    """Current deterministic findings plus the latest AI review results (kept in their own domain)."""
    store = FindingStore(c.db)
    rows = [*store.current(course_id, "quiz")[0], *store.current(course_id, ai_review.AI_DOMAIN)[0]]
    return [r for r in rows if r.status in ("open", "staged")]


def _require_ai(c: AppContainer, task: str, confirmed: bool) -> None:
    """Fail fast (before a job starts) when AI cannot be used or consent is missing."""
    plan = c.ai.plan(task, input_chars=4000, images=0, summary="")
    if not plan["available"]:
        raise AppError("ai_not_configured", status=409, message=plan["reason"])
    if plan["needs_confirmation"] and not confirmed:
        raise AppError("ai_consent_required", status=409)


# ------------------------------------------------------------------------- existing quizzes


@router.get("/courses/{course_id}/quizzes")
async def list_quizzes(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    quizzes = await CanvasAPI(c.canvas()).list_quizzes(course_id)
    counts: dict[str, int] = {}
    for f in _quiz_findings(c, course_id):
        quiz_id = str((f.evidence or {}).get("quiz_id") or "")
        counts[quiz_id] = counts.get(quiz_id, 0) + 1
    return {"quizzes": [{"id": str(q.get("id")), "title": q.get("title"), "quiz_type": q.get("quiz_type"),
                         "published": q.get("published"), "question_count": q.get("question_count"),
                         "points_possible": q.get("points_possible"), "html_url": q.get("html_url"),
                         "open_findings": counts.get(str(q.get("id")), 0)} for q in quizzes]}


@router.get("/courses/{course_id}/quizzes/{quiz_id}")
async def quiz_detail(course_id: str, quiz_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    quiz = await load_quiz(CanvasAPI(c.canvas()), course_id, quiz_id)
    profile = c.settings.get().analysis.regulatory_profile
    findings = [enrich(f, profile) for f in _quiz_findings(c, course_id)
                if str((f.evidence or {}).get("quiz_id")) == quiz_id]
    return {"quiz": {"id": quiz.id, "title": quiz.title, "html_url": quiz.html_url, "settings": quiz.settings,
                     "groups": quiz.groups},
            "questions": [q.as_dict() for q in quiz.questions], "findings": findings}


@router.get("/courses/{course_id}/quizzes/{quiz_id}/settings")
async def copy_settings(course_id: str, quiz_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    quiz = await CanvasAPI(c.canvas()).get_quiz(require_course_id(course_id), quiz_id)
    try:
        settings = settings_from_quiz(quiz)
    except ValidationError as exc:
        raise AppError("validation_error", message="Innstillingene i denne quizen kan ikke brukes for en ny quiz.",
                       detail=str(exc.errors()[0].get("msg"))) from exc
    return {"settings": settings.model_dump(mode="json"), "source": quiz.get("title")}


class ReviewBody(BaseModel):
    use_ai: bool = False
    confirmed: bool = False


@router.post("/courses/{course_id}/quizzes/{quiz_id}/review/prepare")
async def prepare_review(course_id: str, quiz_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    view = latest_snapshot(c, require_course_id(course_id))
    if view is None:
        return {"available": False, "reason": "Kjør en analyse av emnet først, slik at KI-sjekken kan forankres i "
                "emnets innhold.", "payload_summary": None, "needs_confirmation": False, "route": None}
    chunks = build_chunks(view)
    quiz = await load_quiz(CanvasAPI(c.canvas()), course_id, quiz_id)
    chars = sum(len(ch.text) for ch in chunks[:40])
    summary = (f"{len(quiz.questions)} quizspørsmål og utdrag fra emnets sider (inntil {min(10, len(chunks))} "
               "utdrag per gruppe av spørsmål) sendes til KI-leverandøren. Ingen studentdata sendes.")
    return c.ai.plan("quiz_review", input_chars=min(chars, 20000), images=0, summary=summary)


async def _review(job: JobContext, c: AppContainer, course_id: str, quiz_id: str, body: ReviewBody) -> dict[str, Any]:
    api = CanvasAPI(c.canvas())
    progress = job.progress
    progress.set_phase("review", "Kvalitetssjekk av quiz", index=1, count=1, determinate=True)
    progress.add_tasks("quiz", 1)
    t0 = progress.start("quiz", operation="Leser spørsmål og fasit")
    quiz = await load_quiz(api, course_id, quiz_id)
    progress.finish("quiz", t0)
    view = latest_snapshot(c, course_id)
    module = None
    if view is not None:
        names = view.module_of.get(f"quiz:{quiz_id}")
        module = names[0] if names else None
    drafts = [quiz_draft(course_id, quiz, issue, module) for issue in check_quiz(quiz)]
    discarded = 0
    used_model = None
    if body.use_ai:
        if view is None:
            raise AppError("snapshot_missing")
        chunks = build_chunks(view)
        index = BM25(chunks)
        groups = ai_review.batches(quiz.questions)
        progress.add_tasks("ai", len(groups))
        for batch in groups:
            await job.checkpoint()
            t1 = progress.start("ai", item=f"{len(batch)} spørsmål", operation="KI-vurdering mot emnets innhold")
            sources = ai_review.sources_for(index, batch)
            prompt = ai_review.batch_prompt(batch, sources)

            def build(model: str, prompt: str = prompt) -> AIRequest:
                return AIRequest(model=model, system=ai_review.SYSTEM, schema_name="quizvurdering",
                                 json_schema=ai_review.SCHEMA, max_output_tokens=4000,
                                 messages=[AIMessage(parts=[TextPart(text=prompt)])])

            result, _decision = await c.ai.run("quiz_review", build, input_chars=len(prompt),
                                               summary=f"{len(batch)} spørsmål og {len(sources)} kildeutdrag",
                                               confirmed=body.confirmed, course_id=course_id)
            used_model = result.model
            by_chunk = {s.id: s for s in sources}
            answers = {str(a.get("question_id")): a for a in (result.data or {}).get("questions") or []
                       if isinstance(a, dict)}
            for question in batch:
                if question.id in answers:
                    new, lost = ai_review.interpret(course_id, quiz, question, answers[question.id], by_chunk,
                                                    result.model, module)
                    drafts.extend(new)
                    discarded += lost
            progress.finish("ai", t1)
    objects = [f"quiz:{quiz.id}"] + [f"quiz_question:{q.id}" for q in quiz.questions]
    domains = ["quiz", ai_review.AI_DOMAIN] if body.use_ai else ["quiz"]
    with c.db.session() as session:
        run = AnalysisRun(job_id=job.job_id, course_id=course_id, domains=domains, status="complete",
                          scope={"type": "items", "objects": dict.fromkeys(domains, objects)},
                          ruleset_version=RULESET_VERSION,
                          counts={"findings": len(drafts)},
                          limitations=["KI-vurderinger er forslag og må vurderes. Påstander om fasit uten kilde som kunne "
                                       "bekreftes, ble forkastet."] if body.use_ai else [])
        session.add(run)
        session.flush()
        run_id = run.id
    FindingStore(c.db).save(run_id, course_id, drafts)
    for draft in drafts:
        progress.add_findings(f"quiz:{draft.classification}")
    return {"run_id": run_id, "findings": len(drafts), "discarded_unverified": discarded, "ai_used": body.use_ai,
            "model": used_model}


@router.post("/courses/{course_id}/quizzes/{quiz_id}/review")
async def start_review(course_id: str, quiz_id: str, body: ReviewBody,
                       c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    if body.use_ai:
        if latest_snapshot(c, course_id) is None:
            raise AppError("snapshot_missing", status=409)
        _require_ai(c, "quiz_review", body.confirmed)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await _review(ctx, c, course_id, quiz_id, body)

    return c.jobs.submit(kind="quiz_review", title="Kvalitetssjekk av quiz", runner=runner, course_id=course_id,
                         params={"quiz_id": quiz_id, "use_ai": body.use_ai, "domains": ["quiz"]},
                         supports_pause=True).public()


class StageQuestionBody(BaseModel):
    stem: str | None = Field(default=None, max_length=4000)
    answers: list[dict[str, Any]] | None = None


@router.post("/quiz/findings/{finding_id}/stage")
async def stage_question(finding_id: int, body: StageQuestionBody,
                         c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    finding = FindingStore(c.db).get(finding_id)
    fix = finding.fix or {}
    if fix.get("type") != "quiz_question_update":
        raise AppError("unsupported", message="Funnet har ikke noe forslag som kan legges i kø.")
    params = fix["params"]
    stem = (body.stem or params["stem"]).strip()
    answers = [{"text": str(a.get("text") or "").strip(), "correct": bool(a.get("correct"))}
               for a in (body.answers or params["answers"]) if str(a.get("text") or "").strip()]
    if not stem or len(answers) < 2 or not any(a["correct"] for a in answers):
        raise AppError("validation_error", message="Spørsmålet må ha tekst, minst to alternativer og minst ett riktig.")
    target = {"object_type": "quiz_question", "object_id": str(params["question_id"]),
              "quiz_id": str(params["quiz_id"]), "title": finding.object_title, "url": finding.object_url}
    applier = get_applier("quiz_question.update")
    before = await applier.current(CanvasAPI(c.canvas()), ChangeData(0, finding.course_id, applier.kind, target, {}, {}))
    old_key = sorted(str(a["text"]) for a in before["answers"] if a["correct"])
    changes_key = old_key != sorted(str(a["text"]) for a in answers if a["correct"])
    original_text = norm_text(parse_html(before["question_text"]).get_text(" "))
    if " ".join(stem.split()).lower() == " ".join(original_text.split()).lower():
        question_text = before["question_text"]  # unchanged wording: keep the original HTML as it is
    elif ai_review.has_rich_content(before["question_text"]):
        raise AppError("unsupported", message="Spørsmålsteksten inneholder bilder, tabeller eller annet innhold som "
                       "ville gått tapt. Endre teksten i Canvas, eller behold spørsmålsteksten og endre bare "
                       "svaralternativene her.")
    else:
        question_text = f"<p>{escape(stem)}</p>"
    answers = ai_review.carry_over(answers, before["answers"])
    rationale = (f"KI-forslag – må vurderes. {finding.message}"
                 + (" Forslaget ENDRER FASITEN og må kontrolleres nøye." if changes_key else ""))
    return c.changes.stage(
        course_id=finding.course_id, domain="quiz", kind="quiz_question.update",
        title=f"Quizspørsmål: {finding.object_title}", target=target, before=before,
        proposed={"question_text": question_text, "answers": answers},
        rationale=rationale, risk="high" if changes_key else "medium", requires_confirmation=changes_key,
        source={"feature": "quiz", "finding_fingerprints": [finding.fingerprint], "rule_ids": [finding.rule_id]},
        ai_generated=True, merge=True)  # edits happen before queuing; re-queuing replaces the earlier version


# ------------------------------------------------------------------------------ presets


@router.get("/quiz/presets")
async def presets(c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    ensure_presets(c)
    with c.db.session() as session:
        rows = session.scalars(select(QuizPreset).order_by(QuizPreset.builtin.desc(), QuizPreset.name)).all()
        return {"presets": [preset_dict(p) for p in rows]}


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    settings: QuizSettings


@router.post("/quiz/presets")
async def create_preset(body: PresetBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    if body.name in BUILTIN_PRESETS:
        raise AppError("validation_error", message="Navnet er reservert for en innebygd forhåndsinnstilling.")
    with c.db.session() as session:
        row = QuizPreset(name=body.name, settings=body.settings.model_dump(mode="json"), builtin=False)
        session.add(row)
        session.flush()
        return preset_dict(row)


@router.post("/quiz/presets/{preset_id}/default")
async def set_default(preset_id: int, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    """«Bruk som standard for nye quizer»."""
    with c.db.session() as session:
        target = session.get(QuizPreset, preset_id)
        if target is None:
            raise NotFoundError("not_found")
        for row in session.scalars(select(QuizPreset)).all():
            row.is_default = row.id == preset_id
        return preset_dict(target)


@router.delete("/quiz/presets/{preset_id}")
async def delete_preset(preset_id: int, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    with c.db.session() as session:
        row = session.get(QuizPreset, preset_id)
        if row is None:
            raise NotFoundError("not_found")
        if row.builtin:
            raise AppError("conflict", status=409, message="Innebygde forhåndsinnstillinger kan ikke slettes.")
        session.delete(row)
    return {"ok": True}


# ------------------------------------------------------------------------------- builder


@router.post("/courses/{course_id}/quiz-builder/preview")
async def builder_preview(course_id: str, body: BuildRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    plan = build_plan(c, require_course_id(course_id), body)
    return {"summary": plan["summary"], "warnings": plan["warnings"], "group": plan["group"],
            "questions": [{"stem": q["stem"], "type": q["question_type"]} for q in plan["questions"]]}


@router.post("/courses/{course_id}/quiz-builder/stage")
async def builder_stage(course_id: str, body: BuildRequest, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    plan = build_plan(c, course_id, body)
    summary = plan["summary"]
    rationale = (f"Ny klassisk quiz med {summary['questions_asked']} av {summary['questions_total']} spørsmål "
                 f"({summary['points_possible']} poeng). "
                 + ("Publiseres etter opprettelse." if body.settings.published else "Opprettes upublisert."))
    if plan["warnings"]:
        rationale += " Merk: " + " ".join(plan["warnings"])
    return c.changes.stage(
        course_id=course_id, domain="quiz", kind="quiz.create", title=f"Ny quiz: {body.title}",
        target={"object_type": "quiz", "object_id": "", "title": body.title},
        before={}, proposed=plan, rationale=rationale, risk="medium" if body.settings.published else "low",
        source={"feature": "quiz_builder", "bank_ids": body.question_ids})


# ------------------------------------------------------------------------------- bank


@router.get("/courses/{course_id}/bank")
async def bank_list(course_id: str, status: str | None = None, module: str | None = None, q: str | None = None,
                    c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    bank = QuestionBank(c)
    course_id = require_course_id(course_id)
    every = bank.list(course_id)
    items = bank.list(course_id, status=status, module=module, q=q) if (status or module or q) else every
    return {"items": items, "counts": {s: sum(1 for i in every if i["review_status"] == s)
                                       for s in ("draft", "approved", "rejected")}}


@router.post("/courses/{course_id}/bank")
async def bank_create(course_id: str, body: BankItemIn, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    return QuestionBank(c).create(require_course_id(course_id), body)


class BankPatch(BaseModel):
    question_type: QuestionType | None = None
    stem: str | None = Field(default=None, min_length=3, max_length=4000)
    answers: list[AnswerIn] | None = Field(default=None, min_length=2, max_length=10)
    explanation: str | None = Field(default=None, max_length=4000)
    module_name: str | None = Field(default=None, max_length=500)  # null clears the module
    module_id: str | None = Field(default=None, max_length=64)
    topic: str | None = Field(default=None, max_length=300)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    review_status: Literal["draft", "approved", "rejected"] | None = None


@router.patch("/bank/{item_id}")
async def bank_update(item_id: int, body: BankPatch, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    fields = body.model_dump(exclude_unset=True)
    if "answers" in fields and fields["answers"] is not None:
        fields["answers"] = [{"text": a["text"].strip(), "correct": a["correct"]} for a in fields["answers"]
                             if a["text"].strip()]
    return QuestionBank(c).update(item_id, fields)


@router.delete("/bank/{item_id}")
async def bank_delete(item_id: int, c: AppContainer = Depends(get_container)) -> dict[str, bool]:
    _flag(c)
    QuestionBank(c).delete(item_id)
    return {"ok": True}


def _all_types() -> list[QuestionType]:
    return ["single_choice", "multiple_answers", "true_false"]


class GenerateBody(BaseModel):
    module_ids: list[str] = Field(default_factory=list, max_length=100)
    count: int = Field(default=20, ge=1, le=60)
    types: list[QuestionType] = Field(default_factory=_all_types, min_length=1)
    confirmed: bool = False


@router.post("/courses/{course_id}/bank/generate/prepare")
async def generate_prepare(course_id: str, body: GenerateBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    view = latest_snapshot(c, require_course_id(course_id))
    if view is None:
        return {"available": False, "reason": "Kjør en analyse av emnet først, slik at spørsmålene kan forankres i "
                "emnets innhold.", "payload_summary": None, "needs_confirmation": False, "route": None}
    chunks = build_chunks(view, module_ids=body.module_ids or None)
    if not chunks:
        return {"available": False, "reason": "Fant ikke nok tekstinnhold i valgt omfang.", "payload_summary": None,
                "needs_confirmation": False, "route": None}
    selection = generation_plan(chunks, body.count)
    summary, chars = plan_summary(selection)
    largest = max(sum(len(ch.text) for ch in batch) for batch in selection)
    plan = c.ai.plan("quiz_generation", input_chars=largest, images=0, summary=summary)
    return {**plan, "chunks": len(chunks), "pages": len({ch.object_ref for ch in chunks}), "characters": chars}


@router.post("/courses/{course_id}/bank/generate")
async def generate(course_id: str, body: GenerateBody, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    view = latest_snapshot(c, course_id)
    if view is None:
        raise AppError("snapshot_missing", status=409)
    _require_ai(c, "quiz_generation", body.confirmed)

    async def runner(ctx: JobContext) -> dict[str, Any]:
        return await QuestionBank(c).generate(ctx, course_id, view, module_ids=body.module_ids, count=body.count,
                                              types=list(body.types), confirmed=body.confirmed)

    return c.jobs.submit(kind="bank_generate", title="Lager spørsmål til KI-spørsmålsbanken", runner=runner,
                         course_id=course_id, params={"count": body.count}, supports_pause=True).public()


@router.get("/courses/{course_id}/bank/coverage")
async def coverage(course_id: str, c: AppContainer = Depends(get_container)) -> dict[str, Any]:
    _flag(c)
    course_id = require_course_id(course_id)
    return await asyncio.to_thread(QuestionBank(c).coverage, course_id, latest_snapshot(c, course_id))
