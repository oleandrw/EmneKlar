import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../../design-system";
import { AnalyseStep } from "./AnalyseStep";
import { DEFAULT_SCOPE, type Catalog, type Estimate, type Illustration, type IllustrationSettings, type RunDetail, type Scope, type ScopeIndex, type Status } from "./api";
import { ImageSettingsStep } from "./ImageSettingsStep";
import { ReviewStep } from "./ReviewStep";
import { ScopeStep } from "./ScopeStep";

async function axeViolations(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function mockApi(routes: Record<string, unknown>) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: key ? 200 : 404 });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const settings: IllustrationSettings = {
  quality_profile: "max", amount: "balanced", analysis_model: "", planning_model: "", review_model: "", image_provider_id: "openai",
  image_model: "", image_quality: "", image_format: "auto", use_reference_images: true, captions: true, folder: "EmneKlar-illustrasjoner",
  cost_limit_usd: null, concurrency: 2, text_in_images: "auto", credit: true, credit_text: "KI-generert illustrasjon", max_width_px: 900,
};

const catalog: Catalog = {
  styles: [{ key: "modern_3d", label: "Moderne 3D-illustrasjoner", description: "" }, { key: "academic", label: "Akademiske illustrasjoner", description: "" }],
  quality_profiles: [
    { id: "max", label: "Maksimal kvalitet", description: "Mest avanserte modeller.", default: true, review_rounds: 2 },
    { id: "balanced", label: "Balansert", description: "Balanse.", default: false, review_rounds: 1 },
    { id: "fast", label: "Rask", description: "Raskere.", default: false, review_rounds: 0 },
  ],
  roles: { illustration_analysis: "Innholdsanalyse", illustration_planning: "Bildeplan", illustration_review: "Kvalitetskontroll" },
  image_models: [], placements: { after_explanation: "Etter den faglige forklaringen" }, amounts: { low: "Lav", balanced: "Balansert", high: "Høy" },
  statuses: {}, usage_rights: [{ id: "own_copyright", label: "Jeg har opphavsretten" }],
  formats: { auto: "Automatisk (anbefalt)", "16:9": "Bred 16:9", "3:2": "Liggende 3:2", "4:3": "Liggende 4:3", "1:1": "Kvadratisk 1:1", "2:3": "Stående 2:3" },
  image_types: { diagram: "Diagram" },
  pricing: { version: "2026-11-04", currency: "USD", note: "Veiledende priser." },
};

const index: ScopeIndex = {
  modules: [
    { id: "201", name: "Modul 1 – Introduksjon", items_count: 3, pages: [{ page_url: "velkommen", title: "Velkommen" }], other_items: 2, published: true },
    { id: "202", name: "Modul 2 – Læring og teknologi", items_count: 4, pages: [{ page_url: "a", title: "A" }, { page_url: "b", title: "B" }], other_items: 2, published: true },
  ],
  pages: [{ url: "velkommen", title: "Velkommen", published: true, in_module: true, front_page: false }],
};

const model = (ref: string, name: string) => ({ provider_id: ref.split("/")[0], model_id: ref.split("/")[1], display_name: name, ref });

const status: Status = {
  settings,
  choices: {
    profile: { id: "max", label: "Maksimal kvalitet", description: "", review_rounds: 2 },
    roles: {
      illustration_analysis: { role: "illustration_analysis", label: "Innholdsanalyse", primary: model("anthropic/claude-fable-5-1", "Claude Fable 5.1"), fallbacks: [], reason: "Kvalitetsprofilen «Maksimal kvalitet»." },
      illustration_planning: { role: "illustration_planning", label: "Bildeplan", primary: model("anthropic/claude-opus-5-5", "Claude Opus 5.5"), fallbacks: [], reason: "" },
      illustration_review: { role: "illustration_review", label: "Kvalitetskontroll", primary: model("openai/gpt-6-astra", "GPT-6 Astra"), fallbacks: [], reason: "" },
    },
    image: { provider_id: "openai", model: { id: "gpt-image-2.5-sunburst", label: "GPT-Image-2.5 Sunburst", provider_type: "openai", description: "", reference_images: true, qualities: ["high"], sizes: [], default: true, known: true },
      quality: "high", size: "1536x1024", reason: "Kvalitetsprofilen.", available: true, unavailable_reason: null },
  },
  ai: { available: true, reason: null, external_allowed: true, confirm_before_send: true },
  image_providers: [{ id: "openai", name: "OpenAI", type: "openai", configured: true, models: [], needs_model_name: false }],
  design: null, design_versions: [], runs: [], busy_job: null, dry_run: false,
  text_models: [{ ref: "anthropic/claude-opus-5-5", display_name: "Claude Opus 5.5", provider_id: "anthropic", vision: true }],
};

describe("ScopeStep", () => {
  it("offers the four scopes and selects several modules with checkboxes", async () => {
    const user = userEvent.setup();
    const changes: Scope[] = [];
    function Harness() {
      const [scope, setScope] = useState<Scope>(DEFAULT_SCOPE);
      return <ScopeStep scope={scope} onChange={(s) => { changes.push(s); setScope(s); }} index={index} loading={false} error={null} />;
    }
    const { container } = render(wrap(<Harness />));
    for (const label of ["Hele emnet", "Én modul", "Flere moduler", "Én side"]) {
      expect(screen.getByRole("radio", { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(screen.getByRole("radio", { name: /Hele emnet/ })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /Flere moduler/ }));
    await user.click(screen.getByRole("checkbox", { name: /Modul 1 – Introduksjon/ }));
    await user.click(screen.getByRole("checkbox", { name: /Modul 2 – Læring og teknologi/ }));
    expect(changes.at(-1)).toMatchObject({ type: "modules", module_ids: ["201", "202"] });
    expect(screen.getAllByText(/2 andre elementer \(brukes som kontekst\)/)).toHaveLength(2);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("ImageSettingsStep", () => {
  it("shows quality, amount and design up front and keeps model names and costs under «Avanserte innstillinger»", async () => {
    const user = userEvent.setup();
    mockApi({ "/illustrations/assets": { items: [] } });
    const { container } = render(wrap(<ImageSettingsStep courseId="101" settings={settings} onChange={() => {}} status={status} catalog={catalog} />));
    expect(screen.getByRole("heading", { name: "2. Bildeinnstillinger" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Maksimal kvalitet \(standard\)/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Balansert \(standard\)/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Moderne 3D-illustrasjoner/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Korte etiketter i diagrammer/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Merk bildene med «KI-generert illustrasjon»/ })).toBeChecked();
    expect(screen.queryByText(/Claude Fable 5.1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Kostnadsgrense/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Avanserte innstillinger" }));
    expect(screen.getByText(/Claude Fable 5.1/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Maksimal visningsbredde/)).toHaveValue(900);
    expect(screen.getByLabelText(/^Bildeformat/)).toHaveValue("auto");
    expect(await axeViolations(container)).toEqual([]);
  });
});

const estimate: Estimate = {
  available: true, reason: null,
  stats: { modules_in_scope: 2, pages_in_scope: 3, pages_in_several_modules: 1, unpublished_pages: 0, non_page_items: 4, skipped: 0 },
  skipped: [], limitations: ["Bare Canvas-sider kan få illustrasjoner."],
  estimate: { currency: "USD", lines: [{ key: "images", label: "Bildegenerering", calls_low: 2, calls_high: 5, cost_low: 0.4, cost_high: 1.1 }],
    total_low: 0.9, total_high: 2.4, images_low: 2, images_high: 5, unpriced: [], cached_pages: 0, note: "Ikke en garantert pris." },
  payload_summary: "Dette sendes …",
  payload_short: "Undervisningsinnholdet i omfanget sendes til Anthropic og OpenAI for analyse, bildegenerering og kvalitetskontroll.",
  providers: ["Anthropic", "OpenAI"],
  receivers: [{ role: "Innholdsanalyse", service: "Claude Fable 5.1 (Anthropic)", content: "Teksten på 3 side(r)." },
    { role: "Bildegenerering", service: "GPT-Image-2.5 Sunburst (OpenAI)", content: "Bildeprompter." }],
  external: true, needs_confirmation: true, usage_rights_required: false, pages: [],
};

describe("AnalyseStep", () => {
  it("shows a short summary of what is sent, hides models and costs, and starts the analysis after consent", async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      "/illustrations/estimate": estimate,
      "/illustrations/runs": { run: { id: 7 }, job: { id: "job-1", status: "running", progress: { phase_label: "Kartlegger", types: {}, messages: [], eta: { state: "calculating" }, findings: {} } } },
      "/api/jobs/job-1": { id: "job-1", status: "running", progress: { phase: "inventory", phase_label: "Kartlegger emnet", phase_index: 1, phase_count: 4, determinate: false, percent: null, done: 0, total: 0, types: {}, current_item: null, current_operation: null, findings: {}, eta: { state: "calculating" }, in_flight: 0, messages: [] } },
    });
    const started = vi.fn();
    render(wrap(<AnalyseStep courseId="101" scope={{ ...DEFAULT_SCOPE, type: "modules", module_ids: ["201", "202"] }} settings={settings}
      catalog={catalog} busyJobId={null} runId={null} onStarted={started} onDone={() => {}} onNext={() => {}} />));
    await user.click(screen.getByRole("button", { name: /Kartlegg innholdet/ }));
    expect(await screen.findByText(/sendes til Anthropic og OpenAI/)).toBeInTheDocument();
    expect(screen.queryByText(/Claude Fable 5.1 \(Anthropic\)/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Avanserte innstillinger: modeller og kostnadsanslag/ }));
    expect(screen.getByText(/Claude Fable 5.1 \(Anthropic\)/)).toBeInTheDocument();
    expect(screen.getByText(/Totalt anslått/)).toHaveTextContent("0,90 USD – 2,40 USD");
    const start = screen.getByRole("button", { name: "Analyser og foreslå bilder" });
    expect(start).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Jeg godkjenner/ }));
    await user.click(start);
    await waitFor(() => expect(started).toHaveBeenCalled());
    const run = calls.find((c) => c.url.includes("/illustrations/runs"))!;
    expect(run.body).toMatchObject({ mode: "plan", auto_insert: false, confirmed: true, scope: { type: "modules", module_ids: ["201", "202"] } });
  });
});

const ill = (id: number, page: string, status: string, extra: Partial<Illustration> = {}): Illustration => ({
  id, run_id: 3, status, status_label: status === "generated" ? "Klar til gjennomgang" : status, module_id: "201", module_name: "Modul 1 – Introduksjon",
  page_url: page, page_title: page, section: { section_id: "s1", title: "Samarbeid", text: "Tekst", before: { title: "", text: "" }, after: { title: "", text: "" } },
  anchor: { placement: "after_explanation", placement_label: "Etter den faglige forklaringen", section_id: "s1", section_title: "Samarbeid", block_index: 2, block_text: "", warning: null },
  placement_label: "Etter den faglige forklaringen", plan: { concept: `Begrep ${id}` }, prompt: "p", style_override: null, asset_id: "a",
  image_url: "/api/illustrations/assets/a", thumb_url: "/api/illustrations/assets/a?size=thumb", versions: [], review: { verdict: "pass" },
  alt_text: "Fire studenter", decorative: false, caption: "Samarbeid", caption_enabled: true, change_id: null, published: {}, error: null,
  aspect_ratio: "3:2", image_type: "illustration", labels: [], credit: "KI-generert illustrasjon",
  manual_check: false, ai_label: "KI-forslag – må vurderes", ...extra,
});

describe("ReviewStep", () => {
  it("shows the course overview per module and page and approves all images on a page", async () => {
    const user = userEvent.setup();
    const items = [ill(1, "Side 1", "generated"), ill(2, "Side 1", "flagged", { manual_check: true }), ill(3, "Side 2", "generated")];
    const detail: RunDetail = {
      run: { id: 3, course_id: "101", status: "review", status_label: "Klar til gjennomgang", scope: DEFAULT_SCOPE,
        options: { mode: "full", settings, auto_insert: false }, stats: {}, usage: { cost_usd: 1.25, calls: 12, currency: "USD" },
        limitations: [], error: null, job_id: null, created_at: null },
      illustrations: items, counts: { generated: 2, flagged: 1 }, job: null, can_continue: false,
      overview: [{ module_id: "201", name: "Modul 1 – Introduksjon", proposed: 3, pages: [
        { page_url: "Side 1", title: "Side 1", status: "planned", reason: null, summary: null, illustrations: items.slice(0, 2), proposed: 2 },
        { page_url: "Side 2", title: "Side 2", status: "planned", reason: null, summary: null, illustrations: items.slice(2), proposed: 1 },
        { page_url: "Side 3", title: "Side 3", status: "planned", reason: "Siden har ikke naturlig behov.", summary: null, illustrations: [], proposed: 0 },
      ] }],
    };
    const calls = mockApi({ "/illustrations/runs/3": detail, "/illustrations/bulk": { changed: [1, 2], missing_alt_text: [] } });
    const { container } = render(wrap(<ReviewStep runId={3} catalog={catalog} onPublish={() => {}} />));
    expect(await screen.findByRole("heading", { name: "Modul 1 – Introduksjon" })).toBeInTheDocument();
    expect(screen.getByText("2 foreslåtte bilder")).toBeInTheDocument();
    expect(screen.getByText("1 foreslått bilde")).toBeInTheDocument();
    expect(screen.getByText(/Ingen bilder nødvendig/)).toBeInTheDocument();
    expect(screen.getByText("Manuell kontroll")).toBeInTheDocument();
    const page1 = screen.getByRole("region", { name: "Side 1" });
    await user.click(within(page1).getByRole("button", { name: "Godkjenn alle på siden" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/illustrations/bulk"))).toBe(true));
    expect(calls.find((c) => c.url.includes("/illustrations/bulk"))!.body).toEqual({ run_id: 3, level: "page", page_url: "Side 1" });
    expect(await axeViolations(container)).toEqual([]);
  });
});
