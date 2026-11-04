"""Source positions of HTML elements, so content can be inserted or removed without re-serialising the page.

BeautifulSoup is good at *reading* HTML, but writing a page back through it re-serialises everything (entities,
attribute quoting, ``<br>``) – that would show up as changes to text the teacher wrote. This scanner records where
each element starts and ends in the original string. Insertions are then plain splices at element boundaries: every
byte of the teacher's HTML stays exactly as it was.

Implied end tags (``<p>`` closed by a block element, ``<li>`` by the next ``<li>`` …) follow the HTML parsing rules
closely enough for the HTML Canvas stores (it is serialised by Nokogiri and therefore well formed). When the markup is
too broken to trust the positions, :func:`scan` reports ``reliable=False`` and callers refuse to splice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
P_CLOSERS = {"address", "article", "aside", "blockquote", "details", "dialog", "div", "dl", "fieldset", "figcaption",
             "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu",
             "nav", "ol", "p", "pre", "section", "table", "ul"}
# tag → open tags it closes implicitly (when they are the current element)
IMPLIED = {"li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr", "td", "th"}, "td": {"td", "th"},
           "th": {"td", "th"}, "option": {"option"}, "thead": {"tbody", "tfoot"}, "tbody": {"thead", "tbody", "tfoot"},
           "tfoot": {"thead", "tbody"}}
RAW_TEXT = {"script", "style"}


@dataclass
class Span:
    tag: str
    start: int  # offset of "<"
    start_end: int  # offset just after the start tag's ">"
    attrs: dict[str, str]
    parent: Span | None = None
    end: int = -1  # offset just after the end tag (or where the element was implicitly closed)
    inner_end: int = -1  # offset of the end tag "</…" (== end for implied/void)
    children: list[Span] = field(default_factory=list)
    closed: bool = False

    def attr(self, name: str) -> str:
        return self.attrs.get(name, "")

    def walk(self) -> list[Span]:
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


@dataclass
class ScanResult:
    html: str
    root: Span
    reliable: bool
    problems: list[str] = field(default_factory=list)


class _Scanner(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_starts = [0]
        for index, char in enumerate(html):
            if char == "\n":
                self.line_starts.append(index + 1)
        self.root = Span("#root", 0, 0, {})
        self.root.end = self.root.inner_end = len(html)
        self.stack: list[Span] = [self.root]
        self.problems: list[str] = []

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def _close(self, span: Span, at: int, *, end: int | None = None) -> None:
        span.inner_end = at
        span.end = at if end is None else end
        span.closed = end is not None

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> None:
        start = self._pos()
        raw = self.get_starttag_text() or ""
        start_end = start + len(raw)
        current = self.stack[-1]
        if tag in P_CLOSERS and current.tag == "p":
            self._close(self.stack.pop(), start)
            current = self.stack[-1]
        closes = IMPLIED.get(tag)
        if closes:
            # Close the nearest open element of these kinds when nothing structural lies in between.
            for depth in range(len(self.stack) - 1, 0, -1):
                candidate = self.stack[depth]
                if candidate.tag in closes:
                    while len(self.stack) > depth:
                        self._close(self.stack.pop(), start)
                    break
                if candidate.tag in ("table", "ul", "ol", "dl", "select", "div"):
                    break
            current = self.stack[-1]
        span = Span(tag, start, start_end, {k.lower(): (v or "") for k, v in attrs}, parent=current)
        current.children.append(span)
        if tag in VOID or self_closing:
            span.end = span.inner_end = start_end
            span.closed = True
            return
        self.stack.append(span)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag.lower(), attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag.lower(), attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        at = self._pos()
        close = self.html.find(">", at)
        end = len(self.html) if close == -1 else close + 1
        if tag in VOID:
            return  # «</br>» and friends carry no structure
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                while len(self.stack) > depth + 1:
                    inner = self.stack.pop()
                    if inner.tag not in ("p", "li", "dt", "dd", "td", "th", "tr", "option", "tbody", "thead",
                                         "tfoot"):
                        self.problems.append(f"<{inner.tag}> lukket implisitt av </{tag}>")
                    self._close(inner, at)
                self._close(self.stack.pop(), at, end=end)
                return
        if tag == "p":
            self.problems.append("</p> uten åpen <p>")  # browsers create an empty paragraph here
        # Other stray end tags are ignored, like browsers do.


def scan(html: str) -> ScanResult:
    scanner = _Scanner(html)
    try:
        scanner.feed(html)
        scanner.close()
    except (AssertionError, ValueError) as exc:  # pragma: no cover - HTMLParser is very tolerant
        return ScanResult(html, scanner.root, False, [f"Kunne ikke lese HTML: {exc}"])
    problems = list(scanner.problems)
    for span in scanner.stack[1:]:
        if span.tag not in ("p", "li", "dt", "dd", "td", "th", "tr", "tbody", "thead", "tfoot", "option",
                            "html", "body", "colgroup"):
            problems.append(f"<{span.tag}> er ikke lukket")
        span.inner_end = span.end = len(html)
    reliable = not any("ikke lukket" in p or "lukket implisitt" in p for p in problems)
    return ScanResult(html, scanner.root, reliable, problems)
