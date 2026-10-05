# Weekoverzicht per mail instellen (Laposta)

Abonnees krijgen elke vrijdag om 16:00 (Nederlandse tijd) een mail met de nieuwe berichten van
die week. Per bericht staan erin:

- een klikbare titel die naar het bericht zelf leidt;
- een korte samenvatting;
- wat het bericht betekent voor MijnOverheid Zakelijk.

Daarnaast bevat elke mail een link naar de volledige nieuwsbrief van die week en onderaan een
afmeldlink.

## Hoe het werkt

- **Aanmelden en afmelden regelt Laposta.** De knop *Aanmelden* op de site opent het
  aanmeldformulier van Laposta, en de afmeldlink in de mail is ook van Laposta. De
  e-mailadressen staan alleen in Laposta, niet in GitHub.
- **De workflow maakt de mail.** Op vrijdag draait *Nieuwsbrief bijwerken* om 13:40 en om
  14:40 (wintertijd), of om 14:40 en 15:40 (zomertijd). De eerste run haalt de bronnen op, maakt
  het weekoverzicht aan als campagne in Laposta en plant die in voor 16:00. Laposta verstuurt de
  mail. De tweede run is een reserve voor als GitHub de eerste overslaat.
- **Nooit twee keer dezelfde week.** In `data/weekmail.json` staat welke weken zijn verstuurd.
  Daarnaast kijkt de workflow in Laposta of de campagne van die week al bestaat. De volgende mail
  bevat alleen berichten die na de vorige mail zijn gevonden.
- **Geen nieuws, geen mail.** Zijn er in een week geen nieuwe relevante berichten, dan gaat er
  geen mail uit.

## Kosten

Het gratis account van Laposta is genoeg: tot 2.000 abonnees en 12.000 mails per maand. Daar
gelden een paar voorwaarden voor:

- onderaan elke mail staat een klein Laposta-logo;
- er is maximaal één gratis account per organisatie;
- ondersteuning gaat alleen per mail.

Dubbele opt-in, waarbij nieuwe abonnees hun aanmelding eerst via een mail bevestigen, zit
alleen in een betaald abonnement (zie stap 3).

## Wat je nodig hebt

- Een bestaand e-mailadres om vanaf te versturen, bijvoorbeeld een functioneel adres van je
  team. Je moet dit adres bevestigen, dus je moet de mail op dat adres kunnen lezen.
- Iemand die de DNS van dat maildomein kan aanpassen, meestal de IT-afdeling. Dat is nodig
  als het domein DMARC gebruikt (zie stap 4), en bij overheidsdomeinen is dat vrijwel altijd
  zo.
- Beheerrechten op deze GitHub-repository, om een secret toe te voegen.

## Stap 1. Account aanmaken

1. Vraag op [laposta.nl](https://laposta.nl/) een gratis account aan.
2. Heeft je organisatie al een Laposta-account? Vraag dan om een eigen login en maak in dat
   account een aparte lijst aan (stap 2). Een tweede gratis account mag niet.

## Stap 2. Lijst maken

1. Ga naar **Relaties** en maak een nieuwe lijst, bijvoorbeeld *Walletbrief – weekoverzicht*.
2. Klik de lijst aan en open het tabblad **Kenmerken lijst**. Rechts staat de **ID** van de
   lijst, een code van letters en cijfers. Die heb je nodig in stap 6.

## Stap 3. Aanmeldformulier

1. Ga naar **Relaties**, klik de lijst aan en kies **Verrijken → Aanmelden**.
2. Klik onder *Zelfstandig aanmeldformulier* op **Beginnen**. Pas het formulier en de
   bedankpagina aan, bijvoorbeeld:
   - titel: *Walletbrief: weekoverzicht per mail*;
   - tekst: *Elke vrijdag om 16:00 het officiële nieuws over de EUDI Wallet en de European
     Business Wallet, met wat het betekent voor MijnOverheid Zakelijk. Afmelden kan altijd via
     de link onderaan elke mail.*
3. Kopieer de **aanmeldlink**. Die heb je nodig in stap 8.
4. **Opt-in.** Op het gratis account staat een aanmelding direct op de lijst (enkele opt-in).
   Wil je dat nieuwe abonnees hun aanmelding eerst bevestigen (dubbele opt-in)? Dat kan alleen
   met een betaald abonnement; Laposta zet het dan aan via helpdesk@laposta.nl. De AVG en de
   ACM eisen dubbele opt-in niet, wel een afmeldlink in elke mail.
5. *Optioneel:* wil je dat nieuwe abonnees direct een welkomstmail krijgen? Maak dan in
   Laposta een automatisering met het startmoment **Inschrijven** op deze lijst en een blok
   **E-mail versturen**.

## Stap 4. Afzendadres

1. Ga naar **Instellingen → Afzendadressen** en klik op **Nieuw afzendadres**. Vul het adres
   in en kies *zonder beperkingen*, zodat het adres ook als antwoordadres werkt.
2. Laposta stuurt een bevestigingsmail naar dat adres. Klik op de link in die mail. Pas daarna
   kan het adres als afzender worden gebruikt.
3. **Domein authenticeren.** Gebruikt het domein van het adres DMARC, dan komen mails zonder
   authenticatie bij de meeste ontvangers niet aan. Zo regel je het:
   1. Ga naar **Instellingen → Authenticatie** en klik bij het domein op **Toon instructies**.
   2. Laposta toont twee CNAME-records, en soms ook een DMARC-record. Stuur deze naar de
      beheerder van het domein (bij een overheidsdomein meestal IT) met het verzoek ze toe te
      voegen.
   3. Zijn de records toegevoegd? Klik dan opnieuw op **Toon instructies** en daarna op
      **Activeren**.

## Stap 5. API-sleutel koppelen aan GitHub

1. Ga in Laposta naar **Toegang & Abonnement → Koppelingen → API** en maak een nieuwe sleutel.
   Laposta toont de sleutel **maar één keer**, dus kopieer hem meteen. Op het gratis account
   kun je maximaal drie sleutels maken.
2. Ga in GitHub naar deze repository: **Settings → Secrets and variables → Actions → New
   repository secret**.
   - Name: `LAPOSTA_API_KEY`
   - Secret: de sleutel uit Laposta

   Klik op **Add secret**. De sleutel staat daarmee niet in de repository en is niet zichtbaar
   in de logboeken van de workflow.

## Stap 6. Instellingen invullen

Open [`config/notificaties.yaml`](config/notificaties.yaml) in GitHub, klik op het potlood en
vul in:

| Instelling | Wat |
|---|---|
| `lijst_id` | de ID van de lijst uit stap 2 |
| `afzender_email` | het bevestigde afzendadres uit stap 4 |
| `afzender_naam` | de naam die ontvangers zien, bijvoorbeeld *Walletbrief* |

Laat `actief: false` en `aanmeldlink: ""` nog even zo staan. Klik op **Commit changes**.

## Stap 7. Testmail sturen

1. Ga naar **Actions → Nieuwsbrief bijwerken → Run workflow** en kies:
   - *Weekoverzicht per mail*: **test**
   - *E-mailadres voor de testmail*: je eigen adres

   Klik op **Run workflow**.
2. Na een paar minuten ontvang je een testmail met de berichten van de afgelopen zeven dagen.
   Zijn die er niet, dan bevat de testmail de tien nieuwste berichten.
3. Controleer de mail:
   - zijn de titels klikbaar?
   - staan de samenvatting en het blok *Wat betekent dit voor MOZa?* bij elk bericht?
   - werkt de link naar de volledige nieuwsbrief?
   - staat de afmeldlink onderaan?
4. Ging er iets mis? Open de run en kijk in de samenvatting onder **weekoverzicht**. Daar staat
   de foutmelding van Laposta, bijvoorbeeld dat het afzendadres nog niet is bevestigd.

De testcampagne blijft als concept staan onder **Campagnes** in Laposta. Je kunt hem daar
verwijderen.

## Stap 8. Live zetten

1. Zet in [`config/notificaties.yaml`](config/notificaties.yaml):
   - `actief: true`
   - `aanmeldlink:` de link uit stap 3

   Klik op **Commit changes**.
2. Na een paar minuten staat op de site het blok **Weekoverzicht per mail** met de knop
   **Aanmelden**, en onderaan elke pagina een aanmeldlink.
3. Vanaf dan maakt de workflow elke vrijdag het weekoverzicht aan. In Laposta staat het onder
   **Campagnes** als *Walletbrief week [nummer] ([jaar])*, ingepland voor 16:00. Tot 16:00 kun
   je de campagne daar nog bekijken of de verzending annuleren.

## Goed om te weten

- **Tijdstip.** De mail gaat om 16:00 Nederlandse tijd, ook in de zomer. In de winter is dat
  GMT+1, in de zomer GMT+2.
- **Mail meteen versturen.** Kies bij *Run workflow* **versturen**. Is het weekoverzicht van
  deze week al verstuurd en wil je het opnieuw sturen? Vink dan ook *Ook versturen als het
  weekoverzicht van deze week al is verstuurd* aan.
- **Tijdelijk uitzetten.** Zet `actief: false`. Wil je ook de aanmeldknop van de site halen,
  maak dan `aanmeldlink` leeg.
- **Wie er op de lijst staat.** Dat zie je in Laposta onder **Relaties**. Daar kun je ook
  adressen toevoegen of verwijderen.
- **Betere samenvattingen.** Zonder AI-sleutel gebruikt de mail de beschrijving van de bron.
  Sommige bronnen, zoals EUR-Lex, geven geen beschrijving mee. Dan staat er welk onderwerp
  herkend is en aan welke termen. Met het secret `ANTHROPIC_API_KEY` (zie de
  [README](README.md)) krijgt elk bericht een Nederlandse samenvatting en een eigen toelichting
  voor MOZa.
- **Onderwerpregel en aantal berichten.** Pas `onderwerp` en `max_berichten` aan in
  `config/notificaties.yaml`. Staan er meer berichten in een week dan `max_berichten`, dan
  verwijst de mail voor de rest naar de site.
