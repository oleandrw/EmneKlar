# EmneKlar for utviklere

EmneKlar er én modulær monolitt: FastAPI-backend (`backend/`, Python ≥ 3.11) som serverer et React/TypeScript-
grensesnitt (`frontend/`, Vite). Les [CLAUDE.md](../CLAUDE.md) for prosjektets faste regler.

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

Hele rett-og-publiser-flyten kan prøves lokalt med `--demo` (i stedet for `--configured`): et Blueprint-emne (102) med
et tilknyttet emne (104) der en side er låst, siden «Bildegalleri» med mange bilder uten alt-tekst og døde lenker, og
en falsk KI-leverandør for alt-tekstforslag. «Publiser til Canvas» skriver bare til det falske Canvas (i minnet), og
data og hemmeligheter ligger i en engangsmappe og i minnet. Konfigurasjonen `emneklar-demo` i `.claude/launch.json`
starter det samme (port 8769).

```bat
backend\.venv\Scripts\python backend\tests\fakes\dev_server.py --port 8769 --canvas-port 8793 --demo
```

E2E-testene bruker Playwrights egen Chromium. Mangler riktig versjon, last den ned med `npx playwright install chromium`
(i `frontend`).

**Arbeidsflyt:** funksjonsgrener og pull requests mot `main`; GitHub Actions kjører tester, typesjekk, lint,
bygg, tilgjengelighetstester, avhengighetssjekk og – på `main` – bygging og bruk av Windows-pakken (installasjon,
oppdatering, avinstallering). Versjoner følger SemVer
(`VERSION`, `CHANGELOG.md`, `scripts/bump_version.py`), og databaseendringer krever alltid en Alembic-migrering.

## Kjøre fra kildekoden

```bat
git clone https://github.com/oleandrw/EmneKlar.git
cd EmneKlar
setup.bat
start.bat
```

`setup.bat` lager Python-miljøet `backend\.venv` med en Python som finnes på maskinen (3.11 eller nyere) og
installerer de låste avhengighetene. Den bygger grensesnittet når mappen er en kopi av kildekoden, så da trengs
[Node.js LTS](https://nodejs.org/) i tillegg. `setup.bat` spør aldri om og installerer aldri valgfrie tillegg (lokale
modeller). En Git-klone oppdateres med `update.bat` (`git pull --ff-only`). Se [UPDATING.md](UPDATING.md).

Det samme gjelder zip-pakken (`EmneKlar-<versjon>.zip`) uten installasjonsprogrammet: pakk ut, kjør `setup.bat`
og `start.bat`. Det er reserveløsningen for dem som har Python fra før.

Nyttige miljøvariabler når du starter EmneKlar selv:

| Variabel | Virkning |
|---|---|
| `EMNEKLAR_DATA_DIR` | datamappen (standard: `%LOCALAPPDATA%\EmneKlar`). Sett den alltid når du tester, så de vanlige dataene ikke røres. Med den satt kopieres heller ingenting fra den gamle mappen `EmneKlar-Claude` |
| `EMNEKLAR_PORT` | porten (standard 8770) |
| `EMNEKLAR_NO_BROWSER=1` | ikke åpne nettleseren (som `--no-browser`) |
| `EMNEKLAR_SECRET_BACKEND=memory` | hemmeligheter bare i minnet – ingenting skrives til Legitimasjonsbehandling |

En installasjon kan også ha egne standardverdier i filen `emneklar.local.json` i programmappen
(`{"data_dir": "<full sti>", "port": 8791, "keyring_service": "EmneKlar-test"}`). Testutgaven av
installasjonsprogrammet skriver den, så «EmneKlar (test)» har egen datamappe, port og tjeneste i
Legitimasjonsbehandling uansett hvordan den startes. Filen er aldri med i en utgivelse, og miljøvariablene over
går foran den.

## Windows-pakken

En lærer installerer `EmneKlar-<versjon>-setup.exe`. Den inneholder programpakken og en Python-kjøretid, så ingen
Python eller pip brukes på lærerens maskin. Slik henger delene sammen:

| Del | Fil | Skript |
|---|---|---|
| Kjøretid | `EmneKlar-runtime-win-amd64-<id>.zip` | `scripts/build_runtime.py` – python.org sin «embeddable package» (versjon og SHA-256 i `packaging/runtime.json`) + pakkene i `packaging/runtime-win-amd64.txt`, installert med `pip --require-hashes` |
| Programpakke | `EmneKlar-<versjon>.zip` | `scripts/package_release.py --runtime …` – bare programfiler; hver fil Git følger må være merket som programfil eller utviklingsfil |
| Installasjonsprogram | `EmneKlar-<versjon>-setup.exe` | `scripts/build_installer.py` – Inno Setup 6 (`packaging/windows/EmneKlar.iss`) |
| Kontroll | – | `scripts/verify_windows_installer.py` (installer, start, stopp, avinstaller) og `scripts/local_update_test.py` (oppdater en installert kopi, med tilbakerulling) |

Kommandoene står under «Bygge pakken lokalt» og «Slik tester du en oppdatering trygt» i [UPDATING.md](UPDATING.md).
Du trenger Python 3.14 (samme versjon som kjøretiden) og [Inno Setup 6](https://jrsoftware.org/isinfo.php).

* **Etter endringer i `backend/constraints.txt`:** kjør `python scripts\build_runtime.py lock` og commit
  `packaging/runtime-win-amd64.txt`. Testen `test_runtime_build` feiler til låsefilen stemmer med versjonene.
* **Ny Python-versjon i kjøretiden:** endre `python`, `python_url` og `python_sha256` i `packaging/runtime.json`
  (SHA-256 står på utgivelsessiden på python.org), og `RUNTIME_PYTHON` i `.github/workflows/ci.yml` og
  `python-version` i `release.yml` hvis hovedserien endres.
* **Ikonet** (`packaging/windows/EmneKlar.ico`) tegnes av `packaging/windows/make_icon.py` etter
  `frontend/public/favicon.svg`.
* **Plattformforskjeller** hører hjemme i `backend/emneklar/core/system.py` (datamappe, meldinger uten konsollvindu,
  «åpne mappe», plattformnavn for kjøretid) – ikke som spredte `sys.platform`-tester. En test passer på det.

Status for macOS og Linux står i [PLATFORMS.md](PLATFORMS.md).

## Utgivelser

Se «Utgivelse» i [UPDATING.md](UPDATING.md): sett versjon med `scripts/bump_version.py` (også forhåndsversjoner som
`0.2.0-rc.1`), push en tag `vX.Y.Z` som er lik `VERSION`, så bygger `.github/workflows/release.yml` kjøretiden,
programpakken og installasjonsprogrammet, bruker dem (installasjon, oppdatering, tilbakerulling, avinstallering) og
publiserer dem først når alt har bestått.

## Teknisk dokumentasjon

| Dokument | Innhold |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arkitektur, moduler, analyse, endringsmotor, KI-lag |
| [DATA_MODEL.md](DATA_MODEL.md) | Datamodell |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Trusselmodell og tiltak |
| [ACCESSIBILITY_RULES.md](ACCESSIBILITY_RULES.md) | Regelregister og regulatoriske profiler |
| [CANVAS_API.md](CANVAS_API.md) | Verifiserte fakta om Canvas REST API |
| [UPDATING.md](UPDATING.md) | Oppdatering, utgivelser, versjonering, trygg testing og signering |
| [PLATFORMS.md](PLATFORMS.md) | Hva som er bygget, testet og signert på Windows, macOS og Linux |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | Designsystem: tokens, komponenter og regler for brukergrensesnittet |
| [rag-plan.md](rag-plan.md) | Emnets kunnskapsbase (Emne-RAG): plan, valg og avhengigheter |
| [CHANGELOG.md](../CHANGELOG.md) | Endringslogg |

Brukerveiledninger, vanlige spørsmål og feilsøking finnes i programmet under **Hjelp**.
