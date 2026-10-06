"""Content-quality analyzer: links (external + internal), media availability, HTML hygiene."""

from __future__ import annotations

import logging
from collections import defaultdict
from html import escape
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from emneklar.core.canvas.html import canvas_ref, context_text, element_path, find_media, snippet, text_of
from emneklar.core.canvas.snapshot import SnapObj
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.core.security.ssrf import UrlBlocked, validate_url
from emneklar.features.accessibility.checks.base import ContentDoc, element_signature
from emneklar.features.analysis.core import AnalysisContext, AnalysisTask, ObjectCheck
from emneklar.features.content_quality.hygiene import check_hygiene
from emneklar.features.content_quality.linkcheck import LinkChecker, LinkResult, is_checkable
from emneklar.features.content_quality.rules import CATEGORY_LABELS, RULES, RULESET_VERSION
from emneklar.features.findings.store import FindingDraft, make_fingerprint

log = logging.getLogger(__name__)
DOMAIN = "content_quality"
EDITABLE = {"page", "assignment", "discussion", "quiz", "syllabus"}
STATE_RULE = {"DEAD": "CQ-LINK-DEAD", "TIMEOUT": "CQ-LINK-TIMEOUT", "AUTH_REQUIRED": "CQ-LINK-AUTH",
              "REDIRECT": "CQ-LINK-REDIRECT", "UNKNOWN": "CQ-LINK-UNKNOWN"}
KIND_TO_TYPE = {"pages": "page", "assignments": "assignment", "quizzes": "quiz", "discussion_topics": "discussion",
                "files": "file", "announcements": "discussion"}


def draft(ctx: AnalysisContext, obj: SnapObj, rule_id: str, message: str, *, identity: str,
          location: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None,
          fix: dict[str, Any] | None = None, confidence: str = "high", classification: str | None = None) -> FindingDraft:
    rule = RULES[rule_id]
    modules = ctx.view.module_of.get(obj.ref)
    location = dict(location or {})
    if modules:
        location["module"] = modules[0]
    return FindingDraft(
        domain=DOMAIN, rule_id=rule.id, category=rule.category, classification=classification or rule.classification,
        test_method=rule.testability, severity=rule.severity, confidence=confidence, title=rule.title,
        message=message, remediation=rule.remediation,
        fingerprint=make_fingerprint(ctx.course_id, DOMAIN, rule.id, obj.ref, identity),
        object_type=obj.object_type, object_id=obj.canvas_id, object_title=obj.title, object_url=obj.html_url,
        location=location, evidence=evidence or {},
        fix=fix if obj.object_type in EDITABLE and obj.body is not None else None, ruleset_version=RULESET_VERSION)


def anchor_location(a: Tag) -> dict[str, Any]:
    return {"selector": element_path(a), "snippet": snippet(a), "sig": element_signature(a),
            "context": context_text(a)[:400]}


def link_fix(state: str, result: LinkResult | None, a: Tag) -> dict[str, Any] | None:
    if state == "REDIRECT" and result is not None and result.permanent_redirect and result.final_url:
        return {"type": "replace_link_href", "label": "Oppdater lenken til den nye adressen",
                "params": {"suggestion": result.final_url}}
    if state in ("DEAD", "INTERNAL"):
        return {"type": "replace_link_href", "label": "Erstatt lenken eller fjern den (teksten beholdes)",
                "params": {"suggestion": "", "allow_unlink": True, "text": text_of(a)[:200]}}
    return None


class ContentQualityAnalyzer:
    domain = DOMAIN

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck:
        index = self._content_index(ctx)
        media_ids = {m.canvas_id for m in ctx.view.get("media")}
        media_listed = not any(e.get("kind") == "media" for e in ctx.view.errors)

        async def check(doc: ContentDoc, obj: SnapObj) -> list[FindingDraft]:
            drafts: list[FindingDraft] = []
            for issue in check_hygiene(doc.html):
                drafts.append(draft(ctx, obj, issue.rule_id, issue.message, identity=issue.rule_id,
                                    evidence={"count": issue.count, **issue.evidence},
                                    fix={"type": "cleanup", "label": "Rydd opp i koden"}
                                    if issue.rule_id in ("CQ-HTML-EMPTY-PARAGRAPHS", "CQ-HTML-REDUNDANT-SPANS",
                                                         "CQ-HTML-WORD", "CQ-HTML-BR-SPACING", "CQ-HTML-DEPRECATED")
                                    else None))
            for a in doc.soup.find_all("a", href=True):
                drafts.extend(self._internal_link(ctx, obj, a, index))
            if media_listed:
                for el, ref in find_media(doc.soup):
                    if ref.kind == "canvas_media" and ref.media_id and ref.media_id not in media_ids:
                        drafts.append(draft(ctx, obj, "CQ-MEDIA-MISSING",
                                            f"Medieobjektet {ref.media_id} finnes ikke i emnets medieliste.",
                                            identity=f"media:{ref.media_id}", location=anchor_location(el),
                                            confidence="medium"))
            return drafts

        return check

    # -- internal links --------------------------------------------------------------------------

    @staticmethod
    def _content_index(ctx: AnalysisContext) -> dict[str, dict[str, SnapObj]]:
        index: dict[str, dict[str, SnapObj]] = defaultdict(dict)
        for page in ctx.view.get("page"):
            index["page"][page.canvas_id] = page
            if page.meta.get("page_id"):
                index["page"][str(page.meta["page_id"])] = page
        for kind in ("assignment", "quiz", "discussion", "file", "module"):
            for obj in ctx.view.get(kind):
                index[kind][obj.canvas_id] = obj
        return index

    def _internal_link(self, ctx: AnalysisContext, obj: SnapObj, a: Tag,
                       index: dict[str, dict[str, SnapObj]]) -> list[FindingDraft]:
        href = str(a.get("href") or "")
        ref = canvas_ref(href, ctx.canvas_host)
        if ref is None or ref.kind is None:
            return []
        location = anchor_location(a)
        if ref.course_id != ctx.course_id:
            return [draft(ctx, obj, "CQ-LINK-OTHER-COURSE", f"«{text_of(a)[:60]}» går til emne {ref.course_id}.",
                          identity=f"other:{href}", location=location, evidence={"href": href,
                                                                               "other_course": ref.course_id},
                          fix=link_fix("DEAD", None, a))]
        target_type = KIND_TO_TYPE.get(ref.kind)
        if target_type is None or not ref.ident or ref.kind == "announcements":
            return []
        if target_type == "page":
            target = index["page"].get(ref.ident)
        elif ref.ident.isdigit():
            target = index[target_type].get(ref.ident)
        else:
            return []
        list_kind = {"page": "pages", "assignment": "assignments", "quiz": "quizzes", "discussion": "discussions",
                     "file": "files"}[target_type]
        list_failed = any(e.get("kind") == list_kind for e in ctx.view.errors)
        if target is None:
            if list_failed:
                return []
            return [draft(ctx, obj, "CQ-LINK-INTERNAL-MISSING",
                          f"«{text_of(a)[:60]}» peker til {target_type} «{ref.ident}», som ikke finnes i emnet.",
                          identity=f"missing:{href}", location=location, evidence={"href": href},
                          fix=link_fix("DEAD", None, a))]
        if target.meta.get("published") is False and target_type != "file":
            return [draft(ctx, obj, "CQ-LINK-UNPUBLISHED", f"«{text_of(a)[:60]}» går til upublisert innhold "
                          f"«{target.title}».", identity=f"unpublished:{href}", location=location,
                          evidence={"href": href, "target": target.title})]
        return []

    # -- external links and media ---------------------------------------------------------------------

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        tasks: list[AnalysisTask] = []
        if not ctx.settings.analysis.check_external_links:
            ctx.limitations.append("Eksterne lenker ble ikke kontrollert (slått av under Innstillinger → Analyse).")
            return tasks
        checker = self._checker(ctx)
        links: dict[str, list[tuple[SnapObj, Tag, str]]] = defaultdict(list)
        videos: dict[tuple[str, str], list[tuple[SnapObj, Tag]]] = defaultdict(list)
        for obj in ctx.html_objects():
            if not obj.body:
                continue
            soup = ctx.content_doc(obj).soup
            for a in soup.find_all("a", href=True):
                href = str(a.get("href")).strip()
                if is_checkable(href) and canvas_ref(href, ctx.canvas_host) is None and \
                        (urlsplit(href).hostname or "").lower() != ctx.canvas_host:
                    links[href.split("#")[0]].append((obj, a, "link"))
            for el, ref in find_media(soup):
                if ref.kind in ("youtube", "vimeo") and ref.ident:
                    videos[(ref.kind, ref.ident)].append((obj, el))
            for frame in soup.find_all("iframe", src=True):
                src = str(frame.get("src")).strip()
                host = (urlsplit(src).hostname or "").lower()
                if is_checkable(src) and host and host != ctx.canvas_host and not any(
                        v in host for v in ("youtube", "youtu.be", "vimeo")):
                    links[src.split("#")[0]].append((obj, frame, "embed"))
        for item in ctx.view.get("module_item"):
            external = str(item.meta.get("external_url") or "").strip()
            if item.meta.get("type") == "ExternalUrl" and is_checkable(external) and ctx.in_scope(item):
                anchor = BeautifulSoup(f'<a href="">{escape(item.title)}</a>', "html.parser").a
                assert anchor is not None
                anchor["href"] = external
                links[external.split("#")[0]].append((item, anchor, "module_link"))
        for url, uses in links.items():
            tasks.append(AnalysisTask(type="link", item=f"Lenke: {urlsplit(url).hostname or url[:60]}",
                                      operation="Sjekker lenke", domain=DOMAIN,
                                      run=self._link_runner(ctx, checker, url, uses)))
        for (service, ident), video_uses in videos.items():
            tasks.append(AnalysisTask(type="media", item=f"Video ({service}): {ident}",
                                      operation="Kontrollerer at videoen finnes", domain=DOMAIN,
                                      run=self._video_runner(ctx, checker.client, service, ident, video_uses)))
        return tasks

    def _checker(self, ctx: AnalysisContext) -> LinkChecker:
        if "link_checker" not in ctx.shared:
            settings = ctx.settings.analysis
            transport = ctx.container.link_transport
            client = httpx.AsyncClient(transport=transport, follow_redirects=False) if transport is not None \
                else build_guarded_client(float(settings.link_timeout_seconds),
                                          max_connections=settings.link_concurrency)
            ctx.shared["link_checker"] = LinkChecker(client, timeout=float(settings.link_timeout_seconds),
                                                     per_host=settings.link_per_host, db=ctx.container.db,
                                                     cache_hours=settings.link_cache_hours)
            ctx.shared.setdefault("closers", []).append(client.aclose)
        return ctx.shared["link_checker"]

    def _link_runner(self, ctx: AnalysisContext, checker: LinkChecker, url: str,
                     uses: list[tuple[SnapObj, Tag, str]]) -> Any:
        async def run() -> list[FindingDraft]:
            result = await checker.check(url)
            ctx.shared.setdefault("link_results", {})[url] = result.as_dict() | {
                "used_in": sorted({f"{o.object_type}:{o.canvas_id}|{o.title}" for o, _, _ in uses})}
            if result.state == "WORKING":
                return []
            drafts = []
            for obj, el, kind in uses:
                rule = "CQ-EMBED-BROKEN" if kind == "embed" and result.state == "DEAD" else STATE_RULE[result.state]
                label = text_of(el)[:60] if el.name == "a" else "Innebygd innhold"
                location = {"snippet": url, "context": f"Lenke i modul: {obj.title}"} if kind == "module_link" \
                    else anchor_location(el)
                drafts.append(draft(ctx, obj, rule, f"«{label or url[:60]}»: {result.detail}", identity=f"url:{url}",
                                    location=location,
                                    evidence={"href": url, "state": result.state, "http_status": result.http_status,
                                              "final_url": result.final_url, "checked_at": result.checked_at.isoformat(),
                                              "from_cache": result.from_cache},
                                    fix=link_fix(result.state, result, el) if el.name == "a" else None,
                                    confidence=result.confidence))
            return drafts

        return run

    def _video_runner(self, ctx: AnalysisContext, client: httpx.AsyncClient, service: str, ident: str,
                      uses: list[tuple[SnapObj, Tag]]) -> Any:
        async def run() -> list[FindingDraft]:
            status = await oembed_status(client, service, ident)
            if status is None or status == 200:
                return []
            if status in (404, 400):
                message, confidence = "Videoen finnes ikke lenger hos tjenesten.", "high"
            elif status in (401, 403):
                message, confidence = "Videoen er privat eller kan ikke bygges inn.", "medium"
            else:
                return []
            return [draft(ctx, obj, "CQ-MEDIA-UNAVAILABLE", f"{service.capitalize()}: {message}",
                          identity=f"video:{service}:{ident}", location=anchor_location(el),
                          evidence={"service": service, "video_id": ident, "http_status": status},
                          confidence=confidence) for obj, el in uses]

        return run


async def oembed_status(client: httpx.AsyncClient, service: str, ident: str) -> int | None:
    if service == "youtube":
        url = f"https://www.youtube.com/oembed?format=json&url={quote(f'https://www.youtube.com/watch?v={ident}', safe='')}"
    elif service == "vimeo":
        url = f"https://vimeo.com/api/oembed.json?url={quote(f'https://vimeo.com/{ident}', safe='')}"
    else:
        return None
    try:
        validate_url(url)
        response = await client.get(url)
    except (UrlBlocked, httpx.HTTPError):
        return None
    return response.status_code


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)
