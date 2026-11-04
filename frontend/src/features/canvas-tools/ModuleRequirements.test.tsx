import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { ModuleRequirements } from "./ModuleRequirements";

vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "104", course: null, loading: false }) }));
vi.mock("../../core/session", () => ({ useSession: () => ({ dry_run: true }) }));
vi.mock("../../core/ui", () => ({ useUi: () => ({ openChanges: vi.fn() }) }));

const OPTIONS = {
  item_types: [{ type: "Page", label: "Sider", default: "must_view", allowed: [{ value: "must_view", label: "Må vises" }] }],
  statuses: {},
};
const PREVIEW = { modules: [], counts: { add: 2 }, warnings: [], changes: 2 };

afterEach(() => vi.unstubAllGlobals());

describe("ModuleRequirements", () => {
  it("waits for the requirement options before a preview can be requested", async () => {
    // The preview is tied to the chosen policy, which comes from the options. A preview requested before they had
    // loaded was made for an empty policy and was never shown.
    let releaseOptions: () => void = () => undefined;
    const optionsLoaded = new Promise<void>((resolve) => { releaseOptions = resolve; });
    const previews: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/module-requirements/options")) {
        await optionsLoaded;
        return new Response(JSON.stringify(OPTIONS), { status: 200 });
      }
      if (url.includes("/module-requirements/preview")) {
        previews.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify(PREVIEW), { status: 200 });
      }
      return new Response(JSON.stringify({ modules: [], partial: false }), { status: 200 });
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider><ModuleRequirements /></ToastProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("button", { name: "Forhåndsvis" })).toBeDisabled();
    expect(screen.getByText("Henter krav per elementtype …")).toBeInTheDocument();

    releaseOptions();
    const button = await screen.findByRole("button", { name: "Forhåndsvis" });
    await vi.waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    expect(await screen.findByRole("heading", { name: "Forhåndsvisning" })).toBeInTheDocument();
    expect(previews).toEqual([expect.objectContaining({ policy: { Page: "must_view" } })]);
  });
});
