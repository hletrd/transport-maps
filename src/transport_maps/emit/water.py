"""Static coastline tiles: ocean and lakes as one vector layer, built once.

The bands are painted one cell past the shore (contour/grid.py) and this
layer, drawn above them, cuts them back to the real coast. Doing the coast
here instead of clipping every origin's bands means its precision is
independent of the per-origin build -- and can come from OpenStreetMap, whose
coastline is drawn from imagery at tens of metres, where Natural Earth 10m is
generalised for a 1:10,000,000 map.

Ocean: the OSM water polygons published by osmdata.openstreetmap.de (the
coastline, closed and split on a grid so no polygon is huge). Lakes: Natural
Earth 10m, the same set the land mask cuts out, so a lake shore the solver
knows about is drawn and one it does not is not.
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
LAYER = "water"
MIN_ZOOM, MAX_ZOOM = 0, 10
# Tile-space tolerance. At zoom 10 one unit is ~9.5 m, so 8 keeps the coast
# within ~76 m -- about one screen pixel at the page's maximum zoom of 11.
SIMPLIFICATION = 8


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


def _ocean_flatgeobuf() -> Path:
    """The ocean shapefile as FlatGeobuf, which tippecanoe reads directly.

    Converted with GDAL through pyogrio, streaming batch by batch: the
    shapefile is about 1.5 GB and 60 million vertices, which is not something
    to hold as GeoJSON text.
    """
    import pyogrio

    out = config.CACHE / "water-polygons-split-4326.fgb"
    if out.exists():
        return out
    archive = _download()
    folder = config.CACHE / "water-polygons-split-4326"
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


def _lakes_geojson(tmpdir: Path) -> Path:
    """Natural Earth lakes, attributes dropped, as a temporary GeoJSON."""
    import pyogrio

    from transport_maps.sources import landmask

    path = landmask._download(landmask.LAKES_URL, "ne_10m_lakes.zip").resolve()
    meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    geom = meta["geometry_name"] or "wkb_geometry"
    out = tmpdir / "lakes.geojson"
    pyogrio.write_arrow(table.select([geom]), out, driver="GeoJSON",
                        geometry_name=geom, geometry_type=meta["geometry_type"],
                        crs=meta["crs"])
    return out


def build(out: Path) -> Path:
    """Build dist/water.pmtiles. Returns the output path."""
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")
    ocean = _ocean_flatgeobuf()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        lakes = _lakes_geojson(tmpdir)
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
            "--coalesce-densest-as-needed",
            "--extend-zooms-if-still-dropping",
            "--exclude-all",                     # geometry only; no attributes
            str(ocean), str(lakes),
        ], check=True, capture_output=True, text=True)
        shutil.move(str(staged), out)
        print(f"  water tiles: {out.stat().st_size / 1e6:,.0f} MB in "
              f"{(time.perf_counter() - t) / 60:.1f} min")
    return out
