"""Band GeoJSON -> PMTiles via tippecanoe."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

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
