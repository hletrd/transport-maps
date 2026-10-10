"""scripts/h200_rebuild.sh: the rebuild launcher keeps what rebuilds 27-28 learned."""

from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "h200_rebuild.sh").read_text()
CODE = "\n".join(ln for ln in SCRIPT.splitlines() if not ln.lstrip().startswith("#"))


def test_a_new_rebuild_never_trusts_another_builds_records():
    """TRANSPORT_MAPS_RESUME_TRUST_RECORDS accepts any intact record whatever
    it was built from; a rebuild started with it would skip every origin and
    republish the previous build. The launcher clears it.

    Mutation performed and reverted: `unset` replaced by `export ...=1` -> red.
    """
    assert "TRANSPORT_MAPS_RESUME_TRUST_RECORDS=1" not in CODE
    assert "unset TRANSPORT_MAPS_RESUME_TRUST_RECORDS" in CODE
    assert "--skip-existing" in CODE


def test_no_numa_pinning_and_the_thread_caps_stay():
    """--preferred=0 cost remote-memory workers ~20% (17.0 against 14.2 min);
    the thread caps are what keep the shared 8,192 pids from running out."""
    assert "numactl" not in CODE
    for cap in ("TIPPECANOE_MAX_THREADS=2", "POLARS_MAX_THREADS=1", "OMP_NUM_THREADS=1"):
        assert cap in CODE
    assert "pids_headroom" in CODE[CODE.index("start() {"):]


def test_inputs_are_checked_once_and_every_checkout_reads_that_snapshot():
    """G2: inputs checked on every build -- once, online, before four builds
    run --offline; each variant checkout mirrors the full tree's cache, or a
    cp -al copy made for an earlier build keeps the old inputs.

    Mutation performed and reverted: the cache rsync removed -> red.
    """
    start = CODE[CODE.index("start() {"):CODE.index("records_of() {")]
    assert "transport-maps inputs" in start
    assert start.index("transport-maps inputs") < start.index("checkouts")
    assert "--offline" in start
    co = CODE[CODE.index("checkouts() {"):CODE.index("pids_headroom() {")]
    assert '--link-dest="$W/repo/data/cache/" "$W/repo/data/cache/" "$W/$t/data/cache/"' in co


def test_a_leftover_edit_in_a_variant_checkout_does_not_stop_the_start():
    """Rebuild 29's first start stopped on rebuild 28's hot-patches; the
    launcher's own checkouts are moved by force, saying what it discards."""
    co = CODE[CODE.index("checkouts() {"):CODE.index("pids_headroom() {")]
    assert 'checkout -q -f --detach "$head"' in co
    assert co.index("status --short") < co.index("checkout -q -f")
