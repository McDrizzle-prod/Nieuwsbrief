"""Archief van berichten bijhouden: samenvoegen, ontdubbelen en opschonen."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .util import title_key

NL_TZ = ZoneInfo("Europe/Amsterdam")

BEWAAR_DAGEN = 730
MAX_ITEMS = 5000
MIN_TITEL_VOOR_ONTDUBBELEN = 25


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _json_default(value):
    if isinstance(value, (date, datetime)):  # datums uit de YAML-configuratie
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is niet als JSON op te slaan")


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, default=_json_default)
        fh.write("\n")
    os.replace(tmp, path)


def _day(value: str | None) -> date | None:
    """Kalenderdag in Nederlandse tijd (tijdstempels zijn opgeslagen in UTC)."""
    if not value:
        return None
    try:
        if len(value) <= 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(NL_TZ).date()
    except ValueError:
        return None


def display_date(published: str | None, first_seen: str) -> str:
    """Datum voor de nieuwsbrief: publicatiedatum, maar nooit later dan 'gevonden op'.

    Zo komen aankondigingen van toekomstige evenementen in de editie van de week
    waarin ze verschenen, en oude berichten die we pas later vinden in hun eigen week.
    """
    seen = _day(first_seen)
    pub = _day(published)
    if pub and seen:
        return min(pub, seen).isoformat()
    return (pub or seen).isoformat()


def _near(a: dict, b: dict, days: int = 10) -> bool:
    da, db = _day(a.get("published")), _day(b.get("published"))
    return da is None or db is None or abs((da - db).days) <= days


def merge(archive: list[dict], fresh: list[dict], now_iso: str) -> tuple[list[dict], list[dict]]:
    """Nieuwe berichten toevoegen aan het archief; bestaande bijwerken.

    Hetzelfde bericht via een tweede bron (zelfde titel, datum dichtbij) wordt niet
    dubbel opgenomen, maar als extra vindplaats bij het bestaande bericht gezet.
    """
    by_id = {item["id"]: item for item in archive}
    by_title: dict[str, dict] = {}
    for item in archive:
        if len(item["title"]) >= MIN_TITEL_VOOR_ONTDUBBELEN:
            by_title.setdefault(title_key(item["title"]), item)
    added: list[dict] = []
    for item in fresh:
        existing = by_id.get(item["id"])
        if existing is not None:
            for key in ("title", "summary", "source_name", "category", "topics", "topic_hits",
                        "moza", "moza_level", "score"):
                if item.get(key) not in (None, ""):
                    existing[key] = item[key]
            if item.get("published") and not existing.get("published"):
                existing["published"] = item["published"]
            existing["date"] = display_date(existing.get("published"), existing["first_seen"])
            continue
        key = title_key(item["title"])
        twin = by_title.get(key) if len(item["title"]) >= MIN_TITEL_VOOR_ONTDUBBELEN else None
        if twin is not None and twin["source"] != item["source"] and _near(twin, item):
            also = twin.setdefault("also", [])
            if all(a["url"] != item["url"] for a in also):
                also.append({"source": item["source"], "source_name": item["source_name"], "url": item["url"]})
            continue
        item["first_seen"] = now_iso
        item["date"] = display_date(item.get("published"), now_iso)
        by_id[item["id"]] = item
        if len(item["title"]) >= MIN_TITEL_VOOR_ONTDUBBELEN:
            by_title.setdefault(key, item)
        added.append(item)
    return list(by_id.values()), added


def prune(items: list[dict], today: date, keep_days: int = BEWAAR_DAGEN, max_items: int = MAX_ITEMS) -> list[dict]:
    cutoff = today - timedelta(days=keep_days)
    kept = [i for i in items if (_day(i.get("date")) or today) >= cutoff]
    kept.sort(key=lambda i: (i.get("date") or "", i.get("first_seen") or ""), reverse=True)
    return kept[:max_items]
