/*
 * Labelled form controls. Every control has a visible <label> (or fieldset
 * legend); hints and errors are associated with aria-describedby, and errors
 * set aria-invalid. Errors use an icon + text, never colour alone.
 */
import { CircleAlert } from "lucide-react";
import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cx, type Tone } from "./primitives";

interface FieldBase {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  optional?: boolean;
  hideLabel?: boolean;
}

function useFieldIds(id?: string) {
  const generated = useId();
  const controlId = id ?? `f-${generated}`;
  return { controlId, hintId: `${controlId}-hint`, errorId: `${controlId}-error` };
}

function describedBy(hint: unknown, error: unknown, ids: { hintId: string; errorId: string }, extra?: string) {
  const parts = [hint ? ids.hintId : null, error ? ids.errorId : null, extra ?? null].filter(Boolean);
  return parts.length ? parts.join(" ") : undefined;
}

function FieldShell({
  label,
  hint,
  error,
  optional,
  hideLabel,
  ids,
  children,
}: FieldBase & { ids: ReturnType<typeof useFieldIds>; children: ReactNode }) {
  return (
    <div className="ek-field">
      <label className={cx("ek-label", hideLabel && "ek-visually-hidden")} htmlFor={ids.controlId}>
        {label}
        {optional ? <span className="ek-label__optional"> (valgfritt)</span> : null}
      </label>
      {hint ? (
        <p className="ek-hint" id={ids.hintId}>
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p className="ek-error" id={ids.errorId}>
          <CircleAlert aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

export const TextField = forwardRef<
  HTMLInputElement,
  FieldBase & Omit<InputHTMLAttributes<HTMLInputElement>, "size">
>(function TextField(
  { label, hint, error, optional, hideLabel, id, className, "aria-describedby": extraDescribedBy, ...rest },
  ref,
) {
  const ids = useFieldIds(id);
  return (
    <FieldShell label={label} hint={hint} error={error} optional={optional} hideLabel={hideLabel} ids={ids}>
      <input
        ref={ref}
        id={ids.controlId}
        className={cx("ek-input", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint, error, ids, extraDescribedBy)}
        {...rest}
      />
    </FieldShell>
  );
});

export const TextArea = forwardRef<HTMLTextAreaElement, FieldBase & TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function TextArea({ label, hint, error, optional, hideLabel, id, className, ...rest }, ref) {
    const ids = useFieldIds(id);
    return (
      <FieldShell label={label} hint={hint} error={error} optional={optional} hideLabel={hideLabel} ids={ids}>
        <textarea
          ref={ref}
          id={ids.controlId}
          className={cx("ek-textarea", className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(hint, error, ids)}
          {...rest}
        />
      </FieldShell>
    );
  },
);

export interface Option {
  value: string;
  label: string;
  disabled?: boolean;
}

export const SelectField = forwardRef<
  HTMLSelectElement,
  FieldBase & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; placeholder?: string }
>(function SelectField({ label, hint, error, optional, hideLabel, id, className, options, placeholder, ...rest }, ref) {
  const ids = useFieldIds(id);
  return (
    <FieldShell label={label} hint={hint} error={error} optional={optional} hideLabel={hideLabel} ids={ids}>
      <select
        ref={ref}
        id={ids.controlId}
        className={cx("ek-select", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint, error, ids)}
        {...rest}
      >
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
});

export function Checkbox({
  label,
  hint,
  className,
  ...rest
}: { label: ReactNode; hint?: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const hintId = useId();
  return (
    <label className={cx("ek-choice", className)}>
      <input type="checkbox" aria-describedby={hint ? hintId : undefined} {...rest} />
      <span className="ek-choice__text">
        <span>{label}</span>
        {hint ? (
          <span className="ek-choice__hint ek-small" id={hintId}>
            {hint}
          </span>
        ) : null}
      </span>
    </label>
  );
}

export function Fieldset({
  legend,
  hint,
  error,
  children,
  hideLegend,
}: {
  legend: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  hideLegend?: boolean;
}) {
  const hintId = useId();
  const errorId = useId();
  return (
    <fieldset
      className="ek-fieldset"
      aria-describedby={[hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined}
    >
      <legend className={cx("ek-legend", hideLegend && "ek-visually-hidden")}>{legend}</legend>
      {hint ? (
        <p className="ek-hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p className="ek-error" id={errorId}>
          <CircleAlert aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : null}
    </fieldset>
  );
}

export interface RadioOption<T extends string> {
  value: T;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  /** Card variant only: a decorative icon in a tile of this tone. */
  icon?: ReactNode;
  tone?: Tone;
}

export function RadioGroup<T extends string>({
  legend,
  name,
  value,
  onChange,
  options,
  hint,
  error,
  variant = "plain",
  hideLegend,
  columns = 1,
}: {
  legend: ReactNode;
  name: string;
  value: T;
  onChange: (value: T) => void;
  options: RadioOption<T>[];
  hint?: ReactNode;
  error?: ReactNode;
  variant?: "plain" | "card";
  hideLegend?: boolean;
  /** Card variant: choices side by side (fewer columns on narrow screens). */
  columns?: 1 | 2 | 3 | 4;
}) {
  const choices = options.map((option) => (
    <RadioChoice
      key={option.value}
      name={name}
      option={option}
      checked={value === option.value}
      onSelect={() => onChange(option.value)}
      variant={variant}
    />
  ));
  return (
    <Fieldset legend={legend} hint={hint} error={error} hideLegend={hideLegend}>
      {columns > 1 ? (
        <div className="ek-choice-grid" data-cols={columns}>
          {choices}
        </div>
      ) : (
        choices
      )}
    </Fieldset>
  );
}

function RadioChoice<T extends string>({
  name,
  option,
  checked,
  onSelect,
  variant,
}: {
  name: string;
  option: RadioOption<T>;
  checked: boolean;
  onSelect: () => void;
  variant: "plain" | "card";
}) {
  const hintId = useId();
  return (
    <label className={cx("ek-choice", variant === "card" && "ek-choice--card")}>
      <input
        type="radio"
        name={name}
        value={option.value}
        checked={checked}
        disabled={option.disabled}
        onChange={onSelect}
        aria-describedby={option.hint ? hintId : undefined}
      />
      {variant === "card" && option.icon ? (
        <span className="ek-tile" data-tone={option.tone ?? "info"} data-size="sm" aria-hidden="true">
          {option.icon}
        </span>
      ) : null}
      <span className="ek-choice__text">
        <span>{option.label}</span>
        {option.hint ? (
          <span className="ek-choice__hint ek-small" id={hintId}>
            {option.hint}
          </span>
        ) : null}
      </span>
    </label>
  );
}

/** An on/off switch (role="switch"). The visible label is part of the button. */
export function Switch({
  label,
  checked,
  onChange,
  disabled,
  showState = true,
  describedBy: describedById,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  showState?: boolean;
  describedBy?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={describedById}
      className="ek-switch"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="ek-switch__track" aria-hidden="true">
        <span className="ek-switch__thumb" />
      </span>
      <span>{label}</span>
      {showState ? (
        <span className="ek-switch__state" aria-hidden="true">
          {checked ? "På" : "Av"}
        </span>
      ) : null}
    </button>
  );
}
