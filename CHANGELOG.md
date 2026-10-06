# Endringslogg

Alle merkbare endringer i EmneKlar dokumenteres her.
Formatet følger [Keep a Changelog](https://keepachangelog.com/no/1.1.0/), og prosjektet bruker
[semantisk versjonering](https://semver.org/lang/no/).

## [Unreleased]

## [0.1.0] – under utvikling

### Lagt til
- Én lokal applikasjon (FastAPI + React) for Windows med `setup.bat`, `start.bat` og `update.bat`. Tjenesten
  lytter bare på 127.0.0.1; innlogging skjer med engangslenke, og data lagres i `%LOCALAPPDATA%\EmneKlar`.
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
