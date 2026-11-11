import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { onAppStopped, QuitDialog } from "./quit";
import { SessionProvider } from "./session";

const SESSION = {
  csrf_token: "csrf", app: { name: "EmneKlar", version: "0.2.0" }, setup_completed: true, current_course_id: null,
  canvas: { base_url: null, token_configured: false, identity: null },
  general: { theme: "light" }, appearance: { text_size: "normal", density: "normal", reduce_motion: "system", underline_links: false },
  notifications: {}, flags: {}, ai: { external_allowed: false, confirm_before_send: true, providers_enabled: [] },
  regulatory_profile: "no", analysis: { default_domains: [] },
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** `shutdown` answers the quit requests in turn; every request body is recorded. */
function mockApi(shutdown: Response[]) {
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/api/system/shutdown")) {
      bodies.push(JSON.parse(String(init?.body)));
      return shutdown.shift() ?? new Response("{}", { status: 500 });
    }
    return new Response(JSON.stringify(SESSION), { status: 200 });
  }));
  return bodies;
}

const ok = () => new Response(JSON.stringify({ ok: true }), { status: 200 });
const jobsRunning = () => new Response(JSON.stringify({ error: { code: "jobs_running", extra: { jobs: 2 },
  message: "2 jobb(er) kjører fortsatt. De blir avbrutt hvis du avslutter nå." } }), { status: 409 });

afterEach(() => vi.unstubAllGlobals());

describe("Avslutt EmneKlar", () => {
  it("asks first, stops the program and says that it has stopped", async () => {
    const user = userEvent.setup();
    const bodies = mockApi([ok()]);
    const { container } = render(wrap(<SessionProvider><QuitDialog open onClose={() => {}} /></SessionProvider>));
    const dialog = await screen.findByRole("dialog", { name: "Avslutte EmneKlar?" });
    expect(dialog).toHaveTextContent("Du starter programmet igjen fra Start-menyen eller skrivebordet");
    expect(dialog).toHaveTextContent("ingenting endres i Canvas");
    expect(screen.getByRole("button", { name: "Avbryt" })).toHaveFocus();
    expect(await axe.run(container).then((r) => r.violations.map((v) => v.id))).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Avslutt EmneKlar" }));
    expect(await screen.findByRole("heading", { name: "EmneKlar er avsluttet" })).toBeInTheDocument();
    expect(screen.getByText(/du kan lukke denne fanen/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(bodies).toEqual([{ force: false }]);
    // The page that replaces the app does not send the user to a file they may never have seen.
    expect(document.body.textContent).not.toMatch(/start\.bat/);
  });

  it("warns when jobs are running and stops only after «Avslutt likevel»", async () => {
    const user = userEvent.setup();
    const bodies = mockApi([jobsRunning(), ok()]);
    const stopped = vi.fn();
    const off = onAppStopped(stopped);
    render(wrap(<QuitDialog open onClose={() => {}} />));
    await user.click(screen.getByRole("button", { name: "Avslutt EmneKlar" }));
    expect(await screen.findByText(/2 jobb\(er\) kjører fortsatt/)).toBeInTheDocument();
    expect(stopped).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Avslutt EmneKlar" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Avslutt likevel" }));
    await waitFor(() => expect(stopped).toHaveBeenCalledTimes(1));
    expect(bodies).toEqual([{ force: false }, { force: true }]);
    off();
  });

  it("shows another failure and lets the user close the dialog", async () => {
    const user = userEvent.setup();
    mockApi([new Response(JSON.stringify({ error: { code: "unsupported",
      message: "Denne instansen av EmneKlar kan ikke avsluttes herfra." } }), { status: 409 })]);
    const onClose = vi.fn();
    render(wrap(<QuitDialog open onClose={onClose} />));
    await user.click(screen.getByRole("button", { name: "Avslutt EmneKlar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("kan ikke avsluttes herfra");
    await user.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(onClose).toHaveBeenCalled();
  });
});
