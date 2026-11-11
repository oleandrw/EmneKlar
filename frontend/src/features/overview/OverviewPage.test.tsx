import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import {
  accessibilityRest,
  activityMeta,
  activityStatus,
  analysisLine,
  areaNames,
  contentQualityRest,
  coverageDetails,
  coverageLine,
  quizAffected,
  type DomainCard,
  type Overview,
} from "./model";
import { OverviewPage } from "./OverviewPage";

vi.mock("../../core/session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, flags: {}, general: { page_size: 25 } }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const ALL = ["accessibility", "content_quality", "structure", "quiz"];
const RUN = { id: 9, scope_type: "course", status: "complete", time: "2026-11-06T13:20:00+00:00", domains: ALL };
const OLD = { id: 4, scope_type: "course", status: "complete", time: "2026-11-05T09:00:00+00:00", domains: ALL };
const PART = { id: 12, scope_type: "modules", status: "complete", time: "2026-11-09T10:00:00+00:00", domains: ["accessibility"] };
/** «kl. 14.20» in the test machine's time zone. */
const clock = (iso: string) => new Intl.DateTimeFormat("nb-NO", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso)).replace(":", ".");

function card(over: Partial<DomainCard>): DomainCard {
  return { domain: "accessibility", analyzed: true, last_run: RUN.time, run_id: RUN.id, runs: [RUN], total: 0,
    by_classification: {}, by_rule: {}, by_category: {}, violations_high: 0, likely_high: 0, objects: 0, ...over };
}

const steps = ["uu-violations", "dead-links", "uu-likely", "quiz", "uu-manual"].map((key, i) => ({
  key, count: i + 1, title: `Steg ${key}`, description: "Beskrivelse", action: `Åpne ${key}`, tone: "info" as const,
  path: `/universell-utforming?klasse=x${i}`,
}));

const overview: Overview = {
  analysis: RUN,
  cards: {
    accessibility: card({ total: 1110, by_classification: { violation: 152, likely_violation: 806, should_review: 100, manual_check: 50, improvement: 2 } }),
    content_quality: card({ domain: "content_quality", total: 61, by_rule: { "CQ-LINK-DEAD": 5, "CQ-LINK-INTERNAL-MISSING": 1 },
      by_category: { links: 21, html: 40 }, run_id: OLD.id, last_run: OLD.time, runs: [OLD] }),
    structure: card({ domain: "structure", total: 5, by_classification: { should_review: 2, improvement: 3 } }),
    quiz: card({ domain: "quiz", analyzed: false, last_run: null, run_id: null, runs: [] }),
  },
  next_steps: steps,
  activity: [
    { type: "change", time: RUN.time, title: "Pensum", detail: null, status: "apply", summary: "Lenketekst oppdatert" },
    { type: "analysis", time: RUN.time, title: "Hele emnet analysert", detail: "Universell utforming", status: "completed" },
    { type: "analysis", time: OLD.time, title: "Analyse av hele emnet", detail: "Avbrutt", status: "cancelled" },
    { type: "analysis", time: OLD.time, title: "Analyse av valgte moduler", detail: "Feilet", status: "failed" },
    { type: "job", time: OLD.time, title: "Publisering av 2 endringer", detail: "Avbrutt fordi EmneKlar ble avsluttet", status: "interrupted" },
    { type: "change", time: OLD.time, title: "??? Bildenotater", detail: null, status: "apply", summary: "Alt-tekst oppdatert" },
    { type: "analysis", time: OLD.time, title: "Hele emnet analysert", detail: "Emnestruktur", status: "completed" },
  ],
  stats: { run_id: RUN.id, analysed_at: RUN.time, pages: 9, modules: 3, assignments: 3, quizzes: 1, discussions: 1, files: 29, media: 2, unpublished: 1 },
  pending_changes: 0,
};

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <UiProvider><MemoryRouter>{children}</MemoryRouter></UiProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

afterEach(() => vi.unstubAllGlobals());

/** [«figure label», colour class] for each key figure on a card. */
const figureTones = (card: HTMLElement) =>
  // (without the comma that is only there for screen readers)
  [...card.querySelectorAll("[data-value-tone]")].map((m) => [m.textContent?.replace(/,$/, "").replace(/\u00a0/g, " "), m.getAttribute("data-value-tone")]);

describe("overview model", () => {
  it("keeps the classes apart and says what the highlighted figures leave out", () => {
    expect(accessibilityRest(overview.cards.accessibility)).toBe("I tillegg 100 bør vurderes, 50 til manuell kontroll og 2 forbedringsforslag");
    expect(contentQualityRest(overview.cards.content_quality)).toBe("Resten: 15 andre lenkeproblemer og 40 om HTML og kode");
  });

  it("tells a partial analysis apart from the last full one, and a full analysis of one area from one of all areas", () => {
    expect(areaNames(ALL)).toBe("alle områder");
    expect(areaNames(["accessibility", "content_quality", "structure"]), "quiz switched off").toBe("universell utforming, innholdskvalitet og emnestruktur");
    expect(areaNames(["accessibility", "content_quality", "structure"], false)).toBe("alle områder");
    const now = new Date(RUN.time).getFullYear() === new Date().getFullYear() ? "" : ` ${new Date(RUN.time).getFullYear()}`;
    expect(analysisLine(PART, { full: { ...OLD, domains: ["accessibility", "content_quality"] } })).toBe(
      `Siste delanalyse: 9. nov.${now} kl. ${clock(PART.time)} (valgte moduler, universell utforming). `
      + `Hele emnet sist analysert 5. nov.${now} kl. ${clock(OLD.time)} (universell utforming og innholdskvalitet).`);
    expect(analysisLine(PART, { full: null })).toMatch(/Hele emnet er ikke analysert ennå\.$/);
    expect(analysisLine({ ...RUN, domains: ["content_quality"] })).toBe(
      `Sist analysert 6. nov.${now} kl. ${clock(RUN.time)}: hele emnet, innholdskvalitet.`);
    expect(analysisLine(RUN, { cards: Object.values(overview.cards) }), "content quality is from an older analysis")
      .toMatch(/hele emnet, alle områder\. Bygger også på eldre analyser\.$/);
  });

  it("sums up each card's coverage and age in one short line, with the rest behind «Vis detaljer»", () => {
    expect(coverageLine(card({}))).toMatch(/^Hele emnet · 6\. nov\.( 2026)? kl\. \d{2}\.20$/);
    expect(coverageLine(card({ runs: [PART], run_id: PART.id, last_run: PART.time }))).toMatch(/^Delanalyse \(valgte moduler\) · 9\. nov\./);
    const combined = card({ runs: [PART, OLD], last_run: PART.time });
    expect(coverageLine(combined)).toMatch(/^Satt sammen av 2 analyser · nyeste 9\. nov\.( 2026)?$/);
    expect(coverageDetails(combined)).toMatch(/^Resultatene er satt sammen av 2 analyser – for hvert innholdselement gjelder den nyeste: 9\. november.*\(valgte moduler\) og 5\. november.*\(hele emnet\)\.$/);
    expect(coverageDetails(card({})), "one analysis: nothing to add").toBeNull();
    expect(coverageLine(card({ analyzed: false, last_run: null, runs: [] }))).toBeNull();
  });

  it("counts quizzes and questions apart – and describes the old total exactly when the split is missing", () => {
    expect(quizAffected(card({ objects: 4, quizzes_affected: 2, questions_affected: 3 }))).toEqual([
      { value: 2, label: "quizer med funn" }, { value: 3, label: "spørsmål med funn" }]);
    expect(quizAffected(card({ objects: 4 }))).toEqual([{ value: 4, label: "spørsmål og quizer med funn" }]);
  });

  it("keeps «Avbrutt» and «Feilet» apart and never repeats the status in the line below", () => {
    const job = (status: string, detail: string | null) => ({ type: "analysis" as const, time: null, title: "Analyse", detail, status });
    expect(activityStatus(job("cancelled", "Avbrutt"))).toEqual({ kind: "stopped", label: "Avbrutt", tone: "warning" });
    expect(activityStatus(job("interrupted", "Avbrutt fordi EmneKlar ble avsluttet")).tone).toBe("warning");
    expect(activityStatus(job("failed", "Feilet"))).toEqual({ kind: "failed", label: "Feilet", tone: "danger" });
    expect(activityStatus(job("completed", "Quiz"))).toEqual({ kind: "completed", label: "Fullført", tone: "success" });
    expect(activityMeta(job("cancelled", "Avbrutt"))).toBeNull();
    expect(activityMeta(job("completed", "Quiz"))).toBe("Quiz");
    expect(activityStatus(job("something_new", "Noe nytt"))).toEqual({ kind: "other", label: "Noe nytt", tone: "neutral" });
    expect(activityMeta(job("something_new", "Noe nytt")), "the mark already shows it").toBeNull();
    const change = { type: "change" as const, time: null, title: "Side", detail: null, status: "conflict", summary: "Alt-tekst oppdatert" };
    expect(activityStatus(change)).toEqual({ kind: "conflict", label: "Konflikt – ikke sendt", tone: "warning" });
    expect(activityMeta(change)).toBe("Alt-tekst oppdatert");
  });
});

describe("Emneoversikt", () => {
  it("separates avvik from sannsynlige avvik, highlights one step and keeps one time basis", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(overview), { status: 200 })));
    const user = userEvent.setup();
    render(wrap(<OverviewPage />));
    // Each area card is one link: name with the figures, coverage as its description, nothing else inside.
    const uu = await screen.findByRole("link", { name: "Universell utforming: 152 bekreftede avvik, 806 sannsynlige avvik" });
    expect(uu).toHaveAttribute("href", "/universell-utforming");
    expect(uu).toHaveAccessibleDescription(/^Hele emnet · 6\. nov\./);
    expect(figureTones(uu)).toEqual([["152 bekreftede avvik", "critical"], ["806 sannsynlige avvik", "warning"]]);
    expect(within(uu).queryByRole("button"), "no «Vis detaljer» in the card").toBeNull();
    expect(uu.querySelector(".ek-status-card__arrow")).not.toBeNull();

    const cq = screen.getByRole("link", { name: "Innholdskvalitet: 6 døde lenker, 0 utilgjengelige videoer" });
    expect(cq).toHaveAttribute("href", "/innholdskvalitet");
    expect(figureTones(cq), "a zero is muted").toEqual([["6 døde lenker", "critical"], ["0 utilgjengelige videoer", "zero"]]);
    expect(cq, "an older analysis is never hidden").toHaveAccessibleDescription(/^Hele emnet · 5\. nov\./);
    const structure = screen.getByRole("link", { name: "Emnestruktur: 2 bør vurderes, 3 forbedringsforslag" });
    expect(structure).toHaveAttribute("href", "/emnestruktur");
    expect(figureTones(structure)).toEqual([["2 bør vurderes", "warning"], ["3 forbedringsforslag", "info"]]);
    expect(screen.getByRole("link", { name: "Quiz: Ikke analysert ennå" })).toHaveAttribute("href", "/quizassistent");

    // The lines that used to be behind each card's «Vis detaljer», with coverage and age – on the page, not hover-only.
    expect(screen.queryByText("1 110 åpne funn i alt")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Detaljer og dekning per område" }));
    const details = screen.getAllByRole("term")[0].closest("dl")!;
    expect(details).toHaveTextContent("1 110 åpne funn i alt");
    expect(details).toHaveTextContent("I tillegg 100 bør vurderes, 50 til manuell kontroll og 2 forbedringsforslag");
    expect(details).toHaveTextContent("61 åpne funn i alt, blant dem funn om 6 døde lenker og 0 utilgjengelige videoer");
    expect(details).toHaveTextContent("Resten: 15 andre lenkeproblemer og 40 om HTML og kode");
    expect(details).toHaveTextContent("5 forslag i alt");
    expect(details).toHaveTextContent(/Innholdskvalitet\s*Hele emnet · 5\. nov\./);
    expect(details).toHaveTextContent(/Quiz\s*Ikke analysert ennå\./);

    expect(screen.queryByText(/^Tallene er åpne funn/), "the explanation is behind «Hva betyr tallene?»").toBeNull();
    await user.click(screen.getByRole("button", { name: "Hva betyr tallene?" }));
    expect(screen.getByText(/^Tallene er åpne funn/)).toBeVisible();
    expect(screen.getByText(/^Sist analysert 6\. nov\.( 2026)? kl\. \d{2}\.20: hele emnet, alle områder\. Bygger også på eldre analyser\.$/)).toBeInTheDocument();
    expect(screen.getByText("Slik emnet så ut ved siste analyse.")).toBeInTheDocument();

    const recommended = screen.getByRole("list", { name: "Anbefalt neste steg" });
    const rows = within(recommended).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveAttribute("data-featured", "true");
    expect(within(rows[0]).getByRole("link", { name: "Åpne uu-violations" })).toHaveAttribute("href", "/universell-utforming?klasse=x0");
    expect(screen.queryByRole("link", { name: "Åpne quiz" }), "behind «Se alle anbefalinger»").toBeNull();
    await userEvent.click(screen.getByText("Se alle anbefalinger (2 til)"));
    expect(screen.getByRole("link", { name: "Åpne quiz" })).toBeVisible();
    expect(screen.queryByText(/^Rekkefølgen følger hvor sikkert funnet er/), "behind its own question").toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Hvordan prioriteres anbefalingene?" }));
    expect(screen.getByText(/^Rekkefølgen følger hvor sikkert funnet er.*ikke hvor mange funn det er\.$/)).toBeVisible();

    const activity = screen.getByRole("list", { name: "Siste analyser og endringer" });
    const marks = within(activity).getAllByRole("listitem").map((row) => {
      const mark = row.querySelector(".ek-activity__status")!;
      return [row.querySelector(".ek-activity__title")?.textContent, mark.textContent, mark.getAttribute("data-status-tone"),
        row.querySelector(".ek-activity__meta")?.textContent ?? null];
    });
    expect(marks, "at most four events, newest first").toEqual([
      ["Pensum", "Status: Publisert til Canvas", "success", "Lenketekst oppdatert"],
      ["Hele emnet analysert", "Status: Fullført", "success", "Universell utforming"],
      ["Analyse av hele emnet", "Status: Avbrutt", "warning", null],
      ["Analyse av valgte moduler", "Status: Feilet", "danger", null],
    ]);
    for (const row of within(activity).getAllByRole("listitem")) {
      expect(row.querySelector(".ek-activity__status-icon"), "the icon is decorative").toHaveAttribute("aria-hidden", "true");
    }
    // The rest (nothing deleted) is in the job history and the change log.
    expect(screen.queryByText("Publisering av 2 endringer"), "the fifth event is not on the overview").toBeNull();
    expect(screen.getByRole("link", { name: "Jobbhistorikk" })).toHaveAttribute("href", "/rapporter#jobbhistorikk");
    expect(screen.getByRole("link", { name: "Endringslogg" })).toHaveAttribute("href", "/canvas-verktoy/endringslogg");

    expect(screen.getByText(/^«Upublisert innhold» er sider, oppgaver, quizer og diskusjoner.*skal ikke legges sammen\.$/)).toBeInTheDocument();
  });

  it("says before the first analysis that the analysis changes nothing – without hiding the opt-in exception", async () => {
    const empty = { ...overview, cards: Object.fromEntries(Object.entries(overview.cards).map(([k, c]) =>
      [k, { ...c, analyzed: false, last_run: null, run_id: null, runs: [] }])), analysis: null };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(empty), { status: 200 })));
    render(wrap(<OverviewPage />));
    expect(await screen.findByRole("heading", { name: "Kom i gang med første analyse" })).toBeInTheDocument();
    expect(screen.getByText(/Analysen endrer ingenting i Canvas, og rettinger publiseres først når du godkjenner dem/))
      .toHaveTextContent("(med mindre du velger automatisk innsetting i KI-bildeassistenten)");
    expect(screen.queryByText(/Ingenting endres i Canvas før du selv godkjenner det/)).toBeNull();
  });

  it("shows confirmed violations and «Bør vurderes» in the chart by default; the table follows the choice", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(overview), { status: 200 })));
    const user = userEvent.setup();
    render(wrap(<OverviewPage />));
    const choices = await screen.findByRole("group", { name: "Vis i diagrammet" });
    const pressed = () => within(choices).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
    expect(pressed()).toEqual(["Bekreftede avvik og feil", "Bør vurderes"]);
    expect(screen.getByText("Antall åpne funn i de valgte kategoriene – ikke en samlet alvorlighetsgrad.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vis som tabell" }));
    const headers = () => within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers()).toEqual(["Område", "Bekreftede avvik og feil", "Bør vurderes"]);
    const uuRow = within(screen.getByRole("table")).getByRole("row", { name: /Universell utforming/ });
    expect(uuRow, "confirmed and likely never merged").toHaveTextContent(/Universell utforming\s*152\s*100/);
    await user.click(within(choices).getByRole("button", { name: "Sannsynlige avvik og feil" }));
    expect(pressed()).toEqual(["Bekreftede avvik og feil", "Sannsynlige avvik og feil", "Bør vurderes"]);
    expect(headers()).toEqual(["Område", "Bekreftede avvik og feil", "Sannsynlige avvik og feil", "Bør vurderes"]);
    for (const name of ["Bekreftede avvik og feil", "Sannsynlige avvik og feil", "Bør vurderes"]) {
      await user.click(within(choices).getByRole("button", { name }));
    }
    expect(screen.getByText("Velg minst én kategori for å vise diagrammet.")).toBeInTheDocument();
  });

  it("gives the quiz card the same structure: the possible errors first, then quizzes and questions apart", async () => {
    const analysed = { ...overview, analysis: PART, full_analysis: OLD, cards: { ...overview.cards,
      quiz: card({ domain: "quiz", total: 3, total_with_ai: 5, objects: 4, quizzes_affected: 2, questions_affected: 3 }) } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(analysed), { status: 200 })));
    render(wrap(<OverviewPage />));
    const quiz = await screen.findByRole("link", { name: /^Quiz: 5 mulige feil, 2\squizer og 3\sspørsmål\smed\sfunn$/ });
    expect(figureTones(quiz)).toEqual([["5 mulige feil", "warning"], ["2 quizer og 3 spørsmål med funn", "neutral"]]);
    expect(quiz).not.toHaveTextContent("berørt");
    // A newer partial analysis does not make the whole page look newly analysed.
    expect(screen.getByText(/^Siste delanalyse: 9\. nov\..*\(valgte moduler, universell utforming\)\. Hele emnet sist analysert 5\. nov\..*\(alle områder\)\.$/)).toBeInTheDocument();
  });
});
