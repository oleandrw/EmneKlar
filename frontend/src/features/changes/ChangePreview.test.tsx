import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Change } from "./api";
import { ChangePreview } from "./ChangePreview";

function change(partial: Partial<Change>): Change {
  return {
    id: 1, course_id: "101", domain: "canvas", kind: "module_item.update", kind_label: "Endre modulelement",
    title: "Modulkrav: Velkommen", target: { object_type: "module_item", object_id: "1001", title: "Velkommen" },
    before: {}, proposed: {}, rationale: "", risk: "medium", undo_capability: "full", undo_note: "",
    conflict_status: "not_checked", status: "staged", requires_confirmation: false, editable: false, ai_generated: false,
    source: {}, result: {}, error: null, created_at: null, updated_at: null, applied_at: null,
    ...partial,
  } as Change;
}

describe("ChangePreview", () => {
  it("shows completion requirements in Norwegian", () => {
    render(<ChangePreview change={change({ before: { completion_requirement: null }, proposed: { completion_requirement: { type: "must_view" } } })} />);
    expect(screen.getByRole("rowheader", { name: "Fullføringskrav" })).toBeInTheDocument();
    expect(screen.getByText("Se på elementet")).toBeInTheDocument();
  });

  it("summarises a new quiz instead of dumping its plan", () => {
    render(<ChangePreview change={change({
      kind: "quiz.create",
      proposed: {
        title: "Ukequiz", questions: [{ stem: "Hva er JPEG?" }, { stem: "Hva er SVG?" }],
        summary: { questions_total: 2, questions_asked: 1, points_possible: 2, published: false },
        warnings: ["Poengregel brukes bare når studentene har flere forsøk."],
      },
    })} />);
    expect(screen.getByText("1 av 2 (tilfeldig utvalg)")).toBeInTheDocument();
    expect(screen.getByText("Upublisert")).toBeInTheDocument();
    expect(screen.getByText(/Poengregel/)).toBeInTheDocument();
    expect(screen.getByText("Hva er SVG?")).toBeInTheDocument();
  });

  it("shows the answer key before and after for quiz question edits", () => {
    render(<ChangePreview change={change({
      kind: "quiz_question.update",
      before: { question_text: "<p>PNG støtter gjennomsiktighet.</p>", answers: [{ text: "Sant", correct: true }, { text: "Usant", correct: false }] },
      proposed: { question_text: "<p>PNG støtter gjennomsiktighet.</p>", answers: [{ text: "Sant", correct: false }, { text: "Usant", correct: true }] },
    })} />);
    expect(screen.getByText("Svaralternativer nå")).toBeInTheDocument();
    expect(screen.getByText("Foreslåtte svaralternativer")).toBeInTheDocument();
    expect(screen.getAllByText("Riktig")).toHaveLength(2);
  });
});
