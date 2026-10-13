"""A link made with a slug the roster has since corrected still departs.

The audit of 2026-10-12 renamed changsha-cn to kaiping and dropped puyang and
changzhi-cn (data/origins.toml). `FORMER_SLUGS` in web/app.js maps each to
the city its link named.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib

import pytest

from tests.web import _js
from transport_maps import config

ROSTER = {o["slug"] for o in tomllib.loads(
    (config.ROOT / "data" / "origins.toml").read_text(encoding="utf-8"))["origin"]}


def _table() -> dict[str, str]:
    body = _js.statement("const FORMER_SLUGS")
    return dict(re.findall(r'\["([a-z0-9_-]+)", "([a-z0-9_-]+)"\]', body))


def test_every_former_slug_is_gone_and_points_at_a_city_that_is_not():
    """A former slug still in the roster would shadow nothing and mean a
    rename was undone; a target not in it would send the link nowhere.

    Mutation performed and reverted: point puyang at "pujiang" -> RED.
    """
    table = _table()
    assert table == {"changsha-cn": "kaiping", "puyang": "puyang-cn", "changzhi-cn": "changzhi"}
    assert not set(table) & ROSTER, set(table) & ROSTER
    assert set(table.values()) <= ROSTER, set(table.values()) - ROSTER


def test_a_former_slug_resolves_and_a_current_one_wins(tmp_path):
    """Mutation performed and reverted: `bySlug.get(slug) ?? null` (the
    table unread) -> RED."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = f"""
const bySlug = new Map([["kaiping", {{slug: "kaiping"}}], ["changzhi", {{slug: "changzhi"}}],
                        ["puyang-cn", {{slug: "puyang-cn"}}]]);
{_js.statement("const FORMER_SLUGS")}
{_js.function("departureFor")}
console.log(JSON.stringify(["changsha-cn", "puyang", "changzhi-cn", "kaiping", "atlantis",
                            "constructor", ""].map((s) => departureFor(s)?.slug ?? null)));
"""
    out = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["kaiping", "puyang-cn", "changzhi", "kaiping",
                                      None, None, None]
