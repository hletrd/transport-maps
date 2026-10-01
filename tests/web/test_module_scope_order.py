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

What the guard could not see until cycle 16: a listener registration was
truncated at its first newline, so `map.on("error", (e) => {` contributed the
identifiers `map`, `on` and `e` and nothing else. That is the ONLY listener in
app.js registered above the await besides the one-line `resize` one, i.e. the
only one that can fire during the 20-second load window, and its callback calls
`noteTileTrouble`, which calls `announce`. Measured on the unmodified file, the
old seeding gave `{layoutForSize, paintLegend, paintScale, scheduleScaleRefresh}`
with `noteTileTrouble` and `announce` BOTH unreached. Cycle 15 wired
`announce(say)` into that callback and it is safe only because `announce`
happens to be a hoisted `function` rather than an arrow `const` like
`originName` two lines above it -- a coin toss the guard was not watching.
Seeding now uses the balanced-paren span of the registration.

Mutations performed and reverted, with measured results:

- move `let bandSpan = null` back below `markSpan()` -> red, naming bandSpan,
  markSpan and the resize registration. (cycle 9)
- cycle 16, web/app.js: rewrite the hoisted `function announce(text) {` at
  line 2974 as `const announce = (text) => {` -- an arrow const declared 2,184
  lines BELOW the await, exactly the shape `originName` already has on the line
  above. Before the seeding fix: 1 passed (the guard never reached
  `noteTileTrouble`, so it never looked at `announce`). After: 1 failed,
  "announce (declared line 2974) is read by noteTileTrouble(), which a
  module-scope listener at line 693 can reach". Reverted.
- cycle 16, this file: restore the first-newline truncation (`end =
  src.find("\\n", m.start())`) -> the `noteTileTrouble in seeds` assertion goes
  red, 1 failed. Reverted.

The LATE list is EMPTY on the real app.js after the fix: `announce`,
`tileTroubleFor`, `WATER_SOURCE` and `active` are all declared above the await
or above the registration. So cycle 16 found a blind guard, not a live defect.
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
#: A bare call at column 0, e.g. `layoutForSize();`.
_CALL = re.compile(r"^([A-Za-z_$][\w$]*)\(", re.M)


def _call_span(src: str, open_paren: int) -> int:
    """Offset just past the `)` matching the `(` at `open_paren`.

    A listener registration is not one line. `map.on("error", (e) => {` opens a
    twenty-line callback, and truncating the registration at its first newline
    -- which this guard did until cycle 16 -- reads only `map.on(`, whose only
    identifiers are `map`, `on` and `e`. None of them is a module-scope
    function, so THE ONE LISTENER IN app.js THAT FIRES DURING THE 20-SECOND
    LOAD WINDOW seeded nothing at all and its whole call graph
    (`noteTileTrouble` -> `announce`) was never walked.

    `src` has already been through `_strip`, so every paren inside a comment or
    a string literal is a space and cannot unbalance the count.
    """
    depth, i, n = 0, open_paren, len(src)
    while i < n:
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


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

    # Seed: every handler registered at module scope above the await, AND every
    # module-scope function CALLED above it. Both reach a binding declared below
    # the await -- the listener when the module suspends there, the direct call
    # before it is ever reached.
    seeds: dict[str, int] = {}
    listeners_above = 0
    for m in _LISTEN.finditer(src):
        line = _line_of(src, m.start())
        if line >= await_line:
            continue
        listeners_above += 1
        # The whole registration, callback body included -- not its first line.
        call = src[m.start():_call_span(src, m.end() - 1)]
        for name in _NAME.findall(call):
            if name in funcs:
                seeds.setdefault(name, line)
    for m in _CALL.finditer(src):
        line = _line_of(src, m.start())
        if line < await_line and m.group(1) in funcs:
            seeds.setdefault(m.group(1), line)
    assert seeds, "no module-scope listener or call found above the await"
    # app.js has exactly two registrations above the await: the one-line
    # `resize` and the multi-line `map.on("error", ...)`. If the second ever
    # stops contributing a seed the guard is back to reading `map.on(` and
    # walking nothing, which is how it stayed green for a cycle.
    assert listeners_above >= 2, (
        f"only {listeners_above} module-scope listener(s) found above the await; "
        "app.js has changed shape -- re-read this guard before trusting it")
    assert "noteTileTrouble" in seeds, (
        "the map.on(\"error\", ...) callback no longer seeds noteTileTrouble. That "
        "listener is the only one that fires during the 20-second load window, so "
        "a seeding bug there makes this whole guard blind exactly where it matters")

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


# --- C12-11b: the module body below the await --------------------------------
#
# Everything above walks from LISTENERS. The module body itself is just as able
# to reach a binding in its temporal dead zone, and more directly: a statement
# runs top to bottom, so any module-level `let`/`const` it reads -- itself, or
# through a function it calls -- must be declared ABOVE it. Cycle 12 wrote
# exactly that (`for (const c of cities) { ... countryName(c.country) ... }`
# above `const countryName = (() => ...)()`) and caught it by reading, because
# the walk above starts at listeners and never looked at module-body code.
#
# What runs NOW and what runs LATER is decided per arrow function:
#
# - an arrow passed to an array method that calls it synchronously, or to
#   `new Promise`, or invoked on the spot (`(() => { ... })()`), runs now;
# - every other arrow -- a listener, a `.then`, a `setTimeout`, an arrow
#   stored in a `const` -- runs later, and its body is dropped from the
#   statement's "now" text. Below the last top-level await "later" means after
#   evaluation has finished, when every binding exists. Above it, the walk at
#   the top of this file is what covers listeners firing during the suspension.
#
# Functions a statement CALLS are walked transitively, through `function`
# declarations and through arrow consts alike, with the same now/later split
# applied to their bodies.

#: Callee names that invoke an arrow argument before returning.
_SYNC_CALLEES = re.compile(
    r"(?:\.(?:forEach|map|filter|some|every|find|findIndex|findLast|reduce|"
    r"sort|flatMap|from)|new\s+Promise)\s*$")
#: An identifier that is a READ of a binding: not a property after `.` (but a
#: spread `...name` is a read).
_REF = re.compile(r"(?:(?<=\.\.\.)|(?<![.\w$]))([A-Za-z_$][\w$]*)")
#: The same, followed by a call's open paren.
_CALLED = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")


def _code(src: str) -> str:
    """Comments and string literals blanked, offsets kept -- like `_strip`,
    except that a template's `${...}` stays as the code it is. `_strip` blanks
    the whole template, which is right for the listener walk's purposes and
    would hide `${countryName(c.country)}` -- the cycle-12 read -- from this one.
    """
    from tests.web import _js

    out = list(src)

    def blank(lo: int, hi: int) -> None:
        for i in range(lo, hi):
            if out[i] != "\n":
                out[i] = " "

    def walk(lo: int, hi: int) -> None:
        j = lo
        while j < hi:
            k = _js.skip(src, j)
            if k == j:
                j += 1
                continue
            if src[j] == "`":
                # Blank the literal text; recurse into each ${...}.
                i = j
                while i < k:
                    m = src.find("${", i, k)
                    if m < 0:
                        blank(i, k)
                        break
                    blank(i, m + 2)
                    end = _js.close(src, m + 1)
                    walk(m + 2, end)
                    i = end
            elif src[j] in "\"'/":
                blank(j, k)
            j = k

    walk(0, len(src))
    return "".join(out)


def _groups(src: str, lo: int, hi: int) -> dict[int, int]:
    """Every bracket pair inside [lo, hi), as {open: close}, literals skipped."""
    from tests.web import _js

    pairs: dict[int, int] = {}
    stack: list[int] = []
    j = lo
    while j < hi:
        k = _js.skip(src, j)
        if k != j:
            j = k
            continue
        if src[j] in "([{":
            stack.append(j)
        elif src[j] in ")]}" and stack:
            pairs[stack.pop()] = j
        j += 1
    return pairs


def _arrows(src: str, lo: int, hi: int) -> list[tuple[int, int, int]]:
    """(params_start, body_start, body_end) of every arrow in [lo, hi)."""
    from tests.web import _js

    pairs = _groups(src, lo, hi)
    closes = {c: o for o, c in pairs.items()}
    out = []
    j = lo
    while j < hi:
        k = _js.skip(src, j)
        if k != j:
            j = k
            continue
        if src.startswith("=>", j):
            p = j - 1
            while src[p] in " \t\n":
                p -= 1
            if src[p] == ")":
                ps = closes[p]
            else:
                ps = p
                while src[ps - 1].isalnum() or src[ps - 1] in "_$":
                    ps -= 1
            b = j + 2
            while src[b] in " \t\n":
                b += 1
            if src[b] == "{":
                e = pairs[b] + 1
            else:
                # An expression body runs to the `,` `;` or closing bracket of
                # whatever it is nested in.
                e = b
                while e < hi:
                    k = _js.skip(src, e)
                    if k != e:
                        e = k
                        continue
                    if src[e] in "([{":
                        e = pairs[e] + 1
                        continue
                    if src[e] in ",;)]}":
                        break
                    e += 1
            out.append((ps, b, e))
        j += 1
    return out


def _now_text(src: str, lo: int, hi: int) -> str:
    """src[lo:hi] with the bodies of arrows that run LATER blanked out."""
    pairs = _groups(src, lo, hi)
    chars = list(src[lo:hi])
    for ps, b, e in _arrows(src, lo, hi):
        enclosing = [(o, c) for o, c in pairs.items() if o < ps < c and src[o] == "("]
        sync = False
        if enclosing:
            o, c = max(enclosing)
            before = src[lo:o]
            after = src[c + 1:c + 3].lstrip()
            iife = src[o + 1:ps].strip() == "" and after.startswith("(")
            sync = bool(_SYNC_CALLEES.search(before)) or iife
        if not sync:
            for i in range(b - lo, e - lo):
                if chars[i] != "\n":
                    chars[i] = " "
    return "".join(chars)


def _module_statements(src: str) -> list[tuple[int, int]]:
    """[start, end) of every top-level statement: each begins on a column-0
    line at bracket depth 0 and runs to the next one."""
    from tests.web import _js

    starts = []
    j = 0
    while j < len(src):
        k = _js.skip(src, j)
        if k != j:
            j = k
            continue
        c = src[j]
        if (j == 0 or src[j - 1] == "\n") and (c.isalpha() or c in "_$"):
            starts.append(j)
        if c in "([{":
            j = _js.close(src, j) + 1
            continue
        j += 1
    return list(zip(starts, starts[1:] + [len(src)], strict=True))


_ARROW_CONST = re.compile(r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?=[(\w$])")


def _arrow_const(src: str, lo: int, hi: int) -> str | None:
    """The name, if [lo, hi) is `const NAME = (...) => ...` -- a definition,
    whose body runs only when it is called. An IIFE is not one."""
    from tests.web import _js

    m = _ARROW_CONST.match(src, lo)
    if not m:
        return None
    p = m.end()
    if src[p] == "(":
        p = _js.close(src, p) + 1
    else:
        while src[p].isalnum() or src[p] in "_$":
            p += 1
    return m.group(1) if src[p:p + 4].lstrip().startswith("=>") else None


def _late_reads(raw: str, reached: dict[str, set[str]] | None = None) -> list[str]:
    code = _code(raw)
    decls: dict[str, int] = {}
    for m in _DECL.finditer(code):
        for name in _NAME.findall(m.group(1)):
            decls.setdefault(name, _line_of(raw, m.start()))

    callables: dict[str, tuple[int, int]] = {}
    immediate: list[tuple[int, int]] = []
    for lo, hi in _module_statements(raw):
        fm = _FUNC.match(raw, lo)
        if fm:
            callables[fm.group(1)] = (lo, hi)
            continue
        name = _arrow_const(raw, lo, hi)
        if name:
            callables[name] = (lo, hi)
            continue
        immediate.append((lo, hi))

    def reads(lo: int, hi: int, *, whole_arrow: bool = False) -> tuple[set[str], set[str]]:
        """(names read, names CALLED) by the code in [lo, hi) that runs now."""
        if whole_arrow:
            # Calling an arrow const runs ITS body, which _now_text drops.
            ps, b, e = _arrows(raw, lo, hi)[0]
            text = raw[lo:b] + _now_text(raw, b, e) + raw[e:hi]
        else:
            text = _now_text(raw, lo, hi)
        # Comments and literals out, by position: _code preserves offsets.
        text = "".join(t if k != " " or t == "\n" else " "
                       for t, k in zip(text, code[lo:hi], strict=True))
        return set(_REF.findall(text)), set(_CALLED.findall(text))

    funcs = {m.group(1) for m in _FUNC.finditer(raw)}
    body = {n: reads(lo, hi, whole_arrow=n not in funcs)
            for n, (lo, hi) in callables.items()}

    late = []
    for lo, hi in immediate:
        line = _line_of(raw, lo)
        # A name read is checked; a callable is walked only where it is CALLED.
        # Passing `originDragEnd` to `.on(...)` reads it -- a TDZ error if it
        # were a `const` below -- but runs none of its body.
        read, called = reads(lo, hi)
        seen = dict.fromkeys(read, "this statement")
        queue = [n for n in called if n in callables]
        walked = set(queue)
        while queue:
            fn = queue.pop()
            fn_read, fn_called = body[fn]
            for name in fn_read:
                seen.setdefault(name, f"{fn}()")
            for name in fn_called:
                if name in callables and name not in walked:
                    walked.add(name)
                    queue.append(name)
        if reached is not None:
            reached[raw[lo:raw.index("\n", lo)]] = set(seen)
        for name, via in sorted(seen.items()):
            decl = decls.get(name)
            if decl is not None and decl > line:
                late.append(f"{name} (declared line {decl}) is read by {via}, which the "
                            f"module body runs at line {line} -- before line {decl}")
    return late


def test_no_module_body_statement_reaches_a_binding_declared_below_it() -> None:
    """C12-11b. The module body, every statement of it, above the await and
    below, walked through every function it calls.

    Mutation performed and reverted: move the `for (const c of cities)`
    search-key loop back above `const countryName = (() => ...)()` -- the
    cycle-12 near-miss, which the listener walk above stays green on -> red,
    "countryName (declared line 3678) is read by this statement". And move
    the module-level `render();` up to just below `paintSea();` -> red through
    the call graph, "FOLD_DROP ... is read by fold()" among eight. Both leave
    the listener walk above green. Measured on HEAD: nothing late.
    """
    raw = APP.read_text(encoding="utf-8")
    statements = _module_statements(raw)
    # The guard on the guard: app.js has hundreds of top-level statements, and
    # a scanner that lost its place would find a handful and pass.
    assert len(statements) > 300, f"only {len(statements)} module statements found"
    reached: dict[str, set[str]] = {}
    late = _late_reads(raw, reached)
    # And that it reads what it must: the cycle-12 loop reads countryName in a
    # template's `${...}`, and `render();` reaches `fold`'s constants only
    # through two calls. Either going missing means the walk has gone blind.
    assert "countryName" in reached["for (const c of cities) {"], (
        "the search-key loop no longer reads countryName; the walk lost the "
        "template interpolation, or the loop moved -- re-read this guard")
    assert {"cities", "FOLD_DROP"} <= reached["render();"], (
        "render(); no longer reaches cities and FOLD_DROP through the call graph")
    assert not late, (
        "module-body code reads a binding in its temporal dead zone -- a "
        "ReferenceError at load, which boot.js turns into a blank page:\n  "
        + "\n  ".join(late))
