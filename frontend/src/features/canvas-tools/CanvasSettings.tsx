// «Canvas-innstillinger»: categorised analysis of course, page, assignment and quiz settings.
// Preferences are never changed automatically – only an explicit choice is put in the change queue.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListPlus } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { plural } from "../../core/format";
import { useCurrentCourse } from "../../core/course";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  Disclosure,
  EmptyState,
  ExternalLink,
  PageHeader,
  SelectField,
  Spinner,
  Switch,
  useToast,
  type Tone,
} from "../../design-system";
import { BackToTools } from "./shared";

type Category = "technical" | "security_accessibility" | "recommendation" | "preference";

interface SettingItem {
  id: string;
  rule_id: string;
  category: Category;
  category_label: string;
  title: string;
  explanation: string;
  object: { type: string; id: string; title: string | null; url: string | null };
  current: string;
  recommendation: string;
  fix: { kind: "default_view"; options: { value: string; label: string }[] } | { kind: "link"; path: string; label: string } | null;
}

interface SettingsAnalysis {
  items: SettingItem[];
  counts: Record<Category, number>;
  category_labels: Record<Category, string>;
  preferences: { key: string; label: string; description: string; value: boolean }[];
  course: { default_view: string; default_view_label: string; has_front_page: boolean };
  checked: { pages: number; assignments: number; quizzes: number };
  limitations: string[];
}

const CATEGORY_TONE: Record<Category, Tone> = {
  technical: "danger", security_accessibility: "warning", recommendation: "info", preference: "neutral",
};
const ORDER: Category[] = ["technical", "security_accessibility", "recommendation"];

function useStage(courseId: string) {
  const session = useSession();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: "default_view" | "setting"; key?: string; value: string | boolean }) =>
      api.post(`/api/courses/${courseId}/canvas-settings/stage`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({
        tone: "success",
        title: "Endringen er lagt i endringskøen",
        body: session.dry_run ? "Dry run er på – ingenting sendes til Canvas." : "Gjennomfør den fra endringskøen.",
      });
      ui.openChanges();
    },
  });
}

function DefaultViewFix({ courseId, options }: { courseId: string; options: { value: string; label: string }[] }) {
  const [value, setValue] = useState(options[0]?.value ?? "modules");
  const stage = useStage(courseId);
  return (
    <div className="ek-cluster" data-align="end">
      <div style={{ minWidth: "12rem" }}>
        <SelectField label="Ny startside" value={value} onChange={(e) => setValue(e.target.value)} options={options} />
      </div>
      <Button icon={<ListPlus aria-hidden="true" />} onClick={() => stage.mutate({ kind: "default_view", value })} loading={stage.isPending}>
        Legg i endringskøen
      </Button>
      {stage.error ? <Alert tone="danger" role="alert">{(stage.error as Error).message}</Alert> : null}
    </div>
  );
}

function PreferenceRow({ courseId, pref }: { courseId: string; pref: SettingsAnalysis["preferences"][number] }) {
  const [value, setValue] = useState(pref.value);
  const stage = useStage(courseId);
  return (
    <li className="ek-row">
      <div className="ek-row__main">
        <Switch label={pref.label} checked={value} onChange={setValue} />
        {pref.description ? <span className="ek-xs ek-muted">{pref.description}</span> : null}
      </div>
      {value !== pref.value ? (
        <Button size="sm" onClick={() => stage.mutate({ kind: "setting", key: pref.key, value })} loading={stage.isPending}>
          Legg i endringskøen<span className="ek-visually-hidden">: {pref.label}</span>
        </Button>
      ) : null}
      {stage.error ? <Alert tone="danger" role="alert">{(stage.error as Error).message}</Alert> : null}
    </li>
  );
}

export function CanvasSettings() {
  const { courseId } = useCurrentCourse();
  const analysis = useQuery({
    queryKey: ["canvas-settings", courseId],
    queryFn: () => api.get<SettingsAnalysis>(`/api/courses/${courseId}/canvas-settings`),
    enabled: Boolean(courseId),
  });
  const header = <PageHeader title="Canvas-innstillinger" description="Gjennomgang av innstillinger for emnet, sider, oppgaver og quizer." />;
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (analysis.isPending) return <>{header}<Spinner label="Leser innstillinger fra Canvas …" /></>;
  if (analysis.error) return <>{header}<Alert tone="danger" role="alert">{(analysis.error as Error).message}</Alert></>;
  const data = analysis.data;

  return (
    <>
      {header}
      <div className="ek-stack" data-gap="6">
        <BackToTools />
        <p className="ek-small ek-muted">
          Kontrollerte {plural(data.checked.pages, "side", "sider")}, {plural(data.checked.assignments, "oppgave", "oppgaver")} og{" "}
          {plural(data.checked.quizzes, "quiz", "quizer")}.
          Startsiden er «{data.course.default_view_label}». Ingenting endres uten at du legger det i endringskøen.
        </p>
        {ORDER.map((category) => {
          const items = data.items.filter((i) => i.category === category);
          return (
            <section key={category} className="ek-stack" aria-labelledby={`kat-${category}`}>
              <div className="ek-section__header">
                <h2 id={`kat-${category}`}>{data.category_labels[category]}</h2>
                <Badge tone={CATEGORY_TONE[category]}>{items.length}</Badge>
              </div>
              {items.length === 0 ? (
                <p className="ek-small ek-muted">Ingenting å melde.</p>
              ) : (
                <ul className="ek-list-reset ek-stack" data-gap="2">
                  {items.map((item) => (
                    <li key={item.id} className="ek-card" style={{ padding: "1rem 1.25rem" }}>
                      <div className="ek-stack" data-gap="2">
                        <div className="ek-cluster" data-gap="2">
                          <Badge tone={CATEGORY_TONE[item.category]}>{item.category_label}</Badge>
                          <span className="ek-xs ek-muted">
                            {item.object.url ? <ExternalLink href={item.object.url}>{item.object.title}</ExternalLink> : item.object.title}
                          </span>
                        </div>
                        <h3 style={{ fontSize: "var(--text-base)" }}>{item.title}</h3>
                        <p className="ek-small">{item.explanation}</p>
                        {item.current ? <p className="ek-xs ek-muted">Nå: {item.current}</p> : null}
                        {item.recommendation ? <p className="ek-small"><span className="ek-strong">Forslag: </span>{item.recommendation}</p> : null}
                        {item.fix?.kind === "default_view" ? <DefaultViewFix courseId={courseId} options={item.fix.options} /> : null}
                        {item.fix?.kind === "link" ? (
                          <div><ButtonLink to={item.fix.path} size="sm">{item.fix.label}</ButtonLink></div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
        <Card title="Preferanser" headingLevel={2}>
          <p className="ek-small ek-muted">
            Dette er valg som avhenger av hvordan du underviser. EmneKlar anbefaler ingen verdi og endrer dem aldri
            automatisk. Endre en bryter og legg endringen i køen hvis du vil endre den i Canvas.
          </p>
          <ul className="ek-list-reset ek-divider-list ek-mt-4">
            {data.preferences.map((pref) => <PreferenceRow key={pref.key} courseId={courseId} pref={pref} />)}
          </ul>
        </Card>
        <Disclosure summary="Begrensninger">
          <ul className="ek-small">{data.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </Disclosure>
      </div>
    </>
  );
}
