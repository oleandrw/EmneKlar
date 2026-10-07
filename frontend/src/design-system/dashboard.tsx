/*
 * Dashboard building blocks: status cards, key figures, action rows, feature cards, stat tiles and
 * activity lists. Pages compose these (and never style the pieces themselves), so every area of
 * EmneKlar shares one visual language. All figures shown must be real data – there is no
 * placeholder mode.
 */
import { ArrowRight, ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Link } from "react-router";

import { Badge, Button, ButtonLink, cx, type Tone } from "./primitives";

/** Colour of a key figure: critical (red) is for real problems only, so it never dominates. */
export type ValueTone = "critical" | "warning" | "info" | "success" | "neutral";

const numberFormat = new Intl.NumberFormat("nb-NO");
const show = (value: ReactNode): ReactNode => (typeof value === "number" ? numberFormat.format(value) : value);

/* ------------------------------------------------------------------ icon tile */

export function IconTile({
  tone = "neutral",
  size = "md",
  shape = "circle",
  children,
}: {
  tone?: Tone;
  size?: "sm" | "md" | "lg";
  shape?: "circle" | "square";
  children: ReactNode;
}) {
  return (
    <span className="ek-tile" data-tone={tone} data-size={size} data-shape={shape} aria-hidden="true">
      {children}
    </span>
  );
}

/* ------------------------------------------------------------- section header */

export function SectionHeader({
  title,
  description,
  actions,
  headingLevel = 2,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  headingLevel?: 2 | 3;
  id?: string;
}) {
  const Heading = `h${headingLevel}` as "h2";
  return (
    <div className="ek-section-header">
      <div className="ek-section-header__text">
        <Heading id={id}>{title}</Heading>
        {description ? <p className="ek-section-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="ek-section-header__actions">{actions}</div> : null}
    </div>
  );
}

/** «Se alle →» link in a section header. */
export function MoreLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="ek-more-link">
      {children}
      <ArrowRight aria-hidden="true" />
    </Link>
  );
}

/* --------------------------------------------------------------- status card */

export interface StatusMetric {
  value: number | string;
  label: string;
  tone?: ValueTone;
}

/** One area of the course: large icon, title, the most important figures. The whole card is a link. */
export function StatusCard({
  title,
  icon,
  tone,
  to,
  metrics,
  footnote,
  empty,
  headingLevel = 3,
}: {
  title: string;
  icon: ReactNode;
  tone: Tone;
  to: string;
  metrics: StatusMetric[];
  footnote?: ReactNode;
  /** Shown instead of the figures, e.g. «Ikke analysert ennå». */
  empty?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const Heading = `h${headingLevel}` as "h3";
  return (
    <Link to={to} className="ek-status-card">
      <span className="ek-status-card__head">
        <IconTile tone={tone} size="lg">
          {icon}
        </IconTile>
        <Heading className="ek-status-card__title">{title}</Heading>
        <ChevronRight className="ek-status-card__chevron" aria-hidden="true" />
      </span>
      {empty ? (
        <span className="ek-status-card__empty">{empty}</span>
      ) : (
        <span className="ek-status-card__metrics" data-count={metrics.length}>
          {metrics.map((m) => (
            <span key={m.label} className="ek-status-card__metric" data-value-tone={m.tone ?? "neutral"}>
              <span className="ek-status-card__value">{show(m.value)}</span>{" "}
              <span className="ek-status-card__label">{m.label}</span>
            </span>
          ))}
        </span>
      )}
      {footnote ? <span className="ek-status-card__foot">{footnote}</span> : null}
    </Link>
  );
}

/* --------------------------------------------------------------- metric card */

/** A key figure with an icon. A link (`to`), a toggle (`onClick` + `pressed`) or static. */
export function MetricCard({
  icon,
  tone = "neutral",
  shape = "circle",
  value,
  label,
  description,
  valueTone,
  to,
  onClick,
  pressed,
}: {
  icon: ReactNode;
  tone?: Tone;
  shape?: "circle" | "square";
  value: ReactNode;
  label: ReactNode;
  description?: ReactNode;
  valueTone?: ValueTone;
  to?: string;
  onClick?: () => void;
  pressed?: boolean;
}) {
  const content = (
    <>
      <IconTile tone={tone} size="lg" shape={shape}>
        {icon}
      </IconTile>
      <span className="ek-metric-card__body">
        <span className="ek-metric-card__value">{show(value)}</span>{" "}
        <span className="ek-metric-card__label">{label}</span>
        {description ? <span className="ek-metric-card__description">{description}</span> : null}
      </span>
      {to || onClick ? <ChevronRight className="ek-metric-card__chevron" aria-hidden="true" /> : null}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="ek-metric-card" data-value-tone={valueTone}>
        {content}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" className="ek-metric-card" data-value-tone={valueTone} onClick={onClick} aria-pressed={pressed}>
        {content}
      </button>
    );
  }
  return (
    <div className="ek-metric-card" data-value-tone={valueTone}>
      {content}
    </div>
  );
}

/* ---------------------------------------------------------------- action rows */

export function ActionList({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <ul className="ek-action-list" aria-label={label}>
      {children}
    </ul>
  );
}

/** A recommended step: icon, short title, one explaining line and a clear call to action. */
export function ActionRow({
  icon,
  tone = "info",
  title,
  description,
  actionLabel,
  to,
  onClick,
}: {
  icon: ReactNode;
  tone?: Tone;
  title: ReactNode;
  description?: ReactNode;
  actionLabel: string;
  to?: string;
  onClick?: () => void;
}) {
  const titleId = useId();
  const arrow = <ArrowRight aria-hidden="true" />;
  return (
    <li className="ek-action-row">
      <IconTile tone={tone}>{icon}</IconTile>
      <span className="ek-action-row__text">
        <span className="ek-action-row__title" id={titleId}>
          {title}
        </span>
        {description ? <span className="ek-action-row__description">{description}</span> : null}
      </span>
      <span className="ek-action-row__action">
        {to ? (
          <ButtonLink to={to} variant="soft" tone={tone} iconEnd={arrow} aria-describedby={titleId}>
            {actionLabel}
          </ButtonLink>
        ) : (
          <Button variant="soft" tone={tone} onClick={onClick} aria-describedby={titleId} className="ek-btn--between">
            {actionLabel}
            {arrow}
          </Button>
        )}
      </span>
    </li>
  );
}

/* --------------------------------------------------------------- feature card */

/** A tool or area to open: big icon, title, description and one clear action. */
export function FeatureCard({
  icon,
  tone,
  title,
  description,
  actionLabel,
  to,
  children,
  headingLevel = 2,
}: {
  icon: ReactNode;
  tone: Tone;
  title: string;
  description: ReactNode;
  actionLabel?: string;
  to?: string;
  children?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const id = useId();
  const Heading = `h${headingLevel}` as "h2";
  return (
    <section className="ek-feature-card" aria-labelledby={id}>
      <div className="ek-feature-card__head">
        <IconTile tone={tone} size="lg" shape="square">
          {icon}
        </IconTile>
        <div className="ek-feature-card__text">
          <Heading id={id} className="ek-feature-card__title">
            {title}
          </Heading>
          <p className="ek-feature-card__description">{description}</p>
        </div>
      </div>
      {children ? <div className="ek-feature-card__body">{children}</div> : null}
      {to && actionLabel ? (
        <div className="ek-feature-card__action">
          <ButtonLink to={to} variant="soft" tone={tone} size="lg" block iconEnd={<ArrowRight aria-hidden="true" />}
            aria-describedby={id}>
            {actionLabel}
          </ButtonLink>
        </div>
      ) : null}
    </section>
  );
}

/* --------------------------------------------------------------- status badge */

/** Status pill with a coloured dot; the text always states the status (never colour alone). */
export function StatusBadge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <Badge tone={tone} dot>
      {children}
    </Badge>
  );
}

/* ----------------------------------------------------------------- stat tiles */

export function StatList({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ul className={cx("ek-stat-grid", "ek-list-reset")} aria-label={label}>
      {children}
    </ul>
  );
}

/** A count with an icon («147 Bilder»). */
export function StatTile({ icon, tone = "neutral", value, label }: { icon: ReactNode; tone?: Tone; value: number; label: string }) {
  return (
    <li className="ek-stat-tile">
      <IconTile tone={tone} size="sm" shape="square">
        {icon}
      </IconTile>
      <span className="ek-stat-tile__text">
        <span className="ek-stat-tile__value">{show(value)}</span>{" "}
        <span className="ek-stat-tile__label">{label}</span>
      </span>
    </li>
  );
}

/* -------------------------------------------------------------- activity list */

export interface ActivityEntry {
  key: string;
  icon: ReactNode;
  tone: Tone;
  title: ReactNode;
  meta?: ReactNode;
  date?: string;
  time?: string;
}

export function ActivityList({ items, label }: { items: ActivityEntry[]; label: string }) {
  return (
    <ul className="ek-activity" aria-label={label}>
      {items.map((item) => (
        <li key={item.key} className="ek-activity__item">
          <IconTile tone={item.tone} size="sm" shape="square">
            {item.icon}
          </IconTile>
          <span className="ek-activity__text">
            <span className="ek-activity__title">{item.title}</span>
            {item.meta ? <span className="ek-activity__meta">{item.meta}</span> : null}
          </span>
          {item.date || item.time ? (
            <span className="ek-activity__time">
              {item.date ? <span>{item.date}</span> : null}
              {item.time ? <span>{item.time}</span> : null}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------- filter chips */

export interface ChipOption<T extends string> {
  value: T;
  label: string;
  count?: number;
  icon?: ReactNode;
}

/** A row of mutually exclusive filters (one pressed at a time). */
export function FilterChips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="ek-chips" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className="ek-chip" aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}>
          {o.icon}
          {o.label}
          {o.count !== undefined ? <span>({numberFormat.format(o.count)})</span> : null}
        </button>
      ))}
    </div>
  );
}
