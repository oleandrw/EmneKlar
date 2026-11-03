"""Plan completion requirements for module items (pure logic, no Canvas calls).

Allowed requirement/item-type combinations come from :mod:`emneklar.core.canvas.requirements`
(verified against the Canvas documentation). Existing requirements are kept unless
the user explicitly chooses «Erstatt eksisterende».
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from emneklar.core.canvas.requirements import ALLOWED, LABELS, allowed_for, describe, normalize, validate_requirement

ITEM_TYPES = ("Page", "File", "ExternalUrl", "ExternalTool", "Discussion", "Assignment", "Quiz", "SubHeader")
TYPE_LABELS = {"Page": "Side", "File": "Fil", "ExternalUrl": "Ekstern lenke", "ExternalTool": "Eksternt verktøy",
               "Discussion": "Diskusjon", "Assignment": "Oppgave", "Quiz": "Quiz", "SubHeader": "Underoverskrift"}
#: Sensible defaults per item type. «Se på» for reading material, activity-based requirements for activities.
DEFAULT_POLICY: dict[str, str | None] = {
    "Page": "must_view", "File": "must_view", "ExternalUrl": "must_view", "ExternalTool": "must_view",
    "Discussion": "must_contribute", "Assignment": "must_submit", "Quiz": "must_submit", "SubHeader": None,
}
OFFLINE_SUBMISSIONS = {"none", "on_paper", "not_graded", ""}
STATUS_LABELS = {"add": "Nytt krav", "replace": "Erstattes", "remove": "Fjernes", "keep": "Beholdes",
                 "unchanged": "Uendret", "none": "Ingen krav", "not_applicable": "Ikke aktuelt"}
CHANGING = ("add", "replace", "remove")


def _default_policy() -> dict[str, str | None]:
    return dict(DEFAULT_POLICY)


class PlanRequest(BaseModel):
    module_ids: list[str] = Field(default_factory=list, max_length=500)  # empty = whole course
    existing: Literal["keep", "replace"] = "keep"
    policy: dict[str, str | None] = Field(default_factory=_default_policy)
    min_score: float | None = Field(default=None, ge=0)
    # «All requirements / one requirement» is not offered: Canvas' API ignores it (see docs/CANVAS_API.md).
    require_sequential_progress: bool | None = None  # None = leave unchanged

    @field_validator("policy")
    @classmethod
    def _policy(cls, policy: dict[str, str | None]) -> dict[str, str | None]:
        merged = {**DEFAULT_POLICY, **policy}
        for item_type, kind in merged.items():
            if item_type not in ITEM_TYPES:
                raise ValueError(f"Ukjent elementtype {item_type}")
            if kind is not None and (kind not in ALLOWED or item_type not in ALLOWED[kind]):
                raise ValueError(f"«{LABELS.get(kind, kind)}» kan ikke brukes på {TYPE_LABELS[item_type]}")
        return merged

    @model_validator(mode="after")
    def _min_score(self) -> PlanRequest:
        if "min_score" in self.policy.values() and self.min_score is None:
            raise ValueError("Angi minstepoeng når «Oppnå minstepoeng» er valgt")
        return self


def proposed_for(item: dict[str, Any], request: PlanRequest, submission_types: dict[str, list[str]]) -> \
        tuple[dict[str, Any] | None, str | None]:
    item_type = str(item.get("type") or "")
    kind = request.policy.get(item_type)
    note = None
    if kind is None:
        return None, None
    if item_type == "Assignment" and kind in ("must_submit", "min_score"):
        types = submission_types.get(str(item.get("content_id")))
        if types is not None and set(types) <= OFFLINE_SUBMISSIONS:
            # «Levere» cannot be fulfilled without an online submission – fall back to viewing.
            kind, note = "must_view", "Oppgaven har ingen innlevering i Canvas, derfor foreslås «Se på elementet»."
    requirement: dict[str, Any] = {"type": kind}
    if kind == "min_score":
        if request.min_score is None:
            return None, "Minstepoeng er ikke angitt."
        requirement["min_score"] = float(request.min_score)
    validate_requirement(item_type, requirement)
    return requirement, note


def plan_item(item: dict[str, Any], request: PlanRequest, submission_types: dict[str, list[str]]) -> dict[str, Any]:
    item_type = str(item.get("type") or "")
    current = normalize(item.get("completion_requirement"))
    notes: list[str] = []
    if item_type not in ITEM_TYPES or not allowed_for(item_type):
        proposed, status = None, "not_applicable"
    else:
        proposed, note = proposed_for(item, request, submission_types)
        if note:
            notes.append(note)
        if current == proposed:
            status = "unchanged" if current else "none"
        elif current and request.existing == "keep":
            status, proposed = "keep", current
        elif current:
            status = "replace" if proposed else "remove"
        else:
            status = "add" if proposed else "none"
    if item.get("published") is False:
        notes.append("Elementet er upublisert.")
    return {"item_id": str(item.get("id")), "title": item.get("title") or "", "type": item_type,
            "type_label": TYPE_LABELS.get(item_type, item_type), "current": current, "current_label": describe(current),
            "proposed": proposed, "proposed_label": describe(proposed), "status": status,
            "status_label": STATUS_LABELS[status], "notes": notes, "html_url": item.get("html_url")}


def plan(modules: list[dict[str, Any]], request: PlanRequest, submission_types: dict[str, list[str]]) -> dict[str, Any]:
    wanted = set(request.module_ids)
    result: list[dict[str, Any]] = []
    settings_changes = 0
    counts = dict.fromkeys(STATUS_LABELS, 0)
    warnings: list[str] = []
    for module in modules:
        module_id = str(module.get("id"))
        if wanted and module_id not in wanted:
            continue
        rows = [plan_item(item, request, submission_types) for item in module.get("items") or []]
        for row in rows:
            counts[row["status"]] += 1
        current = {"require_sequential_progress": bool(module.get("require_sequential_progress"))}
        proposed = dict(current)
        if request.require_sequential_progress is not None:
            proposed["require_sequential_progress"] = request.require_sequential_progress
        changed = {k: v for k, v in proposed.items() if current[k] != v}
        settings_changes += bool(changed)
        final = [r["proposed"] for r in rows if r["status"] != "not_applicable"]
        if proposed["require_sequential_progress"] and any(r is None for r in final):
            warnings.append(f"«{module.get('name')}»: rekkefølge krever at elementene har krav. Elementer uten krav "
                            "hoppes over i rekkefølgen.")
        result.append({"id": module_id, "name": module.get("name") or "", "published": module.get("published"),
                       "requirement_type": module.get("requirement_type"),
                       "items": rows, "settings": {"current": current, "proposed": proposed, "changed": changed}})
    if wanted and not result:
        warnings.append("Fant ingen av de valgte modulene.")
    return {"modules": result, "counts": counts, "warnings": warnings,
            "changes": counts["add"] + counts["replace"] + counts["remove"] + settings_changes}


def options() -> dict[str, Any]:
    """Item types with the requirement kinds Canvas allows for each (for the UI)."""
    return {"item_types": [{"type": t, "label": TYPE_LABELS[t], "default": DEFAULT_POLICY[t],
                            "allowed": [{"value": k, "label": LABELS[k]} for k in allowed_for(t)]}
                           for t in ITEM_TYPES],
            "statuses": STATUS_LABELS}
