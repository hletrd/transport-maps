"""Resolve Wikipedia article titles to IATA codes via Wikidata property P238."""

import json
import time

import httpx

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
IATA_PROPERTY = "P238"
BATCH = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}
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
            wait = float(r.headers.get("Retry-After", 2**attempt))
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"exhausted retries fetching {url!r}")


def _qids_for_titles(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(titles, BATCH):
        r = _get_with_retry(client, WIKIPEDIA_API, {
            "action": "query", "format": "json", "redirects": "1",
            "prop": "pageprops", "ppprop": "wikibase_item",
            "titles": "|".join(batch),
        })
        data = r.json().get("query", {})

        # Resolve QIDs by canonical title first, then map every ORIGINAL
        # title in this batch to its own canonical form (normalize, then
        # follow any redirect) and look that up. Building this the other
        # way around -- from each returned page back to "the" title that
        # produced it -- silently drops input titles: when two different
        # titles in one batch collapse to the same canonical page (e.g. a
        # redirect alias like "Narita_Airport" alongside the canonical
        # "Narita_International_Airport"), the API reports only ONE page
        # for both, so a page-keyed alias map can recover only one of the
        # two original titles and drops the other -- caching it as "not an
        # airport" even though it plainly is one.
        qid_by_canonical: dict[str, str] = {}
        for page in data.get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                qid_by_canonical[page.get("title", "")] = qid

        normalize_to = {n["from"]: n["to"] for n in data.get("normalized", [])}
        redirect_to = {r_["from"]: r_["to"] for r_ in data.get("redirects", [])}

        for original in batch:
            canonical = normalize_to.get(original, original)
            canonical = redirect_to.get(canonical, canonical)
            qid = qid_by_canonical.get(canonical)
            if qid:
                out[original] = qid
    return out


def _iata_for_qids(client: httpx.Client, qids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(qids, BATCH):
        r = _get_with_retry(client, WIKIDATA_API, {
            "action": "wbgetentities", "format": "json",
            "props": "claims", "ids": "|".join(batch),
        })
        for qid, entity in r.json().get("entities", {}).items():
            claims = entity.get("claims", {}).get(IATA_PROPERTY, [])
            for claim in claims:
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str) and len(value) == 3:
                    out[qid] = value.upper()
                    break
    return out


def _resolve_batch(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """Resolve one batch (<= BATCH titles) straight through to IATA codes."""
    qids = _qids_for_titles(client, titles)
    if not qids:
        return {}
    iata = _iata_for_qids(client, sorted(set(qids.values())))
    return {title: iata.get(qid, "") for title, qid in qids.items()}


def _cache_path():
    return config.CACHE / "wikidata_iata.json"


def _save_cache(cache: dict[str, str]) -> None:
    _atomic_write(_cache_path(), lambda tmp: tmp.write_text(json.dumps(cache, sort_keys=True)))


def iata_for_titles(titles: list[str]) -> dict[str, str]:
    """Article title -> IATA code, omitting titles that are not airports.

    Resolved one batch of BATCH titles at a time, flushing to disk every
    SAVE_EVERY batches, so an interrupted or partially failed run keeps
    everything resolved so far: a re-run only retries what's left. A title
    stays un-cached (and so is retried later) unless it was actually queried
    and found to lack (or have) property P238 -- a batch that fails outright
    after retries is skipped, not recorded as "not an airport".
    """
    config.ensure_dirs()
    cache: dict[str, str] = json.loads(_cache_path().read_text()) if _cache_path().exists() else {}

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
                    print(f"wikidata: batch {n}/{len(batches)} failed, will retry "
                          f"next run: {e!r}")
                else:
                    for title in batch:
                        cache[title] = resolved.get(title, "")
                if n % SAVE_EVERY == 0 or n == len(batches):
                    _save_cache(cache)
                if n % 20 == 0 or n == len(batches):
                    print(f"wikidata: batch {n}/{len(batches)} done ({len(cache)} titles cached)")
                time.sleep(BATCH_DELAY_S)
        if failed_titles:
            print(f"wikidata: {len(failed_titles)} titles unresolved this run "
                  "(will retry on next call)")

    return {t: cache[t] for t in titles if cache.get(t)}
