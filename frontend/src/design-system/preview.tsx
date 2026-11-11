/*
 * Renders (already server-sanitised) Canvas HTML inside a sandboxed iframe.
 * The sandbox has no allow-scripts and no allow-same-origin, so even if
 * sanitisation missed something, the content cannot run code or reach the
 * app. This is the ONLY way Canvas content is displayed as HTML.
 */
import { useLayoutEffect, useMemo, useRef, useState } from "react";

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

/**
 * A small, scaled picture of the top of a page: the content is laid out at `width` × `height` CSS pixels and scaled
 * down to the available width, with no scrolling inside – always from the top. It is a picture only (hidden from
 * assistive technology and not focusable); offer the same content in an {@link HtmlPreview} for reading.
 */
export function ScaledPreview({ html, width = 720, height = 440 }: { html: string; width?: number; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.45);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const update = () => {
      if (el.clientWidth > 0) setScale(Math.min(1, el.clientWidth / width));
    };
    update();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [width]);
  const srcDoc = useMemo(
    () =>
      `<!doctype html><html lang="nb"><head><meta charset="utf-8"><style>${BASE_CSS} html, body { overflow: hidden; }</style></head><body>${html}</body></html>`,
    [html],
  );
  return (
    <div ref={box} className="ek-preview-scaled" style={{ height: `${Math.round(height * scale)}px`, maxWidth: `${width}px` }}>
      <iframe
        className="ek-preview-scaled__frame"
        title="Eksempel (bilde)"
        aria-hidden="true"
        tabIndex={-1}
        sandbox=""
        referrerPolicy="no-referrer"
        scrolling="no"
        srcDoc={srcDoc}
        style={{ width: `${width}px`, height: `${height}px`, transform: `scale(${scale})` }}
      />
    </div>
  );
}

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
