# Trusselmodell

**Hva beskyttes:** Canvas API-token (gir lærerens fulle tilgang i Canvas), KI-nøkler, emneinnhold, integriteten
til Canvas-emner (ingen utilsiktede endringer), lokale data (database, sikkerhetskopier, rapporter).

**Aktører:** ondsinnede nettsider i lærerens nettleser, ondsinnet/kompromittert innhold i Canvas (HTML, filer,
lenker), eksterne nettsteder som lenkesjekken besøker, andre lokale brukere, kompromitterte avhengigheter,
KI-leverandører (dataminimering), utilsiktede feil fra brukeren eller fra EmneKlar selv.

| # | Trussel | Tiltak | Test |
|---|---------|--------|------|
| 1 | **Lekkasje av Canvas-token** | Lagres kun i Windows Credential Manager (`keyring`). Aldri i database, innstillinger, logg, nettleser eller API-svar (API svarer bare «konfigurert ja/nei»). Token sendes bare til konfigurert Canvas-opprinnelse – aldri ved omdirigering eller paginering til annen vert. | `test_foundation`, `test_canvas_client` |
| 2 | **KI-nøkler** | Samme som 1, én oppføring per leverandør. Nøkler brukes bare av backend. | `test_ai` |
| 3 | **Hemmeligheter i logger** | `RedactingFilter` på alle loggere (mønstre + eksakte verdier), httpx-logging av, ingen tilgangslogg (engangslenker i URL). | `test_foundation` |
| 4 | **Lokal tjeneste eksponert** | Binder bare til 127.0.0.1 (konfig nekter annet). Host-sjekk mot DNS-rebinding. Øktcookie HttpOnly + SameSite=Strict fra engangslenke. CSRF-token + Origin-sjekk på alle endrende kall. CORS-preflight avvises alltid. Kontrollkanal (`/control/*`) krever instanshemmelighet fra brukerens egen datamappe og avviser nettleserforespørsler (Origin). | `test_web_security` |
| 5 | **XSS fra Canvas-innhold** | Canvas-HTML settes aldri inn i appens DOM (ESLint forbyr `dangerouslySetInnerHTML`). Forhåndsvisning skjer i `<iframe sandbox="">` (ingen skript, egen opprinnelse) etter sanering på serveren (`nh3`). Streng CSP (`script-src 'self'`). | `test_change_engine`, `test_homepage_builder`, ESLint |
| 6 | **Uklarert Canvas-HTML i analyse** | Parses med BeautifulSoup (ingen kjøring), størrelsesgrenser per objekt. | `test_accessibility_checks` |
| 7 | **SSRF via lenkesjekk** | Bare http/https, port 80/443, ingen brukernavn i URL. Interne vertsnavn (localhost, *.local, …) og private/lenkelokale/metadata-adresser (127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7, fe80::/10, IPv4-mappede m.m.) avvises. Sjekk skjer ved tilkobling (mot DNS-rebinding), omdirigeringer følges manuelt og valideres for hvert hopp. Ingen informasjonskapsler, ingen proxy fra miljøet, ingen token. | `test_content_quality` |
| 8 | **Omdirigeringer i lenkesjekk** | Maks 5 hopp, hvert hopp valideres; omdirigering til innlogging klassifiseres som AUTH_REQUIRED. | `test_content_quality` |
| 9 | **Lokale filer** | `file:`, `data:`, `javascript:` m.m. sjekkes aldri. | `test_content_quality` |
| 10 | **Dokumentparsere (PDF/Office)** | Størrelsesgrense før nedlasting, ZIP-vern (antall, størrelse, komprimeringsgrad, krypterte deler), `defusedxml`, parsing i isolerte arbeidsprosesser med tidsgrense og minnegrense (Windows Job Object). JSON-protokoll, ikke pickle. | `test_documents` |
| 11 | **Stitraversering / ondsinnede filnavn** | Filer fra Canvas lagres med tilfeldige navn; rapporter og sikkerhetskopier hentes via database-id, aldri via sti fra klienten; filnavn til nedlasting saneres. | `test_reports`, `test_change_engine` |
| 12 | **Utilsiktede endringer i Canvas** | Skrivevern i `CanvasClient` (krever `WritePermit` fra endringsmotoren). Dry run blokkerer alle skrivende kall. Konfliktsjekk før skriving, sikkerhetskopi, endringslogg. Høyrisikoendringer krever eksplisitt bekreftelse. | `test_change_engine` |
| 13 | **KI-datalekkasje** | Ekstern KI av som standard; oppsummering av nyttelast før sending; studentinnleveringer, karakterer, meldinger og unødvendige identitetsdata hentes aldri; logger lagrer bare metadata om forespørsler. | `test_ai`, `test_quiz_assistant`, `test_homepage_builder` |
| 14 | **Promptinjeksjon i emneinnhold** | Emneinnhold sendes som data (avgrenset), modellen får ingen verktøy, svar valideres mot skjema og kildesitater kontrolleres mot kildeteksten. KI-forslag blir aldri brukt uten godkjenning. | `test_quiz_assistant` |
| 15 | **Sårbare avhengigheter** | `pip-audit` og `npm audit` i CI, Dependabot, låste versjonsintervaller. | CI |
| 16 | **Andre lokale brukere** | Data i `%LOCALAPPDATA%` (per bruker), hemmeligheter i brukerens nøkkelring. Andre prosesser som kjører som *samme* bruker regnes som tillitsverdige (de kan uansett lese nøkkelringen). | – |
| 17 | **Oppdatering** | Oppdatering henter fra konfigurert GitHub-repo (git) eller release-arkiv med SHA-256-kontroll; sikkerhetskopi av data før migrering; tilbakerulling ved feil; større versjonshopp krever bekreftelse. | `test_update_script`, `test_settings_updates` |
| 18 | **HTML fra forsidebyggeren og redigert HTML** | Generert og manuelt redigert HTML saneres som Canvas gjør (`canvas_safe`), og det som ville blitt fjernet, vises som varsel. Forhåndsvisning bare i sandkasset iframe. Ingen ekstern JavaScript. Fakta hentes fra Canvas; KI-tekst escapes og merkes. | `test_homepage_builder` |
| 19 | **Rapporter og lokale mapper** | Rapporter genereres med escaping, uten skript, og vises under appens CSP. Filer hentes via database-id og sti kontrolleres mot rapportmappen. «Åpne mappen» åpner bare faste mapper i datamappen. | `test_reports` |
| 20 | **Fjerning av innhold i quizspørsmål** | Canvas erstatter et spørsmål i sin helhet ved oppdatering. EmneKlar sender tilbake tilbakemeldingstekster og formatering, beholder original HTML når teksten er uendret og nekter å erstatte rik spørsmålstekst (bilder, tabeller) med ren tekst. | `test_quiz_assistant` |
| 21 | **Personvern ved oppdateringssjekk** | Bare én forespørsel om siste versjon til GitHub (ingen emnedata), høyst én gang i døgnet, og kan slås av. | `test_settings_updates` |
| 22 | **Andre programmer med samme navn eller mappe** | Et annet EmneKlar-program bruker `%LOCALAPPDATA%\EmneKlar`, `database.db`, Alembic-revisjon «0001», nøkkelringtjenesten «EmneKlar», informasjonskapselen `emneklar_session` og port 8765. EmneKlar har egen datamappe, egen nøkkelringtjeneste, en informasjonskapsel per port og standardport 8770. Databasen merkes med `PRAGMA application_id`; før noe åpnes for skriving, leses filhodet direkte, og en database som tilhører et annet program, blir verken migrert eller endret (heller ikke med -wal/-shm-filer). | `test_coexistence` |

## Restrisiko

* Arbeidsprosesser for dokumentparsing kjører som samme Windows-bruker (begrenser krasj og ressursbruk, men er
  ikke en full sandkasse).
* En lokal prosess som kjører som samme bruker kan lese nøkkelringen og datamappen. Dette er utenfor det
  EmneKlar kan beskytte mot.
* Lenkesjekken avslører lærerens IP-adresse for eksterne nettsteder (som ved vanlig nettlesing).
