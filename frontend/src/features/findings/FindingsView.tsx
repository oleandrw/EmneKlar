// Shared list of findings (Universell utforming, Innholdskvalitet, Emnestruktur): key figures per class,
// filters (category, class, status, sorting, search) and the findings themselves.
import { CircleAlert, ClipboardCheck, Lightbulb, Search, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime, formatNumber } from "../../core/format";
import { CategoryIcon } from "../../core/icons";
import { useSession } from "../../core/session";
import { CLASSIFICATION, OBJECT_TYPE, TEST_METHOD, type Classification } from "../../core/labels";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Disclosure,
  EmptyState,
  FilterChips,
  IconTile,
  MetricCard,
  SelectField,
  Spinner,
  StatusBadge,
  TextField,
  ToggleChips,
} from "../../design-system";
import { useFindings, type FindingFilters } from "./api";
import { FindingDetail } from "./FindingDetail";

const CLASS_ORDER: Classification[] = ["violation", "likely_violation", "should_review", "manual_check", "improvement"];
const ALL = "__all__";

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
  const [chosen, setFilters] = useState<Omit<FindingFilters, "page_size">>({
    classification: [], category: [], status: "open", q: "", sort: "priority", page: 1,
  });
  // «Funn per side» from Innstillinger → Generelt.
  const filters: FindingFilters = { ...chosen, page_size: session.general.page_size };
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Finding | null>(null);
  const findings = useFindings(courseId, domain, filters);

  if (!courseId) {
    return <EmptyState title="Velg et emne">Velg et emne i toppen av siden for å se resultater.</EmptyState>;
  }
  if (findings.isPending) return <Spinner label="Henter funn …" />;
  if (findings.error) {
    return (
      <Alert tone="danger" role="alert" title="Kunne ikke hente funn">
        {(findings.error as Error).message}
      </Alert>
    );
  }
  const data = findings.data;
  if (data.runs.length === 0) {
    return (
      <EmptyState
        title="Ingen analyse ennå"
        actions={
          <Button variant="primary" onClick={() => ui.openAnalysis()}>
            Kjør ny analyse
          </Button>
        }
      >
        {emptyText}
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
  const violations = byClass("violation") + byClass("likely_violation");
  const categoryTotal = Object.values(data.summary.by_category).reduce((sum, n) => sum + n, 0);

  return (
    <div className="ek-stack" data-gap="6">
      <div className="ek-grid" data-cols="4" data-gap="5">
        <MetricCard
          icon={<CircleAlert />}
          tone="danger"
          value={violations}
          valueTone={violations ? "critical" : "neutral"}
          label="Avvik / sannsynlige avvik"
          description={`${formatNumber(byClass("violation"))} avvik og ${formatNumber(byClass("likely_violation"))} sannsynlige avvik.`}
        />
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
          Siste analyse {formatDateTime(latest.finished_at ?? latest.started_at)}
          {latest.scope_type !== "course" ? " (deler av emnet – resten vises fra tidligere analyser)" : ""}. Regelsett{" "}
          {latest.ruleset_version ?? "–"}, profil «{data.profile.title}». {data.summary.ignored} ignorert,{" "}
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
          <ToggleChips
            label="Klassifisering"
            showLabel
            values={filters.classification}
            onToggle={(cls) => setFilters((f) => ({ ...f, classification: toggle(f.classification, cls), page: 1 }))}
            options={CLASS_ORDER.map((cls) => ({ value: cls, label: CLASSIFICATION[cls].label, count: byClass(cls) }))}
          />
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

          {data.items.length === 0 ? (
            <EmptyState title="Ingen funn med disse filtrene" headingLevel={3}>
              Prøv å endre filtrene. Husk at automatiske kontroller ikke kan bevise at alt er i orden.
            </EmptyState>
          ) : (
            <ul className="ek-item-list" aria-label="Funn">
              {data.items.map((f) => (
                <li key={f.id} className="ek-item-row">
                  <IconTile tone={CLASSIFICATION[f.classification].tone} size="sm" shape="square">
                    <CategoryIcon category={f.category} />
                  </IconTile>
                  <div className="ek-item-row__main">
                    <h3 className="ek-item-row__title">{f.title}</h3>
                    <p className="ek-item-row__text">{f.message}</p>
                    <p className="ek-item-row__meta">
                      {f.location?.module ? `${f.location.module} › ` : ""}
                      {OBJECT_TYPE[f.object_type ?? ""] ?? ""}: {f.object_title}
                      {" · "}
                      {f.category_label}
                      {" · "}
                      {TEST_METHOD[f.test_method].label}
                    </p>
                  </div>
                  <div className="ek-item-row__side">
                    <StatusBadge tone={CLASSIFICATION[f.classification].tone}>{CLASSIFICATION[f.classification].label}</StatusBadge>
                    {f.status === "staged" ? <Badge tone="violet">I endringskø</Badge> : null}
                    {f.status === "fixed" ? <Badge tone="success">Rettet</Badge> : null}
                    {f.status === "ignored" ? <Badge>Ignorert</Badge> : null}
                    <Button size="sm" onClick={() => setSelected(f)}>
                      {f.fix && f.status === "open" ? "Vis og rett" : "Vis detaljer"}
                      <span className="ek-visually-hidden">: {f.title} i {f.object_title}</span>
                    </Button>
                  </div>
                </li>
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
      <FindingDetail finding={selected} open={selected !== null} onClose={() => setSelected(null)} />
    </div>
  );
}
