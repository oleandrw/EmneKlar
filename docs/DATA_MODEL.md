# Domene- og datamodell

All persistent data ligger i `%LOCALAPPDATA%\EmneKlar-Claude\database.db` (SQLite, WAL) og filer under samme mappe.
Skjemaet endres bare med Alembic-migreringer (`backend/migrations`). Hemmeligheter ligger aldri her.

## Kjerneobjekter

| Tabell | Innhold | Nøkler / merknader |
|---|---|---|
| `settings` | Én rad (`app`) med typede innstillinger (`AppSettings`, Pydantic) | Ingen hemmeligheter |
| `web_sessions` | Økter (SHA-256 av cookie, CSRF-token, sist sett) | Utløper etter 30 dager uten bruk |
| `courses` | Hurtigbuffer av emner fra Canvas (navn, kode, semester, Blueprint, startside) | Canvas-id |
| `snapshots` | Ett normalisert nedlastet emne per analyse (omfang, status, statistikk, feil per innholdstype) | Gjenbrukes av alle analysatorer i kjøringen |
| `snapshot_objects` | Sider, oppgaver, diskusjoner, quizer, quizspørsmål, filer, moduler, modulelementer, emneplan, forside | `(snapshot_id, object_type, canvas_id)`; `body` = HTML, `meta` = JSON |
| `jobs` | Bakgrunnsjobber (type, status, parametre, siste fremdrift, resultat, feil) | UUID |
| `analysis_runs` | Én analysekjøring (domener, omfang, regelsettversjon, profil + versjon, status, begrensninger) | Knyttet til snapshot |
| `findings` | Funn: domene, regel, klassifisering, testmetode, alvorlighet, sikkerhet, objekt, plassering, bevis, forslag, mulig retting, fingeravtrykk, status | Fingeravtrykk = stabil identitet på tvers av kjøringer |
| `finding_decisions` | Brukerens beslutninger som overlever ny analyse («Ignorer» med notat) | Fingeravtrykk |
| `link_checks` | Hurtigbuffer for lenkesjekk (tilstand WORKING/REDIRECT/DEAD/TIMEOUT/AUTH_REQUIRED/UNKNOWN, HTTP-kode, endelig URL) | SHA-256 av normalisert URL |

## Endringer, sikkerhetskopi og logg

| Tabell | Innhold |
|---|---|
| `staged_changes` | Endringskøen: domene, type (`page.update_body`, `module_item.update`, `quiz.create`, …), Canvas-objekt, **før**, **foreslått**, begrunnelse, risiko (lav/middels/høy), angremulighet (full/delvis/ingen) med forklaring, konfliktstatus, status (`staged`, `approved`, `applying`, `applied`, `failed`, `conflict`, `discarded`, `undone`), krever bekreftelse, KI-generert, kilde (funn/forslag) |
| `backups` | Sikkerhetskopi av objektet slik det var i Canvas rett før endring (JSON-fil i `backups\objects\`, SHA-256) |
| `change_log` | Uforanderlig logg: tidspunkt, emne, objekt, handling (`apply`, `undo`, `dry_run`, `failed`, `conflict`), før, etter, regel/begrunnelse, API-resultat, brukerhandling, Dry run, sikkerhetskopi, angret av |

## KI

| Tabell | Innhold |
|---|---|
| `ai_models` | Modellregisteret: leverandør, modell-id, tekst, bilde, strukturert svar, kontekst-/kvalitets-/hastighets-/kostnadsklasse, aktivert, kilde (katalog/oppdaget/bruker), egenskaper kjent |
| `ai_usage` | Metadata om hver KI-forespørsel (oppgave, modell, begrunnelse for valg, reserve brukt, tokens, oppsummering av nyttelast) – **aldri innhold** |

Leverandøroppsett (endepunkt, API-versjon, aktivert) ligger i innstillingene; nøkler i nøkkelringen.

## Quiz, forside, rapporter

| Tabell | Innhold |
|---|---|
| `question_bank` | KI-spørsmålsbanken: type (enkeltvalg, flervalg, sant/usant – utvidbart), spørsmål, svar med fasit, forklaring, kilder (objekt + sitat), modul, tema, vanskelighetsgrad, vurderingsstatus (utkast/godkjent/forkastet), opphav (KI/manuell), forankring (verifisert/delvis/uverifisert), generator, brukt i |
| `quiz_presets` | Forhåndsinnstillinger (Øvingsquiz, Avsluttende test, Egenvurdering, egne), standard for nye quizer |
| `homepage_drafts` | Forsideutkast: modus, stil, seksjoner, HTML, merknader om usikkert innhold, KI brukt |
| `reports` | Genererte rapporter (type, format, filnavn i `reports\`, kjøringer som inngår) |

## Emne-RAG

| Tabell / fil | Innhold |
|---|---|
| `rag_indexes` | Register med én rad per emne: status (tom/bygges/klar/ufullstendig/feilet), valg (omfang, kildetyper, filtyper), embedding-modell, statistikk, hoppede elementer med begrunnelse, begrensninger, siste evaluering (recall@5, MRR, helsescore, testspørsmål), siste jobb og når indeksen sist ble bygget. |
| `rag\course-<id>.sqlite` | Selve indeksen (egen SQLite-fil, `application_id` «EkRG», skjemaversjon): `items` (element, modul, `updated_at`, `content_hash`, signatur, status), `chunks` (tekst, kontekst, type `text/table/image/transcript/slide`, overskriftssti, modul, kilde-URL, sidetall, tidsstempel, metadata, vektor som float32) og `chunks_fts` (FTS5 over norske ordstammer). Kan bygges på nytt fra Canvas. |

## KI-bildeassistent

| Tabell | Innhold |
|---|---|
| `illustration_profiles` | Designprofil per emne, versjonert (stil, palett, kontrast, lys, komposisjon, bakgrunn, detaljnivå, format, kjennetegn, hva som ikke skal med), aktiv versjon, opphav (forhåndsvalg/KI/egen) og referansebilder (asset-id-er) |
| `illustration_runs` | Én kjøring over et omfang: status, omfang, valg (kvalitetsprofil, mengde, modeller, kostnadsgrense, automatisk innsetting), designprofil, jobb, kartlegging og sidestatus, kostnadsanslag, faktisk forbruk, emne- og modulkontekst (sammendrag), begrensninger |
| `illustration_analyses` | Hurtigbuffer for KI-analyse av emne, modul og side (nøkkel: objekt + hash av inndata + analyseversjon) |
| `illustrations` | Ett forslag: modul, side, seksjon (tekst før/etter), anker, pedagogisk plan (formål, begrep, læringsmål, motiv, må vise / må ikke vise, risiko, merverdi), bildeprompt, stil, bildeversjoner med kontrollresultat, alt-tekst, dekorativ, bildetekst, status, endring i køen, publiseringsinfo, fingeravtrykk (mot dubletter) |
| `illustration_assets` | Genererte bilder: fil i datamappen, SHA-256, format, størrelse, modell, Canvas-fil-id etter opplasting |

## Filer i datamappen

```
%LOCALAPPDATA%\EmneKlar-Claude\
  database.db           SQLite-databasen
  backups\objects\      sikkerhetskopier av Canvas-objekter før endring (JSON)
  backups\database\     kopi av databasen før migrering/oppdatering
  reports\              genererte rapporter (HTML/CSV)
  logs\emneklar.log     strukturert logg (JSON-linjer, sensurert)
  cache\                midlertidige nedlastinger (dokumentanalyse); cache\rag\ har transkripsjoner (lokale og
                        fra KI-leverandør), bildebeskrivelser og kontekstsetninger for Emne-RAG (nøkkel = SHA-256),
                        og YouTube-/Vimeo-teksting (nøkkel = tjeneste og video-id, brukes i 30 dager)
  rag\                  Emne-RAG-indekser, én SQLite-fil per emne
  illustrations\        KI-bildeassistent: genererte bilder per emne (<emne-id>\<asset>.png) og miniatyrer
  models\               lokale modeller for Emne-RAG (Hugging Face-buffer og konverterte NB-Whisper-modeller)
  run\instance.json     kjørende instans (port, kontrollhemmelighet) – slettes ved avslutning
```

## Domenebegreper

* **Funn** – klassifisering: *Avvik*, *Sannsynlig avvik*, *Bør vurderes*, *Forbedringsforslag*, *Manuell kontroll*.
  Testmetode: *deterministisk*, *heuristisk*, *KI-assistert*, *manuell*. Sikkerhet: høy/middels/lav.
* **Regel** – metadata i det versjonerte regelsettet: id, tittel, kategori, WCAG-kriterium, WCAG-versjon, nivå,
  testbarhet, alvorlighet, kilde, forklaring, berørte brukere, rettepolicy, regelsettversjon.
* **Regulatorisk profil** – versjonert datasett som sier hvilke kriterier som er lovkrav (og under hvilke vilkår)
  for en gitt sektor; lovstatus beregnes per funn fra valgt profil.
* **Forslag** (struktur, modulkrav, innstillinger, quiz) – blir en `StagedChange` først når brukeren godkjenner.
