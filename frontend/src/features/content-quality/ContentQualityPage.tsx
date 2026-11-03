import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleHelp, Clock, FileCheck, Film, Link2, Lock, Play, RefreshCw, Unlink, CornerDownRight } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ExternalLink,
  FilterChips,
  KeyFigure,
  KeyFigureList,
  PageHeader,
  Spinner,
  Tabs,
  TextField,
  type Column,
  type Tone,
} from "../../design-system";
import { FindingsView } from "../findings/FindingsView";
import { VideoStandardiser } from "./VideoStandardiser";

type LinkState = "WORKING" | "REDIRECT" | "DEAD" | "TIMEOUT" | "AUTH_REQUIRED" | "UNKNOWN";

export const LINK_STATE: Record<LinkState, { label: string; tone: Tone; description: string }> = {
  DEAD: { label: "Død", tone: "danger", description: "Siden finnes ikke (for eksempel 404 eller 410)." },
  TIMEOUT: { label: "Tidsavbrudd", tone: "warning", description: "Svarte ikke i tide. Det betyr ikke at lenken er død." },
  AUTH_REQUIRED: { label: "Krever innlogging", tone: "violet", description: "Siden krever innlogging eller avviser automatiske besøk (for eksempel 401/403)." },
  UNKNOWN: { label: "Ukjent", tone: "neutral", description: "Kunne ikke avgjøres sikkert." },
  REDIRECT: { label: "Omdirigeres", tone: "info", description: "Lenken sender videre til en annen adresse." },
  WORKING: { label: "Virker", tone: "success", description: "Lenken svarte som forventet." },
};
const STATE_ICON: Record<LinkState, ReactNode> = {
  DEAD: <Unlink />,
  TIMEOUT: <Clock />,
  AUTH_REQUIRED: <Lock />,
  UNKNOWN: <CircleHelp />,
  REDIRECT: <CornerDownRight />,
  WORKING: <CircleCheck />,
};
const STATE_ORDER: LinkState[] = ["DEAD", "TIMEOUT", "AUTH_REQUIRED", "UNKNOWN", "REDIRECT", "WORKING"];

interface LinkRow {
  url: string;
  state: LinkState;
  detail: string;
  http_status: number | null;
  final_url: string | null;
  checked_at: string;
  from_cache?: boolean;
  used_in?: string[];
}

interface LinksResponse {
  links: LinkRow[];
  summary: Partial<Record<LinkState, number>>;
  checked_at: string | null;
}

function usedIn(row: LinkRow): string[] {
  return (row.used_in ?? []).map((ref) => ref.split("|").slice(1).join("|") || ref);
}

function LinksPanel() {
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const [state, setState] = useState<string>("problems");
  const [query, setQuery] = useState("");
  const [rechecked, setRechecked] = useState<Record<string, Partial<LinkRow>>>({});
  const links = useQuery({
    queryKey: ["links", courseId],
    queryFn: () => api.get<LinksResponse>(`/api/courses/${courseId}/links`),
    enabled: Boolean(courseId),
  });
  const recheck = useMutation({
    mutationFn: (url: string) => api.post<Partial<LinkRow> & { url: string }>("/api/content-quality/recheck", { url }),
    onSuccess: (result) => setRechecked((current) => ({ ...current, [result.url]: { ...result, checked_at: new Date().toISOString() } })),
  });

  const rows = useMemo(() => {
    const merged = (links.data?.links ?? []).map((row) => ({ ...row, ...(rechecked[row.url] ?? {}) }) as LinkRow);
    const q = query.trim().toLowerCase();
    return merged.filter((row) => {
      if (state === "problems" && (row.state === "WORKING" || row.state === "REDIRECT")) return false;
      if (state !== "problems" && state !== "all" && row.state !== state) return false;
      return !q || `${row.url} ${usedIn(row).join(" ")}`.toLowerCase().includes(q);
    });
  }, [links.data, rechecked, state, query]);

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (links.isPending) return <Spinner label="Henter lenker …" />;
  if (links.error) {
    return (
      <Alert tone="danger" role="alert" title="Kunne ikke hente lenkene">
        {(links.error as Error).message}
      </Alert>
    );
  }
  if (!links.data.checked_at) {
    return (
      <EmptyState
        title="Lenkene er ikke kontrollert ennå"
        headingLevel={3}
        actions={<Button variant="primary" onClick={() => ui.openAnalysis({ domains: ["content_quality"] })}>Kjør analyse</Button>}
      >
        Analysen av innholdskvalitet sjekker alle eksterne lenker i emnet. Ingen lenker endres eller slettes.
      </EmptyState>
    );
  }

  const columns: Column<LinkRow>[] = [
    {
      key: "url",
      header: "Lenke",
      rowHeader: true,
      cell: (row) => (
        <span className="ek-stack ek-url-cell" data-gap="1">
          <ExternalLink href={row.url}>{row.url}</ExternalLink>
          {row.final_url && row.final_url !== row.url ? <span className="ek-xs ek-muted">→ {row.final_url}</span> : null}
        </span>
      ),
    },
    {
      key: "state",
      header: "Status",
      cell: (row) => (
        <span className="ek-stack" data-gap="1">
          <Badge tone={LINK_STATE[row.state]?.tone ?? "neutral"}>{LINK_STATE[row.state]?.label ?? row.state}</Badge>
          <span className="ek-xs ek-muted">
            {row.detail}
            {row.http_status && !row.detail.includes(String(row.http_status)) ? ` (HTTP ${row.http_status})` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "used",
      header: "Brukt i",
      cell: (row) => <span className="ek-small">{usedIn(row).join(", ") || "–"}</span>,
    },
    { key: "checked", header: "Sjekket", cell: (row) => <span className="ek-xs">{formatDateTime(row.checked_at)}</span> },
    {
      key: "actions",
      header: <span className="ek-visually-hidden">Handlinger</span>,
      cell: (row) => (
        <Button size="sm" icon={<RefreshCw aria-hidden="true" size={14} />} onClick={() => recheck.mutate(row.url)}
          loading={recheck.isPending && recheck.variables === row.url}>
          Sjekk på nytt<span className="ek-visually-hidden">: {row.url}</span>
        </Button>
      ),
    },
  ];

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Lenkestatus" description={`Alle eksterne lenker i emnet, kontrollert ${formatDateTime(links.data.checked_at)}.`}>
        <KeyFigureList label="Lenkestatus">
          {STATE_ORDER.map((s) => (
            <KeyFigure key={s} icon={STATE_ICON[s]} tone={LINK_STATE[s].tone} value={links.data.summary[s] ?? 0}
              label={LINK_STATE[s].label} description={LINK_STATE[s].description} />
          ))}
        </KeyFigureList>
      </Card>
      <Alert tone="info" title="Ikke alle feil betyr at lenken er død">
        Noen nettsteder avviser automatiske kontroller (for eksempel med 403) eller svarer tregt. Slike lenker vises som
        «Krever innlogging», «Tidsavbrudd» eller «Ukjent» – kontroller dem manuelt. EmneKlar sletter aldri lenker
        automatisk; rettinger legges i endringskøen fra fanen «Funn».
      </Alert>
      <div className="ek-stack" data-gap="4">
        <FilterChips
          label="Vis"
          showLabel
          value={state}
          onChange={setState}
          options={[
            { value: "problems", label: "Bør kontrolleres" },
            { value: "all", label: "Alle lenker" },
            ...STATE_ORDER.map((s) => ({ value: s, label: LINK_STATE[s].label, count: links.data.summary[s] ?? 0 })),
          ]}
        />
        <div className="ek-toolbar">
          <div className="ek-toolbar__grow">
            <TextField label="Søk i lenker" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
      </div>
      {recheck.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke sjekke lenken">
          {(recheck.error as Error).message}
        </Alert>
      ) : null}
      <DataTable
        caption={`Lenker (${rows.length}) – kontrollert ${formatDateTime(links.data.checked_at)}`}
        columns={columns}
        rows={rows}
        rowKey={(row) => row.url}
        empty="Ingen lenker med dette valget."
      />
    </div>
  );
}

export function ContentQualityPage() {
  usePageTitle("Innholdskvalitet");
  const ui = useUi();
  const [tab, setTab] = useState<"findings" | "links" | "media">("findings");
  return (
    <>
      <PageHeader
        title="Innholdskvalitet"
        description="Tekniske kvalitetsproblemer: lenker som ikke virker, medier som er borte og unødvendig kode. Dette er ikke en vurdering av faglig kvalitet."
        actions={
          <>
            <HelpLink topic="innholdskvalitet" />
            <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => ui.openAnalysis({ domains: ["content_quality"] })}>
              Analyser innholdskvalitet
            </Button>
          </>
        }
      />
      <Tabs
        label="Innholdskvalitet"
        selected={tab}
        onSelect={setTab}
        tabs={[
          { id: "findings", label: "Funn", icon: <FileCheck aria-hidden="true" /> },
          { id: "links", label: "Lenker", icon: <Link2 aria-hidden="true" /> },
          { id: "media", label: "Media", icon: <Film aria-hidden="true" /> },
        ]}
      >
        <div className="ek-mt-6">
          {tab === "findings" ? (
            <FindingsView
              domain="content_quality"
              emptyText="Kjør en analyse for å kontrollere lenker, medier og HTML-kode i emnet. Analysen leser bare fra Canvas."
            />
          ) : tab === "links" ? (
            <LinksPanel />
          ) : (
            <VideoStandardiser />
          )}
        </div>
      </Tabs>
    </>
  );
}
