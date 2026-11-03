# Implementeringsplan

Arbeidet gjøres i **vertikale, testbare skiver** på grenen `feature/emneklar-v1`. Hver skive leveres med
backend, frontend og tester før neste starter. Ingenting slås sammen med `main` uten eksplisitt godkjenning.

| # | Skive | Innhold | Verifisering | Status |
|---|---|---|---|---|
| 0 | Fundament | Konfig, datamappe, sikkerhetsmellomvare, økter, hemmeligheter, sensurering, logging, SQLite + Alembic, jobbmotor + ETA, Canvas-klient med skrivevern, oppstart (launcher), design-system, app-skall | `pytest` (sikkerhet, migrering, ETA, jobber), typesjekk, bygg | Ferdig |
| 1 | Canvas-tilkobling | Oppsettveiviser (9 steg), test av tilkobling, identitet, tilgangssjekk, emneliste, global emnevelger, innstillinger for Canvas | Falsk Canvas (ASGI) i tester: auth, paginering, 429/403-rate limit, tidsavbrudd, tilganger | Ferdig |
| 2 | Analyse + UU | Snapshot, global analysedialog, ekte fremdrift (SSE, ETA, pause/avbryt/bakgrunn), regelregister + profiler, UU-kontroller (bilder, overskrifter, lenker, tabeller, lister, språk/instruksjoner, kontrast, iframe, media, dokumenter), funnliste, Oversikt | Enhetstester per regel, integrasjonstest mot falsk Canvas | Ferdig |
| 3 | Endringsmotor | Endringskø (header + skuff), forhåndsvisning/diff, Dry run, konfliktsjekk, sikkerhetskopi, logg, angre; UU-rettinger (alt-tekst, dekorativ, iframe-tittel, overskriftsnivå, tabelloverskrifter) | Tester for stage/preview/dry run/apply/snapshot/konflikt/angre | Ferdig |
| 4 | Innholdskvalitet | Lenkesjekk (SSRF-vern, tilstander), interne Canvas-lenker, medier, HTML-hygiene, konservativ opprydding med diff | SSRF-tester, tilstandsklassifisering, opprydding bevarer innhold | Ferdig |
| 5 | Emnestruktur | Analyse (plassering, duplikater, navngiving, progresjon, introduksjon), forslag med bevis og sikkerhet, studentreise, flytting via endringskø | Ingen stille flytting; forslag → endring | Ferdig |
| 6 | KI-lag | Leverandører (OpenAI, Anthropic, Azure, lokal), modellregister, ruter med strategier og reserve, personvern (av som standard, samtykke, nyttelastoppsummering), innstillinger | Ruting (billig/kvalitet/bilde/reserve), uten KI, hemmeligheter | Ferdig |
| 7 | Quizassistent | Klassiske quizer: henting, parsing, fasit, deterministiske kontroller, kildeforankret KI-sjekk; KI-spørsmålsbank; quizbygger (innstillinger, forhåndsinnstillinger, spørsmålsgrupper «X av Y», upublisert), dekningsanalyse | Parsing, fasit, grupper, forankring | Ferdig |
| 8 | Emneforside | Tre moduser, fire stiler, seksjoner, Canvas-trygg HTML, forhåndsvisning (PC/nettbrett/mobil), «Opprett som ny side» (standard), «Erstatt» med bekreftelse + sikkerhetskopi | Sanering, mobil/PC, backup før erstatning | Ferdig |
| 9 | Canvas-verktøy | Automatiske modulkrav, Blueprint-låsing (oppdagelse + masselåsing), Canvas-innstillinger (kategoriserte forslag), Backup og endringslogg | Kombinasjoner verifisert mot API-dokumentasjon | Ferdig |
| 10 | Rapporter | Fem rapporttyper, HTML (utskriftsvennlig → PDF via nettleser), CSV; omfang, dato, regelsettversjon, profil, begrensninger | Innhold og formater | Ferdig |
| 11 | Innstillinger, hjelp, flagg, oppdatering | Alle innstillingsseksjoner, funksjonsflagg, hjelpesenter, `setup.bat`/`start.bat`/`update.bat`, versjonssjekk | Oppdateringslogikk (versjon, backup, feil) | Ferdig |
| 12 | Kvalitet og levering | Playwright + axe (tastatur, fokus, dialoger, responsivitet), GitHub Actions, dokumentasjon, CHANGELOG | Hele testpakken grønn | Ferdig |

## Definisjon av ferdig (v1)

Se kravlisten i prosjektbeskrivelsen. Funksjoner som Canvas-API-et ikke støtter, vises som utilgjengelige med
en sannferdig forklaring – aldri som simulert suksess.
