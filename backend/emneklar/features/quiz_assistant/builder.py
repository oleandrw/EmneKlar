"""Building Classic Quizzes from approved bank questions (always via the change engine).

Default: created UNPUBLISHED. "X av Y" uses a question group (pick_count).
After creation the quiz is re-saved (so Canvas recalculates points) and read
back; settings Canvas silently dropped are reported (docs/CANVAS_API.md).
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import WritePermit
from emneklar.core.changes.appliers import Applier, ChangeData, register
from emneklar.core.container import AppContainer
from emneklar.core.errors import AppError
from emneklar.core.storage.models import QuizPreset

CANVAS_TYPE = {"single_choice": "multiple_choice_question", "multiple_answers": "multiple_answers_question",
               "true_false": "true_false_question"}


class QuizSettings(BaseModel):
    quiz_type: Literal["practice_quiz", "assignment", "graded_survey", "survey"] = "practice_quiz"
    time_limit: int | None = Field(default=None, ge=1, le=600)
    shuffle_answers: bool = True
    allowed_attempts: int = Field(default=1, ge=-1, le=50)
    scoring_policy: Literal["keep_highest", "keep_latest"] = "keep_highest"
    show_correct_answers: bool = True
    show_correct_answers_last_attempt: bool = False
    hide_results: Literal["always", "until_after_last_attempt"] | None = None
    one_question_at_a_time: bool = False
    cant_go_back: bool = False
    due_at: datetime | None = None
    unlock_at: datetime | None = None
    lock_at: datetime | None = None
    published: bool = False

    @model_validator(mode="after")
    def _attempts(self) -> QuizSettings:
        if self.allowed_attempts == 0:
            raise ValueError("Antall forsøk må være minst 1 (eller ubegrenset)")
        return self


BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "Øvingsquiz": QuizSettings(quiz_type="practice_quiz", allowed_attempts=-1, show_correct_answers=True,
                              shuffle_answers=True).model_dump(mode="json"),
    "Avsluttende test": QuizSettings(quiz_type="assignment", allowed_attempts=1, time_limit=60,
                                    show_correct_answers=False, hide_results="until_after_last_attempt",
                                    shuffle_answers=True).model_dump(mode="json"),
    "Egenvurdering": QuizSettings(quiz_type="practice_quiz", allowed_attempts=-1, show_correct_answers=True,
                                 one_question_at_a_time=False, shuffle_answers=False).model_dump(mode="json"),
}


def dropped_settings(s: QuizSettings) -> list[str]:
    """Settings Canvas will silently ignore for this combination (verified against canvas-lms source)."""
    notes = []
    single = s.allowed_attempts in (0, 1)
    if single and s.scoring_policy != "keep_highest":
        notes.append("Poengregel brukes bare når studentene har flere forsøk.")
    if single and s.hide_results == "until_after_last_attempt":
        notes.append("«Skjul resultater til etter siste forsøk» krever flere forsøk – Canvas ignorerer det.")
    if s.show_correct_answers_last_attempt and (single or not s.show_correct_answers):
        notes.append("«Vis riktige svar etter siste forsøk» krever flere forsøk og at riktige svar vises.")
    if s.hide_results and s.show_correct_answers:
        notes.append("Riktige svar vises ikke når resultatene er skjult.")
    if s.cant_go_back and not s.one_question_at_a_time:
        notes.append("«Kan ikke gå tilbake» krever «Ett spørsmål om gangen».")
    return notes


def canvas_quiz_fields(title: str, description: str, s: QuizSettings) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "title": title, "description": f"<p>{escape(description)}</p>" if description else "",
        "quiz_type": s.quiz_type, "time_limit": s.time_limit, "shuffle_answers": s.shuffle_answers,
        "allowed_attempts": s.allowed_attempts, "show_correct_answers": s.show_correct_answers,
        "show_correct_answers_last_attempt": s.show_correct_answers_last_attempt, "hide_results": s.hide_results,
        "one_question_at_a_time": s.one_question_at_a_time or s.cant_go_back, "cant_go_back": s.cant_go_back,
        "published": False,
    }
    if s.allowed_attempts not in (0, 1):
        fields["scoring_policy"] = s.scoring_policy
    for key in ("due_at", "unlock_at", "lock_at"):
        value = getattr(s, key)
        if value is not None:
            fields[key] = value.isoformat()
    return fields


def settings_from_quiz(quiz: dict[str, Any]) -> QuizSettings:
    """«Kopier innstillinger fra eksisterende quiz»."""
    def dt(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        except ValueError:
            return None

    attempts = quiz.get("allowed_attempts")
    return QuizSettings(
        quiz_type=quiz.get("quiz_type") if quiz.get("quiz_type") in ("practice_quiz", "assignment", "graded_survey",
                                                                      "survey") else "practice_quiz",
        time_limit=quiz.get("time_limit") or None, shuffle_answers=bool(quiz.get("shuffle_answers")),
        allowed_attempts=int(attempts) if isinstance(attempts, int) and attempts != 0 else 1,
        scoring_policy=quiz.get("scoring_policy") if quiz.get("scoring_policy") in ("keep_highest", "keep_latest")
        else "keep_highest",
        show_correct_answers=bool(quiz.get("show_correct_answers")),
        show_correct_answers_last_attempt=bool(quiz.get("show_correct_answers_last_attempt")),
        hide_results=quiz.get("hide_results") if quiz.get("hide_results") in ("always", "until_after_last_attempt")
        else None,
        one_question_at_a_time=bool(quiz.get("one_question_at_a_time")), cant_go_back=bool(quiz.get("cant_go_back")),
        due_at=dt(quiz.get("due_at")), unlock_at=dt(quiz.get("unlock_at")), lock_at=dt(quiz.get("lock_at")),
        published=False)


class BuildRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    settings: QuizSettings = Field(default_factory=QuizSettings)
    question_ids: list[int] = Field(min_length=1, max_length=200)
    pick_count: int | None = Field(default=None, ge=1, le=200)
    points_per_question: float = Field(default=1.0, ge=0, le=100)
    group_name: str = Field(default="Spørsmål", max_length=100)
    module_id: str | None = Field(default=None, max_length=20)


def build_plan(c: AppContainer, course_id: str, request: BuildRequest) -> dict[str, Any]:
    from emneklar.features.quiz_assistant.bank import QuestionBank

    items = QuestionBank(c).get_many(request.question_ids)
    if len(items) != len(set(request.question_ids)):
        raise AppError("validation_error", message="Noen av spørsmålene finnes ikke lenger i spørsmålsbanken.")
    if any(i.course_id != course_id for i in items):
        raise AppError("validation_error", message="Spørsmålene hører til et annet emne.")
    not_approved = [i.id for i in items if i.review_status != "approved"]
    if not_approved:
        raise AppError("validation_error", message="Bare godkjente spørsmål kan brukes i en quiz.")
    total = len(items)
    pick = request.pick_count if request.pick_count and request.pick_count < total else None
    asked = pick or total
    questions = [{"bank_id": i.id, "question_type": CANVAS_TYPE[i.question_type], "stem": i.stem,
                  "answers": i.answers, "explanation": i.explanation} for i in items]
    return {
        "title": request.title, "description": request.description,
        "quiz_fields": canvas_quiz_fields(request.title, request.description, request.settings),
        "publish_after": request.settings.published, "questions": questions,
        "group": {"name": request.group_name, "pick_count": pick, "question_points": request.points_per_question}
        if pick else None,
        "points_per_question": request.points_per_question, "module_id": request.module_id,
        "summary": {"questions_total": total, "questions_asked": asked,
                    "points_possible": round(asked * request.points_per_question, 2),
                    "published": request.settings.published},
        "warnings": dropped_settings(request.settings),
    }


class QuizCreate(Applier):
    stores_created = True
    kind = "quiz.create"
    label = "Opprett klassisk quiz"
    object_type = "quiz"
    undo_note = "Kan angres ved å slette quizen EmneKlar opprettet, så lenge den ikke er publisert."

    def validate(self, change: ChangeData) -> None:
        if not change.proposed.get("questions") or not change.proposed.get("quiz_fields"):
            raise AppError("validation_error", detail="Quizen mangler spørsmål")

    async def current(self, api: CanvasAPI, change: ChangeData) -> dict[str, Any]:
        return {}

    def conflict(self, before: dict[str, Any], current: dict[str, Any]) -> bool:
        return False

    async def apply(self, api: CanvasAPI, change: ChangeData, permit: WritePermit) -> dict[str, Any]:
        plan = change.proposed
        course_id = change.course_id
        quiz = await api.create_quiz(course_id, dict(plan["quiz_fields"]), permit=permit)
        quiz_id = str(quiz["id"])
        group_id = None
        if plan.get("group"):
            group = await api.create_quiz_group(course_id, quiz_id, {
                "name": plan["group"]["name"], "pick_count": plan["group"]["pick_count"],
                "question_points": plan["group"]["question_points"]}, permit=permit)
            group_id = group.get("id")
        for position, question in enumerate(plan["questions"], start=1):
            payload: dict[str, Any] = {
                "question_name": f"Spørsmål {position}", "question_text": f"<p>{escape(question['stem'])}</p>",
                "question_type": question["question_type"], "points_possible": plan["points_per_question"],
                "position": position, "neutral_comments": question.get("explanation") or "",
                # The key is always explicit: Canvas makes the first answer correct if none has weight 100.
                "answers": [{"answer_text": a["text"], "answer_weight": 100 if a.get("correct") else 0}
                            for a in question["answers"]]}
            if group_id:
                payload["quiz_group_id"] = group_id
            await api.create_quiz_question(course_id, quiz_id, payload, permit=permit)
        # Re-save so Canvas recalculates points/question count (and publish if requested).
        await api.update_quiz(course_id, quiz_id, {"published": bool(plan.get("publish_after"))}, permit=permit)
        module_item_id = None
        if plan.get("module_id"):
            item = await api.create_module_item(course_id, str(plan["module_id"]),
                                                {"type": "Quiz", "content_id": quiz_id, "title": plan["title"]},
                                                permit=permit)
            module_item_id = item.get("id")
        stored = await api.get_quiz(course_id, quiz_id)
        requested = plan["quiz_fields"]
        dropped = [k for k in ("scoring_policy", "hide_results", "show_correct_answers", "cant_go_back",
                               "one_question_at_a_time", "time_limit", "allowed_attempts")
                   if k in requested and requested.get(k) not in (None, False) and stored.get(k) != requested.get(k)]
        return {"quiz_id": quiz_id, "html_url": stored.get("html_url"), "title": stored.get("title"),
                "question_count": stored.get("question_count"), "points_possible": stored.get("points_possible"),
                "published": stored.get("published"), "dropped_settings": dropped, "module_item_id": module_item_id}

    async def undo(self, api: CanvasAPI, change: ChangeData, before: dict[str, Any], permit: WritePermit) -> dict[str, Any]:
        created = (change.proposed.get("_created") or {})
        quiz_id = created.get("quiz_id")
        if not quiz_id:
            raise AppError("undo_not_possible", status=409)
        quiz = await api.get_quiz(change.course_id, str(quiz_id))
        if quiz.get("published"):
            raise AppError("undo_conflict", status=409, message="Quizen er publisert og kan ha besvarelser. "
                           "Avpubliser eller slett den i Canvas om nødvendig.")
        await api.delete_quiz(change.course_id, str(quiz_id), permit=permit)
        return {"deleted": quiz_id}


register(QuizCreate())


# --------------------------------------------------------------------------------- presets


def ensure_presets(c: AppContainer) -> None:
    with c.db.session() as session:
        existing = {p.name for p in session.scalars(select(QuizPreset)).all()}
        for name, settings in BUILTIN_PRESETS.items():
            if name not in existing:
                session.add(QuizPreset(name=name, settings=settings, builtin=True, is_default=False))


def preset_dict(p: QuizPreset) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "settings": p.settings, "builtin": p.builtin, "is_default": p.is_default}
