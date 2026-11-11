# Oppdatering, utgivelser og versjonering

## For brukere

### Slik oppdaterer du

Velg én av to måter:

* **Fra programmet:** *Innstillinger → Generelt*, kortet «Versjon og oppdateringer». Her ser du installert versjon,
  nyeste versjon og endringene. «Se etter oppdateringer» spør GitHub, og «Oppdater nå» starter oppdateringen i et
  eget vindu.
* **Uten programmet:** dobbeltklikk **`update.bat`** i programmappen. Har du installert med installasjonsprogrammet,
  er det `%LOCALAPPDATA%\Programs\EmneKlar`.

Begge gjør det samme. EmneKlar trenger ikke være avsluttet på forhånd – oppdateringen stopper programmet selv og
starter det igjen når den er ferdig. Du kan også laste ned det nyeste installasjonsprogrammet og kjøre det over
installasjonen du har; dataene dine beholdes.

### Hva oppdateringen gjør

Vinduet viser «Steg N av 10» underveis:

| Steg | Hva skjer |
|---|---|
| 1 | Finner EmneKlar hvis det kjører, og stopper det |
| 2 | Kontrollerer installasjonen |
| 3 | Tar sikkerhetskopi av databasen |
| 4 | Ser etter en nyere versjon på GitHub |
| 5 | Henter den nye versjonen og kontrollerer den mot sjekksummen. Trenger den nye versjonen en annen Python-kjøretid enn den som er installert, hentes og kontrolleres også den |
| 6 | Oppdaterer avhengigheter. En installasjon fra installasjonsprogrammet har alt i kjøretiden og installerer ingenting; en installasjon med eget Python-miljø (`setup.bat`) installerer de låste versjonene i `backend/constraints.txt` |
| 7 | Oppdaterer databasen (migreringer) |
| 8 | Bygger brukergrensesnittet (bare Git-installasjoner) |
| 9 | Helsesjekk av den nye versjonen |
| 10 | Starter EmneKlar igjen |

Oppdateringen spør aldri om, laster aldri ned og installerer aldri lokale modeller eller andre valgfrie tillegg.

### Hvis noe går galt

Feiler et av stegene 5–9, settes programfilene, kjøretiden (eller avhengighetene) og databasen tilbake, og forrige
versjon startes igjen. Vinduet forteller hvilket steg som feilet og hvorfor. Hele forløpet logges i
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

Punkt 2 og 3 er **standardkilden** – repositoriet EmneKlar ble installert fra. Feltet viser hvilken det er. Tomt felt
betyr standardkilden. Velger du et annet repository, viser EmneKlar en advarsel om at oppdateringer da hentes fra en
annen kilde (en oppdatering kjører programkode fra repositoriet på maskinen), og du må krysse av for at du vil det før
du kan lagre. API-et (`PATCH /api/settings/advanced`) krever det samme: `confirm_update_repository: true`, ellers
avvises endringen med `update_source_confirmation_required`. Store og små bokstaver regnes som like, slik GitHub gjør:
`Eier/emneklar` er det samme repositoriet som `eier/EmneKlar` og trenger ingen bekreftelse.

Samme sted velger du kanal («Stabile versjoner», som er standard, eller «Også forhåndsversjoner») og om EmneKlar skal
se etter oppdateringer automatisk. Den automatiske sjekken skjer høyst én gang i døgnet, når du åpner
*Innstillinger → Generelt* eller *Hjelp*. Det eneste som sendes til GitHub, er en forespørsel om siste versjon.

### Installasjonstyper

| Type | Kjennetegn | Python | Slik oppdateres den |
|---|---|---|---|
| Installert med installasjonsprogrammet | `install.json` og mappen `runtime` | Innebygd kjøretid i `runtime\` – ingen Python på maskinen brukes, og pip kjøres aldri | Programpakken `EmneKlar-<versjon>.zip` lastes ned og kontrolleres mot `EmneKlar-<versjon>.zip.sha256` (og mot signaturen, når signering er tatt i bruk – se under). Kjøretiden `EmneKlar-runtime-win-amd64-<id>.zip` hentes bare når id-en er en annen enn den installerte, og kontrolleres mot SHA-256 i pakkens `install.json`. |
| Zip-pakken med egen Python | `install.json`, ingen `runtime` | Miljøet `backend\.venv` laget av `setup.bat` | Programpakken som over; avhengighetene installeres med pip (låste versjoner). |
| Git-klone | mappen `.git` finnes | `backend\.venv` | `git pull --ff-only`. Avvises hvis sporede filer har endringer som ikke er lagret i Git. |
| Kopi av kildekoden | ingen av delene | `backend\.venv` | Som zip-pakken. |

### Sikkerhetskopier

* **Databasen** kopieres før hver oppdatering (`backups\database\for-oppdatering-<versjon>-<tid>.db`) og før hver
  migrering (`backups\database\for-migrering-<revisjon>-<tid>.db`), under `%LOCALAPPDATA%\EmneKlar`. EmneKlar
  beholder de fem nyeste kopiene av hver type og sletter eldre kopier ved oppstart. Andre filer i mappen røres ikke.
* **Programfilene** som ble erstattet, legges i `.update\previous-*` i programmappen. De tre nyeste beholdes.
* **Kjøretiden** som ble erstattet, ligger i `.update\runtime-previous` til den nye versjonen har bestått
  helsesjekken. Da slettes den – den forrige kjøretiden kan hentes fra GitHub igjen (eller legges inn med
  installasjonsprogrammet for den versjonen). `.update\python` er kopien av tolkeren som den siste oppdateringen
  kjørte med (ca. 25 MB); den lages på nytt ved neste oppdatering.
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

EmneKlar bruker semantisk versjonering (`MAJOR.MINOR.PATCH`). `VERSION` er fasiten: installasjonsprogrammet,
programpakken, taggen og utgivelsen på GitHub får alle versjonsnummeret derfra. Bruk skriptet for å sette ny versjon –
det oppdaterer `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json` og flytter
innholdet under «Unreleased» i `CHANGELOG.md` til en ny versjonsoverskrift:

```bash
python scripts/bump_version.py 0.2.0
```

**Forhåndsversjoner** heter `X.Y.Z-alpha.N`, `X.Y.Z-beta.N` eller `X.Y.Z-rc.N`:

```bash
python scripts/bump_version.py 0.2.0-rc.1
```

Alle filene får samme versjon, men `CHANGELOG.md` endres ikke: endringene blir stående under «Unreleased» til den
endelige utgivelsen, og utgivelsesnotatene til forhåndsversjonen er den seksjonen. Rekkefølgen er
`0.2.0-rc.1 < 0.2.0-rc.2 < 0.2.0`. Taggen `v0.2.0-rc.1` publiseres som forhåndsversjon på GitHub, og bare
installasjoner med kanalen «Også forhåndsversjoner» får tilbud om den. Når du kjører `bump_version.py 0.2.0`
etterpå, flyttes alt under «Unreleased» til `[0.2.0]`.

Etter at v0.1.0 er utgitt, er databasemigreringene i `backend/migrations` bare tillegg: en publisert migrering
endres eller slettes aldri.

### Filene i en utgivelse

| Fil | Innhold | Lages av |
|---|---|---|
| `EmneKlar-<versjon>-setup.exe` (+ `.sha256`) | Installasjonsprogrammet for Windows: programmet og kjøretiden | `scripts/build_installer.py` (Inno Setup, `packaging/windows/EmneKlar.iss`) |
| `EmneKlar-<versjon>.zip` (+ `.sha256`) | Programpakken: programkoden, migreringene, det ferdigbygde grensesnittet, `setup.bat`/`start.bat`/`update.bat` og oppdateringsskriptene – uten tester og utviklerfiler. Felles for alle plattformer. `install.json` i pakken navngir kjøretiden per plattform med SHA-256 og størrelse | `scripts/package_release.py` |
| `EmneKlar-<versjon>.zip.sha256.sig` | Ed25519-signatur av sjekksumfilen (bare når signering er tatt i bruk) | `scripts/sign_release.py` |
| `EmneKlar-runtime-win-amd64-<id>.zip` (+ `.sha256`) | Python-kjøretiden for Windows: den offisielle «embeddable package» fra python.org med avhengighetene ferdig installert | `scripts/build_runtime.py` |

Kjeden av kontroller: signaturen (når den brukes) dekker sjekksumfilen, sjekksumfilen dekker programpakken, og
`install.json` i programpakken dekker kjøretiden. Installasjonsprogrammet inneholder nøyaktig programpakken og
kjøretiden den navngir.

Kjøretidens id (`cp314-<12 heks>`) er en hash av det som bestemmer innholdet: Python-nedlastingen
(`packaging/runtime.json`) og låsefilen (`packaging/runtime-win-amd64.txt`). Samme innhold gir samme id, og en
installasjon henter ny kjøretid bare når id-en endres. Bygget er reproduserbart: to bygg av de samme låste filene
gir samme zip-fil, bit for bit, så SHA-256 fra et lokalt bygg kan sammenlignes med den i utgivelsen.

### Utgivelse

1. Sett versjon med `scripts/bump_version.py` og fullfør endringsloggen.
2. Lag en tag `vX.Y.Z` (eller `vX.Y.Z-rc.N`) som er lik `VERSION`, og push den.
3. Arbeidsflyten `.github/workflows/release.yml` gjør resten på en ren Windows-maskin: bygger grensesnittet,
   kjøretiden, programpakken og installasjonsprogrammet – og **bruker** dem før noe publiseres: installasjonsprogrammet
   installeres, startes, stoppes, installeres på nytt og avinstalleres (`scripts/verify_windows_installer.py`), og en
   installert kopi oppdateres med ny kjøretid og med en ny versjon som ikke kan starte, som må rulles tilbake
   (`scripts/local_update_test.py`). Først når alt dette har bestått, opprettes utgivelsen på GitHub med endringene
   fra `CHANGELOG.md`. En versjon med `-alpha`, `-beta` eller `-rc` merkes som forhåndsversjon.

Bare Windows bygges og publiseres. Det finnes ingen pakke for macOS eller Linux, og utgivelsen venter ikke på noen –
se [PLATFORMS.md](PLATFORMS.md).

### Bygge pakken lokalt

På Windows, med Python 3.14 (samme versjon som kjøretiden) og Inno Setup 6:

```bat
cd frontend && npm ci && npm run build && cd ..
python scripts\build_runtime.py build
python scripts\package_release.py --runtime dist-release\EmneKlar-runtime-win-amd64-<id>.zip
python scripts\build_installer.py --package dist-release\EmneKlar-<versjon>.zip --runtime dist-release\EmneKlar-runtime-win-amd64-<id>.zip
```

`package_release.py` krever en ren commit. Til testing før noe er committet pakker `--working-tree` mappen slik den
står. `build_installer.py --test-build` lager «EmneKlar (test)» – en egen installasjon med egen mappe, eget navn i
Start-menyen, egen avinstallering og egen datamappe og port, som aldri erstatter en vanlig installasjon og aldri
bruker de vanlige dataene.

Når `backend/constraints.txt` endres (for eksempel av Dependabot), må låsefilen for kjøretiden lages på nytt, ellers
feiler testen som sammenligner dem:

```bat
python scripts\build_runtime.py lock
```

### Slik tester du en oppdatering trygt

Ingen av måtene under rører utviklingsmappen eller den vanlige datamappen din (`%LOCALAPPDATA%\EmneKlar`).

**1. Automatisk, uten GitHub.** Skriptet lager en testinstallasjon i en egen mappe (som installasjonsprogrammet
gjør), starter den, lager «neste utgivelse» av de samme filene og kjører installasjonens egen oppdatering mot den:

```bat
python scripts\local_update_test.py --package dist-release\EmneKlar-<versjon>.zip --runtime dist-release\EmneKlar-runtime-win-amd64-<id>.zip
python scripts\local_update_test.py --package ... --runtime ... --same-runtime
python scripts\local_update_test.py --package ... --runtime ... --break-new-version
```

Den første bytter også kjøretid, den andre beholder den, og den tredje gir en ny versjon som ikke kan starte:
oppdateringen skal da feile i helsesjekken og sette programfilene, kjøretiden og databasen tilbake. Testinstallasjonen
bruker sin egen datamappe, en ledig port, hemmeligheter bare i minnet, og åpner ingen nettleser. Alt som er byttet
ut, er hvor utgivelsen kommer fra: en mappe på maskinen i stedet for GitHub. `--work MAPPE --keep` lar deg se på
resultatet etterpå.

**2. Installasjonsprogrammet.** Bygg en testutgave og la skriptet installere, starte, stoppe og avinstallere den:

```bat
python scripts\build_installer.py --package ... --runtime ... --test-build
python scripts\verify_windows_installer.py --installer dist-release\EmneKlar-<versjon>-setup-test.exe
```

**3. For hånd, mot en ekte forhåndsversjon.** Dette er den eneste måten som også prøver nedlastingen fra GitHub:

1. Installer testutgaven (`EmneKlar-<versjon>-setup-test.exe`). Den legger seg i
   `%LOCALAPPDATA%\Programs\EmneKlar-test` og heter «EmneKlar (test)» i Start-menyen.
2. Testutgaven har **sin egen datamappe, port og tjeneste i Legitimasjonsbehandling**: installasjonsprogrammet
   skriver `emneklar.local.json` i programmappen med `%LOCALAPPDATA%\EmneKlar-test-data`, port 8791 og
   tjenestenavnet «EmneKlar-test». Det gjelder uansett hvordan den startes – snarveien, `start.bat`, `update.bat`
   eller «Oppdater nå» – så den åpner, kopierer og endrer aldri de vanlige dataene dine, et token du legger inn i
   testutgaven, erstatter aldri det ekte, og den kan kjøre samtidig med din vanlige EmneKlar.
3. Velg kanalen «Også forhåndsversjoner» under *Innstillinger → Avanserte innstillinger → Oppdateringer*.
4. Publiser en forhåndsversjon (`python scripts\bump_version.py X.Y.Z-rc.1`, tag `vX.Y.Z-rc.1`). Vanlige
   installasjoner på den stabile kanalen får ikke tilbud om den.
5. Velg «Se etter oppdateringer» og «Oppdater nå» i testutgaven.
6. Avinstaller «EmneKlar (test)» fra Windows-innstillingene når du er ferdig, slett
   `%LOCALAPPDATA%\EmneKlar-test-data`, og fjern oppføringene med «EmneKlar-test» i Legitimasjonsbehandling hvis du
   la inn et token.

`emneklar.local.json` (`{"data_dir": "<full sti>", "port": 8791, "keyring_service": "EmneKlar-test"}`) kan også
legges i en hvilken som helst annen testinstallasjon. Filen er aldri med i en utgivelse, og miljøvariablene `EMNEKLAR_DATA_DIR` og `EMNEKLAR_PORT`
går foran den.

Vil du prøve installasjonsprogrammet nøyaktig slik en lærer møter det, bruker du en egen Windows-bruker på maskinen.
Den har sin egen `%LOCALAPPDATA%`, sin egen Start-meny og sin egen Legitimasjonsbehandling.

### Signering

Ingenting er signert i dag. Det som er forberedt, og hva som mangler:

**Installasjonsprogrammet (Authenticode).** Mangler: et kodesigneringssertifikat (eller en signeringstjeneste).
Uten signatur viser Windows SmartScreen «Windows beskyttet PC-en din» med ukjent utgiver, og læreren må velge
«Mer informasjon → Kjør likevel». `scripts/build_installer.py --sign "<kommando>"` gir kommandoen til Inno Setups
`SignTool`, som da signerer både installasjonsprogrammet og avinstalleringsprogrammet (`$f` er filen som signeres).
Utgivelsesarbeidsflyten bruker hemmeligheten `WINDOWS_SIGN_COMMAND` hvis den finnes, og bygger usignert ellers.
Python-filene i kjøretiden (`python.exe`, `pythonw.exe`, `python314.dll`) er allerede signert av Python Software
Foundation; snarveiene peker på `pythonw.exe`.

**Utgivelsene (Ed25519).** `update.bat` kan i tillegg til SHA-256 kontrollere en signatur: filen
`EmneKlar-<versjon>.zip.sha256.sig` i samme utgivelse, med en Ed25519-signatur (base64, 64 byte) av de nøyaktige
bytene i `EmneKlar-<versjon>.zip.sha256`. Signaturen kontrolleres mot de offentlige nøklene i `RELEASE_SIGNING_KEYS`
i `scripts/update.py`, før selve pakken lastes ned. Kontrollen og signeringen er skrevet i ren Python (RFC 8032, uten
ekstra pakker) og testet mot RFC-ens testvektorer. Mangler: selve nøkkelparet. Det finnes ingen nøkkel i
repositoriet, og bygget lager ingen.

* **I dag:** `RELEASE_SIGNING_KEYS` er tom og `SIGNATURE_REQUIRED` er `False`. Signaturen kontrolleres ikke, og
  oppdateringer virker som før (bare SHA-256).
* **Når en nøkkel er lagt inn:** en gyldig signatur godtas; en signatur som ikke stemmer, stopper alltid
  oppdateringen. En manglende signatur godtas så lenge `SIGNATURE_REQUIRED` er `False`.

Rekkefølgen for å ta signering i bruk – hvert steg er en egen utgivelse, og rekkefølgen kan ikke byttes om:

1. Lag nøkkelparet, på en maskin du stoler på, med den private nøkkelen **utenfor** repositoriet:
   `python scripts\sign_release.py generate --out <fil utenfor repoet>`. Skriptet viser den offentlige nøkkelen og
   nekter å skrive den private nøkkelen inn i repositoriet eller over en annen fil. Ta en sikkerhetskopi av filen et
   trygt sted – mister du den, kan du ikke signere flere utgivelser med den nøkkelen.
2. Legg innholdet i nøkkelfilen inn som hemmeligheten `RELEASE_SIGNING_KEY` i GitHub (Settings → Secrets and variables
   → Actions). Fra da av signerer utgivelsesarbeidsflyten hver utgivelse.
3. Legg den offentlige nøkkelen inn i `RELEASE_SIGNING_KEYS` i `scripts/update.py` og gi ut den versjonen. Den er
   selv signert, og installasjoner som har den, kontrollerer signaturen på alt de henter senere.
4. Vent til brukerne har den versjonen. Først da kan `SIGNATURE_REQUIRED` settes til `True` i en senere utgivelse.
   Settes den for tidlig, stopper oppdateringen hos alle som ikke har nøkkelen – og hos alle hvis en utgivelse
   mangler signatur.

`python scripts\sign_release.py sign --key <fil> dist-release\EmneKlar-<versjon>.zip.sha256` signerer for hånd, og
`... verify --public-key <heks> ...` kontrollerer en signatur.

**macOS.** Ikke aktuelt før det finnes en Mac-pakke. Den ville kreve Apple Developer ID og notarisering – se
[PLATFORMS.md](PLATFORMS.md).
