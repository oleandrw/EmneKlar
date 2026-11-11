import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";

export interface Change {
  id: number;
  course_id: string;
  course_name?: string | null;
  domain: string;
  kind: string;
  kind_label: string;
  title: string;
  target: {
    object_type?: string;
    object_id?: string;
    title?: string;
    url?: string | null;
    module?: string | null;
    module_id?: string;
    item_type?: string;
    moved_from?: { course_id: string; change_id: number };
  };
  before: Record<string, unknown>;
  proposed: Record<string, unknown>;
  rationale: string;
  risk: "low" | "medium" | "high";
  undo_capability: "full" | "partial" | "none";
  undo_note: string;
  conflict_status: "not_checked" | "ok" | "conflict";
  status: "staged" | "approved" | "applying" | "applied" | "failed" | "conflict" | "discarded" | "undone";
  requires_confirmation: boolean;
  editable: boolean;
  ai_generated: boolean;
  source: Record<string, unknown>;
  fix_count: number;
  rebuildable: boolean;
  result: {
    error_category?: "blueprint" | "permission" | "not_found" | "network" | "auth" | null;
    blueprint?: { locked_by?: { id: string; name: string | null } | null; sync_needed?: boolean; associated_course_count?: number | null };
    after?: Record<string, unknown>;
    already_stored?: boolean;
  } & Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string | null;
  applied_at: string | null;
}

export interface ChangeSummary {
  pending: number;
  approved: number;
  problems: number;
  courses: number;
  by_domain: Record<string, number>;
  by_status: Record<string, number>;
}

export interface ChangeList {
  items: Change[];
  groups: { domain: string; label: string; count: number }[];
  courses: { course_id: string; name: string | null; count: number; approved: number; problems: number }[];
  summary: ChangeSummary;
  publishing_job: Job | null;
}

export interface PublishResult {
  change_id: number;
  status: "applied" | "failed" | "conflict" | string;
  message?: string;
  course_id: string;
  title: string;
  error_category?: string | null;
  rebuildable?: boolean;
  skipped?: boolean;
  kind?: string;
  /** Blueprint sync: the Canvas migration to follow until it is finished. */
  migration_id?: string | null;
  blueprint?: { sync_needed?: boolean; associated_course_count?: number | null; locked_by?: { id: string; name: string | null } | null };
}

/** The whole queue across courses – «Én samlet endringskø». */
export function useChanges(enabled = true) {
  return useQuery({
    queryKey: ["changes", "list"],
    queryFn: () => api.get<ChangeList>("/api/changes"),
    enabled,
  });
}

export function useChangeMutations() {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["changes"] });
    void client.invalidateQueries({ queryKey: ["findings"] });
    void client.invalidateQueries({ queryKey: ["changelog"] });
    void client.invalidateQueries({ queryKey: ["overview"] });
    void client.invalidateQueries({ queryKey: ["links"] });
  };
  return {
    refresh,
    approve: useMutation({ mutationFn: (ids: number[]) => api.post("/api/changes/approve", { ids }), onSuccess: refresh }),
    unapprove: useMutation({ mutationFn: (ids: number[]) => api.post("/api/changes/unapprove", { ids }), onSuccess: refresh }),
    discard: useMutation({ mutationFn: (id: number) => api.delete(`/api/changes/${id}`), onSuccess: refresh }),
    conflicts: useMutation({
      mutationFn: (ids: number[]) => api.post<{ items: Change[] }>("/api/changes/check-conflicts", { ids }),
      onSuccess: refresh,
    }),
    rebuild: useMutation({ mutationFn: (id: number) => api.post<Change>(`/api/changes/${id}/rebuild`), onSuccess: refresh }),
    apply: useMutation({
      mutationFn: ({ ids, confirm }: { ids: number[]; confirm: boolean }) =>
        api.post<Job>("/api/changes/apply", { ids, confirm_high_risk: confirm }),
    }),
    edit: useMutation({
      mutationFn: ({ id, proposed }: { id: number; proposed: Record<string, unknown> }) =>
        api.patch<Change>(`/api/changes/${id}`, { proposed }),
      onSuccess: refresh,
    }),
    moveToBlueprint: useMutation({
      mutationFn: (id: number) => api.post<{ moved: Change; sync: Change }>(`/api/changes/${id}/blueprint-move`),
      onSuccess: refresh,
    }),
    stageSync: useMutation({
      mutationFn: (courseId: string) => api.post<Change>(`/api/courses/${courseId}/blueprint/sync/stage`),
      onSuccess: refresh,
    }),
  };
}

export interface BlueprintMovePlan {
  parent: { id: string; name: string | null };
  object_id: string;
  before_display: string;
  after_display: string;
  associated_course_count: number | null;
  associated_courses: { id: string; name: string | null }[];
  note: string;
}

export function useBlueprintMovePlan(changeId: number | null) {
  return useQuery({
    queryKey: ["changes", "blueprint-move", changeId],
    queryFn: () => api.get<BlueprintMovePlan>(`/api/changes/${changeId}/blueprint-move`),
    enabled: changeId !== null,
    retry: false,
  });
}

export interface SyncStatus {
  id: string;
  workflow_state: string;
  finished: boolean;
  failed: boolean;
  label: string;
}

export function useSyncStatus(courseId: string | null, migrationId: string | null) {
  return useQuery({
    queryKey: ["blueprint-sync", courseId, migrationId],
    queryFn: () => api.get<SyncStatus>(`/api/courses/${courseId}/blueprint/migrations/${migrationId}`),
    enabled: Boolean(courseId && migrationId),
    refetchInterval: (query) => (query.state.data?.finished ? false : 5_000),
  });
}

const BLOCK = "(p|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|div|figure|figcaption|iframe|blockquote|section|caption)";

/** Line-broken HTML for diffs (display only). */
export function formatHtml(html: string): string {
  return (html || "")
    .replace(new RegExp(`(<${BLOCK}\\b)`, "gi"), "\n$1")
    .replace(new RegExp(`(</${BLOCK}>)`, "gi"), "$1\n")
    .split("\n")
    .map((l) => l.trimEnd())
    .filter((l) => l.trim())
    .join("\n");
}

export const HTML_FIELDS = ["body", "description", "message", "syllabus_body"];
