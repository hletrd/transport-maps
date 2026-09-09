"""Static coastline tiles: ocean and lakes as one vector layer, built once.

The bands are painted one cell past the shore (contour/grid.py) and this
layer, drawn above them, cuts them back to the real coast. Doing the coast
here instead of clipping every origin's bands means its precision is
independent of the per-origin build -- and can come from OpenStreetMap, whose
coastline is drawn from imagery at tens of metres, where Natural Earth 10m is
generalised for a 1:10,000,000 map.

Ocean: the OSM water polygons published by osmdata.openstreetmap.de (the
coastline, closed and split on a grid so no polygon is huge). Lakes:
HydroLAKES (Messager et al. 2016, CC BY 4.0), 1.4 million lakes over 10 ha
with outlines from the SRTM water body data and national surveys -- Natural
Earth 10m had a few hundred, drawn for a 1:10,000,000 map.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

from transport_maps import config

WATER_URL = "https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip"
LAKES_URL = "https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip"
LAYER = "water"
MIN_ZOOM, MAX_ZOOM = 0, 12
# Tile-space tolerance. At zoom 12 one unit is ~2.4 m, so 4 keeps the coast
# within ~10 m -- a quarter of a screen pixel at the page's maximum zoom of
# 11, and about the precision of the OSM coastline itself.
SIMPLIFICATION = 4
LAKE_ZOOM_FILTER = (
    '{"*": ["any", ["!has", "Lake_area"], '
    '[">=", "Lake_area", 2000], '
    '["all", [">=", "$zoom", 3], [">=", "Lake_area", 200]], '
    '["all", [">=", "$zoom", 5], [">=", "Lake_area", 20]], '
    '["all", [">=", "$zoom", 7], [">=", "Lake_area", 2]], '
    '["all", [">=", "$zoom", 9], [">=", "Lake_area", 0.2]], '
    '[">=", "$zoom", 11]]}'
)


def _download(url: str = WATER_URL) -> Path:
    cached = config.CACHE / url.rsplit("/", 1)[-1]
    if not cached.exists():
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
            r.raise_for_status()
            tmp = cached.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
            tmp.replace(cached)
    return cached


def _flatgeobuf(url: str) -> Path:
    """A zipped shapefile as FlatGeobuf, which tippecanoe reads directly.

    Converted with GDAL through pyogrio, streaming batch by batch: the ocean
    shapefile is about 1.5 GB and 60 million vertices, which is not something
    to hold as GeoJSON text.
    """
    import pyogrio

    stem = url.rsplit("/", 1)[-1].removesuffix(".zip")
    out = config.CACHE / f"{stem}.fgb"
    if out.exists():
        return out
    archive = _download(url)
    folder = config.CACHE / stem
    if not any(folder.glob("**/*.shp")):
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
    shp = next(folder.glob("**/*.shp"))
    with pyogrio.open_arrow(shp, batch_size=20_000) as (meta, reader):
        pyogrio.write_arrow(reader, out.with_suffix(".part.fgb"), driver="FlatGeobuf",
                            geometry_name=meta["geometry_name"] or "wkb_geometry",
                            geometry_type=meta["geometry_type"], crs=meta["crs"])
    out.with_suffix(".part.fgb").replace(out)
    return out


def build(out: Path) -> Path:
    """Build dist/water.pmtiles. Returns the output path."""
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")
    ocean = _flatgeobuf(WATER_URL)
    lakes = _flatgeobuf(LAKES_URL)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        # Local disk, then move: tippecanoe writes through sqlite, whose
        # locking is unreliable on the NFS mount this repo lives on.
        staged = tmpdir / "water.pmtiles"
        t = time.perf_counter()
        subprocess.run([
            "tippecanoe", "-o", str(staged), "--force",
            "-l", LAYER, "-Z", str(MIN_ZOOM), "-z", str(MAX_ZOOM),
            f"--simplification={SIMPLIFICATION}",
            # The split ocean polygons abut along grid lines; without this the
            # shared edges simplify differently and hairlines open between them.
            "--detect-shared-borders",
            # Visvalingam drops the smallest bumps first, which is what a
            # generalised coast should look like. Douglas-Peucker keeps the
            # farthest-out vertices and leaves a sawtooth of spikes at low
            # zoom -- black teeth biting into every coast at zoom 3.
            "--visvalingam",
            # A bay too small to draw should vanish, not become a square.
            "--no-tiny-polygon-reduction",
            # 1.4 million lakes exceed tippecanoe's per-tile feature limit at
            # low zoom. A lake appears once it is a few pixels across: the
            # filter keys on HydroLAKES' area (km^2) against the zoom. Ocean
            # pieces carry no Lake_area and pass everywhere.
            "-j", LAKE_ZOOM_FILTER,
            "--include=Lake_area",               # the only attribute kept
            str(ocean), str(lakes),
        ], check=True, capture_output=True, text=True)
        shutil.move(str(staged), out)
        print(f"  water tiles: {out.stat().st_size / 1e6:,.0f} MB in "
              f"{(time.perf_counter() - t) / 60:.1f} min")
    return out
