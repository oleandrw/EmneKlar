"""Tokens for keyword search: Norwegian (Snowball) stemming and stop words.

FTS5 has no Norwegian stemmer, so documents and queries are stemmed here and FTS5 indexes the stems. The
stemmer follows the Snowball algorithm for Norwegian (snowballstem.org/algorithms/norwegian/stemmer.html).
English words pass through mostly unchanged, which is fine for BM25.
"""

from __future__ import annotations

import re

VOWELS = set("aeiouyæåø")
_STEP1 = sorted(
    "a e ede ande ende ane ene hetene en heten ar er heter as es edes endes enes hetenes ens hetens ers ets et het "
    "ast".split(), key=len, reverse=True)
_STEP1_ALL = sorted([*_STEP1, "erte", "ert", "s"], key=len, reverse=True)
_STEP3 = sorted("leg eleg ig eig lig elig els lov elov slov hetslov".split(), key=len, reverse=True)
_S_ENDING = set("bcdfghjlmnoprtvyz")
WORD = re.compile(r"[0-9a-zæøåäöüéèáàóòúùíìâêîôûç]+", re.IGNORECASE)

STOPWORDS = frozenset(
    "og i er det som en et på til av for med at ikke de den har jeg vi kan skal om fra eller men så også hvis når "
    "hva hvordan hvem hvor hvilke hvilken hvilket alle denne dette disse deg du dere seg sin sitt sine være blir ble "
    "vil må ved etter under mellom uten både bare mer hver eg me dei korleis kva frå berre kvar kven noko nokon "
    "meg min mitt mine oss vår vårt våre han hun ho hen dem deres hans hennes dens dets the and of to is in that it "
    "for on with as are this be by was from or an which at have not can will you your what how who why where when "
    "do does did a".split())


def _r1(word: str) -> int:
    for i in range(1, len(word)):
        if word[i] not in VOWELS and word[i - 1] in VOWELS:
            return max(3, i + 1)
    return len(word)


def stem(word: str) -> str:
    word = word.lower()
    if len(word) < 4 or word.isdigit():
        return word
    r1 = _r1(word)
    # Step 1: the longest matching suffix in R1 decides the action.
    found = next((s for s in _STEP1_ALL if word.endswith(s) and len(word) - len(s) >= r1), None)
    if found in ("erte", "ert"):
        word = word[: -len(found)] + "er"
    elif found == "s":
        before = word[-2]
        if before in _S_ENDING or (before == "k" and len(word) > 2 and word[-3] not in VOWELS):
            word = word[:-1]
    elif found:
        word = word[: -len(found)]
    # Step 2
    if word.endswith(("dt", "vt")) and len(word) - 2 >= r1:
        word = word[:-1]
    # Step 3
    for suffix in _STEP3:
        if word.endswith(suffix) and len(word) - len(suffix) >= r1:
            word = word[: -len(suffix)]
            break
    return word


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text or "")]


def stems(text: str, *, keep_stopwords: bool = False) -> list[str]:
    return [stem(w) for w in words(text) if (keep_stopwords or w not in STOPWORDS) and (len(w) > 1 or w.isdigit())]


def stem_string(text: str) -> str:
    """Space-separated stems, as stored in the FTS5 index."""
    return " ".join(stems(text))


def fts_query(text: str) -> str | None:
    """A safe FTS5 MATCH expression (OR of quoted stems, longer stems also as prefixes), or None."""
    terms = list(dict.fromkeys(stems(text)))
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', "") + '"' + ("*" if len(t) >= 4 else "") for t in terms[:40])


def substring_query(text: str) -> str | None:
    """FTS5 trigram MATCH expression: the query words (≥ 4 letters, no stop words) as substrings."""
    terms = list(dict.fromkeys(w for w in words(text) if len(w) >= 4 and w not in STOPWORDS))
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms[:20])


def estimate_tokens(text: str) -> int:
    """Rough token count for chunk sizing (multilingual tokenizers: ~1.4 tokens per Norwegian word)."""
    count = len(text.split())
    return max(1, round(count * 1.4)) if count else 0
