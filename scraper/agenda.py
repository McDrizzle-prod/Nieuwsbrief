"""Agenda: komende evenementen over de EUDI Wallet en de European Business Wallet.

De bronnen staan in config/agenda.yaml. Per bron worden de evenementen opgehaald
(iCal-agenda, agenda-API van WordPress, agendapagina's, open data van de Tweede Kamer
of de evenementenpagina van de Commissie). Van elk evenement worden datum, tijd en
locatie bepaald en het wordt ingedeeld bij de EUDI Wallet, de Business Wallet of
allebei. Alleen evenementen die over (minstens) een van beide wallets gaan, komen in
de agenda.

Uitvoer:
    data/agenda.json        intern archief (alle evenementen, ook dubbele aankondigingen)
    site/data/agenda.json   wat de site toont: komende evenementen, ontdubbeld
"""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .classify import Classifier
from .fetchers import Context, _container
from .store import NL_TZ
from .util import FetchError, clean_text, item_id

WALLETS = ("eudi", "ebw")
SUMMARY_LIMIT = 420
DETAIL_TTL_DAGEN = 14        # detailpagina's van evenementen zo vaak opnieuw bekijken
BEWAAR_NA_AFLOOP_DAGEN = 7   # afgelopen evenementen nog zo lang in het archief
VERDWENEN_NA_DAGEN = 7       # niet meer aangeboden door een werkende bron: geschrapt


@dataclass
class RawEvent:
    title: str
    url: str
    start: str | None = None   # 'JJJJ-MM-DD' (hele dag) of 'JJJJ-MM-DDTUU:MM:SS+02:00'
    end: str | None = None
    location: str = ""
    online: bool = False
    summary: str = ""
    text: str = ""             # extra tekst om op in te delen; wordt niet opgeslagen


# --- Datums en tijden ------------------------------------------------------------

MAANDEN = {
    "januari": 1, "january": 1, "jan": 1, "februari": 2, "february": 2, "feb": 2,
    "maart": 3, "march": 3, "mrt": 3, "mar": 3, "april": 4, "apr": 4, "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7, "augustus": 8,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "oktober": 10,
    "october": 10, "okt": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_M = "|".join(sorted(MAANDEN, key=len, reverse=True))
_TOT = r"\s*(?:-|–|—|t/m|tm|tot en met|tot|to|until|en|&|and)\s*"
RE_TWEE_MAANDEN = re.compile(
    rf"\b(\d{{1,2}})\s+({_M})\.?,?(?:\s+(\d{{4}}))?{_TOT}(\d{{1,2}})\s+({_M})\.?,?\s+(\d{{4}})\b", re.I)
RE_DAGEN = re.compile(rf"\b(\d{{1,2}})(?:\s*[-–,]\s*\d{{1,2}})*{_TOT}(\d{{1,2}})\s+({_M})\.?,?\s+(\d{{4}})\b", re.I)
RE_DAG = re.compile(rf"\b(\d{{1,2}})\s+({_M})\.?,?\s+(\d{{4}})\b", re.I)
RE_ENGELS = re.compile(rf"\b({_M})\.?\s+(\d{{1,2}})(?:{_TOT}(\d{{1,2}}))?,?\s+(\d{{4}})\b", re.I)
RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RE_NUMERIEK = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
_UUR = r"(?<![\d.:])(\d{1,2})[:.](\d{2})(?![.:]?\d)"
RE_TIJDEN = re.compile(
    rf"{_UUR}\s*(?:uur|u\.?)?\s*(?:-|–|—|tot|to|until|t/m)\s*(?:einde|eindtijd|end)?\s*:?\s*{_UUR}", re.I)
RE_TIJD = re.compile(rf"(?:aanvang|begin(?:tijd)?|start|vanaf|om|at)\s*:?\s*{_UUR}|{_UUR}\s*(?:uur|u\b|h\b)", re.I)
DATUM_LABEL = re.compile(r"\b(?:datum(?:\s*/\s*tijd)?|wanneer|date|when|dag)\s*:", re.I)
LOCATIE_LABEL = re.compile(
    r"\b(?:locatie|waar|location|venue|plaats|adres)\s*:?\s+(.{3,120}?)"
    r"(?=\s+(?:doelgroep|datum|tijd|organisator|organisatie|prijs|kosten|aanmelden|voor wie|programma|"
    r"date|time|organi[sz]er|price|register)\b|\s*[|\n]|$)", re.I)
ONLINE = re.compile(r"\b(?:online|webinar|livestream|live-stream|virtu(?:eel|al)|teams|zoom|hybride|hybrid)\b", re.I)


def _datum(dag: int, maand: int, jaar: int) -> date | None:
    try:
        return date(jaar, maand, dag)
    except ValueError:
        return None


def zoek_periode(text: str) -> tuple[date | None, date | None]:
    """Eerste datum (of periode) in een tekst: '7 en 8 oktober 2026', '18 t/m 19 nov 2026',
    '29-30 october, 2026', '13 november 2026, 11:00 - 17:30 uur en 14 november 2026'."""
    text = " ".join((text or "").split())
    if not text:
        return None, None
    found: list[tuple[int, date, date | None]] = []
    for m in RE_TWEE_MAANDEN.finditer(text):
        jaar2 = int(m.group(6))
        start = _datum(int(m.group(1)), MAANDEN[m.group(2).lower()], int(m.group(3) or jaar2))
        eind = _datum(int(m.group(4)), MAANDEN[m.group(5).lower()], jaar2)
        if start and eind and start <= eind:
            found.append((m.start(), start, eind))
    for m in RE_DAGEN.finditer(text):
        maand, jaar = MAANDEN[m.group(3).lower()], int(m.group(4))
        start, eind = _datum(int(m.group(1)), maand, jaar), _datum(int(m.group(2)), maand, jaar)
        if start and eind and start < eind:
            found.append((m.start(), start, eind))
    for m in RE_ENGELS.finditer(text):
        maand, jaar = MAANDEN[m.group(1).lower()], int(m.group(4))
        start = _datum(int(m.group(2)), maand, jaar)
        eind = _datum(int(m.group(3)), maand, jaar) if m.group(3) else None
        if start:
            found.append((m.start(), start, eind if eind and eind > start else None))
    singles = []
    for m in RE_DAG.finditer(text):
        day = _datum(int(m.group(1)), MAANDEN[m.group(2).lower()], int(m.group(3)))
        if day:
            singles.append((m.start(), m.end(), day))
    for m in RE_ISO.finditer(text):
        day = _datum(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if day:
            singles.append((m.start(), m.end(), day))
    for m in RE_NUMERIEK.finditer(text):
        day = _datum(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if day:
            singles.append((m.start(), m.end(), day))
    singles.sort()
    for i, (pos, end_pos, day) in enumerate(singles):
        eind = None
        # '13 november 2026, 11:00 - 17:30 uur en 14 november 2026': tweede datum vlak erna
        for pos2, _, day2 in singles[i + 1:]:
            if pos2 - end_pos > 120:
                break
            if day < day2 <= day + timedelta(days=7):
                eind = day2
        found.append((pos, day, eind))
    if not found:
        return None, None
    found.sort(key=lambda f: (f[0], f[2] is None))
    return found[0][1], found[0][2]


def zoek_tijden(text: str) -> tuple[time | None, time | None]:
    text = " ".join((text or "").split())
    m = RE_TIJDEN.search(text)
    if m:
        try:
            return time(int(m.group(1)), int(m.group(2))), time(int(m.group(3)), int(m.group(4)))
        except ValueError:
            pass
    m = RE_TIJD.search(text)
    if m:
        uur, minuut = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            return time(int(uur), int(minuut)), None
        except ValueError:
            pass
    return None, None


def moment(day: date, tijd: time | None = None) -> str:
    if tijd is None:
        return day.isoformat()
    return datetime.combine(day, tijd, tzinfo=NL_TZ).isoformat()


def lokaal(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=NL_TZ)
    return value.astimezone(NL_TZ).replace(microsecond=0).isoformat()


def periode_uit_tekst(text: str) -> tuple[str | None, str | None]:
    """Begin en einde (als ISO-tekst) uit vrije tekst; een label als 'Datum:' krijgt voorrang."""
    text = " ".join((text or "").split())
    label = DATUM_LABEL.search(text)
    focus = text[label.start():label.start() + 400] if label else text[:3000]
    start, eind = zoek_periode(focus)
    if start is None and label:
        focus = text[:3000]
        start, eind = zoek_periode(focus)
    if start is None:
        return None, None
    begin_tijd, eind_tijd = zoek_tijden(focus)
    begin = moment(start, begin_tijd)
    einde = None
    if eind_tijd is not None:
        einde = moment(eind or start, eind_tijd)
    elif eind is not None:
        einde = moment(eind)
    return begin, einde


def dag_van(value: str | None) -> date | None:
    if not value:
        return None
    try:
        if len(value) <= 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(NL_TZ).date()
    except ValueError:
        return None


def laatste_dag(event: dict) -> date | None:
    return dag_van(event.get("end")) or dag_van(event.get("start"))


def locatie_uit_tekst(text: str) -> str:
    m = LOCATIE_LABEL.search(" ".join((text or "").split()))
    return clean_text(m.group(1)).strip(" ,.;:-") if m else ""


# --- iCal ----------------------------------------------------------------------

def _ical_tekst(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def _ical_moment(value: str, params: dict) -> tuple[str | None, bool]:
    """(ISO, hele dag?) voor een DTSTART/DTEND-waarde."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value[:8], "%Y%m%d").date().isoformat(), True
        except ValueError:
            return None, False
    try:
        stamp = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None, False
    if value.endswith("Z"):
        stamp = stamp.replace(tzinfo=timezone.utc)
    else:
        try:
            stamp = stamp.replace(tzinfo=ZoneInfo(params.get("TZID", "Europe/Amsterdam").strip('"')))
        except (KeyError, ValueError):
            stamp = stamp.replace(tzinfo=NL_TZ)  # bijv. 'W. Europe Standard Time' van Outlook
    return lokaal(stamp), False


def parse_ical(text: str) -> list[dict]:
    """VEVENT-blokken uit een iCal-bestand als {NAAM: (waarde, parameters)}."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    events, current = [], None
    for line in text.splitlines():
        if line.strip() == "BEGIN:VEVENT":
            current = {}
        elif line.strip() == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            current.setdefault(name.upper(), (value, dict(p.split("=", 1) for p in params if "=" in p)))
    return events


def fetch_ical(source: dict, ctx: Context) -> list[RawEvent]:
    resp = ctx.http.get(source["url"])
    text = resp.content.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text[:2000]:
        raise FetchError("geen iCal-agenda ontvangen")
    events = []
    for record in parse_ical(text):
        if record.get("STATUS", ("",))[0].upper() == "CANCELLED":
            continue
        start, hele_dag = _ical_moment(*record["DTSTART"]) if "DTSTART" in record else (None, False)
        if not start:
            continue
        end = None
        if "DTEND" in record:
            end, _ = _ical_moment(*record["DTEND"])
            if hele_dag and end:  # DTEND van een hele dag is exclusief
                end = (date.fromisoformat(end) - timedelta(days=1)).isoformat()
            if end == start:
                end = None
        url = record.get("URL", ("",))[0].strip() or source.get("site", source["url"])
        location = clean_text(_ical_tekst(record.get("LOCATION", ("",))[0]))
        description = clean_text(_ical_tekst(record.get("DESCRIPTION", ("",))[0]))
        if location.startswith(("http://", "https://")):  # een Teams-link als 'locatie'
            location = "Online"
        events.append(RawEvent(
            title=clean_text(_ical_tekst(record.get("SUMMARY", ("",))[0])),
            url=url, start=start, end=end, location=location,
            summary=clean_text(description, SUMMARY_LIMIT), text=description,
        ))
    return events


# --- WordPress: The Events Calendar --------------------------------------------

def _tribe_moment(utc_value: str | None, local_value: str | None, hele_dag: bool) -> str | None:
    if hele_dag and local_value:
        return local_value[:10]
    if utc_value:
        try:
            return lokaal(datetime.fromisoformat(utc_value.replace(" ", "T")).replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    if local_value:
        try:
            return lokaal(datetime.fromisoformat(local_value.replace(" ", "T")))
        except ValueError:
            return None
    return None


def fetch_tribe(source: dict, ctx: Context) -> list[RawEvent]:
    params = {"per_page": 50, "start_date": datetime.now(NL_TZ).date().isoformat(), **(source.get("params") or {})}
    url, events = source["url"], []
    for _ in range(int(source.get("paginas", 2))):
        resp = ctx.http.get(url, params=params, headers={"Accept": "application/json"})
        try:
            data = resp.json()
        except ValueError as exc:
            raise FetchError("antwoord is geen JSON") from exc
        for record in data.get("events", []):
            hele_dag = bool(record.get("all_day"))
            start = _tribe_moment(record.get("utc_start_date"), record.get("start_date"), hele_dag)
            if not start:
                continue
            end = _tribe_moment(record.get("utc_end_date"), record.get("end_date"), hele_dag)
            venue = record.get("venue") or {}
            if isinstance(venue, list):
                venue = venue[0] if venue else {}
            plaats = [venue.get(k) for k in ("venue", "city", "country") if isinstance(venue, dict) and venue.get(k)]
            description = clean_text(record.get("description"))
            events.append(RawEvent(
                title=clean_text(htmllib.unescape(record.get("title", ""))),
                url=record.get("url") or source["url"],
                start=start, end=end if end and end != start else None,
                location=clean_text(", ".join(dict.fromkeys(plaats))),
                summary=clean_text(record.get("excerpt") or description, SUMMARY_LIMIT), text=description,
            ))
        url, params = data.get("next_rest_url"), None
        if not url:
            break
    return events


# --- Agendapagina's (HTML) -------------------------------------------------------

def _addevent(node) -> dict:
    """Gegevens uit een 'Add to Calendar'-blok (AddEvent), zoals ECP dat gebruikt."""
    block = node.select_one(".addeventatc") if node is not None else None
    if block is None:
        return {}
    fields = {}
    for key in ("start", "end", "timezone", "title", "location", "description"):
        span = block.select_one(f".{key}")
        if span is not None:
            fields[key] = clean_text(span.get_text(" "))
    try:
        zone = ZoneInfo(fields.get("timezone") or "Europe/Amsterdam")
    except (KeyError, ValueError):
        zone = NL_TZ
    for key in ("start", "end"):
        value = fields.get(key)
        if not value:
            continue
        try:
            stamp = datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            fields.pop(key)
            continue
        fields[key] = lokaal(stamp.replace(tzinfo=zone)) if len(value) > 10 else value[:10]
    return fields


def _jsonld_event(page: BeautifulSoup) -> dict:
    for script in page.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                stack.extend(node["@graph"])
            kinds = node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")]
            if any(isinstance(k, str) and k.endswith("Event") for k in kinds) and node.get("startDate"):
                return node
    return {}


def _jsonld_locatie(node: dict) -> tuple[str, bool]:
    place = node.get("location")
    places = place if isinstance(place, list) else [place]
    names, online = [], "Online" in str(node.get("eventAttendanceMode", "")) or "Mixed" in str(
        node.get("eventAttendanceMode", ""))
    for place in places:
        if isinstance(place, str):
            names.append(place)
        elif isinstance(place, dict):
            if "Virtual" in str(place.get("@type")):
                online = True
                continue
            address = place.get("address")
            city = address.get("addressLocality") if isinstance(address, dict) else None
            names.extend(x for x in (place.get("name"), city) if x)
    return clean_text(", ".join(dict.fromkeys(names))), online


def _jsonld_moment(value) -> str | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(str(value)) <= 10:
        return stamp.date().isoformat()
    return lokaal(stamp)


SCHOONMAKEN = re.compile(r"sidebar|related|gerelateerd|share|social|cookie|menu|breadcrumb|newsletter|nieuwsbrief|"
                         r"footer|header|navigation|booking|attendees|aanmeld", re.I)


def hoofdtekst(page: BeautifulSoup) -> str:
    for tag in page(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    for tag in page.find_all(True):
        if tag.decomposed or tag.name in ("html", "body", "main", "article"):
            continue
        marks = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
        if marks.strip() and SCHOONMAKEN.search(marks):
            tag.decompose()
    body = page.find("main") or page.find("article") or page.body or page
    return clean_text(body.get_text(" "), 20000)


def gegevens_uit_pagina(page: BeautifulSoup) -> dict:
    """Datum, tijd, locatie en tekst van een evenementpagina."""
    info: dict = {}
    node = _jsonld_event(page)
    if node:
        info["start"] = _jsonld_moment(node.get("startDate"))
        info["end"] = _jsonld_moment(node.get("endDate"))
        info["location"], info["online"] = _jsonld_locatie(node)
        info["summary"] = clean_text(node.get("description"), SUMMARY_LIMIT)
    add = _addevent(page)
    for key in ("start", "end", "location"):
        if not info.get(key) and add.get(key):
            info[key] = add[key]
    if info.get("start"):
        info["gestructureerd"] = True  # uit JSON-LD of een agendablok, niet uit vrije tekst
    if not info.get("summary") and add.get("description"):
        info["summary"] = clean_text(add["description"], SUMMARY_LIMIT)
    meta = page.find("meta", attrs={"property": "og:description"}) or page.find("meta", attrs={"name": "description"})
    if not info.get("summary") and meta is not None:
        info["summary"] = clean_text(meta.get("content"), SUMMARY_LIMIT)
    stamp = page.find("time", attrs={"datetime": True})
    stamp_value = stamp.get("datetime") if stamp is not None else None
    text = hoofdtekst(page)
    if not info.get("start"):
        start, end = periode_uit_tekst(text)
        if start is None and stamp_value:
            start = _jsonld_moment(stamp_value)
        info["start"], info["end"] = start, end
    if not info.get("location"):
        info["location"] = locatie_uit_tekst(text)
    info["text"] = text
    return {k: v for k, v in info.items() if v not in (None, "")}


def _datum_kop(text: str) -> bool:
    """Is deze kop eigenlijk een datum ('28 okt 2026', '18 t/m 19 nov 2026')?"""
    start, _ = zoek_periode(text)
    rest = RE_DAG.sub("", RE_DAGEN.sub("", text))
    return start is not None and len(re.sub(r"[\W\d_]+", "", rest)) < 8


def _titel(container, anchors) -> str:
    add = _addevent(container)
    if add.get("title"):
        return add["title"]
    for heading in container.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = clean_text(heading.get_text(" "))
        if len(text) >= 8 and not _datum_kop(text):
            return text
    candidates = []
    for anchor in anchors:
        text = clean_text(anchor.get_text(" ") or anchor.get("title", ""))
        if len(text) >= 8 and not _datum_kop(text) and text.lower().strip(" +›»→") not in ("lees meer", "read more"):
            candidates.append(text)
    return min(candidates, key=len) if candidates else ""


def fetch_html_agenda(source: dict, ctx: Context) -> list[RawEvent]:
    resp = ctx.http.get(source["url"])
    soup = BeautifulSoup(resp.content, "lxml")
    base = resp.url
    pattern = re.compile(source["link_patroon"])
    exclude = re.compile(source["link_uitsluiten"]) if source.get("link_uitsluiten") else None
    host = urlparse(base).netloc
    groups: dict[str, list] = {}
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base, anchor["href"]).split("#")[0]
        if urlparse(url).netloc != host or not pattern.search(urlparse(url).path):
            continue
        if url.rstrip("/") == base.split("#")[0].rstrip("/") or (exclude and exclude.search(url)):
            continue
        groups.setdefault(url, []).append(anchor)
    events = []
    for url, anchors in groups.items():
        container = max((_container(a, base, pattern) for a in anchors),
                        key=lambda node: len(node.get_text(" ", strip=True)))
        title = _titel(container, anchors)
        if not title:
            continue
        add = _addevent(container)
        text = clean_text(container.get_text(" "))
        start, end = add.get("start"), add.get("end")
        if not start:
            start, end = periode_uit_tekst(text)
        events.append(RawEvent(
            title=title, url=url, start=start, end=end if end != start else None,
            location=add.get("location") or locatie_uit_tekst(text),
            summary=clean_text(add.get("description") or "", SUMMARY_LIMIT),
        ))
    return events[: int(source.get("max", 40))]


# --- Tweede Kamer (open data) ----------------------------------------------------

def _vul_datums(value):
    if not isinstance(value, str):
        return value
    vandaag = datetime.now(NL_TZ).date()
    return value.replace("{vandaag}", vandaag.isoformat())


def fetch_tk_activiteiten(source: dict, ctx: Context) -> list[RawEvent]:
    params = {k: _vul_datums(v) for k, v in (source.get("params") or {}).items()}
    try:
        records = ctx.http.get(source["url"], params=params).json().get("value", [])
    except ValueError as exc:
        raise FetchError("antwoord is geen JSON") from exc
    overslaan = set(source.get("soorten_overslaan", ["Procedurevergadering"]))
    events = []
    for record in records:
        soort, onderwerp = record.get("Soort") or "Activiteit", clean_text(record.get("Onderwerp"))
        status = (record.get("Status") or "").lower()
        if soort in overslaan or any(s in status for s in ("geannuleerd", "vervallen", "verplaatst")):
            continue
        if not onderwerp or not record.get("Nummer"):
            continue
        start = _jsonld_moment(record.get("Aanvangstijd") or record.get("Datum"))
        if not start:
            continue
        punten = [clean_text(p.get("Onderwerp")) for p in record.get("Agendapunt") or [] if p.get("Onderwerp")]
        soort_pad = "plenaire_vergaderingen/details/activiteit" if "plenair" in soort.lower() else \
            "commissievergaderingen/details"
        title = onderwerp if onderwerp.lower().startswith(soort.lower()) else f"{soort}: {onderwerp}"
        zaal = clean_text(record.get("Locatie"))
        commissie = record.get("Voortouwnaam")
        summary = f"{soort} van de {commissie}." if commissie else f"{soort} van de Tweede Kamer."
        events.append(RawEvent(
            title=title,
            url=f"https://www.tweedekamer.nl/debat_en_vergadering/{soort_pad}?id={record['Nummer']}",
            start=start, end=_jsonld_moment(record.get("Eindtijd")),
            location="Tweede Kamer, Den Haag" + (f" ({zaal})" if zaal else ""),
            summary=summary, text=" ".join(p.rstrip(" .") + "." for p in punten),  # per agendapunt een zin
        ))
    return events


# --- Evenementenpagina van de EUDI Wallet (Commissie) ---------------------------

ACRONIEMEN = {"EU", "EUDI", "EUDIW", "EBW", "EUBW", "ARF", "QTSP", "NL", "EDI", "ETSI", "CEN", "API", "AI", "ID", "LSP"}


def _hoofdletters(title: str) -> str:
    """'EUDI.WALLETS LAUNCHPAD 2.0' -> 'EUDI Wallets Launchpad 2.0'."""
    if not title.isupper():
        return title
    words = re.sub(r"(?<=[A-Z])\.(?=[A-Z])", " ", title).split()
    return " ".join(w if w in ACRONIEMEN or not w.isalpha() else w.capitalize() for w in words)


def fetch_confluence_events(source: dict, ctx: Context) -> list[RawEvent]:
    resp = ctx.http.get(source["url"])
    soup = BeautifulSoup(resp.content, "lxml")
    events = []
    for item in soup.select("div.exc-event-item"):
        holder = item.find_parent("li")
        link = holder.select_one(".details a[href]") if holder is not None else None
        field = {k: clean_text(n.get_text(" ")) for k in ("dates", "title", "time", "description")
                 if (n := item.select_one(f".exc-ev-{k}")) is not None}
        title = _hoofdletters(field.get("title") or (clean_text(link.get_text(" ")) if link else ""))
        iso_dates = RE_ISO.findall(item.get_text(" "))
        if iso_dates:
            start_day = date(*map(int, iso_dates[0]))
            end_day = date(*map(int, iso_dates[-1])) if len(iso_dates) > 1 else None
        else:
            start_day, end_day = zoek_periode(field.get("dates", ""))
        if not title or start_day is None:
            continue
        begin_tijd, eind_tijd = zoek_tijden(field.get("time", ""))
        dates = field.get("dates", "")
        events.append(RawEvent(
            title=title,
            url=urljoin(resp.url, link["href"]) if link else source["url"],
            start=moment(start_day, begin_tijd),
            end=moment(end_day or start_day, eind_tijd) if eind_tijd else (
                end_day.isoformat() if end_day and end_day != start_day else None),
            location=clean_text(dates.split(" - ", 1)[1]).title() if " - " in dates else "",
            summary=clean_text(field.get("description", ""), SUMMARY_LIMIT),
        ))
    return events


FETCHERS = {
    "ical": fetch_ical,
    "tribe": fetch_tribe,
    "html": fetch_html_agenda,
    "tk_activiteiten": fetch_tk_activiteiten,
    "eudi_evenementen": fetch_confluence_events,
}


# --- Detailpagina's -------------------------------------------------------------

def aanvullen_met_details(events: list[RawEvent], source: dict, ctx: Context, classifier: Classifier,
                          vandaag: date) -> None:
    """Evenementpagina's bekijken voor tijd, locatie en tekst om op in te delen.

    Het resultaat wordt in data/state.json bewaard, zodat een pagina pas na twee weken
    opnieuw wordt opgehaald. Alleen komende evenementen worden bekeken.
    """
    cache = ctx.state.setdefault("agenda_paginas", {})
    budget = int(source.get("detail_max", 20))
    for event in events:
        day = dag_van(event.end) or dag_van(event.start)
        if day is not None and day < vandaag:
            continue
        entry = cache.get(event.url)
        fresh = entry and (vandaag - date.fromisoformat(entry["t"])).days < DETAIL_TTL_DAGEN
        if not fresh and budget > 0:
            budget -= 1
            try:
                page = BeautifulSoup(ctx.http.get(event.url).content, "lxml")
            except FetchError:
                continue
            info = gegevens_uit_pagina(page)
            entry = {k: info.get(k) for k in ("start", "end", "location", "online", "summary", "gestructureerd")
                     if info.get(k)}
            entry["t"] = vandaag.isoformat()
            entry["fragment"] = classifier.excerpt(info.get("text", ""))
            cache[event.url] = entry
        if not entry:
            continue
        # De pagina zelf vult het overzicht aan: een tijd bij dezelfde dag, of een datum
        # uit gestructureerde gegevens. Een datum uit vrije tekst wint nooit van het overzicht.
        page_start = entry.get("start")
        if page_start and (
                not event.start
                or (dag_van(page_start) == dag_van(event.start) and "T" in page_start and "T" not in event.start)
                or (entry.get("gestructureerd") and dag_van(page_start) != dag_van(event.start))):
            event.start, event.end = page_start, entry.get("end")
        event.location = event.location or entry.get("location", "")
        event.online = event.online or bool(entry.get("online"))
        event.summary = event.summary or entry.get("summary", "")
        event.text = f"{event.text}\n{entry.get('fragment', '')}"
    for url in [u for u, e in cache.items() if (vandaag - date.fromisoformat(e["t"])).days > 120]:
        del cache[url]


# --- Indelen, samenvoegen en ontdubbelen ------------------------------------------

def indelen(classifier: Classifier, event: RawEvent, source: dict) -> dict | None:
    result = classifier.classify(event.title, f"{event.summary}\n{event.text}", source)
    if result is None:
        return None
    wallets = set(t for t in result["topics"] if t in WALLETS) | set(source.get("wallets") or [])
    if not wallets:
        return None
    return {"wallets": [w for w in WALLETS if w in wallets], "topic_hits": result["topic_hits"],
            "moza": result["moza"], "moza_level": result["moza_level"]}


def is_online(event: RawEvent) -> bool:
    if event.online:
        return True
    return bool(ONLINE.search(f"{event.location} {event.title}")) or (
        not event.location and bool(ONLINE.search(event.summary[:200])))


def maak_record(event: RawEvent, source: dict, indeling: dict, classifier: Classifier) -> dict:
    eigen_url = event.url and event.url not in (source.get("site"), source["url"])
    return {
        "id": item_id(event.url) if eigen_url else item_id(f"{event.url}#{dag_van(event.start)}-{event.title}"),
        "title": event.title,
        "url": event.url,
        "start": event.start,
        "end": event.end,
        "location": event.location,
        "online": is_online(event),
        "summary": event.summary,
        "fragment": classifier.excerpt(event.text) if event.text else "",
        "source": source["id"],
        "source_name": source.get("organisator") or source["naam"],
        "category": source["categorie"],
        "priority": int(source.get("prioriteit", 2)),
        **indeling,
    }


STOPWOORDEN = {"de", "het", "een", "en", "van", "voor", "met", "in", "op", "aan", "over", "the", "a", "an", "of",
               "and", "for", "to", "on", "at", "in", "with", "naar", "bij", "tot", "om"}


def _woorden(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9#]+", title.lower()) if len(w) > 1 and w not in STOPWOORDEN}


def zelfde_evenement(a: dict, b: dict) -> bool:
    if dag_van(a.get("start")) != dag_van(b.get("start")):
        return False
    wa, wb = _woorden(a["title"]), _woorden(b["title"])
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / min(len(wa), len(wb))
    return overlap >= 0.6 or SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio() >= 0.75


def samenvoegen(archive: list[dict], fresh: list[dict], now_iso: str, gelukt: set[str], bronnen: set[str],
                vandaag: date) -> tuple[list[dict], list[dict]]:
    """Nieuwe evenementen toevoegen, bestaande bijwerken, verdwenen en afgelopen opruimen."""
    by_id = {e["id"]: e for e in archive if e.get("source") in bronnen}
    seen, added = set(), []
    for event in fresh:
        seen.add(event["id"])
        old = by_id.get(event["id"])
        event["last_seen"] = now_iso
        if old is not None:
            event["first_seen"] = old.get("first_seen", now_iso)
            by_id[event["id"]] = event
        else:
            event["first_seen"] = now_iso
            by_id[event["id"]] = event
            added.append(event)
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    for key, event in list(by_id.items()):
        if key in seen:
            continue
        if event["source"] == "handmatig" or (
                event["source"] in gelukt and
                now - datetime.fromisoformat(event["last_seen"].replace("Z", "+00:00")) >= timedelta(days=VERDWENEN_NA_DAGEN)):
            del by_id[key]  # uit de configuratie gehaald, of door de bron geschrapt
    kept = [e for e in by_id.values()
            if (laatste_dag(e) or vandaag) >= vandaag - timedelta(days=BEWAAR_NA_AFLOOP_DAGEN)]
    kept.sort(key=lambda e: (e.get("start") or "", e["title"]))
    kept_ids = {e["id"] for e in kept}
    return kept, [e for e in added if e["id"] in kept_ids]


def ontdubbelen(events: list[dict]) -> list[dict]:
    """Hetzelfde evenement uit meerdere bronnen: één keer tonen, met 'ook vermeld bij'."""
    order = sorted(events, key=lambda e: (e.get("priority", 2), e.get("first_seen") or "", e["id"]))
    kept: list[dict] = []
    for event in order:
        twin = next((k for k in kept if zelfde_evenement(k, event)), None)
        if twin is None:
            kept.append({**event, "also": []})
            continue
        if all(a["url"] != event["url"] for a in twin["also"]) and twin["url"] != event["url"]:
            twin["also"].append({"source_name": event["source_name"], "url": event["url"]})
        twin["wallets"] = [w for w in WALLETS if w in set(twin["wallets"]) | set(event["wallets"])]
        twin["first_seen"] = min(twin["first_seen"], event["first_seen"])
        if "T" not in (twin.get("start") or "") and "T" in (event.get("start") or ""):
            twin["start"], twin["end"] = event["start"], event.get("end") or twin.get("end")
        for key in ("location", "summary", "end"):
            if not twin.get(key) and event.get(key):
                twin[key] = event[key]
        twin["online"] = twin["online"] or event["online"]
    kept.sort(key=lambda e: (e.get("start") or "", e["title"]))
    return kept


# --- Handmatig toegevoegde evenementen ----------------------------------------------

def _yaml_moment(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return lokaal(value)
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return lokaal(datetime.fromisoformat(text.replace(" ", "T"))) if len(text) > 10 else \
            date.fromisoformat(text).isoformat()
    except ValueError:
        start, _ = periode_uit_tekst(text)
        return start


def handmatige_evenementen(entries: list[dict]) -> list[tuple[RawEvent, dict]]:
    result = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        start = _yaml_moment(entry.get("start"))
        if not entry.get("titel") or not start:
            continue
        event = RawEvent(
            title=clean_text(entry["titel"]), url=entry.get("url") or "", start=start,
            end=_yaml_moment(entry.get("eind")), location=clean_text(entry.get("locatie") or ""),
            online=bool(entry.get("online")), summary=clean_text(entry.get("samenvatting") or "", SUMMARY_LIMIT),
        )
        source = {"id": "handmatig", "naam": "Handmatig toegevoegd", "categorie": entry.get("categorie", "derden"),
                  "url": event.url or "handmatig", "organisator": entry.get("organisator"),
                  "prioriteit": 1, "wallets": entry.get("wallets") or [], "filter": not entry.get("wallets")}
        result.append((event, source))
    return result


# --- Hoofdlijn -------------------------------------------------------------------------

def bijwerken(config: dict, ctx: Context, classifier: Classifier, archive: list[dict], previous_status: dict,
              now_iso: str, selectie: list[str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Alle agendabronnen ophalen. Geeft (archief, nieuw toegevoegd, bronstatus) terug."""
    agenda = config.get("agenda") or {}
    sources = agenda.get("bronnen") or []
    vandaag = datetime.fromisoformat(now_iso.replace("Z", "+00:00")).astimezone(NL_TZ).date()
    fresh: list[dict] = []
    statuses: list[dict] = []
    gelukt: set[str] = set()
    for source in sources:
        active = source.get("actief", True)
        selected = active and (not selectie or source["id"] in selectie)
        prev = previous_status.get(source["id"], {})
        status = {
            "id": source["id"], "naam": source["naam"], "categorie": source["categorie"], "type": source["type"],
            "url": source["url"], "site": source.get("site", source["url"]),
            "toelichting": " ".join((source.get("toelichting") or "").split()),
            "prioriteit": source.get("prioriteit", 2), "actief": active,
            "ok": prev.get("ok") if active else None, "fout": prev.get("fout") if active else None,
            "gevonden": prev.get("gevonden", 0) if active else 0, "relevant": prev.get("relevant", 0) if active else 0,
            "nieuw": 0, "laatst_gecontroleerd": prev.get("laatst_gecontroleerd"),
            "laatst_succes": prev.get("laatst_succes"),
        }
        statuses.append(status)
        if not selected:
            continue  # niet opgehaald: de evenementen in het archief blijven staan
        print(f"→ agenda: {source['id']} ({source['type']})", flush=True)
        status["laatst_gecontroleerd"] = now_iso
        try:
            if source["type"] not in FETCHERS:
                raise FetchError(f"onbekend brontype '{source['type']}'")
            events = [e for e in FETCHERS[source["type"]](source, ctx) if e.title and e.url and e.start]
            if source.get("detail"):
                aanvullen_met_details(events, source, ctx, classifier, vandaag)
        except FetchError as exc:
            status.update(ok=False, fout=str(exc)[:300])
            print(f"  ✗ {exc}", flush=True)
            continue
        except Exception as exc:  # een kapotte bron mag de rest niet tegenhouden
            status.update(ok=False, fout=f"onverwachte fout: {exc.__class__.__name__}: {exc}"[:300])
            print(f"  ✗ onverwachte fout: {exc!r}", flush=True)
            continue
        relevant = 0
        for event in events:
            indeling = indelen(classifier, event, source)
            if indeling is not None:
                relevant += 1
                fresh.append(maak_record(event, source, indeling, classifier))
        gelukt.add(source["id"])
        status.update(ok=True, fout=None, gevonden=len(events), relevant=relevant, laatst_succes=now_iso)
        print(f"  ✓ {len(events)} evenementen, {relevant} over EUDI/EBW", flush=True)

    for event, source in handmatige_evenementen(agenda.get("handmatig")):
        indeling = indelen(classifier, event, source)
        if indeling is not None:
            fresh.append(maak_record(event, source, indeling, classifier))

    unique = {event["id"]: event for event in fresh}  # zelfde pagina twee keer in een bron
    bronnen = {s["id"] for s in sources} | {"handmatig"}
    merged, added = samenvoegen(archive, list(unique.values()), now_iso, gelukt, bronnen, vandaag)
    nieuw: dict[str, int] = {}
    for event in added:
        nieuw[event["source"]] = nieuw.get(event["source"], 0) + 1
    for status in statuses:
        status["nieuw"] = nieuw.get(status["id"], 0)
    return merged, added, statuses


def site_agenda(merged: list[dict], statuses: list[dict], config: dict, now_iso: str) -> dict:
    """Wat de site nodig heeft: komende evenementen (ontdubbeld) en de bronstatus."""
    vandaag = datetime.fromisoformat(now_iso.replace("Z", "+00:00")).astimezone(NL_TZ).date()
    upcoming = [e for e in merged if (laatste_dag(e) or vandaag) >= vandaag - timedelta(days=1)]
    events = []
    for event in ontdubbelen(upcoming):
        event = {k: v for k, v in event.items() if k not in ("last_seen", "priority", "topic_hits")}
        events.append(event)
    agenda = config.get("agenda") or {}
    return {
        "generated": now_iso,
        "wallets": [{"id": "eudi", "naam": "EUDI Wallet"}, {"id": "ebw", "naam": "Business Wallet (EBW)"}],
        "categorieen": agenda.get("categorieen", {}),
        "evenementen": events,
        "bronnen": statuses,
    }


def step_summary(statuses: list[dict], added: int, total: int) -> str:
    lines = [
        f"### Agenda: {added} nieuwe evenementen (komend en recent: {total})",
        "",
        "| Bron | Status | Gevonden | Over EUDI/EBW | Nieuw | Opmerking |",
        "|---|---|---:|---:|---:|---|",
    ]
    for s in statuses:
        if not s["actief"]:
            continue
        icon = "✅" if s["ok"] else "❌"
        lines.append(f"| {s['naam']} | {icon} | {s.get('gevonden', 0)} | {s.get('relevant', 0)} | "
                     f"{s.get('nieuw', 0)} | {(s.get('fout') or '').replace('|', '/')} |")
    return "\n".join(lines) + "\n"
