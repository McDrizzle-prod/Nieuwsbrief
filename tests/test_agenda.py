import json
import os
import shutil
from datetime import date, datetime, time, timezone

import pytest
import yaml

from scraper import agenda, run as run_module
from scraper.agenda import (
    RawEvent, ontdubbelen, parse_ical, periode_uit_tekst, samenvoegen, site_agenda, zoek_periode, zoek_tijden,
)
from scraper.classify import Classifier
from scraper.fetchers import Context
from scraper.run import load_config
from conftest import ROOT

NU = "2026-10-06T05:00:00Z"
VANDAAG = date(2026, 10, 6)
EUDI_PAGINA = "https://ec.europa.eu/digital-building-blocks/sites/spaces/EUDIGITALIDENTITYWALLET/pages/694497147/Events"

BRONNEN = [
    {"id": "do", "naam": "Digitale Overheid", "categorie": "nl-overheid", "type": "ical",
     "url": "https://www.digitaleoverheid.nl/events.ics", "site": "https://www.digitaleoverheid.nl/evenementen/",
     "filter": True, "detail": True, "prioriteit": 1},
    {"id": "gc", "naam": "Gebruiker Centraal", "categorie": "nl-overheid", "type": "ical",
     "url": "https://www.gebruikercentraal.nl/events.ics", "filter": True, "prioriteit": 1},
    {"id": "svdu", "naam": "Staat van de Uitvoering", "categorie": "nl-overheid", "type": "html",
     "url": "https://staatvandeuitvoering.nl/agenda/", "link_patroon": "/evenement/[^/]+/?$", "filter": True,
     "detail": True, "prioriteit": 2},
    {"id": "ecp", "naam": "ECP", "categorie": "derden", "type": "html", "url": "https://ecp.nl/agenda/",
     "link_patroon": "/agenda/[^/]+/?$", "filter": True, "prioriteit": 1},
    {"id": "ebra", "naam": "EBRA", "categorie": "derden", "type": "tribe",
     "url": "https://ebra.be/wp-json/tribe/events/v1/events", "filter": True},
    {"id": "tk", "naam": "Tweede Kamer", "categorie": "nl-overheid", "type": "tk_activiteiten",
     "url": "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Activiteit", "params": {"$top": 50}, "filter": True,
     "prioriteit": 1},
    {"id": "eudi", "naam": "EUDI Wallet (Commissie)", "categorie": "eu", "type": "eudi_evenementen",
     "url": EUDI_PAGINA, "standaard_onderwerp": "eudi", "prioriteit": 1},
    {"id": "uit", "naam": "Uitgezet", "categorie": "derden", "type": "ical", "url": "https://uit.test/a.ics",
     "actief": False},
]
ROUTES = {
    "https://www.digitaleoverheid.nl/events.ics": "agenda/digitale_overheid.ics",
    "https://www.digitaleoverheid.nl/evenementen/logius-roadshow/": "agenda/logius.html",
    "https://www.digitaleoverheid.nl/evenementen/webinar-wat-is-het-federatief-datastelsel/": "agenda/datastelsel.html",
    "https://www.gebruikercentraal.nl/events.ics": "agenda/gebruiker_centraal.ics",
    "https://staatvandeuitvoering.nl/agenda/": "agenda/svdu_agenda.html",
    "https://staatvandeuitvoering.nl/evenement/europese-id-wallet-conferentie-unfold5/": "agenda/svdu_unfold.html",
    "https://ecp.nl/agenda/": "agenda/ecp_agenda.html",
    "https://ebra.be/wp-json/tribe/events/v1/events": "agenda/ebra.json",
    "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Activiteit": "agenda/tk.json",
    EUDI_PAGINA: "agenda/eudi_events.html",
}


@pytest.fixture
def classifier():
    return Classifier(load_config()["onderwerpen"])


def ophalen(fake_http, classifier, archive=None, previous=None, handmatig=None, now=NU, routes=ROUTES):
    config = {"agenda": {"bronnen": BRONNEN, "handmatig": handmatig or []}}
    ctx = Context(http=fake_http(routes), state={})
    merged, added, statuses = agenda.bijwerken(config, ctx, classifier, archive or [], previous or {}, now)
    return merged, added, {s["id"]: s for s in statuses}, ctx


def per_titel(events):
    return {e["title"]: e for e in events}


# --- datums uit tekst ----------------------------------------------------------------

@pytest.mark.parametrize("tekst, start, eind", [
    ("7 en 8 oktober 2026", date(2026, 10, 7), date(2026, 10, 8)),
    ("18 t/m 19 nov 2026", date(2026, 11, 18), date(2026, 11, 19)),
    ("7 oktober 2026 t/m 8 oktober 2026", date(2026, 10, 7), date(2026, 10, 8)),
    ("30 september - 1 oktober 2026", date(2026, 9, 30), date(2026, 10, 1)),
    ("29-30 october, 2026 - THE EGG, BRUSSELS", date(2026, 10, 29), date(2026, 10, 30)),
    ("10-11-12 December 2025 Sparks, Brussels", date(2025, 12, 10), date(2025, 12, 12)),
    ("October 29-30, 2026", date(2026, 10, 29), date(2026, 10, 30)),
    ("28 okt 2026", date(2026, 10, 28), None),
    ("13 november 2026, 11:00 - 17:30 uur en 14 november 2026, 09:30 - 16:30 uur",
     date(2026, 11, 13), date(2026, 11, 14)),
    ("Aanmelden kan tot 1 oktober 2026. Datum volgt.", date(2026, 10, 1), None),
    ("geen datum hier", None, None),
])
def test_zoek_periode(tekst, start, eind):
    assert zoek_periode(tekst) == (start, eind)


def test_zoek_tijden():
    assert zoek_tijden("Tijd: 09.30 – 17.00 uur") == (time(9, 30), time(17, 0))
    assert zoek_tijden("Aanvang Begintijd 09.30 - einde 16.30 uur") == (time(9, 30), time(16, 30))
    assert zoek_tijden("Aanvang: 13:00 uur") == (time(13, 0), None)
    assert zoek_tijden("Datum 07.10.2026") == (None, None)


def test_periode_uit_tekst_met_label_en_tijden():
    tekst = ("Op 7 en 8 oktober 2026 vindt UNFOLD plaats. Praktische informatie Datum: 7 en 8 oktober 2026 "
             "Tijd: 09.30 – 17.00 uur Locatie: Pathé Nijmegen")
    assert periode_uit_tekst(tekst) == ("2026-10-07T09:30:00+02:00", "2026-10-08T17:00:00+02:00")
    assert periode_uit_tekst("Datum / Tijd: 29 oktober 2026 Hele dag") == ("2026-10-29", None)
    assert agenda.locatie_uit_tekst("7 oktober 2026 Locatie Pathé Nijmegen Doelgroep Iedereen") == "Pathé Nijmegen"


def test_parse_ical_vouwen_en_escapes():
    with open(os.path.join(ROOT, "tests", "fixtures", "agenda", "digitale_overheid.ics"), encoding="utf-8") as fh:
        events = parse_ical(fh.read())
    assert len(events) == 5
    assert events[0]["DESCRIPTION"][0].endswith("Large Scale Pilots\\, met workshops over de NL Wallet.")
    assert events[0]["DTSTART"] == ("20261023T124500", {"TZID": "Europe/Amsterdam"})


# --- bronnen ------------------------------------------------------------------------

def test_bronnen_ophalen_en_indelen(fake_http, classifier):
    merged, added, status, _ = ophalen(fake_http, classifier)
    titels = per_titel(merged)

    # iCal: tijdzone, hele dag (DTEND exclusief), UTC, Teams-link als locatie, geannuleerd weg
    meetup = titels["Meet-up EDI-stelsel en BLSP"]
    assert meetup["start"] == "2026-10-23T12:45:00+02:00" and meetup["end"] == "2026-10-23T18:00:00+02:00"
    assert meetup["wallets"] == ["eudi"] and meetup["location"].endswith("Rotterdam, Nederland")
    roadshow = titels["Logius Roadshow"]  # alleen via de tekst van de evenementpagina
    assert roadshow["start"] == "2026-10-29" and roadshow["end"] is None and roadshow["wallets"] == ["eudi"]
    assert "NL Wallet" in roadshow["fragment"]
    webinar = titels["Webinar: de European Business Wallet voor gemeenten"]
    assert webinar["start"] == "2026-11-10T14:00:00+01:00" and webinar["online"] and webinar["location"] == "Online"
    assert webinar["wallets"] == ["ebw"]
    assert "Webinar: Wat is het Federatief Datastelsel" not in titels  # zijbalk telt niet mee
    assert not any("geannuleerd" in t for t in titels)

    # HTML met detailpagina: datum uit het overzicht, tijd en einddatum van de pagina
    svdu = [e for e in merged if e["source"] == "svdu"]
    assert [e["title"] for e in svdu] == ["Europese ID-wallet conferentie UNFOLD#5"]
    assert svdu[0]["start"] == "2026-10-07T09:30:00+02:00" and svdu[0]["end"] == "2026-10-08T17:00:00+02:00"
    assert svdu[0]["location"] == "Pathé Nijmegen"

    # ECP: gegevens uit het agendablok, titel niet de datumkop
    ecp = titels["Symposium: De European Business Wallet in de praktijk"]
    assert ecp["start"] == "2026-11-17T13:00:00+01:00" and ecp["location"] == "Jaarbeurs MeetUp, Utrecht"
    assert ecp["url"] == "https://ecp.nl/agenda/symposium-de-european-business-wallet-in-de-praktijk/"
    assert "Nederland Digitaal Festival" not in titels

    # WordPress-agenda: hele dag, alleen het EBW-evenement
    ebra = titels["Kick-off meeting European Business Wallet (Luxembourg/Online)"]
    assert (ebra["start"], ebra["end"], ebra["online"]) == ("2026-10-20", "2026-10-21", True)
    assert not any("Reception" in t for t in titels)

    # Tweede Kamer: agendapunten tellen mee; procedurevergadering en geannuleerd niet
    assert titels["Rondetafelgesprek: European Business Wallet"]["location"] == "Tweede Kamer, Den Haag (Thorbeckezaal)"
    debat = titels["Commissiedebat: Digitale overheid"]
    assert debat["wallets"] == ["eudi"] and "EDI-stelsel" in debat["fragment"]
    assert debat["url"].endswith("commissievergaderingen/details?id=2026A06002")
    assert not any(t.startswith(("Procedurevergadering", "Technische briefing")) for t in titels)

    # Commissie: titel netjes, tijden, afgelopen evenement niet in het archief
    launchpad = titels["EUDI Wallets Launchpad 2.0"]
    assert (launchpad["start"], launchpad["end"], launchpad["location"]) == ("2026-10-29", "2026-10-30", "The Egg, Brussels")
    dev = titels["Developers Community Webinar"]
    assert dev["start"] == "2026-11-12T10:00:00+01:00" and dev["end"] == "2026-11-12T11:30:00+01:00" and dev["online"]
    assert not any(e["start"].startswith("2025") for e in merged)

    assert status["do"]["ok"] and status["do"]["gevonden"] == 4 and status["do"]["relevant"] == 3
    assert status["uit"]["actief"] is False and status["uit"]["laatst_gecontroleerd"] is None
    assert len(added) == len(merged)


def test_kapotte_bron_houdt_rest_niet_tegen(fake_http, classifier):
    routes = {k: v for k, v in ROUTES.items() if "ebra" not in k}
    merged, _, status, _ = ophalen(fake_http, classifier, routes=routes)
    assert status["ebra"]["ok"] is False and "404" in status["ebra"]["fout"]
    assert status["do"]["ok"] and merged


def test_detailpaginas_worden_bewaard(fake_http, classifier):
    _, _, _, ctx = ophalen(fake_http, classifier)
    cache = ctx.state["agenda_paginas"]
    assert cache["https://www.digitaleoverheid.nl/evenementen/logius-roadshow/"]["t"] == "2026-10-06"
    # tweede run met dezelfde state: geen detailpagina's opnieuw ophalen
    http = fake_http(ROUTES)
    config = {"agenda": {"bronnen": BRONNEN}}
    agenda.bijwerken(config, Context(http=http, state=ctx.state), classifier, [], {}, NU)
    assert not any("logius-roadshow" in url for url, _ in http.calls)


# --- archief ---------------------------------------------------------------------------

def test_samenvoegen_bewaart_first_seen_en_ruimt_op(fake_http, classifier):
    eerste, _, _, _ = ophalen(fake_http, classifier)
    later = "2026-10-20T05:00:00Z"
    tweede, nieuw, _, _ = ophalen(fake_http, classifier, archive=eerste, now=later)
    assert nieuw == []
    oud = per_titel(eerste)
    for event in tweede:
        assert event["first_seen"] == oud[event["title"]]["first_seen"]
    # 20 oktober: UNFOLD (7-8 okt) is meer dan een week voorbij en weg
    assert "Europese ID-wallet conferentie UNFOLD#5" not in per_titel(tweede)

    # een evenement dat een werkende bron niet meer aanbiedt, verdwijnt na een week
    weg = {**oud["Meet-up EDI-stelsel en BLSP"], "id": "verdwenen", "last_seen": "2026-10-10T05:00:00Z"}
    kept, _ = samenvoegen([weg], [], "2026-10-18T05:00:00Z", {"do"}, {"do"}, date(2026, 10, 18))
    assert kept == []
    kept, _ = samenvoegen([weg], [], "2026-10-18T05:00:00Z", set(), {"do"}, date(2026, 10, 18))
    assert kept == [weg]  # bron werkte niet: blijven staan
    kept, _ = samenvoegen([weg], [], "2026-10-18T05:00:00Z", {"do"}, {"ander"}, date(2026, 10, 18))
    assert kept == []  # bron niet meer in de configuratie


def test_ontdubbelen_en_site(fake_http, classifier):
    merged, _, statuses, _ = ophalen(fake_http, classifier)
    site = site_agenda(merged, list(statuses.values()), {"agenda": {"categorieen": {"eu": "EU"}}}, NU)
    unfold = [e for e in site["evenementen"] if "UNFOLD" in e["title"]]
    assert len(unfold) == 1
    assert unfold[0]["source"] == "gc"  # prioriteit 1 wint
    assert unfold[0]["also"] == [{"source_name": "Staat van de Uitvoering",
                                  "url": "https://staatvandeuitvoering.nl/evenement/europese-id-wallet-conferentie-unfold5/"}]
    assert unfold[0]["location"] == "Pathé Nijmegen, Nijmegen"
    assert all("last_seen" not in e and "priority" not in e for e in site["evenementen"])
    assert [w["id"] for w in site["wallets"]] == ["eudi", "ebw"]
    assert site["evenementen"] == sorted(site["evenementen"], key=lambda e: (e["start"], e["title"]))


def test_ontdubbelen_vult_aan_en_combineert_wallets():
    a = {"id": "a", "title": "Symposium: De European Business Wallet (EBW)", "start": "2026-11-17", "end": None,
         "location": "", "online": False, "summary": "", "source_name": "Digitale Overheid", "url": "https://a",
         "wallets": ["ebw"], "first_seen": "2026-10-02T05:00:00Z", "priority": 1}
    b = {"id": "b", "title": "Symposium: ‘De European Business Wallet - Op naar eenvoudigere dienstverlening’",
         "start": "2026-11-17T13:00:00+01:00", "end": "2026-11-17T17:30:00+01:00", "location": "Utrecht",
         "online": False, "summary": "Over EBW en EUDI.", "source_name": "ECP", "url": "https://b",
         "wallets": ["eudi", "ebw"], "first_seen": "2026-10-01T05:00:00Z", "priority": 2}
    [samen] = ontdubbelen([b, a])
    assert samen["id"] == "a" and samen["start"] == "2026-11-17T13:00:00+01:00" and samen["location"] == "Utrecht"
    assert samen["wallets"] == ["eudi", "ebw"] and samen["first_seen"] == "2026-10-01T05:00:00Z"
    assert samen["also"] == [{"source_name": "ECP", "url": "https://b"}]
    andere_dag = {**b, "id": "c", "start": "2026-11-18"}
    assert len(ontdubbelen([a, andere_dag])) == 2


def test_handmatige_evenementen(fake_http, classifier):
    handmatig = [
        {"titel": "Business Wallets in Action", "start": "2026-11-24 13:00", "eind": "2026-11-24 18:00",
         "locatie": "Utrecht", "organisator": "FIDES", "wallets": ["ebw"], "url": "https://fides.community/x/"},
        {"titel": "Bijeenkomst zonder link over de EUDI Wallet", "start": date(2026, 12, 1)},
        {"titel": "Iets anders", "start": "2026-12-02"},
    ]
    merged, _, _, _ = ophalen(fake_http, classifier, handmatig=handmatig)
    titels = per_titel(merged)
    fides = titels["Business Wallets in Action"]
    assert fides["source_name"] == "FIDES" and fides["start"] == "2026-11-24T13:00:00+01:00" and fides["wallets"] == ["ebw"]
    assert titels["Bijeenkomst zonder link over de EUDI Wallet"]["wallets"] == ["eudi"]
    assert "Iets anders" not in titels


# --- hele run ---------------------------------------------------------------------------

def test_run_schrijft_agenda(tmp_path, fake_http, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_module, "now_utc", lambda: datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc))
    config = tmp_path / "config"
    config.mkdir()
    for name in ("onderwerpen.yaml", "achtergrond.yaml"):
        shutil.copy(os.path.join(ROOT, "config", name), config / name)
    (config / "bronnen.yaml").write_text(yaml.safe_dump({"categorieen": {}, "bronnen": []}), encoding="utf-8")
    (config / "agenda.yaml").write_text(yaml.safe_dump({"categorieen": {"eu": "Europese instellingen"},
                                                        "bronnen": BRONNEN[:2]}), encoding="utf-8")
    assert run_module.run(["--geen-ai"], root=str(tmp_path), http=fake_http(ROUTES)) == 0
    site = json.loads((tmp_path / "site/data/agenda.json").read_text(encoding="utf-8"))
    assert {e["title"] for e in site["evenementen"]} >= {"Meet-up EDI-stelsel en BLSP", "Logius Roadshow"}
    assert site["categorieen"] == {"eu": "Europese instellingen"}
    assert [s["id"] for s in site["bronnen"]] == ["do", "gc"]
    archief = json.loads((tmp_path / "data/agenda.json").read_text(encoding="utf-8"))
    assert all("last_seen" in e for e in archief["evenementen"])
    assert "agenda_paginas" in json.loads((tmp_path / "data/state.json").read_text(encoding="utf-8"))


def test_raw_event_standaardwaarden():
    event = RawEvent(title="t", url="https://x")
    assert (event.start, event.location, event.online) == (None, "", False)


def test_fout_in_de_agenda_houdt_de_nieuwsbrief_niet_tegen(tmp_path, fake_http, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("onderwerpen.yaml", "achtergrond.yaml"):
        shutil.copy(os.path.join(ROOT, "config", name), config / name)
    (config / "bronnen.yaml").write_text(yaml.safe_dump({"categorieen": {}, "bronnen": []}), encoding="utf-8")
    (config / "agenda.yaml").write_text("bronnen:\n  - id: kapot\n", encoding="utf-8")  # naam, type en url ontbreken
    assert run_module.run(["--geen-ai"], root=str(tmp_path), http=fake_http({})) == 0
    assert (tmp_path / "site/data/items.json").exists()
    assert not (tmp_path / "site/data/agenda.json").exists()


def test_handmatig_slaat_rommel_over():
    assert agenda.handmatige_evenementen(["tekst", {"titel": "Zonder datum"}, None]) == []
