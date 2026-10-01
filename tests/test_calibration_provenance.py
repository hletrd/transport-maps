"""Every table in calibration.toml says whether it is fitted or a default.

CLAUDE.md's modelling rule: each calibration constant carries a comment saying
whether it is FITTED (and against what) or a published-figure default. Nothing
enforced that, and the file shipped seven unlabelled tables and three comments
describing refits that never happened. tomllib discards comments, so this reads
the raw text and checks the comment block immediately above every table header
for one of the two labels.

"Immediately above" is the run of contiguous `#` lines ending at the header,
with at most one blank line between that run and the header. A label buried
further up, or inside the table after the header, does not count: the point is
that a reader who jumps to a header sees its provenance without searching.
"""

import re
import tomllib

from transport_maps import config

CALIBRATION = config.ROOT / "calibration.toml"
LABEL = re.compile(r"fitted|published-figure default", re.IGNORECASE)
# `[table]` or `[a.b]`, not `[[array]]`.
HEADER = re.compile(r"^\[([^\[\]]+)\]\s*$")
# [meta] records the provenance of the airborne fit (source, sample size,
# hold-out error); it holds no constant the model applies, so it carries no
# label of its own.
EXEMPT = {"meta"}


def _tables_from_toml(data: dict, prefix: str = "") -> set[str]:
    """Every table path tomllib sees, to check the header regex against."""
    found: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            path = f"{prefix}{key}"
            found.add(path)
            found |= _tables_from_toml(value, f"{path}.")
    return found


def _comment_block_above(lines: list[str], i: int) -> str:
    j = i - 1
    if j >= 0 and lines[j].strip() == "":
        j -= 1
    block: list[str] = []
    while j >= 0 and lines[j].lstrip().startswith("#"):
        block.append(lines[j])
        j -= 1
    return "\n".join(reversed(block))


def unlabelled_tables(text: str) -> list[str]:
    """Table headers with no fitted/published-figure label immediately above."""
    lines = text.splitlines()
    missing = []
    for i, line in enumerate(lines):
        m = HEADER.match(line)
        if not m or m.group(1).strip() in EXEMPT:
            continue
        if not LABEL.search(_comment_block_above(lines, i)):
            missing.append(f"[{m.group(1).strip()}] (line {i + 1})")
    return missing


def test_header_regex_sees_every_table_tomllib_sees():
    """The regex is the whole check; if it missed a header the test could pass
    on an unlabelled table. Pin it to tomllib's view of the same file."""
    text = CALIBRATION.read_text(encoding="utf-8")
    from_regex = {
        m.group(1).strip() for line in text.splitlines() if (m := HEADER.match(line))
    }
    assert from_regex == _tables_from_toml(tomllib.loads(text))
    assert {"airborne", "frequency", "rail", "ferry", "land_border"} <= from_regex


def test_every_calibration_table_is_labelled_fitted_or_default():
    text = CALIBRATION.read_text(encoding="utf-8")
    missing = unlabelled_tables(text)
    assert not missing, (
        "calibration.toml tables with no 'fitted' / 'published-figure default' "
        "label in the comment block immediately above the header: "
        + ", ".join(missing)
    )


def test_label_must_sit_immediately_above_the_header():
    """The rule as applied to the real file, spelled out on a toy one."""
    ok = "# Hand-fitted to two anchors.\n[a]\nx = 1\n\n# Published-figure default.\n\n[b]\ny = 2\n"
    assert unlabelled_tables(ok) == []

    no_comment = "[a]\nx = 1\n"
    assert unlabelled_tables(no_comment) == ["[a] (line 1)"]

    label_after_header = "[a]\n# Published-figure default.\nx = 1\n"
    assert unlabelled_tables(label_after_header) == ["[a] (line 1)"]

    label_two_blanks_up = "# FITTED against something.\n\n\n[a]\nx = 1\n"
    assert unlabelled_tables(label_two_blanks_up) == ["[a] (line 4)"]

    unrelated_comment = "# Fitted elsewhere.\ny = 0\n# Explains the table.\n[a]\nx = 1\n"
    assert unlabelled_tables(unrelated_comment) == ["[a] (line 4)"]

    dotted = "# Published-figure defaults; not fitted.\n[a.b]\nx = 1\n"
    assert unlabelled_tables(dotted) == []
    assert unlabelled_tables("[meta]\ncalibrated = true\n") == []


# --- cycle 7: the claim the DOCUMENTS make, not only calibration.toml --------
#: Every file that describes the road model to a reader. `graph/ground.py`
#: says classes 1-4 are fitted and roadless and local keep published-figure
#: defaults; five of these said, in one way or another, that the whole model
#: was fitted to the 2,998 journeys. CLAUDE.md's calibration rule makes that a
#: correctness question, not a wording one: "prefer a documented, reproducible
#: error over a hidden one."
_ROAD_CLAIM_FILES = (
    "web/index.html",
    "web/llms.txt",
    "README.md",
)


def test_no_document_claims_the_whole_road_model_is_fitted():
    """Wherever the 2,998 journeys are named, the two defaults are named too.

    Mutation performed and reverted: restore "a road-speed model calibrated
    against 2,998 real driving journeys" in web/index.html -> red.
    """
    from transport_maps import config

    # The `continue` used to be `if "2,998" not in text: continue`, which made
    # the guard disarmable by the very edit it exists to catch: reprint the
    # sample count as "2998" or "about 3,000" and the file stops being checked.
    # README.md was already silently exempt for exactly that reason. Every file
    # in the list is now checked for a road-model claim by ANY spelling, and a
    # file that names none is reported rather than skipped.
    unchecked = []
    for rel in _ROAD_CLAIM_FILES:
        text = (config.ROOT / rel).read_text(encoding="utf-8")
        flat = " ".join(text.split())
        claims = re.search(
            r"(road[- ]speed model|road class|driving journeys|per-road-class)", flat, re.I)
        if not claims:
            unchecked.append(rel)
            continue
        assert "published-figure default" in flat, (
            f"{rel} cites the 2,998 sampled journeys without saying that two of the six "
            "road classes keep published-figure defaults, which graph/ground.py records "
            "and CLAUDE.md's calibration rule requires")
    assert not unchecked, (
        "these files are listed as making a road-model claim and no longer make "
        f"one in any spelling this guard recognises, so they are unchecked: {unchecked}")


def test_every_speed_in_the_mode_tooltips_says_which_it_is():
    """The six road-class sentences shipped in index.json are read out in the
    page's route tooltip. Each must say fitted or published-figure default.

    Mutation performed and reverted: drop "a published-figure default" from
    the "track" entry in emit/index.py -> red.
    """
    from transport_maps.emit import index

    detail = index.mode_detail()
    for mode in ("highway", "major road", "minor road", "track"):
        sentence = detail[mode]
        assert "fitted" in sentence or "published-figure default" in sentence, (
            f"the {mode!r} tooltip gives a speed with no provenance: {sentence!r}")
    # "minor road" and "track" are the two that carry a default; they must say
    # so rather than borrowing the word "fitted" from their neighbours.
    assert "published-figure default" in detail["minor road"]
    assert "published-figure default" in detail["track"]
    # And no sentence may print a backwards range.
    import re
    for mode, sentence in detail.items():
        for lo, hi in re.findall(r"(\d+)-(\d+) km/h", sentence):
            assert int(lo) <= int(hi), f"the {mode!r} tooltip prints a backwards range: {sentence!r}"


def test_the_rail_tooltip_names_the_heritage_tier_the_page_describes():
    """The methods page and llms.txt both describe a separate heritage tier;
    the tooltip left it out, so the three disagreed about the model (DEF16-3).
    Read off the calibration, not hard-coded.

    Mutation performed and reverted: drop the heritage clause from the rail
    sentence in emit/index.py -> red.
    """
    from transport_maps.emit import index
    from transport_maps.graph import rail

    heritage = rail.load_rail_calibration().tiers["tourism"].speed_kmh
    sentence = index.mode_detail()["rail"]
    assert f"{heritage:.0f} km/h for heritage" in sentence, sentence
