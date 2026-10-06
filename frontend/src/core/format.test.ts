import { describe, expect, it } from "vitest";

import { fromLocalInput, toLocalInput } from "../features/quiz-assistant/QuizBuilder";
import { formatDuration, formatDurationRange, plural } from "./format";

describe("format helpers", () => {
  it("uses singular and plural forms", () => {
    expect(plural(1, "quiz", "quizer")).toBe("1 quiz");
    expect(plural(3, "quiz", "quizer")).toBe("3 quizer");
  });

  it("formats durations without fake precision", () => {
    expect(formatDuration(134)).toMatch(/2 min 14 sek/);
    expect(formatDurationRange(60, 180)).toMatch(/1.*3 min/);
  });
});

describe("quiz date fields", () => {
  it("round-trips local datetime input values through ISO (UTC)", () => {
    const iso = fromLocalInput("2026-11-02T23:59");
    expect(iso).toMatch(/Z$/);
    expect(toLocalInput(iso)).toBe("2026-11-02T23:59");
    expect(fromLocalInput("")).toBeNull();
    expect(toLocalInput(null)).toBe("");
  });
});
