"""Hoofdprogramma: alle bronnen ophalen, classificeren en de sitegegevens bijwerken.

Gebruik:
    python -m scraper                 # alle actieve bronnen
    python -m scraper --bron we-build # alleen bepaalde bron(nen)
    python -m scraper --droog         # niets wegschrijven, alleen tonen
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import yaml

from . import enrich
from .classify import Classifier
from .fetchers import Context, RawItem, fetch
from .store import load_json, merge, prune, save_json
from .util import FetchError, Http, item_id, iso, now_utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(config_dir: str = os.path.join(ROOT, "config")) -> dict:
    def read(name: str) -> dict:
        with open(os.path.join(config_dir, name), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    return {"bronnen": read("bronnen.yaml"), "onderwerpen": read("onderwerpen.yaml"),
            "achtergrond": read("achtergrond.yaml")}


def make_item(raw: RawItem, source: dict, classification: dict) -> dict:
    return {
        "id": item_id(raw.url),
        "title": raw.title,
        "url": raw.url,
        "summary": raw.summary,
        "published": raw.published,
        "source": source["id"],
        "source_name": source["naam"],
        "category": source["categorie"],
        **classification,
    }


def reclassify(archive: list[dict], classifier: Classifier, sources: dict[str, dict]) -> list[dict]:
    """Archief opnieuw indelen met de huidige zoektermen (na wijzigingen in de config)."""
    kept = []
    for item in archive:
        source = sources.get(item["source"])
        if source is None:
            kept.append(item)
            continue
        text = f"{item.get('summary', '')}\n{item.get('fragment', '')}"
        classification = classifier.classify(item["title"], text, source)
        if classification is None:
            continue
        item.update(classification)
        item["source_name"] = source["naam"]
        item["category"] = source["categorie"]
        kept.append(item)
    return kept


def site_config(config: dict, statuses: list[dict]) -> dict:
    """Het deel van de configuratie dat de website nodig heeft."""
    bronnen = config["bronnen"]
    topics = config["onderwerpen"]
    return {
        "categorieen": bronnen["categorieen"],
        "onderwerpen": [{k: t.get(k) for k in ("id", "naam", "kort")} for t in topics["onderwerpen"]],
        "moza_themas": [{k: t.get(k) for k in ("id", "naam", "uitleg", "moza_onderdelen")}
                        for t in topics["moza_themas"]],
        "achtergrond": config["achtergrond"],
        "bronnen": statuses,
    }


def step_summary(statuses: list[dict], added: int, total: int) -> str:
    lines = [
        f"### Nieuwsbrief bijgewerkt: {added} nieuwe berichten (archief: {total})",
        "",
        "| Bron | Status | Gevonden | Relevant | Nieuw | Opmerking |",
        "|---|---|---:|---:|---:|---|",
    ]
    for s in statuses:
        if not s["actief"]:
            continue
        icon = "✅" if s["ok"] else "❌"
        lines.append(f"| {s['naam']} | {icon} | {s.get('gevonden', 0)} | {s.get('relevant', 0)} | "
                     f"{s.get('nieuw', 0)} | {(s.get('fout') or '').replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def run(argv: list[str] | None = None, root: str = ROOT, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(description="EUDI/EBW-nieuwsbrief bijwerken")
    parser.add_argument("--bron", action="append", help="alleen deze bron-id (meerdere mogelijk)")
    parser.add_argument("--droog", action="store_true", help="niets wegschrijven")
    parser.add_argument("--geen-ai", action="store_true", help="geen AI-samenvattingen maken")
    args = parser.parse_args(argv)

    config = load_config(os.path.join(root, "config"))
    site_data = os.path.join(root, "site", "data")
    state_file = os.path.join(root, "data", "state.json")
    classifier = Classifier(config["onderwerpen"])
    all_sources = config["bronnen"]["bronnen"]
    sources_by_id = {s["id"]: s for s in all_sources}
    items_path = os.path.join(site_data, "items.json")
    status_path = os.path.join(site_data, "status.json")
    archive = load_json(items_path, {"items": []})["items"]
    previous_status = {s["id"]: s for s in load_json(status_path, {"bronnen": []})["bronnen"]}
    state = load_json(state_file, {})

    now = now_utc()
    now_iso = iso(now)
    ctx = Context(http=http or Http(), state=state, known_ids={i["id"] for i in archive})
    fresh: list[dict] = []
    statuses: list[dict] = []

    for source in all_sources:
        active = source.get("actief", True)
        selected = active and (not args.bron or source["id"] in args.bron)
        prev = previous_status.get(source["id"], {})
        status = {
            "id": source["id"], "naam": source["naam"], "categorie": source["categorie"],
            "type": source["type"], "url": source["url"], "site": source.get("site", source["url"]),
            "toelichting": " ".join((source.get("toelichting") or "").split()),
            "prioriteit": source.get("prioriteit", 2), "actief": active,
            "ok": prev.get("ok"), "fout": prev.get("fout"), "gevonden": prev.get("gevonden", 0),
            "relevant": prev.get("relevant", 0), "nieuw": 0,
            "laatst_gecontroleerd": prev.get("laatst_gecontroleerd"),
            "laatst_succes": prev.get("laatst_succes"),
        }
        if not active:
            status.update(ok=None, fout=None, gevonden=0, relevant=0)
        statuses.append(status)
        if not selected:
            continue
        print(f"→ {source['id']} ({source['type']})", flush=True)
        status["laatst_gecontroleerd"] = now_iso
        try:
            raw_items = fetch(source, ctx)
        except FetchError as exc:
            status.update(ok=False, fout=str(exc)[:300])
            print(f"  ✗ {exc}", flush=True)
            continue
        except Exception as exc:  # een kapotte bron mag de rest niet tegenhouden
            status.update(ok=False, fout=f"onverwachte fout: {exc.__class__.__name__}: {exc}"[:300])
            print(f"  ✗ onverwachte fout: {exc!r}", flush=True)
            continue
        # Bij de eerste geslaagde run van een bron is alles 'nieuw'. Berichten zonder
        # publicatiedatum gaan dan wel het archief in, maar niet in de lopende editie.
        first_run = not prev.get("laatst_succes")
        relevant = 0
        for raw in raw_items:
            classification = classifier.classify(raw.title, f"{raw.summary}\n{raw.text}", source)
            if classification is not None:
                relevant += 1
                item = make_item(raw, source, classification)
                if raw.text:
                    item["fragment"] = classifier.excerpt(raw.text)
                if first_run and not raw.published:
                    item["baseline"] = True
                fresh.append(item)
        status.update(ok=True, fout=None, gevonden=len(raw_items), relevant=relevant, laatst_succes=now_iso)
        print(f"  ✓ {len(raw_items)} gevonden, {relevant} relevant", flush=True)

    archive = reclassify(archive, classifier, sources_by_id)
    merged, added = merge(archive, fresh, now_iso)
    merged = prune(merged, now.date())
    kept_ids = {i["id"] for i in merged}
    added = [i for i in added if i["id"] in kept_ids]
    new_per_source = Counter(i["source"] for i in added)
    for status in statuses:
        status["nieuw"] = new_per_source.get(status["id"], 0)

    if not args.geen_ai:
        enrich.enrich_items(merged, config, limit=int(os.environ.get("AI_MAX_BERICHTEN", "40")))

    print(f"\n{len(added)} nieuwe berichten, archief bevat {len(merged)} berichten.")
    for item in sorted(added, key=lambda i: i["date"], reverse=True)[:40]:
        print(f"  + [{item['date']}] {item['source']}: {item['title'][:100]}")

    if args.droog:
        print("(droog: niets weggeschreven)")
    else:
        save_json(items_path, {"generated": now_iso, "items": merged})
        save_json(status_path, {"generated": now_iso, "bronnen": statuses})
        save_json(os.path.join(site_data, "config.json"), site_config(config, statuses))
        save_json(state_file, state)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(step_summary(statuses, len(added), len(merged)))

    tried = [s for s in statuses if s["laatst_gecontroleerd"] == now_iso]
    if tried and not any(s["ok"] for s in tried):
        print("Geen enkele bron kon worden opgehaald.", file=sys.stderr)
        return 1
    return 0
