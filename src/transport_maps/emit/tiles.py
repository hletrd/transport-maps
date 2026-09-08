"""Band GeoJSON -> PMTiles via tippecanoe."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# Measured on a real Seoul band set: Z0-7 gives 3.84 MB, Z0-6 gives 2.38 MB
# (-38%), while quadrupling simplification only saves 12%. Max zoom is the
# dominant size lever. The source is H3 res-5 hexes (~8.5 km edge), and at
# zoom 6 that is already ~3.5 px, so zoom 7 spends bytes on detail finer than
# the underlying data. Do not raise this without re-measuring.
# z7 measured ~38% larger than z6 and keeps band edges crisp a zoom level
# further in; MapLibre overzooms past the source maximum, so the map still
# zooms to 11 without storing tiles for it.
MIN_ZOOM, MAX_ZOOM = 0, 7
LAYER = "bands"


def write_pmtiles(feature_collection: dict, out: Path) -> None:
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False) as fh:
        json.dump(feature_collection, fh)
        src = Path(fh.name)

    try:
        subprocess.run([
            "tippecanoe",
            "-o", str(out), "--force",
            "-l", LAYER,
            "-Z", str(MIN_ZOOM), "-z", str(MAX_ZOOM),
            "--simplification=4",
            # Bands tile the land exactly, so their shared edges must simplify
            # IDENTICALLY -- otherwise low zooms open hairline gaps along every
            # boundary and the sea shows through the middle of a continent.
            "--detect-shared-borders",
            "--coalesce-densest-as-needed",
            "--extend-zooms-if-still-dropping",
            str(src),
        ], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"tippecanoe failed: {exc.stderr}") from exc
    finally:
        src.unlink(missing_ok=True)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"tippecanoe produced no output at {out}")
