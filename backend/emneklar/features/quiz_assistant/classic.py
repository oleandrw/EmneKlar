"""Reading Canvas Classic Quizzes into a normalised model.

Key facts (docs/CANVAS_API.md): the answer key is ``weight`` 100 on read
(``answer_weight`` on write); questions belonging to groups linked to a
question bank are not returned by the questions endpoint.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from emneklar.core.canvas.api import CanvasAPI, answer_is_correct, answer_text
from emneklar.core.canvas.html import norm_text, parse_html

FULLY_CHECKED = {"multiple_choice_question", "true_false_question", "multiple_answers_question"}
TYPE_LABELS = {
    "multiple_choice_question": "Flervalg (ett svar)", "true_false_question": "Sant/usant",
    "multiple_answers_question": "Flere svar", "short_answer_question": "Fyll inn (kort svar)",
    "essay_question": "Langsvar", "matching_question": "Koble sammen", "numerical_question": "Numerisk",
    "fill_in_multiple_blanks_question": "Fyll inn flere felt", "multiple_dropdowns_question": "Nedtrekkslister",
    "calculated_question": "Formel", "file_upload_question": "Filopplasting", "text_only_question": "Bare tekst",
}


@dataclass
class Answer:
    id: str
    text: str
    html: str
    correct: bool
    weight: float
    comments: str = ""


@dataclass
class Question:
    id: str
    quiz_id: str
    name: str
    type: str
    text_html: str
    text: str
    points: float
    group_id: str | None
    position: int
    answers: list[Answer] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.type, self.type)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "quiz_id": self.quiz_id, "name": self.name, "type": self.type,
                "type_label": self.type_label, "text_html": self.text_html, "text": self.text, "points": self.points,
                "group_id": self.group_id, "position": self.position,
                "answers": [{"id": a.id, "text": a.text, "correct": a.correct, "weight": a.weight} for a in self.answers]}


@dataclass
class Quiz:
    id: str
    title: str
    html_url: str | None
    settings: dict[str, Any]
    questions: list[Question]
    groups: list[dict[str, Any]]

    @property
    def bank_groups(self) -> list[dict[str, Any]]:
        return [g for g in self.groups if g.get("assessment_question_bank_id")]


def parse_question(raw: dict[str, Any], quiz_id: str) -> Question:
    html = str(raw.get("question_text") or "")
    answers = []
    for a in raw.get("answers") or []:
        if not isinstance(a, dict):
            continue
        answers.append(Answer(id=str(a.get("id") or ""), text=answer_text(a), html=str(a.get("html") or ""),
                              correct=answer_is_correct(a), weight=float(a.get("weight", a.get("answer_weight")) or 0),
                              comments=str(a.get("comments") or "")))
    return Question(id=str(raw.get("id")), quiz_id=quiz_id, name=str(raw.get("question_name") or ""),
                    type=str(raw.get("question_type") or ""), text_html=html, text=norm_text(parse_html(html).get_text(" ")),
                    points=float(raw.get("points_possible") or 0),
                    group_id=str(raw["quiz_group_id"]) if raw.get("quiz_group_id") else None,
                    position=int(raw.get("position") or 0), answers=answers, raw=raw)


SETTING_KEYS = ("quiz_type", "time_limit", "shuffle_answers", "hide_results", "show_correct_answers",
                "show_correct_answers_last_attempt", "show_correct_answers_at", "hide_correct_answers_at",
                "allowed_attempts", "scoring_policy", "one_question_at_a_time", "cant_go_back", "access_code",
                "due_at", "lock_at", "unlock_at", "published", "points_possible", "question_count", "description")


async def load_quiz(api: CanvasAPI, course_id: str, quiz_id: str) -> Quiz:
    quiz, questions, groups = await asyncio.gather(api.get_quiz(course_id, quiz_id),
                                                   api.list_quiz_questions(course_id, quiz_id),
                                                   api.list_quiz_groups(course_id, quiz_id))
    return Quiz(id=str(quiz.get("id")), title=str(quiz.get("title") or ""), html_url=quiz.get("html_url"),
                settings={k: quiz.get(k) for k in SETTING_KEYS},
                questions=sorted((parse_question(q, quiz_id) for q in questions if isinstance(q, dict)),
                                 key=lambda q: q.position),
                groups=[g for g in groups if isinstance(g, dict)])
