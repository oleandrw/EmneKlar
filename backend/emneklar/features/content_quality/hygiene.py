"""HTML hygiene checks and the conservative cleanup transform.

Cleanup is deliberately conservative. It NEVER:
* changes link targets or media sources (href/src),
* removes iframes, video, audio, object/embed or images,
* removes Canvas attributes (data-api-*, data-media-*, other data-*/aria-*, ids, classes other than Word's Mso*),
* removes inline styles other than Word's mso-* declarations,
* changes tables, lists or headings.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from emneklar.core.canvas.html import parse_html, text_of

PROTECTED = {"iframe", "video", "audio", "object", "embed", "img", "source", "track", "picture", "table", "math"}
DEPRECATED = {"font", "center", "big", "strike", "tt", "marquee", "blink", "basefont"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "param"}
OPTIONAL_CLOSE = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "colgroup", "caption"}
BLOCKS = {"div", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "section", "figure",
          "dl", "hr", "article", "aside", "header", "footer", "nav", "p"}
MSO_STYLE = re.compile(r"\s*mso-[a-z-]+\s*:[^;]*;?", re.IGNORECASE)


@dataclass
class HygieneIssue:
    rule_id: str
    message: str
    count: int = 1
    evidence: dict[str, object] = field(default_factory=dict)
    path: str | None = None


def _is_empty_paragraph(p: Tag) -> bool:
    if p.find(lambda t: isinstance(t, Tag) and t.name not in ("br", "span", "strong", "em", "b", "i")):
        return False
    return not text_of(p)


class _StructureValidator(HTMLParser):
    """Finds structural problems the lenient parsers silently repair."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: Counter[str] = Counter()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [a for a, _ in attrs]
        if len(names) != len(set(names)):
            self.problems["Duplisert attributt"] += 1
        if tag in BLOCKS and "p" in self.stack[-1:]:
            self.problems[f"<{tag}> inne i et avsnitt"] += 1
        if tag == "a" and "a" in self.stack:
            self.problems["Lenke inne i en lenke"] += 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if tag not in self.stack:
            self.problems["Sluttmerke uten startmerke"] += 1
            return
        while self.stack:
            top = self.stack.pop()
            if top == tag:
                return
            if top not in OPTIONAL_CLOSE:
                self.problems["Element som ikke er lukket"] += 1

    def close(self) -> None:
        super().close()
        unclosed = [t for t in self.stack if t not in OPTIONAL_CLOSE]
        if unclosed:
            self.problems["Element som ikke er lukket"] += len(unclosed)


def validate_structure(html: str) -> Counter[str]:
    validator = _StructureValidator()
    try:
        validator.feed(html or "")
        validator.close()
    except Exception:  # noqa: BLE001 - malformed input is exactly what we are reporting
        validator.problems["Kunne ikke tolke koden"] += 1
    return validator.problems


def check_hygiene(html: str) -> list[HygieneIssue]:
    soup = parse_html(html)
    issues: list[HygieneIssue] = []
    if not text_of(soup) and not soup.find(["img", "iframe", "video", "audio", "table", "embed", "object"]):
        issues.append(HygieneIssue("CQ-CONTENT-EMPTY", "Innholdet er tomt."))
        return issues
    empty = [p for p in soup.find_all("p") if _is_empty_paragraph(p)]
    if len(empty) >= 3:
        issues.append(HygieneIssue("CQ-HTML-EMPTY-PARAGRAPHS", f"{len(empty)} tomme avsnitt.", len(empty)))
    spans = [s for s in soup.find_all("span") if not s.attrs or s.attrs == {"style": ""}]
    if spans:
        issues.append(HygieneIssue("CQ-HTML-REDUNDANT-SPANS", f"{len(spans)} span-elementer uten funksjon.", len(spans)))
    mso = len(soup.find_all(class_=re.compile(r"^Mso"))) + len(soup.find_all(style=MSO_STYLE)) + \
        len(soup.find_all(re.compile(r"^o:p$")))
    if mso:
        issues.append(HygieneIssue("CQ-HTML-WORD", f"{mso} elementer med Word-formatering.", mso))
    deprecated = list(soup.find_all(list(DEPRECATED)))
    if deprecated:
        names = sorted({t.name for t in deprecated})
        issues.append(HygieneIssue("CQ-HTML-DEPRECATED", f"{len(deprecated)} utdaterte elementer ({', '.join(names)}).",
                                   len(deprecated), {"elements": names}))
    styles = Counter(str(t.get("style")).strip() for t in soup.find_all(style=True) if str(t.get("style")).strip())
    repeated = [(style, n) for style, n in styles.items() if n >= 10]
    if repeated:
        style, n = max(repeated, key=lambda x: x[1])
        issues.append(HygieneIssue("CQ-HTML-DUPLICATE-STYLES", f"Stilen «{style[:60]}» er gjentatt {n} ganger.", n,
                                   {"style": style[:200]}))
    runs = 0
    for br in soup.find_all("br"):
        sibling = br.next_sibling
        streak = 1
        while sibling is not None and ((isinstance(sibling, Tag) and sibling.name == "br") or
                                       (isinstance(sibling, NavigableString) and not str(sibling).strip())):
            if isinstance(sibling, Tag):
                streak += 1
            sibling = sibling.next_sibling
        if streak >= 3 and not (isinstance(br.previous_sibling, Tag) and br.previous_sibling.name == "br"):
            runs += 1
    if runs:
        issues.append(HygieneIssue("CQ-HTML-BR-SPACING", f"{runs} steder med tre eller flere linjeskift på rad.", runs))
    problems = validate_structure(html)
    if problems:
        summary = ", ".join(f"{k} ({v})" for k, v in problems.most_common(4))
        issues.append(HygieneIssue("CQ-HTML-INVALID", f"Feil i HTML-strukturen: {summary}.", sum(problems.values()),
                                   {"problems": dict(problems)}))
    return issues


# ------------------------------------------------------------------------------------ cleanup

CLEANUP_OPTIONS = {
    "empty_paragraphs": "Fjern tomme avsnitt",
    "redundant_spans": "Fjern span-elementer uten funksjon",
    "word_artifacts": "Fjern Word-rester (Mso-klasser, mso-stiler, o:p)",
    "br_runs": "Slå sammen tre eller flere linjeskift",
    "plain_font": "Fjern font-elementer uten formatering",
}


def cleanup(html: str, options: set[str]) -> tuple[BeautifulSoup, Counter[str]]:
    soup = parse_html(html)
    counts: Counter[str] = Counter()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment) and "[if" in s):
        if "word_artifacts" in options:
            comment.extract()
            counts["word_artifacts"] += 1
    if "word_artifacts" in options:
        for tag in soup.find_all(re.compile(r"^o:p$")):
            tag.unwrap()
            counts["word_artifacts"] += 1
        for tag in soup.find_all(class_=True):
            classes = [c for c in tag.get("class") or [] if not c.startswith("Mso")]
            if len(classes) != len(tag.get("class") or []):
                counts["word_artifacts"] += 1
                if classes:
                    tag["class"] = " ".join(classes)
                else:
                    del tag["class"]
        for tag in soup.find_all(style=True):
            style = str(tag.get("style"))
            cleaned = MSO_STYLE.sub("", style).strip().strip(";").strip()
            if cleaned != style.strip().strip(";").strip():
                counts["word_artifacts"] += 1
                if cleaned:
                    tag["style"] = cleaned
                else:
                    del tag["style"]
    if "redundant_spans" in options:
        for span in soup.find_all("span"):
            if not span.attrs or span.attrs == {"style": ""}:
                span.unwrap()
                counts["redundant_spans"] += 1
    if "plain_font" in options:
        for font in soup.find_all("font"):
            if not font.attrs:
                font.unwrap()
                counts["plain_font"] += 1
    if "empty_paragraphs" in options:
        for p in soup.find_all("p"):
            if _is_empty_paragraph(p) and not p.find(PROTECTED) and not p.get("id"):
                p.decompose()
                counts["empty_paragraphs"] += 1
    if "br_runs" in options:
        for br in soup.find_all("br"):
            if br.parent is None:
                continue
            following = []
            sibling = br.next_sibling
            while sibling is not None and ((isinstance(sibling, Tag) and sibling.name == "br") or
                                           (isinstance(sibling, NavigableString) and not str(sibling).strip())):
                following.append(sibling)
                sibling = sibling.next_sibling
            brs = [s for s in following if isinstance(s, Tag)]
            if len(brs) >= 2:
                for extra in brs[1:]:
                    extra.decompose()
                    counts["br_runs"] += 1
    return soup, counts


def protected_signature(html: str) -> dict[str, list[str]]:
    """Everything cleanup must leave untouched – used by tests and as a runtime safety check."""
    soup = parse_html(html)
    return {
        "hrefs": sorted(str(a.get("href")) for a in soup.find_all(href=True)),
        "srcs": sorted(str(t.get("src")) for t in soup.find_all(src=True)),
        "embeds": sorted(t.name for t in soup.find_all(list(PROTECTED))),
        "data": sorted(f"{k}={v}" for t in soup.find_all(True) for k, v in t.attrs.items()
                       if k.startswith(("data-", "aria-")) or k in ("id", "role", "alt", "title", "lang")),
        "text": [text_of(soup)],
    }
