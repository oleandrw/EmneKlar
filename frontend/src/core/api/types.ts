// Types for API payloads shared across features.
import type { AnalysisDomain, Classification, Confidence, Domain, Severity, TestMethod } from "../labels";

export interface SessionData {
  csrf_token: string;
  app: { name: string; version: string };
  setup_completed: boolean;
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
  /** Marked as a favourite in the course selector (stored in EmneKlar, not in Canvas). */
  favorite?: boolean;
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
  /** Bumped on every change – the newest snapshot of a job wins when two sources disagree. */
  version?: number;
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
  course_id?: string;
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
  location: {
    snippet?: string;
    context?: string;
    selector?: string;
    module?: string;
    modules?: string[];
    module_id?: string;
    module_item_id?: string;
  };
  evidence: Record<string, unknown>;
  remediation: string;
  fix: { type: string; label: string; params?: Record<string, unknown> } | null;
  status: "open" | "ignored" | "verified" | "staged" | "fixed";
  created_at: string;
  fingerprint?: string;
  /** The teacher's decision («Ignorer» or «Kontrollert» with the confirmation chosen), when there is one. */
  decision?: FindingDecision | null;
  category_label?: string;
  rule?: RuleInfo;
  legal?: { status: string; note?: string | null; profile_title: string };
  /** Direct links into Canvas (view, edit, module item, view with the finding's text highlighted). */
  canvas?: CanvasLinks;
  /** True for image findings that can get a KI-forslag til alt-tekst. */
  image?: boolean;
  alt_suggestion?: AltSuggestion | null;
  /** «automatic» = the fix needs no input; «suggestion» = a text suggestion is ready; null = the teacher decides. */
  ready?: "automatic" | "suggestion" | null;
  /** Why the link's address cannot work (e.g. text pasted into the address field), when that is clear. */
  href_problem?: string | null;
}

export interface CanvasLinks {
  view: string | null;
  edit: string | null;
  module_item: string | null;
  module?: string | null;
  highlight: string | null;
}

export interface AltSuggestion {
  status: "none" | "queued" | "running" | "ready" | "failed" | "stale";
  suggestion?: string;
  decorative?: boolean;
  image_kind?: string | null;
  confidence?: string | null;
  notes?: string | null;
  provider?: string | null;
  model?: string | null;
  error?: string | null;
  label?: string;
}

export interface BlueprintWhere {
  course_id: string;
  course_name: string | null;
  role: "blueprint" | "associated" | "course";
  locked: boolean;
  parent: { id: string; name: string | null; course_code?: string | null } | null;
  associated_course_count: number | null;
  sync_needed: boolean;
  message: string;
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
  /** What the teacher can confirm after checking by hand – marks the finding «Kontrollert». */
  confirmations?: RuleConfirmation[];
  /** Media rules: the teacher can state what the recording is (audio only, video with or without sound). */
  media_kind_choice?: boolean;
}

export interface RuleConfirmation {
  id: string;
  label: string;
  hint: string;
  /** Offered only when the finding's evidence has this key (e.g. «exemption_hint» for older documents). */
  requires_evidence?: string | null;
}

export interface FindingDecision {
  decision: "ignored" | "verified";
  reason: string | null;
  note: string | null;
  created_at: string | null;
  /** The confirmation's label («Transkripsjonen finnes …») for «Kontrollert». */
  label: string | null;
}

export type MediaKind = "audio" | "video" | "video_no_audio";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
