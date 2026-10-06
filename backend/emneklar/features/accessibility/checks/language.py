"""Language (3.1.2), sensory instructions (1.3.3/1.4.1) and readability guidance.

Readability (LIX) and capital letters are guidance – never reported as legal
failures.
"""

from __future__ import annotations

import re

from bs4 import Tag

from emneklar.core.canvas.html import element_path, is_hidden, norm_text, text_of
from emneklar.features.accessibility.checks.base import ContentDoc, Issue, fix

LANG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
EN_WORDS = set(
    "the and of to is in that it for on with as are this be by was from or an which at have not can will you your "
    "we they their these those there has been would should could about into than then also more such when what how "
    "all any each other our its were do does".split())
NB_WORDS = set(
    "og i er det som en et på til av for med at ikke de den har jeg vi kan skal om fra eller men så også hvis når "
    "hva hvordan alle denne dette disse deg du dere seg sin sitt sine være blir ble vil må ved etter under mellom "
    "uten både bare mer mange hver ikkje eg me dei korleis kva frå berre mykje".split())
SENSORY_PATTERNS = [
    r"\b(klikk|trykk|velg|bruk|finn|se)\w*\s+(på\s+)?(den|det|de)?\s*(røde|grønne|blå|gule|oransje|lilla|grå|svarte|"
    r"hvite|rosa)\s+\w+",
    r"\b(den|det|de)\s+(røde|grønne|blå|gule|oransje|lilla)\s+(knappen|boksen|teksten|feltet|ikonet|lenken|pilen|pila|"
    r"markeringen|ordene|delen|ruten)",
    r"\b(øverst|nederst|i|til)\s+(til\s+)?(høyre|venstre)\s*(side|hjørne|kolonne|marg)?\b",
    r"\b(markert|uthevet|skrevet|merket)\s+(i|med)\s+(rødt|grønt|blått|gult|rød|grønn|blå|gul)\b",
    r"\b(den|det)\s+(runde|firkantede|trekantede|store|lille)\s+(knappen|ikonet|boksen|symbolet)",
    r"\b(nedenfor|ovenfor|under)\s+til\s+(høyre|venstre)\b",
    r"\b(click|press|select)\s+(on\s+)?the\s+(red|green|blue|yellow|orange|round|square)\s+\w+",
    r"\b(on|to)\s+the\s+(right|left)\s+(side|corner|column)\b",
]
SENSORY = re.compile("|".join(f"(?:{p})" for p in SENSORY_PATTERNS), re.IGNORECASE)
CAPS_RUN = re.compile(r"(?:\b[A-ZÆØÅ]{2,}\b[\s,.:;!?-]+){4,}")
WORD = re.compile(r"[A-Za-zÆØÅæøåÉéÜü]+")


def detect_language(text: str) -> str | None:
    words = [w.lower() for w in WORD.findall(text)]
    if len(words) < 12:
        return None
    en = sum(1 for w in words if w in EN_WORDS) / len(words)
    nb = sum(1 for w in words if w in NB_WORDS) / len(words)
    if en >= 0.15 and en >= 2 * nb:
        return "en"
    if nb >= 0.15 and nb >= 2 * en:
        return "nb"
    return None


def _declared_lang(el: Tag) -> str | None:
    node: Tag | None = el
    while isinstance(node, Tag):
        lang = node.get("lang")
        if lang:
            return str(lang).lower().split("-")[0]
        node = node.parent if isinstance(node.parent, Tag) else None
    return None


def lix(text: str) -> tuple[float, int]:
    words = WORD.findall(text)
    sentences = max(1, len(re.findall(r"[.!?:]+(\s|$)", text)))
    if not words:
        return 0.0, 0
    long_words = sum(1 for w in words if len(w) > 6)
    return len(words) / sentences + long_words * 100 / len(words), len(words)


def check_language(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    soup = doc.soup
    for el in soup.find_all(attrs={"lang": True}):
        value = str(el.get("lang") or "").strip()
        if not LANG_RE.match(value):
            issues.append(Issue("UU-LANG-INVALID", f"Språkkoden «{value}» er ikke gyldig.", element=el,
                                fix=fix("set_lang", "Velg riktig språkkode", path=element_path(el))))

    blocks = [b for b in soup.find_all(["p", "li", "blockquote", "td", "h2", "h3", "h4"])
              if not is_hidden(b) and not b.find(["p", "li", "blockquote", "td"])]
    # Canvas sets the page language from the course/user locale, so the course language is the base –
    # an English page in a Norwegian course is read with a Norwegian voice unless it is marked up.
    page_lang = (doc.language or "nb").lower().split("-")[0]
    page_lang = "nb" if page_lang in ("no", "nn", "nb") else page_lang
    detected = [(b, detect_language(text_of(b))) for b in blocks]
    for block, lang in detected:
        if lang and lang != page_lang and _declared_lang(block) != lang:
            label = {"en": "engelsk", "nb": "norsk"}[lang]
            issues.append(Issue(
                "UU-LANG-PARTS", f"Avsnittet ser ut til å være på {label}, men er ikke språkmerket.", element=block,
                confidence="medium", evidence={"detected": lang, "page_language": page_lang},
                fix=fix("set_lang", f"Merk avsnittet som {label} (lang=\"{lang}\")", path=element_path(block),
                        lang=lang)))

    for block in blocks:
        text = text_of(block)
        match = SENSORY.search(text)
        if match:
            issues.append(Issue(
                "UU-SENSORY", f"«…{match.group(0)}…» kan avhenge av farge, form eller plassering.", element=block,
                context=text, confidence="low", key=f"sensory:{element_path(block)}"))
        caps = CAPS_RUN.search(text + " ")
        if caps:
            issues.append(Issue("UU-CAPS", f"«{norm_text(caps.group(0))[:80]}» er skrevet med store bokstaver.",
                                element=block, key=f"caps:{element_path(block)}"))

    body_text = " ".join(text_of(b) for b in soup.find_all(["p", "li"]))
    score, words = lix(body_text)
    if words >= 150 and score > 55:
        issues.append(Issue("UU-READABILITY", f"Lesbarhetsindeks (LIX) {score:.0f} – krevende tekst.",
                            key="readability", evidence={"lix": round(score, 1), "words": words}))

    for el in soup.find_all(["u", "span"]):
        if el.find_parent("a"):
            continue
        style = str(el.get("style") or "").lower().replace(" ", "")
        if el.name == "u" or "text-decoration:underline" in style:
            if text_of(el):
                issues.append(Issue("UU-UNDERLINE", f"«{text_of(el)[:60]}» er understreket, men er ikke en lenke.",
                                    element=el, fix=fix("remove_underline", "Fjern understrekingen",
                                                        path=element_path(el))))
    return issues
