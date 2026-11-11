// Oppsett: four steps – Tilkobling → Bekreftelse → Emne og regelverk → Ferdig.
//
// The token lives only in this component's memory until the teacher confirms the connection; then the backend stores
// it in the OS credential store (core/auth/secrets.py) and it is cleared here. «Koble til» only tests – nothing is
// saved before «Bekreft og fortsett» – and a change of address or token throws away the earlier result. Nothing is
// created, changed or deleted in Canvas during the setup (only read requests), no analysis or AI is started, and
// external AI stays off.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleHelp, CircleMinus, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { ApiError, api } from "../../core/api/client";
import type { Course } from "../../core/api/types";
import { matchCourses } from "../../core/course";
import { formatDate } from "../../core/format";
import { BrandMark } from "../../core/layout/AppShell";
import { usePageTitle } from "../../core/usePageTitle";
import { useSession } from "../../core/session";
import {
  Alert,
  Button,
  Combobox,
  Disclosure,
  ExternalLink,
  PasswordField,
  RadioGroup,
  Spinner,
  Stepper,
  TextField,
} from "../../design-system";
import {
  accessHeadline,
  accessNotes,
  accessSummary,
  capabilityRow,
  connectionStatus,
  courseMeta,
  courseNames,
  hostOf,
  initialStep,
  readCanvasUrl,
  STEPS,
  type Access,
  type AccessLevel,
  type StepId,
  type TestResult,
} from "./model";

interface Profile {
  id: string;
  title: string;
  description: string;
  sector: string;
  is_legal_requirement: boolean;
  standard: string;
  verified_at: string;
  criteria_count: number;
  document_criteria_count: number;
  legal_basis: { title: string; url?: string | null }[];
}

interface Profiles {
  selected: string;
  profiles: Profile[];
}

/** Preselected in a brand-new setup – a suggested default, not an assessment of the institution. An earlier choice
 * (going back, resuming, an existing setup) is always kept. */
export const DEFAULT_PROFILE = "no-offentlig-2023";

/** One short text per profile (by sector); the legal detail is in the profile data under «Vis detaljer».
 * Checked 10.11.2026 against FOR-2013-06-21-732 § 4 and § 4 b (lovdata.no) and Uutilsynet. The recommendation for
 * the public-sector profile is limited on purpose: «… for de fleste høgskoler» was checked and not used – by count most
 * høgskoler are private (HK-dir, Tilstandsrapport for høyere utdanning 2026: 4 state høgskoler under KD, about 21
 * private), and a private one is covered only after a concrete assessment (FOA § 1-2, Uutilsynet). State universities
 * and university colleges are public bodies. */
export const PROFILE_AUDIENCE: Record<string, string> = {
  public: "Lovkravene for offentlige virksomheter – anbefalt for statlige universiteter og høgskoler.",
  private: "Lovkravene for private virksomheter.",
  best_practice: "Nyere beste praksis – ikke lovkrav i Norge i dag.",
};

/** The nuance behind «Vis detaljer» (Uutilsynet: «offentlig virksomhet» is understood as in the procurement rules,
 * FOA § 1-2; WCAG 2.2 is not part of the Norwegian rules). */
const PROFILE_SCOPE: Record<string, string> = {
  public: "Hva som regnes som offentlig virksomhet, følger regelverket om offentlige anskaffelser. Også private høgskoler "
    + "kan være omfattet – det avhenger av eierskap og finansiering.",
  private: "Velg denne bare hvis institusjonen ikke regnes som offentlig etter regelverket om offentlige anskaffelser.",
  best_practice: "WCAG 2.2 er ikke en del av det norske regelverket i dag.",
};

const LEVEL_ICON: Record<AccessLevel, ReactNode> = {
  all: <CircleCheck aria-hidden="true" />,
  some: <TriangleAlert aria-hidden="true" />,
  none: <CircleMinus aria-hidden="true" />,
  unknown: <CircleHelp aria-hidden="true" />,
};

function errorCode(error: unknown): string {
  return error instanceof ApiError ? error.code : "network";
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return "Fikk ikke kontakt med EmneKlar eller Canvas. Kontroller nettverket og prøv igjen.";
  // Only an address error has a detail that helps («Bruk bare adressen til Canvas, uten sti»); the rest are technical.
  return error.code === "canvas_url_invalid" && error.details ? `${error.message} (${error.details})` : error.message;
}

export function SetupWizard() {
  usePageTitle("Oppsett");
  const session = useSession();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [step, setStep] = useState<StepId>(() => initialStep(session));
  const [baseUrl, setBaseUrl] = useState(session.canvas.base_url ?? "");
  const [token, setToken] = useState("");
  const [tested, setTested] = useState<TestResult | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ baseUrl?: string; token?: string }>({});
  const [courseId, setCourseId] = useState<string>(session.general.default_course_id ?? "");
  const [profile, setProfile] = useState<string>(session.regulatory_profile || DEFAULT_PROFILE);
  // The connection in the credential store is the one on this page: saved now, or found when an interrupted setup was
  // resumed. Typing a new address or token makes it «not saved» again until it is confirmed.
  const [connectionSaved, setConnectionSaved] = useState(() => initialStep(session) === "start");
  const [finished, setFinished] = useState<{ course: Course | null; profile: Profile | null } | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const first = useRef(true);
  const index = STEPS.findIndex((s) => s.id === step);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  const typedUrl = readCanvasUrl(baseUrl);
  const validUrl = "url" in typedUrl ? typedUrl.url : null;
  // The stored token may only be reused for the address it was saved for (the backend enforces this too).
  const storedTokenUsable = session.canvas.token_configured && Boolean(validUrl) && validUrl === session.canvas.base_url;

  const test = useMutation({
    mutationFn: (url: string) =>
      api.post<TestResult>("/api/canvas/test", { base_url: url, token: token.trim() || null, capabilities: true }),
    onSuccess: (result) => {
      setTested(result);
      setStep("confirm");
    },
    onError: (error) => {
      const code = errorCode(error);
      if (code === "canvas_url_invalid") {
        setFieldErrors({ baseUrl: errorText(error) });
        urlRef.current?.focus();
      } else if (["canvas_token_invalid", "canvas_token_missing", "canvas_token_other_url"].includes(code)) {
        setFieldErrors({ token: errorText(error) });
        tokenRef.current?.focus();
      }
    },
  });
  const save = useMutation({
    mutationFn: () => api.put<TestResult>("/api/canvas/connection", {
      base_url: tested?.base_url, token: token.trim() || null, expected_user_id: tested?.identity.id,
    }),
    onSuccess: async () => {
      setToken("");
      setConnectionSaved(true);
      await client.invalidateQueries({ queryKey: ["session"] });
      setStep("start");
    },
  });
  const courses = useQuery({
    queryKey: ["courses", "setup"],
    queryFn: () => api.get<{ courses: Course[] }>("/api/courses?refresh=true"),
    enabled: step === "start",
  });
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () => api.get<Profiles>("/api/accessibility/profiles"),
    enabled: step === "start",
  });
  // A stored profile that no longer exists falls back to the default; any existing one is kept as it is.
  const chosenProfile = profiles.data && !profiles.data.profiles.some((p) => p.id === profile) ? DEFAULT_PROFILE : profile;
  const complete = useMutation({
    mutationFn: () => api.post("/api/setup/complete", { default_course_id: courseId || null, regulatory_profile: chosenProfile }),
    onSuccess: async () => {
      setFinished({
        course: courses.data?.courses.find((c) => c.id === courseId) ?? null,
        profile: profiles.data?.profiles.find((p) => p.id === chosenProfile) ?? null,
      });
      await Promise.all([client.invalidateQueries({ queryKey: ["session"] }), client.invalidateQueries({ queryKey: ["courses"] })]);
      setStep("done");
    },
  });

  const onConnect = (event: FormEvent) => {
    event.preventDefault();
    if (test.isPending) return; // never two checks at once
    test.reset();
    const errors: { baseUrl?: string; token?: string } = {};
    if ("error" in typedUrl) errors.baseUrl = typedUrl.error;
    if (!token.trim() && !storedTokenUsable) {
      errors.token = session.canvas.token_configured && validUrl
        ? "Tokenet som er lagret, hører til en annen Canvas-adresse. Lim inn et tilgangstoken for denne adressen."
        : "Lim inn tilgangstokenet fra Canvas.";
    }
    setFieldErrors(errors);
    if (errors.baseUrl) urlRef.current?.focus();
    else if (errors.token) tokenRef.current?.focus();
    if (errors.baseUrl || errors.token || !validUrl) return;
    setBaseUrl(validUrl);
    test.mutate(validUrl);
  };

  /** «Avbryt endringen» after «Endre valg»: back to the summary with the choices that were saved – nothing is sent. */
  const cancelEdit = () => {
    setCourseId(finished?.course?.id ?? "");
    if (finished?.profile) setProfile(finished.profile.id);
    complete.reset();
    setStep("done");
  };

  /** A change of address or token makes the earlier check (identity and permissions) invalid. */
  const edit = (setter: (value: string) => void, field: "baseUrl" | "token") => (value: string) => {
    setter(value);
    setTested(null);
    setConnectionSaved(false);
    save.reset();
    setFieldErrors((errors) => ({ ...errors, [field]: undefined }));
  };

  /** «Bekreft og fortsett»: saves a new connection; one that is already saved is not sent again. */
  const confirm = () => (connectionSaved ? setStep("start") : save.mutate());

  // Every step that can be shown with what is known is one click away in the list of steps at the top.
  const reachable: Record<StepId, boolean> = {
    connect: true,
    confirm: tested !== null || connectionSaved,
    start: connectionSaved,
    done: connectionSaved && finished !== null,
  };
  const completed: Record<StepId, boolean> = {
    connect: tested !== null || connectionSaved,
    confirm: connectionSaved,
    start: finished !== null,
    done: false,
  };
  const goTo = (id: StepId) => {
    if (id === step || !reachable[id]) return;
    if (id === "confirm" && !tested) {
      // A saved connection whose check is no longer in memory (the setup was resumed): check it again – only reading –
      // from «Tilkobling», which shows the progress and any error, and lands on «Bekreftelse» as «Koble til» does.
      setStep("connect");
      if (validUrl && !test.isPending) test.mutate(validUrl);
      return;
    }
    if (id === "done" && step === "start") cancelEdit(); // back to the summary with the choices that were saved
    else setStep(id);
  };
  /** «Tilbake» on each card: the step before. */
  const back = () => goTo(STEPS[Math.max(0, index - 1)].id);

  const savedHost = hostOf(session.canvas.base_url);
  const nameOf = courseNames(tested?.courses);
  const steps = STEPS.map((s) => ({
    id: s.id, label: s.label, done: completed[s.id] && s.id !== step, disabled: !reachable[s.id],
  }));

  return (
    <div className="ek-setup">
      <main className="ek-setup__main">
        <div className="ek-setup__brand">
          <BrandMark />
          <span>EmneKlar</span>
          <span className="ek-setup__brand-sub">Oppsett</span>
        </div>
        <Stepper label="Steg i oppsettet" steps={steps} current={step} onSelect={goTo} orientation="horizontal" />
        <section className="ek-setup__panel" aria-labelledby="oppsett-tittel">
          <h1 id="oppsett-tittel" ref={headingRef} tabIndex={-1} className="ek-setup__title">
            <span className="ek-visually-hidden">Steg {index + 1} av {STEPS.length}:</span>{" "}
            {STEPS[index].title}
          </h1>

          {step === "connect" ? (
            <form className="ek-stack" data-gap="5" onSubmit={onConnect} noValidate>
              <p className="ek-setup__lead">
                Koble EmneKlar til Canvas for å analysere og forbedre emnene dine. Du forhåndsviser og godkjenner endringer
                før de publiseres.
              </p>
              <TextField
                ref={urlRef}
                label="Canvas-adresse"
                hint="Adressen du bruker i nettleseren, for eksempel https://hiof.instructure.com"
                value={baseUrl}
                onChange={(e) => edit(setBaseUrl, "baseUrl")(e.target.value)}
                error={fieldErrors.baseUrl}
                autoComplete="url"
                inputMode="url"
                spellCheck={false}
              />
              <PasswordField
                ref={tokenRef}
                label="Tilgangstoken"
                revealLabel="Vis tilgangstoken"
                concealLabel="Skjul tilgangstoken"
                hint={storedTokenUsable
                  ? "Et tilgangstoken er lagret for denne adressen. La feltet stå tomt for å bruke det, eller lim inn et nytt."
                  : "Kalles også API-token i Canvas. Det gir EmneKlar samme tilgang som deg – behandle det som et passord."}
                value={token}
                onChange={(e) => edit(setToken, "token")(e.target.value)}
                error={fieldErrors.token}
                maxLength={2000}
              />
              <div className="ek-stack" data-gap="1">
                <Disclosure summary="Slik finner du tilgangstokenet">
                  <div className="ek-stack" data-gap="2">
                    <ol className="ek-setup__howto">
                      <li>Åpne Canvas og velg <strong>Konto</strong> → <strong>Innstillinger</strong>.</li>
                      <li>Under <strong>Godkjente integrasjoner</strong> velger du <strong>+ Nytt tilgangstoken</strong>.</li>
                      <li>Skriv «EmneKlar» som formål, og velg gjerne en utløpsdato.</li>
                      <li>Velg <strong>Generer token</strong>, kopier tokenet og lim det inn her. Canvas viser det bare én gang.</li>
                    </ol>
                    <p className="ek-small">
                      {validUrl
                        ? <ExternalLink href={`${validUrl}/profile/settings`}>Åpne Canvas-innstillinger</ExternalLink>
                        : "Skriv inn Canvas-adressen over, så får du en lenke rett til innstillingene."}
                    </p>
                    <p className="ek-small ek-muted">
                      Finner du ikke knappen, kan institusjonen ha slått av egne tokener. Spør Canvas-administratoren.
                    </p>
                  </div>
                </Disclosure>
                <Disclosure summary="Lagring og databruk">
                  <ul className="ek-setup__facts">
                    <li><strong>Tokenet</strong> lagres når du bekrefter i neste steg – i Windows Legitimasjonsbehandling på
                      denne maskinen. Aldri i en fil, i databasen eller i nettleseren.</li>
                    <li><strong>På denne maskinen:</strong> analysene, databasen og innstillingene.</li>
                    <li><strong>Canvas:</strong> EmneKlar henter emner og innhold med tokenet ditt. Endringer sendes bare når du
                      selv velger «Publiser til Canvas».</li>
                    <li><strong>Eksterne KI-tjenester:</strong> av til du selv slår dem på under Innstillinger. Oppsettet sender
                      ingenting dit, og ingenting analyseres, sendes til KI eller publiseres før du selv starter det.</li>
                  </ul>
                </Disclosure>
              </div>
              {test.isError && !fieldErrors.baseUrl && !fieldErrors.token ? (
                <Alert tone="danger" role="alert" title="Kunne ikke koble til">
                  {errorText(test.error)} Det du har skrevet inn, er beholdt.
                </Alert>
              ) : null}
              <span className="ek-visually-hidden" role="status">{test.isPending ? "Kobler til …" : ""}</span>
              <div className="ek-setup__actions">
                <Button type="submit" variant="primary" loading={test.isPending}>
                  {test.isPending ? "Kobler til …" : "Koble til"}
                </Button>
              </div>
            </form>
          ) : null}

          {step === "confirm" && tested ? (
            <div className="ek-stack" data-gap="4">
              <Alert {...connectionStatus(tested.access)} />
              <dl className="ek-setup__summary">
                <dt>Tilkoblet som</dt>
                <dd className="ek-setup__key">{tested.identity.name || "(uten navn)"}</dd>
                <dt>Canvas-adresse</dt>
                <dd className="ek-setup__key">{hostOf(tested.base_url)}</dd>
              </dl>
              <section className="ek-stack" data-gap="2" aria-labelledby="oppsett-tilganger">
                <h2 id="oppsett-tilganger" className="ek-setup__h2">Tilganger</h2>
                <ul className="ek-setup__access">
                  {accessSummary(tested.access).map((line) => (
                    <li key={line.key} data-level={line.level}>
                      {LEVEL_ICON[line.level]}
                      {line.text ? (
                        <span><strong>{line.title}:</strong> {line.text}</span>
                      ) : (
                        // Granted everywhere: the check mark says it; the status is still read out.
                        <span><strong>{line.title}</strong><span className="ek-visually-hidden">: innvilget</span></span>
                      )}
                    </li>
                  ))}
                </ul>
                {tested.access && tested.access.teaching_courses > 0 && tested.access.capabilities.length > 0 ? (
                  // The number is the access points in the list below – not courses, not granted permissions.
                  <Disclosure summary={`Se alle tilganger (${tested.access.capabilities.length})`}>
                    <div className="ek-stack" data-gap="2">
                      <AccessHeadline access={tested.access} name={nameOf} />
                      {accessNotes(tested.access, nameOf).map((line) => <p key={line} className="ek-small ek-muted">{line}</p>)}
                      <ul className="ek-setup__access ek-setup__access--detail">
                        {tested.access.capabilities.map((cap) => {
                          const row = capabilityRow(
                            cap, nameOf, tested.access!.checked_courses, tested.access!.teaching_courses);
                          return (
                            <li key={cap.key} data-level={row.level}>
                              {LEVEL_ICON[row.level]}
                              <span>
                                <span className="ek-setup__access-label">{cap.label}</span>
                                {row.note ? (
                                  <>
                                    <span className="ek-visually-hidden">:</span>{" "}
                                    <span className="ek-setup__meta">{row.note}</span>
                                  </>
                                ) : (
                                  // No visible text when it is granted everywhere (the sentence above says so) – but
                                  // the status is still read out, since the icon is decorative.
                                  <span className="ek-visually-hidden">: {row.spoken}</span>
                                )}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                      <p className="ek-small ek-muted">Tilgang kan variere mellom emner og kontrolleres på nytt før hver endring.</p>
                    </div>
                  </Disclosure>
                ) : null}
              </section>
              {save.isError ? (
                <Alert tone="danger" role="alert" title="Tilkoblingen ble ikke lagret">
                  {errorText(save.error)}{" "}
                  {errorCode(save.error) === "canvas_identity_changed"
                    ? "Velg «Tilbake» og koble til på nytt."
                    : "En tidligere lagret tilkobling er ikke endret."}
                </Alert>
              ) : null}
              <p className="ek-small ek-muted">Tilkoblingen lagres når du bekrefter.</p>
              <div className="ek-setup__actions">
                <Button onClick={back}>Tilbake</Button>
                <Button variant="primary" onClick={confirm} loading={save.isPending}
                  disabled={errorCode(save.error) === "canvas_identity_changed" && save.isError}>
                  Bekreft og fortsett
                </Button>
              </div>
            </div>
          ) : null}

          {step === "start" ? (
            <div className="ek-stack" data-gap="5">
              <CoursePicker courses={courses.data?.courses} loading={courses.isPending} error={courses.error}
                retry={() => void courses.refetch()} value={courseId} onChange={setCourseId} />
              <section className="ek-stack" data-gap="2" aria-labelledby="oppsett-profil">
                <h2 id="oppsett-profil" className="ek-setup__h2">Krav som skal kontrolleres</h2>
                {profiles.isPending ? <Spinner label="Henter regelverksprofilene …" /> : null}
                {profiles.error ? (
                  <Alert tone="danger" role="alert" title="Kunne ikke hente regelverksprofilene">{errorText(profiles.error)}</Alert>
                ) : null}
                {profiles.data ? (
                  <RadioGroup
                    legend="Regelverksprofil"
                    hideLegend
                    hint="Velg profilen som gjelder for institusjonen din – forhåndsvalget er bare et forslag. Automatiske kontroller kan ikke bevise at kravene er oppfylt."
                    name="profile"
                    variant="card"
                    value={chosenProfile}
                    onChange={setProfile}
                    options={profiles.data.profiles.map((p) => ({
                      value: p.id,
                      label: p.title,
                      hint: PROFILE_AUDIENCE[p.sector],
                      details: <ProfileDetails profile={p} />,
                    }))}
                  />
                ) : null}
              </section>
              {complete.isError ? (
                <Alert tone="danger" role="alert" title={finished ? "Endringene ble ikke lagret" : "Oppsettet ble ikke lagret"}>
                  {errorText(complete.error)}{" "}
                  {finished ? "Valgene som ble lagret tidligere, gjelder fortsatt." : "Prøv igjen – tilkoblingen er beholdt."}
                </Alert>
              ) : null}
              <div className="ek-setup__actions">
                <span className="ek-cluster">
                  <Button onClick={back}>Tilbake</Button>
                  {finished ? (
                    // Came back from the summary: return to it with the saved choices, nothing changed.
                    <Button onClick={cancelEdit}>Avbryt endringen</Button>
                  ) : null}
                </span>
                <Button variant="primary" onClick={() => complete.mutate()} loading={complete.isPending}
                  disabled={!chosenProfile || profiles.isPending}>
                  Fullfør oppsett
                </Button>
              </div>
            </div>
          ) : null}

          {step === "done" ? (
            <div className="ek-stack" data-gap="4">
              <p className="ek-setup__connected">
                <CircleCheck aria-hidden="true" />
                <span>Oppsettet er lagret.</span>
              </p>
              <dl className="ek-setup__summary">
                <dt>Canvas-adresse</dt>
                <dd>{savedHost || hostOf(tested?.base_url)}</dd>
                <dt>Tilkoblet som</dt>
                <dd>{session.canvas.identity?.name ?? tested?.identity.name ?? "–"}</dd>
                <dt>Startemne</dt>
                <dd>{finished?.course ? <CourseName course={finished.course} /> : "Velges senere"}</dd>
                <dt>Valgt regelverksprofil</dt>
                <dd>{finished?.profile?.title ?? chosenProfile}</dd>
              </dl>
              <p>
                {finished?.course ? "Du er klar til å åpne emneoversikten." : "Du er klar til å velge emne."} Du starter selv
                analyser og godkjenner endringer.
              </p>
              <div className="ek-setup__actions">
                <Button onClick={back}>
                  Tilbake<span className="ek-visually-hidden">: endre startemne og regelverksprofil</span>
                </Button>
                <Button variant="primary" onClick={() => navigate(finished?.course ? "/oversikt" : "/oversikt?velg-emne=1")}>
                  {finished?.course ? "Åpne emneoversikten" : "Velg emne"}
                </Button>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}

/** One sentence over «Se alle tilganger», naming the courses checked; with many, the names on request. */
function AccessHeadline({ access, name }: { access: Access; name: (id: string) => string }) {
  const headline = accessHeadline(access, name);
  return (
    <>
      <p className="ek-setup__headline">{headline.text}</p>
      {headline.courses.length ? (
        <Disclosure summary={`Vis emnene (${headline.courses.length})`}>
          <ul className="ek-setup__names ek-small">{headline.courses.map((c) => <li key={c}>{c}</li>)}</ul>
        </Disclosure>
      ) : null}
    </>
  );
}

/** A course as everywhere in the setup: the name on the main line, code and term on a muted line below. */
function CourseName({ course }: { course: Course }) {
  const meta = courseMeta(course);
  return (
    <>
      <span className="ek-setup__course">{course.name}</span>
      {meta ? <span className="ek-setup__meta">{meta}</span> : null}
    </>
  );
}

/** «Hvilket emne vil du starte med?» – one field: click it to see the courses, or type a name, code or term. All
 * courses are searched (the same search as the course selector); empty means «choose later». */
function CoursePicker({ courses, loading, error, retry, value, onChange }: {
  courses: Course[] | undefined;
  loading: boolean;
  error: unknown;
  retry: () => void;
  value: string;
  onChange: (id: string) => void;
}) {
  const all = useMemo(() => courses ?? [], [courses]);
  const options = useMemo(() => all.map((c) => ({
    value: c.id, label: c.name || c.course_code || c.id, meta: courseMeta(c) || undefined,
  })), [all]);
  const search = useCallback((query: string) => {
    const byId = new Map(options.map((o) => [o.value, o]));
    return matchCourses(all, query).map((c) => byId.get(c.id)!);
  }, [all, options]);
  return (
    <section className="ek-stack" data-gap="2" aria-labelledby="oppsett-emne">
      <h2 id="oppsett-emne" className="ek-setup__h2">Hvilket emne vil du starte med?</h2>
      {loading ? <Spinner label="Henter emnene dine fra Canvas …" /> : null}
      {error ? (
        <Alert tone="warning" role="alert" title="Kunne ikke hente emnene">
          {errorText(error)}{" "}
          <Button size="sm" onClick={retry}>Prøv igjen</Button>
        </Alert>
      ) : null}
      {!loading && courses && all.length === 0 ? (
        <p className="ek-small ek-muted">
          Fant ingen emner der du er lærer, assistent eller designer. Velg emne senere, når du har fått tilgang i Canvas.
        </p>
      ) : null}
      {!loading && all.length > 0 ? (
        <Combobox
          label="Startemne"
          hideLabel
          hint="Søk etter emnenavn, emnekode eller semester. La feltet stå tomt for å velge senere – du kan bytte emne når som helst øverst i EmneKlar."
          placeholder="Velg eller søk etter emne"
          options={options}
          search={search}
          value={value}
          onChange={onChange}
          clearLabel="Fjern valgt emne"
          noResults="Fant ingen emner som passer"
        />
      ) : null}
    </section>
  );
}

function ProfileDetails({ profile }: { profile: Profile }) {
  const counts = profile.document_criteria_count !== profile.criteria_count
    ? `${profile.criteria_count} suksesskriterier for nettløsninger og ${profile.document_criteria_count} for dokumenter`
    : `${profile.criteria_count} suksesskriterier`;
  return (
    <div className="ek-stack ek-small" data-gap="2">
      {PROFILE_SCOPE[profile.sector] ? <p>{PROFILE_SCOPE[profile.sector]}</p> : null}
      <p>{profile.description}</p>
      <p><strong>Grunnlag:</strong> {profile.standard}. {counts} i regelverksprofilen.</p>
      {profile.legal_basis.length ? (
        <div>
          <strong>Kilder:</strong>
          <ul className="ek-setup__sources">
            {profile.legal_basis.map((source) => (
              <li key={source.title}>
                {source.url ? <ExternalLink href={source.url}>{source.title}</ExternalLink> : source.title}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="ek-muted">
        {profile.is_legal_requirement ? "Lovkrav." : "Ikke et lovkrav."} Sist kontrollert mot kildene{" "}
        {formatDate(profile.verified_at)}.
      </p>
    </div>
  );
}
