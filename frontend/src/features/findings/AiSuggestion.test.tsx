import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Finding } from "../../core/api/types";
import { ToastProvider } from "../../design-system";
import { resetAiConsentMemory } from "./AiSuggestion";
import { FindingDetail } from "./FindingDetail";

const session = vi.hoisted(() => ({ providers: ["anthropic"] as string[] }));
vi.mock("../../core/session", () => ({
  useSession: () => ({
    canvas: { token_configured: true, base_url: "https://canvas.test", identity: null },
    current_course_id: "101",
    ai: { providers_enabled: session.providers, external_allowed: true, confirm_before_send: true },
    flags: {},
    general: { page_size: 25 },
  }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider><MemoryRouter>{children}</MemoryRouter></ToastProvider>
    </QueryClientProvider>
  );
}

const link: Finding = {
  id: 40, run_id: 1, course_id: "101", domain: "accessibility", rule_id: "UU-LINK-RAWURL", ruleset_version: "2026.11.3",
  category: "links", classification: "improvement", test_method: "heuristic", severity: "minor", confidence: "high",
  title: "Nettadresse brukt som lenketekst", message: "Lenketeksten er en nettadresse.",
  object_type: "assignment", object_id: "301", object_title: "Modul 3 – Oppgave 5", object_url: null,
  location: { module: "Modul 3", context: "Les https://www.plag.no/tjenester/ki før du leverer." },
  evidence: { href: "https://www.plag.no/tjenester/ki" }, remediation: "Skriv en beskrivende lenketekst.", status: "open",
  created_at: "2026-11-07T10:00:00+00:00", fix: { type: "set_link_text", label: "Skriv en beskrivende lenketekst", params: { path: "a:nth-of-type(1)" } },
};
const preview = {
  kind: "assignment.update_description", before_display: "<a>før</a>", after_display: "<a>etter</a>", preview_html: "<p>etter</p>",
  risk: "low", existing_change_id: null, targeted: true, count: 1, occurrences: 1, related: [], changes: [],
  where: { course_id: "101", course_name: "Emne", role: "course", locked: false, parent: null, associated_course_count: null,
    sync_needed: false, message: "Endringen gjøres bare i dette emnet." },
};
const PLAN = { available: true, reason: null, needs_confirmation: true, external: true, task: "link_text",
  payload_summary: "Lenkeadressen, lenketeksten og teksten rundt lenken sendes til KI-leverandøren. Ingen studentdata sendes.",
  route: { provider: "anthropic", model: "Claude Haiku 4.5", reason: "billigst" },
  basis: "Grunnlag: Tittel og et kort utdrag fra målsiden, hentet nå.", weak: null };

type Calls = { url: string; body: unknown }[];

function stub(answer: (n: number) => { status?: number; body: unknown }) {
  const calls: Calls = [];
  let n = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    if (url.endsWith("/ai-suggestion/prepare")) return new Response(JSON.stringify(PLAN), { status: 200 });
    if (url.endsWith("/ai-suggestion")) {
      const a = answer(++n);
      return new Response(JSON.stringify(a.body), { status: a.status ?? 200 });
    }
    if (url.includes("/fix/preview")) return new Response(JSON.stringify(preview), { status: 200 });
    if (url.includes("/fix/approve")) return new Response(JSON.stringify({ id: 1, status: "approved", also_staged: [], errors: [] }), { status: 200 });
    return new Response("{}", { status: 200 });
  }));
  return calls;
}

const ok = (text: string) => ({ body: { finding_id: 40, text, label: "KI-forslag – må vurderes", basis: PLAN.basis, weak: null,
  provider: "anthropic", provider_name: "Anthropic", model: "Claude Haiku 4.5" } });

afterEach(() => {
  vi.unstubAllGlobals();
  resetAiConsentMemory();
  session.providers = ["anthropic"];
});

describe("Foreslå lenketekst med KI", () => {
  it("shows what is sent first, fills the empty field, says where it came from and marks the approved fix", async () => {
    const calls = stub(() => ok("KI-veileder fra Plagiatsjekk"));
    const onNext = vi.fn();
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} nav={{ index: 0, total: 25, onNext }} />));
    const dialog = screen.getByRole("dialog", { name: link.title });
    await userEvent.click(within(dialog).getByRole("button", { name: "Foreslå lenketekst med KI" }));
    expect(await within(dialog).findByText(PLAN.payload_summary)).toBeInTheDocument();
    expect(within(dialog).getByText(PLAN.basis)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/ai-suggestion")), "nothing is sent before consent").toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Send og lag forslag" }));
    const field = within(dialog).getByLabelText("Lenketekst");
    await waitFor(() => expect(field).toHaveValue("KI-veileder fra Plagiatsjekk"));
    expect(within(dialog).getByText("KI-forslag – må vurderes")).toBeInTheDocument();
    expect(within(dialog).getByText(/Laget med Claude Haiku 4\.5 \(Anthropic\)\. Grunnlag: Tittel og et kort utdrag/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/ai-suggestion"))?.body).toEqual({ confirmed: true, avoid: [] });

    // «Nytt forslag»: no new consent for the same task and service in this session; asks for a different text.
    await userEvent.click(within(dialog).getByRole("button", { name: "Nytt forslag" }));
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/ai-suggestion"))).toHaveLength(2));
    expect(within(dialog).queryByRole("button", { name: "Send og lag forslag" })).toBeNull();
    expect(calls.filter((c) => c.url.endsWith("/ai-suggestion"))[1].body).toEqual({ confirmed: true, avoid: ["KI-veileder fra Plagiatsjekk"] });

    const approve = within(dialog).getByRole("button", { name: "Godkjenn og gå til neste" });
    await waitFor(() => expect(approve).toBeEnabled(), { timeout: 3000 });
    await userEvent.click(approve);
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(calls.find((c) => c.url.includes("/fix/approve"))?.body).toMatchObject({ ai_suggestion: true });
    expect(calls.filter((c) => c.url.endsWith("/ai-suggestion")), "one request per click – never while typing").toHaveLength(2);
  });

  it("never replaces what the teacher wrote without a click", async () => {
    stub(() => ok("KI-veileder fra Plagiatsjekk"));
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: link.title });
    const field = within(dialog).getByLabelText("Lenketekst");
    await userEvent.type(field, "Min egen tekst");
    await userEvent.click(within(dialog).getByRole("button", { name: "Foreslå lenketekst med KI" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "Send og lag forslag" }));
    expect(await within(dialog).findByText(/«KI-veileder fra Plagiatsjekk»/)).toBeInTheDocument();
    expect(field).toHaveValue("Min egen tekst");
    await userEvent.click(within(dialog).getByRole("button", { name: "Bruk forslaget" }));
    expect(field).toHaveValue("KI-veileder fra Plagiatsjekk");
  });

  it("keeps the field and the manual fix when the service fails or answers unusably", async () => {
    stub(() => ({ status: 502, body: { error: { code: "ai_bad_response", message: "KI-tjenesten ga ikke et brukbart forslag." } } }));
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: link.title });
    const field = within(dialog).getByLabelText("Lenketekst");
    await userEvent.type(field, "Plagiatsjekk");
    await userEvent.click(within(dialog).getByRole("button", { name: "Foreslå lenketekst med KI" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "Send og lag forslag" }));
    expect(await within(dialog).findByText("Fikk ikke noe forslag")).toBeInTheDocument();
    expect(within(dialog).getByText(/Teksten i feltet er uendret, og du kan skrive den selv/)).toBeInTheDocument();
    expect(field).toHaveValue("Plagiatsjekk");
    expect(within(dialog).getByRole("button", { name: "Foreslå lenketekst med KI" })).toBeEnabled();
  });

  it("ignores a late answer that belongs to another finding", async () => {
    stub(() => ({ body: { ...ok("Feil funn").body, finding_id: 99 } }));
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: link.title });
    await userEvent.click(within(dialog).getByRole("button", { name: "Foreslå lenketekst med KI" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "Send og lag forslag" }));
    await new Promise((r) => setTimeout(r, 50));
    expect(within(dialog).getByLabelText("Lenketekst")).toHaveValue("");
  });

  it("without a KI service, explains it and links to the set-up instead of offering a button", () => {
    session.providers = [];
    stub(() => ok("x"));
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: link.title });
    expect(within(dialog).queryByRole("button", { name: "Foreslå lenketekst med KI" })).toBeNull();
    expect(within(dialog).getByRole("link", { name: "Sett opp KI-assistenter" })).toHaveAttribute("href", "/innstillinger/ki-assistenter");
  });
});
