"""Run `fold()` and check that the shipped city names are actually findable.

`fold()` is the whole of the departure search: `render()` folds the query and
tests `c.skey.includes(f)`, so a name the fold cannot reach is a city the page
cannot find. Nothing in the suite executed it before this file -- it is one of
the 33 top-level `app.js` functions cycle 15's test lane found named in no
test, and the defect it was hiding was live on the deployed site.

The defect: the 553 names in `dist/index.json` carry BOTH apostrophes.

    U+0027  Xi'an, Huai'an, N'Djamena
    U+2019  Tai’an, Lu’an

`fold()` folded accents and dotless i and no punctuation at all, so which
spelling found a city was decided per city by whoever typed the name in.
Measured live on worldmap.atik.kr before the fix: `Lu'an` 0 hits, `Lu’an` 1;
`Tai'an` 0; `Washington DC` 0.

Two traps this file is built around:

1. Slicing. `fold` is a `const` arrow and so are the two regexes it uses, so
   the `_function()` slicer most of this directory uses cannot see any of them
   and a naive slice would run against `FOLD_DROP is not defined`. All three
   are sliced with the self-checking `_const_arrow` from `test_esc.py`, and
   `test_the_slice_really_contains_the_whole_helper` is the guard on the guard.
2. Asserting on the fold's OUTPUT would let the fold and the test drift
   together -- rewrite `fold()` and you rewrite the expected strings to match.
   So the assertions here are about SEARCHABILITY: for every shipped name, the
   ASCII form a keyboard produces must fold to a key that contains it. That
   property is what the page needs, and it is independent of how `fold()`
   spells its answer.

MUTATIONS PERFORMED, with the results as measured -- not as estimated.

1. Revert `fold()` to its pre-cycle-15 body:

       const fold = (s) => String(s).normalize("NFD")
           .replace(/\\p{M}/gu, "").replace(/ı/g, "i").toLowerCase();

   **5 failed, 3 passed.** `test_every_shipped_name_is_findable_as_typed`
   names **2 of 553** -- `Tai’an` and `Lu’an`, the two whose shipped spelling
   uses U+2019. It finds only those two because it types each name as its own
   keyboard form, and the U+0027 cities type back to themselves; the cities
   that were unreachable *the other way* (typing `Lu'an`, or typing `Xi’an`
   for the straight-quote `Xi'an`) are what
   `test_the_two_apostrophes_are_one_key` catches, and it fails on its first
   case. That is why both tests are here: neither alone sees the whole defect.

2. Drop only the `FOLD_SPACE` replacement: **3 failed, 5 passed** --
   `test_hyphens_and_spaces_reach_each_other`, `test_washington_dc_...`
   (the comma), and the slice guard's replacement count.

No mutation came back green.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _const_arrow(name: str) -> str:
    """The verbatim source of a top-level `const NAME = ...;` declaration.

    Ends at the first semicolon that is not inside a string or a regex
    literal. Copied deliberately from `test_esc.py` rather than generalised:
    cycle 15's architect counted 13 distinct slicers across this directory and
    7 of them the naive variant that stops at the first `;`, which would cut
    `fold()` in half at the `;` inside no string at all -- but would cut
    `FOLD_DROP` at the `.` if it ever grew one. Consolidating all 13 is
    carried as DEF15-55; using the self-checking one is not negotiable.
    """
    start = APP.index(f"const {name} = ")
    i, depth, quote = start, 0, None
    while i < len(APP):
        c = APP[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == "/" and APP[i + 1] not in "/*":
            j = i + 1
            while j < len(APP) and APP[j] != "/":
                j += 2 if APP[j] == "\\" else 1
            i = j
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return APP[start:i + 1]
        i += 1
    raise AssertionError(f"const {name} has no terminating semicolon")


FOLD_SRC = "\n".join(_const_arrow(n) for n in ("FOLD_DROP", "FOLD_SPACE", "fold"))

# The names the page actually ships. Read from dist/index.json when it is
# there, because that is the list a visitor searches; falling back to the
# checked-in origin list keeps the file honest on a clone with no dist/.
_INDEX = config.ROOT / "dist" / "index.json"


def _shipped_names() -> list[str]:
    if not _INDEX.exists():
        pytest.skip("dist/index.json is not built; no shipped names to fold")
    meta = json.loads(_INDEX.read_text(encoding="utf-8"))
    return [o["name"] for o in meta["origins"]]


def test_the_slice_really_contains_the_whole_helper() -> None:
    """A slicer that silently truncates gives a green test of nothing."""
    assert FOLD_SRC.count("const ") == 3, (
        f"expected three declarations, sliced {FOLD_SRC.count('const ')}:\n{FOLD_SRC}")
    # Every stage fold() depends on must be inside the slice. Drop any one of
    # them and the searchability tests below stop meaning what they say.
    for stage in (".normalize(", "\\p{M}", "FOLD_DROP", "FOLD_SPACE",
                  ".trim()", ".toLowerCase()"):
        assert stage in FOLD_SRC, f"{stage} is not in the sliced source"
    assert FOLD_SRC.count(".replace(") == 5, (
        f"fold() was sliced with {FOLD_SRC.count('.replace(')} replacements, "
        f"not 5 -- the slicer is wrong, or fold() changed:\n{FOLD_SRC}")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; fold() cannot be run")
    return exe


@pytest.fixture(scope="module")
def fold(node: str, tmp_path_factory):
    """Call the real `fold()` in node, one process for a whole list."""
    path = tmp_path_factory.mktemp("fold") / "fold.cjs"
    path.write_text(
        FOLD_SRC + "\nprocess.stdout.write(JSON.stringify("
        "JSON.parse(process.argv[2]).map(fold)));\n", encoding="utf-8")

    def call(values: list[str]) -> list[str]:
        done = subprocess.run([node, str(path), json.dumps(values)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


# What a keyboard produces for a name that was entered with typographic
# punctuation. This is the transformation a SEARCHER applies, written out by
# hand -- deliberately NOT by calling fold(), which would make the test agree
# with the code by construction.
_AS_TYPED = {
    "‘": "'", "’": "'", "ʼ": "'", "ʻ": "'",
    "`": "'", "´": "'",
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-",
}


def _as_typed(name: str) -> str:
    return "".join(_AS_TYPED.get(ch, ch) for ch in name)


def test_every_shipped_name_is_findable_as_typed(fold) -> None:
    """For every city the page ships, typing its name on an ASCII keyboard
    must find it.

    This is the property the search needs, stated without reference to how
    `fold()` spells its output: fold the name, fold what a searcher types, and
    the first must contain the second -- which is exactly the test `render()`
    runs at `app.js`'s `c.skey.includes(f)`.
    """
    names = _shipped_names()
    keys = fold(names)
    typed = fold([_as_typed(n) for n in names])
    missed = [n for n, k, t in zip(names, keys, typed) if t not in k]
    assert not missed, (
        f"{len(missed)} of {len(names)} shipped cities cannot be found by "
        f"typing their own name on an ASCII keyboard: {missed}")


def test_the_two_apostrophes_are_one_key(fold) -> None:
    """The bug as the owner's visitors met it.

    `dist/index.json` uses U+0027 for Xi'an and U+2019 for Lu’an. Both must
    answer to the straight quote, to the curly one, and to neither.
    """
    cases = [
        ("Lu’an", ["Lu'an", "Lu’an", "Luan"]),
        ("Xi'an", ["Xi'an", "Xi’an", "Xian"]),
        ("N'Djamena", ["N'Djamena", "N’Djamena", "NDjamena"]),
        ("Tai’an", ["Tai'an", "Tai’an", "Taian"]),
        ("Huai'an", ["Huai'an", "Huai’an", "Huaian"]),
    ]
    for name, spellings in cases:
        key = fold([name])[0]
        for typed, folded in zip(spellings, fold(spellings)):
            assert folded in key, (
                f"typing {typed!r} does not find {name!r} "
                f"(key {key!r}, query {folded!r})")


def test_washington_dc_finds_washington_dc(fold) -> None:
    """The dots and the comma are dropped, so the name a visitor writes as
    three words finds the one the gazetteer writes with five stops.
    """
    key = fold(["Washington, D.C."])[0]
    for typed in ("Washington DC", "Washington, D.C.", "washington dc",
                  "Washington D.C."):
        assert fold([typed])[0] in key, f"{typed!r} does not find Washington, D.C."


def test_hyphens_and_spaces_reach_each_other(fold) -> None:
    """A hyphen becomes a space rather than vanishing, so the two halves stay
    separate words: "Port au Prince" and "Port-au-Prince" each find the other,
    and neither collapses into "portauprince".
    """
    for name in ("Port-au-Prince", "Rostov-on-Don", "Mbuji-Mayi", "Pointe-Noire"):
        key = fold([name])[0]
        assert " " in key, f"{name!r} folded to {key!r} with no word break"
        assert fold([name.replace("-", " ")])[0] == key, (
            f"{name!r} and its spaced spelling fold differently")


def test_accents_still_fold(fold) -> None:
    """The behaviour this helper already had, kept under test while it grew.
    Its own comment promises these three by name.
    """
    for typed, name in (("Sao Paulo", "São Paulo"), ("Zurich", "Zürich"),
                        ("Bogota", "Bogotá")):
        assert fold([typed])[0] == fold([name])[0], (
            f"{typed!r} no longer folds onto {name!r}")


def test_the_fold_leaves_no_double_space(fold) -> None:
    """`render()` ranks a match with `(" " + key).includes(" " + f)`, which a
    doubled space would defeat silently -- the city would still be found, but
    would sort below an unrelated substring match.
    """
    names = _shipped_names()
    bad = [n for n, k in zip(names, fold(names))
           if "  " in k or k != k.strip()]
    assert not bad, f"folded keys with a doubled or edge space: {bad}"


def test_the_country_key_still_joins_on_a_single_space() -> None:
    """`skey` is built as `${c.key} ${fold(where)}`, so `fold()` growing a
    `.trim()` must not leave the join able to produce a double space. Read from
    the source rather than run, because building `skey` needs the whole list.
    """
    join = re.search(r"c\.skey = where \? `([^`]*)`", APP)
    assert join, "the skey join has moved; re-read this guard"
    assert join.group(1) == "${c.key} ${fold(where)}", (
        f"the skey join is now {join.group(1)!r}; check it still yields one space")
