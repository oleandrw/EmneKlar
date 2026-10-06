import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const LOGIN = "/auth/launch?token=dev-preview-token";

export async function login(page: Page): Promise<void> {
  await page.goto(LOGIN);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

/** WCAG 2.2 A/AA rules that can be tested automatically. Content inside sandboxed previews is excluded. */
export async function expectNoAxeViolations(page: Page, context: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .exclude("iframe.ek-preview__frame")
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("\n  ")}`,
  );
  expect(summary, `axe-brudd på ${context}`).toEqual([]);
}
