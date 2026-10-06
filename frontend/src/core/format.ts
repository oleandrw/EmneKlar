// Norwegian (bokmål) formatting helpers.

const dateTime = new Intl.DateTimeFormat("nb-NO", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("nb-NO", { dateStyle: "medium" });
const number = new Intl.NumberFormat("nb-NO");

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "–" : dateTime.format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "–" : dateOnly.format(date);
}

export function formatNumber(value: number): string {
  return number.format(value);
}

/** "2 min 14 sek", "45 sek", "1 t 3 min" */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s} sek`;
  const minutes = Math.floor(s / 60);
  const seconds = s % 60;
  if (minutes < 60) return seconds ? `${minutes} min ${seconds} sek` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} t ${rest} min` : `${hours} t`;
}

/** Rounded, honest range: "ca. 2–4 min" or "under 1 min". */
export function formatDurationRange(low: number, high: number): string {
  if (high < 60) return "under 1 min";
  if (high < 3600) {
    const lo = Math.max(1, Math.floor(low / 60));
    const hi = Math.max(lo + 1, Math.ceil(high / 60));
    return `ca. ${lo}–${hi} min`;
  }
  const lo = Math.max(1, Math.floor(low / 3600));
  const hi = Math.max(lo + 1, Math.ceil(high / 3600));
  return `ca. ${lo}–${hi} timer`;
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (Number.isNaN(diff)) return "–";
  if (diff < 60) return "nå nettopp";
  if (diff < 3600) return `for ${Math.floor(diff / 60)} min siden`;
  if (diff < 86400) return `for ${Math.floor(diff / 3600)} t siden`;
  return formatDateTime(value);
}

export function plural(count: number, one: string, many: string): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`;
}
