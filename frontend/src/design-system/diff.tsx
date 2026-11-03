/*
 * Side-by-side before/after view. Changed lines are marked with "−"/"+"
 * symbols and screen-reader text, not only with colour.
 */
import { useMemo } from "react";

export interface DiffLine {
  kind: "same" | "del" | "add";
  text: string;
}

/** Line diff (LCS) – small inputs only (Canvas pages, a few thousand lines at most). */
export function diffLines(before: string, after: string): { left: DiffLine[]; right: DiffLine[] } {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > 4_000_000) {
    return {
      left: a.map((text) => ({ kind: "del", text })),
      right: b.map((text) => ({ kind: "add", text })),
    };
  }
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      left.push({ kind: "same", text: a[i] });
      right.push({ kind: "same", text: b[j] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      left.push({ kind: "del", text: a[i++] });
    } else {
      right.push({ kind: "add", text: b[j++] });
    }
  }
  while (i < a.length) left.push({ kind: "del", text: a[i++] });
  while (j < b.length) right.push({ kind: "add", text: b[j++] });
  return { left, right };
}

const MARK = { same: " ", del: "−", add: "+" } as const;
const SR = { same: "", del: "Fjernet: ", add: "Lagt til: " } as const;

function Pane({ title, lines }: { title: string; lines: DiffLine[] }) {
  return (
    <div className="ek-diff__pane">
      <div className="ek-diff__title">{title}</div>
      <ol className="ek-diff__lines" aria-label={title}>
        {lines.map((line, index) => (
          <li key={index} className="ek-diff__line" data-kind={line.kind}>
            <span className="ek-diff__marker" aria-hidden="true">
              {MARK[line.kind]}
            </span>
            <span>
              {SR[line.kind] ? <span className="ek-visually-hidden">{SR[line.kind]}</span> : null}
              {line.text || " "}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function DiffView({
  before,
  after,
  beforeTitle = "Før",
  afterTitle = "Etter",
}: {
  before: string;
  after: string;
  beforeTitle?: string;
  afterTitle?: string;
}) {
  const { left, right } = useMemo(() => diffLines(before, after), [before, after]);
  const changed = left.filter((l) => l.kind === "del").length + right.filter((l) => l.kind === "add").length;
  return (
    <div className="ek-stack" data-gap="2">
      <p className="ek-small ek-muted">
        {changed === 0 ? "Ingen forskjeller." : `${changed} endrede linjer. «−» er fjernet, «+» er lagt til.`}
      </p>
      <div className="ek-diff">
        <Pane title={beforeTitle} lines={left} />
        <Pane title={afterTitle} lines={right} />
      </div>
    </div>
  );
}
