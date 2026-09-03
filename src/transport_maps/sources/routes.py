"""Wikipedia 'Airlines and destinations' tables -> airline route network."""

import asyncio
import json
import re
import urllib.parse

import httpx
import polars as pl
from selectolax.parser import HTMLParser

from transport_maps import config
from transport_maps.sources import airports, wikidata
from transport_maps.sources._utils import _atomic_write

REST_HTML = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}
# Each REST HTML page is fetched independently and each is roughly 1 MB, so a
# ~4,000-page crawl is dominated by network round trips, not CPU. A bounded
# pool of concurrent requests (rather than one request at a time) is what
# keeps the crawl to minutes instead of hours; the descriptive User-Agent is
# what makes this level of concurrency acceptable to Wikipedia.
CONCURRENCY = 16
MAX_RETRIES = 6
# Batch cache flushes to bound json.dumps/write overhead on a large, still-
# growing cache, while still capping lost work on interruption to one batch.
SAVE_EVERY = 25

_SKIP_PREFIXES = (
    "File:", "Category:", "Help:", "Template:", "Special:", "Portal:", "Wikipedia:",
)
_HEADING_RE = re.compile(r"airlines?\s+and\s+destinations", re.IGNORECASE)
# Large airports split destinations into "Passenger" and "Cargo" subsections.
# Cargo routes carry no passengers, so they must not become graph edges.
_EXCLUDE_SUBSECTION_RE = re.compile(r"cargo|freight", re.IGNORECASE)


def _destination_tables(tree: HTMLParser) -> list:
    """Tables under the 'Airlines and destinations' section, minus cargo subsections.

    The REST HTML nests <section> elements, and on big airports the tables sit in
    an h3 subsection ("Passenger"), NOT directly under the h2. Walking previous
    siblings therefore finds "Passenger" and never the h2 - which yields zero
    destinations. Find the owning section and descend instead.
    """
    for section in tree.css("section"):
        headings = section.css("h2")
        if not headings or not _HEADING_RE.search(headings[0].text() or ""):
            continue
        tables = []
        for table in section.css("table"):
            node, excluded = table.parent, False
            while node is not None and node is not section:
                if node.tag == "section":
                    sub = node.css("h2,h3,h4")
                    if sub and _EXCLUDE_SUBSECTION_RE.search(sub[0].text() or ""):
                        excluded = True
                        break
                node = node.parent
            if not excluded:
                tables.append(table)
        return tables
    return []


def parse_destinations(html: str) -> list[str]:
    """Wiki article titles linked from the Airlines and destinations table(s)."""
    tree = HTMLParser(html)
    titles: list[str] = []

    for table in _destination_tables(tree):
        for anchor in table.css("a[href]"):
            href = anchor.attributes.get("href", "")
            if href.startswith("./"):
                title = href[2:]
            elif "/wiki/" in href:
                title = href.split("/wiki/")[-1]
            else:
                continue
            title = urllib.parse.unquote(title.split("#")[0])
            if not title or title.startswith(_SKIP_PREFIXES):
                continue
            titles.append(title)

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(titles))


async def _fetch_page_html_async(
    client: httpx.AsyncClient, iata: str, title: str, semaphore: asyncio.Semaphore
) -> tuple[str, list[str] | None]:
    """Fetch and parse one airport's REST HTML, retrying on 429 with backoff.

    Returns (iata, None) for a missing page (404) rather than raising, since a
    stale or renamed wikipedia_link in the OurAirports data should not abort
    the whole crawl over one airport.
    """
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(REST_HTML.format(title=urllib.parse.quote(title, safe="")))
            except httpx.TransportError:
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2**attempt)
                continue
            if r.status_code == 404:
                return iata, None
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 2**attempt))
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return iata, parse_destinations(r.text)
    raise RuntimeError(f"exhausted retries fetching {iata} ({title!r}, HTTP 429)")


def _destination_cache_path():
    return config.CACHE / "airline_destinations.json"


def _load_destination_cache() -> dict[str, list[str] | None]:
    """IATA -> parsed destination titles, or None for a 404'd article.

    Persisted incrementally during the crawl so an interrupted run resumes
    from the last completed airport instead of refetching from scratch.
    """
    path = _destination_cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_destination_cache(cache: dict[str, list[str] | None]) -> None:
    path = _destination_cache_path()
    _atomic_write(path, lambda tmp: tmp.write_text(json.dumps(cache)))


async def _crawl_destinations_async(
    titles_by_iata: dict[str, str],
) -> dict[str, list[str] | None]:
    config.ensure_dirs()
    cache = _load_destination_cache()
    todo = [(iata, title) for iata, title in titles_by_iata.items() if iata not in cache]
    if not todo:
        return cache

    print(f"routes: {len(cache)} airports cached, {len(todo)} to fetch "
          f"(concurrency={CONCURRENCY})")
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=60, headers=HEADERS, follow_redirects=True) as client:
        tasks = [
            asyncio.create_task(_fetch_page_html_async(client, iata, title, semaphore))
            for iata, title in todo
        ]
        for n, coro in enumerate(asyncio.as_completed(tasks), start=1):
            iata, dest_titles = await coro
            cache[iata] = dest_titles
            if n % SAVE_EVERY == 0 or n == len(todo):
                _save_destination_cache(cache)
            if n % 100 == 0 or n == len(todo):
                print(f"routes: fetched {n}/{len(todo)} ({iata})")
    return cache


def _crawl_destinations(titles_by_iata: dict[str, str]) -> dict[str, list[str] | None]:
    """Fetch and parse each airport's destinations page, resuming from cache."""
    return asyncio.run(_crawl_destinations_async(titles_by_iata))


def route_network() -> pl.DataFrame:
    """Directed airport pairs with scheduled service. Cached to parquet."""
    out = config.BUILD / "routes.parquet"
    if out.exists():
        return pl.read_parquet(out)

    apts = airports.scheduled_airports()
    valid = set(apts["iata"].to_list())
    titles_by_iata = _wikipedia_titles(apts)

    destinations = _crawl_destinations(titles_by_iata)

    # Resolve every distinct destination title once, in bulk, rather than per
    # airport: wikidata.iata_for_titles() already caches by title, so this
    # keeps the crawl from re-querying the same handful of hub airports
    # (Narita, Los Angeles, ...) thousands of times over.
    all_titles = sorted({t for titles in destinations.values() if titles for t in titles})
    resolved = wikidata.iata_for_titles(all_titles)

    pairs: set[tuple[str, str]] = set()
    for iata, dest_titles in destinations.items():
        if not dest_titles:
            continue
        for title in dest_titles:
            dest_iata = resolved.get(title)
            if dest_iata and dest_iata in valid and dest_iata != iata:
                pairs.add((iata, dest_iata))
                pairs.add((dest_iata, iata))  # scheduled service is bidirectional

    if len(pairs) < 20_000:
        raise RuntimeError(f"route network implausibly small: {len(pairs)} pairs")

    df = pl.DataFrame(sorted(pairs), schema=["src", "dst"], orient="row")
    _atomic_write(out, lambda tmp: df.write_parquet(tmp))
    return df


def _wikipedia_titles(apts: pl.DataFrame) -> dict[str, str]:
    """IATA -> Wikipedia article title, from the OurAirports wikipedia_link column."""
    raw = pl.read_csv(config.CACHE / "ourairports.csv", infer_schema_length=10_000)
    linked = raw.filter(
        pl.col("iata_code").is_in(apts["iata"]) & pl.col("wikipedia_link").is_not_null()
    )
    titles: dict[str, str] = {}
    for iata, link in zip(linked["iata_code"], linked["wikipedia_link"]):
        if "/wiki/" in link:
            titles[iata] = urllib.parse.unquote(link.split("/wiki/")[-1].split("#")[0])
    return titles
