"""Iframes/LTI (4.1.2), media (1.2.x, 1.4.2, 2.2.2) and markup (4.1.1, 4.1.2).

A title on an iframe does not prove that the embedded application is
accessible – external content is always reported as a manual check.
Caption status of external video cannot be verified automatically.
"""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

from emneklar.core.canvas.html import MEDIA_FILE_EXT, element_path, filename_from_url, find_media, norm_text, text_of
from emneklar.features.accessibility.checks.base import ContentDoc, Issue, fix

GENERIC_TITLES = {"iframe", "frame", "embed", "embedded content", "video", "youtube", "youtube video player", "media",
                  "content", "untitled", "player", "external tool", "vimeo", "video player", "innhold", "ramme",
                  "innebygd innhold", "spiller"}
FOCUSABLE = ["a", "button", "input", "select", "textarea", "iframe", "audio", "video"]
EXTERNAL_CAPTIONS_MESSAGE = "Teksting kan ikke verifiseres automatisk."


def _host(src: str) -> str | None:
    host = (urlsplit(src).hostname or "").lower()
    return host or None


def _suggest_title(src: str) -> str:
    host = _host(src) or ""
    if "youtube" in host or "youtu.be" in host:
        return "Video: "
    if "vimeo" in host:
        return "Video: "
    if "/media_attachments_iframe/" in src or "media_objects" in src:
        return "Video: "
    if "/external_tools/" in src:
        return "Verktøy: "
    return ""


def check_iframes(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    external_hosts: set[str] = set()
    for frame in doc.soup.find_all("iframe"):
        src = str(frame.get("src") or "")
        path = element_path(frame)
        hidden = frame.get("aria-hidden") == "true" or str(frame.get("tabindex") or "") == "-1"
        title = norm_text(str(frame.get("title") or "")) or norm_text(str(frame.get("aria-label") or ""))
        if not hidden:
            if not title:
                issues.append(Issue(
                    "UU-IFRAME-NO-TITLE", f"Iframe som viser {_host(src) or src[:80] or 'innhold'} mangler tittel.",
                    element=frame, evidence={"src": src},
                    fix=fix("set_iframe_title", "Legg til en beskrivende tittel", path=path,
                            suggestion=_suggest_title(src))))
            elif title.lower() in GENERIC_TITLES:
                issues.append(Issue(
                    "UU-IFRAME-GENERIC-TITLE", f"Iframen har den generelle tittelen «{title}».", element=frame,
                    evidence={"src": src, "title": title},
                    fix=fix("set_iframe_title", "Skriv en beskrivende tittel", path=path, suggestion=title)))
        host = _host(src)
        is_lti = "/external_tools/" in src
        is_canvas_media = "/media_attachments_iframe/" in src or "/media_objects_iframe" in src
        external = bool(host) and host != (doc.canvas_host or "").lower()
        if is_lti or (external and not is_canvas_media):
            key = "lti" if is_lti else (host or "external")
            if key not in external_hosts:
                external_hosts.add(key)
                label = "et LTI-verktøy" if is_lti else host
                issues.append(Issue(
                    "UU-IFRAME-EXTERNAL", f"Innebygd innhold fra {label} kan ikke kontrolleres automatisk.",
                    element=frame, key=f"external:{key}", evidence={"src": src, "host": host, "lti": is_lti}))
    return issues


def check_media(doc: ContentDoc, media_captions: dict[str, bool | None] | None = None) -> list[Issue]:
    """``media_captions`` maps Canvas media ids / attachment ids to caption status (None = unknown)."""
    issues: list[Issue] = []
    media_captions = media_captions or {}
    soup = doc.soup
    page_text = text_of(soup).lower()
    has_transcript_hint = any(w in page_text for w in ("transkripsjon", "transcript", "tekstversjon", "manus"))
    for el, ref in find_media(soup):
        path = element_path(el)
        src = ref.src.lower()
        if el.has_attr("autoplay") or "autoplay=1" in src or "autoplay=true" in src:
            issues.append(Issue("UU-MEDIA-AUTOPLAY", "Innholdet starter automatisk.", element=el,
                                key=f"autoplay:{path}",
                                fix=fix("remove_autoplay", "Slå av autoavspilling", path=path)))
        if ref.kind in ("canvas_media", "canvas_attachment"):
            status = None
            for key in (ref.media_id, ref.ident):
                if key and media_captions.get(key) is not None:
                    status = media_captions[key]
                    break
            media_type = str(el.get("data-media-type") or "video")
            if status is False:
                issues.append(Issue(
                    "UU-MEDIA-CANVAS-CAPTIONS",
                    f"{'Lydopptaket' if media_type == 'audio' else 'Videoen'} i Canvas har ikke tekstspor.",
                    element=el, confidence="medium", evidence={"media_id": ref.ident, "kind": ref.kind}))
            elif status is None:
                issues.append(Issue(
                    "UU-MEDIA-EXTERNAL-CAPTIONS",
                    "Teksting kunne ikke kontrolleres for denne Canvas-videoen.", element=el,
                    evidence={"media_id": ref.ident, "kind": ref.kind}))
        elif ref.kind in ("youtube", "vimeo", "other_embed"):
            issues.append(Issue("UU-MEDIA-EXTERNAL-CAPTIONS", EXTERNAL_CAPTIONS_MESSAGE, element=el,
                                evidence={"service": ref.kind, "video_id": ref.ident, "src": ref.src}))
        elif ref.kind == "html5_video":
            tracks = [t for t in el.find_all("track") if str(t.get("kind") or "").lower() in ("captions", "subtitles")]
            if not tracks:
                issues.append(Issue("UU-MEDIA-HTML5-TRACK", "Video-elementet har ikke tekstspor.", element=el,
                                    confidence="medium"))
        elif ref.kind == "html5_audio" and not has_transcript_hint:
            issues.append(Issue("UU-MEDIA-AUDIO-ALT", "Lydopptak uten synlig transkripsjon i nærheten.", element=el,
                                confidence="low"))
    for a in soup.find_all("a", href=True):
        name = filename_from_url(str(a.get("href"))).lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if MEDIA_FILE_EXT.get(ext) == "audio" and not has_transcript_hint:
            issues.append(Issue("UU-MEDIA-AUDIO-ALT", f"Lenke til lydfilen «{name}» uten synlig transkripsjon.",
                                element=a, confidence="low", key=f"audio-link:{name}"))
    return issues


def check_markup(doc: ContentDoc) -> list[Issue]:
    issues: list[Issue] = []
    soup = doc.soup
    for el in soup.find_all(["marquee", "blink"]):
        issues.append(Issue("UU-MOVING", f"<{el.name}> beveger eller blinker automatisk.", element=el,
                            fix=fix("unwrap_element", "Vis teksten statisk", path=element_path(el))))
    for el in soup.find_all(True, attrs={"aria-hidden": "true"}):
        focusable = [f for f in el.find_all(FOCUSABLE) if not (f.name == "a" and not f.get("href"))
                     and str(f.get("tabindex") or "") != "-1"]
        if focusable:
            issues.append(Issue("UU-ARIA-HIDDEN-FOCUS",
                                f"Skjult område inneholder {len(focusable)} element(er) som kan få tastaturfokus.",
                                element=el))
    ids = Counter(str(el.get("id")) for el in soup.find_all(id=True))
    for value, count in ids.items():
        if count > 1:
            first = soup.find(id=value)
            issues.append(Issue("UU-DUPLICATE-ID", f"id=\"{value}\" brukes {count} ganger.", element=first,
                                key=f"dup-id:{value}"))
    return issues

