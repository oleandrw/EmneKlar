import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { CanvasToolsPage } from "./CanvasToolsPage";

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
        <MemoryRouter initialEntries={["/canvas-verktoy"]}>
          <Routes><Route path="/canvas-verktoy/*" element={children} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const entry = (id: number, action: string, summary: string | null, title: string | null) => ({
  id, timestamp: "2026-11-06T13:05:00+00:00", change_id: id, kind: "page.update_body", object_type: "page",
  object_id: `side-${id}`, object_title: title, action, before: null, after: null, reason: null, api_result: null,
  user_action: "apply", backup_id: null, undo_of: null, undoable: false, undone_by: null, summary,
});

function stubFetch(capabilities: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const data = url.includes("/capabilities")
      ? capabilities
      : url.includes("/api/changelog")
        ? { total: 3, items: [
            entry(3, "apply", "Lenketekst oppdatert", "Pensum og litteratur"),
            entry(2, "conflict", "Alt-tekst oppdatert", "Bildegalleri"),
            entry(1, "apply", null, "Velkommen"),
          ] }
        : {};
    return new Response(JSON.stringify(data), { status: 200 });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Canvas-verktøy", () => {
  it("shows the tools first with descriptive actions and no badges, then an informative history", async () => {
    stubFetch({ capabilities: [{ key: "modules", label: "Moduler", granted: true }, { key: "settings", label: "Innstillinger", granted: true }],
      blueprint: { is_blueprint: true, is_child: false } });
    const { container } = render(wrap(<CanvasToolsPage />));
    expect(screen.getByText("Du forhåndsviser og godkjenner endringer før de publiseres til Canvas.")).toBeInTheDocument();
    expect(screen.queryByText("Slik publiseres endringer")).not.toBeInTheDocument();
    for (const name of ["Sett modulkrav", "Administrer låsing", "Se innstillinger", "Se endringer og sikkerhetskopier",
      "Åpne kunnskapsbasen", "Lag illustrasjoner"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("link", { name: "Åpne" })).not.toBeInTheDocument();
    // The image assistant promises approval before insertion – and names the opt-in exception.
    expect(screen.getByText(/Du godkjenner bildene før de settes inn i Canvas, med mindre du velger «Automatisk innsetting»[.]/))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sikkerhetskopier og endringslogg" })).toBeInTheDocument();
    expect(screen.getByText(/Innholdet lagres lokalt på denne maskinen/)).toBeInTheDocument();
    expect(container.querySelector(".ek-feature-card .ek-badge")).toBeNull();
    // A calm palette: Canvas tools blue, KI tools violet, the change log neutral – no warning colours as decoration.
    const tones = [...container.querySelectorAll(".ek-feature-card .ek-tile")].map((t) => t.getAttribute("data-tone"));
    expect(tones).toEqual(["info", "info", "info", "neutral", "violet", "violet"]);
    expect(screen.queryByText("Blueprint-emne")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Hjelp/ }), "help is in the sidebar, not on the page").toBeNull();

    const history = await screen.findByRole("list", { name: "Siste handlinger" });
    expect(within(history).getByText("Pensum og litteratur")).toBeInTheDocument();
    expect(within(history).getByText("Lenketekst oppdatert · Publisert til Canvas")).toBeInTheDocument();
    expect(within(history).getByText("Konflikt – ikke sendt: Alt-tekst oppdatert")).toBeInTheDocument();
    expect(within(history).getByText("Publisert til Canvas"), "no invented change type when none is recorded").toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Se alle handlinger" })).toBeInTheDocument();
    const firstTool = screen.getByRole("link", { name: "Sett modulkrav" });
    expect(firstTool.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the access and Blueprint limits as plain text", async () => {
    stubFetch({ capabilities: [{ key: "modules", label: "Moduler", granted: false }, { key: "settings", label: "Innstillinger", granted: true }],
      blueprint: { is_blueprint: false, is_child: false } });
    const { container } = render(wrap(<CanvasToolsPage />));
    expect(await screen.findByText("Du mangler tilgang i Canvas til å endre moduler i dette emnet.")).toBeInTheDocument();
    expect(screen.getByText("Ikke tilgjengelig her – emnet er ikke et Blueprint-emne.")).toBeInTheDocument();
    expect(container.querySelector(".ek-feature-card .ek-badge")).toBeNull();
  });
});
