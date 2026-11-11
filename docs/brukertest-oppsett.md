# Brukertest: oppsettet i EmneKlar (ca. 20 minutter)

En kort test med én lærer som ikke kjenner EmneKlar. Målet er å se om oppsettet kan gjennomføres **uten muntlig
veiledning**. Det er oppsettet som testes, ikke læreren.

## Før testen

- **Velg miljø:**
  - *Realistisk:* en ny EmneKlar-installasjon på lærerens egen maskin med lærerens egen Canvas. Oppsettet leser bare
    fra Canvas – ingenting opprettes, endres eller slettes der.
  - *Uten ekte konto:* testserveren med falsk Canvas (`backend/tests/fakes/dev_server.py`). Gi læreren adressen
    `http://127.0.0.1:8790` og testtokenet på en lapp, og la oppgave 1 handle om å *finne* stedet i sin egen Canvas
    der tokenet lages (uten å lage det).
- Ikke bruk ditt eget, ferdige oppsett. EmneKlar må starte med tomt oppsett.
- **Tokenet:** Ikke se på, skriv ned eller ta bilde av lærerens token. Si at læreren kan slette det i Canvas etterpå.
- Ha klar et notatark (se under) og en klokke.

## Det du sier til læreren (les opp, ikke forklar mer)

«Du skal sette opp et program som heter EmneKlar, som skal hjelpe deg med Canvas-emnene dine. Jeg forklarer ikke
hvordan – vi tester om programmet forklarer det godt nok selv. Tenk gjerne høyt mens du gjør det. Det finnes ingen
feil svar. Hvis du står helt fast, si fra, så noterer jeg det og hjelper deg videre.»

## Oppgavene

Gi én oppgave om gangen, skriftlig.

1. **Koble EmneKlar til Canvas.** Finn adressen til Canvas og et tilgangstoken.
   *Lykkes når:* riktig Canvas-adresse er skrevet inn og læreren forstår hvor tokenet lages (helst uten å forlate
   EmneKlar for å google).
2. **Kontroller at det er deg, og gå videre.** Etterpå: «Er tilkoblingen lagret nå? Når ble den lagret?»
   *Lykkes når:* læreren forstår at «Koble til» bare kontrollerer, og at tilkoblingen lagres ved «Bekreft og
   fortsett».
3. **Velg hvilket emne du vil starte med – eller la det vente.**
   *Lykkes når:* læreren finner emnet i feltet «Velg eller søk etter emne» (eller lar det stå tomt) med vilje.
4. **Velg hvilke krav emnene skal kontrolleres mot.** Etterpå: «Hvorfor valgte du denne? Hvor finner du mer om den?»
   *Lykkes når:* læreren tar et bevisst valg og finner «Vis detaljer» – uten å velge en annen profil ved et uhell.
5. **Du ombestemmer deg: bytt startemne.**
   *Lykkes når:* læreren går tilbake (med «Tilbake» eller trinnene øverst), endrer og fullfører igjen.
6. **Åpne oversikten for emnet ditt.**
   *Lykkes når:* emneoversikten for riktig emne åpnes (eller emnevalget, hvis feltet ble stående tomt).

## Hva du bør se etter

For hver oppgave: noter tid, og om læreren klarte den **alene**, **med nøling** eller **med hjelp**.

- **Nøling:** lange pauser, musepekeren som leter, gjentatte klikk på samme sted, å lese den samme teksten flere ganger.
- **Misforståelser:** tror tokenet er passordet sitt, limer inn en emneadresse som Canvas-adresse, tror «Koble til»
  lagrer, tror «Anbefalt …» betyr at EmneKlar har vurdert institusjonen, tror «Vis detaljer» velger profilen.
- **Hjelpebehov:** hva læreren spør om, og nøyaktig hva du måtte si.
- **Ord som skurrer:** gjenta lærerens egne ord (f.eks. «hva er et token?», «regelverksprofil?»).
- **Feilmeldinger:** skjedde det feil, forsto læreren hva som var galt og hva som måtte gjøres?
- **Tillit:** bekymring for hva som skjer med tokenet eller emnene i Canvas.

## Spørsmål etterpå (3–5 minutter)

1. Hva var lettest, og hva var vanskeligst?
2. Var det noe du var usikker på om du hadde gjort riktig?
3. Hva tror du EmneKlar kommer til å gjøre med emnene dine nå?
4. Var det noe du savnet eller syntes var overflødig?

## Notatark

| Oppgave | Tid | Alene / nøling / hjelp | Hva skjedde (lærerens ord) |
|---|---|---|---|
| 1 Koble til Canvas | | | |
| 2 Bekrefte og lagre | | | |
| 3 Startemne | | | |
| 4 Regelverk og detaljer | | | |
| 5 Bytt startemne | | | |
| 6 Åpne emneoversikten | | | |

Én test gir ikke et sikkert bilde. Er det mulig, gjenta med 3–5 lærere og se etter det som går igjen.
