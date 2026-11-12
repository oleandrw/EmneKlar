import { useQuery } from "@tanstack/react-query";
import { BookOpen, Copy, Info, LifeBuoy, Lightbulb, MessageSquare, MessagesSquare, Rocket, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router";

import { api } from "../../core/api/client";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
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
  const steps: { title: string; body: ReactNode }[] = [
    { title: "Koble til Canvas", body: <>Legg inn adressen til Canvas og et API-token under <Link to="/innstillinger/canvas-tilkobling">Canvas-tilkobling</Link>. Tokenet lagres i Windows Legitimasjonsbehandling.</> },
    { title: "Velg emne", body: <>Velg emnet i emnevelgeren øverst på siden. Valget gjelder alle deler av EmneKlar til du bytter.</> },
    { title: "Kjør analyse", body: <>Bruk analyseknappen øverst til høyre. Den følger siden du står på: «Analyser hele emnet» på Oversikt, «Analyser universell utforming» på Universell utforming og så videre. Velg omfang (hele emnet, moduler eller enkeltelementer) og følg fremdriften under «Analysestatus». Analysen leser bare fra Canvas.</> },
    { title: "Gjennomgå funn", body: <>Se funnene under <Link to="/universell-utforming">Universell utforming</Link>, <Link to="/innholdskvalitet">Innholdskvalitet</Link> og <Link to="/emnestruktur">Emnestruktur</Link>. Hvert funn forklarer hva, hvor, hvorfor og hvordan det kan rettes.</> },
    { title: "Godkjenn forbedringer", body: <>Forhåndsvis en løsning og legg den i endringskøen. Ingenting sendes til Canvas før du gjennomfører endringene.</> },
    { title: "Gjennomfør endringer", body: <>Åpne endringskøen øverst til høyre, godkjenn dem og velg «Publiser til Canvas». Innholdet sikkerhetskopieres først, og endringen logges. Ingenting sendes før du publiserer.</> },
  ];
  return (
    <div className="ek-stack" data-gap="6">
      <ol className="ek-list-reset ek-stack" data-gap="2">
        {steps.map((step, i) => (
          <li key={step.title} className="ek-card ek-card--compact">
            <div className="ek-cluster" data-align="start" data-gap="4">
              <span className="ek-steps__num" aria-hidden="true">{i + 1}</span>
              <div className="ek-stack ek-grow" data-gap="1">
                <h2 className="ek-title-sm">
                  <span className="ek-visually-hidden">Steg {i + 1}: </span>
                  {step.title}
                </h2>
                <p className="ek-small">{step.body}</p>
              </div>
            </div>
          </li>
        ))}
      </ol>
      <Alert tone="info" title="Ingenting endres før du publiserer">
        Analyser, forhåndsvisninger og godkjenning endrer aldri noe i Canvas. Endringer sendes først når du velger
        «Publiser til Canvas» i endringskøen.
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
      <p>Analyseknappen øverst til høyre følger siden du står på: på Oversikt heter den «Analyser hele emnet» og lar deg velge områder, på Universell utforming, Innholdskvalitet, Emnestruktur og Quizassistent analyserer den bare det området. Du velger hele emnet (standard), bestemte moduler eller enkeltelementer. Sider uten egen analyse har ingen analyseknapp. EmneKlar laster ned emnet én gang og gjenbruker det for alle områdene. Analysen kjører i bakgrunnen, også når du bytter side. <strong>Analysestatus</strong>, til venstre for analyseknappen, samler bakgrunnsjobbene som pågår, venter eller har stoppet, og de siste fullførte – og viser hva EmneKlar gjør nå. Hele historikken står under Rapporter. Når omfanget er kjent, vises antall og prosent; før det står det at antallet foreløpig er ukjent. Analyseknappen viser samme status og er sperret så lenge en analyse av emnet pågår. Under «Detaljer» ser du element X av Y og estimert tid, som beregnes ut fra hvor lang tid kontrollene faktisk tar og vises som et intervall når usikkerheten er stor. Du kan sette analysen på pause eller avbryte den. Til den nye analysen er ferdig, vises resultatene fra forrige analyse med sitt eget tidspunkt. En jobb som feilet eller ble avbrutt, blir stående til du velger «Skjul» eller «Prøv igjen». Fullførte jobber forsvinner av seg selv etter et døgn, eller med «Fjern fullførte». Det endrer verken resultatene eller historikken.</p>
      <h2 id="universell-utforming">Universell utforming</h2>
      <p>Funnene deles i <strong>Avvik</strong>, <strong>Sannsynlig avvik</strong>, <strong>Bør vurderes</strong>, <strong>Forbedringsforslag</strong> og <strong>Manuell kontroll</strong>. Hvert funn viser kriterium, juridisk status i den valgte regulatoriske profilen, testmetode og forslag til retting. Profilen velges under <Link to="/innstillinger/analyse">Innstillinger → Analyse</Link>.</p>
      <p>Bruk «Forhåndsvis løsning» for å se endringen før den legges i endringskøen. Forslag til alt-tekst fra KI er alltid merket og må vurderes av deg.</p>
      <p><strong>Godkjenn alle klare</strong> godkjenner rettingene som er <em>klare</em> i hele utvalget du ser på (alle sider): rettinger som er bestemt av funnet, så du ikke må velge noe først – for eksempel å gjøre tekst som bare ser ut som en liste, om til en ekte liste. Regelbaserte tekstforslag kan du velge å ta med. KI-forslag er aldri med; de vurderer du ett for ett. Er ingenting klart, er knappen ikke tilgjengelig.</p>
      <p><strong>KI-forslag i rettevinduet:</strong> for lenketekst, tabelltitler og tittel på innebygd innhold kan du velge «Foreslå … med KI» ved tekstfeltet. Første gang ser du hva som sendes og til hvilken tjeneste; samme type forslag spørres ikke igjen i økten. Under forslaget står hva det bygger på – for lenker om målsiden faktisk ble lest eller bare adressen og teksten rundt. Forslaget er merket «KI-forslag – må vurderes», kan redigeres og legges i endringskøen først når du godkjenner. Har du skrevet noe selv, byttes det ikke ut før du velger «Bruk forslaget». «Godkjenn alle klare» tar aldri med KI-forslag. Uten en KI-tjeneste vises en lenke til oppsettet, og du skriver teksten selv.</p>
      <p><strong>Tittel på innebygde YouTube-videoer:</strong> når en video mangler tittel, fyller EmneKlar inn videoens egen tittel fra YouTube. Svarer ikke YouTube, eller er tittelen der ubrukelig, lages et forslag ut fra sidetittelen og overskriften rundt videoen. Kilden står under feltet. Er det ikke noen god tittel å hente, kan du be om et KI-forslag; du ser først hva som sendes. Har YouTube en tittel, kan du likevel velge «Se hva KI foreslår» for å sammenligne, og gå tilbake til YouTube-tittelen med «Bruk forslaget». Det du selv har skrevet, byttes aldri ut. Skal mange videoer få tittel samtidig, bruk <strong>Standardiser videoavspillere</strong> under Innholdskvalitet.</p>
      <h2 id="innholdskvalitet">Innholdskvalitet</h2>
      <p>Her heter de sikreste funnene <strong>Feil</strong> og <strong>Sannsynlig feil</strong> (for eksempel en død lenke) – «avvik» brukes bare om brudd på krav til universell utforming.</p>
      <p>Kontrollerer lenker, innebygde videoer og HTML-kode. Under <strong>Lenker</strong> står én rad per lenke med kontrollresultat, hvor den er brukt og hva du kan gjøre. Resultatet er <strong>Fungerer</strong>, <strong>Fungerer ikke</strong> (en konkret feil er påvist, for eksempel 404, eller en intern lenke til innhold som ikke finnes i emnet – merket «Intern lenke»), <strong>Krever innlogging</strong> (påvist) eller <strong>Kunne ikke kontrolleres</strong> (for eksempel tidsavbrudd eller 403 – ikke bevis for at lenken er død). Teknisk årsak, HTTP-status og kontrollmetode står under «Tekniske detaljer». «Sjekk på nytt» oppdaterer raden og totalene; interne lenker kontrolleres på nytt når du analyserer innholdskvaliteten. «Døde lenker» på Oversikt er det samme tallet som «Fungerer ikke» her – én per adresse – og lenken derfra åpner nettopp disse radene. «Endre lenke» og «Endre flere steder» endrer bare stedene du velger: du ser gammel og ny adresse og en forhåndsvisning før du godkjenner til endringskøen, og lenketeksten, bilder i lenken og andre egenskaper beholdes med mindre du velger å endre teksten. «Finn alternativ lenke med KI» foreslår opptil tre erstatninger fra faktisk nettsøk (via KI-tjenesten, når den har søk), adressen lenken sender videre til og arkiverte kopier i Internet Archive – aldri adresser KI-en finner på. Hvert forslag viser kilde, begrunnelse, om det er samme ressurs, et alternativ eller en arkivert kopi, og teknisk kontroll med tidspunkt; at en side svarer, betyr ikke at den passer faglig. Finnes ingen gode forslag, står det, og du kan søke selv. Under «Brukt på …» åpner «Rett funnet» funnet for ett sted, der du også kan fjerne lenken og
        beholde teksten. EmneKlar sletter aldri lenker automatisk.</p>
      <p><strong>Media – Standardiser videoavspillere:</strong> finner YouTube-videoer og foreslår én responsiv standard (16:9, maks bredde, sentrert) med beskrivende title. Tittelen hentes i denne rekkefølgen: en god eksisterende title, YouTube-metadata, overskriften og sidetittelen rundt videoen, et KI-forslag (bare når du ber om det) eller det du skriver selv – kilden vises alltid. Forhåndsvis før og etter på PC, nettbrett og mobil, og godkjenn videoene én og én eller alle kompatible samtidig. Endringene legges i endringskøen, og bare koden for selve videoen endres. En god title betyr ikke at videoen er universelt utformet; teksting, transkripsjon og synstolking vurderes separat.</p>
      <h2 id="emnestruktur">Emnestruktur</h2>
      <p>Gir råd om plassering, rekkefølge, navngiving og introduksjoner, med begrunnelse, belegg og sikkerhet (høy, middels eller lav). Ingenting flyttes før du har godkjent forslaget og gjennomført det fra endringskøen. «Studentreisen» viser rekkefølgen studentene møter innholdet i.</p>
      <h2 id="quizassistent">Quizassistent</h2>
      <p><strong>Eksisterende quizer:</strong> kontrollerer klassiske quizer for blant annet manglende eller doble fasiter, like alternativer og duplikater. KI-vurderingen sammenligner spørsmålene med teksten i emnet og viser kildesitater; påstander om feil fasit uten bekreftet kilde forkastes. Fasit endres aldri automatisk. Funnene heter <strong>Feil</strong> og <strong>Sannsynlig feil</strong> – ikke «avvik», som bare brukes om universell utforming.</p>
      <p><strong>KI-spørsmålsbank:</strong> EmneKlars eget arbeidsområde. Spørsmål lages bare fra emnets innhold, med kilde og sitat, og havner som utkast. Godkjenn de du vil bruke.</p>
      <p><strong>Lag ny quiz:</strong> velg godkjente spørsmål, innstillinger eller en forhåndsinnstilling, og eventuelt et tilfeldig utvalg («X av Y»). Quizen opprettes upublisert som standard.</p>
      <h2 id="emnedesign">Emnedesign</h2>
      <p>Under <strong>Emnedesign</strong> i menyen gir du hele emnet eller én modul ett helhetlig design i fire steg: Omfang, Design, Forhåndsvisning og Godkjenning. I første steg velger du hele emnet eller én modul og ser hva som faktisk blir berørt: hvor mange sider, oppgaver og quizer som kan få designet, hva som hoppes over, hva som er delt med andre moduler eller låst fra Blueprint, og hva Emnedesign ikke støtter. Hvert innholdselement telles én gang, også når det brukes i flere moduler; fordelingen per innholdstype ligger under «Se fordeling», og Blueprint forklares samlet for utvalget (detaljer under «Se Blueprint-detaljer»). «Neste: velg design» blir tilgjengelig når innholdet er lest fra Canvas. Designene er <strong>Akademisk</strong> (standard), <strong>Lyst og moderne</strong>, <strong>Visuelt og pedagogisk</strong> og <strong>Grønn akademi</strong>; alle kan forhåndsvises med samme eksempelinnhold og fungerer uten bilder. Designet brukes på forsiden (Emnedesign lager ingen ny forside – har emnet ingen, lager du en side i Canvas og gjør den til forside først), emneplanen, modulintroduksjoner (den første siden i en modul), innholdssider, oppgavebeskrivelser og innledningen i klassiske quizer. New Quizzes, quizspørsmål, diskusjoner og Canvas' eget grensesnitt (navigasjon, sidetitler, innleveringsknapper, quizkontroller) endres ikke – det står i listen «Ikke med i Emnedesign».</p>
      <p><strong>Behold oppbyggingen</strong> gir innholdet valgt stil uten å flytte eller skrive om noe. <strong>Foreslå bedre oppbygging</strong> lar KI foreslå seksjoner og plassering av eksisterende innhold side for side (du ser hva som sendes, og godkjenner først); den finner ikke på læringsmål eller annet faglig innhold, og hver strukturendring vises før du godkjenner. Begge bevarer frister, poeng, fasit, vurderingsregler, innleveringsinnstillinger, lenker, bilder med alt-tekst, tabeller, ligninger, kode og innebygd innhold – et forslag som ville endret noe av dette, stoppes. Du kan bruke designet på nytt eller bytte design uten at formateringen legges oppå hverandre.</p>
      <p>Forslagene publiseres fra endringskøen med «Publiser til Canvas»: innholdet kontrolleres mot Canvas, sikkerhetskopieres og kan angres. Er en side endret i Canvas etter forhåndsvisningen, legges den ikke i køen før du forhåndsviser på nytt. Brukes samme side i flere moduler, gjelder endringen den delte siden overalt – det lages ingen kopier. «Lagre som emnets design» husker profilen og versjonen uten å endre innhold, og «Behold eksisterende design» holder et element utenfor.</p>
      <h2 id="canvas-verktoy">Canvas-verktøy</h2>
      <p><strong>Automatiske modulkrav</strong> foreslår fullføringskrav per elementtype. <strong>Blueprint-låsing</strong> virker bare i Blueprint-emner. <strong>Canvas-innstillinger</strong> kontrollerer at studentene kan gjøre og levere arbeidet: at oppgaver har en innleveringsmåte når de gir poeng, at datoene henger sammen (åpner før fristen, stenges ikke før fristen eller før de åpner), at oppgaver er tildelt noen, og at oppgaver og quizer med frist de neste 14 dagene er publisert. I tillegg meldes sikkerhetsrisikoer, som et offentlig emne eller sider alle kan redigere. Funnene deles i tekniske problemer, sikkerhet, anbefalinger og preferanser – preferanser endres aldri automatisk. Valg som tidsbegrensning og låst rekkefølge i quizer er lærerens og meldes ikke. <strong>Sikkerhetskopier og endringslogg</strong> viser hva som er endret i hvert innhold, status og tidspunkt, med sikkerhetskopier og angring der det er trygt. Det samme vises under «Siste handlinger» nederst på siden.</p>
      <p>Verktøyene endrer ingenting i Canvas direkte: du forhåndsviser og godkjenner endringene, og de publiseres fra endringskøen i topplinjen med «Publiser til Canvas» (se <a href="#endringsko">Endringskøen og publisering</a>). Det eneste unntaket er «Automatisk innsetting» i KI-bildeassistenten, som du må velge selv (se <a href="#bildeassistent">KI-bildeassistent</a>). <strong>Emnets kunnskapsbase</strong> lagres lokalt på denne maskinen og synkroniseres ikke til andre maskiner. Blueprint-låsing er bare tilgjengelig i Blueprint-emner, og mangler du tilgang i Canvas, står det på verktøyet.</p>
      <h2 id="emne-rag">Emnets kunnskapsbase</h2>
      <p>Under <strong>Canvas-verktøy → Emnets kunnskapsbase</strong> lager du en lokal kunnskapsbase av emnet og stiller spørsmål til den. Velg hele emnet eller enkelte moduler og trykk «Opprett kunnskapsbase». Alle kildetyper er med som standard (Canvas-tekst, dokumenter, video, lyd og bilder); under «Tilpass kilder» kan du slå av kilder og filtyper, og under «Avansert» velge KI-tillegg og transkriberingstjeneste – der står det også hva som kan gi ekstra kostnad. Velger du moduler, tas alt i dem med, også det som ikke er publisert ennå. For hele emnet må du slå på «Ta med upubliserte elementer» for å få med upublisert innhold. Lastes noe ned første gang eller sendes noe til en KI-leverandør, ser du først et estimat med hvor mye som leses, omtrentlig tid og hva som sendes, og godtar det; ellers starter byggingen med en gang. Byggingen går i bakgrunnen, kan settes på pause og avbrytes, og «Oppdater kunnskapsbasen» fortsetter der den slapp.</p>
      <p>Bare lærerens innhold leses: sider, oppgave- og quizbeskrivelser, emneplan, lærerens diskusjonsinnlegg og filer lastet opp av lærere. Innleveringer, karakterer, meldinger og studentenes innlegg hentes aldri. Ingenting endres i Canvas.</p>
      <p>«Søk i emnet» virker uten KI og viser de mest relevante utdragene med klikkbare kilder. «Svar med KI» lager et svar der hver påstand har kildehenvisning; svaret er et KI-forslag som må vurderes. Uten KI-leverandør brukes nøkkelordsøk og eksisterende teksting. Semantisk søk og transkripsjon av video uten teksting får du ved å velge en KI-leverandør under Innstillinger i kunnskapsbasen. Lokale modeller følger ikke med EmneKlar.</p>
      <p>Video bruker eksisterende teksting først (Canvas, undertekstfiler, YouTube, Vimeo) og transkriberes ellers lokalt med NB-Whisper – eller av OpenAI, Azure OpenAI eller en egen server hvis du velger det under «Innstillinger». Da sendes bare lyden, og bare etter at du har godtatt det i estimatet. Elementer som venter på samtykke eller en innstilling, prøves igjen ved neste «Oppdater kunnskapsbasen». Bilder beskrives av bildemodellen i KI-oppsettet etter at pynt, ikoner og duplikater er filtrert bort. Under «Kvalitet» ser du en helsescore for søket: den måler om søket finner tilbake utdraget et testspørsmål ble laget fra – ikke hvor gode svarene er. Under «Eksport» kan du laste ned kunnskapsbasen som ZIP for andre RAG-verktøy, eller som Word, PDF, Markdown eller tekst.</p>
      <h2 id="bildeassistent">KI-bildeassistent</h2>
      <p>Under <strong>Canvas-verktøy → KI-bildeassistent</strong> lager du illustrasjoner til emnet i fem steg. <strong>1. Velg innhold:</strong> hele emnet, én modul, flere moduler eller én side. <strong>2. Bildeinnstillinger:</strong> kvalitet (Balansert er standard, Maksimal kvalitet eller Rask), antall illustrasjoner (Lav, Balansert eller Høy) og designprofil. EmneKlar velger selv de beste tilgjengelige KI-modellene; modeller, bildeformat, visningsbredde og kostnader finner du under «Avanserte innstillinger». <strong>3. Analyser:</strong> EmneKlar leser emnet i Canvas og viser kort hva som sendes til hvilke tjenester. Når du har godkjent det, analyserer KI innholdet og foreslår bilder og plassering – bare der de gir faglig verdi.</p>
      <p><strong>Plassering og plan:</strong> KI leser sidens oppbygging og lager først en kort plan for hvert bilde: hvilket faglig poeng det skal gjøre lettere å forstå, hva det konkret viser, og hvor det skal stå og hvorfor. Bildet plasseres etter en avsluttet forklaring det støtter – aldri mellom en innledende setning og listen etter den, en overskrift og første avsnitt, et eksempel og forklaringen eller et bilde og bildeteksten. Tilfører et bilde ikke noe, anbefaler assistenten å la være.</p>
      <p><strong>4. Generer og gjennomgå:</strong> bildene lages og kontrolleres av en bildeanalysemodell, som også foreslår alternativ tekst og bildetekst. Hvert bilde vises i et utdrag av siden med teksten rett før og etter, sammen med begrunnelsen for plasseringen, og du kan flytte det («Flytt opp», «Flytt ned» eller et annet sted) før du godkjenner. Se også hele siden (PC, nettbrett og mobil), og godkjenn, avvis, endre eller lag bildene på nytt – ett bilde, en side, en modul eller alt. Diagrammer og modeller kan ha korte etiketter på innholdets språk; ellers er bildene uten tekst. Bilder med komplekst faglig innhold merkes «Manuell kontroll»: KI kan ikke garantere at et bilde er faglig riktig. Alt er KI-forslag som må vurderes.</p>
      <p><strong>5. Publiser:</strong> bare godkjente bilder lastes opp til Canvas-filene og settes inn mellom avsnittene via endringskøen – med mindre du har valgt <strong>Automatisk innsetting</strong> i steg 3. Da godkjenner og publiserer kjøringen selv bildene som består kvalitetskontrollen, uten at du ser dem først; bilder som må kontrolleres, venter alltid på deg. Også da går alt via endringskøen med konfliktsjekk, sikkerhetskopi, logg og angremulighet. Eksisterende tekst endres ikke, sidens publiseringsstatus beholdes, og bildene vises høyst 900 piksler brede og 560 piksler høye og tilpasser seg mobil og nettbrett. Før innsetting kontrolleres det at stedet på siden fortsatt finnes. Kreditering («KI-generert illustrasjon») står som en egen linje under bildeteksten. «Angre på denne siden» fjerner bare EmneKlars figurer; det du har endret selv, beholdes. Kjører du assistenten på nytt, gjenkjennes eksisterende illustrasjoner, så det blir ikke dubletter.</p>
      <h2 id="endringsko">Endringskøen og publisering</h2>
      <p>Alle endringer i Canvas går gjennom endringskøen: forhåndsvisning, godkjenning, kontroll av at innholdet ikke er endret i mellomtiden, sikkerhetskopi, endring og logg. Velger du «Automatisk innsetting» i KI-bildeassistenten, er det kjøringen som godkjenner bildene som består kvalitetskontrollen – resten av veien er den samme. Endringer med høy risiko må bekreftes ekstra. «Publiser til Canvas» sender alle godkjente endringer på én gang og viser resultatet for hver endring; mislykkede endringer kan prøves på nytt uten at noe blir gjort to ganger.</p>
      <h2 id="rapporter">Rapporter</h2>
      <p>Lag rapporter som HTML eller CSV. HTML-rapporten kan skrives ut eller lagres som PDF fra nettleseren. Rapportene viser omfang, dato, regelsett, funn, manuelle kontroller, rettede og gjenstående funn og begrensninger. De er ikke en sertifisering.</p>
    </div>
  );
}

function Faq() {
  const items: [string, ReactNode][] = [
    ["Kan EmneKlar bekrefte at emnet er universelt utformet?", "Nei. Automatiske kontroller finner mange vanlige feil, men mange krav kan bare vurderes av et menneske. Funn merket «Manuell kontroll» og innhold i eksterne verktøy må du vurdere selv."],
    ["Endrer EmneKlar noe i Canvas uten at jeg vet det?", "Nei. Analyser leser bare. Endringer skjer først når du publiserer dem fra endringskøen, og alt logges."],
    ["Hvorfor åpnes EmneKlar i Edge eller Chrome?", "EmneKlar kjører på denne maskinen og vises i et eget vindu uten adresselinje og faner. Vinduet lages av Google Chrome hvis det er standardnettleseren din, ellers av Microsoft Edge, som følger med Windows. Lenker til Canvas og andre nettsteder åpnes i nettleseren. Finnes verken Edge eller Chrome, åpnes EmneKlar i en vanlig fane i standardnettleseren."],
    ["Hvor lagres Canvas-tokenet?", "I Windows Legitimasjonsbehandling. Det lagres aldri i filer, i databasen, i nettleseren eller i logger."],
    ["Hvordan kobler jeg til OpenAI eller Anthropic?", "Gå til Innstillinger → KI-assistenter. Lag en API-nøkkel hos leverandøren (lenken står i kortet), lim den inn og velg «Koble til». EmneKlar kontrollerer nøkkelen hos leverandøren og lagrer den bare i Windows Legitimasjonsbehandling når kontrollen lykkes. En nøkkel som avvises, lagres ikke, og en nøkkel du har lagret før, beholdes. Endepunkt og ny kontroll av tilkoblingen finner du under «Avansert»."],
    ["Sender EmneKlar innhold til KI?", "Bare hvis du har satt opp en KI-leverandør og slått på «Tillat sending av emneinnhold til ekstern KI». Du ser hva som sendes før det sendes. Studentenes innleveringer, karakterer og meldinger sendes aldri."],
    ["Hvorfor er en lenke merket «Krever innlogging» eller «Tidsavbrudd»?", "Noen nettsteder krever innlogging, avviser automatiske besøk eller svarer tregt. Det betyr ikke at lenken er død. Kontroller den i nettleseren."],
    ["Kan jeg angre en endring?", "Ofte, men ikke alltid. Under Canvas-verktøy → Sikkerhetskopier og endringslogg kan du angre endringer når Canvas gjør det mulig og innholdet ikke er endret av andre etterpå."],
    ["Hvorfor kontrolleres ikke spørsmål fra spørsmålsbanker?", "Canvas-API-et gir ikke tilgang til spørsmål som trekkes fra spørsmålsbanker via quizen. EmneKlar sier fra når en quiz bruker slike grupper."],
    ["Støttes nye quizer (New Quizzes)?", "Ikke i denne versjonen. Quizassistenten virker med klassiske quizer."],
    ["Hvorfor er Blueprint-låsing ikke tilgjengelig?", "Låsing kan bare gjøres i selve Blueprint-emnet. Om et emne er Blueprint-emne, bestemmes av Canvas-administratoren."],
    ["Hva skjer når jeg oppdaterer EmneKlar?", "Du starter oppdateringen under Innstillinger → Generelt. Den stopper programmet, tar sikkerhetskopi av databasen, installerer den nye versjonen, sjekker at den virker og starter på nytt. Går noe galt, settes forrige versjon tilbake. Dataene dine ligger utenfor programmappen og blir ikke slettet."],
    ["Må jeg installere Python eller andre programmer?", "Nei. Installasjonsprogrammet har med alt EmneKlar trenger, og verken installasjonen eller oppdateringen laster ned ekstra pakker. EmneKlar installeres bare for deg og trenger ikke administratorrettigheter."],
    ["Hvordan avinstallerer jeg EmneKlar?", "Åpne Innstillinger → Apper → Installerte apper i Windows, finn EmneKlar og velg Avinstaller. Programmet og snarveiene fjernes. Dataene dine i %LOCALAPPDATA%\\EmneKlar blir liggende til du sletter mappen selv, og Canvas-token og KI-nøkler fjerner du i Windows Legitimasjonsbehandling."],
  ];
  return (
    <ul className="ek-list-reset ek-stack" data-gap="2">
      {items.map(([q, a]) => (
        <li key={q} className="ek-card ek-card--compact">
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
        <li>En skannet PDF er et bilde av sidene og har ingen tekst en skjermleser kan lese. Lag den på nytt fra originalen, eller kjør tekstgjenkjenning (OCR) og les gjennom resultatet. Last opp den nye filen i Canvas med samme filnavn og erstatt den gamle, så virker lenkene fortsatt.</li>
        <li>Er et dokument lastet opp før 1. februar 2022, kan unntaket for eldre dokumenter gjelde hvis det ikke trengs i en aktiv prosess. Da kan du velge «Unntaket for eldre dokumenter gjelder» i funnet og skrive hvorfor. Funnet blir «Kontrollert», og begrunnelsen vises i rapporter. EmneKlar avgjør aldri selv at unntaket gjelder.</li>
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
    ["«Økten er ikke gyldig»", "Start EmneKlar på nytt fra Start-menyen eller skrivebordet. EmneKlar åpnes da med en ny innlogging. Data og innstillinger påvirkes ikke."],
    ["Hvordan avslutter jeg EmneKlar?", "Lukk vinduet. Når det siste EmneKlar-vinduet er lukket, avsluttes programmet etter noen sekunder – kjører en jobb, gjøres den ferdig først. Vil du avslutte med en gang, velger du «Avslutt EmneKlar» i kontomenyen nederst til venstre, under Innstillinger → Sikkerhet og personvern, eller i Start-menyen."],
    ["EmneKlar starter ikke, eller vinduet åpnes ikke", "Prøv snarveien i Start-menyen en gang til. Hjelper ikke det, kjører du installasjonsprogrammet på nytt – dataene og innstillingene dine beholdes. Loggen ligger i %LOCALAPPDATA%\\EmneKlar\\logs."],
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
          <li key={q} className="ek-card ek-card--compact">
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
        <li>Kjører bare på denne maskinen. Data lagres i %LOCALAPPDATA%\EmneKlar, adskilt fra programmet.</li>
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
