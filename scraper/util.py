"""Hulpfuncties: HTTP, datums, tekst en URL's."""

from __future__ import annotations

import calendar
import hashlib
import html
import os
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (compatible; EUDI-EBW-Nieuwsbrief/1.0; "
    "+https://github.com/McDrizzle-prod/Nieuwsbrief)"
)

MAANDEN = {
    "januari": "january", "februari": "february", "maart": "march", "april": "april",
    "mei": "may", "juni": "june", "juli": "july", "augustus": "august",
    "september": "september", "oktober": "october", "november": "november",
    "december": "december", "mrt": "mar", "okt": "oct",
}
DATUM_IN_TEKST = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}\s+[A-Za-zé]{3,9}\.?\s+\d{4}|[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4})\b"
)


class FetchError(Exception):
    """Een bron kon niet (goed) worden opgehaald."""


class Http:
    """requests-sessie met nette User-Agent, time-outs en herhaalpogingen."""

    def __init__(self, timeout: int = 40):
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(total=2, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "nl,en;q=0.8",
        })

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
        headers = dict(headers or {})
        token = os.environ.get("GITHUB_TOKEN")
        if token and urlparse(url).netloc == "api.github.com":
            headers.setdefault("Authorization", f"Bearer {token}")
            headers.setdefault("Accept", "application/vnd.github+json")
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise FetchError(f"verbinding mislukt: {exc.__class__.__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} bij {resp.url}")
        return resp


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def struct_to_iso(value: time.struct_time | None) -> str | None:
    if not value:
        return None
    return iso(datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc))


def parse_date(value) -> str | None:
    """Zet een datum in (bijna) elk formaat om naar ISO; None als dat niet lukt.

    Alleen-datum blijft JJJJ-MM-DD; met tijd wordt het een UTC-tijdstempel.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        stamp = value / 1000 if value > 1e11 else value
        return iso(datetime.fromtimestamp(stamp, tz=timezone.utc))
    text = " ".join(str(value).split())
    lowered = text.lower()
    for nl, en in MAANDEN.items():
        lowered = re.sub(rf"\b{nl}\b", en, lowered)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", lowered):
        return lowered
    try:
        dayfirst = not re.match(r"\d{4}[-/.]", lowered)
        parsed = dateparser.parse(lowered, dayfirst=dayfirst, fuzzy=True)
    except (ValueError, OverflowError):
        return None
    if parsed.year < 1990 or parsed.year > 2100:
        return None
    has_time = bool(re.search(r"\d{1,2}:\d{2}", lowered))
    midnight = (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0)
    return iso(parsed) if has_time and not midnight else parsed.date().isoformat()


def find_date_in_text(text: str) -> str | None:
    match = DATUM_IN_TEKST.search(text or "")
    return parse_date(match.group(1)) if match else None


def clean_text(value: str | None, limit: int | None = None) -> str:
    """HTML weghalen, entiteiten omzetten en witruimte normaliseren."""
    if not value:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "lxml").get_text(" ")
    text = html.unescape(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)       # markdown-afbeeldingen
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)     # markdown-links
    text = " ".join(text.split())
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:")
        text = cut + " …"
    return text


TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_)")


def canonical_url(url: str) -> str:
    parts = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not TRACKING_PARAMS.match(k)]
    path = parts.path or "/"
    return urlunparse((parts.scheme.lower(), parts.netloc.lower(), path, "", urlencode(query), parts.fragment))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:120]


def get_path(data, path: str | None):
    """Waarde ophalen met een pad als 'a.b.0.c'."""
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
        if current is None:
            return None
    return current


def fill_template(template: str, record: dict) -> str:
    """'{a} – {b.c}' invullen met waarden uit een record (ontbrekend wordt leeg)."""
    def repl(match: re.Match) -> str:
        value = get_path(record, match.group(1))
        if isinstance(value, dict):
            value = value.get("value") or value.get("en") or value.get("nl") or ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)  # JSON-id's als 16113.0
        return "" if value is None else str(value)

    filled = re.sub(r"\{([A-Za-z0-9_$.\-]+)\}", repl, template)
    return " ".join(filled.split()).strip(" :–-")
