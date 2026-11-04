# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.
Formatet følger [Keep a Changelog](https://keepachangelog.com/no/1.1.0/), og prosjektet bruker
[semantisk versjonering](https://semver.org/lang/no/).

## [Unreleased]

### Lagt til
- **KI-bildeassistent** under Canvas-verktøy: analyserer hele emnet, én modul, flere moduler eller én side og lager
  faglig presise illustrasjoner i én gjennomgående stil, med alternativ tekst og bildetekst. Arbeidsflyt i sju
  steg (omfang, KI-modeller, designprofil, analyse, generering, gjennomgang, publisering) med oversikt per modul og
  side, godkjenning av ett bilde, en side, en modul eller hele emnet, og «Fortsett» etter avbrudd.
- Hierarkisk kontekstmodell (emne → modul → side → seksjon) med strukturert kontekstpakke og hurtigbufret
  analyse. Sider i flere moduler behandles én gang; andre modulelementer brukes som kontekst.
- Pedagogisk bildeplan per side (formål, begrep, læringsmål, motiv, må vise / må ikke vise, risiko for faglige
  feil, merverdi), med mengdevalg Lav / Balansert / Høy. Null bilder er et gyldig svar. Diagrammer som krever
  tekst anbefales laget i HTML/SVG i stedet.
- Versjonert designprofil per emne med sju stiler (bl.a. moderne 3D, flat, fotografisk, akademisk, isometrisk,
  infografisk, egendefinert), KI-forslag, eksempelbilde og referansebilder som brukes ved nye bilder.
- Bildegenerering i KI-laget (OpenAI Image API med referansebilder, Azure OpenAI, OpenAI-kompatible servere) med
  katalog over bildemodeller (GPT-Image-2.5 Sunburst og Flare). Kvalitetsprofilene Maksimal kvalitet (standard),
  Balansert og Rask velger modeller per rolle (Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5, GPT-6 Astra /
  GPT-6.1 Sol / GPT-6.1 Terra), og avanserte brukere kan velge selv.
- Multimodal kvalitetskontroll av hvert bilde (relevans, samsvar, kvalitet, stil, feil detaljer, tekst i bildet,
  læringsmål) med automatisk ny runde, flagg for manuell kontroll og alt-tekst/bildetekst ut fra det faktiske bildet.
- Kostnadsanslag som intervall før start (veiledende priser, ikke garantert), registrering av faktisk forbruk og
  kostnadsgrense per jobb.
- Publisering via endringsmotoren: 3-stegs filopplasting til Canvas-filer, innsetting som `figure`/`figcaption`
  mellom avsnitt uten å endre eksisterende HTML, konfliktsjekk, sikkerhetskopi, publiseringsstatus beholdes,
  opphavsrett når emnet krever det, valgfri automatisk innsetting, og angring som bare fjerner EmneKlars figurer.
- `GPT-6.1 Terra` i modellkatalogen.

### Endret
- KI-ruterens reserveliste har alltid minst én modell fra en annen leverandør når det finnes.

## [0.1.0] – 2026-11-04

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
- Canvas-verktøy → **Emnets kunnskapsbase**: en lokal kunnskapsbase av emnet (hele emnet eller valgte moduler) med søk og
  KI-svar med klikkbare kildehenvisninger. Leser bare lærerprodusert innhold (sider, oppgave- og quizbeskrivelser,
  emneplan, lærerens diskusjonsinnlegg og filer lastet opp av lærere) – aldri innleveringer, karakterer, meldinger
  eller studentinnlegg. Tekst og dokumenter (PDF, DOCX, PPTX med notater, XLSX, ODT/ODP/ODS, RTF, CSV, TXT,
  Markdown, HTML) gjøres om til strukturert Markdown og deles opp etter overskrifter; tabeller og lysbilder blir egne
  utdrag. Hybridsøk med BM25 og vektorsøk slått sammen med Reciprocal Rank Fusion, rerangering, filtrering på modul
  og kildetype, og en feilsøkingsvisning med poeng før og etter rerangering. Estimat før bygging, bakgrunnsjobb med
  fremdrift, pause, avbryt og gjenopptak, og liste over hoppede elementer. Valgfrie lokale modeller (BGE-M3 og
  bge-reranker-v2-m3) installeres med `setup.bat`, som spør om dem under oppsettet; uten dem brukes nøkkelordsøk.
- Emnets kunnskapsbase → video og lyd: eksisterende teksting brukes først (Canvas-mediespor, undertekstfiler og YouTube-teksting),
  ellers transkriberes Canvas-video og opplastede lyd- og videofiler lokalt med NB-Whisper (modellstørrelse etter
  GPU/CPU, Whisper large-v3 for annet språk). Transkripsjoner bufres på filens SHA-256, deles i biter på 60–120
  sekunder med overlapp og får tidsstempel i kildehenvisningen. YouTube- og Vimeo-lenker åpnes på riktig tidspunkt.
  Bare medier som lærerens innhold peker på, tas med. Panopto, Kaltura og andre LTI-videoer vises som hoppet over med
  forklaring.
- Emnets kunnskapsbase → bilder: bilder på sider, bildefiler og bilder i Office-dokumenter beskrives av bildemodellen i KI-laget
  (Claude-API eller lokal bildemodell), med sidetittel, overskrift, tekst rundt bildet og alt-tekst som ekstra input.
  Beskrivelsen gjengir tekst i bildet og forklarer diagrammer og figurer, og lagres som eget utdrag med lenke til siden.
  Pynt filtreres bort før noe sendes (dekorative bilder, ikoner, logoer, bannere, svært små og ensfargede bilder, SVG og
  duplikater med perceptuell hash), og beskrivelsene bufres på bildets SHA-256. Valgfritt: nøkkelbilder ved
  sceneskifte i video, koblet til tidspunktet. Bildene leses i de isolerte parserprosessene.
- Emnets kunnskapsbase → kontekstuell berikelse (valgfritt, krever KI): én til to setninger foran hvert utdrag som plasserer det i
  dokumentet og modulen, med prompt caching per dokument og buffer. **Kvalitet**: etter hver bygging lages 15–20
  testspørsmål (av KI når det er tillatt, ellers av utdragenes særpregede ord), og recall@5, MRR og en helsescore
  lagres og vises sammen med hvert spørsmål. **Eksport**: ZIP med `chunks.jsonl` (metadata og vektorer), manifest og
  formatbeskrivelse, eller kunnskapsbasen som Word, PDF, Markdown eller ren tekst. Knappen «Oppdater indeks»
  behandler bare nye og endrede elementer og fjerner slettede.
- Emnets kunnskapsbase → transkripsjon via KI-leverandør: video og lyd uten teksting kan transkriberes av OpenAI
  (gpt-transcribe, gpt-4o-mini-transcribe eller whisper-1), Azure OpenAI eller en egen OpenAI-kompatibel server i
  stedet for lokalt med NB-Whisper (Emnets kunnskapsbase → Innstillinger → Transkripsjon: lokalt, via KI-leverandør eller av).
  Bare lyden sendes, i biter på 60–120 sekunder kuttet ved pauser (stille biter sendes ikke), og bare etter at
  estimatet har vist antall minutter, modell og hva som sendes, og du har godtatt det. Tidsstemplene følger bitene,
  også når modellen ikke gir tidsstempler, og teksten fra forrige bit sendes med som hint så navn og fagord skrives
  likt. Videotittel og annet innhold fra emnet sendes ikke.
  Transkripsjonene bufres på filens SHA-256 (felles med lokal transkripsjon), og hvert kall logges under KI-bruk.
  Modellene står i en katalog (`core/ai/transcription_models.json`); en egen modell-id kan skrives inn.
  Elementer som venter på samtykke, modeller eller en innstilling, merkes «Prøves igjen ved neste oppdatering» og
  tas med av «Oppdater indeks» når det er på plass. `av` (PyAV, FFmpeg innebygd) er nå en fast avhengighet for å
  hente ut lyden.
- Emnets kunnskapsbase → Vimeo-teksting: innebygde Vimeo-videoer og Vimeo-lenker i moduler tas med når videoen har teksting.
  Tekstingen hentes slik den innebygde Vimeo-avspilleren gjør det (uoffisielt; bare video-id-en og eventuelt
  tilgangskoden fra en skjult lenke sendes, aldri noe fra emnet), med samme språkrekkefølge som for YouTube og
  opplastet teksting før automatisk. Kildehenvisningen åpner videoen på riktig tidspunkt, også for skjulte lenker.
  Videoer som bare kan vises på bestemte nettsteder eller er passordbeskyttet, vises som hoppet over med forklaring.
  Kan slås av under Emnets kunnskapsbase → Innstillinger (på som standard). Estimatet viser hva som sendes til YouTube og Vimeo.
- Innholdskvalitet → Media: «Standardiser videoavspillere» for YouTube. Finner innebygde videoer, forklarer avvik
  fra én responsiv og Canvas-trygg standard (16:9, maks bredde, sentrert, `allowfullscreen`, `loading="lazy"`),
  foreslår beskrivende title med synlig kilde (eksisterende title, YouTube-metadata, Canvas-kontekst, KI-forslag på
  forespørsel eller manuelt), forhåndsviser før og etter på PC, nettbrett og mobil og legger godkjente endringer i
  endringskøen – én og én eller alle kompatible videoer. Video-ID og parametere beholdes, og bare videoens egen kode
  endres.

### Endret
- Nytt visuelt uttrykk i hele programmet: mørk marineblå meny, lys og lett varm bakgrunn, store hvite kort,
  pastellfarger per område (UU lilla, innholdskvalitet blå, emnestruktur grønn, quiz oransje), større og tydeligere
  typografi (Inter, pakket med appen) og et samlet designsystem med tokens og gjenbrukbare komponenter
  (`docs/DESIGN_SYSTEM.md`). Bare utseendet er endret – funksjonene er de samme.
- Oversikt er bygget om med store statuskort per område, anbefalte steg som handlingsrader, siste aktivitet, et
  tilgjengelig diagram over åpne funn per område (med tabellvisning) og innholdet i emnet som ikonfliser.
- Funnlistene har nøkkeltallkort, filterpiller for kategori og klassifisering og ryddigere rader. Canvas-verktøy har
  siste handlinger, Dry run-status og verktøykort. Quizassistent og Rapporter har nøkkeltall øverst.
- Avhengigheter oppdatert samlet og testet sammen (erstatter Dependabot-PR-ene #2–#11): pydantic 2.14.2 (med
  pydantic-core 2.50.2, som Dependabot-oppdateringen manglet), starlette 1.10.0, alembic 1.20.1, msgpack 1.2.4 og
  pytest 9.2.0 i backend; react-router 8.5.1, @tanstack/react-query 5.105.3, vite 8.3.5, @playwright/test 1.64.1
  og @axe-core/playwright 4.14.0 i frontend.
- Verktøyet heter nå **Emnets kunnskapsbase** i stedet for Emne-RAG – i menyen, på siden, i KI-oppgavene, jobbene
  og meldingene. Adressen (`/canvas-verktoy/emne-rag`) er uendret.
- Ett oppsett for hele programmet: `setup.bat` spør én gang om de valgfrie lokale modellene for Emnets kunnskapsbase
  (standard nei; ingen spørsmål uten konsoll, med `--no-pause` eller når valget er gjort før). `setup-emne-rag.bat` er
  fjernet; `setup.bat --rag` velger modellene uten å spørre, og `--no-rag` hopper over spørsmålet.
- Lenken «← Canvas-verktøy» øverst på verktøysidene (Emnets kunnskapsbase, Automatiske modulkrav, Blueprint-låsing,
  Canvas-innstillinger, Backup og endringslogg) er fjernet. Den gjentok menyen til venstre, der «Canvas-verktøy»
  allerede er markert.
- Emnets kunnskapsbase er roligere og bruker ordet «kunnskapsbase» i stedet for «indeks». Hovedknappen heter **Opprett
  kunnskapsbase** (eller **Oppdater kunnskapsbasen**) og er større, og den første fanen heter «Kunnskapsbase» både
  før og etter. I stedet for en tom indeksboks står statusen «Ingen kunnskapsbase opprettet ennå» rett under
  sidetittelen; kortet over fanene heter «Status». Kildene vises som en liste («Canvas-tekst · Dokumenter · Video og
  lyd · Bilder») med de faktiske valgene og merket «Tilpasset» når de avviker fra standard. Hjelpetekstene og
  forklaringen under hovedknappen er større og har sterkere kontrast. Den blå boksen øverst og teksten nederst er erstattet av én kort
  forklaring ved hovedknappen («Kunnskapsbasen lagres på denne maskinen. Du godkjenner eventuell nedlasting og
  sending til KI først.») med detaljer bak «Les mer» – også om søk og
  transkripsjon skjer lokalt eller hos KI-leverandøren du har valgt (den gamle teksten sa alltid «lokalt»).
- Emnets kunnskapsbase → «Opprett kunnskapsbase» er forenklet: hovedsiden har omfang (hele emnet eller valgte moduler), en kort
  oppsummering av kildene («Inkluderer Canvas-tekst, dokumenter, video, lyd og bilder.»), **Tilpass kilder** og
  hovedknappen. Alle kildetyper er på som standard (bilder bare når KI er satt opp). «Tilpass kilder» åpner et
  sidepanel med kilder og filtyper, upublisert innhold og en **Avansert**-del med KI-tilleggene (kontekstuell
  berikelse, nøkkelbilder) og valg av transkriberingstjeneste. Endrede valg vises i oppsummeringen («Tilpassede
  kilder · Video/lyd og bilder er utelatt.»). Panelet er gjort lettere: «Avansert» er lukket som standard; filtyper
  vises bare med «Dokumenter», transkribering og nøkkelbilder bare med «Video og lyd», og leverandør, modell, språk
  (nedtrekksmeny med «Oppdag automatisk») og personvernboksen bare ved ekstern tjeneste. Hvert valg har én kort
  forklaring, og detaljene ligger bak «Les mer». Transkribering heter *På denne maskinen*, *Ekstern KI-tjeneste* og
  *Bare eksisterende undertekster*, og er merket «Gjelder alle emner». «Bilder» heter nå «Bildebeskrivelser med
  KI» (alt-tekst er alltid med), og alt som kan koste penger, er merket «Kan koste ekstra». Knappene heter
  **Lagre valg** (kildene lagres for emnet i nettleseren, transkriberingsvalget for alle emner) og **Tilbakestill
  kilder** (påvirker bare kildene, filtypene og upublisert innhold). Hovedknappen beregner estimatet først og viser det bare når noe må godkjennes (nedlasting, sending
  til KI, upublisert innhold) eller ingenting ble funnet; ellers starter byggingen med en gang.
- Kontrollen av innebygd innhold (Universell utforming) og videostandardiseringen bruker samme liste over generelle
  titler. «YouTube video», «Embedded video» og titler med kolon eller punktum til slutt regnes nå også som generelle.

### Rettet
- EmneKlar startet ikke når et annet program med samme navn brukte `%LOCALAPPDATA%\EmneKlar` («no such table:
  jobs»). EmneKlar har nå egen datamappe (`%LOCALAPPDATA%\EmneKlar-Claude`), egen oppføring i Windows
  Legitimasjonsbehandling, en innloggingskapsel per port og standardport 8770. En database som tilhører et annet
  program, blir aldri åpnet for skriving – EmneKlar forklarer i stedet hva som er galt.
- Emnets kunnskapsbase: når samme bilde står flere steder, beskrives nå alltid det første (i sidens rekkefølge),
  med alt-teksten og teksten rundt det. Før avhang det av hvilken nedlasting som ble ferdig først.
- Fanerader (for eksempel i Emnets kunnskapsbase) viste et lite loddrett rullefelt helt til høyre på Windows. Streken under
  aktiv fane stakk én piksel ut av raden; nå ruller raden bare sideveis, og bare på smale skjermer.
- Emnets kunnskapsbase: et nytt forsøk som feilet eller måtte vente (for eksempel fordi YouTube blokkerte), erstattet innhold som
  allerede var indeksert med ingenting. Nå beholdes forrige versjon, og elementet prøves igjen ved neste oppdatering.
  Hentet YouTube- og Vimeo-teksting bufres lokalt i 30 dager, så oppdateringer og nybygging ikke spør på nytt.
  Forespørslene spres med litt pause, og blokkerer YouTube (`IpBlocked`), spør EmneKlar ikke mer i den byggingen –
  resten prøves igjen senere med en forklaring. Meldingen etter byggingen sier hvor mange elementer som ble beholdt.
- Emnets kunnskapsbase: YouTube-teksting virket bare med de lokale modellene installert, og ellers sto det misvisende «Fant
  ingen teksting» for hver YouTube-video. `youtube-transcript-api` (liten, ren Python) er nå en fast avhengighet, så
  `update.bat` installerer den. Finnes ikke teksting på norsk eller engelsk, brukes tekstingen videoen har på et
  annet språk. Grunnen vises når tekstingen mangler (ingen teksting, slettet eller privat video, aldersgrense,
  avvist av YouTube); avviste forespørsler prøves igjen ved neste oppdatering. YouTube- og Vimeo-videoer uten
  teksting prøves også igjen ved hver «Oppdater indeks», siden teksting kan legges til der uten at noe endres i Canvas.
- Emnets kunnskapsbase: upublisert innhold forsvant ut av estimatet uten forklaring, slik at for eksempel et Blueprint-emne der
  ingenting er publisert ennå, ga «Fant ikke noe innhold». Nå tas alt i modulene du velger under «Valgte moduler»
  med, publisert eller ikke, og estimatet sier hvor mange upubliserte elementer som er med. For hele emnet trengs
  fortsatt «Ta med upubliserte elementer»; det som holdes utenfor, telles og står i listen over elementer som ikke
  blir med. Upubliserte moduler er merket i modulvalget, «Bygg indeks» er sperret når estimatet ikke fant noe, og
  loggen viser hvor mye EmneKlar fikk fra hver Canvas-liste.
- Lange stier og adresser (for eksempel datamappen under *Innstillinger → Sikkerhet og personvern*) brytes nå over
  flere linjer i stedet for å gi sideveis rulling på mobil.
- Automatiske modulkrav: trykket man «Forhåndsvis» før kravene per elementtype var lastet, ble forhåndsvisningen
  laget uten krav og aldri vist. Knappen venter nå til valgene er lastet, og viser en feilmelding hvis de ikke kan
  hentes.

### Sikkerhet
- Oppdaterte avhengigheter med kjente sårbarheter: certifi 2026.10.19, pypdf 6.21.4, opentelemetry-api 1.45.1 og
  filelock 4.2.1.
