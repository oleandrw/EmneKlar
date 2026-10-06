/*
 * Basic building blocks. Feature code composes these instead of styling
 * elements directly, so the product looks and behaves consistently.
 */
import { TriangleAlert, CircleCheck, ChevronRight, Info, OctagonAlert } from "lucide-react";
import {
  forwardRef,
  useId,
  useState,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Link, type LinkProps } from "react-router";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "violet" | "teal";
type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";

/* ------------------------------------------------------------------ buttons */

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, block, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        "ek-btn",
        variant !== "secondary" && `ek-btn--${variant}`,
        size === "sm" && "ek-btn--sm",
        block && "ek-btn--block",
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="ek-spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: "sm" | "md";
  variant?: Variant;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", variant = "ghost", className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cx("ek-btn", "ek-btn--icon", `ek-btn--${variant}`, size === "sm" && "ek-btn--sm", className)}
      {...rest}
    >
      {children}
    </button>
  );
});

export function ButtonLink({
  variant = "secondary",
  size = "md",
  icon,
  className,
  children,
  ...rest
}: LinkProps & { variant?: Variant; size?: "sm" | "md"; icon?: ReactNode }) {
  return (
    <Link
      className={cx("ek-btn", variant !== "secondary" && `ek-btn--${variant}`, size === "sm" && "ek-btn--sm", className)}
      {...rest}
    >
      {icon}
      {children}
    </Link>
  );
}

export function ExternalLink({ children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a target="_blank" rel="noreferrer noopener" {...rest}>
      {children}
      <span className="ek-visually-hidden"> (åpnes i ny fane)</span>
    </a>
  );
}

/* ------------------------------------------------------------ text helpers */

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="ek-visually-hidden">{children}</span>;
}

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx("ek-badge", className)} data-tone={tone}>
      {icon}
      {children}
    </span>
  );
}

const ALERT_ICONS: Record<Tone, ReactNode> = {
  neutral: <Info aria-hidden="true" />,
  info: <Info aria-hidden="true" />,
  success: <CircleCheck aria-hidden="true" />,
  warning: <TriangleAlert aria-hidden="true" />,
  danger: <OctagonAlert aria-hidden="true" />,
  violet: <Info aria-hidden="true" />,
  teal: <Info aria-hidden="true" />,
};

export function Alert({
  tone = "info",
  title,
  children,
  role,
  banner,
  actions,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  role?: "status" | "alert";
  banner?: boolean;
  actions?: ReactNode;
}) {
  return (
    <div className={cx("ek-alert", banner && "ek-alert--banner")} data-tone={tone} role={role}>
      {ALERT_ICONS[tone]}
      <div style={{ flex: 1, minWidth: 0 }}>
        {title ? <p className="ek-alert__title">{title}</p> : null}
        {children ? <div>{children}</div> : null}
      </div>
      {actions ? <div className="ek-cluster">{actions}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------- cards */

export function Card({
  title,
  eyebrow,
  actions,
  children,
  footer,
  tone,
  flush,
  className,
  headingLevel = 2,
  ...rest
}: Omit<HTMLAttributes<HTMLElement>, "title"> & {
  title?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  tone?: Tone;
  flush?: boolean;
  headingLevel?: 2 | 3 | 4;
}) {
  const Heading = `h${headingLevel}` as "h2";
  return (
    <section
      className={cx("ek-card", tone && "ek-card--tone", flush && "ek-card--flush", className)}
      data-tone={tone}
      {...rest}
    >
      {title || actions || eyebrow ? (
        <div className="ek-card__header">
          <div className="ek-stack" data-gap="1">
            {eyebrow ? <span className="ek-card__eyebrow">{eyebrow}</span> : null}
            {title ? <Heading className="ek-card__title">{title}</Heading> : null}
          </div>
          {actions ? <div className="ek-cluster" data-gap="2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
      {footer ? <div className="ek-card__footer">{footer}</div> : null}
    </section>
  );
}

export function Stat({ value, label, hint }: { value: ReactNode; label: ReactNode; hint?: ReactNode }) {
  return (
    <div className="ek-stat">
      <span className="ek-stat__value">{value}</span>
      <span className="ek-stat__label">{label}</span>
      {hint ? <span className="ek-xs ek-subtle">{hint}</span> : null}
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="ek-kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ----------------------------------------------------------- progress etc. */

export function Spinner({ label = "Laster …" }: { label?: string }) {
  return (
    <span className="ek-cluster" data-gap="2" role="status">
      <span className="ek-spinner" aria-hidden="true" />
      <span className="ek-small ek-muted">{label}</span>
    </span>
  );
}

export function ProgressBar({
  value,
  max = 100,
  label,
  valueText,
  size = "md",
}: {
  /** Omit for an indeterminate bar (work in progress, total unknown). */
  value?: number | null;
  max?: number;
  label: string;
  valueText?: string;
  size?: "sm" | "md";
}) {
  const determinate = typeof value === "number";
  const pct = determinate ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div
      className={cx("ek-progress", size === "sm" && "ek-progress--sm", !determinate && "ek-progress--indeterminate")}
      role="progressbar"
      aria-label={label}
      aria-valuemin={determinate ? 0 : undefined}
      aria-valuemax={determinate ? max : undefined}
      aria-valuenow={determinate ? value : undefined}
      aria-valuetext={valueText}
    >
      <div className="ek-progress__bar" style={determinate ? { width: `${pct}%` } : undefined} />
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  actions,
  headingLevel = 2,
}: {
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const Heading = `h${headingLevel}` as "h2";
  return (
    <div className="ek-empty">
      {icon ? <div className="ek-empty__icon">{icon}</div> : null}
      <Heading>{title}</Heading>
      {children ? <p>{children}</p> : null}
      {actions ? <div className="ek-cluster" style={{ justifyContent: "center" }}>{actions}</div> : null}
    </div>
  );
}

/* ----------------------------------------------------------- page layout */

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="ek-page-header">
      <div className="ek-page-header__text">
        {eyebrow ? <span className="ek-card__eyebrow">{eyebrow}</span> : null}
        <h1 tabIndex={-1} data-page-heading="true">
          {title}
        </h1>
        {description ? <p className="ek-page-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="ek-cluster">{actions}</div> : null}
    </header>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  headingLevel = 2,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  headingLevel?: 2 | 3;
  id?: string;
}) {
  const generated = useId();
  const headingId = id ?? `sec-${generated}`;
  const Heading = `h${headingLevel}` as "h2";
  return (
    <section className="ek-section" aria-labelledby={headingId}>
      <div className="ek-section__header">
        <div className="ek-stack" data-gap="1">
          <Heading id={headingId}>{title}</Heading>
          {description ? <p className="ek-small ek-muted">{description}</p> : null}
        </div>
        {actions ? <div className="ek-cluster" data-gap="2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Disclosure({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  return (
    <div>
      <button
        type="button"
        className="ek-disclosure__button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight aria-hidden="true" />
        {summary}
      </button>
      <div id={panelId} className="ek-disclosure__panel" hidden={!open}>
        {open ? children : null}
      </div>
    </div>
  );
}

export function IconCircle({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className="ek-icon-circle" data-tone={tone} aria-hidden="true">
      {children}
    </span>
  );
}
