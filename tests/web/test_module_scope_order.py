"""A module-scope listener must not reach a binding declared below it.

`web/app.js` is an ES module with a top-level `await` for the globe's load
(`await Promise.race([...])`). Listeners registered ABOVE that await keep firing
while the module is suspended at it -- a `resize` from an Android URL bar
collapsing is the common one -- and any module-level `let`/`const` they reach is
still in its temporal dead zone. The read throws `ReferenceError: Cannot access
'x' before initialization` out of an uncaught listener, `boot.js` catches it and
sets `body.fatal`, and `index.html` turns that into `display: none` over the
whole side rail. The page looks dead. There is no console error left to find
afterwards, which is why CLAUDE.md's deploy rule says to open the page.

This has now happened three times in this project: `SMALL` (U25, a blank page),
`bandMark` (recorded in its own comment), and `bandSpan` (cycle 9, reproduced in
node). The rule is that a module-level binding any module-scope listener can
reach is declared in the state block at the top of the file.

The guard walks the call graph from every handler registered before the first
top-level await and fails on any module-level binding it reaches whose
declaration line is below the registration.

Mutation performed and reverted before committing: move `let bandSpan = null`
back below `markSpan()` -> red, naming bandSpan, markSpan and the resize
registration.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web" / "app.js"

#: `let a = 1, b = null;` at column 0. Captures the whole declarator list so
#: every name in it is found, not just the first.
_DECL = re.compile(r"^(?:let|const|var)\s+([^=;\n]+?)(?:\s*=|;)", re.M)
_NAME = re.compile(r"[A-Za-z_$][\w$]*")
#: A function declaration at column 0, i.e. one hoisted to module scope.
_FUNC = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M)
#: The first top-level `await`, which is where the module suspends.
_AWAIT = re.compile(r"^await\s", re.M)
#: Listener registrations at column 0: `addEventListener(...)`,
#: `foo.addEventListener(...)`, `map.on(...)`, `document.fonts.ready.then(...)`.
_LISTEN = re.compile(
    r"^(?:[\w.$?]+\.)?(?:addEventListener|on|then)\(", re.M)


def _strip(src: str) -> str:
    """Blank out comments and string literals.

    Cycle 6's standing rule: an assertion over source text that a comment can
    satisfy is vacuous. Here the risk is the reverse -- a binding name inside a
    comment or a string would be read as a reference -- but the fix is the same.
    Lengths are preserved so every offset still maps to its original line.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if src[k] != "\n":
                    out[k] = " "
            i = j
        elif c in "\"'`":
            # A ' or " string cannot contain a raw newline in JavaScript, so
            # terminating at one bounds any mis-detection (an apostrophe in a
            # regex literal, say) to the line it started on. A runaway would
            # blank hundreds of real declarations and make this guard vacuous.
            q, multiline, i = c, c == "`", i + 1
            out[i - 1] = " "
            while i < n and src[i] != q:
                if src[i] == "\n" and not multiline:
                    break
                if src[i] == "\\":
                    out[i] = " "
                    i += 1
                if i < n and src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n and src[i] == q:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def _bodies(src: str) -> dict[str, tuple[int, int]]:
    """Byte span of every module-scope function declaration's body."""
    spans: dict[str, tuple[int, int]] = {}
    for m in _FUNC.finditer(src):
        start = src.find("{", m.end())
        if start < 0:
            continue
        depth, i = 0, start
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans[m.group(1)] = (start, i)
    return spans


def test_no_module_scope_listener_reaches_a_binding_declared_below_it() -> None:
    raw = APP.read_text(encoding="utf-8")
    src = _strip(raw)

    await_at = _AWAIT.search(src)
    assert await_at, "app.js no longer has a top-level await; re-read this guard"
    await_line = _line_of(src, await_at.start())

    decls: dict[str, int] = {}
    for m in _DECL.finditer(src):
        for name in _NAME.findall(m.group(1)):
            decls.setdefault(name, _line_of(src, m.start()))
    assert "bandSpan" in decls, "bandSpan is no longer a module-level binding"

    funcs = _bodies(src)
    assert "markSpan" in funcs and "refreshScale" in funcs

    # Seed: every handler registered at module scope above the await.
    seeds: dict[str, int] = {}
    for m in _LISTEN.finditer(src):
        line = _line_of(src, m.start())
        if line >= await_line:
            continue
        end = src.find("\n", m.start())
        call = src[m.start(): len(src) if end < 0 else end]
        for name in _NAME.findall(call):
            if name in funcs:
                seeds.setdefault(name, line)
    assert seeds, "no module-scope listener found above the await"

    # Transitive closure over module-scope function calls.
    reach: dict[str, int] = dict(seeds)
    queue = list(seeds)
    while queue:
        fn = queue.pop()
        lo, hi = funcs[fn]
        for name in set(_NAME.findall(src[lo:hi])):
            if name in funcs and name not in reach:
                reach[name] = reach[fn]
                queue.append(name)

    late: list[str] = []
    for fn, registered in sorted(reach.items()):
        lo, hi = funcs[fn]
        for name in sorted(set(_NAME.findall(src[lo:hi]))):
            decl = decls.get(name)
            # Below the AWAIT, not below the registration: a binding declared
            # between the two is already initialised by the time the module
            # suspends, because nothing can fire during synchronous evaluation.
            # `map` is the one that matters -- it is created below every
            # listener and above the await, and flagging it would be noise.
            if decl is not None and decl > await_line and decl > registered:
                late.append(
                    f"{name} (declared line {decl}) is read by {fn}(), which a "
                    f"module-scope listener at line {registered} can reach while "
                    f"the module is suspended at the top-level await on line "
                    f"{await_line}")
    assert not late, (
        "a module-scope listener can reach a binding in its temporal dead zone; "
        "declare these in the state block at the top of web/app.js:\n  "
        + "\n  ".join(late))
