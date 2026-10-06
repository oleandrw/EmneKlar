import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { Job } from "../../core/api/types";
import { formatDuration, formatDurationRange, formatNumber } from "../../core/format";
import { DOMAIN_LABEL, type Domain } from "../../core/labels";
import { Alert, Button, ConfirmDialog, Disclosure, ProgressBar } from "../../design-system";
import { FINAL_STATUSES, jobAction } from "./useJob";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Venter på å starte",
  running: "Pågår",
  pausing: "Settes på pause – fullfører pågående kontroller …",
  paused: "Satt på pause",
  cancelling: "Avbryter …",
  completed: "Fullført",
  failed: "Feilet",
  cancelled: "Avbrutt",
  interrupted: "Avbrutt fordi EmneKlar ble avsluttet",
};

export function etaText(job: Job): string | null {
  const eta = job.progress.eta;
  if (FINAL_STATUSES.has(job.status) || !job.progress.determinate) return null;
  if (job.status === "paused" || job.status === "pausing") return "Satt på pause";
  if (eta.state === "calculating") return "Beregner estimert tid …";
  if (eta.state === "done") return "Straks ferdig";
  if (eta.state === "range" && eta.low_seconds != null && eta.high_seconds != null) {
    return formatDurationRange(eta.low_seconds, eta.high_seconds);
  }
  if (eta.seconds != null) return formatDuration(eta.seconds);
  return "Beregner estimert tid …";
}

function findingsByDomain(findings: Record<string, number>): { domain: Domain; count: number }[] {
  const totals: Record<string, number> = {};
  for (const [key, count] of Object.entries(findings)) {
    const domain = key.split(":")[0];
    totals[domain] = (totals[domain] ?? 0) + count;
  }
  return Object.entries(totals).map(([domain, count]) => ({ domain: domain as Domain, count }));
}

/** Announces only coarse milestones, so screen readers are not flooded. */
function useMilestoneAnnouncement(job: Job): string {
  const [message, setMessage] = useState("");
  const last = useRef<string>("");
  useEffect(() => {
    const p = job.progress;
    let key = `${job.status}:${p.phase}`;
    let text: string;
    if (FINAL_STATUSES.has(job.status)) text = `Analysen er ${STATUS_TEXT[job.status].toLowerCase()}.`;
    else if (p.determinate && p.percent != null) {
      const quarter = Math.floor(p.percent / 25) * 25;
      key += `:${quarter}`;
      text = quarter > 0 ? `${quarter} prosent fullført.` : `${p.phase_label}.`;
    } else text = `${p.phase_label}.`;
    if (key !== last.current) {
      last.current = key;
      setMessage(text);
    }
  }, [job]);
  return message;
}

export function ProgressPanel({ job, onBackground }: { job: Job; onBackground?: () => void }) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const action = useMutation({ mutationFn: (kind: "pause" | "resume" | "cancel") => jobAction(job.id, kind) });
  const p = job.progress;
  const announcement = useMilestoneAnnouncement(job);
  const final = FINAL_STATUSES.has(job.status);
  const listTotal = p.types.list?.total ?? 0;
  const listDone = p.types.list?.done ?? 0;
  const eta = etaText(job);
  const typeRows = Object.entries(p.types).filter(([key]) => key !== "list");
  const findings = findingsByDomain(p.findings);

  return (
    <div className="ek-stack" data-gap="6">
      <div className="ek-visually-hidden" role="status" aria-live="polite">
        {announcement}
      </div>
      <div className="ek-stack" data-gap="2">
        <div className="ek-cluster" data-justify="between">
          <span className="ek-small ek-muted">
            Steg {p.phase_index || 1} av {p.phase_count || 1}: {p.phase_label}
          </span>
          <span className="ek-small ek-strong">{STATUS_TEXT[job.status]}</span>
        </div>
        {p.determinate && p.percent != null ? (
          <>
            <p className="ek-stat__value" aria-hidden="true">
              {p.percent} % fullført
            </p>
            <ProgressBar value={p.percent} label="Fremdrift for analysen" valueText={`${p.percent} prosent fullført`} />
            <p className="ek-small">
              {final
                ? `${formatNumber(p.done)} av ${formatNumber(p.total)} elementer behandlet`
                : `Behandler element ${formatNumber(Math.min(p.done + 1, p.total))} av ${formatNumber(p.total)}`}
            </p>
          </>
        ) : (
          <>
            <ProgressBar
              value={null}
              label="Henter innhold fra Canvas"
              valueText={`${listDone} av ${listTotal} innholdslister hentet`}
            />
            <p className="ek-small">
              Kartlegger innhold – {listDone} av {listTotal} innholdslister hentet. Prosent og tid vises når omfanget er
              kjent.
            </p>
          </>
        )}
      </div>

      {!final ? (
        <div className="ek-grid" data-cols="2">
          <div className="ek-stack" data-gap="1">
            <span className="ek-small ek-muted">Estimert tid igjen</span>
            <span className="ek-strong">{eta ?? "Beregner estimert tid …"}</span>
          </div>
          <div className="ek-stack" data-gap="1">
            <span className="ek-small ek-muted">Nå analyseres</span>
            <span className="ek-strong ek-break">{p.current_item ?? "–"}</span>
            {p.current_operation ? <span className="ek-small ek-muted">Aktiv kontroll: {p.current_operation}</span> : null}
          </div>
        </div>
      ) : null}

      {typeRows.length > 0 ? (
        <table className="ek-table" style={{ maxWidth: "28rem" }}>
          <caption className="ek-visually-hidden">Fremdrift per innholdstype</caption>
          <thead>
            <tr>
              <th scope="col">Innholdstype</th>
              <th scope="col" className="ek-table__num">
                Ferdig
              </th>
            </tr>
          </thead>
          <tbody>
            {typeRows.map(([key, t]) => (
              <tr key={key}>
                <th scope="row" style={{ fontWeight: 500 }}>
                  {t.label}
                </th>
                <td className="ek-table__num">
                  {t.done}/{t.total}
                  {t.failed ? <span className="ek-xs ek-muted"> ({t.failed} feilet)</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <div className="ek-stack" data-gap="2">
        <h3>Funn så langt</h3>
        {findings.length === 0 ? (
          <p className="ek-small ek-muted">Ingen funn registrert ennå.</p>
        ) : (
          <ul className="ek-list-reset ek-cluster" data-gap="2">
            {findings.map((f) => (
              <li key={f.domain} className="ek-badge" data-tone="info">
                {DOMAIN_LABEL[f.domain] ?? f.domain}: {formatNumber(f.count)}
              </li>
            ))}
          </ul>
        )}
      </div>

      {job.status === "failed" ? (
        <Alert tone="danger" role="alert" title="Analysen feilet">
          {job.error}
        </Alert>
      ) : null}

      {!final ? (
        <div className="ek-cluster">
          {job.supports_pause && job.status === "running" ? (
            <Button onClick={() => action.mutate("pause")} loading={action.isPending}>
              Pause
            </Button>
          ) : null}
          {job.supports_pause && (job.status === "paused" || job.status === "pausing") ? (
            <Button variant="primary" onClick={() => action.mutate("resume")} loading={action.isPending}>
              Fortsett
            </Button>
          ) : null}
          <Button variant="danger" onClick={() => setConfirmCancel(true)} disabled={job.status === "cancelling"}>
            Avbryt
          </Button>
          {onBackground ? <Button onClick={onBackground}>Kjør i bakgrunnen</Button> : null}
        </div>
      ) : null}

      <Disclosure summary="Vis detaljer">
        <div className="ek-stack" data-gap="2">
          <p className="ek-small">
            Tid beregnes ut fra hvor lang tid hver type kontroll faktisk har tatt i denne analysen. Når usikkerheten er
            stor, vises et intervall.
          </p>
          {p.messages.length ? (
            <ul className="ek-small">
              {p.messages.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          ) : (
            <p className="ek-small ek-muted">Ingen meldinger.</p>
          )}
        </div>
      </Disclosure>

      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={() => {
          action.mutate("cancel");
          setConfirmCancel(false);
        }}
        title="Avbryte analysen?"
        confirmLabel="Avbryt analysen"
        cancelLabel="Fortsett analysen"
        danger
      >
        <p>Funn som allerede er registrert, beholdes og merkes som en avbrutt analyse.</p>
      </ConfirmDialog>
    </div>
  );
}
