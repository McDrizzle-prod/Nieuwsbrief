"""Ophalers per brontype. Elke ophaler geeft een lijst RawItem terug."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup

from .util import (
    FetchError,
    Http,
    clean_text,
    fill_template,
    find_date_in_text,
    get_path,
    item_id,
    now_utc,
    parse_date,
    struct_to_iso,
)

SUMMARY_LIMIT = 600


@dataclass
class RawItem:
    title: str
    url: str
    published: str | None = None
    summary: str = ""


@dataclass
class Context:
    http: Http
    state: dict = field(default_factory=dict)
    known_ids: set = field(default_factory=set)


def fetch(source: dict, ctx: Context) -> list[RawItem]:
    kind = source.get("type")
    if kind not in FETCHERS:
        raise FetchError(f"onbekend brontype '{kind}'")
    items = FETCHERS[kind](source, ctx)
    return [i for i in items if i.title and i.url]


# --- RSS/Atom ------------------------------------------------------------------

def fetch_feed(source: dict, ctx: Context) -> list[RawItem]:
    resp = ctx.http.get(source["url"])
    parsed = feedparser.parse(resp.content)
    if not parsed.entries:
        if parsed.bozo:
            raise FetchError(f"geen geldige feed ({parsed.bozo_exception.__class__.__name__})")
        return []
    prefix = source.get("titel_prefix", "")
    items = []
    for entry in parsed.entries[: source.get("max", 60)]:
        content = entry.get("summary") or ""
        if not content and entry.get("content"):
            content = entry["content"][0].get("value", "")
        items.append(RawItem(
            title=prefix + clean_text(entry.get("title")),
            url=urljoin(source["url"], entry.get("link", "")),
            published=struct_to_iso(entry.get("published_parsed") or entry.get("updated_parsed")),
            summary=clean_text(content, SUMMARY_LIMIT),
        ))
    return items


# --- HTML-lijstpagina's ------------------------------------------------------------

def _soup(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(content, "lxml")


def _date_from_node(node) -> str | None:
    if node is None:
        return None
    time_tag = node if node.name == "time" else node.find("time")
    if time_tag is not None:
        found = parse_date(time_tag.get("datetime")) or parse_date(time_tag.get_text(" ", strip=True))
        if found:
            return found
    return find_date_in_text(node.get_text(" ", strip=True)[:400])


def _container(anchor, base: str, pattern: re.Pattern):
    """Grootste omliggende blok dat alleen bij dit bericht hoort (geen links naar andere berichten)."""
    own = urljoin(base, anchor["href"]).split("#")[0]
    node = anchor
    for _ in range(6):
        parent = node.parent
        if parent is None or parent.name in ("body", "html", "main", "[document]"):
            break
        others = {
            url for a in parent.find_all("a", href=True)
            if pattern.search(urlparse(url := urljoin(base, a["href"]).split("#")[0]).path) and url != own
        }
        if others:
            break
        node = parent
        if node.name in ("article", "li"):
            break
    return node


GENERIC_LINK_TEXT = {
    "read more", "lees meer", "lees verder", "continue reading", "meer", "more", "learn more",
    "meer informatie", "more information", "details", "bekijk", "view", "open",
}


def _best_title(container, anchors) -> str:
    """Titel van een bericht: liefst de kop in het blok, anders de beste linktekst."""
    heading = container.find(["h1", "h2", "h3", "h4", "h5"]) if container.name not in ("h1", "h2", "h3", "h4", "h5") else container
    if heading is not None:
        text = clean_text(heading.get_text(" "))
        if len(text) >= 12:
            return text
    candidates = []
    for anchor in anchors:
        for text in (anchor.get_text(" "), anchor.get("title", ""), anchor.get("aria-label", "")):
            text = clean_text(text)
            if len(text) >= 12 and text.lower().strip(" .…›»→>") not in GENERIC_LINK_TEXT:
                candidates.append(text)
    return min(candidates, key=len) if candidates else ""


def fetch_html(source: dict, ctx: Context) -> list[RawItem]:
    resp = ctx.http.get(source["url"])
    soup = _soup(resp.content)
    base = resp.url
    selectors = source.get("selectors")
    items: list[RawItem] = []
    if selectors:
        for node in soup.select(selectors["item"]):
            link_node = node.select_one(selectors.get("link", "a[href]"))
            title_node = node.select_one(selectors.get("titel", "a")) or link_node
            if link_node is None or title_node is None:
                continue
            date_node = node.select_one(selectors["datum"]) if selectors.get("datum") else node
            summary_node = node.select_one(selectors["samenvatting"]) if selectors.get("samenvatting") else None
            items.append(RawItem(
                title=clean_text(title_node.get_text(" ")),
                url=urljoin(base, link_node.get("href", "")),
                published=_date_from_node(date_node),
                summary=clean_text(summary_node.get_text(" ") if summary_node else "", SUMMARY_LIMIT),
            ))
    else:
        pattern = re.compile(source["link_patroon"])
        exclude = re.compile(source["link_uitsluiten"]) if source.get("link_uitsluiten") else None
        host = urlparse(base).netloc
        groups: dict[str, list] = {}
        for anchor in soup.find_all("a", href=True):
            url = urljoin(base, anchor["href"]).split("#")[0]
            path = urlparse(url).path
            if urlparse(url).netloc != host or not pattern.search(path):
                continue
            if url.rstrip("/") == base.split("#")[0].rstrip("/") or (exclude and exclude.search(url)):
                continue
            groups.setdefault(url, []).append(anchor)
        for url, anchors in groups.items():
            container = max((_container(a, base, pattern) for a in anchors),
                            key=lambda node: len(node.get_text(" ", strip=True)))
            title = _best_title(container, anchors)
            if not title:
                continue
            summary = ""
            for paragraph in container.find_all("p"):
                text = clean_text(paragraph.get_text(" "))
                if text and text != title and len(text) > 20:
                    summary = clean_text(text, SUMMARY_LIMIT)
                    break
            items.append(RawItem(title=title, url=url, published=_date_from_node(container), summary=summary))
    items = items[: source.get("max", 40)]
    if source.get("detail"):
        _add_details(items, ctx, source.get("detail_max", 12))
    return items


def _add_details(items: list[RawItem], ctx: Context, limit: int) -> None:
    """Datum en beschrijving van de berichtpagina zelf halen (alleen voor nieuwe berichten)."""
    fetched = 0
    for item in items:
        if fetched >= limit or item_id(item.url) in ctx.known_ids:
            continue
        if item.published and item.summary:
            continue
        fetched += 1
        try:
            page = _soup(ctx.http.get(item.url).content)
        except FetchError:
            continue
        meta = {}
        for tag in page.find_all("meta"):
            key = tag.get("property") or tag.get("name") or tag.get("itemprop")
            if key and tag.get("content"):
                meta.setdefault(key.lower(), tag["content"])
        if not item.published:
            item.published = (
                parse_date(meta.get("article:published_time"))
                or parse_date(meta.get("datepublished"))
                or parse_date(meta.get("date"))
                or _jsonld_date(page)
                or _date_from_node(page.find("time"))
                or _date_from_node(page.find("main") or page.find("article"))
            )
        if not item.summary:
            item.summary = clean_text(meta.get("og:description") or meta.get("description"), SUMMARY_LIMIT)


def _jsonld_date(page: BeautifulSoup) -> str | None:
    for script in page.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for node in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(node, dict) and node.get("datePublished"):
                return parse_date(node["datePublished"])
    return None


# --- JSON-API's ------------------------------------------------------------------

def _records_to_items(records: list, source: dict) -> list[RawItem]:
    fields = source.get("velden", {})
    items = []
    for record in records:
        if not isinstance(record, dict):
            continue
        summary = get_path(record, fields.get("samenvatting")) if fields.get("samenvatting") else ""
        items.append(RawItem(
            title=clean_text(fill_template(fields.get("titel", "{title}"), record)),
            url=fill_template(fields.get("url", "{url}"), record),
            published=parse_date(get_path(record, fields.get("datum"))) if fields.get("datum") else None,
            summary=clean_text(summary if isinstance(summary, str) else json.dumps(summary or ""), SUMMARY_LIMIT)
            if summary else "",
        ))
    return items


def fetch_json(source: dict, ctx: Context) -> list[RawItem]:
    resp = ctx.http.get(source["url"], params=source.get("params"), headers=source.get("headers"))
    try:
        data = resp.json()
    except ValueError as exc:
        raise FetchError("antwoord is geen JSON") from exc
    records = get_path(data, source.get("items"))
    if records is None:
        raise FetchError(f"pad '{source.get('items')}' niet gevonden in JSON-antwoord")
    if isinstance(records, dict):
        records = list(records.values())
    return _records_to_items(records[: source.get("max", 60)], source)


# --- SPARQL (EUR-Lex / CELLAR) -------------------------------------------------

def fetch_sparql(source: dict, ctx: Context) -> list[RawItem]:
    since = (now_utc() - timedelta(days=source.get("dagen_terug", 365))).date().isoformat()
    query = source["query"].replace("{since}", since)
    resp = ctx.http.get(source["url"], params={"query": query, "format": "application/sparql-results+json"},
                        headers={"Accept": "application/sparql-results+json"})
    try:
        bindings = resp.json()["results"]["bindings"]
    except (ValueError, KeyError) as exc:
        raise FetchError("onverwacht SPARQL-antwoord") from exc
    records = [{k: v.get("value") for k, v in row.items()} for row in bindings]
    items = _records_to_items(records, source)
    # Eén regel per document: titels kunnen per taalversie dubbel voorkomen.
    unique: dict[str, RawItem] = {}
    for item in items:
        unique.setdefault(item.url, item)
    return list(unique.values())


# --- SRU (officielebekendmakingen.nl) ---------------------------------------------

def fetch_sru(source: dict, ctx: Context) -> list[RawItem]:
    query = " ".join(source["query"].split())
    sort = source.get("sortering", "dt.modified/sort.descending")
    params = {
        "query": f"{query} sortBy {sort}" if sort else query,
        "maximumRecords": source.get("max", 40),
        "httpAccept": "application/xml",
    }
    resp = ctx.http.get(source["url"], params=params)
    soup = BeautifulSoup(resp.content, "xml")
    items = []
    for record in soup.find_all("recordData"):
        title = record.find("title")
        url = record.find("preferredUrl") or record.find("url")
        date = record.find("available") or record.find("issued") or record.find("modified") or record.find("date")
        doc_type = record.find("type")
        if not title or not url:
            continue
        summary = clean_text(doc_type.get_text()) if doc_type else ""
        items.append(RawItem(
            title=clean_text(title.get_text()),
            url=url.get_text().strip(),
            published=parse_date(date.get_text()) if date else None,
            summary=summary,
        ))
    if not items and soup.find("diagnostic"):
        raise FetchError("SRU-fout: " + clean_text(soup.find("diagnostic").get_text(), 200))
    return items


# --- Pagina's volgen op wijzigingen ----------------------------------------------

def _page_text(content: bytes, selector: str | None) -> str:
    soup = _soup(content)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "iframe"]):
        tag.decompose()
    node = None
    if selector:
        for part in selector.split(","):
            node = soup.select_one(part.strip())
            if node is not None:
                break
    node = node or soup.body or soup
    lines = [" ".join(line.split()) for line in node.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_pagewatch(source: dict, ctx: Context) -> list[RawItem]:
    resp = ctx.http.get(source["url"])
    text = _page_text(resp.content, source.get("selector"))
    if len(text) < 80:
        raise FetchError("pagina bevat (bijna) geen tekst; klopt de selector?")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    watched = ctx.state.setdefault("pagewatch", {})
    previous = watched.get(source["id"])
    now = now_utc()
    watched[source["id"]] = {"hash": digest, "text": text[:60000], "checked": now.isoformat()}
    if previous is None or previous.get("hash") == digest:
        if previous is not None:
            watched[source["id"]]["changed"] = previous.get("changed")
        return []
    watched[source["id"]]["changed"] = now.isoformat()
    old_lines = previous.get("text", "").splitlines()
    added = [line[2:] for line in difflib.ndiff(old_lines, text.splitlines())
             if line.startswith("+ ") and len(line) > 12]
    summary = "Nieuw of gewijzigd op de pagina: " + " · ".join(added) if added else "De pagina is gewijzigd."
    stamp = now.strftime("%Y-%m-%d")
    return [RawItem(
        title=f"Bijgewerkt: {source.get('titel', source['naam'])}",
        url=f"{source['url']}#wijziging-{stamp}",
        published=stamp,
        summary=clean_text(summary, SUMMARY_LIMIT),
    )]


FETCHERS = {
    "feed": fetch_feed,
    "html": fetch_html,
    "json": fetch_json,
    "sparql": fetch_sparql,
    "sru": fetch_sru,
    "pagewatch": fetch_pagewatch,
}
