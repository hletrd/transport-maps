"""scripts/h200_split.py: the records arithmetic behind h200_rebuild.sh split."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("h200_split", ROOT / "scripts" / "h200_split.py")
split = importlib.util.module_from_spec(spec)
spec.loader.exec_module(split)

SLUGS = ["a", "b", "c", "d", "e", "f"]
IH, GH = "in1", "gr1"


def _record(tree: Path, which: str, slug: str, *, state="complete", inputs=IH, graph=GH):
    d = split.map_dir(tree, which)
    (d / ".progress").mkdir(parents=True, exist_ok=True)
    (d / "origins").mkdir(parents=True, exist_ok=True)
    files = [f"{slug}.bin", f"{slug}.pmtiles"]
    for f in files:
        (d / "origins" / f).write_text(f"{tree.name}:{f}")
    (d / ".progress" / f"{slug}.json").write_text(json.dumps(
        {"slug": slug, "state": state, "inputsHash": inputs, "graphHash": graph, "files": files}))


def test_only_this_builds_complete_records_count(tmp_path):
    """The previous build's complete records stay on disk until redone; a
    record counts only with this build's inputs and graph hashes.

    Mutation performed and reverted: the graphHash test dropped from
    `complete` -> red.
    """
    main = tmp_path / "repo"
    _record(main, "full", "a")
    _record(main, "full", "b", graph="old")
    _record(main, "full", "c", inputs="old")
    _record(main, "full", "d", state="writing")
    assert split.main(["todo", "full", str(main), IH, GH], SLUGS) == "b,c,d,e,f"


def test_lack_and_left_split_the_roster_at_the_tail(tmp_path):
    main, tail = tmp_path / "repo", tmp_path / "repo-rail"
    for s in ("a", "b", "c"):
        _record(main, "ferry", s)
    _record(tail, "ferry", "f")
    assert split.main(["lack", "ferry", str(main), str(tail), "3", IH, GH], SLUGS) == "0"
    assert split.main(["lack", "ferry", str(main), str(tail), "2", IH, GH], SLUGS) == "1"
    assert split.main(["left", "ferry", str(main), str(tail), "3", IH, GH], SLUGS) == "d,e"


def test_merge_copies_the_tails_origins_files_then_record(tmp_path):
    """Only the tail's complete, this-build origins that main lacks; files
    before the record, so no record names a missing file.

    Mutation performed and reverted: the `if slug in have: continue` dropped
    (main's own finished origin overwritten by the tail's) -> red.
    """
    main, tail = tmp_path / "repo", tmp_path / "repo-air"
    _record(main, "full", "a")
    _record(tail, "full", "a")
    _record(tail, "full", "e")
    _record(tail, "full", "f", graph="old")
    out = split.main(["merge", "full", str(main), str(tail), IH, GH], SLUGS)
    assert out.startswith("full: merged 1 origin(s)")
    d = split.map_dir(main, "full")
    assert (d / "origins" / "e.bin").read_text() == "repo-air:e.bin"
    assert json.loads((d / ".progress" / "e.json").read_text())["graphHash"] == GH
    assert (d / "origins" / "a.bin").read_text() == "repo:a.bin", "main's own origin kept"
    assert not (d / ".progress" / "f.json").exists(), "an old-graph record crossed over"
