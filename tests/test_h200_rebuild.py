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
