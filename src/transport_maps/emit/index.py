"""index.json plus the shared hover-cell ordering."""

import hashlib
import json
import logging
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import h3
import numpy as np

from transport_maps import _io, config
from transport_maps.emit import hover, modes
from transport_maps.sources import _fetch

# Origin slugs become filenames under dist/origins and path segments in the
# page's fetch URLs, so reject anything that could escape the directory or
# start with a dot or dash: letters, digits, '_' and '-' only, and a
# letter or digit first. One grammar, checked where the slugs are read.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

#: The version of the pipeline-to-page contract this emitter writes, published
#: as `contractVersion` (docs/contract.md, "Versioning"). An index.json without
#: the field predates it and reads as 1. Raise it when an existing field or
#: file changes meaning, width or order -- not for a new optional field the
#: page can ignore. The page is to WARN on a version it does not know, never
#: to stop: every field has a fallback, and the deploy gates are what refuse
#: an inconsistent dist/.
CONTRACT_VERSION = 2

# Redistribution obligations of the open datasets this artifact is derived from.
# The licence firewall (tests/test_licence_firewall.py) only proves that NO
# commercial flight records leaked into dist/; it says nothing about crediting
# the sources that legitimately did. Shipping the map without this block leaves
# the CC-BY-SA and ODbL obligations unmet while every gate reports green.
#
# OSM enters three ways: rail route relations and ferry ways parsed from
# Geofabrik extracts (sources/osm.py), the coastline layer (emit/water.py), and
# GRIP4, which is compiled partly from OSM.
ATTRIBUTION: tuple[dict[str, str], ...] = (
    {
        "name": "Wikipedia",
        "licence": "CC BY-SA 4.0",
        "url": "https://en.wikipedia.org/",
        "usedFor": "airline route network, from 'Airlines and destinations' sections",
    },
    {
        "name": "Wikidata",
        "licence": "CC0 1.0",
        "url": "https://www.wikidata.org/",
        "usedFor": "resolving destination articles to IATA codes (property P238)",
    },
    {
        "name": "OurAirports",
        "licence": "Public Domain",
        "url": "https://ourairports.com/data/",
        "usedFor": "airport locations, sizes and scheduled-service status",
    },
    {
        "name": "Natural Earth",
        "licence": "Public Domain",
        "url": "https://www.naturalearthdata.com/",
        "usedFor": "1:10m land polygons defining the H3 cell universe; the de facto lines LSIB does not draw (Crimea, Northern Cyprus, Somaliland, Western Sahara, Siachen); populated places behind the urban mask",
    },
    {
        "name": "LSIB (U.S. Department of State)",
        "licence": "Public Domain",
        "url": "https://catalog.data.gov/dataset/large-scale-international-boundaries",
        "usedFor": "international boundaries and other lines of separation (Large Scale International Boundaries, v11.4)",
    },
    {
        "name": "GRIP4 (Global Roads Inventory Project)",
        "licence": "CC0 1.0",
        "url": "https://www.globio.info/download-grip-dataset",
        "usedFor": "road-density rasters setting per-cell ground speed",
    },
    {
        "name": "OpenStreetMap",
        "licence": "ODbL 1.0",
        "url": "https://www.openstreetmap.org/copyright",
        "usedFor": "coastlines (water polygons via osmdata.openstreetmap.de); rail route relations and ferry ways; upstream source of the GRIP4 road network",
    },
    {
        "name": "GeoNames",
        "licence": "CC BY 4.0",
        "url": "https://www.geonames.org/",
        # "(cities15000)" names the dataset, which is what a CC BY 4.0 credit
        # is for: GeoNames publishes several extracts under the same licence and
        # a reader cannot reproduce the input without knowing which. README.md
        # and web/llms.txt have always said it; this block, which README.md
        # calls the canonical one, dropped it.
        "usedFor": "departure cities and the place names under the cursor (cities15000)",
    },
    {
        "name": "HydroLAKES",
        "licence": "CC BY 4.0",
        "url": "https://www.hydrosheds.org/products/hydrolakes",
        "usedFor": "lake outlines drawn on the map (Messager et al. 2016)",
    },
    {
        "name": "adsb.lol",
        "licence": "ODbL 1.0",
        "url": "https://adsb.lol/",
        "usedFor": "observed flights behind the fitted cruise speed and "
                   "climb/descent penalty",
    },
)


def load_origins(path: Path | None = None) -> list[dict]:
    path = path or (config.DATA / "origins.toml")
    with open(path, "rb") as fh:
        origins = tomllib.load(fh).get("origin", [])
    if not origins:
        # A valid index.json with no origins is a page that throws on its
        # first line (cities[0]) -- the blank-globe class of failure.
        raise ValueError(f"{path} lists no origins")
    slugs = [str(o.get("slug", "")) for o in origins]
    bad = [s for s in slugs if not _SLUG_RE.fullmatch(s)]
    if bad:
        raise ValueError(f"invalid origin slug(s) in {path}: {bad[:5]} -- letters, digits, "
                         "'_' and '-' only, starting with a letter or digit")
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate origin slug in origins.toml")
    # Names are NOT required to be unique -- Hyderabad, Suzhou, Fuzhou and
    # Taizhou each appear twice in the 553-origin set -- but the page sorts the
    # picker by name, so each pair lands as two adjacent identical rows and the
    # slug that tells them apart is never shown. Warn rather than raise: the
    # data is legitimate and the page disambiguates client-side.
    from collections import Counter
    dupes = sorted(n for n, k in Counter(str(o.get("name", "")) for o in origins).items() if k > 1)
    if dupes:
        logging.getLogger(__name__).warning(
            "%d origin name(s) appear more than once and the picker sorts by name: %s. "
            "The page disambiguates from places.json; add `country = \"XX\"` in "
            "origins.toml (scripts/expand_origins.py writes it now) to name them at the source.",
            len(dupes), ", ".join(dupes[:8]))
    return origins


def write_hover_cells(idx, out: Path, parents: list[str] | None = None) -> None:
    """Sorted res-4 cell ids as little-endian uint64, matching the .bin ordering.

    The frontend computes h3.latLngToCell(lat, lon, 4), converts it to its integer
    form, and binary-searches this array to get the index into each origin's .bin.

    `parents` is `hover.hover_cells(idx)`: the build passes the one list it
    hands every per-origin writer, so this file and theirs share one ordering
    by construction rather than by recomputing it (R3, F7).
    """
    parents = parents if parents is not None else hover.hover_cells(idx)
    ids = np.array([h3.str_to_int(c) for c in parents], dtype="<u8")
    _io.write_bytes(out, ids.tobytes())


def write_reading_parents(idx, out: Path) -> None:
    """The res-3 block ordering for the reading tier, once for the whole site.

    Unlike hover_cells.bin this file is not per-resolution bookkeeping the page
    could derive: it IS derivable (the res-3 parents of hover_cells.bin are the
    same set, because parenthood is transitive), but shipping it means only
    ONE side computes the ordering. The page binary-searches it exactly as it
    already does hover_cells.bin, and the slot within a block is arithmetic, so
    no per-origin cell-id list exists anywhere.
    """
    hover.write_reading_parents(idx, out)


def carry_on_saving() -> dict[str, float]:
    """calibration.toml [carry_on], for the page. Read, never re-typed."""
    import tomllib

    with open(config.ROOT / "calibration.toml", "rb") as fh:
        raw = tomllib.load(fh)["carry_on"]
    return {"departureMin": float(raw["departure_saving_min"]),
            "arrivalMin": float(raw["arrival_saving_min"])}


def urban_slowdown(factor: float) -> str:
    """How the road prose says what the urban congestion factor does to speed.

    "halved" only when the factor is exactly 2. Any other value is stated as
    the number itself, so the sentence cannot claim a halving the model does
    not apply. The loader refuses a factor below 1.
    """
    if factor == 2.0:
        return "halved"
    return f"divided by {factor:g}"


def mode_detail() -> dict[str, str]:
    """One sentence per surface mode, with the calibrated speeds it uses.

    Every figure comes from the calibration objects the graph itself uses,
    so the tooltips cannot drift from the model (they hard-coded 200/75/35/30
    before, which were equal to calibration.toml only by luck).
    """
    from transport_maps.graph import ferry, ground, rail
    from transport_maps.sources import urban

    kmh = ground.SPEED_BY_ROAD_CLASS_KMH
    rc, fc = rail.load_rail_calibration(), ferry.load_ferry_calibration()
    # The tooltip quotes the range the tiers span rather than listing six, and
    # reads it off the calibration so it cannot drift. `tourism` is kept out
    # of the range deliberately -- at 20 km/h it is a heritage railway, not
    # the slow end of scheduled service -- and named on its own instead, as
    # the methods page and llms.txt do (DEF16-3): left out entirely, the
    # tooltip contradicted both about what the model prices.
    tier_lo = rc.tiers["commuter"]
    tier_hi = rc.tiers["high_speed"]
    tier_heritage = rc.tiers["tourism"]
    # The congestion factor divides the free-flow speed inside the urban mask
    # (graph/ground.cell_speed_kmh). This was the literal word "halved", which
    # was true only because calibration.toml [urban] congestion_factor happens
    # to be 2.0: refit it and every road tooltip would still say "halved"
    # (CR3-7). The word is now derived from the number.
    in_cities = (f"{urban_slowdown(urban.URBAN_CONGESTION_FACTOR)} inside cities "
              f"(within {urban.URBAN_RADIUS_KM:.0f} km of a city "
              f"over {urban.URBAN_POP_MIN:,.0f} people)")
    return {
        # Three corrections live in this one string. It named two speeds when
        # the model now prices six service tiers; it said "along the track"
        # when the model uses the straight-line chord between stops times a
        # detour factor, and `sources/osm.py` states outright that geometry is
        # never consulted; and it charged only `boarding_min`, so it said 15
        # minutes where the journey actually pays 20 (`boarding_min` on the way
        # in plus `alighting_min` on the way out).
        "rail": "Scheduled trains from OpenStreetMap route relations, stop to stop. "
                f"Six service tiers, read from each route's own OSM `service` tag "
                f"where it carries one (about a quarter of relations do not, and "
                f"fall to a general-purpose default), "
                f"{tier_lo.speed_kmh:.0f} km/h for a commuter train up to "
                f"{tier_hi.speed_kmh:.0f} km/h for a high-speed one, and "
                f"{tier_heritage.speed_kmh:.0f} km/h for heritage and tourist lines, "
                "over the straight-line "
                f"distance between stops times {rc.detour_factor:.1f} for curves, plus a "
                "per-stop allowance. "
                f"{rc.boarding_min + rc.alighting_min:.0f} min covers reaching the platform "
                "and leaving the arrival station.",
        # Every figure comes from the ferry calibration the graph itself uses,
        # and the sentence says where the wait comes from: this used to claim
        # only a speed and a terminal time, which was the whole model -- a
        # weekly Arctic sailing was charged the same half hour as a commuter
        # shuttle. NOT "fitted" alone and not "default" alone, and the split is
        # the one calibration.toml records: speed_kmh (29.1) and berth_min
        # (11.2) are FITTED to 3,203 OSM timetables, the headway prior is
        # FITTED to eight published crossings, and terminal_min (30) is the
        # published-figure default. A reader is owed both halves.
        #
        # This comment used to say the sailing speed was a published figure and
        # credit a "tortuosity" term. Both were wrong: calibration.toml:276-280
        # marks speed_kmh FITTED, and there is no tortuosity term -- a detour
        # factor was tried during cycle 8 and rejected in favour of the affine
        # berth_min. The string below has always been right; only the comment
        # explaining it was not.
        "ferry": "Scheduled ferry routes from OpenStreetMap. Sailing time from the route's "
                 "own timetable where OSM carries one, otherwise "
                 f"{fc.berth_min:.0f} min to leave and enter harbour plus "
                 f"{fc.speed_kmh:.0f} km/h, both fitted to 3,203 of those timetables. "
                 f"Plus {fc.terminal_min:.0f} min loading at the terminals, a "
                 "published-figure default, and the expected wait for the next sailing "
                 "-- from the timetabled interval where OSM gives one, otherwise from a "
                 "headway fitted to eight published crossings.",
        "highway": f"Motorways and expressways, fitted at {kmh[1]:.0f} km/h free-flow, {in_cities}.",
        # sorted(): the table is ordered by road class, not by speed, so
        # classes 2 and 3 (57 and 50 km/h) printed "fitted at 57-50 km/h" --
        # a backwards range, shipped in index.json and read out in the page's
        # route tooltip beside an ascending "18-25".
        "major road": f"Primary and secondary roads, fitted at "
                      f"{min(kmh[2], kmh[3]):.0f}-{max(kmh[2], kmh[3]):.0f} km/h, {in_cities}.",
        # NOT "fitted at 18-25": class 4 (tertiary) is fitted, class 5 (local)
        # keeps a published-figure default because the fit drew 116 km across
        # four journeys -- graph/ground.py says so in as many words, and
        # CLAUDE.md requires each constant to say which it is. This sentence
        # ships into index.json and is read out in the page's route tooltip.
        "minor road": f"Tertiary roads, fitted at {kmh[4]:.0f} km/h; local roads at "
                      f"{kmh[5]:.0f} km/h, a published-figure default. Both {in_cities}.",
        # Class 0 was the last speed in this table with no provenance on it.
        # graph/ground.py keeps it as a published-figure default because the
        # fit returned a negative time per kilometre for roadless terrain
        # (-0.00978 h/km), which the sign filter in calibrate/ground.py
        # refuses -- and an earlier unguarded fit returned 58 km/h for terrain
        # with no road at all.
        "track": f"No mapped road: {kmh[0]:.0f} km/h, walking pace, a published-figure "
                 "default (the fit for roadless terrain is degenerate).",
    }


def _git_head() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=config.ROOT, capture_output=True, text=True, check=True).stdout
        return head + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else "absent"


#: What computes the artifacts, hashed by CONTENT: the package itself and the
#: pinned dependencies it runs on. Relative to config.ROOT.
CODE_PATHS = ("src/transport_maps", "pyproject.toml", "uv.lock")


def _code_hash() -> str:
    """Digest of every file under CODE_PATHS as it stands in the working tree.

    inputsHash used to take the git head and a dirty flag, which named the
    commit rather than the code: a plan tick, a test or an uncommitted note in
    any tracked file moved it, though no artifact could change. That made it
    useless as the key a resumed build trusts (`build-all --skip-existing`,
    transport_maps.progress): commits land in this checkout daily, so a
    three-day build that died on day two could never resume under the same
    inputsHash. Hashing the content keeps every real code change in the key --
    an uncommitted edit to the solver included, which the dirty flag reduced to
    one bit -- and nothing else. The head is still recorded, as `gitHead`.
    """
    h = hashlib.sha256()
    for rel in CODE_PATHS:
        top = config.ROOT / rel
        files = ([top] if top.is_file() else
                 sorted(f for f in top.rglob("*") if f.is_file()
                        and "__pycache__" not in f.parts and not f.name.startswith(".")))
        if not files:
            h.update(f"{rel}\0absent\0".encode())
        for f in files:
            data = f.read_bytes()
            h.update(f"{f.relative_to(config.ROOT).as_posix()}\0{len(data)}\0".encode())
            h.update(data)
    return h.hexdigest()[:12]


def build_identity(started: datetime | None = None) -> dict[str, str]:
    """Which inputs and which run produced an artifact.

    `inputsHash` covers the code (`_code_hash`: the package and its pinned
    dependencies, by content), the two hand-edited inputs (calibration.toml,
    origins.toml) and the constants that shape the grid, the bands, the
    unreachable sentinel and the mode channels; `buildId` adds the start time so
    two runs of one input set (one of them aborted) stay distinguishable;
    `gitHead` names the commit, for provenance only.

    `inputs` is every raw input the build has read so far, by URL or name,
    with what identifies the copy it read -- sha256, size, ETag and
    Last-Modified for a download, the replication snapshot for an OSM
    extract, the fetch window for the Wikipedia crawl (sources/_fetch.used).
    `build-all` checks them all before calling this (cli._check_inputs), so
    it names the upstream snapshot the artifacts were built from (G2). It is
    deliberately NOT in `inputsHash`: that is the key a resumed build trusts,
    and the data inputs reach that key through the graph digest
    (progress.graph_hash) already.
    """
    started = started or datetime.now(UTC)
    # Everything below is sampled NOW, so this must be called when the build
    # STARTS. It used to be called as the last statement of _build_all_locked,
    # which recorded the checkout as it stood when the build stopped: for the
    # 553-origin run that meant a git head 38 commits ahead and hashes of a
    # calibration.toml and origins.toml rewritten 70 minutes after the graph
    # had already read them. `inputsHash` then named inputs the artifacts were
    # not built from -- the exact opposite of its purpose.
    inputs = _io.params_hash(
        _code_hash(), _sha256(config.ROOT / "calibration.toml"),
        _sha256(config.DATA / "origins.toml"),
        config.SOLVE_RES, config.FINE_RES, config.HOVER_RES, config.BAND_EDGES_MIN,
        # The reading tier's grid and block stride. Without these a res-5
        # reading build and a res-6 one share an inputsHash and a buildId, the
        # same defect config.UNREACHABLE was added below to close.
        config.READING_RES, config.READING_PARENT_RES, config.READING_SLOTS,
        # The sentinel every uint16 array is written with, and which index.json
        # advertises. Two builds differing only in it produced identical
        # inputsHash and identical buildId, so the field that exists to tell
        # artifacts apart could not tell those two apart.
        config.UNREACHABLE,
        modes.CHANNELS)
    return {"inputsHash": inputs,
            "buildId": f"{inputs}-{started:%Y%m%dT%H%M%SZ}",
            "builtAt": started.replace(microsecond=0).isoformat(),
            "gitHead": _git_head(),
            "inputs": _fetch.used()}


def write_index(origins: list[dict], out: Path, *, hover_cell_count: int | None = None,
                graph: dict | None = None, identity: dict | None = None,
                modes_detail: dict[str, str] | None = None,
                rail_detail: bool = True,
                reading_parent_count: int | None = None,
                solver_bundle: Path | None = None) -> None:
    """index.json: what the page needs to read every other artifact.

    `hover_cell_count` is checked by the page against the length of
    hover_cells.bin itself (app.js: `meta.hoverCellCount !== hoverCells.length`
    -> fatal), which catches an index.json and a cell ordering from two
    different builds. It is NOT what validates the per-origin arrays -- those
    are checked against `hoverCells.length` on arrival, whether or not this
    field is present; `graph` says whether rail and ferries
    were in the build (a road-and-air build is otherwise indistinguishable);
    `identity` is build_identity(). All are optional so a stale index.json is
    still valid -- the page has a fallback for each.

    `modes_detail` should be sampled when the build STARTS. Called here it
    re-reads calibration.toml at write time, which for a sixteen-hour build is
    sixteen hours after the graph was weighted: the prose would describe
    constants the artifacts were not built with.

    `rail_detail` says whether {slug}.rail.bin/.rail.json are on disk. It
    defaults True because this emitter's own build always writes them (see
    emit.rail_detail.write_rail_detail, which writes both even when the tables
    are empty), but it MUST be passed by any caller indexing artifacts it did
    not produce -- `reindex` over a dist/ from an older emitter, above all.
    Writing True over a dist/ with no rail files makes the page fetch two 404s
    per origin switch, which browser_verify.sh fails the deploy for, and makes
    check_dist report one problem per origin naming `reindex` as the remedy for
    a state `reindex` created.
    """
    payload = {
        "contractVersion": CONTRACT_VERSION,
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "unreachable": config.UNREACHABLE,
        "hoverRes": config.HOVER_RES,
        "solveRes": config.SOLVE_RES,
        "fineRes": config.FINE_RES,
        # Channel order of .modes.bin, so the page never re-types it.
        "modeChannels": list(modes.CHANNELS),
        # How each surface mode was modelled, for the route's hover notes.
        "modeDetail": modes_detail if modes_detail is not None else mode_detail(),
        # The page asks for {slug}.rail.bin/.rail.json only when this is true,
        # so an older build is not two 404s per origin switch.
        "railDetail": bool(rail_detail),
        # Carry-on only: airport minutes a traveller without a checked bag does
        # not spend, from calibration.toml [carry_on] with its provenance. The
        # page applies them to the journey on screen, never to the bands.
        "carryOn": carry_on_saving(),
        "hoverCellsUrl": "hover_cells.bin",
        # --- the reading tier ------------------------------------------------
        # The resolution of the number the page PRINTS, which is the base band
        # resolution, not hoverRes. The page refuses to use a reading array
        # whose resolution is not the one it computes its cells at, because a
        # mismatch would binary-search the right directory for the wrong cells
        # and read a plausible time from the wrong place on Earth.
        "readingRes": config.READING_RES,
        "readingParentRes": config.READING_PARENT_RES,
        # Fixed block stride. Published rather than recomputed on the page so
        # the two sides cannot disagree about a constant that silently
        # reindexes the whole array: 342 instead of 343 would shift every
        # block after the first and stay in range.
        "readingSlots": config.READING_SLOTS,
        "readingParentsUrl": "reading_parents.bin",
        "readingUrlSuffix": ".r6.bin",
        "attribution": [dict(entry) for entry in ATTRIBUTION],
        "origins": [
            # `country` only when origins.toml carries it: four origin names in
            # the 553-origin set are shared by two cities, and the page has no
            # other way to tell adjacent identical rows apart.
            {"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"],
             **({"country": o["country"]} if o.get("country") else {})}
            for o in origins
        ],
    }
    # The route behind the fine reading (emit/override.py), advertised only
    # when EVERY origin has it: a dist/ from before the override existed has
    # none, and the page must not fetch a 404 per origin switch for it.
    origins_dir = Path(out).parent / "origins"
    if origins and all((origins_dir / f"{o['slug']}.over.bin").exists() for o in origins):
        payload["overrideUrlSuffix"] = ".over.bin"
    # Exclusion variants ("avoid flights" and the rest) complete for EVERY
    # origin listed above, and only those: offering one built for fewer cities
    # would load bands for some and 404 for the rest (transport_maps.variants).
    from transport_maps import variants

    payload["variants"] = [
        {"exclude": mode, "path": f"v/no-{mode}/", "maxZoom": variants.VARIANT_MAX_ZOOM}
        for mode in variants.complete_variants(Path(out).parent,
                                               [o["slug"] for o in origins])]
    if hover_cell_count is not None:
        payload["hoverCellCount"] = int(hover_cell_count)
    if reading_parent_count is not None:
        payload["readingParentCount"] = int(reading_parent_count)
    if graph is not None:
        payload["graph"] = dict(graph)
    if identity is not None:
        payload.update(identity)
    if _solver_matches(solver_bundle, identity):
        from transport_maps.service.wire import WIRE_VERSION

        payload["solver"] = {"wire": WIRE_VERSION}
    _io.write_text(out, json.dumps(payload, separators=(",", ":")))


def _solver_matches(bundle: Path | None, identity: dict | None) -> bool:
    """Whether the page may offer an on-demand departure.

    Only when the solver bundle was written by the SAME build as the arrays
    the page reads (service/bundle.py stamps the build's identity into
    meta.json). A bundle from another build answers with another graph, and a
    time from the exact point that disagrees with the map beside it is the
    one thing the page cannot explain.
    """
    if bundle is None or not identity or not identity.get("buildId"):
        return False
    try:
        meta = json.loads((Path(bundle) / "meta.json").read_text())
    except (OSError, ValueError):
        return False
    return meta.get("identity", {}).get("buildId") == identity["buildId"]
