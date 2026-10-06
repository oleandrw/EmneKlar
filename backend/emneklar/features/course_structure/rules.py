"""Course-structure rules. Suggestions are advisory – nothing is ever moved silently."""

from __future__ import annotations

from dataclasses import dataclass

RULESET_VERSION = "2026.10.1"

CATEGORY_LABELS = {"placement": "Plassering", "modules": "Moduler", "naming": "Navngiving",
                   "progression": "Progresjon", "duplicates": "Duplikater", "publishing": "Publisering"}


@dataclass(frozen=True)
class STRule:
    id: str
    category: str
    title: str
    classification: str
    severity: str
    testability: str
    explanation: str
    remediation: str
    impact: str


_RULES = [
    STRule("ST-ORPHAN", "placement", "Innhold som ikke ligger i noen modul", "should_review", "moderate", "deterministic",
           "Innholdet er publisert, men ligger ikke i noen modul og er ikke lenket fra annet innhold. Studenter som "
           "navigerer via moduler, finner det trolig ikke.",
           "Legg innholdet i riktig modul, lenk til det, eller avpubliser det hvis det ikke skal brukes.",
           "Studentene kan gå glipp av innholdet."),
    STRule("ST-EMPTY-MODULE", "modules", "Tom modul", "should_review", "minor", "deterministic",
           "Modulen har ingen elementer.", "Legg til innhold eller slett modulen i Canvas.",
           "Tomme moduler gjør oversikten mer uklar."),
    STRule("ST-NO-INTRO", "modules", "Modulen mangler introduksjon", "improvement", "minor", "heuristic",
           "Modulen starter rett på innhold eller aktiviteter uten en introduksjon eller oversikt.",
           "Vurder en kort introduksjonsside først i modulen: hva studentene skal lære og gjøre.",
           "En introduksjon gjør det lettere å forstå hensikten med modulen."),
    STRule("ST-NAMING", "naming", "Uensartet navngiving av moduler", "improvement", "minor", "heuristic",
           "Navnet følger ikke samme mønster som de andre modulene i emnet.",
           "Bruk samme mønster for alle moduler, for eksempel «Modul 3 – Video».",
           "Ensartede navn gjør det lettere å orientere seg."),
    STRule("ST-ORDER-DUE", "progression", "Frister følger ikke modulrekkefølgen", "should_review", "moderate",
           "deterministic",
           "En aktivitet i en senere modul har tidligere frist enn en aktivitet i en tidligere modul.",
           "Kontroller frister og rekkefølge slik at progresjonen er tydelig.",
           "Studentene kan oppleve at de må hoppe frem og tilbake."),
    STRule("ST-DUPLICATE", "duplicates", "Mulig duplikat", "should_review", "minor", "heuristic",
           "To elementer har samme tittel eller nesten likt innhold.",
           "Kontroller om begge trengs, og fjern eller slå sammen duplikater.",
           "Duplikater kan gi motstridende eller utdatert informasjon."),
    STRule("ST-MISPLACED", "placement", "Elementet kan høre hjemme i en annen modul", "should_review", "moderate",
           "heuristic",
           "Innholdet ligner mer på innholdet i en annen modul enn på modulen det ligger i. Dette er en vurdering basert "
           "på ordbruk og må kontrolleres.",
           "Vurder om elementet bør flyttes. EmneKlar flytter ingenting uten at du godkjenner det.",
           "Riktig plassering gir en tydeligere læringssti."),
    STRule("ST-UNPUBLISHED-ITEM", "publishing", "Upublisert element i publisert modul", "should_review", "minor",
           "deterministic",
           "Elementet er ikke publisert, men ligger i en publisert modul. Studentene ser det ikke.",
           "Publiser elementet når det er klart, eller fjern det fra modulen.",
           "Studentene kan oppleve at noe mangler."),
    STRule("ST-LONG-MODULE", "modules", "Svært lang modul", "improvement", "info", "deterministic",
           "Modulen har mange elementer.", "Vurder å dele modulen opp eller bruke underoverskrifter.",
           "Lange moduler kan være uoversiktlige."),
]

RULES = {r.id: r for r in _RULES}

JOURNEY_LABEL = {"Page": "Les", "Assignment": "Innlevering", "Quiz": "Quiz", "Discussion": "Diskusjon",
                 "File": "Fil", "ExternalUrl": "Ekstern ressurs", "ExternalTool": "Verktøy", "SubHeader": "Overskrift"}
