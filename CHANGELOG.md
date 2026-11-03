# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.
Formatet følger [Keep a Changelog](https://keepachangelog.com/no/1.1.0/), og prosjektet bruker
[semantisk versjonering](https://semver.org/lang/no/).

## [Unreleased]

### Lagt til
- Canvas-verktøy → **Emne-RAG**: en lokal kunnskapsbase av emnet (hele emnet eller valgte moduler) med søk og
  KI-svar med klikkbare kildehenvisninger. Leser bare lærerprodusert innhold (sider, oppgave- og quizbeskrivelser,
  emneplan, lærerens diskusjonsinnlegg og filer lastet opp av lærere) – aldri innleveringer, karakterer, meldinger
  eller studentinnlegg. Tekst og dokumenter (PDF, DOCX, PPTX med notater, XLSX, ODT/ODP/ODS, RTF, CSV, TXT,
  Markdown, HTML) gjøres om til strukturert Markdown og deles opp etter overskrifter; tabeller og lysbilder blir egne
  utdrag. Hybridsøk med BM25 og vektorsøk slått sammen med Reciprocal Rank Fusion, rerangering, filtrering på modul
  og kildetype, og en feilsøkingsvisning med poeng før og etter rerangering. Estimat før bygging, bakgrunnsjobb med
  fremdrift, pause, avbryt og gjenopptak, og liste over hoppede elementer. Valgfrie lokale modeller (BGE-M3 og
  bge-reranker-v2-m3) installeres med `setup-emne-rag.bat`; uten dem brukes nøkkelordsøk.
- Emne-RAG → video og lyd: eksisterende teksting brukes først (Canvas-mediespor, undertekstfiler og YouTube-teksting),
  ellers transkriberes Canvas-video og opplastede lyd- og videofiler lokalt med NB-Whisper (modellstørrelse etter
  GPU/CPU, Whisper large-v3 for annet språk). Transkripsjoner bufres på filens SHA-256, deles i biter på 60–120
  sekunder med overlapp og får tidsstempel i kildehenvisningen. YouTube- og Vimeo-lenker åpnes på riktig tidspunkt.
  Bare medier som lærerens innhold peker på, tas med. Panopto, Kaltura og andre LTI-videoer vises som hoppet over med
  forklaring.
- Emne-RAG → bilder: bilder på sider, bildefiler og bilder i Office-dokumenter beskrives av bildemodellen i KI-laget
  (Claude-API eller lokal bildemodell), med sidetittel, overskrift, tekst rundt bildet og alt-tekst som ekstra input.
  Beskrivelsen gjengir tekst i bildet og forklarer diagrammer og figurer, og lagres som eget utdrag med lenke til siden.
  Pynt filtreres bort før noe sendes (dekorative bilder, ikoner, logoer, bannere, svært små og ensfargede bilder, SVG og
  duplikater med perceptuell hash), og beskrivelsene bufres på bildets SHA-256. Valgfritt: nøkkelbilder ved
  sceneskifte i video, koblet til tidspunktet. Bildene leses i de isolerte parserprosessene.
- Emne-RAG → kontekstuell berikelse (valgfritt, krever KI): én til to setninger foran hvert utdrag som plasserer det i
  dokumentet og modulen, med prompt caching per dokument og buffer. **Kvalitet**: etter hver bygging lages 15–20
  testspørsmål (av KI når det er tillatt, ellers av utdragenes særpregede ord), og recall@5, MRR og en helsescore
  lagres og vises sammen med hvert spørsmål. **Eksport**: ZIP med `chunks.jsonl` (metadata og vektorer), manifest og
  formatbeskrivelse, eller kunnskapsbasen som Word, PDF, Markdown eller ren tekst. Knappen «Oppdater indeks»
  behandler bare nye og endrede elementer og fjerner slettede.
- Emne-RAG → transkripsjon via KI-leverandør: video og lyd uten teksting kan transkriberes av OpenAI
  (gpt-transcribe, gpt-4o-mini-transcribe eller whisper-1), Azure OpenAI eller en egen OpenAI-kompatibel server i
  stedet for lokalt med NB-Whisper (Emne-RAG → Innstillinger → Transkripsjon: lokalt, via KI-leverandør eller av).
  Bare lyden sendes, i biter på 60–120 sekunder kuttet ved pauser (stille biter sendes ikke), og bare etter at
  estimatet har vist antall minutter, modell og hva som sendes, og du har godtatt det. Tidsstemplene følger bitene,
  også når modellen ikke gir tidsstempler, og teksten fra forrige bit sendes med som hint så navn og fagord skrives
  likt. Videotittel og annet innhold fra emnet sendes ikke.
  Transkripsjonene bufres på filens SHA-256 (felles med lokal transkripsjon), og hvert kall logges under KI-bruk.
  Modellene står i en katalog (`core/ai/transcription_models.json`); en egen modell-id kan skrives inn.
  Elementer som venter på samtykke, modeller eller en innstilling, merkes «Prøves igjen ved neste oppdatering» og
  tas med av «Oppdater indeks» når det er på plass. `av` (PyAV, FFmpeg innebygd) er nå en fast avhengighet for å
  hente ut lyden.
- Emne-RAG → Vimeo-teksting: innebygde Vimeo-videoer og Vimeo-lenker i moduler tas med når videoen har teksting.
  Tekstingen hentes slik den innebygde Vimeo-avspilleren gjør det (uoffisielt; bare video-id-en og eventuelt
  tilgangskoden fra en skjult lenke sendes, aldri noe fra emnet), med samme språkrekkefølge som for YouTube og
  opplastet teksting før automatisk. Kildehenvisningen åpner videoen på riktig tidspunkt, også for skjulte lenker.
  Videoer som bare kan vises på bestemte nettsteder eller er passordbeskyttet, vises som hoppet over med forklaring.
  Kan slås av under Emne-RAG → Innstillinger (på som standard). Estimatet viser hva som sendes til YouTube og Vimeo.
- Innholdskvalitet → Media: «Standardiser videoavspillere» for YouTube. Finner innebygde videoer, forklarer avvik
  fra én responsiv og Canvas-trygg standard (16:9, maks bredde, sentrert, `allowfullscreen`, `loading="lazy"`),
  foreslår beskrivende title med synlig kilde (eksisterende title, YouTube-metadata, Canvas-kontekst, KI-forslag på
  forespørsel eller manuelt), forhåndsviser før og etter på PC, nettbrett og mobil og legger godkjente endringer i
  endringskøen – én og én eller alle kompatible videoer. Video-ID og parametere beholdes, og bare videoens egen kode
  endres.

### Endret
- Kontrollen av innebygd innhold (Universell utforming) og videostandardiseringen bruker samme liste over generelle
  titler. «YouTube video», «Embedded video» og titler med kolon eller punktum til slutt regnes nå også som generelle.

### Rettet
- Fanerader (for eksempel i Emne-RAG) viste et lite loddrett rullefelt helt til høyre på Windows. Streken under
  aktiv fane stakk én piksel ut av raden; nå ruller raden bare sideveis, og bare på smale skjermer.
- Emne-RAG: et nytt forsøk som feilet eller måtte vente (for eksempel fordi YouTube blokkerte), erstattet innhold som
  allerede var indeksert med ingenting. Nå beholdes forrige versjon, og elementet prøves igjen ved neste oppdatering.
  Hentet YouTube- og Vimeo-teksting bufres lokalt i 30 dager, så oppdateringer og nybygging ikke spør på nytt.
  Forespørslene spres med litt pause, og blokkerer YouTube (`IpBlocked`), spør EmneKlar ikke mer i den byggingen –
  resten prøves igjen senere med en forklaring. Meldingen etter byggingen sier hvor mange elementer som ble beholdt.
- Emne-RAG: YouTube-teksting virket bare med de lokale modellene installert, og ellers sto det misvisende «Fant
  ingen teksting» for hver YouTube-video. `youtube-transcript-api` (liten, ren Python) er nå en fast avhengighet, så
  `update.bat` installerer den. Finnes ikke teksting på norsk eller engelsk, brukes tekstingen videoen har på et
  annet språk. Grunnen vises når tekstingen mangler (ingen teksting, slettet eller privat video, aldersgrense,
  avvist av YouTube); avviste forespørsler prøves igjen ved neste oppdatering. YouTube- og Vimeo-videoer uten
  teksting prøves også igjen ved hver «Oppdater indeks», siden teksting kan legges til der uten at noe endres i Canvas.
- Emne-RAG: upublisert innhold forsvant ut av estimatet uten forklaring, slik at for eksempel et Blueprint-emne der
  ingenting er publisert ennå, ga «Fant ikke noe innhold». Nå tas alt i modulene du velger under «Valgte moduler»
  med, publisert eller ikke, og estimatet sier hvor mange upubliserte elementer som er med. For hele emnet trengs
  fortsatt «Ta med upubliserte elementer»; det som holdes utenfor, telles og står i listen over elementer som ikke
  blir med. Upubliserte moduler er merket i modulvalget, «Bygg indeks» er sperret når estimatet ikke fant noe, og
  loggen viser hvor mye EmneKlar fikk fra hver Canvas-liste.
- Lange stier og adresser (for eksempel datamappen under *Innstillinger → Sikkerhet og personvern*) brytes nå over
  flere linjer i stedet for å gi sideveis rulling på mobil.

### Sikkerhet
- Oppdaterte avhengigheter med kjente sårbarheter: certifi 2026.10.19, pypdf 6.21.4, opentelemetry-api 1.45.1 og
  filelock 4.2.1.

## [0.1.0] – under utvikling

### Lagt til
- Én lokal applikasjon (FastAPI + React) for Windows med `setup.bat`, `start.bat` og `update.bat`. Tjenesten
  lytter bare på 127.0.0.1; innlogging skjer med engangslenke, og data lagres i `%LOCALAPPDATA%\EmneKlar-Claude`.
- Oppsettveiviser i ni steg med test av Canvas-tilkobling, identitet, tilganger, standardemne og regulatorisk
  profil. Canvas-token og KI-nøkler lagres bare i Windows Legitimasjonsbehandling.
- Global emnevelger, global analyse med normalisert øyeblikksbilde av emnet, ekte fremdrift (prosent, X av Y,
  per innholdstype, funn underveis, estimert tid med intervall), pause, avbryt og kjøring i bakgrunnen.
- Universell utforming: versjonert regelregister og regulatoriske profiler, kontroller av bilder, overskrifter,
  lenker, tabeller, lister, språk, kontrast, innebygd innhold, video og dokumenter, med forklaring, kriterium,
  juridisk status, testmetode og forslag til retting.
- Innholdskvalitet: SSRF-beskyttet lenkesjekk med seks tilstander, interne Canvas-lenker, medier, HTML-hygiene
  og konservativ opprydding med diff.
- Emnestruktur: veiledende forslag med begrunnelse, belegg og sikkerhet, og studentreisen.
- Quizassistent for klassiske quizer: kvalitetssjekk, kildeforankret KI-vurdering, KI-spørsmålsbank med
  kontrollerte kildesitater, dekningsanalyse og quizbygger med forhåndsinnstillinger og «X av Y».
- Emneforside: tre moduser, fire stiler, elleve seksjoner, Canvas-trygg HTML, forhåndsvisning på PC, nettbrett og
  mobil, «Opprett som ny side», «Erstatt eksisterende forside» med sikkerhetskopi og «Bruk som forside».
- Canvas-verktøy: automatiske modulkrav, Blueprint-låsing, analyse av Canvas-innstillinger og backup/endringslogg
  med angring.
- Felles endringskø med forhåndsvisning, godkjenning, konfliktsjekk, sikkerhetskopi, logg og angring, og global
  Dry run som blokkerer alle skrivende kall til Canvas.
- Valgfrie KI-leverandører (OpenAI, Anthropic, Azure OpenAI, lokal OpenAI-kompatibel), modellregister,
  kostnads- og kvalitetsbevisst modellvalg med reserve, og personvern med samtykke før sending.
- Rapporter i HTML (kan lagres som PDF fra nettleseren) og CSV.
- Innstillinger i åtte deler, funksjonsflagg, hjelpesenter og oppdateringssjekk mot GitHub Releases.
- Oppdatering i ti steg (`update.bat` eller fra Innstillinger) med sikkerhetskopi av databasen, helsesjekk og
  tilbakerulling ved feil. Nye hovedversjoner installeres bare etter bekreftelse. Utgivelsespakker (zip med
  SHA-256) bygges av GitHub Actions. Se `docs/UPDATING.md`.
- Automatiske tester: backend (pytest), frontend (Vitest + axe) og ende-til-ende (Playwright + axe).

### Endret
- Nytt visuelt uttrykk i hele programmet: mørk marineblå meny, lys og lett varm bakgrunn, store hvite kort,
  pastellfarger per område (UU lilla, innholdskvalitet blå, emnestruktur grønn, quiz oransje), større og tydeligere
  typografi (Inter, pakket med appen) og et samlet designsystem med tokens og gjenbrukbare komponenter
  (`docs/DESIGN_SYSTEM.md`). Bare utseendet er endret – funksjonene er de samme.
- Oversikt er bygget om med store statuskort per område, anbefalte steg som handlingsrader, siste aktivitet, et
  tilgjengelig diagram over åpne funn per område (med tabellvisning) og innholdet i emnet som ikonfliser.
- Funnlistene har nøkkeltallkort, filterpiller for kategori og klassifisering og ryddigere rader. Canvas-verktøy har
  siste handlinger, Dry run-status og verktøykort. Quizassistent og Rapporter har nøkkeltall øverst.

### Rettet
- EmneKlar startet ikke når et annet program med samme navn brukte `%LOCALAPPDATA%\EmneKlar` («no such table:
  jobs»). EmneKlar har nå egen datamappe (`%LOCALAPPDATA%\EmneKlar-Claude`), egen oppføring i Windows
  Legitimasjonsbehandling, en innloggingskapsel per port og standardport 8770. En database som tilhører et annet
  program, blir aldri åpnet for skriving – EmneKlar forklarer i stedet hva som er galt.
