"""Deterministic and heuristic quiz-quality checks (no AI)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from emneklar.features.course_structure.similarity import jaccard, shingles
from emneklar.features.quiz_assistant.classic import FULLY_CHECKED, Question, Quiz

ABOVE = re.compile(r"(?i)\b(alle|ingen)\s+(av\s+)?(de\s+)?(ovennevnte|over|ovenfor)\b|\b(all|none)\s+of\s+the\s+above\b|"
                   r"\bbåde\s+[a-d]\s+og\s+[a-d]\b")
NEGATION = re.compile(r"(?i)\b(ikke|unntatt|aldri|not|except|never)\b")


@dataclass
class QuizIssue:
    rule_id: str
    message: str
    question: Question | None
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: str = "high"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip("."))


def check_question(question: Question, quiz: Quiz) -> list[QuizIssue]:
    issues: list[QuizIssue] = []
    if not question.text and question.type != "text_only_question":
        issues.append(QuizIssue("QZ-EMPTY", "Spørsmålsteksten er tom.", question))
    if question.type not in FULLY_CHECKED:
        return issues
    answers = question.answers
    correct = [a for a in answers if a.correct]
    if any(not a.text for a in answers):
        issues.append(QuizIssue("QZ-EMPTY", "Et svaralternativ er tomt.", question))
    if not correct:
        issues.append(QuizIssue("QZ-NO-CORRECT", "Ingen alternativer har full uttelling.", question))
    elif question.type in ("multiple_choice_question", "true_false_question") and len(correct) > 1:
        issues.append(QuizIssue("QZ-MULTIPLE-CORRECT-SINGLE", f"{len(correct)} alternativer er merket som riktige.",
                                question, {"correct": [a.text for a in correct]}))
    if question.type == "multiple_answers_question" and answers and len(correct) == len(answers):
        issues.append(QuizIssue("QZ-ALL-CORRECT", "Alle alternativene er merket som riktige.", question))
    counts = Counter(_norm(a.text) for a in answers if a.text)
    duplicates = [text for text, n in counts.items() if n > 1]
    if duplicates:
        issues.append(QuizIssue("QZ-DUPLICATE-ANSWERS", f"Alternativet «{duplicates[0][:60]}» forekommer flere ganger.",
                                question))
    if question.type == "multiple_choice_question" and 0 < len(answers) < 3:
        issues.append(QuizIssue("QZ-FEW-OPTIONS", f"Bare {len(answers)} alternativer.", question))
    above = [a for a in answers if ABOVE.search(a.text)]
    if above:
        if quiz.settings.get("shuffle_answers"):
            issues.append(QuizIssue("QZ-ABOVE-OPTION", f"«{above[0].text[:60]}» – quizen blander alternativene.",
                                    question))
        else:
            issues.append(QuizIssue("QZ-ABOVE-WEAK", f"«{above[0].text[:60]}».", question, confidence="medium"))
    if question.type == "multiple_choice_question" and len(correct) == 1 and len(answers) >= 3:
        distractors = [len(a.text) for a in answers if not a.correct and a.text]
        if distractors:
            average = sum(distractors) / len(distractors)
            if len(correct[0].text) >= max(25, 1.8 * average):
                issues.append(QuizIssue("QZ-LONGEST-CORRECT", "Det riktige svaret er mye lengre enn feilsvarene.",
                                        question, confidence="medium"))
    if NEGATION.search(question.text) and "<strong>" not in question.text_html and "<b>" not in question.text_html \
            and not re.search(r"\b(IKKE|UNNTATT|NOT)\b", question.text):
        issues.append(QuizIssue("QZ-NEGATION", "Spørsmålet inneholder en nektelse som ikke er uthevet.", question,
                                confidence="medium"))
    graded = quiz.settings.get("quiz_type") in ("assignment", "graded_survey")
    if graded and question.points == 0 and question.group_id is None:
        issues.append(QuizIssue("QZ-ZERO-POINTS", "Spørsmålet gir 0 poeng.", question))
    return issues


def check_quiz(quiz: Quiz, other_questions: list[Question] | None = None) -> list[QuizIssue]:
    issues: list[QuizIssue] = []
    partial = [q for q in quiz.questions if q.type not in FULLY_CHECKED]
    for question in quiz.questions:
        issues.extend(check_question(question, quiz))
    if partial:
        issues.append(QuizIssue("QZ-PARTIAL-SUPPORT", f"{len(partial)} spørsmål av typer som bare kontrolleres "
                                f"delvis ({', '.join(sorted({q.type_label for q in partial}))}).", None))
    for group in quiz.bank_groups:
        issues.append(QuizIssue("QZ-BANK-GROUP", f"Gruppen «{group.get('name')}» trekker {group.get('pick_count')} "
                                "spørsmål fra en spørsmålsbank.", None, {"group_id": group.get("id")}))
    others = other_questions or []
    sh = {q.id: shingles(q.text, size=3) for q in [*quiz.questions, *others]}
    for index, question in enumerate(quiz.questions):
        if not question.text:
            continue
        # Compare with earlier questions only, so the later copy is flagged and the original is left alone.
        for other in [*quiz.questions[:index], *others]:
            same = _norm(question.text) == _norm(other.text)
            if same or jaccard(sh[question.id], sh[other.id]) >= 0.8:
                where = "i samme quiz" if other.quiz_id == question.quiz_id else f"i quiz {other.quiz_id}"
                position = f" (spørsmål {other.position})" if other.quiz_id == question.quiz_id else ""
                issues.append(QuizIssue("QZ-DUPLICATE-QUESTION", f"Spørsmålet ligner et annet spørsmål {where}{position}.",
                                        question, {"same_as": other.text[:200], "other_quiz": other.quiz_id},
                                        confidence="high" if same else "medium"))
                break
    return issues
