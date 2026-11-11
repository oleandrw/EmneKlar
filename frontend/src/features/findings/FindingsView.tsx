// Shared list of findings (Universell utforming, Innholdskvalitet, Emnestruktur): key figures per class,
// filters (category, class, status, sorting, search), the findings themselves – and the fast path through them:
// select several or «Godkjenn alle klare», step from one finding to the next, prepare KI-forslag for images.
import { useMutation } from "@tanstack/react-query";
import { CheckCheck, CircleAlert, ClipboardCheck, Lightbulb, Search, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime, formatNumber } from "../../core/format";
import { CategoryIcon } from "../../core/icons";
import { useSession } from "../../core/session";
import { useCourseAnalysis } from "../../core/jobs";
import {
  CLASSIFICATION,
  OBJECT_TYPE,
  SEVERITY,
  TEST_METHOD,
  classificationFor,
  confirmedLikelyLabels,
  type AnalysisDomain,
  type Classification,
} from "../../core/labels";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Disclosure,
  EmptyState,
  ExternalLink,
  FilterChips,
  IconTile,
  MetricCard,
  SelectField,
  Spinner,
  StatusBadge,
  TextField,
  ToggleChips,
  useToast,
} from "../../design-system";
import { useResultsFreshness } from "../analysis/AnalysisStatus";
import { useJob, FINAL_STATUSES } from "../analysis/useJob";
import { AltConsentDialog, SUGGESTION_STATUS } from "./AltTextSuggestion";
import { bulkApprove, useAltStatus, useFinding, useFindingActions, useFindings, type FindingFilters } from "./api";
import { FindingDetail } from "./FindingDetail";

const CLASS_ORDER: Classification[] = ["violation", "likely_violation", "should_review", "manual_check", "improvement"];
const ALL = "__all__";

/** A selection from a link, e.g. Emneoversikt → «Se alvorlige avvik»:
 * ``?klasse=violation&alvorlighet=critical,serious&regel=…&utvalg=<what it is, in words>``. */
interface Preset {
  classification: string[];
  severity: string[];
  rule: string[];
  label: string | null;
}

const list = (value: string | null) => (value ? value.split(",").map((v) => v.trim()).filter(Boolean) : []);

function presetFromSearch(params: URLSearchParams): Preset {
  return {
    classification: list(params.get("klasse")).filter((c) => (CLASS_ORDER as string[]).includes(c)),
    severity: list(params.get("alvorlighet")),
    rule: list(params.get("regel")),
    label: params.get("utvalg"),
  };
}

function filtersFrom(preset: Preset): Omit<FindingFilters, "page_size"> {
  return { classification: preset.classification, category: [], status: "open", q: "", sort: "priority", page: 1,
    severity: preset.severity, rule: preset.rule };
}

interface BulkResult {
  approved: number[];
  failed: { finding_id: number; object_title: string; message: string }[];
  skipped: { finding_id: number; reason: string }[];
  change_ids: number[];
}

export function FindingsView({
  domain,
  emptyText,
  extra,
}: {
  domain: string;
  emptyText: string;
  extra?: ReactNode;
}) {
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const session = useSession();
  const toast = useToast();
  const actions = useFindingActions();
  const [search, setSearch] = useSearchParams();
  const searchKey = search.toString();
  const preset = useMemo(() => presetFromSearch(new URLSearchParams(searchKey)), [searchKey]);
  const [chosen, setFilters] = useState<Omit<FindingFilters, "page_size">>(() => filtersFrom(preset));
  // A new link to the page (another selection) starts from that selection.
  useEffect(() => setFilters(filtersFrom(preset)), [preset]);
  const narrowed = Boolean(chosen.severity?.length || chosen.rule?.length || preset.label);
  const clearPreset = () => {
    setSearch({}, { replace: true });
    setFilters(filtersFrom({ classification: [], severity: [], rule: [], label: null }));
  };
  // «Funn per side» from Innstillinger → Generelt.
  const filters: FindingFilters = { ...chosen, page_size: session.general.page_size };
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checked, setChecked] = useState<number[]>([]);
  const [bulk, setBulk] = useState<{ ids: number[]; all: boolean } | null>(null);
  const [includeText, setIncludeText] = useState(false);
  const [bulkJob, setBulkJob] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const readyHintId = useId();
  const findings = useFindings(courseId, domain, filters);
  const job = useJob(bulkJob);
  const data = findings.data;
  const newestRun = data?.runs[0];
  // While a new check runs (or after one stopped) the time shown is still the time of the results shown.
  const freshness = useResultsFreshness(domain as AnalysisDomain,
    newestRun ? (newestRun.finished_at ?? newestRun.started_at) : null);
  const { runningHere } = useCourseAnalysis(domain);
  const items = useMemo(() => data?.items ?? [], [data]);
  const ids = useMemo(() => data?.ids ?? [], [data]);

  // The finding being looked at: from the loaded page, or fetched on its own when stepping beyond it. The single
  // fetch is kept for every open finding, so the detail view stays open (with its state) when a refresh moves the
  // finding off the page – e.g. after «Lagre og analyser siden på nytt» replaced it with the right requirement.
  const onPage = items.find((f) => f.id === selectedId) ?? null;
  const fetched = useFinding(selectedId);
  const selected = onPage ?? fetched.data ?? null;
  const index = selectedId !== null ? ids.indexOf(selectedId) : -1;
  const imageIds = items.filter((f) => f.image && f.status === "open").map((f) => f.id);
  const altStatus = useAltStatus(courseId, domain === "accessibility" ? imageIds : []);

  const startBulk = useMutation({
    mutationFn: (request: { ids: number[] }) => bulkApprove(courseId!, request.ids, includeText),
    onSuccess: (result) => {
      setBulk(null);
      setChecked([]);
      setBulkJob(result.job.id);
      toast.show({ tone: "info", title: `Godkjenner ${result.planned} forslag …`, body: result.skipped.length
        ? `${result.skipped.length} krever at du tar stilling til dem først og hoppes over.` : undefined });
    },
  });
  const bulkResult = job.data && FINAL_STATUSES.has(job.data.status) ? (job.data.result as unknown as BulkResult) : null;
  const bulkDone = Boolean(bulkResult);
  useEffect(() => {
    if (bulkDone) actions.refresh(); // the queue (and its header button) shows the newly approved changes at once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bulkDone]);

  if (!courseId) {
    return <EmptyState title="Velg et emne">Velg et emne i toppen av siden for å se resultater.</EmptyState>;
  }
  if (findings.isPending) return <Spinner label="Henter funn …" />;
  if (findings.error || !data) {
    return (
      <Alert tone="danger" role="alert" title="Kunne ikke hente funn">
        {(findings.error as Error | null)?.message ?? "Ukjent feil."}
      </Alert>
    );
  }
  if (data.runs.length === 0) {
    return (
      <EmptyState
        title={runningHere ? "Første kontroll pågår" : "Ingen analyse ennå"}
      >
        {runningHere ? "Funnene vises her når kontrollen er ferdig. Fremdriften står under «Analysestatus» øverst til høyre." : emptyText}
      </EmptyState>
    );
  }
  const latest = data.runs[0];
  const byClass = (cls: Classification) => data.summary.by_classification[cls] ?? 0;
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const firstShown = data.total === 0 ? 0 : (filters.page - 1) * data.page_size + 1;
  const lastShown = Math.min(data.total, filters.page * data.page_size);
  // Confirmed as the main figure, likely ones under it – the same order as Oversikt. Not shown in an area whose rules
  // never give either class (Emnestruktur), instead of an empty card.
  const classes = data.classifications ?? CLASS_ORDER;
  const usesLikely = classes.includes("likely_violation");
  const usesConfirmed = usesLikely || classes.includes("violation");
  const pair = confirmedLikelyLabels(domain);
  const confirmed = byClass("violation");
  const likely = byClass("likely_violation");
  // The class filter shows the classes this area has findings in – and one that is chosen (e.g. through a link from
  // Oversikt) even with 0, so the selection stays visible and can be undone. No «Sannsynlig feil (0)» on Innholdskvalitet.
  const classOptions = CLASS_ORDER.filter((cls) => byClass(cls) > 0 || filters.classification.includes(cls));
  const categoryTotal = Object.values(data.summary.by_category).reduce((sum, n) => sum + n, 0);
  const selectable = items.filter((f) => f.fix && f.status === "open");
  // «Klar» = the fix is decided by the finding, so nothing has to be chosen first (rule-based text suggestions count
  // when included). KI-forslag are never ready. The totals are for the whole selection, which the button works on.
  const readyTotal = data.ready?.automatic ?? items.filter((f) => f.ready === "automatic").length;
  const suggestionsTotal = data.ready?.suggestion ?? items.filter((f) => f.ready === "suggestion").length;
  const anyReady = readyTotal + suggestionsTotal > 0;
  const bulkRunning = Boolean(job.data && !FINAL_STATUSES.has(job.data.status));
  const nav = index >= 0 ? {
    index,
    total: ids.length,
    onPrev: index > 0 ? () => setSelectedId(ids[index - 1]) : undefined,
    onNext: index < ids.length - 1 ? () => setSelectedId(ids[index + 1]) : undefined,
    upcoming: ids.slice(index + 1, index + 6),
  } : undefined;
  const queue = altStatus.data?.queue;
  const imagesOpen = items.some((f) => f.image && f.status === "open");

  return (
    <div className="ek-stack" data-gap="6">
      <div className="ek-grid" data-cols={usesConfirmed ? "4" : "3"} data-gap="5">
        {usesConfirmed ? (
          <MetricCard
            icon={<CircleAlert />}
            tone="danger"
            value={confirmed}
            valueTone={confirmed ? "critical" : "neutral"}
            label={pair.confirmed}
            secondary={usesLikely ? { value: likely, label: pair.likely(likely), tone: "warning" } : null}
            description={pair.description(usesLikely)}
          />
        ) : null}
        <MetricCard
          icon={<TriangleAlert />}
          tone="warning"
          value={byClass("should_review")}
          valueTone={byClass("should_review") ? "warning" : "neutral"}
          label={CLASSIFICATION.should_review.label}
          description={CLASSIFICATION.should_review.description}
        />
        <MetricCard
          icon={<Lightbulb />}
          tone="info"
          value={byClass("improvement")}
          label={CLASSIFICATION.improvement.label}
          description={CLASSIFICATION.improvement.description}
        />
        <MetricCard
          icon={<ClipboardCheck />}
          tone="neutral"
          value={byClass("manual_check")}
          label={CLASSIFICATION.manual_check.label}
          description={CLASSIFICATION.manual_check.description}
        />
      </div>

      <div className="ek-stack" data-gap="2">
        <p className="ek-meta-line">
          {freshness ? `${freshness} ` : null}
          {freshness ? null : latest.status === "cancelled" ? (
            <>
              Siste analyse {formatDateTime(latest.finished_at ?? latest.started_at)} ble avbrutt før den var ferdig – det
              den ikke rakk, vises fra tidligere analyser.{" "}
            </>
          ) : (
            <>
              Siste analyse {formatDateTime(latest.finished_at ?? latest.started_at)}
              {latest.scope_type !== "course" ? " (deler av emnet – resten vises fra tidligere analyser)" : ""}.{" "}
            </>
          )}
          {/* The ruleset and the regulatory profile belong to universal design only. */}
          {domain === "accessibility" ? <>Regelsett {latest.ruleset_version ?? "–"}, profil «{data.profile.title}». </> : null}
          {data.summary.ignored} ignorert, {data.summary.verified ?? 0} kontrollert,{" "}
          {data.summary.staged} i endringskø, {data.summary.fixed} rettet.
        </p>
        {latest.limitations?.length ? (
          <Disclosure summary={`Begrensninger i analysen (${latest.limitations.length})`}>
            <ul className="ek-small">
              {latest.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Disclosure>
        ) : null}
      </div>

      {extra}

      {domain === "accessibility" && imagesOpen ? (
        <Card title="KI-forslag til alt-tekst" headingLevel={3}
          actions={<Button size="sm" icon={<Sparkles aria-hidden="true" />} onClick={() => setConsent(true)}>
            {queue?.consented ? "Forbered forslag for flere bilder" : "Forbered forslag for bildene"}
          </Button>}>
          <p className="ek-small" aria-live="polite">
            {queue && queue.queued + queue.running > 0
              ? `Lager forslag i bakgrunnen: ${queue.running} pågår, ${queue.queued} i kø. Du kan fortsette å jobbe – bildet du åpner, kommer først.`
              : "Forslagene lages i bakgrunnen, tre om gangen, og er klare når du åpner bildene. Du ser hva som sendes før noe sendes, og alle forslag må vurderes."}
          </p>
        </Card>
      ) : null}

      {bulkResult ? (
        <Alert tone={bulkResult.failed?.length ? "warning" : "success"} role="status" title="Godkjenning ferdig"
          actions={<Button size="sm" variant="primary" onClick={ui.openChanges}>Åpne endringskøen</Button>}>
          {bulkResult.approved?.length ?? 0} forslag er godkjent og ligger i endringskøen ({bulkResult.change_ids?.length ?? 0}{" "}
          {bulkResult.change_ids?.length === 1 ? "endring" : "endringer"}).
          {bulkResult.skipped?.length ? ` ${bulkResult.skipped.length} krever at du tar stilling til dem.` : ""}
          {bulkResult.failed?.length ? ` ${bulkResult.failed.length} kunne ikke lages: ${bulkResult.failed.slice(0, 3).map((f) => `${f.object_title}: ${f.message}`).join("; ")}` : ""}
        </Alert>
      ) : job.data && !FINAL_STATUSES.has(job.data.status) ? (
        <Spinner label={`Godkjenner forslag … ${job.data.progress.done} av ${job.data.progress.total} sider`} />
      ) : null}

      {narrowed ? (
        <Alert tone="info" title={`Utvalg: ${preset.label ?? "valgte funn"}`}
          actions={<Button size="sm" onClick={clearPreset}>Vis alle funn</Button>}>
          Listen viser {formatNumber(data.total)} funn i dette utvalget
          {chosen.severity?.length ? ` (alvorlighet ${chosen.severity.map((v) => SEVERITY[v as keyof typeof SEVERITY]?.label.toLowerCase() ?? v).join(" eller ")})` : ""}.
          Tallene over gjelder hele området.
        </Alert>
      ) : null}

      <Card
        title="Funn i innholdet"
        actions={
          <p className="ek-small ek-muted" aria-live="polite">
            {formatNumber(data.total)} funn {findings.isFetching ? "(oppdaterer …)" : ""}
          </p>
        }
      >
        <div className="ek-stack" data-gap="5">
          <FilterChips
            label="Kategori"
            showLabel
            value={filters.category[0] ?? ALL}
            onChange={(value) => setFilters((f) => ({ ...f, category: value === ALL ? [] : [value], page: 1 }))}
            options={[
              { value: ALL, label: "Alle", count: categoryTotal },
              ...data.categories.map((c) => ({
                value: c.id,
                label: c.label,
                count: data.summary.by_category[c.id] ?? 0,
                icon: <CategoryIcon category={c.id} />,
              })),
            ]}
          />
          {classOptions.length ? (
            <ToggleChips
              label="Klassifisering"
              showLabel
              values={filters.classification}
              onToggle={(cls) => setFilters((f) => ({ ...f, classification: toggle(f.classification, cls), page: 1 }))}
              options={classOptions.map((cls) => ({ value: cls, label: classificationFor(cls, domain).label, count: byClass(cls) }))}
            />
          ) : null}
          <form
            className="ek-toolbar"
            role="search"
            aria-label="Søk og sortering"
            onSubmit={(e) => {
              e.preventDefault();
              setFilters((f) => ({ ...f, q: query, page: 1 }));
            }}
          >
            <SelectField
              label="Status"
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value, page: 1 }))}
              options={[
                { value: "open", label: "Åpne funn" },
                { value: "staged", label: "I endringskø" },
                { value: "fixed", label: "Rettet" },
                { value: "ignored", label: "Ignorert" },
                { value: "verified", label: "Kontrollert" },
                { value: "all", label: "Alle" },
              ]}
            />
            <SelectField
              label="Sortering"
              value={filters.sort}
              onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}
              options={[
                { value: "priority", label: "Viktigst først" },
                { value: "object", label: "Etter innhold" },
              ]}
            />
            <div className="ek-search ek-toolbar__grow">
              <TextField label="Søk i funn" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
              <Button type="submit" icon={<Search aria-hidden="true" />}>
                Søk
              </Button>
            </div>
          </form>

          {selectable.length ? (
            <div className="ek-selection-bar" role="region" aria-label="Godkjenn flere">
              <Checkbox
                label={checked.length ? `${checked.length} valgt` : "Velg alle på siden"}
                checked={checked.length > 0 && selectable.every((f) => checked.includes(f.id))}
                onChange={(e) => setChecked(e.target.checked ? selectable.map((f) => f.id) : [])}
              />
              <span id={readyHintId} className="ek-selection-bar__count ek-small ek-muted">
                {anyReady
                  ? `${readyTotal} klare i utvalget${suggestionsTotal ? `, og ${suggestionsTotal} med regelbaserte tekstforslag` : ""}. `
                  : "Ingen klare i utvalget. "}
                Klar betyr at rettingen er bestemt av funnet, så du ikke må velge noe først. KI-forslag må vurderes ett for
                ett og er ikke med.
              </span>
              <Button size="sm" disabled={!checked.length} onClick={() => setBulk({ ids: checked, all: false })}>
                Godkjenn valgte ({checked.length})
              </Button>
              {/* The main action only when there is something ready; otherwise a disabled, quiet button. */}
              <Button size="sm" variant={anyReady ? "primary" : "secondary"} icon={<CheckCheck aria-hidden="true" />}
                aria-describedby={readyHintId} onClick={() => setBulk({ ids: ids, all: true })}
                disabled={!anyReady || bulkRunning}>
                Godkjenn alle klare
              </Button>
            </div>
          ) : null}

          {data.items.length === 0 ? (
            <EmptyState title="Ingen funn med disse filtrene" headingLevel={3}>
              Prøv å endre filtrene. Husk at automatiske kontroller ikke kan bevise at alt er i orden.
            </EmptyState>
          ) : (
            <ul className="ek-item-list" aria-label="Funn">
              {data.items.map((f) => (
                <FindingRow key={f.id} finding={f} checked={checked.includes(f.id)}
                  suggestionStatus={altStatus.data?.items[String(f.id)]?.status ?? f.alt_suggestion?.status}
                  onCheck={(on) => setChecked((cur) => (on ? [...cur, f.id] : cur.filter((x) => x !== f.id)))}
                  onOpen={() => setSelectedId(f.id)} />
              ))}
            </ul>
          )}
          {data.total > 0 ? (
            <nav className="ek-pager" aria-label="Sider med funn">
              <span>
                Viser {formatNumber(firstShown)}–{formatNumber(lastShown)} av {formatNumber(data.total)} funn
              </span>
              {pages > 1 ? (
                <span className="ek-cluster" data-gap="2">
                  <Button size="sm" disabled={filters.page <= 1} onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}>
                    Forrige
                  </Button>
                  <span>
                    Side {filters.page} av {pages}
                  </span>
                  <Button size="sm" disabled={filters.page >= pages} onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}>
                    Neste
                  </Button>
                </span>
              ) : null}
            </nav>
          ) : null}
        </div>
      </Card>
      <FindingDetail finding={selected} open={selectedId !== null && selected !== null} onClose={() => {
        setSelectedId(null);
        actions.refresh();
      }} nav={nav} />

      <ConfirmDialog
        open={bulk !== null}
        onClose={() => setBulk(null)}
        onConfirm={() => bulk && startBulk.mutate({ ids: bulk.ids })}
        title={bulk?.all ? "Godkjenn alle klare forslag" : `Godkjenn ${bulk?.ids.length ?? 0} valgte`}
        confirmLabel="Godkjenn"
        loading={startBulk.isPending}
      >
        <p>
          {bulk?.all ? "Alle funn i listen (alle sider, med filtrene du har valgt) " : "De valgte funnene "}
          som har en retting som er bestemt av funnet selv – for eksempel overskriftsnivå, tabelloverskrifter og opprydding
          i kode – godkjennes og legges i endringskøen, én endring per side. Funn som krever at du velger eller skriver
          noe, hoppes over. Lenker fjernes aldri på denne måten.
        </p>
        <Checkbox
          label="Ta også med regelbaserte tekstforslag"
          hint="Lenketekst laget ut fra selve lenken og ny adresse for lenker som er flyttet. De vises som forslag i endringskøen, der du kan fjerne dem før publisering. KI-forslag tas aldri med her – de gjennomgås og godkjennes i hvert funn."
          checked={includeText}
          onChange={(e) => setIncludeText(e.target.checked)}
        />
        <p className="ek-muted">Ingenting endres i Canvas før du publiserer fra endringskøen.</p>
        {startBulk.error ? <Alert tone="danger" role="alert">{(startBulk.error as Error).message}</Alert> : null}
      </ConfirmDialog>
      <AltConsentDialog courseId={courseId} findingIds={[]} open={consent} onClose={() => setConsent(false)}
        onStarted={(added) => toast.show({ tone: "info", title: added ? `${added} bilder lagt i køen` : "Alle forslag er allerede klare" })} />
    </div>
  );
}

function FindingRow({ finding: f, checked, suggestionStatus, onCheck, onOpen }: {
  finding: Finding;
  checked: boolean;
  suggestionStatus?: string;
  onCheck: (on: boolean) => void;
  onOpen: () => void;
}) {
  const canvas = f.canvas?.highlight ?? f.canvas?.view ?? f.object_url;
  const selectable = Boolean(f.fix) && f.status === "open";
  const suggestion = suggestionStatus && suggestionStatus !== "none" ? SUGGESTION_STATUS[suggestionStatus as keyof typeof SUGGESTION_STATUS] : null;
  return (
    <li className="ek-item-row">
      <span className="ek-item-row__lead">
        {selectable ? (
          <Checkbox label={<span className="ek-visually-hidden">Velg: {f.title} i {f.object_title}</span>} checked={checked}
            onChange={(e) => onCheck(e.target.checked)} />
        ) : null}
        <IconTile tone={classificationFor(f.classification, f.domain).tone} size="sm" shape="square">
          <CategoryIcon category={f.category} />
        </IconTile>
      </span>
      <div className="ek-item-row__main">
        <h3 className="ek-item-row__title">{f.title}</h3>
        <p className="ek-item-row__text">{f.message}</p>
        <p className="ek-item-row__meta">
          {f.location?.module ? `${f.location.module} › ` : ""}
          {OBJECT_TYPE[f.object_type ?? ""] ?? ""}:{" "}
          {canvas ? <ExternalLink href={canvas}>{f.object_title}</ExternalLink> : f.object_title}
          {" · "}
          {f.category_label}
          {" · "}
          {TEST_METHOD[f.test_method].label}
        </p>
      </div>
      <div className="ek-item-row__side">
        <StatusBadge tone={classificationFor(f.classification, f.domain).tone}>{classificationFor(f.classification, f.domain).label}</StatusBadge>
        {f.status === "staged" ? <Badge tone="violet">I endringskø</Badge> : null}
        {f.status === "fixed" ? <Badge tone="success">Rettet</Badge> : null}
        {f.status === "ignored" ? <Badge>Ignorert</Badge> : null}
        {f.status === "verified" ? <Badge tone="success">Kontrollert</Badge> : null}
        {f.status === "open" && f.ready === "automatic" ? <Badge tone="success">Klar til godkjenning</Badge> : null}
        {f.status === "open" && suggestion ? <Badge tone={suggestion.tone} icon={<Sparkles aria-hidden="true" size={14} />}>{suggestion.label}</Badge> : null}
        <Button size="sm" onClick={onOpen}>
          {f.fix && f.status === "open" ? "Vis og rett" : "Vis detaljer"}
          <span className="ek-visually-hidden">: {f.title} i {f.object_title}</span>
        </Button>
      </div>
    </li>
  );
}
