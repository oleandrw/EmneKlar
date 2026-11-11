# EmneKlar – arkitektur

EmneKlar er **én lokal applikasjon** (en modulær monolitt) som kjører på lærerens egen Windows-maskin.
Backend (Python/FastAPI) og frontend (React/TypeScript) leveres som ett program: backend serverer det
ferdigbygde grensesnittet og lytter bare på `127.0.0.1`.

```
┌──────────────────────────────── Lærerens maskin ────────────────────────────────┐
│                                                                                  │
│  Nettleser (React/TS, design-system)        Backend (FastAPI, én prosess)        │
│  ┌──────────────────────────────┐  HTTP     ┌─────────────────────────────────┐  │
│  │ Oversikt │ UU │ Innhold │ …   │◄────────►│ core/security/web  (Host, økt,  │  │
│  │ Global emnevelger,           │ 127.0.0.1 │   CSRF, Origin, CSP)            │  │
│  │ endringskø, analysedialog    │  + SSE    │ features/*  (domener)           │  │
│  └──────────────────────────────┘           │ core/canvas (klient, snapshot)  │──┼─► Canvas REST API
│                                             │ core/changes (endringsmotor)    │  │
│  OS-nøkkelring ◄── token/nøkler ────────────│ core/ai (leverandører, ruter)   │──┼─► Valgt KI-leverandør
│  (Windows Credential Manager)               │ core/jobs (jobber, fremdrift)   │  │   (bare etter samtykke)
│                                             │ core/security/ssrf (lenkesjekk) │──┼─► Eksterne lenker
│  %LOCALAPPDATA%\EmneKlar\                   │ core/storage (SQLite, Alembic)  │  │   (SSRF-beskyttet)
│   database.db, backups\, reports\,          └─────────────────────────────────┘  │
│   logs\, cache\, run\                                                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Prinsipp for all funksjonalitet

**ANALYSER → FORKLAR → FORESLÅ → FORHÅNDSVIS → GODKJENN → ENDRE → LOGG**

Ingen modul skriver direkte til Canvas. Alt som endrer innhold blir et *forslag* som kan forhåndsvises,
legges i den globale endringskøen og bare sendes til Canvas etter godkjenning – via den felles endringsmotoren.

## Moduler

```
backend/emneklar/
  config.py            prosessoppsett (miljøvariabler EMNEKLAR_*), datamappe
  main.py, launcher.py FastAPI-app og oppstart (engangslenke, gjenbruk av kjørende instans, start uten
                       konsollvindu med feilmeldinger i meldingsboks)
  api/                 felles avhengigheter og systemruter (helse, økt, kontrollkanal)
  core/
    security/          web.py (økt/CSRF/Host/CSP), ssrf.py, sanitize.py, redaction.py, safe_zip.py, isolation.py
    auth/secrets.py    hemmeligheter i OS-nøkkelring
    storage/           db.py (SQLite + Alembic), models.py, settings.py (typede innstillinger),
                       legacy.py (engangskopi av data fra det tidligere mappenavnet EmneKlar-Claude)
    system.py          det tynne laget mot maskinen: datamappe per plattform, meldinger uten konsollvindu,
                       «åpne mappe», plattformnavn for innebygd kjøretid (bare standardbiblioteket)
    canvas/            client.py (lavnivå, skrivevern), api.py (typede kall), snapshot.py, html.py
    jobs/              manager.py (bakgrunnsjobber), progress.py, eta.py
    changes/           engine.py (endringskø, konflikt, backup, logg, angre), appliers.py
    backup/            store.py (sikkerhetskopier av Canvas-objekter)
    ai/                providers/, catalog.py (modellregister), router.py, service.py (personvern, logg),
                       images.py (bildemodeller, image_models.json), profiles.py (kvalitetsprofiler,
                       model_profiles.json), pricing.py (veiledende priser for anslag, pricing.json),
                       local/ (lokale modeller for Emne-RAG: embedding, rerangering, NB-Whisper; local_models.json)
    updates/           versjonssjekk mot GitHub Releases
    flags.py           funksjonsflagg
  features/
    analysis/          global analyse (orkestrerer analysatorer over ett snapshot)
    findings/          felles lagring, filtrering, «Ignorer»
    accessibility/     regelregister, profiler, kontroller, dokumentkontroller, rettinger
    content_quality/   lenkesjekk, medier, HTML-hygiene, opprydding med diff
    course_structure/  strukturanalyse, studentreise, flytteforslag
    quiz_assistant/    klassiske quizer, kvalitetssjekk, KI-spørsmålsbank, quizbygger
    module_requirements/, blueprint/, canvas_settings/
    reporting/         HTML/CSV-rapporter
    course_rag/        Emne-RAG (Canvas-verktøy): innhenting, konvertering, chunking, indeks, hybridsøk, svar, eksport
    illustrations/     KI-bildeassistent (Canvas-verktøy): kartlegging, kontekstmodell, bildeplan, designprofil,
                       generering og kvalitetskontroll, deterministisk plassering, publisering via endringsmotoren
    course_design/     Emnedesign: designprofiler som data (profiles.json), innholdsbevarende
                       transformasjon, innholdsoversikt, forhåndsvisning, godkjenning via endringsmotoren
    overview/          domenekort og anbefalte neste steg
frontend/src/
  core/                API-klient, økt, global emnekontekst, layout (navigasjon, topplinje)
  design-system/       tokens, komponenter (kort, nøkkeltall, handlingsrader, diagram, skjema, dialog, tabell, faner) – se DESIGN_SYSTEM.md
  features/            én mappe per domene, speiler backend
```

**Grenser:** domenelogikk ligger i backend og er uavhengig av React-komponenter. Funksjoner bruker kjernen
(Canvas-klient, endringsmotor, KI-ruter, jobber) i stedet for egne klienter. Frontend-funksjoner bruker
design-systemet og den felles API-klienten.

## Global analyse og snapshot

1. Brukeren velger omfang (hele emnet / valgte moduler / enkeltelementer) og analyseområder.
2. En bakgrunnsjobb bygger et **normalisert snapshot** av emnet: lister hentes én gang (sider med
   `include[]=body`, moduler med elementer, oppgaver, diskusjoner, quizer, filer, emneplan) og lagres i
   `snapshot_objects`. Alle analysatorer i samme kjøring bruker de samme objektene – emnet lastes ikke ned flere
   ganger.
3. Analysatorene (UU, innholdskvalitet, struktur, quiz) kjører som oppgaver med begrenset samtidighet.
   Funn lagres fortløpende, slik at fremdriftsvisningen viser funn underveis.
4. Fremdrift strømmes med **SSE** (`/api/jobs/{id}/events`). Prosent og «X av Y» vises først når totalen er
   kjent; ETA beregnes fra observerte varigheter per oppgavetype (EWMA) og observert parallellitet, vises som
   «Beregner estimert tid …» til det finnes nok observasjoner, og som intervall når usikkerheten er stor.
5. Pause er ekte: arbeidere stopper ved sjekkpunkter mellom oppgaver. Jobber fortsetter i bakgrunnen så lenge
   EmneKlar kjører.

## Endringsmotoren

```
forslag (funksjon) ─► StagedChange (før, foreslått, begrunnelse, risiko, angremulighet, oppskrift)
     │ forhåndsvis / rediger / fjern
     ▼
godkjenn (én, valgte eller «Godkjenn alle klare») ─► «Publiser til Canvas» (én jobb, flere emner)
     │  rekkefølge per side: endringer uten oppskrift først, oppskriftsbaserte rettinger etter, Blueprint-synk sist
     ▼
allerede publisert? → hopp over (aldri skrevet to ganger)
konfliktsjekk (hent objektet på nytt, sammenlign med «før»)
     │  allerede lagret i Canvas (tidsavbrudd etter lagring) → registrer, ikke send på nytt
     │  EmneKlar endret samme side i denne publiseringen → bygg rettingen på nytt fra oppskriften
     │  ellers → stopp, krev ny vurdering («Lag forslaget på nytt»)
     ▼
sikkerhetskopi (backups\) ─► skriv via CanvasClient + WritePermit ─► verifiser ─► endringslogg
     ▼
angre (der snapshot + API gjør det mulig, med ny konfliktsjekk)
```

* **Ingen Dry run.** Analyser, forhåndsvisninger, staging og godkjenning gjør bare lesekall; det eneste som skriver,
  er publiseringsjobben, og bare med en `WritePermit` utstedt av endringsmotoren. Den gamle bryteren og
  `change_log.dry_run` er fjernet (migrering 0005); gamle logginnslag med handlingen `dry_run` vises fortsatt.
* **Målrettede rettinger** (`core/canvas/html_edit.py`): alt-tekst, lenkeadresse/-tekst, fjerne lenke,
  overskriftsnivå, iframe-tittel o.l. endrer bare elementet i den opprinnelige HTML-strengen; alt annet på siden
  forblir byte for byte likt. Hele-dokument-rettinger (opprydding, lister, tabeller) og HTML som ikke kan kartlegges
  sikkert, bruker den eldre parse-og-serialiser-veien.
* **Oppskrifter**: hver retting lagrer funn, plassering og parametre (`source.fixes`), så endringen kan bygges på
  nytt på nyere innhold – automatisk når EmneKlar selv nettopp publiserte en annen endring på samme side, og med
  «Lag forslaget på nytt» etter en ekte konflikt.
* **Blueprint** (`core/canvas/blueprint.py`): ingen applikasjonssperre. Canvas avgjør hva brukeren kan endre.
  Forhåndsvisningen sier hvor endringen gjøres og hvem den når; avviser Canvas låst innhold i et tilknyttet emne,
  kan rettingen flyttes til Blueprint-emnet (samme side/entydig tittel, oppskriftene brukes på Blueprint-innholdet),
  og en synkronisering (`blueprint.sync`, høy risiko) legges i køen.
* **Feil forklares**: Blueprint-lås, manglende rettighet, borte innhold og nettverksfeil får hver sin forklaring og
  neste steg; publiseringer som ble avbrutt av en omstart, merkes som feilet og kontrolleres mot Canvas ved nytt forsøk.

## Alt-tekst: forhåndslagde KI-forslag

`features/accessibility/alt_suggestions.py`: bildefunn får kontekst ved analysen (nærmeste overskrift, tekst før og
etter, bildetekst, lenkemål). «Forbered forslag» viser hva som sendes, og legger bildene i en kø som kjører som én
bakgrunnsjobb per emne med høyst tre samtidige kall. Bildet læreren ser på og de neste i listen flyttes fram.
Forslag lagres i `alt_text_suggestions` med en hash av alt som går inn i forespørselen; uendret bilde og kontekst
sendes aldri på nytt, og endret kontekst gir nytt forslag. Bildet vises via `/api/findings/{id}/image` (Canvas-bilder
hentes med token i backend; SVG serveres ikke).

## KI-laget

* `AIProvider`-abstraksjon: OpenAI (Chat Completions), Anthropic (Messages), Azure OpenAI (v1-API eller
  klassisk deployment-URL), lokal OpenAI-kompatibel (Ollama, LM Studio, vLLM).
* **Modellregister** (`ai_models`): leverandør, modell, tekst/bilde/strukturert svar, kontekst-, kvalitets-,
  hastighets- og kostnadsklasse, aktivert. Startdata fra en versjonert katalog; brukeren kan endre alt. Modeller
  som oppdages hos leverandøren får ukjente egenskaper og må klassifiseres før bruk (bortsett fra der
  leverandøren selv oppgir egenskapene, som Anthropics modelliste).
* **Ruteren** velger billigste modell som forventes å holde nok kvalitet for oppgaven (oppgavetype,
  kompleksitet, bilde, kontekststørrelse, strategi), med reserveliste ved feil. Ingen modellnavn er hardkodet i
  funksjonene.
* **Personvern:** ekstern KI er av til brukeren slår den på; før sending vises en oppsummering av hva som
  sendes; studentdata sendes aldri.
* **Emneinnhold er data** (`core/ai/untrusted.py`): alle KI-kall som sender tekst fra emnet eller fra nettsider,
  pakker den inn med `wrap_untrusted_content` – mellom `<<<KURSINNHOLD` og `KURSINNHOLD>>>`, merket som data, med
  skilletegn i innholdet nøytralisert (tre eller flere `<`/`>` blir to), og med en merknad foran når teksten ligner
  instruksjoner til en KI (`has_injection_markers`). `scrub=True` fjerner e-post, telefon, fødselsnummer og signerte
  URL-er der oppgaven ikke trenger dem (alt-tekst, lenketekst, tabell- og videotitler, lenkealternativer, Emnedesign,
  bildebeskrivelser, KI-bildeassistenten). Svar fra Kunnskapsbasen og berikelsen av den vaskes ikke, fordi
  kontaktinformasjon læreren har skrevet i emnet kan være det spørsmålet gjelder. Systemprompten har alltid
  `DATA_RULE`. Modellene får ingen verktøy, og svarene valideres mot skjema.
* **Bildegenerering** er en egen leverandøroppgave (`AIProvider.generate_image`): OpenAI Image API
  (`/images/generations`, og `/images/edits` med referansebilder i `image[]`), Azure OpenAI og OpenAI-kompatible
  servere. Anthropic-modeller analyserer bilder, men lager dem ikke. Bildemodellene står i `image_models.json`;
  en ny bildegenerator er en ny katalograd (og en implementasjon for en ny API-familie). Samme personvernport og
  bruksloggen gjelder.
* **Kvalitetsprofiler** (`model_profiles.json`: Maksimal kvalitet / Balansert / Rask) gir foretrukne modeller per
  rolle; bare aktiverte modeller hos klare leverandører brukes, ellers velger ruteren med profilens strategi.
  `AIService.run(preferred=…)` prøver profilens modeller først, deretter ruterens valg og reserver. Reservelisten
  har alltid minst én modell fra en annen leverandør når det finnes (et leverandøravbrudd bruker ikke opp alle
  forsøk).

## KI-hjelp i arbeidsflyten

KI er en valgfri hjelp ved oppgaven, aldri en forutsetning: alt kan gjøres for hånd, regelbaserte rettinger forblir
regelbaserte, og ingenting sendes til en leverandør før brukeren ber om et forslag. Alle kall går gjennom `AIService`
(ruting, personvernport, samtykke, bruk uten innhold i loggen).

**Felles mønster i rettevinduet** (`features/accessibility/ai_fix.py`, `frontend/src/features/findings/AiSuggestion.tsx`):
«Foreslå … med KI» ved tekstfeltet → se og rediger → forhåndsvisningen følger feltet → godkjenn til endringskøen.

* `POST /api/findings/{id}/ai-suggestion/prepare` viser hva som sendes, grunnlaget og hvilken tjeneste som brukes;
  `POST /api/findings/{id}/ai-suggestion` lager ett forslag. Ingenting legges i køen her.
* Første forespørsel viser samtykket når innstillingen «Bekreft før innhold sendes» er på; samme oppgave med samme
  tjeneste spørres ikke igjen i økten (en ny tjeneste gjør det). Uten konfigurert tjeneste vises en forklaring og en
  lenke til oppsett, ikke en knapp.
* Brukerens egen tekst byttes aldri ut uten et klikk («Bruk forslaget»); én forespørsel per klikk; «Nytt forslag» ber
  om et annet; feil lar feltet stå. Svaret valideres (ren tekst, lengde, ikke generisk, ikke en adresse) og settes inn
  som tekst. Et svar for et annet funn ignoreres.
* En godkjent retting med KI-tekst merkes `ai_generated` i endringskøen. «Godkjenn alle klare» tar aldri med
  KI-forslag (heller ikke ferdige alt-tekstforslag fra bakgrunnskøen) – de gjennomgås i hvert funn.
* Lenkemålet leses trygt (`link_target.py`): Canvas-innhold via Canvas-API-et med lærerens tilgang (tittel og kort
  utdrag av sider, oppgaver og quizer; bare tittel på diskusjoner; filnavn), andre sider gjennom SSRF-vernet (ingen
  informasjonskapsler eller token, omdirigeringer valideres, maks 300 kB, bare HTML). Adresser med
  tilgangsopplysninger hentes ikke, og `safe_url` fjerner brukernavn og sensitive parametere før en adresse sendes
  eller logges. Grunnlaget vises: «hentet nå» eller «bare adressen og teksten rundt».

**Gjennomgått område for område:**

| Område | KI-hjelp | Merknad |
|---|---|---|
| Lenketekst (vag, nettadresse, tom lenke som får tekst) | **Ny:** «Foreslå lenketekst med KI» | Målet leses trygt når det går; ellers sies det at forslaget bygger på adressen og teksten rundt. «Fjern lenken» finnes fortsatt for tomme lenker. |
| Tabelltittel | **Ny:** «Foreslå tabelltittel med KI» | Bare overskriftscellene og teksten rundt sendes – aldri dataradene. |
| Tittel på innebygd innhold | **Ny:** «Foreslå tittel med KI» (andre enn YouTube) | YouTube: videoens egen tittel først, KI-forslag via samme komponent. |
| Alt-tekst | Fantes (bildeanalyse, bakgrunnskø) | Knappen heter «Foreslå alternativtekst med KI». Krever en modell med bildeanalyse. Tas ikke lenger med i «Godkjenn alle klare». |
| Videotittel (Standardiser videoavspillere) | Fantes | YouTube-metadata først, KI bare når brukeren ber om det. |
| Emnedesign | Fantes: «Foreslå bedre oppbygging» | Plasserer eksisterende innhold i seksjoner; skriver ikke nytt innhold. |
| Quizer | Fantes: kvalitetssjekk mot emnets innhold, KI-spørsmålsbank | Fasit, poeng og innstillinger endres aldri automatisk. |
| Emnestruktur | Fantes: semantisk vurdering | Forslag med begrunnelse; ingenting flyttes uten godkjenning. |
| Illustrasjoner og bildetekster | Fantes: KI-bildeassistenten | Krever en leverandør med bildegenerering. |
| Transkripsjon | Fantes i Emnets kunnskapsbase (lokal NB-Whisper eller leverandør) | Transkripsjonene skrives ikke til Canvas – teksting av video må fortsatt lages i Canvas eller Studio. |
| Overskriftsnivå, falske overskrifter, tabelloverskrifter og scope, språkattributt, autoavspilling, opprydding, ny adresse etter omdirigering | Regelbasert | Sikkert med programlogikk; KI ville ikke tilføre noe. |
| Kontrast | Ikke egnet | Fargevalg er lærerens; EmneKlar foreslår ikke farger. |
| Dokumenter (PDF, Word, PowerPoint) | Ikke egnet her | Må rettes i kildefilen utenfor Canvas. |
| Sensoriske instruksjoner, tydeligere tekst, manglende overskrifter i lang tekst | Mangler | Ville omskrive faglig tekst; krever et eget valg om omskriving før det kan tilbys. |
| Masseforslag for lenketekst | Mangler | Alt-tekst har kø for mange bilder; lenketekst lages ett funn om gangen. |
| Alternativ lenke (Innholdskvalitet → Lenker) | **Ny:** «Finn alternativ lenke med KI» | Kandidater bare fra faktiske oppslag: videresending, nettsøk via leverandørens søkeverktøy (Anthropic `web_search_20250305`, OpenAI Responses `web_search`) og Internet Archive. KI velger høyst tre av kandidatene (id-er, aldri egne adresser) og begrunner; teknisk kontroll vises for seg. Uten søk forklares det, og manuelt søk tilbys. |
| Lenketekst i lenkeoversikten | **Ny:** «Foreslå lenketekst med KI» når adressen byttes | Samme tjeneste som i rettevinduet, basert på adressen. |
| Regelverkssamsvar, ukjente fakta, fasit, frister, poeng, vurderingsregler | Aldri | KI erklærer ikke samsvar og endrer ikke vurdering. |

## Sikkerhet

Se [THREAT_MODEL.md](THREAT_MODEL.md). Kort: kun 127.0.0.1, Host-sjekk (DNS-rebinding), øktcookie
(HttpOnly, SameSite=Strict), CSRF-token og Origin-sjekk, streng CSP, sandkasset forhåndsvisning av Canvas-HTML,
SSRF-vern for lenkesjekk, hemmeligheter i nøkkelring, sensurering av logger, isolerte dokumentparsere.

Grensesnittet serveres av backend: filene under `/assets` har innholdshash i navnet og sendes med
`Cache-Control: public, max-age=31536000, immutable` og gzip; `index.html` har `no-cache`, og API-svar har
`no-store` og komprimeres ikke (heller ikke hendelsesstrømmen).

## Emne-RAG

Canvas-verktøy → Emne-RAG bygger en lokal kunnskapsbase av ett emne og leser bare fra Canvas (se
[rag-plan.md](rag-plan.md)):

```
innhenting (lærerinnhold) ─► konvertering til Markdown-blokker (isolerte parserprosesser)
   ─► video: teksting → NB-Whisper ─► bilder: pyntfilter → bildemodell ─► chunking (struktur først)
   ─► (kontekstuell berikelse) ─► embedding (lokalt/leverandør) ─► rag\course-<id>.sqlite (FTS5 + vektorer)
spørsmål ─► BM25 + vektorsøk ─► RRF ─► rerangering ─► svar med kildehenvisninger (KI) eller treff (uten KI)
```

Bakgrunnsjobben lagrer hvert element når det er ferdig, så avbrutte bygg kan fortsettes, og oppdateringer
behandler bare elementer med endret signatur. Etter hver bygging måles søket med testspørsmål (recall@5, MRR).

## Emnedesign

Emnedesign (eget menypunkt, der Emneforside var før) gir hele emnet eller én modul ett design: Omfang → Design →
Forhåndsvisning → Godkjenning (vannrett stegvisning; et steg nås bare etter stegene foran). Ingenting publiseres fra
designvelgeren. Første steg viser hva omfanget faktisk inneholder (innholdsoversikten fra Canvas, med antall per
modul); designsteget trenger ikke innholdet, så læreren kan gå videre mens det leses.

* **Profiler som data** (`course_design/profiles.json`): designverdier (`tokens`) og komponentmaler (inline-stil per
  elementrolle) hver for seg. Fire profiler: Akademisk (standard), Lyst og moderne, Visuelt og pedagogisk og Grønn
  akademi. Emnet lagrer profil og versjon (`course_designs`); «Behold eksisterende design» lagres per element
  (`course_design_exclusions`).
* **Transformasjon** (`transform.py`): deterministisk og idempotent. Tidligere design fjernes først (klasser
  `ek-design*`, `data-ek-d` med egenskapene EmneKlar la til, og eksakt samsvar med deklarasjoner en profil lager eller har laget i en tidligere versjon (`retired_components`) –
  aldri bare én skjult markør), så gjentatt bruk og bytte av profil ikke gir doble innpakninger. Lærerens egne stiler
  fjernes aldri. «Behold oppbyggingen» legger bare til stil (og et banner med emnenavnet på forsiden); «Foreslå bedre
  oppbygging» bruker en KI-plan som valideres (hver blokk nøyaktig én gang, faste seksjonsoverskrifter, ingen tomme
  seksjoner).
* **Bevaringskontroll** før noe legges i køen: tekst, lenkemål, bilder og alt-tekst, innebygd innhold, medier, ankere,
  tabeller og tabelloverskrifter, bildetekster, kode, ligninger og overskrifter. Avvik stopper forslaget.
* **Endringsmotoren:** én endring per element med bare innholdsfeltet (`body`, `description`, `syllabus_body`);
  frister, poeng, fasit og innstillinger sendes aldri. Forhåndsvisningen har en innholdshash; er innholdet endret i
  Canvas før godkjenning, legges ingenting i køen. Konfliktsjekk ved publisering, «Lag forslaget på nytt» bruker
  designet på nytt på det nyeste innholdet (bare stil), sikkerhetskopi og angring som for andre endringer.

## KI-bildeassistent

Canvas-verktøy → KI-bildeassistent lager faglig presise illustrasjoner for hele emnet, én modul, flere moduler
eller én side, og setter dem inn etter godkjenning – eller, når læreren selv har valgt «Automatisk innsetting» for
kjøringen, setter den inn bilder som består kvalitetskontrollen uten gjennomgang (fortsatt via godkjenning og
publiseringsjobben i endringsmotoren; bilder som må kontrolleres, venter alltid):

```
kartlegging (Canvas, ingen KI): moduler med alle elementtyper, sider (paginert), sider i flere moduler én gang
   ─► nivå 1 emnekontekst ─► nivå 2 modulkontekst (med tidligere moduler) ─► nivå 3 hele siden, seksjon for seksjon
   ─► nivå 4 seksjonen (med før/etter) ─► bildeplan (0..n forslag, formål, bildetype, format, korte etiketter,
       må vise / må ikke vise, risiko, prompt)
   ─► bildemodell (+ designprofil, referansebilder, størrelse etter format) ─► multimodal kontroll (karakterer,
       tekstkontroll, alt-tekst, bildetekst)
       ─► ny runde ved behov ─► gjennomgang ─► endringsmotoren (opplasting, innsetting, konfliktsjekk, backup, logg)
```

* **Kontekstpakke** (`context.py`): `course_context`, `module_context`, `page_context`, `section_context`,
  `learning_objectives`, `key_concepts`, `pedagogical_purpose`, `visual_style_guide`, `existing_images`,
  `proposed_placement`, `image_requirements`, `content_language`. Emne- og modulanalysen hurtigbufres
  (`illustration_analyses`) og sendes videre som strukturerte sammendrag; lange sider kortes ned per seksjon.
* **Personvern** (`privacy.py`): bare sider, modulstruktur, emnebeskrivelse og emneplan leses; e-post, telefon,
  fødselsnummer og signerte URL-er fjernes før sending; kursinnhold sendes som avgrenset data.
* **Tekst i bilder:** bildene forklarer mest mulig visuelt. Diagrammer, modeller, infografikk og prosesser kan ha
  korte etiketter (høyst åtte, ett til tre ord, innholdets språk); planen angir dem ordrett, bildeprompten krever
  nøyaktig de etikettene og ingen annen tekst, og kontrollen avviser feilstavet eller uønsket tekst.
* **Figur i Canvas:** `figure` > `img` + `figcaption`, høyst 900 px (innstilling), responsiv, bildetekst
  venstrejustert, kreditering som egen `small`-linje, `loading="lazy"` lenger ned på siden. Etter publisering
  sjekkes figur, bilde, alt-tekst og bildetekst (må finnes) og valgfrie attributter (rapporteres hvis Canvas fjernet
  dem).
* **Plassering** (`htmlspans.py`, `structure.py`, `placement.py`): HTML leses med kildeposisjoner, og figurer
  skjøtes inn *mellom* blokker i innholdsbeholderen – aldri inne i avsnitt, lister, tabeller, iframes eller
  malkomponenter. Ankre er blokkens tag + hash av teksten. Lærerens HTML endres ikke et tegn; angring fjerner bare
  figurer med `data-emneklar-illustration`.
* **Publisering** (`publish.py`): egen endringstype `page.insert_illustrations` (konfliktsjekk mot siden ved
  forhåndsvisning, sikkerhetskopi, 3-stegs filopplasting med gjenbruk av samme fil ved nye forsøk, bare `body`
  sendes, kontroll etterpå, kirurgisk angring).
* **Jobb** (`pipeline.py`): kø med begrenset samtidighet, pause/avbryt, kostnadsmåler med grense per jobb,
  lagring underveis og «Fortsett» etter avbrudd. Re-kjøring gjenkjenner eksisterende illustrasjoner (fingeravtrykk
  per side, seksjon og begrep) og lager ikke dubletter.

## Oppdatering og drift

Én kodebase, én programpakke for alle plattformer og én Python-kjøretid per plattform. Windows er den eneste
plattformen som bygges og gis ut ([PLATFORMS.md](PLATFORMS.md)).

* **Installasjon (Windows):** `EmneKlar-<versjon>-setup.exe` (Inno Setup, per bruker, uten administratorrettigheter)
  legger programpakken og kjøretiden i `%LOCALAPPDATA%\Programs\EmneKlar`, lager snarveier i Start-menyen og på
  skrivebordet og kontrollerer at EmneKlar kan lastes. Ingen Python på maskinen brukes, og pip kjøres aldri.
* **Kjøretiden** (`runtime\`) er python.org sin «embeddable package» med avhengighetene ferdig installert, bygget av
  `scripts/build_runtime.py` fra hash-låste filer. `python314._pth` isolerer den fra miljøvariabler, registeret og
  brukerens egne pakker.
* **Start:** snarveien kjører `runtime\pythonw.exe -m emneklar` – uten konsollvindu. Nettleseren er
  brukergrensesnittet. Kjører EmneKlar allerede, åpnes bare en ny fane. Feil ved oppstart vises i en meldingsboks
  (`core/system.py`). `start.bat` starter det samme programmet i et konsollvindu.
* **Avslutting:** «Avslutt EmneKlar» i programmet (`POST /api/system/shutdown`, med økt og CSRF) eller snarveien i
  Start-menyen (`manage stop` over den lokale kontrollkanalen).
* **Oppdatering:** `update.bat` → `scripts/update.py` følger sekvensen: oppdag kjørende app → valider installasjon →
  sikkerhetskopi av data → sjekk versjon → hent oppdatering (og ny kjøretid når id-en er endret) → oppdater
  avhengigheter (bare installasjoner med eget Python-miljø) → migrer → bygg grensesnitt (bare Git) → helsesjekk →
  start på nytt, med tilbakerulling ved feil. Programfilene byttes fil for fil; kjøretiden byttes som en hel mappe.
  `update.bat` kjører skriptet med en kopi av tolkeren, slik at `runtime\` ikke er i bruk mens den byttes.
* **Avinstallering:** fra Windows-innstillingene. Programmet stoppes, programmappen og snarveiene fjernes, og
  datamappen blir liggende.
* **Reserveløsning:** zip-pakken med `setup.bat` (lager `backend\.venv` med en Python som finnes på maskinen og
  installerer de låste avhengighetene med pip) og `start.bat`.

Se [UPDATING.md](UPDATING.md) og [DEVELOPMENT.md](DEVELOPMENT.md).
