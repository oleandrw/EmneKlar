// Standardiser videoavspillere (Innholdskvalitet → Media): find videos, preview on PC/nettbrett/mobil and queue the
// change – with axe on the tab and on the detail dialog. YouTube metadata may be unavailable here; that is allowed.
import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, login, runAnalysis } from "./helpers";

test("Media: finn videoer, forhåndsvis og legg endringen i køen", async ({ page }) => {
  await login(page);
  await page.goto("/oversikt");
  await page.getByRole("banner").getByRole("button", { name: "Analyser hele emnet" }).click();
  await runAnalysis(page, page.getByRole("dialog", { name: /analyse/i }));

  await page.goto("/innholdskvalitet");
  await page.getByRole("tab", { name: "Media" }).click();
  await page.getByRole("button", { name: /^(Finn videoer|Skann videoene på nytt)$/ }).click();
  await expect(page.getByRole("heading", { name: /YouTube-videoe?r? funnet/ })).toBeVisible({ timeout: 45_000 });
  await page.waitForLoadState("networkidle");
  await expectNoAxeViolations(page, "Innholdskvalitet → Media");

  await page.getByRole("button", { name: /^Vis detaljer\s*: .*Video og medier/ }).click();
  const detail = page.getByRole("dialog", { name: "Video" });
  await expect(detail.getByRole("heading", { name: "Nåværende" })).toBeVisible();
  await expect(detail.getByText(/^Kilde: /).first()).toBeVisible();
  await expect(detail.getByRole("button", { name: "Godkjenn" })).toBeDisabled();
  await detail.getByRole("button", { name: "Forhåndsvis" }).click();
  await expect(detail.getByRole("heading", { name: "Forhåndsvisning" })).toBeVisible({ timeout: 30_000 });
  await detail.getByRole("button", { name: "Mobil" }).click();
  await expect(detail.getByRole("button", { name: "Mobil" })).toHaveAttribute("aria-pressed", "true");
  await expectNoAxeViolations(page, "videodetaljer med forhåndsvisning");
  await detail.getByRole("button", { name: "Godkjenn" }).click();
  await expect(page.getByText("Videoen er lagt i endringskøen")).toBeVisible();
});
