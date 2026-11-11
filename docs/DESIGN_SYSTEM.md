# Designsystem

EmneKlar har ett felles designsystem i `frontend/src/design-system`. Sidene setter sammen komponentene herfra og
definerer aldri egne farger, avstander eller størrelser. Mangler noe, legges det til her, ikke på siden.

Uttrykket er rolig og profesjonelt (høyere utdanning): mørk marineblå meny, lys og lett varm bakgrunn, store hvite
kort med myke kanter og svært svake skygger, pastellflater for ikoner og tydelig typografi.

## Tokens (`styles/tokens.css`)

Alle verdier er CSS-variabler, med egne verdier for lyst og mørkt tema (`data-theme`).

| Gruppe | Variabler | Bruk |
|---|---|---|
| Typografi | `--font-sans` (Inter, pakket med appen), `--text-xs` 13 px … `--text-3xl` 34 px | Sidetittel 34 px, seksjon 21 px, korttittel 17 px, brødtekst 15 px. Ingen tekst under 13 px. |
| Avstand | `--space-1` … `--space-16` (4 px-rutenett), `--density` | All padding og alle mellomrom |
| Form | `--radius-sm/--radius/--radius-lg/--radius-xl`, `--shadow-sm/--shadow/--shadow-md/--shadow-hover/--shadow-lg/--shadow-pop` (lyst og mørkt tema) | Kort 16 px radius, kontroller 10 px |
| Flater | `--color-bg`, `--color-surface`, `--color-surface-muted/-sunken/-hover`, `--color-border(-strong/-input)` | Sidebakgrunn, kort, rader |
| Tekst | `--color-text`, `--color-text-muted`, `--color-text-subtle`, `--color-link` | Alle ≥ 4,5:1 mot flatene |
| Toner | `--tone-{neutral,info,success,warning,danger,violet,teal,orange}-{bg,border,text,icon}` | Merker, varsler, ikonfliser og myke knapper |
| Status for tall | `--status-{critical,warning,info,success,neutral,zero}` | Nøkkeltall og statusmerker: `critical` = bekreftede feil, `warning` = bør vurderes/kontrolleres eller avbrutt, `info` = forslag, `success` = fullført. `zero` = dempet 0 (ikke det samme som fullført). Alle ≥ 4,5:1 mot kortflaten i begge temaer. |
| Diagram | `--chart-violation/-likely/-review/-improvement/-manual`, `--chart-grid`, `--chart-axis` | Kun i diagrammer. Hver serie har minst 3:1 mot kortflaten i begge temaer (WCAG 1.4.11), kontrollert i `tokens.test.ts` |

**Fargeidentitet per område:** Universell utforming = lilla (`violet`), Innholdskvalitet = blå (`info`), Emnestruktur =
grønn/turkis (`teal`), Quiz = varm oransje (`orange`) – se `DOMAIN_TONE` i `core/labels.ts`. Statusfarger (rødt og
gult) er forbeholdt funn og skal ikke dominere.

**Klassifisering:** Avvik og sannsynlig avvik = rød, bør vurderes = gul/oransje, forbedringsforslag = blå, manuell
kontroll = grå (`CLASSIFICATION` i `core/labels.ts`). «Avvik» brukes bare i universell utforming; andre områder sier
«Feil» / «Sannsynlig feil» – bruk `classificationFor(klasse, område)`, ikke `CLASSIFICATION` direkte, der et funn vises. Klassene vises alltid med tekst, aldri bare farge.

**Kontrast:** Alle tekst- og ikonpar i tokens er kontrollert (WCAG 2.2 AA: tekst ≥ 4,5:1, ikoner og kontrollkanter
≥ 3:1). E2E-testene kjører axe på alle sider i lyst og mørkt tema.

## Komponenter

| Komponent | Fil | Bruk |
|---|---|---|
| `PageHeader` | `primitives.tsx` | Sidetittel, beskrivelse, `meta` (f.eks. «Sist analysert»), handlinger til høyre |
| `Card` | `primitives.tsx` | Hvitt kort med tittel, `description` og handlinger |
| `Button`, `ButtonLink` | `primitives.tsx` | `primary` (marineblå), `secondary`, `ghost`, `danger`, `link`, `soft` + `tone`; størrelser `sm`/`md`/`lg` |
| `Badge`, `StatusBadge` | `primitives.tsx`, `dashboard.tsx` | Statuspiller; `StatusBadge` har en prikk |
| `IconTile` | `dashboard.tsx` | Ikon i pastellflate (sirkel eller avrundet firkant) |
| `SectionHeader`, `MoreLink` | `dashboard.tsx` | Overskrift med beskrivelse og «Se alle →» |
| `StatusCard` | `dashboard.tsx` | Område på Oversikt: ikon og tittel, ett eller to nøkkeltall (0 alltid dempet), kort bunnlinje og «Vis detaljer». Tittellenken dekker kortet, så detaljknappen ligger aldri inne i lenken; fokusring rundt hele kortet bare ved `:focus-visible` |
| `MetricCard` | `dashboard.tsx` | Nøkkeltall med ikon øverst på sider; statisk, lenke eller av/på-filter. Valgfritt `secondary` gir et mindre tall under merkelappen (f.eks. «806 sannsynlige avvik» under bekreftede avvik); 0 vises dempet |
| `ActionList`, `ActionRow` | `dashboard.tsx` | Anbefalte steg: ikon, tittel, én forklarende linje, tydelig knapp |
| `FeatureCard` | `dashboard.tsx` | Verktøy eller område å åpne, med én handling. Ikonfargen har mening, ikke pynt: blå for verktøy i Canvas, fiolett for KI-verktøy, nøytral for logg og historikk; oransje og rød bare når noe krever oppmerksomhet |
| `StatList`, `StatTile` | `dashboard.tsx` | Antall med ikon (innhold i emnet) |
| `KeyFigureList`, `KeyFigure` | `dashboard.tsx` | Nøkkeltall med forklaring inne i et kort (f.eks. lenkestatus) |
| `ActivityList` | `dashboard.tsx` | Hendelser med ikon, tittel, statusmerke (tekst + ikon + `--status-*`, lest som «Status: …»), dato og tid |
| `FilterChips`, `ToggleChips` | `dashboard.tsx` | Filterpiller: ett valg / flere valg (`aria-pressed`) |
| `BarChart` | `chart.tsx` | Gruppert stolpediagram med forklaring, verktøytips og tabellvisning |
| `PasswordField` | `forms.tsx` | Hemmeligheter (token, nøkler): skjult som standard, øyeknapp inne i feltet («Vis …»/«Skjul …», `type="button"`), teksten stopper før knappen |
| `Switch` (`describedBy`) | `forms.tsx` | Av/på-bryter som viser «På»/«Av». En hjelpetekst står i et eget avsnitt under bryteren (ikke i samme linje), med `id` som sendes som `describedBy` |
| `RadioGroup` (`variant="card"`, `details`, `truncateLabels`) | `forms.tsx` | Valgkort der hele kortet velger, med «Vis detaljer» utenfor etiketten; radioknappens navn er etiketten, hjelpeteksten er beskrivelsen. `truncateLabels`: lange etiketter på én linje med «…», hele teksten ved musepeker og tastaturfokus, naturlig bryting på berøringsskjerm, med større tekst og på smale skjermer; det tilgjengelige navnet er alltid hele teksten |
| `ProgressBar`, `EmptyState`, `Tabs`, `NavTabs`, `DataTable`, skjemaelementer | diverse | Som før, i nytt uttrykk |

Hjelpeklasser for oppsett (`ek-stack`, `ek-cluster`, `ek-grid` med `data-cols`, `ek-split`, `ek-item-row`, `ek-grow`,
`ek-field-box`, `ek-card--compact` m.fl.) erstatter inline-stiler. Inline-stil brukes bare for verdier som kommer fra
data, som innrykk eller fargeprøver.

## Diagrammer

Diagrammer følger disse reglene: tynne stolper (≤ 24 px) med avrundet topp og 2 px mellomrom, hårfine rutenettlinjer,
forklaring for hver serie, tekst i tekstfarger (aldri seriefargen), verktøytips ved musepeker og tastaturfokus, og en
tabellvisning («Vis som tabell»). Fargene for klassene er kontrollert for fargesvaksyn (CVD-avstand mellom nabofarger)
i begge temaer. Diagrammer viser bare ekte tall. Uten data vises en melding i stedet for et tomt diagram.

## Responsivt

Innholdsområdet er en container (`container: content`). Rutenett og kort tilpasser seg bredden de faktisk har: fire
områdekort på rad når det er plass, 2 × 2 på smalere skjermer, én kolonne på mobil. Smale statuskort setter ikonet over
tittelen. Ingen side skal gi horisontal rulling ved 375 px (testes i E2E).

## Sannferdig grensesnitt

Designet skal aldri vise tall eller funksjoner som ikke finnes. Fra skissene er bevisst utelatt: antall bilder og lenker
(telles ikke), varselbjelle og brukerrolle (ingen datakilde), «Se alle anbefalinger» (ingen slik side) og «Kritisk/
Viktig» som klassenavn (EmneKlar bruker de faste klassene over).
