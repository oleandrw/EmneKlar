// Emne-RAG → Spør emnet: hybrid search with sources, an optional AI answer with citations, and a debug view.
import { useMutation } from "@tanstack/react-query";
import { ExternalLink as ExternalIcon, Search, Sparkles } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";

import { AiBadge, AiConsent, type AiPlan } from "../../../core/ai";
import { api } from "../../../core/api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  Disclosure,
  Fieldset,
  TextArea,
  type Column,
} from "../../../design-system";
import type { AskResult, ChunkType, Hit, QueryBody, RagStatus, SearchResult } from "./api";

const TYPE_LABEL: Record<ChunkType, string> = { text: "Tekst", table: "Tabell", image: "Bilde", transcript: "Video",
  slide: "Lysbilde" };

function SourceLink({ hit, children }: { hit: Hit; children: ReactNode }) {
  if (!hit.url) return <>{children}</>;
  return (
    <a href={hit.url} target="_blank" rel="noreferrer">
      {children}
      <span className="ek-visually-hidden"> (åpnes i ny fane)</span>
    </a>
  );
}

/** Answer text with [S1] markers turned into links to the sources. No HTML from the model is rendered. */
export function AnswerText({ text, sources }: { text: string; sources: Hit[] }) {
  const byId = new Map(sources.map((s) => [s.id, s]));
  const inline = (line: string, key: string) => {
    const parts = line.split(/(\[S\d+\])/g);
    return parts.map((part, i) => {
      const match = /^\[(S\d+)\]$/.exec(part);
      const hit = match ? byId.get(match[1]) : undefined;
      if (!match) return <Fragment key={`${key}-${i}`}>{part.replace(/\*\*(.+?)\*\*/g, "$1")}</Fragment>;
      if (!hit) return null;
      return (
        <Fragment key={`${key}-${i}`}>
          {" "}
          <SourceLink hit={hit}><span className="ek-badge" data-tone="info">[{hit.citation}]</span></SourceLink>
        </Fragment>
      );
    });
  };
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="ek-stack" data-gap="3">
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*(?:[-*•]|\d+[.)])\s+/.test(l))) {
          return (
            <ul key={b}>
              {lines.map((l, i) => <li key={i}>{inline(l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ""), `${b}-${i}`)}</li>)}
            </ul>
          );
        }
        return <p key={b}>{inline(lines.join(" "), String(b))}</p>;
      })}
    </div>
  );
}

function Sources({ hits, title }: { hits: Hit[]; title: string }) {
  return (
    <section className="ek-stack" data-gap="3" aria-label={title}>
      <h3>{title}</h3>
      <ol className="ek-stack" data-gap="3">
        {hits.map((hit) => (
          <li key={hit.chunk_id} className="ek-card ek-card--compact">
            <div className="ek-stack" data-gap="1">
              <span className="ek-cluster" data-gap="2">
                <SourceLink hit={hit}><strong>{hit.citation}</strong></SourceLink>
                <Badge>{TYPE_LABEL[hit.type] ?? hit.type}</Badge>
                {hit.cited ? <Badge tone="success">Brukt i svaret</Badge> : null}
                {hit.meta?.ai_label ? <Badge tone="violet">{hit.meta.ai_label}</Badge> : null}
                {hit.url ? <ExternalIcon aria-hidden="true" className="ek-muted" /> : null}
              </span>
              {hit.heading_path.length ? <span className="ek-xs ek-muted">{hit.heading_path.join(" › ")}</span> : null}
              <span className="ek-small">{hit.snippet}</span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function modesText(result: SearchResult): string {
  const parts = ["nøkkelord (BM25)"];
  if (result.modes.vector) parts.push("semantisk søk");
  parts.push(result.modes.rerank ? "rerangering" : "RRF uten rerangering");
  if (result.modes.rewritten) parts.push(`omskrevet til ${result.queries.length - 1} ekstra søk`);
  return `Søket brukte ${parts.join(", ")}.`;
}

function DebugTables({ result }: { result: SearchResult }) {
  if (!result.debug) return null;
  const num = (v: number | null | undefined, digits = 3) => (v == null ? "–" : v.toFixed(digits));
  const columns: Column<Hit>[] = [
    { key: "rank", header: "Plass", numeric: true, cell: (h) => h.rank },
    { key: "citation", header: "Utdrag", rowHeader: true, cell: (h) => (
      <span className="ek-stack" data-gap="1"><span>{h.citation}</span><span className="ek-xs ek-muted">{h.snippet.slice(0, 120)}</span></span>
    ) },
    { key: "kw", header: "BM25 (plass)", numeric: true, cell: (h) => h.scores?.keyword_rank ?? "–" },
    { key: "vec", header: "Vektor (likhet)", numeric: true, cell: (h) => `${h.scores?.vector_rank ?? "–"} (${num(h.scores?.vector_score)})` },
    { key: "rrf", header: "RRF", numeric: true, cell: (h) => `${h.scores?.rrf_rank} (${num(h.scores?.rrf_score, 4)})` },
    { key: "rerank", header: "Rerangering", numeric: true, cell: (h) => num(h.scores?.rerank_score) },
  ];
  return (
    <Disclosure summary="Feilsøking: kandidater før og etter rerangering">
      <div className="ek-stack" data-gap="4">
        <DataTable caption="Før rerangering (RRF-rekkefølge)" columns={columns}
          rows={result.debug.before_rerank.map((h) => ({ ...h, rank: h.scores?.rrf_rank ?? h.rank }))}
          rowKey={(h) => `b${h.chunk_id}`} empty="Ingen kandidater." />
        <DataTable caption="Etter rerangering" columns={columns} rows={result.debug.after_rerank}
          rowKey={(h) => `a${h.chunk_id}`} empty="Ingen kandidater." />
      </div>
    </Disclosure>
  );
}

export function AskPanel({ courseId, status }: { courseId: string; status: RagStatus }) {
  const [query, setQuery] = useState("");
  const [modules, setModules] = useState<string[]>([]);
  const [types, setTypes] = useState<ChunkType[]>([]);
  const [debug, setDebug] = useState(false);
  const [plan, setPlan] = useState<AiPlan | null>(null);
  const [consented, setConsented] = useState(false);
  const body = (): QueryBody => ({ query, module_ids: modules, types, debug, confirmed: consented });
  const searchMutation = useMutation({
    mutationFn: (b: QueryBody) => api.post<SearchResult>(`/api/courses/${courseId}/rag/search`, b),
  });
  const prepare = useMutation({
    mutationFn: () => api.post<AiPlan>(`/api/courses/${courseId}/rag/ask/prepare`, body()),
    onSuccess: (p) => {
      if (p.available && (!p.needs_confirmation || consented)) {
        ask.mutate({ ...body(), confirmed: consented || !p.needs_confirmation });
      } else setPlan(p);
    },
  });
  const ask = useMutation({
    mutationFn: (b: QueryBody) => api.post<AskResult>(`/api/courses/${courseId}/rag/ask`, b),
  });
  const embeddingConsent = Boolean(status.embedding.needs_confirmation);
  if (!status.stats?.chunks) {
    return <Alert tone="info">Bygg indeksen først. Da kan du søke og stille spørsmål til emnet her.</Alert>;
  }
  const result = ask.data ?? null;
  const searchResult = searchMutation.data ?? null;
  const error = (searchMutation.error ?? prepare.error ?? ask.error) as Error | null;
  const doSearch = () => {
    ask.reset();
    searchMutation.mutate({ ...body(), confirmed: consented || !embeddingConsent });
  };
  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Spør emnet" headingLevel={2}>
        <form className="ek-stack" data-gap="4" onSubmit={(e) => { e.preventDefault(); if (query.trim()) doSearch(); }}>
          <TextArea label="Spørsmål" value={query} onChange={(e) => setQuery(e.target.value)} rows={3}
            hint="For eksempel «Når er fristen for innlevering 1?» eller «Hva er forskjellen på RGB og CMYK?»" />
          <Disclosure summary="Filtrer på modul og kildetype">
            <div className="ek-grid" data-cols="2">
              <Fieldset legend="Moduler" hint="Ingen valgt = alle moduler.">
                {status.modules.map((m) => (
                  <Checkbox key={m.id} label={m.name} checked={modules.includes(m.id)}
                    onChange={(e) => setModules(e.target.checked ? [...modules, m.id] : modules.filter((x) => x !== m.id))} />
                ))}
              </Fieldset>
              <Fieldset legend="Kildetyper" hint="Ingen valgt = alle typer.">
                {status.chunk_types.map((t) => (
                  <Checkbox key={t.key} label={t.label} checked={types.includes(t.key)}
                    onChange={(e) => setTypes(e.target.checked ? [...types, t.key] : types.filter((x) => x !== t.key))} />
                ))}
              </Fieldset>
            </div>
          </Disclosure>
          <Checkbox label="Vis feilsøking (kandidater med poeng før og etter rerangering)" checked={debug}
            onChange={(e) => setDebug(e.target.checked)} />
          {embeddingConsent ? (
            <Checkbox label={`Tillat at spørsmålet sendes til ${status.embedding.label} for embedding`} checked={consented}
              onChange={(e) => setConsented(e.target.checked)} />
          ) : null}
          <div className="ek-cluster">
            <Button type="submit" icon={<Search aria-hidden="true" />} loading={searchMutation.isPending}
              disabled={!query.trim() || (embeddingConsent && !consented)}>
              Søk i emnet
            </Button>
            <Button variant="primary" icon={<Sparkles aria-hidden="true" />} disabled={!query.trim() || !status.ai.available}
              loading={prepare.isPending || ask.isPending} onClick={() => { searchMutation.reset(); prepare.mutate(); }}
              title={status.ai.available ? undefined : status.ai.reason ?? undefined}>
              Svar med KI
            </Button>
          </div>
          {!status.ai.available ? (
            <p className="ek-small ek-muted">Svar med KI er ikke tilgjengelig: {status.ai.reason} Søket virker uten KI.</p>
          ) : null}
          {plan ? (
            <AiConsent plan={plan} loading={ask.isPending} onCancel={() => setPlan(null)}
              onConfirm={() => { setConsented(true); setPlan(null); ask.mutate({ ...body(), confirmed: true }); }} />
          ) : null}
          {error ? <Alert tone="danger" role="alert">{error.message}</Alert> : null}
        </form>
      </Card>

      {result ? (
        <Card title="Svar" headingLevel={2} actions={result.answer ? <AiBadge /> : null}>
          <div className="ek-stack" data-gap="4" aria-live="polite">
            {result.answer == null ? <Alert tone="info">{result.message}</Alert> : (
              <>
                {result.coverage === "none" ? (
                  <Alert tone="warning" title="Emnet dekker ikke spørsmålet">Svaret under forklarer hva som mangler.</Alert>
                ) : result.coverage === "partial" ? (
                  <Alert tone="info" title="Emnet dekker spørsmålet bare delvis" />
                ) : null}
                <AnswerText text={result.answer} sources={result.sources} />
                <p className="ek-xs ek-muted">Modell: {result.model} ({result.provider}). {modesText(result.search)}</p>
              </>
            )}
            {result.search.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
            {result.sources.length ? <Sources hits={result.sources} title="Kilder" /> : null}
            <DebugTables result={result.search} />
          </div>
        </Card>
      ) : null}

      {searchResult ? (
        <Card title="Treff" headingLevel={2}>
          <div className="ek-stack" data-gap="4" aria-live="polite">
            <p className="ek-small">{modesText(searchResult)}</p>
            {searchResult.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
            {searchResult.hits.length ? <Sources hits={searchResult.hits} title="Mest relevante utdrag" />
              : <p className="ek-muted">Fant ingenting som passer.</p>}
            <DebugTables result={searchResult} />
          </div>
        </Card>
      ) : null}
    </div>
  );
}
