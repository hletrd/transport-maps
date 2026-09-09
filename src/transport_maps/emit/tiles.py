"""Band GeoJSON -> PMTiles via tippecanoe."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from transport_maps import _io

# Measured on a real Seoul band set: Z0-7 gives 3.84 MB, Z0-6 gives 2.38 MB
# (-38%), while quadrupling simplification only saves 12%. Max zoom is the
# dominant size lever. At zoom 8 the simplification tolerance is ~0.3 km,
# which keeps the 2.4 km fine cells hexagons under overzoom; z7 measured ~38%
# larger than z6 and keeps band edges crisp a zoom level further in, and
# MapLibre overzooms past the source maximum, so the map still zooms to 11
# without storing tiles for it. Do not raise this without re-measuring.
MIN_ZOOM, MAX_ZOOM = 0, 8
LAYER = "bands"


def scratch_dir() -> Path:
    """Where tippecanoe's input and output are staged: LOCAL disk, in one
    named directory. tippecanoe writes its output through sqlite3, whose file
    locking is unreliable over NFS -- and this repo lives on an NFS mount;
    writing straight to dist/ survived 111 origins of a 157-origin build and
    then died with "sqlite3 map insert failed: disk I/O error" (which is why
    the input is not under data/build either). A named directory, with the
    writing process's pid in every file name, is what lets sweep_scratch()
    remove what a killed worker left behind -- 650 MB per origin at res 6/7 --
    without touching a build that is still running."""
    d = Path(tempfile.gettempdir()) / "transport-maps"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Staging files are named <slug>.<pid>.<random>.geojson|.pmtiles.
_STAGED = re.compile(r"^.+\.(\d+)\.[^.]+\.(geojson|pmtiles)$")


def sweep_scratch(directory: Path | None = None) -> int:
    """Delete staging files whose writing process is gone; returns the count.

    The directory is shared by every build on the machine (and by the test
    suite), so a file is only stale when the pid in its name no longer exists;
    anything else -- including files without a pid, which are not ours -- is
    left alone.
    """
    n = 0
    d = directory or scratch_dir()
    for p in d.iterdir():
        m = _STAGED.match(p.name)
        if p.is_file() and m and not _io.pid_alive(int(m.group(1))):
            p.unlink(missing_ok=True)
            n += 1
    return n


def _threads(workers: int | None) -> dict[str, str]:
    """tippecanoe uses every core by default; with several workers each
    running one, cap it to the worker's share (it honours this variable)."""
    if not workers or workers <= 1:
        return {}
    cores = os.cpu_count() or 1
    return {"TIPPECANOE_MAX_THREADS": str(max(1, cores // workers))}


def write_pmtiles(feature_collection: dict, out: Path, *, workers: int | None = None) -> None:
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")

    out = Path(out)
    scratch = scratch_dir()
    fd, src_name = tempfile.mkstemp(dir=scratch, prefix=f"{out.stem}.{os.getpid()}.", suffix=".geojson")
    src = Path(src_name)
    with os.fdopen(fd, "w") as fh:
        json.dump(feature_collection, fh)
    staged = src.with_suffix(".pmtiles")

    try:
        # Relative paths and cwd=scratch: tippecanoe records its whole command
        # line in the archive's metadata, which the page fetches on every
        # source load, so an absolute path here is a local path served to
        # every visitor (CRIT-17).
        result = subprocess.run([
            "tippecanoe",
            "-o", staged.name, "--force",
            "-l", LAYER, "-n", out.stem, "-N", f"{out.stem} travel-time bands",
            "-Z", str(MIN_ZOOM), "-z", str(MAX_ZOOM),
            # Tippecanoe simplifies in TILE space, so its tolerance scales with
            # zoom and cannot pull a rounded corner back onto a hex vertex the
            # way a fixed degree tolerance does. This is the right knob for
            # size; the geometry handed to it stays smooth.
            "--simplification=8",
            # Visvalingam drops the smallest bumps first. Douglas-Peucker keeps
            # the farthest-out vertices, which on a hex edge at low zoom means
            # a sawtooth of spikes.
            "--visvalingam",
            # A band fragment too small to draw should vanish, not become a
            # square of the same area.
            "--no-tiny-polygon-reduction",
            "--coalesce-densest-as-needed",
            "--extend-zooms-if-still-dropping",
            src.name,
        ], check=True, capture_output=True, text=True, cwd=scratch,
            env={**os.environ, **_threads(workers)})
        # The 650 MB input is done with as soon as tippecanoe returns.
        src.unlink(missing_ok=True)
        # tippecanoe says when it had to coarsen a tile to make it fit, and
        # nothing else does: a coarsened tile is what turns a coast into teeth.
        notes = [l for l in result.stderr.splitlines()
                 if "tile " in l and ("too large" in l or "detail" in l or "dropping" in l)]
        for note in notes[:3]:
            print(f"  tippecanoe: {note.strip()[:140]}")
        # Publish by copying into a same-directory temp file and renaming it
        # over the target. shutil.move across filesystems is a copy PLUS an
        # unlink: the destination was truncated for the seconds the copy took,
        # and a worker killed mid-copy left a partial archive that the deploy
        # gate (existence only) shipped.
        _io.atomic_write(out, lambda tmp: shutil.copyfile(staged, tmp))
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"tippecanoe failed: {exc.stderr}") from exc
    finally:
        src.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"tippecanoe produced no output at {out}")
