// Images in feature pages (generated illustrations, thumbnails) and a clickable step list for wizards.
import { Check, ChevronRight } from "lucide-react";
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

function StepContent<T extends string>({ step, index, current }: { step: StepItem<T>; index: number; current: T }) {
  return (
    <>
      <span className="ek-steps__num" aria-hidden="true">
        {step.done && step.id !== current ? <Check size={14} /> : index + 1}
      </span>
      <span>
        {step.label}
        {step.done ? <span className="ek-visually-hidden"> (fullført)</span> : null}
      </span>
    </>
  );
}

/** Step navigation; steps can be revisited, and a disabled step cannot be skipped to.
 *  `orientation="horizontal"`: one row above the content («1 Omfang → 2 Design → …»); on narrow screens it becomes
 *  one line, «Steg 1 av 4 – Omfang» (the wizard then needs its own back buttons). Without `onSelect` it only shows
 *  progress (no buttons) – for flows where a step must not be skipped to, such as the setup. */
export function Stepper<T extends string>({
  steps,
  current,
  onSelect,
  label,
  orientation = "vertical",
}: {
  steps: StepItem<T>[];
  current: T;
  onSelect?: (id: T) => void;
  label: string;
  orientation?: "vertical" | "horizontal";
}) {
  const horizontal = orientation === "horizontal";
  const index = Math.max(0, steps.findIndex((s) => s.id === current));
  return (
    <nav aria-label={label} className={cx(horizontal && "ek-stepper--horizontal")}>
      {horizontal ? (
        <p className="ek-stepper__compact">
          Steg {index + 1} av {steps.length} – {steps[index]?.label}
        </p>
      ) : null}
      <ol className={cx("ek-steps", horizontal && "ek-steps--horizontal")}>
        {steps.map((step, i) => (
          <li
            key={step.id}
            className={cx("ek-steps__item", "ek-steps__item--button")}
            aria-current={step.id === current ? "step" : undefined}
            data-done={step.done ? "true" : undefined}
          >
            {onSelect ? (
              <button type="button" className="ek-steps__button" onClick={() => onSelect(step.id)} disabled={step.disabled}>
                <StepContent step={step} index={i} current={current} />
              </button>
            ) : (
              <span className="ek-steps__button ek-steps__button--static">
                <StepContent step={step} index={i} current={current} />
              </span>
            )}
            {horizontal && i < steps.length - 1 ? (
              <ChevronRight className="ek-steps__sep" aria-hidden="true" size={16} />
            ) : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}
