"""What a recording is – audio only, video with sound, video without sound, or unknown – and hints about its
text alternative.

The requirement depends on the kind (verified against Uutilsynet's guidance on 1.2.1 and W3C Understanding 1.2.2):

* **Audio only** (prerecorded): WCAG 1.2.1 – an equivalent text alternative, normally a transcript of speech and of
  other sounds needed to understand the content, on the page or behind a clear link. Not synchronised captions.
* **Video with sound**: WCAG 1.2.2 – captions that follow the sound. A separate transcript does not replace them.
* **Video without sound**: WCAG 1.2.1 – a text or audio alternative. 1.2.2 does not apply.
* Both criteria exempt media that is an alternative to text on the page and clearly labelled as such.

Evidence, strongest first: the teacher's own statement (:class:`MediaAssessment`), Canvas' metadata (the media
object's ``media_type``, the file's ``content-type``), Canvas' markup (``data-media-type`` / ``?type=`` written by the
editor, ``data-media_comment_type``), the file type in the player, an ``<audio>`` element (it can only play sound), a
video service. A ``<video>`` element alone proves nothing: Canvas plays audio recordings in a video player too, and a
Canvas data fix-up writes ``data-media-type="video"`` when it does not know the type – so metadata wins over markup.
Whether a video has sound cannot be read from Canvas; only the teacher can say «video uten lyd».
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import Tag

from emneklar.core.canvas.html import MediaRef, filename_from_url, norm_text, text_of

AUDIO = "audio"
VIDEO = "video"
VIDEO_NO_AUDIO = "video_no_audio"
UNKNOWN = "unknown"
USER_KINDS = (AUDIO, VIDEO, VIDEO_NO_AUDIO)
KIND_LABELS = {AUDIO: "Lydopptak", VIDEO: "Video med lyd", VIDEO_NO_AUDIO: "Video uten lyd", UNKNOWN: "Ukjent medietype"}

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".oga", ".opus", ".flac"}
VIDEO_EXT = {".mp4", ".m4v", ".mov"}  # .webm and .ogg hold audio as often as video: not evidence either way
TRANSCRIPT_WORDS = ("transkripsjon", "transkribert", "transcript", "tekstversjon", "tekstutgave", "manus",
                    "tekst til opptaket", "teksten til opptaket", "tekst til lydopptaket")
MEDIA_ALTERNATIVE_WORDS = ("innlest", "opplest", "opplesing", "opplesning", "lydversjon", "lydutgave",
                           "audio version", "read aloud", "lytt til teksten")
HEADINGS = ("h2", "h3", "h4", "h5", "h6")
BLOCKS = ("p", "div", "figure", "li", "section", "td", "blockquote", *HEADINGS)


@dataclass(frozen=True)
class MediaKind:
    kind: str  # audio|video|video_no_audio|unknown
    source: str  # user|canvas_media|canvas_file|markup|file_type|element|service|none
    basis: str  # what the kind is based on, for the teacher

    def as_evidence(self) -> dict[str, str]:
        return {"media_kind": self.kind, "kind_source": self.source, "kind_basis": self.basis}


def mime_kind(value: object) -> str | None:
    """``audio`` / ``video`` from a MIME type or Canvas ``media_type`` (``audio``, ``video/*``, ``audio/mp4``)."""
    top = str(value or "").strip().lower().split("/")[0]
    return top if top in (AUDIO, VIDEO) else None


def _word(kind: str) -> str:
    return "lyd" if kind == AUDIO else "video"


def user_kind(kind: str) -> MediaKind:
    return MediaKind(kind, "user", f"Du har angitt at opptaket er {KIND_LABELS[kind].lower()}.")


def canvas_media_kind(media_type: object) -> MediaKind | None:
    kind = mime_kind(media_type)
    return MediaKind(kind, "canvas_media", f"Canvas oppgir medietypen «{media_type}» for opptaket.") if kind else None


def canvas_file_kind(content_type: object) -> MediaKind | None:
    kind = mime_kind(content_type)
    return MediaKind(kind, "canvas_file", f"Filen i Canvas har filtypen {content_type}.") if kind else None


def sources_of(el: Tag) -> list[str]:
    found = [str(el.get("src") or el.get("data") or el.get("href") or "")]
    found += [str(s.get("src") or "") for s in el.find_all("source")]
    return [s for s in found if s]


def media_keys(el: Tag, ref: MediaRef | None) -> list[str]:
    """Identity of the recording, for the teacher's statement and Canvas' metadata (most specific first)."""
    keys: list[str] = []
    if ref is not None:
        if ref.media_id:
            keys.append(f"media:{ref.media_id}")
        if ref.kind == "canvas_attachment" and ref.ident:
            keys.append(f"attachment:{ref.ident}")
        elif ref.kind == "canvas_media" and ref.ident and ref.ident != ref.media_id:
            keys.append(f"media:{ref.ident}")
        if ref.kind in ("youtube", "vimeo") and ref.ident:
            keys.append(f"{ref.kind}:{ref.ident}")
    if not keys:
        src = next(iter(sources_of(el)), "")
        if src:
            keys.append(f"src:{src.split('?')[0][:390]}")
    return keys


def markup_kind(el: Tag, ref: MediaRef | None) -> MediaKind | None:
    """The kind as the content itself states it (Canvas' editor markup, the file type, the element, the service)."""
    for attr in ("data-media-type", "data-media_comment_type"):
        kind = mime_kind(el.get(attr))
        if kind:
            return MediaKind(kind, "markup", f"Canvas har merket innbyggingen som {_word(kind)} ({attr}).")
    for src in sources_of(el):
        if "media_attachments_iframe" in src or "media_objects_iframe" in src:
            kind = mime_kind((parse_qs(urlsplit(src).query).get("type") or [""])[0])
            if kind:
                return MediaKind(kind, "markup", f"Canvas har merket innbyggingen som {_word(kind)} (type={kind}).")
    for source in el.find_all("source"):
        kind = mime_kind(source.get("type"))
        if kind:
            return MediaKind(kind, "file_type", f"Avspilleren oppgir filtypen {source.get('type')}.")
    if el.name == "audio":
        return MediaKind(AUDIO, "element", "Avspilleren er et lydelement (<audio>), som bare kan spille av lyd.")
    if ref is not None and ref.kind in ("youtube", "vimeo"):
        service = "YouTube" if ref.kind == "youtube" else "Vimeo"
        return MediaKind(VIDEO, "service", f"{service} er en videotjeneste.")
    for src in sources_of(el):
        name = filename_from_url(src).lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext in AUDIO_EXT:
            return MediaKind(AUDIO, "file_type", f"Filen er en lydfil ({ext}).")
        if ext in VIDEO_EXT:
            return MediaKind(VIDEO, "file_type", f"Filen er en videofil ({ext}).")
    return None


def unknown_kind(el: Tag) -> MediaKind:
    if el.name == "video":
        basis = ("Canvas oppgir ikke medietypen, og et videoelement kan også spille av bare lyd – Canvas viser "
                 "lydopptak i en videoavspiller.")
    else:
        basis = "Canvas oppgir ikke om opptaket er lyd eller video."
    return MediaKind(UNKNOWN, "none", basis)


def resolve_kind(el: Tag, ref: MediaRef | None, *, assessed: dict[str, str] | None = None,
                 canvas: dict[str, MediaKind] | None = None) -> MediaKind:
    keys = media_keys(el, ref)
    for key in keys:
        if (assessed or {}).get(key) in USER_KINDS:
            return user_kind(str((assessed or {})[key]))
    for key in keys:
        if key in (canvas or {}):
            return (canvas or {})[key]
    return markup_kind(el, ref) or unknown_kind(el)


# -- hints about a text alternative (never proof) ---------------------------------------------------------------


def _block(el: Tag) -> Tag:
    node: Tag = el
    while node.parent is not None and isinstance(node.parent, Tag) and node.name not in BLOCKS:
        if node.parent.name in ("body", "[document]"):
            break
        node = node.parent
    return node


def _neighbourhood(el: Tag, span: int = 3) -> list[Tag]:
    block = _block(el)
    nodes = [block]
    for direction in ("previous", "next"):
        sibling = block
        for _ in range(span):
            sibling = getattr(sibling, f"find_{direction}_sibling")()
            if sibling is None:
                break
            nodes.append(sibling)
    return nodes


def _short(text: str, limit: int = 100) -> str:
    text = norm_text(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def text_alternative_candidates(el: Tag) -> list[str]:
    """Links and headings near the recording that look like a transcript. Shown to the teacher as «mulig
    tekstalternativ» – a word like «transkripsjon» does not prove that the text is a full alternative."""
    found: list[str] = []
    for node in _neighbourhood(el):
        anchors = [node] if node.name == "a" else node.find_all("a")
        for a in anchors:
            label = norm_text(text_of(a))
            target = str(a.get("href") or "").lower()
            if label and (any(w in label.lower() for w in TRANSCRIPT_WORDS) or any(w in target for w in TRANSCRIPT_WORDS)):
                found.append(f"Lenke: «{_short(label)}»")
        headings = [node] if node.name in HEADINGS else node.find_all(list(HEADINGS))
        for h in headings:
            label = norm_text(text_of(h))
            if any(w in label.lower() for w in TRANSCRIPT_WORDS):
                found.append(f"Overskrift: «{_short(label)}»")
    return list(dict.fromkeys(found))[:3]


def media_alternative_hint(el: Tag) -> str | None:
    """Text near the recording that may label it as a reading of text on the page («Innlest versjon av teksten»)."""
    for node in _neighbourhood(el, span=2):
        text = norm_text(text_of(node))
        lower = text.lower()
        for word in MEDIA_ALTERNATIVE_WORDS:
            at = lower.find(word)
            if at >= 0:
                start = max(0, at - 40)
                return _short(("…" if start else "") + text[start:at + 80])
    return None
