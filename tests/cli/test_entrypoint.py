"""`python -m transport_maps.cli` must actually run.

Without a `__main__` guard the module imports, does nothing and exits 0 -- a
build that silently performs no work while reporting success. That is the
worst possible failure mode for a pipeline invoked from a shell script, so it
gets a test rather than a comment.
"""

import subprocess
import sys


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "transport_maps.cli", *args],
        capture_output=True, text=True, timeout=120,
    )


def test_module_invocation_reaches_the_argument_parser():
    # --help is served by argparse, so this proves main() ran without needing
    # any data files present.
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    assert "build-all" in r.stdout, f"parser never ran; stdout was {r.stdout!r}"


def test_module_invocation_rejects_an_unknown_subcommand():
    """Exit 0 on nonsense is exactly the silent-success bug this guards."""
    r = _run("not-a-real-command")
    assert r.returncode != 0, "unknown subcommand exited 0"


def test_no_subcommand_is_an_error_not_a_silent_success():
    r = _run()
    assert r.returncode != 0, "bare invocation exited 0 having done nothing"
