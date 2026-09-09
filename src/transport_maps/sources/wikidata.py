"""Resolve Wikipedia article titles to IATA codes via Wikidata property P238."""

import json
import time

import httpx

from transport_maps import config
from transport_maps.sources._utils import (
    _atomic_write,
    _refuse_partial,
    _retry_after_seconds,
    _validated_json,
)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
IATA_PROPERTY = "P238"
BATCH = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build; https://worldmap.atik.kr/)"}
MAX_RETRIES = 6
# Flush the cache this often (in batches), not just at the end: route_network()
# resolves thousands of distinct destination titles in one bulk pass, which is
# enough sequential requests that a late failure must not discard everything
# resolved before it.
SAVE_EVERY = 5
# Courtesy pacing between requests, on top of per-request retry/backoff.
BATCH_DELAY_S = 0.1


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _get_with_retry(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    """GET with backoff-and-retry on HTTP 429 and on dropped connections.

    A bulk resolution pass over thousands of titles is enough batched
    requests in a tight loop to trip the Action API's own burst limiter
    (HTTP 429) or, observed in practice, to have the server simply drop the
    connection mid-response (httpx.TransportError) even though this API is
    far more generous than the REST HTML endpoint. Retrying rather than
    crashing keeps either failure mode from taking down the whole build.
    """
    for attempt in range(MAX_RETRIES):
        try:
            r = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2**attempt)
            continue
        if r.status_code == 429:
            if attempt == MAX_RETRIES - 1:
                r.raise_for_status()
            time.sleep(_retry_after_seconds(r.headers.get("Retry-After"), attempt))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"exhausted retries fetching {url!r}")


def _qids_for_titles(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """Resolve up to BATCH titles to Wikidata QIDs in a single request."""
    r = _get_with_retry(client, WIKIPEDIA_API, {
        "action": "query", "format": "json", "redirects": "1",
        "prop": "pageprops", "ppprop": "wikibase_item",
        "titles": "|".join(titles),
    })
    data = _validated_json(r, expect_key="query", require_batchcomplete=True)

    # Resolve QIDs by canonical title first, then map every ORIGINAL title
    # in this batch to its own canonical form (normalize, then follow any
    # redirect) and look that up. Building this the other way around --
    # from each returned page back to "the" title that produced it --
    # silently drops input titles: when two different titles in one batch
    # collapse to the same canonical page (e.g. a redirect alias like
    # "Narita_Airport" alongside the canonical "Narita_International_
    # Airport"), the API reports only ONE page for both, so a page-keyed
    # alias map can recover only one of the two original titles and drops
    # the other -- caching it as "not an airport" even though it plainly
    # is one.
    qid_by_canonical: dict[str, str] = {}
    for page in data.get("pages", {}).values():
        qid = page.get("pageprops", {}).get("wikibase_item")
        if qid:
            qid_by_canonical[page.get("title", "")] = qid

    normalize_to = {n["from"]: n["to"] for n in data.get("normalized", [])}
    redirect_to = {r_["from"]: r_["to"] for r_ in data.get("redirects", [])}

    out: dict[str, str] = {}
    for original in titles:
        canonical = normalize_to.get(original, original)
        canonical = redirect_to.get(canonical, canonical)
        qid = qid_by_canonical.get(canonical)
        if qid:
            out[original] = qid
    return out


def _iata_for_qids(client: httpx.Client, qids: list[str]) -> dict[str, str]:
    """Resolve up to BATCH QIDs to IATA codes ("" if confirmed P238-less).

    A qid absent from the returned dict was NOT confirmed either way this
    round -- e.g. `wbgetentities` is documented to follow an entity
    redirect by default, and may report the result keyed by the redirect's
    target id rather than the id actually requested, in which case the
    requested id never appears as a response key at all. The caller must
    not conflate "absent from this result" with "confirmed to lack P238":
    doing that once poisoned real, resolvable airports as empty forever,
    since an empty result is cached specifically so it's never re-queried.
    """
    r = _get_with_retry(client, WIKIDATA_API, {
        "action": "wbgetentities", "format": "json",
        "props": "claims", "ids": "|".join(qids),
    })
    entities = _validated_json(r, expect_key="entities", require_batchcomplete=False)

    out: dict[str, str] = {}
    for qid, entity in entities.items():
        if qid not in qids:
            # Reported under a different id than requested (e.g. a
            # redirect target) -- we cannot map it back to which requested
            # id it satisfies, so leave the requested id unconfirmed rather
            # than guessing at a mapping.
            continue
        value = ""
        for claim in entity.get("claims", {}).get(IATA_PROPERTY, []):
            candidate = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(candidate, str) and len(candidate) == 3:
                value = candidate.upper()
                break
        out[qid] = value
    return out


def _resolve_batch(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """Resolve one batch (<= BATCH titles) straight through to IATA codes.

    A title absent from the returned dict was not confirmed either way
    this round and must be retried later, not cached as "not an airport".
    """
    qids = _qids_for_titles(client, titles)
    # Titles that never resolved to any Wikidata item at all (not a valid
    # Wikipedia article, or an article with no linked item) are genuinely
    # not airports -- safe to resolve as "" immediately.
    result: dict[str, str] = {t: "" for t in titles if t not in qids}
    if qids:
        iata = _iata_for_qids(client, sorted(set(qids.values())))
        for title, qid in qids.items():
            if qid in iata:
                result[title] = iata[qid]
            # else: qid's status wasn't confirmed this round -- leave title
            # out of `result` so it's retried on a later call.
    return result


# Bump when the title -> IATA resolution rules change; see routes.PARSER_VERSION.
RESOLVER_VERSION = 1


def _cache_path():
    return config.CACHE / "wikidata_iata.json"


def _load_cache() -> dict[str, str]:
    path = _cache_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    if "_resolver_version" not in raw:
        return raw                                   # legacy flat format == version 1
    if raw["_resolver_version"] != RESOLVER_VERSION:
        print(f"wikidata: title cache was resolved by version {raw['_resolver_version']}, "
              f"resolver is {RESOLVER_VERSION}; re-resolving", flush=True)
        return {}
    return raw["titles"]


def _save_cache(cache: dict[str, str]) -> None:
    payload = {"_resolver_version": RESOLVER_VERSION, "titles": cache}
    _atomic_write(_cache_path(), lambda tmp: tmp.write_text(json.dumps(payload, sort_keys=True)))


def iata_for_titles(titles: list[str]) -> dict[str, str]:
    """Article title -> IATA code, omitting titles that are not airports.

    Resolved one batch of BATCH titles at a time, flushing to disk every
    SAVE_EVERY batches, so an interrupted or partially failed run keeps
    everything resolved so far: a re-run only retries what's left. A title
    stays un-cached (and so is retried later) unless it was actually queried
    and found to lack (or have) property P238 -- a batch that fails outright
    after retries is skipped, not recorded as "not an airport".

    Raises rather than returning a partial mapping when anything was left
    unresolved. The caller (`routes.route_network`) writes its result to
    `routes.parquet` and returns that file forever after, so "retry on the
    next call" never happens: a title silently omitted here is a route
    permanently missing from the shipped network. The flush above still runs
    first, so the re-run this forces is cheap.
    """
    config.ensure_dirs()
    cache: dict[str, str] = _load_cache()

    unknown = [t for t in titles if t not in cache]
    if unknown:
        batches = list(_chunks(unknown, BATCH))
        failed_titles: list[str] = []
        with httpx.Client(timeout=60, headers=HEADERS, follow_redirects=True) as client:
            for n, batch in enumerate(batches, start=1):
                try:
                    resolved = _resolve_batch(client, batch)
                except (httpx.HTTPStatusError, httpx.TransportError, RuntimeError) as e:
                    failed_titles.extend(batch)
                    print(f"wikidata: batch {n}/{len(batches)} failed: {e!r}")
                else:
                    for title in batch:
                        if title in resolved:
                            cache[title] = resolved[title]
                        else:
                            # Unconfirmed this round -- left un-cached so a
                            # re-run retries it, and counted so this run
                            # refuses to hand back a partial mapping.
                            failed_titles.append(title)
                if n % SAVE_EVERY == 0 or n == len(batches):
                    _save_cache(cache)
                if n % 20 == 0 or n == len(batches):
                    print(f"wikidata: batch {n}/{len(batches)} done ({len(cache)} titles cached)")
                time.sleep(BATCH_DELAY_S)
        _refuse_partial(
            "Wikidata IATA resolution", failed_titles,
            "the resolved titles are already cached, so a re-run retries only these",
        )

    return {t: cache[t] for t in titles if cache.get(t)}
