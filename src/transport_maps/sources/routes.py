"""Wikipedia 'Airlines and destinations' sections -> airline route network."""

import collections
import itertools
import json
import re
import time
import urllib.parse

import httpx
import polars as pl

from transport_maps import config
from transport_maps.sources import airports, wikidata
from transport_maps.sources._utils import (
    IncompleteResponse,
    _atomic_write,
    _params_hash,
    _refuse_partial,
    _retry_after_seconds,
    _validated_json,
)

ACTION_API = "https://en.wikipedia.org/w/api.php"
TITLES_PER_REQUEST = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build; https://worldmap.atik.kr/)"}
MAX_RETRIES = 6

# Both heading patterns capture the leading "=" run so the section can be
# closed at the next heading of the same level or shallower (_section_end).
# The section is not always level 2: an article that files it under
# "== Operations ==" has it at level 3, and closing it only at the next
# level-2 heading read its sibling sections as destinations (CR13-2).
_SECTION_RE = re.compile(r"^(==+)\s*Airlines and destinations\s*==+\s*$", re.IGNORECASE | re.MULTILINE)
# Cargo routes carry no passengers, so they must not become graph edges.
_CARGO_RE = re.compile(r"^(===+)\s*(?:Cargo|Freight)[^=]*=+\s*$", re.IGNORECASE | re.MULTILINE)
# Captures the article title, stopping at a "#Section" fragment, which may
# precede the "|label". Without the fragment group a link such as
# [[Tokyo International Airport#Terminal 3|Haneda]] matched nothing at all
# and the destination was silently dropped (CR13-6). A same-page link,
# [[#Ground transport]], has no title and still matches nothing.
_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
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


def _section_end(text: str, level: int, pos: int) -> int:
    """Offset of the first heading at `level` or shallower (a sibling or a
    parent) at or after `pos`, or the end of `text` if there is none."""
    boundary = re.compile(rf"^={{2,{level}}}[^=]", re.MULTILINE).search(text, pos)
    return boundary.start() if boundary is not None else len(text)


def _strip_cargo_subsections(body: str) -> str:
    """Remove Cargo/Freight subsections without discarding what follows them.

    Cutting everything from the first Cargo heading to the end of the body
    would also throw away any later Passenger subsection. Excise only the
    span from a Cargo heading up to the next heading at the same level or
    shallower (a sibling or parent section), or to the end of the body if
    there is none.
    """
    while True:
        cargo = _CARGO_RE.search(body)
        if cargo is None:
            return body
        end = _section_end(body, len(cargo.group(1)), cargo.end())
        body = body[: cargo.start()] + body[end:]


def parse_destinations(wikitext: str) -> list[str]:
    """Wiki article titles linked from the Airlines and destinations section."""
    match = _SECTION_RE.search(wikitext)
    if match is None:
        return []

    body = wikitext[match.end(): _section_end(wikitext, len(match.group(1)), match.end())]
    body = _strip_cargo_subsections(body)

    titles: list[str] = []
    for raw in _LINK_RE.findall(body):
        title = raw.strip().replace(" ", "_")
        if not title or title.startswith(_SKIP_PREFIXES):
            continue
        titles.append(title)

    return list(dict.fromkeys(titles))


def _fetch_wikitext(
    client: httpx.Client, titles: list[str]
) -> tuple[dict[str, str], set[str]]:
    """Article title -> wikitext, plus the titles enwiki confirms do not exist.

    Returns `(content_by_title, confirmed_absent)`. A title in neither is one
    the API did not account for at all -- treat that as an unresolved fetch to
    retry, NOT as "this airport has no destinations". Conflating the two is
    how a title whose article merely failed to come back gets cached forever
    as a destination-less airport.
    """
    r = client.get(ACTION_API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "redirects": "1",
        "titles": "|".join(titles),
    })
    r.raise_for_status()
    data = _validated_json(r, expect_key="query", require_batchcomplete=True)

    # Resolve content by canonical title first, then map every ORIGINAL
    # title in this batch to its own canonical form (normalize, then follow
    # any redirect) and look that up -- see wikidata._qids_for_titles for
    # why building this the other way around (page -> "the" title that
    # produced it) is wrong: when two different input titles collapse to
    # the same canonical page in one batch, the API reports only one page
    # for both, so a page-keyed alias map can hand it back to only one of
    # them and silently drops the other.
    content_by_canonical: dict[str, str] = {}
    # A page the API marks "missing" (no such article) or "invalid" (not a
    # legal title) is a definitive answer: enwiki has nothing to fetch, now
    # or on any later run. OurAirports' wikipedia_link column points at
    # non-English Wikipedias for a handful of airports (Flugplatz_Juist,
    # Пластун_(аэропорт), Bandar_Udara_Oksibil, ...) and carries the odd
    # typo, so a small number of these is expected and permanent.
    absent_canonical: set[str] = set()
    for page in data.get("pages", []):
        title = page.get("title", "")
        revisions = page.get("revisions")
        if revisions:
            content_by_canonical[title] = revisions[0]["slots"]["main"]["content"]
        elif page.get("missing") or page.get("invalid"):
            absent_canonical.add(title)

    normalize_to = {n["from"]: n["to"] for n in data.get("normalized", [])}
    redirect_to = {r_["from"]: r_["to"] for r_ in data.get("redirects", [])}

    out: dict[str, str] = {}
    confirmed_absent: set[str] = set()
    for original in titles:
        canonical = normalize_to.get(original, original)
        canonical = redirect_to.get(canonical, canonical)
        content = content_by_canonical.get(canonical)
        if content is not None:
            out[original] = content
        elif canonical in absent_canonical:
            confirmed_absent.add(original)
    return out, confirmed_absent


def _fetch_wikitext_with_retry(
    client: httpx.Client, titles: list[str]
) -> tuple[dict[str, str], set[str]]:
    """`_fetch_wikitext`, backing off and retrying on HTTP 429 rather than crashing.

    An API-level error (readonly, maxlag, ...) raises RuntimeError from
    `_validated_json` immediately, without retrying here -- the caller's
    per-batch skip handles that the same way it handles a batch that exhausts
    its 429 retries. An incomplete/paginated response raises
    `IncompleteResponse`, which the caller answers by halving the batch.
    """
    for attempt in range(MAX_RETRIES):
        try:
            return _fetch_wikitext(client, titles)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                time.sleep(_retry_after_seconds(e.response.headers.get("Retry-After"), attempt))
                continue
            raise
    raise RuntimeError("exhausted retries fetching a wikitext batch (HTTP 429)")


# Bump when parse_destinations' own code changes. The per-airport cache below
# stores PARSED destinations, so a parser fix never reaches an airport that is
# already cached unless the cache is rebuilt. The regexes and _SKIP_PREFIXES
# need no bump: _parser_key hashes them directly, so editing one is a miss on
# its own (CR13-13: two of the four regexes used to be left out of the key,
# so a fix to _LINK_RE would have been a silent cache hit).
# 2: the section closes at its own level, not at the next level-2 heading.
PARSER_VERSION = 2


def _parser_key() -> str:
    """Every constant that governs what `parse_destinations` returns.

    Patterns and flags both: dropping re.IGNORECASE from _SECTION_RE changes
    which headings match while `.pattern` stays byte-identical.
    """
    return _params_hash(PARSER_VERSION, _SKIP_PREFIXES,
                        _SECTION_RE.pattern, _SECTION_RE.flags,
                        _CARGO_RE.pattern, _CARGO_RE.flags,
                        _LINK_RE.pattern, _LINK_RE.flags)


def _destination_cache_path():
    return config.CACHE / "airline_destinations.json"


def _load_destination_cache() -> dict[str, list[str] | None]:
    """Article title -> parsed destination titles, or None for an absent article.

    Keyed on the ARTICLE, which is what was fetched and parsed, not on the
    IATA code: when OurAirports re-points a code at a different article, an
    IATA-keyed entry kept serving the old article's destinations.

    Persisted incrementally during the crawl so an interrupted run resumes
    from the last completed batch instead of refetching from scratch. A cache
    parsed under any other `_parser_key` is a miss and the crawl starts over,
    and so is one written before the key existed (the flat format and the
    `_parser_version` one, both keyed by IATA): nothing in it says which parser
    produced it.
    """
    path = _destination_cache_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    stamp = raw.get("_parser_key")
    if stamp != _parser_key() or "articles" not in raw:
        print(f"routes: destination cache was parsed under key {stamp}, parser is "
              f"{_parser_key()}; re-crawling", flush=True)
        return {}
    return raw["articles"]


def _save_destination_cache(cache: dict[str, list[str] | None]) -> None:
    path = _destination_cache_path()
    payload = {"_parser_key": _parser_key(), "articles": cache}
    _atomic_write(path, lambda tmp: tmp.write_text(json.dumps(payload)))


def _crawl_destinations(
    titles_by_iata: dict[str, str],
) -> tuple[dict[str, list[str] | None], list[str]]:
    """Fetch and parse each airport's destinations section, resuming from cache.

    Wikipedia's Action API returns up to TITLES_PER_REQUEST full-article
    wikitexts per call, so ~4,000 airports cost on the order of 80 requests
    rather than one per airport.

    Returns `(destinations, unresolved)`, both by IATA code. `unresolved` lists
    every code whose article this run could not settle either way -- a batch
    that failed outright, or a title the API neither returned content for nor
    confirmed absent. Those articles are deliberately NOT written to the cache,
    so a re-run refetches exactly them and nothing else; the caller must refuse
    to persist a route network while the list is non-empty (see
    `route_network`).
    """
    config.ensure_dirs()
    cache = _load_destination_cache()
    todo = list(dict.fromkeys(t for t in titles_by_iata.values() if t not in cache))
    if todo:
        pending = collections.deque(itertools.batched(todo, TITLES_PER_REQUEST))
        print(f"routes: {len(cache)} articles cached, {len(todo)} to fetch in {len(pending)} batches")
        n = 0
        with httpx.Client(timeout=60, headers=HEADERS, follow_redirects=True) as client:
            while pending:
                batch = pending.popleft()
                n += 1
                try:
                    wikitext_by_title, confirmed_absent = _fetch_wikitext_with_retry(client, list(batch))
                except IncompleteResponse as e:
                    # Fifty whole articles can exceed one response, and the API
                    # then pages: part of the batch and a `continue`. The batch
                    # is a pure function of what is still uncached, so a re-run
                    # asks for the same fifty and fails the same way, and
                    # route_network refuses forever (A11, CR-18). Halve it and
                    # ask again at once; one article always fits.
                    if len(batch) > 1:
                        half = len(batch) // 2
                        pending.extendleft((batch[half:], batch[:half]))
                        print(f"routes: batch {n} of {len(batch)} came back partial; "
                              f"asking again as {half} and {len(batch) - half}")
                        continue
                    print(f"routes: batch {n} failed: {e!r}")
                except (httpx.HTTPStatusError, httpx.TransportError, RuntimeError) as e:
                    print(f"routes: batch {n} failed: {e!r}")
                else:
                    for title in batch:
                        wikitext = wikitext_by_title.get(title)
                        if wikitext is not None:
                            cache[title] = parse_destinations(wikitext)
                        elif title in confirmed_absent:
                            # enwiki has no such article; nothing to fetch, ever.
                            cache[title] = None
                    _save_destination_cache(cache)
                print(f"routes: batch {n} done ({len(cache)} articles cached, "
                      f"{len(pending)} batches left)")

    destinations = {iata: cache[t] for iata, t in titles_by_iata.items() if t in cache}
    unresolved = [iata for iata, t in titles_by_iata.items() if t not in cache]
    if unresolved:
        print(f"routes: {len(unresolved)} airports unresolved this run")
    return destinations, unresolved


def _network_cache_path(iatas: list[str], titles_by_iata: dict[str, str]):
    """Stamped with everything that shapes the pair set: the parser and the
    resolver, the sanity pairs, and both inputs -- the airports a pair may
    join and the article crawled for each.

    The inputs are hashed whole. The airport table's stamped name, which this
    used to carry instead, records the rules the table was built under but not
    the OurAirports download it was built from, and says nothing about the
    article links. The bare routes.parquet before that was keyed on
    `.exists()` and is no longer read at all (CR13-3)."""
    stamp = _params_hash(_parser_key(), wikidata.RESOLVER_VERSION, _SANITY_PAIRS,
                         sorted(iatas), sorted(titles_by_iata.items()))
    return config.BUILD / f"routes_{stamp}.parquet"


def route_network() -> pl.DataFrame:
    """Directed airport pairs with scheduled service. Cached to parquet.

    The airport table and the article links are read before the cache is
    consulted because they are part of its key; both are local files.
    """
    apts = airports.scheduled_airports()
    valid = set(apts["iata"].to_list())
    titles_by_iata = _wikipedia_titles(apts)

    out = _network_cache_path(sorted(valid), titles_by_iata)
    if out.exists():
        return pl.read_parquet(out)
    legacy = config.BUILD / "routes.parquet"
    if legacy.exists():
        # CR13-3: this file used to be returned here, and since this branch
        # never wrote `out`, it won on every later run too -- so no parser,
        # resolver or airport-table change could ever reach the network. It
        # records no inputs, so it is not evidence of anything; say so once.
        print(f"routes: ignoring legacy {legacy.name}, whose inputs are unknown; "
              f"building {out.name}", flush=True)

    destinations, unresolved = _crawl_destinations(titles_by_iata)
    _refuse_partial(
        "destination crawl", unresolved,
        "re-run to refetch exactly these; the per-airport cache keeps the rest",
    )

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
    """IATA -> Wikipedia article title, from the OurAirports wikipedia_link column.

    Read through `airports._download()` rather than straight off the cache
    path (CR13-24): this now runs on every call, cache hit or not, because the
    result is part of the network's key, and a cached airport table does not
    mean the CSV it came from is still on disk.
    """
    raw = pl.read_csv(airports._download(), infer_schema_length=10_000)
    linked = raw.filter(
        pl.col("iata_code").is_in(apts["iata"]) & pl.col("wikipedia_link").is_not_null()
    )
    titles: dict[str, str] = {}
    for iata, link in zip(linked["iata_code"], linked["wikipedia_link"]):
        if "/wiki/" in link:
            titles[iata] = urllib.parse.unquote(link.split("/wiki/")[-1].split("#")[0])
    return titles
