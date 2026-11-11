"""Render reports as a self-contained, print-friendly HTML document and as CSV (semicolon, UTF-8 with BOM).

All values are escaped; the HTML has no scripts and no external resources. «Lagre som PDF»
is done from the browser's print dialog, which uses the print styles below.
"""

from __future__ import annotations

import csv
import io
from html import escape
from typing import Any

from emneklar import __version__
from emneklar.features.reporting.data import CLASS_ORDER, SUMMARY_LABELS, DomainReport, ReportData

MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
          "desember"]

CSS = """
body { font-family: "Segoe UI", Arial, sans-serif; color: #1b2430; margin: 0; background: #ffffff; line-height: 1.5; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 24px 48px; }
h1 { font-size: 28px; margin: 0 0 4px; color: #14213d; }
h2 { font-size: 22px; margin: 36px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #14213d; color: #14213d; }
h3 { font-size: 18px; margin: 24px 0 8px; color: #14213d; }
p.lead { margin: 0 0 16px; color: #3a4656; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; font-size: 14px; }
caption { text-align: left; font-weight: 600; padding: 4px 0; }
th, td { border: 1px solid #c8d0db; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #eef2f7; }
.meta th { width: 220px; }
.note { background: #fff7e0; border-left: 4px solid #8a6d00; padding: 10px 14px; margin: 16px 0; }
.muted { color: #4a5565; font-size: 13px; }
ul { margin: 4px 0 12px; }
a { color: #1d4f91; }
@media print {
  main { padding: 0; max-width: none; }
  h2 { break-after: avoid; }
  tr, li { break-inside: avoid; }
  a { color: inherit; }
}
"""


def date_label(value: Any) -> str:
    local = value.astimezone()
    return f"{local.day}. {MONTHS[local.month - 1]} {local.year} kl. {local:%H:%M}"


def _object(f: dict[str, Any]) -> str:
    title = escape(f["object_title"] or "")
    url = str(f.get("object_url") or "")
    where = f'<a href="{escape(url)}">{title}</a>' if url.startswith(("https://", "http://")) else title
    if f.get("module"):
        where += f'<br><span class="muted">{escape(f["module"])}</span>'
    return where


def _criteria(f: dict[str, Any]) -> str:
    if f["criteria"]:
        text = ", ".join(escape(c) for c in f["criteria"])
        return text + (f'<br><span class="muted">{escape(f["legal_label"])}</span>' if f["legal_label"] else "")
    return escape(f["category_label"])


def _table(caption: str, findings: list[dict[str, Any]], accessibility: bool) -> str:
    if not findings:
        return ""
    head = "Kriterium / lovstatus" if accessibility else "Kategori"
    rows = "".join(
        f"<tr><td>{escape(f['classification_label'])}<br><span class=\"muted\">{escape(f['severity_label'])}</span></td>"
        f"<td><strong>{escape(f['title'])}</strong><br>{escape(f['message'])}</td><td>{_object(f)}</td>"
        f"<td>{_criteria(f)}</td><td>{escape(f['method_label'])}</td><td>{escape(f['remediation'])}</td></tr>"
        for f in findings)
    return (f"<table><caption>{escape(caption)}</caption><thead><tr><th scope=\"col\">Klasse</th>"
            f"<th scope=\"col\">Funn</th><th scope=\"col\">Hvor</th><th scope=\"col\">{head}</th>"
            f"<th scope=\"col\">Testmetode</th><th scope=\"col\">Forslag til retting</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _summary(domains: list[DomainReport]) -> str:
    header = "".join(f'<th scope="col">{escape(SUMMARY_LABELS[c])}</th>' for c in CLASS_ORDER)
    rows = []
    for d in domains:
        if not d.analysed:
            rows.append(f'<tr><th scope="row">{escape(d.label)}</th><td colspan="{len(CLASS_ORDER) + 3}">'
                        "Ikke analysert ennå</td></tr>")
            continue
        counts = d.counts
        cells = "".join(f"<td>{counts[c]}</td>" for c in CLASS_ORDER)
        rows.append(f'<tr><th scope="row">{escape(d.label)}</th>{cells}<td>{counts["fixed"]}</td>'
                    f"<td>{counts['ignored']}</td><td>{counts['verified']}</td></tr>")
    return (f'<table><caption>Åpne funn per område og klasse</caption><thead><tr><th scope="col">Område</th>{header}'
            f'<th scope="col">Rettet</th><th scope="col">Ignorert</th><th scope="col">Kontrollert</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            "</table>")


def _domain(d: DomainReport) -> str:
    out = f"<h2>{escape(d.label)}</h2>"
    if not d.analysed:
        return out + "<p>Området er ikke analysert ennå. Kjør en analyse i EmneKlar for å få resultater.</p>"
    runs = "".join(f"<li>{escape(r['scope'])}, {escape(date_label(r['started_at']))}"
                   + (f" (regelsett {escape(str(r['ruleset_version']))})" if r["ruleset_version"] else "") + "</li>"
                   for r in d.runs)
    out += f"<p>Resultatene bygger på disse analysene:</p><ul>{runs}</ul>"
    accessibility = d.domain == "accessibility"
    out += _table("Gjenstående funn", d.remaining, accessibility) or "<p>Ingen gjenstående funn.</p>"
    if d.manual:
        out += "<h3>Manuell kontroll</h3><p>Dette kan ikke avgjøres automatisk og må kontrolleres av et menneske.</p>"
        out += _table("Krever manuell kontroll", d.manual, accessibility)
    if d.fixed:
        items = "".join(f"<li>{escape(f['title'])} – {escape(f['object_title'] or '')}</li>" for f in d.fixed)
        out += f"<h3>Rettet ({len(d.fixed)})</h3><ul>{items}</ul>"
    if d.ignored:
        out += (f"<h3>Ignorert ({len(d.ignored)})</h3><p>Funn som er vurdert og markert som ignorert i EmneKlar.</p>"
                + "<ul>" + "".join(f"<li>{escape(f['title'])} – {escape(f['object_title'] or '')}</li>"
                                   for f in d.ignored) + "</ul>")
    if d.verified:
        out += (f"<h3>Kontrollert manuelt ({len(d.verified)})</h3><p>Manuelle kontroller der læreren har bekreftet "
                "forholdet i EmneKlar (for eksempel at et lydopptak har transkripsjon). EmneKlar har ikke selv "
                "kontrollert innholdet i bekreftelsen.</p><ul>"
                + "".join(f"<li>{escape(f['title'])} – {escape(f['object_title'] or '')}"
                          + (f": {escape(f['decision_label'])}" if f["decision_label"] else "")
                          + (f" ({escape(f['decision_note'])})" if f["decision_note"] else "") + "</li>"
                          for f in d.verified) + "</ul>")
    if d.limitations:
        out += "<h3>Begrensninger</h3><ul>" + "".join(f"<li>{escape(x)}</li>" for x in d.limitations) + "</ul>"
    return out


def render_html(data: ReportData) -> str:
    course = escape(data.course_name) + (f" ({escape(data.course_code)})" if data.course_code else "")
    meta = [("Emne", course), ("Rapport laget", escape(date_label(data.created_at))),
            ("Regelsett", escape(", ".join(sorted({v for d in data.domains for v in d.rulesets})) or "–"))]
    if data.profile:
        meta.append(("Regulatorisk profil", f"{escape(data.profile['title'])} (versjon "
                                            f"{escape(data.profile['version'])}, {escape(data.profile['standard'])})"))
    meta.append(("Laget med", f"EmneKlar {escape(__version__)}"))
    meta_rows = "".join(f'<tr><th scope="row">{k}</th><td>{v}</td></tr>' for k, v in meta)
    body = (f"<h1>{escape(data.title)}</h1><p class=\"lead\">{course}</p>"
            f'<table class="meta"><caption>Om rapporten</caption><tbody>{meta_rows}</tbody></table>'
            f'<div class="note"><p style="margin:0">{escape(data.disclaimer)}</p></div>'
            f"<h2>Sammendrag</h2>{_summary(data.domains)}" + "".join(_domain(d) for d in data.domains))
    return (f'<!doctype html><html lang="nb"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(data.title)} – {escape(data.course_name)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main></body></html>")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Prevent spreadsheet formula injection from course content.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def render_csv(data: ReportData) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Område", "Status", "Klasse", "Alvorlighet", "Testmetode", "Regel", "Tittel", "Beskrivelse",
                     "Objekttype", "Objekt", "Modul", "URL", "Kriterier", "Lovstatus", "Forslag til retting",
                     "Bekreftet av lærer"])
    for d in data.domains:
        for f in d.remaining + d.manual + d.fixed + d.ignored + d.verified:
            confirmed = " – ".join(x for x in (f["decision_label"], f["decision_note"]) if x) \
                if f["status"] == "verified" else ""
            writer.writerow([_cell(x) for x in (
                d.label, f["status_label"], f["classification_label"], f["severity_label"], f["method_label"],
                f["rule_id"], f["title"], f["message"], f["object_type"], f["object_title"], f["module"],
                f["object_url"], ", ".join(f["criteria"]), f["legal_label"], f["remediation"], confirmed)])
    return "﻿".encode() + buffer.getvalue().encode("utf-8")
