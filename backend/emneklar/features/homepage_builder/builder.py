"""Generate Canvas-safe homepage HTML from course facts (pure functions, no Canvas calls).

Principles: never invent course facts – facts come from Canvas, everything else is a
clearly marked placeholder («Fyll inn») or a marked AI suggestion («KI-forslag – må
vurderes»). Layout uses flex-wrap blocks so it works on desktop, tablet and mobile
without media queries or JavaScript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from typing import Any, Literal

from bs4 import BeautifulSoup

from emneklar.core.security.sanitize import ALLOWED_CSS, ALLOWED_TAGS, canvas_sanitize
from emneklar.features.homepage_builder.styles import AI_MARK, PLACEHOLDER, STYLES, Style

Mode = Literal["design", "design_content", "improve"]
MODES = {"design": "Kun design", "design_content": "Design + innhold", "improve": "Forbedre eksisterende forside"}
SECTIONS: dict[str, tuple[str, str]] = {
    "velkommen": ("Velkommen", "Banner med emnenavn og en kort velkomst."),
    "om_emnet": ("Om emnet", "Hva emnet handler om."),
    "praktisk": ("Praktisk informasjon", "Undervisning, pensum og vurdering."),
    "fremdrift": ("Fremdriftsplan", "Modulene i rekkefølge, med åpningsdatoer fra Canvas."),
    "frister": ("Viktige frister", "Kommende frister hentet fra Canvas."),
    "hurtiglenker": ("Hurtiglenker", "Snarveier til sentrale deler av emnet."),
    "moduler": ("Moduloversikt", "Et kort for hver modul."),
    "ressurser": ("Ressurser", "Filer og ressurssider i emnet."),
    "studieaktivitet": ("Studieaktivitet", "Aktiviteter i emnet og forventet arbeidsinnsats."),
    "kontakt": ("Kontakt", "Hvordan studentene kan kontakte faglærer."),
    "veiledning": ("Personlig veiledning", "Hvordan studentene kan få veiledning."),
}
DEFAULT_SECTIONS = {
    "design": ["velkommen", "om_emnet", "hurtiglenker", "moduler", "kontakt"],
    "design_content": ["velkommen", "om_emnet", "hurtiglenker", "moduler", "frister", "kontakt"],
    "improve": ["velkommen", "hurtiglenker", "frister"],
}
QUICK_LINKS = [("modules", "Moduler", "modules"), ("announcements", "Kunngjøringer", "announcements"),
               ("assignments", "Oppgaver", "assignments"), ("syllabus", "Emneplan", "assignments/syllabus"),
               ("discussions", "Diskusjoner", "discussion_topics"), ("grades", "Karakterer", "grades"),
               ("files", "Filer", "files")]
RESOURCE_WORDS = re.compile(r"(?i)\b(ressurs\w*|pensum\w*|litteratur\w*|lenker|kilder|leseliste\w*)\b")
PRACTICAL_WORDS = re.compile(r"(?i)\b(praktisk\w*|timeplan\w*|undervisningsplan\w*|vurdering\w*|eksamen\w*)\b")
MONTHS = ["jan.", "feb.", "mars", "apr.", "mai", "juni", "juli", "aug.", "sep.", "okt.", "nov.", "des."]


@dataclass
class CourseContext:
    course_id: str
    name: str
    code: str | None = None
    term: str | None = None
    description: str = ""
    syllabus_text: str = ""
    modules: list[dict[str, Any]] = field(default_factory=list)  # {id, name, items_count, unlock_at}
    deadlines: list[dict[str, Any]] = field(default_factory=list)  # {title, due_at: datetime, url, kind}
    visible_tabs: set[str] | None = None  # None = unknown
    pages: list[dict[str, Any]] = field(default_factory=list)  # {title, url}
    discussions: list[dict[str, Any]] = field(default_factory=list)  # {title, url}
    counts: dict[str, int] = field(default_factory=dict)  # assignments, quizzes, discussions, files
    front_page_html: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


@dataclass
class Draft:
    html: str
    notes: list[dict[str, str]]
    warnings: list[str]


def format_date(value: datetime) -> str:
    local = value.astimezone()
    return f"{local.day}. {MONTHS[local.month - 1]} {local.year} kl. {local:%H:%M}"


class _Writer:
    def __init__(self, style: Style, ctx: CourseContext, mode: Mode) -> None:
        self.s, self.ctx, self.mode = style, ctx, mode
        self.notes: list[dict[str, str]] = []

    # -- primitives ------------------------------------------------------------------------------

    def link(self, path: str, text: str) -> str:
        href = path if path.startswith("/") else f"/courses/{self.ctx.course_id}/{path}"
        return f'<a href="{escape(href)}" style="color: {self.s.link};">{escape(text)}</a>'

    def heading(self, title: str) -> str:
        font = f" font-family: {self.s.heading_font};" if self.s.heading_font else ""
        return (f'<h2 style="color: {self.s.heading}; font-size: 22px; margin: 28px 0 12px 0; padding-bottom: 6px; '
                f'border-bottom: 2px solid {self.s.accent};{font}">{escape(title)}</h2>')

    def placeholder(self, section: str, text: str) -> str:
        self.notes.append({"section": section, "kind": "placeholder", "message": text})
        return (f'<p style="background-color: {PLACEHOLDER["bg"]}; border-left: 4px solid {PLACEHOLDER["border"]}; '
                f'color: {PLACEHOLDER["text"]}; padding: 8px 12px; margin: 8px 0;"><strong>Fyll inn:</strong> '
                f'{escape(text)}</p>')

    def ai_text(self, section: str, text: str) -> str:
        self.notes.append({"section": section, "kind": "ai", "message": "KI-forslag – må vurderes før publisering."})
        paragraphs = "".join(f'<p style="margin: 0 0 6px 0;">{escape(p.strip())}</p>'
                             for p in text.split("\n") if p.strip())
        return (f'<div style="background-color: {AI_MARK["bg"]}; border-left: 4px solid {AI_MARK["border"]}; '
                f'color: {AI_MARK["text"]}; padding: 8px 12px; margin: 8px 0;">'
                f'<p style="margin: 0 0 4px 0; font-size: 14px;"><strong>KI-forslag – må vurderes</strong></p>'
                f"{paragraphs}</div>")

    def card(self, inner: str) -> str:
        return (f'<div style="flex: 1 1 240px; background-color: {self.s.card_bg}; border: 1px solid '
                f'{self.s.card_border}; border-top: 4px solid {self.s.accent}; border-radius: {self.s.radius}; '
                f'padding: 16px;">{inner}</div>')

    @staticmethod
    def cards(cards: list[str]) -> str:
        return f'<div style="display: flex; flex-wrap: wrap; gap: 16px; margin: 0 0 8px 0;">{"".join(cards)}</div>'

    def small(self, text: str) -> str:
        return f'<p style="font-size: 14px; margin: 8px 0 0 0;">{escape(text)}</p>'

    @property
    def facts(self) -> bool:
        return self.mode != "design"

    # -- sections --------------------------------------------------------------------------------

    def velkommen(self, ai: dict[str, str]) -> str:
        s, ctx = self.s, self.ctx
        meta = " · ".join(escape(x) for x in (ctx.code, ctx.term) if x)
        font = f" font-family: {s.heading_font};" if s.heading_font else ""
        border = f" border-bottom: 3px solid {s.accent};" if s.banner_bg == "#ffffff" else ""
        banner = (f'<div style="background-color: {s.banner_bg}; color: {s.banner_text}; padding: 28px 24px; '
                  f'border-radius: {s.radius}; margin: 0 0 16px 0;{border}">'
                  + (f'<p style="margin: 0; font-size: 14px; color: {s.banner_text};">{meta}</p>' if meta else "")
                  + f'<h2 style="margin: 4px 0 0 0; font-size: 30px; color: {s.banner_text};{font}">'
                  f"Velkommen til {escape(ctx.name)}</h2></div>")
        if ai.get("welcome"):
            body = self.ai_text("velkommen", ai["welcome"])
        else:
            body = self.placeholder("velkommen", "Skriv en kort velkomst: hva emnet handler om, og hvordan studentene "
                                                 "bør komme i gang.")
        return banner + body

    def om_emnet(self, ai: dict[str, str]) -> str:
        ctx = self.ctx
        out = self.heading("Om emnet")
        if ai.get("about"):
            out += self.ai_text("om_emnet", ai["about"])
        elif self.facts and ctx.description:
            out += f'<p style="margin: 0 0 8px 0;">{escape(ctx.description)}</p>'
        elif self.facts and ctx.syllabus_text:
            excerpt = ctx.syllabus_text[:400].rsplit(" ", 1)[0] + ("…" if len(ctx.syllabus_text) > 400 else "")
            out += (f'<p style="margin: 0 0 4px 0;">Fra emneplanen:</p><blockquote style="margin: 0 0 8px 0; '
                    f'padding: 4px 12px; border-left: 4px solid {self.s.card_border};">{escape(excerpt)}</blockquote>')
        else:
            out += self.placeholder("om_emnet", "Beskriv emnet med to–tre setninger: tema, læringsutbytte og hvem "
                                                "emnet passer for.")
        if self.facts and ctx.syllabus_text:
            out += f'<p style="margin: 8px 0 0 0;">{self.link("assignments/syllabus", "Les hele emneplanen")}</p>'
        return out

    def praktisk(self) -> str:
        out = self.heading("Praktisk informasjon")
        pages = [p for p in self.ctx.pages if PRACTICAL_WORDS.search(p["title"])] if self.facts else []
        if pages:
            self.notes.append({"section": "praktisk", "kind": "heuristic",
                               "message": "Sidene er funnet ut fra titlene. Kontroller at de passer."})
            out += '<ul style="margin: 0; padding-left: 20px;">' + "".join(
                f"<li>{self.link('pages/' + p['url'], p['title'])}</li>" for p in pages[:6]) + "</ul>"
        out += self.placeholder("praktisk", "Undervisningstid og -sted, pensum og vurderingsform.")
        return out

    def fremdrift(self) -> str:
        out = self.heading("Fremdriftsplan")
        modules = self.ctx.modules if self.facts else []
        if not modules:
            return out + self.placeholder("fremdrift", "Oversikt over uker eller temaer i emnet.")
        rows = []
        for module in modules:
            unlock = module.get("unlock_at")
            when = f" – åpner {escape(format_date(unlock))}" if isinstance(unlock, datetime) else ""
            rows.append(f"<li>{self.link('modules/' + str(module['id']), module['name'])}{when}</li>")
        return out + '<ol style="margin: 0; padding-left: 24px;">' + "".join(rows) + "</ol>"

    def frister(self) -> str:
        out = self.heading("Viktige frister")
        if not self.facts:
            return out + self.placeholder("frister", "De viktigste fristene i emnet.")
        upcoming = [d for d in self.ctx.deadlines if d["due_at"] >= self.ctx.generated_at][:8]
        if not upcoming:
            return out + self.small("Canvas har ingen kommende frister for emnet nå.") + self.placeholder(
                "frister", "Legg inn viktige datoer, eller fjern seksjonen.")
        items = "".join(f"<li><strong>{escape(format_date(d['due_at']))}</strong> – {self.link(d['url'], d['title'])}"
                        f" ({escape(d['kind'])})</li>" for d in upcoming)
        self.notes.append({"section": "frister", "kind": "stale", "message": "Fristene på siden oppdateres ikke "
                           "automatisk hvis de endres i Canvas."})
        return (out + f'<ul style="margin: 0; padding-left: 20px;">{items}</ul>'
                + self.small(f"Hentet fra Canvas {format_date(self.ctx.generated_at)}. Kalenderen og «Kommende» i "
                             "Canvas viser alltid gjeldende frister."))

    def hurtiglenker(self) -> str:
        tabs = self.ctx.visible_tabs
        links = [(label, path) for tab, label, path in QUICK_LINKS
                 if (tab in tabs if tabs is not None else tab in ("modules", "announcements", "assignments", "grades"))]
        buttons = "".join(
            f'<a href="/courses/{escape(self.ctx.course_id)}/{path}" style="display: inline-block; padding: 10px 16px; '
            f'border: 2px solid {self.s.link}; border-radius: 999px; color: {self.s.link}; text-decoration: none;">'
            f"{escape(label)}</a>" for label, path in links)
        return self.heading("Hurtiglenker") + f'<div style="display: flex; flex-wrap: wrap; gap: 12px;">{buttons}</div>'

    def moduler(self) -> str:
        out = self.heading("Moduloversikt")
        if not self.facts or not self.ctx.modules:
            return out + self.placeholder("moduler", "Kort om hver modul eller hvert tema.")
        cards = []
        for module in self.ctx.modules:
            count = int(module.get("items_count") or 0)
            title = self.link("modules/" + str(module["id"]), module["name"])
            cards.append(self.card(f'<h3 style="margin: 0 0 6px 0; font-size: 18px; color: {self.s.heading};">{title}'
                                   f'</h3><p style="margin: 0; font-size: 14px;">{count} '
                                   f'{"element" if count == 1 else "elementer"}</p>'))
        return out + self.cards(cards)

    def ressurser(self) -> str:
        out = self.heading("Ressurser")
        items = []
        if self.facts:
            pages = [p for p in self.ctx.pages if RESOURCE_WORDS.search(p["title"])]
            if pages:
                self.notes.append({"section": "ressurser", "kind": "heuristic",
                                   "message": "Ressurssidene er funnet ut fra titlene. Kontroller at de passer."})
            items += [f"<li>{self.link('pages/' + p['url'], p['title'])}</li>" for p in pages[:6]]
            tabs = self.ctx.visible_tabs
            if self.ctx.counts.get("files") and (tabs is None or "files" in tabs):
                items.append(f"<li>{self.link('files', 'Filer i emnet')}</li>")
        if items:
            out += f'<ul style="margin: 0; padding-left: 20px;">{"".join(items)}</ul>'
        else:
            out += self.placeholder("ressurser", "Lenker til pensum, nyttige nettsider og verktøy.")
        return out

    def studieaktivitet(self) -> str:
        out = self.heading("Studieaktivitet")
        counts = self.ctx.counts
        if self.facts and any(counts.get(k) for k in ("assignments", "quizzes", "discussions")):
            parts = [f"{counts[k]} {label}" for k, label in (("assignments", "oppgaver"), ("quizzes", "quizer"),
                                                              ("discussions", "diskusjoner")) if counts.get(k)]
            out += f'<p style="margin: 0 0 8px 0;">Emnet har {escape(", ".join(parts))}.</p>'
        return out + self.placeholder("studieaktivitet", "Forventet arbeidsinnsats per uke, og hvordan studentene bør "
                                                         "jobbe med stoffet.")

    def kontakt(self) -> str:
        out = self.heading("Kontakt")
        out += self.placeholder("kontakt", "Navn på faglærer, e-post og hvor raskt studentene kan vente svar.")
        return out + f'<p style="margin: 8px 0 0 0;">Du kan også sende melding i {self.link("/conversations", "Innboks")}' \
                     " i Canvas.</p>"

    def veiledning(self) -> str:
        return self.heading("Personlig veiledning") + self.placeholder(
            "veiledning", "Når og hvordan studentene kan få veiledning, og hvordan de bestiller tid.")


def build(ctx: CourseContext, *, style: str, mode: Mode, sections: list[str], preserve_existing: bool = True,
          ai: dict[str, str] | None = None) -> Draft:
    if style not in STYLES:
        raise ValueError(f"Ukjent stil {style}")
    chosen = [s for s in dict.fromkeys(sections) if s in SECTIONS]
    writer = _Writer(STYLES[style], ctx, mode)
    ai = ai or {}
    parts: list[str] = []
    for key in chosen:
        if key == "velkommen":
            parts.append(writer.velkommen(ai))
            if mode == "improve" and preserve_existing and ctx.front_page_html:
                parts.append(_existing(ctx.front_page_html))
        elif key == "om_emnet":
            parts.append(writer.om_emnet(ai))
        else:
            parts.append(getattr(writer, key)())
    if mode == "improve" and preserve_existing and ctx.front_page_html and "velkommen" not in chosen:
        parts.insert(0, _existing(ctx.front_page_html))
    if mode == "improve" and not preserve_existing:
        writer.notes.append({"section": "", "kind": "replace", "message": "Eksisterende innhold på forsiden er ikke "
                             "med i utkastet. Det sikkerhetskopieres hvis du erstatter forsiden."})
    s = STYLES[style]
    html = (f'<div style="max-width: 1100px; margin: 0 auto; color: {s.text}; line-height: 1.5;">'
            + "".join(parts) + "</div>")
    clean, warnings = canvas_safe(html)
    return Draft(html=clean, notes=writer.notes, warnings=warnings)


def _existing(html: str) -> str:
    """Existing front page content, kept as-is (only Canvas-sanitised)."""
    return f'<div style="margin: 0 0 16px 0;">{canvas_sanitize(html)}</div>'


_STYLE_PROP = re.compile(r"(?:^|;)\s*([a-zA-Z-]+)\s*:")


def canvas_safe(html: str) -> tuple[str, list[str]]:
    """Sanitise like Canvas and report what Canvas would remove (so the preview matches the stored page)."""
    soup = BeautifulSoup(html or "", "html.parser")
    warnings: list[str] = []
    removed_tags = sorted({t.name for t in soup.find_all(True) if t.name not in ALLOWED_TAGS})
    if removed_tags:
        warnings.append("Canvas fjerner disse elementene: " + ", ".join(f"<{t}>" for t in removed_tags) + ".")
    props: set[str] = set()
    for tag in soup.find_all(style=True):
        props |= {p.lower() for p in _STYLE_PROP.findall(str(tag.get("style")))}
    dropped = sorted(p for p in props if p not in ALLOWED_CSS)
    if dropped:
        warnings.append("Canvas fjerner disse stilene: " + ", ".join(dropped) + ".")
    return canvas_sanitize(html), warnings
