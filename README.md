# EmneKlar

EmneKlar hjelper lærere og emneansvarlige med å analysere, kvalitetssikre og forbedre emner i Canvas. Programmet
kjører på din egen Windows-maskin og bruker Canvas med ditt eget API-token. Ingenting endres i Canvas før du har sett
og godkjent det.

## Hva EmneKlar kan

* **Universell utforming** – finner mulige avvik etter et versjonert regelsett og valgt regulatorisk profil, med
  forklaring, kriterium, testmetode og forslag til retting. EmneKlar påstår aldri at et emne er «100 % universelt
  utformet».
* **Innholdskvalitet** – lenker, medier og HTML-kode.
* **Emnestruktur** – veiledende forslag og studentreisen.
* **Quizassistent** – kvalitetssjekk av klassiske quizer, KI-spørsmålsbank og quizbygger.
* **Emneforside** – lag eller forbedre forsiden med forhåndsvisning på PC, nettbrett og mobil.
* **Canvas-verktøy** – modulkrav, Blueprint-låsing, Canvas-innstillinger, backup og endringslogg, og **Emnets
  kunnskapsbase**: still spørsmål til emnets innhold og få svar med klikkbare kilder.
* **Rapporter** – HTML (kan lagres som PDF) og CSV.

Alt følger samme prinsipp: **analyser → forklar → foreslå → forhåndsvis → godkjenn → endre → logg**. Med **Dry run**
slått på sendes ingenting til Canvas.

## Installere

Du trenger 64-biters Windows 10 eller 11 og internett under installasjonen. Administratorrettigheter trengs ikke.

1. Installer [Python 3.11 eller nyere](https://www.python.org/downloads/windows/). Kryss av for **«Add python.exe to
   PATH»** i installasjonsprogrammet.
2. Last ned **`EmneKlar-<versjon>.zip`** fra [siste utgivelse](https://github.com/oleandrw/EmneKlar/releases/latest).
3. Pakk ut ZIP-filen i en mappe du selv eier, for eksempel `Dokumenter\EmneKlar`. Unngå `Program Files`, ellers
   kan ikke EmneKlar oppdatere seg selv.
   * Advarer Windows om filene? Høyreklikk ZIP-filen før du pakker ut, velg **Egenskaper**, kryss av for
     **Opphev blokkering** (på engelsk «Unblock») og trykk **OK**.
4. Dobbeltklikk **`setup.bat`**. Den lager et eget Python-miljø for EmneKlar. Det tar noen minutter første gang.
5. Dobbeltklikk **`start.bat`**. Nettleseren åpnes med EmneKlar. Lukk vinduet til EmneKlar for å avslutte.
6. Følg oppsettveiviseren: Canvas-adresse, API-token, test av tilkoblingen og valg av emne. Tokenet lager du i Canvas
   under **Konto → Innstillinger → Godkjente integrasjoner**.

**Tips når du prøver EmneKlar for første gang:** la **Dry run** (øverst til høyre) være på. Da kan du utforske alt uten
at noe sendes til Canvas.

## Oppdatere

EmneKlar oppdaterer seg selv fra GitHub:

* Gå til **Innstillinger → Generelt**, trykk **Se etter oppdateringer** og deretter **Oppdater nå**.
* Eller lukk EmneKlar og dobbeltklikk **`update.bat`**.

Oppdateringen tar sikkerhetskopi av databasen, sjekker at den nye versjonen starter og setter forrige versjon tilbake
hvis noe går galt. Dataene dine og innstillingene beholdes. Nye hovedversjoner installeres bare etter at du har
bekreftet. Under **Innstillinger → Avanserte innstillinger → Oppdateringer** kan du la EmneKlar se etter
oppdateringer selv, høyst én gang i døgnet. Se [docs/UPDATING.md](docs/UPDATING.md) for detaljer.

## Emnets kunnskapsbase

Under **Canvas-verktøy → Emnets kunnskapsbase** samler EmneKlar tekst, dokumenter, video og bilder fra emnet på din
maskin. Under **Spør emnet** kan du søke i innholdet eller få svar fra KI med kilder du kan klikke deg til. Svarene er
merket «KI-forslag – må vurderes». Bare lærerens innhold brukes, aldri innleveringer, karakterer, meldinger eller
studentinnlegg.

Kunnskapsbasen virker uten ekstra installasjon, med nøkkelordsøk og eksisterende teksting. For bedre søk og
transkripsjon av video uten teksting på din egen maskin kan du installere lokale modeller. Lukk EmneKlar og
dobbeltklikk **`setup-emne-rag.bat`**. Det laster ned flere GB, og `update.bat` beholder modellene senere. Video uten
teksting kan også transkriberes av en ekstern KI-tjeneste som OpenAI. Da sendes bare lyden, og bare etter at du har
godkjent det.

## Personvern og sikkerhet

* EmneKlar lytter bare på `127.0.0.1` og kan ikke nås fra nettverket.
* Canvas-token og API-nøkler lagres bare i Windows Legitimasjonsbehandling, aldri i filer, databasen, nettleseren
  eller logger.
* Dataene dine ligger i `%LOCALAPPDATA%\EmneKlar-Claude` (database, sikkerhetskopier, rapporter og logger), atskilt fra
  programmet. Oppdatering eller ny installasjon sletter dem ikke.
* KI er valgfritt. Sending av emneinnhold til eksterne KI-tjenester er **av** til du slår det på, og du ser hva som
  sendes før det sendes. Studentenes innleveringer, karakterer og meldinger sendes aldri.

Trusselmodellen står i [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Hjelp og problemer

* Brukerveiledninger, vanlige spørsmål og feilsøking finnes i programmet under **Hjelp**.
* Under **Hjelp → Feilsøking** kan du kopiere feilsøkingsinformasjon. Den inneholder ingen token, nøkler eller
  emneinnhold.
* Loggen ligger i `%LOCALAPPDATA%\EmneKlar-Claude\logs\emneklar.log`.
* Fant du en feil? Meld den under [Issues](https://github.com/oleandrw/EmneKlar/issues).

## Avinstallere

1. Lukk EmneKlar og slett mappen du pakket ut programmet i.
2. Vil du også fjerne dataene dine, sletter du `%LOCALAPPDATA%\EmneKlar-Claude`.
3. Vil du fjerne token og nøkler, åpner du **Legitimasjonsbehandling** i Windows. Under **Windows-legitimasjon →
   Generell legitimasjon** fjerner du oppføringene som inneholder `EmneKlar-Claude`.

## For utviklere

Oppsett, tester, utviklingsserver med falsk Canvas, utgivelser og teknisk dokumentasjon står i
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Endringene står i [CHANGELOG.md](CHANGELOG.md).
