// The core workflow: analyse → find → context → fix → approve → publish (to the fake Canvas) → log.
import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, login, runAnalysis } from "./helpers";

test("analyse, fix alt text beside the image, approve, publish and find it in the change log", async ({ page }) => {
  await login(page);

  // The one analysis button follows the page: «Analyser hele emnet» on Oversikt → dialog with scope and areas.
  await page.goto("/oversikt");
  await expect(page.getByRole("button", { name: /^Analyser/ })).toHaveCount(1);
  await page.getByRole("banner").getByRole("button", { name: "Analyser hele emnet" }).click();
  const dialog = page.getByRole("dialog", { name: /analyse/i });
  await expect(dialog.getByRole("radio", { name: "Hele emnet" })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: /Quizkvalitet/ })).not.toBeChecked();
  await runAnalysis(page, dialog, "analysestatus (ferdig analyse)");

  // Universell utforming → a missing alt text: the image, its context and the Canvas links in one view.
  await page.getByRole("navigation", { name: /hoved/i }).getByRole("link", { name: "Universell utforming" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Universell utforming" })).toBeVisible();
  await page.getByRole("button", { name: /Vis og rett\s*: Bilde mangler alternativ tekst/ }).first().click();
  const detail = page.getByRole("dialog", { name: "Bilde mangler alternativ tekst" });
  await expect(detail.getByRole("heading", { name: "Hvor" })).toBeVisible();
  await expect(detail.getByRole("img", { name: /Bildet som vurderes/ })).toBeVisible();
  await expect(detail.getByRole("link", { name: /Åpne i Canvas/ })).toHaveAttribute("target", "_blank");
  await expectNoAxeViolations(page, "funn-detalj (alt-tekst)");
  await detail.getByLabel("Alternativ tekst").fill("Skjermbilde som sammenligner raster- og vektorgrafikk");
  await expect(detail.getByText("Bare dette elementet endres")).toBeVisible();
  await detail.getByRole("button", { name: /^Godkjenn/ }).click();
  await expect(page.getByText("Godkjent – ligger i endringskøen")).toBeVisible();
  await page.keyboard.press("Escape"); // the detail has moved on to the next finding

  // Endringskø → publish everything approved, with a short confirmation.
  await page.getByRole("button", { name: /klar til publisering/ }).click();
  const drawer = page.getByRole("dialog", { name: "Endringskø" });
  await expect(drawer.getByText("1 UU-retting")).toBeVisible();
  await expectNoAxeViolations(page, "endringskø");
  await drawer.getByRole("button", { name: "Publiser til Canvas (1)" }).click();
  const confirm = page.getByRole("dialog", { name: "Publiser til Canvas" });
  await expect(confirm.getByText(/Digital kompetanse for lærere/)).toBeVisible();
  await confirm.getByRole("button", { name: "Publiser 1 endring" }).click();
  await expect(drawer.getByText("Resultat av publiseringen")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("Publisert").first()).toBeVisible();
  await drawer.getByRole("button", { name: "Lukk" }).first().click();

  // Sikkerhetskopier og endringslogg shows the change with undo.
  await page.goto("/canvas-verktoy/endringslogg");
  await expect(page.getByRole("heading", { level: 1, name: "Sikkerhetskopier og endringslogg" })).toBeVisible();
  await expect(page.getByText("Publisert").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^Angre/ }).first()).toBeVisible();
});

test("a dead link is fixed from «Brukt i»: remove the link, keep the text", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("switch", { name: /Dry run/ })).toHaveCount(0);
  await page.goto("/innholdskvalitet");
  // On an area page the same header button analyses only that area.
  await expect(page.getByRole("button", { name: /^Analyser/ })).toHaveCount(1);
  await page.getByRole("banner").getByRole("button", { name: "Analyser innholdskvalitet" }).click();
  await expect(page.getByRole("dialog", { name: "Analyser innholdskvalitet" }).getByRole("checkbox")).toHaveCount(0);
  await runAnalysis(page, page.getByRole("dialog", { name: /analyse/i }));

  await page.getByRole("tab", { name: "Lenker" }).click();
  const row = page.getByRole("row", { name: /example\.org\/missing/ });
  await row.getByRole("button", { name: /^Brukt på/ }).click();
  await expect(row.getByRole("link", { name: /Bildeformater/ })).toHaveAttribute("href", /\/courses\/101\/pages\/bildeformater/);
  await row.getByRole("button", { name: /^Rett funnet\s?: .* i Bildeformater$/ }).click();
  const detail = page.getByRole("dialog", { name: "Lenken fungerer ikke" });
  await detail.getByRole("radio", { name: /Fjern lenken, behold teksten/ }).check();
  await expect(detail.getByText("Bare dette elementet endres")).toBeVisible();
  await detail.getByRole("button", { name: /^Godkjenn/ }).click();
  await expect(page.getByText("Godkjent – ligger i endringskøen")).toBeVisible();
});
