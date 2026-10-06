// Types for API payloads shared across features.
import type { AnalysisDomain, Classification, Confidence, Domain, Severity, TestMethod } from "../labels";

export interface SessionData {
  csrf_token: string;
  app: { name: string; version: string };
  setup_completed: boolean;
  dry_run: boolean;
  current_course_id: string | null;
  canvas: { base_url: string | null; token_configured: boolean; identity: { id: string; name: string } | null };
  general: {
    language: string;
    theme: "light" | "dark" | "system";
    start_page: string;
    default_course_id: string | null;
    page_size: number;
  };
  appearance: {
    text_size: "normal" | "large" | "larger";
    density: "comfortable" | "compact";
    reduce_motion: "system" | "always";
    underline_links: boolean;
  };
  notifications: { notify_job_complete: boolean; browser_notifications: boolean };
  flags: Record<string, boolean>;
  ai: { external_allowed: boolean; confirm_before_send: boolean; providers_enabled: string[] };
  regulatory_profile: string;
  analysis: { default_domains: AnalysisDomain[] };
}

export interface Course {
  id: string;
  name: string;
  course_code: string | null;
  term_name: string | null;
  workflow_state: string | null;
  is_blueprint: boolean;
  default_view: string | null;
  roles: string[];
}

export interface JobProgress {
  phase: string;
  phase_label: string;
  phase_index: number;
  phase_count: number;
  determinate: boolean;
  percent: number | null;
  done: number;
  total: number;
  types: Record<string, { label: string; total: number; done: number; failed: number }>;
  current_item: string | null;
  current_operation: string | null;
  findings: Record<string, number>;
  eta: {
    state: "calculating" | "estimate" | "range" | "done";
    seconds?: number | null;
    low_seconds?: number | null;
    high_seconds?: number | null;
    confidence?: string | null;
  };
  in_flight: number;
  messages: string[];
}

export interface Job {
  id: string;
  kind: string;
  course_id: string | null;
  title: string;
  status: "queued" | "running" | "pausing" | "paused" | "cancelling" | "completed" | "failed" | "cancelled" | "interrupted";
  params?: { domains?: string[]; scope?: string } & Record<string, unknown>;
  supports_pause: boolean;
  error: string | null;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: JobProgress;
}

export interface Finding {
  id: number;
  run_id: number;
  domain: Domain;
  rule_id: string;
  ruleset_version: string | null;
  category: string;
  classification: Classification;
  test_method: TestMethod;
  severity: Severity;
  confidence: Confidence;
  title: string;
  message: string;
  object_type: string | null;
  object_id: string | null;
  object_title: string | null;
  object_url: string | null;
  location: { snippet?: string; context?: string; selector?: string; module?: string };
  evidence: Record<string, unknown>;
  remediation: string;
  fix: { type: string; label: string; params?: Record<string, unknown> } | null;
  status: "open" | "ignored" | "staged" | "fixed";
  created_at: string;
  fingerprint?: string;
  category_label?: string;
  rule?: RuleInfo;
  legal?: { status: string; note?: string | null; profile_title: string };
}

export interface RuleInfo {
  id: string;
  title: string;
  category: string;
  category_label: string;
  classification: string;
  wcag: string[];
  wcag_titles: Record<string, string>;
  wcag_version: string | null;
  level: string | null;
  testability: TestMethod;
  severity: Severity;
  explanation: string;
  affected_users: string;
  sources: { title: string; url: string }[];
  fix_policy: string;
  ruleset_version: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
