# EmneKlar – engineering rules

EmneKlar is ONE local, modular application (FastAPI backend + React/TypeScript frontend served by the
backend) for analysing, quality-assuring and improving Canvas courses. UI language: Norwegian Bokmål.
Internal identifiers: English. See `docs/ARCHITECTURE.md` for the full picture.

## Invariants (do not break)

1. **One application.** Never create a second implementation, service or app. New functionality goes into an
   existing domain (`backend/emneklar/features/<domain>`, `frontend/src/features/<domain>`). The primary
   navigation is fixed (8 entries + Innstillinger/Hjelp) – do not add entries casually.
2. **Canvas writes only via the change engine.** Every mutating Canvas request goes
   preview → staged change → (approval) → conflict check → backup → apply → change log.
   `CanvasClient` refuses writes without a `WritePermit` (issued only in `core/changes`) and refuses all writes
   while Dry run is on. Never bypass this. Never silently move, delete or rewrite course content.
3. **Reuse shared infrastructure.** Canvas: `core/canvas` (client, typed API, snapshot). AI: `core/ai`
   (provider abstraction + router; no hard-coded model names in features). UI: `frontend/src/design-system`
   (no ad-hoc styling of controls). Jobs/progress: `core/jobs`.
4. **Secrets** (Canvas token, AI keys) live only in the OS credential store (`core/auth/secrets.py`). Never in
   code, git, settings, the database, logs, the browser or API responses. Never log Authorization headers.
5. **Accessibility legal status is data, not code.** Rules (`features/accessibility/rules/ruleset.json`) and
   regulatory profiles (`features/accessibility/profiles/*.json`) are versioned; findings store rule id +
   ruleset/profile version. Never claim automated testing proves compliance; never show "100 % universelt
   utformet". Keep the classes Avvik / Sannsynlig avvik / Bør vurderes / Forbedringsforslag / Manuell kontroll and
   the test methods deterministic / heuristic / AI-assisted / manual.
6. **AI is optional and privacy-gated.** Core features must work without AI. External AI is off until the user
   enables it; show a payload summary before sending; never send student submissions, grades, messages or
   unnecessary identity data. Mark output «KI-forslag – må vurderes». AI is never the sole accessibility judge.
7. **Truthful UI.** No fake metrics, no fake progress, no buttons that do nothing. If Canvas does not support
   something, show it as unavailable with a truthful explanation.
8. **Local only.** The server binds to 127.0.0.1. Keep the Host/Origin/CSRF/session checks in
   `core/security/web.py`. Link checking goes through the SSRF guard (`core/security/ssrf.py`).
9. **User data is separate from code**: `%LOCALAPPDATA%\EmneKlar` (database, backups, reports, logs, cache).
10. **Database schema changes require an Alembic migration** (`backend/migrations`). Before v0.1.0 is
    released the initial migration may be regenerated; after that migrations are append-only.

## Workflow

- Work on feature branches; never push or merge to `main` without explicit permission.
- Update tests when behaviour changes. Backend: `cd backend && .venv\Scripts\python -m pytest`.
  Frontend: `cd frontend && npm test && npm run typecheck && npm run lint`. E2E + axe: `npm run e2e`.
- Do not redesign or rewrite working modules unless required.
- Keep `VERSION`, `backend/pyproject.toml` and `CHANGELOG.md` in sync (`scripts/bump_version.py`).
- Verify Canvas API behaviour against the official docs (see `docs/CANVAS_API.md`) – never guess enum values.
