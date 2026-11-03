import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";

export interface Change {
  id: number;
  course_id: string;
  domain: string;
  kind: string;
  kind_label: string;
  title: string;
  target: { object_type?: string; object_id?: string; title?: string; url?: string; module_id?: string; item_type?: string };
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
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string | null;
  applied_at: string | null;
}

export interface ChangeList {
  items: Change[];
  groups: { domain: string; label: string; count: number }[];
  dry_run: boolean;
}

export function useChanges(courseId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["changes", "list", courseId],
    queryFn: () => api.get<ChangeList>(`/api/changes${courseId ? `?course_id=${courseId}` : ""}`),
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
  };
  return {
    refresh,
    approve: useMutation({ mutationFn: (ids: number[]) => api.post("/api/changes/approve", { ids }), onSuccess: refresh }),
    discard: useMutation({ mutationFn: (id: number) => api.delete(`/api/changes/${id}`), onSuccess: refresh }),
    conflicts: useMutation({
      mutationFn: (ids: number[]) => api.post<{ items: Change[] }>("/api/changes/check-conflicts", { ids }),
      onSuccess: refresh,
    }),
    apply: useMutation({
      mutationFn: ({ ids, confirm }: { ids: number[]; confirm: boolean }) =>
        api.post<Job>("/api/changes/apply", { ids, confirm_high_risk: confirm }),
    }),
    edit: useMutation({
      mutationFn: ({ id, proposed }: { id: number; proposed: Record<string, unknown> }) =>
        api.patch<Change>(`/api/changes/${id}`, { proposed }),
      onSuccess: refresh,
    }),
  };
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
