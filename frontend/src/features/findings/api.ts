import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, qs } from "../../core/api/client";
import type { AltSuggestion, BlueprintWhere, Finding, Job, MediaKind } from "../../core/api/types";

export interface RunInfo {
  id: number;
  domains: string[];
  scope_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  counts: Record<string, number>;
  ruleset_version: string | null;
  profile_id: string | null;
  profile_version: string | null;
  limitations: string[];
  stats: Record<string, number>;
}

export interface FindingsResponse {
  items: Finding[];
  /** Every id in the current filter and order (for stepping through findings and «Godkjenn alle klare»). */
  ids: number[];
  total: number;
  page: number;
  page_size: number;
  summary: {
    total: number;
    ignored: number;
    verified: number;
    fixed: number;
    staged: number;
    by_classification: Record<string, number>;
    by_category: Record<string, number>;
    actionable: number;
  };
  categories: { id: string; label: string }[];
  /** The classes this area's rules can give (from the rule registry); older servers leave it out. */
  classifications?: string[];
  /** Ready fixes in the whole selection (all pages): «Godkjenn alle klare» works on these. */
  ready?: { automatic: number; suggestion: number };
  runs: RunInfo[];
  profile: { id: string; title: string; version: string };
}

export interface FindingFilters {
  classification: string[];
  category: string[];
  /** Only from a link (e.g. Emneoversikt → «Se alvorlige avvik»); shown as «Utvalg» above the list. */
  severity?: string[];
  rule?: string[];
  status: string;
  q: string;
  sort: string;
  page: number;
  page_size: number;
}

export function useFindings(courseId: string | null, domain: string, filters: FindingFilters) {
  return useQuery({
    queryKey: ["findings", courseId, domain, filters],
    queryFn: () =>
      api.get<FindingsResponse>(
        `/api/courses/${courseId}/findings${qs({
          domain,
          classification: filters.classification,
          category: filters.category,
          severity: filters.severity ?? [],
          rule: filters.rule ?? [],
          status: filters.status,
          q: filters.q,
          sort: filters.sort,
          page: filters.page,
          page_size: filters.page_size,
        })}`,
      ),
    enabled: Boolean(courseId),
    placeholderData: keepPreviousData,
  });
}

/** One finding by id (when stepping beyond the loaded page, or opening a fix from the link overview). */
export function useFinding(id: number | null) {
  return useQuery({
    queryKey: ["findings", "one", id],
    queryFn: () => api.get<Finding>(`/api/findings/${id}`),
    enabled: id !== null,
  });
}

export function useFindingActions() {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["findings"] });
    void client.invalidateQueries({ queryKey: ["overview"] });
    void client.invalidateQueries({ queryKey: ["changes"] });
    void client.invalidateQueries({ queryKey: ["links"] });
  };
  return {
    ignore: useMutation({
      mutationFn: ({ id, note }: { id: number; note?: string }) => api.post<Finding>(`/api/findings/${id}/ignore`, { note }),
      onSuccess: refresh,
    }),
    reopen: useMutation({
      mutationFn: (id: number) => api.post<Finding>(`/api/findings/${id}/reopen`),
      onSuccess: refresh,
    }),
    /** «Kontrollert»: confirm one of the rule's confirmations (survives re-analysis, listed in reports). */
    verify: useMutation({
      mutationFn: ({ id, confirmation, note }: { id: number; confirmation: string; note?: string }) =>
        api.post<Finding>(`/api/findings/${id}/verify`, { confirmation, note }),
      onSuccess: refresh,
    }),
    /** State what the recording is, then analyse the content again so the right requirement is shown. */
    mediaKind: useMutation({
      mutationFn: async ({ finding, kind }: { finding: Finding; kind: MediaKind | null }) => {
        const saved = await api.post<{ reanalyse: { object_type: string; object_id: string } | null }>(
          `/api/findings/${finding.id}/media-kind`, { kind });
        if (!saved.reanalyse) return null;
        return api.post<Job>("/api/analysis", {
          course_id: finding.course_id, scope: "items", domains: ["accessibility"], items: [saved.reanalyse],
        });
      },
    }),
    refresh,
  };
}

export type LinkAction = "replace" | "unlink" | "remove";
export type FixScope = "this" | "page" | "course";

export interface FixParams {
  text?: string;
  decorative?: boolean;
  level?: number;
  lang?: string;
  url?: string;
  unlink?: boolean;
  link_action?: LinkAction;
  link_text?: string;
  scope?: FixScope;
  options?: string[];
  /** The text is (based on) a KI-forslag the teacher reviewed – the change is marked as KI-generated. */
  ai_suggestion?: boolean;
}

/** «Foreslå … med KI» for a finding's text field (link text, table caption, the title of embedded content). */
export const findingAi = {
  prepare: (findingId: number, href?: string) =>
    api.post<import("./AiSuggestion").AiTextPlan>(`/api/findings/${findingId}/ai-suggestion/prepare`, { href }),
  run: (findingId: number, confirmed: boolean, avoid: string[], href?: string) =>
    api.post<import("./AiSuggestion").AiTextResult>(`/api/findings/${findingId}/ai-suggestion`, { confirmed, avoid, href }),
};

export interface FixPreview {
  kind: string;
  before_display: string;
  after_display: string;
  preview_html: string;
  risk: string;
  existing_change_id: number | null;
  /** The changed elements only (targeted edits): what the reviewer needs to see first. */
  changes: { before: string; after: string }[];
  targeted: boolean;
  count: number;
  occurrences: number;
  where: BlueprintWhere;
  related: { finding_id: number; object_type: string; object_id: string; object_title: string; module?: string }[];
}

export interface StagedFix {
  id: number;
  status: string;
  also_staged: { id: number }[];
  errors: { finding_id: number; object_title: string; message: string }[];
}

export function fixPreview(id: number, params: FixParams) {
  return api.post<FixPreview>(`/api/findings/${id}/fix/preview`, params);
}

export function fixStage(id: number, params: FixParams) {
  return api.post<StagedFix>(`/api/findings/${id}/fix/stage`, params);
}

/** «Godkjenn»: the fix goes into the change queue as approved, ready for «Publiser til Canvas». */
export function fixApprove(id: number, params: FixParams) {
  return api.post<StagedFix>(`/api/findings/${id}/fix/approve`, params);
}

export function bulkApprove(courseId: string, findingIds: number[], includeTextSuggestions: boolean) {
  return api.post<{ job: Job; planned: number; skipped: { finding_id: number; reason: string }[] }>("/api/findings/fix/bulk", {
    course_id: courseId,
    finding_ids: findingIds,
    include_text_suggestions: includeTextSuggestions,
  });
}

/* ------------------------------------------------------------------------- KI-forslag til alt-tekst */

export interface AltPlan {
  available: boolean;
  reason: string | null;
  payload_summary: string | null;
  needs_confirmation: boolean;
  external?: boolean;
  route: { provider: string; model: string; reason: string } | null;
  images?: number;
  already_ready?: number;
  to_send?: number;
  queue?: AltQueueState;
}

export interface AltQueueState {
  queued: number;
  running: number;
  job_id: string | null;
  consented: boolean;
}

export const altText = {
  prepareBatch: (courseId: string, findingIds: number[] = []) =>
    api.post<AltPlan>("/api/ai/tasks/alt-text/batch/prepare", { course_id: courseId, finding_ids: findingIds }),
  startBatch: (courseId: string, findingIds: number[] = []) =>
    api.post<{ added: number; queue: AltQueueState }>("/api/ai/tasks/alt-text/batch/start", {
      course_id: courseId,
      finding_ids: findingIds,
      confirmed: true,
    }),
  prioritize: (courseId: string, findingIds: number[]) =>
    api.post<{ added: number; allowed: boolean; queue: AltQueueState }>("/api/ai/tasks/alt-text/prioritize", {
      course_id: courseId,
      finding_ids: findingIds,
    }),
  retry: (findingId: number) => api.post<{ queue: AltQueueState }>("/api/ai/tasks/alt-text/retry", { finding_id: findingId }),
  cancel: (courseId: string) => api.post<{ queue: AltQueueState }>(`/api/courses/${courseId}/alt-text/cancel`),
};

/** Suggestion status for the given findings; polls while anything is queued or running. */
export function useAltStatus(courseId: string | null, ids: number[]) {
  return useQuery({
    queryKey: ["alt-text", courseId, ids],
    queryFn: () =>
      api.get<{ items: Record<string, AltSuggestion>; queue: AltQueueState }>(
        `/api/courses/${courseId}/alt-text/status${qs({ ids: ids.map(String) })}`,
      ),
    enabled: Boolean(courseId) && ids.length > 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const busy = data.queue.queued + data.queue.running > 0 ||
        Object.values(data.items).some((s) => s.status === "queued" || s.status === "running");
      return busy ? 1_500 : false;
    },
  });
}
