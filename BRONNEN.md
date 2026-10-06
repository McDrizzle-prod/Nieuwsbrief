# Bronnen voor de Walletbrief

Dit overzicht laat zien waar officieel nieuws over de **EUDI Wallet** en de **European
Business Wallet (EBW)** verschijnt, en hoe de Walletbrief die bronnen volgt. De nadruk ligt
op officiële berichtgeving: Europese Commissie, Europees Parlement, Raad, de Large Scale
Pilots en de Nederlandse overheid.

De status is getest vanaf de GitHub-runners op 5 oktober 2026. De actuele status per bron
staat altijd op het tabblad **Bronnen** van de nieuwsbrief.

**Methoden**

| Methode | Betekenis |
|---|---|
| RSS/Atom | De bron publiceert een feed; die wordt dagelijks gelezen. |
| Webpagina | Een nieuwsoverzicht wordt gelezen; links naar berichten worden herkend aan hun adres. |
| API | Een officiële open-data-interface (JSON, SPARQL of SRU) wordt bevraagd. |
| Pagina volgen | Een vaste pagina wordt bewaard; elke inhoudelijke wijziging wordt een bericht. |
| Filter | Alleen berichten over EUDI, EBW of vertrouwensdiensten komen door (bij brede bronnen). |

## 1. Europese Commissie

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [Shaping Europe's digital future](https://digital-strategy.ec.europa.eu/en/news) (DG CONNECT) | Nieuws, persberichten, publicaties en evenementen van het directoraat dat EUDI en EBW trekt | Eerste plek voor aankondigingen zoals het EBW-voorstel en vastgestelde uitvoeringshandelingen | RSS + filter | Werkt |
| [Beleidspagina European Business Wallets](https://digital-strategy.ec.europa.eu/en/policies/business-wallets) | Stand van het beleid, documenten, technische werkgroepen | Officiële samenvatting van het EBW-dossier door de Commissie | Pagina volgen | Werkt |
| [Beleidspagina EUDI Wallet-implementatie](https://digital-strategy.ec.europa.eu/en/policies/eudi-wallet-implementation) | Uitrol, pilots en uitvoeringshandelingen | Mijlpalen in de uitrol van de wallet | Pagina volgen | Werkt |
| [EU Digital Identity Wallet – News](https://ec.europa.eu/digital-building-blocks/sites/spaces/EUDIGITALIDENTITYWALLET/pages/712507533/News) | Nieuws van de officiële wallet-site: ARF-versies, consultaties, studies, evenementen | Technische en juridische voortgang van de EUDI Wallet | Webpagina | Werkt |
| [Have your say](https://ec.europa.eu/info/law/better-regulation/have-your-say) | Consultaties en feedbackperiodes, onder meer op ontwerp-uitvoeringshandelingen | Hier kunnen ook Nederlandse overheden reageren op regels die MOZa raken | API (JSON) | Werkt |
| [EUR-Lex](https://eur-lex.europa.eu/) | Uitvoeringsverordeningen op basis van eIDAS en documenten met "business wallet" of "digital identity wallet" in de titel | De bindende regels zelf, zoals COM(2025) 838 en de uitvoeringsverordeningen voor wallets | API (SPARQL) | Werkt |
| [Architecture and Reference Framework](https://github.com/eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework) (GitHub van de Commissie) | Nieuwe versies van het ARF | Het technische raamwerk waarop wallets en koppelingen worden gebouwd | Atom | Werkt |

## 2. Europees Parlement

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [Legislative Observatory 2025/0358(COD)](https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2025/0358(COD)) | Officiële procedurefiche van de EBW-verordening met alle stappen en documenten | Elke stap in het wetgevingsproces: ITRE-stemming, plenaire vergadering, trilogen | Pagina volgen | Werkt |
| [Open data van het Parlement](https://data.europarl.europa.eu/en/home), procedure 2025/0358(COD) | Elke procedurestap als gegeven: verwijzing, adviezen (IMCO, JURI), ITRE-verslag, indiening voor de plenaire vergadering | Exacte datum van elke stap, ook als de website van het Parlement niet bereikbaar is | API (JSON) | Werkt |
| [EP Think Tank (EPRS)](https://www.europarl.europa.eu/thinktank/en/home) | Briefings en analyses, zoals [European business wallets](https://www.europarl.europa.eu/RegData/etudes/BRIE/2025/774703/EPRS_BRI(2025)774703_EN.pdf) | Onafhankelijke duiding van het voorstel voor Parlementsleden | RSS + filter (blog epthinktank.eu) | Werkt |
| [Persberichten](https://www.europarl.europa.eu/news/en/press-room) | Persberichten over stemmingen in ITRE en de plenaire vergadering | Officiële uitslag van stemmingen | RSS + filter | Uit (zie onder) |
| [Legislative Train: European business wallets](https://www.europarl.europa.eu/legislative-train/theme-a-new-plan-for-europe-s-sustainable-prosperity-and-competitiveness/file-european-business-wallet) | Samenvatting van de stand van het dossier, maandelijks bijgewerkt | Snel overzicht van waar het dossier staat | Pagina volgen | Uit (zie onder) |

De website www.europarl.europa.eu weigert geautomatiseerde verzoeken met een
JavaScript-controle (HTTP 202 zonder inhoud). De persberichten en de Legislative Train staan
daarom uit in de configuratie. De procedurestappen komen via de Legislative Observatory en
de open-data-API toch binnen, en grote stemmingen worden ook gemeld door WE BUILD en
DG CONNECT. Gaat de controle eraf, zet de bronnen dan aan met `actief: true`.

## 3. Raad van de EU

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [Persberichten](https://www.consilium.europa.eu/en/press/press-releases/) | Persberichten, onder meer van de Telecomraad | Positie van de lidstaten, zoals de [onderhandelingspositie over de EBW van 9 juni 2026](https://www.consilium.europa.eu/en/press/press-releases/2026/06/09/european-business-wallets-council-adopts-negotiating-position/) | RSS + filter | Werkt |

## 4. Large Scale Pilots

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [WE BUILD](https://www.webuildconsortium.eu/news) | Nieuws van het consortium (meer dan 180 organisaties) dat wallets test in B2B-, B2G- en B2C-processen, plus duiding van het EBW-wetgevingsproces | De pilot voor business wallets; use cases tussen bedrijven en overheden liggen dicht bij MOZa | Webpagina | Werkt |
| [APTITUDE](https://aptitude.digital-identity-wallet.eu/news-corner/) | Nieuws van de pilot onder leiding van Frankrijk: reizen, ticketing, kentekenbewijs, betalen | Ervaringen met de EUDI Wallet in de praktijk | RSS | Werkt |

De pilots uit de eerste ronde (POTENTIAL, EWC, NOBID, DC4EU) zijn afgerond. Hun resultaten
verschijnen via de wallet-site van de Commissie, die al gevolgd wordt.

## 5. Techniek en standaarden

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [ETSI](https://www.etsi.org/newsroom/news) | Nieuws van de Europese normalisatie-instelling; ETSI ESI maakt de normen voor vertrouwensdiensten en (gekwalificeerde) elektronische aangetekende bezorging | QERDS-normen bepalen hoe MOZa berichten met business wallets zou uitwisselen | RSS + filter | Werkt |

## 6. Nederlandse overheid

| Bron | Wat verschijnt er | Waarom relevant | Methode | Status |
|---|---|---|---|---|
| [Tweede Kamer](https://www.tweedekamer.nl/kamerstukken) (open data) | Kamerbrieven, verslagen, moties en position papers, bijvoorbeeld voor het rondetafelgesprek over de EBW | Nederlandse inzet en Kamerdebat over EBW, EUDI en MOZa | API (OData) + filter | Werkt |
| [Officiële bekendmakingen](https://zoek.officielebekendmakingen.nl/) | Kamerstukken en Staatscourant, zoals BNC-fiches en beslisnota's | Formele stukken, waaronder [BNC-fiche 3 over de EBW](https://www.rijksoverheid.nl/documenten/publicaties/2025/11/19/fiche-3-verordening-europese-business-wallet) | API (SRU) + filter | Werkt |
| [Eerste Kamer – E260004](https://www.eerstekamer.nl/eu/edossier/e260004_voorstel_voor_een) | EU-dossier van de Eerste Kamer over het EBW-voorstel | Nederlandse behandeling van het voorstel | Pagina volgen | Werkt |
| [Digitale Overheid](https://www.digitaleoverheid.nl/nieuws/) (BZK) | Nieuws over EDI-stelsel, NL Wallet, eHerkenning en Berichtenbox voor bedrijven | Nederlandse uitvoering van eIDAS en de bouwstenen waar MOZa op leunt | RSS + filter | Werkt |
| [NL Wallet](https://github.com/MinBZK/nl-wallet) (GitHub van BZK) | Nieuwe versies van de Nederlandse EUDI-wallet | De wallet die Nederland eind 2026 moet aanbieden en die MOZa al test | Atom | Werkt |

## 7. MijnOverheid Zakelijk

Berichten van MOZa zelf (Actueel, MOZa Weekly en de issues op GitHub) worden bewust niet
gevolgd. De Walletbrief gaat over nieuws over de wallets en wat dat betekent voor MOZa,
niet over de communicatie van het programma zelf. De MOZa-lens in de nieuwsbrief komt uit
de thema's en kernvragen in `config/onderwerpen.yaml` en `config/achtergrond.yaml`.

## 8. Bekeken, maar (nog) niet automatisch gevolgd

| Bron | Reden | Alternatief |
|---|---|---|
| Persdienst van de Commissie ([Press corner](https://ec.europa.eu/commission/presscorner/)) | Pagina wordt pas in de browser opgebouwd; geen bruikbare feed | Persberichten over EUDI en EBW verschijnen ook bij DG CONNECT (bron 1) |
| Documentenregister van de Raad | Geen feed; documenten zijn vaak niet openbaar (LIMITE) | Persberichten van de Raad (bron 3) |
| ENISA, CEN/TC 224 | Weinig nieuws over wallets; certificering loopt via uitvoeringshandelingen | EUR-Lex (bron 1) en ETSI (bron 5) |
| Rijksoverheid.nl (nieuws en documenten per onderwerp) | Na de vernieuwing van de site werken de oude RSS-adressen en de open-data-API (v1) niet meer | Kamerbrieven en BNC-fiches komen binnen via Tweede Kamer en Officiële bekendmakingen (bron 6) |
| RvIG en EDI-stelsel (edi.pleio.nl), Logius, KVK | Nieuws over wallets komt ook via Digitale Overheid en Kamerstukken | Toevoegen kan met *Bron onderzoeken* (zie hieronder) |
| Vakmedia (Biometric Update, iBestuur, Binnenlands Bestuur, Computable) | Niet officieel | Biometric Update staat klaar in `config/bronnen.yaml` met `actief: false` |

## 9. Agenda: bronnen voor evenementen

Het tabblad **Agenda** toont de komende evenementen over de EUDI Wallet en de Business
Wallet. Via een keuzemenu kies je de wallet. Je ziet een maandoverzicht van vandaag tot over
een maand en een lijst van evenementen die net zijn toegevoegd. Brede agenda's worden
gefilterd: een evenement komt alleen in de agenda als de titel, de beschrijving of de
evenementpagina een wallet noemt (zoektermen uit `config/onderwerpen.yaml`). De bronnen
staan in [`config/agenda.yaml`](config/agenda.yaml).

| Bron | Wat staat erin | Methode | Status |
|---|---|---|---|
| [EU Digital Identity Wallet – Events](https://ec.europa.eu/digital-building-blocks/sites/spaces/EUDIGITALIDENTITYWALLET/pages/694497147/Events) (Commissie) | Launchpads, webinars en andere evenementen van de Commissie over de EUDI Wallet | Webpagina | Werkt |
| [Tweede Kamer](https://www.tweedekamer.nl/debat_en_vergadering) (open data) | Commissiedebatten, rondetafelgesprekken en technische briefings waarbij een wallet, eIDAS of digitale identiteit op de agenda staat | API (OData) + filter | Werkt |
| [Digitale Overheid – evenementen](https://www.digitaleoverheid.nl/evenementen/) (BZK) | De centrale agenda van de digitale overheid, met onder meer meet-ups van het EDI-stelsel en de Logius Roadshow | iCal + evenementpagina + filter | Werkt |
| [Gebruiker Centraal](https://www.gebruikercentraal.nl/evenementen/) | Bijeenkomsten over dienstverlening, waaronder de ID-wallet-conferentie UNFOLD | iCal + evenementpagina + filter | Werkt |
| [Staat van de Uitvoering](https://staatvandeuitvoering.nl/agenda/) | Agenda rond publieke dienstverlening (ICTU, in opdracht van BZK) | Webpagina + evenementpagina + filter | Werkt |
| [Europa decentraal](https://europadecentraal.nl/agenda/) | Bijeenkomsten over Europees recht en beleid voor decentrale overheden | Agenda-API (WordPress) + filter | Werkt |
| [KVK – evenementen](https://www.kvk.nl/evenementen/) | Evenementen van de Kamer van Koophandel; alleen bijeenkomsten over een wallet komen door | Webpagina + evenementpagina + filter | Werkt |
| [ECP – agenda](https://ecp.nl/agenda/) | Symposia over de European Business Wallet, met het ministerie van Economische Zaken (programma Vertrouwensdiensten) | Webpagina + evenementpagina + filter | Werkt |
| [IDnext](https://idnext.eu/calendar) | Conferenties over digitale identiteit, waaronder de jaarlijkse IDnext over eIDAS 2.0 | Agenda-API (WordPress) + filter | Werkt |
| [EBRA](https://ebra.be/events/) | Europese handelsregisters (waaronder KVK) over hun rol in de Business Wallet | Agenda-API (WordPress) + filter | Werkt |

Hetzelfde evenement staat vaak bij meer bronnen (bijvoorbeeld bij ECP en bij Digitale
Overheid). De agenda toont het dan één keer, met de andere vindplaatsen onder *ook vermeld
bij*.

**Bekeken, maar niet automatisch gevolgd**

| Bron | Reden | Alternatief |
|---|---|---|
| FIDES ([fides.community](https://fides.community/)) | Weigert geautomatiseerde verzoeken (HTTP 403) en heeft geen agenda-overzicht | Zelf toevoegen onder `handmatig` in `config/agenda.yaml` |
| Europees Parlement | De Legislative Observatory toont voor de EBW geen geplande datums; de website weigert geautomatiseerde verzoeken | Stemmingen en procedurestappen verschijnen in de nieuwsbrief; een aangekondigde datum kun je handmatig toevoegen |
| Raad van de EU | Vergaderingen (zoals de Telecomraad) noemen de wallets niet in de titel | Uitkomsten komen via de persberichten in de nieuwsbrief |
| DG CONNECT ([digital-strategy.ec.europa.eu/en/events](https://digital-strategy.ec.europa.eu/en/events)) | Zelden over wallets; evenementen verwijzen vaak door naar andere sites | De EUDI-evenementenpagina van de Commissie (hierboven) |
| EDI-stelsel NL ([edi.pleio.nl](https://edi.pleio.nl/)) | Agenda alleen via JavaScript en een niet-openbare interface | Meet-ups van het EDI-stelsel staan ook bij Digitale Overheid |
| WE BUILD, APTITUDE | Geen eigen agenda; evenementen staan in hun nieuws | De nieuwsbrief volgt hun nieuws |
| Ministerie van EZ, Logius, RvIG | Geen eigen evenementenoverzicht | Hun bijeenkomsten staan bij ECP en Digitale Overheid |
| Digicampus, NLdigital, VNG, Dutch Blockchain Coalition | Geen bruikbare agenda gevonden (pagina niet gevonden of certificaatfout) | Zelf toevoegen onder `handmatig` |

**Zelf een evenement toevoegen**

Staat een evenement niet in de agenda, bijvoorbeeld een bijeenkomst van FIDES of een
aangekondigde stemming in het Parlement? Voeg het toe onder `handmatig` in
[`config/agenda.yaml`](config/agenda.yaml), met titel, datum (en eventueel tijd), locatie,
link en de wallet(s). Het staat in de agenda tot het voorbij is.

## Een bron toevoegen

1. Start in GitHub *Actions → Bron onderzoeken → Run workflow* en vul de URL in. De
   samenvatting van de run laat zien of er een feed is, welke links op nieuwsberichten
   lijken en hoe die eruitzien.
2. Open [`config/bronnen.yaml`](config/bronnen.yaml), klik op het potlood en voeg een blok
   toe, bijvoorbeeld:

   ```yaml
   - id: kvk-nieuws
     naam: "KVK – nieuws"
     categorie: nl-overheid
     type: feed            # of html met link_patroon
     url: https://voorbeeld.nl/feed/
     filter: true          # alleen berichten over EUDI/EBW
     prioriteit: 2
     toelichting: Waarom deze bron relevant is.
   ```

3. Kies *Commit changes*. De nieuwsbrief wordt opnieuw opgebouwd en de nieuwe bron
   verschijnt op het tabblad **Bronnen**.
