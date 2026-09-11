"""The deploy scripts must not lie about what they do.

Three separate cycle-6 findings, all in comments, all in the one script that
decides whether a build reaches the public:

  - the header said `browser_verify.sh` "is a SEPARATE stage and is not run
    from here" while line 155 ran it and, under `set -euo pipefail`, owned its
    exit code. `git log -S` dates the stage to 29c6330 and the contradicting
    sentence to 83fb802 -- the commit that corrected this header for DOC3-14;
  - the free-space pre-flight added back the live set that `df` had already
    excluded, demanding 36.1 GiB for a measured 15.69 GiB `dist`;
  - a comment named `tests/web/test_water.py`, which has never existed.

None of them changed behaviour except the second, and that one could refuse a
deploy that would have succeeded. A comment in a deploy script is operator
documentation: someone reads it at 2 a.m. and acts on it.
"""

import re

from transport_maps import config

ROOT = config.ROOT
DEPLOY = (ROOT / "scripts" / "deploy_verify.sh").read_text(encoding="utf-8")
BROWSER = (ROOT / "scripts" / "browser_verify.sh").read_text(encoding="utf-8")


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_the_deploy_script_does_not_deny_running_the_browser_stage():
    """Mutation performed and reverted: put "is not run from here" back -> red."""
    runs = "browser_verify.sh" in _code(DEPLOY)
    assert runs, "the deploy no longer opens a browser; CLAUDE.md requires it"
    comments = "\n".join(ln for ln in DEPLOY.splitlines() if ln.lstrip().startswith("#"))
    flat = " ".join(comments.split())
    assert "is not run from here" not in flat, (
        "the header denies running a stage this script runs and whose exit "
        "code it takes")


def test_the_free_space_check_does_not_count_the_live_set_twice():
    """`df` reports what is free; the old set is already occupying disk.

    `--delay-updates` stages the NEW payload beside the old one, so the
    transient requirement is the payload plus a margin. Adding the old set back
    demanded 2.3x -- 36.1 GiB for a 15.69 GiB dist -- where V26 specified 1.3x.

    Mutation performed and reverted: restore `* 23 / 10` -> red.
    """
    m = re.search(r"want_kb=\$\(\(\s*need_kb \* (\d+) / (\d+)\s*\)\)", DEPLOY)
    assert m, "the free-space pre-flight has moved; re-derive this test"
    factor = int(m.group(1)) / int(m.group(2))
    assert 1.0 < factor < 2.0, (
        f"the free-space demand is {factor:.1f}x the payload. Above 2x it is "
        "counting the live set df has already excluded, and can refuse a "
        "deploy that would succeed; at or below 1x there is no margin at all")


def test_every_test_path_the_deploy_scripts_name_exists():
    """A comment named `tests/web/test_water.py`; the file is at
    `tests/emit/test_water.py` and always was.

    Mutation performed and reverted: name a non-existent test file in either
    script -> red.
    """
    named = set()
    for text in (DEPLOY, BROWSER):
        named |= set(re.findall(r"\btests/[\w/]*test_\w+\.py", text))
    assert named, "neither deploy script names a test file; re-derive this test"
    missing = sorted(p for p in named if not (ROOT / p).is_file())
    assert not missing, f"the deploy scripts name test files that do not exist: {missing}"


def test_the_page_gate_runs_the_directory_rather_than_a_hand_typed_list():
    """The hand-typed list omitted the one test measuring band-colour
    separation, which CLAUDE.md makes a standing rule. A directory cannot
    forget a file.

    Mutation performed and reverted: replace `tests/web/` with two named
    files -> red.
    """
    m = re.search(r"page_gate\(\) \{(.*?)\n\}", DEPLOY, re.S)
    assert m, "page_gate has moved; re-derive this test"
    # Strip the comments first. Written without this, the assertion was
    # satisfied by the comment that explains the directory -- the second time
    # in this cycle a guard was saved by its own prose, and the second time the
    # mutation caught it and reading it did not.
    assert re.search(r"\btests/web/(?!\w)", _code(m.group(1))), (
        "the page gate runs named files again instead of the whole directory")
