# EmneKlar – engineering rules

EmneKlar is ONE local, modular application (FastAPI backend + React/TypeScript frontend served by the
backend) for analysing, quality-assuring and improving Canvas courses. UI language: Norwegian Bokmål.
Internal identifiers: English. See `docs/ARCHITECTURE.md` for the full picture.

## Invariants (do not break)

1. **One application.** Never create a second implementation, service or app. New functionality goes into an
   existing domain (`backend/emneklar/features/<domain>`, `frontend/src/features/<domain>`). The primary
   navigation is fixed (8 entries + Innstillinger/Hjelp) – do not add entries casually.
2. **Canvas writes only via the change engine.** Every mutating Canvas request goes
   preview → staged change → approval → «Publiser til Canvas» → conflict check → backup → apply → change log.
   `CanvasClient` refuses writes without a `WritePermit` (issued only in `core/changes`, by the publish job).
   Analyses, previews, staging and approval only read. There is no Dry run switch (removed in 0005) – the explicit
   publish step is the guard. Never bypass this. The one opt-in exception to «the teacher sees and approves each
   change first» is the KI-bildeassistent's «Automatisk innsetting» (chosen per run, off by default): images that
   pass the quality check are approved and published by the run itself – still through approve → publish job
   (WritePermit, conflict check, backup, log, undo); flagged images always wait. Say so wherever the UI or docs
   promise approval before insertion. Never silently move, delete or rewrite course content; fixes edit
   only the targeted element (`core/canvas/html_edit.py`). Blueprint locks are Canvas' decision, not an EmneKlar
   block – describe where a change lands (`core/canvas/blueprint.py`) and explain Canvas' refusals.
3. **Reuse shared infrastructure.** Canvas: `core/canvas` (client, typed API, snapshot). AI: `core/ai`
   (provider abstraction + router; no hard-coded model names in features). UI: `frontend/src/design-system`
   (no ad-hoc styling of controls). Jobs/progress: `core/jobs`. Platform differences (data folder, messages
   without a console window, opening a folder, which bundled runtime fits the machine): `core/system.py` – no
   scattered `sys.platform` tests.
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
   Course and web content goes into a prompt only through `core/ai/untrusted.py` (`wrap_untrusted_content`: delimited
   as data, delimiters neutralised, injection attempts marked, optional scrubbing) with `DATA_RULE` in the system
   prompt – never a hand-made `<<<` block.
7. **Truthful UI.** No fake metrics, no fake progress, no buttons that do nothing. If Canvas does not support
   something, show it as unavailable with a truthful explanation.
8. **Local only.** The server binds to 127.0.0.1. Keep the Host/Origin/CSRF/session checks in
   `core/security/web.py`. Link checking goes through the SSRF guard (`core/security/ssrf.py`).
9. **User data is separate from code**: `%LOCALAPPDATA%\EmneKlar` (database, backups, reports, logs, cache).
   The program, its data folder and its Credential Manager service are all called «EmneKlar» (decided before the
   first public release). Data from the earlier name «EmneKlar-Claude» is copied once by `core/storage/legacy.py` –
   never moved, changed or deleted. An independent EmneKlar implementation also uses `%LOCALAPPDATA%\EmneKlar`,
   `database.db`, the keyring service "EmneKlar", the cookie `emneklar_session` and port 8765. EmneKlar only opens a
   database marked with its own `PRAGMA application_id` (or an empty one) – see `core/storage/db.py` – and refuses to
   start in a folder the other program has filled; it keeps its own default port (8770) and a session cookie per
   port. Never weaken these checks. The two programs cannot be told apart in the Credential Manager, so they must not
   be installed for the same Windows user.
10. **Database schema changes require an Alembic migration** (`backend/migrations`). Before v0.1.0 is
    released the initial migration may be regenerated; after that migrations are append-only.

## Workflow

- Work on feature branches; never push or merge to `main` without explicit permission.
- Update tests when behaviour changes. Backend: `cd backend && .venv\Scripts\python -m pytest`.
  Frontend: `cd frontend && npm test && npm run typecheck && npm run lint`. E2E + axe: `npm run e2e`.
- CI type-checks on Linux as well as Windows. Before pushing, run mypy as both:
  `.venv\Scripts\mypy emneklar ..\scripts` and `.venv\Scripts\mypy --platform linux emneklar ..\scripts`
  (Windows-only modules such as `winreg` need a `sys.platform` guard, or the Linux jobs stop before the tests).
- Do not redesign or rewrite working modules unless required.
- Keep `VERSION`, `backend/pyproject.toml` and `CHANGELOG.md` in sync (`scripts/bump_version.py`).
- One release pipeline, Windows first: `scripts/build_runtime.py` (bundled Python runtime, hash-locked in
  `packaging/`), `scripts/package_release.py`, `scripts/build_installer.py`, `scripts/update.py`. Extend these – do
  not add a second packaging or update mechanism. After changing `backend/constraints.txt`, run
  `python scripts/build_runtime.py lock`. Setup and update never ask about, download or install local models.
  Never claim a platform is supported unless it is built and tested: `docs/PLATFORMS.md` is the record.
- Test installs and updates only with `EMNEKLAR_DATA_DIR` set (never the user's data folder):
  `scripts/local_update_test.py`, `scripts/verify_windows_installer.py` with a `--test-build` installer.
- Never commit a signing key or certificate; do not set `SIGNATURE_REQUIRED` or add a release key without the
  owner's decision (order in `docs/UPDATING.md`).
- Verify Canvas API behaviour against the official docs (see `docs/CANVAS_API.md`) – never guess enum values.
