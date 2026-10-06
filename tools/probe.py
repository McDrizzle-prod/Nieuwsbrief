"""Onderzoek een of meer URL's voordat je ze als bron toevoegt.

Toont per URL: HTTP-status, type inhoud, gevonden RSS/Atom-feeds, de eerste
berichten uit een feed of JSON-antwoord, en voor HTML-pagina's de links die op
nieuwsberichten lijken (met een CSS-pad waarmee je een selector kunt maken).
Voor agenda's ook: iCal-agenda's, evenementen in schema.org-opmaak (JSON-LD) en
de agenda-API van WordPress (The Events Calendar).

Gebruik:
    python tools/probe.py https://voorbeeld.eu/nieuws [https://...]
    python tools/probe.py --guess-feeds https://voorbeeld.eu/

Zonder installatie: start in GitHub de workflow "Bron onderzoeken" en vul de
URL's in. De uitkomst staat in de samenvatting van de run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; EUDI-EBW-Nieuwsbrief/1.0; "
    "+https://github.com/McDrizzle-prod/Nieuwsbrief)"
)
BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)
FEED_GUESSES = ["feed/", "rss", "rss.xml", "index.xml", "feed.xml", "atom.xml", "news/rss.xml"]
DATE_RE = re.compile(
    r"\b(\d{1,2}[ ./-](?:\d{1,2}|[A-Za-z]{3,9})[ ./-]\d{4}|\d{4}-\d{2}-\d{2})\b"
)

out_lines: list[str] = []


def emit(line: str = "") -> None:
    print(line)
    out_lines.append(line)


def css_path(tag, depth: int = 4) -> str:
    parts = []
    node = tag
    while node is not None and node.name not in (None, "[document]", "html", "body") and len(parts) < depth:
        cls = ".".join(c for c in (node.get("class") or [])[:2])
        parts.append(node.name + (f".{cls}" if cls else ""))
        node = node.parent
    return " > ".join(reversed(parts))


def describe_feed(content: bytes) -> bool:
    parsed = feedparser.parse(content)
    if not parsed.entries and not parsed.feed.get("title"):
        return False
    emit(f"  FEED: '{parsed.feed.get('title', '')}' — {len(parsed.entries)} berichten")
    for entry in parsed.entries[:8]:
        date = entry.get("published") or entry.get("updated") or "-"
        emit(f"    - [{date}] {entry.get('title', '')[:110]}")
        emit(f"      {entry.get('link', '')}")
    return True


def describe_ical(content: bytes) -> bool:
    text = content.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text[:2000]:
        return False
    events = text.split("BEGIN:VEVENT")[1:]
    emit(f"  ICAL: {len(events)} evenementen")
    for block in events[:10]:
        unfolded = re.sub(r"\r?\n[ \t]", "", block)
        fields = {}
        for line in unfolded.splitlines():
            key, _, value = line.partition(":")
            fields.setdefault(key.split(";")[0], value)
        emit(f"    - {fields.get('DTSTART', '-')} | {fields.get('SUMMARY', '')[:100]}")
        emit(f"      {fields.get('LOCATION', '')[:80]} {fields.get('URL', '')}")
    return True


def describe_jsonld(soup) -> None:
    """Evenementen in schema.org-opmaak (JSON-LD), zoals veel agenda's die meesturen."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if not isinstance(node, dict):
                continue
            stack.extend(node.get("@graph", []) if isinstance(node.get("@graph"), list) else [])
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(isinstance(k, str) and k.endswith("Event") for k in kinds):
                place = node.get("location")
                if isinstance(place, list):
                    place = place[0] if place else None
                where = place.get("name") if isinstance(place, dict) else place
                emit(f"  JSON-LD {kinds[0]}: {str(node.get('name', ''))[:90]} | {node.get('startDate')} – "
                     f"{node.get('endDate')} | {where} | {node.get('url', '')}")
            elif kinds and kinds[0]:
                emit(f"  JSON-LD {kinds[0]}")


def describe_wordpress(url: str, soup, agent: str) -> None:
    """WordPress-sites: welke berichttypen er zijn en of The Events Calendar een API heeft."""
    api = soup.find("link", attrs={"rel": "https://api.w.org/"})
    if not api:
        return
    root = urljoin(url, api.get("href", "/wp-json/"))
    emit(f"  WordPress-API: {root}")
    for path in ("wp/v2/types", "tribe/events/v1/events?per_page=5"):
        try:
            r = requests.get(urljoin(root, path), headers={"User-Agent": agent}, timeout=30)
        except requests.RequestException as exc:
            emit(f"    {path}: FOUT {exc}")
            continue
        if not r.ok:
            emit(f"    {path}: HTTP {r.status_code}")
            continue
        try:
            data = r.json()
        except ValueError:
            emit(f"    {path}: geen JSON")
            continue
        if path.startswith("wp/v2/types"):
            for slug, info in (data.items() if isinstance(data, dict) else []):
                emit(f"    berichttype {slug}: rest_base={info.get('rest_base')}")
        else:
            events = data.get("events", []) if isinstance(data, dict) else []
            emit(f"    The Events Calendar: {data.get('total', len(events)) if isinstance(data, dict) else '?'} evenementen")
            for ev in events[:8]:
                venue = ev.get("venue") or {}
                emit(f"      - {ev.get('start_date')} | {ev.get('title', '')[:90]} | "
                     f"{venue.get('venue', '') if isinstance(venue, dict) else ''} | {ev.get('url', '')}")


def describe_json(content: bytes) -> bool:
    try:
        data = json.loads(content)
    except ValueError:
        return False
    emit("  JSON:")
    snippet = json.dumps(data, ensure_ascii=False, indent=1)
    for line in snippet.splitlines()[:60]:
        emit("    " + line[:160])
    return True


def describe_pattern(url: str, content: bytes, pattern: str) -> None:
    """Toon alle links waarvan het pad overeenkomt met een link_patroon uit bronnen.yaml."""
    soup = BeautifulSoup(content, "lxml")
    regex = re.compile(pattern)
    found = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("#")[0]
        if regex.search(urlparse(href).path):
            text = " ".join(a.get_text(" ", strip=True).split())
            found.setdefault(href, text)
    emit(f"  Links die passen bij link_patroon '{pattern}': {len(found)}")
    for href, text in list(found.items())[:40]:
        emit(f"    - {href}  [{text[:60]}]")


def describe_text(content: bytes, needle: str) -> None:
    """Toon waar een stuk tekst op de pagina staat, met omliggende tekst en HTML."""
    soup = BeautifulSoup(content, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    hits = [node for node in soup.find_all(string=re.compile(re.escape(needle), re.I))][:4]
    emit(f"  Tekst '{needle}': {len(hits)} keer gevonden")
    for node in hits:
        parent = node.parent
        block = parent
        while block.parent is not None and len(block.get_text(" ", strip=True)) < 250 and block.parent.name not in ("body", "html"):
            block = block.parent
        emit(f"    pad: {css_path(parent, 6)}")
        emit("    tekst: " + " ".join(block.get_text(" ", strip=True).split())[:700])
        emit("    html: " + " ".join(str(block).split())[:900])


def describe_html(url: str, content: bytes, agent: str = "") -> None:
    soup = BeautifulSoup(content, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    emit(f"  HTML-titel: {title[:120]}")
    describe_jsonld(soup)
    describe_wordpress(url, soup, agent or USER_AGENT)
    for a in soup.find_all("a", href=True):
        if re.search(r"\.ics\b|ical|webcal:|outlook|google\.com/calendar", a["href"], re.I):
            emit(f"  Agenda-link: {urljoin(url, a['href'])}")
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator:
        emit(f"  Generator: {generator.get('content')}")
    for link in soup.find_all("link", attrs={"rel": "alternate"}):
        if "xml" in (link.get("type") or ""):
            emit(f"  Feed-link: {urljoin(url, link.get('href', ''))} ({link.get('type')})")
    articles = soup.find_all("article")
    emit(f"  <article>-elementen: {len(articles)}")
    for heading in soup.find_all(["h1", "h2", "h3"])[:25]:
        emit(f"  Kop {heading.name}: {heading.get_text(' ', strip=True)[:70]}  (pad: {css_path(heading)})")
    feedish = [urljoin(url, a["href"]) for a in soup.find_all("a", href=True)
               if re.search(r"rss|feed|atom|\.xml", a["href"], re.I)]
    for href in list(dict.fromkeys(feedish))[:30]:
        emit(f"  Mogelijke feed-link: {href}")
    host = urlparse(url).netloc
    seen = set()
    shown = 0
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(url, a["href"])
        if len(text) < 25 or href in seen or urlparse(href).netloc != host:
            continue
        seen.add(href)
        container = a.find_parent(["article", "li", "div"])
        date_match = DATE_RE.search(container.get_text(" ", strip=True)) if container else None
        time_tag = container.find("time") if container else None
        date = (time_tag.get("datetime") or time_tag.get_text(strip=True)) if time_tag else (
            date_match.group(1) if date_match else "-"
        )
        emit(f"    - {text[:100]}")
        emit(f"      {href}")
        emit(f"      pad: {css_path(a)} | datum: {date}")
        shown += 1
        if shown >= 25:
            break


def probe(url: str, guess_feeds: bool, agent: str = USER_AGENT, pattern: str | None = None,
          needle: str | None = None) -> None:
    emit("")
    emit(f"## {url}")
    try:
        accept = ("application/json" if "graphql" in url or "/wp-json/" in url
                  else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        resp = requests.get(url, headers={"User-Agent": agent, "Accept": accept,
                                          "Accept-Language": "nl,en;q=0.8"}, timeout=40)
    except requests.RequestException as exc:
        emit(f"  FOUT: {exc}")
        return
    ctype = resp.headers.get("content-type", "")
    emit(f"  Status {resp.status_code} | {ctype} | {len(resp.content)} bytes | eind-URL {resp.url}")
    if resp.status_code >= 400:
        emit("  Begin van antwoord: " + resp.text[:300].replace("\n", " "))
        return
    body = resp.content
    if ("calendar" in ctype or body.lstrip()[:15] == b"BEGIN:VCALENDAR") and describe_ical(body):
        return
    if "json" in ctype and describe_json(body):
        return
    if any(t in ctype for t in ("xml", "rss", "atom")) and describe_feed(body):
        return
    if body.lstrip()[:1] in (b"{", b"[") and describe_json(body):
        return
    if body.lstrip()[:5] == b"<?xml" and describe_feed(body):
        return
    if body.lstrip()[:5] == b"<?xml":
        emit("  XML (geen feed): " + resp.text[:1500].replace("\n", " "))
        return
    describe_html(resp.url, body, agent)
    if pattern:
        describe_pattern(resp.url, body, pattern)
    if needle:
        describe_text(body, needle)
    if guess_feeds:
        base = resp.url if resp.url.endswith("/") else resp.url + "/"
        for guess in FEED_GUESSES:
            candidate = urljoin(base, guess)
            try:
                r = requests.get(candidate, headers={"User-Agent": USER_AGENT}, timeout=20)
            except requests.RequestException:
                continue
            parsed = feedparser.parse(r.content) if r.ok else None
            if parsed and parsed.entries:
                emit(f"  Gevonden feed: {candidate} ({len(parsed.entries)} berichten)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--guess-feeds", action="store_true", help="probeer gangbare feed-adressen")
    parser.add_argument("--browser", action="store_true", help="doe je voor als gewone browser (User-Agent)")
    parser.add_argument("--patroon", help="toon links die passen bij dit link_patroon (regex)")
    parser.add_argument("--tekst", help="toon waar deze tekst op de pagina staat, met de HTML eromheen")
    args = parser.parse_args()
    agent = BROWSER_AGENT if args.browser else USER_AGENT
    for raw in args.urls:
        for url in raw.split():
            probe(url.strip(), args.guess_feeds, agent, args.patroon, args.tekst)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(out_lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
