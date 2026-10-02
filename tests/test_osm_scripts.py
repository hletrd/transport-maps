"""scripts/osm_fixed_links.sh and scripts/osm_rail.sh, run for real against
stub `curl` and `osmium` executables (G2: OSM_REPLACE=1 is how a build
refreshes an extract, so it has to replace one -- and only a whole one).

The stubs serve state.txt, a HEAD with a Content-Length, and a body; they log
every URL asked for. Nothing leaves the machine.
"""

import os
import stat
import subprocess

import pytest

from transport_maps import config

SCRIPTS = config.ROOT / "scripts"
STATE = r"2026-10-01T20\:21\:30Z"
DATED = "https://download.geofabrik.de/asia-261001.osm.pbf"

CURL = r"""#!/usr/bin/env bash
out=""; head=0; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2; continue;;
    -C|--max-time|--limit-rate|--retry|--retry-delay|-w) shift 2; continue;;
    -fsSI|-fsSLI|-I) head=1;;
    http*) url="$1";;
  esac
  shift
done
echo "$url" >> "$STUB_LOG"
case "$url" in
  *state.txt) printf 'sequenceNumber=4931\ntimestamp=%s\n' "$STUB_STATE";;
  *) if [ "$head" = 1 ]; then
       printf 'HTTP/1.1 200 OK\r\nContent-Length: %s\r\n\r\n' \
         "${STUB_LENGTH:-$(wc -c < "$STUB_BODY" | tr -d ' ')}"
     elif [ -n "$out" ]; then cat "$STUB_BODY" > "$out"; fi;;
esac
"""

OSMIUM = r"""#!/usr/bin/env bash
[ -n "${STUB_OSMIUM_FAIL:-}" ] && exit 1
src=""; out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2; continue;;
    *.osm.pbf) [ -z "$src" ] && src="$1";;
  esac
  shift
done
{ printf 'filtered:'; cat "$src"; } > "$out"
"""


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("curl", CURL), ("osmium", OSMIUM)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    body = tmp_path / "body.pbf"
    body.write_bytes(b"new extract from geofabrik")
    osm = tmp_path / "osm"
    osm.mkdir()
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "OSM_DIR": str(osm),
            "STUB_LOG": str(tmp_path / "curl.log"), "STUB_STATE": STATE,
            "STUB_BODY": str(body)}


def _run(script, env, *regions, **extra):
    done = subprocess.run(["bash", str(SCRIPTS / script), *regions], env={**env, **extra},
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _asked(env):
    log = env["STUB_LOG"]
    return open(log).read().split() if os.path.exists(log) else []


def _osm(env):
    from pathlib import Path

    return Path(env["OSM_DIR"])


# --- osm_fixed_links.sh -------------------------------------------------------


def test_fixed_links_skips_a_present_extract_unless_told_to_replace(env):
    raw = _osm(env) / "asia.osm.pbf"
    raw.write_bytes(b"old extract")
    assert "[skip] asia" in _run("osm_fixed_links.sh", env, "asia")
    assert raw.read_bytes() == b"old extract" and _asked(env) == []


def test_fixed_links_replace_downloads_the_dated_file_over_the_old(env):
    """Mutation: keep the unconditional skip of a present raw -> red."""
    raw = _osm(env) / "asia.osm.pbf"
    raw.write_bytes(b"old extract")
    _run("osm_fixed_links.sh", env, "asia", OSM_REPLACE="1")
    assert raw.read_bytes() == b"new extract from geofabrik"
    assert (_osm(env) / "asia.osm.pbf.source").read_text().strip() == DATED
    assert DATED in _asked(env)


def test_fixed_links_replace_keeps_the_old_extract_when_the_size_is_wrong(env):
    """The size check stands: a short or spliced download never replaces a
    whole extract. Mutation: drop the length comparison -> red."""
    raw = _osm(env) / "asia.osm.pbf"
    raw.write_bytes(b"old extract")
    out = _run("osm_fixed_links.sh", env, "asia", OSM_REPLACE="1", STUB_LENGTH="999999")
    assert "[FAIL] asia" in out
    assert raw.read_bytes() == b"old extract"
    assert (_osm(env) / "asia.osm.pbf.part").exists(), "left as .part for a resume"


def test_fixed_links_replace_does_not_redownload_the_current_file(env):
    raw = _osm(env) / "asia.osm.pbf"
    raw.write_bytes(b"current extract")
    (_osm(env) / "asia.osm.pbf.source").write_text(DATED + "\n")
    assert "[ok  ] asia" in _run("osm_fixed_links.sh", env, "asia", OSM_REPLACE="1")
    assert raw.read_bytes() == b"current extract" and DATED not in _asked(env)


# --- osm_rail.sh --------------------------------------------------------------


def test_rail_skips_a_filtered_extract_unless_told_to_replace(env):
    out = _osm(env) / "asia-rail.osm.pbf"
    out.write_bytes(b"old rail")
    assert "[skip] asia" in _run("osm_rail.sh", env, "asia")
    assert out.read_bytes() == b"old rail"


def test_rail_replace_filters_a_present_full_extract_and_keeps_it(env):
    """The full extract belongs to the bridge parse: filtering it must not
    delete it, and must not download a second copy. Mutation: delete the raw
    unconditionally after the filter, as the script used to -> red."""
    raw = _osm(env) / "asia.osm.pbf"
    raw.write_bytes(b"full extract")
    (_osm(env) / "asia-rail.osm.pbf").write_bytes(b"old rail")
    _run("osm_rail.sh", env, "asia", OSM_REPLACE="1")
    assert (_osm(env) / "asia-rail.osm.pbf").read_bytes() == b"filtered:full extract"
    assert raw.read_bytes() == b"full extract"
    assert _asked(env) == []


def test_rail_downloads_the_dated_file_checks_its_size_and_drops_it(env):
    _run("osm_rail.sh", env, "asia", OSM_REPLACE="1")
    assert (_osm(env) / "asia-rail.osm.pbf").read_bytes() == b"filtered:new extract from geofabrik"
    assert not (_osm(env) / "asia.osm.pbf").exists(), "a raw it downloaded is deleted"
    assert DATED in _asked(env), "pinned to the dated file, not to -latest"
    out = _run("osm_rail.sh", env, "europe", OSM_REPLACE="1", STUB_LENGTH="1")
    assert "[FAIL] europe" in out and not (_osm(env) / "europe-rail.osm.pbf").exists()


def test_a_failed_filter_leaves_the_previous_rail_extract(env):
    (_osm(env) / "asia.osm.pbf").write_bytes(b"full extract")
    out_path = _osm(env) / "asia-rail.osm.pbf"
    out_path.write_bytes(b"old rail")
    out = _run("osm_rail.sh", env, "asia", OSM_REPLACE="1", STUB_OSMIUM_FAIL="1")
    assert "[FAIL] filter asia" in out
    assert out_path.read_bytes() == b"old rail"
    assert not list(_osm(env).glob("*.new.osm.pbf"))
