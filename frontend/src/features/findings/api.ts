import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, qs } from "../../core/api/client";
import type { Finding } from "../../core/api/types";

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
  total: number;
  page: number;
  page_size: number;
  summary: {
    total: number;
    ignored: number;
    fixed: number;
    staged: number;
    by_classification: Record<string, number>;
    by_category: Record<string, number>;
    actionable: number;
  };
  categories: { id: string; label: string }[];
  runs: RunInfo[];
  profile: { id: string; title: string; version: string };
}

export interface FindingFilters {
  classification: string[];
  category: string[];
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

export function useFindingActions() {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["findings"] });
    void client.invalidateQueries({ queryKey: ["overview"] });
    void client.invalidateQueries({ queryKey: ["changes"] });
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
    refresh,
  };
}

export interface FixParams {
  text?: string;
  decorative?: boolean;
  level?: number;
  lang?: string;
}

export interface FixPreview {
  kind: string;
  before_display: string;
  after_display: string;
  preview_html: string;
  risk: string;
  existing_change_id: number | null;
}

export function fixPreview(id: number, params: FixParams) {
  return api.post<FixPreview>(`/api/findings/${id}/fix/preview`, params);
}

export function fixStage(id: number, params: FixParams) {
  return api.post<{ id: number }>(`/api/findings/${id}/fix/stage`, params);
}
