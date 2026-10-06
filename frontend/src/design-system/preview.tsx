/*
 * Renders (already server-sanitised) Canvas HTML inside a sandboxed iframe.
 * The sandbox has no allow-scripts and no allow-same-origin, so even if
 * sanitisation missed something, the content cannot run code or reach the
 * app. This is the ONLY way Canvas content is displayed as HTML.
 */
import { useMemo } from "react";

export type PreviewDevice = "desktop" | "tablet" | "mobile";

const WIDTHS: Record<PreviewDevice, number> = { desktop: 1100, tablet: 768, mobile: 375 };

// Approximates Canvas's content styles so previews look close to the real page.
const BASE_CSS = `
  html { font-family: "Lato", "Segoe UI", system-ui, sans-serif; color: #273540; line-height: 1.5; }
  body { margin: 0; padding: 18px 22px; font-size: 16px; background: #fff; }
  h1, h2, h3, h4 { line-height: 1.25; color: #273540; }
  a { color: #0e68b3; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; }
  td, th { border: 1px solid #c7cdd1; padding: 4px 8px; }
  iframe { max-width: 100%; border: 1px dashed #8b96a0; background: #f5f5f5; }
  .ek-preview-placeholder { display: block; padding: 12px; border: 1px dashed #8b96a0; background: #f5f5f5; color: #3d4a55; }
`;

export function HtmlPreview({
  html,
  title,
  device = "desktop",
  minHeight = 420,
}: {
  html: string;
  /** Accessible name of the frame, e.g. «Forhåndsvisning av forsiden». */
  title: string;
  device?: PreviewDevice;
  minHeight?: number;
}) {
  const srcDoc = useMemo(
    () =>
      `<!doctype html><html lang="nb"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${BASE_CSS}</style></head><body>${html}</body></html>`,
    [html],
  );
  const width = WIDTHS[device];
  return (
    <div className="ek-preview">
      <iframe
        className="ek-preview__frame"
        title={title}
        sandbox=""
        referrerPolicy="no-referrer"
        srcDoc={srcDoc}
        style={{ maxWidth: `${width}px`, minHeight: `${minHeight}px`, height: `${minHeight}px` }}
      />
    </div>
  );
}
