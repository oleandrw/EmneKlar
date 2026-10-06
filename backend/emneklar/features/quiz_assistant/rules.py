"""Quiz-quality rules (Classic Quizzes)."""

from __future__ import annotations

from dataclasses import dataclass

RULESET_VERSION = "2026.10.1"
CATEGORY_LABELS = {"key": "Fasit", "options": "Svaralternativer", "wording": "Formulering", "duplicates": "Duplikater",
                   "grounding": "Forankring i emnet", "coverage": "Dekning", "limits": "Begrensninger"}


@dataclass(frozen=True)
class QZRule:
    id: str
    category: str
    title: str
    classification: str
    severity: str
    testability: str
    explanation: str
    remediation: str


_RULES = [
    QZRule("QZ-NO-CORRECT", "key", "Ingen svar er merket som riktig", "violation", "critical", "deterministic",
           "Spørsmålet har ingen svaralternativer med full uttelling (vekt 100) i Canvas. Ingen studenter kan få poeng.",
           "Kontroller fasiten i Canvas og merk riktig svar."),
    QZRule("QZ-MULTIPLE-CORRECT-SINGLE", "key", "Flere riktige svar i et enkeltvalgsspørsmål", "likely_violation",
           "serious", "deterministic",
           "Spørsmålet er av typen «flervalg (ett svar)», men flere alternativer er merket som riktige.",
           "Bruk spørsmålstypen «flere svar», eller merk bare ett alternativ som riktig."),
    QZRule("QZ-ALL-CORRECT", "key", "Alle alternativer er riktige", "should_review", "moderate", "deterministic",
           "Alle svaralternativene er merket som riktige.", "Kontroller fasiten og legg til feil alternativer."),
    QZRule("QZ-DUPLICATE-ANSWERS", "options", "Like svaralternativer", "violation", "serious", "deterministic",
           "To eller flere svaralternativer har samme tekst.", "Gjør alternativene ulike."),
    QZRule("QZ-EMPTY", "wording", "Tom spørsmålstekst eller tomt alternativ", "violation", "serious", "deterministic",
           "Spørsmålet eller et svaralternativ er tomt.", "Fyll inn teksten eller fjern det tomme alternativet."),
    QZRule("QZ-FEW-OPTIONS", "options", "Få svaralternativer", "improvement", "minor", "deterministic",
           "Flervalgsspørsmålet har færre enn tre alternativer, noe som øker sjansen for å gjette riktig.",
           "Vurder flere troverdige feilsvar (distraktorer)."),
    QZRule("QZ-ABOVE-OPTION", "options", "«Alle/ingen av de ovennevnte» med blandet rekkefølge", "likely_violation",
           "serious", "deterministic",
           "Et alternativ viser til de andre alternativene («ovennevnte»), men quizen blander rekkefølgen på "
           "alternativene. Da gir alternativet ikke mening.",
           "Omformuler alternativet, eller slå av blanding av svaralternativer for denne quizen."),
    QZRule("QZ-ABOVE-WEAK", "options", "«Alle/ingen av de ovennevnte»", "improvement", "minor", "heuristic",
           "Alternativer som «alle de ovennevnte» gjør det ofte lettere å gjette riktig svar.",
           "Vurder å erstatte alternativet med et konkret feilsvar."),
    QZRule("QZ-LONGEST-CORRECT", "options", "Riktig svar er mye lengre enn de andre", "improvement", "minor", "heuristic",
           "Det riktige svaret er tydelig lengre enn feilsvarene. Det kan avsløre fasiten.",
           "Gjør alternativene omtrent like lange og like presise."),
    QZRule("QZ-NEGATION", "wording", "Nektelse i spørsmålet", "improvement", "minor", "heuristic",
           "Spørsmålet inneholder en nektelse («ikke», «unntatt»). Slike spørsmål misforstås lett.",
           "Uthev nektelsen (for eksempel med fet skrift), eller omformuler positivt."),
    QZRule("QZ-DUPLICATE-QUESTION", "duplicates", "Likt eller nesten likt spørsmål", "should_review", "moderate",
           "heuristic", "Spørsmålet er likt eller nesten likt et annet spørsmål.", "Fjern eller omformuler duplikatet."),
    QZRule("QZ-ZERO-POINTS", "wording", "Spørsmål uten poeng", "should_review", "minor", "deterministic",
           "Spørsmålet gir 0 poeng i en vurdert quiz.", "Kontroller poengene."),
    QZRule("QZ-PARTIAL-SUPPORT", "limits", "Spørsmålstypen kontrolleres bare delvis", "manual_check", "info", "manual",
           "EmneKlar kontrollerer flervalg, flere svar og sant/usant i detalj. Andre spørsmålstyper kontrolleres bare "
           "for tom tekst.", "Kontroller spørsmålet manuelt."),
    QZRule("QZ-BANK-GROUP", "limits", "Spørsmål fra spørsmålsbank kunne ikke kontrolleres", "manual_check", "info",
           "manual", "Quizen trekker spørsmål fra en spørsmålsbank. Canvas-API-et gir ikke disse spørsmålene gjennom "
           "quizen, så de er ikke kontrollert.", "Kontroller spørsmålene i spørsmålsbanken manuelt."),
    QZRule("QZ-AI-KEY", "key", "Fasiten bør kontrolleres (KI-vurdering)", "should_review", "serious", "ai",
           "En KI-modell har vurdert spørsmålet mot emnets innhold og mener fasiten kan være feil, eller at flere/ingen "
           "svar er riktige. KI-forslag – må vurderes.",
           "Les kildeutdraget og kontroller fasiten. EmneKlar endrer aldri fasit automatisk."),
    QZRule("QZ-AI-AMBIGUOUS", "wording", "Spørsmålet kan være tvetydig (KI-vurdering)", "should_review", "moderate", "ai",
           "En KI-modell mener spørsmålet eller alternativene kan tolkes på flere måter. KI-forslag – må vurderes.",
           "Vurder å presisere spørsmålet."),
    QZRule("QZ-AI-DISTRACTORS", "options", "Svake feilsvar (KI-vurdering)", "improvement", "minor", "ai",
           "En KI-modell mener ett eller flere feilsvar er lite troverdige. KI-forslag – må vurderes.",
           "Vurder mer troverdige feilsvar."),
    QZRule("QZ-AI-UNSUPPORTED", "grounding", "Spørsmålet støttes ikke av emnets innhold (KI-vurdering)",
           "should_review", "moderate", "ai",
           "KI-modellen fant ikke støtte for spørsmålet eller fasiten i det valgte emneinnholdet. Det kan bety at "
           "spørsmålet bygger på annet stoff. KI-forslag – må vurderes.",
           "Kontroller kilden for spørsmålet, eller legg innholdet til i emnet."),
]
RULES = {r.id: r for r in _RULES}
