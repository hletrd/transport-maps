"""Slicing `web/app.js` for tests: one matcher that knows what a brace is.

Every node-run test in this directory lifts real source out of app.js and runs
it, which is only as honest as the slice. Until cycle 18 each file carried its
own slicer, and most took `APP.index("{", start)` as the body brace and counted
every `{` and `}` after it. Two ways that goes wrong, both silent:

- A DESTRUCTURED PARAMETER opens and closes a brace before the body --
  `paintOrigin(o, { keepZoom = false } = {})` -- so the "body" is the
  signature alone, and `assert "x" in body` over it passes for nothing (C12-10).
- A brace inside a string, a template, a comment or a regex literal is counted
  as code. `"{"` in a message, or a comment that quotes a block, ends the slice
  early or runs it past the function's end.

So: the parameter list is walked to its close before the body brace is looked
for, and every bracket is matched by a scanner that skips `//` and `/* */`
comments, `'` and `"` strings, templates (with `${...}` nested to any depth)
and regex literals. Regex detection is the usual heuristic -- a `/` is a regex
where an operand may start, i.e. not after an identifier, a number, a closing
bracket or a string -- which is right for every `/` in app.js and is checked by
`tests/web/test_js_slicer.py` against the shapes that defeat it.
"""

from __future__ import annotations

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

_CLOSER = {"(": ")", "[": "]", "{": "}"}
#: Keywords after which a `/` starts a regex rather than dividing.
_REGEX_AFTER = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                "void", "throw", "case", "do", "else", "yield", "await"}


def _line(src: str, i: int) -> int:
    return src.count("\n", 0, i) + 1


def _regex_may_start(src: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    c = src[j]
    if c.isalnum() or c in "_$":
        k = j
        while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
            k -= 1
        return src[k + 1:j + 1] in _REGEX_AFTER
    return c not in ")]}\"'`"


def skip(src: str, i: int) -> int:
    """If a comment, string, template or regex literal starts at `i`, the
    offset just past it; otherwise `i` unchanged."""
    c = src[i]
    nxt = src[i + 1] if i + 1 < len(src) else ""
    try:
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            return len(src) if j < 0 else j
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                raise IndexError
            return j + 2
        if c in "\"'":
            j = i + 1
            while src[j] != c:
                if src[j] == "\n":
                    raise IndexError
                j += 2 if src[j] == "\\" else 1
            return j + 1
        if c == "`":
            j = i + 1
            while src[j] != "`":
                if src[j] == "\\":
                    j += 2
                elif src.startswith("${", j):
                    j = close(src, j + 1) + 1
                else:
                    j += 1
            return j + 1
        if c == "/" and _regex_may_start(src, i):
            j, in_class = i + 1, False
            while in_class or src[j] != "/":
                if src[j] == "\n":
                    raise IndexError
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                j += 1
            j += 1
            while j < len(src) and src[j].isalpha():
                j += 1
            return j
    except IndexError:
        raise AssertionError(
            f"unterminated {c!r} literal or comment at app.js line {_line(src, i)}"
        ) from None
    return i


def close(src: str, i: int) -> int:
    """Offset of the bracket that closes the one at `i`."""
    assert src[i] in _CLOSER, f"{src[i]!r} at line {_line(src, i)} is not a bracket"
    stack = [_CLOSER[src[i]]]
    j = i + 1
    while j < len(src):
        k = skip(src, j)
        if k != j:
            j = k
            continue
        c = src[j]
        if c in _CLOSER:
            stack.append(_CLOSER[c])
        elif c in ")]}":
            want = stack.pop()
            assert c == want, (
                f"{c!r} at line {_line(src, j)} closes a bracket expecting {want!r}")
            if not stack:
                return j
        j += 1
    raise AssertionError(f"bracket at line {_line(src, i)} is never closed")


def find(src: str, chars: str, start: int) -> int:
    """First offset at or after `start` holding one of `chars` as CODE -- not
    inside a comment, a string, a template or a regex literal."""
    j = start
    while j < len(src):
        k = skip(src, j)
        if k != j:
            j = k
            continue
        if src[j] in chars:
            return j
        j += 1
    raise AssertionError(f"none of {chars!r} after line {_line(src, start)}")


def function(name: str, src: str = APP, *, with_async: bool = False) -> str:
    """The verbatim source of `function NAME(...) { ... }`.

    `with_async` keeps a leading `async ` keyword, for a function whose body
    awaits and would not parse without it.
    """
    start = src.index(f"function {name}(")
    if with_async and src[max(0, start - 6):start] == "async ":
        start -= 6
    params = src.index("(", start)
    body = find(src, "{", close(src, params) + 1)
    end = close(src, body)
    out = src[start:end + 1]
    assert src[body + 1:end].strip(), f"function {name} sliced to an empty body:\n{out}"
    return out


def block(anchor: str, src: str = APP, *, opener: str = "{", after: str = "") -> str:
    """From `anchor` to the bracket closing the first `opener` that follows it
    (or follows `after`, when given: `after="=>"` takes an arrow's body)."""
    start = src.index(anchor)
    i = src.index(after, start) + len(after) if after else start
    return src[start:close(src, find(src, opener, i)) + 1]


def statement(anchor: str, src: str = APP) -> str:
    """From `anchor` to the first `;` outside every bracket and literal --
    a `const NAME = ...;` declaration however many lines it spans."""
    start = src.index(anchor)
    j = start
    while j < len(src):
        k = skip(src, j)
        if k != j:
            j = k
            continue
        c = src[j]
        if c in _CLOSER:
            j = close(src, j) + 1
            continue
        if c == ";":
            return src[start:j + 1]
        j += 1
    raise AssertionError(f"{anchor!r} has no terminating semicolon")
