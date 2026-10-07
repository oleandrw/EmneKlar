# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.
Formatet følger [Keep a Changelog](https://keepachangelog.com/no/1.1.0/), og prosjektet bruker
[semantisk versjonering](https://semver.org/lang/no/).

## [Unreleased]

### Lagt til
- Innholdskvalitet → Media: «Standardiser videoavspillere» for YouTube. Finner innebygde videoer, forklarer avvik
  fra én responsiv og Canvas-trygg standard (16:9, maks bredde, sentrert, `allowfullscreen`, `loading="lazy"`),
  foreslår beskrivende title med synlig kilde (eksisterende title, YouTube-metadata, Canvas-kontekst, KI-forslag på
  forespørsel eller manuelt), forhåndsviser før og etter på PC, nettbrett og mobil og legger godkjente endringer i
  endringskøen – én og én eller alle kompatible videoer. Video-ID og parametere beholdes, og bare videoens egen kode
  endres.

### Endret
- Kontrollen av innebygd innhold (Universell utforming) og videostandardiseringen bruker samme liste over generelle
  titler. «YouTube video», «Embedded video» og titler med kolon eller punktum til slutt regnes nå også som generelle.

## [0.1.0] – under utvikling

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

### Endret
- Nytt visuelt uttrykk i hele programmet: mørk marineblå meny, lys og lett varm bakgrunn, store hvite kort,
  pastellfarger per område (UU lilla, innholdskvalitet blå, emnestruktur grønn, quiz oransje), større og tydeligere
  typografi (Inter, pakket med appen) og et samlet designsystem med tokens og gjenbrukbare komponenter
  (`docs/DESIGN_SYSTEM.md`). Bare utseendet er endret – funksjonene er de samme.
- Oversikt er bygget om med store statuskort per område, anbefalte steg som handlingsrader, siste aktivitet, et
  tilgjengelig diagram over åpne funn per område (med tabellvisning) og innholdet i emnet som ikonfliser.
- Funnlistene har nøkkeltallkort, filterpiller for kategori og klassifisering og ryddigere rader. Canvas-verktøy har
  siste handlinger, Dry run-status og verktøykort. Quizassistent og Rapporter har nøkkeltall øverst.

### Rettet
- EmneKlar startet ikke når et annet program med samme navn brukte `%LOCALAPPDATA%\EmneKlar` («no such table:
  jobs»). EmneKlar har nå egen datamappe (`%LOCALAPPDATA%\EmneKlar-Claude`), egen oppføring i Windows
  Legitimasjonsbehandling, en innloggingskapsel per port og standardport 8770. En database som tilhører et annet
  program, blir aldri åpnet for skriving – EmneKlar forklarer i stedet hva som er galt.
