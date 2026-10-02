"""Geofabrik extracts: is the copy on disk the current one? (G2)

The OSM inputs are not fetched by `_fetch`. They are tens of gigabytes, and
two shell scripts own downloading them: `scripts/osm_fixed_links.sh` keeps the
full regional extracts (`{region}.osm.pbf`) that sources/fixed_links.py
parses, and `scripts/osm_rail.sh` filters them to rail and ferries
(`{region}-rail.osm.pbf`) for sources/osm.py. Both download a DATED file named
by the region's replication state, `{region}-updates/state.txt`.

So the check is the same question asked differently: each build reads every
region's state.txt (a few hundred bytes each) and compares its timestamp with
the snapshot the local extract was cut from, which every Geofabrik PBF carries
in its header as `osmosis_replication_timestamp` -- and which the rail filter
preserves, measured on the extracts in data/cache/osm. When the upstream is
newer by MAX_AGE_DAYS or more, the script for that region is run again with
OSM_REPLACE=1, which re-downloads the dated file, checks its size against the
server's and only then replaces the old one.

Why a threshold rather than "any newer file": Geofabrik republishes every
region DAILY. With no threshold every build would re-download all of it --
about 85 GB of full extracts, plus a 100 GB pass for rail -- to pick up one
day of edits, and a build that runs for three days would always be behind by
the time it finished. MAX_AGE_DAYS bounds how stale an extract may get; set
TRANSPORT_MAPS_OSM_MAX_AGE_DAYS=0 for "re-extract whenever the dated file
changed", which is the owner's rule read literally.

A failed check, a missing tool (osm_rail.sh needs the `osmium` command-line
tool, which the build host does not have) or a failed script leaves the
extract on disk in use and says so, like a mirror being down for `_fetch`.
Offline, nothing is asked.

An extract that is not on disk at all is NOT downloaded here. That is an
install step, tens of gigabytes, and the build has always reported it rather
than done it ("rail: EXCLUDED -- ... run scripts/osm_rail.sh first"); a fresh
clone running `build-all --only seoul` must not start an 85 GB download.
Nor is a full extract whose raw file was deleted after its bridge parse was
cached (sources/fixed_links.py invites that, to free ~70 GB): re-downloading
it would undo the operator's choice of disk over freshness. A cache behind
Geofabrik is reported with the command that refreshes it, every build, and
otherwise used as it is.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import pathlib
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

from transport_maps import config
from transport_maps.sources import _fetch

logger = logging.getLogger(__name__)

STATE_URL = "https://download.geofabrik.de/{region}-updates/state.txt"
MAX_AGE_ENV = "TRANSPORT_MAPS_OSM_MAX_AGE_DAYS"
MAX_AGE_DAYS = 7.0
SCRIPTS = config.ROOT / "scripts"

# Every region either extract kind is cut for: the seven continental extracts
# in sources/fixed_links.REGIONS, which scripts/osm_rail.sh also loops over.
REGIONS = ("africa", "asia", "australia-oceania", "central-america",
           "europe", "north-america", "south-america")

_STATE_TS = re.compile(r"^timestamp=(.+)$", re.MULTILINE)


def max_age() -> timedelta:
    raw = os.environ.get(MAX_AGE_ENV, "").strip()
    return timedelta(days=float(raw) if raw else MAX_AGE_DAYS)


def _parse_ts(value: str) -> datetime:
    """`2026-09-20T20:22:06Z`, as both state.txt (with escaped colons) and
    the PBF header write it."""
    return datetime.fromisoformat(value.replace("\\", "").strip().replace("Z", "+00:00"))


def snapshot(path: pathlib.Path) -> datetime | None:
    """The replication timestamp in a PBF's header, or None when it has none
    (a hand-made extract, a test fixture) or cannot be read."""
    import osmium

    try:
        reader = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
        try:
            value = reader.header().get("osmosis_replication_timestamp")
        finally:
            reader.close()
        return _parse_ts(value) if value else None
    except (RuntimeError, OSError, ValueError):
        return None


def upstream(region: str) -> datetime | None:
    """When the region's current extract was cut, from its state.txt; None
    (and a warning) when that cannot be read."""
    url = STATE_URL.format(region=region)
    try:
        m = _STATE_TS.search(_fetch.get_text(url))
        if m is None:
            raise ValueError("no timestamp= line")
        return _parse_ts(m.group(1))
    except Exception as exc:  # noqa: BLE001 -- any failure to read it means "not checked", never a dead build
        logger.warning("could not read %s (%s); the %s extracts on disk are used as they are",
                       url, exc, region)
        return None


@dataclasses.dataclass(frozen=True)
class Extract:
    region: str
    kind: str                    # "rail" (osm_rail.sh) or "full" (osm_fixed_links.sh)
    local: datetime | None       # None: absent, or no timestamp in its header
    upstream: datetime | None    # None: not checked
    present: bool = True         # on disk (a full extract: or a parse of it)

    @property
    def stale(self) -> bool:
        if self.upstream is None or not self.present:
            return False
        if self.local is None:
            # On disk with no snapshot in its header: its age is unknown.
            return True
        # Strictly newer first: at a max age of 0 an extract already at the
        # upstream's snapshot must not be downloaded again every build.
        return self.upstream > self.local and self.upstream - self.local >= max_age()


def _local(extracts_dir: pathlib.Path, region: str, kind: str,
           up: datetime | None = None) -> Extract:
    if kind == "rail":
        path = extracts_dir / f"{region}-rail.osm.pbf"
        present = path.exists()
        return Extract(region, kind, snapshot(path) if present else None, up, present)
    path = extracts_dir / f"{region}.osm.pbf"
    if path.exists():
        return Extract(region, kind, snapshot(path), up)
    # The full extracts exist only to feed the fixed-link parse and may be
    # deleted once it is cached; the cache's name then carries the snapshot.
    # Not `present`: only a raw file on disk is ever replaced (module docstring).
    from transport_maps.sources import fixed_links

    return Extract(region, kind, fixed_links.cached_snapshot(region), up, present=False)


def survey(extracts_dir: pathlib.Path, regions=REGIONS) -> list[Extract]:
    """Every region's two extracts, local snapshot against upstream."""
    out = []
    for region in regions:
        up = upstream(region)
        for kind in ("full", "rail"):
            out.append(_local(extracts_dir, region, kind, up))
    return out


def _run(script: str, regions: list[str], extracts_dir: pathlib.Path) -> bool:
    cmd = ["bash", str(SCRIPTS / script), *regions]
    env = {**os.environ, "OSM_DIR": str(extracts_dir), "OSM_REPLACE": "1"}
    logger.info("re-extracting %s: %s", ", ".join(regions), " ".join(cmd))
    done = subprocess.run(cmd, env=env, check=False)
    if done.returncode != 0:
        logger.warning("%s exited %d; the extracts it did not replace are used as they are",
                       script, done.returncode)
    return done.returncode == 0


def refresh(extracts_dir: pathlib.Path | None = None, regions=REGIONS) -> list[Extract]:
    """Check every extract against Geofabrik and re-extract the stale ones.

    Full extracts first: the rail filter reads a full extract when one is on
    disk, so a region stale in both is downloaded once. Returns the survey as
    it stands afterwards, which is also recorded for the build identity.
    """
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    if _fetch.offline():
        found = [_local(extracts_dir, r, k) for r in regions for k in ("full", "rail")]
        _record(found)
        return found

    found = survey(extracts_dir, regions)
    for e in found:
        behind = (e.local is not None and e.upstream is not None
                  and e.upstream - e.local >= max_age())
        if not e.present and behind:
            logger.warning(
                "%s fixed links were parsed from the %s extract, %s behind Geofabrik's, and its "
                "raw file is gone, so it is not re-downloaded automatically; refresh it with "
                "OSM_REPLACE=1 scripts/osm_fixed_links.sh %s", e.region, e.local.date(),
                e.upstream - e.local, e.region)
        elif not e.present and e.local is None:
            logger.info("%s %s extract: not on disk, so not refreshed; the build reports it "
                        "missing (install it with its script)", e.region, e.kind)
        if e.stale:
            logger.info("%s %s extract: local %s, Geofabrik %s -- older than %s, re-extracting",
                        e.region, e.kind, e.local, e.upstream, max_age())
    full = [e.region for e in found if e.kind == "full" and e.stale]
    rail = [e.region for e in found if e.kind == "rail" and e.stale]
    if full:
        _run("osm_fixed_links.sh", full, extracts_dir)
    if rail:
        if shutil.which("osmium") is None:
            logger.warning(
                "rail extracts for %s are older than Geofabrik's by %s or more, and the osmium "
                "command-line tool is not installed here, so they cannot be re-filtered: run "
                "OSM_REPLACE=1 scripts/osm_rail.sh %s where it is and copy the results into %s. "
                "Building with the extracts on disk.",
                ", ".join(rail), max_age(), " ".join(rail), extracts_dir)
        else:
            _run("osm_rail.sh", rail, extracts_dir)
    if full or rail:
        ups = {e.region: e.upstream for e in found}
        found = [_local(extracts_dir, e.region, e.kind, ups[e.region]) for e in found]
        # The scripts report a failed region and go on to the next, exiting 0;
        # the snapshot on disk is what says whether a refresh happened.
        behind = [f"{e.region} {e.kind}" for e in found if e.stale]
        if behind:
            logger.warning("still older than Geofabrik's after the refresh, so built as they are: "
                           "%s", ", ".join(behind))
    _record(found)
    return found


def _record(found: list[Extract]) -> None:
    for e in found:
        _fetch.record(f"geofabrik:{e.region}-{e.kind}", {
            "snapshot": e.local.isoformat() if e.local else None,
            "upstream": e.upstream.isoformat() if e.upstream else None,
        })


def adopt(new: pathlib.Path, legacy: pathlib.Path) -> None:
    """Rename a derived cache from its pre-G2 key to its current one.

    The OSM caches used to key each extract on (name, size, mtime) and now key
    it on (name, size, snapshot). An old cache whose key matches the file on
    disk today was built from exactly that file -- same name, same size, never
    touched since -- so it is the same answer under a better name, and
    re-parsing (hours, for the fixed links) to rediscover it would be waste.
    """
    if new != legacy and not new.exists() and legacy.exists():
        os.replace(legacy, new)
        logger.info("adopted %s as %s (same extract, keyed by its snapshot now)",
                    legacy.name, new.name)


def stamp(dt: datetime) -> str:
    """A snapshot as it appears in a cache name."""
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
