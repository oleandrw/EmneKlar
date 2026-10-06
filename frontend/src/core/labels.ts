// Shared Norwegian labels for domain values. Keep wording here so every
// screen describes the same concept the same way.
import type { Tone } from "../design-system";

export type Domain = "accessibility" | "content_quality" | "structure" | "quiz" | "quiz_ai";
/** Areas in the analysis dialog (AI quiz reviews are started from the Quiz Assistant). */
export type AnalysisDomain = Exclude<Domain, "quiz_ai">;
export type Classification = "violation" | "likely_violation" | "should_review" | "improvement" | "manual_check";
export type TestMethod = "deterministic" | "heuristic" | "ai" | "manual";
export type Severity = "critical" | "serious" | "moderate" | "minor" | "info";
export type Confidence = "high" | "medium" | "low";

export const DOMAIN_LABEL: Record<Domain, string> = {
  accessibility: "Universell utforming",
  content_quality: "Innholdskvalitet",
  structure: "Emnestruktur",
  quiz: "Quizkvalitet",
  quiz_ai: "Quizkvalitet (KI-vurdering)",
};

export const CLASSIFICATION: Record<Classification, { label: string; tone: Tone; description: string }> = {
  violation: {
    label: "Avvik",
    tone: "danger",
    description: "Bryter et suksesskriterium etter en deterministisk kontroll.",
  },
  likely_violation: {
    label: "Sannsynlig avvik",
    tone: "warning",
    description: "Tyder sterkt på brudd, men bør bekreftes av et menneske.",
  },
  should_review: {
    label: "Bør vurderes",
    tone: "info",
    description: "Kan være et problem avhengig av sammenhengen.",
  },
  improvement: {
    label: "Forbedringsforslag",
    tone: "teal",
    description: "God praksis som gjør innholdet bedre, men ikke et krav.",
  },
  manual_check: {
    label: "Manuell kontroll",
    tone: "violet",
    description: "Kan ikke avgjøres automatisk. Et menneske må kontrollere.",
  },
};

export const TEST_METHOD: Record<TestMethod, { label: string; description: string }> = {
  deterministic: { label: "Deterministisk", description: "Sikker, regelbasert kontroll av koden." },
  heuristic: { label: "Heuristisk", description: "Mønstergjenkjenning. Kan gi falske treff." },
  ai: { label: "KI-assistert", description: "Forslag fra en språkmodell. Må alltid vurderes." },
  manual: { label: "Manuell", description: "Krever menneskelig vurdering." },
};

export const SEVERITY: Record<Severity, { label: string; tone: Tone }> = {
  critical: { label: "Kritisk", tone: "danger" },
  serious: { label: "Alvorlig", tone: "warning" },
  moderate: { label: "Moderat", tone: "info" },
  minor: { label: "Lav", tone: "neutral" },
  info: { label: "Info", tone: "neutral" },
};

export const CONFIDENCE: Record<Confidence, string> = {
  high: "Høy",
  medium: "Middels",
  low: "Lav",
};

export const OBJECT_TYPE: Record<string, string> = {
  page: "Side",
  front_page: "Forside",
  assignment: "Oppgave",
  discussion: "Diskusjon",
  quiz: "Quiz",
  quiz_question: "Quizspørsmål",
  syllabus: "Emneplan",
  file: "Fil",
  module: "Modul",
  module_item: "Modulelement",
  course: "Emne",
  announcement: "Kunngjøring",
};

export const RISK: Record<string, { label: string; tone: Tone }> = {
  low: { label: "Lav risiko", tone: "success" },
  medium: { label: "Middels risiko", tone: "warning" },
  high: { label: "Høy risiko", tone: "danger" },
};

export const UNDO: Record<string, string> = {
  full: "Kan angres",
  partial: "Kan delvis angres",
  none: "Kan ikke angres automatisk",
};

export const LEGAL_STATUS: Record<string, { label: string; tone: Tone }> = {
  required: { label: "Lovkrav i valgt profil", tone: "danger" },
  conditional: { label: "Lovkrav under vilkår", tone: "warning" },
  not_required: { label: "Ikke lovkrav i valgt profil", tone: "neutral" },
  best_practice: { label: "Anbefalt praksis", tone: "teal" },
  none: { label: "Ikke knyttet til et krav", tone: "neutral" },
};
