"""KI-forslag til alt-tekst – prepared ahead of review in a controlled queue.

* **Privacy first.** Nothing is sent before the teacher has seen what will be sent («Forbered forslag» shows the
  payload summary and the model) – unless only a local model is used or «Bekreft før innhold sendes» is off. Only the
  image and a short excerpt of the surrounding course text are sent, never student data. AI stays optional: every
  image finding can be fixed by hand, and every suggestion is marked «KI-forslag – må vurderes».
* **Controlled queue.** At most :data:`CONCURRENCY` images are processed at a time, in one background job per course.
  The image the teacher is looking at and the next ones in the list are moved to the front («prioritize»), so the
  next suggestion is usually ready when the teacher moves on.
* **Cache.** Suggestions are stored per finding (``alt_text_suggestions``) with a hash of everything that goes into
  the prompt (image address, surrounding text, page, existing alt text, prompt version). An unchanged image is never
  sent twice; a changed image or context gets a new suggestion. Identical inputs elsewhere are copied, not re-sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select

from emneklar.core import flags
from emneklar.core.ai.base import AIError, AIMessage, AIRequest, ImagePart, TextPart
from emneklar.core.ai.service import AI_LABEL
from emneklar.core.ai.untrusted import DATA_RULE, wrap_untrusted_content
from emneklar.core.canvas.api import CanvasAPI
from emneklar.core.canvas.client import CanvasError
from emneklar.core.canvas.html import filename_from_url, parse_html
from emneklar.core.errors import AppError
from emneklar.core.jobs.manager import ACTIVE, JobContext
from emneklar.core.security.guarded_http import build_guarded_client
from emneklar.core.security.ssrf import UrlBlocked, validate_url
from emneklar.core.storage.models import AltTextSuggestion, Finding
from emneklar.features.findings.store import FindingStore

if TYPE_CHECKING:
    from emneklar.core.container import AppContainer

log = logging.getLogger(__name__)

PROMPT_VERSION = "2"
CONCURRENCY = 3
CONTEXT_CHARS = 600
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
JOB_KIND = "alt_text_suggestions"
#: Errors where nothing was sent (consent missing, AI not set up, feature off) – not stored as a failed suggestion.
NOT_SENT = {"ai_consent_required", "ai_not_configured", "ai_no_model", "feature_disabled"}
OBJECT_LABELS = {"page": "siden", "assignment": "oppgaven", "discussion": "diskusjonen", "quiz": "quizen",
                 "syllabus": "emneplanen"}

SYSTEM = (
    "Du skriver forslag til alternativ tekst (alt-tekst) for bilder i et emne i Canvas, etter WCAG 2.2 "
    "suksesskriterium 1.1.1 (ikke-tekstlig innhold). Skriv på norsk bokmål.\n"
    "Slik vurderer du bildet:\n"
    "1. Se på bildet og på teksten rundt det. Finn ut hva bildet bidrar med for den som skal lære: hva viser det, og "
    "hva skal studenten forstå av det her?\n"
    "2. Informativt bilde: beskriv innholdet og poenget i denne sammenhengen – ikke bare utseendet. Hold det kort og "
    "presist (normalt under 150 tegn). Skriv lengre (opptil ca. 300 tegn) bare når bildet har viktig informasjon som "
    "ikke står i teksten, for eksempel tall, tekst i bildet eller et forløp.\n"
    "3. Komplekst bilde (diagram, graf, kart, modell): skriv en kort alt-tekst som sier hva det er og hovedbudskapet, "
    "og si i notes at det trengs en lengre beskrivelse i teksten eller rett ved bildet.\n"
    "4. Bilde med tekst: gjengi teksten som er viktig.\n"
    "5. Lenket bilde (funksjonelt): beskriv hvor lenken går eller hva den gjør, ikke bildet.\n"
    "6. Dekorativt bilde (pynt, gjentar bare det som står i teksten, eller formidler ikke noe): sett decorative til "
    "true og alt_text til en tom streng.\n"
    "Ikke begynn med «Bilde av» eller «Illustrasjon av». Ikke gjenta bildeteksten eller setninger som står rett ved "
    "bildet. Ikke gjett på navn på personer. Vær ærlig om usikkerhet i confidence og notes.\n"
    + DATA_RULE
)
SCHEMA = {
    "type": "object",
    "properties": {
        "alt_text": {"type": "string"},
        "decorative": {"type": "boolean"},
        "image_kind": {"type": "string", "enum": ["informative", "decorative", "functional", "complex", "text"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string"},
    },
    "required": ["alt_text", "decorative", "image_kind", "confidence", "notes"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------------------------------- inputs


def is_image_finding(finding: Finding) -> bool:
    return (finding.rule_id.startswith("UU-IMG-") and (finding.fix or {}).get("type") == "set_alt"
            and bool((finding.evidence or {}).get("src")))


def context_of(finding: Finding) -> dict[str, Any]:
    evidence = finding.evidence or {}
    context = dict(evidence.get("image_context") or {})
    if not context and (finding.location or {}).get("context"):
        context = {"same_block": str(finding.location["context"])}
    return {k: (str(v)[:CONTEXT_CHARS] if isinstance(v, str) else v) for k, v in context.items() if v}


def input_hash(finding: Finding) -> str:
    evidence = finding.evidence or {}
    payload = {"v": PROMPT_VERSION, "src": evidence.get("src"), "alt": evidence.get("alt"), "context": context_of(finding),
               "title": finding.object_title, "module": (finding.location or {}).get("module")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_prompt(finding: Finding) -> str:
    evidence = finding.evidence or {}
    context = context_of(finding)
    where = OBJECT_LABELS.get(str(finding.object_type), "innholdet")
    lines = [f"Bildet står på {where} «{finding.object_title}»"
             + (f" i modulen «{finding.location['module']}»" if (finding.location or {}).get("module") else "") + "."]
    if context.get("heading"):
        lines.append(f"Nærmeste overskrift over bildet: «{context['heading']}»")
    for key, label in (("before", "Tekst før bildet"), ("same_block", "Tekst i samme avsnitt som bildet"),
                       ("after", "Tekst etter bildet"), ("caption", "Bildetekst (figcaption) som allerede vises")):
        if context.get(key):
            lines.append(wrap_untrusted_content(label, str(context[key]), scrub=True))
    if not any(context.get(k) for k in ("before", "same_block", "after")):
        lines.append("Det står ingen tekst rett ved bildet.")
    if evidence.get("alt"):
        lines.append(f"Nåværende alt-tekst (kan være feil eller mangelfull): «{evidence['alt']}»")
    if context.get("link_href"):
        lines.append(f"Bildet er en lenke til: {context['link_href']}")
    filename = filename_from_url(str(evidence.get("src") or ""))
    if filename:
        lines.append(f"Filnavn (kan være misvisende): {filename}")
    lines.append("Foreslå alternativ tekst.")
    return "\n".join(lines)


async def fetch_image(c: AppContainer, src: str, *, allowed: set[str] = IMAGE_TYPES,
                      max_bytes: int = MAX_IMAGE_BYTES) -> tuple[bytes, str]:
    """The image behind a finding: Canvas files through the authenticated API (the token never leaves the backend),
    other hosts through the SSRF guard."""
    base = c.settings.get().canvas.base_url or ""
    absolute = urljoin(base + "/", src) if not urlsplit(src).scheme else src
    client = c.canvas()
    if client.is_canvas_origin(absolute):
        try:
            data, content_type = await CanvasAPI(client).file_bytes(absolute, max_bytes=max_bytes)
        except (CanvasError, AppError) as exc:
            raise AppError("file_unsupported", message="Kunne ikke hente bildet fra Canvas.") from exc
    else:
        try:
            validate_url(absolute)
        except UrlBlocked as exc:
            raise AppError("url_blocked", message=exc.message) from exc
        http = httpx.AsyncClient(transport=c.link_transport) if c.link_transport is not None \
            else build_guarded_client(15.0)
        try:
            response = await http.get(absolute)
            if response.status_code != 200 or len(response.content) > max_bytes:
                raise AppError("file_unsupported", message="Kunne ikke hente bildet.")
            data, content_type = response.content, response.headers.get("content-type")
        except httpx.HTTPError as exc:
            raise AppError("file_unsupported", message="Kunne ikke hente bildet.") from exc
        finally:
            await http.aclose()
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed:
        raise AppError("file_unsupported", message="Bildeformatet kan ikke vises eller analyseres (bruk PNG, JPEG, WebP "
                       "eller GIF).")
    return data, content_type


# ------------------------------------------------------------------------------------------- storage


def suggestion_dict(row: AltTextSuggestion, current_hash: str | None = None) -> dict[str, Any]:
    stale = current_hash is not None and row.input_hash != current_hash
    return {"status": "stale" if stale and row.status == "ready" else row.status, "suggestion": row.suggestion,
            "decorative": row.decorative, "image_kind": row.image_kind or None, "confidence": row.confidence or None,
            "notes": row.notes or None, "provider": row.provider or None, "model": row.model or None,
            "error": row.error, "label": AI_LABEL,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def suggestions_for(c: AppContainer, course_id: str, fingerprints: list[str]) -> dict[str, dict[str, Any]]:
    if not fingerprints:
        return {}
    with c.db.session() as session:
        rows = session.scalars(select(AltTextSuggestion).where(
            AltTextSuggestion.course_id == course_id, AltTextSuggestion.fingerprint.in_(fingerprints))).all()
        return {r.fingerprint: suggestion_dict(r) for r in rows}


def _row(session: Any, finding: Finding) -> AltTextSuggestion:
    row = session.scalars(select(AltTextSuggestion).where(AltTextSuggestion.course_id == finding.course_id,
                                                          AltTextSuggestion.fingerprint == finding.fingerprint)).first()
    if row is None:
        row = AltTextSuggestion(course_id=finding.course_id, fingerprint=finding.fingerprint, finding_id=finding.id,
                                input_hash="", status="queued", suggestion="", decorative=False, image_kind="",
                                confidence="", notes="", provider="", model="")
        session.add(row)
    return row


# ------------------------------------------------------------------------------------------- generation


async def generate(c: AppContainer, finding: Finding, *, confirmed: bool) -> dict[str, Any]:
    """Make (or reuse) the suggestion for one image finding and store it."""
    digest = input_hash(finding)
    with c.db.session() as session:
        row = _row(session, finding)
        if row.status == "ready" and row.input_hash == digest:
            return suggestion_dict(row)
        twin = session.scalars(select(AltTextSuggestion).where(
            AltTextSuggestion.input_hash == digest, AltTextSuggestion.status == "ready")).first()
        if twin is not None and twin is not row:
            for key in ("suggestion", "decorative", "image_kind", "confidence", "notes", "provider", "model"):
                setattr(row, key, getattr(twin, key))
            row.input_hash, row.status, row.error, row.finding_id = digest, "ready", None, finding.id
            return suggestion_dict(row)
        previous = row.status if row.status != "running" else "queued"
        row.status, row.error, row.finding_id = "running", None, finding.id
    try:
        data, content_type = await fetch_image(c, str((finding.evidence or {}).get("src") or ""))
        prompt = build_prompt(finding)

        def build(model: str) -> AIRequest:
            return AIRequest(model=model, system=SYSTEM, schema_name="alt_tekst", json_schema=SCHEMA,
                             max_output_tokens=700,
                             messages=[AIMessage(parts=[ImagePart.from_bytes(data, content_type), TextPart(text=prompt)])])

        result, _decision = await c.ai.run("alt_text", build, input_chars=len(prompt), images=1,
                                           summary=f"1 bilde fra «{finding.object_title}»", confirmed=confirmed,
                                           course_id=finding.course_id)
        answer = result.data or {}
        suggestion = str(answer.get("alt_text") or "").strip()[:500]
        decorative = bool(answer.get("decorative"))
        if not suggestion and not decorative:
            raise AIError("ai_bad_response", status=502, detail="Tomt forslag")
    except AppError as exc:
        with c.db.session() as session:
            row = _row(session, finding)
            if exc.code in NOT_SENT:
                row.status = previous  # nothing was sent: not a failed suggestion, the teacher must decide first
                raise
            row.status, row.error, row.input_hash = "failed", exc.message, digest
            return suggestion_dict(row)
    with c.db.session() as session:
        row = _row(session, finding)
        row.status, row.error, row.input_hash = "ready", None, digest
        row.suggestion = "" if decorative else suggestion
        row.decorative = decorative
        row.image_kind = str(answer.get("image_kind") or "")[:16]
        row.confidence = str(answer.get("confidence") or "")[:8]
        row.notes = str(answer.get("notes") or "")[:2000]
        row.provider, row.model = result.provider, result.model
        return suggestion_dict(row)


# ------------------------------------------------------------------------------------------- queue


@dataclass
class _Pending:
    priority: int
    seq: int
    finding_id: int
    fingerprint: str


class AltQueue:
    """One per running application. All state lives in the event loop (no threads), so plain dicts are safe."""

    def __init__(self, c: AppContainer) -> None:
        self.c = c
        self.pending: dict[str, dict[str, _Pending]] = {}  # course → fingerprint → item
        self.inflight: dict[str, set[str]] = {}
        self.consent: set[str] = set()
        self.jobs: dict[str, str] = {}  # course → job id
        self._seq = 0

    def plan(self, course_id: str, count: int) -> dict[str, Any]:
        settings = self.c.settings.get()
        if not flags.is_enabled(settings, "ai_alt_text"):
            return {"available": False, "reason": "KI-forslag til alt-tekst er slått av under Avanserte innstillinger.",
                    "payload_summary": None, "needs_confirmation": False, "route": None, "external": False}
        summary = (f"{count} bilde{'r' if count != 1 else ''} og opptil {CONTEXT_CHARS * 3} tegn tekst rundt hvert "
                   "bilde (overskrift, tekst før og etter, bildetekst og sidetittel) sendes til KI-leverandøren. "
                   "Ingen studentdata sendes.")
        return self.c.ai.plan("alt_text", input_chars=1800, images=1, summary=summary)

    def allowed(self, course_id: str) -> bool:
        plan = self.plan(course_id, 1)
        return bool(plan["available"]) and (not plan["needs_confirmation"] or course_id in self.consent)

    def enqueue(self, course_id: str, findings: list[Finding], *, front: bool = False,
                retry_failed: bool = False) -> int:
        """Add image findings (in the given order). ``front`` moves them ahead of everything already waiting. Ready
        suggestions for unchanged input are never redone; failed ones only on an explicit retry."""
        queue = self.pending.setdefault(course_id, {})
        inflight = self.inflight.setdefault(course_id, set())
        with self.c.db.session() as session:
            rows = {r.fingerprint: r for r in session.scalars(select(AltTextSuggestion).where(
                AltTextSuggestion.course_id == course_id,
                AltTextSuggestion.fingerprint.in_([f.fingerprint for f in findings]))).all()}
            done = {fp: (r.status, r.input_hash) for fp, r in rows.items() if r.status in ("ready", "failed")}
        base = min((p.priority for p in queue.values()), default=0) - len(findings) - 1 if front else 0
        added = 0
        for index, finding in enumerate(findings):
            fp = finding.fingerprint
            if not is_image_finding(finding) or fp in inflight:
                continue
            status, digest = done.get(fp, (None, None))
            if digest == input_hash(finding) and (status == "ready" or (status == "failed" and not retry_failed)):
                continue
            self._seq += 1
            priority = base + index if front else (queue[fp].priority if fp in queue else 1_000_000 + self._seq)
            if fp in queue:
                queue[fp].priority = min(queue[fp].priority, priority)
                continue
            queue[fp] = _Pending(priority, self._seq, finding.id, fp)
            added += 1
        with self.c.db.session() as session:
            for finding in findings:
                if finding.fingerprint in queue:
                    row = _row(session, finding)
                    if row.status not in ("running",):
                        row.status = "queued"
                        row.error = None
        if added:
            self._ensure_job(course_id, added)
        return added

    def _next(self, course_id: str) -> _Pending | None:
        queue = self.pending.get(course_id) or {}
        if not queue:
            return None
        fp, item = min(queue.items(), key=lambda kv: (kv[1].priority, kv[1].seq))
        del queue[fp]
        self.inflight.setdefault(course_id, set()).add(fp)
        return item

    def _ensure_job(self, course_id: str, added: int) -> None:
        job_id = self.jobs.get(course_id)
        if job_id is not None:
            try:
                state = self.c.jobs.get(job_id)
                if state.status in ACTIVE:
                    state.tracker.add_tasks("image", added)
                    return
            except AppError:
                pass
        total = len(self.pending.get(course_id) or {})

        async def runner(ctx: JobContext) -> dict[str, Any]:
            progress = ctx.progress
            progress.set_phase("alt", "Forbereder alt-tekstforslag", index=1, count=1, determinate=True)
            progress.add_tasks("image", total)
            counts = {"ready": 0, "failed": 0}

            async def worker() -> None:
                while True:
                    await ctx.checkpoint()
                    item = self._next(course_id)
                    if item is None:
                        return
                    t0 = progress.start("image", item="Bilde", operation="Lager forslag")
                    status = "failed"
                    try:
                        finding = FindingStore(self.c.db).get(item.finding_id)
                        status = (await generate(self.c, finding, confirmed=True))["status"]
                    except Exception:
                        log.exception("Alt-tekstforslag feilet for funn %s", item.finding_id)
                    finally:
                        self.inflight.get(course_id, set()).discard(item.fingerprint)
                    counts["ready" if status == "ready" else "failed"] += 1
                    progress.finish("image", t0, failed=status != "ready")

            while True:
                await asyncio.gather(*(worker() for _ in range(CONCURRENCY)))
                if not self.pending.get(course_id):
                    self.jobs.pop(course_id, None)  # no await between the check and the pop
                    return counts

        state = self.c.jobs.submit(kind=JOB_KIND, title="Forbereder alt-tekstforslag", runner=runner,
                                   course_id=course_id, params={"images": total}, supports_pause=True,
                                   hard_cancel=True, exclusive=False)
        self.jobs[course_id] = state.id

    def cancel(self, course_id: str) -> None:
        self.pending.pop(course_id, None)
        job_id = self.jobs.get(course_id)
        if job_id:
            with contextlib.suppress(AppError):
                self.c.jobs.cancel(job_id)

    def state(self, course_id: str) -> dict[str, Any]:
        job_id = self.jobs.get(course_id)
        return {"queued": len(self.pending.get(course_id) or {}), "running": len(self.inflight.get(course_id) or ()),
                "job_id": job_id, "consented": course_id in self.consent}


_queues: weakref.WeakKeyDictionary[AppContainer, AltQueue] = weakref.WeakKeyDictionary()


def queue_for(c: AppContainer) -> AltQueue:
    queue = _queues.get(c)
    if queue is None:
        queue = _queues[c] = AltQueue(c)
    return queue


def parse_context_from_html(html: str, finding: Finding) -> dict[str, Any] | None:
    """Context for findings from older analyses (without ``image_context``), computed from the live HTML."""
    from emneklar.features.accessibility.checks.images import image_context
    from emneklar.features.accessibility.fixes import locate

    try:
        el = locate(parse_html(html), finding.location or {})
    except AppError:
        return None
    return image_context(el)
