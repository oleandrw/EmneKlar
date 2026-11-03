import { Bell, Brain, FlaskConical, Gauge, Link2, Palette, ShieldCheck, SlidersHorizontal, type LucideIcon } from "lucide-react";
import { Link, Navigate, useParams } from "react-router";

import { usePageTitle } from "../../core/usePageTitle";
import { Alert, PageHeader, Spinner } from "../../design-system";
import { AiSettings } from "./AiSettings";
import { useSettings } from "./api";
import { CanvasSettingsSection } from "./CanvasSettingsSection";
import { GeneralSettings } from "./GeneralSettings";
import { AdvancedSettings, AnalysisSettings, AppearanceSettings, NotificationSettings, PrivacySettings } from "./OtherSections";

const SECTIONS: { slug: string; label: string; icon: LucideIcon }[] = [
  { slug: "generelt", label: "Generelt", icon: SlidersHorizontal },
  { slug: "canvas-tilkobling", label: "Canvas-tilkobling", icon: Link2 },
  { slug: "ki-assistenter", label: "KI-assistenter", icon: Brain },
  { slug: "analyse", label: "Analyse", icon: Gauge },
  { slug: "sikkerhet-og-personvern", label: "Sikkerhet og personvern", icon: ShieldCheck },
  { slug: "utseende", label: "Utseende", icon: Palette },
  { slug: "varsler", label: "Varsler", icon: Bell },
  { slug: "avanserte-innstillinger", label: "Avanserte innstillinger", icon: FlaskConical },
];

export function SettingsPage() {
  const { section = "generelt" } = useParams();
  const current = SECTIONS.find((s) => s.slug === section);
  usePageTitle(current ? `${current.label} – Innstillinger` : "Innstillinger");
  const data = useSettings();
  if (!current) return <Navigate to="/innstillinger" replace />;

  let body;
  if (data.isPending) body = <Spinner label="Henter innstillinger …" />;
  else if (data.error) body = <Alert tone="danger" role="alert">{(data.error as Error).message}</Alert>;
  else {
    const s = data.data.settings;
    const key = (part: unknown) => JSON.stringify(part);
    body = {
      generelt: <GeneralSettings key={key(s.general)} settings={s} />,
      "canvas-tilkobling": <CanvasSettingsSection />,
      "ki-assistenter": <AiSettings />,
      analyse: <AnalysisSettings key={key(s.analysis)} settings={s} />,
      "sikkerhet-og-personvern": <PrivacySettings key={key(s.privacy)} settings={s} />,
      utseende: <AppearanceSettings key={key(s.appearance)} settings={s} />,
      varsler: <NotificationSettings settings={s} />,
      "avanserte-innstillinger": <AdvancedSettings key={key(s.advanced)} settings={s} flags={data.data.flags} />,
    }[current.slug];
  }

  return (
    <>
      <PageHeader title="Innstillinger" description={`${current.label}${data.data ? ` · EmneKlar ${data.data.version}` : ""}`} />
      <div className="ek-sidebar-layout">
        <nav aria-label="Innstillinger">
          <ul className="ek-subnav">
            {SECTIONS.map((s) => (
              <li key={s.slug}>
                <Link to={`/innstillinger/${s.slug}`} aria-current={s.slug === current.slug ? "page" : undefined}>
                  <s.icon aria-hidden="true" />
                  {s.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div>{body}</div>
      </div>
    </>
  );
}
