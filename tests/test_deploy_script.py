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
    # Emptiness cannot be the discriminator, and neither can the exit status:
    # `agent-browser console` with no session exits 0 and prints nothing, which
    # is byte-identical to a clean console. Measured against the live site after
    # a first version of this fix failed a page whose console was simply clean.
    # So the gate must prove the session answers BEFORE trusting a silent read.
    assert "the page under test is not answering" in code, (
        "browser_verify.sh reads the console without first proving the PAGE is "
        "answering, so an unread console is indistinguishable from a clean one")
    # Tied to the page, not to the tool: agent-browser eval happily returns a
    # literal, and even location.href, on a session sitting at about:blank.
    assert "location.href" in code and "#map canvas" in code, (
        "the liveness probe does not read anything that only the page under "
        "test can answer")
    probe = code.index("the page under test is not answering")
    read = code.index("agent-browser console")
    assert probe < read, (
        "the liveness probe runs after the console read, which proves nothing "
        "about the read")
    assert "is not answering" in code and "fail=1" in code

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


def test_a_remote_free_space_figure_cannot_run_a_command_on_this_machine():
    """`free_kb` is remote output, and every use of it is an arithmetic
    context: `[ "$free_kb" -lt ... ]` and three `$(( free_kb/1024/1024 ))`.

    Bash evaluates a NAME inside `$(( ))` by evaluating its value as an
    arithmetic expression, and an array subscript inside one is a command
    substitution. A host answering `MODE[$(id -un > PWNED)]` instead of a
    number therefore runs that command here. It was demonstrated with a stub
    `ssh`, and `set -u` is not a defence: it only decides which already-set
    name works as the subscript.

    The remote is the owner's own server, so this is a primitive rather than a
    live attack. It is also one `case` to close, in the one script that talks
    to another machine.

    This test runs the real shell, because the defect IS the shell's
    behaviour: a pattern assertion would pass against a `case` that does not
    actually reject.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    guard = re.search(r"case \$\{free_kb:-\} in(.+?)esac", DEPLOY, re.S)
    assert guard, "the free-space figure is no longer sanitised before it is used"

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "PWNED"
        # Exactly the shape the script has: a hostile value, the sanitiser, and
        # then the arithmetic the script performs on it.
        script = f'''set -u
DEPLOY_HOST=stub
free_kb='MODE[$(printf x > {marker})]'
case ${{free_kb:-}} in
  "") ;;
  *[!0-9]*) echo "  $DEPLOY_HOST returned a non-numeric free-space figure; ignoring it"
            free_kb="" ;;
esac
if [ -z "$free_kb" ]; then echo REFUSED
else echo $(( free_kb / 1024 / 1024 )); fi
'''
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert "REFUSED" in done.stdout, done.stdout
        assert not marker.exists(), (
            "the arithmetic expansion executed a command from remote output")

        # ...and the positive control: a real figure must still be used, or the
        # guard has simply disabled the free-space check.
        ok = subprocess.run(
            ["bash", "-c", script.replace("'MODE[$(printf x > " + str(marker) + ")]'",
                                          "'20971520'")],
            capture_output=True, text=True)
        assert ok.stdout.strip() == "20", ok.stdout


def test_the_sanitised_figure_is_read_before_every_arithmetic_use_of_it():
    """A second `free_kb=` assignment after the `case`, or an arithmetic use
    before it, would reopen the hole silently.
    """
    code = _code(DEPLOY)
    case_at = code.index("case ${free_kb:-} in")
    read_at = code.index("free_kb=$(ssh")
    assert read_at < case_at, "the figure is sanitised before it is read"
    uses = [m.start() for m in re.finditer(r'\[ "\$free_kb" -lt|\$\(\(\s*free_kb', code)]
    assert len(uses) >= 3, f"the arithmetic uses moved; found {len(uses)}"
    assert min(uses) > case_at, "free_kb reaches an arithmetic context before the sanitiser"
    assert code.count("free_kb=$(") == 1, "a second assignment can reopen the hole"


def _page_gate_source() -> str:
    """The real `page_gate` function, lifted verbatim from the deploy script.

    Anchored on a closing brace in column 0, which is the function's own and
    not one of the `${...}` or `$(( ))` inside it.
    """
    m = re.search(r"^page_gate\(\) \{\n.*?^\}", DEPLOY, re.S | re.M)
    assert m, "page_gate is gone or has been reshaped; re-read this guard"
    src = m.group(0)
    # The guard on the guard: the slice must hold both refusals, or the tests
    # below would be exercising a fragment and passing for the wrong reason.
    assert "command -v node" in src, "the node pre-flight is not in the slice"
    assert "skipped" in src, "the skip check is not in the slice"
    return src


def _run_page_gate(tmp, pytest_summary: str, pytest_rc: int = 0,
                   with_node: bool = True, collected: int | None = None,
                   ruff_rc: int = 0, dist_present: bool = True):
    """Run the REAL page_gate with `uv` and `node` stubbed out.

    A pattern assertion cannot see these defects: the whole class is that
    pytest exits 0 on a skip, a deselect, an xfail and an empty run, and the
    shell therefore carried on. Only the shell can show that it now does not.

    `page_gate` calls `uv` three times -- `ruff check`, `pytest
    --collect-only`, then the real `pytest` -- so the stub has to tell them
    apart. A stub that answered all three with the run summary made the
    collected-count floor read the summary line as its collected count, which
    is a way of passing this harness while the gate is broken.

    `collected` defaults to the number of passes in the summary, so an
    existing caller that only cares about the pass/skip arithmetic gets a
    consistent pair without stating it twice.

    `dist_present` writes a `dist/index.json` into the scratch cwd: the gate
    refuses a "needs a built dist/" skip when dist/ IS built, because those
    tests had something to read and did not read it.
    """
    import re as _re
    import subprocess
    from pathlib import Path

    if collected is None:
        m = _re.search(r"(\d+) passed", pytest_summary)
        skips = _re.findall(r"^SKIPPED \[(\d+)\]", pytest_summary, _re.M)
        n_skipped = sum(int(n) for n in skips)
        if not skips:
            m2 = _re.search(r"(\d+) skipped", pytest_summary)
            n_skipped = int(m2.group(1)) if m2 else 0
        collected = (int(m.group(1)) if m else 0) + n_skipped

    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    work = Path(tmp) / "work"
    (work / "dist").mkdir(parents=True, exist_ok=True)
    if dist_present:
        (work / "dist" / "index.json").write_text("{}")
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *'ruff check'*) exit {ruff_rc} ;;\n"
        f'  *--collect-only*) echo "{collected} tests collected in 0.42s"; exit 0 ;;\n'
        "esac\n"
        f'printf "%s\\n" "{pytest_summary}"\nexit {pytest_rc}\n')
    uv.chmod(0o755)
    if with_node:
        node = bin_dir / "node"
        node.write_text("#!/bin/sh\nexit 0\n")
        node.chmod(0o755)
    # A PATH holding only the stubs, so a real `node` on the developer's
    # machine cannot make the node-missing case pass by accident.
    script = (f'set -euo pipefail\nPATH="{bin_dir}:/usr/bin:/bin"\ncd "{work}"\n'
              f"{_page_gate_source()}\npage_gate\necho GATE_RETURNED_OK\n")
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_the_page_gate_refuses_a_run_whose_tests_skipped(tmp_path):
    """pytest exits 0 when a test skips. 22 files under tests/web/ skip
    themselves without `node` -- 19 of them, measured, including the only
    parse of app.js and the only legend-tick enforcement -- so this stage used
    to print a row of dots and return success having checked none of it.

    Both summary shapes are covered. pytest writes "N passed, M skipped" when
    something ran and "M skipped in ..." when nothing did, and the second is
    exactly the all-skipped case the check exists for -- a `sed` written for
    the first form silently missed it, which is why this test has two cases.

    Mutation performed and reverted: delete the `skipped` refusal from
    page_gate -> both cases print GATE_RETURNED_OK and this test goes red.
    """
    for summary in ("421 passed, 3 skipped in 30.00s",
                    "19 skipped in 0.12s"):
        done = _run_page_gate(tmp_path, summary)
        assert done.returncode != 0, (
            f"the page gate accepted {summary!r}:\n{done.stdout}{done.stderr}")
        assert "SKIPPED" in done.stdout, done.stdout
        assert "GATE_RETURNED_OK" not in done.stdout, (
            "the gate carried on past a skipped run")


def test_the_page_gate_still_accepts_a_clean_run(tmp_path):
    """The positive control. Without it the test above passes just as well
    against a gate that refuses everything, which would be a different way of
    not deploying.
    """
    done = _run_page_gate(tmp_path, "424 passed in 34.98s")
    assert done.returncode == 0, f"{done.stdout}{done.stderr}"
    assert "GATE_RETURNED_OK" in done.stdout, done.stdout


def test_the_page_gate_refuses_when_node_is_absent(tmp_path):
    """`node` on the build host resolves through an fnm per-shell-session
    path, so a deploy from launchd, cron, or any shell fnm did not initialise
    has none -- and every node-gated test would skip itself to green. Checked
    up front so the operator reads one sentence instead of counting dots.
    """
    done = _run_page_gate(tmp_path, "424 passed in 34.98s", with_node=False)
    assert done.returncode != 0, done.stdout
    assert "node is not on PATH" in done.stdout, done.stdout
    assert "GATE_RETURNED_OK" not in done.stdout


def test_the_page_gate_still_fails_on_a_real_test_failure(tmp_path):
    """The skip check must not swallow the case the gate was built for. Under
    `set -e` a bare failing pipeline would have aborted before the skip check
    ran, so the two refusals are sequenced with `|| rc=$?` -- this proves they
    compose rather than shadow each other.
    """
    done = _run_page_gate(tmp_path, "2 failed, 419 passed in 31.00s", pytest_rc=1)
    assert done.returncode != 0, done.stdout
    assert "page-asset gate failed" in done.stdout, done.stdout
    assert "GATE_RETURNED_OK" not in done.stdout


# --- C16-2 / C16-3: the holes cycle 15's skip refusal left ------------------
#
# C15-2 made a skip a failure, which was right and is kept. It left four
# other ways for pytest to exit 0 having checked almost nothing, and it broke
# the one deploy mode documented as not needing dist/.


def test_the_page_gate_refuses_a_deselected_run(tmp_path):
    """`skipped` is not the only word pytest prints for "did not run", and
    `deselected` is the one no other guard in this gate can see.

    Measured against the gate as cycle 15 left it, by lifting the real
    `page_gate` out of the script and feeding it scripted summaries: all of
    `3 passed, 421 deselected`, `431 passed, 19 xfailed`, `1 passed` and
    `448 passed, 2 errors` were ACCEPTED, rc=0.

    Reachable today and not hypothetical: `pyproject.toml` already carries
    `-m 'not network and not real_multi_band'`, so a single
    `pytestmark = pytest.mark.network` on `tests/web/test_parses.py` -- the
    file `page_gate`'s own comment calls "why this stage is worth having at
    all", and the only parse of `app.js` anywhere in the repository --
    removes it from the deploy gate with no output an operator would notice.

    THE COLLECTED COUNT IS THE POINT OF THIS TEST, and my first version of it
    got it wrong. I stubbed `--collect-only` at 450 beside a summary of
    `3 passed, 421 deselected`, deleted the deselect refusal to check the
    test went red, and it stayed GREEN at 19 passed -- because the floor
    caught it instead. That state cannot occur: measured,
    `pytest -q --collect-only` APPLIES deselection and reports the reduced
    number (`no tests collected (26 deselected)` for a `-k` that matches
    nothing). So in the real defect `collected` is 3 too, the floor is
    satisfied, and this loop is the only thing standing between a one-line
    `pytestmark` and an unparsed `app.js` on the live site. The stub now says
    3, and deleting the refusal reddens this test.
    """
    done = _run_page_gate(tmp_path, "3 passed, 421 deselected in 0.10s", collected=3)
    assert done.returncode != 0, (
        f"the page gate accepted a run with 421 deselected:"
        f"\n{done.stdout}{done.stderr}")
    assert "deselected" in done.stdout, done.stdout
    assert "GATE_RETURNED_OK" not in done.stdout


def test_the_page_gate_refuses_xfails_and_errors(tmp_path):
    """The other two words, at the collected counts they really occur with.

    `xfailed` and `errors` are run outcomes, not collection ones, so
    `--collect-only` still reports the full number and the floor below
    catches these as well. Both refusals are kept: the floor says "225 are
    unaccounted for", which is true but does not tell the operator that the
    reason is 19 xfails. Two guards, one of them legible.
    """
    for summary in ("431 passed, 19 xfailed in 30.00s",
                    "448 passed, 2 errors in 9.00s"):
        done = _run_page_gate(tmp_path, summary, collected=450)
        assert done.returncode != 0, (
            f"the page gate accepted {summary!r}:\n{done.stdout}{done.stderr}")
        assert "GATE_RETURNED_OK" not in done.stdout, (
            f"the gate carried on past {summary!r}")


def test_the_page_gate_asserts_a_floor_on_how_much_ran(tmp_path):
    """Counting failures proves nothing failed. It does not prove anything ran.

    Two shapes: a run that collected 450 and passed 200 (225 vanished between
    collection and the summary), and a run that collected nothing at all --
    which `1 passed in 0.01s` above is the degenerate case of. Neither can be
    caught by looking for a bad word in the output, because there is no bad
    word: the output is entirely good news about a run that did not happen.
    """
    short = _run_page_gate(tmp_path, "200 passed in 5.00s", collected=450)
    assert short.returncode != 0, short.stdout
    assert "unaccounted for" in short.stdout, short.stdout

    empty = _run_page_gate(tmp_path, "0 passed in 0.01s", collected=0)
    assert empty.returncode != 0, empty.stdout
    assert "collected no tests at all" in empty.stdout, empty.stdout


_DIST_SKIPS = (
    "SKIPPED [2] tests/web/test_origin_near.py:106: "
    "needs a built dist/: dist/index.json is not built; no origins to scan\n"
    "SKIPPED [1] tests/web/test_city_label_dots.py:251: "
    "needs a built dist/: dist/ is not built here; nothing to measure against\n"
    "SKIPPED [4] tests/test_licence_firewall.py:73: "
    "needs a built dist/: no scannable files under dist; nothing built yet\n"
    "443 passed, 7 skipped in 11.00s")


def test_page_only_still_works_on_a_tree_that_has_no_dist(tmp_path):
    """The regression C15-2 shipped, and the reason the skip rule needed a
    sentinel rather than a blanket refusal.

    `deploy_verify.sh`'s own header documents `--page-only` as "web/ only: no
    dist gate" -- the mode for a page fix while a rebuild owns `dist/`, which
    is exactly the situation this repository has been in for three cycles.
    C15-1 and C15-3 then added four `dist/`-conditional skips to the gate's
    own file set, joining the licence firewall's. Measured with `dist/`
    hidden: 21 passed / 0 skipped became **14 passed / 7 skipped**. `dist/`
    is gitignored, so that is every clone, and the refusal message never
    mentioned `dist/`.

    It also contradicted `tests/test_licence_firewall.py`, which asserts in
    as many words that a skip is the CORRECT answer for an unbuilt tree.
    """
    done = _run_page_gate(tmp_path, _DIST_SKIPS, dist_present=False)
    assert done.returncode == 0, (
        f"--page-only refused on a tree with no dist/:\n{done.stdout}{done.stderr}")
    assert "GATE_RETURNED_OK" in done.stdout, done.stdout


def test_a_skip_that_is_not_about_dist_still_refuses(tmp_path):
    """The half of C15-2 that must not be weakened while fixing the other half.

    One non-sentinel skip mixed in among six sentinel ones, on a tree with no
    `dist/`: still refused. Without this, "tell the two apart" would be
    indistinguishable from "stop checking".
    """
    mixed = ("SKIPPED [6] tests/web/test_origin_near.py:106: "
             "needs a built dist/: nothing built\n"
             "SKIPPED [1] tests/web/test_vendor.py:9: node is not on PATH\n"
             "443 passed, 7 skipped in 11.00s")
    done = _run_page_gate(tmp_path, mixed, dist_present=False)
    assert done.returncode != 0, done.stdout
    assert "other than an unbuilt dist/" in done.stdout, done.stdout
    assert "GATE_RETURNED_OK" not in done.stdout


def test_a_dist_skip_refuses_when_dist_is_actually_built(tmp_path):
    """The sentinel is not a way to opt out of the gate.

    If `dist/index.json` is on disk and a test skipped saying it is not, the
    test had something to read and did not read it. That is the C15-2 case
    again wearing the sentinel, and it is refused.
    """
    done = _run_page_gate(tmp_path, _DIST_SKIPS, dist_present=True)
    assert done.returncode != 0, done.stdout
    assert "dist/index.json is present" in done.stdout, done.stdout


def test_the_skip_sentinel_has_not_drifted_between_the_two_files():
    """`page_gate` greps for a string `tests/conftest.py` writes. They are in
    different languages and nothing else connects them, so if one is reworded
    the gate silently counts zero sentinel skips and `--page-only` breaks
    again -- the same failure, one indirection further away.
    """
    from tests.conftest import NEEDS_DIST
    assert NEEDS_DIST in DEPLOY, (
        f"tests/conftest.py's NEEDS_DIST is {NEEDS_DIST!r}, which "
        f"deploy_verify.sh does not grep for")
    assert "skip_without_dist" in (
        ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")


def test_the_page_gate_runs_ruff(tmp_path):
    """`ruff check` is one of this repository's two gates and NOTHING invoked
    it -- no CI, no pre-commit hook, and zero references in either deploy
    script. It was a gate by convention: whatever the last person to run it
    by hand had left it as. A deploy is the moment it is worth knowing.
    """
    assert "ruff check" in DEPLOY, "the page gate does not run ruff"
    done = _run_page_gate(tmp_path, "450 passed in 12.00s", ruff_rc=1)
    assert done.returncode != 0, done.stdout
    assert "ruff check failed" in done.stdout, done.stdout
    assert "GATE_RETURNED_OK" not in done.stdout


def test_the_browser_stage_still_asks_whether_water_rendered():
    """CLAUDE.md makes this a standing deploy rule, in as many words:
    "`dist/water.pmtiles` is static and not produced by `build-all`. Without
    it the page shows no error -- the shore just goes back to being
    hex-shaped one cell out to sea. `deploy_verify.sh` refuses to deploy
    without it and `browser_verify.sh` asks the map whether water features
    actually rendered."

    Both refusals work. Neither was tested: cycle 16's verifier lane deleted
    `browser_verify.sh`'s water block and `tests/test_deploy_script.py` stayed
    at 12 passed. This is the half CLAUDE.md assigns to the browser stage --
    a header-valid but tile-empty archive passes `check_dist`'s header parse
    and only a rendered-feature count can see it.
    """
    assert 'getLayer("water")' in BROWSER, (
        "browser_verify.sh no longer asks the map for the water layer")
    assert 'queryRenderedFeatures({layers:["water"]})' in BROWSER, (
        "browser_verify.sh no longer counts rendered water features, so a "
        "header-valid but tile-empty water.pmtiles would pass every gate")
    assert re.search(r'waterFeatures":\[1-9\]', BROWSER), (
        "the water check no longer refuses a zero feature count")
    assert "water layer rendered nothing" in BROWSER, (
        "the water failure no longer sets fail=1 with a message")


def _run_transfer_kb(tmp_path, rsync_body: str) -> str:
    """The script's own transfer_kb, run with a stub rsync first on PATH."""
    import subprocess

    fn = re.search(r"\ntransfer_kb\(\) \{.*?\n\}\n", DEPLOY, re.S)
    assert fn, "transfer_kb has moved; re-derive this test"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "rsync"
    stub.write_text("#!/bin/bash\n" + rsync_body)
    stub.chmod(0o755)
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "f").write_bytes(b"\0" * 300_000)
    script = ("RSYNC_COMMON=(-a)\nDEPLOY_HOST=h\nDEPLOY_ROOT=/r\n" + fn.group(0)
              + "transfer_kb\n")
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=tmp_path,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin"})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_space_check_counts_what_rsync_will_stage_not_the_whole_tree(tmp_path):
    """--delay-updates stages CHANGED files only. Counting all of dist/ refused
    the 2026-10-01 deploy: 108 GiB counted, 56 GiB actually changed, 116 free.

    Mutation performed and reverted: make transfer_kb print `du -sk dist`
    unconditionally -> red.
    """
    got = _run_transfer_kb(tmp_path, 'echo "Total transferred file size: 2,097,152 bytes"\n')
    assert got == str(2_097_152 // 1024 + 1)


def test_the_space_check_falls_back_to_the_whole_tree_when_rsync_cannot_say(tmp_path):
    """A dry run that fails, or prints something else, must not read as zero
    bytes to stage -- that would wave any deploy through.

    Mutation performed and reverted: fall back to `echo 0` -> red.
    """
    for i, body in enumerate(("exit 12\n", 'echo "Total transferred file size: none"\n')):
        (tmp_path / str(i)).mkdir()
        got = _run_transfer_kb(tmp_path / str(i), body)
        assert int(got) >= 290, (body, got)


HEADERS_CONF = ROOT / "deploy" / "worldmap-security-headers.conf"


def _conf_headers() -> list[tuple[str, str]]:
    """(Name, value) per `add_header` in the conf, read line by line -- a
    different reading from the script's regex, so a parse bug in either shows."""
    out = []
    for line in HEADERS_CONF.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("add_header ") and line.endswith(" always;"):
            name, rest = line[len("add_header "):].split(" ", 1)
            out.append((name, rest[: -len(" always;")].strip().strip('"')))
    return out


def _run_header_check(tmp_path, responses: dict[str, str], default: str,
                      conf=HEADERS_CONF, curl_rc: int = 0):
    """The REAL check_security_headers, with a stub `curl` that answers each
    path with the canned response whose key the URL ends with."""
    import subprocess

    fn = re.search(r"^check_security_headers\(\) \{.*?^\}", DEPLOY, re.S | re.M)
    assert fn, "check_security_headers is gone from deploy_verify.sh or was reshaped"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cases = ""
    for i, (suffix, body) in enumerate(responses.items()):
        (tmp_path / f"r{i}").write_text(body)
        cases += f'  *"{suffix}") cat "{tmp_path}/r{i}" ;;\n'
    (tmp_path / "default").write_text(default)
    stub = bin_dir / "curl"
    stub.write_text("#!/bin/bash\nurl=${@: -1}\ncase \"$url\" in\n" + cases
                    + f'  *) cat "{tmp_path}/default" ;;\nesac\nexit {curl_rc}\n')
    stub.chmod(0o755)
    script = (f"set -euo pipefail\nSITE_URL=https://example.test\n{fn.group(0)}\n"
              f'check_security_headers "{conf}" "" app.js index.json water.pmtiles'
              ' && echo HEADERS_OK || echo HEADERS_REFUSED\n')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin"})


def _response(headers: list[tuple[str, str]], status="HTTP/2 200") -> str:
    return "\r\n".join([status, *(f"{n}: {v}" for n, v in headers), "", ""])


def test_the_header_check_accepts_what_the_live_site_serves(tmp_path):
    """The positive control, in both header spellings: HTTP/2 lower-cases the
    names (what the live site sends, measured 2026-10-02) and HTTP/1.1 keeps
    nginx's capitals. Without it every refusal below could be a check that
    refuses everything."""
    conf = _conf_headers()
    assert len(conf) >= 6, conf
    lower = _response([(n.lower(), v) for n, v in conf] + [("content-type", "text/html")])
    upper = _response(conf, status="HTTP/1.1 200 OK")
    done = _run_header_check(tmp_path, {"app.js": upper}, lower)
    assert "HEADERS_OK" in done.stdout, done.stdout + done.stderr
    assert done.stdout.count("all 6 match the conf") == 4, done.stdout


def test_the_header_check_fails_a_deploy_whose_headers_drifted(tmp_path):
    """Q2. The check used to PRINT whether a CSP header was present on three
    paths and assert nothing; HSTS, X-Frame-Options, Referrer-Policy and
    Permissions-Policy were not looked at at all. Each drift below is one the
    old block passed.

    Mutations performed and reverted, each confirmed RED:
      * the `if not have` ABSENT branch removed        -> the missing-CSP and
                                                          missing-HSTS cases pass
      * the exact-value comparison removed             -> the four altered-value
                                                          cases pass
      * `|| bad=1` dropped from the python call        -> every case passes
    """
    conf = _conf_headers()
    values = dict(conf)

    def without(name):
        return _response([(n, v) for n, v in conf if n != name])

    def changed(name, value):
        return _response([(n, value if n == name else v) for n, v in conf])

    good = _response(conf)
    pp = values["Permissions-Policy"]
    assert "browsing-topics=()" in pp, pp
    cases = {
        "CSP missing on app.js only": ({"app.js": without("Content-Security-Policy")},
                                       "/app.js: content-security-policy ABSENT"),
        "no HSTS": ({"water.pmtiles": without("Strict-Transport-Security")},
                    "/water.pmtiles: strict-transport-security ABSENT"),
        "a CSP with a source appended": (
            {"index.json": changed("Content-Security-Policy",
                                   values["Content-Security-Policy"] + " https://evil.example")},
            "/index.json: content-security-policy is"),
        "Permissions-Policy without the advertising APIs": (
            {"app.js": changed("Permissions-Policy", pp.split(", browsing-topics")[0])},
            "/app.js: permissions-policy is"),
        "framing allowed": ({"app.js": changed("X-Frame-Options", "SAMEORIGIN")},
                            "/app.js: x-frame-options is"),
        "referrer tightened past Nominatim's requirement": (
            {"app.js": changed("Referrer-Policy", "no-referrer")},
            "/app.js: referrer-policy is"),
    }
    for why, (responses, message) in cases.items():
        sub = tmp_path / re.sub(r"\W+", "_", why)
        sub.mkdir()
        done = _run_header_check(sub, responses, good)
        assert "HEADERS_REFUSED" in done.stdout, (why, done.stdout + done.stderr)
        assert message in done.stdout, (why, message, done.stdout)


def test_the_header_check_cannot_pass_by_reading_nothing(tmp_path):
    """Two ways to expect or receive nothing: a conf the parse cannot read
    (the check would want no headers and pass every response), and a curl that
    fails (no headers at all).

    Mutation performed and reverted: remove the `required <= want.keys()` guard
    -> the unreadable-conf case passes -> red.
    """
    good = _response(_conf_headers())
    bogus = tmp_path / "bogus.conf"
    bogus.write_text("# add_header lines moved somewhere else\n")
    (tmp_path / "a").mkdir()
    done = _run_header_check(tmp_path / "a", {}, good, conf=bogus)
    assert "HEADERS_REFUSED" in done.stdout, done.stdout + done.stderr
    assert "could not read" in done.stdout, done.stdout

    (tmp_path / "b").mkdir()
    done = _run_header_check(tmp_path / "b", {}, "", curl_rc=7)
    assert "HEADERS_REFUSED" in done.stdout, done.stdout + done.stderr
    assert "ABSENT" in done.stdout


def test_the_deploy_enforces_the_header_check_on_every_asset_class():
    """The function is only a gate if the deploy calls it, on the asset classes
    nginx serves from different locations (the page, scripts, JSON, binary
    arrays, PMTiles), and stops when it fails.

    Mutation performed and reverted: replace the call's `exit 1` with `true`
    -> red.
    """
    code = _code(DEPLOY)
    call = re.search(r'^check_security_headers "\$ROOT/deploy/worldmap-security-headers\.conf"'
                     r'(.*?)\|\| \{([^}]*)\}', code, re.S | re.M)
    assert call, "the deploy no longer runs check_security_headers against the conf"
    paths, on_fail = call.group(1), call.group(2)
    for path in ('""', "app.js", "index.json", "hover_cells.bin", ".pmtiles"):
        assert path in paths, f"the header check no longer covers {path}"
    assert "exit 1" in on_fail, "a header mismatch no longer stops the deploy"
    assert "CSP header:" not in code, "the report-only header loop is back"


def _browser_fn(name: str) -> str:
    """A function lifted verbatim from browser_verify.sh: a multi-line body
    closed by a brace in column 0, or a one-line `name() { ...; }`."""
    m = (re.search(rf"^{name}\(\) \{{\n.*?^\}}", BROWSER, re.S | re.M)
         or re.search(rf"^{name}\(\) \{{.*\}}$", BROWSER, re.M))
    assert m, f"{name} is gone from browser_verify.sh or has been reshaped"
    return m.group(0)


def _run_wait_until(tmp_path, answers: list[str], limit: int):
    """The real wait_until, with a stub `agent-browser` that prints one line of
    `answers` per call (the last repeats) in the shape a real eval returns."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "answers").write_text("\n".join(answers) + "\n")
    stub = bin_dir / "agent-browser"
    stub.write_text(
        "#!/bin/bash\n"
        f'n=$(cat "{tmp_path}/n" 2>/dev/null || echo 0); echo $((n + 1)) > "{tmp_path}/n"\n'
        f'total=$(wc -l < "{tmp_path}/answers")\n'
        "i=$(( n + 1 > total ? total : n + 1 ))\n"
        f'sed -n "${{i}}p" "{tmp_path}/answers"\n')
    stub.chmod(0o755)
    script = (f"set -u\nfail=0\n{_browser_fn('wait_until')}\n"
              f'wait_until {limit} "the thing" "js"; echo "rc=$? fail=$fail"\n')
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, timeout=60)
    calls = int((tmp_path / "n").read_text())
    return done, calls


def test_the_browser_stage_waits_for_the_page_not_for_a_clock():
    """C12-8 / V13-28. Both cold loads slept a fixed 15 s and 10 s, chosen
    against 553 origins, before reading data that grew to 1,464 rows and a
    ~10 MB reading tier -- the mechanism behind four gate failures on correct
    code. Each must now poll a readiness condition before its first read.

    Mutations performed and reverted: put `; sleep 15` back on the first open
    -> red; drop the `?from=tokyo` open's wait_until -> red.
    """
    code = _code(BROWSER)
    for opener, first_read in (('agent-browser open "$URL"', "R=$(agent-browser eval"),
                               ('agent-browser open "${URL}?from=tokyo"', 'q.value="JFK"')):
        at = code.index(opener)
        line = code[at:code.index("\n", at)]
        assert not re.search(r"sleep\s+\d", line), (
            f"a cold load waits a fixed time again: {line.strip()}")
        between = code[at:code.index(first_read, at)]
        assert re.search(r"^wait_until \d+ ", between, re.M), (
            f"nothing waits for the page between `{opener}` and its first read")


def test_wait_until_returns_as_soon_as_the_page_answers(tmp_path):
    """The positive control: the poll must not simply always time out."""
    done, calls = _run_wait_until(tmp_path, ['"false"', '"false"', '"true"'], limit=30)
    assert "rc=0 fail=0" in done.stdout, done.stdout + done.stderr
    assert "ready after" in done.stdout
    assert calls == 3, f"polled {calls} times for an answer that came on the third"


def test_wait_until_fails_loudly_when_the_page_never_gets_there(tmp_path):
    """A ceiling that is reached must set fail=1 and say what it waited for --
    a timeout that falls through silently is the old fixed sleep again.

    Mutations performed and reverted: delete `fail=1` from wait_until -> red;
    `return 1` -> `return 0` -> red; compare `$got` against "false" instead of
    "true" -> red (the positive control above goes red as well).
    """
    # $SECONDS ticks in whole seconds, so a 2 s ceiling can see one poll or
    # two depending on where in the second it started; 3 s always sees two.
    done, calls = _run_wait_until(tmp_path, ['"false"'], limit=3)
    assert "rc=1 fail=1" in done.stdout, done.stdout + done.stderr
    assert "!! waited 3 s for the thing" in done.stdout
    assert calls >= 2, "it gave up without polling"


def test_wait_until_treats_a_tool_error_as_not_ready(tmp_path):
    """No session, a CDP disconnect or a JS exception comes back as text, never
    as `true`, so it must run out the ceiling and fail -- and show the text."""
    done, _ = _run_wait_until(tmp_path, ["Error: no browser session"], limit=2)
    assert "rc=1 fail=1" in done.stdout, done.stdout + done.stderr
    assert "Error: no browser session" in done.stdout


def _city_list(cl: str, cities: int = 1464, cap: int = 60):
    import subprocess

    script = (f"set -u\nCITIES={cities}\nCAP={cap}\n{_browser_fn('json_num')}\n"
              f"{_browser_fn('check_city_list')}\n"
              'check_city_list "$1"; echo "rc=$?"\n')
    return subprocess.run(["bash", "-c", script, "_", cl], capture_output=True, text=True)


def _cl(rows, durations, no_route=0, blank=0, departing=1):
    # The real shape: agent-browser prints the JSON as a quoted string and the
    # gate strips its backslashes, so the object arrives wrapped in quotes.
    return (f'"{{"rows":{rows},"durations":{durations},"coords":0,"clipped":0,'
            f'"noRoute":{no_route},"blank":{blank},"departing":{departing}}}"')


def test_the_city_list_check_accepts_a_correct_list():
    """Positive controls, capped and uncapped (a small local dist can show a
    "no route" row; a capped list is the quickest 60 and cannot)."""
    for cl, cities in ((_cl(60, 59), 1464), (_cl(3, 1, no_route=1), 3)):
        done = _city_list(cl, cities=cities)
        assert "rc=0" in done.stdout, (cl, done.stdout + done.stderr)
        assert "!!" not in done.stdout


def test_the_city_list_check_refuses_what_the_old_patterns_let_through():
    """`'"departing":1'` was an unanchored substring, satisfied by 1000-1464,
    and `"durations":[1-9][0-9]` asserted ten timed rows out of sixty. Each case
    here must fail with its own reason; the first two passed the old greps.

    Mutations performed and reverted, each confirmed RED:
      * `[ "$dep" -eq 1 ]` -> `[ "$dep" -ge 1 ]`       -> departing 1000 passes
      * the `blank -ne 0` branch removed              -> 49 blank rows report
                                                         the wrong reason
      * the counts-add-up branch removed              -> 5 unrecognised rows
                                                         pass
      * the `dur -ge 1` check removed                 -> the all-"no route"
                                                         list passes
      * the capped-list `no route` check removed      -> 5 unreachable rows in
                                                         a ranked list pass
      * the empty-count guard removed                 -> unreadable output
                                                         reports the wrong
                                                         reason
    """
    old = re.compile(r'"durations":[1-9][0-9]')
    cases = [
        (_cl(60, 59, departing=1000), 1464, "1000 rows are marked as the current departure"),
        (_cl(60, 10, blank=49), 1464, "49 of 60 city rows carry no travel time"),
        (_cl(60, 54), 1464, "5 of 60 city rows read as neither"),
        (_cl(3, 0, no_route=2), 3, "carries no travel times"),
        (_cl(60, 54, no_route=5), 1464, "yet 5 of its rows have no route"),
    ]
    for cl, cities, why in cases[:2]:
        # Proof these are cases the OLD gate waved through.
        assert old.search(cl) and '"departing":1' in cl, cl
    for cl, cities, why in cases:
        done = _city_list(cl, cities=cities)
        assert "rc=1" in done.stdout, (cl, done.stdout + done.stderr)
        assert why in done.stdout, (why, done.stdout + done.stderr)

    for unreadable in ("", "Error: no browser session", '"{"rows":60}"'):
        done = _city_list(unreadable)
        assert "rc=1" in done.stdout, (unreadable, done.stdout)
        assert "could not read the city-list counts" in done.stdout, done.stdout


def test_the_city_list_check_is_what_the_gate_runs():
    """The two loose greps are gone from the gate, and the function the tests
    above exercise is the one it calls on the eval's output.

    Mutation performed and reverted: restore the `'"departing":1'` grep in
    place of the check_city_list call -> red.
    """
    code = _code(BROWSER)
    assert '"departing":1\'' not in code, "the unanchored departing grep is back"
    assert '"durations":[1-9][0-9]' not in code, "the ten-row durations floor is back"
    assert re.search(r'^check_city_list "\$CL" \|\| fail=1$', code, re.M), (
        "the gate no longer runs check_city_list on the city-list eval")
    for key in ("noRoute:", "blank:", "departing:"):
        assert key in code, f"the city-list eval no longer reports {key}"


def test_a_deploy_offering_the_solver_checks_the_servers_bundle(tmp_path):
    """index.json may offer an on-demand departure only if the server holds
    the bundle from the same build; the deploy refuses otherwise.

    Mutation performed and reverted: make solver_gate `return 0` first -> red.
    """
    import json
    import subprocess

    fn = re.search(r"\nsolver_gate\(\) \{.*?\n\}\n", DEPLOY, re.S)
    assert fn, "solver_gate has moved; re-derive this test"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "dist").mkdir()

    def run(index: dict, server_build: str) -> subprocess.CompletedProcess:
        (tmp_path / "dist" / "index.json").write_text(json.dumps(index))
        ssh = bin_dir / "ssh"
        ssh.write_text(f"#!/bin/bash\necho {server_build}\n")
        ssh.chmod(0o755)
        script = "DEPLOY_HOST=h\n" + fn.group(0) + "solver_gate\necho PASSED\n"
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              cwd=tmp_path, env={"PATH": f"{bin_dir}:/usr/bin:/bin"})

    assert "PASSED" in run({"buildId": "b1"}, "zzz").stdout, "no solver offered: nothing to check"
    assert "PASSED" in run({"buildId": "b1", "solver": {"wire": 1}}, "b1").stdout
    bad = run({"buildId": "b1", "solver": {"wire": 1}}, "b0")
    assert bad.returncode == 1 and "deploy_solver.sh" in bad.stdout


def _bash_fn(name: str) -> str:
    fn = re.search(r"\n" + name + r"\(\) \{.*?\n\}\n", DEPLOY, re.S)
    assert fn, f"{name} has moved; re-derive this test"
    return fn.group(0)


def test_each_batch_carries_an_origins_map_and_its_variants_together(tmp_path):
    """A batch swaps whole origins: a departure's full-map files and its
    avoid-a-mode files from one build, never split across batches.

    Mutation performed and reverted: drop `v/*/origins/"$slug".*` from the
    list -> red.
    """
    import subprocess

    d = tmp_path / "dist"
    for slug in ("a", "b", "c"):
        for sub in ("origins", "v/no-air/origins", "v/no-rail/origins"):
            (d / sub).mkdir(parents=True, exist_ok=True)
            for ext in (".pmtiles", ".bin", ".r6.bin"):
                (d / sub / f"{slug}{ext}").write_bytes(b"x")
    out = tmp_path / "lists"
    out.mkdir()
    script = "CHUNK=2\n" + _bash_fn("chunk_lists") + f"chunk_lists {out}\n"
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    lists = sorted(out.iterdir())
    assert [p.name for p in lists] == ["chunk-0001", "chunk-0002"]
    first = lists[0].read_text().split()
    assert len(first) == 2 * 9 and all(p.split("/")[-1][0] in "ab" for p in first)
    assert "v/no-rail/origins/b.r6.bin" in first
    assert sorted(lists[1].read_text().split()) == sorted(
        f"{sub}/c{ext}" for sub in ("origins", "v/no-air/origins", "v/no-rail/origins")
        for ext in (".bin", ".pmtiles", ".r6.bin"))


def test_batches_are_refused_when_the_cell_layout_changed(tmp_path):
    """Origins from two builds can share a page only if both were made against
    the same hover_cells.bin and reading_parents.bin.

    Mutation performed and reverted: make layouts_identical `return 0` first
    -> red.
    """
    import subprocess

    d = tmp_path / "dist"
    d.mkdir()
    for f in ("hover_cells.bin", "reading_parents.bin"):
        (d / f).write_bytes(b"layout")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def run(remote_hash: str) -> int:
        ssh = bin_dir / "ssh"
        ssh.write_text(f"#!/bin/bash\necho '{remote_hash}  x'\n")
        ssh.chmod(0o755)
        script = "DEPLOY_HOST=h\nDEPLOY_ROOT=/r\n" + _bash_fn("layouts_identical") + "layouts_identical\n"
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=tmp_path,
                              env={"PATH": f"{bin_dir}:/usr/bin:/bin"}).returncode

    import hashlib

    same = hashlib.sha256(b"layout").hexdigest()
    assert run(same) == 0
    assert run("0" * 64) == 1
