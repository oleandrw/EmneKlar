# Domene- og datamodell

All persistent data ligger i `%LOCALAPPDATA%\EmneKlar\database.db` (SQLite, WAL) og filer under samme mappe.
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
| `analysis_runs` | Én analysekjøring (domener, omfang, regelsettversjon, profil + versjon, status, begrensninger, `counts`) | Knyttet til snapshot. `counts` er åpne funn kjøringen lagret, per `domene:klasse` – samme tall som sidene viser |
| `findings` | Funn: domene, regel, klassifisering, testmetode, alvorlighet, sikkerhet, objekt, plassering, bevis, forslag, mulig retting, fingeravtrykk, status | Fingeravtrykk = stabil identitet på tvers av kjøringer; lagres én gang per kjøring |
| `finding_decisions` | Brukerens beslutninger som overlever ny analyse: «Ignorer» med notat, eller «Kontrollert» (`verified`) med bekreftelsen fra regelen (`reason`, f.eks. `transcript`) og notat. Funnets status blir beslutningen (`ignored` / `verified`). | Fingeravtrykk |
| `media_assessments` | Lærerens opplysning om hva et opptak er (`audio`, `video`, `video_no_audio`) per emne og medienøkkel (`media:<id>`, `attachment:<id>`, `youtube:<id>`, `vimeo:<id>`, `src:<adresse>`). Brukes i analysen foran Canvas' metadata og avgjør om 1.2.1 eller 1.2.2 kontrolleres (migrering 0006). | Emne + medienøkkel |
| `link_checks` | Hurtigbuffer for lenkesjekk (tilstand WORKING/REDIRECT/DEAD/TIMEOUT/AUTH_REQUIRED/UNKNOWN, HTTP-kode, endelig URL) | SHA-256 av normalisert URL |

## Endringer, sikkerhetskopi og logg

| Tabell | Innhold |
|---|---|
| `staged_changes` | Endringskøen: domene, type (`page.update_body`, `module_item.update`, `quiz.create`, …), Canvas-objekt, **før**, **foreslått**, begrunnelse, risiko (lav/middels/høy), angremulighet (full/delvis/ingen) med forklaring, konfliktstatus, status (`staged`, `approved`, `applying`, `applied`, `failed`, `conflict`, `discarded`, `undone`), krever bekreftelse, KI-generert, kilde (funn/forslag; for rettinger også `fixes` – oppskriftene som lar endringen bygges på nytt på nyere innhold) |
| `backups` | Sikkerhetskopi av objektet slik det var i Canvas rett før endring (JSON-fil i `backups\objects\`, SHA-256) |
| `change_log` | Uforanderlig logg: tidspunkt, emne, objekt, handling (`apply`, `undo`, `failed`, `conflict`; `dry_run` bare i innslag fra før Dry run ble fjernet), før, etter, regel/begrunnelse, API-resultat, brukerhandling, sikkerhetskopi, angret av. Kolonnen `dry_run` er fjernet i migrering 0005. |
| `alt_text_suggestions` | KI-forslag til alt-tekst per bildefunn (fingeravtrykk): status (`queued`, `running`, `ready`, `failed`), forslag, dekorativt, bildetype, sikkerhet, merknad, leverandør/modell, feil, og `input_hash` (bilde, kontekst, side, alt-tekst, promptversjon) – uendret input sendes aldri på nytt. Innholdet sendes aldri til Canvas før læreren godkjenner en retting. |

## KI

| Tabell | Innhold |
|---|---|
| `ai_models` | Modellregisteret: leverandør, modell-id, tekst, bilde, strukturert svar, kontekst-/kvalitets-/hastighets-/kostnadsklasse, aktivert, kilde (katalog/oppdaget/bruker), egenskaper kjent |
| `ai_usage` | Metadata om hver KI-forespørsel (oppgave, modell, begrunnelse for valg, reserve brukt, tokens, oppsummering av nyttelast) – **aldri innhold** |

Leverandøroppsett (endepunkt, API-versjon, aktivert) ligger i innstillingene; nøkler i nøkkelringen.

## Quiz og rapporter

| Tabell | Innhold |
|---|---|
| `question_bank` | KI-spørsmålsbanken: type (enkeltvalg, flervalg, sant/usant – utvidbart), spørsmål, svar med fasit, forklaring, kilder (objekt + sitat), modul, tema, vanskelighetsgrad, vurderingsstatus (utkast/godkjent/forkastet), opphav (KI/manuell), forankring (verifisert/delvis/uverifisert), generator, brukt i |
| `quiz_presets` | Forhåndsinnstillinger (Øvingsquiz, Avsluttende test, Egenvurdering, egne), standard for nye quizer |
| `reports` | Genererte rapporter (type, format, filnavn i `reports\`, kjøringer som inngår) |

## Emne-RAG

| Tabell / fil | Innhold |
|---|---|
| `rag_indexes` | Register med én rad per emne: status (tom/bygges/klar/ufullstendig/feilet), valg (omfang, kildetyper, filtyper), embedding-modell, statistikk, hoppede elementer med begrunnelse, begrensninger, siste evaluering (recall@5, MRR, helsescore, testspørsmål), siste jobb og når indeksen sist ble bygget. |
| `rag\course-<id>.sqlite` | Selve indeksen (egen SQLite-fil, `application_id` «EkRG», skjemaversjon): `items` (element, modul, `updated_at`, `content_hash`, signatur, status), `chunks` (tekst, kontekst, type `text/table/image/transcript/slide`, overskriftssti, modul, kilde-URL, sidetall, tidsstempel, metadata, vektor som float32) og `chunks_fts` (FTS5 over norske ordstammer). Kan bygges på nytt fra Canvas. |

## Emnedesign

| Tabell | Innhold |
|---|---|
| `course_designs` | Emnedesign: emnets designprofil og versjon, behandlingsmåte (`keep` / `structure`) og om illustrasjoner er valgt. Å lagre valget endrer ikke innhold. Nøkkel: emne (migrering 0007). |
| `course_design_exclusions` | «Behold eksisterende design»: innhold emnets design ikke foreslås for (`page:<url>`, `assignment:<id>`, `quiz:<id>`, `syllabus:<id>`). Nøkkel: emne + element. |

## KI-bildeassistent

| Tabell | Innhold |
|---|---|
| `illustration_profiles` | Designprofil per emne, versjonert (stil, palett, kontrast, lys, komposisjon, bakgrunn, detaljnivå, format, kjennetegn, hva som ikke skal med), aktiv versjon, opphav (forhåndsvalg/KI/egen) og referansebilder (asset-id-er) |
| `illustration_runs` | Én kjøring over et omfang: status, omfang, valg (kvalitetsprofil, mengde, modeller, kostnadsgrense, automatisk innsetting), designprofil, jobb, kartlegging og sidestatus, kostnadsanslag, faktisk forbruk, emne- og modulkontekst (sammendrag), begrensninger |
| `illustration_analyses` | Hurtigbuffer for KI-analyse av emne, modul og side (nøkkel: objekt + hash av inndata + analyseversjon) |
| `illustrations` | Ett forslag: modul, side, seksjon (tekst før/etter), anker, pedagogisk plan (formål, begrep, læringsmål, motiv, må vise / må ikke vise, risiko, merverdi), bildetype, format, korte etiketter, bildeprompt, stil, bildeversjoner med kontrollresultat, alt-tekst, dekorativ, bildetekst, kreditering, status, endring i køen, publiseringsinfo (med kontroll av hva Canvas beholdt), fingeravtrykk (mot dubletter) |
| `illustration_assets` | Genererte bilder: fil i datamappen, SHA-256, format, størrelse, modell, Canvas-fil-id etter opplasting |

## Filer i datamappen

```
%LOCALAPPDATA%\EmneKlar\
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
  kopiert-fra-EmneKlar-Claude.json   finnes bare når dataene ble kopiert fra det tidligere mappenavnet (når, hva)
  run\instance.json     kjørende instans (port, kontrollhemmelighet) – slettes ved avslutning
```

## Domenebegreper

* **Funn** – klassifisering: *Avvik*, *Sannsynlig avvik*, *Bør vurderes*, *Forbedringsforslag*, *Manuell kontroll*.
  Klassene `violation` og `likely_violation` heter *Avvik* / *Sannsynlig avvik* bare i universell utforming; i
  Innholdskvalitet, Emnestruktur og Quiz heter de *Feil* / *Sannsynlig feil* (lagret verdi er den samme).
  Testmetode: *deterministisk*, *heuristisk*, *KI-assistert*, *manuell*. Sikkerhet: høy/middels/lav.
* **Regel** – metadata i det versjonerte regelsettet: id, tittel, kategori, WCAG-kriterium, WCAG-versjon, nivå,
  testbarhet, alvorlighet, kilde, forklaring, berørte brukere, rettepolicy, regelsettversjon.
* **Regulatorisk profil** – versjonert datasett som sier hvilke kriterier som er lovkrav (og under hvilke vilkår)
  for en gitt sektor; lovstatus beregnes per funn fra valgt profil.
* **Forslag** (struktur, modulkrav, innstillinger, quiz) – blir en `StagedChange` først når brukeren godkjenner.
