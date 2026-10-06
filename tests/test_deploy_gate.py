"""deploy/worldmap-deploy-gate.sh: the forced command of the build host's key.

The key sits on a shared machine, so the gate must accept exactly what
scripts/deploy_verify.sh sends the web host and refuse everything else. Both
halves are tested against the deploy script's OWN command strings, read out of
it: a new remote check in deploy_verify.sh turns this red until the gate
learns it, instead of failing a deploy halfway.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "deploy" / "worldmap-deploy-gate.sh"
DEPLOY = (ROOT / "scripts" / "deploy_verify.sh").read_text(encoding="utf-8")
WRAPPER = (ROOT / "scripts" / "deploy_from_h200.sh").read_text(encoding="utf-8")
DEPLOY_ROOT = "/var/www/worldmap"


def _quoted_after(text: str, start: int) -> str:
    """The bash double-quoted word that begins at or after `start`, raw."""
    i = start
    while text[i] in " \t\\\n":
        i += 1
    assert text[i] == '"', text[start:start + 80]
    j = i + 1
    while text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    return text[i:j + 1]


def _remote_commands() -> list[str]:
    """Every command deploy_verify.sh hands `ssh ... "$DEPLOY_HOST"`, as the
    web host receives it (expanded by bash, for each file the loop names)."""
    words = [_quoted_after(DEPLOY, m.end())
             for m in re.finditer(r'ssh -o BatchMode=yes "\$DEPLOY_HOST"', DEPLOY)]
    assert len(words) >= 4, "deploy_verify.sh's remote checks have moved; re-derive this test"
    out = []
    for word in words:
        for f in ("hover_cells.bin", "reading_parents.bin"):
            got = subprocess.run(["bash", "-c", f'DEPLOY_ROOT={DEPLOY_ROOT}; f={f}; printf %s {word}'],
                                 capture_output=True, text=True, check=True).stdout
            if got not in out:
                out.append(got)
    return out


def _gate(command: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the gate as sshd would, with df/sha256sum/python3 stubbed to say so."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    for name in ("df", "sha256sum", "python3"):
        p = stubs / name
        # df's answer goes through `awk 'NR==2{print $4}'`, so it is shaped
        # like df's: a header, then the free figure in the fourth column.
        body = ("echo 'Filesystem 1024-blocks Used Available'; echo 'x 1 2 STUB-df'"
                if name == "df" else f"echo STUB-{name}")
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "SSH_ORIGINAL_COMMAND": command}
    return subprocess.run(["sh", str(GATE)], capture_output=True, text=True, env=env)


def test_every_check_deploy_verify_sends_is_let_through(tmp_path):
    """Mutation performed and reverted: the df pattern's `NR==2` changed to
    `NR==1` in the gate -> red."""
    commands = _remote_commands()
    assert any(c.startswith("df -Pk") for c in commands)
    assert any("hover_cells.bin" in c for c in commands) and any("meta.json" in c for c in commands)
    for c in commands:
        done = _gate(c, tmp_path)
        assert done.returncode == 0 and "STUB-" in done.stdout, (c, done.stderr)


@pytest.mark.parametrize("command", [
    "",
    "id",
    "bash",
    "cat /etc/passwd",
    "sha256sum '/etc/shadow'",
    f"df -Pk '{DEPLOY_ROOT}' | awk 'NR==2{{print $4}}'; id",
    f"sha256sum '{DEPLOY_ROOT}/hover_cells.bin' && rm -rf {DEPLOY_ROOT}",
    "rsync --daemon",
])
def test_anything_else_is_refused_and_nothing_runs(command, tmp_path):
    """Mutation performed and reverted: the default branch made
    `exec sh -c "$SSH_ORIGINAL_COMMAND"` -> red."""
    done = _gate(command, tmp_path)
    assert done.returncode != 0 and "refused" in done.stderr
    assert "STUB-" not in done.stdout


def test_rsync_is_handed_to_rrsync_confined_to_the_web_root():
    body = GATE.read_text(encoding="utf-8")
    m = re.search(r'"rsync --server "\*\)\s*\n\s*exec (\S+) "\$ROOT"', body)
    assert m and m.group(1) == "/usr/bin/rrsync"
    assert re.search(r"^ROOT=/var/www/worldmap$", body, re.M)


def test_only_the_build_host_wrapper_hands_the_browser_stage_away():
    """BROWSER_VERIFY=by-caller skips the page check in deploy_verify.sh; the
    one caller that sets it must run browser_verify.sh itself, last, and
    exit with its status.

    Mutation performed and reverted: the wrapper's final `exec
    .../browser_verify.sh` removed -> red.
    """
    assert re.search(r'if \[ "\$\{BROWSER_VERIFY:-\}" = "by-caller" \]; then', DEPLOY)
    assert re.search(r'^\s+"\$ROOT/scripts/browser_verify\.sh" "\$SITE_URL/"$', DEPLOY, re.M), \
        "the default path no longer opens a browser"
    def code_of(p):
        return "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
    setters = [p for p in (ROOT / "scripts").glob("*.sh") if "BROWSER_VERIFY=by-caller" in code_of(p)]
    assert setters == [ROOT / "scripts" / "deploy_from_h200.sh"]
    code = [ln for ln in WRAPPER.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert code[-1].strip() == 'exec "$ROOT/scripts/browser_verify.sh" "$SITE_URL/"'
    assert WRAPPER.index("BROWSER_VERIFY=by-caller") < WRAPPER.index('exec "$ROOT/scripts/browser_verify.sh"')
