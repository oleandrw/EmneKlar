"""Quiz analyzer for the global analysis (deterministic checks of Classic Quizzes)."""

from __future__ import annotations

from typing import Any

from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.snapshot import SnapObj
from emneklar.features.analysis.core import AnalysisContext, AnalysisTask, ObjectCheck
from emneklar.features.findings.store import FindingDraft, make_fingerprint
from emneklar.features.quiz_assistant.checks import QuizIssue, check_quiz
from emneklar.features.quiz_assistant.classic import Quiz, load_quiz
from emneklar.features.quiz_assistant.rules import RULES, RULESET_VERSION

DOMAIN = "quiz"


def quiz_draft(course_id: str, quiz: Quiz, issue: QuizIssue, module: str | None) -> FindingDraft:
    rule = RULES[issue.rule_id]
    question = issue.question
    location: dict[str, Any] = {}
    if module:
        location["module"] = module
    if question is not None:
        location["context"] = question.text[:400]
        object_type, object_id = "quiz_question", question.id
        title = f"{quiz.title}: {question.name or question.text[:60] or 'Spørsmål'}"
        evidence: dict[str, Any] = {"quiz_id": quiz.id, "quiz_title": quiz.title, "question_type": question.type_label,
                                    "answers": [{"text": a.text, "correct": a.correct} for a in question.answers][:12],
                                    **issue.evidence}
    else:
        object_type, object_id, title = "quiz", quiz.id, quiz.title
        evidence = {"quiz_id": quiz.id, "quiz_title": quiz.title, **issue.evidence}
    ref = f"{object_type}:{object_id}"
    return FindingDraft(
        domain=DOMAIN, rule_id=rule.id, category=rule.category, classification=rule.classification,
        test_method=rule.testability, severity=rule.severity, confidence=issue.confidence, title=rule.title,
        message=issue.message, remediation=rule.remediation,
        fingerprint=make_fingerprint(course_id, DOMAIN, rule.id, ref, issue.message if question is None else rule.id),
        object_type=object_type, object_id=object_id, object_title=title, object_url=quiz.html_url,
        location=location, evidence=evidence, ruleset_version=RULESET_VERSION)


class QuizAnalyzer:
    domain = DOMAIN

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck | None:
        return None

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        tasks = []
        for quiz_obj in ctx.view.get("quiz"):
            if not ctx.in_scope(quiz_obj):
                continue
            tasks.append(AnalysisTask(type="question", item=ctx.view.location_label(quiz_obj),
                                      operation="Kontrollerer spørsmål og fasit", domain=DOMAIN,
                                      run=self._runner(ctx, quiz_obj), objects=[quiz_obj.ref]))
        return tasks

    def _runner(self, ctx: AnalysisContext, quiz_obj: SnapObj) -> Any:
        async def run() -> list[FindingDraft]:
            try:
                quiz = await load_quiz(ctx.api, ctx.course_id, quiz_obj.canvas_id)
            except CanvasError as exc:
                ctx.limitations.append(f"Quizen «{quiz_obj.title}» kunne ikke leses: {exc.message}")
                return []
            modules = ctx.view.module_of.get(quiz_obj.ref)
            module = modules[0] if modules else None
            return [quiz_draft(ctx.course_id, quiz, issue, module) for issue in check_quiz(quiz)]

        return run
