// KI-bildeassistent: API types and hooks (backend: emneklar/features/illustrations/api.py).
import { useQuery } from "@tanstack/react-query";

import { api } from "../../../core/api/client";
import type { Job } from "../../../core/api/types";

export type ScopeType = "course" | "module" | "modules" | "page";
export type QualityProfileId = "max" | "balanced" | "fast";
export type Amount = "low" | "balanced" | "high";
export type ImageFormat = "auto" | "16:9" | "3:2" | "4:3" | "1:1" | "2:3";

export interface Scope {
  type: ScopeType;
  module_ids: string[];
  page_url: string | null;
  include_unpublished: boolean;
  include_outside_modules: boolean;
  only_missing: boolean;
}

export const DEFAULT_SCOPE: Scope = {
  type: "course",
  module_ids: [],
  page_url: null,
  include_unpublished: true,
  include_outside_modules: true,
  only_missing: false,
};

export interface IllustrationSettings {
  quality_profile: QualityProfileId;
  amount: Amount;
  analysis_model: string;
  planning_model: string;
  review_model: string;
  image_provider_id: string;
  image_model: string;
  image_quality: "" | "low" | "medium" | "high" | "xhigh" | "max";
  image_format: ImageFormat;
  use_reference_images: boolean;
  captions: boolean;
  text_in_images: "auto" | "never";
  credit: boolean;
  credit_text: string;
  max_width_px: number;
  folder: string;
  cost_limit_usd: number | null;
  concurrency: number;
}

export interface ModelRef {
  provider_id: string;
  model_id: string;
  display_name: string;
  ref: string;
}

export interface RoleChoice {
  role: string;
  label: string;
  primary: ModelRef | null;
  fallbacks: ModelRef[];
  reason: string;
}

export interface ImageModel {
  id: string;
  label: string;
  provider_type: string;
  description: string;
  reference_images: boolean;
  qualities: string[];
  sizes: string[];
  default: boolean;
  known: boolean;
}

export interface Choices {
  profile: { id: QualityProfileId; label: string; description: string; review_rounds: number };
  roles: Record<string, RoleChoice>;
  image: {
    provider_id: string;
    model: ImageModel | null;
    quality: string;
    size: string;
    reason: string;
    available: boolean;
    unavailable_reason: string | null;
  };
}

export interface DesignData {
  style_key: string;
  name: string;
  rationale: string;
  illustration_style: string;
  palette: string[];
  palette_description: string;
  contrast: string;
  lighting: string;
  composition: string;
  background: string;
  detail_level: string;
  visual_traits: string;
  avoid: string[];
  people: string;
  aspect_ratio: ImageFormat;
}

export interface DesignProfile {
  id: number;
  version: number;
  name: string;
  style_key: string;
  style_label: string;
  origin: string;
  active: boolean;
  data: DesignData;
  reference_assets: string[];
  created_at: string | null;
  style_prompt: string;
}

export interface RunSummary {
  id: number;
  course_id: string;
  status: string;
  status_label: string;
  scope: Scope;
  options: { mode: "full" | "plan"; settings: IllustrationSettings; auto_insert: boolean };
  stats: {
    inventory?: { modules_in_scope: number; pages_in_scope: number; pages_in_several_modules: number; unpublished_pages: number; non_page_items: number; skipped: number };
    skipped?: { title: string; reason: string }[];
  } & Record<string, unknown>;
  usage: { cost_usd?: number; estimated_usd?: number; calls?: number; unreported_calls?: number; limit_usd?: number | null; currency?: string };
  limitations: string[];
  error: string | null;
  job_id: string | null;
  created_at: string | null;
}

export interface Status {
  settings: IllustrationSettings;
  choices: Choices;
  ai: { available: boolean; reason: string | null; external_allowed: boolean; confirm_before_send: boolean };
  image_providers: { id: string; name: string; type: string; configured: boolean; models: ImageModel[]; needs_model_name: boolean }[];
  design: DesignProfile | null;
  design_versions: DesignProfile[];
  runs: RunSummary[];
  busy_job: { id: string; title: string; status: string } | null;
  text_models: { ref: string; display_name: string; provider_id: string; vision: boolean }[];
}

export interface Catalog {
  styles: { key: string; label: string; description: string }[];
  quality_profiles: { id: QualityProfileId; label: string; description: string; default: boolean; review_rounds: number }[];
  roles: Record<string, string>;
  image_models: ImageModel[];
  placements: Record<string, string>;
  amounts: Record<Amount, string>;
  statuses: Record<string, string>;
  formats: Record<ImageFormat, string>;
  image_types: Record<string, string>;
  usage_rights: { id: string; label: string }[];
  pricing: { version: string; currency: string; note: string };
}

export interface ScopeIndex {
  modules: { id: string; name: string; items_count: number; pages: { page_url: string; title: string }[]; other_items: number; published: boolean }[];
  pages: { url: string; title: string; published: boolean; in_module: boolean; front_page: boolean }[];
}

export interface Anchor {
  placement: string;
  placement_label: string;
  section_id: string | null;
  section_title: string;
  block_index: number;
  block_text: string;
  warning: string | null;
}

export interface Illustration {
  id: number;
  run_id: number;
  status: string;
  status_label: string;
  module_id: string | null;
  module_name: string | null;
  page_url: string;
  page_title: string;
  section: { section_id: string; title: string; text: string; before: { title: string; text: string }; after: { title: string; text: string } };
  anchor: Anchor;
  placement_label: string;
  plan: {
    pedagogical_purpose?: string;
    concept?: string;
    learning_goal?: string;
    motif?: string;
    composition?: string;
    must_show?: string[];
    must_not_show?: string[];
    accuracy_risk?: "low" | "medium" | "high";
    accuracy_notes?: string;
    adds_value?: string;
    placement_reason?: string;
  };
  prompt: string;
  style_override: string | null;
  asset_id: string | null;
  image_url: string | null;
  thumb_url: string | null;
  versions: { asset_id: string; attempt: number; verdict: string; issues: string[]; scores: Record<string, number | null> }[];
  review: {
    verdict?: string;
    relevance?: number;
    content_alignment?: number;
    visual_quality?: number;
    style_consistency?: number;
    supports_learning_goal?: number;
    text_status?: "none" | "correct" | "errors" | "unwanted";
    text_issues?: string[];
    caption_adds_value?: boolean;
    issues?: string[];
    incorrect_details?: string[];
    manual_check?: boolean;
    manual_check_reason?: string;
  };
  alt_text: string;
  decorative: boolean;
  caption: string;
  caption_enabled: boolean;
  aspect_ratio: Exclude<ImageFormat, "auto">;
  image_type: string;
  labels: string[];
  credit: string;
  change_id: number | null;
  published: { file_id?: string; at?: string; html_check?: { ok: boolean; missing: string[]; dropped: string[] } | null };
  error: string | null;
  manual_check: boolean;
  ai_label: string;
}

export interface OverviewPage {
  page_url: string;
  title: string;
  status: string;
  reason: string | null;
  summary: string | null;
  illustrations: Illustration[];
  proposed: number;
}

export interface RunDetail {
  run: RunSummary;
  illustrations: Illustration[];
  overview: { module_id: string; name: string; pages: OverviewPage[]; proposed: number }[];
  counts: Record<string, number>;
  job: Job | null;
  can_continue: boolean;
}

export interface Receiver {
  service: string;
  role: string;
  content: string;
}

export interface EstimateLine {
  key: string;
  label: string;
  calls_low: number;
  calls_high: number;
  cost_low: number | null;
  cost_high: number | null;
}

export interface Estimate {
  available: boolean;
  reason: string | null;
  stats: NonNullable<RunSummary["stats"]["inventory"]>;
  skipped: { title: string; reason: string }[];
  limitations: string[];
  estimate: {
    currency: string;
    lines: EstimateLine[];
    total_low: number;
    total_high: number;
    images_low: number;
    images_high: number;
    unpriced: string[];
    cached_pages: number;
    note: string;
  };
  payload_summary: string;
  payload_short: string;
  providers: string[];
  receivers: Receiver[];
  external: boolean;
  needs_confirmation: boolean;
  usage_rights_required: boolean;
  pages: { url: string; title: string; module: string; published: boolean; modules: string[] }[];
}

export interface PublishPreview {
  pages: {
    page_url: string;
    title: string;
    ok: boolean;
    error?: string;
    published?: boolean;
    replaces?: string[];
    illustrations: { id: number; placement_label?: string; section?: string; alt_text?: string; decorative?: boolean; caption?: string | null; thumb_url?: string | null }[];
  }[];
  folder: string;
  usage_rights_required: boolean;
  note: string;
}

export function useIllustrationStatus(courseId: string | null) {
  return useQuery({
    queryKey: ["illustrations", courseId],
    queryFn: () => api.get<Status>(`/api/courses/${courseId}/illustrations`),
    enabled: Boolean(courseId),
  });
}

export function useCatalog() {
  return useQuery({
    queryKey: ["illustrations", "catalog"],
    queryFn: () => api.get<Catalog>("/api/illustrations/catalog"),
    staleTime: 10 * 60_000,
  });
}

export function useScopeIndex(courseId: string | null) {
  return useQuery({
    queryKey: ["illustrations", courseId, "scope-index"],
    queryFn: () => api.get<ScopeIndex>(`/api/courses/${courseId}/illustrations/scope-index`),
    enabled: Boolean(courseId),
    staleTime: 60_000,
  });
}

export function useRun(runId: number | null) {
  return useQuery({
    queryKey: ["illustrations", "run", runId],
    queryFn: () => api.get<RunDetail>(`/api/illustrations/runs/${runId}`),
    enabled: runId !== null,
  });
}

export const RUN_TONE: Record<string, "neutral" | "info" | "success" | "warning" | "danger"> = {
  created: "neutral",
  analyzing: "info",
  planned: "info",
  generating: "info",
  review: "success",
  completed: "success",
  cancelled: "warning",
  interrupted: "warning",
  cost_limit: "warning",
  failed: "danger",
};

export const ILLUSTRATION_TONE: Record<string, "neutral" | "info" | "success" | "warning" | "danger" | "violet"> = {
  proposed: "info",
  skipped: "neutral",
  queued: "neutral",
  generating: "info",
  generated: "violet",
  flagged: "warning",
  failed: "danger",
  approved: "success",
  rejected: "neutral",
  staged: "info",
  published: "success",
  conflict: "danger",
  undone: "neutral",
};

export function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "ukjent";
  return `${value.toLocaleString("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}
