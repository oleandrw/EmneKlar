# Oppdatering, utgivelser og versjonering

## For brukere

### Slik oppdaterer du

Velg én av to måter:

* **Fra programmet:** *Innstillinger → Generelt*, kortet «Versjon og oppdateringer». Her ser du installert versjon,
  nyeste versjon og endringene. «Se etter oppdateringer» spør GitHub, og «Oppdater nå» starter oppdateringen i et
  eget vindu.
* **Uten programmet:** dobbeltklikk **`update.bat`** i EmneKlar-mappen.

Begge gjør det samme. EmneKlar trenger ikke være lukket på forhånd – oppdateringen stopper programmet selv og starter
det igjen når den er ferdig.

### Hva oppdateringen gjør

Vinduet viser «Steg N av 10» underveis:

| Steg | Hva skjer |
|---|---|
| 1 | Finner EmneKlar hvis det kjører, og stopper det |
| 2 | Kontrollerer installasjonen |
| 3 | Tar sikkerhetskopi av databasen |
| 4 | Ser etter en nyere versjon på GitHub |
| 5 | Henter den nye versjonen |
| 6 | Oppdaterer avhengigheter (låste versjoner fra `backend/constraints.txt`) |
| 7 | Oppdaterer databasen (migreringer) |
| 8 | Bygger brukergrensesnittet (bare Git-installasjoner) |
| 9 | Helsesjekk av den nye versjonen |
| 10 | Starter EmneKlar igjen |

### Hvis noe går galt

Feiler et av stegene 5–9, settes programfilene, avhengighetene og databasen tilbake, og forrige versjon startes
igjen. Vinduet forteller hvilket steg som feilet og hvorfor. Hele forløpet logges i
`%LOCALAPPDATA%\EmneKlar\logs\update.log`.

Dataene dine i `%LOCALAPPDATA%\EmneKlar` (database, sikkerhetskopier, rapporter, logger) slettes aldri av en
oppdatering.

### Større versjoner

En ny hovedversjon (for eksempel fra 1.x til 2.0) kan endre hvordan EmneKlar virker. Den installeres aldri uten at du
bekrefter:

* i programmet må du krysse av for at du har lest endringene før oppdateringen kan startes, og
* i `update.bat` vises endringene, og du må skrive `JA`.

Mindre versjoner og feilrettinger installeres uten ekstra spørsmål.

### Hvor oppdateringene kommer fra

EmneKlar henter utgivelser fra et GitHub-repositorium. Det bestemmes i denne rekkefølgen:

1. *Innstillinger → Avanserte innstillinger → Oppdateringer*, feltet «GitHub-repository for oppdateringer» (formen
   `eier/repo`),
2. `origin` i Git, hvis EmneKlar er installert med Git,
3. `install.json` i en ferdig utgivelse.

Samme sted velger du kanal («Stabile versjoner», som er standard, eller «Også forhåndsversjoner») og om EmneKlar skal
se etter oppdateringer automatisk. Den automatiske sjekken skjer høyst én gang i døgnet, når du åpner
*Innstillinger → Generelt* eller *Hjelp*. Det eneste som sendes til GitHub, er en forespørsel om siste versjon.

### Installasjonstyper

| Type | Kjennetegn | Slik oppdateres den |
|---|---|---|
| Git-klone | mappen `.git` finnes | `git pull --ff-only`. Avvises hvis sporede filer har endringer som ikke er lagret i Git. |
| Ferdig utgivelse | `install.json` finnes | Utgivelsespakken `EmneKlar-<versjon>.zip` lastes ned og kontrolleres mot `EmneKlar-<versjon>.zip.sha256`. |
| Kopi av kildekoden | ingen av delene | Som ferdig utgivelse. |

### Sikkerhetskopier

* **Databasen** kopieres før hver oppdatering (`backups\database\for-oppdatering-<versjon>-<tid>.db`) og før hver
  migrering (`backups\database\for-migrering-<revisjon>-<tid>.db`), under `%LOCALAPPDATA%\EmneKlar`. EmneKlar
  beholder de fem nyeste kopiene av hver type og sletter eldre kopier ved oppstart. Andre filer i mappen røres ikke.
* **Programfilene** som ble erstattet, legges i `.update\previous-*` i EmneKlar-mappen. De tre nyeste beholdes.
* Sikkerhetskopiene av innhold EmneKlar har endret i Canvas (brukes til angring) slettes aldri automatisk.

### Valg for `update.bat`

| Valg | Virkning |
|---|---|
| `--allow-major` | Installer en ny hovedversjon uten å spørre |
| `--no-start` | Ikke start EmneKlar etter oppdateringen |
| `--no-pause` | Ikke vent på Enter før vinduet lukkes |
| `--from-app` | Brukes når programmet starter oppdateringen (ingen spørsmål i vinduet) |

Avslutningskoder: `0` = oppdatert eller allerede nyeste versjon, `1` = oppdateringen feilet (endringene er satt
tilbake, eller ingenting var endret ennå), `2` = ikke startet (avbrutt av deg, eller stoppet av en
sikkerhetskontroll, for eksempel en ny hovedversjon uten bekreftelse eller ulagrede endringer i Git).

## For utviklere

### Versjonering

EmneKlar bruker semantisk versjonering (`MAJOR.MINOR.PATCH`). `VERSION` er fasiten. Bruk skriptet for å sette ny
versjon – det oppdaterer `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json`
og flytter innholdet under «Unreleased» i `CHANGELOG.md` til en ny versjonsoverskrift:

```bash
python scripts/bump_version.py 0.2.0
```

Etter at v0.1.0 er utgitt, er databasemigreringene i `backend/migrations` bare tillegg: en publisert migrering
endres eller slettes aldri.

### Utgivelse

1. Sett versjon med `scripts/bump_version.py` og fullfør endringsloggen.
2. Lag en tag `vX.Y.Z` som er lik `VERSION`, og push den.
3. Arbeidsflyten `.github/workflows/release.yml` bygger grensesnittet, lager `EmneKlar-X.Y.Z.zip` og
   `EmneKlar-X.Y.Z.zip.sha256` med `scripts/package_release.py` og publiserer dem som en GitHub-utgivelse med
   endringene fra `CHANGELOG.md`. `update.bat` laster ned nøyaktig disse to filene.

Pakken kan også lages lokalt (etter `npm ci && npm run build` i `frontend`):

```bash
python scripts/package_release.py --repository eier/repo
```
