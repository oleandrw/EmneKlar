# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.
Formatet følger [Keep a Changelog](https://keepachangelog.com/no/1.1.0/), og prosjektet bruker
[semantisk versjonering](https://semver.org/lang/no/).

## [Unreleased]

### Lagt til
- **Installasjonsprogram for Windows:** `EmneKlar-<versjon>-setup.exe` installerer EmneKlar for én bruker, uten
  administratorrettigheter, med snarvei i Start-menyen og på skrivebordet og avinstallering fra Windows-innstillingene.
  Du trenger ikke lenger å installere Python eller andre verktøy: en ferdig Python-kjøretid med alle avhengighetene
  følger med (`runtime\`), og verken installasjonen eller oppdateringen kjører pip eller laster ned pakker.
  Installasjonsprogrammet stopper et EmneKlar som kjører, nekter å legge en eldre versjon over en nyere, og
  kontrollerer til slutt at programmet kan lastes. Det er **ikke kodesignert** ennå, så Windows SmartScreen advarer om
  ukjent utgiver. Zip-pakken med `setup.bat` og egen Python er beholdt som reserveløsning.
- **Start uten konsollvindu og «Avslutt EmneKlar»:** snarveien starter EmneKlar uten konsollvindu – nettleseren er
  brukergrensesnittet. Programmet avsluttes med «Avslutt EmneKlar» i kontomenyen, under Innstillinger → Sikkerhet og
  personvern, øverst i oppsettsveiviseren eller i Start-menyen; det advarer først hvis jobber kjører. Å lukke nettleserfanen stopper ikke
  programmet. Feil ved oppstart vises i en meldingsboks, og nettleseren åpnes bare når EmneKlar faktisk svarer.
  `EMNEKLAR_NO_BROWSER=1` gjør det samme som `--no-browser`.
- **Oppdatering av en installasjon med innebygd kjøretid:** `update.bat` og «Oppdater nå» virker på en installert
  utgivelse uten Python på maskinen. Trenger den nye versjonen en annen kjøretid, hentes den fra samme utgivelse,
  kontrolleres mot SHA-256 i programpakkens `install.json` og byttes som en hel mappe; er kjøretiden den samme, hentes
  ingenting. Feiler et senere steg, settes den forrige kjøretiden tilbake sammen med programfilene og databasen.
- **Forhåndsversjoner:** `scripts/bump_version.py 0.2.0-rc.1` (alpha, beta eller rc med nummer) setter versjonen i
  alle filer og lar `CHANGELOG.md` stå; utgivelsesnotatene er da «Unreleased». Taggen publiseres som forhåndsversjon,
  og bare kanalen «Også forhåndsversjoner» får tilbud om den.
- **Bygging og kontroll av Windows-pakken:** `scripts/build_runtime.py` (kjøretiden), `scripts/build_installer.py`
  (installasjonsprogrammet, Inno Setup), `scripts/verify_windows_installer.py` (installerer, starter, stopper og
  avinstallerer) og `scripts/local_update_test.py` (oppdaterer en installert kopi lokalt, uten GitHub og uten å røre
  dine data – også med en ny versjon som ikke kan starte). `build_installer.py --test-build` lager «EmneKlar (test)»,
  som installeres ved siden av en vanlig installasjon og har egen datamappe, port og tjeneste i
  Legitimasjonsbehandling (`emneklar.local.json` i programmappen), så den aldri åpner eller kopierer de vanlige
  dataene og aldri erstatter det ekte Canvas-tokenet – uansett hvordan den startes.
- **Signering lagt til rette:** `scripts/sign_release.py` lager nøkkelpar (den private nøkkelen skrives aldri i
  repositoriet), signerer sjekksumfilen og kontrollerer signaturen. Utgivelsesarbeidsflyten signerer når
  hemmelighetene `RELEASE_SIGNING_KEY` og `WINDOWS_SIGN_COMMAND` finnes, og gir ut usignert – og sier det – når de
  mangler. Ingen nøkkel og intet sertifikat finnes ennå, og signatur er ikke påkrevd.
- **Plattformstatus:** `docs/PLATFORMS.md` sier hva som er bygget, testet og signert på Windows, macOS og Linux, og
  hva som mangler. Bare Windows gis ut.
- **Signerte utgivelser (forberedt):** `update.bat` kan kontrollere en Ed25519-signatur av sjekksumfilen
  (`EmneKlar-<versjon>.zip.sha256.sig`) mot offentlige nøkler i koden, i tillegg til SHA-256. Ingen nøkkel er lagt inn
  ennå, og signatur er ikke påkrevd, så oppdateringer virker som før til signering er på plass. Se `docs/UPDATING.md`.
- **KI-bildeassistent** under Canvas-verktøy: analyserer hele emnet, én modul, flere moduler eller én side og lager
  faglig relevante illustrasjoner i én gjennomgående stil, med alternativ tekst og bildetekst. Fem steg: Velg
  innhold, Bildeinnstillinger, Analyser, Generer og gjennomgå, Publiser. Oversikt per modul og side, godkjenning av
  ett bilde, en side, en modul eller hele emnet, og «Fortsett» etter avbrudd.
- Bildeinnstillinger samler kvalitet (Balansert – standard, Maksimal kvalitet, Rask), antall illustrasjoner (Lav,
  Balansert, Høy) og designprofil. De beste tilgjengelige KI-modellene velges automatisk ut fra kvaliteten;
  modellnavn, bildeformat, visningsbredde og kostnader ligger under «Avanserte innstillinger».
- Hierarkisk kontekstmodell (emne → modul → side → seksjon) med strukturert kontekstpakke og hurtigbufret
  analyse. KI vurderer selv hvor bilder gir pedagogisk verdi og foreslår naturlig plassering; null bilder er et
  gyldig svar. Sider i flere moduler behandles én gang; andre modulelementer brukes som kontekst.
- Versjonert designprofil per emne med sju stiler, KI-forslag, eksempelbilde og referansebilder. Bildeformatet
  velges automatisk per bilde (16:9, 3:2, 4:3, 1:1 eller 2:3) innenfor emnets stil, eller låses for emnet.
- Tekst i bildene bare der den gir faglig verdi: korte etiketter i diagrammer, modeller, infografikk og prosesser,
  på innholdets språk, nøyaktig angitt i bildeplanen og kontrollert for stavefeil, lesbarhet og uønsket tekst.
  Andre bilder er tekstfrie. Kan slås av.
- Kvalitetskontroll av hvert bilde med en bildeanalysemodell (relevans, samsvar, kvalitet, stil, feil detaljer,
  tekst, læringsmål), ny runde ved behov, flagg for manuell kontroll, alt-tekst ut fra det faktiske bildet
  (dekorative bilder får `alt=""`) og bildetekst bare når den tilfører noe. Kreditering («KI-generert
  illustrasjon») er en egen linje, adskilt fra bildeteksten.
- Forhåndsvisning av bildene på selve siden (PC, nettbrett og mobil) før publisering.
- Canvas-tilpasset HTML: `figure`/`img`/`figcaption`, høyst 900 px bred som standard (kan endres), responsiv,
  bildetekst venstrejustert under bildet, `loading="lazy"` for bilder lenger ned på siden. Etter publisering
  kontrolleres hva Canvas beholdt; attributter Canvas fjerner (som `loading`), vises i grensesnittet.
- Bildegenerering i KI-laget (OpenAI Image API med referansebilder og vilkårlige formater, Azure OpenAI,
  OpenAI-kompatible servere) med katalog over bildemodeller (GPT-Image-2.5 Sunburst og Flare). Kvalitetsprofilene
  fordeler Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5 og GPT-6 Astra / GPT-6.1 Sol / GPT-6.1 Terra på analyse,
  bildeplan og kontroll.
- Kostnadsanslag som intervall før start (veiledende priser, ikke garantert), registrering av faktisk forbruk og
  kostnadsgrense per jobb.
- Publisering via endringsmotoren: 3-stegs filopplasting til Canvas-filer, innsetting mellom avsnitt uten å endre
  eksisterende HTML, konfliktsjekk (også mot lagringer under opplastingen), sikkerhetskopi, publiseringsstatus
  beholdes, opphavsrett når emnet krever det, valgfri automatisk innsetting, og angring som bare fjerner
  EmneKlars figurer.
- `GPT-6.1 Terra` i modellkatalogen.
- **Rett direkte i EmneKlar.** Døde og problematiske lenker: erstatt adressen, endre lenketeksten, fjern lenken men
  behold teksten, eller fjern hele lenken – for én forekomst, alle på siden eller alle steder i emnet. Lenker uten
  tekst får forslag til lenketekst; overskriftsnivå vises med koden. Alle rettinger forhåndsvises automatisk, med
  «Slik blir det» som viser bare elementet før og etter.
- **Målrettede endringer** (`core/canvas/html_edit.py`): rettinger endrer bare elementet i den opprinnelige HTML-en.
  Andre lenker, bilder, innebygd innhold og formatering på siden forblir byte for byte like.
- **Alt-tekst med bildet foran deg:** detaljvisningen viser selve bildet (også Canvas-bilder som krever innlogging –
  tokenet blir i backend), hvor det står (side, modul, nærmeste overskrift), teksten før og etter, bildeteksten og
  nåværende alt-tekst, side om side med KI-forslaget og et redigerbart felt. «Dekorativt» gir tom alt-tekst.
- **Forhåndslagde KI-forslag:** «Forbered forslag» viser hva som sendes, og lager forslag i bakgrunnen, tre om
  gangen. Bildet du ser på og de neste i listen kommer først. Forslag lagres og gjenbrukes så lenge bildet og
  konteksten er uendret, og status (i kø, genereres, klart, feilet) vises i listen og i detaljvisningen. Ny prompt
  med WCAG 1.1.1-veiledning og den pedagogiske sammenhengen.
- **Direkte til Canvas:** hvert funn har «Åpne i Canvas», «Rediger i Canvas» og «Vis i modulen» (ny fane) for sider,
  oppgaver, quizer, diskusjoner/kunngjøringer, emneplan, filer og modulelementer. Lenketeksten eller overskriften
  markeres når nettleseren støtter tekstfragmenter. «Brukt i» i lenkeoversikten er klikkbar og har «Rett» per sted.
- **Rask godkjenning:** «Godkjenn» legger rettingen godkjent i køen og åpner neste funn; «Hopp over»; bla med
  Forrige/Neste (Alt + N / Alt + P, Ctrl + Enter godkjenner). Velg flere funn og «Godkjenn valgte», eller
  «Godkjenn alle klare» (rettinger som er bestemt av funnet, eventuelt med klare tekstforslag) – én endring per side.
- **Én samlet endringskø og «Publiser til Canvas»:** køen viser alle emner, hva som er godkjent, feil og
  konflikter. Publisering viser emner og antall før bekreftelse, fremdrift underveis og resultat per endring, med
  «Prøv igjen», «Lag forslaget på nytt» etter en konflikt og «Angre godkjenning».
- **Blueprint uten egne sperrer:** rettinger tilbys også for Blueprint-låst innhold, og forhåndsvisningen sier hvor
  endringen gjøres og hvilke emner den når. Avviser Canvas en endring av låst innhold, kan den flyttes til
  Blueprint-emnet med ett klikk, og en synkronisering til de tilknyttede emnene legges i køen (med status fra Canvas).
- Utviklingsserveren har `--demo`: Blueprint-emne med tilknyttet emne og låst side, mange funn på én side og en falsk
  KI-leverandør, så hele flyten kan prøves lokalt uten å endre et ekte emne.

- **Emnedesign** i hovedmenyen (der Emneforside var): gi hele emnet eller én modul ett helhetlig design.
  - Flyten er Omfang → Design → Forhåndsvisning → Godkjenning, vist som en vannrett stegrad (på mobil «Steg 1 av
    4 – Omfang»). Et steg kan ikke hoppes over, og valgene beholdes når du går tilbake.
  - Første steg har valgkort for hele emnet eller én modul, modulvelger med antall innholdselementer (og søk når
    emnet har mange moduler), en oppsummering av hva som faktisk blir berørt (fra Canvas), tydelige tilstander for
    innlasting, feil med «Prøv igjen», manglende tilgang og tomt emne, og et eksempel på design på brede skjermer.
  - «Analyser emnet» er nedtonet i Emnedesign og blir aldri avkortet i topplinjen.
  - Første steg viser unike totaler (en side i flere moduler eller som forside telles én gang), hva som hoppes
    over, tilgangsbegrensninger og fordelingen under «Se fordeling». Blueprint forklares samlet for utvalget med
    faktiske tall – Blueprint-emne eller tilknyttet emne, låste elementer og hvordan endringer synkroniseres – og
    detaljer under «Se Blueprint-detaljer».
  - Modulvelgeren er én sammenhengende komponent med søk, antall moduler eller treff og klikkbare rader med antall
    elementer (og plassering når navn er like). Valget lagres med modulens ID, og «Neste: velg design» står i en fast
    handlingsrad som blir tilgjengelig når innholdet er lest.
  - Eksemplet viser toppen av en side uten intern rulling, og «Se større eksempel» åpner det i en dialog.
  - Knappen i topplinjen heter «Analyser emnet» (uten tre prikker). Svevemarkeringen i sidepanelet er svakere enn
    markeringen av gjeldende side.
  - Rettet: antall filer og andre elementer som ikke støttes, telles én gang selv om de ligger i flere moduler, og New
    Quizzes telles bare for modulen som er valgt.
  - Fire designprofiler: Akademisk (standard), Lyst og moderne, Visuelt og pedagogisk, og Grønn akademi (etter
    NETTPED-spesifikasjonen). Alle kan forhåndsvises med samme eksempelinnhold.
  - Designet brukes på forside, emneplan, modulintroduksjoner, innholdssider, oppgavebeskrivelser og innledningen i
    klassiske quizer. New Quizzes, quizspørsmål, diskusjoner og Canvas' grensesnitt utelates, med begrunnelse.
  - «Behold oppbyggingen» endrer bare stilen. «Foreslå bedre oppbygging» lager KI-forslag til seksjoner og plassering
    av eksisterende innhold. Forslaget valideres, vises før godkjenning og skriver ikke nytt innhold.
  - Bevaringskontroll stopper forslag som ville endret tekst, lenker, bilder, tabeller, ligninger, kode eller innebygd
    innhold.
  - Gjentatt bruk og bytte av profil gir ingen doble innpakninger. Designet gjenkjennes også når Canvas har fjernet
    klasser og attributter.
  - Forhåndsvisningen sammenlignes med innholdet i Canvas før godkjenning, så nyere endringer ikke overskrives.
  - Lagret designvalg per emne, og «Behold eksisterende design» per element. Migrering 0007.
  - Feltene for aktiviteter har avrundede hjørner og tynn kant i samme farge som overskriftsstripen, uten tykk
    strek til venstre (profilversjon 2). Innhold med den første versjonen får den nye stilen når designet brukes
    på nytt; den gamle streken fjernes.

- **Tittel på innebygde YouTube-videoer** i rettevinduet under Universell utforming: feltet fylles med videoens
  egen tittel fra YouTube, ellers et forslag ut fra sidetittelen og overskriften rundt videoen, og kilden vises.
  Uten god tittel kan du be om et KI-forslag (merket «KI-forslag – må vurderes»), etter å ha sett hva som sendes.
  Har YouTube en tittel, kan du likevel be om et KI-forslag for å sammenligne («Se hva KI foreslår»).
  Bruker samme oppslag som «Standardiser videoavspillere»; det du har skrevet selv, byttes aldri ut.

- **Unntak for eldre dokumenter** (regelsett 2026.11.3): dokumentfunn for filer lastet opp før 1. februar 2022
  kan bekreftes med «Unntaket for eldre dokumenter gjelder» og en begrunnelse. Funnet blir «Kontrollert», også
  ved nye analyser og i rapporter. Valget tilbys og godtas bare når opplastingsdatoen tillater det.
- Trinnvis veiledning for skannede PDF-er: fjern dem hvis de ikke trengs, lag dem på nytt fra originalen eller med
  tekstgjenkjenning (OCR), og erstatt filen i Canvas med samme filnavn så lenkene virker.

- **KI-forslag i rettevinduet** – ett felles mønster («Foreslå … med KI» → se og rediger → forhåndsvis → godkjenn til
  endringskøen) for lenketekst (vage lenker, nettadresser som lenketekst og tomme lenker), tabelltitler og tittel på
  innebygd innhold. Lenkemålet leses trygt (Canvas-innhold via API-et, andre sider gjennom SSRF-vernet, aldri
  adresser med tilgangsopplysninger), og grunnlaget vises. Tabeller sender bare overskriftscellene. Svaret valideres,
  brukerens egen tekst byttes ikke ut uten et klikk, samtykke huskes per oppgave og tjeneste i økten, og en godkjent
  retting med KI-tekst merkes som KI-generert. Uten KI-tjeneste vises en lenke til oppsettet.
- «Godkjenn alle klare» tar ikke lenger med KI-forslag til alt-tekst som ingen har gjennomgått – bare regelbaserte
  tekstforslag. Knappen i alt-tekstvurderingen heter «Foreslå alternativtekst med KI».

- **Lenkeoversikten under Innholdskvalitet**: én rad per lenke (Lenke – Kontrollresultat – Brukt i – Handlinger)
  med tittel fra lenketeksten, domene og forkortet adresse, «Brukt på N steder (M lenker)» som kan utvides, og
  stablet visning på smale skjermer. Statusene er «Fungerer», «Fungerer ikke» (påvist feil), «Krever innlogging»
  og «Kunne ikke kontrolleres» – tidsavbrudd og 403 telles aldri som døde lenker, og totaler og filtre bruker samme
  inndeling. «Sjekk på nytt» lagrer resultatet og oppdaterer raden og totalene.
- **Endre lenke / Endre flere steder**: velg hvilke steder som skal endres, se gammel og ny adresse og en
  forhåndsvisning, og godkjenn til endringskøen (med ombygging på nyere innhold ved konflikt). Lenketekst, bilder og
  attributter beholdes med mindre du velger ny lenketekst. Ved flere steder er ingenting forhåndsvalgt, og knappen
  sier hva som mangler. «Rett funnet» under «Brukt på …» åpner funnet for ett sted (også «Fjern lenken, behold
  teksten»).
- **Finn alternativ lenke med KI**: opptil tre forslag fra videresending, nettsøk via KI-tjenestens søkeverktøy
  (Anthropic og OpenAI) og Internet Archive, med kilde, begrunnelse, type (samme ressurs, alternativ, arkivert),
  teknisk kontroll og kjente begrensninger. KI kan bare velge blant faktiske kandidater. Nettsøk er lagt til i
  KI-laget (`web_search`).
- **Analysestatus**, rett til venstre for analyseknappen, samler bakgrunnsjobbene – innholdskvalitet, universell
  utforming, emnestruktur, mediekontroll og de andre – i ett kompakt panel. I hvile er kontrollen et diskret ikon
  (navn og verktøytips «Analysestatus»); ellers viser den for eksempel «1 pågår» eller «2 pågår · 1 avbrutt», med et
  statisk varselsymbol ved feil eller avbrudd, og teller alle aktive og uløste jobber. Analyseknappen står fast når
  kontrollen endrer bredde (også når toppfeltet brytes på smale skjermer). Tekniske jobbfeil heter «Feilet» eller
  «Avbrutt», aldri «avvik».
  - Hver jobb viser navn, statusmerke (blå «Pågår», grønn «Fullført», gul «Avbrutt», rød «Feilet», «Venter») og hva
    EmneKlar gjør nå. Med kjent omfang vises en tynn blå linje, antall og prosent regnet fra de samme tallene (for
    eksempel «124 av 380 lenker · 32 %»); når tallene bare gjelder stegene så langt, står det. Før omfanget er kjent,
    vises et segment som beveger seg og «Antall foreløpig ukjent» – ingen prosent.
  - Rolig: én roterende indikator, bare i kontrollen og bare mens panelet er lukket. Radene, analyseknappen og sidene
    har ingen. Med redusert bevegelse er indikatoren et stillestående symbol og linjen stripet.
  - Rydder seg selv: pågående og ventende jobber først, så uløste (feilet eller avbrutt), så høyst fire fullførte fra
    det siste døgnet under «Sist fullførte» («Ingen analyser pågår» står over når ingenting kjører) – og høyst ti rader («Vis alle aktive og uløste (N)» når det er flere). En ny kjøring av samme
    jobb for samme emne og omfang erstatter den gamle raden; en aktiv jobb skjules aldri. «Fjern fullførte» og «Skjul»
    rydder bare oversikten, ikke resultatene eller historikken.
  - Uløste jobber – også en jobb du selv avbrøt – blir stående, uansett alder, til du velger «Skjul» eller «Prøv igjen». «Prøv igjen» starter bare den
    samme analysen på nytt med samme valg, i samme rad; andre jobber får «Gå til …», og publisering til Canvas prøves
    aldri på nytt herfra.
  - Panelet åpner seg når du starter en jobb, uten å flytte fokus, og ligger over innholdet. Escape og klikk utenfor
    lukker det. Fremdriften blir værende når du bytter side, og jobber for et annet emne merkes med emnet.
  - Mister EmneKlar kontakten med serveren, vises «Ingen kontakt» og «status ukjent» i stedet for at jobben ser ut til
    å fortsette. Etter en omstart vises jobber som ble avbrutt, ut fra historikken.
  - Skjermlesere får beskjed når en jobb starter, når omfanget blir kjent og når den er ferdig – ikke ved hver
    prosentendring.
- **Jobbhistorikk** under Rapporter: de siste 50 analysene og bakgrunnsjobbene for emnet, med status, tidspunkt og
  resultat eller årsak. Panelet lenker hit.

### Endret
- **Utgivelsen brukes før den publiseres:** når en tag `v*` pushes, bygger arbeidsflyten kjøretiden, programpakken og
  installasjonsprogrammet på en ren Windows-maskin, installerer, starter, oppdaterer (også med tilbakerulling) og
  avinstallerer dem – og oppretter utgivelsen først når alt har bestått. Alle filnavn får versjonen fra `VERSION`.
  CI har fått samme kontroll på `main` (`windows-package`), Python 3.14 i testmatrisen (versjonen som følger med
  Windows-pakken), sårbarhetssjekk av de låste pakkene i kjøretiden, og en startprøve på Linux og macOS som aldri kan
  stoppe en utgivelse. Ingen av de nye jobbene har kjørt ennå.
- **Feilmeldinger og Hjelp forutsetter ikke lenger `start.bat`:** tekstene viser til Start-menyen og
  installasjonsprogrammet, og Hjelp → Feilsøking forklarer hvordan EmneKlar startes, avsluttes og repareres.
  `setup.bat` i en installasjon med innebygd kjøretid installerer ingenting – den kontrollerer installasjonen.
- **Ett tynt lag mot maskinen:** datamappe per plattform, meldinger uten konsollvindu, «åpne mappe» og plattformnavn
  for kjøretid ligger i `core/system.py`. En test stopper nye, spredte plattformtester.
- **Ett navn – EmneKlar:** datamappen heter nå `%LOCALAPPDATA%\EmneKlar`, og tjenesten i Windows
  Legitimasjonsbehandling heter «EmneKlar» (før: `EmneKlar-Claude`). Første gang den nye versjonen starter, kopieres den
  gamle datamappen til den nye (database, sikkerhetskopier, rapporter, logger, indekser og bilder – ikke hurtigbuffer
  og nedlastede modeller), og Canvas-token og KI-nøkler kopieres til det nye tjenestenavnet. Den gamle mappen og de
  gamle oppføringene endres ikke; slett dem når du har sett at alt virker. Kopien gjøres bare for standardmappen, bare
  én gang, og aldri inn i en mappe som allerede har en database. EmneKlar åpner fortsatt aldri en database som
  tilhører et annet program. Et annet program med samme navn kan ikke brukes av samme Windows-bruker, fordi
  oppføringene i Legitimasjonsbehandling da deles (se `docs/THREAT_MODEL.md`).
- **Utgivelsespakken inneholder bare programmet:** `EmneKlar-<versjon>.zip` har nå bare det som trengs for å kjøre og
  oppdatere EmneKlar: programkoden, databasemigreringene, det ferdigbygde grensesnittet, `setup.bat`, `start.bat`,
  `update.bat` og oppdateringsskriptene. Tester, `.github/`, `.claude/`, `CLAUDE.md`, kildekoden til grensesnittet og
  utviklerdokumentasjonen er ikke lenger med. Hver fil Git følger må være merket som programfil eller utviklingsfil i
  `scripts/package_release.py`; en fil som ikke er merket, stopper byggingen. `--working-tree` pakker mappen slik
  den står, til testing før noe er committet.
- **Raskere lasting av grensesnittet:** filene under `/assets` har innholdshash i navnet og får nå
  `Cache-Control: public, max-age=31536000, immutable`, og de sendes gzip-komprimert. `index.html` hentes fortsatt på
  nytt hver gang (`no-cache`), og API-svar bufres ikke (`no-store`) og komprimeres ikke.
- **Skyggenivåene er komplette, og diagramteksten følger typografiskalaen:** `--shadow-md` og `--shadow-lg` var brukt,
  men ikke definert, så reserveverdien gjaldt. Nå er de definert i lyst og mørkt tema, mellom de eksisterende
  nivåene. Aksetekstene i diagrammene bruker `--text-xs` i stedet for 13 px, og følger dermed tekststørrelsen du
  velger. En test kontrollerer at alle skyggenivåene som brukes, finnes i begge temaer.
- **Roligere farger på verktøykortene i Canvas-verktøy:** kortene hadde seks ulike farger, og den oransje på
  «Sikkerhetskopier og endringslogg» kunne leses som en advarsel. Nå har fargen mening: blå for verktøy som arbeider
  på emnet i Canvas, fiolett for KI-verktøyene og nøytral for endringsloggen. Oransje og rød er forbeholdt det som
  krever oppmerksomhet.
- **Én primær analysehandling i quizdetaljen:** «Analyser quizkvalitet» øverst til høyre er hovedhandlingen, som ellers
  i programmet. Knappen i quizdetaljen heter nå «Kontroller bare denne quizen» og er en rolig handling som starter den
  samme kontrollen for én quiz.
- **Oppsettet har fire steg i stedet for ni**: Tilkobling (adresse og tilgangstoken med øyeknapp i feltet, samlet
  tokenveiledning, «Lagring og databruk» og «Koble til»), Bekreftelse (hvem du er tilkoblet som, Canvas-adresse,
  antall emner og tilganger – tilkoblingen lagres først når du bekrefter), Emne og regelverk (startemne med søk når
  listen er lang, og «Krav som skal kontrolleres» med «Norge – lovkrav, offentlig sektor» forhåndsvalgt i et nytt oppsett,
  detaljer og kilder) og Ferdig (kort oppsummering uten token; «Åpne EmneKlar» åpner oversikten eller emnevalget). Feil
  vises ved feltet de gjelder, og det du har skrevet, beholdes ved nettverksfeil. Et oppsett som ble avbrutt etter at
  tilkoblingen var lagret – også fra den gamle ni-stegsveiviseren – fortsetter på Emne og regelverk, og et tidligere
  valgt regelverk beholdes. Ingen analyse, KI eller publisering startes fra oppsettet.
- **Oppsettets siste finpuss**: startemnet vises med navn på én linje og emnekode og semester dempet på neste, likt i
  steg 3 og på oppsummeringen. «Tilkoblet som …» gjentas ikke i steg 3. Bekreftelsen bruker naturlige tall («2 emner
  med lærer-, assistent- eller designertilgang», «i begge kontrollerte emner»), og «Se alle tilganger (N)» viser hver
  tilgang som innvilget, delvis, mangler eller ukjent. Ferdig-siden har «Åpne emneoversikten» eller «Velg emne» og
  «Endre valg», som går tilbake til emne og regelverk uten ny tilkobling; en mislykket lagring vises aldri som lagret.
- **Tilgangslisten i oppsettet er kortere**: «Se alle tilganger (N)» sier én gang at alle tilgangene er innvilget i
  de kontrollerte emnene, og viser deretter bare navnene. Undertekst står bare der noe mangler, varierer eller ikke kunne
  kontrolleres – med emnekoden («Mangler i PDK2-26H»). Hvilke emner som ble kontrollert (og hvilke som ikke kunne
  kontrolleres), står over listen. Tilgangskontrollen er den samme; svaret sier nå også hvilke emner avvikene gjelder.
- **Emnenavn i bekreftelsen**: «Emner» viser emnene med navn, ett per linje (emnekode bare der to navn er like), og
  «Vis alle N emner» når det er mange. Over tilgangslisten står én setning med emnenavnene («Alle kontrollerte tilganger
  er innvilget i A og B.»); ved mange emner en kort setning og «Vis emnene». Tilgangssvaret viser til emnene med id.
- **Statusboksen i bekreftelsen følger tilgangene**: grønn «Tilkoblingen virker.» bare når alle kontrollerte tilganger
  er innvilget; ellers en dempet advarsel – «… men noen tilganger mangler.» eller «… men enkelte tilganger kunne ikke
  kontrolleres.». Manglende skrivetilgang er aldri en mislykket tilkobling og stopper ikke oppsettet. Over tilgangslisten
  står bare tallet («6 av 7 tilganger er innvilget i begge emnene.»). Overskriften, oppsummeringen og radene bruker samme
  ord: «kontrollerte» står bare når ikke alle emner ble kontrollert («i begge emnene» / «i 4 av 5 kontrollerte emner»).
- **Offentlig profil** har én tekst: «Lovkravene for offentlige virksomheter – anbefalt for statlige universiteter og
  høgskoler.»
- **Ferdig-siden**: «Endre valg» er en sekundærknapp ved siden av hovedknappen, og setningen om Innstillinger er fjernet.
- **Lange emnenavn i steg 3** vises på én linje med «…». Hele navnet vises når musepekeren er over valget eller det har
  tastaturfokus, og brytes naturlig på berøringsskjermer, med større tekst og på smale skjermer; skjermlesere får alltid
  hele navnet (`RadioGroup truncateLabels`).
- **Nytt felt i designsystemet: `PasswordField`** – skjult som standard, med en øyeknapp inne i feltet som heter «Vis …»
  / «Skjul …», aldri sender skjemaet og aldri dekker teksten.
- **Tilkoblingen er tryggere**: et lagret token sendes aldri til en annen Canvas-adresse, bare den bekreftede brukeren
  lagres, og mislykkes lagringen, beholdes den forrige tilkoblingen. Et token som skrives inn, maskeres i loggene også
  når det ikke lagres.
- **Radioknapper** har bare etiketten som navn og hjelpeteksten som beskrivelse (før ble hjelpeteksten lest to ganger).
- **Emneoversikten** er ryddigere: områdekortene har samme oppbygning (ikon og tittel, hovedtall, kort bunnlinje), og
  de lange detaljlinjene ligger bak «Vis detaljer». Forklaringen av tallene er flyttet bak «Hva betyr tallene?».
  Tallene følger faste fargeregler (rødt = bekreftede feil, oransje = bør vurderes eller kontrolleres, blått = forslag,
  0 alltid dempet, med eget token `--status-zero`). «Siste analyser og aktivitet» har statusmerker med tekst og ikon
  (Fullført, Avbrutt, Feilet m.fl.). Fokusringen vises bare ved tastaturnavigasjon.
- **Canvas-innstillinger** kontrollerer det som hindrer studentene i å gjøre og levere arbeidet:
  - nye kontroller for oppgaver som gir poeng uten innleveringsmåte i Canvas, oppgaver som ikke er tildelt noen,
    elementer som stenges før de åpner, og upubliserte oppgaver og quizer med frist de neste 14 dagene (bare i
    publiserte emner som ikke er Blueprint-emner);
  - datoene vises som «15.09.2026 kl. 23:59» i stedet for Canvas' tekniske format;
  - «Quizen har tidsbegrensning» og «Studentene kan ikke gå tilbake» er fjernet – det er lærerens valg, ikke feil.
    Kategorien heter nå «Sikkerhet».
- KI-ruterens reserveliste har alltid minst én modell fra en annen leverandør når det finnes.
- Publisering er robust mot flere endringer på samme side (fast rekkefølge, og oppskriftsbaserte rettinger bygges på
  nytt på innholdet EmneKlar nettopp publiserte), mot avbrudd og tidsavbrudd (en endring som allerede er lagret i
  Canvas, sendes ikke på nytt) og mot dobbel publisering (bare én publisering om gangen; publiserte endringer kan ikke
  sendes igjen). Canvas-avvisninger forklares (Blueprint-lås, manglende rettighet, borte innhold, nettverk).
- Fremdriftsvinduet for analysen viser bare prosent, estimert tid og hva som er ferdig per innholdstype – ikke lenger
  elementet som analyseres akkurat nå eller funn så langt.
- **Canvas-verktøy** har fått en ryddigere side:
  - Verktøyene vises først, i mer kompakte kort uten merkebobler. Knappene sier hva som skjer: «Sett modulkrav»,
    «Administrer låsing», «Se innstillinger», «Se endringer og sikkerhetskopier», «Åpne kunnskapsbasen» og «Lag
    illustrasjoner».
  - Manglende tilgang i Canvas og «ikke et Blueprint-emne» står som vanlig tekst på kortet. At kunnskapsbasen lagres
    lokalt på denne maskinen, står i beskrivelsen.
  - Kortet «Slik publiseres endringer» er fjernet. Forklaringen står i endringskøen og i hjelpen.
  - «Siste handlinger» ligger under verktøyene og viser innhold, hva som ble endret, status og tidspunkt, for eksempel
    «Lenketekst oppdatert · Publisert til Canvas». Det hentes fra det som er registrert med endringen: rettingene i
    den, ellers endringstypen. Uten slike opplysninger vises bare status.
  - «Backup og endringslogg» heter nå «Sikkerhetskopier og endringslogg».
- Hjelp: spørsmålstegnet i topplinjen og «Hjelp»-lenkene på sidene er fjernet. Hjelpen ligger i «Hjelp» i sidemenyen,
  også i menyen på små skjermer.
- **Profilen** ligger nederst i sidepanelet, under «Innstillinger» og «Hjelp», med navnet og en liten pil. Kontomenyen
  åpnes oppover og viser Canvas-adressen og «Canvas-tilkobling». Den kan brukes med tastatur: Escape lukker menyen og
  gir fokus tilbake. Topplinjen viser ikke lenger profilen.
- **Emnevelgeren:**
  - Emner kan markeres som favoritter med stjernen og vises da først. Favorittene lagres i EmneKlar; Canvas'
    egne favoritter endres ikke.
  - Du kan søke på emne-ID, tallet i Canvas-adressen (…/courses/547/…), eller lime inn hele adressen. ID-en står på
    hvert emne.
  - Finnes ikke emnet, sier listen hvilke emner den viser, og emnelisten kan hentes på nytt fra Canvas.
- KI-bildeassistenten bruker «Balansert» som standard kvalitet (tidligere «Maksimal kvalitet»).
- Hvis KI ikke kan brukes, sier meldingen hva som mangler: lagret nøkkel, men leverandøren er ikke slått på; slått på,
  men mangler nøkkel; eller ekstern KI er ikke tillatt. Før sto det «Ingen KI-leverandør er satt opp» også når nøkler var
  lagret. Når du lagrer en nøkkel, slås leverandøren på (den kan slås av igjen). Sending til ekstern KI krever fortsatt
  sin egen innstilling.
- **Emneoversikten** er lettere å lese:
  - Universell utforming viser «avvik» og «sannsynlige avvik» hver for seg. Resten står som «I tillegg 12 bør vurderes,
    8 til manuell kontroll og 1 forbedringsforslag». Hvert funn har én klasse, så tallene overlapper ikke.
  - Innholdskvalitet viser totalen med «hvorav» og hva resten er. Emnestruktur viser «bør vurderes» og
    «forbedringsforslag» hver for seg, med totalen under. Tallene formateres på norsk («1 110»).
  - «Anbefalt neste steg» fremhever én handling og viser to til. Resten ligger under «Se alle anbefalinger».
    Rekkefølgen følger klasse (avvik før sannsynlige avvik) og alvorlighet, ikke antall.
  - «Alvorlige UU-funn» er delt i «avvik med høy alvorlighet» og «sannsynlige avvik med høy alvorlighet bør
    kontrolleres». Knappene («Se alvorlige avvik», «Se døde lenker», «Se manuelle kontroller» …) åpner listen med
    samme utvalg og antall. Listen sier hvilket utvalg den viser, og har «Vis alle funn».
  - Funnlisten kan filtreres på alvorlighet og regel fra en lenke.
  - «Siste analyser og aktivitet» viser én post per publisert endring, med innhold, hva som ble endret, status og
    tidspunkt. Publiseringsjobben gjentas ikke. Analyser står i fortid («Hele emnet analysert»).
  - Tidspunktet for analysen står én gang øverst. Områder fra en eldre analyse eller fra flere analyser merkes. Innhold
    i emnet dateres med samme analyse.
- **Emneoversikten prioriterer tydeligere og er mer presis:**
  - Universell utforming har «Bekreftede avvik» som hovedtall og «Sannsynlige avvik» som et mindre tall under;
    Emnestruktur har «Bør vurderes» over «Forbedringsforslag». Døde lenker og utilgjengelige videoer er ulike problemer
    og står som likeverdige rader. Alle kort har samme oppbygning, med etikettene på linje.
  - Quiz-kortet viser «Mulige feil» og, hver for seg, «quizer med funn» og «spørsmål med funn» (fra funnene selv, i
    stedet for samlebetegnelsen «spørsmål og quizer berørt»).
  - Én navigasjon per kort: tittelen er lenken, med pil. «Vis detaljer» er en egen kontroll som åpner tekst i kortet –
    ikke lenger en knapp over en lenkeflate som dekker hele kortet.
  - Hvert kort har én kort linje om dekning og alder («Hele emnet · 6. nov. kl. 15.42», «Delanalyse (valgte moduler)
    · …», «Satt sammen av 3 analyser · nyeste 10. nov.»). Hvilke analyser resultatene er satt sammen av, står under
    «Vis detaljer».
  - Linjen øverst skiller «Siste delanalyse: …» fra «Hele emnet sist analysert …», sier hvilke områder analysen
    gjaldt (en full analyse av ett område er ikke «alle områder»), og sier fra når oversikten også bygger på eldre
    analyser. Oversikts-API-et gir derfor områdene for hver analyse og siste analyse av hele emnet.
  - Forklaringen av rekkefølgen på anbefalingene ligger bak «Hvordan prioriteres anbefalingene?». Prioriteringen er
    uendret.
  - «Siste analyser og aktivitet» viser høyst fem hendelser, med lenker til Jobbhistorikk og Endringslogg for resten.
    Kortene i nederste rad tilpasser høyden til innholdet, så det blir ikke tomrom under anbefalingene.
  - «Åpne funn per område» viser bekreftede avvik og «Bør vurderes» som standard; sannsynlige avvik (egen farge),
    forbedringsforslag og manuell kontroll kan velges i tillegg. Bekreftede og sannsynlige avvik slås aldri sammen,
    tabellen følger valgene, og diagrammet sier at det viser antall funn – ikke en samlet alvorlighetsgrad.
  - «Innhold i emnet» forklarer at «Upublisert innhold» allerede er med i tallene over og ikke skal legges sammen med
    dem.
- **Én analyseknapp, øverst til høyre, som følger siden:** «Analyser hele emnet» på Oversikt, «Analyser universell
  utforming», «Analyser innholdskvalitet», «Analyser emnestruktur» og «Analyser quizkvalitet» på sidene for hvert
  område. Fra en side for ett område analyseres bare det området (ingen «Full analyse» der); på Oversikt velger du
  områder som før. Sider uten egen analyse har ingen analyseknapp, og analyseknappene inne på sidene er fjernet –
  tomme sider viser til knappen øverst. Omfanget (hele emnet, moduler eller enkeltelementer) velges som før.
- **Analysen kjører i bakgrunnen:** når du starter den, lukkes dialogen og Analysestatus åpnes. Mens en analyse av
  emnet pågår, er analyseknappen deaktivert og viser samme status som panelet, uten animasjon – for eksempel
  «Analyserer innholdet · 124 av 380», på smale skjermer bare «124 av 380». Den beholder tastaturfokus.
  «Lagre og analyser siden på nytt» (medietype) er sperret i mellomtiden. «Detaljer» i panelet viser den fullstendige
  fremdriften med estimert tid.
- **Tidspunkt for resultatene:** mens en ny kontroll pågår, står det «Viser resultater fra 6. november kl. 15.42. Ny
  kontroll pågår.» (eller «Første kontroll pågår.»), og resultater og tidspunkt oppdateres sammen når kontrollen er
  ferdig. Blir den nye kontrollen ikke fullført, står det at den ikke ble fullført.
- Jobber som startes på en side (quizkontroll, spørsmålsbank, kunnskapsbase, bildeassistent, videoskanning,
  medietype), viser én statuslinje uten animasjon i stedet for et stort fremdriftsfelt; hele fremdriften står i
  Analysestatus.

### Fjernet
- **Lokale modeller er ute av oppsett og pakke:** `setup.bat` spør ikke lenger om lokale modeller for Emnets
  kunnskapsbase, og verken oppsett eller oppdatering laster ned eller installerer dem (`--rag`, `--no-rag` og
  `emneklar-extras.txt` er fjernet). De er ikke med i utgivelsespakken. Kunnskapsbasen bruker nøkkelordsøk og
  eksisterende teksting, og semantisk søk og transkripsjon kan fortsatt velges med en KI-leverandør. Innstillingene
  viser ikke lenger valg som krever lokale modeller, og meldingene ber ikke lenger om å kjøre `setup.bat` for å få
  dem. Støtten i programkoden er beholdt for utviklere som selv installerer `backend[rag]`.
- **Emneforside** – forsidebyggeren og menypunktet er erstattet av Emnedesign, som gir den eksisterende forsiden
  samme design som resten av emnet. Lokale forsideutkast (tabellen `homepage_drafts`) fjernes i migrering 0008;
  databasen kopieres til `backups\database` før migreringen. Sider som allerede er opprettet eller erstattet i
  Canvas, og endringsloggen og sikkerhetskopiene for dem, berøres ikke og kan fortsatt angres. Startsiden
  «Emneforside» blir «Emnedesign».
- **Dry run** – bryteren i toppmenyen, varselbanneret, innstillingen og kolonnen `change_log.dry_run` (migrering
  0005). Analyser og forhåndsvisninger har alltid vært skrivebeskyttet; det eksplisitte trinnet «Publiser til Canvas»
  er nå vernet mot utilsiktede endringer. Gamle logginnslag fra Dry run vises fortsatt.

### Rettet
- **Riktig melding ved feil metode (405):** en forespørsel med en metode adressen ikke støtter, ble vist som «Noe gikk
  galt i EmneKlar». Nå får den koden `method_not_allowed` og en saklig melding, og `Allow` sendes med. Ekte
  uventede feil er fortsatt `internal_error`.
- **CSP-kommentaren stemmer med verdien:** kommentaren sa `frame-ancestors 'none'`, mens policyen er `'self'` (EmneKlar
  viser egne sider i en ramme, for eksempel forhåndsvisningen i KI-bildeassistenten). Kommentaren er rettet, og en test
  kontrollerer at de strenge direktivene står og at kommentaren følger verdien. Hvorfor `style-src` fortsatt tillater
  inline-stil, står i koden og i trusselmodellen.
- **UU-regelsett og lovprofil bare på Universell utforming:** linjen under nøkkeltallene viste regelsett og regulatorisk
  profil også på Innholdskvalitet og Emnestruktur. Nå står de bare på Universell utforming; dato, omfang og antall
  ignorert, kontrollert, i endringskø og rettet står som før på alle områdesidene.
- **«Godkjenn alle klare» er ikke hovedhandling når ingenting er klart:** knappen var primær og tilgjengelig ved siden
  av «0 klare uten valg på denne siden», og tallet gjaldt bare siden mens knappen gjelder hele utvalget. Nå teller
  funnlisten de klare i hele utvalget. Er ingenting klart, er knappen deaktivert og ikke primær. Teksten ved knappen –
  som også er knappens beskrivelse for skjermlesere – forklarer at «klar» betyr at rettingen er bestemt av funnet, og at
  KI-forslag ikke er med. Hjelp er oppdatert.
- **Standardkilden for oppdateringer med andre bokstaver:** skrev du standardrepositoriet med andre store og små
  bokstaver (for eksempel «Oleandrw/emneklar»), ba EmneKlar om bekreftelse som for en annen kilde. GitHub skiller ikke
  på store og små bokstaver, så nå gjør heller ikke EmneKlar det – i skjemaet og på serveren. Et faktisk annet
  repository krever fortsatt bekreftelse.
- **Klassefilteret viser bare klasser med funn:** områdesidene viste alle fem klassene, også «Sannsynlig feil (0)» på
  Innholdskvalitet og «Feil (0)» på Emnestruktur. Nå vises bare klassene som har funn i området, pluss en klasse som er
  valgt – for eksempel via en lenke fra Oversikt – selv om den har 0 treff, så valget kan oppheves.
- **Evalueringen i Kunnskapsbasen bruker også det felles vernet:** utdragene som sendes til KI for å lage testspørsmål,
  gikk som rå tekst. Nå avgrenses de som data med den felles hjelperen, og systemprompten har den felles regelen. En
  test stopper nye KI-kall som sender emneinnhold uten hjelperen.
- **Felles vern mot promptinjeksjon:** bare KI-bildeassistenten avgrenset og vasket emneinnhold; de andre KI-kallene
  pakket rå tekst inn mellom `<<<` og `>>>`, og tekst i emnet kunne avslutte blokken selv. Nå bruker alle KI-kall som
  sender emneinnhold én felles hjelper (`core/ai/untrusted.py`): innholdet avgrenses og merkes som data, skilletegn i
  innholdet nøytraliseres, tekst som ligner instruksjoner til en KI merkes, og personopplysninger oppgaven ikke trenger
  fjernes der det passer. Gjelder alt-tekst, lenketekst, tabell- og iframe-titler, videotitler, lenkealternativer,
  Emnedesign, Kunnskapsbasen (svar, berikelse og bildebeskrivelser), quizvurdering, spørsmålsbanken og
  KI-bildeassistenten. Sjekken for injeksjonsforsøk, som lå ubrukt, brukes nå av hjelperen.
- **Ærlig tekst om automatisk innsetting:** kortet for KI-bildeassistenten, sideoverskriften, Emnedesign, README,
  Hjelp (Canvas-verktøy, steg 5 i KI-bildeassistenten og endringskøen), tomtilstanden på Oversikt og trusselmodellen
  lovet at du godkjenner bildene før de settes inn. Nå nevner de unntaket: «Automatisk innsetting», som du velger selv
  før kjøringen, setter inn bilder som består kvalitetskontrollen uten gjennomgang – fortsatt via endringskøen med
  sikkerhetskopi og angremulighet. Funksjonen er beholdt uendret.
- **Preferanser i Canvas-innstillinger:** hjelpeteksten under hver bryter rant rett inn i «På»/«Av» («PåGir
  studentene …»). Den står nå på egen linje med avstand, og er bryterens beskrivelse for skjermlesere.
- **«Avvik» bare om universell utforming:** klassene «Avvik» og «Sannsynlig avvik» (brudd på et suksesskriterium) ble
  også brukt om døde lenker i Innholdskvalitet og fasitfeil i Quiz. Utenfor universell utforming heter de nå «Feil» og
  «Sannsynlig feil», med forklaringer uten UU-krav – i funnlister, filtre, nøkkeltall, funndetaljen, quizvisningen,
  rapportene (HTML og CSV) og hjelpeteksten. Diagrammet på Oversikt, som viser alle områdene, sier «avvik og feil».
- **Døde lenker betyr det samme på Oversikt og under Lenker:** Oversikt talte døde lenker som funn (også lenker til
  innhold som ikke finnes i emnet), mens Lenker-fanen talte bare eksterne adresser med tilstanden «Fungerer ikke». Nå
  er en død lenke én adresse som er påvist død – ekstern eller intern – begge steder. Interne lenker til innhold som
  ikke finnes, vises under Lenker, merket «Intern lenke», med «Brukt i», «Endre lenke» og «Rett funnet» (uten
  «Sjekk på nytt» og KI-søk, som ikke gir mening for en intern adresse). «Se døde lenker» på Oversikt åpner
  Innholdskvalitet → Lenker med «Fungerer ikke» valgt – de samme radene som tallet.
- **Rapporter viser ikke lenger alle åpne funn som et rødt hovedtall:** tallet summerte alle klasser, også
  forbedringsforslag og manuelle kontroller. Nå er bekreftede avvik og feil hovedtallet (rødt bare når det finnes
  noen), sannsynlige et mindre tall under, og antall åpne funn i alt står som vanlig tekst – som på Oversikt.
- **Analysestatus teller det samme som sidene:** det ferdige resultatet av en analyse («… · 85 funn») talte hvert
  utkast, også når samme adresse sto flere ganger på én side og ble lagret som ett funn. Nå kommer tallene i
  Analysestatus, jobbresultatet og analysekjøringen fra de lagrede funnene – unike og åpne, som på sidene og i
  Rapporter. «Funn så langt» underveis teller fortsatt etter hvert. Et fingeravtrykk lagres dessuten bare én gang per
  kjøring, også når to deler av analysen finner det samme.
- **«Bør vurderes» i diagrammene har nok kontrast:** fargen var 2,7:1 mot hvitt i lyst tema og er mørknet til 3,6:1
  (3,3:1 mot sidebakgrunnen). Mørkt tema hadde allerede 5,4:1 og er uendret. En test kontrollerer at alle
  diagramseriene har minst 3:1 mot kortflaten i begge temaer. Tallfargene i statuskortene er ikke endret.
- **Bekreftede og sannsynlige avvik er skilt på områdesidene:** det første nøkkeltallet på Universell utforming,
  Innholdskvalitet og Emnestruktur slo sammen avvik og sannsynlige avvik til ett tall («Avvik / sannsynlige avvik»).
  Nå er bekreftede avvik hovedtallet og sannsynlige avvik et mindre tall under, som på Oversikt. Innholdskvalitet sier
  «Bekreftede feil» (området har ingen sannsynlige feil), og Emnestruktur, der reglene aldri gir avvik eller feil,
  viser ikke kortet. Hvilke klasser et område bruker, kommer fra regelregisteret (`classifications` i funnlisten).
- **Oppdateringskilden kan ikke byttes i det stille:** feltet «GitHub-repository for oppdateringer» viser standardkilden
  (repositoriet EmneKlar ble installert fra). Et annet repository gir en advarsel om at oppdateringer da hentes fra en
  annen kilde, og må bekreftes med en avkrysning før det kan lagres. API-et krever den samme bekreftelsen. Tomt felt
  betyr fortsatt standardkilden.
- **Publisering krever godkjenning:** «Publiser til Canvas» (API-et `/api/changes/apply`) godtar bare godkjente
  endringer. En endring som bare ligger i køen, eller som feilet sist, avvises med `change_state_invalid` og en
  forklaring, og ingenting skrives til Canvas. En feilet endring må godkjennes på nytt før et nytt forsøk (det gjør
  «Prøv igjen» i endringskøen). Kontrollen gjentas rett før hver skriving. Automatisk innsetting i
  bildeassistenten godkjenner endringene selv før publisering og virker som før.
- **En avbrutt analyse skjulte tidligere funn:** innhold analysen aldri rakk å kontrollere, regnet som kontrollert, så
  funn fra forrige analyse forsvant. Nå gjelder en avbrutt analyse bare det den faktisk kontrollerte. Lenkelisten
  viser den siste fullførte lenkekontrollen i stedet for en avbrutt og ufullstendig en, og lenker du har sjekket på
  nytt én og én, blandes ikke med resultatene fra en ny kontroll.
- **Feil Canvas-token logget deg ut av EmneKlar:** Canvas' avvisning av et token (HTTP 401) ble tolket som en utløpt
  EmneKlar-økt og viste «Økten er ikke gyldig». Nå vises feilen ved tokenfeltet; bare EmneKlars egen øktkontroll logger
  ut.
- **Fokus etter dialoger:** når en dialog lukkes ved at den fjernes (ikke bare skjules), går fokus nå tilbake til
  knappen som åpnet den, i stedet for til toppen av siden.
- **Feilaktig «Video i Canvas uten tekstspor»:** emnets medieliste viser ofte ingen tekstspor selv for tekstede
  videoer, fordi Canvas lagrer sporene på mediefilen. Teksting leses nå fra filen (også via `media_entry_id` i
  emnets filer); ukjent status vises som manuell kontroll, aldri som manglende teksting.
- **Feilaktig «Video uten tekstspor (track)»:** Canvas' egne medieopptak og videofiler i `<video>`-elementer ble
  vurdert som vanlige HTML5-videoer. De vurderes nå som Canvas-medier.
- **YouTube-teksting kontrolleres** (regelsett 2026.11.1) i stedet for at hver video ble «Teksting kan ikke
  verifiseres automatisk»: teksting fra den som lastet opp gir ikke funn, bare automatisk teksting gir «Bør
  vurderes», ingen teksting gir «Sannsynlig avvik». Bare video-id-en sendes; høyst 400 nye videoer per analyse,
  hurtigbuffer i en uke, og kontrollen stopper høflig hvis YouTube avviser forespørsler.
- Tomme lenker kan få tekst og riktig adresse i stedet for bare å fjernes; ugyldige adresser (for eksempel tekst
  limt inn i adressefeltet) forklares og kan ikke lagres. Blueprint-merknaden i selve Blueprint-emnet sier nå at
  innholdet er låst i de tilknyttede emnene, ikke her.
- **Lydopptak fikk feil regel** («Video i Canvas uten tekstspor», WCAG 1.2.2, «last opp teksting»). Mediekontrollen
  skiller nå mellom typer (regelsett 2026.11.2, kontrollert mot Uutilsynets veiledning om 1.2.1 og W3C Understanding
  1.2.2):
  - *Rene lydopptak* kontrolleres mot 1.2.1: «Kontroller tekstalternativ til lydopptak» (manuell kontroll, moderat).
    Manglende tekstspor alene gir ikke «Sannsynlig avvik» eller «Alvorlig». Tekst eller lenker som ligner en
    transkripsjon, vises som «mulig tekstalternativ», men godtas aldri automatisk.
  - *Video med lyd* kontrolleres mot 1.2.2 som før. En separat transkripsjon erstatter ikke teksting.
  - *Video uten lyd* gir ikke tekstingsfunn, men «Kontroller alternativ til video uten lyd» (1.2.1).
  - *Ukjent medietype* gir manuell kontroll med forklaring av hva som er usikkert, ikke automatisk «video». Typen
    hentes fra Canvas' medieobjekt og fil før merkingen i koden. Et `<video>`-element alene er ikke bevis på bilde.
  - Påstanden «er opptaket uten tale, gjelder ikke kravet» er fjernet. Andre betydningsfulle lyder kan kreve teksting.
- **Bekreft etter kontroll:** manuelle mediekontroller kan bekreftes (for eksempel «Transkripsjonen finnes på siden
  eller via en tydelig lenke», eller unntaket «Opptaket er et tydelig merket alternativ til tekst på siden»). Funnet
  får status «Kontrollert». Statusen gjelder også ved nye analyser og vises i rapportene under «Kontrollert manuelt»
  (i CSV: ny siste kolonne «Bekreftet av lærer»).
  Medietypen kan angis («Lydopptak», «Video med lyd», «Video uten lyd»), og siden analyseres da på nytt med riktig
  krav. Migrering 0006 (`media_assessments`, `finding_decisions.reason`).

### Sikkerhet
- **Hash-låste pakker i Windows-pakken:** kjøretiden bygges fra en Python-nedlasting med låst SHA-256
  (`packaging/runtime.json`) og fra `packaging/runtime-win-amd64.txt`, der hver pakke har nøyaktig versjon og
  SHA-256 for den ene filen som installeres (`pip --require-hashes`, ingen bygging fra kildekode). Bygget er
  reproduserbart: to bygg av de samme låste filene gir samme zip-fil, bit for bit. Kjøretiden er isolert fra
  miljøvariabler, registeret og brukerens egne Python-pakker. `backend/constraints.txt` (kildeinstallasjon
  og CI) låser fortsatt bare versjoner – se restrisiko i `docs/THREAT_MODEL.md`.
- **Utviklerverktøy oppdatert:** `zod` 4.6.5 → 4.6.7 (høy alvorlighet, via eslint-plugin-react-hooks) og
  `typescript-eslint` 8.72.1 → 8.72.2, innenfor dagens versjonsintervaller (bare `package-lock.json`). `npm audit
  --omit=dev` og `pip-audit` finner ingen sårbarheter. Gjenstår: 10 moderate funn i `minimatch` via eslint og
  typescript-eslint, som bare kan rettes med et hovedversjonshopp – se trusselmodellens restrisiko.

## [0.1.0] – 2026-11-04

### Lagt til
- Én lokal applikasjon (FastAPI + React) for Windows med `setup.bat`, `start.bat` og `update.bat`. Tjenesten
  lytter bare på 127.0.0.1; innlogging skjer med engangslenke, og data lagres i `%LOCALAPPDATA%\EmneKlar-Claude`.
- Oppsettveiviser i ni steg med test av Canvas-tilkobling, identitet, tilganger, standardemne og regulatorisk
  profil. Canvas-token og KI-nøkler lagres bare i Windows Legitimasjonsbehandling.
- Global emnevelger, global analyse med normalisert øyeblikksbilde av emnet, ekte fremdrift (prosent, X av Y,
  per innholdstype, funn underveis, estimert tid med intervall), pause, avbryt og kjøring i bakgrunnen.
- Universell utforming: versjonert regelregister og regulatoriske profiler, kontroller av bilder, overskrifter,
  lenker, tabeller, lister, språk, kontrast, innebygd innhold, video og dokumenter, med forklaring, kriterium,
  juridisk status, testmetode og forslag til retting.
- Innholdskvalitet: SSRF-beskyttet lenkesjekk med seks tilstander, interne Canvas-lenker, medier, HTML-hygiene
  og konservativ opprydding med diff.
- Emnestruktur: veiledende forslag med begrunnelse, belegg og sikkerhet, og studentreisen.
- Quizassistent for klassiske quizer: kvalitetssjekk, kildeforankret KI-vurdering, KI-spørsmålsbank med
  kontrollerte kildesitater, dekningsanalyse og quizbygger med forhåndsinnstillinger og «X av Y».
- Emneforside: tre moduser, fire stiler, elleve seksjoner, Canvas-trygg HTML, forhåndsvisning på PC, nettbrett og
  mobil, «Opprett som ny side», «Erstatt eksisterende forside» med sikkerhetskopi og «Bruk som forside».
- Canvas-verktøy: automatiske modulkrav, Blueprint-låsing, analyse av Canvas-innstillinger og backup/endringslogg
  med angring.
- Felles endringskø med forhåndsvisning, godkjenning, konfliktsjekk, sikkerhetskopi, logg og angring, og global
  Dry run som blokkerer alle skrivende kall til Canvas.
- Valgfrie KI-leverandører (OpenAI, Anthropic, Azure OpenAI, lokal OpenAI-kompatibel), modellregister,
  kostnads- og kvalitetsbevisst modellvalg med reserve, og personvern med samtykke før sending.
- Rapporter i HTML (kan lagres som PDF fra nettleseren) og CSV.
- Innstillinger i åtte deler, funksjonsflagg, hjelpesenter og oppdateringssjekk mot GitHub Releases.
- Oppdatering i ti steg (`update.bat` eller fra Innstillinger) med sikkerhetskopi av databasen, helsesjekk og
  tilbakerulling ved feil. Nye hovedversjoner installeres bare etter bekreftelse. Utgivelsespakker (zip med
  SHA-256) bygges av GitHub Actions. Se `docs/UPDATING.md`.
- Automatiske tester: backend (pytest), frontend (Vitest + axe) og ende-til-ende (Playwright + axe).
- Canvas-verktøy → **Emnets kunnskapsbase**: en lokal kunnskapsbase av emnet (hele emnet eller valgte moduler) med søk og
  KI-svar med klikkbare kildehenvisninger. Leser bare lærerprodusert innhold (sider, oppgave- og quizbeskrivelser,
  emneplan, lærerens diskusjonsinnlegg og filer lastet opp av lærere) – aldri innleveringer, karakterer, meldinger
  eller studentinnlegg. Tekst og dokumenter (PDF, DOCX, PPTX med notater, XLSX, ODT/ODP/ODS, RTF, CSV, TXT,
  Markdown, HTML) gjøres om til strukturert Markdown og deles opp etter overskrifter; tabeller og lysbilder blir egne
  utdrag. Hybridsøk med BM25 og vektorsøk slått sammen med Reciprocal Rank Fusion, rerangering, filtrering på modul
  og kildetype, og en feilsøkingsvisning med poeng før og etter rerangering. Estimat før bygging, bakgrunnsjobb med
  fremdrift, pause, avbryt og gjenopptak, og liste over hoppede elementer. Valgfrie lokale modeller (BGE-M3 og
  bge-reranker-v2-m3) installeres med `setup.bat`, som spør om dem under oppsettet; uten dem brukes nøkkelordsøk.
- Emnets kunnskapsbase → video og lyd: eksisterende teksting brukes først (Canvas-mediespor, undertekstfiler og YouTube-teksting),
  ellers transkriberes Canvas-video og opplastede lyd- og videofiler lokalt med NB-Whisper (modellstørrelse etter
  GPU/CPU, Whisper large-v3 for annet språk). Transkripsjoner bufres på filens SHA-256, deles i biter på 60–120
  sekunder med overlapp og får tidsstempel i kildehenvisningen. YouTube- og Vimeo-lenker åpnes på riktig tidspunkt.
  Bare medier som lærerens innhold peker på, tas med. Panopto, Kaltura og andre LTI-videoer vises som hoppet over med
  forklaring.
- Emnets kunnskapsbase → bilder: bilder på sider, bildefiler og bilder i Office-dokumenter beskrives av bildemodellen i KI-laget
  (Claude-API eller lokal bildemodell), med sidetittel, overskrift, tekst rundt bildet og alt-tekst som ekstra input.
  Beskrivelsen gjengir tekst i bildet og forklarer diagrammer og figurer, og lagres som eget utdrag med lenke til siden.
  Pynt filtreres bort før noe sendes (dekorative bilder, ikoner, logoer, bannere, svært små og ensfargede bilder, SVG og
  duplikater med perceptuell hash), og beskrivelsene bufres på bildets SHA-256. Valgfritt: nøkkelbilder ved
  sceneskifte i video, koblet til tidspunktet. Bildene leses i de isolerte parserprosessene.
- Emnets kunnskapsbase → kontekstuell berikelse (valgfritt, krever KI): én til to setninger foran hvert utdrag som plasserer det i
  dokumentet og modulen, med prompt caching per dokument og buffer. **Kvalitet**: etter hver bygging lages 15–20
  testspørsmål (av KI når det er tillatt, ellers av utdragenes særpregede ord), og recall@5, MRR og en helsescore
  lagres og vises sammen med hvert spørsmål. **Eksport**: ZIP med `chunks.jsonl` (metadata og vektorer), manifest og
  formatbeskrivelse, eller kunnskapsbasen som Word, PDF, Markdown eller ren tekst. Knappen «Oppdater indeks»
  behandler bare nye og endrede elementer og fjerner slettede.
- Emnets kunnskapsbase → transkripsjon via KI-leverandør: video og lyd uten teksting kan transkriberes av OpenAI
  (gpt-transcribe, gpt-4o-mini-transcribe eller whisper-1), Azure OpenAI eller en egen OpenAI-kompatibel server i
  stedet for lokalt med NB-Whisper (Emnets kunnskapsbase → Innstillinger → Transkripsjon: lokalt, via KI-leverandør eller av).
  Bare lyden sendes, i biter på 60–120 sekunder kuttet ved pauser (stille biter sendes ikke), og bare etter at
  estimatet har vist antall minutter, modell og hva som sendes, og du har godtatt det. Tidsstemplene følger bitene,
  også når modellen ikke gir tidsstempler, og teksten fra forrige bit sendes med som hint så navn og fagord skrives
  likt. Videotittel og annet innhold fra emnet sendes ikke.
  Transkripsjonene bufres på filens SHA-256 (felles med lokal transkripsjon), og hvert kall logges under KI-bruk.
  Modellene står i en katalog (`core/ai/transcription_models.json`); en egen modell-id kan skrives inn.
  Elementer som venter på samtykke, modeller eller en innstilling, merkes «Prøves igjen ved neste oppdatering» og
  tas med av «Oppdater indeks» når det er på plass. `av` (PyAV, FFmpeg innebygd) er nå en fast avhengighet for å
  hente ut lyden.
- Emnets kunnskapsbase → Vimeo-teksting: innebygde Vimeo-videoer og Vimeo-lenker i moduler tas med når videoen har teksting.
  Tekstingen hentes slik den innebygde Vimeo-avspilleren gjør det (uoffisielt; bare video-id-en og eventuelt
  tilgangskoden fra en skjult lenke sendes, aldri noe fra emnet), med samme språkrekkefølge som for YouTube og
  opplastet teksting før automatisk. Kildehenvisningen åpner videoen på riktig tidspunkt, også for skjulte lenker.
  Videoer som bare kan vises på bestemte nettsteder eller er passordbeskyttet, vises som hoppet over med forklaring.
  Kan slås av under Emnets kunnskapsbase → Innstillinger (på som standard). Estimatet viser hva som sendes til YouTube og Vimeo.
- Innholdskvalitet → Media: «Standardiser videoavspillere» for YouTube. Finner innebygde videoer, forklarer avvik
  fra én responsiv og Canvas-trygg standard (16:9, maks bredde, sentrert, `allowfullscreen`, `loading="lazy"`),
  foreslår beskrivende title med synlig kilde (eksisterende title, YouTube-metadata, Canvas-kontekst, KI-forslag på
  forespørsel eller manuelt), forhåndsviser før og etter på PC, nettbrett og mobil og legger godkjente endringer i
  endringskøen – én og én eller alle kompatible videoer. Video-ID og parametere beholdes, og bare videoens egen kode
  endres.

### Endret
- Nytt visuelt uttrykk i hele programmet: mørk marineblå meny, lys og lett varm bakgrunn, store hvite kort,
  pastellfarger per område (UU lilla, innholdskvalitet blå, emnestruktur grønn, quiz oransje), større og tydeligere
  typografi (Inter, pakket med appen) og et samlet designsystem med tokens og gjenbrukbare komponenter
  (`docs/DESIGN_SYSTEM.md`). Bare utseendet er endret – funksjonene er de samme.
- Oversikt er bygget om med store statuskort per område, anbefalte steg som handlingsrader, siste aktivitet, et
  tilgjengelig diagram over åpne funn per område (med tabellvisning) og innholdet i emnet som ikonfliser.
- Funnlistene har nøkkeltallkort, filterpiller for kategori og klassifisering og ryddigere rader. Canvas-verktøy har
  siste handlinger, Dry run-status og verktøykort. Quizassistent og Rapporter har nøkkeltall øverst.
- Avhengigheter oppdatert samlet og testet sammen (erstatter Dependabot-PR-ene #2–#11): pydantic 2.14.2 (med
  pydantic-core 2.50.2, som Dependabot-oppdateringen manglet), starlette 1.10.0, alembic 1.20.1, msgpack 1.2.4 og
  pytest 9.2.0 i backend; react-router 8.5.1, @tanstack/react-query 5.105.3, vite 8.3.5, @playwright/test 1.64.1
  og @axe-core/playwright 4.14.0 i frontend.
- Verktøyet heter nå **Emnets kunnskapsbase** i stedet for Emne-RAG – i menyen, på siden, i KI-oppgavene, jobbene
  og meldingene. Adressen (`/canvas-verktoy/emne-rag`) er uendret.
- Ett oppsett for hele programmet: `setup.bat` spør én gang om de valgfrie lokale modellene for Emnets kunnskapsbase
  (standard nei; ingen spørsmål uten konsoll, med `--no-pause` eller når valget er gjort før). `setup-emne-rag.bat` er
  fjernet; `setup.bat --rag` velger modellene uten å spørre, og `--no-rag` hopper over spørsmålet.
- Lenken «← Canvas-verktøy» øverst på verktøysidene (Emnets kunnskapsbase, Automatiske modulkrav, Blueprint-låsing,
  Canvas-innstillinger, Backup og endringslogg) er fjernet. Den gjentok menyen til venstre, der «Canvas-verktøy»
  allerede er markert.
- Emnets kunnskapsbase er roligere og bruker ordet «kunnskapsbase» i stedet for «indeks». Hovedknappen heter **Opprett
  kunnskapsbase** (eller **Oppdater kunnskapsbasen**) og er større, og den første fanen heter «Kunnskapsbase» både
  før og etter. I stedet for en tom indeksboks står statusen «Ingen kunnskapsbase opprettet ennå» rett under
  sidetittelen; kortet over fanene heter «Status». Kildene vises som en liste («Canvas-tekst · Dokumenter · Video og
  lyd · Bilder») med de faktiske valgene og merket «Tilpasset» når de avviker fra standard. Hjelpetekstene og
  forklaringen under hovedknappen er større og har sterkere kontrast. Den blå boksen øverst og teksten nederst er erstattet av én kort
  forklaring ved hovedknappen («Kunnskapsbasen lagres på denne maskinen. Du godkjenner eventuell nedlasting og
  sending til KI først.») med detaljer bak «Les mer» – også om søk og
  transkripsjon skjer lokalt eller hos KI-leverandøren du har valgt (den gamle teksten sa alltid «lokalt»).
- Emnets kunnskapsbase → «Opprett kunnskapsbase» er forenklet: hovedsiden har omfang (hele emnet eller valgte moduler), en kort
  oppsummering av kildene («Inkluderer Canvas-tekst, dokumenter, video, lyd og bilder.»), **Tilpass kilder** og
  hovedknappen. Alle kildetyper er på som standard (bilder bare når KI er satt opp). «Tilpass kilder» åpner et
  sidepanel med kilder og filtyper, upublisert innhold og en **Avansert**-del med KI-tilleggene (kontekstuell
  berikelse, nøkkelbilder) og valg av transkriberingstjeneste. Endrede valg vises i oppsummeringen («Tilpassede
  kilder · Video/lyd og bilder er utelatt.»). Panelet er gjort lettere: «Avansert» er lukket som standard; filtyper
  vises bare med «Dokumenter», transkribering og nøkkelbilder bare med «Video og lyd», og leverandør, modell, språk
  (nedtrekksmeny med «Oppdag automatisk») og personvernboksen bare ved ekstern tjeneste. Hvert valg har én kort
  forklaring, og detaljene ligger bak «Les mer». Transkribering heter *På denne maskinen*, *Ekstern KI-tjeneste* og
  *Bare eksisterende undertekster*, og er merket «Gjelder alle emner». «Bilder» heter nå «Bildebeskrivelser med
  KI» (alt-tekst er alltid med), og alt som kan koste penger, er merket «Kan koste ekstra». Knappene heter
  **Lagre valg** (kildene lagres for emnet i nettleseren, transkriberingsvalget for alle emner) og **Tilbakestill
  kilder** (påvirker bare kildene, filtypene og upublisert innhold). Hovedknappen beregner estimatet først og viser det bare når noe må godkjennes (nedlasting, sending
  til KI, upublisert innhold) eller ingenting ble funnet; ellers starter byggingen med en gang.
- Kontrollen av innebygd innhold (Universell utforming) og videostandardiseringen bruker samme liste over generelle
  titler. «YouTube video», «Embedded video» og titler med kolon eller punktum til slutt regnes nå også som generelle.

### Rettet
- EmneKlar startet ikke når et annet program med samme navn brukte `%LOCALAPPDATA%\EmneKlar` («no such table:
  jobs»). EmneKlar har nå egen datamappe (`%LOCALAPPDATA%\EmneKlar-Claude`), egen oppføring i Windows
  Legitimasjonsbehandling, en innloggingskapsel per port og standardport 8770. En database som tilhører et annet
  program, blir aldri åpnet for skriving – EmneKlar forklarer i stedet hva som er galt.
- Emnets kunnskapsbase: når samme bilde står flere steder, beskrives nå alltid det første (i sidens rekkefølge),
  med alt-teksten og teksten rundt det. Før avhang det av hvilken nedlasting som ble ferdig først.
- Fanerader (for eksempel i Emnets kunnskapsbase) viste et lite loddrett rullefelt helt til høyre på Windows. Streken under
  aktiv fane stakk én piksel ut av raden; nå ruller raden bare sideveis, og bare på smale skjermer.
- Emnets kunnskapsbase: et nytt forsøk som feilet eller måtte vente (for eksempel fordi YouTube blokkerte), erstattet innhold som
  allerede var indeksert med ingenting. Nå beholdes forrige versjon, og elementet prøves igjen ved neste oppdatering.
  Hentet YouTube- og Vimeo-teksting bufres lokalt i 30 dager, så oppdateringer og nybygging ikke spør på nytt.
  Forespørslene spres med litt pause, og blokkerer YouTube (`IpBlocked`), spør EmneKlar ikke mer i den byggingen –
  resten prøves igjen senere med en forklaring. Meldingen etter byggingen sier hvor mange elementer som ble beholdt.
- Emnets kunnskapsbase: YouTube-teksting virket bare med de lokale modellene installert, og ellers sto det misvisende «Fant
  ingen teksting» for hver YouTube-video. `youtube-transcript-api` (liten, ren Python) er nå en fast avhengighet, så
  `update.bat` installerer den. Finnes ikke teksting på norsk eller engelsk, brukes tekstingen videoen har på et
  annet språk. Grunnen vises når tekstingen mangler (ingen teksting, slettet eller privat video, aldersgrense,
  avvist av YouTube); avviste forespørsler prøves igjen ved neste oppdatering. YouTube- og Vimeo-videoer uten
  teksting prøves også igjen ved hver «Oppdater indeks», siden teksting kan legges til der uten at noe endres i Canvas.
- Emnets kunnskapsbase: upublisert innhold forsvant ut av estimatet uten forklaring, slik at for eksempel et Blueprint-emne der
  ingenting er publisert ennå, ga «Fant ikke noe innhold». Nå tas alt i modulene du velger under «Valgte moduler»
  med, publisert eller ikke, og estimatet sier hvor mange upubliserte elementer som er med. For hele emnet trengs
  fortsatt «Ta med upubliserte elementer»; det som holdes utenfor, telles og står i listen over elementer som ikke
  blir med. Upubliserte moduler er merket i modulvalget, «Bygg indeks» er sperret når estimatet ikke fant noe, og
  loggen viser hvor mye EmneKlar fikk fra hver Canvas-liste.
- Lange stier og adresser (for eksempel datamappen under *Innstillinger → Sikkerhet og personvern*) brytes nå over
  flere linjer i stedet for å gi sideveis rulling på mobil.
- Automatiske modulkrav: trykket man «Forhåndsvis» før kravene per elementtype var lastet, ble forhåndsvisningen
  laget uten krav og aldri vist. Knappen venter nå til valgene er lastet, og viser en feilmelding hvis de ikke kan
  hentes.

### Sikkerhet
- Oppdaterte avhengigheter med kjente sårbarheter: certifi 2026.10.19, pypdf 6.21.4, opentelemetry-api 1.45.1 og
  filelock 4.2.1.
