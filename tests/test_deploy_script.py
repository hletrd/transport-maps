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


def test_no_gate_in_the_browser_stage_passes_on_empty_output():
    """A check that reports success when it did not run is worse than none.

    `browser_verify.sh` is the gate CLAUDE.md's deploy rule rests on: "No deploy
    is done until it has been opened in a browser... `curl` returning 200 proves
    nothing about whether the page runs."

    Two of its checks could report a pass without having read anything. The
    console check was the only capture in the file using `2>/dev/null`, so a
    dead session or a CDP disconnect gave empty stdout, `grep -ci` printed 0,
    and it announced "errors: 0". The origin-label check fired only on a
    POSITIVE grep for the old slug, so an empty result -- eval failed, page
    never loaded, the probe's own "no origin label" string -- was a pass.

    Mutations performed and reverted: restore `2>/dev/null` on the console
    capture -> red; delete the `case "$C" in` guard -> red.
    """
    code = _code(BROWSER)
    console = [ln for ln in code.splitlines() if "agent-browser console" in ln]
    assert console, "the console check is gone from browser_verify.sh"
    for line in console:
        assert "2>/dev/null" not in line, (
            "the console capture discards stderr, so a failed agent-browser "
            f"call greps to 0 and the gate passes without reading it: {line.strip()}")
    assert "could not be read" in code, (
        "nothing in browser_verify.sh fails when the console comes back empty")

    # NOT `'no origin label' in code`: that string is the probe's own return
    # value and appears in the eval it sends to the browser, so the assertion
    # was satisfied by the very thing it was meant to guard -- the fourth shape
    # of vacuity this repository has now recorded (the assertion's scope is
    # derived from its subject). The guard must be a line that BOTH matches the
    # empty/failed result and sets fail=1.
    guards = [ln.strip() for ln in code.splitlines()
              if "no origin label" in ln and "fail=1" in ln]
    assert guards, (
        "an empty or failed origin-label probe does not set fail=1, so the "
        "check passes when it did not run")
    # ...and the source check must be positive, not only negative-on-seoul.
    assert re.search(r'grep -q "origins/\.\*\\\.pmtiles" \|\|', code) or any(
        'origins/' in ln and "||" in ln and "fail=1" in ln
        for ln in code.splitlines()), (
        "the bands-source check fires only when the OLD slug is still there, so "
        "an empty result reads as a pass")

    # Every capture in the file folds stderr in, so a tool failure shows up as
    # unmatched content rather than as silence. Any that does not is the next
    # instance of this bug.
    silent = [ln.strip() for ln in code.splitlines()
              if "agent-browser" in ln and "2>/dev/null" in ln and "$(" in ln
              and "|| true" not in ln]
    assert not silent, (
        "these captures discard stderr, so a failed call is indistinguishable "
        "from a clean one:\n  " + "\n  ".join(silent))


def test_the_remote_free_space_check_quotes_the_deploy_root():
    """`df -Pk $DEPLOY_ROOT` inside a double-quoted ssh command is expanded by
    the LOCAL shell into the remote command string, then split by the REMOTE
    shell. A root with a space in it makes df report on its first word -- a
    different filesystem with different free space -- and the guard that exists
    to stop a half-written dist/ reaching the server measures somewhere else.

    Mutation performed and reverted: unquote it -> red.
    """
    code = _code(DEPLOY)
    df = [ln for ln in code.splitlines() if "df -Pk" in ln]
    assert df, "the free-space check is gone"
    for line in df:
        assert re.search(r"df -Pk\s+'\$DEPLOY_ROOT'|df -Pk\s+\\\"\$DEPLOY_ROOT\\\"", line), (
            f"$DEPLOY_ROOT reaches the remote df unquoted: {line.strip()}")
