# Universell utforming – kilder, profiler og klassifisering

*Kontrollert mot primærkilder 6. oktober 2026. Juridisk status ligger i versjonerte datafiler
(`backend/emneklar/features/accessibility/profiles/*.json`) – ikke i koden eller i UI-tekster. Når regelverket
endres, legges det til en ny profilversjon; gamle funn beholder versjonen de ble laget med.*

## Rettslig grunnlag (Norge)

* **Likestillings- og diskrimineringsloven § 18** (LOV-2017-06-16-51): plikt til universell utforming av
  hovedløsninger for IKT rettet mot eller stilt til rådighet for brukere; § 19 a aktivitetsplikt.
  https://lovdata.no/dokument/NL/lov/2017-06-16-51
* **Forskrift om universell utforming av IKT-løsninger** (FOR-2013-06-21-732), sist endret ved
  FOR-2023-01-17-87 (i kraft 1.2.2023). https://lovdata.no/dokument/SF/forskrift/2013-06-21-732
  * Offentlig sektor (§ 4b): oppfyllelse av EN 301 549 V3.2.1 (2021-03) – kapittel 9 tilsvarer WCAG 2.1 A+AA.
  * Privat sektor (§ 4): WCAG 2.0 A+AA unntatt 1.2.3, 1.2.4 og 1.2.5.
  * Utdanning (§ 3 g): «nettløsninger som er en integrert del av virksomhetens undervisning eller
    informasjonsformidling» – læringsplattformer (LMS) og innhold bak innlogging er omfattet.
  * Unntak (§ 4c): dokumentformater publisert før 1.2.2022 (med mindre de trengs i aktive prosesser), direkte
    tidsbaserte medier, tredjepartsinnhold utenfor virksomhetens kontroll (høy terskel), arkiver m.m.
  * Synstolking (1.2.5) for forhåndsinnspilt video publisert 1.2.2024 eller senere (offentlig sektor).
* **Uutilsynets kriterieliste**: https://www.uutilsynet.no/wcag-standarden/wcag-standarden/86 –
  48 kriterier for offentlig sektor (WCAG 2.1 A+AA minus 1.2.3 og 1.2.4), 35 for privat sektor, 44 for
  dokumenter. 4.1.1 (Parsing) er fortsatt med i listen.
* Lærerens ansvar: https://www.uutilsynet.no/veiledning/laererens-ansvar-universell-utforming/2675
* Video og teksting i utdanning: https://www.uutilsynet.no/wcag-standarden/sporsmal-og-svar-om-video/895

**Status for nyere standarder (oktober 2026):** WCAG 2.2 (W3C-anbefaling 2023, gjeldende utgave 12.12.2024) og
EN 301 549 V4.1.1 (september 2026, harmonisert med WCAG 2.2) er **ikke** lovkrav i Norge. Det finnes ingen
offentlig høring eller tidsplan. WCAG 2.2 tilbys derfor som profil for anbefalt praksis.

## Profiler i EmneKlar

| Id | Navn | Grunnlag | Kriterier |
|---|---|---|---|
| `no-offentlig-2023` | Norge – lovkrav, offentlig sektor (standard) | Forskriften § 4b, EN 301 549 V3.2.1 / WCAG 2.1 | 48 (1.2.5 under vilkår); dokumenter 44 |
| `no-privat-2013` | Norge – lovkrav, privat sektor | Forskriften § 4, WCAG 2.0 | 35 |
| `wcag22-aa` | WCAG 2.2 AA – anbefalt beste praksis | W3C WCAG 2.2, EN 301 549 V4.1.1 | 55 (ikke lovkrav) |

Om en institusjon regnes som «offentlig sektor» avgjøres av anskaffelsesregelverket (FOA § 1-2). De fleste
universiteter og høgskoler er offentlige.

## Klassifisering av funn

| Klasse | Når |
|---|---|
| **Avvik** | Deterministisk brudd på et suksesskriterium (f.eks. bilde uten `alt`-attributt, iframe uten tittel, lenke uten tilgjengelig navn). |
| **Sannsynlig avvik** | Sterke indikasjoner, men kan i sjeldne tilfeller være riktig (filnavn som alt-tekst, tekst formatert som overskrift uten overskriftskode, Canvas-video med lyd uten tekstspor). |
| **Bør vurderes** | Kan være et problem avhengig av sammenheng (hoppende overskriftsnivåer, «les mer» der konteksten er uklar, duplisert alt-tekst). |
| **Forbedringsforslag** | God praksis som ikke er krav (rå URL som lenketekst, lesbarhet/LIX, store bokstaver, tabelltittel). |
| **Manuell kontroll** | Kan ikke avgjøres automatisk (kontrast når bakgrunnen ikke er kjent, teksting av ekstern video, innholdet i eksterne verktøy/LTI, dokumenters lesbarhet). |

Testmetode: *deterministisk*, *heuristisk*, *KI-assistert*, *manuell*.

## Faglige presiseringer som er kodet inn

* `alt=""` er riktig for dekorative bilder (H67). Et tomt alt er bare et problem når bildet ser ut til å bære
  informasjon (f.eks. eneste innhold i en lenke).
* Bildetekst (`figcaption`) er **ikke** et alternativ til alt-tekst, og WCAG krever ikke bildetekst.
* 2.4.4 vurderes «i kontekst»: «klikk her» i en setning som forklarer målet, består; uten kontekst er det et
  sannsynlig avvik. Lenker som åpner PDF eller ny fane krever ikke varsel.
* Hopp i overskriftsnivå er ikke i seg selv et WCAG-brudd (W3C har ingen feilteknikk for det) → *Bør vurderes*.
  Tekst formatert som overskrift uten overskriftskode (F2) → *Sannsynlig avvik* (1.3.1).
* Canvas viser sidetittelen som `h1`; innhold bør derfor starte på `h2`.
* Kontrast vurderes automatisk bare når både forgrunns- og bakgrunnsfarge er kjent i koden; ellers manuell
  kontroll. Terskler rundes ikke (4,499:1 er under 4,5:1). Stor tekst: minst 24 px, eller 18,67 px fet.
* En iframe med tittel beviser ikke at det innebygde verktøyet er universelt utformet.
* Teksting av YouTube-video kontrolleres når eksterne kontroller er på (regelsett 2026.11.1): teksting fra den som
  lastet opp → ingen funn (kvaliteten vurderes ikke); bare YouTubes automatiske teksting → *Bør vurderes*
  (`UU-MEDIA-YOUTUBE-AUTO-CAPTIONS`, ukorrigert automatisk teksting regnes vanligvis ikke som tilstrekkelig); ingen
  teksting → *Sannsynlig avvik* (`UU-MEDIA-YOUTUBE-NO-CAPTIONS`). Kontrollen bruker et uoffisielt grensesnitt og
  sender bare video-id-en. Det som ikke kunne kontrolleres (Vimeo, andre tjenester, YouTube som avviser forespørsler),
  vises som manuell kontroll: «Teksting kan ikke verifiseres automatisk.»
* Teksting av video i Canvas leses fra mediefilen (`/media_attachments/:id/media_tracks`); emnets medieliste brukes
  bare når den viser teksting. Ukjent status gir manuell kontroll, aldri «mangler teksting». Canvas' egne
  `<video>`-elementer (medieopptak og videofiler fra editoren) vurderes som Canvas-medier, ikke som HTML5-video.
* **Unntak for eldre dokumenter** (regelsett 2026.11.3): alle dokumentregler (`UU-DOC-*`) har bekreftelsen
  «Unntaket for eldre dokumenter gjelder» (`older_document_exemption`). Den tilbys og godtas bare når analysen
  har funnet at filen er lastet opp før 1. februar 2022 (`evidence.exemption_hint`, `requires_evidence`), og
  funnet blir «Kontrollert» med lærerens begrunnelse. EmneKlar avgjør aldri selv at unntaket gjelder.
  `UU-DOC-PDF-NO-TEXT` har trinnvis veiledning (fjern, lag på nytt fra originalen, OCR, erstatt filen i Canvas).
* **Medietypen avgjør kravet** (regelsett 2026.11.2, kontrollert 6. november 2026 mot
  [Uutilsynet: 1.2.1 Bare lyd og bare video](https://www.uutilsynet.no/veiledning/121-bare-lyd-og-bare-video-forhandsinnspilt/1232)
  og [W3C Understanding 1.2.2](https://www.w3.org/WAI/WCAG21/Understanding/captions-prerecorded.html)):

  | Medietype | Krav | Regel | Klasse |
  |---|---|---|---|
  | Bare lyd (forhåndsinnspilt) | 1.2.1: likeverdig tekstalternativ, normalt transkripsjon av tale (med hvem som snakker) og andre lyder som trengs for å forstå innholdet. Kan stå på siden eller bak en tydelig lenke. Tekstspor i avspilleren er ikke kravet. | `UU-MEDIA-AUDIO-ALT` «Kontroller tekstalternativ til lydopptak» | Manuell kontroll (moderat) |
  | Video med lyd | 1.2.2: teksting som følger lyden – tale og andre betydningsfulle lyder. En separat transkripsjon erstatter ikke teksting. | `UU-MEDIA-CANVAS-CAPTIONS`, `-HTML5-TRACK`, `-YOUTUBE-*`, `-EXTERNAL-CAPTIONS` | Som før |
  | Video uten lyd | 1.2.1: tekst- eller lydalternativ. 1.2.2 gjelder ikke. | `UU-MEDIA-VIDEO-ONLY-ALT` | Manuell kontroll |
  | Ukjent | Forklarer hva som er usikkert; læreren angir typen. | `UU-MEDIA-TYPE-UNKNOWN` | Manuell kontroll |

  Begge kriteriene unntar et opptak som er et *tydelig merket* mediealternativ til tekst på siden (F74). Unntaket
  bekreftes av læreren; EmneKlar viser bare tekst som kan tyde på det («Innlest versjon av …»).
* Typen hentes i denne rekkefølgen: lærerens opplysning, Canvas' metadata (medieobjektets `media_type`, filens
  `content-type`), Canvas' merking i koden (`data-media-type`, `?type=` i `media_attachments_iframe`,
  `data-media_comment_type`), filtypen i avspilleren (`<source type>`, filendelse), et `<audio>`-element, en
  videotjeneste (YouTube, Vimeo). Et `<video>`-element alene er ikke bevis på bilde: Canvas spiller også av lyd i
  videoavspilleren, og en datarettingsjobb i Canvas skriver `data-media-type="video"` når typen er ukjent. Om en video
  har lyd, står ikke i Canvas – bare læreren kan angi «video uten lyd».
* Tekst eller lenker ved et lydopptak som ligner en transkripsjon, vises som «mulig tekstalternativ». Ingen tekst godtas
  automatisk som fullverdig alternativ. Læreren bekrefter (status «Kontrollert», vises i rapporter).
* Video uten tale kan likevel trenge teksting når musikk, lydeffekter eller andre lyder bærer mening.
* En tagget PDF er ikke automatisk universelt utformet.
* Automatiske verktøy kan ikke fastslå samsvar (W3C). EmneKlar viser aldri «100 % universelt utformet».
