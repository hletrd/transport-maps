"""Per-origin completion records: which build wrote an origin's files, and
whether it finished writing them.

A build rewrites dist/ in place, origin by origin. Every file is atomic on its
own (`_io.atomic_write`), but an origin is nine files, and a build stopped
between two of them -- a gate failing in another worker terminates the pool,
the OOM killer, a reboot -- left an origin half new and half old. Every check
that existed passed it: the fixed-width arrays are the same length whichever
build wrote them, and the node-universe fingerprint lives in the one file, the
.json, that the dead build may not have reached. A variant build died that way
two thirds through on 2026-09-28, and the only safe restart was all of it.

So each origin carries a record, `<root>/.progress/<slug>.json`:

  * written as "writing" BEFORE the origin's first file is replaced, and as
    "complete" -- with every file's size -- only AFTER its last one. A record
    that still says "writing" is an origin a build stopped inside, and
    scripts/check_dist.py refuses it.
  * keyed on `Stamp.key`: the run's inputsHash (code, calibration, origins,
    format constants -- emit.index.build_identity), a digest of the graph it
    solved on (every data input lands there), the excluded mode and the
    origin's own row. `build-all --skip-existing` trusts a record only under
    the CURRENT key and only while every file it lists is still there at the
    recorded size; anything else is rebuilt.

Out of the served tree on purpose: a dot-directory, which the deploy's rsync
filter (`.*`, and `.progress/` by name) never copies and the page never asks
for. The records describe the build machine's dist/, not the site.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pickle
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from transport_maps import _io

DIRNAME = ".progress"
#: Every file `cli._solve_one` writes for an origin, as suffixes of its slug.
#: A record must list exactly these: one written by code that wrote fewer is
#: not a complete origin for code that writes more.
SUFFIXES = (".pmtiles", ".bin", ".r6.bin", ".over.bin", ".json", ".air.bin",
            ".modes.bin", ".rail.bin", ".rail.json")
COMPLETE = "complete"
WRITING = "writing"


def graph_hash(csr, hover_parents, cell_class, rail_tables) -> str:
    """Digest of what every origin is solved on and written against.

    inputsHash is sampled before the graph exists, so it can name the code and
    the hand-edited files but not the data: routes.parquet, the OSM extracts,
    GRIP4 and the land mask all enter through here instead. The edge arrays
    carry every weight; the hover ordering is what every array is indexed by;
    the cell classes go into .modes.bin and the rail tables into .rail.json
    without passing through an edge. About a second per GB of graph, once.
    """
    # Canonical forms, not as-built ones (2026-10-05): rebuild 28's two starts
    # on h200 read the same inputs with the same code and produced the same
    # 115 origins to the kilobyte, yet hashed ec7cc57f... and 0a0f2fba..., so
    # --skip-existing resumed nothing. Edges within a row land in whatever
    # order assembly reached them, and a set of strings pickles in a different
    # order in every process (PYTHONHASHSEED). Sorting the row indices on a
    # copy, and serialising the rail tables with sets and dict keys sorted,
    # leaves the graph alone and makes the digest a property of its content.
    csr = csr.copy()
    csr.sum_duplicates()
    csr.sort_indices()
    h = hashlib.sha256(repr(tuple(csr.shape)).encode())
    for arr in (csr.indptr, csr.indices, csr.data, np.asarray(cell_class)):
        arr = np.ascontiguousarray(arr)
        h.update(f"{arr.dtype.str}{arr.shape}".encode())
        # memoryview, not tobytes(): a copy of a gigabyte of edges in the
        # parent is a gigabyte every forked worker would inherit.
        h.update(memoryview(arr.reshape(-1).view(np.uint8)))
    h.update("\n".join(hover_parents).encode())
    h.update(pickle.dumps(_canonical(rail_tables), protocol=5))
    return h.hexdigest()[:16]


def _canonical(obj):
    """`obj` with every set and dict in a fixed order (see graph_hash)."""
    if isinstance(obj, dict):
        return tuple(sorted(((repr(k), _canonical(v)) for k, v in obj.items()),
                            key=lambda kv: kv[0]))
    if isinstance(obj, (set, frozenset)):
        return tuple(sorted((_canonical(v) for v in obj), key=repr))
    if isinstance(obj, (list, tuple)):
        return tuple(_canonical(v) for v in obj)
    if isinstance(obj, np.ndarray):
        return (obj.dtype.str, obj.shape, obj.tobytes())
    return obj


@dataclasses.dataclass(frozen=True)
class Stamp:
    """One run's identity as the records see it."""
    inputs_hash: str
    build_id: str
    graph_hash: str
    exclude: str | None

    @classmethod
    def of(cls, identity: dict, graph: str, exclude: str | None) -> Stamp:
        return cls(str(identity.get("inputsHash", "")), str(identity.get("buildId", "")),
                   graph, exclude)

    def key(self, origin: dict) -> str:
        return _io.params_hash(self.inputs_hash, self.graph_hash, self.exclude,
                               origin["slug"], float(origin["lat"]), float(origin["lon"]),
                               length=16)


def record_path(root: Path, slug: str) -> Path:
    return Path(root) / DIRNAME / f"{slug}.json"


def read(root: Path, slug: str) -> dict | None:
    """The record, None when there is none, or state "unreadable"."""
    path = record_path(root, slug)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "unreadable"}
    return rec if isinstance(rec, dict) else {"state": "unreadable"}


def _write(root: Path, slug: str, stamp: Stamp, origin: dict, state: str,
           files: dict[str, int] | None) -> None:
    payload = {"slug": slug, "state": state, "key": stamp.key(origin),
               "inputsHash": stamp.inputs_hash, "graphHash": stamp.graph_hash,
               "exclude": stamp.exclude, "buildId": stamp.build_id,
               "at": datetime.now(UTC).replace(microsecond=0).isoformat()}
    if files is not None:
        payload["files"] = files
    _io.write_text(record_path(root, slug), json.dumps(payload, indent=1))


def begin(root: Path, origin: dict, stamp: Stamp) -> None:
    """Mark the origin as being rewritten. Call before its first file."""
    _write(root, origin["slug"], stamp, origin, WRITING, None)


def finish(root: Path, origin: dict, stamp: Stamp) -> None:
    """Record the origin complete, with its files' sizes. Call after its last.

    A file the build should have written and did not is an error here, not a
    record listing fewer files.
    """
    slug = origin["slug"]
    out = Path(root) / "origins"
    files = {f"{slug}{s}": (out / f"{slug}{s}").stat().st_size for s in SUFFIXES}
    _write(root, slug, stamp, origin, COMPLETE, files)


def files_problem(root: Path, rec: dict) -> str | None:
    """Why a complete record's files are no longer the ones it recorded."""
    out = Path(root) / "origins"
    for name, size in sorted((rec.get("files") or {}).items()):
        p = out / name
        if not p.exists():
            return f"{name} is missing"
        if p.stat().st_size != size:
            return f"{name} is {p.stat().st_size:,} bytes, recorded {size:,}"
    return None


#: Operator override: trust a complete record for this origin and variant
#: whatever inputs and graph digests it carries -- the operator asserts the
#: outputs would be the same. For records written before graph_hash was made
#: canonical: rebuild 28's restart on h200, where the two starts matched on all
#: 115 origins compared, and the code changed between them only in ways that
#: write nothing (the huge-page setting, this digest). Files must still be
#: intact at their recorded sizes; a half-written origin is never trusted.
TRUST_RECORDS_ENV = "TRANSPORT_MAPS_RESUME_TRUST_RECORDS"


def _accepted_other_graph(rec: dict, origin: dict, stamp: Stamp) -> bool:
    if os.environ.get(TRUST_RECORDS_ENV) != "1":
        return False
    theirs = dataclasses.replace(stamp, inputs_hash=str(rec.get("inputsHash", "")),
                                 graph_hash=str(rec.get("graphHash", "")))
    return rec.get("key") == theirs.key(origin)


def problem(root: Path, origin: dict, stamp: Stamp) -> str | None:
    """Why this origin's files cannot be trusted as this run's, or None.

    None only for a complete record under the current key that lists every
    file of SUFFIXES, each still at its recorded size.
    """
    slug = origin["slug"]
    rec = read(root, slug)
    if rec is None:
        return "no completion record"
    if rec.get("state") != COMPLETE:
        return f"a build stopped while writing it ({rec.get('buildId', 'record unreadable')})"
    if rec.get("key") != stamp.key(origin) and not _accepted_other_graph(rec, origin, stamp):
        return f"built from other inputs (inputsHash {rec.get('inputsHash')}, " \
               f"graph {rec.get('graphHash')})"
    if set(rec.get("files") or {}) != {f"{slug}{s}" for s in SUFFIXES}:
        return "its record lists a different set of files"
    return files_problem(root, rec)
