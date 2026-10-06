# Walletbrief: nieuwsbrief over EUDI Wallet en European Business Wallet

De Walletbrief verzamelt elke dag officieel nieuws over de **EU Digital Identity Wallet
(EUDI Wallet)** en de **European Business Wallet (EBW)**. Bronnen zijn onder meer de
Europese Commissie, het Europees Parlement, de Raad, de Large Scale Pilots (WE BUILD,
APTITUDE), EUR-Lex en de Nederlandse overheid. Het resultaat is een nieuwsbrief per week,
met bij elk bericht de **MOZa-lens**: hoe raakt dit MijnOverheid Zakelijk?

Alles draait in GitHub. Je hoeft niets te installeren; een browser is genoeg.

- **Nieuwsbrief lezen:** `https://mcdrizzle-prod.github.io/Nieuwsbrief/` (na de eenmalige
  instelling hieronder)
- **Welke bronnen en waarom:** [BRONNEN.md](BRONNEN.md)
- **Agenda:** komende evenementen over de EUDI Wallet en de Business Wallet, met een
  maandoverzicht en de nieuw toegevoegde evenementen (tabblad *Agenda*)

## Zo werkt het

```
GitHub Actions (elke ochtend)            GitHub Pages
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ scraper haalt ±20 bronnen op │  ─────►  │ site/: nieuwsbrief per week, │
│ (RSS, webpagina's, API's,    │  data    │ MOZa-lens, archief, dossiers │
│  EUR-Lex, Kamerstukken)      │  (JSON)  │ en bronnenstatus             │
│ → filtert op EUDI/EBW        │          └──────────────────────────────┘
│ → deelt in naar MOZa-thema's │
│ → (optioneel) AI-samenvatting│
└──────────────────────────────┘
```

1. De workflow **Nieuwsbrief bijwerken** draait elke ochtend. Je kunt hem ook zelf starten.
2. De scraper haalt alle bronnen uit [`config/bronnen.yaml`](config/bronnen.yaml) op.
   Brede bronnen, zoals alle persberichten van het Parlement, worden gefilterd op
   zoektermen uit [`config/onderwerpen.yaml`](config/onderwerpen.yaml).
3. Elk bericht krijgt onderwerpen (EBW, EUDI, vertrouwensdiensten) en MOZa-thema's:
   berichtenverkeer, inloggen en vertegenwoordiging, gegevensdeling, verplichtingen en
   planning, architectuur, ondertekening, pilots en soevereiniteit. Daaruit volgt een
   relevantie voor MOZa: hoog, middel of laag.
4. Nieuwe berichten komen in `site/data/items.json` en de site wordt opnieuw gepubliceerd.
5. In dezelfde run haalt de scraper de agenda's op uit
   [`config/agenda.yaml`](config/agenda.yaml): van de Commissie, de Tweede Kamer,
   Digitale Overheid, ECP en andere. Evenementen over de EUDI Wallet of de Business Wallet
   komen in `site/data/agenda.json`.

## Eenmalig instellen (5 minuten, alleen in de browser)

1. **GitHub Pages aanzetten:** ga naar *Settings → Pages* en kies bij *Build and
   deployment → Source* de optie **GitHub Actions**. Zolang dat niet is gebeurd, geeft
   elke run de waarschuwing "GitHub Pages staat uit"; de berichten worden wel verzameld.
2. **Eerste run starten:** ga naar *Actions → Nieuwsbrief bijwerken → Run workflow*. Na
   een paar minuten staat de nieuwsbrief online. De link staat bij de run onder
   *publiceren*.
3. *(Optioneel)* **AI-samenvattingen:** voeg onder *Settings → Secrets and variables →
   Actions* een secret `ANTHROPIC_API_KEY` toe. Elk nieuw bericht krijgt dan een
   Nederlandse samenvatting en een korte toelichting over de gevolgen voor MOZa, gemaakt
   met Claude van Anthropic. Er gaan alleen titel, bron en openbare samenvatting van het
   bericht naar de API, maximaal 40 berichten per run (instelbaar met de variabele
   `AI_MAX_BERICHTEN`). Zonder sleutel werkt alles ook, met de indeling op trefwoorden.

> De hoofdbranch van deze repository heet nu `claude/epic-brown-nqj88f`. Wil je liever
> `main`? Hernoem de branch via *Settings → General → Default branch* (het potlood).
> Controleer daarna onder *Settings → Environments → github-pages* dat de nieuwe naam
> mag publiceren.

## Dagelijks gebruik

| Wat wil je? | Waar? |
|---|---|
| Nieuwsbrief van deze week lezen | De site, tab **Nieuwsbrief** |
| Nieuwsbrief doorsturen | **Kopieer voor e-mail** en plak in Outlook, of **Download HTML** |
| Komende evenementen bekijken | Tab **Agenda**: kies de EUDI Wallet of de Business Wallet; rechts staat wat nieuw is toegevoegd |
| Oudere berichten zoeken | Tab **Archief** (zoeken en filteren op onderwerp, bron en MOZa-relevantie) |
| Stand van het EBW-dossier en de MOZa-kernvragen | Tab **Dossiers** |
| Zien welke bronnen werken | Tab **Bronnen**, of de samenvatting van de laatste run onder *Actions* |
| Direct verversen | *Actions → Nieuwsbrief bijwerken → Run workflow* |

## Aanpassen zonder te programmeren

Alle instellingen staan in YAML-bestanden die je in GitHub kunt bewerken: open het
bestand, klik op het potlood en kies *Commit changes*. De nieuwsbrief wordt daarna
automatisch opnieuw opgebouwd.

- **Bron toevoegen of uitzetten:** [`config/bronnen.yaml`](config/bronnen.yaml). Twijfel je
  over een website? Start *Actions → Bron onderzoeken*, vul de URL in en bekijk in de
  samenvatting welke feeds en nieuwslinks er zijn. Met het veld *link_patroon* zie je
  welke links een patroon oplevert, en *als browser* laat zien of een site
  geautomatiseerde verzoeken weigert.
- **Zoektermen en MOZa-thema's:** [`config/onderwerpen.yaml`](config/onderwerpen.yaml).
  Hier staat ook de uitleg per thema die in de MOZa-lens verschijnt.
- **Agenda:** [`config/agenda.yaml`](config/agenda.yaml). Hier staan de agendabronnen. Onder
  `handmatig` kun je zelf een evenement toevoegen dat geen bron levert.
- **Dossierstappen en kernvragen:** [`config/achtergrond.yaml`](config/achtergrond.yaml).
  Deze teksten worden niet gescraped. Werk ze bij als het dossier een stap zet; de
  nieuwsbrief meldt zulke stappen via de bronnen.

## Mappen

| Map | Inhoud |
|---|---|
| `config/` | bronnen, zoektermen en MOZa-thema's, dossierteksten, agendabronnen |
| `scraper/` | Python-code die bronnen ophaalt, indeelt en het archief bijhoudt; `agenda.py` doet hetzelfde voor evenementen |
| `site/` | de nieuwsbrief (HTML, CSS en JavaScript, zonder externe bibliotheken) |
| `site/data/` | gegenereerde gegevens: berichten, agenda, bronstatus en configuratie voor de site |
| `data/` | interne status: de laatst bekende tekst van gevolgde pagina's en bekeken evenementpagina's (`state.json`), en het archief van de agenda (`agenda.json`) |
| `tools/probe.py` | hulpmiddel om een nieuwe bron te verkennen |
| `tests/` | tests met voorbeeldpagina's per brontype |

## Lokaal draaien (optioneel, voor ontwikkelaars)

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest            # tests
python -m scraper --droog   # alle bronnen ophalen zonder iets weg te schrijven
python -m scraper --bron we-build --bron tweede-kamer
python -m http.server -d site 8000   # site bekijken op http://localhost:8000
```

## Kanttekeningen

- De indeling gebeurt op trefwoorden en is daardoor grof. Controleer voor
  besluitvorming altijd de originele bron.
- Websites veranderen soms van opbouw. Een bron die faalt, staat met de foutmelding op het
  tabblad **Bronnen**; de rest van de nieuwsbrief werkt dan gewoon door.
- Gevolgde pagina's (zoals de Legislative Train) leveren pas een bericht op als ze na de
  eerste meting veranderen.
