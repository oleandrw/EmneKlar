import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { api } from "../../core/api/client";
import type { Course } from "../../core/api/types";
import { usePageTitle } from "../../core/usePageTitle";
import { useSession } from "../../core/session";
import { Alert, Button, Card, ExternalLink, RadioGroup, Spinner, TextField } from "../../design-system";

const STEPS = [
  "Velkommen",
  "Canvas-adresse",
  "API-token",
  "Test tilkoblingen",
  "Din Canvas-identitet",
  "Tilganger",
  "Standardemne",
  "Regelverksprofil",
  "Ferdig",
];

interface TestResult {
  ok: boolean;
  base_url: string;
  identity: { id: string; name: string };
  teaching_courses: number;
}

interface CapabilitySummary {
  teaching_courses: number;
  checked_courses: number;
  capabilities: { key: string; label: string; granted: number; checked: number }[];
}

interface Profiles {
  selected: string;
  profiles: { id: string; title: string; description: string; criteria_count: number; is_legal_requirement: boolean }[];
}

export function SetupWizard() {
  usePageTitle("Oppsett");
  const session = useSession();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [step, setStep] = useState(0);
  const [baseUrl, setBaseUrl] = useState(session.canvas.base_url ?? "");
  const [token, setToken] = useState("");
  const [tested, setTested] = useState<TestResult | null>(null);
  const [courseId, setCourseId] = useState<string>("");
  const [profile, setProfile] = useState<string>(session.regulatory_profile);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const test = useMutation({
    mutationFn: () => api.post<TestResult>("/api/canvas/test", { base_url: baseUrl, token: token || null }),
    onSuccess: setTested,
  });
  const save = useMutation({
    mutationFn: () => api.put<TestResult>("/api/canvas/connection", { base_url: baseUrl, token: token || null }),
    onSuccess: async () => {
      setToken("");
      await client.invalidateQueries({ queryKey: ["session"] });
      setStep(5);
    },
  });
  const summary = useQuery({
    queryKey: ["capability-summary"],
    queryFn: () => api.get<CapabilitySummary>("/api/canvas/capability-summary"),
    enabled: step === 5,
  });
  const courses = useQuery({
    queryKey: ["courses", "setup"],
    queryFn: () => api.get<{ courses: Course[] }>("/api/courses?refresh=true"),
    enabled: step === 6,
  });
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () => api.get<Profiles>("/api/accessibility/profiles"),
    enabled: step === 7,
  });
  const complete = useMutation({
    mutationFn: () => api.post("/api/setup/complete", { default_course_id: courseId || null, regulatory_profile: profile }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["session"] });
      await client.invalidateQueries({ queryKey: ["courses"] });
      navigate("/oversikt");
    },
  });

  const urlError = baseUrl && !/^https?:\/\/[^\s/]+\.[^\s/]+\/?$/.test(baseUrl.trim()) && !/^[^\s/]+\.[^\s/]+$/.test(baseUrl.trim())
    ? "Skriv bare adressen til Canvas, for eksempel https://hiof.instructure.com"
    : undefined;
  const tokenNeeded = !session.canvas.token_configured;

  const next = () => setStep((s) => Math.min(STEPS.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-bg)", padding: "2rem 1rem" }}>
      <main className="ek-stack" data-gap="6" style={{ maxWidth: "62rem", margin: "0 auto" }}>
        <div className="ek-cluster" data-gap="2">
          <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="#13254a" />
            <path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#9ec1ff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="ek-strong" style={{ fontSize: "var(--text-lg)" }}>
            EmneKlar – oppsett
          </span>
        </div>
        <div className="ek-wizard">
          <nav aria-label="Steg i oppsettet">
            <ol className="ek-steps">
              {STEPS.map((label, index) => (
                <li key={label} className="ek-steps__item" aria-current={index === step ? "step" : undefined} data-done={index < step}>
                  <span className="ek-steps__num" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span>
                    {label}
                    {index < step ? <span className="ek-visually-hidden"> (fullført)</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          </nav>
          <Card>
            <div className="ek-stack" data-gap="6">
              <h1 ref={headingRef} tabIndex={-1} style={{ fontSize: "var(--text-xl)" }}>
                Steg {step + 1} av {STEPS.length}: {STEPS[step]}
              </h1>

              {step === 0 ? (
                <div className="ek-stack">
                  <p>
                    EmneKlar hjelper deg å analysere og forbedre Canvas-emner: universell utforming, innholdskvalitet,
                    emnestruktur, quizer og emneforside.
                  </p>
                  <ul>
                    <li>Alt kjører lokalt på denne maskinen.</li>
                    <li>Ingenting endres i Canvas før du har forhåndsvist og godkjent endringen.</li>
                    <li>Canvas-tokenet lagres i Windows Legitimasjonsbehandling – aldri i en fil eller i nettleseren.</li>
                    <li>KI er valgfritt og slått av til du selv slår det på.</li>
                  </ul>
                </div>
              ) : null}

              {step === 1 ? (
                <TextField
                  label="Adressen til Canvas"
                  hint="Den du bruker i nettleseren, for eksempel https://hiof.instructure.com"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  error={urlError}
                  autoComplete="url"
                  inputMode="url"
                  required
                />
              ) : null}

              {step === 2 ? (
                <div className="ek-stack">
                  {session.canvas.token_configured ? (
                    <Alert tone="success" title="Et token er allerede lagret">
                      Du kan gå videre, eller lime inn et nytt token for å erstatte det.
                    </Alert>
                  ) : null}
                  <ol className="ek-small">
                    <li>Logg inn i Canvas og velg <strong>Konto → Innstillinger</strong>.</li>
                    <li>Velg <strong>+ Nytt tilgangstoken</strong>, gi det navnet «EmneKlar» og en utløpsdato.</li>
                    <li>Kopier tokenet og lim det inn her. Canvas viser det bare én gang.</li>
                  </ol>
                  <TextField
                    label="Canvas API-token"
                    type="password"
                    autoComplete="off"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    hint="Tokenet gir samme tilgang som deg i Canvas. Det lagres bare i Windows Legitimasjonsbehandling."
                  />
                  {baseUrl && !urlError ? (
                    <p className="ek-small">
                      <ExternalLink href={`${baseUrl.replace(/\/$/, "").replace(/^(?!https?:\/\/)/, "https://")}/profile/settings`}>
                        Åpne Canvas-innstillingene
                      </ExternalLink>
                    </p>
                  ) : null}
                </div>
              ) : null}

              {step === 3 ? (
                <div className="ek-stack">
                  <p>EmneKlar henter din bruker og emneliste fra Canvas. Ingenting lagres før neste steg.</p>
                  <div>
                    <Button variant="primary" onClick={() => test.mutate()} loading={test.isPending}>
                      Test tilkoblingen
                    </Button>
                  </div>
                  {test.error ? (
                    <Alert tone="danger" role="alert" title="Tilkoblingen feilet">
                      {(test.error as Error).message}
                    </Alert>
                  ) : null}
                  {tested ? (
                    <Alert tone="success" role="status" title="Tilkoblingen virker">
                      Canvas svarte på {tested.base_url}.
                    </Alert>
                  ) : null}
                </div>
              ) : null}

              {step === 4 ? (
                <div className="ek-stack">
                  {tested ? (
                    <>
                      <p>
                        Du er logget inn som <strong>{tested.identity.name}</strong> og har lærer-, assistent- eller
                        designertilgang i <strong>{tested.teaching_courses}</strong> emner.
                      </p>
                      <p className="ek-small ek-muted">Stemmer ikke dette? Gå tilbake og bruk et annet token.</p>
                    </>
                  ) : (
                    <Alert tone="warning">Test tilkoblingen i forrige steg først.</Alert>
                  )}
                  {save.error ? (
                    <Alert tone="danger" role="alert" title="Kunne ikke lagre">
                      {(save.error as Error).message}
                    </Alert>
                  ) : null}
                </div>
              ) : null}

              {step === 5 ? (
                <div className="ek-stack">
                  {summary.isPending ? <Spinner label="Kontrollerer tilganger i emnene dine …" /> : null}
                  {summary.error ? <Alert tone="danger">{(summary.error as Error).message}</Alert> : null}
                  {summary.data ? (
                    <>
                      <p>
                        Kontrollert i {summary.data.checked_courses} av {summary.data.teaching_courses} emner. Tilganger
                        kan variere mellom emner – EmneKlar sjekker også før hver endring.
                      </p>
                      <ul className="ek-list-reset ek-stack" data-gap="2">
                        {summary.data.capabilities.map((cap) => {
                          const ok = cap.checked > 0 && cap.granted === cap.checked;
                          return (
                            <li key={cap.key} className="ek-cluster" data-gap="2">
                              {ok ? (
                                <CircleCheck aria-hidden="true" color="var(--tone-success-text)" size={18} />
                              ) : (
                                <CircleX aria-hidden="true" color="var(--tone-danger-text)" size={18} />
                              )}
                              <span>
                                {cap.label}: {ok ? "ja" : `i ${cap.granted} av ${cap.checked} emner`}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </>
                  ) : null}
                </div>
              ) : null}

              {step === 6 ? (
                <div className="ek-stack">
                  {courses.isPending ? <Spinner label="Henter emner …" /> : null}
                  {courses.data ? (
                    <RadioGroup
                      legend="Hvilket emne vil du starte med?"
                      hint="Valgfritt. Du kan alltid bytte emne øverst i EmneKlar."
                      name="default-course"
                      value={courseId}
                      onChange={setCourseId}
                      options={[
                        { value: "", label: "Velg senere" },
                        ...courses.data.courses.map((c) => ({
                          value: c.id,
                          label: c.course_code ?? c.name,
                          hint: `${c.name}${c.term_name ? ` · ${c.term_name}` : ""}`,
                        })),
                      ]}
                    />
                  ) : null}
                </div>
              ) : null}

              {step === 7 ? (
                <div className="ek-stack">
                  {profiles.data ? (
                    <RadioGroup
                      legend="Hvilke krav skal funnene vurderes mot?"
                      hint="De fleste universiteter og høgskoler er offentlig sektor. Du kan endre dette senere."
                      name="profile"
                      variant="card"
                      value={profile}
                      onChange={setProfile}
                      options={profiles.data.profiles.map((p) => ({
                        value: p.id,
                        label: `${p.title} (${p.criteria_count} kriterier)`,
                        hint: p.description,
                      }))}
                    />
                  ) : (
                    <Spinner label="Henter profiler …" />
                  )}
                </div>
              ) : null}

              {step === 8 ? (
                <div className="ek-stack">
                  <p>Oppsettet er klart. Neste steg er å kjøre en analyse av emnet.</p>
                  {complete.error ? <Alert tone="danger">{(complete.error as Error).message}</Alert> : null}
                </div>
              ) : null}

              <div className="ek-cluster" data-justify="between">
                <Button onClick={back} disabled={step === 0}>
                  Tilbake
                </Button>
                {step === 4 ? (
                  <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!tested}>
                    Bekreft og lagre tilkoblingen
                  </Button>
                ) : step === 8 ? (
                  <Button variant="primary" onClick={() => complete.mutate()} loading={complete.isPending}>
                    Gå til EmneKlar
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    onClick={next}
                    disabled={
                      (step === 1 && (!baseUrl || Boolean(urlError))) ||
                      (step === 2 && tokenNeeded && !token) ||
                      (step === 3 && !tested) ||
                      (step === 5 && !summary.data) ||
                      (step === 7 && !profile)
                    }
                  >
                    Neste
                  </Button>
                )}
              </div>
            </div>
          </Card>
        </div>
      </main>
    </div>
  );
}
