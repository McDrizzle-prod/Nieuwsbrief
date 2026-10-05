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
