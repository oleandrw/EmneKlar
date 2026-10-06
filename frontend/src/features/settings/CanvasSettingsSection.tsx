import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, KeyRound, PlugZap } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  KeyValue,
  Spinner,
  TextField,
  useToast,
} from "../../design-system";

interface CanvasStatus {
  base_url: string | null;
  token_configured: boolean;
  identity: { id: string; name: string } | null;
  last_verified_at: string | null;
  secret_backend: string;
}

interface Capabilities {
  capabilities: { key: string; label: string; granted: boolean }[];
  blueprint: { is_blueprint: boolean; is_child: boolean; associated_course_count: number | null };
}

export function CanvasSettingsSection() {
  const client = useQueryClient();
  const toast = useToast();
  const { courseId, course } = useCurrentCourse();
  const status = useQuery({ queryKey: ["canvas-status"], queryFn: () => api.get<CanvasStatus>("/api/canvas/status") });
  const caps = useQuery({
    queryKey: ["capabilities", courseId],
    queryFn: () => api.get<Capabilities>(`/api/courses/${courseId}/capabilities`),
    enabled: Boolean(courseId),
  });
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["canvas-status"] });
    void client.invalidateQueries({ queryKey: ["session"] });
    void client.invalidateQueries({ queryKey: ["courses"] });
  };
  const verify = useMutation({
    mutationFn: () => api.post<{ identity: { name: string } }>("/api/canvas/verify"),
    onSuccess: (r) => {
      refresh();
      toast.show({ tone: "success", title: "Tilkoblingen virker", body: `Innlogget som ${r.identity.name}.` });
    },
  });
  const save = useMutation({
    mutationFn: () => api.put("/api/canvas/connection", { base_url: baseUrl ?? status.data?.base_url ?? "", token: token || null }),
    onSuccess: () => {
      setToken("");
      refresh();
      toast.show({ tone: "success", title: "Canvas-tilkoblingen er lagret" });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete("/api/canvas/token"),
    onSuccess: () => {
      setConfirmDelete(false);
      refresh();
    },
  });

  if (status.isPending) return <Spinner label="Henter Canvas-status …" />;
  if (status.error) return <Alert tone="danger" role="alert">{(status.error as Error).message}</Alert>;
  const s = status.data;
  const url = baseUrl ?? s.base_url ?? "";

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Canvas-tilkobling" headingLevel={2}>
        <div className="ek-stack">
          <KeyValue items={[
            ["Canvas-adresse", s.base_url ?? "Ikke satt"],
            ["API-token", s.token_configured ? <Badge key="t" tone="success" icon={<CircleCheck aria-hidden="true" size={14} />}>Lagret sikkert</Badge> : <Badge key="t" tone="warning">Mangler</Badge>],
            ["Innlogget som", s.identity?.name ?? "–"],
            ["Sist kontrollert", s.last_verified_at ? formatDateTime(s.last_verified_at) : "–"],
            ["Lagring av token", s.secret_backend],
          ]} />
          <p className="ek-xs ek-muted">
            Tokenet lagres bare i Windows Legitimasjonsbehandling og vises aldri i EmneKlar, i nettleseren eller i logger.
          </p>
          <div className="ek-cluster">
            <Button icon={<PlugZap aria-hidden="true" />} onClick={() => verify.mutate()} loading={verify.isPending}
              disabled={!s.token_configured}>
              Test tilkoblingen
            </Button>
          </div>
          {verify.error ? <Alert tone="danger" role="alert" title="Tilkoblingen feilet">{(verify.error as Error).message}</Alert> : null}
        </div>
      </Card>

      <Card title="Endre adresse eller bytt token" headingLevel={2}>
        <form className="ek-stack" onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}>
          <TextField label="Canvas-adresse" type="url" value={url} onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://institusjon.instructure.com" autoComplete="url" />
          <TextField label="Nytt API-token" type="password" value={token} onChange={(e) => setToken(e.target.value)}
            autoComplete="off" spellCheck={false} optional
            hint="La feltet stå tomt for å beholde tokenet som er lagret. Lag et nytt token i Canvas under Konto → Innstillinger → Godkjente integrasjoner." />
          {save.error ? <Alert tone="danger" role="alert" title="Kunne ikke lagre">{(save.error as Error).message}</Alert> : null}
          <div className="ek-cluster">
            <Button type="submit" variant="primary" icon={<KeyRound aria-hidden="true" />} loading={save.isPending}
              disabled={!url || (!token && url === s.base_url)}>
              Test og lagre
            </Button>
            {s.token_configured ? (
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>Fjern token</Button>
            ) : null}
          </div>
        </form>
      </Card>

      <Card title={`Tilganger${course ? ` i ${course.course_code ?? course.name}` : ""}`} headingLevel={2}>
        {!courseId ? <p className="ek-small">Velg et emne for å se tilgangene dine i det.</p> : null}
        {caps.isPending && courseId ? <Spinner label="Sjekker tilganger …" /> : null}
        {caps.data ? (
          <div className="ek-stack">
            <ul className="ek-list-reset ek-stack" data-gap="1">
              {caps.data.capabilities.map((c) => (
                <li key={c.key} className="ek-cluster" data-gap="2">
                  {c.granted ? <Badge tone="success">Ja</Badge> : <Badge tone="warning">Nei</Badge>}
                  <span className="ek-small">{c.label}</span>
                </li>
              ))}
            </ul>
            <p className="ek-small">
              Blueprint: {caps.data.blueprint.is_blueprint
                ? `emnet er et Blueprint-emne (${caps.data.blueprint.associated_course_count ?? 0} tilknyttede emner)`
                : caps.data.blueprint.is_child ? "emnet får innhold fra et Blueprint-emne" : "ikke Blueprint-emne"}.
            </p>
            <p className="ek-xs ek-muted">Tilgangene styres i Canvas. EmneKlar kan bare gjøre det du selv har lov til.</p>
          </div>
        ) : null}
        {caps.error ? <Alert tone="danger" role="alert">{(caps.error as Error).message}</Alert> : null}
      </Card>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
        title="Fjerne Canvas-tokenet?"
        confirmLabel="Fjern token"
        danger
        loading={remove.isPending}
      >
        <p>Tokenet slettes fra Windows Legitimasjonsbehandling. EmneKlar kan ikke hente data fra Canvas før du legger inn et nytt.</p>
        <p>Husk å slette tokenet i Canvas også hvis du ikke skal bruke det mer.</p>
      </ConfirmDialog>
    </div>
  );
}
