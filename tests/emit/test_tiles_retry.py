"""tippecanoe that cannot start a thread is retried; anything else is not."""

import subprocess

import pytest

from transport_maps.emit import tiles


def _failing(times, stderr):
    calls = []

    def run(args, **kw):
        calls.append(args)
        if len(calls) <= times:
            raise subprocess.CalledProcessError(1, args, stderr=stderr)
        return subprocess.CompletedProcess(args, 0, "", "")
    return run, calls


def test_a_thread_failure_is_waited_out(monkeypatch):
    """h200, 2026-10-05: 'pthread_create: Resource temporarily unavailable'
    ended four builds. Mutation performed and reverted: raise on the first
    failure -> red."""
    run, calls = _failing(3, "  28.5%  1/1/0\\npthread_create: Resource temporarily unavailable\\n")
    monkeypatch.setattr(tiles.subprocess, "run", run)
    slept = []
    tiles._run_tippecanoe(["tippecanoe"], cwd=".", env={}, sleep=slept.append)
    assert len(calls) == 4 and slept == [30.0, 60.0, 90.0]


def test_any_other_failure_is_raised_at_once(monkeypatch):
    """Mutation performed and reverted: retry every failure -> red."""
    run, calls = _failing(1, "Unknown option --frobnicate\\n")
    monkeypatch.setattr(tiles.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        tiles._run_tippecanoe(["tippecanoe"], cwd=".", env={}, sleep=lambda s: None)
    assert len(calls) == 1


def test_an_operator_thread_cap_is_a_ceiling(monkeypatch):
    """The worker share (cores // workers) overwrote TIPPECANOE_MAX_THREADS=2.
    Mutation performed and reverted: ignore the environment -> red."""
    monkeypatch.setattr(tiles.os, "cpu_count", lambda: 192)
    monkeypatch.delenv("TIPPECANOE_MAX_THREADS", raising=False)
    assert tiles._threads(24) == {"TIPPECANOE_MAX_THREADS": "8"}
    monkeypatch.setenv("TIPPECANOE_MAX_THREADS", "2")
    assert tiles._threads(24) == {"TIPPECANOE_MAX_THREADS": "2"}
    monkeypatch.setenv("TIPPECANOE_MAX_THREADS", "64")
    assert tiles._threads(24) == {"TIPPECANOE_MAX_THREADS": "8"}
