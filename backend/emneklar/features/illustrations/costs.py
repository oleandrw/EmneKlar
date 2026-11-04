"""Cost estimates (before a job) and the cost meter (during a job, with the teacher's limit per job).

Estimates use the indicative prices in core/ai/pricing.json and are shown as a range, never as a guaranteed price.
During the job, actual usage is recorded whenever the provider reports it (tokens); calls without reliable usage
data are counted as «uten bruksdata» and estimated. Before every paid call the meter checks that the call's estimate
fits under the limit – the job stops cleanly (status «Kostnadsgrense nådd») instead of exceeding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from emneklar.core.ai import pricing
from emneklar.core.ai.router import estimate_tokens
from emneklar.core.errors import AppError
from emneklar.features.illustrations.choices import Choices

# Expected illustrations per analysed page (the planner decides; these are only for the estimate).
EXPECTED_PER_PAGE = {"low": (0.2, 0.8), "balanced": (0.5, 1.6), "high": (1.0, 3.2)}
REGENERATION_RATE = 0.35  # share of images that need a new round when rounds are allowed (estimate)


class CostLimitReached(AppError):
    def __init__(self, spent: float, limit: float) -> None:
        super().__init__("illustration_cost_limit", status=409,
                         message=f"Kostnadsgrensen for jobben er nådd (anslått brukt {spent:.2f} av {limit:.2f} USD). "
                                 "Jobben er stoppet. Det som er laget, er lagret.")


def provider_type(choices: Choices, provider_id: str, c: Any) -> str:
    config = c.settings.get().provider(provider_id)
    return config.type if config else provider_id


def text_call_cost(c: Any, model: dict[str, Any] | None, input_chars: int, output_tokens: int,
                   images: int = 0) -> float | None:
    if model is None:
        return None
    config = c.settings.get().provider(model["provider_id"])
    ptype = config.type if config else model["provider_id"]
    return pricing.text_cost(ptype, model["model_id"], estimate_tokens(input_chars, images), output_tokens)


def image_call_cost(c: Any, choices: Choices, *, prompt_chars: int, references: int,
                    size: str | None = None) -> float | None:
    model = choices.image.model
    if not model:
        return None
    ptype = provider_type(choices, choices.image.provider_id, c)
    return pricing.image_cost(ptype, model["id"], quality=choices.image.quality, size=size or choices.image.size,
                              prompt_tokens=prompt_chars // 4, reference_images=references)


@dataclass
class Line:
    key: str
    label: str
    calls_low: float
    calls_high: float
    unit_cost: float | None

    def as_dict(self) -> dict[str, Any]:
        unit = self.unit_cost
        return {"key": self.key, "label": self.label, "calls_low": round(self.calls_low),
                "calls_high": round(self.calls_high + 0.49), "unit_cost": None if unit is None else round(unit, 4),
                "cost_low": None if unit is None else round(unit * self.calls_low, 2),
                "cost_high": None if unit is None else round(unit * self.calls_high, 2)}


def estimate(c: Any, choices: Choices, *, modules: int, pages: int, cached_pages: int, page_chars: int,
             amount: str, generate: bool, references: int, existing_images: int = 0) -> dict[str, Any]:
    """A range for a whole job. ``pages`` is the number of pages to analyse, ``page_chars`` their total text."""
    profile = choices.profile
    roles = choices.roles
    new_pages = max(0, pages - cached_pages)
    avg_page = page_chars // max(1, pages)
    context_chars = 12_000  # course and module summaries, design profile and instructions per page call
    lines = [
        Line("course", "Emneanalyse", 1, 1, text_call_cost(c, roles["illustration_analysis"].primary,
                                                            min(profile.course_chars, 4000 + modules * 600), 1500)),
        Line("modules", "Modulanalyse", modules, modules,
             text_call_cost(c, roles["illustration_analysis"].primary, 6000 + profile.module_page_chars * 6, 1500)),
        Line("pages", "Sideanalyse", new_pages, new_pages,
             text_call_cost(c, roles["illustration_analysis"].primary, min(avg_page, profile.page_chars) + context_chars,
                            2500)),
        Line("planning", "Bildeplan og bildeprompter", pages, pages,
             text_call_cost(c, roles["illustration_planning"].primary,
                            min(avg_page, profile.page_chars) + context_chars + 6000, 2500)),
    ]
    low, high = EXPECTED_PER_PAGE.get(amount, EXPECTED_PER_PAGE["balanced"])
    images_low, images_high = (pages * low, pages * high) if existing_images == 0 else (existing_images, existing_images)
    if generate:
        rounds = profile.review_rounds
        regen_high = images_high * REGENERATION_RATE * rounds
        lines.append(Line("images", "Bildegenerering", images_low, images_high + regen_high,
                          image_call_cost(c, choices, prompt_chars=4000, references=references)))
        lines.append(Line("review", "Kvalitetskontroll med alt-tekst og bildetekst", images_low,
                          images_high + regen_high,
                          text_call_cost(c, roles["illustration_review"].primary, 9000, 1200, images=1 + (
                              1 if references else 0))))
    rows = [line.as_dict() for line in lines if line.calls_high > 0]
    unpriced = [row["label"] for row in rows if row["unit_cost"] is None]
    total_low = sum(row["cost_low"] or 0 for row in rows)
    total_high = sum(row["cost_high"] or 0 for row in rows)
    return {"currency": pricing.pricing()["currency"], "lines": rows, "total_low": round(total_low, 2),
            "total_high": round(total_high, 2), "images_low": round(images_low), "images_high": round(images_high + 0.49),
            "unpriced": unpriced, "cached_pages": cached_pages, "pricing": pricing.summary(),
            "note": ("Anslaget bygger på veiledende listepriser og forventet antall bilder. Det er ikke en garantert "
                     "pris – faktisk forbruk avhenger av innholdet, modellene og leverandørens avtale.")}


@dataclass
class CostMeter:
    limit: float | None
    spent: float = 0.0
    estimated_part: float = 0.0
    calls: int = 0
    unreported: int = 0
    by_kind: dict[str, dict[str, float]] = field(default_factory=dict)

    @classmethod
    def from_usage(cls, usage: dict[str, Any], limit: float | None) -> CostMeter:
        return cls(limit=limit, spent=float(usage.get("cost_usd") or 0), estimated_part=float(
            usage.get("estimated_usd") or 0), calls=int(usage.get("calls") or 0),
                   unreported=int(usage.get("unreported_calls") or 0), by_kind=dict(usage.get("by_kind") or {}))

    def check(self, next_cost: float | None) -> None:
        if self.limit is None:
            return
        if self.spent + (next_cost or 0) > self.limit:
            raise CostLimitReached(self.spent, self.limit)

    def charge(self, kind: str, cost: float | None, *, reported: bool, fallback: float | None = None) -> None:
        self.calls += 1
        value = cost if cost is not None else fallback
        if not reported:
            self.unreported += 1
            self.estimated_part += value or 0
        self.spent += value or 0
        row = self.by_kind.setdefault(kind, {"calls": 0, "cost_usd": 0.0})
        row["calls"] += 1
        row["cost_usd"] = round(row["cost_usd"] + (value or 0), 4)

    def as_dict(self) -> dict[str, Any]:
        return {"cost_usd": round(self.spent, 4), "estimated_usd": round(self.estimated_part, 4), "calls": self.calls,
                "unreported_calls": self.unreported, "by_kind": self.by_kind, "limit_usd": self.limit,
                "currency": pricing.pricing()["currency"]}
