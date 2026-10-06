"""Course-structure analyzer (advisory suggestions with evidence and qualitative confidence)."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from emneklar.core.canvas.html import canvas_ref, parse_html, text_of
from emneklar.core.canvas.snapshot import SnapObj
from emneklar.features.analysis.core import AnalysisContext, AnalysisTask, ObjectCheck
from emneklar.features.course_structure.rules import RULES, RULESET_VERSION
from emneklar.features.course_structure.similarity import TfIdf, jaccard, shingles
from emneklar.features.findings.store import FindingDraft, make_fingerprint

DOMAIN = "structure"
INTRO = re.compile(r"(?i)\b(intro|introduksjon|innledning|oversikt|velkommen|om modulen|om emnet|læringsmål|"
                   r"start her|kom i gang|overview|welcome)\b")
NAME_PATTERN = re.compile(r"^\s*(?P<prefix>[A-Za-zÆØÅæøå]+)\s*(?P<num>\d{1,2})\s*(?P<sep>[:–—\-.]?)\s*(?P<rest>.*)$")
CONTENT_TYPES = {"Page": "page", "Assignment": "assignment", "Discussion": "discussion", "Quiz": "quiz", "File": "file"}


def _draft(ctx: AnalysisContext, obj: SnapObj, rule_id: str, message: str, *, identity: str, confidence: str,
           evidence: dict[str, Any] | None = None, fix: dict[str, Any] | None = None,
           module_name: str | None = None) -> FindingDraft:
    rule = RULES[rule_id]
    location: dict[str, Any] = {}
    modules = ctx.view.module_of.get(obj.ref)
    if module_name or modules:
        location["module"] = module_name or modules[0]  # type: ignore[index]
    return FindingDraft(
        domain=DOMAIN, rule_id=rule.id, category=rule.category, classification=rule.classification,
        test_method=rule.testability, severity=rule.severity, confidence=confidence, title=rule.title,
        message=message, remediation=rule.remediation,
        fingerprint=make_fingerprint(ctx.course_id, DOMAIN, rule.id, obj.ref, identity),
        object_type=obj.object_type, object_id=obj.canvas_id, object_title=obj.title, object_url=obj.html_url,
        location=location, evidence={"impact": rule.impact, **(evidence or {})}, fix=fix,
        ruleset_version=RULESET_VERSION)


def _due(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class StructureAnalyzer:
    domain = DOMAIN

    def object_check(self, ctx: AnalysisContext) -> ObjectCheck | None:
        return None

    def tasks(self, ctx: AnalysisContext) -> list[AnalysisTask]:
        modules = [m for m in ctx.view.modules() if ctx.in_scope(m)]
        objects = [m.ref for m in modules] + [i.ref for m in modules for i in ctx.view.items_of(m.canvas_id)]

        async def run() -> list[FindingDraft]:
            return analyze_structure(ctx, modules)

        return [AnalysisTask(type="structure", item="Emnestruktur", operation="Analyserer moduler og rekkefølge",
                             domain=DOMAIN, run=run, objects=objects)]


def analyze_structure(ctx: AnalysisContext, modules: list[SnapObj]) -> list[FindingDraft]:
    view = ctx.view
    drafts: list[FindingDraft] = []
    whole_course = ctx.request.scope == "course"
    text_by_ref = {obj.ref: text_of(parse_html(obj.body)) for kind in ("page", "assignment", "discussion", "quiz")
                   for obj in view.get(kind) if obj.body}

    # -- orphans (only meaningful for the whole course) ------------------------------------------
    if whole_course:
        linked: set[str] = set()
        for kind in ("page", "assignment", "discussion", "quiz", "syllabus"):
            for obj in view.get(kind):
                for a in parse_html(obj.body).find_all("a", href=True) if obj.body else []:
                    ref = canvas_ref(str(a.get("href")), ctx.canvas_host)
                    if ref and ref.ident:
                        kind_map = {"pages": "page", "assignments": "assignment", "quizzes": "quiz",
                                    "discussion_topics": "discussion"}
                        if ref.kind in kind_map:
                            linked.add(f"{kind_map[ref.kind]}:{ref.ident}")
        page_ids = {str(p.meta.get("page_id")): p.canvas_id for p in view.get("page")}
        linked |= {f"page:{page_ids[r.split(':', 1)[1]]}" for r in list(linked)
                   if r.startswith("page:") and r.split(":", 1)[1] in page_ids}
        for kind in ("page", "assignment", "discussion", "quiz"):
            for obj in view.get(kind):
                if obj.meta.get("published") is False or obj.meta.get("front_page") or obj.ref in view.module_of:
                    continue
                if kind == "assignment" and (obj.meta.get("quiz_id") or "online_quiz" in (obj.meta.get("submission_types")
                                                                                          or [])):
                    continue
                if obj.ref in linked:
                    continue
                drafts.append(_draft(ctx, obj, "ST-ORPHAN", f"«{obj.title}» ligger ikke i noen modul og er ikke lenket "
                                     "fra annet innhold.", identity="orphan", confidence="medium"))

    # -- per module -----------------------------------------------------------------------------------
    for module in modules:
        items = view.items_of(module.canvas_id)
        content_items = [i for i in items if i.meta.get("type") != "SubHeader"]
        if not items:
            drafts.append(_draft(ctx, module, "ST-EMPTY-MODULE", f"Modulen «{module.title}» er tom.", identity="empty",
                                 confidence="high", module_name=module.title))
            continue
        if len(content_items) >= 3:
            first = items[0]
            if not (first.meta.get("type") in ("Page", "SubHeader") and INTRO.search(first.title)):
                drafts.append(_draft(ctx, module, "ST-NO-INTRO", f"«{module.title}» starter med «{first.title}».",
                                     identity="intro", confidence="low", module_name=module.title,
                                     evidence={"first_item": first.title}))
        if len(items) > 25:
            drafts.append(_draft(ctx, module, "ST-LONG-MODULE", f"«{module.title}» har {len(items)} elementer.",
                                 identity="long", confidence="high", module_name=module.title,
                                 evidence={"items": len(items)}))
        if module.meta.get("published") is not False:
            for item in items:
                if item.meta.get("published") is False and item.meta.get("type") != "SubHeader":
                    drafts.append(_draft(ctx, item, "ST-UNPUBLISHED-ITEM", f"«{item.title}» i «{module.title}» er "
                                         "ikke publisert.", identity="unpublished", confidence="high",
                                         module_name=module.title))

    drafts.extend(_naming(ctx, modules))
    drafts.extend(_due_order(ctx, modules))
    drafts.extend(_duplicates(ctx, text_by_ref))
    drafts.extend(_misplaced(ctx, modules, text_by_ref))
    return drafts


def _naming(ctx: AnalysisContext, modules: list[SnapObj]) -> list[FindingDraft]:
    parsed = [(m, NAME_PATTERN.match(m.title)) for m in modules]
    matching = [(m, p) for m, p in parsed if p]
    if len(matching) < 3:
        return []
    prefixes: dict[str, int] = defaultdict(int)
    seps: dict[str, int] = defaultdict(int)
    for _, p in matching:
        prefixes[p.group("prefix")] += 1
        seps[p.group("sep") or ""] += 1
    prefix = max(prefixes, key=prefixes.get)  # type: ignore[arg-type]
    sep = max(seps, key=seps.get)  # type: ignore[arg-type]
    if prefixes[prefix] < 2 or prefixes[prefix] / len(matching) < 0.5:
        return []
    drafts = []
    for module, p in matching:
        if p.group("prefix").lower() != prefix.lower():
            continue
        rest = p.group("rest").strip()
        if not rest:
            continue
        good_rest = rest[0].upper() + rest[1:]
        separator = f" {sep} " if sep in ("–", "—", "-") else (f"{sep} " if sep else " ")
        suggestion = f"{prefix} {p.group('num')}{separator}{good_rest}".replace("  ", " ")
        if suggestion != module.title:
            drafts.append(_draft(
                ctx, module, "ST-NAMING", f"«{module.title}» avviker fra mønsteret «{prefix} N{separator}Tittel».",
                identity="naming", confidence="medium", module_name=module.title,
                evidence={"suggestion": suggestion, "pattern": f"{prefix} N{separator}Tittel"},
                fix={"type": "rename_module", "label": f"Endre navn til «{suggestion}»",
                     "params": {"module_id": module.canvas_id, "name": suggestion}}))
    return drafts


def _due_order(ctx: AnalysisContext, modules: list[SnapObj]) -> list[FindingDraft]:
    view = ctx.view
    latest: datetime | None = None
    latest_title = ""
    latest_module = ""
    drafts = []
    for module in modules:
        dues = []
        for item in view.items_of(module.canvas_id):
            due = _due((item.meta.get("content_details") or {}).get("due_at"))
            if due is None:
                ref = view.item_content_ref(item)
                content = view.by_ref.get(ref or "")
                due = _due(content.meta.get("due_at")) if content else None
            if due is not None:
                dues.append((due, item))
        for due, item in sorted(dues, key=lambda x: x[0]):
            if latest is not None and due < latest - timedelta(days=1):
                drafts.append(_draft(
                    ctx, item, "ST-ORDER-DUE",
                    f"«{item.title}» i «{module.title}» har frist {due:%d.%m.%Y}, før «{latest_title}» i "
                    f"«{latest_module}» ({latest:%d.%m.%Y}).", identity="due-order", confidence="high",
                    module_name=module.title, evidence={"due_at": due.isoformat(), "earlier_module": latest_module}))
        if dues:
            module_latest = max(d for d, _ in dues)
            if latest is None or module_latest > latest:
                latest = module_latest
                latest_title = max(dues, key=lambda x: x[0])[1].title
                latest_module = module.title
    return drafts


def _duplicates(ctx: AnalysisContext, text_by_ref: dict[str, str]) -> list[FindingDraft]:
    drafts = []
    pages = [p for p in ctx.view.get("page") if ctx.in_scope(p)]
    by_title: dict[str, list[SnapObj]] = defaultdict(list)
    for page in pages:
        by_title[page.title.strip().lower()].append(page)
    reported: set[str] = set()
    for title, same in by_title.items():
        if len(same) > 1 and title:
            for page in same[1:]:
                reported.add(page.ref)
                drafts.append(_draft(ctx, page, "ST-DUPLICATE", f"«{page.title}» har samme tittel som en annen side.",
                                     identity="dup-title", confidence="high",
                                     evidence={"same_as": [p.title for p in same if p is not page][:3]}))
    sh = {p.ref: shingles(text_by_ref.get(p.ref, "")) for p in pages if len(text_by_ref.get(p.ref, "").split()) >= 40}
    refs = sorted(sh)
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            if b in reported:
                continue
            score = jaccard(sh[a], sh[b])
            if score >= 0.85:
                page = ctx.view.by_ref[b]
                other = ctx.view.by_ref[a]
                reported.add(b)
                drafts.append(_draft(ctx, page, "ST-DUPLICATE", f"«{page.title}» har nesten samme innhold som "
                                     f"«{other.title}».", identity=f"dup-content:{a}", confidence="medium",
                                     evidence={"same_as": [other.title]}))
    return drafts


def _misplaced(ctx: AnalysisContext, modules: list[SnapObj], text_by_ref: dict[str, str]) -> list[FindingDraft]:
    view = ctx.view
    all_modules = view.modules()
    if len(all_modules) < 3:
        return []
    documents: dict[str, str] = {}
    membership: dict[str, list[str]] = defaultdict(list)  # module id -> item keys
    item_info: dict[str, tuple[SnapObj, SnapObj]] = {}
    for module in all_modules:
        documents[f"module:{module.canvas_id}"] = module.title
        for item in view.items_of(module.canvas_id):
            ref = view.item_content_ref(item)
            text = text_by_ref.get(ref or "", "")
            if len(text.split()) < 40:
                continue
            key = f"item:{item.canvas_id}"
            documents[key] = f"{item.title} {text}"
            membership[module.canvas_id].append(key)
            item_info[key] = (item, module)
    if len(item_info) < 4:
        return []
    tfidf = TfIdf(documents)
    drafts = []
    in_scope = {m.canvas_id for m in modules}
    for key, (item, module) in item_info.items():
        if module.canvas_id not in in_scope:
            continue
        vec = tfidf.vectors[key]

        def profile(module_id: str, exclude: str | None = None) -> dict[str, float]:
            vectors = [tfidf.vectors[k] for k in membership[module_id] if k != exclude]
            vectors.append(tfidf.vectors[f"module:{module_id}"])
            return tfidf.centroid(vectors)

        own = tfidf.cosine(vec, profile(module.canvas_id, exclude=key))
        best_module, best = None, 0.0
        for other in all_modules:
            if other.canvas_id == module.canvas_id or not membership[other.canvas_id]:
                continue
            score = tfidf.cosine(vec, profile(other.canvas_id))
            if score > best:
                best_module, best = other, score
        if best_module is None or best < 0.25 or best < own * 1.6 + 0.05:
            continue
        confidence = "medium" if best >= own * 2.5 + 0.05 else "low"
        terms = tfidf.shared_terms(vec, profile(best_module.canvas_id))
        drafts.append(_draft(
            ctx, item, "ST-MISPLACED", f"«{item.title}» ligger i «{module.title}», men ligner mer på innholdet i "
            f"«{best_module.title}».", identity="misplaced", confidence=confidence, module_name=module.title,
            evidence={"current_module": module.title, "suggested_module": best_module.title, "shared_terms": terms},
            fix={"type": "move_item", "label": f"Flytt til «{best_module.title}»",
                 "params": {"item_id": item.canvas_id, "from_module": module.canvas_id,
                            "to_module": best_module.canvas_id, "item_type": item.meta.get("type")}}))
    return drafts
