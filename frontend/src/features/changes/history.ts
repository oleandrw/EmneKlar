// How a published change is described in every history (Canvas-verktøy, the change log, Emneoversikt): what was changed
// – from what was recorded with the change – and what happened to it.
import type { Tone } from "../../design-system";

/** «dry_run» only in entries from before the Dry run switch was removed. */
export type LogAction = "apply" | "dry_run" | "conflict" | "failed" | "undo";

export const ACTION: Record<LogAction, { label: string; tone: Tone }> = {
  apply: { label: "Publisert til Canvas", tone: "success" },
  dry_run: { label: "Ikke sendt (tidligere testmodus)", tone: "neutral" },
  conflict: { label: "Konflikt – ikke sendt", tone: "warning" },
  failed: { label: "Feilet", tone: "danger" },
  undo: { label: "Angret", tone: "info" },
};

/** «Lenketekst oppdatert · Publisert til Canvas»; «Konflikt – ikke sendt: Alt-tekst oppdatert»; only the status when
 * nothing about the change itself was recorded (never a guessed change type). */
export function historyLine(entry: { action: string; summary?: string | null }): string {
  const status = ACTION[entry.action as LogAction]?.label ?? entry.action;
  if (!entry.summary) return status;
  return entry.action === "apply" ? `${entry.summary} · ${status}` : `${status}: ${entry.summary}`;
}
