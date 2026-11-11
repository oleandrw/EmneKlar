import { describe, expect, it } from "vitest";

import { classificationFor, confirmedLikelyLabels } from "./labels";

describe("class labels per area", () => {
  it("says «avvik» only for universal design", () => {
    expect(classificationFor("violation", "accessibility").label).toBe("Avvik");
    expect(classificationFor("likely_violation", "accessibility").label).toBe("Sannsynlig avvik");
    expect(classificationFor("violation", "accessibility").description).toMatch(/suksesskriterium/);
    for (const domain of ["content_quality", "structure", "quiz", "quiz_ai"]) {
      expect(classificationFor("violation", domain).label).toBe("Feil");
      expect(classificationFor("likely_violation", domain).label).toBe("Sannsynlig feil");
      expect(classificationFor("violation", domain).description).not.toMatch(/suksesskriterium|WCAG|universell/i);
    }
    // The other classes have the same words everywhere.
    expect(classificationFor("should_review", "quiz").label).toBe("Bør vurderes");
    expect(classificationFor("manual_check", "content_quality").label).toBe("Manuell kontroll");
  });

  it("names the headline pair for the area", () => {
    expect(confirmedLikelyLabels("accessibility").confirmed).toBe("Bekreftede avvik");
    expect(confirmedLikelyLabels("quiz").confirmed).toBe("Bekreftede feil");
    expect(confirmedLikelyLabels("quiz").likely(1)).toBe("sannsynlig feil");
    expect(confirmedLikelyLabels("accessibility").likely(2)).toBe("sannsynlige avvik");
  });
});
