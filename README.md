# EmneKlar

EmneKlar er et lokalt verktøy for lærere og emneansvarlige som vil analysere, kvalitetssikre og trygt forbedre
emner i Canvas. Programmet kjører på din egen Windows-maskin og bruker Canvas REST API med ditt eget API-token.

* **Universell utforming** – funn etter et versjonert regelsett og valgt regulatorisk profil, med forklaring,
  kriterium, testmetode og forslag til retting. EmneKlar påstår aldri at et emne er «100 % universelt utformet».
* **Innholdskvalitet** – lenker, medier og HTML-kode.
* **Emnestruktur** – veiledende forslag og studentreisen.
* **Quizassistent** – kvalitetssjekk av klassiske quizer, KI-spørsmålsbank og quizbygger.
* **Emneforside** – lag eller forbedre forsiden med forhåndsvisning på PC, nettbrett og mobil.
* **Canvas-verktøy** – modulkrav, Blueprint-låsing, Canvas-innstillinger, backup og endringslogg, og **Emne-RAG**:
  en lokal kunnskapsbase av emnet som du kan stille spørsmål til, med klikkbare kilder.
* **Rapporter** – HTML (kan lagres som PDF) og CSV.

Alt følger samme prinsipp: **analyser → forklar → foreslå → forhåndsvis → godkjenn → endre → logg**. Ingenting
endres i Canvas før du har godkjent det i endringskøen, og med **Dry run** sendes ingenting.

## Kom i gang (Windows)

1. Installer [Python 3.11 eller nyere](https://www.python.org/downloads/windows/) (kryss av for «Add python.exe to
   PATH»). Administratorrettigheter trengs ikke.
2. Last ned EmneKlar (ferdig utgivelse fra GitHub Releases, eller en kopi av repositoriet) og pakk ut i en mappe.
3. Dobbeltklikk **`setup.bat`**. Den lager et eget Python-miljø og installerer det EmneKlar trenger.
   * En ferdig utgivelse inneholder et ferdigbygd grensesnitt. Kjører du fra en kopi av kildekoden, trengs også
     [Node.js LTS](https://nodejs.org/) for å bygge grensesnittet.
4. Dobbeltklikk **`start.bat`**. Nettleseren åpnes med EmneKlar. Lukk vinduet til EmneKlar for å avslutte.
5. Følg oppsettveiviseren: Canvas-adresse, API-token (lages i Canvas under *Konto → Innstillinger → Godkjente
   integrasjoner*), test av tilkobling og valg av emne.

**Oppdatering:** dobbeltklikk **`update.bat`**, eller trykk «Oppdater nå» under *Innstillinger → Generelt*.
Oppdateringen tar sikkerhetskopi av databasen, sjekker at den nye versjonen virker og setter forrige versjon
tilbake hvis noe går galt. Større versjoner installeres aldri uten at du bekrefter. Se
[docs/UPDATING.md](docs/UPDATING.md).

## Emne-RAG – kort brukerveiledning

1. Gå til **Canvas-verktøy → Emne-RAG** (emnet velges i toppen av siden).
2. Velg **Hele emnet** eller **Valgte moduler**. Alle kildetyper er med som standard: tekst fra Canvas, dokumenter
   (PDF, Word, PowerPoint, Excel, OpenDocument, RTF, CSV, tekst), video og lyd, og bilder (bilder krever KI).
   **Tilpass kilder** lar deg slå av kilder og filtyper, ta med upublisert innhold og – under **Avansert** – velge
   KI-tillegg (kontekstuell berikelse, nøkkelbilder) og transkriberingstjeneste, med forklaring av hva som koster.
   **Tilbakestill til standard** slår alt på igjen.
3. Trykk **Bygg indeks**. Lastes noe ned første gang eller sendes noe til KI, ser du først et estimat (hvor mye som
   leses, omtrentlig tid og hva som sendes) og godtar det; ellers starter byggingen med en gang. Byggingen går i
   bakgrunnen og kan settes på pause eller avbrytes; **Oppdater indeks** fortsetter der den slapp og behandler bare
   det som er endret.
4. Under **Spør emnet** kan du søke uten KI eller få et svar med KI der hver påstand har en klikkbar kilde
   ([Sidetittel – Modul], [Video «…» – 12:34], [Fil.pdf s. 4], [Bilde på «…»]). Svaret er et KI-forslag som må vurderes.
5. **Kvalitet** viser en helsescore for søket (recall@5 og MRR fra testspørsmål), og **Eksport** gir indeksen som ZIP
   (JSONL med metadata og vektorer) eller som Word, PDF, Markdown eller tekst for andre verktøy.

Bare lærerens innhold leses – aldri innleveringer, karakterer, meldinger eller studentinnlegg. Semantisk søk,
rerangering og transkripsjon kjører lokalt med valgfrie modeller (flere GB): lukk EmneKlar og dobbeltklikk
**`setup-emne-rag.bat`** (eller kjør `setup.bat --rag`). `update.bat` beholder dem senere. Uten lokale modeller bruker
Emne-RAG nøkkelordsøk og eksisterende teksting. Video uten teksting kan i stedet transkriberes av OpenAI, Azure
OpenAI eller en egen OpenAI-kompatibel server (Emne-RAG → Innstillinger → Transkripsjon); da sendes bare lyden, og
bare etter at du har sett estimatet og godtatt sendingen. Standardinstallasjonen kjører på CPU; har maskinen en NVIDIA-GPU med
CUDA-utgaven av PyTorch og CUDA-bibliotekene for CTranslate2, brukes GPU automatisk (kan overstyres under
Emne-RAG → Innstillinger). Skannede PDF-er leses med Tesseract hvis det er installert med norsk språkpakke.

## Personvern og sikkerhet

* EmneKlar lytter bare på `127.0.0.1` og kan ikke nås fra nettverket.
* Canvas-token og API-nøkler lagres bare i Windows Legitimasjonsbehandling – aldri i filer, databasen, nettleseren
  eller logger.
* Dine data ligger i `%LOCALAPPDATA%\EmneKlar-Claude` (database, sikkerhetskopier, rapporter, logger), adskilt fra
  programmet. Oppdatering eller ny installasjon sletter dem ikke. Mappen heter ikke bare «EmneKlar» fordi et annet
  program med samme navn bruker `%LOCALAPPDATA%\EmneKlar`. De to programmene deler ingen filer og kan kjøre samtidig.
  EmneKlar åpner bare sin egen database og endrer aldri en database som tilhører et annet program.
* KI er valgfritt. Sending av emneinnhold til eksterne KI-tjenester er **av** til du slår det på, og du ser hva som
  sendes før det sendes. Studentenes innleveringer, karakterer og meldinger sendes aldri.

Se [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for trusselmodellen.

## Dokumentasjon

| Dokument | Innhold |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arkitektur, moduler, analyse, endringsmotor, KI-lag |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Datamodell |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Trusselmodell og tiltak |
| [docs/ACCESSIBILITY_RULES.md](docs/ACCESSIBILITY_RULES.md) | Regelregister og regulatoriske profiler |
| [docs/CANVAS_API.md](docs/CANVAS_API.md) | Verifiserte fakta om Canvas REST API |
| [docs/UPDATING.md](docs/UPDATING.md) | Oppdatering, utgivelser og versjonering |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | Designsystem: tokens, komponenter og regler for brukergrensesnittet |
| [CHANGELOG.md](CHANGELOG.md) | Endringslogg |

Brukerveiledninger, vanlige spørsmål og feilsøking finnes i programmet under **Hjelp**.

## For utviklere

EmneKlar er én modulær monolitt: FastAPI-backend (`backend/`, Python ≥ 3.11) som serverer et React/TypeScript-
grensesnitt (`frontend/`, Vite). Les [CLAUDE.md](CLAUDE.md) for prosjektets faste regler.

```bat
:: Backend
cd backend
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]" -c constraints.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check emneklar tests
.venv\Scripts\python -m mypy emneklar

:: Frontend
cd frontend
npm ci
npm run typecheck && npm run lint && npm test
npm run build
npm run e2e        :: Playwright + axe mot en falsk Canvas (krever npm run build først)
```

Utviklingsserver med falsk Canvas og testdata (ingen ekte Canvas trengs):

```bat
backend\.venv\Scripts\python backend\tests\fakes\dev_server.py --port 8766 --canvas-port 8790 --configured
```

Åpne deretter `http://127.0.0.1:8766/auth/launch?token=dev-preview-token`.

**Arbeidsflyt:** funksjonsgrener og pull requests mot `main`; GitHub Actions kjører tester, typesjekk, lint,
bygg, tilgjengelighetstester, avhengighetssjekk og en Windows-installasjonstest. Versjoner følger SemVer
(`VERSION`, `CHANGELOG.md`, `scripts/bump_version.py`), og databaseendringer krever alltid en Alembic-migrering.
