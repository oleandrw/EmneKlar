/*
 * Dashboard building blocks: status cards, key figures, action rows, feature cards, stat tiles and
 * activity lists. Pages compose these (and never style the pieces themselves), so every area of
 * EmneKlar shares one visual language. All figures shown must be real data – there is no
 * placeholder mode.
 */
import { ArrowRight, ChevronRight, Info, TriangleAlert } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Link } from "react-router";

import { Badge, Button, ButtonLink, cx, type Tone } from "./primitives";

/** Colour of a key figure: critical (red) is for real problems only, so it never dominates. «zero» is a muted 0. */
export type ValueTone = "critical" | "warning" | "info" | "success" | "neutral" | "zero";

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

/**
 * One area of the course, as one link: icon and title, one big figure with its label, a smaller line at the bottom, and
 * an arrow in a circle – all inside the same link (one tab stop, Enter or one tap opens the area; no other control in
 * it). A thin line in the area's colour finishes the card; it is decoration, not a progress bar. The coverage and age
 * of the figures are read with the link (aria-describedby) and shown on the page outside the card. A figure of 0 is
 * always muted, whatever its class.
 */
export function StatusCard({
  title,
  icon,
  tone,
  to,
  metric,
  secondary,
  description,
  empty,
  headingLevel = 3,
}: {
  title: string;
  icon: ReactNode;
  tone: Tone;
  to: string;
  /** The one big figure. */
  metric: StatusMetric;
  /** The smaller line at the bottom, e.g. «12 sannsynlige avvik». */
  secondary?: { text: string; tone?: ValueTone } | null;
  /** Read with the card by screen readers, e.g. the coverage and age of the figures. */
  description?: string | null;
  /** Shown instead of the figures, e.g. «Ikke analysert ennå». */
  empty?: string;
  headingLevel?: 2 | 3;
}) {
  const Heading = `h${headingLevel}` as "h3";
  const descriptionId = useId();
  // The name comes from the visible text («Universell utforming: 28 bekreftede avvik, 12 sannsynlige avvik»); the
  // colon and comma are only for screen readers, so the name always contains what is seen (WCAG 2.5.3).
  return (
    <Link to={to} className="ek-status-card" data-tone={tone} aria-describedby={description ? descriptionId : undefined}>
      <div className="ek-status-card__head">
        <IconTile tone={tone} size="lg">{icon}</IconTile>
        <Heading className="ek-status-card__title">{title}<span className="ek-visually-hidden">:</span></Heading>
      </div>
      {empty ? (
        <p className="ek-status-card__empty">{empty}</p>
      ) : (
        <p className="ek-status-card__figure" data-value-tone={metric.value === 0 ? "zero" : (metric.tone ?? "neutral")}>
          <span className="ek-status-card__value">{show(metric.value)}</span>{" "}
          <span className="ek-status-card__label">{metric.label}{secondary?.text ? <span className="ek-visually-hidden">,</span> : null}</span>
        </p>
      )}
      <div className="ek-status-card__foot">
        <span className="ek-status-card__secondary" data-value-tone={secondary?.tone}>{empty ? null : secondary?.text}</span>
        <span className="ek-status-card__arrow" aria-hidden="true"><ArrowRight /></span>
      </div>
      <span className="ek-status-card__accent" aria-hidden="true" />
      {description ? <span id={descriptionId} hidden>{description}</span> : null}
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
  secondary,
}: {
  icon: ReactNode;
  tone?: Tone;
  shape?: "circle" | "square";
  value: ReactNode;
  label: ReactNode;
  description?: ReactNode;
  valueTone?: ValueTone;
  /** A smaller figure under the label, e.g. «3 sannsynlige avvik» under the confirmed ones (0 is muted). */
  secondary?: { value: number; label: string; tone?: ValueTone } | null;
  to?: string;
  onClick?: () => void;
  pressed?: boolean;
}) {
  const kind = typeof value === "string" ? "text" : "number";
  const content = (
    <>
      <IconTile tone={tone} size="lg" shape={shape}>
        {icon}
      </IconTile>
      <span className="ek-metric-card__body">
        <span className="ek-metric-card__value">{show(value)}</span>{" "}
        <span className="ek-metric-card__label">{label}</span>
        {secondary ? (
          <span className="ek-metric-card__secondary" data-value-tone={secondary.value === 0 ? "zero" : (secondary.tone ?? "neutral")}>
            <span className="ek-metric-card__secondary-value">{show(secondary.value)}</span> {secondary.label}
          </span>
        ) : null}
        {description ? <span className="ek-metric-card__description">{description}</span> : null}
      </span>
      {to || onClick ? <ChevronRight className="ek-metric-card__chevron" aria-hidden="true" /> : null}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="ek-metric-card" data-value-tone={valueTone} data-value-kind={kind}>
        {content}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" className="ek-metric-card" data-value-tone={valueTone} data-value-kind={kind} onClick={onClick}
        aria-pressed={pressed}>
        {content}
      </button>
    );
  }
  return (
    <div className="ek-metric-card" data-value-tone={valueTone} data-value-kind={kind}>
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

/** A recommended step: icon, short title, one explaining line and a clear call to action. ``featured``: the one step
 * recommended first – a stronger frame and a primary button. */
export function ActionRow({
  icon,
  tone = "info",
  title,
  description,
  actionLabel,
  to,
  onClick,
  featured,
}: {
  icon: ReactNode;
  tone?: Tone;
  title: ReactNode;
  description?: ReactNode;
  actionLabel: string;
  to?: string;
  onClick?: () => void;
  featured?: boolean;
}) {
  const titleId = useId();
  const arrow = <ArrowRight aria-hidden="true" />;
  const variant = featured ? "primary" : "soft";
  return (
    <li className="ek-action-row" data-featured={featured ? "true" : undefined}>
      <IconTile tone={tone}>{icon}</IconTile>
      <span className="ek-action-row__text">
        <span className="ek-action-row__title" id={titleId}>
          {title}
        </span>
        {description ? <span className="ek-action-row__description">{description}</span> : null}
      </span>
      <span className="ek-action-row__action">
        {to ? (
          <ButtonLink to={to} variant={variant} tone={featured ? undefined : tone} iconEnd={arrow} aria-describedby={titleId}>
            {actionLabel}
          </ButtonLink>
        ) : (
          <Button variant={variant} tone={featured ? undefined : tone} onClick={onClick} aria-describedby={titleId}
            className="ek-btn--between">
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
  notice,
  noticeTone = "warning",
  headingLevel = 2,
}: {
  icon: ReactNode;
  tone: Tone;
  title: string;
  description: ReactNode;
  /** The visible text is the link's accessible name – make it say what happens («Sett modulkrav»). */
  actionLabel?: string;
  to?: string;
  /** Only what limits the tool here (missing access in Canvas, not a Blueprint course) – no status badges. */
  notice?: ReactNode;
  noticeTone?: "warning" | "info";
  headingLevel?: 2 | 3;
}) {
  const id = useId();
  const Heading = `h${headingLevel}` as "h2";
  return (
    <section className="ek-feature-card" aria-labelledby={id}>
      <div className="ek-feature-card__head">
        <IconTile tone={tone} size="md" shape="square">
          {icon}
        </IconTile>
        <div className="ek-feature-card__text">
          <Heading id={id} className="ek-feature-card__title">
            {title}
          </Heading>
          <p className="ek-feature-card__description">{description}</p>
          {notice ? (
            <p className="ek-feature-card__notice" data-tone={noticeTone}>
              {noticeTone === "warning" ? <TriangleAlert aria-hidden="true" /> : <Info aria-hidden="true" />}
              <span>{notice}</span>
            </p>
          ) : null}
        </div>
      </div>
      {to && actionLabel ? (
        <div className="ek-feature-card__action">
          <ButtonLink to={to} variant="soft" tone={tone} block iconEnd={<ArrowRight aria-hidden="true" />}
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

/* --------------------------------------------------------------- key figures */

export function KeyFigureList({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ul className="ek-key-figures" aria-label={label}>
      {children}
    </ul>
  );
}

/** A figure inside a card: icon, number, label and a short explanation (no card of its own). */
export function KeyFigure({
  icon,
  tone = "neutral",
  value,
  label,
  description,
}: {
  icon: ReactNode;
  tone?: Tone;
  value: number;
  label: string;
  description?: ReactNode;
}) {
  return (
    <li className="ek-key-figure">
      <IconTile tone={tone} shape="square">
        {icon}
      </IconTile>
      <span className="ek-key-figure__text">
        <span className="ek-key-figure__value">{show(value)}</span>{" "}
        <span className="ek-key-figure__label">{label}</span>
        {description ? <span className="ek-key-figure__description">{description}</span> : null}
      </span>
    </li>
  );
}

/* -------------------------------------------------------------- activity list */

/** Colour of an activity's status mark (the --status-* tokens): success = completed, warning = stopped or a conflict,
 * danger = failed. */
export type ActivityStatusTone = "success" | "warning" | "danger" | "info" | "neutral";

export interface ActivityEntry {
  key: string;
  icon: ReactNode;
  tone: Tone;
  title: ReactNode;
  meta?: ReactNode;
  /** A compact status mark: text and icon, so it never relies on colour; read as «Status: …». */
  status?: { label: string; tone: ActivityStatusTone; icon: ReactNode };
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
            {item.status || item.meta ? (
              <span className="ek-activity__sub">
                {item.status ? (
                  <span className="ek-activity__status" data-status-tone={item.status.tone}>
                    <span className="ek-activity__status-icon" aria-hidden="true">{item.status.icon}</span>
                    <span className="ek-visually-hidden">Status: </span>
                    {item.status.label}
                  </span>
                ) : null}
                {item.meta ? <span className="ek-activity__meta">{item.meta}</span> : null}
              </span>
            ) : null}
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

function ChipGroup({ label, showLabel, children }: { label: string; showLabel?: boolean; children: ReactNode }) {
  const id = useId();
  if (!showLabel) {
    return (
      <div className="ek-chips" role="group" aria-label={label}>
        {children}
      </div>
    );
  }
  return (
    <div className="ek-filter-group">
      <span id={id} className="ek-filter-group__label">
        {label}
      </span>
      <div className="ek-chips" role="group" aria-labelledby={id}>
        {children}
      </div>
    </div>
  );
}

function Chip({ option, pressed, onClick }: { option: ChipOption<string>; pressed: boolean; onClick: () => void }) {
  return (
    <button type="button" className="ek-chip" aria-pressed={pressed} onClick={onClick}>
      {option.icon}
      {option.label}
      {option.count !== undefined ? <>{" "}<span>({numberFormat.format(option.count)})</span></> : null}
    </button>
  );
}

/** A row of mutually exclusive filters (one pressed at a time). */
export function FilterChips<T extends string>({
  label,
  options,
  value,
  onChange,
  showLabel,
}: {
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Show the label above the chips (otherwise it is only announced). */
  showLabel?: boolean;
}) {
  return (
    <ChipGroup label={label} showLabel={showLabel}>
      {options.map((o) => (
        <Chip key={o.value} option={o} pressed={o.value === value} onClick={() => onChange(o.value)} />
      ))}
    </ChipGroup>
  );
}

/** A row of independent on/off filters (any number pressed). */
export function ToggleChips<T extends string>({
  label,
  options,
  values,
  onToggle,
  showLabel,
}: {
  label: string;
  options: ChipOption<T>[];
  values: T[];
  onToggle: (value: T) => void;
  showLabel?: boolean;
}) {
  return (
    <ChipGroup label={label} showLabel={showLabel}>
      {options.map((o) => (
        <Chip key={o.value} option={o} pressed={values.includes(o.value)} onClick={() => onToggle(o.value)} />
      ))}
    </ChipGroup>
  );
}
