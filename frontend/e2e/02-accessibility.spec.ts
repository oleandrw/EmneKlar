// Automated accessibility checks (axe, WCAG 2.2 A/AA) of every main page, in light and dark theme,
// on desktop and mobile, plus keyboard basics. Automated checks do not replace manual testing.
import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, login } from "./helpers";

const PAGES: [string, string][] = [
  ["/oversikt", "Oversikt"],
  ["/universell-utforming", "Universell utforming"],
  ["/innholdskvalitet", "Innholdskvalitet"],
  ["/emnestruktur", "Emnestruktur"],
  ["/quizassistent", "Quizassistent"],
  ["/quizassistent/sporsmalsbank", "Quizassistent"],
  ["/quizassistent/ny-quiz", "Quizassistent"],
  ["/emneforside", "Emneforside"],
  ["/canvas-verktoy", "Canvas-verktøy"],
  ["/canvas-verktoy/modulkrav", "Automatiske modulkrav"],
  ["/canvas-verktoy/blueprint", "Blueprint-låsing"],
  ["/canvas-verktoy/innstillinger", "Canvas-innstillinger"],
  ["/canvas-verktoy/endringslogg", "Backup og endringslogg"],
  ["/canvas-verktoy/emne-rag", "Emne-RAG"],
  ["/rapporter", "Rapporter"],
  ["/innstillinger/generelt", "Innstillinger"],
  ["/innstillinger/ki-assistenter", "Innstillinger"],
  ["/innstillinger/sikkerhet-og-personvern", "Innstillinger"],
  ["/innstillinger/avanserte-innstillinger", "Innstillinger"],
  ["/hjelp/kom-i-gang", "Hjelp"],
  ["/hjelp/brukerveiledninger", "Hjelp"],
];

test.describe("axe – lyst tema", () => {
  for (const [path, heading] of PAGES) {
    test(path, async ({ page }) => {
      await login(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectNoAxeViolations(page, path);
    });
  }
});

test("axe – Emne-RAG: «Tilpass kilder»", async ({ page }) => {
  await login(page);
  await page.goto("/canvas-verktoy/emne-rag");
  await page.getByRole("button", { name: "Tilpass kilder" }).click();
  const panel = page.getByRole("dialog", { name: "Tilpass kilder" });
  await expect(panel.getByRole("heading", { name: "Avansert" })).toBeVisible();
  await expectNoAxeViolations(page, "emne-rag-tilpass-kilder");
  await panel.getByRole("button", { name: "Avbryt" }).click();
  await expect(page.getByRole("button", { name: "Tilpass kilder" })).toBeFocused();
});

test("axe – mørkt tema og dialoger", async ({ page }) => {
  await login(page);
  await page.goto("/innstillinger/generelt");
  await page.getByLabel("Tema").selectOption("dark");
  await page.getByRole("button", { name: "Lagre" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  for (const path of ["/oversikt", "/universell-utforming", "/emneforside", "/innstillinger/ki-assistenter"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expectNoAxeViolations(page, `${path} (mørkt tema)`);
  }
  await page.getByRole("banner").getByRole("button", { name: "Kjør ny analyse" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoAxeViolations(page, "analysedialog (mørkt tema)");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.goto("/innstillinger/generelt");
  await page.getByLabel("Tema").selectOption("light");
  await page.getByRole("button", { name: "Lagre" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("tastatur: hopp til hovedinnhold og synlig fokus", async ({ page }) => {
  await login(page);
  await page.goto("/oversikt");
  // Wait until the page has rendered and settled: the app moves focus to the page heading after (client-side)
  // navigation, and on slower machines that can happen after a too-early blur and steal the first Tab.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  // Start from the top of the document.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: /hovedinnhold/i });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  // The global analysis dialog traps focus and returns it to the opener.
  const opener = page.getByRole("banner").getByRole("button", { name: "Kjør ny analyse" });
  await opener.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
});

test.describe("mobil", () => {
  test.use({ viewport: { width: 375, height: 812 } });
  test("navigasjonen er tilgjengelig som meny, og sidene består axe", async ({ page }) => {
    await login(page);
    await page.goto("/oversikt");
    const menu = page.getByRole("button", { name: /meny/i });
    await expect(menu).toBeVisible();
    await menu.click();
    await expect(page.getByRole("dialog").getByRole("link", { name: "Rapporter" })).toBeVisible();
    await page.getByRole("dialog").getByRole("link", { name: "Rapporter" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Rapporter" })).toBeVisible();
    await expectNoAxeViolations(page, "/rapporter (mobil)");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "ingen horisontal rulling på mobil").toBeLessThanOrEqual(1);
  });
});

test.describe("mobil – alle sider", () => {
  test.use({ viewport: { width: 375, height: 812 } });
  test("ingen side gir horisontal rulling", async ({ page }) => {
    await login(page);
    const overflowing: string[] = [];
    for (const [path] of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 1) overflowing.push(`${path} (+${overflow}px)`);
    }
    expect(overflowing).toEqual([]);
  });
});
