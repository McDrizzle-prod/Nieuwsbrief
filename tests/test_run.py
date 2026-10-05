import json
import os
import shutil
from types import SimpleNamespace

import yaml

from scraper import enrich
from scraper.run import load_config, run
from conftest import ROOT

BRONNEN = {
    "categorieen": {"eu-commissie": "Europese Commissie", "pilots": "Large Scale Pilots"},
    "bronnen": [
        {"id": "ec", "naam": "Commissie", "categorie": "eu-commissie", "type": "feed",
         "url": "https://feed.test/rss.xml", "filter": True, "prioriteit": 1},
        {"id": "webuild", "naam": "WE BUILD", "categorie": "pilots", "type": "html",
         "url": "https://site.test/news", "link_patroon": "/news/[^/?#]+/?$", "detail": True,
         "standaard_onderwerp": "ebw", "prioriteit": 1},
        {"id": "kapot", "naam": "Kapotte bron", "categorie": "pilots", "type": "feed",
         "url": "https://bestaat.niet/feed", "filter": True},
        {"id": "uit", "naam": "Uitgezet", "categorie": "pilots", "type": "feed",
         "url": "https://uit.test/feed", "actief": False},
    ],
}
ROUTES = {
    "https://feed.test/rss.xml": "feed.xml",
    "https://site.test/news": "lijst.html",
    "https://site.test/news/we-build-joins-global-digital-collaboration-2026": "artikel.html",
}


def make_root(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name in ("onderwerpen.yaml", "achtergrond.yaml"):
        shutil.copy(os.path.join(ROOT, "config", name), config / name)
    (config / "bronnen.yaml").write_text(yaml.safe_dump(BRONNEN, allow_unicode=True), encoding="utf-8")
    return tmp_path


def test_volledige_run(tmp_path, fake_http, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    root = make_root(tmp_path)
    assert run(["--geen-ai"], root=str(root), http=fake_http(ROUTES)) == 0

    items = json.loads((root / "site/data/items.json").read_text(encoding="utf-8"))["items"]
    titles = {i["title"] for i in items}
    assert "Gigabit Infrastructure Act enters into application" not in titles  # weggefilterd
    assert "Commission proposes European Business Wallets to simplify business operations" in titles
    assert "WE BUILD joins Global Digital Collaboration 2026" in titles
    assert all(i["date"] and i["first_seen"] for i in items)

    status = {s["id"]: s for s in json.loads((root / "site/data/status.json").read_text())["bronnen"]}
    assert status["ec"]["ok"] and status["ec"]["gevonden"] == 3 and status["ec"]["relevant"] == 2
    assert status["kapot"]["ok"] is False and "404" in status["kapot"]["fout"]
    assert status["uit"]["actief"] is False and status["uit"]["laatst_gecontroleerd"] is None

    site_config = json.loads((root / "site/data/config.json").read_text(encoding="utf-8"))
    assert site_config["moza_themas"][0]["id"] == "berichten"
    assert site_config["achtergrond"]["dossiers"][0]["id"] == "ebw"

    # tweede run: niets nieuws, archief blijft gelijk
    assert run(["--geen-ai"], root=str(root), http=fake_http(ROUTES)) == 0
    again = json.loads((root / "site/data/items.json").read_text(encoding="utf-8"))["items"]
    assert len(again) == len(items)
    status = {s["id"]: s for s in json.loads((root / "site/data/status.json").read_text())["bronnen"]}
    assert status["ec"]["nieuw"] == 0


def test_run_faalt_als_geen_enkele_bron_werkt(tmp_path, fake_http):
    root = make_root(tmp_path)
    assert run(["--geen-ai", "--bron", "kapot"], root=str(root), http=fake_http({})) == 1


def test_enrich_zonder_sleutel_doet_niets(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    items = [{"id": "a", "title": "t", "source_name": "s"}]
    assert enrich.enrich_items(items, load_config(), limit=5) == 0
    assert "ai" not in items[0]


def test_enrich_verwerkt_antwoord(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            ids = [m["id"] for m in json.loads(kwargs["messages"][0]["content"])]
            result = {"berichten": [{"id": i, "samenvatting": "Samenvatting.", "moza_relevantie": "hoog",
                                     "moza_toelichting": "Raakt de Berichtenbox."} for i in ids]}
            return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                   content=[SimpleNamespace(type="text", text=json.dumps(result))])

    class FakeClient:
        def __init__(self):
            self.beta = SimpleNamespace(messages=FakeMessages())

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    items = [{"id": f"i{n}", "title": f"Bericht {n}", "source_name": "Bron", "date": "2026-10-0{n}",
              "summary": "tekst", "score": n} for n in range(1, 10)]
    items[0]["ai"] = {"samenvatting": "al gedaan"}
    assert enrich.enrich_items(items, load_config(), limit=20) == 8
    assert len(calls) == 1  # 8 berichten = één groep
    assert calls[0]["fallbacks"] == "default"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert items[1]["ai"]["moza_relevantie"] == "hoog"
    assert items[0]["ai"] == {"samenvatting": "al gedaan"}


def test_final_text_neemt_tekst_na_fallback():
    response = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="half"),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="text", text='{"berichten": []}'),
    ])
    assert enrich._final_text(response) == '{"berichten": []}'
