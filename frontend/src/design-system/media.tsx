// Images in feature pages (generated illustrations, thumbnails) and a clickable step list for wizards.
import type { ReactNode } from "react";

import { cx } from "./primitives";

/** A framed image. `size="thumb"` is a fixed 3:2 tile for overviews; `"large"` scales to the available width. */
export function ImageFrame({
  src,
  alt,
  size = "large",
  caption,
  placeholder,
}: {
  src: string | null;
  alt: string;
  size?: "thumb" | "large";
  caption?: ReactNode;
  /** Shown when there is no image yet (e.g. «Ikke generert»). */
  placeholder?: ReactNode;
}) {
  return (
    <figure className="ek-image" data-size={size}>
      {src ? (
        <img src={src} alt={alt} loading="lazy" />
      ) : (
        <div className="ek-image__placeholder">{placeholder ?? "Ingen bilde"}</div>
      )}
      {caption ? <figcaption className="ek-image__caption">{caption}</figcaption> : null}
    </figure>
  );
}

export interface StepItem<T extends string> {
  id: T;
  label: string;
  done?: boolean;
  disabled?: boolean;
}

/** Vertical step navigation (uses the wizard styles of the set-up wizard); steps can be revisited. */
export function Stepper<T extends string>({
  steps,
  current,
  onSelect,
  label,
}: {
  steps: StepItem<T>[];
  current: T;
  onSelect: (id: T) => void;
  label: string;
}) {
  return (
    <nav aria-label={label}>
      <ol className="ek-steps">
        {steps.map((step, index) => (
          <li
            key={step.id}
            className={cx("ek-steps__item", "ek-steps__item--button")}
            aria-current={step.id === current ? "step" : undefined}
            data-done={step.done ? "true" : undefined}
          >
            <button type="button" className="ek-steps__button" onClick={() => onSelect(step.id)} disabled={step.disabled}>
              <span className="ek-steps__num" aria-hidden="true">
                {index + 1}
              </span>
              <span>
                {step.label}
                {step.done ? <span className="ek-visually-hidden"> (fullført)</span> : null}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
