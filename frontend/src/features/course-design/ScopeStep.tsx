// Emnedesign, step 1 «Omfang»: the whole course or one module, what is actually affected (from Canvas – never sample
// figures) and Blueprint in one short, correct explanation. The designs themselves are shown in the next step.
// Counts are of unique content: a page used in several modules, or used as the front page, is one item; the kinds are
// disjoint, so the breakdown adds up to the total.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Layers, LibraryBig } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { api, ApiError } from "../../core/api/client";
import { plural } from "../../core/format";
import { Alert, Button, Card, Disclosure, RadioGroup, Spinner, TextField } from "../../design-system";
import type { BlueprintSelection, ContentKind, Inventory, InventoryItem, InventoryModule } from "./api";

export type Scope = "course" | "module";

/** Modules from this many on get a search field. */
const SEARCH_FROM = 8;

const KIND_WORDS: Record<ContentKind, [string, string]> = {
  front_page: ["forside", "forsider"],
  syllabus: ["emneplan", "emneplaner"],
  module_intro: ["modulintroduksjon", "modulintroduksjoner"],
  page: ["side", "sider"],
  assignment: ["oppgave", "oppgaver"],
  quiz: ["klassisk quiz", "klassiske quizer"],
};
const KIND_LABEL: Record<ContentKind, string> = {
  front_page: "Forside", syllabus: "Emneplan", module_intro: "Modulintroduksjoner", page: "Andre sider",
  assignment: "Oppgaver", quiz: "Klassiske quizer",
};
const KIND_ORDER: ContentKind[] = ["front_page", "syllabus", "module_intro", "page", "assignment", "quiz"];
/** Which Canvas permission (from /capabilities) editing each kind needs; the course syllabus is not checked. */
const NEEDS: Partial<Record<ContentKind, "pages" | "assignments">> = {
  front_page: "pages", module_intro: "pages", page: "pages", assignment: "assignments", quiz: "assignments",
};

interface Capabilities {
  capabilities: { key: string; label: string; granted: boolean }[];
}

function useCapabilities(courseId: string) {
  return useQuery({
    queryKey: ["capabilities", courseId],
    queryFn: () => api.get<Capabilities>(`/api/courses/${courseId}/capabilities`),
    staleTime: 60_000,
    retry: false,
  });
}

function list(parts: string[]): string {
  return parts.length <= 1 ? parts.join("") : `${parts.slice(0, -1).join(", ")} og ${parts[parts.length - 1]}`;
}

/** «1 forside, 12 sider og 2 klassiske quizer». */
export function kindCounts(items: InventoryItem[]): string {
  return list(KIND_ORDER.flatMap((kind) => {
    const n = items.filter((i) => i.kind === kind).length;
    return n ? [`${n} ${n === 1 ? KIND_WORDS[kind][0] : KIND_WORDS[kind][1]}`] : [];
  }));
}

/** What the scope holds, from the inventory: unique items, what can get the design, and what is skipped. */
export function scopeFacts(items: InventoryItem[]) {
  const ready = items.filter((i) => !i.empty && !i.excluded);
  return {
    ready,
    empty: items.filter((i) => i.empty).length,
    excluded: items.filter((i) => i.excluded && !i.empty).length,
    locked: ready.filter((i) => i.locked).length,
    shared: ready.filter((i) => i.shared),
  };
}

function LoadError({ query, what }: { query: UseQueryResult<unknown>; what: string }) {
  const error = query.error;
  const forbidden = error instanceof ApiError && (error.status === 403 || error.code === "canvas_forbidden");
  return (
    <Alert tone="danger" role="alert" title={forbidden ? "Mangler tilgang i Canvas" : `Kunne ikke lese ${what}`}>
      <p>{forbidden ? "Canvas gir deg ikke tilgang til å lese innholdet i dette emnet." : (error as Error)?.message}</p>
      <Button size="sm" onClick={() => void query.refetch()} loading={query.isFetching}>Prøv igjen</Button>
    </Alert>
  );
}

/** «6 elementer, 4 kan få design» – plus «modul 3 av 19 · ikke publisert» only where it tells equal names apart. */
export function moduleMeta(m: InventoryModule, all: InventoryModule[]): string {
  const parts: string[] = [];
  if (typeof m.total === "number" && typeof m.count === "number") {
    parts.push(m.total === 0 ? "Tom modul"
      : `${plural(m.total, "element", "elementer")}, ${m.count ? `${m.count} kan få design` : "ingen kan få design"}`);
  } else if (typeof m.count === "number") {
    parts.push(m.count ? `${m.count} kan få design` : "Ingen kan få design");
  }
  const same = all.filter((x) => (x.name ?? "").trim().toLowerCase() === (m.name ?? "").trim().toLowerCase());
  if (same.length > 1) {
    if (m.position) parts.push(`modul ${m.position} av ${all.length}`);
    if (m.published === false) parts.push("ikke publisert");
  }
  return parts.join(" · ");
}

function ModulePicker({ courseInventory, moduleId, setModuleId }: {
  courseInventory: UseQueryResult<Inventory>;
  moduleId: string;
  setModuleId: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const legendId = useId();
  const modules = courseInventory.data?.modules ?? [];
  // The chosen module is easy to find again: scroll the list (not the page) to it when the picker opens.
  useEffect(() => {
    const listEl = listRef.current;
    const row = listEl?.querySelector<HTMLElement>("input:checked")?.closest("li");
    if (listEl && row && (row.offsetTop < listEl.scrollTop || row.offsetTop + row.offsetHeight > listEl.scrollTop + listEl.clientHeight)) {
      listEl.scrollTop = Math.max(0, row.offsetTop - listEl.clientHeight / 2);
    }
  }, [courseInventory.data]);
  if (courseInventory.isPending) return <Spinner label="Henter modulene fra Canvas …" />;
  if (courseInventory.error) return <LoadError query={courseInventory} what="modulene" />;
  if (modules.length === 0) return <p className="ek-small ek-muted">Emnet har ingen moduler.</p>;
  const searchable = modules.length >= SEARCH_FROM;
  const needle = query.trim().toLowerCase();
  const shown = needle ? modules.filter((m) => (m.name ?? "").toLowerCase().includes(needle)) : modules;
  const chosen = modules.find((m) => m.id === moduleId);
  return (
    <fieldset className="ek-module-picker">
      <legend id={legendId} className="ek-module-picker__legend">Velg modul</legend>
      <div className="ek-module-picker__box">
        {searchable ? (
          <div className="ek-module-picker__search">
            <TextField label="Søk etter modul" hideLabel type="search" value={query} placeholder="Søk etter modulnavn …"
              onChange={(e) => setQuery(e.target.value)} />
          </div>
        ) : null}
        <p className="ek-module-picker__count" aria-live="polite">
          {needle ? plural(shown.length, "treff", "treff") : plural(modules.length, "modul", "moduler")}
        </p>
        {shown.length ? (
          <ul ref={listRef} className="ek-module-list" aria-labelledby={legendId}>
            {shown.map((m) => {
              const meta = moduleMeta(m, modules);
              return (
                <li key={m.id}>
                  <label className="ek-module-row">
                    <input type="radio" name="design-module" value={m.id} checked={m.id === moduleId} onChange={() => setModuleId(m.id)} />
                    <span className="ek-module-row__text">
                      <span className="ek-module-row__name">{m.name || "Modul uten navn"}</span>
                      {meta ? <span className="ek-module-row__meta">{meta}</span> : null}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="ek-module-picker__empty">
            <p className="ek-small">Ingen moduler passer søket «{query.trim()}».</p>
            <Button size="sm" variant="ghost" onClick={() => setQuery("")}>Tøm søket</Button>
          </div>
        )}
      </div>
      {chosen && !shown.includes(chosen) ? <p className="ek-small">Valgt: {chosen.name}</p> : null}
    </fieldset>
  );
}

function BlueprintNote({ blueprint }: { blueprint: BlueprintSelection }) {
  return (
    <div className="ek-stack" data-gap="1">
      <p className="ek-small">{blueprint.summary}</p>
      {blueprint.limitation ? <p className="ek-small ek-strong">{blueprint.limitation}</p> : null}
      <Disclosure summary="Se Blueprint-detaljer">
        <ul className="ek-small">{blueprint.details.map((d) => <li key={d}>{d}</li>)}</ul>
      </Disclosure>
    </div>
  );
}

function ScopeSummary({ inventory, courseId, scope, module }: {
  inventory: UseQueryResult<Inventory>;
  courseId: string;
  scope: Scope;
  module: InventoryModule | undefined;
}) {
  const capabilities = useCapabilities(courseId);
  if (inventory.isLoading) return <Spinner label="Leser innholdet fra Canvas …" />;
  if (inventory.error) return <LoadError query={inventory} what="innholdet" />;
  if (!inventory.data) return null;
  const { items, not_included: notIncluded, blueprint } = inventory.data;
  const place = scope === "module" ? "i modulen" : "i emnet";
  const counted = notIncluded.filter((x) => /\(\d+\)$/.test(x.label));
  const { ready, empty, excluded, locked, shared } = scopeFacts(items);
  const granted = (key: string) => capabilities.data?.capabilities?.find((c) => c.key === key)?.granted !== false;
  const blocked = ready.filter((i) => NEEDS[i.kind] && !granted(NEEDS[i.kind]!));
  const missing = (capabilities.data?.capabilities ?? []).filter((c) => (c.key === "pages" || c.key === "assignments") && !c.granted);
  const lockedNote = !locked ? ""
    : blueprint?.role === "blueprint" ? ` – inkludert ${locked} som er låst i de tilknyttede emnene`
      : ` – inkludert ${locked} som er låst fra Blueprint-emnet`;
  return (
    <section className="ek-stack" data-gap="2" aria-labelledby="omfang-berort">
      <h3 id="omfang-berort">Dette blir berørt</h3>
      {module ? (
        <p className="ek-small">
          <span className="ek-strong">{module.name}</span>
          {typeof module.total === "number"
            ? `: ${plural(module.total, "element", "elementer")} i modulen, ${ready.length ? `${ready.length} kan få design` : "ingen kan få design"}.`
            : ""}
        </p>
      ) : null}
      {ready.length === 0 ? (
        <Alert tone="info" title="Ikke noe som kan få design">
          {items.length === 0
            ? `Fant ingen sider, oppgaver eller klassiske quizer ${place} som Emnedesign kan formatere.`
            : `Innholdet ${place} er tomt eller beholder eget design.`}
          {counted.length ? ` Ikke med: ${list(counted.map((x) => x.label))}.` : ""}
        </Alert>
      ) : (
        <dl className="ek-scope-summary">
          <dt>Kan få design</dt>
          <dd>{plural(ready.length, "innholdselement", "innholdselementer")}{lockedNote}</dd>
          {empty || excluded ? (
            <>
              <dt>Hoppes over</dt>
              <dd>{list([empty ? plural(empty, "tomt element", "tomme elementer") : "",
                excluded ? `${excluded} som beholder eget design` : ""].filter(Boolean))}</dd>
            </>
          ) : null}
          {missing.length ? (
            <>
              <dt>Tilgang</dt>
              <dd>
                Du mangler tilgang i Canvas til å {list(missing.map((c) => c.label.toLowerCase()))}.{" "}
                {ready.length - blocked.length} av {ready.length} kan endres med dine rettigheter.
              </dd>
            </>
          ) : null}
          {counted.length ? (
            <>
              <dt>Ikke med</dt>
              <dd>{list(counted.map((x) => x.label))} – støttes ikke av Emnedesign</dd>
            </>
          ) : null}
        </dl>
      )}
      {capabilities.isLoading ? <p className="ek-xs ek-muted">Kontrollerer tilgangen din i Canvas …</p> : null}
      {capabilities.error ? <p className="ek-xs ek-muted">Tilgangen din i Canvas kunne ikke kontrolleres. Canvas avgjør ved publisering.</p> : null}
      {shared.length ? (
        <p className="ek-small">
          {plural(shared.length, "element brukes", "elementer brukes")} også i andre moduler ({list(shared.slice(0, 3).map((i) => `«${i.title}»`))}
          {shared.length > 3 ? " med flere" : ""}). Endringen gjelder det delte innholdet og blir synlig alle steder det brukes – det lages ingen kopier.
        </p>
      ) : null}
      {blueprint ? <BlueprintNote blueprint={blueprint} /> : null}
      {ready.length ? (
        <Disclosure summary="Se fordeling">
          <div className="ek-stack" data-gap="2">
            <table className="ek-table">
              <caption className="ek-visually-hidden">Innhold som kan få design, per innholdstype</caption>
              <tbody>
                {KIND_ORDER.filter((kind) => ready.some((i) => i.kind === kind)).map((kind) => (
                  <tr key={kind}><th scope="row">{KIND_LABEL[kind]}</th><td>{ready.filter((i) => i.kind === kind).length}</td></tr>
                ))}
                <tr><th scope="row">Til sammen</th><td>{ready.length}</td></tr>
              </tbody>
            </table>
            <p className="ek-xs ek-muted">
              Hvert innholdselement telles én gang, også når det brukes i flere moduler. Forsiden og modulintroduksjonene er sider,
              men telles ikke på nytt under «Andre sider».
            </p>
          </div>
        </Disclosure>
      ) : null}
    </section>
  );
}

/** Everything Emnedesign leaves alone, in one place. */
function NotChanged({ inventory }: { inventory: UseQueryResult<Inventory> }) {
  return (
    <Disclosure summary="Hva Emnedesign ikke endrer">
      <div className="ek-stack" data-gap="2">
        <p className="ek-small">
          Emnedesign formaterer støttet innhold du kan redigere i Canvas: sider, emneplanen, oppgavebeskrivelser og innledningen i
          klassiske quizer. Canvas' innebygde menyer, knapper og quizkontroller endres ikke.
        </p>
        {inventory.data ? (
          <ul className="ek-small">
            {inventory.data.not_included.map((x) => <li key={x.label}><span className="ek-strong">{x.label}:</span> {x.reason}</li>)}
          </ul>
        ) : null}
      </div>
    </Disclosure>
  );
}

/** Why «Neste» is not available yet (or null when it is). */
export function blockedReason(scope: Scope, moduleId: string, inventory: UseQueryResult<Inventory>): string | null {
  if (scope === "module" && !moduleId) return "Velg en modul først.";
  if (inventory.error) return "Innholdet må kunne leses før du går videre.";
  if (!inventory.data) return "Venter på innholdet fra Canvas …";
  if (!scopeFacts(inventory.data.items).ready.length) return "Det er ikke noe som kan få design i omfanget.";
  return null;
}

export function ScopeStep({ courseId, scope, setScope, moduleId, setModuleId, courseInventory, inventory, onNext }: {
  courseId: string;
  scope: Scope;
  setScope: (scope: Scope) => void;
  moduleId: string;
  setModuleId: (id: string) => void;
  courseInventory: UseQueryResult<Inventory>;
  inventory: UseQueryResult<Inventory>;
  onNext: () => void;
}) {
  const reasonId = useId();
  const noModules = courseInventory.data?.modules.length === 0;
  const valid = scope === "course" || Boolean(moduleId);
  const reason = blockedReason(scope, moduleId, inventory);
  const module = scope === "module" ? courseInventory.data?.modules.find((m) => m.id === moduleId) : undefined;
  return (
    <div className="ek-stack" data-gap="3">
      <Card title="Velg omfang">
        <div className="ek-stack" data-gap="4">
          <RadioGroup<Scope> legend="Hva skal få designet?" name="design-scope" variant="card" columns={2} value={scope} onChange={setScope}
            options={[
              { value: "course", label: "Hele emnet", hint: "Gi støttet innhold i emnet en felles designprofil.", icon: <LibraryBig />, tone: "info" },
              { value: "module", label: "Én modul", icon: <Layers />, tone: "violet", disabled: noModules,
                hint: noModules ? "Emnet har ingen moduler." : "Gi innholdet i en valgt modul en felles designprofil." },
            ]} />
          {scope === "module" ? <ModulePicker courseInventory={courseInventory} moduleId={moduleId} setModuleId={setModuleId} /> : null}
          {valid ? <ScopeSummary inventory={inventory} courseId={courseId} scope={scope} module={module} /> : null}
          <NotChanged inventory={inventory} />
        </div>
      </Card>
      <div className="ek-action-bar">
        {reason ? <span id={reasonId} className="ek-small ek-muted">{reason}</span> : null}
        <Button variant="primary" disabled={reason !== null} aria-describedby={reason ? reasonId : undefined} onClick={onNext}>
          Neste: velg design
        </Button>
      </div>
    </div>
  );
}
