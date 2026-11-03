import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../../design-system";
import { DEFAULT_OPTIONS, type Estimate, type Hit, type RagStatus, type SearchResult } from "./api";
import { AnswerText, AskPanel } from "./AskPanel";
import { BuildPanel } from "./BuildPanel";

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
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: key ? 200 : 404 });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const hit = (id: string, citation: string, extra: Partial<Hit> = {}): Hit => ({
  id, chunk_id: Number(id.slice(1)), type: "text", item_kind: "page", title: "Raster og vektor", heading_path: ["Rasterbilder"],
  module: "Modul 1", url: "https://canvas.test/courses/104/pages/raster", page: null, page_end: null, start: null, end: null,
  citation, snippet: "Et rasterbilde er bygd opp av piksler.", text: "Et rasterbilde er bygd opp av piksler.", rank: 1,
  ...extra,
});

const status = (partial: Partial<RagStatus> = {}): RagStatus => ({
  index: null, stats: { chunks: 12, chunk_types: { text: 10, table: 2 }, items: { page: 3 }, item_status: { done: 3 },
    vectors: 12, tokens: 2000, video_minutes: 0, keyword_engine: "fts5" },
  modules: [{ id: "301", name: "Modul 1 – Grunnlag" }], error: null, index_embedding: "local:BAAI/bge-m3",
  model_mismatch: false,
  embedding: { available: true, label: "BGE-M3", reason: null, needs_download: false, download_mb: 0 },
  reranker: { available: true, label: "BGE reranker", reason: null, needs_download: false, download_mb: 0 },
  device: "cpu",
  local: { installed: { embedding: true, reranker: true, whisper: true, youtube: false }, device: "cpu", cuda: false,
    models_dir: "C:\\data\\models", models: [] },
  ai: { available: false, reason: "Ingen KI-leverandør er satt opp." }, busy_job: null,
  settings: { embedding_backend: "local", embedding_model: "", embedding_provider_id: "local", embedding_provider_model: "",
    reranker_enabled: true, reranker_model: "", device: "auto", whisper_model: "auto", whisper_other_language_model: "",
    youtube_captions: true, candidates: 40, top_k: 6, query_rewrite: false, max_file_mb: 50, max_video_mb: 2000 },
  file_groups: [{ key: "pdf", label: "PDF" }, { key: "word", label: "Word" }],
  chunk_types: [{ key: "text", label: "Tekst" }, { key: "table", label: "Tabeller" }],
  not_available: { video: "Video og lyd kommer i neste versjon av Emne-RAG." },
  providers: [],
  ...partial,
});

describe("AnswerText", () => {
  it("turns [S1] markers into links to the cited sources and drops unknown ones", () => {
    render(<AnswerText text={"Rasterbilder består av piksler [S1].\n\n- RGB på skjerm [S2]\n- CMYK [S9]"}
      sources={[hit("S1", "Raster og vektor – Modul 1"), hit("S2", "Fargemodeller.pptx lysbilde 1")]} />);
    const link = screen.getByRole("link", { name: /Raster og vektor – Modul 1/ });
    expect(link).toHaveAttribute("href", "https://canvas.test/courses/104/pages/raster");
    expect(screen.getByText("[Fargemodeller.pptx lysbilde 1]")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByText(/S9/)).not.toBeInTheDocument();
  });
});

describe("AskPanel", () => {
  it("searches without AI and shows cited sources", async () => {
    const result: SearchResult = { hits: [hit("S1", "Raster og vektor – Modul 1")], queries: ["piksler"], notes: [],
      modes: { keyword: true, vector: true, rerank: true, rewritten: false } };
    const calls = mockApi({ "/rag/search": result });
    const { container } = render(wrap(<AskPanel courseId="104" status={status()} />));
    expect(screen.getByRole("button", { name: "Svar med KI" })).toBeDisabled();
    expect(screen.getByText(/Søket virker uten KI/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Spørsmål/), "Hva er et rasterbilde?");
    await userEvent.click(screen.getByRole("button", { name: "Søk i emnet" }));
    expect(await screen.findByText("Raster og vektor – Modul 1")).toBeInTheDocument();
    expect(screen.getByText(/semantisk søk, rerangering/)).toBeInTheDocument();
    expect(calls.at(-1)?.body).toMatchObject({ query: "Hva er et rasterbilde?", module_ids: [], types: [] });
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("BuildPanel", () => {
  it("shows an estimate and requires accepting first-time downloads", async () => {
    const estimate: Estimate = {
      counts: { page: 3, file_pdf: 2 }, words: 1200, documents: { count: 2, size_mb: 1.5, too_large: [] },
      chunks_estimate: 9, skipped: [{ key: "page:blokk", kind: "page", kind_label: "Side", title: "Blokkside",
        reason: "Blokkredigering", url: null }], limitations: [], modules: [],
      time: { low_seconds: 10, high_seconds: 50, assumptions: ["Embedding: ca. 3 utdrag per sekund (CPU)."] },
      downloads: [{ label: "BGE-M3", size_mb: 2270, kind: "embedding" }], ai: [],
      embedding: { available: true, label: "BGE-M3", reason: null, needs_download: true, download_mb: 2270 },
      reranker: { available: false, label: "x", reason: null, needs_download: false, download_mb: 0 }, device: "cpu",
      privacy: ["Bare lærerprodusert innhold leses."], index: { exists: false, embedding: null, built_at: null },
    };
    const calls = mockApi({ "/rag/estimate": estimate });
    const { container } = render(wrap(<BuildPanel courseId="104" status={status({ stats: null })} />));
    expect(screen.getByRole("checkbox", { name: /Video og lyd/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Beregn estimat" }));
    expect(await screen.findByRole("rowheader", { name: "Sider" })).toBeInTheDocument();
    expect(screen.getByText(/Bare lærerprodusert innhold/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Bygg indeks" });
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Jeg godtar nedlasting/ }));
    await waitFor(() => expect(start).toBeEnabled());
    expect(calls[0].body).toMatchObject({ ...DEFAULT_OPTIONS });
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("QualityPanel and ExportPanel", () => {
  it("shows the health score with an honest explanation and download links", async () => {
    const { QualityPanel } = await import("./QualityPanel");
    const { ExportPanel } = await import("./ExportPanel");
    const evaluated = status({
      index: {
        status: "ready", options: {}, embedding: { identity: "local:BAAI/bge-m3", label: "BGE-M3", backend: "local" },
        stats: {}, skipped: [], limitations: [], last_job_id: null, built_at: "2026-11-03T10:00:00Z", updated_at: null,
        evaluation: {
          method: "keywords", method_label: "Nøkkelordspørsmål (uten KI)", recall_at_5: 0.8, mrr: 0.7, health: 75,
          health_label: "Middels", created_at: "2026-11-03T10:00:00Z", explanation: "Helsescoren måler gjenfinning.",
          questions: [{ question: "fargehjul primærfarger", chunk_id: 3, citation: "Fargelære – Modul 2", rank: 1 },
            { question: "pensum kapittel", chunk_id: 4, citation: "Pensum.pdf s. 1", rank: null }],
        },
      },
    });
    const { container } = render(wrap(<><QualityPanel courseId="104" status={evaluated} /><ExportPanel courseId="104" status={evaluated} /></>));
    expect(screen.getByText("Middels")).toBeInTheDocument();
    expect(screen.getByText("Ikke funnet")).toBeInTheDocument();
    expect(screen.getByText(/måler gjenfinning/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /La KI lage testspørsmålene/ })).toBeDisabled();
    const zip = screen.getByRole("link", { name: /Last ned ZIP for andre RAG-verktøy/ });
    expect(zip).toHaveAttribute("href", "/api/courses/104/rag/export?format=zip");
    expect(screen.getAllByRole("link", { name: /Last ned/ })).toHaveLength(5);
    expect(await axeViolations(container)).toEqual([]);
  });
});
