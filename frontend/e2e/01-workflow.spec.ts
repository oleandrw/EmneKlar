// The core workflow: analyse → explain → suggest → preview → approve → change → log.
import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("analyse, preview a fix, queue it, apply it and find it in the change log", async ({ page }) => {
  await login(page);

  // Kjør ny analyse (header) → dialog with scope and areas.
  await page.getByRole("banner").getByRole("button", { name: "Kjør ny analyse" }).click();
  const dialog = page.getByRole("dialog", { name: /analyse/i });
  await expect(dialog.getByRole("radio", { name: "Hele emnet" })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: /Quizkvalitet/ })).not.toBeChecked();
  await dialog.getByRole("button", { name: "Start analyse" }).click();
  await expect(dialog.getByText("Fullført", { exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(dialog.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  await dialog.getByRole("button", { name: "Lukk" }).first().click();

  // Universell utforming → a missing alt text.
  await page.getByRole("navigation", { name: /hoved/i }).getByRole("link", { name: "Universell utforming" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Universell utforming" })).toBeVisible();
  await page.getByRole("button", { name: /Vis og rett\s*: Bilde mangler alternativ tekst/ }).first().click();
  const detail = page.getByRole("dialog", { name: "Bilde mangler alternativ tekst" });
  await expect(detail.getByRole("heading", { name: "Hvorfor det er viktig" })).toBeVisible();
  await detail.getByLabel("Alternativ tekst").fill("Skjermbilde som sammenligner raster- og vektorgrafikk");
  await expect(detail.getByRole("button", { name: "Legg endring til kø" })).toBeDisabled();
  await detail.getByRole("button", { name: "Forhåndsvis løsning" }).click();
  await expect(detail.getByText(/raster- og vektorgrafikk/).first()).toBeVisible();
  await detail.getByRole("button", { name: "Legg endring til kø" }).click();
  await expect(page.getByText("Endringen er lagt i endringskøen")).toBeVisible();

  // Endringskø → approve and apply.
  await page.getByRole("button", { name: /endring(er)? klar/ }).click();
  const drawer = page.getByRole("dialog", { name: "Endringskø" });
  await expect(drawer.getByText("1 UU-retting")).toBeVisible();
  await drawer.getByRole("button", { name: /^Gjennomfør\s*:/ }).first().click();
  await expect(drawer.getByText(/Gjennomført/).first()).toBeVisible({ timeout: 30_000 });
  await drawer.getByRole("button", { name: "Lukk" }).first().click();

  // Backup og endringslogg shows the change with undo.
  await page.goto("/canvas-verktoy/endringslogg");
  await expect(page.getByRole("heading", { level: 1, name: "Backup og endringslogg" })).toBeVisible();
  await expect(page.getByText("Gjennomført").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^Angre/ }).first()).toBeVisible();
});

test("Dry run blocks writes but keeps previews and the queue working", async ({ page }) => {
  await login(page);
  const dryRun = page.getByRole("switch", { name: /Dry run/ });
  await dryRun.click();
  await expect(dryRun).toHaveAttribute("aria-checked", "true");
  await page.goto("/canvas-verktoy/modulkrav");
  await page.getByRole("button", { name: "Forhåndsvis" }).click();
  await expect(page.getByRole("heading", { name: "Forhåndsvisning" })).toBeVisible();
  await page.getByRole("button", { name: /^Legg \d+ endringer i kø/ }).click();
  const drawer = page.getByRole("dialog", { name: "Endringskø" });
  await drawer.getByRole("checkbox").first().check();
  await drawer.getByRole("button", { name: /Gjennomfør valgte/ }).click();
  await expect(drawer.getByText(/Dry run – ikke sendt/).first()).toBeVisible({ timeout: 30_000 });
  await drawer.getByRole("button", { name: "Lukk" }).first().click();
  await page.getByRole("switch", { name: /Dry run/ }).click();
});
