// Quiz Assistant API: existing Classic Quizzes, KI-spørsmålsbank, presets and the quiz builder.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AiPlan } from "../../core/ai";
import { api, qs } from "../../core/api/client";
import type { Finding, Job } from "../../core/api/types";

export interface QuizSummary {
  id: string;
  title: string;
  quiz_type: string | null;
  published: boolean | null;
  question_count: number | null;
  points_possible: number | null;
  html_url: string | null;
  open_findings: number;
}

export interface QuizAnswer {
  id?: string;
  text: string;
  correct: boolean;
  weight?: number;
}

export interface QuizQuestion {
  id: string;
  name: string;
  type: string;
  type_label: string;
  text: string;
  points: number;
  group_id: string | null;
  position: number;
  answers: QuizAnswer[];
}

export interface QuizDetail {
  quiz: { id: string; title: string; html_url: string | null; settings: Record<string, unknown>; groups: { id: string; name: string; pick_count: number; assessment_question_bank_id: string | null }[] };
  questions: QuizQuestion[];
  findings: Finding[];
}

export type QuestionType = "single_choice" | "multiple_answers" | "true_false";
export type ReviewStatus = "draft" | "approved" | "rejected";

export interface BankItem {
  id: number;
  question_type: QuestionType;
  type_label: string;
  stem: string;
  answers: QuizAnswer[];
  explanation: string;
  sources: { object_ref: string; title: string; chunk_id: string; quote: string }[];
  module_id: string | null;
  module_name: string | null;
  topic: string;
  difficulty: "easy" | "medium" | "hard";
  review_status: ReviewStatus;
  origin: "ai" | "manual";
  grounding: "verified" | "partial" | "unverified";
  generator: { provider?: string; model?: string; route_reason?: string };
  used_in: { quiz_id: string | null; title: string | null; html_url: string | null }[];
  created_at: string | null;
}

export interface Coverage {
  modules: { module: string; module_id: string | null; words: number; approved: number; draft: number; rejected: number; level: string }[];
  total: { approved: number; draft: number; rejected: number };
}

export interface QuizSettings {
  quiz_type: "practice_quiz" | "assignment" | "graded_survey" | "survey";
  time_limit: number | null;
  shuffle_answers: boolean;
  allowed_attempts: number;
  scoring_policy: "keep_highest" | "keep_latest";
  show_correct_answers: boolean;
  show_correct_answers_last_attempt: boolean;
  hide_results: "always" | "until_after_last_attempt" | null;
  one_question_at_a_time: boolean;
  cant_go_back: boolean;
  due_at: string | null;
  unlock_at: string | null;
  lock_at: string | null;
  published: boolean;
}

export interface Preset {
  id: number;
  name: string;
  settings: QuizSettings;
  builtin: boolean;
  is_default: boolean;
}

export interface BuildRequest {
  title: string;
  description: string;
  settings: QuizSettings;
  question_ids: number[];
  pick_count: number | null;
  points_per_question: number;
  group_name: string;
  module_id: string | null;
}

export interface BuildPreview {
  summary: { questions_total: number; questions_asked: number; points_possible: number; published: boolean };
  warnings: string[];
  group: { name: string; pick_count: number; question_points: number } | null;
  questions: { stem: string; type: string }[];
}

export const DIFFICULTY: Record<string, string> = { easy: "Lett", medium: "Middels", hard: "Vanskelig" };
export const REVIEW_STATUS: Record<ReviewStatus, { label: string; tone: "neutral" | "success" | "danger" }> = {
  draft: { label: "Til vurdering", tone: "neutral" },
  approved: { label: "Godkjent", tone: "success" },
  rejected: { label: "Avvist", tone: "danger" },
};
export const QUESTION_TYPES: { value: QuestionType; label: string }[] = [
  { value: "single_choice", label: "Enkeltvalg (ett riktig svar)" },
  { value: "multiple_answers", label: "Flere riktige svar" },
  { value: "true_false", label: "Sant/usant" },
];
export const QUIZ_TYPES: { value: QuizSettings["quiz_type"]; label: string }[] = [
  { value: "practice_quiz", label: "Øvingsquiz (gir ikke karakter)" },
  { value: "assignment", label: "Vurdert quiz" },
  { value: "graded_survey", label: "Vurdert spørreundersøkelse" },
  { value: "survey", label: "Spørreundersøkelse" },
];
export const COVERAGE_LEVEL: Record<string, { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info" }> = {
  no_content: { label: "Lite tekst å bygge på", tone: "neutral" },
  none: { label: "Ingen godkjente spørsmål", tone: "danger" },
  low: { label: "Lav dekning", tone: "warning" },
  medium: { label: "Middels dekning", tone: "info" },
  good: { label: "God dekning", tone: "success" },
};

export function useQuizzes(courseId: string | null) {
  return useQuery({
    queryKey: ["quizzes", courseId],
    queryFn: () => api.get<{ quizzes: QuizSummary[] }>(`/api/courses/${courseId}/quizzes`),
    enabled: Boolean(courseId),
  });
}

export function useQuizDetail(courseId: string | null, quizId: string | null) {
  return useQuery({
    queryKey: ["quiz", courseId, quizId],
    queryFn: () => api.get<QuizDetail>(`/api/courses/${courseId}/quizzes/${quizId}`),
    enabled: Boolean(courseId && quizId),
  });
}

export function prepareReview(courseId: string, quizId: string) {
  return api.post<AiPlan>(`/api/courses/${courseId}/quizzes/${quizId}/review/prepare`);
}

export function startReview(courseId: string, quizId: string, body: { use_ai: boolean; confirmed: boolean }) {
  return api.post<Job>(`/api/courses/${courseId}/quizzes/${quizId}/review`, body);
}

export interface BankFilters {
  status: string;
  module: string;
  q: string;
}

export function useBank(courseId: string | null, filters: BankFilters) {
  return useQuery({
    queryKey: ["bank", courseId, filters],
    queryFn: () =>
      api.get<{ items: BankItem[]; counts: Record<ReviewStatus, number> }>(
        `/api/courses/${courseId}/bank${qs({ status: filters.status, module: filters.module, q: filters.q })}`,
      ),
    enabled: Boolean(courseId),
  });
}

export function useCoverage(courseId: string | null) {
  return useQuery({
    queryKey: ["bank-coverage", courseId],
    queryFn: () => api.get<Coverage>(`/api/courses/${courseId}/bank/coverage`),
    enabled: Boolean(courseId),
  });
}

export function useBankMutations(courseId: string | null) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["bank"] });
    void client.invalidateQueries({ queryKey: ["bank-coverage"] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Partial<BankItem>) => api.post<BankItem>(`/api/courses/${courseId}/bank`, body),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Partial<BankItem> & { id: number }) => api.patch<BankItem>(`/api/bank/${id}`, body),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.delete(`/api/bank/${id}`), onSuccess: refresh }),
    refresh,
  };
}

export function usePresets() {
  return useQuery({ queryKey: ["quiz-presets"], queryFn: () => api.get<{ presets: Preset[] }>("/api/quiz/presets") });
}
