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

export const DEFAULT_OPTIONS: BuildOptions = {
  scope: "course",
  module_ids: [],
  text: true,
  documents: true,
  images: false,
  video: false,
  file_groups: ["pdf", "word", "powerpoint", "excel", "text"],
  include_unpublished: false,
  contextual_enrichment: false,
  keyframes: false,
};

export interface SkippedItem {
  key: string;
  kind: string;
  kind_label: string;
  title: string;
  reason: string;
  url: string | null;
  failed?: boolean;
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
  whisper_model: "auto" | "tiny" | "base" | "small" | "medium" | "large";
  whisper_other_language_model: string;
  youtube_captions: boolean;
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
}

export interface AiTaskEstimate {
  task: string;
  label: string;
  calls: number;
  input_tokens: number;
  images?: number;
  available: boolean;
  reason: string | null;
  external: boolean;
  route: { provider: string; model: string; reason: string } | null;
}

export interface Estimate {
  counts: Record<string, number>;
  words: number;
  documents: { count: number; size_mb: number; too_large: { title: string; size_mb: number }[] };
  video?: { count: number; with_captions: number; minutes_known: number; unknown_duration: number;
    to_transcribe: number; unavailable: number };
  images?: { candidates: number; documents_note: string };
  chunks_estimate: number;
  skipped: SkippedItem[];
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
