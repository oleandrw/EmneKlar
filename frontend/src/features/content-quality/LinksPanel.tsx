// Innholdskvalitet → Lenker: one row per checked link – Lenke · Kontrollresultat · Brukt i · Handlinger.
// Categories say what the check proves: «Fungerer», «Fungerer ikke» (a concrete error – also an internal link to
// content that does not exist), «Krever innlogging» (proven), «Kunne ikke kontrolleres» (timeouts, 403, blocked
// checks – not proof of anything). Oversikt's «døde lenker» is the «Fungerer ikke» total here. «Endre lenke» changes only the
// places the teacher picks, after a preview, through the change queue; «Finn alternativ lenke med KI» suggests up to
// three replacements found by real lookups – the teacher decides.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleHelp, Copy, ExternalLink as ExternalIcon, Lock, RefreshCw, Search, Unlink } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { AiConsent, AI_LABEL, type AiPlan } from "../../core/ai";
import { api } from "../../core/api/client";
import type { CanvasLinks } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime, formatWhen } from "../../core/format";
import { useCourseAnalysis } from "../../core/jobs";
import { useSession } from "../../core/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  DiffView,
  Disclosure,
  EmptyState,
  ExternalLink,
  Fieldset,
  FilterChips,
  KeyFigure,
  KeyFigureList,
  Spinner,
  TextField,
  useToast,
  type Column,
  type Tone,
} from "../../design-system";
import { AiSuggestion, consentGiven, rememberConsent } from "../findings/AiSuggestion";
import { useFinding } from "../findings/api";
import { FindingDetail } from "../findings/FindingDetail";
import { useResultsFreshness } from "../analysis/AnalysisStatus";

export type LinkCategory = "broken" | "login" | "unchecked" | "working";

export const CATEGORY: Record<LinkCategory, { label: string; tone: Tone; icon: ReactNode; description: string }> = {
  broken: { label: "Fungerer ikke", tone: "danger", icon: <Unlink />, description: "En konkret feil er påvist, for eksempel at siden ikke finnes (404/410)." },
  login: { label: "Krever innlogging", tone: "violet", icon: <Lock />, description: "Nettstedet ba om innlogging (401) eller sendte videre til en innloggingsside." },
  unchecked: { label: "Kunne ikke kontrolleres", tone: "warning", icon: <CircleHelp />, description: "Ingen svar i tide, avvist automatisk kontroll (for eksempel 403) eller serverfeil – ikke bevis for at lenken er død." },
  working: { label: "Fungerer", tone: "success", icon: <CircleCheck />, description: "Lenken svarte som forventet (også når den sender videre)." },
};
const ORDER: LinkCategory[] = ["broken", "login", "unchecked", "working"];

export interface LinkPlace {
  object_type: string;
  object_id: string;
  title: string;
  module?: string | null;
  count?: number | null;
  text?: string | null;
  canvas?: CanvasLinks;
  finding_id?: number | null;
}

export interface LinkRow {
  /** The address as written in the content (an internal link is relative: /courses/…). */
  url: string;
  /** «internal»: a link to course content that does not exist – compared with the course, no web check. */
  kind?: "internal";
  /** The full address to open (internal links). */
  open_url?: string | null;
  state: string;
  category: LinkCategory;
  category_label: string;
  detail: string;
  method?: string;
  http_status: number | null;
  final_url: string | null;
  checked_at: string;
  title: string | null;
  places: number;
  occurrences: number;
  uses?: LinkPlace[];
}

interface LinksResponse {
  links: LinkRow[];
  summary: Partial<Record<LinkCategory, number>>;
  checked_at: string | null;
  /** «cancelled» when only a cancelled check has links (the list is then incomplete). */
  run_status?: string | null;
}

function shortAddress(url: string): { host: string; rest: string } {
  try {
    const u = new URL(url);
    const rest = `${u.pathname}${u.search}`.replace(/^\/$/, "");
    return { host: u.hostname.replace(/^www\./, ""), rest: rest.length > 60 ? `${rest.slice(0, 57)}…` : rest };
  } catch {
    return { host: url.slice(0, 40), rest: "" };
  }
}

const EDITABLE = new Set(["page", "assignment", "discussion", "quiz", "syllabus"]);

function LinkCell({ row }: { row: LinkRow }) {
  const toast = useToast();
  const address = row.open_url ?? row.url;
  const { host, rest } = shortAddress(address);
  return (
    <span className="ek-link-cell">
      <span className="ek-strong">{row.title ?? host}</span>
      <span className="ek-link-cell__address">
        {row.title ? host : null}{row.title && rest ? " · " : null}{rest || (row.title ? "" : row.url)}
      </span>
      <span className="ek-cluster" data-gap="1">
        <Button size="sm" variant="ghost" icon={<Copy aria-hidden="true" size={14} />}
          onClick={() => navigator.clipboard?.writeText(address).then(() => toast.show({ tone: "success", title: "Adressen er kopiert" }))}>
          Kopier adressen<span className="ek-visually-hidden">: {row.url}</span>
        </Button>
        {row.kind === "internal" ? <Badge tone="neutral">Intern lenke</Badge> : null}
      </span>
      {row.final_url && row.final_url !== row.url ? <span className="ek-link-cell__address">→ sender videre til {row.final_url}</span> : null}
    </span>
  );
}

function Places({ row, onChange, onFix }: { row: LinkRow; onChange: (place: LinkPlace) => void; onFix: (findingId: number) => void }) {
  const [open, setOpen] = useState(false);
  const places = row.uses ?? [];
  if (!places.length) return <span className="ek-small ek-muted">–</span>;
  const first = places[0];
  const label = `Brukt på ${places.length === 1 ? "1 sted" : `${places.length} steder`}` +
    (row.occurrences > places.length ? ` (${row.occurrences} lenker)` : "");
  return (
    <div>
      <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}<span className="ek-visually-hidden">: {row.title ?? row.url}</span>
      </Button>
      {!open ? (
        <p className="ek-xs ek-muted">For eksempel «{first.title}»{first.module ? ` (${first.module})` : ""}</p>
      ) : (
        <ul className="ek-link-places">
          {places.map((place) => {
            const href = place.canvas?.highlight ?? place.canvas?.view;
            return (
              <li key={`${place.object_type}:${place.object_id}`}>
                <span className="ek-small">{href ? <ExternalLink href={href}>{place.title}</ExternalLink> : place.title}</span>
                <span className="ek-xs ek-muted">
                  {place.module ? `Modul: ${place.module}` : "Ikke i en modul"}
                  {place.count && place.count > 1 ? ` · ${place.count} lenker her` : ""}
                </span>
                {EDITABLE.has(place.object_type) ? (
                  <div className="ek-cluster" data-gap="2">
                    <Button size="sm" onClick={() => onChange(place)}>
                      Endre lenke{" "}<span className="ek-visually-hidden">i {place.title}</span>
                    </Button>
                    {/* The finding's own fix: also offers «Fjern lenken, behold teksten» for this one place. */}
                    {place.finding_id && row.category !== "working" ? (
                      <Button size="sm" variant="ghost" onClick={() => onFix(place.finding_id!)}>
                        Rett funnet<span className="ek-visually-hidden">: {row.url} i {place.title}</span>
                      </Button>
                    ) : null}
                  </div>
                ) : <span className="ek-xs ek-muted">Endres i Canvas (lenke i modulen).</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- «Finn alternativ lenke med KI» */

interface Suggestion {
  url: string;
  title: string;
  publisher: string;
  relation: "same" | "alternative" | "archive";
  relation_label: string;
  reason: string;
  limitations: string[];
  origin: string;
  archived_at?: string | null;
  check: { state: string; label: string; detail?: string; checked_at?: string };
}

interface AltAnswer {
  url: string;
  suggestions: Suggestion[];
  none_found: boolean;
  note?: string | null;
  searched: boolean;
  search_note?: string | null;
  considered: number;
  model?: string;
  provider_name?: string;
}

interface AltPlan extends AiPlan {
  task?: string;
  search?: { available: boolean; service: string | null; note: string | null };
}

function manualSearch(row: LinkRow): string {
  const { host } = shortAddress(row.url);
  return `https://duckduckgo.com/?q=${encodeURIComponent(`${row.title ?? ""} ${host}`.trim())}`;
}

function Alternatives({ courseId, row, place, onUse }: {
  courseId: string;
  row: LinkRow;
  place: LinkPlace | undefined;
  onUse: (s: Suggestion) => void;
}) {
  const session = useSession();
  const [plan, setPlan] = useState<AltPlan | null>(null);
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AltAnswer | null>(null);
  const [seen, setSeen] = useState<string[]>([]);
  const body = { url: row.url, link_text: place?.text ?? row.title ?? undefined, page_title: place?.title, module: place?.module ?? undefined };
  const find = useMutation({
    mutationFn: (confirmed: boolean) => api.post<AltAnswer>(`/api/courses/${courseId}/links/alternatives`, { ...body, confirmed, avoid: seen }),
    onError: () => setAsking(false),
    onSuccess: (a, confirmed) => {
      if (a.url !== row.url) return; // a late answer for another link
      if (confirmed && plan) rememberConsent(plan.task ?? "link_alternatives", plan.route?.provider);
      setAsking(false);
      setAnswer(a);
      setSeen((cur) => [...cur, ...a.suggestions.map((s) => s.url)]);
    },
  });
  const prepare = useMutation({
    mutationFn: () => api.post<AltPlan>(`/api/courses/${courseId}/links/alternatives/prepare`, body),
    onSuccess: (p) => {
      setPlan(p);
      if (!p.available) return;
      if (p.needs_confirmation && !consentGiven(p.task ?? "link_alternatives", p.route?.provider)) setAsking(true);
      else find.mutate(p.needs_confirmation);
    },
  });
  const manual = (
    <p className="ek-small">
      Søk selv: <ExternalLink href={manualSearch(row)}>Søk etter ressursen på nettet</ExternalLink> ·{" "}
      <ExternalLink href={`https://web.archive.org/web/*/${row.url}`}>Se arkiverte versjoner</ExternalLink>
    </p>
  );
  if (session.ai.providers_enabled.length === 0) {
    return (
      <div className="ek-stack" data-gap="1">
        <p className="ek-small ek-muted">
          Forslag til alternativ lenke krever en KI-tjeneste med nettsøk. <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>.
        </p>
        {manual}
      </div>
    );
  }
  const busy = prepare.isPending || find.isPending;
  const error = (find.error ?? prepare.error) as Error | null;
  return (
    <div className="ek-stack" data-gap="2">
      <div className="ek-cluster" data-gap="2">
        <Button size="sm" icon={<Search aria-hidden="true" />} loading={busy} disabled={busy || asking} onClick={() => prepare.mutate()}>
          {answer ? "Nye forslag" : "Finn alternativ lenke med KI"}
        </Button>
        {find.isPending ? <span className="ek-small ek-muted" role="status">Søker og kontrollerer kandidater …</span> : null}
      </div>
      {plan && !plan.available ? <p className="ek-small">{plan.reason} <Link to="/innstillinger/ki-assistenter">Innstillinger → KI-assistenter</Link></p> : null}
      {plan?.search && !plan.search.available ? <p className="ek-xs ek-muted">{plan.search.note}</p> : null}
      {asking && plan ? (
        <AiConsent plan={plan} onCancel={() => setAsking(false)} onConfirm={() => find.mutate(true)} loading={find.isPending}
          confirmLabel="Send og søk" />
      ) : null}
      {error ? <Alert tone="warning" role="alert" title="Fikk ikke noe forslag">{error.message} Du kan skrive adressen selv.</Alert> : null}
      {answer ? (
        <div className="ek-stack" data-gap="2" aria-live="polite">
          <p className="ek-small">
            <span className="ek-strong">{AI_LABEL}</span>. {answer.model ? `Vurdert av ${answer.model}${answer.provider_name ? ` (${answer.provider_name})` : ""} ` : ""}
            blant {answer.considered} {answer.considered === 1 ? "kandidat" : "kandidater"} fra {answer.searched ? "nettsøk, " : ""}videresending og Internet Archive.
          </p>
          {answer.search_note ? <p className="ek-xs ek-muted">{answer.search_note}</p> : null}
          {answer.none_found ? (
            <Alert tone="info" title="Fant ingen gode erstatninger">
              {answer.note ?? "Ingen av kandidatene passet."} {manual}
            </Alert>
          ) : (
            <ul className="ek-link-candidates">
              {answer.suggestions.map((s) => (
                <li key={s.url} className="ek-card ek-card--compact">
                  <div className="ek-stack" data-gap="1">
                    <span className="ek-strong">{s.title}</span>
                    <span className="ek-link-cell__address">{s.url}</span>
                    <span className="ek-small">{s.relation_label}{s.archived_at ? ` (${s.archived_at})` : ""} · {s.publisher}</span>
                    <span className="ek-small">{s.reason}</span>
                    <span className="ek-xs">
                      Teknisk kontroll: <Badge tone={CATEGORY_TONE[s.check.state] ?? "neutral"}>{s.check.label}</Badge>
                      {s.check.checked_at ? ` ${formatDateTime(s.check.checked_at)}` : ""} – sier ikke om den passer faglig.
                    </span>
                    {s.limitations.length ? <span className="ek-xs ek-muted">Begrensninger: {s.limitations.join(" ")}</span> : null}
                    <div className="ek-cluster" data-gap="2">
                      <ExternalLink href={s.url} className="ek-btn ek-btn--sm">Åpne og undersøk</ExternalLink>
                      <Button size="sm" variant="primary" onClick={() => onUse(s)}>Bruk denne adressen</Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

const CATEGORY_TONE: Record<string, Tone> = { WORKING: "success", REDIRECT: "success", DEAD: "danger", AUTH_REQUIRED: "violet", TIMEOUT: "warning", UNKNOWN: "warning" };

/* ------------------------------------------------------------------------------- «Endre lenke» */

interface ReplacePreview {
  places: { object_type: string; object_id: string; title: string; count: number; changes: { before: string; after: string }[]; message: string | null }[];
  where: { message: string; role: string };
}

function ChangeLinkDialog({ courseId, row, start, onClose }: { courseId: string; row: LinkRow; start: LinkPlace | null; onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const editable = (row.uses ?? []).filter((p) => EDITABLE.has(p.object_type));
  const key = (p: LinkPlace) => `${p.object_type}:${p.object_id}`;
  const [chosen, setChosen] = useState<string[]>(start ? [key(start)] : editable.length === 1 ? [key(editable[0])] : []);
  const [url, setUrl] = useState("");
  const [fromAi, setFromAi] = useState<{ url: string; relation: string } | null>(null);
  const [changeText, setChangeText] = useState(false);
  const [text, setText] = useState("");
  const [aiText, setAiText] = useState<string | null>(null);
  const places = editable.filter((p) => chosen.includes(key(p)));
  const body = {
    old_url: row.url, new_url: url.trim(), link_text: changeText && text.trim() ? text.trim() : null,
    places: places.map((p) => ({ object_type: p.object_type, object_id: p.object_id, title: p.title })),
    ai_suggestion: (fromAi !== null && fromAi.url === url.trim()) || (changeText && aiText !== null && text.trim() !== ""),
  };
  const stamp = JSON.stringify(body);
  const [previewed, setPreviewed] = useState<{ stamp: string; data: ReplacePreview } | null>(null);
  const preview = useMutation({
    mutationFn: () => api.post<ReplacePreview>(`/api/courses/${courseId}/links/replace/preview`, body),
    onSuccess: (data) => setPreviewed({ stamp, data }),
  });
  const approve = useMutation({
    mutationFn: () => api.post<{ approved: number[]; skipped: unknown[] }>(`/api/courses/${courseId}/links/replace/approve`, body),
    onSuccess: (r) => {
      toast.show({ tone: "success", title: `${r.approved.length} ${r.approved.length === 1 ? "endring" : "endringer"} godkjent i endringskøen`,
        body: "Ingenting endres i Canvas før du velger «Publiser til Canvas» i endringskøen." });
      void client.invalidateQueries({ queryKey: ["changes"] });
      onClose();
    },
  });
  const current = previewed?.stamp === stamp ? previewed.data : null;
  const changes = current?.places.reduce((n, p) => n + p.count, 0) ?? 0;
  const misleading = fromAi && fromAi.url === url.trim() && fromAi.relation !== "same";
  const needsId = useId();
  // With several places nothing is chosen in advance, so say why «Forhåndsvis endringen» cannot be used yet.
  const needs = [!url.trim() && "en ny adresse", !places.length && "minst ett valgt sted"].filter(Boolean).join(" og ");
  return (
    <Dialog open onClose={onClose} size="xl" title={editable.length > 1 ? "Endre lenken på flere steder" : "Endre lenke"}
      description="Bare stedene du velger, endres – etter forhåndsvisning og godkjenning i endringskøen.">
      <div className="ek-stack" data-gap="5">
        <div className="ek-stack" data-gap="1">
          <span className="ek-small ek-strong">Lenken nå</span>
          <span className="ek-link-cell__address">{row.url}</span>
          <span className="ek-xs">{row.category_label}: {row.detail}</span>
        </div>
        <TextField label="Ny adresse" type="url" value={url} placeholder="https://" onChange={(e) => setUrl(e.target.value)}
          hint={fromAi && fromAi.url === url.trim() ? "Adressen kommer fra et KI-forslag. Åpne den og kontroller at den passer." : "Lim inn adressen lenken skal gå til, eller finn et forslag under."} />
        {/* An internal link points into the course itself: a web search for a replacement does not apply. */}
        {row.kind !== "internal" ? (
          <Alternatives courseId={courseId} row={row} place={start ?? editable[0]} onUse={(s) => {
            setUrl(s.url);
            setFromAi({ url: s.url, relation: s.relation });
          }} />
        ) : null}
        <div className="ek-stack" data-gap="2">
          <Checkbox label="Endre også lenketeksten" checked={changeText} onChange={(e) => setChangeText(e.target.checked)}
            hint={misleading ? "Den nye adressen er ikke samme ressurs – vurder om lenketeksten fortsatt stemmer." : "Ellers beholdes lenketeksten, bilder i lenken og andre egenskaper."} />
          {changeText ? (
            <>
              <TextField label="Ny lenketekst" value={text} maxLength={200} onChange={(e) => {
                setText(e.target.value);
                if (!e.target.value.trim()) setAiText(null);
              }} />
              <AiSuggestion label="Foreslå lenketekst med KI" text={text} setText={setText} initial="" onSuggested={setAiText}
                prepare={() => api.post(`/api/courses/${courseId}/links/link-text-suggestion/prepare`, { url: url.trim() || row.url, current_text: row.title ?? "", page_title: (start ?? editable[0])?.title ?? "" })}
                run={(confirmed, avoid) => api.post(`/api/courses/${courseId}/links/link-text-suggestion`, { url: url.trim() || row.url, current_text: row.title ?? "", page_title: (start ?? editable[0])?.title ?? "", confirmed, avoid })} />
            </>
          ) : null}
        </div>
        <Fieldset legend="Hvor skal lenken endres?">
          {editable.length > 1 ? (
            <div className="ek-cluster" data-gap="2">
              <Button size="sm" variant="ghost" onClick={() => setChosen(editable.map(key))}>Velg alle</Button>
              <Button size="sm" variant="ghost" onClick={() => setChosen([])}>Fjern alle</Button>
            </div>
          ) : null}
          {editable.map((p) => (
            <Checkbox key={key(p)} checked={chosen.includes(key(p))}
              onChange={(e) => setChosen(e.target.checked ? [...chosen, key(p)] : chosen.filter((k) => k !== key(p)))}
              label={<>{p.title}{p.module ? <span className="ek-muted"> · {p.module}</span> : null}{p.count && p.count > 1 ? <span className="ek-muted"> · {p.count} lenker</span> : null}</>} />
          ))}
          {editable.length < (row.uses ?? []).length ? <p className="ek-xs ek-muted">Lenker direkte i moduler endres i Canvas.</p> : null}
        </Fieldset>
        <div className="ek-cluster" data-gap="2">
          <Button onClick={() => preview.mutate()} loading={preview.isPending} disabled={!places.length || !url.trim()}
            aria-describedby={needs ? needsId : undefined}>Forhåndsvis endringen</Button>
          <Button variant="ghost" onClick={onClose}>Behold lenken</Button>
        </div>
        {needs ? <p id={needsId} className="ek-xs ek-muted">Forhåndsvisning krever {needs}.</p> : null}
        {preview.error ? <Alert tone="danger" role="alert">{(preview.error as Error).message}</Alert> : null}
        {current ? (
          <section className="ek-stack" data-gap="3" aria-labelledby="lenke-forhandsvisning">
            <h3 id="lenke-forhandsvisning">Slik blir det</h3>
            {current.where.role !== "course" ? <p className="ek-small">{current.where.message}</p> : null}
            {current.places.map((p) => (
              <div key={`${p.object_type}:${p.object_id}`} className="ek-stack" data-gap="1">
                <span className="ek-strong ek-small">{p.title} – {p.count ? `${p.count} ${p.count === 1 ? "lenke" : "lenker"} endres` : p.message}</span>
                {p.changes.slice(0, 3).map((ch, i) => <DiffView key={i} before={ch.before} after={ch.after} />)}
              </div>
            ))}
            {approve.error ? <Alert tone="danger" role="alert">{(approve.error as Error).message}</Alert> : null}
            <div>
              <Button variant="primary" disabled={!changes} loading={approve.isPending} onClick={() => approve.mutate()}>
                Godkjenn til endringskøen
              </Button>
            </div>
          </section>
        ) : null}
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------------------------- the panel */

export function LinksPanel() {
  const { courseId } = useCurrentCourse();
  const toast = useToast();
  // ``?lenker=broken`` (Oversikt → «Se døde lenker») opens the rows that figure counts.
  const [search] = useSearchParams();
  const [filter, setFilter] = useState<string>(() => {
    const wanted = search.get("lenker");
    return wanted && (ORDER as string[]).includes(wanted) ? wanted : "problems";
  });
  const [query, setQuery] = useState("");
  const [changing, setChanging] = useState<{ row: LinkRow; place: LinkPlace | null } | null>(null);
  const [fixing, setFixing] = useState<number | null>(null);
  const [updates, setUpdates] = useState<Record<string, Partial<LinkRow>>>({});
  const [summary, setSummary] = useState<LinksResponse["summary"] | null>(null);
  const links = useQuery({
    queryKey: ["links", courseId],
    queryFn: () => api.get<LinksResponse>(`/api/courses/${courseId}/links`),
    enabled: Boolean(courseId),
  });
  const checkedAt = links.data?.checked_at ?? null;
  const freshness = useResultsFreshness("content_quality", checkedAt);
  const { runningHere } = useCourseAnalysis("content_quality");
  // A new check replaces the results: links re-checked one by one belong to the old list.
  useEffect(() => {
    setUpdates({});
    setSummary(null);
  }, [checkedAt]);
  const recheck = useMutation({
    mutationFn: (url: string) => api.post<Partial<LinkRow> & { url: string; summary?: LinksResponse["summary"] | null }>(
      "/api/content-quality/recheck", { url, course_id: courseId }),
    onSuccess: (result) => {
      const { summary: totals, ...rest } = result;
      setUpdates((cur) => ({ ...cur, [result.url]: rest }));
      if (totals) setSummary(totals);
      // The row updates in place; the toast region (role=status) also tells screen reader users the result.
      toast.show({ tone: result.category === "working" ? "success" : "info", title: `Sjekket på nytt: ${result.category_label ?? ""}`,
        body: result.detail ? `${result.url} – ${result.detail}` : result.url });
    },
  });
  const rows = useMemo(() => {
    const merged = (links.data?.links ?? []).map((row) => ({ ...row, ...(updates[row.url] ?? {}) }) as LinkRow);
    const q = query.trim().toLowerCase();
    return merged.filter((row) => {
      if (filter === "problems" && row.category === "working") return false;
      if (filter !== "problems" && filter !== "all" && row.category !== filter) return false;
      return !q || `${row.url} ${row.title ?? ""} ${(row.uses ?? []).map((u) => `${u.title} ${u.module ?? ""}`).join(" ")}`.toLowerCase().includes(q);
    });
  }, [links.data, updates, filter, query]);

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (links.isPending) return <Spinner label="Henter lenker …" />;
  if (links.error) return <Alert tone="danger" role="alert" title="Kunne ikke hente lenkene">{(links.error as Error).message}</Alert>;
  if (!links.data.checked_at) {
    return (
      <EmptyState title={runningHere ? "Første lenkekontroll pågår" : "Lenkene er ikke kontrollert ennå"} headingLevel={3}>
        {runningHere ? "Lenkene vises her når kontrollen er ferdig. " : "Start med «Analyser innholdskvalitet» øverst til høyre. "}
        Analysen av innholdskvalitet sjekker alle eksterne lenker i emnet. Ingen lenker endres eller slettes.
      </EmptyState>
    );
  }
  const totals = summary ?? links.data.summary;

  const columns: Column<LinkRow>[] = [
    { key: "link", header: "Lenke", rowHeader: true, width: "32%", cell: (row) => <LinkCell row={row} /> },
    {
      key: "result", header: "Kontrollresultat", cell: (row) => (
        <span className="ek-stack" data-gap="1">
          <Badge tone={CATEGORY[row.category]?.tone ?? "neutral"}>{row.category_label}</Badge>
          <span className="ek-xs">{row.detail}</span>
          <span className="ek-xs ek-muted">Sjekket {formatDateTime(row.checked_at)}</span>
          <Disclosure summary="Tekniske detaljer">
            <span className="ek-xs ek-stack" data-gap="1">
              <span>Tilstand: {row.state}{row.http_status ? ` · HTTP ${row.http_status}` : ""}</span>
              {row.method ? <span>{row.method}</span> : null}
              {row.final_url && row.final_url !== row.url ? <span>Endelig adresse: {row.final_url}</span> : null}
            </span>
          </Disclosure>
        </span>
      ),
    },
    { key: "places", header: "Brukt i", cell: (row) => <Places row={row} onChange={(place) => setChanging({ row, place })} onFix={setFixing} /> },
    {
      key: "actions", header: "Handlinger", cell: (row) => {
        const uncertain = row.category === "unchecked" || row.category === "login";
        const editable = (row.uses ?? []).filter((p) => EDITABLE.has(p.object_type)).length;
        return (
          <span className="ek-stack" data-gap="1">
            <ExternalLink href={row.open_url ?? row.url} className={`ek-btn ek-btn--sm${uncertain ? " ek-btn--primary" : ""}`}>
              <ExternalIcon aria-hidden="true" size={14} /> Åpne lenke
            </ExternalLink>
            {row.kind === "internal" ? (
              // A web check of a Canvas address without logging in proves nothing; the next analysis checks it again.
              <span className="ek-xs ek-muted">Kontrolleres på nytt når du analyserer innholdskvaliteten.</span>
            ) : (
              <Button size="sm" variant={uncertain ? "secondary" : "ghost"} icon={<RefreshCw aria-hidden="true" size={14} />}
                onClick={() => recheck.mutate(row.url)} loading={recheck.isPending && recheck.variables === row.url}
                disabled={recheck.isPending && recheck.variables === row.url}>
                Sjekk på nytt<span className="ek-visually-hidden">: {row.url}</span>
              </Button>
            )}
            {editable ? (
              <Button size="sm" variant={row.category === "broken" ? "primary" : "ghost"} onClick={() => setChanging({ row, place: null })}>
                {editable > 1 ? "Endre flere steder" : "Endre lenke"}<span className="ek-visually-hidden">: {row.url}</span>
              </Button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <div className="ek-stack" data-gap="5">
      <Card title="Lenkestatus" description={`${freshness
        ?? (links.data.run_status === "cancelled"
          ? `Lenkekontrollen ${formatWhen(links.data.checked_at)} ble avbrutt før alle lenkene var sjekket – listen er ufullstendig.`
          : `Siste samlede lenkekontroll: ${formatDateTime(links.data.checked_at)}.`)} Hver lenke viser når den sist ble sjekket.`}>
        <KeyFigureList label="Lenkestatus">
          {ORDER.map((c) => (
            <KeyFigure key={c} icon={CATEGORY[c].icon} tone={CATEGORY[c].tone} value={totals[c] ?? 0} label={CATEGORY[c].label}
              description={CATEGORY[c].description} />
          ))}
        </KeyFigureList>
      </Card>
      <div className="ek-stack" data-gap="3">
        <FilterChips label="Vis" showLabel value={filter} onChange={setFilter}
          options={[
            { value: "problems", label: "Bør kontrolleres" },
            { value: "all", label: "Alle lenker" },
            ...ORDER.map((c) => ({ value: c, label: CATEGORY[c].label, count: totals[c] ?? 0 })),
          ]} />
        <TextField label="Søk i lenker" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          hint="Søk i adresse, tittel, side og modul." />
      </div>
      {recheck.error ? <Alert tone="danger" role="alert" title="Kunne ikke sjekke lenken">{(recheck.error as Error).message}</Alert> : null}
      <DataTable caption={`Lenker (${rows.length})`} columns={columns} rows={rows} rowKey={(row) => row.url}
        empty="Ingen lenker med dette valget." stackOnMobile align="top" />
      {changing && courseId ? (
        <ChangeLinkDialog key={changing.row.url} courseId={courseId} row={changing.row} start={changing.place}
          onClose={() => setChanging(null)} />
      ) : null}
      <FixFromLinks findingId={fixing} onClose={() => setFixing(null)} />
    </div>
  );
}

/** Opens the fix for one finding (from «Brukt i»). */
function FixFromLinks({ findingId, onClose }: { findingId: number | null; onClose: () => void }) {
  const finding = useFinding(findingId);
  return <FindingDetail finding={finding.data ?? null} open={findingId !== null && Boolean(finding.data)} onClose={onClose} />;
}
