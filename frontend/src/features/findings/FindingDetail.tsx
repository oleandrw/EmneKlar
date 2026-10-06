import { useState } from "react";

import type { Finding } from "../../core/api/types";
import { CLASSIFICATION, CONFIDENCE, LEGAL_STATUS, OBJECT_TYPE, SEVERITY, TEST_METHOD } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  ExternalLink,
  KeyValue,
  TextArea,
} from "../../design-system";
import { AiBadge } from "../../core/ai";
import { useFindingActions } from "./api";
import { FixPanel } from "./FixPanel";

/** «Ignorer» means different things per domain: reject a structure suggestion, keep a quiz question. */
const DISMISS: Record<string, { heading: string; start: string; confirm: string; reopen: string; hint: string }> = {
  structure: {
    heading: "Avvis", start: "Avvis forslaget …", confirm: "Avvis forslaget", reopen: "Gjenåpne forslaget",
    hint: "Begrunnelsen lagres lokalt. Forslaget vises ikke igjen ved nye analyser.",
  },
  quiz: {
    heading: "Behold", start: "Behold spørsmålet som det er …", confirm: "Behold og skjul funnet", reopen: "Gjenåpne funnet",
    hint: "Begrunnelsen lagres lokalt. Funnet vises ikke igjen ved nye kontroller.",
  },
  default: {
    heading: "Ignorer", start: "Ignorer …", confirm: "Ignorer funnet", reopen: "Gjenåpne funnet",
    hint: "Begrunnelsen lagres lokalt og vises i rapporter. Funnet forblir ignorert ved nye analyser.",
  },
};

interface SourceQuote {
  chunk_id?: string;
  quote: string;
  title?: string | null;
}

const EVIDENCE_LABELS: Record<string, string> = {
  ratio: "Målt kontrast",
  required: "Krav",
  ratio_against_default: "Kontrast mot standardfarge",
  foreground: "Tekstfarge",
  background: "Bakgrunnsfarge",
  alt: "Alt-tekst",
  href: "Lenkemål",
  src: "Kilde",
  lix: "LIX",
  words: "Antall ord",
  file: "Fil",
  pages: "Sider",
  state: "Tilstand",
  http_status: "HTTP-status",
  final_url: "Endelig adresse",
};

function evidenceRows(evidence: Record<string, unknown>): [string, string][] {
  return Object.entries(evidence)
    .filter(([key, value]) => key in EVIDENCE_LABELS && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [EVIDENCE_LABELS[key], key.startsWith("ratio") ? `${value}:1` : String(value)]);
}

export function FindingDetail({ finding, open, onClose }: { finding: Finding | null; open: boolean; onClose: () => void }) {
  const actions = useFindingActions();
  const [note, setNote] = useState("");
  const [ignoring, setIgnoring] = useState(false);
  if (!finding) return null;
  const cls = CLASSIFICATION[finding.classification];
  const rule = finding.rule;
  const legal = finding.legal ? LEGAL_STATUS[finding.legal.status] : null;
  const evidence = finding.evidence ?? {};
  const rows = evidenceRows(evidence);
  const exemption = typeof evidence.exemption_hint === "string" ? evidence.exemption_hint : null;
  const automatic = Array.isArray(evidence.automatically_checked) ? (evidence.automatically_checked as string[]) : null;
  const manual = Array.isArray(evidence.requires_manual_check) ? (evidence.requires_manual_check as string[]) : null;
  const sources = Array.isArray(evidence.sources) ? (evidence.sources as SourceQuote[]) : null;
  const dismiss = DISMISS[finding.domain === "quiz_ai" ? "quiz" : finding.domain] ?? DISMISS.default;

  return (
    <Dialog open={open} onClose={onClose} size="lg" title={finding.title} description={finding.message}>
      <div className="ek-stack" data-gap="6">
        <div className="ek-cluster">
          <Badge tone={cls.tone}>{cls.label}</Badge>
          <Badge tone={SEVERITY[finding.severity].tone}>Alvorlighet: {SEVERITY[finding.severity].label}</Badge>
          <Badge>{TEST_METHOD[finding.test_method].label} test</Badge>
          <Badge>Sikkerhet: {CONFIDENCE[finding.confidence]}</Badge>
          {finding.test_method === "ai" ? <AiBadge /> : null}
          {finding.status !== "open" ? <Badge tone="violet">Status: {{ ignored: "Ignorert", staged: "I endringskø", fixed: "Rettet", open: "Åpen" }[finding.status]}</Badge> : null}
        </div>

        <section className="ek-stack" data-gap="2" aria-labelledby="hvor">
          <h3 id="hvor">Hvor</h3>
          <KeyValue
            items={[
              [OBJECT_TYPE[finding.object_type ?? ""] ?? "Objekt", finding.object_url ? (
                <ExternalLink href={finding.object_url}>{finding.object_title}</ExternalLink>
              ) : (
                finding.object_title ?? "–"
              )],
              ...(finding.location?.module ? ([["Modul", finding.location.module]] as [string, string][]) : []),
            ]}
          />
          {finding.location?.snippet ? (
            <pre className="ek-code-block" aria-label="Utdrag av koden">
              {finding.location.snippet}
            </pre>
          ) : null}
          {finding.location?.context ? <p className="ek-small ek-muted">Sammenheng: «{finding.location.context}»</p> : null}
        </section>

        {rule ? (
          <section className="ek-stack" data-gap="2" aria-labelledby="hvorfor">
            <h3 id="hvorfor">Hvorfor det er viktig</h3>
            <p>{rule.explanation}</p>
            <p>
              <span className="ek-strong">Berørte brukere: </span>
              {rule.affected_users}
            </p>
          </section>
        ) : null}

        {rows.length ? (
          <section className="ek-stack" data-gap="2" aria-labelledby="bevis">
            <h3 id="bevis">Målinger</h3>
            <KeyValue items={rows} />
          </section>
        ) : null}

        {rule ? (
          <section className="ek-stack" data-gap="2" aria-labelledby="krav">
            <h3 id="krav">Krav og kilde</h3>
            <KeyValue
              items={[
                [
                  "Suksesskriterium",
                  rule.wcag.length
                    ? rule.wcag.map((c) => `${c} ${rule.wcag_titles?.[c] ?? ""}`).join(", ") +
                      (rule.level ? ` (nivå ${rule.level}, WCAG ${rule.wcag_version})` : "")
                    : "Ikke knyttet til et suksesskriterium (god praksis)",
                ],
                [
                  "Status i valgt profil",
                  legal ? (
                    <span className="ek-stack" data-gap="1">
                      <Badge tone={legal.tone}>{legal.label}</Badge>
                      <span className="ek-xs ek-muted">
                        {finding.legal?.profile_title}
                        {finding.legal?.note ? ` – ${finding.legal.note}` : ""}
                      </span>
                    </span>
                  ) : (
                    "–"
                  ),
                ],
                ["Testmetode", `${TEST_METHOD[finding.test_method].label}: ${TEST_METHOD[finding.test_method].description}`],
                ["Regelsett", `${rule.id} · versjon ${rule.ruleset_version}`],
              ]}
            />
            <ul className="ek-small">
              {rule.sources.map((s) => (
                <li key={s.url}>
                  <ExternalLink href={s.url}>{s.title}</ExternalLink>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {sources ? (
          <section className="ek-stack" data-gap="2" aria-labelledby="kilder">
            <h3 id="kilder">Kilder i emnet</h3>
            {sources.length ? (
              <ul className="ek-list-reset ek-stack" data-gap="2">
                {sources.map((s, i) => (
                  <li key={i}>
                    <blockquote className="ek-quote">«{s.quote}»</blockquote>
                    {s.title ? <p className="ek-xs ek-muted">Fra «{s.title}»</p> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ek-small ek-muted">KI-modellen oppga ingen sitater som kunne bekreftes i emnets innhold.</p>
            )}
            <p className="ek-xs ek-muted">Sitatene er kontrollert mot teksten i emnet. Påstander uten bekreftet kilde vises ikke.</p>
          </section>
        ) : null}

        {exemption ? (
          <Alert tone="info" title="Mulig unntak">
            {exemption}
          </Alert>
        ) : null}
        {evidence.blueprint_locked ? (
          <Alert tone="warning" title="Låst av Blueprint">
            Innholdet er låst av et Blueprint-emne og må rettes i Blueprint-emnet.
          </Alert>
        ) : null}
        {automatic && manual ? (
          <div className="ek-grid" data-cols="2">
            <div>
              <h3>Automatisk kontrollert</h3>
              <ul className="ek-small">{automatic.map((x) => <li key={x}>{x}</li>)}</ul>
            </div>
            <div>
              <h3>Krever manuell kontroll</h3>
              <ul className="ek-small">{manual.map((x) => <li key={x}>{x}</li>)}</ul>
            </div>
          </div>
        ) : null}

        <section className="ek-stack" data-gap="2" aria-labelledby="forslag">
          <h3 id="forslag">Slik kan det rettes</h3>
          <p>{finding.remediation}</p>
        </section>

        {finding.fix && finding.status !== "fixed" ? (
          <FixPanel finding={finding} onStaged={onClose} />
        ) : null}

        <section className="ek-stack" data-gap="2" aria-labelledby="ignorer">
          <h3 id="ignorer">{dismiss.heading}</h3>
          {finding.status === "ignored" ? (
            <Button onClick={() => actions.reopen.mutate(finding.id, { onSuccess: onClose })} loading={actions.reopen.isPending}>
              {dismiss.reopen}
            </Button>
          ) : ignoring ? (
            <div className="ek-stack" data-gap="2">
              <TextArea
                label="Begrunnelse"
                optional
                hint={dismiss.hint}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={1000}
              />
              <div className="ek-cluster">
                <Button onClick={() => setIgnoring(false)}>Avbryt</Button>
                <Button
                  variant="primary"
                  loading={actions.ignore.isPending}
                  onClick={() => actions.ignore.mutate({ id: finding.id, note: note || undefined }, { onSuccess: onClose })}
                >
                  {dismiss.confirm}
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={() => setIgnoring(true)}>{dismiss.start}</Button>
          )}
        </section>
      </div>
    </Dialog>
  );
}
