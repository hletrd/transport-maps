"""Atomic file writes and cache-key hashing, shared by every layer.

Every artifact under dist/ and every derived cache is written through
`atomic_write`: the content goes to a same-directory temp file that is
renamed over the target, so a process killed mid-write (a worker stopped by
Pool.terminate, a signal, an OOM kill) can never leave a truncated file for a
`.exists()` check or the deploy gate to mistake for a complete one. The rename
is atomic on POSIX, including the NFS mount this repo lives on, because the
temp file is in the target's own directory.
"""

import hashlib
import json
import os
import pathlib
import tempfile
from collections.abc import Callable

# Public artifacts and caches: readable by the web server and by other users.
ARTIFACT_MODE = 0o644


def atomic_write(path: pathlib.Path, write_fn: Callable[[pathlib.Path], None],
                 mode: int = ARTIFACT_MODE) -> None:
    """Call `write_fn(tmp)` on a same-directory temp file, then replace `path`.

    `write_fn` must write the full content to the path it is given. On any
    failure the temp file is removed and the target is left untouched.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp_path = pathlib.Path(tmp_name)
    try:
        write_fn(tmp_path)
        # mkstemp creates 0600 and os.replace preserves it; a web server
        # serving dist/ answers 403 for such a file, which is how the
        # gazetteer once shipped invisible.
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_bytes(path: pathlib.Path, data: bytes) -> None:
    atomic_write(path, lambda tmp: tmp.write_bytes(data))


def write_text(path: pathlib.Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write(path, lambda tmp: tmp.write_text(text, encoding=encoding))


def params_hash(*values, length: int = 8) -> str:
    """Short stable digest of the constants that govern a derived cache.

    Derived caches keyed on a bare `.exists()` short-circuit on the file built
    under the OLD value of a constant: the change silently never takes effect
    and every test still passes against the stale artifact. Stamping this
    into the filename turns that into a cache MISS (CLAUDE.md testing rule).

    Values are serialised with `json.dumps(..., sort_keys=True)`, so dict
    order does not affect the digest but any change of value does.
    """
    payload = json.dumps(values, sort_keys=True, default=repr)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
