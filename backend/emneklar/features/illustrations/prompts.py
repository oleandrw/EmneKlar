"""System prompts and response schemas for the assistant's AI calls.

Every call returns structured JSON (schemas below; strict-mode compatible: all properties required, no extra
properties). The models never get tools. Course text is passed as delimited data (see :mod:`privacy`).
"""

from __future__ import annotations

from typing import Any

from emneklar.features.illustrations.placement import PLACEMENTS
from emneklar.features.illustrations.privacy import DATA_RULE

ANALYSIS_VERSION = "1"  # bump when the analysis prompts or schemas change (invalidates the analysis cache)


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": STR}
LEVEL = {"type": "string", "enum": ["high", "medium", "low", "none"]}

# -------------------------------------------------------------------------------- level 1: course

COURSE_SYSTEM = (
    "Du er en erfaren universitetspedagog og læringsdesigner. Du analyserer et emne i Canvas for å forstå faglig "
    "innhold, målgruppe og pedagogisk uttrykk, som grunnlag for faglig presise illustrasjoner. Vær konkret og kort. "
    "Finn ikke på læringsmål – skriv bare mål som står i eller tydelig følger av innholdet, og la listen være tom "
    "ellers. " + DATA_RULE
)
COURSE_SCHEMA = _obj({
    "subject_area": STR, "audience": STR, "level": STR, "course_summary": STR,
    "learning_objectives": STRS, "key_concepts": STRS, "main_themes": STRS,
    "pedagogical_tone": STR, "visual_direction": STR, "content_language": STR,
    "sensitive_topics": STR,
})

# -------------------------------------------------------------------------------- level 2: module

MODULE_SYSTEM = (
    "Du er en erfaren universitetspedagog. Du analyserer én modul i et Canvas-emne: hovedtema, læringsmål, hva "
    "studenten skal lære, hvordan modulen bygger på tidligere moduler, og hvordan sidene henger sammen. Bruk "
    "emnekonteksten for å forstå modulens rolle i emnet. Finn ikke på læringsmål. " + DATA_RULE
)
MODULE_SCHEMA = _obj({
    "module_summary": STR, "main_theme": STR, "learning_objectives": STRS, "what_students_learn": STR,
    "builds_on": STR, "key_concepts": STRS,
    "page_relations": {"type": "array", "items": _obj({"page_url": STR, "role": STR, "summary": STR})},
})

# -------------------------------------------------------------------------------- level 3: page

PAGE_SYSTEM = (
    "Du er en erfaren universitetspedagog. Du leser HELE innholdet på én Canvas-side – alle seksjoner, forklaringer, "
    "begreper, definisjoner, eksempler, oppgaver og refleksjonsspørsmål, og eksisterende bilder og bildetekster – og "
    "beskriver hva siden forsøker å lære studenten og hvordan delene henger sammen. Bruk emne- og modulkonteksten. "
    "Vurder for hver seksjon om en illustrasjon kan gjøre faglig innhold lettere å forstå (ikke pynt). "
    "Bruk seksjons-id-ene slik de står i innholdet. " + DATA_RULE
)
PAGE_SCHEMA = _obj({
    "page_summary": STR, "learning_goal": STR,
    "key_concepts": {"type": "array", "items": _obj({"term": STR, "explanation": STR})},
    "examples": STRS, "tasks": STRS, "content_language": STR,
    "how_parts_connect": STR, "existing_images_assessment": STR,
    "sections": {"type": "array", "items": _obj({
        "section_id": STR,
        "role": {"type": "string", "enum": ["introduction", "explanation", "example", "task", "reflection", "summary",
                                            "resources", "practical", "other"]},
        "summary": STR, "illustration_potential": LEVEL, "why": STR})},
})

# -------------------------------------------------------------------------------- level 4: planning + prompts

AMOUNT_RULES = {
    "low": "Foreslå bare illustrasjoner der de tydelig gjør et sentralt faglig poeng lettere å forstå. Høyst én per "
           "side. Null er et godt svar.",
    "balanced": "Foreslå illustrasjoner der de tilfører faglig verdi. Vanligvis null til to per side, avhengig av "
                "sidens behov. Null er et godt svar når siden ikke har et naturlig behov.",
    "high": "Foreslå illustrasjoner for alle seksjoner der et bilde kan støtte forståelsen. Inntil fire per side, men "
            "aldri bilder uten faglig funksjon.",
}
AMOUNT_CAP = {"low": 1, "balanced": 2, "high": 4}

IMAGE_TYPES = ["scene", "illustration", "object", "diagram", "model", "infographic", "process", "concept_map"]
TEXT_TYPES = {"diagram", "model", "infographic", "process", "concept_map"}  # where short labels may help
ASPECTS = ["16:9", "3:2", "4:3", "1:1", "2:3"]
MAX_LABELS = 8

PLANNING_SYSTEM = (
    "Du er en erfaren læringsdesigner og illustratør for høyere utdanning. Du lager en pedagogisk bildeplan for én "
    "Canvas-side ut fra fire nivåer av kontekst: emnet, modulen, hele siden og den konkrete seksjonen. "
    "Regler: (1) Hver illustrasjon skal støtte et konkret faglig poeng i en bestemt seksjon – aldri bare sidetittelen. "
    "Foreslå bare bilder som tilfører pedagogisk verdi; et fast antall er aldri et mål, og null bilder er et godt svar. "
    "(2) Vurder om bildet tilfører noe som eksisterende bilder ikke dekker; unngå å gjenta motiver som allerede er "
    "planlagt eller publisert andre steder i emnet, med mindre gjentakelsen er pedagogisk begrunnet. "
    "(3) Bildet skal være faglig korrekt: angi hva det MÅ vise og hva som IKKE må fremstilles (feil rekkefølge i en "
    "prosess, oppdiktede sammenhenger, misvisende detaljer). Vurder risikoen for faglige feil. "
    "(4) Forklar mest mulig visuelt. Tekst i bildet brukes bare når den gjør det lettere å forstå – typisk i "
    "diagrammer, modeller, infografikk, prosessillustrasjoner og begrepskart – og da som korte begreper og tydelige "
    f"etiketter (høyst {MAX_LABELS}, ett til tre ord hver), aldri lange tekstblokker, overskrifter som gjentar "
    "sidetittelen, logoer eller vannmerker. Skriv etikettene nøyaktig slik de skal stå i bildet, på samme språk som "
    "undervisningsinnholdet, i labels. Scener, situasjoner og vanlige illustrasjoner har tomme labels. "
    "(5) Velg image_type og et bildeformat som passer innholdet: 16:9 for brede scener, prosesser og tidslinjer, 3:2 "
    "for vanlige scener og illustrasjoner, 4:3 for diagrammer og modeller, 1:1 for enkeltobjekter og symboler, 2:3 "
    "for høye motiver. "
    "(6) Velg plassering som passer leseflyten: page_start (bare når et åpningsbilde for siden/modulen gir mening), "
    "after_intro, under_heading, after_explanation, end_of_section eller before_task. "
    "(7) image_prompt skrives på engelsk for bildemodellen: konkret motiv, situasjon, personer og gjenstander, "
    "komposisjon og hva som skal være i fokus, med den faglige konteksten bildet trenger. Ikke beskriv stilen – den "
    "legges til fra emnets designprofil – og ikke skriv etikettene inn i prompten (de legges til fra labels). "
    "Personer skal være oppdiktede og ikke ligne virkelige personer. "
    "(8) Ingen personopplysninger i prompten. " + DATA_RULE
)
PLANNING_SCHEMA = _obj({
    "needs_illustrations": {"type": "boolean"},
    "reason": STR,
    "illustrations": {"type": "array", "items": _obj({
        "section_id": STR,
        "placement": {"type": "string", "enum": list(PLACEMENTS)},
        "placement_reason": STR,
        "pedagogical_purpose": STR,
        "concept": STR,
        "learning_goal": STR,
        "image_type": {"type": "string", "enum": IMAGE_TYPES},
        "aspect_ratio": {"type": "string", "enum": ASPECTS},
        "motif": STR,
        "composition": STR,
        "relevant_context": STR,
        "must_show": STRS,
        "must_not_show": STRS,
        "labels": STRS,
        "accuracy_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "accuracy_notes": STR,
        "adds_value": STR,
        "decorative": {"type": "boolean"},
        "image_prompt": STR,
    })},
})

# -------------------------------------------------------------------------------- design profile

DESIGN_SYSTEM = (
    "Du er art director for undervisningsillustrasjoner i høyere utdanning. Foreslå én gjennomgående visuell stil "
    "for alle illustrasjonene i emnet, ut fra fagområde, målgruppe og pedagogisk uttrykk. Stilen skal gi et "
    "helhetlig, profesjonelt uttrykk uten at bildene blir like. Skriv feltene på engelsk (de brukes i bildeprompter), "
    "unntatt name og rationale som skrives på norsk bokmål. Fargene oppgis som hex-koder med god kontrast. " + DATA_RULE
)
DESIGN_SCHEMA = _obj({
    "style_key": {"type": "string", "enum": ["modern_3d", "flat_minimal", "photo_realistic", "academic", "isometric",
                                             "infographic", "custom"]},
    "name": STR, "rationale": STR,
    "illustration_style": STR, "palette": STRS, "palette_description": STR, "contrast": STR, "lighting": STR,
    "composition": STR, "background": STR, "detail_level": STR, "visual_traits": STR, "avoid": STRS,
    "people": STR,
})

# -------------------------------------------------------------------------------- review (multimodal)

REVIEW_SYSTEM = (
    "Du kvalitetssikrer en KI-generert undervisningsillustrasjon. Undersøk det FAKTISKE bildet nøye og vurder det "
    "mot sideinnholdet, seksjonen og kravene: faglig relevans, samsvar med innholdet, visuell kvalitet, konsistens "
    "med emnets bildestil (og referansebildet hvis det følger med), feilaktige eller misvisende detaljer, og om "
    "bildet støtter læringsmålet. Gi karakter 1–5. "
    "Kontroller teksten i bildet: hvis det er planlagt etiketter, skal de stå der, være stavet nøyaktig som planlagt, "
    "være lesbare og faglig presise, og ingen annen tekst skal finnes (text_status correct). Er en etikett feil, "
    "feilstavet, uleselig eller plassert feil, er det errors; tekst som ikke var planlagt (også logoer og vannmerker), "
    "er unwanted; ingen tekst og ingen planlagt er none. Beskriv problemene i text_issues. "
    "Du kan ikke garantere faglig korrekthet: velg verdict manual_check når innholdet er komplekst, teknisk eller "
    "vitenskapelig og bør kontrolleres av en fagperson, eller når du er usikker. Velg revise når bildet kan bli bra "
    "med en forbedret prompt (skriv den i revised_prompt, på engelsk), og reject når motivet er feil. "
    "Skriv alt_text på innholdets språk ut fra det bildet faktisk viser: konkret, kort (helst under 150 tegn), "
    "meningsbærende elementer i denne sammenhengen, uten «Bilde av», og ikke en gjentakelse av bildeteksten. For "
    "diagrammer og modeller med etiketter skal alt_text gjengi det etikettene formidler. "
    "Sett decorative til true bare hvis bildet ikke formidler noe faglig. Skriv caption på innholdets språk: én kort "
    "setning som forklarer hvordan bildet henger sammen med fagstoffet – ikke en beskrivelse av motivet. Sett "
    "caption_adds_value til false når en bildetekst bare ville gjentatt motivet eller teksten rundt. " + DATA_RULE
)
SCORE = {"type": "integer", "enum": [1, 2, 3, 4, 5]}
REVIEW_SCHEMA = _obj({
    "relevance": SCORE, "content_alignment": SCORE, "visual_quality": SCORE, "style_consistency": SCORE,
    "supports_learning_goal": SCORE,
    "text_status": {"type": "string", "enum": ["none", "correct", "errors", "unwanted"]},
    "text_issues": STRS,
    "incorrect_details": STRS, "issues": STRS,
    "verdict": {"type": "string", "enum": ["pass", "revise", "manual_check", "reject"]},
    "manual_check_reason": STR, "revised_prompt": STR, "image_description": STR,
    "alt_text": STR, "decorative": {"type": "boolean"}, "caption": STR, "caption_adds_value": {"type": "boolean"},
})

_COMMON_RULES = ("Fictional people only; do not depict real, identifiable persons. Factually and pedagogically accurate "
                 "for higher education. Explain as much as possible visually through situations, objects, interaction, "
                 "composition and visual metaphors. No logos, brand names, watermarks or signatures.")
#: Appended to every image prompt without labels (the image models get no other instructions).
IMAGE_RULES = ("Strict requirements: absolutely no text of any kind in the image – no letters, words, numbers, labels, "
               "captions, titles or signs with writing. " + _COMMON_RULES)


def label_rules(labels: list[str], language: str) -> str:
    """Rules for an image with short labels (diagrams, models, infographics, processes)."""
    quoted = "; ".join(f'"{label}"' for label in labels)
    return (f"Text in the image: only these short labels, each spelled exactly as given (language: {language}): "
            f"{quoted}. Place each label next to the element it names, large, high-contrast and clearly legible, in a "
            "clean sans-serif typeface. No other text: no title, no headings, no sentences, no numbers that are not in "
            "the labels, no captions. " + _COMMON_RULES)
