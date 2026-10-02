"""docs/contract.md against the code it describes.

The contract document names every `index.json` field and every per-origin
file. Both sets are derived here from the CODE -- the emitter's source and
`progress.SUFFIXES` -- and from the DOCUMENT's own tables, and each must equal
the other. A field added to `write_index` without a row, or a row left behind
for a field that was removed, turns this red.

Mutations performed (2026-10-02), each RED, each restored:
  - delete the `contractVersion` row from the index.json table  -> RED (doc side)
  - add `"probe": 1` to write_index's payload literal            -> RED (code side)
  - delete the `.over.bin` row from the per-origin table          -> RED
  - add ".probe" to progress.SUFFIXES                             -> RED
  - delete the `water.pmtiles` row from the shared table          -> RED
"""

from __future__ import annotations

import ast
import re

from transport_maps import config, progress

DOC = config.ROOT / "docs" / "contract.md"
INDEX_SRC = config.ROOT / "src" / "transport_maps" / "emit" / "index.py"


def _section(title: str) -> str:
    """The text of one `##`/`###` section, up to the next heading of any level
    at or above it. Scoped explicitly, so a key named in prose elsewhere in the
    file cannot satisfy a table row's absence."""
    text = DOC.read_text(encoding="utf-8")
    m = re.search(rf"^(#+) {re.escape(title)}\s*$", text, re.M)
    assert m, f"docs/contract.md has no section {title!r}"
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _first_column_names(section: str) -> set[str]:
    """Every backticked name in the FIRST cell of each table row."""
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        first = line.split("|")[1]
        names.update(re.findall(r"`([^`]+)`", first))
    return names


def _write_index_keys() -> set[str]:
    """Every top-level key write_index can put in index.json, read from its
    source: the payload literal, every `payload["k"] = ...`, and the identity
    dict that `payload.update(identity)` merges in (build_identity's return)."""
    tree = ast.parse(INDEX_SRC.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    keys: set[str] = set()
    for node in ast.walk(funcs["write_index"]):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "payload" and isinstance(node.value, ast.Dict):
                    keys |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
                if (isinstance(t, ast.Subscript) and getattr(t.value, "id", None) == "payload"
                        and isinstance(t.slice, ast.Constant)):
                    keys.add(t.slice.value)
    ret = next(n for n in ast.walk(funcs["build_identity"]) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict), "build_identity no longer returns a dict literal"
    keys |= {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}
    return keys


def test_every_index_json_field_has_a_row_and_every_row_a_field():
    code = _write_index_keys()
    assert len(code) > 20, f"only {len(code)} keys parsed from write_index; re-derive this test"
    doc = _first_column_names(_section("`index.json`"))
    assert code - doc == set(), f"index.json fields with no row in docs/contract.md: {code - doc}"
    assert doc - code == set(), f"docs/contract.md rows for fields write_index no longer writes: {doc - code}"


def test_every_per_origin_file_has_a_row_and_every_row_a_file():
    doc = _first_column_names(_section("Per origin: `dist/origins/{slug}.*`"))
    code = set(progress.SUFFIXES)
    assert code - doc == set(), f"per-origin files with no row: {code - doc}"
    assert doc - code == set(), f"rows for files cli._solve_one no longer writes: {doc - code}"


def test_every_shared_file_the_deploy_requires_has_a_row():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_dist", config.ROOT / "scripts" / "check_dist.py")
    check_dist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_dist)
    doc = _first_column_names(_section("Shared, once per site"))
    required = {"index.json", "hover_cells.bin", "reading_parents.bin", *check_dist.REQUIRED_EXTRAS}
    assert required - doc == set(), f"shared files with no row: {required - doc}"
