import { useQuery } from "@tanstack/react-query";
import { BookOpen, Copy, Info, LifeBuoy, Lightbulb, MessageSquare, MessagesSquare, Rocket, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router";

import { api } from "../../core/api/client";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import { Alert, Button, Card, Disclosure, ExternalLink, PageHeader, useToast } from "../../design-system";

const TOPICS: { slug: string; label: string; icon: LucideIcon }[] = [
  { slug: "kom-i-gang", label: "Kom i gang", icon: Rocket },
  { slug: "brukerveiledninger", label: "Brukerveiledninger", icon: BookOpen },
  { slug: "vanlige-sporsmal", label: "Vanlige spørsmål", icon: MessagesSquare },
  { slug: "tips", label: "Tips og beste praksis", icon: Lightbulb },
  { slug: "feilsoking", label: "Feilsøking", icon: LifeBuoy },
  { slug: "kontakt", label: "Kontakt / tilbakemelding", icon: MessageSquare },
  { slug: "om", label: "Om EmneKlar", icon: Info },
];

interface UpdateStatus {
  current_version: string;
  repository: string | null;
  install: { label: string };
}

function useDiagnostics(): () => string {
  const session = useSession();
  const status = useQuery({ queryKey: ["update-status"], queryFn: () => api.get<UpdateStatus>("/api/updates/status") });
  return () =>
    [
      `EmneKlar ${session.app.version}`,
      `Installasjon: ${status.data?.install.label ?? "ukjent"}`,
      `Nettleser: ${navigator.userAgent}`,
      `Dry run: ${session.dry_run ? "på" : "av"}`,
      `Canvas tilkoblet: ${session.canvas.token_configured ? "ja" : "nei"}`,
      `KI-leverandører aktivert: ${session.ai.providers_enabled.length}`,
      `Funksjonsflagg av: ${Object.entries(session.flags).filter(([, on]) => !on).map(([k]) => k).join(", ") || "ingen"}`,
    ].join("\n");
}

function CopyDiagnostics() {
  const toast = useToast();
  const text = useDiagnostics();
  return (
    <Button icon={<Copy aria-hidden="true" />} onClick={() => {
      void navigator.clipboard.writeText(text()).then(
        () => toast.show({ tone: "success", title: "Feilsøkingsinfo er kopiert", body: "Den inneholder ingen token, nøkler eller emneinnhold." }),
        () => toast.show({ tone: "warning", title: "Kunne ikke kopiere til utklippstavlen" }),
      );
    }}>
      Kopier feilsøkingsinfo
    </Button>
  );
}

function GettingStarted() {
  const ui = useUi();
  const steps: { title: string; body: ReactNode }[] = [
    { title: "Koble til Canvas", body: <>Legg inn adressen til Canvas og et API-token under <Link to="/innstillinger/canvas-tilkobling">Canvas-tilkobling</Link>. Tokenet lagres i Windows Legitimasjonsbehandling.</> },
    { title: "Velg emne", body: <>Velg emnet i emnevelgeren øverst på siden. Valget gjelder alle deler av EmneKlar til du bytter.</> },
    { title: "Kjør analyse", body: <>Trykk «Kjør ny analyse», velg omfang og områder, og følg fremdriften. Analysen leser bare fra Canvas. <Button size="sm" variant="link" onClick={() => ui.openAnalysis()}>Kjør ny analyse nå</Button></> },
    { title: "Gjennomgå funn", body: <>Se funnene under <Link to="/universell-utforming">Universell utforming</Link>, <Link to="/innholdskvalitet">Innholdskvalitet</Link> og <Link to="/emnestruktur">Emnestruktur</Link>. Hvert funn forklarer hva, hvor, hvorfor og hvordan det kan rettes.</> },
    { title: "Godkjenn forbedringer", body: <>Forhåndsvis en løsning og legg den i endringskøen. Ingenting sendes til Canvas før du gjennomfører endringene.</> },
    { title: "Gjennomfør endringer", body: <>Åpne endringskøen øverst til høyre, se over endringene og gjennomfør dem. Innholdet sikkerhetskopieres først, og endringen logges. Med Dry run på sendes ingenting.</> },
  ];
  return (
    <div className="ek-stack" data-gap="6">
      <ol className="ek-list-reset ek-stack" data-gap="2">
        {steps.map((step, i) => (
          <li key={step.title} className="ek-card" style={{ padding: "1rem 1.25rem" }}>
            <div className="ek-cluster" data-align="start" data-gap="4">
              <span className="ek-steps__num" aria-hidden="true">{i + 1}</span>
              <div className="ek-stack" data-gap="1" style={{ flex: 1 }}>
                <h2 style={{ fontSize: "var(--text-md)" }}>
                  <span className="ek-visually-hidden">Steg {i + 1}: </span>
                  {step.title}
                </h2>
                <p className="ek-small">{step.body}</p>
              </div>
            </div>
          </li>
        ))}
      </ol>
      <Alert tone="info" title="Prøv trygt med Dry run">
        Slå på Dry run øverst på siden hvis du vil prøve alt uten at noe sendes til Canvas.
      </Alert>
    </div>
  );
}

function Guides() {
  return (
    <div className="ek-prose">
      <h2 id="oversikt">Oversikt</h2>
      <p>Oversikten viser status for hvert område for emnet du har valgt, anbefalte neste steg og siste aktivitet. EmneKlar viser ingen samlet «prosent universelt utformet», fordi automatiske kontroller ikke kan måle det.</p>
      <h2 id="analyse">Analyse og fremdrift</h2>
      <p>«Kjør ny analyse» lar deg velge hele emnet, bestemte moduler eller enkeltelementer, og hvilke områder som skal kontrolleres. EmneKlar laster ned emnet én gang og gjenbruker det for alle områdene. Fremdriften viser prosent, element X av Y, hva som kontrolleres nå og estimert tid. Tiden beregnes ut fra hvor lang tid kontrollene faktisk tar, og vises som et intervall når usikkerheten er stor. Du kan sette analysen på pause, avbryte den eller la den kjøre i bakgrunnen.</p>
      <h2 id="universell-utforming">Universell utforming</h2>
      <p>Funnene deles i <strong>Avvik</strong>, <strong>Sannsynlig avvik</strong>, <strong>Bør vurderes</strong>, <strong>Forbedringsforslag</strong> og <strong>Manuell kontroll</strong>. Hvert funn viser kriterium, juridisk status i den valgte regulatoriske profilen, testmetode og forslag til retting. Profilen velges under <Link to="/innstillinger/analyse">Innstillinger → Analyse</Link>.</p>
      <p>Bruk «Forhåndsvis løsning» for å se endringen før den legges i endringskøen. Forslag til alt-tekst fra KI er alltid merket og må vurderes av deg.</p>
      <h2 id="innholdskvalitet">Innholdskvalitet</h2>
      <p>Kontrollerer lenker, innebygde videoer og HTML-kode. Lenker får status Virker, Omdirigeres, Død, Tidsavbrudd, Krever innlogging eller Ukjent. Tidsavbrudd og 403 betyr ikke at lenken er død. EmneKlar sletter aldri lenker automatisk; du velger selv ny adresse eller å fjerne lenken og beholde teksten. Opprydding i kode endrer ikke tekst, lenker eller innebygd innhold.</p>
      <h2 id="emnestruktur">Emnestruktur</h2>
      <p>Gir råd om plassering, rekkefølge, navngiving og introduksjoner, med begrunnelse, belegg og sikkerhet (høy, middels eller lav). Ingenting flyttes før du har godkjent forslaget og gjennomført det fra endringskøen. «Studentreisen» viser rekkefølgen studentene møter innholdet i.</p>
      <h2 id="quizassistent">Quizassistent</h2>
      <p><strong>Eksisterende quizer:</strong> kontrollerer klassiske quizer for blant annet manglende eller doble fasiter, like alternativer og duplikater. KI-vurderingen sammenligner spørsmålene med teksten i emnet og viser kildesitater; påstander om feil fasit uten bekreftet kilde forkastes. Fasit endres aldri automatisk.</p>
      <p><strong>KI-spørsmålsbank:</strong> EmneKlars eget arbeidsområde. Spørsmål lages bare fra emnets innhold, med kilde og sitat, og havner som utkast. Godkjenn de du vil bruke.</p>
      <p><strong>Lag ny quiz:</strong> velg godkjente spørsmål, innstillinger eller en forhåndsinnstilling, og eventuelt et tilfeldig utvalg («X av Y»). Quizen opprettes upublisert som standard.</p>
      <h2 id="emneforside">Emneforside</h2>
      <p>Velg «Kun design», «Design + innhold» eller «Forbedre eksisterende forside», en stil og seksjoner. Innhold EmneKlar ikke kan vite, merkes «Fyll inn». Forhåndsvis på PC, nettbrett og mobil. «Opprett som ny side» er det trygge valget; «Erstatt eksisterende forside» krever bekreftelse og tar sikkerhetskopi først.</p>
      <h2 id="canvas-verktoy">Canvas-verktøy</h2>
      <p><strong>Automatiske modulkrav</strong> foreslår fullføringskrav per elementtype. <strong>Blueprint-låsing</strong> virker bare i Blueprint-emner. <strong>Canvas-innstillinger</strong> deler funn i tekniske problemer, sikkerhet og tilgjengelighet, anbefalinger og preferanser – preferanser endres aldri automatisk. <strong>Backup og endringslogg</strong> viser alt som er endret, med angring der det er trygt.</p>
      <h2 id="endringsko">Endringskøen og Dry run</h2>
      <p>Alle endringer i Canvas går gjennom endringskøen: forhåndsvisning, godkjenning, kontroll av at innholdet ikke er endret i mellomtiden, sikkerhetskopi, endring og logg. Endringer med høy risiko må bekreftes ekstra. Med Dry run på sendes ingen endringer til Canvas, men alt annet virker.</p>
      <h2 id="rapporter">Rapporter</h2>
      <p>Lag rapporter som HTML eller CSV. HTML-rapporten kan skrives ut eller lagres som PDF fra nettleseren. Rapportene viser omfang, dato, regelsett, funn, manuelle kontroller, rettede og gjenstående funn og begrensninger. De er ikke en sertifisering.</p>
    </div>
  );
}

function Faq() {
  const items: [string, ReactNode][] = [
    ["Kan EmneKlar bekrefte at emnet er universelt utformet?", "Nei. Automatiske kontroller finner mange vanlige feil, men mange krav kan bare vurderes av et menneske. Funn merket «Manuell kontroll» og innhold i eksterne verktøy må du vurdere selv."],
    ["Endrer EmneKlar noe i Canvas uten at jeg vet det?", "Nei. Analyser leser bare. Endringer skjer først når du gjennomfører dem fra endringskøen, og alt logges. Med Dry run på sendes ingenting."],
    ["Hvor lagres Canvas-tokenet?", "I Windows Legitimasjonsbehandling. Det lagres aldri i filer, i databasen, i nettleseren eller i logger."],
    ["Sender EmneKlar innhold til KI?", "Bare hvis du har satt opp en KI-leverandør og slått på «Tillat sending av emneinnhold til ekstern KI». Du ser hva som sendes før det sendes. Studentenes innleveringer, karakterer og meldinger sendes aldri."],
    ["Hvorfor er en lenke merket «Krever innlogging» eller «Tidsavbrudd»?", "Noen nettsteder krever innlogging, avviser automatiske besøk eller svarer tregt. Det betyr ikke at lenken er død. Kontroller den i nettleseren."],
    ["Kan jeg angre en endring?", "Ofte, men ikke alltid. Under Canvas-verktøy → Backup og endringslogg kan du angre endringer når Canvas gjør det mulig og innholdet ikke er endret av andre etterpå."],
    ["Hvorfor kontrolleres ikke spørsmål fra spørsmålsbanker?", "Canvas-API-et gir ikke tilgang til spørsmål som trekkes fra spørsmålsbanker via quizen. EmneKlar sier fra når en quiz bruker slike grupper."],
    ["Støttes nye quizer (New Quizzes)?", "Ikke i denne versjonen. Quizassistenten virker med klassiske quizer."],
    ["Hvorfor er Blueprint-låsing ikke tilgjengelig?", "Låsing kan bare gjøres i selve Blueprint-emnet. Om et emne er Blueprint-emne, bestemmes av Canvas-administratoren."],
    ["Hva skjer når jeg oppdaterer EmneKlar?", "Oppdateringen stopper programmet, tar sikkerhetskopi av databasen, installerer den nye versjonen, sjekker at den virker og starter på nytt. Går noe galt, settes forrige versjon tilbake. Dataene dine ligger utenfor programmappen og blir ikke slettet."],
  ];
  return (
    <ul className="ek-list-reset ek-stack" data-gap="2">
      {items.map(([q, a]) => (
        <li key={q} className="ek-card" style={{ padding: "0.75rem 1rem" }}>
          <Disclosure summary={q}>
            <p className="ek-small">{a}</p>
          </Disclosure>
        </li>
      ))}
    </ul>
  );
}

function Tips() {
  return (
    <div className="ek-prose">
      <h2>Bilder</h2>
      <ul>
        <li>Beskriv hva bildet formidler i sammenhengen, ikke bare hvordan det ser ut.</li>
        <li>Bruk tom alt-tekst bare når bildet er ren pynt.</li>
        <li>Komplekse figurer trenger i tillegg en lengre beskrivelse i teksten. <ExternalLink href="https://www.w3.org/WAI/tutorials/images/complex/">W3C: komplekse bilder</ExternalLink></li>
      </ul>
      <h2>Overskrifter og lenker</h2>
      <ul>
        <li>Bruk overskrifter i riktig rekkefølge (Overskrift 2, deretter 3). Sidetittelen er allerede overskrift 1. <ExternalLink href="https://www.w3.org/WAI/tutorials/page-structure/headings/">W3C: overskrifter</ExternalLink></li>
        <li>Skriv lenketekster som sier hvor lenken går – unngå «klikk her». <ExternalLink href="https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html">WCAG 2.4.4</ExternalLink></li>
      </ul>
      <h2>Video og dokumenter</h2>
      <ul>
        <li>Video med tale trenger teksting. EmneKlar kan bare kontrollere teksting i Canvas Studio-/mediefiler, ikke for eksempel YouTube. <ExternalLink href="https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded.html">WCAG 1.2.2</ExternalLink></li>
        <li>Lag dokumenter med innebygde overskrifter og alt-tekst før du lager PDF. En tagget PDF er ikke automatisk tilgjengelig.</li>
      </ul>
      <h2>Emnestruktur og quizer</h2>
      <ul>
        <li>Gi modulene et fast navnemønster og en kort introduksjon.</li>
        <li>Skriv spørsmål med én tydelig riktig fasit, troverdige feilsvar og uten «alle de ovennevnte» når svarene blandes.</li>
        <li>Gi studenter med tilrettelegging ekstra tid i Canvas når quizen har tidsbegrensning.</li>
      </ul>
      <p>Mer om lærerens ansvar: <ExternalLink href="https://www.uutilsynet.no/veiledning/laererens-ansvar-universell-utforming/2675">Uutilsynet: Lærerens ansvar for universell utforming</ExternalLink></p>
    </div>
  );
}

function Troubleshooting() {
  const items: [string, ReactNode][] = [
    ["«Økten er ikke gyldig»", "Start EmneKlar med start.bat. Nettleseren åpnes da med en ny innlogging. Data og innstillinger påvirkes ikke."],
    ["«Canvas avviste tokenet»", <>Tokenet kan være utløpt eller slettet. Lag et nytt i Canvas og legg det inn under <Link to="/innstillinger/canvas-tilkobling">Canvas-tilkobling</Link>.</>],
    ["«Canvas ber EmneKlar vente»", "Canvas begrenser antall forespørsler. EmneKlar venter og prøver igjen automatisk. Du kan senke «Samtidige forespørsler til Canvas» under Innstillinger → Analyse."],
    ["«Fant ingen sikker nøkkelring»", "EmneKlar trenger Windows Legitimasjonsbehandling for å lagre token. Kontakt IT-støtte hvis den er sperret på maskinen."],
    ["Endringen havnet i «Konflikt»", "Innholdet ble endret i Canvas etter at forslaget ble laget. Kjør analysen på nytt og lag et nytt forslag. EmneKlar overskriver aldri nyere arbeid."],
    ["Analysen tar lang tid", "Store emner med mange lenker og dokumenter tar tid. Du kan kjøre analysen i bakgrunnen, analysere bare valgte moduler, eller slå av dokumentkontroll under Innstillinger → Analyse."],
  ];
  return (
    <div className="ek-stack" data-gap="6">
      <ul className="ek-list-reset ek-stack" data-gap="2">
        {items.map(([q, a]) => (
          <li key={q} className="ek-card" style={{ padding: "0.75rem 1rem" }}>
            <Disclosure summary={q}><p className="ek-small">{a}</p></Disclosure>
          </li>
        ))}
      </ul>
      <Card title="Feilsøkingsinformasjon" headingLevel={2}>
        <div className="ek-stack">
          <p className="ek-small">Kopier informasjon om versjon og oppsett når du ber om hjelp. Loggen finner du under <Link to="/innstillinger/avanserte-innstillinger">Avanserte innstillinger</Link>.</p>
          <div><CopyDiagnostics /></div>
        </div>
      </Card>
    </div>
  );
}

function Contact() {
  const status = useQuery({ queryKey: ["update-status"], queryFn: () => api.get<UpdateStatus>("/api/updates/status") });
  const repo = status.data?.repository;
  return (
    <div className="ek-stack" data-gap="6">
      {repo ? (
        <Card title="Meld feil eller foreslå forbedringer" headingLevel={2}>
          <p className="ek-small">EmneKlar utvikles på GitHub. Der kan du melde feil og foreslå forbedringer.</p>
          <p className="ek-mt-2"><ExternalLink href={`https://github.com/${repo}/issues`}>github.com/{repo}/issues</ExternalLink></p>
        </Card>
      ) : (
        <Card title="Hjelp og tilbakemelding" headingLevel={2}>
          <p className="ek-small">Kontakt den som har installert EmneKlar for deg, eller IT-støtten ved institusjonen din.</p>
        </Card>
      )}
      <Card title="Når du ber om hjelp" headingLevel={2}>
        <div className="ek-stack">
          <p className="ek-small">Beskriv hva du gjorde og hva som skjedde, og legg ved feilsøkingsinfo. Del aldri Canvas-token eller API-nøkler.</p>
          <div><CopyDiagnostics /></div>
        </div>
      </Card>
    </div>
  );
}

function About() {
  const session = useSession();
  return (
    <div className="ek-prose">
      <p><strong>EmneKlar {session.app.version}</strong> er et lokalt verktøy for analyse, kvalitetssikring og trygg forbedring av emner i Canvas.</p>
      <h2>Prinsipper</h2>
      <ul>
        <li>Analyser – forklar – foreslå – forhåndsvis – godkjenn – endre – logg.</li>
        <li>Kjører bare på denne maskinen. Data lagres i %LOCALAPPDATA%\EmneKlar-Claude, adskilt fra programmet.</li>
        <li>Alle endringer i Canvas går via endringskøen, med sikkerhetskopi og logg.</li>
        <li>KI er valgfritt, og ingenting sendes til ekstern KI uten at du har slått det på.</li>
        <li>Juridisk status for universell utforming kommer fra versjonerte regelsett og profiler, ikke fra automatisk testing alene.</li>
      </ul>
      <h2>Kilder</h2>
      <ul>
        <li><ExternalLink href="https://developerdocs.instructure.com/services/canvas">Canvas REST API (Instructure)</ExternalLink></li>
        <li><ExternalLink href="https://lovdata.no/dokument/SF/forskrift/2013-06-21-732">Forskrift om universell utforming av IKT-løsninger (Lovdata)</ExternalLink></li>
        <li><ExternalLink href="https://lovdata.no/dokument/NL/lov/2017-06-16-51">Likestillings- og diskrimineringsloven (Lovdata)</ExternalLink></li>
        <li><ExternalLink href="https://www.uutilsynet.no/wcag-standarden/wcag-standarden/86">Uutilsynet: WCAG-standarden</ExternalLink></li>
        <li><ExternalLink href="https://www.w3.org/WAI/standards-guidelines/wcag/">W3C WAI: WCAG</ExternalLink></li>
      </ul>
    </div>
  );
}

export function HelpPage() {
  const { topic = "kom-i-gang" } = useParams();
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    if (target) {
      target.scrollIntoView({ block: "start" });
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    }
  }, [hash, topic]);
  const current = TOPICS.find((t) => t.slug === topic);
  usePageTitle(current ? `${current.label} – Hjelp` : "Hjelp");
  if (!current) return <Navigate to="/hjelp" replace />;
  const body = {
    "kom-i-gang": <GettingStarted />,
    brukerveiledninger: <Guides />,
    "vanlige-sporsmal": <Faq />,
    tips: <Tips />,
    feilsoking: <Troubleshooting />,
    kontakt: <Contact />,
    om: <About />,
  }[current.slug];
  return (
    <>
      <PageHeader title="Hjelp" description={current.label} />
      <div className="ek-sidebar-layout">
        <nav aria-label="Hjelp">
          <ul className="ek-subnav">
            {TOPICS.map((t) => (
              <li key={t.slug}>
                <Link to={`/hjelp/${t.slug}`} aria-current={t.slug === current.slug ? "page" : undefined}>
                  <t.icon aria-hidden="true" />
                  {t.label}
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
