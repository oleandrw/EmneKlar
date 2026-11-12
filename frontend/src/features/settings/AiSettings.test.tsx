import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { AiSettings } from "./AiSettings";

vi.mock("../../core/session", () => ({ useSession: () => ({ flags: { ai_model_discovery: true } }) }));

const KEY = "sk-proj-hemmelig1234567890";

function provider(id: "openai" | "anthropic", overrides: Record<string, unknown> = {}) {
  return {
    id, type: id, name: id === "openai" ? "OpenAI" : "Anthropic", enabled: false,
    endpoint: id === "openai" ? "https://api.openai.com/v1" : "https://api.anthropic.com", api_version: null,
    last_status: "unknown", last_message: null, last_checked_at: null, key_configured: false, local: false,
    data_leaves_machine: true, needs_key: true, models_stale: false,
    key_page: id === "openai" ? "https://platform.openai.com/api-keys" : "https://platform.claude.com/settings/keys",
    ...overrides,
  };
}

interface Call { method: string; url: string; body: unknown }

function renderSettings(initial: ReturnType<typeof provider>[], answer: (call: Call) => Response | Promise<Response> | null) {
  let providers = initial;
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    if (call.method !== "GET") calls.push(call);
    const custom = await answer(call);
    if (custom) {
      if (custom.ok && call.url.endsWith("/connect")) {
        const updated = (await custom.clone().json()) as ReturnType<typeof provider>;
        providers = providers.map((p) => (p.id === updated.id ? updated : p));
      }
      return custom;
    }
    if (url.endsWith("/key") && call.method === "DELETE") {
      providers = providers.map((p) => (url.includes(`/${p.id}/`) ? { ...p, key_configured: false, enabled: false, last_status: "unknown" } : p));
      return Response.json({ ok: true });
    }
    if (url.startsWith("/api/ai/providers")) {
      return Response.json({ providers, unavailable_reason: null, privacy: { allow_external_ai: true } });
    }
    if (url.startsWith("/api/ai/models")) return Response.json({ models: [], catalog_version: "1", catalog_note: "" });
    if (url.startsWith("/api/ai/routing")) return Response.json({ strategy: "auto", strategies: [], tasks: [] });
    if (url.startsWith("/api/ai/usage")) return Response.json({ items: [] });
    return Response.json({});
  }));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ToastProvider><AiSettings /></ToastProvider></MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

const card = async (name: string) => (await screen.findByRole("heading", { name, level: 3 })).closest(".ek-card") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

describe("KI-assistenter: «Koble til»", () => {
  it("shows one compact layout for OpenAI and Anthropic: switch, key field, «Koble til» and a link to the provider's key page", async () => {
    renderSettings([provider("openai"), provider("anthropic")], () => null);
    for (const [name, href] of [["OpenAI", "https://platform.openai.com/api-keys"], ["Anthropic", "https://platform.claude.com/settings/keys"]]) {
      const box = await card(name);
      expect(within(box).getByRole("switch", { name: `Bruk ${name}` })).toBeInTheDocument();
      expect(within(box).getByLabelText("API-nøkkel")).toHaveAttribute("type", "password");
      expect(within(box).getByRole("button", { name: "Koble til" })).toBeInTheDocument();
      const link = within(box).getByRole("link", { name: new RegExp(`^Finn eller lag en API-nøkkel hos ${name}`) });
      expect(link).toHaveAttribute("href", href);
      expect(link).toHaveAttribute("target", "_blank");
      expect(within(box).getByText("Ikke tilkoblet")).toBeInTheDocument();
      for (const gone of ["Lagre", "Test tilkobling", "Hent modelliste"]) {
        expect(within(box).queryByRole("button", { name: gone }), `${gone} is replaced by «Koble til»`).toBeNull();
      }
      expect(within(box).queryByLabelText("Endepunkt"), "the endpoint is under «Avansert»").toBeNull();
    }
  });

  it("shows «Kobler til …» while checking, blocks a second click, and then shows the stored key with «Bytt nøkkel» and «Fjern»", async () => {
    let release: () => void = () => undefined;
    const calls = renderSettings([provider("openai")], (call) => (call.url.endsWith("/connect")
      ? new Promise<Response>((resolve) => {
        release = () => resolve(Response.json(provider("openai", {
          key_configured: true, enabled: true, last_status: "ok", last_message: "Tilkoblet.", last_checked_at: "2026-11-12T10:00:00Z" })));
      })
      : null));
    const user = userEvent.setup();
    const box = await card("OpenAI");
    await user.type(within(box).getByLabelText("API-nøkkel"), KEY);
    await user.click(within(box).getByRole("button", { name: "Koble til" }));
    const busy = within(box).getByRole("button", { name: "Kobler til …" });
    expect(busy).toBeDisabled();
    await user.click(busy);
    expect(calls.filter((c) => c.url.endsWith("/connect")), "one request, however many clicks").toEqual([
      { method: "POST", url: "/api/ai/providers/openai/connect", body: { api_key: KEY } }]);
    release();
    expect(await within(box).findByText("Nøkkel lagret sikkert")).toBeInTheDocument();
    expect(within(box).getByText("Tilkoblet")).toBeInTheDocument();
    expect(within(box).queryByLabelText("API-nøkkel"), "the field is hidden once connected").toBeNull();
    expect(within(box).getByRole("button", { name: "Bytt nøkkel" })).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "Fjern nøkkelen til OpenAI" })).toBeInTheDocument();
    expect(box.textContent).not.toContain(KEY);
    expect(box.textContent, "no model count and no repeated status").not.toMatch(/modeller|Tilkoblet\./);
    expect(box.querySelector(".ek-alert"), "no green confirmation box").toBeNull();
  });

  it("explains a rejected key, keeps the field, and «Bytt nøkkel» can be cancelled", async () => {
    renderSettings([provider("openai", { key_configured: true, enabled: true, last_status: "ok" })], (call) => (call.url.endsWith("/connect")
      ? Response.json({ error: { code: "ai_key_invalid", message: "OpenAI avviste nøkkelen. Den lagrede nøkkelen er beholdt." } }, { status: 400 })
      : null));
    const user = userEvent.setup();
    const box = await card("OpenAI");
    await user.click(within(box).getByRole("button", { name: "Bytt nøkkel" }));
    const field = within(box).getByLabelText("API-nøkkel");
    await waitFor(() => expect(field).toHaveFocus());
    await user.type(field, "sk-proj-feilnokkel1234567890");
    await user.click(within(box).getByRole("button", { name: "Koble til" }));
    expect(await within(box).findByRole("alert")).toHaveTextContent("OpenAI avviste nøkkelen. Den lagrede nøkkelen er beholdt.");
    expect(within(box).getByLabelText("API-nøkkel")).toHaveValue("sk-proj-feilnokkel1234567890");
    await user.click(within(box).getByRole("button", { name: "Avbryt" }));
    expect(within(box).getByText("Nøkkel lagret sikkert")).toBeInTheDocument();
    await waitFor(() => expect(within(box).getByRole("button", { name: "Bytt nøkkel" })).toHaveFocus());
  });

  it("keeps the endpoint and a manual check under «Avansert», and «Fjern» removes the key", async () => {
    const calls = renderSettings([provider("openai", { key_configured: true, enabled: true, last_status: "ok" })], (call) => (
      call.url.endsWith("/connect") ? Response.json(provider("openai", { key_configured: true, enabled: true, last_status: "ok" })) : null));
    const user = userEvent.setup();
    const box = await card("OpenAI");
    await user.click(within(box).getByRole("button", { name: "Avansert" }));
    expect(within(box).getByLabelText("Endepunkt")).toHaveValue("https://api.openai.com/v1");
    await user.click(within(box).getByRole("button", { name: "Kontroller tilkoblingen" }));
    await waitFor(() => expect(calls).toContainEqual({ method: "POST", url: "/api/ai/providers/openai/connect", body: {} }));
    await user.click(within(box).getByRole("button", { name: "Fjern nøkkelen til OpenAI" }));
    expect(await within(box).findByRole("button", { name: "Koble til" })).toBeInTheDocument();
    expect(within(box).getByText("Ikke tilkoblet")).toBeInTheDocument();
  });

  it("shows a failed check once, as the card's status", async () => {
    renderSettings([provider("anthropic", { key_configured: true, enabled: true, last_status: "error",
      last_message: "Anthropic avviste nøkkelen. Kontroller at hele nøkkelen er kopiert." })], () => null);
    const box = await card("Anthropic");
    expect(within(box).getByText("Feil")).toBeInTheDocument();
    expect(within(box).getAllByText(/Anthropic avviste nøkkelen/)).toHaveLength(1);
  });

  it("fetches an old model list again in the background, once", async () => {
    const calls = renderSettings([provider("openai", { key_configured: true, enabled: true, last_status: "ok", models_stale: true })],
      (call) => (call.url.endsWith("/refresh-models") ? Response.json({ refreshed: true, added: 0 }) : null));
    const box = await card("OpenAI");
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/refresh-models"))).toHaveLength(1));
    expect(within(box).queryByText(/modell/i), "nothing about it on the card").toBeNull();
  });
});
