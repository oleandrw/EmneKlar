import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import { resetAiConsentMemory } from "../findings/AiSuggestion";
import { LinksPanel } from "./LinksPanel";

const session = vi.hoisted(() => ({ providers: ["anthropic"] as string[] }));
vi.mock("../../core/session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, ai: { providers_enabled: session.providers, external_allowed: true, confirm_before_send: true },
    flags: {}, general: { page_size: 25 } }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const place = (id: string, title: string, module: string, count = 1) => ({ object_type: "page", object_id: id, title, module, count, text: "Pensumliste for emnet",
  canvas: { view: `https://canvas.test/courses/101/pages/${id}`, highlight: null, edit: null, module_item: null } });
const LONG = "https://www.example.org/pensum/2025/emner/digital-kompetanse/lesestoff/liste-over-pensum-for-hele-emnet?versjon=3";
const LINKS = {
  checked_at: "2026-11-06T10:00:00+00:00",
  summary: { broken: 1, unchecked: 1, working: 1 },
  links: [
    { url: LONG, state: "DEAD", category: "broken", category_label: "Fungerer ikke", detail: "Siden finnes ikke (HTTP 404).",
      method: "Automatisk kontroll uten innlogging", http_status: 404, final_url: null, checked_at: "2026-11-06T10:00:00+00:00",
      title: "Pensumliste for emnet", places: 2, occurrences: 4,
      uses: [{ ...place("oppsummering", "Oppsummering", "Modul 3", 3), finding_id: 7 }, place("fargelaere", "Fargelære", "Modul 2")] },
    { url: "https://www.example.org/ressurs", state: "UNKNOWN", category: "unchecked", category_label: "Kunne ikke kontrolleres",
      detail: "Nettstedet avviste kontrollen (HTTP 403).", http_status: 403, final_url: null, checked_at: "2026-11-06T10:00:00+00:00",
      title: null, places: 1, occurrences: 1, uses: [place("velkommen", "Velkommen", "Modul 1")] },
    { url: "https://www.example.org/plan", state: "WORKING", category: "working", category_label: "Fungerer", detail: "Lenken virker.",
      http_status: 200, final_url: null, checked_at: "2026-11-06T10:00:00+00:00", title: null, places: 1, occurrences: 1,
      uses: [place("velkommen", "Velkommen", "Modul 1")] },
  ],
};
const PLAN = { available: true, reason: null, needs_confirmation: true, external: true, task: "link_alternatives",
  payload_summary: "Søket sendes til Claude, som søker på nettet. Ingen studentdata sendes.",
  route: { provider: "anthropic", model: "Claude Haiku 4.5", reason: "billigst" }, search: { available: true, service: "Claude", note: null } };
const SUGGESTION = { url: "https://www.example.org/pensum-2026", title: "Pensumliste 2026", publisher: "Example", relation: "same",
  relation_label: "Samme ressurs, ny adresse", reason: "Samme liste for 2026.", limitations: [], origin: "search",
  check: { state: "WORKING", label: "Fungerer", checked_at: "2026-11-07T09:00:00+00:00" } };

type Calls = { url: string; body: unknown }[];
function stub(alternatives: (body: { url: string }) => unknown = (b) => ({ url: b.url, suggestions: [SUGGESTION], none_found: false, searched: true,
  considered: 3, model: "Claude Haiku 4.5", provider_name: "Anthropic" })) {
  const calls: Calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    let data: unknown = {};
    if (url.endsWith("/courses/101/links")) data = LINKS;
    else if (url.endsWith("/content-quality/recheck")) {
      data = { url: body.url, state: "WORKING", category: "working", category_label: "Fungerer", detail: "Lenken virker.",
        http_status: 200, checked_at: "2026-11-07T12:00:00+00:00", summary: { broken: 0, unchecked: 1, working: 2 } };
    } else if (url.endsWith("/links/alternatives/prepare")) data = PLAN;
    else if (url.endsWith("/links/alternatives")) data = alternatives(body);
    else if (url.endsWith("/links/replace/preview")) {
      data = { where: { role: "course", message: "" }, places: body.places.map((p: { object_type: string; object_id: string; title: string }) => ({
        ...p, count: 3, message: null, changes: [{ before: `<a href="${LONG}">P</a>`, after: `<a href="${body.new_url}">P</a>` }] })) };
    } else if (url.endsWith("/links/replace/approve")) data = { approved: [1], skipped: [] };
    return new Response(JSON.stringify(data), { status: 200 });
  }));
  return calls;
}

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider><UiProvider><MemoryRouter>{children}</MemoryRouter></UiProvider></ToastProvider>
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetAiConsentMemory();
  session.providers = ["anthropic"];
});

describe("Lenker", () => {
  it("shows one compact row per link, with a title, the address and places to expand", async () => {
    stub();
    const user = userEvent.setup();
    render(wrap(<LinksPanel />));
    const table = await screen.findByRole("table", { name: /Lenker/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows, "«Bør kontrolleres» hides working links").toHaveLength(2);
    const first = rows[0];
    expect(within(first).getByRole("rowheader")).toHaveTextContent("Pensumliste for emnet");
    expect(within(first).getByText(/example\.org · \/pensum\/2025/)).toBeInTheDocument();
    const toggle = within(first).getByRole("button", { name: /Brukt på 2 steder \(4 lenker\)/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(first).getByText("For eksempel «Oppsummering» (Modul 3)")).toBeInTheDocument();
    await user.click(toggle);
    expect(within(first).getByRole("link", { name: /Fargelære/ })).toHaveAttribute("href", "https://canvas.test/courses/101/pages/fargelaere");
    expect(within(first).getByText("Modul: Modul 3 · 3 lenker her")).toBeInTheDocument();
    expect(within(first).getAllByRole("button", { name: /Endre lenke i/ })).toHaveLength(2);
    expect(within(first).getAllByRole("button", { name: /^Rett funnet/ }), "the finding's own fix, where there is a finding")
      .toHaveLength(1);
    expect(within(first).getByRole("button", { name: /Endre flere steder/ })).toBeInTheDocument();
    expect(screen.getByText(/Siste samlede lenkekontroll:/)).toBeInTheDocument();
  });

  it("keeps uncertain checks apart from proven errors and puts «Åpne lenke» first for them", async () => {
    stub();
    const user = userEvent.setup();
    render(wrap(<LinksPanel />));
    const table = await screen.findByRole("table", { name: /Lenker/ });
    const uncertain = within(table).getAllByRole("row")[2];
    expect(within(uncertain).getByText("Kunne ikke kontrolleres")).toBeInTheDocument();
    expect(within(uncertain).getByRole("link", { name: /Åpne lenke/ })).toHaveClass("ek-btn--primary");
    expect(within(uncertain).queryByText("Fungerer ikke")).toBeNull();
    await user.click(screen.getByRole("button", { name: /^Fungerer ikke/ }));
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(1);
  });

  it("«Sjekk på nytt» updates the row and the totals", async () => {
    const calls = stub();
    const user = userEvent.setup();
    render(wrap(<LinksPanel />));
    await screen.findByRole("table", { name: /Lenker/ });
    await user.click(screen.getByRole("button", { name: /Alle lenker/ }));
    await user.click(screen.getByRole("button", { name: `Sjekk på nytt: ${LONG}` }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/recheck"))?.body).toEqual({ url: LONG, course_id: "101" }));
    const row = screen.getByRole("rowheader", { name: /Pensumliste for emnet/ }).closest("tr")!;
    await waitFor(() => expect(within(row).getByText("Fungerer")).toBeInTheDocument());
    expect(screen.getAllByRole("status").some((s) => s.textContent?.includes("Sjekket på nytt: Fungerer")),
      "the result is announced, not only shown in the row").toBe(true);
    const figures = screen.getByRole("list", { name: "Lenkestatus" });
    expect(within(figures).getByText(/^2/, { selector: "*" })).toBeTruthy();
  });

  it("changes only the chosen places, after a preview, and can use a KI alternative", async () => {
    const calls = stub();
    const user = userEvent.setup();
    render(wrap(<LinksPanel />));
    await user.click(await screen.findByRole("button", { name: `Endre flere steder: ${LONG}` }));
    const dialog = screen.getByRole("dialog", { name: "Endre lenken på flere steder" });
    const preview = within(dialog).getByRole("button", { name: "Forhåndsvis endringen" });
    expect(preview).toBeDisabled();
    expect(preview, "nothing is chosen in advance, and the button says why").toHaveAccessibleDescription(
      "Forhåndsvisning krever en ny adresse og minst ett valgt sted.");
    await user.click(within(dialog).getByRole("button", { name: "Finn alternativ lenke med KI" }));
    expect(await within(dialog).findByText(PLAN.payload_summary)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/links/alternatives")), "nothing is sent before consent").toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Send og søk" }));
    expect(await within(dialog).findByText("Pensumliste 2026")).toBeInTheDocument();
    expect(within(dialog).getByText(/Samme ressurs, ny adresse · Example/)).toBeInTheDocument();
    expect(within(dialog).getByText(/sier ikke om den passer faglig/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Bruk denne adressen" }));
    expect(within(dialog).getByLabelText("Ny adresse")).toHaveValue("https://www.example.org/pensum-2026");
    await user.click(within(dialog).getByRole("checkbox", { name: /Fargelære/ }));
    await user.click(preview);
    expect(await within(dialog).findByText(/Fargelære – 3 lenker endres/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/replace/preview"))?.body).toEqual({
      old_url: LONG, new_url: "https://www.example.org/pensum-2026", link_text: null, ai_suggestion: true,
      places: [{ object_type: "page", object_id: "fargelaere", title: "Fargelære" }] });
    await user.click(within(dialog).getByRole("button", { name: "Godkjenn til endringskøen" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/replace/approve"))).toBe(true));
    expect(calls.some((c) => c.url.includes("/changes/apply")), "nothing is published here").toBe(false);
  });

  it("says plainly when no good replacement was found, and offers a manual search", async () => {
    stub((b) => ({ url: b.url, suggestions: [], none_found: true, note: "Ingen av kandidatene passet.", searched: true, considered: 2 }));
    const user = userEvent.setup();
    render(wrap(<LinksPanel />));
    await user.click(await screen.findByRole("button", { name: `Endre flere steder: ${LONG}` }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Finn alternativ lenke med KI" }));
    await user.click(await within(dialog).findByRole("button", { name: "Send og søk" }));
    expect(await within(dialog).findByText("Fant ingen gode erstatninger")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Søk etter ressursen på nettet/ })).toHaveAttribute("href", expect.stringContaining("duckduckgo.com"));
    expect(within(dialog).getByLabelText("Ny adresse")).toHaveValue("");
  });

  it("ignores an answer that belongs to another link, and works by hand without KI", async () => {
    stub(() => ({ url: "https://annen.example.org", suggestions: [SUGGESTION], none_found: false, searched: true, considered: 1 }));
    const user = userEvent.setup();
    const { unmount } = render(wrap(<LinksPanel />));
    await user.click(await screen.findByRole("button", { name: `Endre flere steder: ${LONG}` }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Finn alternativ lenke med KI" }));
    await user.click(await within(dialog).findByRole("button", { name: "Send og søk" }));
    await new Promise((r) => setTimeout(r, 50));
    expect(within(dialog).queryByText("Pensumliste 2026")).toBeNull();
    unmount();

    session.providers = [];
    stub();
    render(wrap(<LinksPanel />));
    await user.click(await screen.findByRole("button", { name: `Endre flere steder: ${LONG}` }));
    const manual = screen.getByRole("dialog");
    expect(within(manual).queryByRole("button", { name: "Finn alternativ lenke med KI" })).toBeNull();
    expect(within(manual).getByRole("link", { name: "Sett opp KI-assistenter" })).toBeInTheDocument();
    await user.type(within(manual).getByLabelText("Ny adresse"), "https://ny.example.org/pensum");
    await user.click(within(manual).getByRole("checkbox", { name: /Oppsummering/ }));
    expect(within(manual).getByRole("button", { name: "Forhåndsvis endringen" })).toBeEnabled();
  });
});

describe("dead links from Oversikt", () => {
  const INTERNAL = {
    url: "/courses/101/pages/finnes-ikke", open_url: "https://canvas.test/courses/101/pages/finnes-ikke", kind: "internal",
    state: "DEAD", category: "broken", category_label: "Fungerer ikke",
    detail: "Peker til innhold som ikke finnes i emnet (slettet, flyttet eller feil adresse).", http_status: null,
    final_url: null, checked_at: "2026-11-06T10:00:00+00:00", title: "gammel side", places: 1, occurrences: 1,
    uses: [{ ...place("bildeformater", "Bildeformater", "Modul 1"), finding_id: 9 }],
  };

  it("opens «Fungerer ikke» with internal dead links among the external ones", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(url);
      const data = url.endsWith("/courses/101/links")
        ? { ...LINKS, summary: { ...LINKS.summary, broken: 2 }, links: [LINKS.links[0], INTERNAL, ...LINKS.links.slice(1)] }
        : {};
      return new Response(JSON.stringify(data), { status: 200 });
    }));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider><UiProvider>
          <MemoryRouter initialEntries={["/innholdskvalitet?fane=lenker&lenker=broken"]}><LinksPanel /></MemoryRouter>
        </UiProvider></ToastProvider>
      </QueryClientProvider>,
    );
    const table = await screen.findByRole("table", { name: /Lenker/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows, "only the rows the figure on Oversikt counts").toHaveLength(2);
    const internal = rows.find((r) => within(r).queryByText("Intern lenke"))!;
    expect(within(internal).getByRole("rowheader")).toHaveTextContent("gammel side");
    expect(within(internal).getByText("Fungerer ikke")).toBeInTheDocument();
    expect(within(internal).getByRole("link", { name: /Åpne lenke/ }))
      .toHaveAttribute("href", "https://canvas.test/courses/101/pages/finnes-ikke");
    // No web check of a Canvas address without logging in: the next analysis checks it again.
    expect(within(internal).queryByRole("button", { name: /Sjekk på nytt/ })).toBeNull();
    expect(within(internal).getByText("Kontrolleres på nytt når du analyserer innholdskvaliteten.")).toBeInTheDocument();
    expect(within(table).getByText("Pensumliste for emnet")).toBeInTheDocument();
  });
});
