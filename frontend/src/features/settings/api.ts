import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../core/api/client";
import type { AnalysisDomain } from "../../core/labels";
import { useToast } from "../../design-system";

export interface FlagInfo {
  key: string;
  name: string;
  description: string;
  stage: "stable" | "beta" | "experimental";
  default_on: boolean;
  enabled: boolean;
  overridden: boolean;
}

export interface AppSettings {
  setup_completed: boolean;
  dry_run: boolean;
  current_course_id: string | null;
  general: { language: string; theme: "light" | "dark" | "system"; start_page: string; default_course_id: string | null; page_size: number };
  canvas: { base_url: string | null; identity: { id: string; name: string } | null; last_verified_at: string | null };
  analysis: {
    default_domains: AnalysisDomain[];
    regulatory_profile: string;
    check_external_links: boolean;
    link_timeout_seconds: number;
    link_concurrency: number;
    link_per_host: number;
    link_cache_hours: number;
    check_documents: boolean;
    max_document_mb: number;
    canvas_concurrency: number;
    include_unpublished: boolean;
  };
  privacy: { allow_external_ai: boolean; confirm_before_send: boolean; snapshot_retention_days: number };
  appearance: { text_size: "normal" | "large" | "larger"; density: "comfortable" | "compact"; reduce_motion: "system" | "always"; underline_links: boolean };
  notifications: { notify_job_complete: boolean; browser_notifications: boolean };
  advanced: {
    feature_flags: Record<string, boolean>;
    update_repository: string | null;
    update_channel: "stable" | "prerelease";
    check_updates: boolean;
    debug_logging: boolean;
  };
}

export interface SettingsPayload {
  settings: AppSettings;
  flags: FlagInfo[];
  version: string;
  data_dir: string;
}

export type Section = "general" | "analysis" | "privacy" | "appearance" | "notifications" | "advanced";

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<SettingsPayload>("/api/settings") });
}

export function useSaveSettings(section: Section) {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<SettingsPayload>(`/api/settings/${section}`, body),
    onSuccess: (data) => {
      client.setQueryData(["settings"], data);
      void client.invalidateQueries({ queryKey: ["session"] });
      toast.show({ tone: "success", title: "Innstillingene er lagret" });
    },
  });
}
