// The detail view of a finding, built for fixing: where it is (with direct links into Canvas), the fix itself, and
// quick navigation to the next finding. The rule basis and technical details are kept, one click away.
import { ChevronLeft, ChevronRight, ExternalLink as ExternalIcon, PencilLine, ListTree } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import type { Finding } from "../../core/api/types";
import { classificationFor, CONFIDENCE, LEGAL_STATUS, OBJECT_TYPE, SEVERITY, TEST_METHOD } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Disclosure,
  ExternalButtonLink,
  ExternalLink,
  KeyValue,
  TextArea,
} from "../../design-system";
import { AiBadge } from "../../core/ai";
import { useFindingActions } from "./api";
import { FixPanel } from "./FixPanel";
import { availableConfirmations, ConfirmSection, MediaKindSection, TextAlternativeHints } from "./MediaCheck";

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

export interface FindingNav {
  /** 0-based position in the current list (all pages). */
  index: number;
  total: number;
  onPrev?: () => void;
  onNext?: () => void;
  /** Ids of the next findings (their KI-forslag are prepared first). */
  upcoming?: number[];
}

/** Where the finding is, with direct links: open in Canvas (with the text highlighted where possible), edit in Canvas,
 * the module item. Opens in a new tab. */
function WhereSection({ finding }: { finding: Finding }) {
  const links = finding.canvas;
  const view = links?.highlight ?? links?.view ?? finding.object_url;
  const blueprint = (finding.evidence?.blueprint ?? null) as
    { locked?: boolean; child_content?: boolean; master_content?: boolean } | null;
  const modules = finding.location?.modules ?? (finding.location?.module ? [finding.location.module] : []);
  return (
    <section className="ek-stack" data-gap="2" aria-labelledby={`hvor-${finding.id}`}>
      <h3 id={`hvor-${finding.id}`}>Hvor</h3>
      <KeyValue
        items={[
          [OBJECT_TYPE[finding.object_type ?? ""] ?? "Innhold", finding.object_title ?? "–"],
          ...(modules.length ? ([[modules.length > 1 ? "Moduler" : "Modul", modules.join(", ")]] as [string, string][]) : []),
        ]}
      />
      <div className="ek-cluster" data-gap="2">
        {view ? (
          <ExternalButtonLink href={view} icon={<ExternalIcon aria-hidden="true" />}>Åpne i Canvas</ExternalButtonLink>
        ) : null}
        {links?.edit ? (
          <ExternalButtonLink href={links.edit} icon={<PencilLine aria-hidden="true" />} variant="ghost">Rediger i Canvas</ExternalButtonLink>
        ) : null}
        {links?.module_item ? (
          <ExternalButtonLink href={links.module_item} icon={<ListTree aria-hidden="true" />} variant="ghost">Vis i modulen</ExternalButtonLink>
        ) : null}
      </div>
      {links?.highlight ? (
        <p className="ek-xs ek-muted">Canvas markerer «{decodeURIComponent(links.highlight.split("#:~:text=")[1] ?? "").replace(/%2D/g, "-")}» når siden åpnes, i nettlesere som støtter det.</p>
      ) : view ? (
        <p className="ek-xs ek-muted">Canvas kan ikke åpne et bestemt element direkte. Bruk utdraget og sammenhengen under for å finne stedet.</p>
      ) : null}
      {/* «restricted_by_master_course» means different things: in an associated course the content is locked here; in
          the Blueprint course itself it is locked in the associated courses only and can be edited here. */}
      {blueprint?.child_content && blueprint.locked ? (
        <Alert tone="warning" title="Låst av Blueprint">
          Innholdet er låst av et Blueprint-emne. Du kan likevel godkjenne rettingen – Canvas avgjør ved publisering om den kan
          lagres her, og hvis ikke kan du flytte den til Blueprint-emnet med ett klikk i endringskøen.
        </Alert>
      ) : blueprint?.child_content ? (
        <p className="ek-xs ek-muted">Innholdet kommer fra et Blueprint-emne. En endring her gjelder bare dette emnet.</p>
      ) : blueprint?.master_content && blueprint.locked ? (
        <p className="ek-xs ek-muted">
          Elementet er låst i de tilknyttede emnene. Du kan endre det her i Blueprint-emnet; endringen når de tilknyttede
          emnene ved neste synkronisering.
        </p>
      ) : null}
    </section>
  );
}

export function FindingDetail({ finding, open, onClose, nav }: {
  finding: Finding | null;
  open: boolean;
  onClose: () => void;
  nav?: FindingNav;
}) {
  const actions = useFindingActions();
  const [note, setNote] = useState("");
  const [ignoring, setIgnoring] = useState(false);
  useEffect(() => {
    setIgnoring(false);
    setNote("");
  }, [finding?.id]);
  if (!finding) return null;
  // «Avvik» only in universal design; «Feil» for a dead link or a wrong answer key.
  const cls = classificationFor(finding.classification, finding.domain);
  const rule = finding.rule;
  const legal = finding.legal ? LEGAL_STATUS[finding.legal.status] : null;
  const evidence = finding.evidence ?? {};
  const rows = evidenceRows(evidence);
  const exemption = typeof evidence.exemption_hint === "string" ? evidence.exemption_hint : null;
  const automatic = Array.isArray(evidence.automatically_checked) ? (evidence.automatically_checked as string[]) : null;
  const manual = Array.isArray(evidence.requires_manual_check) ? (evidence.requires_manual_check as string[]) : null;
  const sources = Array.isArray(evidence.sources) ? (evidence.sources as SourceQuote[]) : null;
  const dismiss = DISMISS[finding.domain === "quiz_ai" ? "quiz" : finding.domain] ?? DISMISS.default;
  const next = () => (nav?.onNext ? nav.onNext() : onClose());
  const fixable = finding.fix && finding.status !== "fixed";
  const manualCheck = finding.classification === "manual_check";
  const confirmations = availableConfirmations(finding);
  const confirmable = confirmations.length > 0;
  // Only an exemption to confirm (older documents): the content itself still needs fixing unless the exemption applies.
  const onlyExemption = confirmable && confirmations.every((c) => c.requires_evidence);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!event.altKey || event.ctrlKey || event.metaKey) return;
    const key = event.key.toLowerCase();
    if (key === "n" && nav?.onNext) {
      event.preventDefault();
      nav.onNext();
    } else if (key === "p" && nav?.onPrev) {
      event.preventDefault();
      nav.onPrev();
    }
  };

  return (
    <Dialog open={open} onClose={onClose} size="xl" title={finding.title} description={finding.message}>
      <div className="ek-stack" data-gap="6" onKeyDown={onKeyDown}>
        <div className="ek-finding-nav">
          <div className="ek-cluster" data-gap="2">
            <Badge tone={cls.tone}>{cls.label}</Badge>
            <Badge tone={SEVERITY[finding.severity].tone}>Alvorlighet: {SEVERITY[finding.severity].label}</Badge>
            {finding.test_method === "ai" ? <AiBadge /> : null}
            {finding.status !== "open" ? <Badge tone={finding.status === "verified" ? "success" : "violet"}>Status: {{ ignored: "Ignorert", verified: "Kontrollert", staged: "I endringskø", fixed: "Rettet", open: "Åpen" }[finding.status]}</Badge> : null}
          </div>
          {nav ? (
            <nav className="ek-cluster" data-gap="2" aria-label="Bla mellom funn">
              <Button size="sm" icon={<ChevronLeft aria-hidden="true" />} onClick={nav.onPrev} disabled={!nav.onPrev}>Forrige</Button>
              <span className="ek-small" aria-live="polite">Funn {nav.index + 1} av {nav.total}</span>
              <Button size="sm" onClick={nav.onNext} disabled={!nav.onNext}>Neste<ChevronRight aria-hidden="true" /></Button>
            </nav>
          ) : null}
        </div>

        <WhereSection finding={finding} />

        {sources ? (
          <section className="ek-stack" data-gap="2" aria-labelledby={`kilder-${finding.id}`}>
            <h3 id={`kilder-${finding.id}`}>Kilder i emnet</h3>
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

        {exemption ? <Alert tone="info" title="Mulig unntak">{exemption}</Alert> : null}

        {fixable ? (
          <FixPanel key={finding.id} finding={finding} onDone={next} onSkip={nav?.onNext} upcoming={nav?.upcoming ?? []}
            hasNext={Boolean(nav?.onNext)} />
        ) : (
          <section className="ek-stack" data-gap="2" aria-labelledby={`forslag-${finding.id}`}>
            <h3 id={`forslag-${finding.id}`}>{manualCheck ? "Slik kontrollerer du" : "Slik kan det rettes"}</h3>
            <p>{finding.remediation}</p>
            {!finding.fix ? (
              <p className="ek-small ek-muted">
                {onlyExemption
                  ? "EmneKlar kan ikke rette dette automatisk. Rett dokumentet og last det opp på nytt i Canvas – eller bekreft under at unntaket gjelder."
                  : confirmable
                    ? "Kontroller innholdet i Canvas. Er det i orden, bekrefter du det under."
                    : "EmneKlar kan ikke rette dette automatisk. Åpne innholdet i Canvas og rett det der."}
              </p>
            ) : null}
          </section>
        )}

        {finding.category === "media" ? (
          <>
            <TextAlternativeHints finding={finding} />
            <MediaKindSection key={`kind-${finding.id}`} finding={finding} />
          </>
        ) : null}
        <ConfirmSection key={`confirm-${finding.id}`} finding={finding} onDone={next} onClose={onClose} />

        <Disclosure summary="Hvorfor det er viktig og regelgrunnlag">
          <div className="ek-stack" data-gap="4">
            {fixable ? <p>{finding.remediation}</p> : null}
            {rule ? (
              <section className="ek-stack" data-gap="2">
                <h3>Hvorfor det er viktig</h3>
                <p>{rule.explanation}</p>
                <p><span className="ek-strong">Berørte brukere: </span>{rule.affected_users}</p>
              </section>
            ) : null}
            {rows.length ? (
              <section className="ek-stack" data-gap="2">
                <h3>Målinger</h3>
                <KeyValue items={rows} />
              </section>
            ) : null}
            {rule ? (
              <section className="ek-stack" data-gap="2">
                <h3>Krav og kilde</h3>
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
                      ) : "–",
                    ],
                    ["Testmetode", `${TEST_METHOD[finding.test_method].label}: ${TEST_METHOD[finding.test_method].description}`],
                    ["Sikkerhet", CONFIDENCE[finding.confidence]],
                    ["Regelsett", `${rule.id} · versjon ${rule.ruleset_version}`],
                  ]}
                />
                <ul className="ek-small">
                  {rule.sources.map((s) => (
                    <li key={s.url}><ExternalLink href={s.url}>{s.title}</ExternalLink></li>
                  ))}
                </ul>
              </section>
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
          </div>
        </Disclosure>

        {finding.location?.snippet || finding.location?.context ? (
          <Disclosure summary="Teknisk informasjon (kode og sammenheng)">
            <div className="ek-stack" data-gap="2">
              {finding.location?.snippet ? (
                <pre className="ek-code-block" aria-label="Utdrag av koden">{finding.location.snippet}</pre>
              ) : null}
              {finding.location?.context ? <p className="ek-small ek-muted">Sammenheng: «{finding.location.context}»</p> : null}
            </div>
          </Disclosure>
        ) : null}

        <section className="ek-stack" data-gap="2" aria-labelledby={`ignorer-${finding.id}`}>
          <h3 id={`ignorer-${finding.id}`}>{dismiss.heading}</h3>
          {finding.status === "ignored" ? (
            <div>
              <Button onClick={() => actions.reopen.mutate(finding.id, { onSuccess: onClose })} loading={actions.reopen.isPending}>
                {dismiss.reopen}
              </Button>
            </div>
          ) : ignoring ? (
            <div className="ek-stack" data-gap="2">
              <TextArea label="Begrunnelse" optional hint={dismiss.hint} value={note} onChange={(e) => setNote(e.target.value)}
                maxLength={1000} />
              <div className="ek-cluster">
                <Button onClick={() => setIgnoring(false)}>Avbryt</Button>
                <Button variant="primary" loading={actions.ignore.isPending}
                  onClick={() => actions.ignore.mutate({ id: finding.id, note: note || undefined }, { onSuccess: next })}>
                  {dismiss.confirm}
                </Button>
              </div>
            </div>
          ) : (
            <div><Button onClick={() => setIgnoring(true)}>{dismiss.start}</Button></div>
          )}
        </section>
      </div>
    </Dialog>
  );
}
