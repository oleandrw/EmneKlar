// Emne-RAG: API types and queries (Canvas-verktøy → Emne-RAG).
import { useQuery } from "@tanstack/react-query";

import { api } from "../../../core/api/client";

export type FileGroup = "pdf" | "word" | "powerpoint" | "excel" | "text";
export type ChunkType = "text" | "table" | "image" | "transcript" | "slide";

export interface BuildOptions {
  scope: "course" | "modules";
  module_ids: string[];
  text: boolean;
  documents: boolean;
  images: boolean;
  video: boolean;
  file_groups: FileGroup[];
  include_unpublished: boolean;
  contextual_enrichment: boolean;
  keyframes: boolean;
}

// Every source is on by default; what costs extra (KI-tillegg) is off until chosen under «Tilpass kilder».
export const DEFAULT_OPTIONS: BuildOptions = {
  scope: "course",
  module_ids: [],
  text: true,
  documents: true,
  images: true,
  video: true,
  file_groups: ["pdf", "word", "powerpoint", "excel", "text"],
  include_unpublished: false,
  contextual_enrichment: false,
  keyframes: false,
};

/** «Tilbakestill kilder»: the default sources, file types and unpublished choice; scope, modules and the KI add-ons
 * under «Avansert» are kept. */
export function resetSources(options: BuildOptions): BuildOptions {
  const { text, documents, video, images, file_groups, include_unpublished } = DEFAULT_OPTIONS;
  return { ...options, text, documents, video, images, file_groups: [...file_groups], include_unpublished };
}

// «Lagre valg» keeps the source choices per course in this browser (nothing secret; see core/api/client.ts). The
// transcription choice is a server setting that applies to all courses.
const SAVED_FLAGS = ["text", "documents", "video", "images", "include_unpublished", "contextual_enrichment",
  "keyframes"] as const;
const savedKey = (courseId: string) => `emneklar.rag.sources.${courseId}`;

export function loadSavedSources(courseId: string): Partial<BuildOptions> {
  try {
    const raw = window.localStorage.getItem(savedKey(courseId));
    if (!raw) return {};
    const data = JSON.parse(raw) as Record<string, unknown>;
    const out: Partial<BuildOptions> = {};
    for (const key of SAVED_FLAGS) {
      const value = data[key];
      if (typeof value === "boolean") out[key] = value;
    }
    if (Array.isArray(data.file_groups)) {
      out.file_groups = DEFAULT_OPTIONS.file_groups.filter((g) => (data.file_groups as unknown[]).includes(g));
    }
    return out;
  } catch {
    return {};  // storage blocked or unreadable: the defaults apply
  }
}

export function saveSources(courseId: string, options: BuildOptions): boolean {
  const data: Record<string, unknown> = { file_groups: options.file_groups };
  for (const key of SAVED_FLAGS) data[key] = options[key];
  try {
    window.localStorage.setItem(savedKey(courseId), JSON.stringify(data));
    return true;
  } catch {
    return false;  // storage blocked: the choices apply until the page is closed
  }
}

/** What is actually sent: options that need KI are off when KI is not set up (the summary says why). */
export function effectiveOptions(options: BuildOptions, status: RagStatus): BuildOptions {
  const ai = status.ai.available;
  const allowed = (key: keyof BuildOptions) => !status.not_available[key];
  const video = options.video && allowed("video");
  return {
    ...options,
    video,
    images: options.images && ai && allowed("images"),
    contextual_enrichment: options.contextual_enrichment && ai && allowed("contextual_enrichment"),
    keyframes: options.keyframes && video && ai && allowed("keyframes"),
  };
}

const SOURCE_SHORT: [keyof Pick<BuildOptions, "text" | "documents" | "video" | "images">, string][] = [
  ["text", "Canvas-tekst"], ["documents", "dokumenter"], ["video", "video/lyd"], ["images", "bilder"]];
const GROUP_SHORT: Record<FileGroup, string> = { pdf: "PDF", word: "Word-dokumenter", powerpoint: "presentasjoner",
  excel: "regneark", text: "tekstfiler" };

export function listNb(items: string[]): string {
  return items.length <= 1 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} og ${items[items.length - 1]}`;
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export interface SourceSummary {
  customized: boolean;
  nothing: boolean;
  text: string;
  notes: string[];
}

/** The one-line summary on the main page («Inkluderer …» or «Tilpassede kilder · … er utelatt.»). */
export function sourceSummary(options: BuildOptions, status: RagStatus): SourceSummary {
  const effective = effectiveOptions(options, status);
  const off = SOURCE_SHORT.filter(([key]) => !options[key]).map(([, label]) => label);
  if (options.documents) {
    off.push(...status.file_groups.filter((g) => !options.file_groups.includes(g.key)).map((g) => GROUP_SHORT[g.key]));
  }
  const extras: string[] = [];
  if (options.scope === "course" && options.include_unpublished) extras.push("Upublisert innhold tas med.");
  if (effective.contextual_enrichment) extras.push("Kontekstuell berikelse med KI er på.");
  if (effective.keyframes) extras.push("Nøkkelbilder fra video er på.");
  const customized = off.length > 0 || extras.length > 0;
  const included = [effective.text && "Canvas-tekst", effective.documents && "dokumenter",
    ...(effective.video ? ["video", "lyd"] : []), effective.images && "bilder"].filter((x): x is string => Boolean(x));
  const notes: string[] = [];
  const aiMissing = status.ai.reason ? `: ${status.ai.reason}` : ".";
  if (options.images && !effective.images) notes.push(`Bilder tas ikke med fordi KI ikke er satt opp${aiMissing}`);
  if (options.video && !effective.video) notes.push(status.not_available.video ?? "Video og lyd er ikke tilgjengelig.");
  if (options.contextual_enrichment && !effective.contextual_enrichment) {
    notes.push(`Kontekstuell berikelse er valgt, men krever KI${aiMissing}`);
  }
  const nothing = included.length === 0;
  const text = nothing ? "Ingen kilder er valgt."
    : customized ? ["Tilpassede kilder", off.length ? `${capitalise(listNb(off))} er utelatt.` : null, ...extras]
      .filter(Boolean).join(" · ")
      : `Inkluderer ${listNb(included)}.`;
  return { customized, nothing, text, notes };
}

export interface SkippedItem {
  key: string;
  kind: string;
  kind_label: string;
  title: string;
  reason: string;
  url: string | null;
  failed?: boolean;
  waiting?: boolean;
}

export interface Choice {
  available: boolean;
  label: string;
  reason: string | null;
  needs_download: boolean;
  download_mb: number;
  external?: boolean;
  needs_confirmation?: boolean;
  backend?: string;
  identity?: string | null;
}

export interface LocalModel {
  id: string;
  kind: "embedding" | "reranker" | "whisper" | "whisper_other";
  label: string;
  size_mb: number;
  default: boolean;
  downloaded: boolean;
  notes: string | null;
}

export interface RagSettings {
  embedding_backend: "local" | "provider" | "none";
  embedding_model: string;
  embedding_provider_id: string;
  embedding_provider_model: string;
  reranker_enabled: boolean;
  reranker_model: string;
  device: "auto" | "cpu" | "cuda";
  transcription: "local" | "provider" | "off";
  transcription_provider_id: string;
  transcription_model: string;
  transcription_language: string;
  whisper_model: "auto" | "tiny" | "base" | "small" | "medium" | "large";
  whisper_other_language_model: string;
  youtube_captions: boolean;
  vimeo_captions: boolean;
  candidates: number;
  top_k: number;
  query_rewrite: boolean;
  max_file_mb: number;
  max_video_mb: number;
}

export interface Evaluation {
  method: "ai" | "keywords";
  method_label: string;
  questions: { question: string; chunk_id: number; citation: string; rank: number | null }[];
  recall_at_5: number;
  mrr: number;
  health: number;
  health_label: string;
  created_at: string;
  explanation: string;
}

export interface RagIndex {
  status: "empty" | "building" | "ready" | "partial" | "failed";
  options: Partial<BuildOptions>;
  embedding: { identity: string | null; label: string; backend: string };
  stats: Record<string, unknown>;
  skipped: SkippedItem[];
  limitations: string[];
  evaluation: Evaluation | Record<string, never>;
  last_job_id: string | null;
  built_at: string | null;
  updated_at: string | null;
}

export interface IndexStats {
  chunks: number;
  chunk_types: Partial<Record<ChunkType, number>>;
  items: Record<string, number>;
  item_status: Record<string, number>;
  vectors: number;
  tokens: number;
  video_minutes: number;
  keyword_engine: "fts5" | "python";
}

export interface RagStatus {
  index: RagIndex | null;
  stats: IndexStats | null;
  modules: { id: string; name: string }[];
  error: { code: string; message: string } | null;
  index_embedding: string | null;
  model_mismatch: boolean;
  embedding: Choice;
  reranker: Choice;
  device: "cpu" | "cuda";
  local: {
    installed: { embedding: boolean; reranker: boolean; whisper: boolean; youtube: boolean };
    device: string | null;
    cuda: boolean | null;
    models_dir: string;
    models: LocalModel[];
  };
  ai: { available: boolean; reason: string | null };
  busy_job: string | null;
  settings: RagSettings;
  file_groups: { key: FileGroup; label: string }[];
  chunk_types: { key: ChunkType; label: string }[];
  not_available: Record<string, string>;
  providers: { id: string; name: string; type: string }[];
  transcription: {
    mode: RagSettings["transcription"];
    plan: { available: boolean; reason: string | null; external: boolean;
      model: { id: string; label: string; segments: boolean | null } | null } | null;
  };
  transcription_models: { id: string; label: string; provider_type: string; segments: boolean | null; default: boolean }[];
}

export interface AiTaskEstimate {
  task: string;
  label: string;
  calls: number;
  input_tokens: number;
  images?: number;
  minutes?: number;
  available: boolean;
  reason: string | null;
  external: boolean;
  route: { provider: string; model: string; reason: string } | null;
}

export interface Estimate {
  counts: Record<string, number>;
  words: number;
  documents: { count: number; size_mb: number; too_large: { title: string; size_mb: number }[] };
  video?: { count: number; with_captions: number; youtube: number; vimeo: number; minutes_known: number;
    unknown_duration: number;
    to_transcribe: number; unavailable: number; transcription: RagSettings["transcription"]; model: string;
    minutes_to_transcribe: number };
  images?: { candidates: number; documents_note: string };
  chunks_estimate: number;
  skipped: SkippedItem[];
  unpublished: number;
  unpublished_included: number;
  limitations: string[];
  modules: { id: string; name: string; published: boolean; items_count: number }[];
  time: { low_seconds: number; high_seconds: number; assumptions: string[] };
  downloads: { label: string; size_mb: number; kind: string }[];
  ai: AiTaskEstimate[];
  embedding: Choice;
  reranker: Choice;
  device: string;
  privacy: string[];
  index: { exists: boolean; embedding: { identity: string | null; label: string } | null; built_at: string | null };
}

export interface Hit {
  id?: string;
  chunk_id: number;
  type: ChunkType;
  item_kind: string;
  title: string;
  heading_path: string[];
  module: string | null;
  url: string | null;
  page: number | null;
  page_end: number | null;
  start: number | null;
  end: number | null;
  citation: string;
  snippet: string;
  text: string;
  rank: number;
  cited?: boolean;
  meta?: { ai_label?: string; image_url?: string; video_title?: string } & Record<string, unknown>;
  scores?: {
    keyword_rank: number | null;
    keyword_score: number | null;
    vector_rank: number | null;
    vector_score: number | null;
    rrf_score: number;
    rrf_rank: number;
    rerank_score: number | null;
  };
}

export interface SearchResult {
  hits: Hit[];
  modes: { keyword: boolean; vector: boolean; rerank: boolean; rewritten: boolean };
  queries: string[];
  notes: string[];
  debug?: { before_rerank: Hit[]; after_rerank: Hit[] };
}

export interface AskResult {
  answer: string | null;
  coverage: "full" | "partial" | "none";
  cited: string[];
  sources: Hit[];
  search: SearchResult;
  label?: string;
  model?: string;
  provider?: string;
  message?: string;
}

export interface QueryBody {
  query: string;
  module_ids: string[];
  types: ChunkType[];
  debug: boolean;
  confirmed?: boolean;
}

export function useRagStatus(courseId: string | null) {
  return useQuery({
    queryKey: ["rag", courseId],
    queryFn: () => api.get<RagStatus>(`/api/courses/${courseId}/rag`),
    enabled: Boolean(courseId),
  });
}

export const KIND_ORDER: [string, string][] = [
  ["page", "Sider"],
  ["assignment", "Oppgavebeskrivelser"],
  ["quiz", "Quizbeskrivelser"],
  ["discussion", "Lærerens diskusjonsinnlegg"],
  ["syllabus", "Emneplan"],
  ["file_pdf", "PDF-filer"],
  ["file_word", "Word og tekstdokumenter"],
  ["file_powerpoint", "Presentasjoner"],
  ["file_excel", "Regneark"],
  ["file_text", "Tekstfiler"],
  ["video_file", "Video- og lydfiler"],
  ["media", "Canvas-video og -lyd"],
  ["youtube", "YouTube-videoer"],
  ["vimeo", "Vimeo-videoer"],
  ["subtitle", "Undertekstfiler"],
  ["image_file", "Bildefiler"],
  ["image", "Bilder på sider"],
];

export const STATUS_LABEL: Record<RagIndex["status"], string> = {
  empty: "Tom",
  building: "Bygges",
  ready: "Klar",
  partial: "Ufullstendig",
  failed: "Feilet",
};

export function formatMb(mb: number): string {
  if (mb >= 1000) return `${(mb / 1000).toLocaleString("nb-NO", { maximumFractionDigits: 1 })} GB`;
  return `${Math.round(mb).toLocaleString("nb-NO")} MB`;
}
