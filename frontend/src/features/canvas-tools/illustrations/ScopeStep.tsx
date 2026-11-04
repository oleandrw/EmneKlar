// Step 1 – Velg omfang: whole course, one module, several modules or one page.
import { BookOpen, FileText, Layers, ListTree } from "lucide-react";

import { Alert, Card, Checkbox, Fieldset, RadioGroup, SelectField, Spinner } from "../../../design-system";
import type { Scope, ScopeIndex, ScopeType } from "./api";

export function ScopeStep({ scope, onChange, index, loading, error }: {
  scope: Scope;
  onChange: (scope: Scope) => void;
  index: ScopeIndex | undefined;
  loading: boolean;
  error: string | null;
}) {
  const set = (patch: Partial<Scope>) => onChange({ ...scope, ...patch });
  const modules = index?.modules ?? [];
  const pages = index?.pages ?? [];
  const toggleModule = (id: string, on: boolean) =>
    set({ module_ids: on ? [...scope.module_ids, id] : scope.module_ids.filter((m) => m !== id) });

  return (
    <Card title="1. Velg omfang" description="Hva skal KI-bildeassistenten arbeide med? Uansett valg leses emnets struktur, slik at bildene passer inn i helheten.">
      <div className="ek-stack" data-gap="6">
        <RadioGroup<ScopeType>
          legend="Omfang"
          name="illustration-scope"
          variant="card"
          columns={2}
          value={scope.type}
          onChange={(type) => set({ type, module_ids: type === "module" ? scope.module_ids.slice(0, 1) : scope.module_ids })}
          options={[
            { value: "course", label: "Hele emnet", icon: <BookOpen />, hint: "Én samlet bildeplan og én gjennomgående stil for alle moduler og sider." },
            { value: "module", label: "Én modul", icon: <Layers />, hint: "Modulens sider analyseres med modulens rolle i emnet som kontekst." },
            { value: "modules", label: "Flere moduler", icon: <ListTree />, hint: "Utvalgte moduler behandles som én oppgave med felles plan og stil." },
            { value: "page", label: "Én side", icon: <FileText />, hint: "Siden analyseres med modul- og emnekonteksten rundt." },
          ]}
        />
        {loading ? <Spinner label="Henter moduler og sider fra Canvas …" /> : null}
        {error ? <Alert tone="danger" title="Kunne ikke hente moduler og sider">{error}</Alert> : null}
        {scope.type === "module" && index ? (
          <SelectField
            label="Modul"
            value={scope.module_ids[0] ?? ""}
            onChange={(e) => set({ module_ids: e.target.value ? [e.target.value] : [] })}
            placeholder="Velg modul"
            options={modules.map((m) => ({ value: m.id, label: `${m.name} (${m.pages.length} sider)` }))}
          />
        ) : null}
        {scope.type === "modules" && index ? (
          <Fieldset legend="Moduler" hint="Velg modulene som skal behandles samlet.">
            <div className="ek-stack" data-gap="2">
              {modules.map((m) => (
                <Checkbox
                  key={m.id}
                  label={m.name}
                  hint={`${m.pages.length} sider${m.other_items ? `, ${m.other_items} andre elementer (brukes som kontekst)` : ""}${m.published ? "" : " – ikke publisert"}`}
                  checked={scope.module_ids.includes(m.id)}
                  onChange={(e) => toggleModule(m.id, e.target.checked)}
                />
              ))}
            </div>
          </Fieldset>
        ) : null}
        {scope.type === "page" && index ? (
          <SelectField
            label="Side"
            value={scope.page_url ?? ""}
            onChange={(e) => set({ page_url: e.target.value || null })}
            placeholder="Velg side"
            options={pages.map((p) => ({
              value: p.url,
              label: `${p.title}${p.published ? "" : " (ikke publisert)"}${p.in_module ? "" : " – utenfor moduler"}`,
            }))}
          />
        ) : null}
        <Fieldset legend="Valg" nested>
          <div className="ek-stack" data-gap="2">
            <Checkbox label="Ta med upubliserte sider" hint="Du ser dem som lærer; studentene ser dem ikke før de publiseres."
              checked={scope.include_unpublished} onChange={(e) => set({ include_unpublished: e.target.checked })} />
            {scope.type === "course" ? (
              <Checkbox label="Ta med sider som ikke ligger i en modul" checked={scope.include_outside_modules}
                onChange={(e) => set({ include_outside_modules: e.target.checked })} />
            ) : null}
            <Checkbox label="Bare nye eller endrede sider"
              hint="Ny kjøring: hopper over sider som allerede har illustrasjoner fra EmneKlar og ikke er endret siden. Eksisterende illustrasjoner gjenkjennes uansett, så det lages ikke dubletter."
              checked={scope.only_missing} onChange={(e) => set({ only_missing: e.target.checked })} />
          </div>
        </Fieldset>
        <p className="ek-small ek-muted">
          Bare Canvas-sider kan få illustrasjoner. Oppgaver, diskusjoner, quizer, filer og lenker i modulene brukes som kontekst.
          En side som ligger i flere moduler, behandles én gang.
        </p>
      </div>
    </Card>
  );
}

export function scopeReady(scope: Scope): boolean {
  if (scope.type === "module" || scope.type === "modules") return scope.module_ids.length > 0;
  if (scope.type === "page") return Boolean(scope.page_url);
  return true;
}
