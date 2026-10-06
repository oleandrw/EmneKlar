// «Lag ny quiz»: build a Classic Quiz from approved bank questions. Created unpublished by default, via the change queue.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, ListPlus, Save, Star } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Fieldset,
  KeyValue,
  SelectField,
  Spinner,
  TextArea,
  TextField,
  useToast,
} from "../../design-system";
import {
  QUIZ_TYPES,
  useBank,
  usePresets,
  useQuizzes,
  type BuildPreview,
  type BuildRequest,
  type Preset,
  type QuizSettings,
} from "./api";

const DEFAULT_SETTINGS: QuizSettings = {
  quiz_type: "practice_quiz", time_limit: null, shuffle_answers: true, allowed_attempts: 1, scoring_policy: "keep_highest",
  show_correct_answers: true, show_correct_answers_last_attempt: false, hide_results: null, one_question_at_a_time: false,
  cant_go_back: false, due_at: null, unlock_at: null, lock_at: null, published: false,
};

/** ISO (UTC) → value for <input type="datetime-local"> in local time. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function SettingsForm({ settings, onChange }: { settings: QuizSettings; onChange: (s: QuizSettings) => void }) {
  const set = <K extends keyof QuizSettings>(key: K, value: QuizSettings[K]) => onChange({ ...settings, [key]: value });
  const multiple = settings.allowed_attempts !== 1;
  return (
    <div className="ek-stack">
      <div className="ek-grid" data-cols="2">
        <SelectField label="Quiztype" value={settings.quiz_type} options={QUIZ_TYPES}
          onChange={(e) => set("quiz_type", e.target.value as QuizSettings["quiz_type"])} />
        <SelectField label="Antall forsøk" value={String(settings.allowed_attempts)}
          onChange={(e) => set("allowed_attempts", Number(e.target.value))}
          options={[
            { value: "1", label: "1 forsøk" }, { value: "2", label: "2 forsøk" }, { value: "3", label: "3 forsøk" },
            { value: "5", label: "5 forsøk" }, { value: "10", label: "10 forsøk" }, { value: "-1", label: "Ubegrenset" },
          ]} />
        {multiple ? (
          <SelectField label="Poengregel" value={settings.scoring_policy}
            onChange={(e) => set("scoring_policy", e.target.value as QuizSettings["scoring_policy"])}
            options={[{ value: "keep_highest", label: "Beste forsøk teller" }, { value: "keep_latest", label: "Siste forsøk teller" }]} />
        ) : null}
        <TextField label="Tidsbegrensning (minutter)" type="number" min={1} max={600} optional
          value={settings.time_limit ?? ""} hint="La feltet stå tomt for ingen tidsbegrensning."
          onChange={(e) => set("time_limit", e.target.value ? Number(e.target.value) : null)} />
        <SelectField label="Resultater for studentene" value={settings.hide_results ?? ""}
          onChange={(e) => set("hide_results", (e.target.value || null) as QuizSettings["hide_results"])}
          options={[
            { value: "", label: "Vis resultatene" },
            { value: "until_after_last_attempt", label: "Skjul til etter siste forsøk" },
            { value: "always", label: "Skjul alltid" },
          ]} />
      </div>
      <Fieldset legend="Visning">
        <Checkbox label="Bland rekkefølgen på svaralternativene" checked={settings.shuffle_answers}
          onChange={(e) => set("shuffle_answers", e.target.checked)} />
        <Checkbox label="Vis riktige svar etter innlevering" checked={settings.show_correct_answers}
          onChange={(e) => set("show_correct_answers", e.target.checked)} />
        {multiple && settings.show_correct_answers ? (
          <Checkbox label="Vis riktige svar først etter siste forsøk" checked={settings.show_correct_answers_last_attempt}
            onChange={(e) => set("show_correct_answers_last_attempt", e.target.checked)} />
        ) : null}
        <Checkbox label="Ett spørsmål om gangen" checked={settings.one_question_at_a_time}
          onChange={(e) => set("one_question_at_a_time", e.target.checked)} />
        {settings.one_question_at_a_time ? (
          <Checkbox label="Studentene kan ikke gå tilbake til tidligere spørsmål" checked={settings.cant_go_back}
            hint="Kan være en barriere for noen studenter. Bruk bare når det er faglig nødvendig."
            onChange={(e) => set("cant_go_back", e.target.checked)} />
        ) : null}
      </Fieldset>
      <div className="ek-grid" data-cols="2">
        <TextField label="Tilgjengelig fra" type="datetime-local" optional value={toLocalInput(settings.unlock_at)}
          onChange={(e) => set("unlock_at", fromLocalInput(e.target.value))} />
        <TextField label="Frist" type="datetime-local" optional value={toLocalInput(settings.due_at)}
          onChange={(e) => set("due_at", fromLocalInput(e.target.value))} />
        <TextField label="Tilgjengelig til" type="datetime-local" optional value={toLocalInput(settings.lock_at)}
          onChange={(e) => set("lock_at", fromLocalInput(e.target.value))} />
      </div>
      <Checkbox label="Publiser quizen når den er opprettet" checked={settings.published}
        hint="Standard er upublisert, slik at du kan se over quizen i Canvas først."
        onChange={(e) => set("published", e.target.checked)} />
    </div>
  );
}

export function QuizBuilder() {
  const { courseId } = useCurrentCourse();
  const session = useSession();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const bank = useBank(courseId, { status: "approved", module: "", q: "" });
  const presets = usePresets();
  const quizzes = useQuizzes(courseId);
  const modules = useQuery({
    queryKey: ["structure", courseId],
    queryFn: () => api.get<{ modules: { id: string; name: string }[] }>(`/api/courses/${courseId}/structure`),
    enabled: Boolean(courseId),
  });

  const [selected, setSelected] = useState<number[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [settings, setSettings] = useState<QuizSettings>(DEFAULT_SETTINGS);
  const [presetId, setPresetId] = useState<string>("");
  const [randomPick, setRandomPick] = useState(false);
  const [pickCount, setPickCount] = useState("");
  const [points, setPoints] = useState("1");
  const [moduleId, setModuleId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [previewed, setPreviewed] = useState<{ key: string; data: BuildPreview } | null>(null);
  const [initialized, setInitialized] = useState(false);

  // Start from the preset marked «Bruk som standard for nye quizer» (once, when presets have loaded).
  const defaultPreset = presets.data?.presets.find((p) => p.is_default);
  if (presets.data && !initialized) {
    setInitialized(true);
    if (defaultPreset) {
      setPresetId(String(defaultPreset.id));
      setSettings({ ...DEFAULT_SETTINGS, ...defaultPreset.settings, published: false });
    }
  }

  const request: BuildRequest = useMemo(() => ({
    title: title.trim(), description, settings, question_ids: selected,
    pick_count: randomPick && pickCount ? Number(pickCount) : null, points_per_question: Number(points) || 0,
    group_name: "Spørsmål", module_id: moduleId || null,
  }), [title, description, settings, selected, randomPick, pickCount, points, moduleId]);
  const requestKey = JSON.stringify(request);
  // A preview is only valid for exactly the request it was made for.
  const preview = previewed?.key === requestKey ? previewed.data : null;

  const previewMutation = useMutation({
    mutationFn: () => api.post<BuildPreview>(`/api/courses/${courseId}/quiz-builder/preview`, request),
    onSuccess: (data) => setPreviewed({ key: requestKey, data }),
  });
  const stage = useMutation({
    mutationFn: () => api.post(`/api/courses/${courseId}/quiz-builder/stage`, request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({
        tone: "success",
        title: "Quizen er lagt i endringskøen",
        body: session.dry_run ? "Dry run er på – quizen opprettes ikke før du slår det av." : "Gjennomfør den fra endringskøen.",
      });
      ui.openChanges();
    },
  });
  const copySettings = useMutation({
    mutationFn: (quizId: string) =>
      api.get<{ settings: QuizSettings; source: string }>(`/api/courses/${courseId}/quizzes/${quizId}/settings`),
    onSuccess: (data) => {
      setSettings({ ...DEFAULT_SETTINGS, ...data.settings, published: false });
      setPresetId("");
      toast.show({ tone: "info", title: `Innstillinger kopiert fra «${data.source}»` });
    },
  });
  const savePreset = useMutation({
    mutationFn: () => api.post<Preset>("/api/quiz/presets", { name: presetName.trim(), settings }),
    onSuccess: (preset) => {
      void client.invalidateQueries({ queryKey: ["quiz-presets"] });
      setPresetId(String(preset.id));
      setPresetName("");
      toast.show({ tone: "success", title: `Forhåndsinnstillingen «${preset.name}» er lagret` });
    },
  });
  const makeDefault = useMutation({
    mutationFn: (id: string) => api.post<Preset>(`/api/quiz/presets/${id}/default`),
    onSuccess: (preset) => {
      void client.invalidateQueries({ queryKey: ["quiz-presets"] });
      toast.show({ tone: "success", title: `«${preset.name}» brukes nå som standard for nye quizer` });
    },
  });

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (bank.isPending || presets.isPending) return <Spinner label="Henter spørsmål og innstillinger …" />;
  const approved = bank.data?.items ?? [];
  const byModule = approved.reduce<Record<string, typeof approved>>((acc, item) => {
    const key = item.module_name ?? "Uten modul";
    (acc[key] ??= []).push(item);
    return acc;
  }, {});
  const pickError = randomPick && pickCount && (Number(pickCount) < 1 || Number(pickCount) >= selected.length)
    ? `Velg et tall fra 1 til ${Math.max(1, selected.length - 1)}.` : undefined;
  const ready = title.trim() && selected.length > 0 && !pickError;

  if (!approved.length) {
    return (
      <EmptyState title="Ingen godkjente spørsmål ennå" headingLevel={2}>
        Godkjenn spørsmål i KI-spørsmålsbanken først. Bare godkjente spørsmål kan brukes i en quiz.
      </EmptyState>
    );
  }

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="1. Velg spørsmål" headingLevel={2}
        actions={
          <Button size="sm" onClick={() => setSelected(selected.length === approved.length ? [] : approved.map((i) => i.id))}>
            {selected.length === approved.length ? "Fjern alle" : "Velg alle"}
          </Button>
        }>
        <div className="ek-stack">
          {Object.entries(byModule).map(([module, items]) => (
            <Fieldset key={module} legend={`${module} (${items.length})`}>
              {items.map((item) => (
                <Checkbox key={item.id} label={item.stem} hint={`${item.type_label} · ${item.answers.length} alternativer`}
                  checked={selected.includes(item.id)}
                  onChange={(e) => setSelected(e.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} />
              ))}
            </Fieldset>
          ))}
          <p className="ek-small" aria-live="polite">{selected.length} spørsmål valgt</p>
        </div>
      </Card>

      <Card title="2. Quiz og spørsmålsutvalg" headingLevel={2}>
        <div className="ek-stack">
          <TextField label="Tittel" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} required />
          <TextArea label="Beskrivelse" optional value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
            maxLength={4000} />
          <Checkbox label="Trekk et tilfeldig utvalg spørsmål til hver student («X av Y»)" checked={randomPick}
            hint="Canvas lager en spørsmålsgruppe og trekker like mange spørsmål til hver student."
            onChange={(e) => setRandomPick(e.target.checked)} />
          <div className="ek-grid" data-cols="2">
            {randomPick ? (
              <TextField label={`Antall spørsmål per student (av ${selected.length})`} type="number" min={1}
                value={pickCount} onChange={(e) => setPickCount(e.target.value)} error={pickError} />
            ) : null}
            <TextField label="Poeng per spørsmål" type="number" min={0} max={100} step="0.5" value={points}
              onChange={(e) => setPoints(e.target.value)} />
            <SelectField label="Legg quizen i modul" value={moduleId} onChange={(e) => setModuleId(e.target.value)}
              placeholder="Ikke legg i en modul" options={(modules.data?.modules ?? []).map((m) => ({ value: m.id, label: m.name }))} />
          </div>
        </div>
      </Card>

      <Card title="3. Innstillinger" headingLevel={2}>
        <div className="ek-stack">
          <div className="ek-grid" data-cols="2">
            <SelectField label="Forhåndsinnstilling" value={presetId} placeholder="Egendefinert"
              options={(presets.data?.presets ?? []).map((p) => ({ value: String(p.id), label: p.is_default ? `${p.name} (standard)` : p.name }))}
              onChange={(e) => {
                setPresetId(e.target.value);
                const preset = presets.data?.presets.find((p) => String(p.id) === e.target.value);
                if (preset) setSettings({ ...DEFAULT_SETTINGS, ...preset.settings, published: false });
              }} />
            <SelectField label="Kopier innstillinger fra eksisterende quiz" value="" placeholder="Velg quiz …"
              options={(quizzes.data?.quizzes ?? []).map((q) => ({ value: q.id, label: q.title }))}
              onChange={(e) => e.target.value && copySettings.mutate(e.target.value)} />
          </div>
          {presetId ? (
            <div>
              <Button size="sm" icon={<Star aria-hidden="true" />} onClick={() => makeDefault.mutate(presetId)} loading={makeDefault.isPending}
                disabled={presets.data?.presets.find((p) => String(p.id) === presetId)?.is_default}>
                Bruk som standard for nye quizer
              </Button>
            </div>
          ) : null}
          <SettingsForm settings={settings} onChange={(s) => {
            setSettings(s);
            setPresetId("");
          }} />
          <div className="ek-cluster" data-align="end">
            <div style={{ flex: 1, minWidth: "14rem" }}>
              <TextField label="Lagre innstillingene som ny forhåndsinnstilling" placeholder="Navn" value={presetName}
                onChange={(e) => setPresetName(e.target.value)} maxLength={100} />
            </div>
            <Button icon={<Save aria-hidden="true" />} onClick={() => savePreset.mutate()} loading={savePreset.isPending}
              disabled={!presetName.trim()}>
              Lagre
            </Button>
          </div>
          {savePreset.error || copySettings.error ? (
            <Alert tone="danger" role="alert">{((savePreset.error ?? copySettings.error) as Error).message}</Alert>
          ) : null}
        </div>
      </Card>

      <Card title="4. Forhåndsvis og legg i endringskøen" headingLevel={2}>
        <div className="ek-stack">
          <div className="ek-cluster">
            <Button icon={<Eye aria-hidden="true" />} onClick={() => previewMutation.mutate()} loading={previewMutation.isPending}
              disabled={!ready}>
              Forhåndsvis
            </Button>
            <Button variant="primary" icon={<ListPlus aria-hidden="true" />} onClick={() => stage.mutate()} loading={stage.isPending}
              disabled={!preview} title={preview ? undefined : "Forhåndsvis quizen først"}>
              Legg i endringskøen
            </Button>
          </div>
          {!ready ? <p className="ek-small ek-muted">Skriv en tittel og velg minst ett spørsmål.</p> : null}
          {previewMutation.error || stage.error ? (
            <Alert tone="danger" role="alert" title="Noe gikk galt">{((previewMutation.error ?? stage.error) as Error).message}</Alert>
          ) : null}
          {preview ? (
            <div className="ek-stack">
              <KeyValue items={[
                ["Spørsmål", preview.summary.questions_asked === preview.summary.questions_total
                  ? `${preview.summary.questions_total}` : `${preview.summary.questions_asked} av ${preview.summary.questions_total} (tilfeldig utvalg)`],
                ["Poeng", String(preview.summary.points_possible)],
                ["Status etter opprettelse", preview.summary.published ? "Publisert" : "Upublisert"],
              ]} />
              {preview.warnings.length ? (
                <Alert tone="warning" title="Canvas vil ignorere noen innstillinger">
                  <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                </Alert>
              ) : null}
              <ol className="ek-small">
                {preview.questions.map((q, i) => <li key={i}>{q.stem}</li>)}
              </ol>
              <p className="ek-xs ek-muted">
                <Badge tone="info">Etter opprettelse</Badge> EmneKlar leser quizen tilbake fra Canvas og viser om noen
                innstillinger ble endret av Canvas.
              </p>
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
