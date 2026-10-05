from scraper.fetchers import Context, fetch
from scraper.util import item_id


def test_feed_levert_berichten_met_datum(fake_http):
    http = fake_http({"https://feed.test/rss.xml": "feed.xml"})
    items = fetch({"type": "feed", "url": "https://feed.test/rss.xml"}, Context(http=http))
    assert len(items) == 3
    first = items[0]
    assert first.title.startswith("Commission proposes European Business Wallets")
    assert first.published == "2025-11-19T11:00:00Z"
    assert first.summary == "Public sector bodies will accept business wallets to send and receive documents."


def test_feed_titel_prefix(fake_http):
    http = fake_http({"https://feed.test/rss.xml": "feed.xml"})
    source = {"type": "feed", "url": "https://feed.test/rss.xml", "titel_prefix": "ARF-release: "}
    assert fetch(source, Context(http=http))[0].title.startswith("ARF-release: Commission")


def test_html_automatisch_met_detailpagina(fake_http):
    http = fake_http({
        "https://site.test/news": "lijst.html",
        "https://site.test/news/we-build-joins-global-digital-collaboration-2026": "artikel.html",
    })
    source = {"type": "html", "url": "https://site.test/news", "link_patroon": "/news/[^/?#]+/?$", "detail": True}
    items = fetch(source, Context(http=http))
    titles = [i.title for i in items]
    assert titles == [
        "European business wallets: Council adopts negotiating position",
        "WE BUILD joins Global Digital Collaboration 2026",
        "MEPs back European business wallets to cut red tape",
        "Privacy statement for the news pages",
    ]
    council, collab, meps, _ = items
    # kop staat buiten de link; "Continue reading" mag geen titel worden
    assert meps.published == "2026-09-17"
    assert meps.summary == "The ITRE committee adopted its report on the business wallet."
    assert council.published == "2026-06-09"
    assert council.summary == "The Council agreed its position on the business wallet regulation."
    # geen datum op de lijstpagina: die komt van de berichtpagina
    assert collab.published == "2026-06-30T08:00:00Z"
    assert collab.summary == "Discover our sessions."


def test_html_link_uitsluiten(fake_http):
    http = fake_http({"https://site.test/news": "lijst.html"})
    source = {"type": "html", "url": "https://site.test/news", "link_patroon": "/news/[^/?#]+/?$",
              "link_uitsluiten": "privacy"}
    titles = [i.title for i in fetch(source, Context(http=http))]
    assert "Privacy statement for the news pages" not in titles and len(titles) == 3


def test_html_detail_alleen_voor_nieuwe_berichten(fake_http):
    http = fake_http({"https://site.test/news": "lijst.html"})
    known = {item_id("https://site.test/news/we-build-joins-global-digital-collaboration-2026"),
             item_id("https://site.test/news/privacy-statement")}
    source = {"type": "html", "url": "https://site.test/news", "link_patroon": "/news/[^/?#]+/?$", "detail": True}
    fetch(source, Context(http=http, known_ids=known))
    assert [url for url, _ in http.calls] == ["https://site.test/news"]


def test_html_met_selectors(fake_http):
    http = fake_http({"https://site.test/news": "lijst.html"})
    source = {"type": "html", "url": "https://site.test/news",
              "selectors": {"item": "div.card", "titel": "h3", "link": "a", "datum": "span.date"}}
    items = fetch(source, Context(http=http))
    assert [i.title for i in items][:2] == [
        "European business wallets: Council adopts negotiating position",
        "WE BUILD joins Global Digital Collaboration 2026",
    ]
    assert items[0].published == "2026-06-09"


def test_json_met_sjablonen(fake_http):
    http = fake_http({"https://tk.test/Document": "tk.json"})
    source = {
        "type": "json", "url": "https://tk.test/Document", "params": {"$top": 2}, "items": "value",
        "velden": {"titel": "{Soort}: {Onderwerp}",
                   "url": "https://www.tweedekamer.nl/downloads/document?id={DocumentNummer}",
                   "datum": "Datum", "samenvatting": "Titel"},
    }
    items = fetch(source, Context(http=http))
    assert items[0].title == "Brief regering: Fiche: Verordening Europese Business Wallet"
    assert items[0].url == "https://www.tweedekamer.nl/downloads/document?id=2026D01713"
    assert items[0].published == "2026-01-16"
    assert http.calls[0][1] == {"$top": 2}


def test_sparql_ontdubbelt_per_document(fake_http):
    http = fake_http({"https://sparql.test/": "sparql.json"})
    source = {
        "type": "sparql", "url": "https://sparql.test/", "dagen_terug": 30,
        "query": 'SELECT * WHERE { FILTER(?date >= "{since}"^^xsd:date) }',
        "velden": {"titel": "{title}", "url": "https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:{celex}",
                   "datum": "date"},
    }
    items = fetch(source, Context(http=http))
    assert len(items) == 2
    assert items[0].title.startswith("Commission Implementing Regulation (EU) 2024/2977")
    assert items[1].published == "2025-11-19"
    query = http.calls[0][1]["query"]
    assert "{since}" not in query and '"20' in query


def test_sru_officiele_bekendmakingen(fake_http):
    http = fake_http({"https://sru.test/sru": "sru.xml"})
    source = {"type": "sru", "url": "https://sru.test/sru", "query": 'cql.textAndIndexes="business wallet"'}
    items = fetch(source, Context(http=http))
    assert len(items) == 1
    assert items[0].title == "Fiche: Verordening Europese Business Wallet"
    assert items[0].url == "https://zoek.officielebekendmakingen.nl/kst-22112-4100.html"
    assert items[0].published == "2026-01-16"
    assert http.calls[0][1]["query"].endswith("sortBy dt.modified/sort.descending")


def test_pagewatch_meldt_alleen_echte_wijzigingen(fake_http):
    source = {"id": "train", "naam": "Train", "titel": "Legislative Train EBW", "type": "pagewatch",
              "url": "https://ep.test/train", "selector": "main"}
    state: dict = {}
    first = fetch(source, Context(http=fake_http({"https://ep.test/train": "pagina_v1.html"}), state=state))
    assert first == []  # eerste keer: alleen nulmeting
    same = fetch(source, Context(http=fake_http({"https://ep.test/train": "pagina_v1.html"}), state=state))
    assert same == []
    changed = fetch(source, Context(http=fake_http({"https://ep.test/train": "pagina_v2.html"}), state=state))
    assert len(changed) == 1
    assert changed[0].title == "Bijgewerkt: Legislative Train EBW"
    assert "ITRE adopted its report on 10 September 2026" in changed[0].summary
    assert "Menu" not in changed[0].summary  # header valt buiten de selector
    assert changed[0].url.startswith("https://ep.test/train#wijziging-")
    assert state["pagewatch"]["train"]["changed"]


def test_json_met_float_id_en_samenvattingssjabloon(fake_http):
    http = fake_http({"https://hys.test/search": "hys.json"})
    source = {
        "type": "json", "url": "https://hys.test/search", "items": "initiativeResultDtoPage.content",
        "velden": {"titel": "Consultatie: {shortTitle}",
                   "url": "https://ec.europa.eu/info/law/better-regulation/have-your-say/initiatives/{id}_en",
                   "datum": "currentStatuses.0.feedbackStartDate",
                   "samenvatting": "Feedback: {currentStatuses.0.receivingFeedbackStatus}. {snippet}"},
    }
    [item] = fetch(source, Context(http=http))
    assert item.url.endswith("/initiatives/16113_en")
    assert item.published == "2026-02-05T09:16:24Z"
    assert item.summary == "Feedback: CLOSED. registration of wallet -relying parties"


def test_feed_met_volledige_tekst(fake_http):
    http = fake_http({
        "https://moza.test/weekly/index.xml": "weekly.xml",
        "https://moza.test/weekly/moza-weekly-23-september-2026/": "weekly_post.html",
    })
    source = {"type": "feed", "url": "https://moza.test/weekly/index.xml", "volledige_tekst": True}
    known = {item_id("https://moza.test/weekly/moza-weekly-16-september-2026/")}
    items = fetch(source, Context(http=http, known_ids=known))
    assert "inloggen met de NL Wallet" in items[0].text
    assert "MOZa" not in items[0].text.split("MOZa Weekly")[0]  # header weggelaten
    assert items[1].text == ""  # bekend bericht: pagina niet opnieuw opgehaald


def test_ep_procedurestappen(fake_http):
    http = fake_http({"https://ep.test/procedures/2025-0358/events": "ep_events.json"})
    source = {"type": "ep_procedure", "url": "https://ep.test/procedures/2025-0358/events",
              "procedure": "2025/0358(COD)", "titel": "European business wallets", "hoofdcommissie": "ITRE"}
    items = fetch(source, Context(http=http))
    titles = [i.title for i in items]
    assert titles == [
        "Europees Parlement, European business wallets: voorstel doorverwezen naar de commissie",
        "Europees Parlement, European business wallets: commissie stelt verslag vast (ITRE)",
        "Europees Parlement, European business wallets: adviserende commissie stelt advies vast (IMCO)",
        "Europees Parlement, European business wallets: verslag ingediend voor de plenaire vergadering",
        "Europees Parlement, European business wallets: something new",
    ]  # amendementen worden standaard overgeslagen
    plenary = items[3]
    assert plenary.published == "2026-09-23"
    assert plenary.summary == "Procedure 2025/0358(COD). Document: A-10-2026-0240."
    assert plenary.url.endswith("reference=2025/0358(COD)#2025-0358-DEPOT-2026-09-23")
    assert http.calls[0][1] == {"format": "application/ld+json"}
