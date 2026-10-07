"""Standardiser videoavspillere (Innholdskvalitet → Media): YouTube embeds in a responsive, accessible standard.

Pure functions only – the API module (``video_api``) reads content, fetches metadata and stages changes through
the change engine. Version 1 handles YouTube iframes.

* The video ID and the query parameters are never changed (``t`` becomes ``start``, which is what the embed
  player understands). Autoplay is kept and reported separately.
* The standard markup uses only what Canvas' sanitiser keeps (``core/security/sanitize.py``): ``aspect-ratio`` is
  not kept, so the 16:9 box uses the classic ``padding-bottom`` technique.
* Only the embed's own part of the HTML is replaced (by source position), so the rest of the page – text,
  whitespace and other embeds – stays byte for byte the same.
* A semantic comparison with the standard decides whether anything needs to change, which makes the standardiser
  idempotent: standard markup never produces a second change.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from emneklar.core.canvas.html import is_generic_iframe_title, norm_text, text_of

STANDARD_CLASS = "ek-video"
DEFAULT_MAX_WIDTH = 960
DEFAULT_RATIO = 56.25  # 16:9 as padding-bottom percentage
TITLE_MAX = 120
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
EMBED_HOSTS = {"youtube.com", "www.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{6,20}")
PLAYLIST_ID = "videoseries"
STANDARD_ALLOW = "accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
INNER_STYLE = "position: relative; height: 0; padding-bottom: {ratio}%; overflow: hidden;"
IFRAME_STYLE = "position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;"

# Wrappers that only hold the video and may be replaced together with it.
WRAPPER_STYLE = {"position", "padding", "padding-top", "padding-bottom", "height", "overflow", "max-width", "width",
                 "margin", "margin-top", "margin-bottom", "margin-left", "margin-right", "text-align", "display"}
WRAPPER_CLASS = re.compile(r"video|embed|responsive|media|iframe|player", re.IGNORECASE)
PHRASING_PARENTS = {"p", "span", "a", "strong", "em", "b", "i", "u", "font", "small", "sub", "sup", "label", "q",
                    "cite", "code"}


class TitleSource(StrEnum):
    EXISTING = "existing"
    YOUTUBE_METADATA = "youtube_metadata"
    PAGE_CONTEXT = "page_context"
    AI_SUGGESTION = "ai_suggestion"
    MANUAL = "manual"


TITLE_SOURCE_LABEL = {
    TitleSource.EXISTING: "Eksisterende title",
    TitleSource.YOUTUBE_METADATA: "YouTube-metadata",
    TitleSource.PAGE_CONTEXT: "Canvas-kontekst",
    TitleSource.AI_SUGGESTION: "KI-forslag",
    TitleSource.MANUAL: "Skrevet inn manuelt",
}

ISSUE_LABEL = {
    "fixed_size": "Fast størrelse",
    "missing_title": "Mangler title",
    "generic_title": "Generell title",
    "old_embed": "Avvikende eller gammel embed-kode",
    "not_standard": "Følger ikke standarden",
    "manual": "Krever manuell kontroll",
}


# ----------------------------------------------------------------------------------------- options


@dataclass(frozen=True)
class VideoOptions:
    max_width: int | None = DEFAULT_MAX_WIDTH  # None = full available width
    keep_ratio: bool = False  # False = 16:9
    responsive: bool = True
    center: bool = True
    lazy: bool = True
    fix_title: bool = True


# ------------------------------------------------------------------------------------------- URLs


@dataclass(frozen=True)
class YouTubeUrl:
    video_id: str
    nocookie: bool
    params: tuple[tuple[str, str], ...]
    is_embed: bool  # already an /embed/ URL on https on a host that allows embedding


def _seconds(value: str) -> int | None:
    """«90», «90s», «1m30s», «1h2m3s» → seconds."""
    text = value.strip().lower()
    if text.isdigit():
        return int(text)
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_youtube_url(src: str) -> YouTubeUrl | None:
    """The video ID and parameters of a YouTube URL, or None for anything else."""
    text = (src or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    query = parse_qsl(parts.query, keep_blank_values=True)
    segments = [s for s in parts.path.split("/") if s]
    if host in SHORT_HOSTS:
        video_id = segments[0] if segments else ""
        embed_form = False
    elif host in YOUTUBE_HOSTS:
        if len(segments) >= 2 and segments[0] in ("embed", "shorts", "live", "v"):
            video_id = segments[1]
        elif segments == ["watch"]:
            video_id = dict(query).get("v", "")
        else:
            return None
        embed_form = segments[0] == "embed"
    else:
        return None
    if not VIDEO_ID.fullmatch(video_id):
        return None
    params = [(k, v) for k, v in query if k != "v"]
    keys = {k for k, _ in params}
    if "t" in keys and "start" not in keys:
        converted = []
        for key, value in params:
            seconds = _seconds(value) if key == "t" else None
            converted.append(("start", str(seconds)) if seconds is not None else (key, value))
        params = converted
    is_embed = (embed_form and parts.scheme == "https" and host in EMBED_HOSTS
                and not any(k == "t" for k, _ in params))
    return YouTubeUrl(video_id=video_id, nocookie="nocookie" in host, params=tuple(params), is_embed=is_embed)


def embed_src(original: str, url: YouTubeUrl) -> str:
    """The src to use: a working embed URL is kept exactly; others become ``https://www.youtube.com/embed/ID``."""
    if url.is_embed:
        return original.strip()
    host = "www.youtube-nocookie.com" if url.nocookie else "www.youtube.com"
    query = urlencode(list(url.params))
    return f"https://{host}/embed/{url.video_id}" + (f"?{query}" if query else "")


def has_autoplay(url: YouTubeUrl) -> bool:
    return any(k == "autoplay" and v.strip() == "1" for k, v in url.params)


# ----------------------------------------------------------------------------------------- titles


def format_video_title(title: str) -> str:
    """«NotebookLM Audio Overview» → «Video: NotebookLM Audio Overview», kept concise."""
    text = norm_text(title)
    if not re.match(r"(?i)video\s*[:–—-]", text):
        text = f"Video: {text}"
    if len(text) > TITLE_MAX:
        text = text[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,.;:–—-") + " …"
    return text


_POOR = re.compile(r"(?i)^(recording|opptak|video|movie|clip|klipp|untitled|uten tittel|img|mov|vid|dsc|"
                   r"screen ?recording|skjermopptak|zoom|meeting|møte)[\s_.-]*\d*([\s_.-]*\d+)*$")


def is_poor_title(title: str | None) -> bool:
    """A metadata title that does not describe the video («Recording 27», «IMG_1234.mov», «Video»)."""
    text = norm_text(title)
    if is_generic_iframe_title(text) or len(text) < 4:
        return True
    if re.search(r"(?i)\.(mp4|mov|avi|mkv|webm|m4v|wmv)$", text) or not re.search(r"[A-Za-zÆØÅæøå]{3}", text):
        return True
    return bool(_POOR.match(text))


@dataclass
class VideoContext:
    page_title: str = ""
    heading: str = ""
    before: str = ""
    after: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"page_title": self.page_title, "heading": self.heading, "before": self.before, "after": self.after}


@dataclass
class TitleProposal:
    title: str | None
    source: TitleSource | None
    needs_review: bool

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "source": self.source.value if self.source else None,
                "source_label": TITLE_SOURCE_LABEL[self.source] if self.source else None,
                "needs_review": self.needs_review}


def context_title(context: VideoContext) -> str | None:
    """«Slik bruker du NotebookLM» on the page «Lag KI-generert podcast» →
    «Video: Slik bruker du NotebookLM (Lag KI-generert podcast)». A suggestion that must be reviewed."""
    heading = context.heading if not is_poor_title(context.heading) else ""
    page = context.page_title if not is_poor_title(context.page_title) else ""
    if heading and page and page.lower() not in heading.lower() and heading.lower() not in page.lower():
        return format_video_title(f"{heading} ({page})")
    if heading or page:
        return format_video_title(heading or page)
    return None


def resolve_title(current: str, metadata_title: str | None, context: VideoContext, *,
                  overwrite_existing: bool = False) -> TitleProposal:
    """Strict priority: a good existing title, YouTube metadata, Canvas context – AI and manual entry come later."""
    if not is_generic_iframe_title(current) and not (overwrite_existing and metadata_title
                                                     and not is_poor_title(metadata_title)):
        return TitleProposal(norm_text(current), TitleSource.EXISTING, needs_review=False)
    if metadata_title and not is_poor_title(metadata_title):
        return TitleProposal(format_video_title(metadata_title), TitleSource.YOUTUBE_METADATA, needs_review=False)
    title = context_title(context)
    if title:
        return TitleProposal(title, TitleSource.PAGE_CONTEXT, needs_review=True)
    return TitleProposal(None, None, needs_review=True)


def validate_title(title: str) -> str:
    """A title the teacher entered or approved: required, descriptive and concise."""
    text = norm_text(title)
    if is_generic_iframe_title(text) or len(text) < 4:
        raise ValueError("Skriv en tittel som sier hva videoen handler om (ikke bare «Video» eller «YouTube»).")
    if len(text) > 200:
        raise ValueError("Tittelen er for lang. Hold den kort – under 120 tegn er best.")
    return text


# ------------------------------------------------------------------------------------- the markup


def _style(text: str | None) -> dict[str, str]:
    props: dict[str, str] = {}
    for part in (text or "").split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            value = re.sub(r"\s+", " ", value.strip().lower())
            value = re.sub(r"(?<![\d.])0px\b", "0", value)
            if name.strip():
                props[name.strip().lower()] = value
    return props


def ratio_for(iframe: Tag, options: VideoOptions) -> float:
    if options.keep_ratio:
        try:
            width = float(str(iframe.get("width") or "").rstrip("px"))
            height = float(str(iframe.get("height") or "").rstrip("px"))
            if width > 0 and height > 0:
                return round(height / width * 100, 2)
        except ValueError:
            pass
    return DEFAULT_RATIO


def _num(value: float) -> str:
    return f"{value:g}"


def standard_markup(*, src: str, title: str | None, ratio: float, options: VideoOptions, allow: str | None) -> str:
    """The EmneKlar video standard: responsive, centered (optional), max width, Canvas-safe."""
    outer = []
    if options.max_width:
        outer.append(f"max-width: {options.max_width}px;")
    outer.append("margin: 1em auto;" if options.center else "margin: 1em 0;")
    attrs = [f'src="{html_lib.escape(src, quote=True)}"']
    if title:
        attrs.append(f'title="{html_lib.escape(title, quote=True)}"')
    attrs.append(f'style="{IFRAME_STYLE}"')
    if allow:
        attrs.append(f'allow="{html_lib.escape(allow, quote=True)}"')
    attrs.append('allowfullscreen="allowfullscreen"')
    if options.lazy:
        attrs.append('loading="lazy"')
    return (f'<div class="{STANDARD_CLASS}" style="{" ".join(outer)}">'
            f'<div style="{INNER_STYLE.format(ratio=_num(ratio))}">'
            f'<iframe {" ".join(attrs)}></iframe></div></div>')


def _shape(node: Any) -> Any:
    """A comparable form of markup: names, attributes (styles parsed, booleans as present) and children."""
    if isinstance(node, NavigableString):
        text = norm_text(str(node))
        return ("#text", text) if text else None
    if not isinstance(node, Tag):
        return None
    attrs: list[tuple[str, Any]] = []
    for name, value in node.attrs.items():
        if name == "style":
            attrs.append((name, tuple(sorted(_style(str(value)).items()))))
        elif name == "class":
            attrs.append((name, tuple(sorted(value if isinstance(value, list) else str(value).split()))))
        elif name in ("allowfullscreen",):
            attrs.append((name, True))
        else:
            attrs.append((name, norm_text(str(value))))
    children = tuple(c for c in (_shape(ch) for ch in node.children) if c is not None)
    return (node.name, tuple(sorted(attrs)), children)


def same_markup(a: str, b: str) -> bool:
    shapes = []
    for markup in (a, b):
        soup = BeautifulSoup(markup, "html.parser")
        shapes.append(tuple(s for s in (_shape(ch) for ch in soup.children) if s is not None))
    return shapes[0] == shapes[1]


# ---------------------------------------------------------------------------------- finding embeds


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


_TAG = r"(?:[^>\"']|\"[^\"]*\"|'[^']*')*"


def element_span(source: str, starts: list[int], el: Tag) -> tuple[int, int] | None:
    """Start and end offset of ``el`` in the original HTML (start tag to matching end tag)."""
    if el.sourceline is None or el.sourcepos is None:
        return None
    start = starts[el.sourceline - 1] + el.sourcepos
    opening = re.compile(rf"<{el.name}\b{_TAG}>", re.IGNORECASE).match(source, start)
    if not opening:
        return None
    if opening.group(0).endswith("/>"):
        return start, opening.end()
    depth = 1
    pattern = re.compile(rf"<(/?){el.name}\b{_TAG}>", re.IGNORECASE)
    for match in pattern.finditer(source, opening.end()):
        if match.group(1):
            depth -= 1
        elif not match.group(0).endswith("/>"):
            depth += 1
        if depth == 0:
            return start, match.end()
    return None


def _only_child(parent: Tag, child: Tag) -> bool:
    for node in parent.children:
        if node is child:
            continue
        if isinstance(node, NavigableString) and not norm_text(str(node)):
            continue
        return False
    return True


def _wrapper_like(div: Tag) -> bool:
    for name, value in div.attrs.items():
        if name == "style":
            if not set(_style(str(value))) <= WRAPPER_STYLE:
                return False
        elif name == "class":
            classes = value if isinstance(value, list) else str(value).split()
            if not all(c == STANDARD_CLASS or WRAPPER_CLASS.search(c) for c in classes):
                return False
        else:
            return False
    return True


def _region_root(iframe: Tag) -> Tag:
    node = iframe
    for _ in range(3):
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name not in ("div", "p") or not _only_child(parent, node):
            break
        if parent.name == "p":
            if set(parent.attrs) - {"style", "class"}:
                break
            node = parent
            break
        if not _wrapper_like(parent):
            break
        node = parent
    return node


def _nearest_heading(el: Tag) -> str:
    heading = el.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    return text_of(heading)[:150] if isinstance(heading, Tag) else ""


def _nearby_text(root: Tag, direction: str) -> str:
    sibling = root.find_previous_sibling() if direction == "before" else root.find_next_sibling()
    for _ in range(3):
        if not isinstance(sibling, Tag):
            break
        text = text_of(sibling)
        if text:
            return text[:200]
        sibling = sibling.find_previous_sibling() if direction == "before" else sibling.find_next_sibling()
    return ""


@dataclass
class Embed:
    """One YouTube iframe in a piece of HTML."""

    video_id: str
    occurrence: int  # nth iframe with this video ID in the HTML (stable key together with the video ID)
    url: YouTubeUrl
    iframe: Tag
    root: Tag
    span: tuple[int, int] | None  # region (the iframe and its wrappers) in the original HTML
    iframe_span: tuple[int, int] | None
    title: str
    issues: list[str] = field(default_factory=list)
    manual_reason: str | None = None
    layout_manual: bool = False
    context: VideoContext = field(default_factory=VideoContext)

    @property
    def size_label(self) -> str | None:
        width, height = self.iframe.get("width"), self.iframe.get("height")
        style = _style(str(self.iframe.get("style") or ""))
        width = width or style.get("width")
        height = height or style.get("height")
        if width and height:
            return f"{str(width).replace('px', '')} × {str(height).replace('px', '')}"
        return None

    @property
    def layout_label(self) -> str:
        if "fixed_size" in self.issues:
            return "Fast størrelse"
        if self.is_standard_layout:
            return "Responsiv (EmneKlar-standard)"
        if _responsive_wrapper(self.iframe):
            return "Responsiv (annen kode)"
        return "Uten fast størrelse"

    @property
    def is_standard_layout(self) -> bool:
        return self.root.name == "div" and STANDARD_CLASS in (self.root.get("class") or [])


def _responsive_wrapper(iframe: Tag) -> bool:
    parent = iframe.parent
    if not isinstance(parent, Tag):
        return False
    style = _style(str(parent.get("style") or ""))
    return any(style.get(k, "").endswith("%") for k in ("padding-bottom", "padding-top")) or STANDARD_CLASS in (
        parent.get("class") or [])


def find_embeds(source: str, page_title: str = "") -> list[Embed]:
    """All YouTube iframes in the HTML, with the part of the source that belongs to each of them."""
    soup = BeautifulSoup(source or "", "html.parser")
    starts = _line_starts(source or "")
    embeds: list[Embed] = []
    seen: dict[str, int] = {}
    for iframe in soup.find_all("iframe"):
        url = parse_youtube_url(str(iframe.get("src") or ""))
        if url is None:
            continue
        occurrence = seen.get(url.video_id, 0)
        seen[url.video_id] = occurrence + 1
        root = _region_root(iframe)
        embed = Embed(video_id=url.video_id, occurrence=occurrence, url=url, iframe=iframe, root=root,
                      span=element_span(source, starts, root), iframe_span=element_span(source, starts, iframe),
                      title=norm_text(str(iframe.get("title") or "")),
                      context=VideoContext(page_title=norm_text(page_title)[:150], heading=_nearest_heading(iframe),
                                           before=_nearby_text(root, "before"), after=_nearby_text(root, "after")))
        _classify(embed)
        embeds.append(embed)
    return embeds


INVALID_ID = "Adressen til YouTube-videoen mangler en gyldig video-ID. Kontroller videoen i Canvas."
FLASH_EMBED = ("Videoen er bygd inn med gammel Flash-kode (object/embed), som ikke spilles av i dag. Bygg den inn på "
               "nytt fra YouTube i Canvas.")


def _youtube_host(src: str) -> bool:
    text = (src or "").strip()
    try:
        host = (urlsplit("https:" + text if text.startswith("//") else text).hostname or "").lower()
    except ValueError:
        return False
    return host in YOUTUBE_HOSTS or host in SHORT_HOSTS


def find_unsupported(source: str) -> list[tuple[str, str]]:
    """YouTube content that cannot be standardised automatically: (src, reason) – shown for manual control."""
    soup = BeautifulSoup(source or "", "html.parser")
    found: list[tuple[str, str]] = []
    for iframe in soup.find_all("iframe"):
        src = str(iframe.get("src") or "")
        if _youtube_host(src) and parse_youtube_url(src) is None:
            found.append((src, INVALID_ID))
    for el in soup.find_all(["object", "embed"]):
        if el.name == "embed" and el.find_parent("object") is not None:
            continue
        sources = [str(el.get("src") or el.get("data") or "")]
        sources += [str(p.get("value") or "") for p in el.find_all("param")]
        flash = next((s for s in sources if _youtube_host(s)), None)
        if flash is not None:
            found.append((flash, FLASH_EMBED))
    return found


def _classify(embed: Embed) -> None:
    iframe, issues = embed.iframe, embed.issues
    style = _style(str(iframe.get("style") or ""))
    fixed = bool(iframe.get("width") or iframe.get("height") or style.get("width", "").endswith("px")
                 or style.get("height", "").endswith("px"))
    if fixed and not _responsive_wrapper(iframe):
        issues.append("fixed_size")
    if not embed.title:
        issues.append("missing_title")
    elif is_generic_iframe_title(embed.title):
        issues.append("generic_title")
    if not embed.url.is_embed or (_responsive_wrapper(iframe) and not embed.is_standard_layout):
        issues.append("old_embed")
    parent = embed.root.parent
    if embed.span is None or embed.iframe_span is None:
        embed.manual_reason = "Koden rundt videoen kunne ikke leses sikkert. Kontroller videoen i Canvas."
        embed.layout_manual = True
    elif embed.root is iframe and isinstance(parent, Tag) and parent.name in PHRASING_PARENTS:
        embed.manual_reason = ("Videoen står inne i et avsnitt sammen med tekst. Størrelsen endres ikke automatisk; "
                               "flytt videoen til et eget avsnitt i Canvas.")
        embed.layout_manual = True
    if embed.manual_reason:
        issues.append("manual")


# --------------------------------------------------------------------------------------- proposals


@dataclass
class Proposal:
    markup: str | None  # replacement for the region (or for the iframe tag only), None = no change
    span: tuple[int, int] | None
    layout_changed: bool
    title: str | None


def _iframe_tag_only(embed: Embed, src: str, title: str | None, options: VideoOptions) -> str:
    """The iframe with only its attributes adjusted (when its layout must stay as it is)."""
    attrs: dict[str, str] = {}
    for name, value in embed.iframe.attrs.items():
        attrs[name] = " ".join(value) if isinstance(value, list) else str(value)
    attrs["src"] = src
    if title:
        attrs["title"] = title
    attrs.setdefault("allowfullscreen", "allowfullscreen")
    if options.lazy:
        attrs.setdefault("loading", "lazy")
    rendered = " ".join(f'{name}="{html_lib.escape(value, quote=True)}"' for name, value in attrs.items())
    inner = embed.iframe.decode_contents()
    return f"<iframe {rendered}>{inner}</iframe>"


def propose(embed: Embed, options: VideoOptions, title: str | None) -> Proposal:
    """The replacement for this embed, or no change when it already follows the standard."""
    src = embed_src(str(embed.iframe.get("src") or ""), embed.url)
    new_title = title if (title and options.fix_title) else (embed.title or None)
    if options.responsive and not embed.layout_manual and embed.span is not None:
        allow = str(embed.iframe.get("allow") or "") or STANDARD_ALLOW
        markup = standard_markup(src=src, title=new_title, ratio=ratio_for(embed.iframe, options), options=options,
                                 allow=allow)
        start, end = embed.span
        current = embed.root.decode()
        if same_markup(current, markup):
            return Proposal(None, None, False, new_title)
        return Proposal(markup, (start, end), True, new_title)
    if embed.iframe_span is None:
        return Proposal(None, None, False, new_title)
    markup = _iframe_tag_only(embed, src, new_title, options)
    if same_markup(embed.iframe.decode(), markup):
        return Proposal(None, None, False, new_title)
    return Proposal(markup, embed.iframe_span, False, new_title)


def splice(source: str, edits: list[tuple[tuple[int, int], str]]) -> str:
    """Replace the given spans (non-overlapping) and nothing else."""
    result = source
    for (start, end), markup in sorted(edits, key=lambda e: e[0][0], reverse=True):
        result = result[:start] + markup + result[end:]
    return result


def find_embed(embeds: list[Embed], video_id: str, occurrence: int) -> Embed | None:
    return next((e for e in embeds if e.video_id == video_id and e.occurrence == occurrence), None)


# ---------------------------------------------------------------------------------------- previews


def _placeholder(iframe: Tag, label: str) -> Tag:
    soup = BeautifulSoup("", "html.parser")
    box = soup.new_tag("div")
    style = _style(str(iframe.get("style") or ""))
    if style.get("position") == "absolute":
        size = "position: absolute; top: 0; left: 0; width: 100%; height: 100%;"
    else:
        width = str(iframe.get("width") or style.get("width") or "560").replace("px", "")
        height = str(iframe.get("height") or style.get("height") or "315").replace("px", "")
        width = f"{width}px" if width.isdigit() else width
        height = f"{height}px" if height.isdigit() else height
        size = f"width: {width}; height: {height};"
    box["style"] = (size + " background: #1f2937; color: #ffffff; display: flex; align-items: center; "
                    "justify-content: center; text-align: center; font-family: sans-serif; font-size: 15px;")
    box.string = f"▶ {label}"
    return box


def preview_markup(markup: str, label: str) -> str:
    """The markup with YouTube players drawn as placeholders of the same size (no request to YouTube)."""
    soup = BeautifulSoup(markup, "html.parser")
    for iframe in soup.find_all("iframe"):
        if parse_youtube_url(str(iframe.get("src") or "")) is not None:
            iframe.replace_with(_placeholder(iframe, label))
    return str(soup)
