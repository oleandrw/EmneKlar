import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Finding, RuleInfo } from "../../core/api/types";
import { ToastProvider } from "../../design-system";
import { FindingDetail } from "./FindingDetail";

vi.mock("../../core/session", () => ({
  useSession: () => ({
    canvas: { token_configured: true, base_url: "https://canvas.test", identity: null },
    current_course_id: "101",
    ai: { providers_enabled: [], external_allowed: false, confirm_before_send: true },
    flags: {},
    general: { page_size: 25 },
  }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function stubFetch(handler: (url: string) => unknown) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(JSON.stringify(handler(url) ?? {}), { status: 200 });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const GUIDANCE = "Kontroller at lydopptaket har en transkripsjon på siden eller via en tydelig lenke. Teksten skal gjengi tale og andre lyder som er nødvendige for å forstå innholdet.";

const audioRule: RuleInfo = {
  id: "UU-MEDIA-AUDIO-ALT", title: "Kontroller tekstalternativ til lydopptak", category: "media", category_label: "Video og lyd",
  classification: "manual_check", wcag: ["1.2.1"], wcag_titles: { "1.2.1": "Bare lyd og bare video (forhåndsinnspilt)" },
  wcag_version: "2.0", level: "A", testability: "manual", severity: "moderate", explanation: "Forhåndsinnspilte lydopptak …",
  affected_users: "Døve og hørselshemmede.", sources: [], fix_policy: "manual", ruleset_version: "2026.11.2",
  media_kind_choice: true,
  confirmations: [
    { id: "transcript", label: "Transkripsjonen finnes på siden eller via en tydelig lenke", hint: "Bekreft bare når teksten gjengir tale." },
    { id: "media_alternative", label: "Opptaket er et tydelig merket alternativ til tekst på siden", hint: "Gjelder bare når siden sier det tydelig." },
  ],
};

const audio: Finding = {
  id: 21, run_id: 1, course_id: "101", domain: "accessibility", rule_id: "UU-MEDIA-AUDIO-ALT", ruleset_version: "2026.11.2",
  category: "media", classification: "manual_check", test_method: "manual", severity: "moderate", confidence: "medium",
  title: "Kontroller tekstalternativ til lydopptak",
  message: "Lydopptak i Canvas – kontroller at det har et tekstalternativ (transkripsjon).",
  object_type: "page", object_id: "intervju", object_title: "Intervju", object_url: "https://canvas.test/courses/101/pages/intervju",
  location: {}, remediation: GUIDANCE, status: "open", created_at: "2026-11-06T10:00:00+00:00", fix: null,
  evidence: {
    media_key: "media:m-lyd", media_kind: "audio", kind_source: "canvas_media",
    kind_basis: "Canvas oppgir medietypen «audio» for opptaket.",
    text_alternative_candidates: ["Lenke: «Transkripsjon (PDF)»"], media_alternative_hint: null,
  },
  rule: audioRule,
  canvas: { view: "https://canvas.test/courses/101/pages/intervju", edit: null, module_item: null, highlight: null },
};

describe("media findings", () => {
  it("shows an audio check as a manual check with the guidance, the basis and possible transcripts, and confirms it", async () => {
    const calls = stubFetch(() => ({ ...audio, status: "verified" }));
    const onNext = vi.fn();
    render(wrap(<FindingDetail finding={audio} open onClose={() => {}} nav={{ index: 0, total: 2, onNext }} />));
    const dialog = screen.getByRole("dialog", { name: audio.title });
    expect(within(dialog).getByText("Manuell kontroll")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Sannsynlig avvik/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "Slik kontrollerer du" })).toBeInTheDocument();
    expect(within(dialog).getByText(GUIDANCE)).toBeInTheDocument();
    expect(within(dialog).getByText("Lydopptak")).toBeInTheDocument();
    expect(within(dialog).getByText("Canvas oppgir medietypen «audio» for opptaket.")).toBeInTheDocument();
    expect(within(dialog).getByText("Lenke: «Transkripsjon (PDF)»")).toBeInTheDocument();
    expect(within(dialog).getByText(/EmneKlar kan ikke avgjøre det/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("radio", { name: /tydelig merket alternativ/ }));
    await userEvent.type(within(dialog).getByLabelText(/Merknad/), "Innlest versjon av teksten over");
    await userEvent.click(within(dialog).getByRole("button", { name: "Bekreft og merk som kontrollert" }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    const verify = calls.find((c) => c.url.endsWith("/api/findings/21/verify"));
    expect(verify?.body).toEqual({ confirmation: "media_alternative", note: "Innlest versjon av teksten over" });
  });

  it("shows what was confirmed for a verified finding and can reopen it", async () => {
    const calls = stubFetch(() => ({ ...audio, status: "open" }));
    const onClose = vi.fn();
    const verified: Finding = {
      ...audio, status: "verified",
      decision: { decision: "verified", reason: "transcript", note: "Under opptaket", created_at: null,
        label: "Transkripsjonen finnes på siden eller via en tydelig lenke" },
    };
    render(wrap(<FindingDetail finding={verified} open onClose={onClose} />));
    expect(screen.getByText("Status: Kontrollert")).toBeInTheDocument();
    expect(screen.getByText("Transkripsjonen finnes på siden eller via en tydelig lenke")).toBeInTheDocument();
    expect(screen.getByText("Merknad: Under opptaket")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Gjenåpne funnet" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls.some((c) => c.url.endsWith("/api/findings/21/reopen"))).toBe(true);
  });

  it("lets the teacher state the kind of an unknown recording and analyses the page again", async () => {
    const unknown: Finding = {
      ...audio, id: 22, rule_id: "UU-MEDIA-TYPE-UNKNOWN", title: "Kontroller medietype og alternativ",
      message: "Medietypen er ukjent: et videoelement kan også spille av bare lyd.",
      evidence: { media_key: "media:m-ukjent", media_kind: "unknown", kind_source: "none",
        kind_basis: "Canvas oppgir ikke medietypen, og et videoelement kan også spille av bare lyd." },
      rule: { ...audioRule, id: "UU-MEDIA-TYPE-UNKNOWN", confirmations: [] },
    };
    const calls = stubFetch((url) => {
      if (url.endsWith("/media-kind")) return { media_key: "media:m-ukjent", kind: "video_no_audio", reanalyse: { object_type: "page", object_id: "intervju" } };
      if (url.endsWith("/api/analysis")) return { id: "job-9", status: "queued", progress: {} };
      if (url.includes("/api/jobs/job-9")) return { id: "job-9", status: "completed", progress: {} };
      return {};
    });
    render(wrap(<FindingDetail finding={unknown} open onClose={() => {}} />));
    expect(screen.getByText("Ukjent medietype")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bekreft og merk som kontrollert" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Video uten lyd/ }));
    await userEvent.click(screen.getByRole("button", { name: "Lagre og analyser siden på nytt" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/analysis"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/api/findings/22/media-kind"))?.body).toEqual({ kind: "video_no_audio" });
    expect(calls.find((c) => c.url.endsWith("/api/analysis"))?.body).toEqual({
      course_id: "101", scope: "items", domains: ["accessibility"], items: [{ object_type: "page", object_id: "intervju" }],
    });
    expect(await screen.findByText("Siden er analysert på nytt")).toBeInTheDocument();
  });
});

const EXEMPTION = "Lastet opp før 1. februar 2022 – unntaket for eldre dokumenter i forskriften § 4c kan gjelde hvis dokumentet ikke trengs i en aktiv prosess.";
const scanRule: RuleInfo = {
  ...audioRule, id: "UU-DOC-PDF-NO-TEXT", title: "PDF ser ut til å være skannet (ingen tekst)", category: "documents",
  category_label: "Dokumenter", classification: "likely_violation", media_kind_choice: false, ruleset_version: "2026.11.3",
  confirmations: [{ id: "older_document_exemption", label: "Unntaket for eldre dokumenter gjelder",
    hint: "Dokumentet ble lastet opp før 1. februar 2022 og trengs ikke i en aktiv prosess.", requires_evidence: "exemption_hint" }],
};
const scan: Finding = {
  ...audio, id: 31, rule_id: "UU-DOC-PDF-NO-TEXT", category: "documents", classification: "likely_violation", severity: "critical",
  title: "PDF ser ut til å være skannet (ingen tekst)", message: "«HvaErLærerensPfDK.pdf» har ingen lesbar tekst på de første sidene.",
  object_type: "file", object_id: "77", object_title: "HvaErLærerensPfDK.pdf", remediation: "Trengs dokumentet fortsatt? …",
  evidence: { file: "HvaErLærerensPfDK.pdf", format: "pdf", exemption_hint: EXEMPTION }, rule: scanRule,
};

describe("older documents", () => {
  it("offers the exemption only when the upload date allows it, and confirms it with a reason", async () => {
    const calls = stubFetch(() => ({ ...scan, status: "verified" }));
    const onNext = vi.fn();
    render(wrap(<FindingDetail finding={scan} open onClose={() => {}} nav={{ index: 0, total: 2, onNext }} />));
    const dialog = screen.getByRole("dialog", { name: scan.title });
    expect(within(dialog).getByText(EXEMPTION)).toBeInTheDocument();
    expect(within(dialog).getByText(/bekreft under at unntaket gjelder/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("radio", { name: /Unntaket for eldre dokumenter gjelder/ }));
    expect(within(dialog).getByText(/hvorfor dokumentet ikke trengs i emnet nå/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Merknad/), "Arkiv fra 2019, ikke i bruk");
    await userEvent.click(within(dialog).getByRole("button", { name: "Bekreft og merk som kontrollert" }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(calls.find((c) => c.url.endsWith("/api/findings/31/verify"))?.body)
      .toEqual({ confirmation: "older_document_exemption", note: "Arkiv fra 2019, ikke i bruk" });
  });

  it("does not offer the exemption for a newer document", () => {
    stubFetch(() => ({}));
    const newer = { ...scan, evidence: { file: "Ny.pdf", format: "pdf" } };
    render(wrap(<FindingDetail finding={newer} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: scan.title });
    expect(within(dialog).queryByRole("heading", { name: "Bekreft etter kontroll" })).toBeNull();
    expect(within(dialog).getByText("EmneKlar kan ikke rette dette automatisk. Åpne innholdet i Canvas og rett det der.")).toBeInTheDocument();
  });
});
