"""Wikipedia 'Airlines and destinations' sections -> airline route network.

Only year-round scheduled service becomes a route (owner decision,
2026-10-04). Each destination link in the section is parsed into a `Listing`
that carries its service class, any dated change and the airline of its row,
and `_left_out` decides, against the build's `service_date`, which listings
fly on that day and keep flying. The section's own markup is the only
evidence, so where it is ambiguous a link is left out rather than guessed in.

Where. Only links inside a destination table are read: the {{Airport
destination list}} / {{Airport-dest-list}} template, or a wikitable. Prose in
the section is mostly what no longer flies ("formerly served by", "there are
no scheduled services") and says nothing about season. Not read either: links
in references, in footnote templates, in destination MAPS ({{Location map~}}
pins mark seasonal and future destinations by colour alone), and in any
subsection whose heading names something other than year-round scheduled
passenger flying -- Cargo, Charter, Seasonal, Historical / Former / Previous
service, Statistics / Top destinations / Busiest routes, Destination maps,
Military, Medevac.

Service class. A label opens a class that runs to the end of its CELL -- the
next `|` or `||` of the table, or the template's closing `}}` -- and not just
to the next `<br>`: by the WikiProject Airports convention the year-round
list comes first, and a list that wraps carries on under its label.

    | [[Air New Zealand]] | [[Auckland Airport|Auckland]] <br/> '''Seasonal:''' [[Christchurch Airport|Christchurch]]
        -> Auckland scheduled (kept), Christchurch seasonal (left out)
    | [[China Eastern Airlines]] |''' Seasonal:''' [[Shanghai Pudong International Airport|Shanghai–Pudong]]
        -> the whole row is seasonal: ADL-PVG flies 20 June - 2 August only
    | [[Norse Atlantic Airways]] | '''Seasonal:''' [[Athens]], [[London–Gatwick]], <br />[[Rome–Fiumicino]]
        -> all three seasonal
    '''Charter:''', '''Seasonal charter:''', '''Seasonal''':, an unbolded
        Charter:, and "[[X]] (Seasonal)" / "[[X]] (charter)" after one link -> left out
    '''Hajj & Umrah:''', '''Mining charter:''', '''Notes:''', any other bold
        label ending in a colon                                            -> left out

Dated changes: a parenthesis after the link (references are stripped first,
so `[[X]]<ref>..</ref> (ends ..)` binds to X), judged on the service date D.

    [[X]] (begins 1 June 2026)     kept if the date is on or before D
    [[X]] (resumes 25 October 2026), (suspended until January 18, 2027)
                                   suspended now: kept if the date is on or before D
    [[X]] (ends 8 December 2026)   kept if the date is AFTER D
    [[X]] (suspended), (terminated), (begins TBA)
                                   left out: no date says it flies on D
    [[X]], [[Y]] (both begin 26 October 2026)   applies to X and Y

A month or a year alone is read at its conservative end: "begins June 2027"
as 30 June, "ends 2027" as 1 January. A date that does not parse leaves the
link out.

Two articles. A pair is usually listed twice, once in each airport's article,
and the two can disagree about the same airline (Aberdeen: easyJet to Paris
year-round; Charles de Gaulle: the same flights seasonal). An airline's
service on a pair is year-round only if every listing of it, in either
article, says so, and the pair is kept if any airline's is (_year_round_pairs).

The article cache keeps the PARSE (every listing with its class and date),
not the decision, so a build on another day judges the dates again without
refetching anything; the day is in the route network's key instead.
"""

import collections
import hashlib
import itertools
import json
import os
import re
import time
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

import httpx
import polars as pl

from transport_maps import config
from transport_maps.sources import _fetch, airports, wikidata
from transport_maps.sources._utils import (
    IncompleteResponse,
    _atomic_write,
    _params_hash,
    _refuse_partial,
    _retry_after_seconds,
    _stale,
    _validated_json,
)

ACTION_API = "https://en.wikipedia.org/w/api.php"
TITLES_PER_REQUEST = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build; https://worldmap.atik.kr/)"}
MAX_RETRIES = 6
# An article fetched longer ago than this is fetched again (G2: every build
# checks its inputs). The crawl is not one file with an ETag but ~4,000
# articles, fifty to a request, so "check" means "fetch again": about 80
# requests, which the owner accepted per build (2026-10-02). A day rather than
# zero so that a build restarted the same day -- after a crash, say -- reads
# the crawl the first attempt read instead of a slightly different one, which
# would change the graph and void `--skip-existing`. An article whose refetch
# fails keeps its cached parse, and stays stale, so the next build asks again.
ARTICLE_MAX_AGE = timedelta(hours=24)
# Pins the day begins/ends/resumes dates are judged against (YYYY-MM-DD), so
# an offline rebuild of a past build can judge them as that build did. Unset,
# it is the UTC day the process first asks (service_date).
SERVICE_DATE_ENV = "TRANSPORT_MAPS_SERVICE_DATE"

# Both heading patterns capture the leading "=" run so the section can be
# closed at the next heading of the same level or shallower (_section_end).
# The section is not always level 2: an article that files it under
# "== Operations ==" has it at level 3, and closing it only at the next
# level-2 heading read its sibling sections as destinations (CR13-2).
_SECTION_RE = re.compile(r"^(==+)\s*Airlines and destinations\s*==+\s*$", re.IGNORECASE | re.MULTILINE)
# Subsections that list no year-round scheduled passenger service. Cargo
# carries no passengers; the rest are charter, seasonal, past, military or
# ambulance flying, or a statistics table or destination map that repeats the
# list without its Seasonal/Charter labels.
_EXCLUDED_SUBSECTION_RE = re.compile(
    r"^(===+)\s*[^=\n]*?(?:Cargo|Freight|Charter|Seasonal|Histor|Former|Previous|Statistic"
    r"|Top\b|Busiest|\bMaps?\b|Military|Med[ie]vac|Ambulance)[^=\n]*=+\s*$",
    re.IGNORECASE | re.MULTILINE)
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
# Comments and references go before anything is read: a citation names
# airlines, publishers and, now and then, an airport, and none is a route.
_NOISE_RE = re.compile(r"<!--.*?-->|<ref\b[^>]*/>|<ref\b[^>]*>.*?</ref\s*>",
                       re.IGNORECASE | re.DOTALL)
# A label that opens a service class: '''Seasonal:''', ''' Seasonal:''',
# '''Seasonal''':, '''Charter:''', '''Seasonal charter:''', and the few written
# without the bold ("| Charter: [[X]]"). `_service_of` reads the class.
_LABEL_RE = re.compile(
    r"'{2,3}\s*([^'\n\[\]{}|<>]{1,40}?)\s*'{2,3}\s*(:?)"
    r"|\b(?:seasonal(?:\s+ch[ae]rters?)?|charters?)\s*:",
    re.IGNORECASE)
# A dated (or undated) change of service in parentheses after a link.
_CHANGE_RE = re.compile(
    r"\(\s*(both\s+|all\s+)?(?:temporarily\s+)?"
    r"(begins?|starts?|commences?|ends?|resumes?|suspended|terminated|cancell?ed)\b([^()]*)\)",
    re.IGNORECASE)
# The template that holds the table; any other template is inline, and a "|"
# inside it does not end a cell.
_LIST_TEMPLATE_RE = re.compile(r"^\s*airport[- ]?dest(?:ination)?[- ]?list\s*$", re.IGNORECASE)
# Templates whose links are not destinations: maps, whose pins mark seasonal
# and future service by colour alone, and footnotes.
_NOT_DESTINATIONS_TEMPLATE_RE = re.compile(
    r"^\s*(?:[^|]*map[^|]*|efn(?:-[a-z]+)?|refn|ref|note|sfn[a-z]*)\s*$", re.IGNORECASE)
# What ends a cell outside any inline template: "|" or "||" (which also
# covers "|-"). "||" is one token, not two around an empty cell, so the cell
# before the destinations is still the airline's when they come.
_CELL_END_RE = re.compile(r"\|\|?")
# A class written after the link instead of as a label: "[[X]] (Seasonal)".
_NOTE_RE = re.compile(r"\(\s*(seasonal(?:\s+charters?)?|charters?)\s*\)", re.IGNORECASE)
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_DATE_RE = re.compile(
    r"\b(?:(\d{1,2})\s+([a-z]{3,9})\.?,?\s+(\d{4})"     # 25 October 2026
    r"|([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})"           # October 25, 2026
    r"|([a-z]{3,9})\.?,?\s+(\d{4})"                       # October 2026
    r"|(\d{4}))\b",                                       # 2026
    re.IGNORECASE)
# parse_destinations' scanner: a link, a template opening (with its name) or
# closing, a wikitable opening or closing, a cell end, a label, a dated
# change, a class note. Earlier alternatives win where two match at one place.
_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{rx.pattern})" for name, rx in (
    ("link", _LINK_RE), ("open", re.compile(r"\{\{[^{}|]*")), ("close", re.compile(r"\}\}")),
    ("table", re.compile(r"\{\||\|\}")), ("end", _CELL_END_RE), ("label", _LABEL_RE),
    ("change", _CHANGE_RE), ("note", _NOTE_RE))),
    re.IGNORECASE | re.DOTALL)
# Routes so well-established that their absence means the crawl or the
# Wikidata resolution silently broke somewhere, not that the route doesn't
# exist. ICN<->NRT is one of the world's busiest routes; resolver bugs in
# this pipeline have twice produced a network that "built successfully"
# while missing it.
_SANITY_PAIRS: tuple[tuple[str, str], ...] = (("ICN", "NRT"),)


class Listing(NamedTuple):
    """One destination link as the section lists it.

    `service` is "scheduled", "seasonal", "charter", "seasonal charter" or
    "other" (any other label). `change` is None or "begins", "ends",
    "resumes" or "suspended", and `on` the ISO date it takes effect -- already
    the conservative end of a month or year (module docstring) -- or None
    when none was given or it did not parse. `airline` is the first link of
    the cell before the link's own -- the airline column of the row -- or ""
    when that cell has none."""

    title: str
    service: str = "scheduled"
    change: str | None = None
    on: str | None = None
    airline: str = ""


def service_date() -> date:
    """The day this build judges begins/ends/resumes dates against: the UTC
    day the process first asks, or SERVICE_DATE_ENV. Fixed per process, like
    every other input (sources/_fetch), so one build reads one network even if
    it runs past midnight."""
    global _service_date
    if _service_date is None:
        pinned = os.environ.get(SERVICE_DATE_ENV, "").strip()
        _service_date = date.fromisoformat(pinned) if pinned else datetime.now(UTC).date()
    return _service_date


_service_date: date | None = None


def _section_end(text: str, level: int, pos: int) -> int:
    """Offset of the first heading at `level` or shallower (a sibling or a
    parent) at or after `pos`, or the end of `text` if there is none."""
    boundary = re.compile(rf"^={{2,{level}}}[^=]", re.MULTILINE).search(text, pos)
    return boundary.start() if boundary is not None else len(text)


def _strip_excluded_subsections(body: str) -> str:
    """Remove Cargo, Charter, ... subsections without discarding what follows.

    Cutting everything from the first such heading to the end of the body
    would also throw away any later Passenger subsection. Excise only the
    span from the heading up to the next heading at the same level or
    shallower (a sibling or parent section), or to the end of the body if
    there is none.
    """
    while True:
        cut = _EXCLUDED_SUBSECTION_RE.search(body)
        if cut is None:
            return body
        end = _section_end(body, len(cut.group(1)), cut.end())
        body = body[: cut.start()] + body[end:]


def _service_of(label: str) -> str:
    text = label.lower()
    if "seasonal" in text:
        return "seasonal charter" if re.search(r"ch[ae]rter", text) else "seasonal"
    if "charter" in text:
        return "charter"
    if re.fullmatch(r"\W*(?:year[- ]round|scheduled)\W*", text):
        return "scheduled"
    return "other"


def _label_service(token: str) -> str | None:
    """The class a label token opens, or None for bold text that is no label
    (a bolded name, "'''Note'''"): one that neither ends in a colon nor says
    seasonal or charter."""
    m = _LABEL_RE.fullmatch(token)
    text = m.group(1) if m.group(1) is not None else token
    labelled = m.group(1) is None or text.endswith(":") or m.group(2)
    if not labelled and not re.search(r"seasonal|ch[ae]rter", text, re.IGNORECASE):
        return None
    return _service_of(text)


def _change_date(change: str, text: str) -> str | None:
    """ISO date of the first date in `text`, taken at the conservative end of
    a month or a year: the last day for a start, the first for an end."""
    m = _DATE_RE.search(text)
    if m is None:
        return None
    day, month, year = ((m.group(1), m.group(2), m.group(3)) if m.group(1) else
                        (m.group(5), m.group(4), m.group(6)) if m.group(4) else
                        (None, m.group(7), m.group(8)) if m.group(7) else
                        (None, None, m.group(9)))
    month_no = next((i + 1 for i, name in enumerate(_MONTHS)
                     if month and len(month) >= 3 and name.startswith(month.lower())), None)
    if month is not None and month_no is None:
        return None
    late = change != "ends"
    try:
        if day is not None:
            return date(int(year), month_no, int(day)).isoformat()
        if month_no is not None:
            first = date(int(year), month_no, 1)
            if not late:
                return first.isoformat()
            return (date(first.year + first.month // 12, first.month % 12 + 1, 1)
                    - timedelta(days=1)).isoformat()
        return date(int(year), 12, 31).isoformat() if late else date(int(year), 1, 1).isoformat()
    except ValueError:
        return None


def _parse_change(token: str) -> tuple[str, str | None, int]:
    """(change, date, how many preceding links it covers) of a change token."""
    m = _CHANGE_RE.fullmatch(token)
    word, rest = m.group(2).lower(), m.group(3)
    if word.startswith(("begin", "start", "commence")):
        change = "begins"
    elif word.startswith("end"):
        change = "ends"
    elif word.startswith("resume") or re.match(r"\s*until\b", rest, re.IGNORECASE):
        change = "resumes"     # "(suspended until <date>)" is a resumption
    else:
        change = "suspended"
    on = _change_date(change, rest) if change != "suspended" else None
    covers = 0 if m.group(1) and m.group(1).lower().startswith("all") else (
        2 if m.group(1) else 1)
    return change, on, covers


def parse_destinations(wikitext: str) -> list[Listing]:
    """Every destination link in the Airlines and destinations section, with
    its service class and any dated change (module docstring). Links are
    listed whatever their class; `_left_out` decides which become routes."""
    match = _SECTION_RE.search(wikitext)
    if match is None:
        return []

    body = wikitext[match.end(): _section_end(wikitext, len(match.group(1)), match.end())]
    body = _strip_excluded_subsections(_NOISE_RE.sub("", body))

    listings: list[Listing] = []
    stack: list[str] = []          # open templates: "list", "inline" or "skip"
    tables = 0                     # open wikitables
    service = "scheduled"
    cell: list[int] = []           # indices into `listings` of this cell's links
    airline = ""                   # first link of the cell before this one
    for tok in _TOKEN_RE.finditer(body):
        kind, text = tok.lastgroup, tok.group()
        in_cell_level = not stack or stack[-1] == "list"
        if kind == "open":
            name = text[2:]
            kind = ("list" if _LIST_TEMPLATE_RE.match(name) else
                    "skip" if _NOT_DESTINATIONS_TEMPLATE_RE.match(name) else "inline")
            stack.append(kind)
            if kind == "list":
                service, cell, airline = "scheduled", [], ""
        elif kind == "close":
            if stack and stack.pop() == "list":
                service, cell, airline = "scheduled", [], ""
        elif kind == "table":
            tables = max(0, tables + (1 if text == "{|" else -1))
            service, cell, airline = "scheduled", [], ""
        elif kind == "end":
            if in_cell_level:
                airline = listings[cell[0]].title if cell else ""
                service, cell = "scheduled", []
        elif kind == "label":
            opened = _label_service(text)
            if opened is not None:
                service = opened
        elif kind == "change":
            change, on, covers = _parse_change(text)
            for i in (cell if covers == 0 else cell[-covers:]):
                listings[i] = listings[i]._replace(change=change, on=on)
        elif kind == "note":
            if cell:
                listings[cell[-1]] = listings[cell[-1]]._replace(service=_service_of(text))
        elif "skip" not in stack and ("list" in stack or tables):
            title = _LINK_RE.fullmatch(text).group(1).strip().replace(" ", "_")
            if title and not title.startswith(_SKIP_PREFIXES):
                cell.append(len(listings))
                listings.append(Listing(title, service, airline=airline))

    return list(dict.fromkeys(listings))


def _left_out(listing: Listing, day: date) -> str | None:
    """Why `listing` is not year-round scheduled service on `day`, or None
    if it is."""
    if listing.service != "scheduled":
        return listing.service
    if listing.change is None:
        return None
    if listing.change == "suspended":
        return "suspended"
    if listing.on is None:
        return f"{listing.change} undated"
    on = date.fromisoformat(listing.on)
    if listing.change == "ends":
        return None if on > day else "ended"
    return None if on <= day else f"{listing.change} later"


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
# 3: each link carries its service class and dated change (Listing); maps,
#    footnotes, references and non-scheduled subsections are not read.
PARSER_VERSION = 3


def _parser_key() -> str:
    """Every constant that governs what `parse_destinations` returns.

    Patterns and flags both: dropping re.IGNORECASE from _SECTION_RE changes
    which headings match while `.pattern` stays byte-identical. _TOKEN_RE is
    hashed whole because it is built from the cell-end pattern and the
    template brackets as well as the regexes named here.
    """
    return _params_hash(PARSER_VERSION, _SKIP_PREFIXES, _MONTHS,
                        _SECTION_RE.pattern, _SECTION_RE.flags,
                        _EXCLUDED_SUBSECTION_RE.pattern, _EXCLUDED_SUBSECTION_RE.flags,
                        _LINK_RE.pattern, _LINK_RE.flags,
                        _NOISE_RE.pattern, _NOISE_RE.flags,
                        _LABEL_RE.pattern, _LABEL_RE.flags,
                        _CHANGE_RE.pattern, _CHANGE_RE.flags,
                        _NOTE_RE.pattern, _NOTE_RE.flags,
                        _LIST_TEMPLATE_RE.pattern, _LIST_TEMPLATE_RE.flags,
                        _NOT_DESTINATIONS_TEMPLATE_RE.pattern, _NOT_DESTINATIONS_TEMPLATE_RE.flags,
                        _DATE_RE.pattern, _DATE_RE.flags,
                        _TOKEN_RE.pattern, _TOKEN_RE.flags)


def _destination_cache_path():
    return config.CACHE / "airline_destinations.json"


def _load_raw_destination_cache() -> dict:
    path = _destination_cache_path()
    return json.loads(path.read_text()) if path.exists() else {}


def _load_destination_cache() -> dict[str, list[Listing] | None]:
    """Article title -> parsed listings, or None for an absent article.

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
    raw = _load_raw_destination_cache()
    if not raw:
        return {}
    stamp = raw.get("_parser_key")
    if stamp != _parser_key() or "articles" not in raw:
        print(f"routes: destination cache was parsed under key {stamp}, parser is "
              f"{_parser_key()}; re-crawling", flush=True)
        return {}
    return {t: None if rows is None else [Listing(*row) for row in rows]
            for t, rows in raw["articles"].items()}


def _load_fetched_at() -> dict[str, str]:
    """Article title -> when it was fetched (ISO, UTC). An article with no
    entry -- every article in a cache written before G2 -- counts as older
    than ARTICLE_MAX_AGE, so the first build after G2 refetches the lot."""
    raw = _load_raw_destination_cache()
    if raw.get("_parser_key") != _parser_key():
        return {}
    return raw.get("fetched_at", {})


def _save_destination_cache(cache: dict[str, list[Listing] | None],
                            fetched_at: dict[str, str] | None = None) -> None:
    path = _destination_cache_path()
    payload = {"_parser_key": _parser_key(), "articles": cache,
               "fetched_at": {t: at for t, at in (fetched_at or {}).items() if t in cache}}
    _atomic_write(path, lambda tmp: tmp.write_text(json.dumps(payload)))


def _crawl_destinations(
    titles_by_iata: dict[str, str],
) -> tuple[dict[str, list[Listing] | None], list[str]]:
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

    A cached article older than ARTICLE_MAX_AGE is fetched again (G2), and if
    that fails its cached parse is used with a warning rather than counted
    unresolved: the crawl is refreshed when Wikipedia answers and does not
    fail the build when it does not. Offline (`build-all --offline`) nothing is
    fetched at all.
    """
    config.ensure_dirs()
    cache = _load_destination_cache()
    fetched_at = _load_fetched_at()
    now = datetime.now(UTC)
    stamp = now.replace(microsecond=0).isoformat()
    wanted = list(dict.fromkeys(titles_by_iata.values()))
    stale = [] if _fetch.offline() else [
        t for t in wanted if t in cache and _stale(fetched_at.get(t), now, ARTICLE_MAX_AGE)]
    todo = [] if _fetch.offline() else [t for t in wanted if t not in cache] + stale
    if todo:
        pending = collections.deque(itertools.batched(todo, TITLES_PER_REQUEST))
        print(f"routes: {len(cache)} articles cached, {len(todo)} to fetch "
              f"({len(stale)} older than {ARTICLE_MAX_AGE}) in {len(pending)} batches")
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
                            fetched_at[title] = stamp
                        elif title in confirmed_absent:
                            # enwiki has no such article; nothing to fetch, ever.
                            cache[title] = None
                            fetched_at[title] = stamp
                    _save_destination_cache(cache, fetched_at)
                print(f"routes: batch {n} done ({len(cache)} articles cached, "
                      f"{len(pending)} batches left)")

    destinations = {iata: cache[t] for iata, t in titles_by_iata.items() if t in cache}
    unresolved = [iata for iata, t in titles_by_iata.items() if t not in cache]
    if unresolved:
        print(f"routes: {len(unresolved)} airports unresolved this run")
    kept = [t for t in stale if fetched_at.get(t) != stamp]
    if kept:
        print(f"routes: WARNING {len(kept)} articles could not be refetched; using their "
              "cached parse, and the next build will ask again", flush=True)
    times = sorted(fetched_at[t] for t in wanted if t in fetched_at)
    _fetch.record("wikipedia:airline-destinations", {
        "articles": len(wanted),
        "fetchedFrom": times[0] if times else None,
        "fetchedTo": times[-1] if times else None,
        # The day begins/ends/resumes dates were judged against: the same
        # crawl read on another day can make another network.
        "serviceDate": service_date().isoformat(),
    })
    return destinations, unresolved


def _crawl_digest(destinations: dict[str, list[Listing] | None],
                  resolved: dict[str, str]) -> str:
    """sha256 of what the crawl and the resolver answered: each airport's
    parsed listings, classes and dates included, and each destination
    title's IATA code."""
    payload = json.dumps({"destinations": destinations, "resolved": resolved},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _network_cache_path(iatas: list[str], titles_by_iata: dict[str, str], crawl: str,
                        day: date):
    """Stamped with everything that shapes the pair set: the parser and the
    resolver, the sanity pairs, and the inputs -- the airports a pair may
    join, the article crawled for each, what those articles said (`crawl`,
    `_crawl_digest`), and the day their begins/ends/resumes dates are judged
    against (`day`, service_date): one crawl makes a different network the
    day a listed route begins or ends.

    The inputs are hashed whole. The airport table's stamped name, which this
    used to carry instead, records the rules the table was built under but not
    the OurAirports download it was built from, and says nothing about the
    article links. The bare routes.parquet before that was keyed on
    `.exists()` and is no longer read at all (CR13-3). The crawl's content
    joined the key with G2: once articles are refetched, the same airports and
    links can carry different destinations, and a key without them would read
    back the network the old articles made."""
    stamp = _params_hash(_parser_key(), wikidata.RESOLVER_VERSION, _SANITY_PAIRS,
                         sorted(iatas), sorted(titles_by_iata.items()), crawl,
                         day.isoformat())
    return config.BUILD / f"routes_{stamp}.parquet"


def route_network() -> pl.DataFrame:
    """Directed airport pairs with year-round scheduled service on the build's
    service date (module docstring). Cached to parquet.

    The airport table, the article links and the crawl itself are settled
    before the cache is consulted because all three are part of its key. With
    the article cache fresh (ARTICLE_MAX_AGE) and the resolver's too, that
    costs no request.
    """
    apts = airports.scheduled_airports()
    valid = set(apts["iata"].to_list())
    titles_by_iata = _wikipedia_titles(apts)

    destinations, unresolved = _crawl_destinations(titles_by_iata)
    _refuse_partial(
        "destination crawl", unresolved,
        "re-run to refetch exactly these; the per-airport cache keeps the rest",
    )

    # Resolve every distinct destination title once, in bulk, rather than per
    # airport: wikidata.iata_for_titles() already caches by title, so this
    # keeps the crawl from re-querying the same handful of hub airports
    # (Narita, Los Angeles, ...) thousands of times over.
    all_titles = sorted({x.title for listings in destinations.values() if listings
                         for x in listings})
    resolved = wikidata.iata_for_titles(all_titles)

    day = service_date()
    out = _network_cache_path(sorted(valid), titles_by_iata,
                              _crawl_digest(destinations, resolved), day)
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

    pairs, left_out, disputed = _year_round_pairs(destinations, resolved, valid, day)
    print(f"routes: {len(pairs)} directed pairs of year-round scheduled service on {day}; "
          "listings left out: "
          + (", ".join(f"{n} {why}" for why, n in left_out.most_common()) or "none")
          + f"; {disputed} pairs left out because the other end's article says otherwise "
          "for the same airline", flush=True)

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


def _year_round_pairs(destinations: dict[str, list[Listing] | None],
                      resolved: dict[str, str], valid: set[str], day: date,
                      ) -> tuple[set[tuple[str, str]], collections.Counter[str], int]:
    """Directed pairs with year-round scheduled service on `day`, the count of
    listings left out by reason (`_left_out`), and how many pairs some listing
    called year-round but the other end's article contradicted.

    A pair is usually listed twice, once in each airport's article, and the
    two can disagree: Aberdeen lists easyJet's Paris flights as year-round
    while Charles de Gaulle lists the same flights as seasonal. An airline's
    service on a pair counts as year-round only if EVERY listing of it, in
    either article, says so; the pair is kept if any airline's does. A pair
    one article omits is decided by the other alone. Service is bidirectional,
    so a kept pair is kept both ways.
    """
    by_pair: dict[tuple[str, str], dict[str, bool]] = {}
    listed_year_round: set[tuple[str, str]] = set()
    left_out: collections.Counter[str] = collections.Counter()
    for iata, listings in destinations.items():
        for listing in listings or ():
            dest_iata = resolved.get(listing.title)
            if not (dest_iata and dest_iata in valid and dest_iata != iata):
                continue
            pair = (min(iata, dest_iata), max(iata, dest_iata))
            reason = _left_out(listing, day)
            if reason is None:
                listed_year_round.add(pair)
            else:
                left_out[reason] += 1
            # Case-folded: one article links [[EasyJet]], the other [[easyJet]].
            airline = listing.airline.casefold()
            by_airline = by_pair.setdefault(pair, {})
            by_airline[airline] = by_airline.get(airline, True) and reason is None
    kept = {pair for pair, by_airline in by_pair.items() if any(by_airline.values())}
    return kept | {(b, a) for a, b in kept}, left_out, len(listed_year_round - kept)


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
