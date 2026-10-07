// Developer helper (not a test): screenshots of EmneKlar pages for visual comparison with the design mockups.
//   node e2e/screenshot.mjs <origin> <outDir> [path ...] [--width 1440] [--height 1086] [--dark] [--full]
// Logs in with the dev preview token, so it only works against tests/fakes/dev_server.py.
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? args.splice(i, 2)[1] : fallback;
};
const has = (name) => {
  const i = args.indexOf(name);
  if (i >= 0) args.splice(i, 1);
  return i >= 0;
};
const width = Number(flag("--width", "1440"));
const height = Number(flag("--height", "1086"));
const dark = has("--dark");
const full = has("--full");
const [origin, outDir, ...paths] = args;
if (!origin || !outDir) {
  console.error("Bruk: node e2e/screenshot.mjs <origin> <outDir> [path ...]");
  process.exit(1);
}
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width, height }, colorScheme: dark ? "dark" : "light" });
await page.goto(`${origin}/auth/launch?token=dev-preview-token`);
await page.getByRole("heading", { level: 1 }).waitFor();
for (const path of paths.length ? paths : ["/oversikt"]) {
  await page.goto(`${origin}${path}`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.waitForTimeout(600);
  const name = `${path.replace(/^\//, "").replace(/\//g, "_") || "root"}${dark ? "-dark" : ""}-${width}.png`;
  await page.screenshot({ path: join(outDir, name), fullPage: full });
  console.log(join(outDir, name));
}
await browser.close();
