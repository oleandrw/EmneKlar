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
│  │ Global emnevelger, Dry run,  │ 127.0.0.1 │   CSRF, Origin, CSP)            │  │
│  │ endringskø, analysedialog    │  + SSE    │ features/*  (domener)           │  │
│  └──────────────────────────────┘           │ core/canvas (klient, snapshot)  │──┼─► Canvas REST API
│                                             │ core/changes (endringsmotor)    │  │
│  OS-nøkkelring ◄── token/nøkler ────────────│ core/ai (leverandører, ruter)   │──┼─► Valgt KI-leverandør
│  (Windows Credential Manager)               │ core/jobs (jobber, fremdrift)   │  │   (bare etter samtykke)
│                                             │ core/security/ssrf (lenkesjekk) │──┼─► Eksterne lenker
│  %LOCALAPPDATA%\EmneKlar-Claude\            │ core/storage (SQLite, Alembic)  │  │   (SSRF-beskyttet)
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
  main.py, launcher.py FastAPI-app og oppstart (engangslenke, gjenbruk av kjørende instans)
  api/                 felles avhengigheter og systemruter (helse, økt, Dry run, kontrollkanal)
  core/
    security/          web.py (økt/CSRF/Host/CSP), ssrf.py, sanitize.py, redaction.py, safe_zip.py, isolation.py
    auth/secrets.py    hemmeligheter i OS-nøkkelring
    storage/           db.py (SQLite + Alembic), models.py, settings.py (typede innstillinger)
    canvas/            client.py (lavnivå, skrivevern), api.py (typede kall), snapshot.py, html.py
    jobs/              manager.py (bakgrunnsjobber), progress.py, eta.py
    changes/           engine.py (endringskø, konflikt, backup, logg, angre), appliers.py
    backup/            store.py (sikkerhetskopier av Canvas-objekter)
    ai/                providers/, catalog.py (modellregister), router.py, service.py (personvern, logg)
    updates/           versjonssjekk mot GitHub Releases
    flags.py           funksjonsflagg
  features/
    analysis/          global analyse (orkestrerer analysatorer over ett snapshot)
    findings/          felles lagring, filtrering, «Ignorer»
    accessibility/     regelregister, profiler, kontroller, dokumentkontroller, rettinger
    content_quality/   lenkesjekk, medier, HTML-hygiene, opprydding med diff
    course_structure/  strukturanalyse, studentreise, flytteforslag
    quiz_assistant/    klassiske quizer, kvalitetssjekk, KI-spørsmålsbank, quizbygger
    homepage_builder/  stiler, seksjoner, Canvas-trygg HTML
    module_requirements/, blueprint/, canvas_settings/
    reporting/         HTML/CSV-rapporter
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
forslag (funksjon) ─► StagedChange (før, foreslått, begrunnelse, risiko, angremulighet)
     │ forhåndsvis / rediger / fjern
     ▼
godkjenn ─► konfliktsjekk (hent objektet på nytt, sammenlign med «før»)
     │            konflikt → stopp, krev ny vurdering
     ▼
Dry run? ─ ja ─► logg «simulert», ingen skrivende kall
     │ nei
     ▼
sikkerhetskopi (backups\) ─► skriv via CanvasClient + WritePermit ─► verifiser ─► endringslogg
     ▼
angre (der snapshot + API gjør det mulig, med ny konfliktsjekk)
```

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

## Sikkerhet

Se [THREAT_MODEL.md](THREAT_MODEL.md). Kort: kun 127.0.0.1, Host-sjekk (DNS-rebinding), øktcookie
(HttpOnly, SameSite=Strict), CSRF-token og Origin-sjekk, streng CSP, sandkasset forhåndsvisning av Canvas-HTML,
SSRF-vern for lenkesjekk, hemmeligheter i nøkkelring, sensurering av logger, isolerte dokumentparsere.

## Oppdatering og drift

* `setup.bat` installerer (Python-venv, avhengigheter, bygger grensesnittet om nødvendig).
* `start.bat` starter (eller gjenbruker kjørende instans) og åpner nettleseren.
* `update.bat` følger sekvensen: oppdag kjørende app → valider installasjon → sikkerhetskopi av data → sjekk
  versjon → hent oppdatering → oppdater avhengigheter → migrer → bygg grensesnitt → helsesjekk → start på nytt,
  med tilbakerulling ved feil. Se [UPDATING.md](UPDATING.md).
