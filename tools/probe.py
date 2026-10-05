"""Onderzoek een of meer URL's voordat je ze als bron toevoegt.

Toont per URL: HTTP-status, type inhoud, gevonden RSS/Atom-feeds, de eerste
berichten uit een feed of JSON-antwoord, en voor HTML-pagina's de links die op
nieuwsberichten lijken (met een CSS-pad waarmee je een selector kunt maken).

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


def describe_html(url: str, content: bytes) -> None:
    soup = BeautifulSoup(content, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    emit(f"  HTML-titel: {title[:120]}")
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator:
        emit(f"  Generator: {generator.get('content')}")
    for link in soup.find_all("link", attrs={"rel": "alternate"}):
        if "xml" in (link.get("type") or ""):
            emit(f"  Feed-link: {urljoin(url, link.get('href', ''))} ({link.get('type')})")
    articles = soup.find_all("article")
    emit(f"  <article>-elementen: {len(articles)}")
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


def probe(url: str, guess_feeds: bool, agent: str = USER_AGENT, pattern: str | None = None) -> None:
    emit("")
    emit(f"## {url}")
    try:
        resp = requests.get(url, headers={"User-Agent": agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    describe_html(resp.url, body)
    if pattern:
        describe_pattern(resp.url, body, pattern)
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
    args = parser.parse_args()
    agent = BROWSER_AGENT if args.browser else USER_AGENT
    for raw in args.urls:
        for url in raw.split():
            probe(url.strip(), args.guess_feeds, agent, args.patroon)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(out_lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
