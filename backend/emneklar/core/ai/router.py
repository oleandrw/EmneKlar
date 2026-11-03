"""Cost/performance-aware model routing.

Goal: use the least expensive / smallest model that is expected to give
adequate quality for the task. No model names are hard-coded – routing works
only on the capability registry (quality, speed, cost, context, vision,
structured output) and the user's strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from emneklar.core.storage.settings import AppSettings


@dataclass(frozen=True)
class TaskProfile:
    key: str
    label: str
    description: str
    min_quality: int  # adequate quality for a normal input
    floor_quality: int  # never go below this, even with «Prioriter lav kostnad»
    vision: bool
    structured: bool
    output_tokens: int
    complex_input_tokens: int  # above this input size the task needs one quality class more


TASKS: dict[str, TaskProfile] = {t.key: t for t in (
    TaskProfile("text_simple", "Enkel tekstomskriving", "Korte omskrivinger, for eksempel bedre lenketekst.", 1, 1,
                False, True, 500, 20_000),
    TaskProfile("text_standard", "Standard tekst", "Vanlige tekstoppgaver på én side.", 2, 1, False, True, 1500, 30_000),
    TaskProfile("alt_text", "Alt-tekst", "Forslag til alternativ tekst for bilder (bildeanalyse).", 2, 2, True, True,
                600, 10_000),
    TaskProfile("image_analysis", "Bildeanalyse", "Tolkning av bilder, for eksempel tekst i bilder.", 2, 2, True, True,
                800, 10_000),
    TaskProfile("quiz_review", "Kvalitetssjekk av quiz", "Vurderer spørsmål og fasit mot emnets innhold.", 3, 2, False,
                True, 2000, 40_000),
    TaskProfile("quiz_generation", "Quizgenerering", "Lager spørsmål forankret i emnets innhold.", 3, 2, False, True,
                8000, 30_000),
    TaskProfile("course_structure", "Emnestruktur", "Semantisk vurdering av hele emnets struktur.", 3, 3, False, True,
                3000, 30_000),
    TaskProfile("homepage_content", "Emneforside", "Tekstforslag til emnets forside.", 2, 2, False, True, 3000, 30_000),
    TaskProfile("rag_answer", "Emne-RAG: svar", "Svarer på spørsmål ut fra utdrag fra emnet, med kildehenvisninger.", 2,
                2, False, True, 2500, 30_000),
    TaskProfile("rag_query", "Emne-RAG: omskriving av søk", "Gjør vage spørsmål om til presise søk.", 1, 1, False, True,
                400, 20_000),
    TaskProfile("rag_context", "Emne-RAG: kontekstuell berikelse",
                "Én til to setninger som plasserer hvert utdrag i dokumentet og modulen.", 1, 1, False, True, 2000,
                60_000),
    TaskProfile("rag_image", "Emne-RAG: bildebeskrivelse",
                "Beskriver bilder, diagrammer og tekst i bilder (bildeanalyse).", 2, 2, True, True, 1200, 10_000),
    TaskProfile("rag_eval", "Emne-RAG: testspørsmål", "Lager testspørsmål for å måle hvor godt søket fungerer.", 1, 1,
                False, True, 1500, 20_000),
)}

#: Usage log entries that are not routed tasks (embedding models are chosen under Emne-RAG, not by the router).
USAGE_LABELS: dict[str, str] = {"rag_embedding": "Emne-RAG: embedding", "rag_transcription": "Emne-RAG: transkripsjon"}

STRATEGY_LABEL = {"auto": "Automatisk", "low_cost": "Prioriter lav kostnad", "speed": "Prioriter hastighet",
                  "quality": "Prioriter kvalitet", "manual": "Manuell styring"}


def estimate_tokens(chars: int, images: int = 0) -> int:
    """Conservative estimate without a tokenizer (~3 characters per token for Norwegian text)."""
    return chars // 3 + images * 1600


def context_class_for(tokens: int) -> int:
    if tokens <= 30_000:
        return 1
    if tokens <= 120_000:
        return 2
    if tokens <= 380_000:
        return 3
    return 4


@dataclass
class RouteDecision:
    task: str
    strategy: str
    primary: dict[str, Any] | None
    fallbacks: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    required_quality: int = 1
    min_context: int = 1
    excluded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        def short(m: dict[str, Any] | None) -> dict[str, Any] | None:
            return None if m is None else {"provider_id": m["provider_id"], "model_id": m["model_id"],
                                            "display_name": m["display_name"]}

        return {"task": self.task, "task_label": TASKS[self.task].label, "strategy": self.strategy,
                "strategy_label": STRATEGY_LABEL[self.strategy], "primary": short(self.primary),
                "fallbacks": [short(m) for m in self.fallbacks], "reason": self.reason,
                "required_quality": self.required_quality, "min_context": self.min_context, "excluded": self.excluded}


def route(task: str, settings: AppSettings, models: list[dict[str, Any]], ready: dict[str, bool], *,
          input_tokens: int = 0, needs_vision: bool | None = None) -> RouteDecision:
    """``ready`` maps provider id → whether data may be sent to it now (configured, enabled, privacy allows)."""
    profile = TASKS[task]
    strategy = settings.ai.strategy
    vision = profile.vision if needs_vision is None else needs_vision
    required = min(4, profile.min_quality + (1 if input_tokens > profile.complex_input_tokens else 0))
    if strategy == "low_cost":
        required = max(profile.floor_quality, required - 1)
    min_context = context_class_for(input_tokens + profile.output_tokens)
    excluded: list[str] = []
    usable: list[dict[str, Any]] = []
    for m in models:
        name = f"{m['display_name']} ({m['provider_id']})"
        if not m["enabled"]:
            continue
        if not m["capabilities_known"]:
            excluded.append(f"{name}: ikke klassifisert")
            continue
        if not ready.get(m["provider_id"]):
            continue
        if vision and not m["vision"]:
            excluded.append(f"{name}: mangler bildeanalyse")
            continue
        if m["context_class"] < min_context:
            excluded.append(f"{name}: for liten kontekst")
            continue
        usable.append(m)

    decision = RouteDecision(task=task, strategy=strategy, primary=None, required_quality=required,
                             min_context=min_context, excluded=excluded)
    if strategy == "manual":
        pinned = settings.ai.manual_models.get(task, "")
        provider_id, _, model_id = pinned.partition("/")
        chosen = next((m for m in usable if m["provider_id"] == provider_id and m["model_id"] == model_id), None)
        if chosen is None:
            decision.reason = ("Manuell styring: ingen modell er valgt for denne oppgaven, eller den valgte modellen er "
                               "ikke tilgjengelig.")
            return decision
        decision.primary = chosen
        decision.reason = f"Manuell styring: du har valgt {chosen['display_name']} for «{profile.label}»."
        return decision

    adequate = [m for m in usable if m["quality_class"] >= required]
    pool = adequate or sorted(usable, key=lambda m: -m["quality_class"])[:1]
    def structured_first(m: dict[str, Any]) -> int:
        return 0 if (m["structured_output"] or not profile.structured) else 1

    if strategy == "speed":
        ordered = sorted(pool, key=lambda m: (structured_first(m), -m["speed_class"], m["cost_class"], -m["quality_class"]))
    elif strategy == "quality":
        ordered = sorted(pool, key=lambda m: (structured_first(m), -m["quality_class"], m["cost_class"]))
    else:  # auto / low_cost: cheapest adequate model, then faster, then better
        ordered = sorted(pool, key=lambda m: (structured_first(m), m["cost_class"], -m["speed_class"], m["quality_class"]))
    preferred = settings.ai.task_providers.get(task)
    if preferred:
        ordered.sort(key=lambda m: 0 if m["provider_id"] == preferred else 1)
    if not ordered:
        decision.reason = "Ingen aktivert og klassifisert modell passer for oppgaven."
        return decision
    decision.primary = ordered[0]
    # Fallbacks: other adequate models, then stronger ones if everything else fails.
    rest = list(ordered[1:]) + [m for m in sorted(usable, key=lambda m: -m["quality_class"])
                                       if m not in ordered]
    decision.fallbacks = rest[:3]
    m = decision.primary
    why = {"auto": "rimeligste modell som forventes å holde nok kvalitet",
           "low_cost": "lavest mulig kostnad innenfor minimumskvaliteten",
           "speed": "raskeste modell med nok kvalitet", "quality": "beste tilgjengelige kvalitet"}[strategy]
    needs = [f"kvalitet ≥ {required}"]
    if vision:
        needs.append("bildeanalyse")
    if min_context > 1:
        needs.append(f"kontekstklasse ≥ {min_context}")
    if not adequate:
        why = "ingen modell oppfyller kvalitetskravet – bruker den beste tilgjengelige"
    decision.reason = (f"{STRATEGY_LABEL[strategy]}: {m['display_name']} ({m['provider_id']}) er valgt som {why} "
                       f"for «{profile.label}» ({', '.join(needs)}).")
    if preferred and m["provider_id"] == preferred:
        decision.reason += " Foretrukket leverandør for oppgaven er brukt."
    return decision
