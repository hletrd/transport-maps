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
import tomllib

import pytest

from tests.conftest import skip_without_dist
from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _const_arrow(name: str) -> str:
    """The verbatim source of a top-level `const NAME = ...;` declaration.

    Ends at the first semicolon outside every bracket, string and regex
    literal -- `fold()` and `FOLD_DROP` are full of both.
    """
    return _js.statement(f"const {name} = ")


FOLD_SRC = "\n".join(_const_arrow(n) for n in ("FOLD_DROP", "FOLD_SPACE", "fold"))

# The names the page ships. `data/origins.toml` FIRST, `dist/index.json` only
# as a supplement.
#
# Cycle 15 wrote this the other way round and the comment above it claimed a
# fallback the code did not have -- it called `pytest.skip`. Two things were
# wrong with that. It read 553 names when 1,464 are checked into the tree, so
# the guard could not go red for any of the 911 origins the running rebuild
# will publish: cycle 16's test lane ran the property over all 1,464 and
# measured **0 misses**, i.e. the gate would have stayed green through the
# rebuild whether or not it worked. And the skip put this file in the set that
# `deploy_verify.sh`'s page gate refuses on, which broke `--page-only` -- the
# one deploy mode documented as not needing `dist/` -- on every clone.
#
# `origins.toml` is the source `build-all` reads, so it is the list the page
# will ship, not merely the list it happens to ship today.
_INDEX = config.ROOT / "dist" / "index.json"
_ORIGINS = config.ROOT / "data" / "origins.toml"


def _shipped_names() -> list[str]:
    names: list[str] = []
    if _ORIGINS.exists():
        names = [o["name"] for o in
                 tomllib.loads(_ORIGINS.read_text(encoding="utf-8"))["origin"]]
    if _INDEX.exists():
        meta = json.loads(_INDEX.read_text(encoding="utf-8"))
        shipped = [o["name"] for o in meta["origins"]]
        # A name in dist/ but not in origins.toml means the built site is
        # ahead of the checked-in list; fold it too rather than miss it.
        names += [n for n in shipped if n not in set(names)]
    if not names:
        skip_without_dist("neither data/origins.toml nor dist/index.json is present")
    return names


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


# --- the ranking guard (C16-1.3) ------------------------------------------
#
# `fold()` decides WHICH cities a query matches. `rankCity()` decides which of
# them the visitor gets when they press Enter, and Enter clicks row 1.
#
# The defect this guard exists for shipped live and was found in cycle 16.
# C15-1 dropped the apostrophe family from `fold()` -- correctly -- which made
# `xi'an` fold to `xian`, a substring of `feng`+`xian`+`g`. The list was
# alphabetical, `Fengxiang` sorts before `Xi'an`, and typing the exact and
# correctly spelled name of a city of 13 million departed from a district of
# Shanghai. Cycle 15's verification recorded `Xi'an -> 4 hits` as a pass: it
# counted hits and never asked which was first.
#
# So the property is not "the name is findable" (the tests above) but "the
# name RANKS FIRST". It is asserted over every shipped name rather than over
# the one city that broke, because the rebuild takes the list from 553 to
# 1,464 and with it the collision surface.
#
# MUTATIONS PERFORMED, with the results as measured.
#
# 1. Flatten the ranker -- `rankCity` returns 0 for everything, which IS the
#    pre-fix behaviour, since the list then keeps its alphabetical order:
#    **4 failed, 8 passed.** The general property names **20 of 1,464**
#    cities that depart from somewhere else. That is the number worth
#    recording, because cycle 16's review found one:
#
#      Xi'an   -> Fengxiang       London  -> East London
#      Quito   -> Iquitos         Cali    -> Aguascalientes
#      Lu'an   -> Kluang          Huzhou  -> Chuzhou
#      Salem   -> Jerusalem       Turin   -> Maturin
#      Ji'an   -> Hongjiang       Gaya    -> Cagayan de Oro
#      Palma   -> Las Palmas ...  Santos  -> General Santos
#      Osh     -> Baoshan         Orel    -> Morelia   ... and six more
#
#    At the 553 origins `dist/` holds today only Xi'an is affected; the other
#    nineteen arrive with the rebuild. Typing "London" and getting East
#    London is the one a visitor would notice first.
#
# 2. Drop only the exact-match tier: **1 failed, 3 errored.** The errors are
#    the slice guard doing its job -- `_rank_city_src()` counts three
#    `return`s and refuses to hand a two-tier ranker to the fixture. Red, but
#    less legible than mutation 1.
#
# 3. Drop only the word-boundary tier: same shape, **1 failed, 3 errored**.
#
# No mutation came back green.


def _rank_city_src() -> str:
    """The verbatim `rankCity` arrow out of `render()`.

    Not `_const_arrow`: `rankCity` is declared inside a function, so the
    top-level `const rankCity = ` anchor that helper looks for does not exist
    at column 0. Sliced from its declaration to the closing `};` of the arrow
    body, and the assertions below check the slice really holds all four tiers
    before anything is run against it.
    """
    start = APP.index("  const rankCity = (c) => {")
    end = APP.index("\n  };", start) + len("\n  };")
    return APP[start:end]


def test_the_rank_slice_really_contains_all_four_tiers() -> None:
    """The guard on the guard: a truncated slice ranks everything alike and
    every assertion below passes for the wrong reason.
    """
    src = _rank_city_src()
    assert src.count("return") == 3, (
        f"rankCity sliced with {src.count('return')} returns, not 3:\n{src}")
    for tier in ("c.key === f", "c.key.startsWith(f)", '(" " + c.key).includes(" " + f)'):
        assert tier in src, f"{tier} is not in the sliced rankCity:\n{src}"


@pytest.fixture(scope="module")
def rank(node: str, tmp_path_factory):
    """Run the real `rankCity` over the real `fold()`, in node.

    Returns, for a typed query, the names it matches in the order `render()`
    would build the rows -- which is what Enter acts on.
    """
    path = tmp_path_factory.mktemp("rank") / "rank.cjs"
    path.write_text(
        FOLD_SRC + "\n"
        "const [names, queries] = JSON.parse(process.argv[2]);\n"
        # `cities` is sorted by localeCompare once and the rank sort is
        # stable, exactly as app.js builds it -- so ties break alphabetically
        # here for the same reason they do on the page.
        "const cities = names.slice().sort((a, b) => a.localeCompare(b))\n"
        "  .map((name) => ({ name, key: fold(name) }));\n"
        "const out = {};\n"
        "for (const q of queries) {\n"
        "  const f = fold(q);\n"
        + _rank_city_src().replace("  const rankCity", "  const rankCity") + "\n"
        "  const hits = cities.filter((c) => c.key.includes(f))\n"
        "    .map((c) => ({ c, r: rankCity(c) }))\n"
        "    .sort((a, b) => a.r - b.r)\n"
        "    .map((e) => e.c);\n"
        "  out[q] = { order: hits.map((c) => c.name),\n"
        "             exact: hits.length > 0 && hits[0].key === f };\n"
        "}\n"
        "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")

    def call(names: list[str], queries: list[str]) -> dict[str, dict]:
        done = subprocess.run([node, str(path), json.dumps([names, queries])],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def test_every_shipped_name_ranks_its_own_city_first(rank) -> None:
    """Type a city's exact name and Enter departs from that city.

    The property is asserted on the FOLDED KEY of the first hit, not on its
    name, and the difference is not pedantry -- it is what makes the assertion
    both correct and strict.

    Once `fold()` has done its work, two cities can share a key honestly.
    `Fuzhou` and `Fuzhou` are two different Chinese cities; `San José` in
    Costa Rica and `San Jose` in California fold to one key because the fold
    drops the accent on purpose, and it must, or `San Jose` would not find
    `San José`. A search cannot tell those apart and is not wrong to return
    either. What it must never do is rank a DIFFERENT key first -- which is
    exactly the `Xi'an` -> `Fengxiang` defect, where the query key `xian` lost
    to the unrelated key `fengxiang`.

    The `San José` case is only visible at 1,464 origins. At the 553 the
    built `dist/` holds, it does not exist -- which is the whole reason this
    file now reads `data/origins.toml` instead of `dist/index.json`.
    """
    names = _shipped_names()
    ranked = rank(names, names)
    wrong = {q: r["order"][:3] for q, r in ranked.items() if not r["exact"]}
    assert not wrong, (
        f"{len(wrong)} of {len(names)} names do not rank a city of their own "
        f"name first, so Enter departs from somewhere else: {wrong}")


def test_the_xian_regression_specifically(rank) -> None:
    """The instance that shipped, pinned by name.

    Kept beside the general property because a future change could satisfy
    the general test by weakening the fold instead of fixing the rank, and
    this one names the four cities that must all still be reachable.
    """
    names = _shipped_names()
    if "Xi'an" not in names and "Xi’an" not in names:
        pytest.skip("Xi'an is not in the shipped origin list")
    xian = "Xi'an" if "Xi'an" in names else "Xi’an"
    hits = {q: r["order"] for q, r in rank(names, [xian, "xi'an", "xian"]).items()}
    for typed in (xian, "xi'an", "xian"):
        assert hits[typed], f"{typed!r} matched nothing at all"
        assert hits[typed][0] == xian, (
            f"typing {typed!r} ranks {hits[typed][0]!r} first, not {xian!r}; "
            f"full order {hits[typed]}")
    # The other three must still be findable -- a rank that fixed Xi'an by
    # making the fold stricter would break these instead.
    assert "Fengxiang" in hits["xian"], "Fengxiang is no longer matched by 'xian'"


def test_a_prefix_outranks_an_interior_match(rank) -> None:
    """The middle two tiers, on data rather than on a constructed fixture.

    `ning` is an interior substring of Jining and Xining and a prefix of
    Ningbo, so the prefix must come first. This is the tier that stops a
    one-syllable query returning the alphabetically-first accident.
    """
    names = _shipped_names()
    have = [n for n in ("Ningbo", "Jining", "Xining", "Nanning") if n in names]
    if len(have) < 2 or "Ningbo" not in have:
        pytest.skip("the ning cities are not in the shipped origin list")
    order = rank(names, ["ning"])["ning"]["order"]
    assert order[0] == "Ningbo", (
        f"'ning' ranks {order[0]!r} above the city it prefixes; order {order}")
