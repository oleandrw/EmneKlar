"""Feature flags.

Flags make it possible to ship new or experimental functionality safely and
incrementally. Each flag has a default stage; the user can override it under
Innstillinger → Avanserte innstillinger. Add new flags here – never invent
ad-hoc toggles elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from emneklar.core.errors import AppError
from emneklar.core.storage.settings import AppSettings

Stage = Literal["stable", "beta", "experimental"]


@dataclass(frozen=True)
class FlagDef:
    key: str
    name: str
    description: str
    stage: Stage
    default_on: bool


FLAGS: tuple[FlagDef, ...] = (
    FlagDef("quiz_assistant", "Quizassistent",
            "Kvalitetssjekk av klassiske quizer, KI-spørsmålsbank og quizbygger.", "stable", True),
    FlagDef("homepage_builder", "Emneforside",
            "Bygg eller forbedre emnets forside med forhåndsvisning.", "stable", True),
    FlagDef("document_checks", "Dokumentanalyse (PDF og Office)",
            "Automatiske kontroller av PDF-, Word-, PowerPoint- og Excel-filer i emnet.", "beta", True),
    FlagDef("ai_alt_text", "KI-forslag til alt-tekst",
            "Bruk en bildeanalysemodell til å foreslå alternativ tekst. Forslag må alltid vurderes.", "beta", True),
    FlagDef("ai_model_discovery", "Hent modelliste fra leverandør",
            "Hent tilgjengelige modeller fra KI-leverandøren. Nye modeller må klassifiseres før bruk.", "beta", True),
    FlagDef("course_rag", "Emnets kunnskapsbase",
            "Samle emnets innhold lokalt og still spørsmål med kildehenvisninger (Canvas-verktøy).", "beta",
            True),
    FlagDef("student_journey", "Studentreisen",
            "Visualisering av rekkefølgen studentene møter innholdet i.", "stable", True),
)

_BY_KEY = {flag.key: flag for flag in FLAGS}


def is_enabled(settings: AppSettings, key: str) -> bool:
    flag = _BY_KEY.get(key)
    if flag is None:
        return False
    override = settings.advanced.feature_flags.get(key)
    return flag.default_on if override is None else bool(override)


def require(settings: AppSettings, key: str) -> None:
    if not is_enabled(settings, key):
        raise AppError("feature_disabled", status=403, detail=key)


def describe(settings: AppSettings) -> list[dict[str, object]]:
    return [
        {"key": f.key, "name": f.name, "description": f.description, "stage": f.stage,
         "default_on": f.default_on, "enabled": is_enabled(settings, f.key),
         "overridden": f.key in settings.advanced.feature_flags}
        for f in FLAGS
    ]


def known(key: str) -> bool:
    return key in _BY_KEY
