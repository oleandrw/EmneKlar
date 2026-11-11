# EmneKlar

EmneKlar hjelper lærere og emneansvarlige med å analysere, kvalitetssikre og forbedre emner i Canvas. Programmet
kjører på din egen Windows-maskin og bruker Canvas med ditt eget API-token. Ingenting endres i Canvas før du har sett
og godkjent det – med ett unntak du må velge selv: «Automatisk innsetting» i KI-bildeassistenten setter inn bilder
som består kvalitetskontrollen, uten at du ser hvert bilde først. Også de går via endringskøen, med konfliktsjekk,
sikkerhetskopi, logg og angremulighet.

## Hva EmneKlar kan

* **Universell utforming** – finner mulige avvik etter et versjonert regelsett og valgt regulatorisk profil, med
  forklaring, kriterium, testmetode og forslag til retting. EmneKlar påstår aldri at et emne er «100 % universelt
  utformet».
* **Innholdskvalitet** – lenker, medier og HTML-kode.
* **Emnestruktur** – veiledende forslag og studentreisen.
* **Quizassistent** – kvalitetssjekk av klassiske quizer, KI-spørsmålsbank og quizbygger.
* **Emnedesign** – gi hele emnet eller én modul ett helhetlig design (forside, emneplan, sider, oppgaver og
  quizinnledninger), med forhåndsvisning før og etter og godkjenning før noe publiseres.
* **Canvas-verktøy** – modulkrav, Blueprint-låsing, Canvas-innstillinger, backup og endringslogg, og **Emnets
  kunnskapsbase**: still spørsmål til emnets innhold og få svar med klikkbare kilder.
* **Rapporter** – HTML (kan lagres som PDF) og CSV.

Alt følger samme prinsipp: **analyser → finn → se sammenhengen → rett → godkjenn → publiser → logg**. Analyser og
forhåndsvisninger endrer aldri noe i Canvas; godkjente endringer samles i én endringskø og sendes først når du velger
**Publiser til Canvas**.

## Installere

Du trenger 64-biters Windows 10 eller 11. Du trenger ikke administratorrettigheter, og du trenger ikke å installere
Python eller andre verktøy – alt EmneKlar trenger, følger med.

1. Last ned **`EmneKlar-<versjon>-setup.exe`** fra [siste utgivelse](https://github.com/oleandrw/EmneKlar/releases/latest).
2. Kjør filen og følg veiviseren. EmneKlar installeres bare for deg, i `%LOCALAPPDATA%\Programs\EmneKlar`, med snarvei
   i Start-menyen og – hvis du vil – på skrivebordet. Ingenting lastes ned under installasjonen.
   * Installasjonsprogrammet er foreløpig **ikke signert**. Windows kan derfor vise «Windows beskyttet PC-en din».
     Har du lastet ned filen fra lenken over, velger du **Mer informasjon → Kjør likevel**. Vil du kontrollere filen
     først, sammenligner du SHA-256 med `EmneKlar-<versjon>-setup.exe.sha256` i utgivelsen (i PowerShell:
     `Get-FileHash EmneKlar-<versjon>-setup.exe`).
3. Start **EmneKlar** fra Start-menyen eller skrivebordet. EmneKlar åpnes i et eget vindu uten adresselinje og faner.
   Vinduet lages av Microsoft Edge, som følger med Windows – eller av Google Chrome hvis det er standardnettleseren
   din. Selve programmet kjører i bakgrunnen på maskinen din. Finnes verken Edge eller Chrome, åpnes EmneKlar i en
   vanlig fane i standardnettleseren.
4. Følg oppsettet i fire steg: **Tilkobling** (Canvas-adresse og tilgangstoken – «Koble til» kontrollerer dem),
   **Bekreftelse** (hvem du er tilkoblet som, Canvas-adresse og tilganger – først her lagres tilkoblingen), **Emne og
   regelverk** (startemne og hvilke krav som skal kontrolleres) og **Ferdig**. Tokenet lager du i Canvas under
   **Konto → Innstillinger → Godkjente integrasjoner**.

**Avslutte EmneKlar:** lukk vinduet. Når det siste EmneKlar-vinduet er lukket, avsluttes programmet etter noen
sekunder; en jobb som kjører (for eksempel en analyse eller en publisering til Canvas), gjøres ferdig først. Vil du
avslutte med en gang, velger du **Avslutt EmneKlar** i kontomenyen nederst til venstre i programmet, under
**Innstillinger → Sikkerhet og personvern** eller i Start-menyen. Åpner du snarveien mens EmneKlar kjører, får du et
nytt vindu i det samme programmet.

**Tips når du prøver EmneKlar for første gang:** analyser, åpne funn og godkjenn så mye du vil – ingenting sendes til
Canvas før du trykker **Publiser til Canvas** i endringskøen og bekrefter. Vil du prøve publiseringen uten et ekte
emne, kan du bruke utviklingsserveren med falskt Canvas (se [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).

**Andre plattformer:** EmneKlar gis ut og testes for Windows. Det finnes ingen pakke for macOS eller Linux – se
[docs/PLATFORMS.md](docs/PLATFORMS.md) for hva som er undersøkt og hva som mangler.

**Uten installasjonsprogrammet:** har du Python 3.11 eller nyere fra før, kan du i stedet pakke ut
`EmneKlar-<versjon>.zip` i en mappe du selv eier og dobbeltklikke `setup.bat` og deretter `start.bat`. Det er en
reserveløsning: den laster ned avhengighetene med pip og starter EmneKlar i et konsollvindu. Se
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Oppdatere

EmneKlar oppdaterer seg selv fra GitHub:

* Gå til **Innstillinger → Generelt**, trykk **Se etter oppdateringer** og deretter **Oppdater nå**.
* Eller dobbeltklikk **`update.bat`** i programmappen (`%LOCALAPPDATA%\Programs\EmneKlar`).

Oppdateringen kjører i et eget vindu. Den stopper EmneKlar, tar sikkerhetskopi av databasen, kontrollerer det den
laster ned mot sjekksummen i utgivelsen, sjekker at den nye versjonen starter – og setter forrige versjon tilbake hvis
noe går galt. Dataene dine og innstillingene beholdes. Nye hovedversjoner installeres bare etter at du har bekreftet.
Under **Innstillinger → Avanserte innstillinger → Oppdateringer** kan du la EmneKlar se etter oppdateringer selv,
høyst én gang i døgnet. Du kan også alltid laste ned og kjøre det nyeste installasjonsprogrammet over den gamle
installasjonen. Se [docs/UPDATING.md](docs/UPDATING.md) for detaljer.

## Emnets kunnskapsbase

Under **Canvas-verktøy → Emnets kunnskapsbase** samler EmneKlar tekst, dokumenter, video og bilder fra emnet på din
maskin. Under **Spør emnet** kan du søke i innholdet eller få svar fra KI med kilder du kan klikke deg til. Svarene er
merket «KI-forslag – må vurderes». Bare lærerens innhold brukes, aldri innleveringer, karakterer, meldinger eller
studentinnlegg.

Kunnskapsbasen virker uten ekstra installasjon, med nøkkelordsøk og eksisterende teksting. Vil du ha semantisk søk
eller transkripsjon av video uten teksting, velger du en KI-leverandør i innstillingene for kunnskapsbasen. Ved
transkripsjon sendes bare lyden, og bare etter at du har godkjent det. Lokale modeller følger ikke med EmneKlar.

## Personvern og sikkerhet

* EmneKlar lytter bare på `127.0.0.1` og kan ikke nås fra nettverket.
* Canvas-token og API-nøkler lagres bare i Windows Legitimasjonsbehandling, aldri i filer, databasen, nettleseren
  eller logger.
* Dataene dine ligger i `%LOCALAPPDATA%\EmneKlar` (database, sikkerhetskopier, rapporter og logger), atskilt fra
  programmet. Oppdatering eller ny installasjon sletter dem ikke.
* KI er valgfritt. Sending av emneinnhold til eksterne KI-tjenester er **av** til du slår det på, og du ser hva som
  sendes før det sendes. Studentenes innleveringer, karakterer og meldinger sendes aldri. Emneinnhold sendes alltid
  som avgrenset data, aldri som instruksjoner: tekst i en side som prøver å styre KI-en, blir merket og ikke fulgt.

Trusselmodellen står i [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Hjelp og problemer

* Brukerveiledninger, vanlige spørsmål og feilsøking finnes i programmet under **Hjelp**.
* Under **Hjelp → Feilsøking** kan du kopiere feilsøkingsinformasjon. Den inneholder ingen token, nøkler eller
  emneinnhold.
* Loggen ligger i `%LOCALAPPDATA%\EmneKlar\logs\emneklar.log`.
* Fant du en feil? Meld den under [Issues](https://github.com/oleandrw/EmneKlar/issues).

## Avinstallere

1. Åpne **Innstillinger → Apper → Installerte apper** i Windows, finn **EmneKlar** og velg **Avinstaller**.
   Avinstalleringen stopper EmneKlar og fjerner programmet og snarveiene.
2. Dataene dine blir liggende. Vil du også fjerne dem, sletter du `%LOCALAPPDATA%\EmneKlar`. Brukte du en tidlig
   versjon, kan det også ligge en eldre kopi i `%LOCALAPPDATA%\EmneKlar-Claude`.
3. Vil du fjerne token og nøkler, åpner du **Legitimasjonsbehandling** i Windows. Under **Windows-legitimasjon →
   Generell legitimasjon** fjerner du oppføringene som inneholder `EmneKlar` (og `EmneKlar-Claude` fra en tidlig
   versjon).

## For utviklere

Oppsett, tester, utviklingsserver med falsk Canvas, utgivelser og teknisk dokumentasjon står i
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Endringene står i [CHANGELOG.md](CHANGELOG.md).
