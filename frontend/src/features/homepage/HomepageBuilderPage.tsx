import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code, FilePlus, Replace, Sparkles, WandSparkles } from "lucide-react";
import { useState } from "react";

import { AiConsent, AiNotConfigured, useAiConfigured, type AiPlan } from "../../core/ai";
import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ExternalLink,
  Fieldset,
  HtmlPreview,
  PageHeader,
  RadioGroup,
  Spinner,
  TextArea,
  TextField,
  useToast,
  type PreviewDevice,
} from "../../design-system";

type Mode = "design" | "design_content" | "improve";

interface Options {
  modes: { value: Mode; label: string }[];
  styles: { value: string; label: string; description: string; colors: { banner: string; accent: string; background: string } }[];
  sections: { value: string; label: string; description: string }[];
  default_sections: Record<Mode, string[]>;
}

interface Context {
  name: string;
  has_front_page: boolean;
  modules: number;
  upcoming_deadlines: number;
  has_syllabus: boolean;
  has_description: boolean;
}

interface Draft {
  id: number;
  mode: Mode;
  mode_label: string;
  style: string;
  style_label: string;
  sections: string[];
  preserve_existing: boolean;
  html: string;
  preview_html: string;
  notes: { section: string; kind: "placeholder" | "ai" | "stale" | "heuristic" | "replace"; message: string }[];
  warnings: string[];
  ai_used: boolean;
  created_at: string | null;
}

interface CreatedPage {
  change_id: number;
  title: string;
  url: string;
  html_url: string | null;
  applied_at: string | null;
}

const MODE_HINTS: Record<Mode, string> = {
  design: "En ferdig layout med tydelig merkede felt du fyller ut selv. Bruker bare emnenavnet fra Canvas.",
  design_content: "Layout med innhold hentet fra emnet: moduler, kommende frister og hurtiglenker. Ingenting blir funnet på.",
  improve: "Gir den nåværende forsiden et nytt design. Eksisterende innhold beholdes som standard.",
};
const NOTE_LABEL: Record<Draft["notes"][number]["kind"], { label: string; tone: "warning" | "violet" | "info" | "neutral" | "danger" }> = {
  placeholder: { label: "Fyll inn", tone: "warning" },
  ai: { label: "KI-forslag – må vurderes", tone: "violet" },
  stale: { label: "Oppdateres ikke automatisk", tone: "info" },
  heuristic: { label: "Kontroller", tone: "neutral" },
  replace: { label: "Erstatter innhold", tone: "danger" },
};

function DraftView({ draft, sectionLabel }: { draft: Draft; sectionLabel: (key: string) => string }) {
  const session = useSession();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [editing, setEditing] = useState(false);
  const [html, setHtml] = useState(draft.html);
  const [title, setTitle] = useState("Forside (utkast fra EmneKlar)");
  const [confirmReplace, setConfirmReplace] = useState(false);
  const save = useMutation({
    mutationFn: () => api.put<Draft>(`/api/homepage/drafts/${draft.id}`, { html }),
    onSuccess: (updated) => {
      void client.invalidateQueries({ queryKey: ["homepage-drafts"] });
      setHtml(updated.html);
      setEditing(false);
    },
  });
  const stage = useMutation({
    mutationFn: (action: "create_page" | "replace_front") => api.post(`/api/homepage/drafts/${draft.id}/stage`, { action, title }),
    onSuccess: (_, action) => {
      setConfirmReplace(false);
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({
        tone: "success",
        title: action === "create_page" ? "Ny side lagt i endringskøen" : "Erstatning av forsiden lagt i endringskøen",
        body: session.dry_run ? "Dry run er på – ingenting sendes til Canvas før du slår det av." : "Gjennomfør den fra endringskøen.",
      });
      ui.openChanges();
    },
  });
  const notes = draft.notes;

  return (
    <Card title="Utkast" eyebrow={`${draft.mode_label} · ${draft.style_label}`} headingLevel={2}>
      <div className="ek-stack" data-gap="6">
        {draft.warnings.length ? (
          <Alert tone="warning" title="Canvas ville endret noe av koden">
            <ul>{draft.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            Forhåndsvisningen viser innholdet slik Canvas lagrer det.
          </Alert>
        ) : null}
        {notes.length ? (
          <section className="ek-stack" data-gap="2" aria-labelledby="merknader">
            <h3 id="merknader">Dette må du se på</h3>
            <ul className="ek-list-reset ek-stack" data-gap="1">
              {notes.map((n, i) => (
                <li key={i} className="ek-cluster" data-gap="2">
                  <Badge tone={NOTE_LABEL[n.kind].tone}>{NOTE_LABEL[n.kind].label}</Badge>
                  <span className="ek-small">
                    {n.section ? <span className="ek-strong">{sectionLabel(n.section)}: </span> : null}
                    {n.message}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="ek-stack" data-gap="2">
          <div className="ek-cluster" role="group" aria-label="Visning">
            {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
              <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d}
                onClick={() => setDevice(d)}>
                {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
              </Button>
            ))}
            <Button size="sm" icon={<Code aria-hidden="true" />} aria-pressed={editing} onClick={() => setEditing((v) => !v)}>
              {editing ? "Skjul HTML" : "Forhåndsvis HTML"}
            </Button>
          </div>
          <HtmlPreview html={draft.preview_html} title="Forhåndsvisning av forsiden" device={device} minHeight={560} />
        </div>

        {editing ? (
          <div className="ek-stack" data-gap="2">
            <TextArea label="HTML" value={html} onChange={(e) => setHtml(e.target.value)} rows={14} spellCheck={false}
              hint="Du kan redigere koden. Det Canvas ikke tillater, fjernes når du lagrer – og vises som varsel over." />
            <div className="ek-cluster">
              <Button onClick={() => setHtml(draft.html)} disabled={html === draft.html}>Angre endringene</Button>
              <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={html === draft.html}>
                Lagre HTML
              </Button>
            </div>
            {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}
          </div>
        ) : null}

        <section className="ek-stack" aria-labelledby="publiser">
          <h3 id="publiser">Bruk utkastet</h3>
          <TextField label="Tittel på den nye siden" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} />
          <div className="ek-cluster">
            <Button variant="primary" icon={<FilePlus aria-hidden="true" />} onClick={() => stage.mutate("create_page")}
              loading={stage.isPending && stage.variables === "create_page"} disabled={!title.trim()}>
              Opprett som ny side
            </Button>
            <Button variant="danger" icon={<Replace aria-hidden="true" />} onClick={() => setConfirmReplace(true)}>
              Erstatt eksisterende forside
            </Button>
          </div>
          <p className="ek-xs ek-muted">
            «Opprett som ny side» er det trygge valget: siden opprettes upublisert, og den nåværende forsiden endres ikke.
          </p>
          {stage.error ? <Alert tone="danger" role="alert" title="Kunne ikke legge i kø">{(stage.error as Error).message}</Alert> : null}
        </section>
      </div>
      <ConfirmDialog
        open={confirmReplace}
        onClose={() => setConfirmReplace(false)}
        onConfirm={() => stage.mutate("replace_front")}
        title="Erstatte innholdet på forsiden?"
        confirmLabel="Legg erstatningen i kø"
        danger
        loading={stage.isPending}
      >
        <p>Innholdet på emnets forside erstattes med utkastet når du gjennomfører endringen fra endringskøen.</p>
        <p>Nåværende innhold sikkerhetskopieres først og kan gjenopprettes fra endringsloggen.</p>
      </ConfirmDialog>
    </Card>
  );
}

function CreatedPages({ courseId }: { courseId: string }) {
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const created = useQuery({
    queryKey: ["homepage-created", courseId],
    queryFn: () => api.get<{ items: CreatedPage[] }>(`/api/courses/${courseId}/homepage/created`),
  });
  const use = useMutation({
    mutationFn: (url: string) => api.post(`/api/courses/${courseId}/homepage/use-as-front`, { url }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({ tone: "success", title: "«Bruk som forside» er lagt i endringskøen" });
      ui.openChanges();
    },
  });
  if (!created.data?.items.length) return null;
  return (
    <Card title="Sider laget fra utkast" headingLevel={2}>
      <ul className="ek-list-reset ek-divider-list">
        {created.data.items.map((page) => (
          <li key={page.change_id} className="ek-row">
            <div className="ek-row__main">
              {page.html_url ? <ExternalLink href={page.html_url}>{page.title}</ExternalLink> : <span>{page.title}</span>}
              <span className="ek-xs ek-muted">Opprettet {formatDateTime(page.applied_at)}</span>
            </div>
            <Button size="sm" onClick={() => use.mutate(page.url)} loading={use.isPending && use.variables === page.url}>
              Bruk som forside<span className="ek-visually-hidden">: {page.title}</span>
            </Button>
          </li>
        ))}
      </ul>
      {use.error ? <Alert tone="danger" role="alert">{(use.error as Error).message}</Alert> : null}
      <p className="ek-xs ek-muted ek-mt-2">«Bruk som forside» publiserer siden og gjør den til startsiden i emnet.</p>
    </Card>
  );
}

export function HomepageBuilderPage() {
  usePageTitle("Emneforside");
  const session = useSession();
  const { courseId } = useCurrentCourse();
  const aiConfigured = useAiConfigured();
  const client = useQueryClient();
  const options = useQuery({ queryKey: ["homepage-options"], queryFn: () => api.get<Options>("/api/homepage/options"), staleTime: Infinity });
  const context = useQuery({
    queryKey: ["homepage-context", courseId],
    queryFn: () => api.get<Context>(`/api/courses/${courseId}/homepage/context`),
    enabled: Boolean(courseId),
  });
  const drafts = useQuery({
    queryKey: ["homepage-drafts", courseId],
    queryFn: () => api.get<{ items: Draft[] }>(`/api/courses/${courseId}/homepage/drafts`),
    enabled: Boolean(courseId),
  });
  const [mode, setMode] = useState<Mode>("design_content");
  const [style, setStyle] = useState("academic");
  const [sections, setSections] = useState<string[] | null>(null);
  const [preserve, setPreserve] = useState(true);
  const [useAi, setUseAi] = useState(false);
  const [plan, setPlan] = useState<AiPlan | null>(null);
  const [draftId, setDraftId] = useState<number | null>(null);
  const [latest, setLatest] = useState<Draft | null>(null);

  const chosen = sections ?? options.data?.default_sections[mode] ?? [];
  const body = { mode, style, sections: chosen, preserve_existing: preserve, use_ai: useAi && mode !== "design" };
  const generate = useMutation({
    mutationFn: (confirmed: boolean) => api.post<Draft>(`/api/courses/${courseId}/homepage/drafts`, { ...body, confirmed }),
    onSuccess: (draft) => {
      setPlan(null);
      setLatest(draft);
      void client.invalidateQueries({ queryKey: ["homepage-drafts"] });
      setDraftId(draft.id);
    },
  });
  const prepare = useMutation({
    mutationFn: () => api.post<AiPlan>(`/api/courses/${courseId}/homepage/prepare-ai`, body),
    onSuccess: setPlan,
  });

  if (session.flags.homepage_builder === false) {
    return (
      <>
        <PageHeader title="Emneforside" />
        <Alert tone="info" title="Emneforside er slått av">Funksjonen kan slås på under Innstillinger → Avanserte innstillinger.</Alert>
      </>
    );
  }
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (options.isPending || context.isPending) return <Spinner label="Henter emnet …" />;
  if (options.error || context.error) {
    return <Alert tone="danger" role="alert" title="Kunne ikke hente emnet">{((options.error ?? context.error) as Error).message}</Alert>;
  }
  const ctx = context.data;
  const draft = drafts.data?.items.find((d) => d.id === draftId) ?? (latest?.id === draftId ? latest : null);
  const sectionLabel = (key: string) => options.data.sections.find((s) => s.value === key)?.label ?? key;

  return (
    <>
      <PageHeader
        title="Emneforside"
        description="Lag en ny forside eller gi den nåværende et løft. Alt forhåndsvises, og ingenting endres i Canvas før du godkjenner det."
      />
      <div className="ek-stack" data-gap="6">
        <Card title="1. Utgangspunkt" headingLevel={2}>
          <div className="ek-stack">
            <RadioGroup
              legend="Hva vil du lage?"
              hideLegend
              name="mode"
              variant="card"
              value={mode}
              onChange={(value) => {
                setMode(value);
                setSections(null);
              }}
              options={options.data.modes.map((m) => ({
                value: m.value, label: m.label,
                hint: m.value === "improve" && !ctx.has_front_page ? "Emnet har ingen forside å forbedre." : MODE_HINTS[m.value],
                disabled: m.value === "improve" && !ctx.has_front_page,
              }))}
            />
            {mode === "improve" ? (
              <Checkbox label="Bevar eksisterende innhold" checked={preserve} onChange={(e) => setPreserve(e.target.checked)}
                hint="Anbefalt. Teksten på forsiden beholdes uendret og får det nye designet rundt seg." />
            ) : null}
            {mode !== "design" ? (
              <p className="ek-xs ek-muted">
                Fra emnet: {ctx.modules} moduler, {ctx.upcoming_deadlines} kommende frister
                {ctx.has_syllabus ? ", emneplan" : ""}{ctx.has_description ? ", emnebeskrivelse" : ""}.
              </p>
            ) : null}
          </div>
        </Card>

        <Card title="2. Stil" headingLevel={2}>
          <RadioGroup
            legend="Visuell stil"
            hideLegend
            name="style"
            variant="card"
            value={style}
            onChange={setStyle}
            options={options.data.styles.map((s) => ({
              value: s.value,
              label: (
                <span className="ek-cluster" data-gap="2">
                  <span className="ek-swatches" aria-hidden="true">
                    <span className="ek-swatch" style={{ background: s.colors.banner }} />
                    <span className="ek-swatch" style={{ background: s.colors.accent }} />
                    <span className="ek-swatch" style={{ background: s.colors.background }} />
                  </span>
                  {s.label}
                </span>
              ),
              hint: s.description,
            }))}
          />
        </Card>

        <Card title="3. Innhold" headingLevel={2}>
          <div className="ek-stack">
            <Fieldset legend="Seksjoner" hint="Seksjonene kommer i denne rekkefølgen. Innhold EmneKlar ikke kan vite, merkes «Fyll inn».">
              {options.data.sections.map((s) => (
                <Checkbox key={s.value} label={s.label} hint={s.description} checked={chosen.includes(s.value)}
                  onChange={(e) => setSections(e.target.checked ? [...chosen, s.value] : chosen.filter((x) => x !== s.value))} />
              ))}
            </Fieldset>
            {mode !== "design" ? (
              aiConfigured ? (
                <Checkbox label="Foreslå velkomsttekst og beskrivelse med KI" checked={useAi} onChange={(e) => setUseAi(e.target.checked)}
                  hint="Teksten bygger bare på emnenavn, modulnavn og emneplanen, og merkes «KI-forslag – må vurderes»." />
              ) : (
                <AiNotConfigured what="Tekstforslag med KI" />
              )
            ) : null}
            <div className="ek-cluster">
              <Button
                variant="primary"
                icon={body.use_ai ? <Sparkles aria-hidden="true" /> : <WandSparkles aria-hidden="true" />}
                onClick={() => (body.use_ai ? prepare.mutate() : generate.mutate(false))}
                loading={generate.isPending || prepare.isPending}
                disabled={chosen.length === 0}
              >
                Generer utkast
              </Button>
            </div>
            {plan ? (
              <AiConsent plan={plan} onCancel={() => setPlan(null)} onConfirm={() => generate.mutate(true)}
                loading={generate.isPending} confirmLabel="Send og lag utkast" />
            ) : null}
            {generate.error || prepare.error ? (
              <Alert tone="danger" role="alert" title="Kunne ikke lage utkastet">{((generate.error ?? prepare.error) as Error).message}</Alert>
            ) : null}
          </div>
        </Card>

        {draft ? <DraftView key={`${draft.id}-${draft.html.length}`} draft={draft} sectionLabel={sectionLabel} /> : null}

        {drafts.data && drafts.data.items.length > 0 ? (
          <Card title="Tidligere utkast" headingLevel={2}>
            <ul className="ek-list-reset ek-divider-list">
              {drafts.data.items.map((d) => (
                <li key={d.id} className="ek-row">
                  <div className="ek-row__main">
                    <span>{d.mode_label} · {d.style_label}</span>
                    <span className="ek-xs ek-muted">{formatDateTime(d.created_at)}{d.ai_used ? " · med KI-forslag" : ""}</span>
                  </div>
                  <Button size="sm" onClick={() => setDraftId(d.id)} aria-pressed={d.id === draftId}>
                    Vis<span className="ek-visually-hidden"> utkast fra {formatDateTime(d.created_at)}</span>
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        <CreatedPages courseId={courseId} />
      </div>
    </>
  );
}
