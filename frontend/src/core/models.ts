// The model registry in the user interface: the one source every model selector reads (backend: core/ai/catalog.py,
// GET /api/ai/models). A selector says which capabilities its function needs and gets the enabled, classified models
// that have them – it never keeps a model list of its own. Changes under Innstillinger → KI-assistenter reach every
// selector through `useModelRegistryRefresh`, without a restart or a page reload.
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api/client";

export type ModelKind = "text" | "image" | "transcription" | "embedding";
export type Capability = "text" | "vision" | "structured_output" | "image_generation" | "reference_images"
  | "transcription" | "timestamps" | "embedding";

/** Request parameters a model supports. Image models have all the image fields; transcription models `segments`. */
export interface ModelParams {
  qualities?: string[];
  sizes?: string[];
  aspect_sizes?: Record<string, string>;
  reference_images?: boolean;
  max_reference_images?: number;
  complexities?: string[];
  input_fidelity?: boolean;
  segments?: boolean | null;
}

export interface AiModel {
  id: number;
  provider_id: string;
  model_id: string;
  /** "provider_id/model_id" – the value text-model settings store. */
  ref: string;
  display_name: string;
  description: string;
  kind: ModelKind;
  kind_label: string;
  capabilities: Capability[];
  params: ModelParams;
  vision: boolean;
  structured_output: boolean;
  context_class: number;
  quality_class: number;
  speed_class: number;
  cost_class: number;
  priority: number;
  is_default: boolean;
  enabled: boolean;
  source: "catalog" | "discovered" | "user";
  capabilities_known: boolean;
  notes: string | null;
  /** The provider is set up and may be used now. */
  provider_ready?: boolean;
  /** Indicative list price (never guaranteed); null when none is known. */
  price?: Record<string, unknown> | null;
  suggested_kind?: ModelKind;
}

export interface ModelRegistry {
  models: AiModel[];
  catalog_version: string;
  catalog_note: string;
  kinds: { id: ModelKind; label: string }[];
  capabilities: Record<string, string>;
  image_qualities: string[];
  image_complexities: string[];
  max_priority: number;
}

export const MODEL_REGISTRY_KEY = ["ai-models"] as const;

/** Every model in the registry. Always fresh: fetched again when a page opens and when the window gets focus. */
export function useModelRegistry() {
  return useQuery({
    queryKey: MODEL_REGISTRY_KEY,
    queryFn: () => api.get<ModelRegistry>("/api/ai/models"),
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });
}

/** Everything that is computed from the registry: the registry itself, routing, and the features' own model choices. */
const DEPENDENT_QUERIES = ["ai-providers", "ai-models", "ai-routing", "session", "illustrations", "rag"];

/** Call after any change to models, providers or routing: every selector and automatic choice is fetched again. */
export function useModelRegistryRefresh() {
  const client = useQueryClient();
  return () => {
    for (const key of DEPENDENT_QUERIES) void client.invalidateQueries({ queryKey: [key] });
  };
}

export interface ModelNeed {
  /** Capabilities the function needs; a model must have all of them. */
  requires: Capability[] | string[];
  /** Only models at this provider. */
  providerId?: string;
}

/** The models a selector may offer: enabled, classified, with every required capability. */
export function selectableModels(models: AiModel[] | undefined, need: ModelNeed): AiModel[] {
  return (models ?? []).filter((m) => m.enabled && m.capabilities_known
    && (!need.providerId || m.provider_id === need.providerId)
    && need.requires.every((c) => (m.capabilities as string[]).includes(c)));
}

export interface ModelOption {
  value: string;
  label: string;
}

/**
 * Options for a model selector. `value` says what the setting stores: the model id (one provider) or the ref
 * "provider/model" (any provider). A stored choice that is no longer offered is kept as an option marked
 * «ikke tilgjengelig», so the teacher sees what was chosen instead of a silently changed field.
 */
export function modelOptions(models: AiModel[] | undefined, need: ModelNeed, options: {
  value: "model_id" | "ref";
  current?: string | null;
  providerName?: (id: string) => string;
  describe?: boolean;
}): ModelOption[] {
  const out = selectableModels(models, need).map((m) => ({
    value: options.value === "ref" ? m.ref : m.model_id,
    label: [
      options.value === "ref" ? `${m.display_name} (${options.providerName?.(m.provider_id) ?? m.provider_id})` : m.display_name,
      options.describe && m.description ? ` – ${m.description}` : "",
      m.is_default ? " (standard)" : "",
    ].join(""),
  }));
  const current = options.current ?? "";
  if (current && !out.some((o) => o.value === current)) {
    out.push({ value: current, label: `${current.includes("/") ? current.split("/").slice(1).join("/") : current} (ikke tilgjengelig)` });
  }
  return out;
}

/** True when a stored choice is not among the models the selector may offer now. */
export function choiceUnavailable(models: AiModel[] | undefined, need: ModelNeed, value: "model_id" | "ref", current: string | null | undefined): boolean {
  if (!current || !models) return false;
  return !selectableModels(models, need).some((m) => (value === "ref" ? m.ref : m.model_id) === current);
}
