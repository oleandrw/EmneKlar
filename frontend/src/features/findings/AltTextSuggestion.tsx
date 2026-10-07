// Optional AI suggestion for alt text. Opt-in per click; shows what will be sent first.
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import type { Finding } from "../../core/api/types";
import { useSession } from "../../core/session";
import { Alert, Badge, Button } from "../../design-system";

interface Prepared {
  available: boolean;
  reason: string | null;
  payload_summary: string | null;
  needs_confirmation: boolean;
  route: { provider: string; model: string; reason: string } | null;
}

interface Suggestion {
  suggestion: string;
  label: string;
  provider: string;
  model: string;
}

export function AltTextSuggestion({ finding, onUse }: { finding: Finding; onUse: (text: string) => void }) {
  const session = useSession();
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [result, setResult] = useState<Suggestion | null>(null);
  const prepare = useMutation({
    mutationFn: () => api.post<Prepared>("/api/ai/tasks/alt-text/prepare", { finding_id: finding.id }),
    onSuccess: (data) => {
      setPrepared(data);
      if (data.available && !data.needs_confirmation) run.mutate();
    },
  });
  const run = useMutation({
    mutationFn: () => api.post<Suggestion>("/api/ai/tasks/alt-text", { finding_id: finding.id, confirmed: true }),
    onSuccess: setResult,
  });

  const configured = session.ai.providers_enabled.length > 0 && session.flags.ai_alt_text !== false;
  if (!configured) {
    return (
      <p className="ek-xs ek-muted">
        KI-forslag til alt-tekst krever en KI-leverandør med bildeanalyse.{" "}
        <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>
      </p>
    );
  }

  return (
    <div className="ek-stack" data-gap="2">
      {!prepared ? (
        <div>
          <Button size="sm" icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate()} loading={prepare.isPending}>
            Foreslå alt-tekst med KI
          </Button>
        </div>
      ) : null}
      {prepare.error ? <Alert tone="danger">{(prepare.error as Error).message}</Alert> : null}
      {prepared && !prepared.available ? (
        <Alert tone="info" title="KI-forslag er ikke tilgjengelig">
          {prepared.reason}
        </Alert>
      ) : null}
      {prepared?.available && prepared.needs_confirmation && !result ? (
        <Alert
          tone="warning"
          title="Bekreft før innhold sendes"
          actions={
            <>
              <Button size="sm" onClick={() => setPrepared(null)}>
                Avbryt
              </Button>
              <Button size="sm" variant="primary" onClick={() => run.mutate()} loading={run.isPending}>
                Send og foreslå
              </Button>
            </>
          }
        >
          {prepared.payload_summary}
          {prepared.route ? ` Modell: ${prepared.route.model} (${prepared.route.provider}).` : null}
        </Alert>
      ) : null}
      {run.error ? <Alert tone="danger">{(run.error as Error).message}</Alert> : null}
      {result ? (
        <div className="ek-card ek-card--tone ek-card--compact" data-tone="violet">
          <div className="ek-stack" data-gap="2">
            <Badge tone="violet" icon={<Sparkles aria-hidden="true" />}>
              {result.label}
            </Badge>
            <p>«{result.suggestion}»</p>
            <div className="ek-cluster">
              <Button size="sm" variant="primary" onClick={() => onUse(result.suggestion)}>
                Bruk forslaget i feltet
              </Button>
              <span className="ek-xs ek-muted">
                {result.model} · {result.provider}
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
