import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import { FindingsView } from "./FindingsView";

vi.mock("../../core/session", () => ({
  useSession: () => ({
    canvas: { token_configured: true, base_url: "https://canvas.test", identity: null },
    ai: { providers_enabled: [], external_allowed: false, confirm_before_send: true },
    flags: {}, general: { page_size: 25 },
  }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

function wrap(children: ReactNode, url: string) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <UiProvider><MemoryRouter initialEntries={[url]}>{children}</MemoryRouter></UiProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const response = {
  items: [], ids: [], total: 12, page: 1, page_size: 25,
  summary: { total: 958, ignored: 0, verified: 0, fixed: 0, staged: 0, by_classification: { violation: 152 }, by_category: {}, actionable: 0 },
  categories: [], profile: { id: "p", title: "Profil", version: "1" },
  runs: [{ id: 1, domains: ["accessibility"], scope_type: "course", status: "complete", started_at: null,
    finished_at: "2026-11-06T13:20:00+00:00", counts: {}, ruleset_version: "1", profile_id: "p", profile_version: "1", limitations: [] }],
};

afterEach(() => vi.unstubAllGlobals());

function serve(body: object) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.includes("/findings") ? body : { items: {}, queue: {} }), { status: 200 })));
}

const firstCard = async () => {
  await screen.findByText(/i endringskø/);
  return document.querySelector(".ek-metric-card");
};
const metaLine = () => document.querySelector(".ek-meta-line")!;

describe("the headline figures", () => {
  it("shows confirmed avvik as the main figure and likely ones as a smaller figure (Universell utforming)", async () => {
    serve({ ...response, classifications: ["violation", "likely_violation", "should_review", "improvement", "manual_check"],
      summary: { ...response.summary, by_classification: { violation: 152, likely_violation: 806 } } });
    render(wrap(<FindingsView domain="accessibility" emptyText="" />, "/universell-utforming"));
    const card = (await firstCard())!;
    expect(card.querySelector(".ek-metric-card__value")).toHaveTextContent("152");
    expect(card.querySelector(".ek-metric-card__label")).toHaveTextContent("Bekreftede avvik");
    expect(card.querySelector(".ek-metric-card__secondary")).toHaveTextContent("806 sannsynlige avvik");
    expect(screen.queryByText("Avvik / sannsynlige avvik")).toBeNull();
    expect(document.querySelector(".ek-grid")).toHaveAttribute("data-cols", "4");
    expect(metaLine()).toHaveTextContent(/Regelsett 1, profil «Profil»\. 0 ignorert, 0 kontrollert, 0 i endringskø, 0 rettet\./);
    expect(screen.getByRole("button", { name: /^Avvik/ })).toBeInTheDocument();
  });

  it("says «feil» outside universal design and leaves out a class the area never gives", async () => {
    serve({ ...response, classifications: ["violation", "should_review", "improvement", "manual_check"],
      summary: { ...response.summary, by_classification: { violation: 7 } } });
    render(wrap(<FindingsView domain="content_quality" emptyText="" />, "/innholdskvalitet"));
    const card = (await firstCard())!;
    expect(card.querySelector(".ek-metric-card__label")).toHaveTextContent("Bekreftede feil");
    expect(card.querySelector(".ek-metric-card__value")).toHaveTextContent("7");
    expect(card.querySelector(".ek-metric-card__secondary")).toBeNull();
    expect(card).not.toHaveTextContent(/avvik/i);
    // No universal-design ruleset or regulatory profile outside Universell utforming – the rest of the line stays.
    expect(metaLine()).not.toHaveTextContent(/Regelsett|profil/);
    expect(metaLine()).toHaveTextContent(/Siste analyse .* 0 ignorert, 0 kontrollert, 0 i endringskø, 0 rettet\./);
    // The class filter uses the area's words too, and leaves out classes without findings here.
    expect(screen.getByRole("button", { name: /^Feil/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Sannsynlig feil/ }), "no «Sannsynlig feil (0)»").toBeNull();
    expect(screen.queryByRole("button", { name: /^Bør vurderes/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Avvik/ })).toBeNull();
  });

  it("shows no empty «avvik» card in an area without them (Emnestruktur)", async () => {
    serve({ ...response, classifications: ["should_review", "improvement"],
      summary: { ...response.summary, by_classification: { should_review: 3 } } });
    render(wrap(<FindingsView domain="structure" emptyText="" />, "/emnestruktur"));
    const card = (await firstCard())!;
    expect(card.querySelector(".ek-metric-card__label")).toHaveTextContent("Bør vurderes");
    expect(screen.queryByText(/Bekreftede/)).toBeNull();
    expect(document.querySelector(".ek-grid")).toHaveAttribute("data-cols", "3");
    expect(screen.queryByRole("button", { name: /^Feil/ }), "no «Feil (0)» on Emnestruktur").toBeNull();
    expect(metaLine()).not.toHaveTextContent(/Regelsett|profil/);
    expect(screen.getByRole("button", { name: /^Bør vurderes/ })).toBeInTheDocument();
  });

  it("keeps a class chosen through a link visible, also with 0 findings", async () => {
    serve({ ...response, classifications: ["violation", "likely_violation", "should_review", "improvement", "manual_check"],
      summary: { ...response.summary, by_classification: { violation: 152 } } });
    render(wrap(<FindingsView domain="accessibility" emptyText="" />, "/universell-utforming?klasse=manual_check"));
    await firstCard();
    const chosen = screen.getByRole("button", { name: /^Manuell kontroll/ });
    expect(chosen).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Avvik/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: /^Sannsynlig avvik/ })).toBeNull();
  });
});

describe("«Godkjenn alle klare»", () => {
  const fixable = { id: 1, domain: "accessibility", rule_id: "UU-HEAD-EMPTY", title: "Tom overskrift", message: "",
    classification: "violation", severity: "serious", test_method: "deterministic", category: "headings",
    category_label: "Overskrifter", status: "open", object_type: "page", object_title: "Side", fix: { type: "remove_element" },
    ready: null, location: {}, evidence: {} };

  it("is disabled and not the main action when nothing in the selection is ready", async () => {
    serve({ ...response, items: [fixable], ids: [1], total: 1, ready: { automatic: 0, suggestion: 0 } });
    render(wrap(<FindingsView domain="accessibility" emptyText="" />, "/universell-utforming"));
    const button = await screen.findByRole("button", { name: "Godkjenn alle klare" });
    expect(button).toBeDisabled();
    expect(button).not.toHaveClass("ek-btn--primary");
    expect(button).toHaveAccessibleDescription(/^Ingen klare i utvalget\. Klar betyr at rettingen er bestemt av funnet/);
    expect(button).toHaveAccessibleDescription(/KI-forslag må vurderes ett for ett og er ikke med\.$/);
  });

  it("is the main action when findings in the selection are ready – also on other pages", async () => {
    serve({ ...response, items: [fixable], ids: [1, 2, 3], total: 3, ready: { automatic: 2, suggestion: 1 } });
    render(wrap(<FindingsView domain="accessibility" emptyText="" />, "/universell-utforming"));
    const button = await screen.findByRole("button", { name: "Godkjenn alle klare" });
    expect(button).toBeEnabled();
    expect(button).toHaveClass("ek-btn--primary");
    expect(button).toHaveAccessibleDescription(/^2 klare i utvalget, og 1 med regelbaserte tekstforslag\./);
  });
});

describe("a selection from a link", () => {
  it("asks the API for exactly the selection, says so and can show everything again", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(url.includes("/findings") ? response : { items: {}, queue: {} }), { status: 200 });
    }));
    render(wrap(<FindingsView domain="accessibility" emptyText="" />,
      "/universell-utforming?klasse=violation&alvorlighet=critical,serious&utvalg=Avvik+med+h%C3%B8y+alvorlighet"));
    expect(await screen.findByText("Utvalg: Avvik med høy alvorlighet")).toBeInTheDocument();
    expect(screen.getByText(/Listen viser 12 funn i dette utvalget \(alvorlighet kritisk eller alvorlig\)/)).toBeInTheDocument();
    const first = new URL(urls.find((u) => u.includes("/findings"))!, "http://x");
    expect(first.searchParams.getAll("classification")).toEqual(["violation"]);
    expect(first.searchParams.getAll("severity")).toEqual(["critical", "serious"]);

    await userEvent.click(screen.getByRole("button", { name: "Vis alle funn" }));
    await waitFor(() => expect(screen.queryByText(/^Utvalg:/)).not.toBeInTheDocument());
    const last = new URL(urls.filter((u) => u.includes("/findings")).at(-1)!, "http://x");
    expect(last.searchParams.getAll("severity")).toEqual([]);
    expect(last.searchParams.getAll("classification")).toEqual([]);
  });
});
