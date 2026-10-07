/*
 * Grouped bar chart (SVG). Follows the data-visualisation rules in docs/DESIGN_SYSTEM.md:
 * thin bars (≤ 24 px) with 4 px rounded data ends and 2 px gaps, hairline grid, a legend for
 * every series, text in text colours (never the series colour), a tooltip on hover and keyboard
 * focus, and a table view so no value is only reachable through colour or hovering.
 */
import { ChartColumnBig, Table2 } from "lucide-react";
import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import { Button } from "./primitives";

export interface ChartCategory {
  key: string;
  label: string;
  /** Used when there is too little room for the full label. */
  shortLabel?: string;
}

export interface ChartSeries {
  key: string;
  label: string;
  /** A chart colour token, e.g. `var(--chart-violation)`. */
  color: string;
  values: number[];
}

const numberFormat = new Intl.NumberFormat("nb-NO");
const AXIS_WIDTH = 40;
const TOP = 12;
const LABEL_BAND = 40;
const BAR_GAP = 2;
const MAX_BAR = 24;

/** Clean, whole-number ticks from 0 to just above `max`. */
export function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude);
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
}

/** Bar with rounded top corners and a square base. */
function barPath(x: number, y: number, w: number, h: number, radius = 4): string {
  const r = Math.min(radius, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const measure = (value: number) => {
      if (value > 0) setWidth(Math.round(value));
    };
    measure(element.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => measure(entries[0]?.contentRect.width ?? 0));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function BarChart({
  label,
  categories,
  series,
  categoryHeader,
  height = 200,
  emptyText = "Ingen verdier å vise.",
}: {
  /** Describes the chart for screen readers and captions the table view. */
  label: string;
  categories: ChartCategory[];
  series: ChartSeries[];
  /** Header of the first table column, e.g. «Område». */
  categoryHeader: string;
  height?: number;
  emptyText?: string;
}) {
  const [plotRef, width] = useWidth(640);
  const [active, setActive] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const max = Math.max(0, ...series.flatMap((s) => s.values));

  if (max === 0) return <p className="ek-chart__empty">{emptyText}</p>;

  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const plotWidth = Math.max(width - AXIS_WIDTH, 160);
  const band = plotWidth / categories.length;
  const barWidth = Math.max(4, Math.min(MAX_BAR, (band * 0.64 - BAR_GAP * (series.length - 1)) / series.length));
  const groupWidth = barWidth * series.length + BAR_GAP * (series.length - 1);
  const y = (value: number) => height - (value / top) * height;
  const useShort = band < 120;
  const describe = (i: number) =>
    `${categories[i].label}: ${series.map((s) => `${s.label} ${numberFormat.format(s.values[i] ?? 0)}`).join(", ")}`;
  const tooltipX = active === null ? 0 : Math.min(Math.max(AXIS_WIDTH + active * band + band / 2, 110), width - 110);
  const tooltipTop = active === null ? 0 : Math.max(0, TOP + y(Math.max(...series.map((s) => s.values[active] ?? 0))) - 12);

  return (
    <figure className="ek-chart">
      <div className="ek-chart__top">
        <ul className="ek-chart__legend" aria-label="Forklaring">
          {series.map((s) => (
            <li key={s.key}>
              <span className="ek-chart__swatch" style={{ "--swatch": s.color } as CSSProperties} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
        <Button size="sm" variant="ghost" aria-pressed={table} onClick={() => setTable((v) => !v)}
          icon={table ? <ChartColumnBig aria-hidden="true" /> : <Table2 aria-hidden="true" />}>
          {table ? "Vis diagram" : "Vis som tabell"}
        </Button>
      </div>

      <div className="ek-chart__plot" ref={plotRef} hidden={table} data-active={active !== null}>
        <svg width={width} height={TOP + height + LABEL_BAND} role="group" aria-label={label}>
          <g transform={`translate(${AXIS_WIDTH}, ${TOP})`}>
            {ticks.map((t) => (
              <g key={t} aria-hidden="true">
                <line className={t === 0 ? "ek-chart__baseline" : "ek-chart__grid"} x1={0} x2={plotWidth} y1={y(t)} y2={y(t)} />
                <text className="ek-chart__tick" x={-10} y={y(t)} dy="0.35em" textAnchor="end">
                  {numberFormat.format(t)}
                </text>
              </g>
            ))}
            {categories.map((category, i) => {
              const x0 = i * band + (band - groupWidth) / 2;
              return (
                <g key={category.key} className="ek-chart__group" tabIndex={0} role="img" aria-label={describe(i)}
                  data-active={active === i} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(i)} onBlur={() => setActive(null)}>
                  <rect className="ek-chart__hit" x={i * band + 3} y={-6} width={band - 6} height={height + LABEL_BAND} rx={8} />
                  {series.map((s, j) => {
                    const value = s.values[i] ?? 0;
                    if (value <= 0) return null;
                    return (
                      <path key={s.key} className="ek-chart__bar" fill={s.color}
                        d={barPath(x0 + j * (barWidth + BAR_GAP), y(value), barWidth, height - y(value))} />
                    );
                  })}
                  <text className="ek-chart__category" x={i * band + band / 2} y={height + 24} textAnchor="middle" aria-hidden="true">
                    {useShort && category.shortLabel ? category.shortLabel : category.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
        {active !== null ? (
          <div className="ek-chart__tooltip" style={{ left: tooltipX, top: tooltipTop, transform: "translate(-50%, -100%)" }}
            aria-hidden="true">
            <p className="ek-chart__tooltip-title">{categories[active].label}</p>
            {series.map((s) => (
              <p key={s.key} className="ek-chart__tooltip-row">
                <span className="ek-chart__tooltip-key" style={{ "--swatch": s.color } as CSSProperties} />
                <span className="ek-chart__tooltip-value">{numberFormat.format(s.values[active] ?? 0)}</span>
                <span>{s.label}</span>
              </p>
            ))}
          </div>
        ) : null}
      </div>

      {table ? (
        <div className="ek-table-wrap">
          <table className="ek-table">
            <caption className="ek-visually-hidden">{label}</caption>
            <thead>
              <tr>
                <th scope="col">{categoryHeader}</th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="ek-table__num">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((category, i) => (
                <tr key={category.key}>
                  <th scope="row">{category.label}</th>
                  {series.map((s) => (
                    <td key={s.key} className="ek-table__num">
                      {numberFormat.format(s.values[i] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </figure>
  );
}
