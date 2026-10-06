"""Content-quality rules (technical quality – not accessibility, not academic quality)."""

from __future__ import annotations

from dataclasses import dataclass

RULESET_VERSION = "2026.10.1"


@dataclass(frozen=True)
class CQRule:
    id: str
    category: str
    title: str
    classification: str
    severity: str
    testability: str
    explanation: str
    remediation: str


CATEGORY_LABELS = {"links": "Lenker", "media": "Video og innebygd innhold", "html": "HTML og kode",
                   "content": "Innhold"}

_RULES = [
    CQRule("CQ-LINK-DEAD", "links", "Lenken fungerer ikke", "violation", "serious", "deterministic",
           "Lenkemålet finnes ikke (for eksempel «404 Ikke funnet», eller domenet finnes ikke). Studentene får en feilside.",
           "Finn riktig adresse og erstatt lenken, eller fjern lenken og behold teksten. EmneKlar sletter aldri lenker automatisk."),
    CQRule("CQ-LINK-INTERNAL-MISSING", "links", "Intern lenke til innhold som ikke finnes", "violation", "serious",
           "deterministic",
           "Lenken peker til en side, oppgave eller fil i emnet som ikke finnes (lenger). Dette skjer ofte når innhold "
           "er slettet eller har fått ny adresse.",
           "Pek lenken til riktig innhold i emnet."),
    CQRule("CQ-LINK-OTHER-COURSE", "links", "Lenke til et annet emne", "should_review", "moderate", "deterministic",
           "Lenken går til innhold i et annet Canvas-emne. Det skjer ofte etter kopiering fra et tidligere semester. "
           "Studentene har vanligvis ikke tilgang til det andre emnet.",
           "Erstatt lenken med tilsvarende innhold i dette emnet."),
    CQRule("CQ-LINK-UNPUBLISHED", "links", "Lenke til upublisert innhold", "should_review", "moderate", "deterministic",
           "Lenken går til innhold som ikke er publisert. Studentene får en feilmelding når de klikker.",
           "Publiser innholdet, eller fjern lenken til det er klart."),
    CQRule("CQ-LINK-TIMEOUT", "links", "Lenken svarte ikke i tide", "should_review", "moderate", "deterministic",
           "Nettstedet svarte ikke innen tidsfristen. Det kan være midlertidig. En tidsavbrudd betyr ikke at lenken er død.",
           "Prøv lenken selv senere. Kontroller på nytt med «Sjekk lenken på nytt»."),
    CQRule("CQ-LINK-AUTH", "links", "Lenken krever innlogging", "manual_check", "minor", "heuristic",
           "Lenken går til en innloggingsside eller krever tilgang. Studentene kan mangle tilgang.",
           "Kontroller at studentene har tilgang, eller legg til en forklaring ved lenken."),
    CQRule("CQ-LINK-REDIRECT", "links", "Lenken videresendes", "improvement", "minor", "deterministic",
           "Lenken videresendes til en annen adresse. Den virker, men kan slutte å virke hvis videresendingen fjernes.",
           "Vurder å oppdatere lenken til den endelige adressen."),
    CQRule("CQ-LINK-UNKNOWN", "links", "Lenken kunne ikke kontrolleres", "manual_check", "minor", "manual",
           "EmneKlar fikk ikke et sikkert svar (for eksempel «403 Ingen tilgang», serverfeil, sertifikatfeil, eller en "
           "intern adresse som av sikkerhetshensyn ikke kontrolleres). Det betyr ikke at lenken er død.",
           "Åpne lenken selv og kontroller at den virker for studentene."),
    CQRule("CQ-MEDIA-UNAVAILABLE", "media", "Videoen er ikke tilgjengelig", "violation", "serious", "deterministic",
           "Videotjenesten oppgir at videoen er fjernet, privat eller ikke kan bygges inn.",
           "Bytt til en tilgjengelig video eller lenk til en alternativ kilde."),
    CQRule("CQ-MEDIA-MISSING", "media", "Medieobjekt i Canvas ble ikke funnet", "should_review", "moderate",
           "heuristic",
           "Siden viser et medieobjekt som ikke finnes i emnets medieliste. Det kan komme fra et annet emne eller være slettet.",
           "Åpne siden i Canvas og kontroller at videoen spilles av."),
    CQRule("CQ-EMBED-BROKEN", "media", "Innebygd innhold laster ikke", "violation", "serious", "deterministic",
           "Adressen til det innebygde innholdet (iframe) finnes ikke.",
           "Erstatt eller fjern det innebygde innholdet."),
    CQRule("CQ-HTML-EMPTY-PARAGRAPHS", "html", "Mange tomme avsnitt", "improvement", "minor", "deterministic",
           "Innholdet har tomme avsnitt som brukes som mellomrom. Det gir ujevn avstand og unødvendig kode.",
           "Fjern de tomme avsnittene (Opprydding)."),
    CQRule("CQ-HTML-REDUNDANT-SPANS", "html", "Overflødige span-elementer", "improvement", "info", "deterministic",
           "Innholdet har span-elementer uten noen funksjon, ofte etter kopiering fra andre programmer.",
           "Fjern de overflødige elementene (Opprydding)."),
    CQRule("CQ-HTML-WORD", "html", "Rester fra Word", "improvement", "minor", "deterministic",
           "Innholdet har formatering kopiert fra Word (Mso-klasser, mso-stiler). Det gjør koden tung og formateringen "
           "uforutsigbar.",
           "Fjern Word-restene (Opprydding)."),
    CQRule("CQ-HTML-DEPRECATED", "html", "Utdatert HTML", "improvement", "minor", "deterministic",
           "Innholdet bruker utdaterte HTML-elementer (for eksempel font eller center).",
           "Bruk Canvas' formatering i stedet. Opprydding fjerner bare elementer uten egen formatering."),
    CQRule("CQ-HTML-DUPLICATE-STYLES", "html", "Samme stil gjentatt mange ganger", "improvement", "info",
           "deterministic",
           "Den samme inline-stilen er gjentatt på mange elementer. Det gjør innholdet tungt å vedlikeholde.",
           "Vurder å bruke Canvas' standardformatering. Stiler fjernes aldri automatisk, fordi det kan endre utseendet."),
    CQRule("CQ-HTML-INVALID", "html", "Ugyldig HTML-struktur", "should_review", "minor", "deterministic",
           "Koden har feil i strukturen (for eksempel blokker inne i avsnitt eller elementer som ikke lukkes). "
           "Nettlesere retter dette på ulike måter, og hjelpemidler kan lese innholdet feil.",
           "Rett strukturen i HTML-redigeringen, eller lag innholdet på nytt i Canvas-redigeringen."),
    CQRule("CQ-HTML-BR-SPACING", "html", "Linjeskift brukt som mellomrom", "improvement", "info", "deterministic",
           "Flere linjeskift etter hverandre brukes for å lage mellomrom.",
           "Bruk avsnitt i stedet for mange linjeskift (Opprydding)."),
    CQRule("CQ-CONTENT-EMPTY", "content", "Tomt innhold", "should_review", "moderate", "deterministic",
           "Siden eller beskrivelsen er tom.",
           "Legg inn innhold, eller fjern elementet hvis det ikke skal brukes."),
]

RULES = {r.id: r for r in _RULES}
