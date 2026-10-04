"""International boundaries as a line tileset, borders.pmtiles.

From the U.S. Department of State's Large Scale International Boundaries
(LSIB), public domain, rather than Natural Earth 1:10m. Natural Earth's
vertices are about 2 km apart and drawn for a 1:10,000,000 map; the page zooms
to 11 (38 m a pixel) beside an OpenStreetMap coastline drawn to ~10 m, and at
that zoom the old line visibly ignored the shore. Measured against OSM's
admin_level=2 ways (and, where the border is a river, OSM's river centreline),
median / 90th-percentile offset of points sampled every 20 m along each line,
2026-10-04:

    region                       Natural Earth 10m     LSIB 11.4
    Dead Sea (Jordan/West Bank)    979 / 1,881 m       95 / 426 m
    Jordan River                   204 /   517 m        5 /  23 m
    West Bank west edge (32.2N)    639 / 1,551 m       12 /  50 m
    Rio Grande at Laredo           627 / 1,528 m        2 /   7 m
    Amur at Blagoveshchensk        402 / 1,312 m       95 / 189 m
    Danube (Romania/Bulgaria)    2,937 / 4,051 m      154 / 395 m
    Mekong at Vientiane            438 /   942 m        0 /  13 m

LSIB says of itself that most lines are within 100 m of their true position.
geoBoundaries CGAZ measured the same as LSIB (it is built from it) but ships
polygons; OSM is as good but needs a planet extract to build.

That precision costs size. LSIB carries 4.3 million vertices; even simplified
to 0.0002 deg (22 m) it is 745,000 vertices and 5.5 MB gzipped as one GeoJSON,
against 0.58 MB for the old borders.json -- downloaded and parsed whole on
every visit. So it is a PMTiles layer like the coast, simplified per zoom to
one tile unit (4.8 m at z11, an eighth of a pixel), and a view fetches only
its own tiles. Measured on the archive this builds (2026-10-04): 412 lines,
12.4 MB in all, but the opening globe's four z1 tiles total 17 KB, no tile
at any zoom exceeds 15 KB, and none at z10-11 exceeds 4 KB. Points sampled
every 20 m along raw LSIB sit a median 0.9 m (worst 6 m) from the z11 tiles
and 2.5 m (worst 15 m) from the z10 ones in each region above, so the
offsets from OSM in the table hold for what is drawn.

Every feature carries `kind`, following LSIB's own ranks, which its metadata
asks a map to keep visually distinct, rank 1 most prominent:

  international  rank 1, an international boundary.
  other          rank 2, "other line of international separation": armistice
                 lines (the West Bank's 1949 line, Gaza's 1950 line), lines of
                 control (Kashmir) and actual control, claim lines, the Korean
                 MDL, provisional and administrative lines, and the Hong Kong
                 and Macau limits.
  special        rank 3: DMZ edges, the UNDOF lines, the Guantanamo lease.

LSIB is U.S. policy ("political recognition and dispute status", its metadata
says), and the page must not adopt a contested position it did not take
before. Two corrections hold it to what Natural Earth's default view, the
previous source, already drew:

* GOLAN_PAIRS. LSIB ranks the Israel/Syria and Israel/Lebanon lines on the
  Golan's edge as international boundaries. Natural Earth calls the first the
  1974 ceasefire line ("Line of control") and the second indefinite; they are
  drawn as `other`.
* NE_KEPT. Where LSIB has no line at all because the U.S. counts a territory
  as part of one state -- Crimea, Northern Cyprus, Somaliland, Western
  Sahara, Siachen -- Natural Earth's line is kept, as `other` (or `special`
  for its overlay and lease limits), so nothing the page separated before is
  silently merged. Selected by Natural Earth's `ne_id`, each with its reason,
  and the build refuses an edition that no longer carries one.

Lines LSIB ranks 1 that Natural Earth marks disputed (the McMahon Line, Hala'ib
on the 22nd parallel, the Essequibo) stay solid: they were solid before too,
since the old layer drew every line alike.
"""

import json
import shutil
import subprocess
import tempfile
import time
import warnings
from pathlib import Path

import pyogrio
import shapely

from .. import config
from .._io import atomic_write, params_hash
from ..sources import _fetch

LSIB_URL = "https://data.geodata.state.gov/LSIB.gpkg"
#: The edition the corrections below were reviewed against. The GeoPackage's
#: one line layer is named for its edition, and the URL above always serves
#: the newest, so a new edition is refused by name rather than read with
#: overrides written for another one.
LSIB_LAYER = "Department of State LSIB v11.4 24Feb2025"
NE_URL = ("https://naturalearth.s3.amazonaws.com/10m_cultural/"
          "ne_10m_admin_0_boundary_lines_land.zip")
LAYER = "borders"
#: MAX_ZOOM is the page's own maxZoom (web/app.js); MapLibre never asks a
#: vector source for a zoom above floor(mapZoom). tippecanoe simplifies each
#: zoom to one tile unit, 40,075 km / (2**11 * 4096) = 4.8 m at z11: an eighth
#: of a 38 m pixel, against the 55 m Natural Earth was simplified to.
MIN_ZOOM, MAX_ZOOM = 0, 11
KIND_BY_RANK = {"1": "international", "2": "other", "3": "special"}
#: LSIB country pairs whose rank-1 line is drawn as `other` (see the module
#: docstring): the Golan Heights' edges, which LSIB ranks as international
#: since the 2019 U.S. recognition and Natural Earth does not.
GOLAN_PAIRS = (("ISRAEL", "LEBANON"), ("ISRAEL", "SYRIA"))
#: Natural Earth lines LSIB does not draw, by ne_id. Each was found by
#: sampling every Natural Earth line every 0.01 deg and listing those mostly
#: farther than 0.05 deg (5.5 km, about Natural Earth's own worst error in
#: the table above, 5.7 km on the Danube) from any LSIB line. The lines on
#: that list classed "International boundary" were Natural Earth's errors
#: (Chad/Libya, Tajikistan/China) and are not kept; nor are three disputed
#: lines only partly off LSIB's (South Sudan's with Sudan and Ethiopia, one
#: China/India claim), which would have run beside LSIB's own as a double.
NE_KEPT = {
    1746708787: "Crimea: the Perekop isthmus line",
    1746708837: "Crimea: the Kerch Strait line",
    1746708827: "the southern Kurils, between Hokkaido and the islands",
    1746708483: "Northern Cyprus: line of control, east",
    1746708491: "Northern Cyprus: line of control",
    1746708497: "Northern Cyprus: line of control, west",
    1746708639: "Cyprus: UN buffer zone limit",
    1746708645: "Cyprus: UN buffer zone limit, west",
    1746708649: "Cyprus: UN buffer zone limit, east",
    1746705343: "Somaliland",
    1746705351: "Western Sahara: the line of control (the berm)",
    1746708721: "Western Sahara: the line of control at the Algerian tripoint",
    1746708603: "Siachen Glacier, Pakistan side",
    1746708607: "Siachen Glacier, India side",
    1746708751: "Bhutan/China: Natural Earth's disputed alignment in the north",
    1746709091: "Argentina/Chile: the Southern Patagonian Ice Field",
    1746708621: "Baikonur Cosmodrome lease",
}
#: Natural Earth classes drawn as `special` rather than `other`, matching
#: LSIB's rank 3 for the same kind of line (DMZ edges, Guantanamo).
NE_SPECIAL = {"Overlay limit", "Lease limit"}


def _download(url: str, name: str) -> Path:
    # Checked against the upstream on every run and streamed (G2): a changed
    # file is fetched again, an unchanged one answers 304, a failure keeps the
    # cached copy, and --offline makes no request at all.
    return _fetch.fetch(url, config.CACHE / name, timeout=600).path


def _lsib_path() -> Path:
    # Keyed on the edition and URL: the URL is unversioned, so a cache named
    # only "LSIB.gpkg" would keep serving the old edition after LSIB_LAYER moved.
    return _download(LSIB_URL, f"LSIB-{params_hash(LSIB_URL, LSIB_LAYER)}.gpkg")


def _ne_path() -> Path:
    return _download(NE_URL, "ne_10m_admin_0_boundary_lines_land.zip")


def _geoms(table) -> list:
    col = next(c for c in table.schema.names if "geom" in c.lower())
    return list(shapely.from_wkb(table.column(col).to_pylist()))


def lsib_features(path: Path) -> list[dict]:
    """LSIB's lines as (kind, geometry) features."""
    with warnings.catch_warnings():
        # LSIB ships its GeoPackage in WAL mode, and SQLite cannot make the
        # -wal/-shm files beside it on the NFS mount this repo lives on, so
        # GDAL warns twice and reopens it immutable -- which is what a cached
        # input is. The warning is about the mount, not the data.
        warnings.filterwarnings("ignore", message=".*WAL-enabled database", category=RuntimeWarning)
        layers = [str(name) for name, _ in pyogrio.list_layers(path)]
        if LSIB_LAYER not in layers:
            raise RuntimeError(
                f"{path.name} holds layers {layers}, not {LSIB_LAYER!r}: a new LSIB edition. "
                "Review its ranks and the corrections in emit/borders.py, then update LSIB_LAYER.")
        _, table = pyogrio.read_arrow(path, layer=LSIB_LAYER)
    cols = table.to_pydict()
    golan = {frozenset(p) for p in GOLAN_PAIRS}
    feats = []
    for i, g in enumerate(_geoms(table)):
        if g is None or g.is_empty:
            continue
        rank = str(cols["RANK"][i])
        if rank not in KIND_BY_RANK:
            raise RuntimeError(f"LSIB feature {cols['ID'][i]} has rank {rank!r}, "
                               f"not one of {sorted(KIND_BY_RANK)}")
        kind = KIND_BY_RANK[rank]
        if frozenset((cols["COUNTRY1"][i], cols["COUNTRY2"][i])) in golan:
            kind = "other"
        feats.append({"kind": kind, "geometry": g})
    return feats


def ne_features(path: Path) -> list[dict]:
    """The Natural Earth lines in NE_KEPT. Refuses an edition missing any."""
    _, table = pyogrio.read_arrow(f"/vsizip/{path.resolve()}" if path.suffix == ".zip" else path)
    cols = table.to_pydict()
    feats, seen = [], set()
    for i, g in enumerate(_geoms(table)):
        ne_id = cols["ne_id"][i]
        if ne_id not in NE_KEPT or g is None or g.is_empty:
            continue
        seen.add(ne_id)
        kind = "special" if cols["FEATURECLA"][i] in NE_SPECIAL else "other"
        feats.append({"kind": kind, "geometry": g})
    missing = sorted(set(NE_KEPT) - seen)
    if missing:
        raise RuntimeError(
            f"Natural Earth no longer carries ne_id {missing} "
            f"({'; '.join(NE_KEPT[m] for m in missing)}): a new edition. Find the "
            "replacement lines and update NE_KEPT rather than dropping them silently.")
    return feats


def write_lines(features: list[dict], fh) -> int:
    """One GeoJSON feature per line (GeoJSONSeq), the form tippecanoe streams."""
    for f in features:
        fh.write(json.dumps({"type": "Feature", "properties": {"kind": f["kind"]},
                             "geometry": shapely.geometry.mapping(f["geometry"])},
                            separators=(",", ":")))
        fh.write("\n")
    return len(features)


def tile(features: list[dict], out: Path) -> int:
    """Write `features` to `out` as a PMTiles line layer. Returns the count."""
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        # Local disk and short relative names, as emit/water.py does:
        # tippecanoe writes through sqlite, unreliable on the NFS mount this
        # repo lives on, and records its argv in the metadata every visitor
        # fetches, so an absolute path would be served to all of them.
        with open(tmpdir / "borders.geojsonl", "w", encoding="utf-8") as fh:
            n = write_lines(features, fh)
        subprocess.run([
            "tippecanoe", "-o", "borders.pmtiles", "--force",
            "-l", LAYER, "-n", "borders",
            "-N", "International boundaries: LSIB, with Natural Earth where LSIB has none",
            "-Z", str(MIN_ZOOM), "-z", str(MAX_ZOOM),
            "-y", "kind",
            # Lines are never dropped to thin a tile; a border that vanished
            # at low zoom would read as countries merging.
            "--no-feature-limit", "--no-tile-size-limit",
            "-P", "borders.geojsonl",
        ], check=True, capture_output=True, text=True, cwd=tmpdir)
        atomic_write(out, lambda tmp: shutil.copyfile(tmpdir / "borders.pmtiles", tmp))
    return n


def build(out: Path) -> int:
    t = time.perf_counter()
    feats = lsib_features(_lsib_path()) + ne_features(_ne_path())
    n = tile(feats, out)
    print(f"  borders: {n} lines, {out.stat().st_size / 1e6:.1f} MB "
          f"in {time.perf_counter() - t:.0f} s")
    return n
