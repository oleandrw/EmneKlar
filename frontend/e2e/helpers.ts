import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

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

/** Starts the analysis from the open dialog: the dialog closes, «Analysestatus» at the top right opens as the
 *  confirmation (focus stays where it was), and the job ends as «Fullført». Optionally checks the panel with axe. */
export async function runAnalysis(page: Page, dialog: Locator, axeContext?: string): Promise<void> {
  await dialog.getByRole("button", { name: "Start analyse" }).click();
  await expect(dialog).toBeHidden();
  const status = page.getByRole("region", { name: "Analysestatus" });
  await expect(status).toBeVisible();
  await expect(status.getByRole("listitem").first()).toContainText("Fullført", { timeout: 45_000 });
  await expect(status.getByRole("listitem").first()).toContainText("kontrollert");
  if (axeContext) await expectNoAxeViolations(page, axeContext);
  await page.getByRole("button", { name: "Lukk analysestatus" }).click();
  await expect(status).toBeHidden();
}
