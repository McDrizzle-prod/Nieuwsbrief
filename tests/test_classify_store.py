from datetime import date

import yaml

from scraper.classify import Classifier, compile_term
from scraper.store import display_date, merge, prune
from scraper.util import parse_date
from conftest import ROOT


def classifier():
    with open(f"{ROOT}/config/onderwerpen.yaml", encoding="utf-8") as fh:
        return Classifier(yaml.safe_load(fh))


def test_zoektermen():
    assert compile_term("business wallet").search("European Business Wallets")
    assert compile_term("EBW").search("de EBW-verordening")
    assert not compile_term("EBW").search("ebw")
    assert not compile_term("EUDI").search("EUDIW")
    assert compile_term("notificati*").search("Notificatiedienst")
    assert not compile_term("LEI").search("Leiden")
    assert not compile_term("WE BUILD").search("we build trust")
    assert compile_term("re:2025/0358").search("2025/0358(COD)")


def test_filter_houdt_irrelevante_berichten_buiten():
    c = classifier()
    assert c.classify("Gigabit Infrastructure Act", "Faster networks.", {"filter": True}) is None
    hit = c.classify("Council adopts position on European business wallets",
                     "Public sector bodies must accept wallets to send and receive documents via QERDS.",
                     {"filter": True, "prioriteit": 1})
    assert hit["topics"][0] == "ebw"
    assert {m["thema"] for m in hit["moza"]} >= {"berichten", "verplichtingen"}
    assert hit["moza_level"] == "hoog"


def test_standaardonderwerp_bij_ongefilterde_bron():
    c = classifier()
    hit = c.classify("v2.6.0", "", {"filter": False, "standaard_onderwerp": "eudi", "prioriteit": 2})
    assert hit["topics"] == ["eudi"]
    assert hit["moza_level"] == "laag"


def test_datums():
    assert parse_date("10 september 2026") == "2026-09-10"
    assert parse_date("9 June 2026") == "2026-06-09"
    assert parse_date("05/10/2026") == "2026-10-05"
    assert parse_date("2026-10-05") == "2026-10-05"
    assert parse_date("2026-01-16T00:00:00+01:00") == "2026-01-16"
    assert parse_date("2026-06-30T10:00:00+02:00") == "2026-06-30T08:00:00Z"
    assert parse_date("geen datum") is None


def test_weergavedatum():
    # aankondiging van een toekomstig evenement hoort in de week waarin we hem vonden
    assert display_date("2026-12-01", "2026-10-05T06:00:00Z") == "2026-10-05"
    assert display_date("2026-06-09", "2026-10-05T06:00:00Z") == "2026-06-09"
    assert display_date(None, "2026-10-04T23:30:00Z") == "2026-10-05"  # Nederlandse tijd


def item(id_, title, source, published="2026-10-01", url=None):
    return {"id": id_, "title": title, "url": url or f"https://x.test/{id_}", "summary": "",
            "published": published, "source": source, "source_name": source, "category": "eu-raad",
            "topics": ["ebw"], "moza": [], "moza_level": "middel", "score": 3}


def test_merge_ontdubbelt_op_id_en_titel():
    archive, added = merge([], [item("a", "European business wallets: Council adopts negotiating position", "raad")],
                           "2026-10-05T06:00:00Z")
    assert len(added) == 1 and added[0]["first_seen"] == "2026-10-05T06:00:00Z"
    again = item("a", "European business wallets: Council adopts negotiating position", "raad")
    twin = item("b", "European Business Wallets – Council adopts negotiating position!", "we-build", "2026-10-03")
    archive, added = merge(archive, [again, twin], "2026-10-06T06:00:00Z")
    assert added == []
    assert len(archive) == 1
    assert archive[0]["first_seen"] == "2026-10-05T06:00:00Z"
    assert archive[0]["also"][0]["source"] == "we-build"


def test_merge_houdt_paginawijzigingen_apart():
    first = item("p1", "Bijgewerkt: Legislative Train – European business wallets", "train", "2026-10-01")
    second = item("p2", "Bijgewerkt: Legislative Train – European business wallets", "train", "2026-10-03")
    archive, _ = merge([], [first], "2026-10-01T06:00:00Z")
    archive, added = merge(archive, [second], "2026-10-03T06:00:00Z")
    assert len(archive) == 2 and len(added) == 1


def test_prune():
    old = item("old", "Oud bericht over de EUDI Wallet uit 2023", "x", "2023-01-01")
    new = item("new", "Nieuw bericht over de business wallet", "x", "2026-10-01")
    archive, _ = merge([], [old, new], "2026-10-05T06:00:00Z")
    kept = prune(archive, date(2026, 10, 5), keep_days=730)
    assert [i["id"] for i in kept] == ["new"]


def test_fragment_met_relevante_zinnen():
    c = classifier()
    text = ("We hielden een teamdag. In de proefomgeving kun je nu inloggen met de NL Wallet. "
            "We onderzoeken hoe de Yivi Business Wallet zich daartoe verhoudt. Verder werkten we aan iets anders.")
    fragment = c.excerpt(text)
    assert fragment.startswith("In de proefomgeving kun je nu inloggen met de NL Wallet.")
    assert "Yivi Business Wallet" in fragment and "teamdag" not in fragment
    hit = c.classify("MOZa Weekly 23 september 2026", fragment, {"filter": True, "prioriteit": 1})
    assert hit is not None and "ebw" in hit["topics"] and "eudi" in hit["topics"]


def test_sjabloonfilters():
    from scraper.util import fill_template
    record = {"s": {"start": "2026/03/11 19:06:02", "eind": "2026/05/06 23:59:59", "status": "CLOSED"},
              "leeg": {"start": "2025/06/02 19:08:17", "eind": "", "status": "DISABLED"}}
    assert fill_template("Periode {s.start|datum} – {s.eind|datum} ({s.status|nl}).", record) == \
        "Periode 11 maart 2026 – 6 mei 2026 (gesloten)."
    assert fill_template("Periode {leeg.start|datum} – {leeg.eind|datum} ({leeg.status|nl}).", record) == \
        "Periode 2 juni 2025 (niet opengesteld)."


def test_fragment_uit_lange_agenda():
    c = classifier()
    agenda = ("MOZa teamdag - 8 september Regieteam - 9 september Stuurgroep - 25 september Evenementen "
              "Common Ground Fieldlab - 14 september met een sessie over de notificatiedienst "
              + "en nog meer agendapunten " * 10
              + "Symposium De European Business Wallet - 30 september in Den Haag " + "en verder " * 30)
    fragment = c.excerpt(agenda)
    assert "European Business Wallet" in fragment
    assert fragment.startswith("… ") and fragment.endswith(" …") and len(fragment) < 300
