"""System prompts and response schemas for the assistant's AI calls.

Every call returns structured JSON (schemas below; strict-mode compatible: all properties required, no extra
properties). The models never get tools. Course text is passed as delimited data (see :mod:`privacy`).
"""

from __future__ import annotations

from typing import Any

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

IMAGE_TYPES = ["scene", "comparison", "illustration", "object", "diagram", "model", "infographic", "process",
               "concept_map"]
TEXT_TYPES = {"diagram", "model", "infographic", "process", "concept_map"}  # where short labels may help
ASPECTS = ["16:9", "3:2", "4:3", "1:1", "2:3"]
MAX_LABELS = 6
MAX_SCENES = 4

PLANNING_SYSTEM = (
    "Du er en erfaren læringsdesigner og illustratør for høyere utdanning. Du lager en pedagogisk bildeplan for én "
    "Canvas-side ut fra fire nivåer av kontekst: emnet, modulen, hele siden og den konkrete seksjonen. Les sidens "
    "struktur og mening først: overskrifter, avsnitt, lister, tabeller, eksempler og eksisterende bilder. "
    "Regler: (1) Lag en kort plan for hver illustrasjon før bildeprompten: hvilket faglig poeng bildet skal gjøre "
    "lettere å forstå (pedagogical_purpose, én setning), hva bildet konkret skal vise – personer, situasjon, handling "
    "og gjenstander (motif) – og hvor det skal stå og hvorfor (insertion_point og placement_reason). Bruk den samme "
    "planen både til bildeprompten og til plasseringen. "
    "(2) Hver illustrasjon skal støtte et konkret faglig poeng – aldri bare sidetittelen. Unngå generiske "
    "læringsbilder som bare pynter siden (studenter rundt en PC, lyspærer, bokstabler, tannhjul, hjerner, sjakkbrikker, "
    "trapper mot et mål). Foreslå bare bilder som tilfører noe teksten ikke allerede gjør tydelig; et fast antall er "
    "aldri et mål. Tilfører en illustrasjon ikke noe, skal du anbefale å la være: ingen illustrasjoner, og en kort "
    "begrunnelse i reason. "
    "(3) Plassering: velg insertion_point blant INNSETTINGSPUNKTER (id-ene). Punktene ligger bare mellom tekst som "
    "kan deles – en innledende setning og listen etter den, en overskrift og første avsnitt, et eksempel og "
    "forklaringen, og et bilde og bildeteksten deles aldri. Velg punktet rett etter den avsluttede forklaringen bildet "
    "støtter, når leseren har fått begrepene bildet viser – ofte etter en liste og avsnittet som oppsummerer den, før "
    "neste deloverskrift. Ikke før teksten har introdusert det bildet viser, og ikke midt i et resonnement. p0 (øverst "
    "på siden) bare for et åpningsbilde for hele siden. placement_reason forklarer kort hvorfor bildet står der. "
    "(4) Gjør motivet presist: tilpass personer (alder, rolle, situasjon) til målgruppen i emnekonteksten – for "
    "eksempel voksne studenter, deltidsstudenter eller lærere i videreutdanning – og til sideinnholdet, og beskriv dem "
    "i people. Når siden skiller mellom begreper eller situasjoner, kan en sammenligning (image_type comparison) med "
    f"samme oppdiktede person i to til {MAX_SCENES} scener gjøre forskjellen tydelig: beskriv hver scene kort på engelsk "
    "i scenes (ellers tom liste). Bruk ikke trapper, stiger, piler, stier eller nummererte trinn som antyder en "
    "rekkefølge eller progresjon teksten ikke beskriver; shows_sequence er true bare når teksten beskriver en "
    "rekkefølge eller prosess. "
    "(5) Vurder om bildet tilfører noe som eksisterende bilder ikke dekker; unngå å gjenta motiver som allerede er "
    "planlagt eller publisert andre steder i emnet, med mindre gjentakelsen er pedagogisk begrunnet. "
    "(6) Bildet skal være faglig korrekt: angi hva det MÅ vise og hva som IKKE må fremstilles (feil rekkefølge i en "
    "prosess, oppdiktede sammenhenger, misvisende detaljer). Vurder risikoen for faglige feil. "
    "(7) Begrens tekst i bildet. Forklar mest mulig visuelt. Tekst brukes bare når den gjør det lettere å forstå – "
    "typisk i diagrammer, modeller, infografikk, prosessillustrasjoner og begrepskart – og da som korte begreper og "
    f"tydelige etiketter (høyst {MAX_LABELS}, ett til tre ord hver), aldri lange tekstblokker, overskrifter som "
    "gjentar sidetittelen, logoer eller vannmerker. Skriv etikettene nøyaktig slik de skal stå i bildet, på samme språk "
    "som undervisningsinnholdet, i labels. Scener, sammenligninger og vanlige illustrasjoner har som regel tomme labels. "
    "(8) Velg image_type og et bildeformat som passer innholdet: 16:9 for brede scener, sammenligninger med flere "
    "scener, prosesser og tidslinjer, 3:2 for vanlige scener og illustrasjoner, 4:3 for diagrammer og modeller, 1:1 "
    "for enkeltobjekter og symboler, 2:3 for høye motiver. "
    "(9) image_prompt skrives på engelsk for bildemodellen: konkret motiv, situasjon, personer og gjenstander, "
    "komposisjon og hva som skal være i fokus, med den faglige konteksten bildet trenger. Ikke beskriv stilen – den "
    "legges til fra emnets designprofil – og ikke skriv etikettene inn i prompten (de legges til fra labels). "
    "Personer skal være oppdiktede og ikke ligne virkelige personer. "
    "(10) Ingen personopplysninger i prompten. " + DATA_RULE
)


def planning_schema(point_ids: list[str]) -> dict[str, Any]:
    """The plan's schema for one page: ``insertion_point`` must be one of the page's own insertion points."""
    return _obj({
        "needs_illustrations": {"type": "boolean"},
        "reason": STR,
        "illustrations": {"type": "array", "items": _obj({
            "insertion_point": {"type": "string", "enum": point_ids},
            "placement_reason": STR,
            "pedagogical_purpose": STR,
            "concept": STR,
            "learning_goal": STR,
            "image_type": {"type": "string", "enum": IMAGE_TYPES},
            "aspect_ratio": {"type": "string", "enum": ASPECTS},
            "motif": STR,
            "people": STR,
            "scenes": STRS,
            "shows_sequence": {"type": "boolean"},
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


PLANNING_SCHEMA = planning_schema(["p0"])

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
    "Et generisk læringsbilde som ikke viser det faglige poenget (pynt), gir lav relevans og verdict revise eller "
    "reject. Trapper, piler eller trinn som antyder en rekkefølge innholdet ikke beskriver, er en feil detalj. "
    "Du kan ikke garantere faglig korrekthet: velg verdict manual_check når innholdet er komplekst, teknisk eller "
    "vitenskapelig og bør kontrolleres av en fagperson, eller når du er usikker. Velg revise når bildet kan bli bra "
    "med en forbedret prompt (skriv den i revised_prompt, på engelsk), og reject når motivet er feil. "
    "Skriv alt_text på innholdets språk ut fra det bildet faktisk viser: konkret, kort (helst under 150 tegn), "
    "meningsbærende elementer i denne sammenhengen – det faglige poenget bildet viser, for eksempel forskjellen mellom "
    "scenene – uten «Bilde av», og ikke en gjentakelse av bildeteksten. For "
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

#: Added when the text describes no order or progression (the plan's shows_sequence is false).
NO_SEQUENCE = ("Do not use staircases, ladders, arrows, paths, podiums, numbered steps or timelines – nothing that "
               "suggests an order, ranking or progression; the ideas shown are parallel, not steps.")


def layout_rules(scenes: list[str], *, sequence: bool) -> str:
    """A comparison in several scenes: equal panels with the same fictional person, read side by side."""
    panels = "; ".join(f"Panel {n}: {scene}" for n, scene in enumerate(scenes, 1))
    return (f"Layout: {len(scenes)} equal panels side by side, separated by thin plain gutters, showing the same "
            "fictional person with the same appearance and clothing in every panel, so the difference between the "
            f"situations is what stands out. {panels}."
            + ("" if sequence else " The panels are situations to compare, not steps: no arrows, numbers or "
               "connecting lines between them."))


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
