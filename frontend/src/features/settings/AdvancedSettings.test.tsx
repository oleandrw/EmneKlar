import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import type { AppSettings } from "./api";
import { AdvancedSettings, sameRepository } from "./OtherSections";

const settings = {
  advanced: { feature_flags: {}, update_repository: null, update_channel: "stable", check_updates: true, debug_logging: false },
} as unknown as AppSettings;

const status = {
  current_version: "0.1.0", install: { type: "git", label: "Git", path: "C:/x", branch: "main", can_start_from_app: false },
  repository: "oleandrw/EmneKlar", default_repository: "oleandrw/EmneKlar", default_repository_source: "Git-remote origin",
  repository_is_custom: false, channel: "stable", check_enabled: true, last_checked_at: null, last_error: null,
  latest: null, update_available: false, is_major: false, checking: false, changelog: [],
};

function renderAdvanced() {
  const patches: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/updates/status")) return new Response(JSON.stringify(status), { status: 200 });
    if (init?.method === "PATCH") {
      patches.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ settings, flags: [] }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ToastProvider><AdvancedSettings settings={settings} flags={[]} /></ToastProvider></MemoryRouter>
    </QueryClientProvider>,
  );
  return patches;
}

afterEach(() => vi.unstubAllGlobals());

describe("update source", () => {
  it("shows the standard source, and another repository needs a deliberate confirmation before it is saved", async () => {
    const patches = renderAdvanced();
    const user = userEvent.setup();
    const field = screen.getByLabelText("GitHub-repository for oppdateringer");
    expect(await screen.findByText("oleandrw/EmneKlar")).toBeInTheDocument();
    expect(field).toHaveAccessibleDescription(/Standardkilde: oleandrw\/EmneKlar \(fra Git-remote origin\)\. La feltet stå tomt for å bruke standardkilden\./);

    await user.type(field, "fremmed/EmneKlar");
    expect(screen.getByText("Et annet repository betyr en annen kilde for oppdateringer")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Lagre" });
    expect(save, "not without confirming").toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Ja, jeg vil hente oppdateringer fra fremmed/EmneKlar" }));
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(patches).toEqual([expect.objectContaining({
      update_repository: "fremmed/EmneKlar", confirm_update_repository: true })]));
  });

  it("an empty field (the standard source) or the standard source itself needs no confirmation", async () => {
    renderAdvanced();
    const user = userEvent.setup();
    const field = screen.getByLabelText("GitHub-repository for oppdateringer");
    await screen.findByText("oleandrw/EmneKlar");
    await user.type(field, "oleandrw/EmneKlar");
    expect(screen.queryByText("Et annet repository betyr en annen kilde for oppdateringer")).toBeNull();
    expect(screen.getByRole("button", { name: "Lagre" })).toBeEnabled();
    await user.clear(field);
    expect(screen.queryByRole("checkbox", { name: /Ja, jeg vil hente/ })).toBeNull();
  });

  it("treats the standard source in other letters as the standard source – another repository still needs confirming", async () => {
    const patches = renderAdvanced();
    const user = userEvent.setup();
    const field = screen.getByLabelText("GitHub-repository for oppdateringer");
    await screen.findByText("oleandrw/EmneKlar");
    await user.type(field, "Oleandrw/emneklar");
    expect(screen.queryByText("Et annet repository betyr en annen kilde for oppdateringer")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Lagre" }));
    await waitFor(() => expect(patches).toEqual([expect.objectContaining({ update_repository: "Oleandrw/emneklar" })]));
    expect(patches[0], "nothing to confirm").not.toHaveProperty("confirm_update_repository");
    await user.clear(field);
    await user.type(field, "fremmed/emneklar");
    expect(screen.getByText("Et annet repository betyr en annen kilde for oppdateringer")).toBeInTheDocument();
    expect(sameRepository("oleandrw/EmneKlar", " OLEANDRW/emneklar ")).toBe(true);
    expect(sameRepository("oleandrw/EmneKlar", "fremmed/EmneKlar")).toBe(false);
    expect(sameRepository("", null)).toBe(false);
  });
});
