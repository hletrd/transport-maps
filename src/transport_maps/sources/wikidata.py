"""Resolve Wikipedia article titles to IATA codes via Wikidata property P238."""

import json

import httpx

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
IATA_PROPERTY = "P238"
BATCH = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _qids_for_titles(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(titles, BATCH):
        r = client.get(WIKIPEDIA_API, params={
            "action": "query", "format": "json", "redirects": "1",
            "prop": "pageprops", "ppprop": "wikibase_item",
            "titles": "|".join(batch),
        })
        r.raise_for_status()
        data = r.json().get("query", {})
        # Follow redirects back to the title we asked for.
        alias = {r_["to"]: r_["from"] for r_ in data.get("redirects", [])}
        for page in data.get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if not qid:
                continue
            title = page.get("title", "")
            out[alias.get(title, title)] = qid
    return out


def _iata_for_qids(client: httpx.Client, qids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(qids, BATCH):
        r = client.get(WIKIDATA_API, params={
            "action": "wbgetentities", "format": "json",
            "props": "claims", "ids": "|".join(batch),
        })
        r.raise_for_status()
        for qid, entity in r.json().get("entities", {}).items():
            claims = entity.get("claims", {}).get(IATA_PROPERTY, [])
            for claim in claims:
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str) and len(value) == 3:
                    out[qid] = value.upper()
                    break
    return out


def iata_for_titles(titles: list[str]) -> dict[str, str]:
    """Article title -> IATA code, omitting titles that are not airports."""
    config.ensure_dirs()
    cache_path = config.CACHE / "wikidata_iata.json"
    cache: dict[str, str] = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    unknown = [t for t in titles if t not in cache]
    if unknown:
        with httpx.Client(timeout=60, headers=HEADERS, follow_redirects=True) as client:
            qids = _qids_for_titles(client, unknown)
            iata = _iata_for_qids(client, sorted(set(qids.values())))
        for title in unknown:
            qid = qids.get(title)
            cache[title] = iata.get(qid, "") if qid else ""
        _atomic_write(cache_path, lambda tmp: tmp.write_text(json.dumps(cache, sort_keys=True)))

    return {t: cache[t] for t in titles if cache.get(t)}
