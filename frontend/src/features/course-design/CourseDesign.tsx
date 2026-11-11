// Emnedesign: give the whole course or one module one consistent design.
// Omfang → Design → Forhåndsvisning → Godkjenning (horizontal steps; a step can only be reached after the ones before).
// Nothing is published from here: approved proposals go to the change queue («Publiser til Canvas» – conflict check,
// backup, change log, undo).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, Eye, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { AiBadge, AiConsent, type AiPlan } from "../../core/ai";
import { useCurrentCourse } from "../../core/course";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import { usePageTitle } from "../../core/usePageTitle";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  HtmlPreview,
  PageHeader,
  RadioGroup,
  Spinner,
  Stepper,
  useToast,
  type PreviewDevice,
} from "../../design-system";
import {
  previewItems,
  useDesignProfiles,
  useInventory,
  useSavedDesign,
  type ApproveResult,
  type DesignMode,
  type InventoryItem,
  type PreviewItem,
  type StructurePlan,
} from "./api";
import { ScopeStep, type Scope } from "./ScopeStep";

type Step = "omfang" | "design" | "forhandsvis" | "godkjenn";
const ORDER: Step[] = ["omfang", "design", "forhandsvis", "godkjenn"];

const MODE_OPTIONS: { value: DesignMode; label: string; hint: string }[] = [
  { value: "keep", label: "Behold oppbyggingen (standard)",
    hint: "Gir innholdet valgt stil. Tekst, rekkefølge, seksjoner og formatering med mening beholdes – ingenting skrives om." },
  { value: "structure", label: "Foreslå bedre oppbygging",
    hint: "KI foreslår seksjoner og plassering av eksisterende innhold, side for side. Du ser hver endring før du godkjenner. Det skrives ikke nytt innhold." },
];

function DeviceToggle({ device, onChange }: { device: PreviewDevice; onChange: (d: PreviewDevice) => void }) {
  return (
    <div className="ek-cluster" role="group" aria-label="Visning">
      {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
        <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d} onClick={() => onChange(d)}>
          {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
        </Button>
      ))}
    </div>
  );
}

function status(item: InventoryItem, preview: PreviewItem | undefined, profileRef: string): { label: string; tone: "success" | "warning" | "danger" | "neutral" | "info" } {
  if (item.excluded) return { label: "Beholder eget design", tone: "neutral" };
  if (item.empty) return { label: "Tomt – hoppes over", tone: "neutral" };
  if (!preview) return item.design === profileRef ? { label: "Har dette designet", tone: "neutral" } : { label: "Ikke forhåndsvist", tone: "info" };
  if (preview.error) return { label: "Kunne ikke leses", tone: "danger" };
  if (preview.problems?.length) return { label: "Stoppet", tone: "danger" };
  if (preview.unchanged) return { label: "Har allerede dette designet", tone: "neutral" };
  return { label: preview.structured ? "Klar – ny oppbygging" : "Klar", tone: "success" };
}

const HEADER = (
  <PageHeader title="Emnedesign"
    description="Gi emnet eller en modul et gjennomført design. Se og godkjenn endringene før de sendes til Canvas." />
);

/** The «Emnedesign» page in the main menu. */
export function CourseDesignPage() {
  usePageTitle("Emnedesign");
  const session = useSession();
  if (session.flags.course_design === false) {
    return (
      <>
        {HEADER}
        <Alert tone="info" title="Emnedesign er slått av">Funksjonen kan slås på under Innstillinger → Avanserte innstillinger.</Alert>
      </>
    );
  }
  return <CourseDesign />;
}

export function CourseDesign() {
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const profiles = useDesignProfiles();
  const saved = useSavedDesign(courseId);
  const [step, setStepState] = useState<Step>("omfang");
  // The furthest step reached: the steps after it cannot be skipped to.
  const [reached, setReached] = useState(0);
  const setStep = (next: Step) => {
    setStepState(next);
    setReached((r) => Math.max(r, ORDER.indexOf(next)));
  };
  const [scope, setScope] = useState<Scope>("course");
  const [moduleId, setModuleId] = useState<string>("");
  const [profileId, setProfileId] = useState<string>("");
  const [mode, setMode] = useState<DesignMode>("keep");
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [selected, setSelected] = useState<string[] | null>(null);
  const [previews, setPreviews] = useState<Record<string, PreviewItem>>({});
  const [plans, setPlans] = useState<Record<string, StructurePlan>>({});
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [aiPlan, setAiPlan] = useState<{ key: string; plan: AiPlan } | null>(null);
  const [results, setResults] = useState<ApproveResult[] | null>(null);

  const courseInventory = useInventory(courseId, null, true);
  const inventory = useInventory(courseId, scope === "module" ? moduleId || null : null, scope === "course" || Boolean(moduleId));
  const items = useMemo(() => inventory.data?.items ?? [], [inventory.data]);
  const profile = profiles.data?.profiles.find((p) => p.id === profileId) ?? profiles.data?.profiles.find((p) => p.default);
  const profileRef = profile ? `${profile.id}@${profile.version}` : "";

  useEffect(() => {
    if (!profileId && (saved.data || profiles.data)) {
      setProfileId(saved.data?.design?.profile_id ?? profiles.data?.default ?? "");
      if (saved.data?.design?.mode) setMode(saved.data.design.mode);
    }
  }, [saved.data, profiles.data, profileId]);
  // A new scope or design starts a new preview – nothing from the earlier choice is shown for the new one.
  useEffect(() => {
    setSelected(null);
    setPreviews({});
    setResults(null);
    setOpenKey(null);
  }, [scope, moduleId, profileId, mode]);
  // Another course: start again from the scope (its modules and content are different).
  useEffect(() => {
    setModuleId("");
    setPlans({});
    setAiPlan(null);
    setStepState("omfang");
    setReached(0);
  }, [courseId]);

  const chosen = selected ?? items.filter((i) => !i.excluded && !i.empty && i.design !== profileRef).map((i) => i.key);
  const chosenItems = items.filter((i) => chosen.includes(i.key));
  const ready = chosenItems.filter((i) => {
    const p = previews[i.key];
    return p && !p.error && !p.problems?.length && !p.unchanged;
  });

  const runPreview = useMutation({
    mutationFn: (list: InventoryItem[]) => previewItems(courseId!, profile!.id, list, mode === "structure" ? plans : {}),
    onSuccess: (list) => setPreviews((cur) => ({ ...cur, ...Object.fromEntries(list.map((p) => [p.key, p])) })),
  });
  const saveDesign = useMutation({
    mutationFn: () => api.put(`/api/courses/${courseId}/course-design`, { profile_id: profile!.id, mode }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["course-design", courseId, "saved"] });
      toast.show({ tone: "success", title: `«${profile!.label}» er lagret som emnets design`, body: "Ingen innhold er endret." });
    },
  });
  const exclude = useMutation({
    mutationFn: ({ key, excluded }: { key: string; excluded: boolean }) =>
      api.put(`/api/courses/${courseId}/course-design/items/${encodeURIComponent(key)}/exclusion`, { excluded }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["course-design", courseId, "inventory"] }),
  });
  const prepare = useMutation({
    mutationFn: (item: InventoryItem) =>
      api.post<AiPlan>(`/api/courses/${courseId}/course-design/structure/prepare`, { item: item.key, title: item.title }),
    onSuccess: (plan, item) => setAiPlan({ key: item.key, plan }),
  });
  const suggest = useMutation({
    mutationFn: (item: InventoryItem) =>
      api.post<{ plan: StructurePlan; note: string }>(`/api/courses/${courseId}/course-design/structure`, {
        item: item.key, title: item.title, confirmed: true,
      }),
    onSuccess: async (result, item) => {
      setAiPlan(null);
      const next = { ...plans, [item.key]: result.plan };
      setPlans(next);
      const [fresh] = await previewItems(courseId!, profile!.id, [item], next);
      setPreviews((cur) => ({ ...cur, [item.key]: fresh }));
      toast.show({ tone: "info", title: "Forslag til oppbygging er klart", body: result.note || "Se endringene før du godkjenner." });
    },
  });
  const approve = useMutation({
    mutationFn: (list: InventoryItem[]) =>
      api.post<{ results: ApproveResult[] }>(`/api/courses/${courseId}/course-design/approve`, {
        profile_id: profile!.id,
        items: list.map((i) => ({ key: i.key, content_hash: previews[i.key]?.content_hash ?? "", kind: i.kind, title: i.title,
          plan: mode === "structure" ? plans[i.key] ?? null : null })),
      }),
    onSuccess: (r) => {
      setResults(r.results);
      void client.invalidateQueries({ queryKey: ["changes"] });
    },
  });

  if (!courseId) return <>{HEADER}<EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState></>;

  const scopeValid = scope === "course" || Boolean(moduleId);
  const at = ORDER.indexOf(step);
  const steps = [
    { id: "omfang" as Step, label: "Omfang", done: at > 0 },
    { id: "design" as Step, label: "Design", done: at > 1, disabled: !scopeValid },
    { id: "forhandsvis" as Step, label: "Forhåndsvisning", done: at > 2, disabled: !scopeValid || reached < 1 || !profile },
    { id: "godkjenn" as Step, label: "Godkjenning", disabled: ready.length === 0 },
  ];
  const back = (to: Step, label: string) => (
    <Button variant="ghost" icon={<ArrowLeft aria-hidden="true" />} onClick={() => setStep(to)}>Tilbake: {label}</Button>
  );
  const open = items.find((i) => i.key === openKey) ?? null;
  const openPreview = open ? previews[open.key] : undefined;
  const toggle = (key: string, on: boolean) => setSelected(on ? [...chosen, key] : chosen.filter((k) => k !== key));

  return (
    <>
      {HEADER}
      <div className="ek-stack" data-gap="5">
        <Stepper label="Steg i Emnedesign" orientation="horizontal" steps={steps} current={step} onSelect={setStep} />
        <div className="ek-stack" data-gap="4">
          {step === "omfang" ? (
            <ScopeStep courseId={courseId} scope={scope} setScope={setScope} moduleId={moduleId} setModuleId={setModuleId}
              courseInventory={courseInventory} inventory={inventory}
              sample={profiles.data?.profiles.find((p) => p.default)} onNext={() => setStep("design")} />
          ) : null}

          {step === "design" ? (
            <Card title="Velg design"
              description="Designet brukes likt på alt innhold i omfanget: farger, typografi, avstander og informasjonsfelt. Oppsettet tilpasses innholdstypen.">
              {profiles.isPending ? <Spinner label="Henter designprofiler …" /> : null}
              {profiles.data && profile ? (
                <div className="ek-stack" data-gap="5">
                  <RadioGroup legend="Design" name="design-profile" variant="card" columns={2} value={profile.id} onChange={setProfileId}
                    options={profiles.data.profiles.map((p) => ({ value: p.id, label: p.default ? `${p.label} (standard)` : p.label, hint: p.description }))} />
                  <RadioGroup<DesignMode> legend="Oppbygging" name="design-mode" value={mode} onChange={setMode} options={MODE_OPTIONS}
                    hint="Velg om sidene skal beholde oppbyggingen de har, eller få forslag til en bedre oppbygging med det innholdet som finnes." />
                  {mode === "structure" ? (
                    <Alert tone="info" title="Slik virker «Foreslå bedre oppbygging»">
                      For hver side ber du om et forslag. KI-en ser bare korte utdrag av innholdet, foreslår seksjoner (for eksempel
                      introduksjon, læringsmål, fagstoff, eksempler og aktiviteter) og plassering av det som finnes. Den finner ikke på
                      læringsmål, vurderingskriterier eller annet faglig innhold, og omskriver ingenting. Sider uten forslag får bare stilen.
                    </Alert>
                  ) : null}
                  <div className="ek-stack" data-gap="2">
                    <h3>Forhåndsvisning med eksempelinnhold</h3>
                    <DeviceToggle device={device} onChange={setDevice} />
                    <HtmlPreview html={mode === "structure" ? profile.sample_structure : profile.sample_keep}
                      title={`Eksempelinnhold med designet ${profile.label}`} device={device} minHeight={520} />
                  </div>
                  <p className="ek-small ek-muted">
                    Illustrasjoner er et valgfritt tillegg – alle designene fungerer uten bilder. Vil du ha illustrasjoner i samme stil, lag dem
                    med <Link to="/canvas-verktoy/bildeassistent">KI-bildeassistenten</Link>, som setter dem inn med alternativ tekst etter godkjenning (med mindre du velger «Automatisk innsetting»).
                  </p>
                  <div className="ek-cluster" data-justify="between">
                    <div className="ek-cluster">
                      {back("omfang", "omfang")}
                      <Button onClick={() => saveDesign.mutate()} loading={saveDesign.isPending}>Lagre som emnets design</Button>
                    </div>
                    <Button variant="primary" onClick={() => setStep("forhandsvis")}>Neste: forhåndsvis</Button>
                  </div>
                  {saved.data?.design ? (
                    <p className="ek-xs ek-muted">
                      Emnets design nå: {profiles.data.profiles.find((p) => p.id === saved.data?.design?.profile_id)?.label ?? saved.data.design.profile_id}{" "}
                      (versjon {saved.data.design.profile_version}). Å lagre designvalget endrer ikke innhold.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </Card>
          ) : null}

          {step === "forhandsvis" ? (
            <Card title="Forhåndsvis" description="Velg hva som skal få designet, og se før og etter. Innholdet leses fra Canvas; ingenting endres her.">
              <div className="ek-stack" data-gap="4">
                {inventory.isLoading ? <Spinner label="Leser innholdet fra Canvas …" /> : null}
                {inventory.error ? (
                  <Alert tone="danger" role="alert" title="Kunne ikke lese innholdet">
                    <p>{(inventory.error as Error).message}</p>
                    <Button size="sm" onClick={() => void inventory.refetch()} loading={inventory.isFetching}>Prøv igjen</Button>
                  </Alert>
                ) : null}
                {inventory.error ? <div>{back("design", "design")}</div> : null}
                {inventory.data?.blueprint ? (
                  <Alert tone="info" title="Blueprint">
                    {inventory.data.blueprint.summary}
                    {inventory.data.blueprint.limitation ? <> {inventory.data.blueprint.limitation}</> : null}
                  </Alert>
                ) : null}
                {inventory.data ? (
                  <>
                    <ul className="ek-list-reset ek-stack" data-gap="2" aria-label="Innhold i omfanget">
                      {items.map((item) => {
                        const s = status(item, previews[item.key], profileRef);
                        const preview = previews[item.key];
                        return (
                          <li key={item.key} className="ek-card ek-card--compact">
                            <div className="ek-stack" data-gap="2">
                              <div className="ek-cluster" data-justify="between">
                                <Checkbox label={<><span className="ek-strong">{item.title}</span> <span className="ek-small ek-muted">· {item.kind_label}</span></>}
                                  checked={chosen.includes(item.key)} disabled={item.excluded || item.empty}
                                  onChange={(e) => toggle(item.key, e.target.checked)} />
                                <Badge tone={s.tone}>{s.label}</Badge>
                              </div>
                              {item.modules.length ? (
                                <p className="ek-xs ek-muted">
                                  {item.shared ? `Brukt i ${item.modules.length} moduler (${item.modules.join(", ")}). Endringen gjelder det delte innholdet overalt – det lages ingen kopier.`
                                    : `Modul: ${item.modules[0]}`}
                                </p>
                              ) : null}
                              {item.locked ? (
                                <p className="ek-xs ek-muted">
                                  {inventory.data?.blueprint?.role === "blueprint"
                                    ? "Låst i de tilknyttede emnene: synkroniseringen erstatter innholdet der."
                                    : "Låst fra Blueprint-emnet. Canvas avgjør ved publisering om endringen kan lagres her; hvis ikke kan den flyttes til Blueprint-emnet fra endringskøen."}
                                </p>
                              ) : null}
                              {item.design && item.design !== profileRef ? <p className="ek-xs ek-muted">Har et annet emnedesign ({item.design.split("@")[0]}). Det erstattes – ikke legges oppå.</p> : null}
                              {preview?.problems?.length ? (
                                <p className="ek-xs ek-error" role="alert"><CircleAlert aria-hidden="true" size={14} /> Stoppet: designet ville endret {preview.problems.join(", ")}.</p>
                              ) : null}
                              {preview?.error ? <p className="ek-xs ek-error" role="alert">{preview.error}</p> : null}
                              <div className="ek-cluster" data-gap="2">
                                {preview && !preview.error ? (
                                  <Button size="sm" icon={<Eye aria-hidden="true" />} aria-pressed={openKey === item.key}
                                    onClick={() => setOpenKey(openKey === item.key ? null : item.key)}>
                                    {openKey === item.key ? "Skjul før og etter" : "Vis før og etter"}
                                  </Button>
                                ) : null}
                                {mode === "structure" && !item.excluded && !item.empty ? (
                                  <Button size="sm" icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate(item)}
                                    loading={(prepare.isPending && prepare.variables?.key === item.key) || (suggest.isPending && suggest.variables?.key === item.key)}>
                                    {plans[item.key] ? "Foreslå på nytt" : "Foreslå oppbygging"}
                                  </Button>
                                ) : null}
                                {plans[item.key] ? (
                                  <Button size="sm" variant="ghost" onClick={async () => {
                                    const rest = { ...plans };
                                    delete rest[item.key];
                                    setPlans(rest);
                                    const [fresh] = await previewItems(courseId, profile!.id, [item], {});
                                    setPreviews((cur) => ({ ...cur, [item.key]: fresh }));
                                  }}>Bruk bare stilen</Button>
                                ) : null}
                                <Button size="sm" variant="ghost" loading={exclude.isPending && exclude.variables?.key === item.key}
                                  onClick={() => exclude.mutate({ key: item.key, excluded: !item.excluded })}>
                                  {item.excluded ? "Bruk emnets design" : "Behold eksisterende design"}
                                </Button>
                              </div>
                              {aiPlan?.key === item.key ? (
                                <AiConsent plan={aiPlan.plan} onCancel={() => setAiPlan(null)} onConfirm={() => suggest.mutate(item)}
                                  loading={suggest.isPending} confirmLabel="Foreslå oppbygging" />
                              ) : null}
                              {suggest.error && suggest.variables?.key === item.key ? <Alert tone="danger" role="alert">{(suggest.error as Error).message}</Alert> : null}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                    {items.length === 0 ? <p className="ek-muted">Fant ikke innhold EmneKlar kan formatere i omfanget.</p> : null}
                    <div className="ek-cluster" data-justify="between">
                      <div className="ek-cluster">
                        {back("design", "design")}
                        <Button variant="primary" disabled={chosenItems.length === 0} loading={runPreview.isPending}
                          onClick={() => runPreview.mutate(chosenItems)}>
                          Lag forhåndsvisning ({chosenItems.length})
                        </Button>
                      </div>
                      <Button onClick={() => setStep("godkjenn")} disabled={ready.length === 0}>Neste: godkjenn</Button>
                    </div>
                    {runPreview.error ? <Alert tone="danger" role="alert">{(runPreview.error as Error).message}</Alert> : null}
                  </>
                ) : null}
                {open && openPreview?.before !== undefined ? (
                  <section className="ek-stack" data-gap="3" aria-labelledby="for-og-etter">
                    <h3 id="for-og-etter">Før og etter: {open.title}</h3>
                    <DeviceToggle device={device} onChange={setDevice} />
                    {openPreview.structured ? <AiBadge /> : null}
                    {openPreview.structure_changes?.length ? (
                      <Alert tone="warning" title="Endret oppbygging">
                        <ul className="ek-small">{openPreview.structure_changes.map((c) => <li key={c}>{c}</li>)}</ul>
                      </Alert>
                    ) : (
                      <p className="ek-small">Bare stilendringer: tekst, rekkefølge og seksjoner er som før.</p>
                    )}
                    {openPreview.notes?.length ? <ul className="ek-small">{openPreview.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
                    <div className="ek-grid" data-cols="2">
                      <div className="ek-stack" data-gap="1">
                        <h4>Før</h4>
                        <HtmlPreview html={openPreview.before} title={`Før: ${open.title}`} device={device} minHeight={480} />
                      </div>
                      <div className="ek-stack" data-gap="1">
                        <h4>Etter</h4>
                        <HtmlPreview html={openPreview.after ?? ""} title={`Etter: ${open.title}`} device={device} minHeight={480} />
                      </div>
                    </div>
                  </section>
                ) : null}
              </div>
            </Card>
          ) : null}

          {step === "godkjenn" ? (
            <Card title="Godkjenn til endringskøen"
              description="Forslagene legges godkjent i endringskøen. Ingenting sendes før du velger «Publiser til Canvas». Innholdet kontrolleres mot Canvas og sikkerhetskopieres før endringen, og kan angres fra endringsloggen.">
              <div className="ek-stack" data-gap="4">
                <ul className="ek-small">
                  <li>{ready.filter((i) => !plans[i.key]).length} med bare stilendringer</li>
                  <li>{ready.filter((i) => plans[i.key]).length} med ny oppbygging (KI-forslag – må vurderes)</li>
                  <li>{chosenItems.length - ready.length} valgte er ikke med (ikke forhåndsvist, stoppet eller har allerede designet)</li>
                </ul>
                <p className="ek-small ek-muted">Frister, poeng, fasit, vurderingsregler, innleveringsinnstillinger og lenkemål endres ikke – bare innholdsteksten får designet.</p>
                <div className="ek-cluster">
                  {back("forhandsvis", "forhåndsvisning")}
                  <Button variant="primary" disabled={ready.length === 0} loading={approve.isPending} onClick={() => approve.mutate(ready)}>
                    Godkjenn {ready.length} forslag til endringskøen
                  </Button>
                  <Button onClick={ui.openChanges}>Åpne endringskøen</Button>
                </div>
                {approve.error ? <Alert tone="danger" role="alert">{(approve.error as Error).message}</Alert> : null}
                {results ? (
                  <Alert tone={results.every((r) => r.status === "approved" || r.status === "unchanged") ? "success" : "warning"} role="status"
                    title={`${results.filter((r) => r.status === "approved").length} forslag er godkjent i endringskøen`}>
                    <ul className="ek-small">
                      {results.filter((r) => r.status !== "approved").map((r) => (
                        <li key={r.key}>{items.find((i) => i.key === r.key)?.title ?? r.key}: {r.message}</li>
                      ))}
                    </ul>
                    {results.some((r) => r.status === "changed") ? (
                      <Button size="sm" onClick={() => setStep("forhandsvis")}>Forhåndsvis på nytt</Button>
                    ) : null}
                  </Alert>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}
