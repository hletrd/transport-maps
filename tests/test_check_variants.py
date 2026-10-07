"""scripts/check_variants.py: no avoid-a-mode map faster than the full map."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_variants", ROOT / "scripts" / "check_variants.py")
check_variants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_variants)


def _dist(tmp_path: Path, full: list[int], variant: list[int]) -> Path:
    d = tmp_path / "dist"
    (d / "origins").mkdir(parents=True)
    (d / "v" / "no-air" / "origins").mkdir(parents=True)
    (d / "index.json").write_text(json.dumps({"origins": [{"slug": "seoul"}],
                                              "variants": [{"exclude": "air"}]}))
    for suffix in check_variants.SUFFIXES:
        np.asarray(full, dtype="<u2").tofile(d / "origins" / f"seoul{suffix}")
        np.asarray(variant, dtype="<u2").tofile(d / "v" / "no-air" / "origins" / f"seoul{suffix}")
    return d


def test_a_variant_that_is_never_faster_passes(tmp_path):
    assert check_variants.check(_dist(tmp_path, [10, 20, 65535], [10, 25, 65535])) == []


def test_a_single_faster_cell_fails_and_is_named(tmp_path):
    """Mutation performed and reverted: `var < full` made `var > full` -> red."""
    problems = check_variants.check(_dist(tmp_path, [10, 20, 30], [10, 19, 30]))
    assert len(problems) == 2, problems
    assert all("1 cells in 1 origins" in p and "worst 1 min at seoul" in p for p in problems)


def test_unreachable_in_the_full_map_but_reached_in_a_variant_fails(tmp_path):
    problems = check_variants.check(_dist(tmp_path, [65535], [400]))
    assert problems and "worst 65135 min" in problems[0]


def test_a_length_mismatch_is_reported_not_compared(tmp_path):
    problems = check_variants.check(_dist(tmp_path, [10, 20], [10]))
    assert problems and "1 cells against the full map's 2" in problems[0]
