import { Search } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime, formatNumber } from "../../core/format";
import { CLASSIFICATION, OBJECT_TYPE, TEST_METHOD, type Classification } from "../../core/labels";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Disclosure,
  EmptyState,
  Fieldset,
  SelectField,
  Spinner,
  TextField,
} from "../../design-system";
import { useFindings, type FindingFilters } from "./api";
import { FindingDetail } from "./FindingDetail";

const CLASS_ORDER: Classification[] = ["violation", "likely_violation", "should_review", "manual_check", "improvement"];

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
  const [filters, setFilters] = useState<FindingFilters>({
    classification: [], category: [], status: "open", q: "", sort: "priority", page: 1, page_size: 50,
  });
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
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="ek-stack" data-gap="6">
      <div className="ek-grid" data-cols="4">
        {CLASS_ORDER.map((cls) => (
          <Card key={cls} tone={CLASSIFICATION[cls].tone} headingLevel={3}>
            <div className="ek-stack" data-gap="1">
              <span className="ek-stat__value">{formatNumber(data.summary.by_classification[cls] ?? 0)}</span>
              <span className="ek-strong">{CLASSIFICATION[cls].label}</span>
              <span className="ek-xs">{CLASSIFICATION[cls].description}</span>
            </div>
          </Card>
        ))}
      </div>

      <p className="ek-small ek-muted">
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

      {extra}

      <Card title="Filtrer" headingLevel={2}>
        <form
          className="ek-grid"
          data-cols="2"
          onSubmit={(e) => {
            e.preventDefault();
            setFilters((f) => ({ ...f, q: query, page: 1 }));
          }}
        >
          <Fieldset legend="Klassifisering">
            {CLASS_ORDER.map((cls) => (
              <Checkbox
                key={cls}
                label={`${CLASSIFICATION[cls].label} (${data.summary.by_classification[cls] ?? 0})`}
                checked={filters.classification.includes(cls)}
                onChange={() => setFilters((f) => ({ ...f, classification: toggle(f.classification, cls), page: 1 }))}
              />
            ))}
          </Fieldset>
          <div className="ek-stack">
            <SelectField
              label="Kategori"
              value={filters.category[0] ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value ? [e.target.value] : [], page: 1 }))}
              placeholder="Alle kategorier"
              options={data.categories.map((c) => ({ value: c.id, label: `${c.label} (${data.summary.by_category[c.id] ?? 0})` }))}
            />
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
            <div className="ek-cluster" data-align="start">
              <div style={{ flex: 1 }}>
                <TextField label="Søk i funn" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <Button type="submit" icon={<Search aria-hidden="true" />} style={{ marginTop: "1.6rem" }}>
                Søk
              </Button>
            </div>
          </div>
        </form>
      </Card>

      <section className="ek-stack" aria-labelledby="funnliste">
        <div className="ek-section__header">
          <h2 id="funnliste">Funn</h2>
          <p className="ek-small ek-muted" aria-live="polite">
            {formatNumber(data.total)} funn {findings.isFetching ? "(oppdaterer …)" : ""}
          </p>
        </div>
        {data.items.length === 0 ? (
          <EmptyState title="Ingen funn med disse filtrene" headingLevel={3}>
            Prøv å endre filtrene. Husk at automatiske kontroller ikke kan bevise at alt er i orden.
          </EmptyState>
        ) : (
          <ul className="ek-list-reset ek-stack" data-gap="2">
            {data.items.map((f) => (
              <li key={f.id} className="ek-card" style={{ padding: "1rem 1.25rem" }}>
                <div className="ek-cluster" data-justify="between" data-align="start">
                  <div className="ek-stack" data-gap="1" style={{ flex: 1, minWidth: "16rem" }}>
                    <div className="ek-cluster" data-gap="2">
                      <Badge tone={CLASSIFICATION[f.classification].tone}>{CLASSIFICATION[f.classification].label}</Badge>
                      <span className="ek-xs ek-muted">{f.category_label}</span>
                      <span className="ek-xs ek-muted">· {TEST_METHOD[f.test_method].label}</span>
                      {f.status === "staged" ? <Badge tone="violet">I endringskø</Badge> : null}
                      {f.status === "fixed" ? <Badge tone="success">Rettet</Badge> : null}
                      {f.status === "ignored" ? <Badge>Ignorert</Badge> : null}
                    </div>
                    <h3 style={{ fontSize: "var(--text-base)" }}>{f.title}</h3>
                    <p className="ek-small">{f.message}</p>
                    <p className="ek-xs ek-muted">
                      {f.location?.module ? `${f.location.module} › ` : ""}
                      {OBJECT_TYPE[f.object_type ?? ""] ?? ""}: {f.object_title}
                    </p>
                  </div>
                  <div className="ek-cluster" data-gap="2">
                    <Button size="sm" onClick={() => setSelected(f)}>
                      {f.fix && f.status === "open" ? "Vis og rett" : "Vis detaljer"}
                      <span className="ek-visually-hidden">: {f.title} i {f.object_title}</span>
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {pages > 1 ? (
          <nav className="ek-cluster" aria-label="Sider med funn">
            <Button size="sm" disabled={filters.page <= 1} onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}>
              Forrige
            </Button>
            <span className="ek-small">
              Side {filters.page} av {pages}
            </span>
            <Button size="sm" disabled={filters.page >= pages} onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}>
              Neste
            </Button>
          </nav>
        ) : null}
      </section>
      <FindingDetail finding={selected} open={selected !== null} onClose={() => setSelected(null)} />
    </div>
  );
}
