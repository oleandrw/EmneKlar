// Alt text review: the image itself beside its context, the KI-forslag (prepared ahead in the background queue) and
// the field the teacher decides with. Nothing is sent to an AI provider before the teacher has seen what will be sent.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageOff, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import type { AltSuggestion, Finding } from "../../core/api/types";
import { useSession } from "../../core/session";
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Spinner, TextArea, type Tone } from "../../design-system";
import { altText, useAltStatus, type AltPlan } from "./api";

export const SUGGESTION_STATUS: Record<AltSuggestion["status"], { label: string; tone: Tone }> = {
  none: { label: "Ikke laget ennå", tone: "neutral" },
  queued: { label: "I kø", tone: "info" },
  running: { label: "Genereres …", tone: "info" },
  ready: { label: "KI-forslag klart", tone: "violet" },
  failed: { label: "Forslaget feilet", tone: "danger" },
  stale: { label: "Bildet eller teksten er endret", tone: "warning" },
};

interface ImageContext {
  heading?: string | null;
  before?: string | null;
  same_block?: string | null;
  after?: string | null;
  caption?: string | null;
  link_href?: string | null;
}

function shorten(text: string, max = 280): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()} …` : text;
}

/** The finding's image, fetched through EmneKlar (Canvas images need the teacher's Canvas access; the token stays
 * in the backend). */
export function FindingImage({ finding }: { finding: Finding }) {
  const [failed, setFailed] = useState(false);
  const alt = typeof finding.evidence.alt === "string" ? finding.evidence.alt : "";
  return (
    <figure className="ek-review__image">
      {failed ? (
        <div className="ek-stack ek-small ek-muted" data-gap="2" style={{ padding: "var(--space-6)", textAlign: "center" }}>
          <ImageOff aria-hidden="true" />
          <span>Bildet kunne ikke vises her (for eksempel SVG, et slettet bilde eller en side som avviser henting).</span>
        </div>
      ) : (
        // The alt text here describes the review copy itself: the current alt text (or the file) – never a guess.
        <img src={`/api/findings/${finding.id}/image`} alt={alt ? `Bildet som vurderes. Nåværende alt-tekst: ${alt}` :
          "Bildet som vurderes (har ingen alt-tekst ennå)"} onError={() => setFailed(true)} />
      )}
    </figure>
  );
}

/** Where the image sits and what is written around it – what the alt text has to fit into. */
export function ImageContextView({ finding }: { finding: Finding }) {
  const context = (finding.evidence.image_context ?? {}) as ImageContext;
  const fallback = finding.location?.context;
  const current = finding.evidence.alt;
  const surrounding = [context.before, context.same_block, context.after].filter(Boolean) as string[];
  return (
    <div className="ek-review__context">
      {context.heading ? <p className="ek-small"><span className="ek-strong">Under overskriften: </span>«{context.heading}»</p> : null}
      {surrounding.length ? (
        <>
          <span className="ek-strong ek-small">Teksten rundt bildet</span>
          {context.before ? <blockquote aria-label="Tekst før bildet">{shorten(context.before)}</blockquote> : null}
          {context.same_block ? <blockquote aria-label="Tekst i samme avsnitt">{shorten(context.same_block)}</blockquote> : null}
          {context.after ? <blockquote aria-label="Tekst etter bildet">{shorten(context.after)}</blockquote> : null}
        </>
      ) : fallback ? (
        <blockquote>{shorten(fallback)}</blockquote>
      ) : (
        <p className="ek-small ek-muted">Det står ingen tekst rett ved bildet.</p>
      )}
      {context.caption ? <p className="ek-small"><span className="ek-strong">Bildetekst: </span>«{context.caption}»</p> : null}
      {context.link_href ? <p className="ek-small"><span className="ek-strong">Bildet er en lenke til: </span>{context.link_href}</p> : null}
      <p className="ek-small">
        <span className="ek-strong">Nåværende alt-tekst: </span>
        {typeof current === "string" ? (current ? `«${current}»` : "tom (merket som dekorativt)") : "mangler"}
      </p>
    </div>
  );
}

/** «Forbered KI-forslag»: shows exactly what will be sent before anything leaves the machine. */
export function AltConsentDialog({ courseId, findingIds, open, onClose, onStarted }: {
  courseId: string;
  findingIds: number[];
  open: boolean;
  onClose: () => void;
  onStarted?: (added: number) => void;
}) {
  const [plan, setPlan] = useState<AltPlan | null>(null);
  const client = useQueryClient();
  const prepare = useMutation({ mutationFn: () => altText.prepareBatch(courseId, findingIds), onSuccess: setPlan });
  const start = useMutation({
    mutationFn: () => altText.startBatch(courseId, findingIds),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ["alt-text"] });
      void client.invalidateQueries({ queryKey: ["findings"] });
      onStarted?.(result.added);
      onClose();
    },
  });
  useEffect(() => {
    if (open) prepare.mutate();
    else setPlan(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const available = plan?.available ?? false;
  return (
    <ConfirmDialog
      open={open}
      onClose={onClose}
      onConfirm={() => start.mutate()}
      title="Forbered KI-forslag til alt-tekst"
      confirmLabel={plan?.needs_confirmation ? "Send og lag forslag" : "Lag forslag"}
      loading={start.isPending}
      confirmDisabled={!available || (plan?.to_send ?? 1) === 0}
    >
      {prepare.isPending ? <Spinner label="Ser hva som skal sendes …" /> : null}
      {prepare.error ? <Alert tone="danger">{(prepare.error as Error).message}</Alert> : null}
      {plan && !plan.available ? <Alert tone="info" title="KI-forslag er ikke tilgjengelig">{plan.reason}</Alert> : null}
      {plan?.available ? (
        <>
          <p>
            {plan.to_send ?? 0} av {plan.images ?? 0} bilder får forslag
            {plan.already_ready ? ` (${plan.already_ready} er allerede klare og sendes ikke på nytt)` : ""}. Forslagene lages i
            bakgrunnen, tre om gangen – bildet du ser på, kommer først.
          </p>
          <p>{plan.payload_summary}</p>
          {plan.route ? <p className="ek-muted">Modell: {plan.route.model} ({plan.route.provider}).</p> : null}
          <p className="ek-muted">Forslagene er KI-forslag som må vurderes. Ingenting endres i Canvas før du godkjenner og publiserer.</p>
        </>
      ) : null}
      {start.error ? <Alert tone="danger" role="alert">{(start.error as Error).message}</Alert> : null}
    </ConfirmDialog>
  );
}

/** The suggestion for one image: status, text and «Bruk forslaget». Also moves this image (and the next ones) to the
 * front of the queue when suggestions are allowed for the course. */
export function AltSuggestionPanel({ finding, upcoming, onUse, onReady }: {
  finding: Finding;
  upcoming: number[];
  onUse: (text: string, decorative: boolean) => void;
  /** Called once when a suggestion is (or becomes) ready – the editor pre-fills an untouched field with it. */
  onReady?: (suggestion: AltSuggestion) => void;
}) {
  const session = useSession();
  const courseId = finding.course_id ?? null;
  const status = useAltStatus(courseId, [finding.id]);
  const client = useQueryClient();
  const [consent, setConsent] = useState(false);
  const prioritized = useRef<number | null>(null);
  const reported = useRef<number | null>(null);
  const suggestion = useMemo<AltSuggestion>(
    () => status.data?.items[String(finding.id)] ?? finding.alt_suggestion ?? { status: "none" },
    [status.data, finding.id, finding.alt_suggestion],
  );
  const queue = status.data?.queue;

  useEffect(() => {
    if (suggestion.status === "ready" && reported.current !== finding.id) {
      reported.current = finding.id;
      onReady?.(suggestion);
    }
  }, [suggestion, finding.id, onReady]);

  useEffect(() => {
    if (!courseId || prioritized.current === finding.id) return;
    prioritized.current = finding.id;
    void altText.prioritize(courseId, [finding.id, ...upcoming].slice(0, 6)).then(() =>
      client.invalidateQueries({ queryKey: ["alt-text", courseId] }));
  }, [courseId, finding.id, upcoming, client]);

  const retry = useMutation({
    mutationFn: () => altText.retry(finding.id),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["alt-text"] }),
  });

  const configured = session.ai.providers_enabled.length > 0 && session.flags.ai_alt_text !== false;
  if (!configured) {
    return (
      <p className="ek-xs ek-muted">
        KI-forslag til alt-tekst krever en KI-leverandør med bildeanalyse.{" "}
        <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>. Du kan alltid skrive alt-teksten selv.
      </p>
    );
  }
  const info = SUGGESTION_STATUS[suggestion.status];
  return (
    <div className="ek-card ek-card--tone ek-card--compact" data-tone="violet">
      <div className="ek-stack" data-gap="2">
        <div className="ek-cluster" data-justify="between">
          <Badge tone="violet" icon={<Sparkles aria-hidden="true" />}>KI-forslag – må vurderes</Badge>
          <Badge tone={info.tone} dot>{info.label}</Badge>
        </div>
        <div aria-live="polite">
          {suggestion.status === "ready" ? (
            <div className="ek-stack" data-gap="2">
              <p>{suggestion.decorative ? "Forslag: bildet ser dekorativt ut (tom alt-tekst)." : `«${suggestion.suggestion}»`}</p>
              {suggestion.notes ? <p className="ek-xs ek-muted">Merknad: {suggestion.notes}</p> : null}
              <div className="ek-cluster">
                <Button size="sm" variant="primary" onClick={() => onUse(suggestion.suggestion ?? "", Boolean(suggestion.decorative))}>
                  Bruk forslaget
                </Button>
                <span className="ek-xs ek-muted">
                  {suggestion.model ?? ""}{suggestion.confidence ? ` · sikkerhet: ${{ high: "høy", medium: "middels", low: "lav" }[suggestion.confidence] ?? suggestion.confidence}` : ""}
                </span>
              </div>
            </div>
          ) : suggestion.status === "queued" || suggestion.status === "running" ? (
            <Spinner label={suggestion.status === "running" ? "Lager forslag …" : `I kø${queue ? ` (${queue.queued} venter)` : ""} …`} />
          ) : suggestion.status === "failed" ? (
            <div className="ek-stack" data-gap="2">
              <p className="ek-small">{suggestion.error ?? "Forslaget kunne ikke lages."}</p>
              <div><Button size="sm" icon={<RefreshCw aria-hidden="true" />} onClick={() => retry.mutate()} loading={retry.isPending}>Prøv igjen</Button></div>
            </div>
          ) : queue?.consented ? (
            <Spinner label="Legger bildet i køen …" />
          ) : (
            <div className="ek-stack" data-gap="2">
              <p className="ek-small">Få et forslag laget i bakgrunnen – også for de neste bildene i listen, så de er klare når du kommer dit.</p>
              <div><Button size="sm" icon={<Sparkles aria-hidden="true" />} onClick={() => setConsent(true)}>Foreslå alternativtekst med KI</Button></div>
            </div>
          )}
        </div>
        {retry.error ? <Alert tone="danger">{(retry.error as Error).message}</Alert> : null}
      </div>
      {courseId ? (
        <AltConsentDialog courseId={courseId} findingIds={[]} open={consent} onClose={() => setConsent(false)}
          onStarted={() => void altText.prioritize(courseId, [finding.id, ...upcoming].slice(0, 6))} />
      ) : null}
    </div>
  );
}

/** The alt text editor used by the fix panel: image and context side by side with suggestion and decision. */
export function AltTextReview({ finding, upcoming, text, setText, decorative, setDecorative }: {
  finding: Finding;
  upcoming: number[];
  text: string;
  setText: (value: string) => void;
  decorative: boolean;
  setDecorative: (value: boolean) => void;
}) {
  const touched = useRef(false);
  const onReady = useCallback((s: AltSuggestion) => {
    if (touched.current) return;
    setDecorative(Boolean(s.decorative));
    if (!s.decorative && s.suggestion) setText(s.suggestion);
  }, [setDecorative, setText]);
  return (
    <div className="ek-review">
      <div className="ek-review__media">
        <FindingImage finding={finding} />
        <ImageContextView finding={finding} />
      </div>
      <div className="ek-stack" data-gap="4">
        <AltSuggestionPanel finding={finding} upcoming={upcoming} onReady={onReady} onUse={(value, isDecorative) => {
          touched.current = true;
          setDecorative(isDecorative);
          if (!isDecorative) setText(value);
        }} />
        <Checkbox
          label="Bildet er dekorativt (tom alt-tekst)"
          hint="Velg dette bare når bildet ikke formidler noe som ikke står i teksten."
          checked={decorative}
          onChange={(e) => setDecorative(e.target.checked)}
        />
        {!decorative ? (
          <TextArea
            label="Alternativ tekst"
            value={text}
            rows={3}
            maxLength={500}
            onChange={(e) => {
              touched.current = true;
              setText(e.target.value);
            }}
            hint={`Beskriv det bildet formidler her – kort og presist, normalt under 150 tegn (${text.trim().length} tegn). Ikke gjenta teksten rundt bildet.`}
          />
        ) : null}
      </div>
    </div>
  );
}
