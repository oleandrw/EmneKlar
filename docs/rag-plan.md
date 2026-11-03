# Emne-RAG – plan

*Skrevet før implementeringen (november 2026). Planen beskriver valg og antakelser; brukerveiledningen står i
README og i programmets hjelp.*

## Mål

Et nytt verktøy under **Canvas-verktøy → Emne-RAG** (`/canvas-verktoy/emne-rag`) som bygger en lokal
kunnskapsbase (RAG-indeks) av et Canvas-emne – hele emnet eller valgte moduler – med tekst, dokumenter, bilder
og video, og lar læreren stille spørsmål med klikkbare kildehenvisninger. Primærnavigasjonen endres ikke
(CLAUDE.md, invariant 1): verktøyet er et kort på Canvas-verktøy-siden, slik brukeren ba om.

Verktøyet **leser** bare fra Canvas. Det skriver aldri til Canvas, så endringsmotoren er ikke involvert
(invariant 2 gjelder skriving).

## Gjenbruk av eksisterende infrastruktur

| Behov | Gjenbrukes |
|---|---|
| Canvas-kall, paginering, struping, nedlasting | `core/canvas/client.py`, `core/canvas/api.py` (nye lesekall legges her) |
| HTML-tolking, Canvas-lenker, medier i HTML | `core/canvas/html.py` (`parse_html`, `canvas_ref`, `find_media`) |
| Bakgrunnsjobb, fremdrift, pause, avbryt, SSE | `core/jobs` (`JobManager`, `ProgressTracker`), frontend `JobRunner`/`ProgressPanel` |
| Utrygge dokumenter | `core/security/isolation.py` (egne arbeidsprosesser), `safe_zip.py`, `defusedxml` |
| Eksterne bilder | `core/security/ssrf.py` + `guarded_http.py` (som KI-alt-tekst) |
| KI (berikelse, bilder, svar, testspørsmål) | `core/ai/service.py` + ruteren (nye oppgavetyper), personvernporten og `AiConsent` i frontend |
| Innstillinger, funksjonsflagg | `core/storage/settings.py` (ny del `rag`), `core/flags.py` (flagg `course_rag`) |
| UI | design-systemet (`Card`, `Tabs`, `RadioGroup`, `Checkbox`, `DataTable`, `Alert`, `FeatureCard` …) |

Nytt delt lag i kjernen: **`core/ai/local/`** – lokale modeller (embedding, reranker, tale-til-tekst) med lat
lasting, nedlastingsstatus og CUDA-deteksjon. Modellnavn står i en versjonert katalog
(`core/ai/local_models.json`), ikke i funksjonskoden (invariant 3).

## Filer

```
backend/emneklar/core/ai/local/        __init__.py (katalog, status, enhet), embedding.py, rerank.py, whisper.py
backend/emneklar/core/ai/local_models.json
backend/emneklar/core/ai/providers/openai_compat.py   + embeddings (OpenAI, Azure, Ollama/LM Studio)
backend/emneklar/core/ai/router.py     + oppgavetyper rag_answer, rag_context, rag_image, rag_query, rag_eval
backend/emneklar/core/storage/models.py + RagIndex (register over indekser)  → migrering 0002
backend/emneklar/features/course_rag/
  api.py          ruter: status, estimat, bygg/oppdater, spør, feilsøk, evaluering, eksport, innstillinger
  sources.py      innhenting fra Canvas (moduler, sider, oppgaver, lærerinnlegg, quizbeskrivelser, filer, medier)
  convert/        html_md.py (HTML → Markdown), documents.py (PDF/DOCX/PPTX/XLSX/ODF/RTF/CSV/TXT/MD → enheter)
  markdown.py     Markdown → blokker med overskriftssti
  chunking.py     strukturbasert chunking, tabeller, lysbilder, transkripsjoner
  text.py         norsk stemming (Snowball) og stoppord for BM25
  store.py        én SQLite-fil per emne: elementer, chunks, FTS5, vektorer
  search.py       hybridsøk (BM25 + vektor) med RRF, filtrering, rerangering, spørreomskriving
  answer.py       svar med kildehenvisninger
  media.py        video/lyd: Canvas-teksting, YouTube-teksting, NB-Whisper, segment-chunking, nøkkelbilder
  images.py       bildeinnsamling, pyntfilter, perceptuell hash, bildebeskrivelser
  enrich.py       kontekstuell berikelse (contextual retrieval)
  evaluation.py   testspørsmål, recall@5, MRR, helsescore
  export.py       ZIP (JSONL + vektorer), Markdown, Word, PDF, tekst
  builder.py      bakgrunnsjobben (faser, gjenopptak, inkrementell oppdatering)
frontend/src/features/canvas-tools/rag/   CourseRag.tsx (faner), BuildPanel, AskPanel, QualityPanel, ExportPanel,
                                           SettingsPanel, api.ts
backend/tests/test_course_rag_*.py         enhetstester + integrasjonstest mot falsk Canvas
```

## Avhengigheter

* **Alltid installert** (små hjul for Windows og Linux, CPython 3.11–3.14): `numpy` (vektorsøk), `Pillow`
  (bildefilter, perceptuell hash), `pypdfium2` (gjengi skannede PDF-sider for OCR), `fpdf2` (PDF-eksport),
  `av` (PyAV med FFmpeg innebygd: henter ut lyden for transkripsjon via KI-leverandør og nøkkelbilder).
  Låses i `backend/constraints.txt`.
* **Valgfritt, «lokale modeller»** (`pip install -e "backend[rag]"`): `sentence-transformers` (BGE-M3,
  bge-reranker-v2-m3; drar med PyTorch), `faster-whisper` (CTranslate2 + PyAV, som har FFmpeg innebygd – ingen
  egen ffmpeg-installasjon), `youtube-transcript-api`. Installeres med `setup.bat --rag` eller dobbeltklikk på
  `setup-emne-rag.bat`. Valget huskes i `backend\.venv\emneklar-extras.txt`, så `update.bat` beholder det.
  Grunnen til at dette er valgfritt: PyTorch og modellene er flere GB; resten av EmneKlar skal fortsatt
  installeres raskt.
* **Ikke valgt:** Docling (drar med PyTorch og egne layoutmodeller, og kjører ikke i de isolerte
  parserprosessene) og PyMuPDF (AGPL-lisens). LanceDB/sqlite-vec trengs ikke: et emne har sjelden over noen
  titusen chunks, og eksakt vektorsøk med numpy over vektorer lagret i SQLite er raskt nok, krever ingen
  utvidelse som må lastes i SQLite og fungerer likt på alle Windows-installasjoner. FTS5 er med i Pythons SQLite
  på Windows; finnes det ikke, brukes en BM25-reserve i Python.

## Lagring

* Hoveddatabasen får tabellen `rag_indexes` (én rad per emne: status, valg, modell, statistikk, hoppede elementer,
  evaluering, sist bygget) via Alembic-migrering `0002`.
* Selve indeksen ligger i `%LOCALAPPDATA%\EmneKlar-Claude\rag\course-<id>.sqlite` (én fil per emne), merket med
  egen `PRAGMA application_id` og skjemaversjon. Den er avledet data som kan bygges på nytt; ved ny skjemaversjon
  bes brukeren bygge indeksen på nytt.
* Buffer: `cache\rag\transcripts\<sha256>.json` (nøkkel = filhash), `cache\rag\images\<sha256>.json`.
* Modeller: `%LOCALAPPDATA%\EmneKlar-Claude\models` (Hugging Face-buffer), aldri delt med andre programmer.

## Faser (én commit per fase)

1. **Innhenting + tekst/dokumenter + chunking + indeks + hybridsøk + rerank + enkel chat med kilder.**
   Omfang (hele emnet / moduler), kildetyper og filtyper, estimat, bakgrunnsjobb med fremdrift, pause, avbryt og
   gjenopptak (ferdige elementer lagres fortløpende), BM25 + vektor + RRF + reranker, svar med kilder (KI) eller
   rene søketreff (uten KI).
2. **Video/lyd:** Canvas-teksting (`media_attachments/:id/media_tracks?include[]=webvtt_content`, sporadresser fra
   `courses/:id/media_objects`), YouTube-teksting, ellers NB-Whisper lokalt (modellstørrelse etter GPU/CPU,
   annet språk → Whisper large-v3) eller via KI-leverandør (se under), segmenter på 60–120 s med overlapp, buffer
   på filhash, valgfrie nøkkelbilder.
3. **Bilder:** innsamling fra sider, dokumenter og bildefiler, pyntfilter (størrelse, form, filnavn, duplikater
   med dHash), beskrivelse med bildemodell via KI-laget (Claude-API eller lokal VLM), alt-tekst som ekstra
   input, egne bilde-chunks.
4. **Kontekstuell berikelse** (prompt caching per dokument), **inkrementell oppdatering**, **evaluering**
   (15–20 testspørsmål, recall@5, MRR, helsescore, feilsøkingsvisning) og **eksport** (ZIP med JSONL og vektorer,
   Markdown, Word, PDF, ren tekst). CHANGELOG, README og hjelp.

## Personvern (krav)

* Bare lærerprodusert innhold: sider, oppgavebeskrivelser, quizbeskrivelser, emneplan og diskusjonstemaer der
  forfatteren er lærer/assistent/designer i emnet (`courses/:id/users?enrollment_type[]=teacher|ta|designer`, bare
  id-er brukes og lagres ikke). Svar i diskusjoner (`entries`/`view`) hentes **aldri**. Innleveringer,
  karakterer, meldinger og studentdata hentes aldri.
* Medieobjekter tas bare med når lærerens innhold peker på dem (emnets medieliste kan inneholde studentopptak).
* Filer som er lastet opp av andre enn lærere i emnet, hoppes over.
* KI er valgfritt og går gjennom personvernporten med oppsummering før sending. Embedding, reranking og
  transkripsjon kjører lokalt som standard. Transkripsjon via KI-leverandør er et eget valg: bare lyden sendes,
  bare etter samtykke i estimatet. Svar merkes «KI-forslag – må vurderes».

## Antakelser og valg

* «Velg emne» bruker den globale emnevelgeren i toppen av EmneKlar.
* «Jeg vil også ha forskjellige alternativer. PDF, WORD …» står under eksport og tolkes som **eksportformater**
  (Word, PDF, Markdown, tekst i tillegg til ZIP), slik at kunnskapsbasen kan lastes opp i verktøy som NotebookLM
  eller Copilot. I tillegg leses flere filtyper enn de som er nevnt: ODT/ODP/ODS, RTF, CSV, HTML og
  undertekstfiler (VTT/SRT). Gamle binærformater (DOC/PPT/XLS) hoppes over med forklaring.
* Upubliserte elementer tas ikke med som standard (kan slås på).
* Uten lokale modeller eller embedding-API brukes bare nøkkelordsøk (BM25); grensesnittet sier det tydelig.
  Embedding kan også gå via en OpenAI-kompatibel leverandør (f.eks. Ollama med `bge-m3` lokalt).
* NB-Whisper finnes offisielt i Transformers-format. EmneKlar laster ned den offisielle modellen og konverterer
  den lokalt til CTranslate2 første gang (krever lokale modeller), i stedet for å stole på uoffisielle
  konverteringer.
* Kostnad: EmneKlar lagrer ikke priser (se modellkatalogen), så estimatet viser antall KI-kall, tokens og valgt
  modell, ikke kroner. Tidsestimatet er et grovt anslag med oppgitte forutsetninger.
* Varighet for Canvas-video beregnes fra `media_sources` (størrelse og bitrate) når det finnes; ellers vises
  «ukjent varighet».
* Tidsstempel-lenker: YouTube (`&t=`) og Vimeo (`#t=`) åpnes på riktig sted. Canvas-video kan ikke åpnes på et
  bestemt tidspunkt via lenke; lenken går til siden/filen, og tidsstempelet vises i kildehenvisningen.
* Panopto, Kaltura (LTI) og Vimeo uten offentlig teksting kan ikke leses via Canvas-API-et og vises som hoppet over
  med forklaring. Lyd fra YouTube lastes ikke ned (YouTubes vilkår); uten teksting hoppes videoen over.
* Skannede PDF-er: OCR med Tesseract hvis det er installert (norsk språkpakke), ellers med bildemodell via KI
  hvis bilder er slått på og KI er tillatt; ellers hoppes filen over med forklaring.
* Evalueringen måler om søket finner tilbake utdraget et testspørsmål ble laget fra (gjenfinning), ikke hvor
  gode svarene er. Uten KI lages testspørsmål av utdragets mest særpregede ord, og det står i rapporten.

## Transkripsjon via KI-leverandør

Lagt til etter fase 4, for maskiner uten GPU eller uten plass til lokale modeller. Valget står under
Emne-RAG → Innstillinger → Transkripsjon (lokalt / via KI-leverandør / av), med leverandør, modell og språk.

* Leverandører: OpenAI, Azure OpenAI (deploymentnavnet er modell-id-en) og egne OpenAI-kompatible servere
  (`/audio/transcriptions`, multipart). Andre leverandørtyper vises som utilgjengelige med forklaring.
* Modeller står i `core/ai/transcription_models.json` (ingen modellnavn i funksjonskoden): `gpt-transcribe`
  (standard), `gpt-4o-mini-transcribe` og `whisper-1`. Det står også om modellen gir tidsstempler per segment;
  en ukjent modell-id prøves først med segmenter og faller tilbake til ren tekst.
* Lyden hentes ut med PyAV i en isolert parserprosess (`rag_audio_pieces`), blir mono 16 kHz WAV og kuttes i
  biter på 60–120 s ved den stilleste pausen. Stille biter sendes ikke. Bitene gir tidsstempler også når modellen
  bare returnerer tekst (`gpt-transcribe` gir ikke segmenter).
* Personvern: bare lyden sendes (som `lyd-001.wav` osv.), aldri videotittel, filnavn, emnetekst eller
  studentdata. Teksten leverandøren returnerte for forrige bit, sendes med neste bit som stavehjelp. Estimatet viser
  minutter, modell, leverandør og hva som sendes; uten samtykke sendes ingenting og videoen får status «venter».
  Hvert kall logges i KI-bruk (`rag_transcription`). Transkripsjonen bufres på filens SHA-256, felles med lokal
  transkripsjon, så samme fil sendes aldri to ganger.
* Elementer som venter på noe brukeren kan endre (samtykke, modeller, innstillinger, filgrense), lagres med status
  `pending` og prøves igjen ved neste «Oppdater indeks» i stedet for å regnes som uendret.

## GPU

`setup.bat --rag` installerer PyTorch fra PyPI, som på Windows er CPU-utgaven. EmneKlar oppdager CUDA automatisk
(`torch.cuda.is_available()` for embedding og rerangering, `ctranslate2.get_cuda_device_count()` for Whisper), så
GPU brukes når CUDA-utgaven av PyTorch og CUDA-bibliotekene er installert i `backend\.venv`. Valget kan overstyres
(Automatisk / Bare CPU / NVIDIA-GPU).

## Testing

Enhetstester for HTML → Markdown, dokumentparsere, chunking, norsk stemming, RRF, lagring, inkrementell
oppdatering, teksting (VTT/SRT), transkripsjons-chunking, pyntfilter/dHash, berikelse, evaluering og eksport.
Integrasjonstest: et lite testemne i den falske Canvas-instansen bygges via API-et med en deterministisk
test-embedder, så det stilles spørsmål og kildene kontrolleres. Personvern: diskusjonsinnlegg fra studenter og
svar i diskusjoner kommer aldri med. Frontend: Vitest + axe for Emne-RAG-siden.
