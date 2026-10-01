#!/usr/bin/env python3
"""The dist/ consistency gate, as a module the deploy script calls and the
suite tests.

    uv run python scripts/check_dist.py [--dist dist] [--web web] [--copy-only]

Refuses a build whose artifacts disagree with each other: a hover array of
one length under a cell ordering of another renders plausible, silently
wrong times for every cell (it shipped once, and dist/ is exactly that
mixture during every in-place rebuild). Everything it knows about the file
layout comes from the emitters, not from a second copy of the widths.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

from transport_maps.config import READING_SLOTS
from transport_maps.emit.modes import CHANNELS

REQUIRED_EXTRAS = ("places.json", "airports.json", "borders.json", "water.pmtiles")
# Evidence of an aborted writer; a deploy that merely excluded them would ship
# the partial file next to them.
STRAY = re.compile(r"^(\..*|.*-journal|.*\.tmp|.*\.part|.*\.partial|tmp.*)$")
PMTILES_MAGIC = b"PMTiles"
# "N cities" / "N departures": the count must come from index.json at runtime
# (it said 553 over a 157-origin build once, and "hundreds" over 157 after
# that).
#
# The literal was `[0-9]{3}` -- exactly three digits -- which stopped working
# the moment origins.toml went from 553 to 1,464. Measured before widening it:
# "553 cities" was caught, and "1464 cities", "1464 origins", "1464 departure
# cities" and "over 1464 cities" were all missed. A gate that silently stops
# gating at the transition it exists to police is worse than no gate, and
# deploy/README.md documents this one as what prevents a stale count shipping.
#
# Spelled-out counts are matched too: five of them were live on the site
# ("more than five hundred cities" in the meta description, the og and twitter
# cards, the JSON-LD name and the noscript block) and the numeric pattern
# could never have seen any of them.
_N = r"[0-9]{1,3}(?:[,\u00a0 ][0-9]{3})*|[0-9]{4,}"
_WORDS = (r"(?:a |one |two |three |four |five |six |seven |eight |nine )?"
          r"(?:hundred|thousand)s?(?: of)?")
COUNT_CLAIM = re.compile(
    rf"\b(?:{_N}|{_WORDS}) (?:cities|departure|origin)", re.I)


#: Substrings that must never appear in a PMTiles metadata blob. The blob is
#: served to every visitor -- pmtiles.js fetches the first few KB of every
#: archive on load -- and tippecanoe writes its own argv and input paths into
#: it by default. 64ab007 fixed the emitter; archives written before that, and
#: any produced outside build-all (water.pmtiles is built by a standalone
#: script), still carry a build host's home directory.
#:
#: "generator_options" was in this tuple and had to come out. tippecanoe writes
#: that key on EVERY archive it produces, so the token matched a perfectly
#: clean one -- the detector fired 100 % of the time and therefore carried no
#: signal at all, and deferred.md's exit criterion ("becomes a failure in the
#: same commit") would have failed every deploy on a clean build.
#:
#: Nothing is lost by removing it: the leak that actually reaches a visitor is
#: a PATH, generator_options is merely where tippecanoe usually puts it, and
#: the four prefixes below match it there. The Windows form is added because
#: none of the POSIX prefixes would catch `C:\Users\...`.
PMTILES_METADATA_LEAKS = ("/users/", "/home/", "/var/folders/", "/private/",
                          "c:\\users\\")

#: Commercial-provider fingerprints, the same list the licence firewall
#: enforces over text (`tests/test_licence_firewall.py`). That firewall's
#: SCANNED_SUFFIXES is .json/.geojson/.toml/.txt/.md/.html/.js/.xml -- which
#: excludes .pmtiles and .bin, i.e. every binary artefact an origin ships.
#: CLAUDE.md and deploy/README.md both call the firewall "the only automated
#: licence gate in the project", and it could not see the format most of the
#: published bytes are in. No forbidden token reaches a .pmtiles today (the
#: tippecanoe invocations and the feature properties were traced), so this
#: closes a coverage gap rather than a live leak -- but the metadata blob is
#: one unauthenticated `Range: 0-4095` GET from any visitor, and the decoded
#: text is already in hand here, so the check costs nothing.
PMTILES_FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id",
                     "routes.googleapis.com", "x-goog-api-key", "computeroutes",
                     "google_routes")


def pmtiles_metadata_text(path: Path) -> str | None:
    """The archive's JSON metadata blob, lowercased, or None if unreadable.

    A single unauthenticated `Range: 0-4095` GET returns this blob, so whatever
    is in it is public the moment the archive is. Split out from the leak check
    below so `tests/test_licence_firewall.py` can apply ITS token list to the
    same text without carrying a second PMTiles parser, and without reading the
    28 MB of tile bodies behind it.
    """
    blob = _pmtiles_metadata_bytes(path)
    return None if blob is None else blob.decode("utf-8", "ignore").lower()


def _pmtiles_metadata_bytes(path: Path) -> bytes | None:
    """The metadata blob, gunzipped, as stored -- case and all."""
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(127)
        start, length = struct.unpack_from("<QQ", head, 24)
        if not length or start + length > size or length > 4 << 20:
            return None
        fh.seek(start)
        blob = fh.read(length)
    if blob[:2] == b"\x1f\x8b":
        import gzip
        try:
            blob = gzip.decompress(blob)
        except OSError:
            return None
    return blob


def _pmtiles_metadata_leak(path: Path) -> str | None:
    """A build-host path or a commercial-provider fingerprint in the metadata.

    The emitter-side test builds a fresh archive with today's code and asserts
    on that, which structurally cannot see a file already on disk.
    """
    text = pmtiles_metadata_text(path)
    if text is None:
        return None
    provider = next((t for t in PMTILES_FORBIDDEN if t in text), None)
    if provider:
        return (f"{path.name} metadata contains {provider!r}: a commercial-provider "
                "fingerprint in a published archive, which the licence firewall forbids")
    hit = next((t for t in PMTILES_METADATA_LEAKS if t in text), None)
    return f"{path.name} metadata contains {hit!r}: a build-host path served to every visitor" \
        if hit else None


def _group_warnings(warnings: list[str]) -> dict[str, set[str]]:
    """{leak kind: {filenames}}. A warning reads "<name> <kind>"; anything that
    does not is its own group, so a future warning shape is still printed."""
    groups: dict[str, set[str]] = {}
    for w in set(warnings):
        name, _, rest = w.partition(" ")
        groups.setdefault(rest or w, set()).add(name if rest else "-")
    return groups


def _pmtiles_ok(path: Path) -> str | None:
    """None when the archive's header is sane, else the problem."""
    size = path.stat().st_size
    if size < 127:
        return f"{path.name} is {size} bytes, not a PMTiles archive"
    with open(path, "rb") as fh:
        head = fh.read(127)
    if head[:7] != PMTILES_MAGIC:
        return f"{path.name} does not start with the PMTiles magic"
    # root dir, metadata, leaf dirs, tile data: offset/length pairs at 8..71
    for name, off in (("root directory", 8), ("metadata", 24), ("leaf directories", 40), ("tile data", 56)):
        start, length = struct.unpack_from("<QQ", head, off)
        if start + length > size:
            return f"{path.name} {name} runs past the end of the file (truncated copy?)"
    return None


def _water_problems(path: Path) -> list[str]:
    """water.pmtiles against what emit/water.py builds and web/app.js reads.

    `_pmtiles_ok` proves only that the header is a PMTiles header whose ranges
    fit the file. That passed the 867 MB z0-12 archive whose z12 tiles -- 42.7%
    of the tile section -- no page zoom can request (E15), and it would pass an
    archive whose one layer is not called `water`, which the page's
    `"source-layer": "water"` then draws nothing from: no error, the shore just
    goes back to being hex-shaped, the failure CLAUDE.md names. This file is
    not produced by build-all, so a stale copy is the normal way to get one
    wrong, and the deploy is the last place that can notice.

    The expected zoom range and layer name come from `emit/water.py`, the
    emitter, never from a second copy here; tests/emit/test_water.py ties the
    emitter's zoom to the page's maxZoom and tests/web/test_check_dist.py the
    layer name to the page's source-layer.
    """
    from transport_maps.emit import water

    bad = []
    with open(path, "rb") as fh:
        head = fh.read(127)
    # PMTiles v3: tile type at byte 99 (1 = MVT), min and max zoom at 100, 101.
    tile_type, zmin, zmax = head[99], head[100], head[101]
    if tile_type != 1:
        bad.append(f"{path.name} holds tile type {tile_type}, not vector (MVT, 1): "
                   "the page adds it as a vector source")
    if (zmin, zmax) != (water.MIN_ZOOM, water.MAX_ZOOM):
        bad.append(f"{path.name} spans z{zmin}-z{zmax}, emit/water.py builds "
                   f"z{water.MIN_ZOOM}-z{water.MAX_ZOOM}: a stale archive; rebuild it with "
                   "scripts/build_water_tiles.py")
    blob = _pmtiles_metadata_bytes(path)
    try:
        meta = json.loads(blob) if blob else None
    except ValueError:
        meta = None
    layers = meta.get("vector_layers") if isinstance(meta, dict) else None
    if not isinstance(layers, list):
        bad.append(f"{path.name} metadata has no vector_layers, so nothing confirms the "
                   f"{water.LAYER!r} layer the page draws the coast from")
    else:
        ids = sorted(str(lyr.get("id")) for lyr in layers if isinstance(lyr, dict))
        if water.LAYER not in ids:
            bad.append(f"{path.name} has vector layers {ids}, not {water.LAYER!r}: the page's "
                       "water layer would render nothing and the shore would go hex-shaped")
    return bad


def check_dist(dist: Path, origins: list[dict] | None = None,
               n_channels: int = len(CHANNELS),
               warn_out: list[str] | None = None) -> list[str]:
    """Every problem found under `dist`, or an empty list.

    `origins` is the expected origin list (data/origins.toml); when given,
    index.json must list exactly those slugs -- a partial build never
    rewrites index.json, so a mismatch means a stale one.

    `warn_out` collects findings that are REPORTED but do not fail the deploy.
    There is exactly one class of those: a build-host path in a PMTiles
    metadata blob. The only remedy is regenerating the tileset, the leak is
    already live on archives written before 64ab007, and water.pmtiles is not
    produced by build-all at all -- so failing here would block every deploy on
    an artifact the deploy cannot fix, without removing one byte of exposure.
    plan/deferred.md records the exit criterion: when the water tileset is next
    rebuilt this becomes a failure in the same commit.
    """
    dist = Path(dist)
    bad: list[str] = []
    warn = warn_out if warn_out is not None else []
    if (dist / ".build.lock").exists():
        bad.append(".build.lock present: a build is running, or died holding it")
    for p in dist.rglob("*"):
        if p.is_file() and STRAY.match(p.name) and p.name != ".build.lock":
            bad.append(f"stray file {p.relative_to(dist)} (an aborted writer's leftover)")

    index_path = dist / "index.json"
    if not index_path.exists():
        return [*bad, "index.json missing"]
    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [*bad, f"index.json unreadable: {exc}"]
    listed = idx.get("origins") or []
    if not listed:
        bad.append("index.json lists no origins")
    if origins is not None:
        want = {o["slug"] for o in origins}
        have = {o["slug"] for o in listed}
        if want != have:
            bad.append(f"index.json lists {len(have)} origins, origins.toml has {len(want)} "
                       f"(missing {sorted(want - have)[:5]}, extra {sorted(have - want)[:5]})")
    # REQUIRED, not "checked if present". Both fields are the page's only
    # defence against a mixed build, and `if key in idx` meant an index.json
    # written by an emitter older than the artifacts beside it -- which is what
    # a long build publishes, since the parent writes index.json at the end
    # using the module it imported at the start -- passed this gate with the
    # guards silently off. `transport-maps reindex` rewrites the file alone.
    if "modeChannels" not in idx:
        bad.append("index.json has no modeChannels: the page cannot check the .modes.bin channel "
                   "order. Run `uv run transport-maps reindex`.")
    elif len(idx["modeChannels"]) != n_channels:
        bad.append(f"index.json modeChannels has {len(idx['modeChannels'])} entries, emitter has {n_channels}")

    # app.js: `const EDGES = meta.bandEdgesMin` and then expandRamp(EDGES) --
    # fatal() on load without it, which is a blank page, not a degraded one.
    # check_dist called such a dist/ consistent.
    edges = idx.get("bandEdgesMin")
    if not isinstance(edges, list) or not edges:
        bad.append("index.json has no bandEdgesMin: the page cannot draw a legend and "
                   "stops on load. Run `uv run transport-maps reindex`.")
    elif list(edges) != sorted(edges) or len(set(edges)) != len(edges):
        bad.append(f"index.json bandEdgesMin is not strictly ascending: {edges[:8]}...")

    # Attribution is a LICENCE OBLIGATION, not a nicety, and it is the one
    # class of defect where the shipped artifact can be wrong while the code is
    # right -- which is exactly what happened: HydroLAKES lakes (CC BY 4.0)
    # have been drawn on the live map with the live index.json naming seven
    # sources and neither HydroLAKES nor GeoNames among them, because the
    # deployed index predates their addition to emit.index.ATTRIBUTION. No gate
    # could see it, because nothing compared the two.
    from transport_maps.emit.index import ATTRIBUTION
    if ATTRIBUTION:
        named = {(a or {}).get("name") for a in idx.get("attribution") or []}
        missing = [a["name"] for a in ATTRIBUTION if a["name"] not in named]
        if missing:
            bad.append(
                "index.json attribution does not credit "
                + ", ".join(missing)
                + ", which the pipeline consumes and whose licence requires it. "
                  "Run `uv run transport-maps reindex`.")

    cells_path = dist / "hover_cells.bin"
    if not cells_path.exists():
        return [*bad, "hover_cells.bin missing"]
    if cells_path.stat().st_size % 8:
        bad.append("hover_cells.bin is not a whole number of uint64 ids")
    n_cells = cells_path.stat().st_size // 8
    if "hoverCellCount" not in idx:
        bad.append("index.json has no hoverCellCount: the page cannot refuse an origin array from "
                   "a different build. Run `uv run transport-maps reindex`.")
    elif idx["hoverCellCount"] != n_cells:
        bad.append(f"index.json hoverCellCount {idx['hoverCellCount']} != hover_cells.bin {n_cells}")

    # The reading tier's directory. Absent means a dist/ built before the tier
    # existed, which is publishable -- the page falls back to the res-4 array.
    # Present means every listed origin must have its block array at exactly
    # the directory's width: half a build is the blank-globe failure this
    # script exists to prevent, and a block array that is short by one block
    # shifts every reading after it without changing any file's parseability.
    parents_path = dist / "reading_parents.bin"
    reading_bytes = 0
    if parents_path.exists():
        psize = parents_path.stat().st_size
        if psize == 0 or psize % 8:
            bad.append(f"reading_parents.bin is {psize} bytes, not a whole number of uint64 ids")
        else:
            n_parents = psize // 8
            reading_bytes = n_parents * READING_SLOTS * 2
            declared = idx.get("readingParentCount")
            if declared is None:
                bad.append("reading_parents.bin ships but index.json has no readingParentCount: "
                           "the page cannot refuse a reading array from a different build. "
                           "Run `uv run transport-maps reindex`.")
            elif declared != n_parents:
                bad.append(f"index.json readingParentCount {declared} != "
                           f"reading_parents.bin {n_parents}")
            if idx.get("readingSlots") not in (None, READING_SLOTS):
                bad.append(f"index.json readingSlots {idx.get('readingSlots')} != "
                           f"{READING_SLOTS}: the page would read the right block "
                           "at the wrong slot, which is in range and wrong everywhere")
            # A directory whose ids are not at readingParentRes would be
            # binary-searched successfully for cells it does not contain, so
            # every land reading would miss and report open water.
            want_res = idx.get("readingParentRes")
            if want_res is not None and n_parents:
                head = np.fromfile(parents_path, dtype="<u8", count=min(4096, n_parents))
                res_of = ((head >> np.uint64(52)) & np.uint64(0xF)).astype(int)
                wrong = int((res_of != want_res).sum())
                if wrong:
                    bad.append(f"reading_parents.bin: {wrong} of the first {len(head)} ids "
                               f"are not at resolution {want_res}")

    widths = {".bin": 2, ".air.bin": 2, ".modes.bin": 2 * n_channels}
    # Every exclusion variant index.json offers must hold every listed origin's
    # files, at the full set's widths: choosing one that does not would load
    # bands for some cities and 404 for the rest (transport_maps.variants).
    for v in idx.get("variants") or []:
        vdir = dist / v.get("path", "") / "origins"
        for o in listed:
            for suffix in (".pmtiles", ".json", *widths):
                p = vdir / f"{o['slug']}{suffix}"
                if not p.exists():
                    bad.append(f"variant no-{v.get('exclude')}: {p.name} missing")
                elif suffix in widths and p.stat().st_size != n_cells * widths[suffix]:
                    bad.append(f"variant no-{v.get('exclude')}: {p.name} has "
                               f"{p.stat().st_size // widths[suffix]} entries, expected {n_cells}")
            # The page reads a variant's reading tier and route override from
            # the variant's own directory, exactly as it does the full set's.
            if reading_bytes:
                r6 = vdir / f"{o['slug']}.r6.bin"
                if not r6.exists():
                    bad.append(f"variant no-{v.get('exclude')}: {r6.name} missing")
                elif r6.stat().st_size != reading_bytes:
                    bad.append(f"variant no-{v.get('exclude')}: {r6.name} is "
                               f"{r6.stat().st_size} bytes, expected {reading_bytes}")
            if idx.get("overrideUrlSuffix"):
                over = vdir / f"{o['slug']}{idx['overrideUrlSuffix']}"
                entry = 4 + 2 + 2 * n_channels
                if not over.exists():
                    bad.append(f"variant no-{v.get('exclude')}: {over.name} missing")
                elif over.stat().st_size % entry:
                    bad.append(f"variant no-{v.get('exclude')}: {over.name} is "
                               f"{over.stat().st_size} bytes, not whole {entry}-byte entries")
    n_nodes: dict[int, list[str]] = {}
    rail_advertised = bool(idx.get("railDetail"))
    for o in listed:
        s = o["slug"]
        base = dist / "origins" / s
        for suffix, width in widths.items():
            p = base.with_name(s + suffix)
            if not p.exists():
                bad.append(f"{s}{suffix} missing")
            elif p.stat().st_size != n_cells * width:
                bad.append(f"{s}{suffix} has {p.stat().st_size // width} entries, expected {n_cells}")
        if reading_bytes:
            r6 = base.with_name(s + ".r6.bin")
            if not r6.exists():
                bad.append(f"{s}.r6.bin missing although reading_parents.bin ships")
            elif r6.stat().st_size != reading_bytes:
                bad.append(f"{s}.r6.bin is {r6.stat().st_size} bytes, expected {reading_bytes} "
                           f"({reading_bytes // (READING_SLOTS * 2)} blocks x {READING_SLOTS} slots)")
        rail_bin, rail_json = base.with_name(s + ".rail.bin"), base.with_name(s + ".rail.json")
        if rail_bin.exists() != rail_json.exists():
            bad.append(f"{s}: .rail.bin and .rail.json must ship together")
        if rail_advertised and not rail_bin.exists():
            bad.append(f"{s}.rail.bin missing although index.json advertises railDetail")
        if rail_bin.exists() and rail_bin.stat().st_size != n_cells * 2:
            bad.append(f"{s}.rail.bin has {rail_bin.stat().st_size // 2} entries, expected {n_cells}")
        if rail_json.exists():
            # app.js reads j.stations and indexes it by the uint16 in .rail.bin.
            # A file without that key leaves `table` undefined and railVia()
            # throws out of the click handler on any rail-served cell, leaving
            # the previous destination's itinerary on screen with no error.
            try:
                rail_payload = json.loads(rail_json.read_text(encoding="utf-8"))
                if not isinstance(rail_payload.get("stations"), list):
                    bad.append(f"{s}.rail.json has no stations list (the page indexes it)")
            except (OSError, ValueError):
                bad.append(f"{s}.rail.json is unreadable")
        # The fine-cell route (emit/override.py): advertised means present for
        # every origin, and whole 4+2+2*channels-byte entries -- the page
        # refuses anything else, which would silently lose the route detail.
        if idx.get("overrideUrlSuffix"):
            over = base.with_name(s + idx["overrideUrlSuffix"])
            entry = 4 + 2 + 2 * n_channels
            if not over.exists():
                bad.append(f"{s}{idx['overrideUrlSuffix']} missing although index.json advertises it")
            elif over.stat().st_size % entry:
                bad.append(f"{s}{idx['overrideUrlSuffix']} is {over.stat().st_size} bytes, "
                           f"not whole {entry}-byte entries")
        routes = base.with_name(s + ".json")
        if not routes.exists():
            bad.append(f"{s}.json missing (the route panel walks it)")
        else:
            try:
                payload = json.loads(routes.read_text(encoding="utf-8"))
                off = payload.get("offsets")
                if not isinstance(off, dict) or not isinstance(payload.get("nodes"), list):
                    bad.append(f"{s}.json lacks offsets/nodes")
                elif not all(isinstance(off.get(k), int) for k in ("airports", "stations")):
                    # An empty or partial offsets object passed the `in` test
                    # above and made the route panel silently disappear: the
                    # page checks the same two numbers and gives up quietly.
                    bad.append(f"{s}.json offsets lacks airports/stations "
                               f"(the route panel silently disappears): {sorted(off)}")
                else:
                    # The per-origin fingerprint of the build that made this
                    # file. Every fixed-width array is n_cells long whatever the
                    # solve resolution, because the res-4 parent count depends
                    # on the land mask -- so all 349 shipped arrays are the same
                    # size and a stale res-5 array passes every length check
                    # above.
                    #
                    # BOTH offsets, not just the first. offsets.airports is
                    # idx.n_cells, so it moves only with the solve resolution
                    # (about 635k at res 5 against 13.7M at res 6). The gap
                    # between the two offsets is the AIRPORT COUNT, which moves
                    # whenever the airport set changes -- an added snap rule, a
                    # new source extract, a different filter. Keying on
                    # offsets.airports alone, this gate called a dist/ holding
                    # 3,990 airports in some origins and 3,996 in others
                    # consistent, while parsing offsets.stations two lines above
                    # and discarding it. CLAUDE.md: "Never deploy a partial
                    # dist/. The per-origin arrays and hover_cells.bin must come
                    # from the same build; mixing them renders a blank globe
                    # with no error."
                    n_nodes.setdefault((off["airports"], off["stations"]), []).append(s)
            except (OSError, ValueError):
                bad.append(f"{s}.json is not valid JSON (truncated write?)")
        tiles = base.with_name(s + ".pmtiles")
        if not tiles.exists():
            bad.append(f"{s}.pmtiles missing")
        else:
            problem = _pmtiles_ok(tiles)
            if problem:
                bad.append(problem)
            else:
                leak = _pmtiles_metadata_leak(tiles)
                if leak:
                    warn.append(leak)

    # Every origin of one build walks the same node universe, so a disagreement
    # means two builds are mixed in dist/ -- the failure the deploy rule calls
    # out as having twice produced a blank live site.
    if len(n_nodes) > 1:
        groups = ", ".join(
            f"{a:,} cells / {(t - a) // 2:,} airports in {len(v)} origin(s) e.g. {v[0]}"
            for (a, t), v in sorted(n_nodes.items(), key=lambda kv: -len(kv[1]))[:3])
        bad.append(f"origins disagree on the node universe ({groups}): dist/ mixes two builds")

    for extra in REQUIRED_EXTRAS:
        p = dist / extra
        if not p.exists():
            bad.append(f"{extra} missing")
        elif extra.endswith(".pmtiles"):
            problem = _pmtiles_ok(p)
            if problem:
                bad.append(problem)
            else:
                if extra == "water.pmtiles":
                    bad.extend(_water_problems(p))
                leak = _pmtiles_metadata_leak(p)
                if leak:
                    warn.append(leak)
    return bad


def check_copy(web: Path) -> list[str]:
    """The page copy must not state a city count the data can contradict."""
    bad = []
    # A --web path that does not exist returned [] -- "no problems" -- so a
    # typo in deploy_verify.sh, or a rename of web/, skipped the page gate in
    # complete silence and the deploy went ahead. An absent tree is a problem
    # with the invocation, not a clean bill of health.
    if not Path(web).is_dir():
        return [f"--web {web} is not a directory: the page copy was never checked"]
    for name in ("index.html", "llms.txt"):
        p = Path(web) / name
        if not p.exists():
            bad.append(f"web/{name} missing from {web}: the page copy gate cannot run")
            continue
        for m in COUNT_CLAIM.finditer(p.read_text(encoding="utf-8")):
            bad.append(f"web/{name} states a city count ({m.group(0)!r}); derive it from index.json")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=Path("dist"))
    ap.add_argument("--web", type=Path, default=Path("web"))
    ap.add_argument("--copy-only", action="store_true", help="check the page copy only (page-only deploy)")
    ap.add_argument("--no-origins", action="store_true", help="do not compare index.json with data/origins.toml")
    args = ap.parse_args()

    problems = check_copy(args.web)
    warnings: list[str] = []
    if not args.copy_only:
        origins = None
        if not args.no_origins:
            from transport_maps.emit.index import load_origins
            origins = load_origins()
        problems += check_dist(args.dist, origins, warn_out=warnings)
        if not problems:
            # .get throughout: this summary used to KeyError on an index.json
            # it had just declared consistent, because check_dist never
            # required `attribution` or `bandEdgesMin`.
            idx = json.loads((args.dist / "index.json").read_text())
            n = (args.dist / "hover_cells.bin").stat().st_size // 8
            bands = len(idx.get("bandEdgesMin") or []) + 1
            print(f"  hover cells {n:,} | origins {len(idx.get('origins') or [])} | bands {bands} "
                  f"| solveRes {idx.get('solveRes')} | build {idx.get('buildId', 'unstamped')}")
            print(f"  attribution {[a.get('name') for a in idx.get('attribution') or []]}")
    if warnings:
        # Reported, not fatal; see check_dist's docstring for why, and
        # plan/deferred.md for the exit criterion that makes it fatal.
        #
        # Grouped by KIND, not truncated alphabetically. With 447 archives
        # warning, `sorted(...)[:8]` printed eight filenames beginning with
        # "a" and dropped the rest -- so water.pmtiles, the only archive
        # carrying a '/users/' path and the only one build-all can never fix,
        # was never once shown. One line per distinct leak, with a count and
        # two examples, fits every kind on screen however many files share it.
        print("  WARNINGS (not blocking):")
        for kind, names in sorted(_group_warnings(warnings).items()):
            shown = ", ".join(sorted(names)[:2])
            more = f" and {len(names) - 2} more" if len(names) > 2 else ""
            print(f"    {len(names)} x {kind}  [{shown}{more}]")
    if problems:
        print("  PROBLEMS:", *problems[:15], sep="\n    ")
        if len(problems) > 15:
            print(f"    ... and {len(problems) - 15} more")
        sys.exit(1)
    if args.copy_only:
        # --page-only ships web/ and never looks at dist/. Claiming dist/ is
        # consistent here put an assertion about work that never ran into the
        # deploy transcript.
        print("  page copy checked (no dist/ gate: --copy-only)")
    else:
        print("  dist/ is consistent: every origin has pmtiles + bin + air.bin + modes.bin + json, "
              "rail files paired, no strays; page copy states no count")


if __name__ == "__main__":
    main()
