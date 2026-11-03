// Shared UI for privacy-gated AI calls: show what will be sent, get explicit consent, then run.
import { Sparkles } from "lucide-react";
import { Link } from "react-router";

import { Alert, Badge, Button } from "../design-system";
import { useSession } from "./session";

export interface AiPlan {
  available: boolean;
  reason: string | null;
  payload_summary: string | null;
  needs_confirmation: boolean;
  external?: boolean;
  route: { provider: string; model: string; reason: string } | null;
}

export const AI_LABEL = "KI-forslag – må vurderes";

/** True when at least one AI provider is enabled (whether it may be used is decided per call). */
export function useAiConfigured(): boolean {
  const session = useSession();
  return session.ai.providers_enabled.length > 0;
}

export function AiNotConfigured({ what }: { what: string }) {
  return (
    <p className="ek-small ek-muted">
      {what} krever en KI-leverandør. Kjernefunksjonene virker uten KI.{" "}
      <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>
    </p>
  );
}

/**
 * Shows the result of a «prepare» call: why AI is unavailable, or the payload summary with
 * «Send» / «Avbryt». When no confirmation is needed (local model or confirmation turned off)
 * the caller may run directly, but the summary is still shown.
 */
export function AiConsent({
  plan,
  onConfirm,
  onCancel,
  confirmLabel = "Send til KI",
  loading,
}: {
  plan: AiPlan;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  loading?: boolean;
}) {
  if (!plan.available) {
    return (
      <Alert tone="info" title="KI er ikke tilgjengelig" actions={<Button size="sm" onClick={onCancel}>Lukk</Button>}>
        {plan.reason}
      </Alert>
    );
  }
  return (
    <Alert
      tone={plan.external ? "warning" : "info"}
      title={plan.external ? "Bekreft før innhold sendes" : "Klar til å bruke KI"}
      actions={
        <>
          <Button size="sm" onClick={onCancel} disabled={loading}>
            Avbryt
          </Button>
          <Button size="sm" variant="primary" icon={<Sparkles aria-hidden="true" />} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p>{plan.payload_summary}</p>
      {plan.route ? (
        <p className="ek-xs ek-muted">
          Modell: {plan.route.model} ({plan.route.provider}). {plan.route.reason}
        </p>
      ) : null}
      {plan.external === false ? <p className="ek-xs ek-muted">Modellen kjører lokalt – innholdet forlater ikke maskinen.</p> : null}
    </Alert>
  );
}

export function AiBadge() {
  return (
    <Badge tone="violet" icon={<Sparkles aria-hidden="true" />}>
      {AI_LABEL}
    </Badge>
  );
}
