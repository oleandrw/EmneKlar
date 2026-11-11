import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { HelpPage } from "./HelpPage";

vi.mock("../../core/session", () => ({
  useSession: () => ({ app: { version: "0.1.0" }, canvas: { token_configured: true }, ai: { providers_enabled: [] }, flags: {} }),
}));

afterEach(() => vi.unstubAllGlobals());

function renderHelp(topic: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/hjelp/${topic}`]}>
          <Routes><Route path="/hjelp/:topic" element={<HelpPage />} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Hjelp → Feilsøking", () => {
  it("explains how an installed EmneKlar is started and stopped – without assuming start.bat or a console window", async () => {
    const user = userEvent.setup();
    const { container } = renderHelp("feilsoking");
    for (const question of ["«Økten er ikke gyldig»", "Hvordan avslutter jeg EmneKlar?",
      "EmneKlar starter ikke, eller vinduet åpnes ikke"]) {
      await user.click(screen.getByText(question));  // the answers are folded until they are asked for
    }
    expect(container).toHaveTextContent("Når det siste EmneKlar-vinduet er lukket, avsluttes programmet etter noen sekunder");
    expect(container).toHaveTextContent("velger du «Avslutt EmneKlar» i kontomenyen");
    expect(container).toHaveTextContent("Start EmneKlar på nytt fra Start-menyen eller skrivebordet");
    expect(container).toHaveTextContent("kjører du installasjonsprogrammet på nytt – dataene og innstillingene dine beholdes");
    expect(container.textContent).not.toMatch(/start\.bat|setup\.bat|EmneKlar-Claude|vinduet til EmneKlar/);
  });
});

describe("Hjelp → Vanlige spørsmål", () => {
  it("answers how EmneKlar is installed, updated and removed – without Python and without losing data", async () => {
    const user = userEvent.setup();
    const { container } = renderHelp("vanlige-sporsmal");
    for (const question of ["Må jeg installere Python eller andre programmer?", "Hvordan avinstallerer jeg EmneKlar?",
      "Hva skjer når jeg oppdaterer EmneKlar?"]) {
      await user.click(screen.getByText(question));
    }
    expect(container).toHaveTextContent("Installasjonsprogrammet har med alt EmneKlar trenger");
    expect(container).toHaveTextContent("trenger ikke administratorrettigheter");
    expect(container).toHaveTextContent("Innstillinger → Apper → Installerte apper");
    expect(container).toHaveTextContent("Dataene dine i %LOCALAPPDATA%\\EmneKlar blir liggende");
    expect(container).toHaveTextContent("Du starter oppdateringen under Innstillinger → Generelt");
    expect(container.textContent).not.toMatch(/setup\.bat|start\.bat|EmneKlar-Claude/);
  });
});

describe("Hjelp → Brukerveiledninger (kunnskapsbasen)", () => {
  it("does not tell anyone to install local models", () => {
    const { container } = renderHelp("brukerveiledninger");
    expect(container).toHaveTextContent("Lokale modeller følger ikke med EmneKlar");
    expect(container.textContent).not.toMatch(/setup\.bat|svar «j»/);
  });
});

describe("Hjelp → Brukerveiledninger", () => {
  it("names «Automatisk innsetting» wherever it promises approval before insertion", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/hjelp/brukerveiledninger"]}>
            <Routes><Route path="/hjelp/:topic" element={<HelpPage />} /></Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    const publish = screen.getByText(/^bare godkjente bilder lastes opp/).closest("p")!;
    expect(publish).toHaveTextContent(/med mindre du har valgt Automatisk innsetting i steg 3/);
    expect(publish).toHaveTextContent(/bilder som må kontrolleres, venter alltid på deg/);
    expect(screen.getByText(/Det eneste unntaket er «Automatisk innsetting» i KI-bildeassistenten/)).toBeInTheDocument();
    expect(screen.getByText(/er det kjøringen som godkjenner bildene som består kvalitetskontrollen/)).toBeInTheDocument();
  });
});
