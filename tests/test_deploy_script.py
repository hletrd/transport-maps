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
                   with_node: bool = True):
    """Run the REAL page_gate with `uv` and `node` stubbed out.

    A pattern assertion cannot see this defect: the whole bug was that pytest
    exits 0 on a skip and the shell therefore carried on. Only the shell can
    show that it now does not.
    """
    import subprocess
    from pathlib import Path

    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "{pytest_summary}"\nexit {pytest_rc}\n')
    uv.chmod(0o755)
    if with_node:
        node = bin_dir / "node"
        node.write_text("#!/bin/sh\nexit 0\n")
        node.chmod(0o755)
    # A PATH holding only the stubs, so a real `node` on the developer's
    # machine cannot make the node-missing case pass by accident.
    script = (f'set -euo pipefail\nPATH="{bin_dir}:/usr/bin:/bin"\n'
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
        assert "SKIPPED rather than ran" in done.stdout, done.stdout
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
