import json
import os
import shutil
from datetime import date, datetime, timezone

import pytest
import yaml

from scraper import weekmail
from scraper.store import NL_TZ
from scraper.weekmail import Laposta, LapostaFout, berichten_sinds, maak_mail, moza_tekst, tijdslot, week_info
from conftest import ROOT

UTC = timezone.utc
# Vrijdag 9 oktober 2026 valt in de zomertijd (UTC+2), vrijdag 6 november in de wintertijd (UTC+1).
ZOMER_VRIJDAG = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)   # 16:00 Nederlandse tijd
THEMAS = {
    "berichten": {"id": "berichten", "naam": "Berichtenverkeer & notificaties",
                  "moza_onderdelen": ["Berichtenbox voor bedrijven", "Notificatiedienst"]},
    "identiteit": {"id": "identiteit", "naam": "Inloggen, identificatie & vertegenwoordiging",
                   "moza_onderdelen": ["MOZa-portaal (inloggen)", "Machtigen"]},
}
ONDERWERPEN = {"ebw": "European Business Wallet", "eudi": "EUDI Wallet & eIDAS 2.0"}
CFG = {"site_url": "https://voorbeeld.github.io/Nieuwsbrief", "onderwerp": "Walletbrief week {week}: {berichten}",
       "max_berichten": 25}


def bericht(n, **extra):
    item = {
        "id": f"id{n}", "title": f"Bericht {n}", "url": f"https://bron.test/{n}", "summary": f"Samenvatting {n}.",
        "source": "bron", "source_name": "Bron", "category": "eu-commissie", "topics": ["ebw"],
        "topic_hits": {"ebw": ["business wallet"]}, "moza": [{"thema": "berichten", "termen": ["notificatie"]}],
        "moza_level": "middel", "score": 3, "first_seen": "2026-10-07T08:00:00Z", "date": "2026-10-07",
    }
    item.update(extra)
    return item


# --- tijdslot ---------------------------------------------------------------------

@pytest.mark.parametrize("utc, actie", [
    # zomertijd (UTC+2): de runs van 12:40 en 13:40 UTC plannen de mail in voor 16:00
    (datetime(2026, 10, 9, 12, 40, tzinfo=UTC), "inplannen"),
    (datetime(2026, 10, 9, 13, 40, tzinfo=UTC), "inplannen"),
    (datetime(2026, 10, 9, 13, 57, tzinfo=UTC), "nu"),          # bijna 16:00: direct
    (datetime(2026, 10, 9, 14, 40, tzinfo=UTC), "nu"),          # vertraagde run
    # wintertijd (UTC+1)
    (datetime(2026, 11, 6, 12, 40, tzinfo=UTC), "inplannen"),
    (datetime(2026, 11, 6, 13, 40, tzinfo=UTC), "inplannen"),
    (datetime(2026, 11, 6, 7, 0, tzinfo=UTC), "overslaan"),     # te vroeg
    (datetime(2026, 11, 6, 17, 50, tzinfo=UTC), "nu"),          # tot drie uur na 16:00
    (datetime(2026, 11, 6, 18, 30, tzinfo=UTC), "overslaan"),
    (datetime(2026, 10, 8, 13, 40, tzinfo=UTC), "overslaan"),   # donderdag
])
def test_tijdslot(utc, actie):
    gekozen, doel, reden = tijdslot(utc)
    assert gekozen == actie, reden
    if actie == "inplannen":
        assert doel.astimezone(NL_TZ).strftime("%A %H:%M") == "Friday 16:00"
        assert doel.astimezone(UTC).hour == (14 if utc.month == 10 else 15)  # zomer- of wintertijd
    else:
        assert doel is None


# --- selectie en opbouw -----------------------------------------------------------

def test_berichten_sinds_kiest_nieuwe_berichten_en_sorteert_op_relevantie():
    items = [
        bericht(1),
        bericht(2, moza_level="hoog", score=9),
        bericht(3, baseline=True),                                      # nulmeting
        bericht(4, first_seen="2026-10-01T08:00:00Z"),                  # al in vorige mail
        bericht(5, date="2026-09-01"),                                  # oud bericht van een nieuwe bron
        bericht(6, moza_level="laag", ai={"moza_relevantie": "hoog"}),  # AI-oordeel telt
    ]
    sinds = datetime(2026, 10, 2, 14, 0, tzinfo=UTC)
    gekozen = berichten_sinds(items, sinds, ZOMER_VRIJDAG)
    assert [i["id"] for i in gekozen] == ["id2", "id6", "id1"]


def test_week_info():
    assert week_info(date(2026, 10, 9)) == ("2026-41", 41, "5 – 11 oktober 2026")
    assert week_info(date(2026, 10, 1))[2] == "28 september – 4 oktober 2026"
    assert week_info(date(2027, 1, 1)) == ("2026-53", 53, "28 december 2026 – 3 januari 2027")


def test_moza_tekst_gebruikt_ai_of_themas():
    assert moza_tekst(bericht(1, ai={"moza_toelichting": "Raakt de Berichtenbox."}), THEMAS) == "Raakt de Berichtenbox."
    tekst = moza_tekst(bericht(1, moza=[{"thema": "berichten"}, {"thema": "identiteit"}]), THEMAS)
    assert tekst.startswith("Relevantie voor MOZa: middel. Raakt berichtenverkeer & notificaties en inloggen")
    assert "Berichtenbox voor bedrijven" in tekst and "Machtigen" in tekst
    assert "EBW-dossier in het algemeen" in moza_tekst(bericht(1, moza=[]), THEMAS)
    assert "Geen direct raakvlak" in moza_tekst(bericht(1, moza=[], topics=["eudi"], moza_level="laag"), THEMAS)


def test_mail_bevat_klikbare_titels_samenvatting_moza_en_afmeldlink():
    items = [
        bericht(1, title="Raad neemt <positie> in", url="https://raad.test/pb?a=1&b=2", moza_level="hoog"),
        bericht(2, category="nl-overheid", summary="", topic_hits={"ebw": ["EBW", "business wallet"]}),
        bericht(3, url="javascript:alert(1)", topics=["eudi"], ai={"samenvatting": "AI-samenvatting."}),
    ]
    onderwerp, inhoud = maak_mail(items, date(2026, 10, 9), CFG, THEMAS, ONDERWERPEN)

    assert onderwerp == "Walletbrief week 41: 3 berichten"
    # klikbare titel, met escaping van de titel en de link
    assert '<a href="https://raad.test/pb?a=1&amp;b=2"' in inhoud
    assert "Raad neemt &lt;positie&gt; in</a>" in inhoud
    assert 'href="#"' in inhoud and "javascript:" not in inhoud
    # samenvatting: van de bron, van de AI, of afgeleid uit de herkende termen
    assert "Samenvatting 1." in inhoud and "AI-samenvatting." in inhoud
    assert "Gaat over European Business Wallet (herkend aan: EBW, business wallet)." in inhoud
    # een heel korte brontekst ("Kamerstuk") krijgt de onderwerpen erbij
    _, kort = maak_mail([bericht(4, summary="Kamerstuk")], date(2026, 10, 9), CFG, THEMAS, ONDERWERPEN)
    assert "Kamerstuk. Gaat over European Business Wallet (herkend aan: business wallet)." in kort
    # MOZa-lens per bericht
    assert inhoud.count("Wat betekent dit voor MOZa?") == 3
    # link naar de volledige nieuwsbrief van deze week en afmelden
    assert 'href="https://voorbeeld.github.io/Nieuwsbrief/#editie-2026-41"' in inhoud
    assert 'href="/tag/unsubscribe"' in inhoud  # afmeldlink van Laposta
    # secties zoals op de site
    assert "European Business Wallet (1)" in inhoud and "EUDI Wallet &amp; eIDAS (1)" in inhoud
    assert "Nederland (1)" in inhoud
    assert "waarvan 1 met hoge relevantie" in inhoud


def test_mail_met_te_veel_of_geen_berichten():
    items = [bericht(n) for n in range(30)]
    _, inhoud = maak_mail(items, date(2026, 10, 9), {**CFG, "max_berichten": 25}, THEMAS)
    assert inhoud.count("Wat betekent dit voor MOZa?") == 25
    assert "En nog 5 andere berichten" in inhoud

    onderwerp, inhoud = maak_mail([], date(2026, 10, 9), CFG, THEMAS)
    assert onderwerp == "Walletbrief week 41: 0 berichten"
    assert "geen nieuwe berichten" in inhoud and "/tag/unsubscribe" in inhoud


# --- Laposta-client ---------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, data=None, auth=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "auth": auth})
        return self.responses.pop(0)


def test_laposta_client_stuurt_formuliervelden_zoals_de_api_verwacht():
    session = FakeSession(FakeResponse(201, {"campaign": {"campaign_id": "abc123"}}),
                          *[FakeResponse(200, {"campaign": {}}) for _ in range(4)])
    client = Laposta("geheim", session=session)
    assert client.maak_campagne("Naam", "Onderwerp", "Walletbrief", "nieuws@voorbeeld.nl", "lijst1") == "abc123"
    client.vul_inhoud("abc123", "<p>hoi</p>")
    client.testmail("abc123", "ik@voorbeeld.nl")
    client.verstuur("abc123")
    client.plan_in("abc123", datetime(2026, 10, 9, 16, 0, tzinfo=NL_TZ))

    maak, inhoud, test, verstuur, plan = session.calls
    assert maak["url"] == "https://api.laposta.nl/v2/campaign" and maak["method"] == "POST"
    assert maak["auth"] == ("geheim", "")
    assert dict(maak["data"]) == {"type": "regular", "name": "Naam", "subject": "Onderwerp",
                                  "from[name]": "Walletbrief", "from[email]": "nieuws@voorbeeld.nl",
                                  "list_ids[0]": "lijst1"}
    assert inhoud["url"].endswith("/campaign/abc123/content") and dict(inhoud["data"]) == {"html": "<p>hoi</p>"}
    assert test["url"].endswith("/campaign/abc123/action/testmail") and dict(test["data"]) == {"email": "ik@voorbeeld.nl"}
    assert verstuur["url"].endswith("/campaign/abc123/action/send")
    assert plan["url"].endswith("/campaign/abc123/action/schedule")
    assert dict(plan["data"]) == {"delivery_requested": "2026-10-09T16:00:00+02:00"}


def test_laposta_client_geeft_leesbare_fout():
    fout = {"error": {"type": "invalid_input", "message": "Email address not approved", "code": 208,
                      "parameter": "from[email]"}}
    client = Laposta("geheim", session=FakeSession(FakeResponse(400, fout)))
    with pytest.raises(LapostaFout, match=r"HTTP 400: Email address not approved \(parameter: from\[email\]\)"):
        client.maak_campagne("Naam", "Onderwerp", "Walletbrief", "x@voorbeeld.nl", "lijst1")


def test_laposta_campagnes():
    body = {"data": [{"campaign": {"campaign_id": "a", "name": "Walletbrief week 41 (2026)"}}, {"iets": 1}]}
    client = Laposta("geheim", session=FakeSession(FakeResponse(200, body)))
    assert client.campagnes() == [{"campaign_id": "a", "name": "Walletbrief week 41 (2026)"}]


# --- hoofdprogramma ---------------------------------------------------------------

class FakeLaposta:
    def __init__(self, bestaand=None, fout=None):
        self.bestaand = bestaand or []
        self.fout = fout
        self.calls = []

    def campagnes(self):
        self.calls.append(("campagnes",))
        return self.bestaand

    def maak_campagne(self, naam, onderwerp, afzender_naam, afzender_email, lijst_id):
        self.calls.append(("maak", naam, onderwerp, afzender_naam, afzender_email, lijst_id))
        if self.fout:
            raise LapostaFout(self.fout)
        return "c1"

    def vul_inhoud(self, campagne_id, inhoud):
        self.calls.append(("inhoud", campagne_id, inhoud))

    def testmail(self, campagne_id, email):
        self.calls.append(("testmail", campagne_id, email))

    def verstuur(self, campagne_id):
        self.calls.append(("verstuur", campagne_id))

    def plan_in(self, campagne_id, moment):
        self.calls.append(("plan_in", campagne_id, moment))

    def soorten(self):
        return [c[0] for c in self.calls]


def make_root(tmp_path, items, **cfg):
    config = tmp_path / "config"
    config.mkdir(parents=True)
    for name in ("bronnen.yaml", "onderwerpen.yaml", "achtergrond.yaml"):
        shutil.copy(os.path.join(ROOT, "config", name), config / name)
    instellingen = {"actief": True, "lijst_id": "lijst1", "afzender_naam": "Walletbrief",
                    "afzender_email": "nieuws@voorbeeld.nl", "site_url": "https://voorbeeld.github.io/Nieuwsbrief/",
                    "onderwerp": "Walletbrief week {week}: {berichten}", "ook_zonder_berichten": False}
    instellingen.update(cfg)
    (config / "notificaties.yaml").write_text(yaml.safe_dump(instellingen, allow_unicode=True), encoding="utf-8")
    (tmp_path / "site" / "data").mkdir(parents=True)
    (tmp_path / "site" / "data" / "items.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return tmp_path


def verstuurd(root):
    path = root / "data" / "weekmail.json"
    return json.loads(path.read_text(encoding="utf-8"))["verstuurd"] if path.exists() else {}


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("LAPOSTA_API_KEY", "geheim")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def test_versturen_verstuurt_een_keer_per_week(tmp_path):
    root = make_root(tmp_path, [bericht(1), bericht(2, first_seen="2026-09-20T08:00:00Z")])
    laposta = FakeLaposta()
    assert weekmail.main(["--modus", "versturen"], root=str(root), laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 0
    assert laposta.soorten() == ["campagnes", "maak", "inhoud", "verstuur"]
    maak = laposta.calls[1]
    assert maak[1:] == ("Walletbrief week 41 (2026)", "Walletbrief week 41: 1 bericht", "Walletbrief",
                        "nieuws@voorbeeld.nl", "lijst1")
    assert "Bericht 1" in laposta.calls[2][2] and "Bericht 2" not in laposta.calls[2][2]
    assert verstuurd(root) == {"2026-41": {"campagne_id": "c1", "verzending": "2026-10-09T14:00:00Z",
                                           "tot": "2026-10-07T08:00:00Z", "berichten": 1}}

    # tweede run in dezelfde week: niets
    tweede = FakeLaposta()
    assert weekmail.main(["--modus", "versturen"], root=str(root), laposta=tweede, klok=lambda: ZOMER_VRIJDAG) == 0
    assert tweede.calls == []


def test_volgende_week_alleen_berichten_na_vorige_mail(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    path = root / "site" / "data" / "items.json"
    path.write_text(json.dumps({"generated": "2026-10-09T12:41:00Z", "items": [bericht(1)]}), encoding="utf-8")
    assert weekmail.main([], root=str(root), laposta=FakeLaposta(), klok=lambda: ZOMER_VRIJDAG) == 0
    assert verstuurd(root)["2026-41"]["tot"] == "2026-10-09T12:41:00Z"

    # een week later: alleen wat na de vorige mail is gevonden
    nieuw = bericht(2, first_seen="2026-10-12T05:00:00Z", date="2026-10-12")
    path.write_text(json.dumps({"generated": "2026-10-16T12:41:00Z", "items": [nieuw, bericht(1)]}), encoding="utf-8")
    laposta = FakeLaposta()
    assert weekmail.main([], root=str(root), laposta=laposta, klok=lambda: datetime(2026, 10, 16, 14, tzinfo=UTC)) == 0
    html = laposta.calls[2][2]
    assert "Bericht 2" in html and "Bericht 1" not in html
    assert set(verstuurd(root)) == {"2026-41", "2026-42"}


def test_gepland_plant_in_voor_vier_uur(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    laposta = FakeLaposta()
    assert weekmail.main(["--modus", "gepland"], root=str(root), laposta=laposta,
                         klok=lambda: datetime(2026, 10, 9, 12, 42, tzinfo=UTC)) == 0
    assert laposta.soorten() == ["campagnes", "maak", "inhoud", "plan_in"]
    assert laposta.calls[3][2] == datetime(2026, 10, 9, 16, 0, tzinfo=NL_TZ)
    assert verstuurd(root)["2026-41"]["verzending"] == "2026-10-09T14:00:00Z"


def test_gepland_na_vier_uur_direct(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    laposta = FakeLaposta()
    assert weekmail.main(["--modus", "gepland"], root=str(root), laposta=laposta,
                         klok=lambda: datetime(2026, 10, 9, 14, 40, tzinfo=UTC)) == 0
    assert laposta.soorten() == ["campagnes", "maak", "inhoud", "verstuur"]


def test_gepland_slaat_over_buiten_het_tijdslot(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    laposta = FakeLaposta()
    donderdag = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)
    assert weekmail.main(["--modus", "gepland"], root=str(root), laposta=laposta, klok=lambda: donderdag) == 0
    assert laposta.calls == [] and verstuurd(root) == {}


def test_niets_versturen_als_het_uit_staat_of_er_geen_berichten_zijn(tmp_path):
    root = make_root(tmp_path, [bericht(1)], actief=False)
    laposta = FakeLaposta()
    assert weekmail.main([], root=str(root), laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 0
    assert laposta.calls == []

    leeg = make_root(tmp_path / "leeg", [bericht(1, first_seen="2026-09-01T08:00:00Z")])
    assert weekmail.main([], root=str(leeg), laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 0
    assert laposta.calls == []


def test_ontbrekende_instellingen_geven_een_fout(tmp_path, monkeypatch):
    root = make_root(tmp_path, [bericht(1)], lijst_id="")
    laposta = FakeLaposta()
    assert weekmail.main([], root=str(root), laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 1
    monkeypatch.delenv("LAPOSTA_API_KEY")
    andere = make_root(tmp_path / "zonder-sleutel", [bericht(1)])
    assert weekmail.main(["--modus", "test", "--testadres", "ik@voorbeeld.nl"], root=str(andere),
                         laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 1
    assert laposta.calls == []


def test_fout_van_laposta_laat_de_week_open(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    laposta = FakeLaposta(fout="Laposta-API gaf HTTP 400: Email address not approved")
    assert weekmail.main([], root=str(root), laposta=laposta, klok=lambda: ZOMER_VRIJDAG) == 1
    assert verstuurd(root) == {}


def test_testmail_gaat_alleen_naar_het_testadres(tmp_path):
    root = make_root(tmp_path, [bericht(1)], actief=False)
    laposta = FakeLaposta()
    assert weekmail.main(["--modus", "test", "--testadres", "ik@voorbeeld.nl"], root=str(root), laposta=laposta,
                         klok=lambda: ZOMER_VRIJDAG) == 0
    assert laposta.soorten() == ["maak", "inhoud", "testmail"]
    assert laposta.calls[0][1] == "Walletbrief week 41 (2026) – test 09-10 16:00"
    assert laposta.calls[2] == ("testmail", "c1", "ik@voorbeeld.nl")
    assert verstuurd(root) == {}
    assert weekmail.main(["--modus", "test", "--testadres", "geen-adres"], root=str(root),
                         laposta=FakeLaposta(), klok=lambda: ZOMER_VRIJDAG) == 1


def test_al_verstuurd_volgens_laposta(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    eerder = [{"campaign_id": "oud", "name": "Walletbrief week 41 (2026)", "created": "2026-10-09 14:41:02",
               "delivery_requested": "2026-10-09 16:00:00"},
              {"campaign_id": "test", "name": "Walletbrief week 41 (2026) – test 09-10 10:00", "delivery_requested": ""}]
    laposta = FakeLaposta(bestaand=eerder)
    assert weekmail.main(["--modus", "gepland"], root=str(root), laposta=laposta,
                         klok=lambda: datetime(2026, 10, 9, 13, 40, tzinfo=UTC)) == 0
    assert laposta.soorten() == ["campagnes"]
    assert verstuurd(root)["2026-41"] == {"campagne_id": "oud", "verzending": "2026-10-09T14:00:00Z",
                                          "tot": "2026-10-09T12:41:02Z", "berichten": None}


def test_forceer_verstuurt_deze_week_opnieuw(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    assert weekmail.main([], root=str(root), laposta=FakeLaposta(), klok=lambda: ZOMER_VRIJDAG) == 0
    laposta = FakeLaposta()
    later = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)
    assert weekmail.main(["--forceer"], root=str(root), laposta=laposta, klok=lambda: later) == 0
    assert laposta.soorten() == ["maak", "inhoud", "verstuur"]
    assert laposta.calls[0][1] == "Walletbrief week 41 (2026) – opnieuw 09-10 17:00"
    assert "Bericht 1" in laposta.calls[1][2]


def test_voorbeeld_schrijft_html(tmp_path):
    root = make_root(tmp_path, [bericht(1)])
    doel = tmp_path / "mail.html"
    assert weekmail.main(["--voorbeeld", str(doel)], root=str(root), laposta=FakeLaposta(),
                         klok=lambda: ZOMER_VRIJDAG) == 0
    assert "Bericht 1" in doel.read_text(encoding="utf-8")
