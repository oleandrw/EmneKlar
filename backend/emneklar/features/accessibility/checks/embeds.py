"""Iframes/LTI (4.1.2), media (1.2.x, 1.4.2, 2.2.2) and markup (4.1.1, 4.1.2).

A title on an iframe does not prove that the embedded application is
accessible – external content is always reported as a manual check.
Caption status of external video cannot be verified automatically.
Media rules depend on what the recording is (media_kinds.py): audio only is
checked against 1.2.1 (text alternative), video with sound against 1.2.2
(captions); a text near a video never replaces its captions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from bs4 import Tag

from emneklar.core.canvas.html import (
    MEDIA_FILE_EXT,
    MediaRef,
    element_path,
    filename_from_url,
    find_media,
    is_generic_iframe_title,
    norm_text,
)
from emneklar.features.accessibility.checks.base import ContentDoc, Issue, fix
from emneklar.features.accessibility.media_kinds import (
    AUDIO,
    UNKNOWN,
    VIDEO,
    VIDEO_NO_AUDIO,
    MediaKind,
    media_alternative_hint,
    media_keys,
    resolve_kind,
    sources_of,
    text_alternative_candidates,
)

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
            elif is_generic_iframe_title(title):
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


def _caption_status(ref: MediaRef, media_captions: dict[str, bool | None]) -> bool | None:
    for key in (ref.media_id, ref.ident):
        if key and media_captions.get(key) is not None:
            return media_captions[key]
    return None


def _audio_issue(el: Tag, evidence: dict[str, Any], *, where: str, track: bool | None,
                 key: str | None = None) -> Issue:
    """WCAG 1.2.1 for audio only: a text alternative (transcript) – never «missing captions». A manual check:
    EmneKlar cannot tell whether a text near the recording is a full alternative, so candidates are only pointed
    out, and the teacher confirms."""
    candidates = text_alternative_candidates(el)
    hint = media_alternative_hint(el)
    parts = [f"{where} – kontroller at det har et tekstalternativ (transkripsjon)."]
    if track:
        parts.append("Canvas har et tekstspor for opptaket, men for rene lydopptak er kravet et tekstalternativ på "
                     "siden eller via en tydelig lenke.")
    if candidates:
        parts.append(f"Mulig tekstalternativ ved opptaket: {'; '.join(candidates)}. Kontroller at det gjengir hele "
                     "opptaket.")
    if hint:
        parts.append(f"Teksten ved opptaket kan tyde på at det er en innlesing av tekst på siden: «{hint}».")
    data = evidence | {"text_alternative_candidates": candidates or None, "media_alternative_hint": hint}
    return Issue("UU-MEDIA-AUDIO-ALT", " ".join(parts), element=el, confidence="medium", evidence=data, key=key)


def _kind_issue(el: Tag, kind: MediaKind, evidence: dict[str, Any], *, where: str, track: bool | None,
                key: str | None = None) -> Issue | None:
    """The finding for audio only, video without sound and an unknown kind. Video with sound (captions) is decided
    by the caller."""
    if kind.kind == AUDIO:
        return _audio_issue(el, evidence, where=where, track=track, key=key)
    if kind.kind == VIDEO_NO_AUDIO:
        return Issue("UU-MEDIA-VIDEO-ONLY-ALT", "Video uten lyd – kontroller at den har et tekst- eller lydalternativ.",
                     element=el, confidence="medium", evidence=evidence, key=key)
    if kind.kind == UNKNOWN:
        track_note = {True: " Canvas har et tekstspor for opptaket.",
                      False: " Canvas har ikke registrert noe tekstspor for opptaket."}.get(track, "") \
            if track is not None else ""
        return Issue("UU-MEDIA-TYPE-UNKNOWN",
                     f"Medietypen er ukjent: {kind.basis}{track_note} Velg hva opptaket er, så viser EmneKlar "
                     "riktig krav.", element=el, confidence="medium", evidence=evidence, key=key)
    return None


def check_media(doc: ContentDoc, media_captions: dict[str, bool | None] | None = None,
                youtube_captions: dict[str, str | None] | None = None, *,
                media_kinds: dict[str, MediaKind] | None = None, assessed: dict[str, str] | None = None) -> list[Issue]:
    """``media_captions`` maps Canvas media ids / attachment ids to caption status (None = unknown);
    ``youtube_captions`` maps YouTube video ids to ``manual | auto | none | unavailable`` (None = not checked);
    ``media_kinds`` holds Canvas' metadata per media key and ``assessed`` the teacher's statement per media key
    (media_kinds.py). The kind decides the rule: audio only → 1.2.1 text alternative, video with sound → 1.2.2
    captions, video without sound → 1.2.1 alternative, unknown → manual check of the kind."""
    issues: list[Issue] = []
    media_captions = media_captions or {}
    youtube_captions = youtube_captions or {}
    soup = doc.soup
    handled: set[int] = set()
    for el, ref in find_media(soup):
        handled.add(id(el))
        path = element_path(el)
        src = ref.src.lower()
        if el.has_attr("autoplay") or "autoplay=1" in src or "autoplay=true" in src:
            issues.append(Issue("UU-MEDIA-AUTOPLAY", "Innholdet starter automatisk.", element=el,
                                key=f"autoplay:{path}",
                                fix=fix("remove_autoplay", "Slå av autoavspilling", path=path)))
        kind = resolve_kind(el, ref, assessed=assessed, canvas=media_kinds)
        keys = media_keys(el, ref)
        evidence: dict[str, Any] = {"media_key": keys[0] if keys else None, **kind.as_evidence()}
        if ref.kind in ("canvas_media", "canvas_attachment"):
            status = _caption_status(ref, media_captions)
            evidence |= {"media_id": ref.ident, "kind": ref.kind, "captions": status}
            if kind.kind != VIDEO:
                found = _kind_issue(el, kind, evidence, where="Lydopptak i Canvas", track=status)
                if found:
                    issues.append(found)
            elif status is False:
                issues.append(Issue("UU-MEDIA-CANVAS-CAPTIONS", "Videoen i Canvas har ikke tekstspor.", element=el,
                                    confidence="medium", evidence=evidence))
            elif status is None:
                issues.append(Issue("UU-MEDIA-EXTERNAL-CAPTIONS",
                                    "Teksting kunne ikke kontrolleres for denne Canvas-videoen.", element=el,
                                    evidence=evidence))
        elif ref.kind in ("youtube", "vimeo", "other_embed"):
            evidence |= {"service": ref.kind, "video_id": ref.ident, "src": ref.src}
            state = youtube_captions.get(ref.ident) if ref.kind == "youtube" and ref.ident else None
            if kind.kind != VIDEO:
                found = _kind_issue(el, kind, evidence, where="Lydopptaket", track=None)
                if found:
                    issues.append(found)
            elif state:
                evidence["captions"] = state
                if state == "none":
                    issues.append(Issue("UU-MEDIA-YOUTUBE-NO-CAPTIONS", "YouTube-videoen har ingen teksting.",
                                        element=el, confidence="medium", evidence=evidence))
                elif state == "auto":
                    issues.append(Issue("UU-MEDIA-YOUTUBE-AUTO-CAPTIONS",
                                        "YouTube-videoen har bare automatisk teksting fra YouTube.", element=el,
                                        confidence="medium", evidence=evidence))
                # manual: the uploader added captions – nothing to report. unavailable: the content quality check
                # says so.
            else:
                issues.append(Issue("UU-MEDIA-EXTERNAL-CAPTIONS", EXTERNAL_CAPTIONS_MESSAGE, element=el,
                                    evidence=evidence))
        elif ref.kind in ("html5_video", "html5_audio"):
            tracks = [t for t in el.find_all("track") if str(t.get("kind") or "").lower() in ("captions", "subtitles")]
            evidence |= {"src": next(iter(sources_of(el)), None), "captions": bool(tracks)}
            if kind.kind == VIDEO:
                if not tracks:
                    issues.append(Issue("UU-MEDIA-HTML5-TRACK", "Video-elementet har ikke tekstspor.", element=el,
                                        confidence="medium", evidence=evidence))
            else:
                found = _kind_issue(el, kind, evidence, where="Lydopptaket", track=bool(tracks))
                if found:
                    issues.append(found)
    for a in soup.find_all("a", href=True):
        if id(a) in handled:
            continue
        name = filename_from_url(str(a.get("href"))).lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if MEDIA_FILE_EXT.get(ext) != "audio":
            continue
        kind = resolve_kind(a, None, assessed=assessed)
        keys = media_keys(a, None)
        evidence = {"media_key": keys[0] if keys else None, **kind.as_evidence(), "href": str(a.get("href"))}
        found = _kind_issue(a, kind, evidence, where=f"Lenke til lydfilen «{name}»", track=None,
                            key=f"audio-link:{name}") if kind.kind != VIDEO else None
        if found:
            issues.append(found)
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

