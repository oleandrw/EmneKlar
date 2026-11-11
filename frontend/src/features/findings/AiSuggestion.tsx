// «Foreslå … med KI» by a text field – the same for every fix that has KI help (link text, table caption, the title of
// embedded content, a video title): request a suggestion → see and edit it → the preview follows the field → approve
// to the change queue. A suggestion is never approved by itself.
//
// * No KI service set up: a short explanation and a link to the settings – no button that cannot deliver.
// * What is sent, and to which service, is shown before the first request; once confirmed, the same task with the same
//   service is not asked again in this session (a new service is).
// * The teacher's own text is never replaced without a click («Bruk forslaget»); one request per click, never while
//   typing; errors leave the field as it is, so the fix can always be written by hand.
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";

import { AI_LABEL, AiConsent, type AiPlan } from "../../core/ai";
import { useSession } from "../../core/session";
import { Alert, Button } from "../../design-system";

export interface AiTextPlan extends AiPlan {
  task?: string;
  /** What the suggestion rests on (for example whether the link's target was read). */
  basis?: string | null;
  weak?: string | null;
}

export interface AiTextResult {
  text: string;
  basis?: string | null;
  weak?: string | null;
  provider?: string;
  provider_name?: string;
  model?: string;
  finding_id?: number;
}

const SETTINGS = "/innstillinger/ki-assistenter";
/** Consent given in this session, per task and service. */
const confirmedFor = new Set<string>();

export function resetAiConsentMemory() {
  confirmedFor.clear();
}

/** Consent for a task with a service, given earlier in this session (shared by every KI help in the app). */
export function consentGiven(task: string, provider: string | undefined): boolean {
  return confirmedFor.has(`${task}|${provider ?? ""}`);
}

export function rememberConsent(task: string, provider: string | undefined): void {
  confirmedFor.add(`${task}|${provider ?? ""}`);
}

export function AiSuggestion({ label, prepare, run, text, setText, initial, onSuggested, findingId }: {
  /** «Foreslå lenketekst med KI» */
  label: string;
  prepare: () => Promise<AiTextPlan>;
  run: (confirmed: boolean, avoid: string[]) => Promise<AiTextResult>;
  text: string;
  setText: (value: string) => void;
  /** What the field started with, and other suggestions EmneKlar filled in – they may be replaced without asking,
   *  unlike what the teacher wrote. */
  initial: string | string[];
  /** The KI text now in the field (the fix is then marked as KI-generated). */
  onSuggested?: (text: string) => void;
  /** A late answer for another finding is ignored. */
  findingId?: number;
}) {
  const session = useSession();
  const [plan, setPlan] = useState<AiTextPlan | null>(null);
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<AiTextResult | null>(null);
  const [waiting, setWaiting] = useState<AiTextResult | null>(null);
  const history = useRef<string[]>([]);
  const consentKey = (p: AiTextPlan) => `${p.task ?? label}|${p.route?.provider ?? ""}`;

  const runIt = useMutation({
    mutationFn: (confirmed: boolean) => run(confirmed, history.current.slice(-5)),
    // A failure closes the consent box, so a new attempt is one click away (the field is left as it is).
    onError: () => setAsking(false),
    onSuccess: (answer, confirmed) => {
      if (findingId !== undefined && answer.finding_id !== undefined && answer.finding_id !== findingId) return;
      if (confirmed && plan) confirmedFor.add(consentKey(plan));
      setAsking(false);
      history.current.push(answer.text);
      const replaceable = Array.isArray(initial) ? initial : [initial];
      const untouched = !text.trim() || replaceable.includes(text) || (result !== null && text === result.text);
      setResult(answer);
      if (untouched) {
        setText(answer.text);
        setWaiting(null);
        onSuggested?.(answer.text);
      } else {
        setWaiting(answer);
      }
    },
  });
  const prepareIt = useMutation({
    mutationFn: prepare,
    onSuccess: (p) => {
      setPlan(p);
      if (!p.available) return;
      if (p.needs_confirmation && !confirmedFor.has(consentKey(p))) setAsking(true);
      else runIt.mutate(p.needs_confirmation);
    },
  });

  if (session.ai.providers_enabled.length === 0) {
    return (
      <p className="ek-small ek-muted">
        KI-forslag krever en KI-tjeneste. <Link to={SETTINGS}>Sett opp KI-assistenter</Link>. Du kan alltid skrive teksten selv.
      </p>
    );
  }
  const busy = prepareIt.isPending || runIt.isPending;
  const error = (runIt.error ?? prepareIt.error) as Error | null;
  return (
    <div className="ek-stack" data-gap="2">
      <div className="ek-cluster" data-gap="2">
        <Button size="sm" icon={<Sparkles aria-hidden="true" />} loading={busy} disabled={busy || asking}
          onClick={() => {
            setWaiting(null);
            prepareIt.mutate();
          }}>
          {result ? "Nytt forslag" : label}
        </Button>
        {runIt.isPending ? (
          <span className="ek-small ek-muted" role="status">Lager forslag{plan?.route ? ` med ${plan.route.model}` : ""} …</span>
        ) : null}
      </div>
      {plan && !plan.available ? (
        <p className="ek-small">{plan.reason} <Link to={SETTINGS}>Innstillinger → KI-assistenter</Link>. Du kan skrive teksten selv.</p>
      ) : null}
      {asking && plan ? (
        <AiConsent plan={plan} onCancel={() => setAsking(false)} onConfirm={() => runIt.mutate(true)} loading={runIt.isPending}
          confirmLabel="Send og lag forslag" />
      ) : null}
      {asking && plan?.basis ? <p className="ek-xs ek-muted">{plan.basis}</p> : null}
      {result && !waiting ? (
        <p className="ek-small">
          <span className="ek-strong">{AI_LABEL}</span>.{" "}
          {result.model ? `Laget med ${result.model}${result.provider_name ? ` (${result.provider_name})` : ""}. ` : ""}
          {result.basis}
        </p>
      ) : null}
      {result?.weak && !waiting ? <p className="ek-small ek-muted">{result.weak}</p> : null}
      {waiting ? (
        <p className="ek-small">
          Nytt {AI_LABEL.toLowerCase()}: «{waiting.text}»{" "}
          <Button variant="link" size="sm" onClick={() => {
            setText(waiting.text);
            onSuggested?.(waiting.text);
            setWaiting(null);
          }}>Bruk forslaget</Button>
        </p>
      ) : null}
      {error ? (
        <Alert tone="warning" role="alert" title="Fikk ikke noe forslag">
          {error.message} Teksten i feltet er uendret, og du kan skrive den selv.
        </Alert>
      ) : null}
    </div>
  );
}
