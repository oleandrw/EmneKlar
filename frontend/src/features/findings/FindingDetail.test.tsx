import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { Finding } from "../../core/api/types";
import { ToastProvider } from "../../design-system";
import { FindingDetail } from "./FindingDetail";

vi.mock("../../core/session", () => ({
  useSession: () => ({
    canvas: { token_configured: false, base_url: null, identity: null },
    current_course_id: null,
    ai: { providers_enabled: [], external_allowed: false, confirm_before_send: true },
    flags: {},
  }),
}));

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const base: Finding = {
  id: 1, run_id: 1, domain: "quiz_ai", rule_id: "QZ-AI-KEY", ruleset_version: "2026.10.1", category: "key",
  classification: "should_review", test_method: "ai", severity: "serious", confidence: "medium",
  title: "Fasiten bør kontrolleres (KI-vurdering)", message: "Kildene tyder på at et annet alternativ er riktig.",
  object_type: "quiz_question", object_id: "603", object_title: "Quiz: Spørsmål 3", object_url: null,
  location: {}, remediation: "Kontroller fasiten.", status: "open", created_at: "2026-10-06T19:00:00+00:00",
  evidence: {
    quiz_id: "401", label: "KI-forslag – må vurderes",
    sources: [{ chunk_id: "K1", quote: "PNG støtter gjennomsiktighet", title: "Bildeformater" }],
    answers: [{ text: "Sant", correct: true }, { text: "Usant", correct: false }],
  },
  fix: {
    type: "quiz_question_update", label: "Godkjenn forslag",
    params: { stem: "PNG støtter ikke gjennomsiktighet.", answers: [{ text: "Sant", correct: false }, { text: "Usant", correct: true }], changes_key: true },
  },
};

describe("FindingDetail for AI quiz findings", () => {
  it("shows verified sources, the AI label and a warning when the key would change", () => {
    render(wrap(<FindingDetail finding={base} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: base.title });
    expect(within(dialog).getAllByText("KI-forslag – må vurderes").length).toBeGreaterThan(0);
    expect(within(dialog).getByRole("heading", { name: "Kilder i emnet" })).toBeInTheDocument();
    expect(within(dialog).getByText(/PNG støtter gjennomsiktighet/)).toBeInTheDocument();
    expect(within(dialog).getByText("Forslaget endrer fasiten")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Godkjenn forslag/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "Behold" })).toBeInTheDocument();
  });

  it("lets the teacher edit the suggestion before it is queued", async () => {
    render(wrap(<FindingDetail finding={base} open onClose={() => {}} />));
    await userEvent.click(screen.getByRole("button", { name: "Rediger" }));
    expect(screen.getByLabelText("Spørsmålstekst")).toHaveValue("PNG støtter ikke gjennomsiktighet.");
    expect(screen.getAllByRole("checkbox", { name: "Riktig" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Legg redigert forslag i kø" })).toBeEnabled();
  });
});

describe("FindingDetail for structure suggestions", () => {
  it("uses «Avvis» instead of «Ignorer» and requires a preview before approval", async () => {
    const finding: Finding = {
      ...base, domain: "structure", rule_id: "ST-NAMING", test_method: "heuristic", evidence: {},
      title: "Navnet avviker fra mønsteret", fix: { type: "rename_module", label: "Endre navn", params: { module_id: "203", name: "Modul 3: Video" } },
    };
    render(wrap(<FindingDetail finding={finding} open onClose={() => {}} />));
    expect(screen.getByRole("heading", { name: "Avvis" })).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: /Godkjenn forslag/ });
    expect(approve).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Forhåndsvis" }));
    expect(approve).toBeEnabled();
    expect(screen.getByText("Modul 3: Video")).toBeInTheDocument();
  });
});
