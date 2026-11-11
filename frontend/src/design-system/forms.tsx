/*
 * Labelled form controls. Every control has a visible <label> (or fieldset
 * legend); hints and errors are associated with aria-describedby, and errors
 * set aria-invalid. Errors use an icon + text, never colour alone.
 */
import { Check, ChevronDown, CircleAlert, Eye, EyeOff, X } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cx, Disclosure, type Tone } from "./primitives";

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
  return { controlId, labelId: `${controlId}-label`, hintId: `${controlId}-hint`, errorId: `${controlId}-error` };
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
      <label id={ids.labelId} className={cx("ek-label", hideLabel && "ek-visually-hidden")} htmlFor={ids.controlId}>
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

/** A secret (token, key): hidden by default, with an eye button inside the right end of the field. The button never
 * submits the form or clears the field, and its name says what it does («Vis …» / «Skjul …»). The text never runs
 * under the button. */
export const PasswordField = forwardRef<
  HTMLInputElement,
  FieldBase & Omit<InputHTMLAttributes<HTMLInputElement>, "size" | "type"> & { revealLabel?: string; concealLabel?: string }
>(function PasswordField(
  { label, hint, error, optional, hideLabel, id, className, revealLabel = "Vis", concealLabel = "Skjul",
    "aria-describedby": extraDescribedBy, ...rest },
  ref,
) {
  const ids = useFieldIds(id);
  const [shown, setShown] = useState(false);
  const toggleLabel = shown ? concealLabel : revealLabel;
  return (
    <FieldShell label={label} hint={hint} error={error} optional={optional} hideLabel={hideLabel} ids={ids}>
      <div className="ek-input-affix">
        <input
          ref={ref}
          id={ids.controlId}
          type={shown ? "text" : "password"}
          className={cx("ek-input", "ek-input--affix", className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(hint, error, ids, extraDescribedBy)}
          autoComplete="off"
          spellCheck={false}
          {...rest}
        />
        <button type="button" className="ek-input-affix__button" aria-label={toggleLabel} title={toggleLabel}
          aria-controls={ids.controlId} onClick={() => setShown((v) => !v)}>
          {shown ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </button>
      </div>
    </FieldShell>
  );
});


/** One choice in a {@link Combobox}: the main line, and an optional smaller line under it (code, term …). */
export interface ComboboxOption {
  value: string;
  label: string;
  meta?: string;
}

/** `text` with every occurrence of the search marked (bold and underlined – not by colour alone). */
function marked(text: string, query: string): ReactNode {
  const needle = query.trim().toLowerCase();
  if (!needle) return text;
  const lower = text.toLowerCase();
  const parts: ReactNode[] = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at} className="ek-combobox__match">{text.slice(at, at + needle.length)}</mark>);
    from = at + needle.length;
  }
  if (!parts.length) return text;
  if (from < text.length) parts.push(text.slice(from));
  return parts;
}

/**
 * One field for choosing among many (ARIA 1.2 combobox: an input and a listbox). Clicking it, or ↓, opens the list;
 * typing searches it. The list shows a few options at a time and scrolls; ↑/↓ move, Enter chooses, Esc closes, and the
 * matching text is marked. The chosen option stays in the field – a long name wraps instead of being cut – and the ×
 * button empties the choice. A search without matches says so instead of showing an empty list.
 */
export function Combobox({
  label,
  hint,
  error,
  optional,
  hideLabel,
  id,
  options,
  value,
  onChange,
  search,
  placeholder,
  clearLabel = "Fjern valget",
  noResults = "Fant ingen treff",
}: FieldBase & {
  id?: string;
  options: ComboboxOption[];
  /** The chosen option's value; "" when nothing is chosen. */
  value: string;
  onChange: (value: string) => void;
  /** The options that match a typed text, best first. Default: the text is in the label or in the smaller line. */
  search?: (query: string) => ComboboxOption[];
  placeholder?: string;
  clearLabel?: string;
  noResults?: string;
}) {
  const ids = useFieldIds(id);
  const listId = `${ids.controlId}-list`;
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const chosen = options.find((o) => o.value === value) ?? null;
  const results = useMemo(() => {
    const text = query.trim();
    if (!text) return options;
    if (search) return search(text);
    const needle = text.toLowerCase();
    return options.filter((o) => `${o.label} ${o.meta ?? ""}`.toLowerCase().includes(needle));
  }, [options, query, search]);

  useEffect(() => {
    if (!open) return;
    const item = listRef.current?.children[active] as HTMLElement | undefined;
    item?.scrollIntoView?.({ block: "nearest" });
  }, [open, active]);

  const openWith = (text: string) => {
    setQuery(text);
    setOpen(true);
    setActive(text.trim() ? 0 : Math.max(0, options.findIndex((o) => o.value === value)));
  };
  const close = () => {
    setOpen(false);
    setQuery("");
  };
  const choose = (option: ComboboxOption) => {
    onChange(option.value);
    close();
  };
  const clear = () => {
    onChange("");
    close();
    inputRef.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const typed = event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) openWith("");
      else setActive((i) => (event.key === "ArrowDown" ? Math.min(results.length - 1, i + 1) : Math.max(0, i - 1)));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      if (results[active]) choose(results[active]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    } else if (!open && chosen && (typed || event.key === "Backspace" || event.key === "Delete")) {
      // The chosen name is in the field: typing starts a new search instead of adding to the name.
      event.preventDefault();
      openWith(typed ? event.key : "");
    }
  };

  // While something is chosen and the list is closed, the field shows the chosen option (wrapping) and the input lies
  // over it, with the same text for screen readers.
  const covered = chosen !== null && !open;
  return (
    <FieldShell label={label} hint={hint} error={error} optional={optional} hideLabel={hideLabel} ids={ids}>
      <div className="ek-combobox">
        <div className="ek-combobox__field" data-open={open ? "true" : undefined}>
          {covered ? (
            <span className="ek-combobox__value" aria-hidden="true">
              <span className="ek-combobox__label">{chosen.label}</span>
              {chosen.meta ? <span className="ek-combobox__meta">{chosen.meta}</span> : null}
            </span>
          ) : null}
          <input
            ref={inputRef}
            id={ids.controlId}
            className={cx("ek-combobox__input", covered && "ek-combobox__input--covered")}
            role="combobox"
            aria-expanded={open}
            aria-controls={open ? listId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy(hint, error, ids)}
            value={open ? query : chosen?.label ?? ""}
            placeholder={covered ? undefined : placeholder}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => openWith(event.target.value)}
            onClick={() => {
              if (!open) openWith("");
            }}
            onKeyDown={onKeyDown}
            onPaste={(event) => {
              if (open || !chosen) return;
              event.preventDefault();
              openWith(event.clipboardData.getData("text"));
            }}
            onBlur={close}
          />
          {chosen ? (
            <button type="button" className="ek-combobox__clear" aria-label={clearLabel} title={clearLabel}
              onMouseDown={(event) => event.preventDefault()} onClick={clear}>
              <X aria-hidden="true" />
            </button>
          ) : (
            <ChevronDown className="ek-combobox__chevron" aria-hidden="true" />
          )}
        </div>
        {open ? (
          // A press anywhere in the list (also its scroll bar) keeps the focus in the field.
          <div className="ek-combobox__popup" onMouseDown={(event) => event.preventDefault()}>
            {results.length ? (
              <ul ref={listRef} id={listId} role="listbox" aria-labelledby={ids.labelId} className="ek-combobox__list">
                {results.map((option, i) => (
                  <li key={option.value} id={`${listId}-${i}`} role="option" aria-selected={option.value === value}
                    aria-label={option.meta ? `${option.label}, ${option.meta}` : undefined}
                    tabIndex={-1} className="ek-combobox__option" data-active={i === active ? "true" : undefined}
                    onMouseMove={() => setActive(i)} onClick={() => choose(option)}>
                    <span className="ek-combobox__label">{marked(option.label, query)}</span>
                    {option.meta ? <span className="ek-combobox__meta">{marked(option.meta, query)}</span> : null}
                    {option.value === value ? <Check className="ek-combobox__check" aria-hidden="true" /> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p id={listId} className="ek-combobox__empty">{noResults}</p>
            )}
          </div>
        ) : null}
        <p className="ek-visually-hidden" role="status">
          {open && query.trim() ? (results.length ? `${results.length} treff.` : noResults) : ""}
        </p>
      </div>
    </FieldShell>
  );
}

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
  nested,
}: {
  legend: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  hideLegend?: boolean;
  /** Indented under the control it belongs to (for example file types under «Dokumenter»). */
  nested?: boolean;
}) {
  const hintId = useId();
  const errorId = useId();
  return (
    <fieldset
      className={cx("ek-fieldset", nested && "ek-fieldset--nested")}
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
  /** Card variant only: longer explanation behind «Vis detaljer» (outside the label, so the card stays one choice). */
  details?: ReactNode;
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
  truncateLabels,
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
  /** Long labels on one line with «…»; the full label shows on hover and keyboard focus, wraps on touch screens,
   * with larger text and on narrow screens, and is always the radio's accessible name. */
  truncateLabels?: boolean;
}) {
  const choices = options.map((option) => (
    <RadioChoice
      key={option.value}
      name={name}
      option={option}
      checked={value === option.value}
      onSelect={() => onChange(option.value)}
      variant={variant}
      truncate={truncateLabels}
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
  truncate,
}: {
  name: string;
  option: RadioOption<T>;
  checked: boolean;
  onSelect: () => void;
  variant: "plain" | "card";
  truncate?: boolean;
}) {
  const hintId = useId();
  const labelId = useId();
  const card = variant === "card";
  const withDetails = card && option.details != null;
  const label = (
    <label className={cx("ek-choice", card && !withDetails && "ek-choice--card", withDetails && "ek-choice-card__label")}>
      <input
        type="radio"
        name={name}
        value={option.value}
        checked={checked}
        disabled={option.disabled}
        onChange={onSelect}
        // The name is the label alone and the hint its description – otherwise the hint is read twice.
        aria-labelledby={labelId}
        aria-describedby={option.hint ? hintId : undefined}
      />
      {card && option.icon ? (
        <span className="ek-tile" data-tone={option.tone ?? "info"} data-size="sm" aria-hidden="true">
          {option.icon}
        </span>
      ) : null}
      <span className="ek-choice__text">
        <span className={cx("ek-choice__label", truncate && "ek-choice__label--truncate")} id={labelId}>{option.label}</span>
        {option.hint ? (
          <span className="ek-choice__hint ek-small" id={hintId}>
            {option.hint}
          </span>
        ) : null}
      </span>
    </label>
  );
  if (!withDetails) return label;
  // A card with «Vis detaljer»: the label covers the whole card (a click anywhere selects it), and the details toggle
  // lies above it, outside the label – never a button inside a label.
  return (
    <div className="ek-choice--card ek-choice-card">
      {label}
      <div className="ek-choice-card__details">
        <Disclosure summary={<>Vis detaljer{" "}<span className="ek-visually-hidden">om {option.label}</span></>}>
          {option.details}
        </Disclosure>
      </div>
    </div>
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
