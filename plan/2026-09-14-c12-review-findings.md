# Cycle 12 — what the eleven review lanes found

Companion to `archive/2026-09-14-c12-requested-features.md`. That file holds the three
tasks the owner named; this one holds everything else the review raised, each
either scheduled with a target cycle or deferred with a citation, an unchanged
severity and confidence, a reason and the exit criterion that reopens it.

Sources: `.context/reviews/{code-reviewer,security-reviewer,perf-reviewer,
test-engineer,critic,architect,designer,verifier,tracer,debugger,
document-specialist}.md` and `_aggregate.md`.

---

## C12-1 — the running build dies at origin 970. CRITICAL. **Escalated.**

`CR12-1` + `DBG12-1`, both High confidence, confirmed a third time by direct
execution in the orchestrator.

`data/origins.toml:6251-6256` puts kota-kinabalu at 5.9749, 116.0724. That
point's res-6 cell `8668156e7ffffff` is **absent from both land-mask caches**
(`data/build/land_cells_r6_74c3737a.parquet`, `..._dd95e3b5.parquet`, 4,091,715
cells each; three ring-1 neighbours are land, nearest `8668156efffffff` at
4.2 km). `solve/dijkstra.py:24-29` raises a bare `ValueError`; `GateFailure` is a
`RuntimeError` subclass (`cli.py:200`) and `cli.py:404` catches only
`GateFailure`. Nothing on the path catches `ValueError`.

Origins get **no** nearest-land snap: `_nearest_land` (`graph/nodes.py:120-154`)
has exactly one caller, `_place_airports` at `nodes.py:179`. Airports are
snapped, origins are not. All 1,464 were tested; kota-kinabalu is the only one.

`rebuild19` reaches origin 970 roughly 26 to 33 hours in. No on-disk edit
rescues it — the parent read `origins.toml` into memory at 13:46 and the workers
were forked with the modules imported.

- [x] **C12-1a** Escalated to the owner. Stopping a running build is
      destructive and is not this lane's call.
- [x] **C12-1b** Make `origin_node` snap to the nearest land cell exactly as
      airports do, and raise `GateFailure` rather than `ValueError` when no land
      is within range, so the build names the slug instead of printing a
      traceback. This is what makes a restart safe and does not touch the
      running process.
- [x] **C12-1c** A test over the real `data/origins.toml` that is red before
      the fix and green after. (The original certificate was false, C13-11;
      re-proved 2026-10-02 through `cli._solve_one`, both mutations red.)
- [x] **C12-1d** Land-validate in `scripts/expand_origins.py`, which added the
      911 new origins with no check at all (`DBG12-2`, High).

## C12-2 — the departure list prints raw ISO-2 codes beside country names

`ARCH12-5` (High) + `TR12-4` (Medium), independent. `emit/index.py:334-335`
emits `country` only when `origins.toml` carries it; the 911 new rows do, the
553 legacy rows do not. `cityCountry()` (`app.js:1443-1447`) therefore returns
a raw ISO-2 code for one group and a gazetteer country **name** for the other.
Ambiguous names went 4 → 13 and 8 of the 13 pairs are mixed-source, so the list
reads "London United Kingdom" directly above "London CA". `countryName()`
already exists at `app.js:3001` and is already used for airport rows at `:3084`.

- [x] **C12-2** Route `cityCountry` through `countryName`. One line, plus a test.

## C12-3 — the departure list does not survive 1,464 rows

`PR12-1` (High) + `ARCH12-3` (Medium) + `UX12-10/11/12` (High), three lanes
independently. `render()` (`app.js:3035-3232`) is a full unvirtualised rebuild
with no windowing, no `content-visibility` and no debounce on the `input`
handler (`:3379`).

Measured: 3,318 nodes today → 8,784 at 1,464; 38,357 px of list, which is 175
screens at 390x844 and 378 at 844x390 with a 0.27 px scrollbar thumb. "a"
matches 1,097 of the 1,464 real names, so the **first** keystroke pays near-full
price, as does every backspace to empty. Search matches the city name only — a
country cannot be typed, and only 13 of 1,451 distinct names carry a suffix.

The JS half is not the problem and is recorded here so a later cycle does not
chase it: all 1,464 `lookup()` calls plus the filter and sort measure 2.39 ms.

- [x] **C12-3a** Cap the unfiltered view and say so, with a footer line naming
      the true total. This deletes the scroll-to-current block and `inView()`
      rather than adding code.
- [x] **C12-3b** Fold country into the search key, so a country can be typed.
- [x] **C12-3c** rAF-debounce the input handler.
- [ ] **C12-3d** `content-visibility: auto` on the rows — cycle 13.
- [ ] **C12-3e** Windowed rendering, the real answer if the cap is ever lifted
      — deferred, exit criterion below.

## C12-4 — the headline can read "no scheduled route" over a full itinerary

`TR12-1` (High) + `CR12-2` (High). The tracer **refuted** the "headline reads
res-6, itinerary reads res-4" framing — both come from the same `lookup()` at
`app.js:1882-1896` — and proved a narrower, worse case. When the res-6 slot
holds the padding sentinel (`emit/hover.py:249-250`), `lookup()` returns 65535
while the coarse res-4 value is finite; `usable` at `:2133-2134` goes false, the
headline prints "no scheduled route", `renderRoute` erases the arc at `:2959`,
and the reconciliation note's guard at `:2259` (`reading < MAX_MINUTES`)
excludes exactly this case — so **nothing is said**. Measured at 7.03% of res-6
cells inside flown res-4 cells, 84% of them between 60°S and 60°N.

- [ ] **C12-4** Cycle 13. Not built this cycle: the fix is a change to the
      reading-tier reconciliation that wants its own cycle and its own gate,
      and the remit is explicit that only the three named tasks plus HIGH
      correctness land now. Recorded as scheduled, not deferred.

## C12-5 — `renderPins()` is missing from the reading-tier arrival block

`TR12-2` (High) + `CR12-3` (Medium). `app.js:1611-1617` calls `rereadPointer`,
`renderLegs`, `render`, `renderDeparture` and `refreshScale` but **not**
`renderPins`, so the Route panel's Time row keeps its res-4 value while the
headline moves to res-6. The two tiers differ at 96.4% of land points, median
26 min, p99 301 min.

- [x] **C12-5** One line: add `renderPins()` to that block. HIGH correctness,
      one-line fix, lands this cycle.

## C12-6 — the count gate cannot see a four-digit count

`VER12-3` + `CR12-6` + `DOC12-6`, merged at High. `scripts/check_dist.py:36`
`COUNT_CLAIM = r"\b[0-9]{3} (cities|departure|origin)"` is hardcoded to three
digits. Measured: `553 cities` is caught; `1464 cities`, `1464 origins`,
`1464 departure cities` and `over 1464 cities` are **all missed**. The gate stops
working at exactly this transition, and `deploy/README.md:17-18` documents it as
the thing that prevents a stale count shipping.

- [x] **C12-6** Widen to `[0-9]{1,3}(?:[, ][0-9]{3})*`, and add the four-digit
      cases to its test.

## C12-7 — five visitor-facing strings state the wrong city count

`DOC12` (23 High, 32 of them count staleness) + `UX12-20`. Shipping to visitors:
`web/index.html:7` (meta description), `:15` (og:description), `:23`
(twitter:description), `:33` (JSON-LD name) and `:1099` (`<noscript>`) all say
"more than five hundred cities". `README.md:5` says 553.

- [x] **C12-7a** The five visitor-facing strings and `README.md:5`.
- [x] **C12-7b** The ~26 stale in-code comments naming 553 — cycle 13, deferred
      below. They mislead a reader, not a visitor.
      2026-10-02, PARTIAL: the present-tense ones in `web/app.js`,
      `tests/web/test_search_fold.py` and `test_readout_state.py` now say
      "then"/"at the time" or name no count. Left open for `src/` and
      `scripts/` (`cli.py:478` "553 today", `validate.py:180`,
      `emit/hover.py:226`, `contour/bands.py:28`, `cli.py:522`), which that
      pass was not scoped to touch. DONE 2026-10-02 (e688db1): those six now
      say "every origin"; the dated 553-origin records in `scripts/` and
      `cli.py` are history and stay. Past-tense measurements naming 553 are
      records, not staleness, and stay.

## C12-8 — fixed sleeps in the browser gate break at 1,464 origins

`VER12-1/2` (High). `scripts/browser_verify.sh:96` (`sleep 15`) and `:327`
(`sleep 10`) are the only unconditional cold-load waits, and every data-level
assertion reads straight after them. `index.json` goes 40 KB → ~106 KB and
`render()` builds 1,464 rows. This is the same shape as the three gate failures
the team lead reports, and the same shape as commits `9d7c484` and `5cf7ad2`.
The fix is polling for the condition, never a bigger number.

Two thresholds that do not break but silently weaken: `:144`
`"durations":[1-9][0-9]` asserts only 10 timed rows out of 1,464, and `:147`
`'"departing":1'` is an unanchored substring satisfied by anything from 1000 to
1464.

- [x] **C12-8** Cycle 13. Deferred this cycle with a reason, below: the gate is
      correct against the **currently deployed** 553-origin build, this cycle
      deploys page-only against exactly that build, and rewriting the gate in the
      same cycle that depends on it to verify a deploy is how a weakened gate
      ships. It must be rewritten and proved against the new build.
      *Done 2026-10-02, outside any deploy:* both cold loads poll `wait_until`
      (a 90 s ceiling that sets `fail=1` and names what never arrived) for the
      condition the following reads need -- map style and tiles, every capped
      row timed, the departure label; Tokyo selected with its times landed.
      `check_city_list` replaces both loose greps: exactly one `departing`,
      no blank row, the counts add up to the rows, at least one time, and no
      "no route" in a capped (ranked) list. Proved against the live 1,464-origin
      build (`ALL CHECKS PASSED`, ready after 2 s on both waits);
      `tests/test_deploy_script.py`, twelve mutants.

## C12-9 — `esc()` is disabled in the one harness that exercises it

`SEC12-1` + `TE12-1`. Covered by F1 in the features plan. Recorded here because
it is also the cycle's only security finding above Low.

- [x] **C12-9a** `tests/web/test_esc.py`, seven mutants.
- [x] **C12-9b** Move the escape inside `railVia()` (`app.js:2090-2099`), which
      interpolates OSM station and route names unescaped and is safe only
      because its single call site wraps it. A second call site would be stored
      XSS with the gate green.

---

## Deferred, with exit criteria

Nothing here is a security, correctness or data-loss finding except where a
repo rule is quoted permitting it.

| ID | citation | sev | conf | reason | exit criterion |
|---|---|---|---|---|---|
| C12-3e | `app.js:3035-3232` | High | High | The cap in C12-3a removes the user-visible symptom at a fraction of the risk. Windowing is a rewrite of the list's focus, roving-tabindex and scroll behaviour, all of which have shipped defects before | The cap is lifted, or a measurement shows the capped list over 100 ms on a mid-range phone |
| C12-3d | `app.js` `.results button` | Med | High | Needs a browser measurement to be worth anything, and a browser measurement this cycle competes with the build | `browser_verify.sh` gains a paint-cost probe |
| C12-4 | `app.js:2133-2134`, `:2259` | High | High | Scheduled for cycle 13, not dropped. The remit this cycle is the three named tasks plus HIGH correctness with a bounded fix; this one changes the reading-tier reconciliation and needs its own gate | Cycle 13 opens |
| C12-7b | ~26 sites, `DOC12` list | Med | High | Comments, not visitor-facing copy | Cycle 13 opens |
| C12-8 | `browser_verify.sh:96,327,144,147` | High | High | This cycle's own deploy is verified by this gate against the 553-origin build it is correct for. Rewriting a gate in the cycle that depends on it is how a weakened gate ships | The rebuild lands, or cycle 13 opens, whichever is first |
| PR12-2/3/4/6/17 | `emit/hover.py`, `contour/bands.py`, `graph/nodes.py` | High | Med | ~110 s per origin of origin-independent recomputation, about 9 h of the 39 h build. Cannot be touched while a build is running and cannot be measured while one is | The build finishes or is stopped |
| PR12-5 | 650 MB GeoJSON materialised | High | Med | Same: build-side, build running | As above |
| DBG12-4 | `emit/tiles.py:90` | Med | High | `subprocess.run` with no timeout; a hung tippecanoe hangs the build silently. Build-side | As above |
| DBG12-5 | pids 12633-12640 | Med | High | Eight orphan `build-all` processes, 4 d 19 h old, holding ~10.4 GB of swap. **Killing processes is destructive** — escalated to the owner, not actioned | Owner decides |
| DBG12-6 | `check_dist`, `reindex` | Med | High | Arrays from different builds are byte-identical in length, so nothing detects a mixed `dist/`. Today the 553-vs-1,464 slug-set comparison saves it; that net vanishes once all 1,464 exist once | The rebuild lands |
| DBG12-3 | `cli.py:405` and 4 gates | High | High | Three per-origin gates raise `ValueError`/`RuntimeError` rather than `GateFailure`. C12-1b fixes the one that is live; the other three abort correctly, only with a traceback instead of a slug | Cycle 13 opens |
| SEC12-2 | `deploy_verify.sh:186-191` | Med | High | Prints "CSP header: ABSENT" and exits 0; `test_csp.py` never reads the real nginx conf. Live state verified correct today — all six headers present, CSP byte-identical to the repo | Cycle 13, or any nginx change |
| SEC12 LOW ×8 | see the lane file | Low | — | `esc` missing `'` (latent, no single-quoted sink), `a.href = s.url` scheme unchecked, `MODE_FALLBACK` without `Object.hasOwn`, `np.load` without explicit `allow_pickle=False`, no checksum on the water archives (verified **not** zip-slip), three CSP hardening items | Cycle 13 |
| TE12-2…7, 11 | see the lane file | High/Med | High | Seven vacuous tests with surviving mutants, including `test_ferry_model.py:229-231`, which carries a **false mutation certificate** — the mutation it claims reddens the last line reddens nothing | Cycle 13; this is a CLAUDE.md testing-rule violation and is scheduled, not dropped |
| TE12-8 | `tests/sources/test_cache_provenance.py` | Med | High | Sound, but its `STAMPED` list omits six hashed inputs | Cycle 13 |
| TR12-3 | three rounding conventions | Med | High | Every printed time is floor(true), ~0.5 min optimistic. Consistent and documented, not wrong | Cycle 13 |
| TR12-5 | `app.js:3803`, `:1365`, `:2680` | Med | Med | `geocoded: Boolean(requestedPin.label)` strips `?label=` on restore and prints a false Nominatim credit | Cycle 13 |
| ARCH12-6/9/10/11 | see the lane file | Med/Low | High | Three URL policies for one artefact class; cycle-10 plan citations stale by a median 127 lines; "553" in ~24 comments | Cycle 13 |
| ARCH12-1 | `app.js` 197 KB | Low | High | **Keep one file.** The usual justification is false — the CSP does not block a split — but 17 test files read it as one blob with 54 ordering assertions, and a split makes those throw or go vacuous rather than fail. CLAUDE.md rates that worse than no test | Only if the test harness changes first |
| UX12-1…9, 13…19 | see the lane file | Med/Low | High/Med | Accessibility, responsive and copy items below the cycle's remit | Cycle 13 |
| DOC12 (~60 remaining) | see the lane file | High/Med | High | Attribution cross-check, lying comments, plan-table accuracy, eight false mutation certificates | Cycle 13; the eight certificates ride with TE12 |

### Retired — measured and found not to be problems

Recorded so a later cycle does not re-open them:

- `render()`'s per-row `lookup()` at 1,464 rows is 6.1 ms, not the 4.5 ms-per-157
  the stale comment at `app.js:3116` implies scaling to trouble.
- `worldTicks` **is** exercised, by `test_legend_detail.py:141`.
- `np.maximum.at` over the 82 M-edge table is 0.3 s on numpy 2.x, not a hotspot.
- The free-space pre-flight needs no change: it is a ratio and scales correctly.
- The page's 404 and truncation handling is genuinely strong apart from the
  equal-length case in DBG12-6.
- Zero bare `except:` in `src/`; all ten `httpx` call sites carry explicit
  timeouts; all `dist/` writes go through `_io.atomic_write`.

---

## Found while implementing, not by the review

Two defects the review lanes did not find, both caught by building the thing.

### C12-10 — `_function()` slices a signature when a parameter is destructured

Every JS slicer in `tests/web/` takes `APP.index("{", start)` as the body
brace. For `paintOrigin(o, { keepZoom = false } = {})` that brace belongs to
the **parameter**, so the matcher returns the signature alone — and an
`assert "x" in body` over a signature passes for nothing at all.

Found in `tests/web/test_marker_drag.py`, which is the first test to slice a
function with that shape. Fixed there by walking the parameter parens first,
with a guard test that fails if the slice comes back a single line.

- [x] Fixed in `test_marker_drag.py` and `test_departure_list_cap.py`.
- [x] (2026-10-02: replaced everywhere by the shared `tests/web/_js.py`,
      checked by `tests/web/test_js_slicer.py`.) The same naive matcher is still in `test_route_geometry.py`,
      `test_itinerary_grid.py`, `test_city_country.py` and roughly a dozen
      others. **Not currently vacuous**: none of the functions they slice has
      a destructured parameter, checked. Deferred to cycle 13 as a latent
      trap, with the exit criterion that it re-opens the moment any of those
      functions gains an options object. Severity Medium, confidence High.

### C12-11 — a temporal dead zone ReferenceError, caught before it shipped

Building the search keys (C12-3b) put a `for (const c of cities)` loop calling
`countryName` **above** `const countryName = (() => …)()`. That is a
`ReferenceError: Cannot access 'countryName' before initialization` at module
load; `boot.js` catches it, `index.html` turns it into `display:none` over the
whole rail, and the page is blank with no console error left to find.

`node --check` passes it — a temporal dead zone error is valid syntax. CLAUDE.md
records three of these having shipped (`SMALL`, `bandMark`, `bandSpan`); this
would have been the fourth, and the first not caught by
`tests/web/test_module_scope_order.py`, whose walk starts at handlers
registered before the top-level await and so does not reach module-body code
after it.

- [x] The loop moved below the IIFE; the ReferenceError reproduced in node to
      confirm the claim rather than assert it; pinned by
      `test_departure_list_cap.py::test_the_search_key_is_built_below_countryname`.
- [x] **C12-11b** (2026-10-02: the module body is walked too; the cycle-12
      mutation goes red): `test_module_scope_order.py` only walks handlers registered
      before the top-level await. Module-body code *after* it is unchecked, and
      that is where this one was. Extending the walk is cycle 13. Severity
      High, confidence High — it is the failure mode CLAUDE.md is written
      around, and the existing gate cannot see it.

### C12-12 — the input debounce made Enter depart from the wrong city

Caught by the deploy gate, which is the outcome the gate exists for.

The keydown handler decides what Enter means by **reading the rendered list**:
a first row means "depart from that city", no row means "search this as an
address" (`app.js`, the `$("q")` keydown handler). Coalescing `render()` to one
animation frame (C12-3c) broke that — typing an address and pressing Enter
within the same frame found the list built for the **previous** query and
clicked its first row, so the page departed from an unrelated city instead of
searching. A fast typist reproduces it as readily as the gate does.

- [x] `flushRender()` runs a pending frame immediately; Enter and ArrowDown
      call it before reading the list, and Escape cancels the pending frame
      rather than letting it land on the query it has just cleared.
- [x] Three tests, two mutants confirmed red.

### C12-13 — a check I wrote in this cycle could not fail

`browser_verify.sh`'s new "the list footer names the true total" assertion
built its expected value with

```
python3 -c 'print(f"{int(__import__(\"sys\").argv[1]):,}")' "$CITIES"
```

whose backslashes the shell ate. Python printed a `SyntaxError`, the variable
came back **empty**, and `grep -q ""` matches anything — so the check passed on
every page, including one with no footer at all. It was green for two runs
before the `SyntaxError` in the log was noticed.

Exactly the failure mode CLAUDE.md's testing rule names, in a gate written to
enforce honesty about a cap.

- [x] Rewritten without nested quoting, and it now asserts the expected value
      is non-empty before using it.

### C12-14 — the browser gate typed and clicked inside one frame

The searched-destination check dispatched an `input` event and read `.results`
in the same tick. With the render coalesced, the airport row did not exist yet,
the click never happened, and the total row it looked for was absent for that
reason rather than because anything disagreed — a reported defect on a correct
page, which is the fourth time a gate in this project has done that.

**The gate was wrong, not the page**: no human types and clicks inside one
frame, and the two paths that can act within one now flush the pending render
themselves. The assertion is unchanged; only the interaction is split into the
two steps a person takes.

The same check's `announced` assertion also tested only `/JFK/` against the
live region, which `render()` satisfies on its own by announcing "1 match for
JFK" — it passed with no destination chosen at all. It now also requires "door
to door", which only `announceReading()` writes.

- [x] Both fixed. Live gate after them: **ALL CHECKS PASSED**, zero failures,
      console errors 0, all four viewports clean.

---

## Gates and deploy, cycle 12

| gate | result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run pytest` | 869 passed, 4 deselected, exit 0 (17:01) |
| `bash scripts/deploy_verify.sh --page-only` | deployed; `browser_verify.sh` ALL CHECKS PASSED |

Verified live at 1280x800, 820x1180, 390x844 and 844x390, plus the
return-to-desktop path, a phone tap, and the folded sheet. Console errors: 0.

Verified against the **deployed 553-origin build**, which the page must keep
working on while the rebuild runs: the list reads 60 rows with the footer
"Showing 60 of 553 departure cities, the quickest to reach from Seoul", the
count coming from `index.json` rather than any literal. Both drags were
exercised on the live site: the departure snapped Seoul → Tokyo with "Moved to
Tokyo — the nearest departure city, 1130 km from where you dropped the marker.
Times are measured from Tokyo, not from that point.", the marker returned to
Tokyo's real coordinates, and the permalink followed. The destination handle
dragged Seoul → Beijing and the headline and the Route panel agreed at 6 h 35
min; dragged into open water it correctly refused and dropped the pin.

---

## C12-1, closed: the build was stopped and the land audit run

The owner stopped `rebuild19` at origin 65 of 1,464 after verifying the finding
independently, and reaped the eight orphan `build-all` processes (4 d 21 h old,
parented to init, fully swapped). Free memory went from 7.75 GB to 21.28 GB.
Forty minutes lost against the 26 to 33 hours projected.

One correction from the owner worth keeping, because it would have made an
automated reaper dangerous: **"ppid 1" alone does not identify an orphan.** The
live build's own `nohup` wrapper (pid 34887) also showed ppid 1. Nothing in
this repository selects processes to kill, and nothing should on that basis.

### The pre-restart audit — all 1,464 origins

Run against `land_cells_r6_74c3737a.parquet`, which is what
`landmask._cells_cache_path(SOLVE_RES)` resolves to on this tree (4,091,715
cells). Resolution 6 is the correct level to check at: `_split` is built from
the land mask, so an off-mask cell is never split into fine children.

| outcome | count |
|---|---|
| on the mask, no snap needed | 1,463 |
| snapped, ring 1 (~6 km) | 1 |
| snapped, ring 2 (~13 km) | 0 |
| no land within two rings — would abort | **0** |

The single snap is `kota-kinabalu`, 4.24 km, one cell east. No origin needs
removal.

Stated honestly: that table comes from a script that re-implements the two-ring
test against the same cache file the build reads — it is not a call into the
shipped `origin_node`. The shipped function is covered separately by the four
tests in `tests/solve/test_origin_snap.py`, two of them mutated red. The logic
and the data are each verified, by different means, rather than one standing in
for the other.

Build-path tests before the go-ahead: 42 passed, 1 deselected, exit 0
(`test_origin_snap.py`, `test_golden.py`, `contour/test_bands.py`,
`test_cli.py`).

### Still open, scheduled rather than done

- [ ] **C12-1e** A pre-flight that resolves every origin against the mask right
      after `build_index()`, turning a future bad coordinate into a first-minute
      failure instead of an hour-26 one. **Deliberately not landed before the
      restart**: it is a change to the build path immediately before a 39-hour
      run, and the restart was the critical path. The `expand_origins.py` land
      check and `tests/solve/test_origin_snap.py` already prevent a bad
      coordinate being introduced; this would catch one that arrives by some
      other route, such as a land-mask regression. Cycle 13.
