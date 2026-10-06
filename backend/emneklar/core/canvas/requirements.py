"""Module completion requirements – the verified type/item table (docs/CANVAS_API.md).

Canvas only half-enforces this table server-side, so EmneKlar enforces it.
Never add values that are not in the official documentation.
"""

from __future__ import annotations

from typing import Any

from emneklar.core.errors import AppError

ALLOWED: dict[str, set[str]] = {
    "must_view": {"Page", "Assignment", "Quiz", "Discussion", "File", "ExternalUrl", "ExternalTool"},
    "must_contribute": {"Assignment", "Discussion", "Page"},
    "must_submit": {"Assignment", "Quiz"},
    "min_score": {"Assignment", "Quiz"},
    "must_mark_done": {"Assignment", "Page"},
}

LABELS = {
    "must_view": "Se på elementet",
    "must_contribute": "Bidra (skrive innlegg/redigere)",
    "must_submit": "Levere",
    "min_score": "Oppnå minstepoeng",
    "must_mark_done": "Merke som ferdig",
}


def allowed_for(item_type: str) -> list[str]:
    return [kind for kind, types in ALLOWED.items() if item_type in types]


def validate_requirement(item_type: str, requirement: dict[str, Any]) -> None:
    kind = str(requirement.get("type") or "")
    if kind not in ALLOWED:
        raise AppError("validation_error", detail=f"Ukjent fullføringskrav: {kind}")
    if item_type not in ALLOWED[kind]:
        raise AppError("validation_error", detail=f"«{LABELS[kind]}» kan ikke brukes på {item_type}")
    if kind == "min_score":
        try:
            if float(requirement.get("min_score")) < 0:  # type: ignore[arg-type]
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise AppError("validation_error", detail="Minstepoeng må være et tall ≥ 0") from exc


def normalize(requirement: dict[str, Any] | None) -> dict[str, Any] | None:
    """Canvas returns extra keys (e.g. ``completed``) – compare ``type`` and, for min_score, ``min_score``."""
    if not requirement or not requirement.get("type"):
        return None
    result: dict[str, Any] = {"type": requirement["type"]}
    if requirement.get("type") == "min_score" and requirement.get("min_score") is not None:
        result["min_score"] = float(requirement["min_score"])
    return result


def describe(requirement: dict[str, Any] | None) -> str:
    if not requirement:
        return "Ingen krav"
    label = LABELS.get(str(requirement.get("type")), str(requirement.get("type")))
    if requirement.get("type") == "min_score":
        return f"{label} ({requirement.get('min_score')})"
    return label
