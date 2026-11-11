# Plattformer: hva som er bygget, testet og trygt å gi ut

EmneKlar har én kodebase. Det som skiller plattformene, ligger i et tynt lag (`backend/emneklar/core/system.py`,
oppstarts- og oppdateringsskriptene og pakkingen). **Windows er den eneste plattformen som bygges, testes og gis ut.**
Dette dokumentet sier hva som faktisk er gjort – ikke hva som burde virke.

Status per 11. november 2026. «I GitHub Actions» betyr at jobben har kjørt og bestått der – ikke bare at den finnes.

## Oversikt

| Plattform | Pakke | Bygget | Testet | Signert | Trygt å publisere som stabil |
|---|---|---|---|---|---|
| Windows 10/11, x64 | Installasjonsprogram med innebygd kjøretid (`EmneKlar-<versjon>-setup.exe`) | Ja – lokalt på Windows 11 og på en ren Windows-kjører i GitHub Actions | Ja. Lokalt og i GitHub Actions (jobben `windows-package`, 11.11.2026): installasjon, start uten konsollvindu, avslutting, reinstallasjon mens programmet kjører, avinstallering, oppdatering med bytte av kjøretid og tilbakerulling. Bare lokalt: vernet mot nedgradering og oppdatering med samme kjøretid | Nei – Authenticode-sertifikat mangler. Python-filene i kjøretiden er signert av Python Software Foundation | Ja. Utgivelsesjobben (`release.yml`) har publisert forhåndsversjonen 0.2.0-alpha.1 (11.11.2026). Kjent ulempe uten signatur: SmartScreen advarer om ukjent utgiver, og Chrome kan blokkere nedlastingen |
| Windows 10/11, x64 | Zip-pakke med egen Python (`setup.bat`) – reserveløsning | Ja | Ja: `setup.bat`, start og stopp lokalt og i CI-jobben `windows-install` (11.11.2026); oppdateringen er dekket av enhetstester | – | Ja, som reserveløsning for dem som har Python |
| Windows på ARM | Ingen egen pakke. x64-pakken kan trolig kjøre under emulering | Nei | Nei | – | Nei – ikke prøvd |
| macOS, Apple Silicon (arm64) | Ingen | Nei | Bare én ting: programmet starter fra kildekoden og svarer på `/api/health` i GitHub Actions (`macos-latest`, 11.11.2026). Ingen pakke, installasjon, nøkkelring eller oppdatering er prøvd | Nei – krever Apple Developer ID | Nei |
| macOS, Intel (x86_64) | Ingen | Nei | Som over, på `macos-15-intel` (11.11.2026) | Nei | Nei |
| Linux, x86_64 | Ingen | Nei | At programmet starter fra kildekoden og svarer på `/api/health`, og at backend-testene består på Ubuntu med Python 3.11–3.14 (824 består, én hoppes over fordi den trenger `cmd.exe`) – begge i GitHub Actions, 11.11.2026. Ingen pakke, installasjon, nøkkelring eller oppdatering er prøvd | – | Nei |
| Linux, ARM (aarch64) | Ingen | Nei | Nei | – | Nei |

## Windows

Løsningen er beskrevet i [UPDATING.md](UPDATING.md) og [DEVELOPMENT.md](DEVELOPMENT.md). Kort:

* **Kjøretid:** den offisielle «embeddable package» av CPython 3.14.10 fra python.org (SHA-256 låst i
  `packaging/runtime.json`), med avhengighetene installert fra `packaging/runtime-win-amd64.txt` med
  `pip --require-hashes`. Bygget er reproduserbart (to bygg gir samme fil, bit for bit). Filen `python314._pth`
  gjør at kjøretiden ser bort fra miljøvariabler, registeret og pakker i brukerens profil. Læreren kjører aldri pip,
  og det som er testet, er det som installeres.
* **Installasjon:** Inno Setup, per bruker, i `%LOCALAPPDATA%\Programs\EmneKlar`, uten administratorrettigheter.
* **Start og stopp:** snarveiene starter `runtime\pythonw.exe -m emneklar` (ingen konsoll). EmneKlar vises i et eget
  vindu (Edge eller Chrome i app-modus), eller i en vanlig fane når ingen av dem finnes. Programmet stoppes med
  «Avslutt EmneKlar» i programmet eller i Start-menyen. På macOS og Linux åpnes alltid en vanlig fane. Appvinduet er
  prøvd lokalt på Windows 11 med Chrome og Edge, startet fra kildekoden (11.11.2026) – ikke ennå fra en installasjon.
* **Oppdatering:** `update.bat` → `scripts/update.py`. Programfilene byttes fil for fil med sikkerhetskopi;
  kjøretiden byttes som en hel mappe og settes tilbake som en hel mappe hvis noe feiler.

Det som gjenstår på Windows:

* **Kodesignering** av installasjonsprogrammet (sertifikat mangler). Uten den advarer SmartScreen, og Chrome kan stoppe
  nedlastingen som «farlig» – det skjedde med installasjonsprogrammet fra CI 11.11.2026.
* **Signerte utgivelser** (Ed25519) – verktøy og arbeidsflyt er klare, nøkkelparet er ikke laget.
* **Oppdatering fra en ekte GitHub-utgivelse** på en installert maskin («Oppdater nå» til 0.2.0-alpha.1). Utgivelsesjobben
  kjørte første gang 11.11.2026 for taggen `v0.2.0-alpha.1`, besto alle stegene og publiserte forhåndsversjonen; den
  prøver oppdateringen med lokale filer før den publiserer, men en oppdatering som henter fra GitHub, er ikke prøvd ennå.
* **Windows på ARM** er ikke prøvd.
* **Styrte maskiner:** der IT har sperret kjøring av programmer fra brukerens egen profil (AppLocker/WDAC), kan en
  installasjon per bruker ikke kjøre. Det kan EmneKlar ikke omgå.

## macOS

**Ingen Mac-pakke finnes.** Det eneste som er prøvd på macOS, er at programmet starter fra kildekoden og svarer i
GitHub Actions (Apple Silicon og Intel). Det er derfor ikke en støttet plattform.

Undersøkt:

* **Avhengighetene:** alle 42 pakkene i låsefilen har ferdigbygde filer («wheels») på PyPI for CPython 3.14 på macOS,
  både for Apple Silicon (arm64) og Intel (x86_64) – kontrollert mot PyPI 11.11.2026. De binære pakkene er `av`,
  `markupsafe`, `nh3`, `numpy`, `pillow`, `pydantic-core` og `pypdfium2`; resten er ren Python. Avhengighetene er
  altså ikke hindringen.
* **Python-kjøretid:** python.org har ingen «embeddable package» for macOS. En Mac-pakke må bygges på en annen
  Python-distribusjon som kan flyttes (for eksempel python-build-standalone) eller med et verktøy som lager en
  `.app` (for eksempel Briefcase eller py2app). Ingen av delene er prøvd. `scripts/build_runtime.py` håndterer bare
  oppsettet til Windows-pakken (`python314._pth` finnes bare på Windows).
* **Apple Silicon og Intel** er to ulike bygg. Et «universal2»-bygg ville kreve at både Python og alle de binære
  pakkene finnes som universal2; det er ikke kontrollert. Hver arkitektur må bygges og testes for seg, på maskin
  eller CI-kjører av samme type (`macos-latest` er Apple Silicon, `macos-15-intel` er Intel).

Klart i koden:

* Datamappen: `~/Library/Application Support/EmneKlar` (`core/system.py`, dekket av en enhetstest – ikke kjørt på en
  Mac).
* Plattformnavnet for kjøretid (`macos-arm64`, `macos-x86_64`) og en `install.json` som kan navngi én kjøretid per
  plattform. Oppdatereren velger kjøretid etter plattformnavnet.
* `scripts/update.py` har grener for andre systemer enn Windows (stien til tolkeren, start som egen økt), men de
  er ikke kjørt.
* Hemmeligheter: `keyring` bruker macOS-nøkkelringen uten ekstra pakker. Ikke prøvd med EmneKlar.

Gjenstår før en Mac-pakke kan gis ut:

1. En kjøretid som kan flyttes, bygget og låst med hasher, for arm64 og x86_64 hver for seg.
2. En `.app` med ikon som starter EmneKlar uten terminalvindu, og en måte å avslutte på (i dag: «Avslutt EmneKlar» i
   programmet; snarveiene i Start-menyen finnes bare på Windows).
3. Oppstart og oppdatering uten `.bat`-filer: det finnes ingen `setup.sh`, `start.sh` eller `update.sh`, og
   «Oppdater nå» i programmet er bare tilgjengelig på Windows (`core/updates/service.py`).
4. «Åpne mappen» (Innstillinger) og meldingsbokser ved oppstartsfeil er bare laget for Windows (`core/system.py`
   svarer at det ikke støttes).
5. **Signering og notarisering:** en Mac-app som lastes ned, må signeres med Developer ID og notariseres av Apple,
   ellers stopper Gatekeeper den. Det krever en Apple Developer-konto, som ikke finnes i dag.
6. Testing på ekte maskiner av begge arkitekturer: installasjon, start, oppdatering, tilbakerulling, avinstallering.

## Linux

**Ingen Linux-pakke finnes.** Linux er ikke en støttet plattform, og EmneKlar lover ingen generell
Linux-kompatibilitet.

Det som er kjent:

* **Backend-testene** består på Ubuntu i CI (Python 3.11–3.14, 11.11.2026; én hoppes over fordi den trenger `cmd.exe`),
  og en startprøve har vist at programmet starter fra kildekoden og svarer (11.11.2026). Det viser at programkoden
  kan lastes, testes og startes der – ikke at EmneKlar kan installeres, startes av en lærer eller oppdateres.
* **Avhengighetene:** alle 42 pakkene har ferdigbygde filer for CPython 3.14 på Linux x86_64 og aarch64
  (manylinux/musllinux), kontrollert mot PyPI 11.11.2026.
* **Datamappen:** `$XDG_DATA_HOME/emneklar`, ellers `~/.local/share/emneklar` (enhetstestet).
* **Hemmeligheter:** `keyring` trenger en Secret Service-tjeneste (GNOME Keyring eller KWallet) og pakkene
  `SecretStorage` og `jeepney`, som ikke er låst i `backend/constraints.txt`. Uten en slik tjeneste (for eksempel på
  en tjener uten skrivebord) kan EmneKlar ikke lagre Canvas-tokenet.

Slik kan en utvikler kjøre EmneKlar fra kildekoden på Linux eller macOS (ikke testet i denne runden):

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -c backend/constraints.txt -e backend
(cd frontend && npm ci && npm run build)
(cd backend && .venv/bin/python -m emneklar)
```

Gjenstår før en Linux-pakke kan gis ut:

1. Bestemme distribusjoner og arkitektur som skal støttes, og et pakkeformat (for eksempel AppImage eller en
   tar-pakke med kjøretid). Ingenting er valgt.
2. En kjøretid som kan flyttes, låst med hasher (som for macOS).
3. Oppstart uten terminal (en `.desktop`-fil), en måte å avslutte på, «Åpne mappen» (`xdg-open`) og oppdatering uten
   `update.bat`.
4. Testing på de valgte distribusjonene.

## Jobbene i GitHub Actions

| Jobb | Kjører | Hva den gjør | Kan stoppe en utgivelse |
|---|---|---|---|
| `backend`, `frontend`, `dependency-audit` | hver pull request (Linux) og på `main` | tester, typesjekk, lint, bygg, sårbarhetssjekk | – |
| `windows-package` | `main` og manuelt | bygger kjøretid, pakke og installasjonsprogram; installerer, starter, oppdaterer, ruller tilbake og avinstallerer. Har alt bestått, lagres installasjonsprogrammet i 14 dager som artefakt (ikke signert, ikke en utgivelse) | – |
| `windows-install` | `main` og manuelt | `setup.bat` med egen Python, start og stopp | – |
| `platform-smoke` (Ubuntu, macOS arm64, macOS Intel) | `main` og manuelt, `continue-on-error` | starter programmet fra kildekoden og sjekker `/api/health`. Ikke en støtteerklæring | Nei |
| `release` → `windows` | når en tag `v*` pushes | bygger og **verifiserer** Windows-pakken, og publiserer først da | Ja – bare Windows |

Jobbene `windows-package`, `windows-install` og `platform-smoke` kjørte første gang 11.11.2026 og besto. Utgivelsesjobben
kjørte første gang samme dag, for taggen `v0.2.0-alpha.1`: alle stegene besto, og forhåndsversjonen ble publisert.
