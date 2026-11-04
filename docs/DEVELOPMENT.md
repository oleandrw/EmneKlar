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

**Arbeidsflyt:** funksjonsgrener og pull requests mot `main`; GitHub Actions kjører tester, typesjekk, lint,
bygg, tilgjengelighetstester, avhengighetssjekk og en Windows-installasjonstest. Versjoner følger SemVer
(`VERSION`, `CHANGELOG.md`, `scripts/bump_version.py`), og databaseendringer krever alltid en Alembic-migrering.

## Kjøre fra kildekoden

```bat
git clone https://github.com/oleandrw/EmneKlar.git
cd EmneKlar
setup.bat
start.bat
```

`setup.bat` bygger grensesnittet når mappen er en kopi av kildekoden, så da trengs [Node.js LTS](https://nodejs.org/) i
tillegg til Python. En Git-klone oppdateres med `update.bat` (`git pull --ff-only`). Se
[UPDATING.md](UPDATING.md).

## Utgivelser

Se «Utgivelse» i [UPDATING.md](UPDATING.md): sett versjon med `scripts/bump_version.py`, push en tag `vX.Y.Z` som er
lik `VERSION`, så bygger `.github/workflows/release.yml` `EmneKlar-X.Y.Z.zip` med sjekksum og publiserer den.

## Teknisk dokumentasjon

| Dokument | Innhold |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arkitektur, moduler, analyse, endringsmotor, KI-lag |
| [DATA_MODEL.md](DATA_MODEL.md) | Datamodell |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Trusselmodell og tiltak |
| [ACCESSIBILITY_RULES.md](ACCESSIBILITY_RULES.md) | Regelregister og regulatoriske profiler |
| [CANVAS_API.md](CANVAS_API.md) | Verifiserte fakta om Canvas REST API |
| [UPDATING.md](UPDATING.md) | Oppdatering, utgivelser og versjonering |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | Designsystem: tokens, komponenter og regler for brukergrensesnittet |
| [rag-plan.md](rag-plan.md) | Emnets kunnskapsbase (Emne-RAG): plan, valg og avhengigheter |
| [CHANGELOG.md](../CHANGELOG.md) | Endringslogg |

Brukerveiledninger, vanlige spørsmål og feilsøking finnes i programmet under **Hjelp**.
