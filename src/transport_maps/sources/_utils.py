"""Shared utilities for sources modules."""

import os
import pathlib
import tempfile
from collections.abc import Callable


def _atomic_write(path: pathlib.Path, write_fn: Callable[[pathlib.Path], None]) -> None:
    """Write via a same-directory temp file, then atomically replace `path`.

    `write_fn` receives the temp file's path and must write the full content
    to it. Same-directory rename is atomic on POSIX, so a process killed
    mid-write can never leave a truncated file at `path` for the next run's
    `.exists()` check to mistake for a complete, valid cache entry.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp_path = pathlib.Path(tmp_name)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
