"""Wikipedia 'Airlines and destinations' sections -> airline route network."""

import itertools
import json
import re
import time
import urllib.parse

import httpx
import polars as pl

from transport_maps import config
from transport_maps.sources import airports, wikidata
from transport_maps.sources._utils import _atomic_write

ACTION_API = "https://en.wikipedia.org/w/api.php"
TITLES_PER_REQUEST = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}
MAX_RETRIES = 6

_SECTION_RE = re.compile(r"^==+\s*Airlines and destinations\s*==+\s*$", re.IGNORECASE | re.MULTILINE)
# Cargo routes carry no passengers, so they must not become graph edges.
_CARGO_RE = re.compile(r"^===+\s*(Cargo|Freight)[^=]*===+\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_TOP_HEADING_RE = re.compile(r"^==[^=]", re.MULTILINE)
_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]")
_SKIP_PREFIXES = (
    "File:", "Category:", "Help:", "Template:", "Special:", "Portal:", "Wikipedia:",
    "Image:",
)
# Routes so well-established that their absence means the crawl or the
# Wikidata resolution silently broke somewhere, not that the route doesn't
# exist. ICN<->NRT is one of the world's busiest routes; resolver bugs in
# this pipeline have twice produced a network that "built successfully"
# while missing it.
_SANITY_PAIRS: tuple[tuple[str, str], ...] = (("ICN", "NRT"),)


def parse_destinations(wikitext: str) -> list[str]:
    """Wiki article titles linked from the Airlines and destinations section."""
    match = _SECTION_RE.search(wikitext)
    if match is None:
        return []

    body = wikitext[match.end():]
    nxt = _NEXT_TOP_HEADING_RE.search(body)
    if nxt is not None:
        body = body[: nxt.start()]

    cargo = _CARGO_RE.search(body)
    if cargo is not None:
        body = body[: cargo.start()]

    titles: list[str] = []
    for raw in _LINK_RE.findall(body):
        title = raw.strip().replace(" ", "_")
        if not title or title.startswith(_SKIP_PREFIXES):
            continue
        titles.append(title)

    return list(dict.fromkeys(titles))


def _fetch_wikitext(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """Article title -> wikitext, up to TITLES_PER_REQUEST titles per call."""
    r = client.get(ACTION_API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "titles": "|".join(titles),
    })
    r.raise_for_status()
    data = r.json().get("query", {})
    alias = {n["to"]: n["from"] for n in data.get("normalized", [])}
    alias.update({n["to"]: n["from"] for n in data.get("redirects", [])})

    out: dict[str, str] = {}
    for page in data.get("pages", []):
        revisions = page.get("revisions")
        if not revisions:
            continue
        title = page.get("title", "")
        out[alias.get(title, title)] = revisions[0]["slots"]["main"]["content"]
    return out


def _fetch_wikitext_with_retry(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """`_fetch_wikitext`, backing off and retrying on HTTP 429 rather than crashing."""
    for attempt in range(MAX_RETRIES):
        try:
            return _fetch_wikitext(client, titles)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                wait = float(e.response.headers.get("Retry-After", 2**attempt))
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("exhausted retries fetching a wikitext batch (HTTP 429)")


def _destination_cache_path():
    return config.CACHE / "airline_destinations.json"


def _load_destination_cache() -> dict[str, list[str] | None]:
    """IATA -> parsed destination titles, or None for an article with no revision.

    Persisted incrementally during the crawl so an interrupted run resumes
    from the last completed batch instead of refetching from scratch.
    """
    path = _destination_cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_destination_cache(cache: dict[str, list[str] | None]) -> None:
    path = _destination_cache_path()
    _atomic_write(path, lambda tmp: tmp.write_text(json.dumps(cache)))


def _crawl_destinations(titles_by_iata: dict[str, str]) -> dict[str, list[str] | None]:
    """Fetch and parse each airport's destinations section, resuming from cache.

    Wikipedia's Action API returns up to TITLES_PER_REQUEST full-article
    wikitexts per call, so ~4,000 airports cost on the order of 80 requests
    rather than one per airport.
    """
    config.ensure_dirs()
    cache = _load_destination_cache()
    todo = [(iata, title) for iata, title in titles_by_iata.items() if iata not in cache]
    if not todo:
        return cache

    batches = list(itertools.batched(todo, TITLES_PER_REQUEST))
    print(f"routes: {len(cache)} airports cached, {len(todo)} to fetch in {len(batches)} batches")
    with httpx.Client(timeout=60, headers=HEADERS, follow_redirects=True) as client:
        for n, batch in enumerate(batches, start=1):
            titles = [title for _, title in batch]
            wikitext_by_title = _fetch_wikitext_with_retry(client, titles)
            for iata, title in batch:
                wikitext = wikitext_by_title.get(title)
                cache[iata] = parse_destinations(wikitext) if wikitext is not None else None
            _save_destination_cache(cache)
            print(f"routes: batch {n}/{len(batches)} done ({len(cache)} airports cached)")
    return cache


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

    missing_sanity_pairs = [p for p in _SANITY_PAIRS if p not in pairs]
    if missing_sanity_pairs:
        raise RuntimeError(
            f"route network is missing well-known route(s): {missing_sanity_pairs} -- "
            "this means the crawl or Wikidata resolution silently broke somewhere, "
            "not that the route doesn't exist"
        )

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
