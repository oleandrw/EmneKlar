// The chart series are graphical objects (WCAG 1.4.11): each needs ≥ 3:1 against the card surface it is drawn on,
// in both themes. jsdom computes no colours, so the values are read from tokens.css itself.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const styles = join(dirname(fileURLToPath(import.meta.url)), "styles");
const css = readFileSync(join(styles, "tokens.css"), "utf-8");
const components = readFileSync(join(styles, "components.css"), "utf-8") + readFileSync(join(styles, "base.css"), "utf-8");

/** The custom properties a block declares (any value). */
function declared(selector: string): Set<string> {
  const start = css.indexOf(selector);
  const open = css.indexOf("{", start);
  const body = css.slice(open + 1, css.indexOf("\n}", open));
  return new Set([...body.matchAll(/(--[\w-]+):/g)].map((m) => m[1]));
}

/** The declarations of the first block whose selector list contains `selector`. */
function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  const body = css.slice(open + 1, css.indexOf("\n}", open));
  const values: Record<string, string> = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b/g)) values[m[1]] = m[2].toLowerCase();
  return values;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const SERIES = ["--chart-violation", "--chart-likely", "--chart-review", "--chart-improvement", "--chart-manual"];

describe("chart colours", () => {
  it("measures contrast like WCAG", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#e08a1e", "#ffffff")).toBeLessThan(3); // the old «Bør vurderes» amber
  });

  for (const [theme, selector] of [["light", ':root[data-theme="light"]'], ["dark", ':root[data-theme="dark"]']] as const) {
    it(`has ≥ 3:1 for every series on the ${theme} card surface`, () => {
      const tokens = block(selector);
      const surface = tokens["--color-surface"];
      expect(surface).toBeDefined();
      const ratios = Object.fromEntries(SERIES.map((name) => [name, Number(contrast(tokens[name], surface).toFixed(2))]));
      for (const name of SERIES) expect(ratios[name], `${theme} ${name}`).toBeGreaterThanOrEqual(3);
    });
  }

  it("defines every shadow level the components use, in both themes – no fallback hides a missing one", () => {
    const used = new Set([...components.matchAll(/var\((--shadow[\w-]*)/g)].map((m) => m[1]));
    expect([...used].sort()).toEqual(["--shadow", "--shadow-hover", "--shadow-lg", "--shadow-md", "--shadow-pop", "--shadow-sm"]);
    const base = declared(":root {");
    const dark = declared(':root[data-theme="dark"]');
    for (const name of used) {
      expect(base.has(name), `${name} in the light/base tokens`).toBe(true);
      expect(dark.has(name), `${name} in the dark tokens`).toBe(true);
    }
    expect(components).not.toMatch(/var\(--shadow[\w-]*,/);
  });

  it("uses the type scale for text sizes, not hard-coded pixels", () => {
    expect(components).not.toMatch(/font-size:\s*\d+px/);
  });

  it("keeps «Bør vurderes» at ≥ 3:1 on the light page plane too", () => {
    const light = block(':root[data-theme="light"]');
    expect(contrast(light["--chart-review"], light["--color-bg"])).toBeGreaterThanOrEqual(3);
  });
});
