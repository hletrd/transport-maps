"""Rail routes from OpenStreetMap `type=route, route=train` relations.

A route relation carries an ORDERED list of stop members, which is the station
sequence directly. The tempting alternative -- walking the member ways' geometry
and inferring which station comes next -- is wrong on every branching line,
every reversal, and every route whose ways are not contiguous in the relation.
Member order is authoritative; geometry is not consulted at all.

Two passes are required and cannot be merged: relations name their stops by node
id, and a PBF stores nodes before relations, so the ids to look up are not known
until after the node block has already streamed past.
"""

from __future__ import annotations

import pathlib
import re

import osmium
import polars as pl

from .. import config
from ._utils import _atomic_write, _params_hash

# Members carrying the passenger stop sequence. A route may use the modern
# `stop*` roles or only the older `platform*` ones; preferring stops and falling
# back keeps both shapes usable instead of silently yielding an empty sequence.
STOP_ROLES = ("stop", "stop_entry_only", "stop_exit_only")
PLATFORM_ROLES = ("platform", "platform_entry_only", "platform_exit_only")
# Below this a "route" is a fragment or a tagging error, not a service.
MIN_STOPS = 2

SCHEMA = {
    "route_id": pl.Int64, "seq": pl.Int64, "stop_id": pl.Int64,
    "lat": pl.Float64, "lon": pl.Float64, "name": pl.Utf8,
    # Which speed tier the route is priced at, from its `service` tag. This
    # REPLACED a `highspeed` boolean, which was the only thing distinguishing
    # one train from another and which 1% of route relations on Earth carry --
    # 0% outside Europe. See `service_tier` below and `[rail.tiers]` in
    # calibration.toml.
    "tier": pl.Utf8,
    # The relation's own name -- "KTX 경부선", "ICE 12" -- so the page can say
    # which line a journey rode, not just that it rode one.
    "route_name": pl.Utf8,
    # Who runs it and what it is called. Measured coverage over all 19,297
    # `type=route, route=train` relations in the seven extracts: `operator`
    # 92%, `ref` 88%. `operator` is the only field whose coverage survives
    # leaving Europe (Africa 80%, everywhere else 90-95%), which is why it is
    # here and `service` alone is not enough to caption a leg.
    "operator": pl.Utf8,
    "ref": pl.Utf8,
}

# ---- the service tiers ------------------------------------------------------
#
# Slowest first. The order IS the tie-break for a `;`-joined value, so it must
# stay sorted by speed; `[rail.tiers]` in calibration.toml carries the fitted
# figures and the residuals.
#
# Measured over all 19,297 train route relations, not guessed: `regional` 41.1%,
# absent 26.7%, `commuter` 14.7%, `long_distance` 11.2%, `high_speed` 1.8%,
# `national` 1.2%, `tourism` 1.1%, `international` 0.5%, `night` 0.5%. Note what
# is NOT there: `suburban` has FIVE relations worldwide and `car_shuttle` five,
# so neither earns a tier -- `commuter`, which an earlier guess did not include
# at all, has 2,829.
RAIL_TIERS = ("tourism", "commuter", "default", "regional",
              "long_distance", "high_speed")
DEFAULT_TIER = "default"

# Raw `service` value -> tier. Synonyms are folded on meaning and then checked
# against whatever observations exist, never the other way round:
#   national (n=44) and international (n=16) price best as long_distance
#     (median predicted/observed 1.17 and 0.96, against 1.28 and 1.05 as
#     regional); neither has enough observations to identify its own overhead.
#   suburban (n=4) prices best as commuter (1.02).
#   local, urban, stopping, ordinary and light_rail are stopping-service
#     synonyms with no observations of their own; commuter is their meaning.
# Everything absent or unrecognised -- `night`, `express`, `car_shuttle`,
# `industrial`, `rapid`, `branch` -- falls to `default`, which is itself FITTED
# (n=717) on relations carrying a duration but no `service`. `night` (n=8)
# prices best there too (0.96, against 0.77 as long_distance).
_TIER_BY_SERVICE = {
    "high_speed": "high_speed", "highspeed": "high_speed",
    "long_distance": "long_distance", "national": "long_distance",
    "international": "long_distance",
    "regional": "regional",
    "commuter": "commuter", "suburban": "commuter", "local": "commuter",
    "urban": "commuter", "stopping": "commuter", "ordinary": "commuter",
    "light_rail": "commuter",
    "tourism": "tourism", "tourist": "tourism", "touristic": "tourism",
}


def service_tier(tags) -> str:
    """The speed tier a route relation is priced at.

    `highspeed=yes` promotes to the top tier whatever `service` says. It is a
    positive assertion about the track, it can only promote (nothing is faster
    than `high_speed`), and the two relations carrying it in the fit set imply
    153 km/h against their tier's 81.8 -- so honouring it is what the data says.

    A `;`-joined value ("international;long_distance", "tourism;night;regional")
    resolves to the SLOWEST tier among the tokens it recognises. About 60
    relations worldwide are multi-valued, and the choice is safe rather than
    arbitrary: `graph/rail.ride_edges` already resolves parallel services on a
    shared segment by `min(minutes)`, so a genuinely faster service running the
    same track still wins the edge.
    """
    if tags.get("highspeed") == "yes":
        return "high_speed"
    raw = (tags.get("service") or "").strip().lower()
    if not raw:
        return DEFAULT_TIER
    found = [_TIER_BY_SERVICE[part] for token in raw.split(";")
             if (part := token.strip()) in _TIER_BY_SERVICE]
    if not found:
        return DEFAULT_TIER
    return min(found, key=RAIL_TIERS.index)


def _relations(path) -> tuple[dict, set[int]]:
    """Ordered stop-node ids per train route, plus every id to resolve."""
    routes, wanted = {}, set()
    for obj in osmium.FileProcessor(str(path), osmium.osm.RELATION):
        t = obj.tags
        if t.get("type") != "route" or t.get("route") != "train":
            continue
        for roles in (STOP_ROLES, PLATFORM_ROLES):
            ids = [m.ref for m in obj.members
                   if m.type == "n" and m.role in roles]
            if len(ids) >= MIN_STOPS:
                routes[obj.id] = {"stops": ids,
                                  "name": t.get("name") or "",
                                  "tier": service_tier(t),
                                  "operator": (t.get("operator") or "").strip(),
                                  "ref": (t.get("ref") or "").strip()}
                wanted.update(ids)
                break
    return routes, wanted


def _nodes(path, wanted: set[int]) -> dict:
    """Coordinates and names for the stop ids a relation pass asked for."""
    found = {}
    if not wanted:
        return found
    for obj in osmium.FileProcessor(str(path), osmium.osm.NODE):
        if obj.id in wanted:
            found[obj.id] = (obj.location.lat, obj.location.lon,
                             obj.tags.get("name") or "")
    return found


def _parse(path) -> list[dict]:
    routes, wanted = _relations(path)
    coords = _nodes(path, wanted)
    rows = []
    for route_id, r in routes.items():
        # A stop whose node the extract does not contain (a route crossing the
        # region boundary) is dropped, not guessed at. Renumber so `seq` stays
        # gapless and a consumer can trust consecutive pairs are adjacent stops.
        resolved = [(sid, coords[sid]) for sid in r["stops"] if sid in coords]
        if len(resolved) < MIN_STOPS:
            continue
        for seq, (sid, (lat, lon, node_name)) in enumerate(resolved):
            # A stop node with no `name` gets an EMPTY name, not the route's.
            # It used to inherit `r["name"]`, and `emit/rail_detail` then
            # published that as the station: 1,144 of 124,488 shipped rows read
            # `via S1: Rostock Hbf -> Warnemünde (S1: Rostock Hbf ->
            # Warnemünde)`, the line's own name standing in for the place. An
            # empty string is what the page degrades on; a wrong name is not.
            rows.append({"route_id": route_id, "seq": seq, "stop_id": sid,
                         "lat": lat, "lon": lon,
                         "name": node_name,
                         "tier": r["tier"],
                         "route_name": r["name"],
                         "operator": r["operator"], "ref": r["ref"]})
    return rows


FERRY_SCHEMA = {
    "way_id": pl.Int64, "from_lat": pl.Float64, "from_lon": pl.Float64,
    "to_lat": pl.Float64, "to_lon": pl.Float64, "name": pl.Utf8,
    # The three fields the wait model needs. Nullable: most ways carry none of
    # them, and a null is "OSM did not say", which the graph answers with its
    # fitted prior. A zero or a guessed default here would be indistinguishable
    # from a real measurement.
    "duration_min": pl.Float64, "interval_min": pl.Float64,
    "service_fraction": pl.Float64,
}
# A node sitting exactly on the antimeridian is where the extract cut the way,
# not where the ferry calls. Measuring to it invented two 4,800 km crossings
# out of one Pacific route. Real terminals do not land on the line to six
# decimal places.
ANTIMERIDIAN_EPS_DEG = 1e-6


# ---- the schedule tags -------------------------------------------------------
#
# Measured over all 30,629 `route=ferry` ways in the extracts, so the accepted
# set is the observed set rather than a guess at what OSM contains:
#
#   duration (n=4,598)  HH:MM 3,583 - H:MM 631 - bare minutes 226 -
#                       H:MM:SS 102 - ISO-8601 PT... 40 - HHH:MM 3 -
#                       "N min" 2 - comma decimal 2 - malformed 9
#   interval (n=552)    HH:MM 272 - bare minutes 185 - H:MM:SS 30 -
#                       free text 27 - H:MM 15 - day/count phrases 10 -
#                       HHH:MM 8 - other 5
#
# The five accepted forms cover 99.7% of `duration` and 92.4% of `interval`.
# Everything else is REJECTED and counted, not guessed at: "1:00, 0:30 (Peak),
# On request", "three_times_a_day", "at_least:180" and
# "IV - V: 3x/semaine;VI-IX: daily" all carry real information that no
# single number represents, and inventing one would be worse than admitting
# there is none.
_HMS = re.compile(r"^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$")
_BARE_MIN = re.compile(r"^\d{1,5}$")
_ISO8601 = re.compile(r"^P(?:(\d+(?:\.\d+)?)D)?"
                      r"(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?"
                      r"(?:(\d+(?:\.\d+)?)S)?)?$")


def parse_minutes(raw: str | None) -> float | None:
    """An OSM `duration`/`interval` value in minutes, or None if unparseable.

    Three-digit hours are accepted here on purpose. `144:00` is the real
    six-day Cape Town-Tristan da Cunha sailing; the same string on a 50 km hop
    is a weekly interval in the wrong field. This function cannot tell them
    apart and does not try -- `graph/ferry.trusted_duration_min` rejects by
    implied speed, which can. Rejecting every HHH:MM here would throw the one
    genuine case away with the mis-tagged ones.
    """
    if raw is None:
        return None
    t = raw.strip()
    if not t:
        return None
    if (m := _HMS.match(t)):
        h, mi, sec = m.group(1), m.group(2), m.group(3) or "0"
        return int(h) * 60.0 + int(mi) + int(sec) / 60.0
    if _BARE_MIN.match(t):
        return float(t)
    if t.startswith("P") and (m := _ISO8601.match(t)):
        d, h, mi, sec = (float(g) if g else 0.0 for g in m.groups())
        if d == h == mi == sec == 0.0:
            return None                    # bare "P"/"PT" says nothing
        return d * 1440.0 + h * 60.0 + mi + sec / 60.0
    return None


# An astronomical season. A `seasonal` value that NAMES its seasons is taken at
# three months each; `spring;summer;autumn` is therefore nine months.
SEASON_MONTHS = 3
# A bare `seasonal=yes` names no season, so the length has to come from
# somewhere else: about five months is the typical operating window of a
# seasonal ferry (the Norrona's summer timetable, most Scottish, Scandinavian
# and Great Lakes services). A published-figure default, not fitted -- there is
# nothing in OSM to fit it against.
UNSPECIFIED_SEASON_MONTHS = 5
_SEASON_NAMES = frozenset((
    "spring", "summer", "autumn", "fall", "winter", "dry_season", "wet_season",
))
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_RANGE = re.compile(r"\b([a-z]{3})[a-z]*\s*[-\u2013]\s*([a-z]{3})[a-z]*\b")


def _months_named(value: str) -> int | None:
    """Months in an explicit range like "April-October", or None."""
    m = _MONTH_RANGE.search(value)
    if not m:
        return None
    try:
        a, b = _MONTHS.index(m.group(1)), _MONTHS.index(m.group(2))
    except ValueError:
        return None
    return (b - a) % 12 + 1


def service_fraction(tags) -> float:
    """Share of the YEAR the service runs, from `seasonal` and `opening_hours`.

    The map carries no date, so "leave now" can only be answered as a year
    average: a summer-only ferry met in February is genuinely not there, and
    scaling the frequency is what that means arithmetically.

    What this does NOT model, and must not be read as modelling: restriction
    within the day or the week. 879 of the 1,325 ways carrying `opening_hours`
    are day-conditional, and evaluating an opening-hours expression properly is
    a parser this repository does not have. `24/7` is honoured because it is
    the one value that says service IS continuous; everything else
    sub-seasonal returns 1.0 and the shortfall is recorded rather than guessed.

    Both tags are also essentially absent where the error matters most: their
    coverage is ZERO above 400 km, so this touches short crossings only.
    """
    hours = (tags.get("opening_hours") or "").strip()
    raw = (tags.get("seasonal") or "").strip().lower()
    if hours == "24/7":
        return 1.0
    for value in (raw, hours.lower()):
        if (n := _months_named(value)) is not None:
            return n / 12.0
    if not raw or raw == "no":
        return 1.0
    named = [part for part in re.split(r"[;,]", raw) if part.strip() in _SEASON_NAMES]
    if named:
        return min(12, SEASON_MONTHS * len(named)) / 12.0
    if raw in ("yes", "1", "true"):
        return UNSPECIFIED_SEASON_MONTHS / 12.0
    # A `seasonal` value in none of those shapes ("April-October" already
    # handled, "limited", a free-text note). Unparseable, so unchanged.
    return 1.0


def _ferries(path, rejected: dict[str, int] | None = None) -> list[dict]:
    """Ferry ways reduced to their two endpoints, plus their schedule tags.

    A ferry way's intermediate nodes trace the sea crossing and carry no
    information the graph can use: what matters is which two places it joins.
    The TAGS are a different matter -- `duration` and `interval` are the two
    numbers the wait model would otherwise have to invent, and this parse used
    to read `name` and discard every one of them.

    Pass a dict as `rejected` to have the unparseable tag counts accumulated
    into it: a rejection is a real loss and the loader prints it rather than
    letting it look like an absent tag.
    """
    ways, wanted = {}, set()
    for obj in osmium.FileProcessor(str(path), osmium.osm.WAY):
        t = obj.tags
        if t.get("route") != "ferry":
            continue
        refs = [n.ref for n in obj.nodes]
        if len(refs) < 2 or refs[0] == refs[-1]:
            continue
        sched = {}
        for field, tag in (("duration_min", "duration"), ("interval_min", "interval")):
            raw = t.get(tag)
            sched[field] = parse_minutes(raw)
            if raw is not None and sched[field] is None and rejected is not None:
                rejected[tag] = rejected.get(tag, 0) + 1
        sched["service_fraction"] = service_fraction(t)
        ways[obj.id] = (refs[0], refs[-1], t.get("name") or "", sched)
        wanted.update((refs[0], refs[-1]))

    coords = {}
    if wanted:
        for obj in osmium.FileProcessor(str(path), osmium.osm.NODE):
            if obj.id in wanted:
                coords[obj.id] = (obj.location.lat, obj.location.lon)

    rows = []
    for way_id, (a, b, name, sched) in ways.items():
        if a in coords and b in coords:
            if any(abs(abs(coords[n][1]) - 180.0) < ANTIMERIDIAN_EPS_DEG for n in (a, b)):
                continue
            rows.append({"way_id": way_id,
                         "from_lat": coords[a][0], "from_lon": coords[a][1],
                         "to_lat": coords[b][0], "to_lon": coords[b][1],
                         "name": name, **sched})
    return rows


# Bumped when the ferry parse changes shape, so a parquet written by the old
# code is a MISS and not a silently reused wrong answer. `rail_routes` has had
# this guard since a logic fix that touched no constant needed one; the ferry
# side did not, which made adding the schedule tags a silent cache HIT -- the
# 30,629-row parquet would have been reused, the new columns would have been
# absent or null, every crossing would have fallen back to the prior, and every
# test would have stayed green.
# 1: duration, interval and service_fraction parsed off the way's tags.
FERRY_PARSER_VERSION = 1


def _ferry_cache_path(fingerprint) -> pathlib.Path:
    """Everything that governs the parquet's CONTENT, and nothing that does not.

    `MIN_FERRY_KM`/`MAX_FERRY_KM` used to be hashed here on the stated grounds
    that "the graph filters by length, so both constants govern the parquet's
    content". They never did: nothing in this module filters by length, the
    bound is applied in `graph/ferry.plausible_crossing` at graph-build time,
    and the two constants now live there. Hashing them meant a change to a
    graph-layer bound needlessly re-parsed 4.2 GB of PBF.
    """
    key = _params_hash(fingerprint, ANTIMERIDIAN_EPS_DEG, sorted(FERRY_SCHEMA),
                       SEASON_MONTHS, UNSPECIFIED_SEASON_MONTHS,
                       FERRY_PARSER_VERSION)
    return config.CACHE / f"ferry_links-{key}.parquet"


# Bumped when the parse or the cross-extract merge changes shape, so a cache
# built by the old code is a MISS and not a silently reused wrong answer.
# 2: the cross-extract merge below stopped interleaving two extracts' stop
# sequences into one route.
# 3: `service` replaced the `highspeed` boolean as the speed selector, and
#    `operator`/`ref` joined the schema. Without this bump the 257,007-row
#    parquet is a cache HIT, the new columns are absent, every train reverts to
#    one of two speeds, and every test stays green.
RAIL_PARSER_VERSION = 3


def _rail_cache_path(fingerprint) -> pathlib.Path:
    # `sorted(SCHEMA)` yields the KEYS only, so changing a column's dtype --
    # `tier` from Boolean to Utf8, say -- left the key unchanged and the stale
    # parquet was read back under the new schema. The items are what govern the
    # content; `_params_hash` cannot digest a dtype object, so they are
    # stringified.
    schema = sorted((k, str(v)) for k, v in SCHEMA.items())
    return config.CACHE / (
        "rail_routes-"
        + _params_hash(fingerprint, STOP_ROLES, PLATFORM_ROLES, MIN_STOPS, schema,
                       RAIL_TIERS, DEFAULT_TIER,
                       sorted(_TIER_BY_SERVICE.items()), RAIL_PARSER_VERSION)
        + ".parquet")


def _fingerprint(extracts_dir, paths, *, by_mtime: bool = False) -> list[tuple]:
    """What the rail and ferry caches key each extract on: its directory and
    name, its size, and the replication snapshot in its header (G2) -- or its
    mtime, for an extract whose header carries none, and for `by_mtime`, the
    pre-G2 key, which `geofabrik.adopt` uses to rename a cache built from
    the very same file rather than parse it again."""
    from transport_maps.sources import geofabrik

    out = []
    for p in paths:
        st = p.stat()
        snap = None if by_mtime else geofabrik.snapshot(p)
        out.append((str(extracts_dir), p.name, st.st_size,
                    snap.isoformat() if snap else st.st_mtime_ns))
    return out


def ferry_links(*, extracts_dir=None) -> pl.DataFrame:
    """Every ferry crossing's two endpoints and schedule tags, across all extracts."""
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    paths = sorted(extracts_dir.glob("*-rail.osm.pbf"))
    if not paths:
        raise FileNotFoundError(
            f"no *-rail.osm.pbf in {extracts_dir}; run scripts/osm_rail.sh first"
        )
    from transport_maps.sources import geofabrik

    cached = _ferry_cache_path(_fingerprint(extracts_dir, paths))
    geofabrik.adopt(cached, _ferry_cache_path(_fingerprint(extracts_dir, paths, by_mtime=True)))
    if cached.exists():
        return pl.read_parquet(cached)

    rows, rejected = [], {}
    for p in paths:
        rows.extend(_ferries(p, rejected))
    if rejected:
        print("  ferry schedule tags rejected as unparseable: "
              + ", ".join(f"{k}={v:,}" for k, v in sorted(rejected.items())), flush=True)
    # A crossing mapped in two regional extracts appears twice under one id.
    df = pl.DataFrame(rows, schema=FERRY_SCHEMA).unique(subset=["way_id"], keep="first")
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df


def rail_routes(*, extracts_dir=None) -> pl.DataFrame:
    """Every train route's ordered stops, across all filtered regional extracts."""
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    paths = sorted(extracts_dir.glob("*-rail.osm.pbf"))
    if not paths:
        raise FileNotFoundError(
            f"no *-rail.osm.pbf in {extracts_dir}; run scripts/osm_rail.sh first"
        )

    # The key must cover the INPUT BYTES, not just the filenames. Keying on
    # names alone means a re-downloaded extract -- same name, new contents --
    # silently reuses the stale parquet, and two callers pointing at different
    # directories that happen to hold "europe-rail.osm.pbf" read each other's
    # results. Size and mtime were what changed when a file was replaced; the
    # replication snapshot in the header is what the file IS (G2), and does
    # not change when it is merely copied.
    from transport_maps.sources import geofabrik

    cached = _rail_cache_path(_fingerprint(extracts_dir, paths))
    geofabrik.adopt(cached, _rail_cache_path(_fingerprint(extracts_dir, paths, by_mtime=True)))
    if cached.exists():
        return pl.read_parquet(cached)

    rows = []
    for p in paths:
        before = len(rows)
        # Which extract a row came from is what the merge below needs, and it
        # was not recorded: without it the counts are per route_id over BOTH
        # extracts and carry no information about either.
        for row in _parse(p):
            rows.append({**row, "_extract": p.name})
        print(f"  {p.name}: {len(rows) - before:,} stop rows", flush=True)

    df = pl.DataFrame(rows, schema={**SCHEMA, "_extract": pl.Utf8})
    if df.is_empty():
        raise RuntimeError(
            "parsed every extract and found no train routes at all; the filter "
            "step most likely dropped the route relations"
        )
    df = _pick_one_extract_per_route(df)
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df


def _pick_one_extract_per_route(df: pl.DataFrame) -> pl.DataFrame:
    """One route id, one extract's stop sequence -- whole, never spliced.

    A cross-border service appears in two regional extracts, each holding only
    the stops inside its own region, and `_parse` renumbers `seq` from 0 per
    extract. The previous merge counted rows per `route_id` over the
    CONCATENATION of both, so `_n` was one constant per route, the
    `sort("_n", descending=True)` that was meant to make "the longer one wins"
    happen was a no-op, and `unique(["route_id","seq"])` then kept whichever
    row of each seq came first -- an interleaving of the two truncated
    sequences.

    Measured on the shipped cache before this fix: 1,823 duplicated
    (route_id, stop_id) pairs across 469 routes, 891 routes with a
    >200 km "consecutive" hop and a maximum of 6,351 km. Route 8382151 read
    Vladivostok -> Nizhny Novgorod -> Ozernaya Pad -> Moscow -> Muchnaya, and
    `rail.ride_edges` books every one of those fabricated hops at line speed.

    The extract with the most stops for a route wins, ties broken by extract
    name so the result does not depend on directory iteration order.
    """
    counts = (df.group_by(["route_id", "_extract"]).len().rename({"len": "_n"})
                .sort(["route_id", "_n", "_extract"], descending=[False, True, False])
                .unique(subset=["route_id"], keep="first")
                .select("route_id", "_extract"))
    return (df.join(counts, on=["route_id", "_extract"], how="inner")
              .drop("_extract")
              .sort("route_id", "seq"))
