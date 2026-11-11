"""Targeted edits of Canvas HTML: change one element without re-serialising the rest of the document.

BeautifulSoup is used to *find* the element a fix applies to. Writing the whole document back through
BeautifulSoup would re-serialise everything (entities, attribute quoting, ``<br>``, whitespace) – a link fix could
then show up as changes to every other part of the page. Instead, the element is mapped to its exact position in the
original string (:mod:`emneklar.core.canvas.htmlspans`) and only that element's bytes are replaced. Everything else
in the document stays byte-for-byte identical.

Mapping: both BeautifulSoup (``html.parser``) and the scanner create exactly one node per start tag and append it to
the currently open node, so a pre-order walk of either tree visits elements in start-tag order. The n-th element in
``soup.find_all(True)`` is therefore the n-th scanned span. Each mapping is double-checked (tag name and the key
attributes must agree); when anything does not line up, :class:`EditError` is raised and callers fall back to the
older whole-document serialisation (or refuse), never to a guess.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from emneklar.core.canvas.htmlspans import VOID, Span, scan

# Attributes compared between the BeautifulSoup element and the scanned span (values as the parsers decode them).
_CHECKED_ATTRS = ("href", "src", "alt", "title", "id", "lang")
_ATTR_RE = re.compile(r"""(\s+)([^\s"'=<>/`]+)(\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")


class EditError(Exception):
    """The element could not be mapped safely to the source; the caller must not splice."""


@dataclass
class Edit:
    start: int
    end: int
    replacement: str
    before: str = ""  # outer HTML of the element before the edit (for the compact «what changes» view)
    after: str = ""  # … and after


@dataclass
class EditPlan:
    """Edits collected against one original string, applied back to front so offsets stay valid."""

    html: str
    edits: list[Edit] = field(default_factory=list)
    _spans: list[Span] | None = None
    _reliable: bool = True

    def spans(self) -> list[Span]:
        if self._spans is None:
            result = scan(self.html)
            self._spans = result.root.walk()[1:]
            self._reliable = result.reliable
        return self._spans

    # -- mapping -------------------------------------------------------------------------------

    def span_for(self, soup: BeautifulSoup, el: Tag, *, need_end: bool = False) -> Span:
        index = next((i for i, candidate in enumerate(soup.find_all(True)) if candidate is el), None)
        spans = self.spans()
        if index is None or index >= len(spans):
            raise EditError("Fant ikke elementet i kildekoden.")
        span = spans[index]
        if span.tag != (el.name or "").lower():
            raise EditError("Elementet i kildekoden stemmer ikke med det som ble funnet.")
        for name in _CHECKED_ATTRS:
            ours = _attr_text(el.get(name))
            theirs = html_lib.unescape(span.attrs[name]) if name in span.attrs else None
            if ours != theirs:
                raise EditError("Attributtene i kildekoden stemmer ikke med elementet.")
        if need_end and not (span.closed or span.tag in VOID):
            raise EditError("Elementet har ingen eksplisitt slutt-tagg.")
        if need_end and not self._reliable:
            raise EditError("HTML-koden er for uryddig til en målrettet endring.")
        return span

    # -- operations ------------------------------------------------------------------------------

    def set_attrs(self, soup: BeautifulSoup, el: Tag, changes: dict[str, str | None]) -> None:
        """Set (str) or remove (None) attributes in the element's start tag only."""
        span = self.span_for(soup, el)
        start_tag = self.html[span.start:span.start_end]
        new_tag = edit_start_tag(start_tag, changes)
        outer_end = span.end if span.end > span.start_end and (span.closed or span.tag in VOID) else span.start_end
        before = self.html[span.start:outer_end]
        after = new_tag + self.html[span.start_end:outer_end]
        self._add(Edit(span.start, span.start_end, new_tag, before=before, after=after))

    def replace_inner(self, soup: BeautifulSoup, el: Tag, inner_html: str) -> None:
        span = self.span_for(soup, el, need_end=True)
        before = self.html[span.start:span.end]
        after = self.html[span.start:span.start_end] + inner_html + self.html[span.inner_end:span.end]
        self._add(Edit(span.start_end, span.inner_end, inner_html, before=before, after=after))

    def replace_outer(self, soup: BeautifulSoup, el: Tag, outer_html: str) -> None:
        span = self.span_for(soup, el, need_end=True)
        self._add(Edit(span.start, span.end, outer_html, before=self.html[span.start:span.end], after=outer_html))

    def set_attrs_and_inner(self, soup: BeautifulSoup, el: Tag, changes: dict[str, str | None], inner_html: str) -> None:
        span = self.span_for(soup, el, need_end=True)
        new_tag = edit_start_tag(self.html[span.start:span.start_end], changes)
        outer = new_tag + inner_html + self.html[span.inner_end:span.end]
        self._add(Edit(span.start, span.end, outer, before=self.html[span.start:span.end], after=outer))

    def unwrap(self, soup: BeautifulSoup, el: Tag) -> None:
        """Remove the element's tags but keep its content (e.g. «remove the link, keep the text»)."""
        span = self.span_for(soup, el, need_end=True)
        inner = self.html[span.start_end:span.inner_end]
        self._add(Edit(span.start, span.end, inner, before=self.html[span.start:span.end], after=inner))

    def remove(self, soup: BeautifulSoup, el: Tag) -> None:
        span = self.span_for(soup, el, need_end=True)
        self._add(Edit(span.start, span.end, "", before=self.html[span.start:span.end], after=""))

    def rename(self, soup: BeautifulSoup, el: Tag, new_name: str) -> None:
        """Change the tag name (e.g. h4 → h3), keeping attributes and content."""
        span = self.span_for(soup, el, need_end=True)
        start_tag = self.html[span.start:span.start_end]
        end_tag = self.html[span.inner_end:span.end]
        if not re.match(rf"<{re.escape(span.tag)}\b", start_tag, re.IGNORECASE) or \
                not re.fullmatch(rf"</{re.escape(span.tag)}\s*>", end_tag, re.IGNORECASE):
            raise EditError("Kunne ikke lese taggen i kildekoden.")
        new_start = f"<{new_name}" + start_tag[1 + len(span.tag):]
        outer = new_start + self.html[span.start_end:span.inner_end] + f"</{new_name}>"
        self._add(Edit(span.start, span.end, outer, before=self.html[span.start:span.end], after=outer))

    # -- result ------------------------------------------------------------------------------------

    def _add(self, edit: Edit) -> None:
        for other in self.edits:
            if edit.start < other.end and other.start < edit.end:
                raise EditError("To endringer gjelder samme del av innholdet.")
        self.edits.append(edit)

    def apply(self) -> str:
        result = self.html
        for edit in sorted(self.edits, key=lambda e: e.start, reverse=True):
            result = result[:edit.start] + edit.replacement + result[edit.end:]
        return result

    def changes(self) -> list[dict[str, str]]:
        return [{"before": e.before, "after": e.after} for e in sorted(self.edits, key=lambda e: e.start)]


def _attr_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def escape_attr(value: str) -> str:
    return html_lib.escape(value, quote=True).replace("&#x27;", "'")


def escape_text(value: str) -> str:
    return html_lib.escape(value, quote=False)


def edit_start_tag(start_tag: str, changes: dict[str, str | None]) -> str:
    """Set or remove attributes in a raw start tag, leaving all other attributes exactly as written."""
    match = re.match(r"<([A-Za-z][^\s/>]*)", start_tag)
    if not match:
        raise EditError("Kunne ikke lese starttaggen.")
    head = match.group(0)
    rest = start_tag[len(head):]
    closing = re.search(r"\s*/?>\s*$", rest)
    if not closing:
        raise EditError("Kunne ikke lese starttaggen.")
    body, tail = rest[:closing.start()], rest[closing.start():]
    pending = {k.lower(): v for k, v in changes.items()}
    out: list[str] = []
    position = 0
    for attr in _ATTR_RE.finditer(body):
        if attr.start() != position:
            raise EditError("Uventet innhold i starttaggen.")
        position = attr.end()
        name = attr.group(2).lower()
        if name in pending:
            value = pending.pop(name)
            if value is not None:
                out.append(f'{attr.group(1)}{attr.group(2)}="{escape_attr(value)}"')
            continue
        out.append(attr.group(0))
    if body[position:].strip():
        raise EditError("Uventet innhold i starttaggen.")
    out.append(body[position:])
    for name, value in pending.items():
        if value is not None:
            out.append(f' {name}="{escape_attr(value)}"')
    return head + "".join(out) + tail
