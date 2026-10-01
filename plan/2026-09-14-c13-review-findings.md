# Cycle 13 — everything the eleven lanes found, scheduled or deferred

Eleven review lanes ran on 2026-09-14 against `feat/transport-pipeline` at
`45e23ea`, under the `rebuild20` build lock. **250 raw findings, 196 distinct
after dedupe, 54 at HIGH.** Every one of them is in the index at the foot of
this file with its ID, its file and line, its severity and its confidence, so
nothing depends on `.context/reviews/`, which is deliberately not committed
(`.gitignore:29`).

The cycle's scope was fixed by the orchestrator before the reviews ran: the
build pre-flight, the solver service design and its graph-free half, **plus any
genuine HIGH-severity correctness or security defect**. The owner's standing
instruction is "do not overwork". Cycle 12 raised 212 findings and scheduled
most of them into a ledger rather than a diff; this cycle does the same, and
the four HIGH defects below are the ones that met the bar.

The solver work has its own document: `2026-09-14-c13-solver-service.md`.

---

## Done this cycle

- [x] **C13-1 — the build pre-flight.** `f01ea2b`. Every selected origin is
  resolved against the land mask the moment `nodes.build_index()` returns and
  before `build.build_graph()` runs, naming every bad row at once. Twelve
  tests, each mutated red. Two additions the brief did not ask for and the code
  needed: the snap is now logged with its distance (DBG13-2), and
  `MAX_SNAPPED_ORIGIN_FRACTION` bounds a mask regression that would otherwise
  pass every per-origin check because every coastal city simply snaps inland.
  `MIN_ORIGINS_FOR_SNAP_BOUND` keeps it from firing on `--only kota-kinabalu`.
  Also closes ARCH13-10 in part: `snap_origin` is now one function with two
  callers rather than a private-field walk inlined per caller.

- [x] **C13-2 — the solver service design and its graph-free half.** `94fdcde`,
  `fe40b96`. See the solver document. Answers ARCH13 part A, PR13's budget,
  SEC13's threat model and C13-19; corrects C13-1 and C13-2, which are findings
  against the cycle-10 plan rather than against the code.

- [x] **C13-3 — the failure message was hidden by the rule that reveals it.**
  `e53ed0b`. HIGH; CR13-1, FCR13-1, DBG13-3, D13-1 independently. At 820x1180,
  390x844 and 844x390 a fatal produced a masthead, a black canvas and no
  explanation. `fatal()` and `boot.js`'s `say()` now move the readout back into
  `<body>` before writing. Seven tests against a stub DOM that models parentage
  — the old stub had none, which is why no source assertion could have caught
  it.

- [x] **C13-4 — a remote free-space figure reached an arithmetic expansion.**
  `b1567e9`. HIGH; SEC13-2 and DBG13-4, the latter proved with a stub `ssh`
  that wrote a file on the operator's machine. One `case` rejecting anything
  that is not a run of digits. Tested against the real shell, with a positive
  control so the guard cannot pass by disabling the check.

- [x] **C13-5 — the `esc()` sink inventory inspected two of six sinks.**
  `268e98d`. HIGH; SEC13-1, C13-10, TE13-1 and V13-8 independently. Measured:
  with `esc()` deleted from `app.js:2704` and `:2785`, `uv run pytest
  tests/web/` reported **389 passed**. Whole-statement capture, balanced
  interpolation extraction, bare-variable sinks no longer skipped, and three
  guards on the guard. Five mutations red, three of which were green before.

---

## Scheduled, not done — cycle 14, in this order

- [x] **C13-6 — the reading tier said "no scheduled route" where the coarse
  tier said ten hours.** `fe93bea`. HIGH; TR13-1 and DBG13-1, the latter decoded
  from the shipped binaries. `emit/hover.py:write_reading` fills every slot of a
  res-3 block with the sentinel and writes only the land slots;
  `_representative_children` gives the res-4 tier a fastest-child fallback and
  the res-6 tier has none. **553 of 553 shipped origins** read 65535 at Kota
  Kinabalu's cell while the coarse tier reads 231 to 2,140 minutes;
  **281,328 of 4,446,252 res-6 cells (6.33 %)** are in that state structurally;
  **13 of 34,135 labelled places** and **47 of 4,008 airports** are affected,
  Bodø, Tarawa, Bora Bora and the Galápagos among them.

  **Fixed in the page, and the emitter-side fix is rejected rather than
  deferred.** Giving the reading tier a fallback means filling padding slots,
  and 6.33 % of those slots are genuinely open water inside a land-touching
  res-3 parent — so it would paint door-to-door times over the ocean, which is
  worse than the defect. `plan/deferred.md:582` (C10-6) deferred this because
  "the page has no res-6 land set". It has none and needs none: it ships a
  res-4 land set, and when the tier it trusts for land has a real answer for
  the cell the pointer is in, printing that beats printing a sentinel. The
  value is then read from a wider cell than the outline, which the page already
  has a sentence for — `readingGrid()` now reports the tier actually read
  rather than the presence of the array, so the disclosure fires. Seven tests,
  five mutations red.

  This also closes C10-6 in `deferred.md`, whose stated premise is now false.

- [ ] **C13-7 — `route_network()` returns the legacy parquet on a bare
  `.exists()`.** HIGH. CR13-3, DBG13-6, and the running build's own log says
  `using legacy routes.parquet whose inputs are unknown`. `debugger` refined
  the mechanism: the stamped path is checked first and is correctly keyed, but
  the legacy branch returns **without ever writing the stamped file**, so it
  wins for ever. Consequence today is benign — 0 of 3,741 route endpoints are
  missing from any airport table — which is why it is scheduled rather than
  urgent. It also makes CR13-2 and CR13-6 unfixable: CR13-13 records that the
  cache stamp omits `_LINK_RE`, so correcting the section parser would no-op.
  **Fix CR13-3, CR13-13, CR13-2 and CR13-6 together or not at all.** Exit
  criterion: the same, the build must not be re-crawling while it runs.

- [ ] **C13-8 — a build can start beside a resident solver and neither can see
  the other.** ARCH13-2, and a prerequisite for anything resident.
  `cli.py:175` and `deploy_verify.sh:74` both detect concurrency by matching
  the literal string `build-all`. Tracked as C13-F2.6 in the solver document.

- [ ] **C13-9 — two gates that cannot fail.** V13-27 (HIGH):
  `deploy_verify.sh:56-57` exits 0 when `node` is absent, so a syntactically
  broken `app.js` ships; reproduced, though with `228 passed, 143 skipped`
  rather than the counts first reported, and `node` **is** on PATH here so it
  is not currently blind. V13-28 (HIGH): `browser_verify.sh:106` and `:359`
  still `sleep` a fixed time before reading data that grew from 553 to 1,464
  rows — the mechanism behind the four recorded gate failures on correct code.
  Both are in the deploy path this cycle must run, so neither is touched while
  a build holds the lock: changing a gate in the same cycle that runs it makes
  a failure unattributable.

- [ ] **C13-10 — the fourteen documentation HIGHs.** DOC13-1…DOC13-14. Two are
  visitor-facing and go first: DOC13-1, the page telling readers the fit wanted
  roadless terrain "infinitely fast" when the measured reciprocal is
  −102.2 km/h, and DOC13-5, `data/origins.toml`'s header still describing 157
  plus 396 rows in a 1,464-row file. DOC13-2 (`plan/README.md` calling F1, F3
  and F4 unbuilt when all three shipped) is fixed in this cycle's README edit.

- [ ] **C13-11 — the seventeen plan ticks that did not hold.** V13-1…V13-17,
  including a third un-recorded false tick in cycle 8 and cycle 12's own
  C12-1c, whose mutation certificate is false: `tests/solve/test_origin_snap.py:108-110`
  raises the `GateFailure` in its own body, so deleting `cli.py:222-223` leaves
  it green. Correcting a false tick is bookkeeping, and this cycle's diff is
  already the largest thing it can verify.
  - [x] C12-1c's half (2026-10-02): `test_origin_snap.py` now drives
    `cli._solve_one` itself; deleting its `except ValueError` -> red, and
    dropping `snap_origin`'s `_nearest_land` branch -> red on the new
    snapped-origin test. The other sixteen V13 ticks remain open.

---

## Deferred, with exit criteria

Deferral rules read before writing this section: CLAUDE.md is the only rule
file; `plan/README.md` states that every finding is scheduled, fixed with
evidence in a commit body, or recorded here with its citation, original
severity and confidence, the reason and the exit criterion. Nothing is
downgraded. **Security, correctness and data-loss findings are not deferred**:
every HIGH is either done above, scheduled above, or appears in this table with
a build-lock exit criterion that fires within days.

| group | IDs | sev | conf | reason | exit criterion |
|---|---|---|---|---|---|
| **Blocked by the running build** | C13-7 (CR13-3, CR13-13, CR13-2, CR13-6), DBG13-7, ARCH13-5 | HIGH–MEDIUM | High | Each changes what a build produces or what a build reads. `rebuild20` forked with these modules imported, so an edit cannot reach it; a wrong fix would not surface until the next 39-hour run. Editing build inputs under a build is how this project lost rebuild19. C13-6 was in this group until it turned out to have a better fix in the page, which needs no build at all. | `rebuild20` completes or is stopped, and `dist/.build.lock` is gone |
| **In the deploy path this cycle must run** | V13-27, V13-28, V13-29, V13-30, V13-32, SEC13-5, SEC13-6, SEC13-8, C13-6 (deploy_verify), FCR13-7 | HIGH–MEDIUM | High | The orchestrator's note is explicit: gates have failed four times on correct code, and changing a gate in the cycle that runs it makes the next failure unattributable. SEC13-2 was the exception and is fixed, because it is not a gate — it is a shell-injection primitive. | A cycle whose deploy is not `--page-only`, or any cycle that does not run `deploy_verify.sh` |
| **Performance, all analytic** | PR13-1…PR13-18 except those in the solver document | HIGH–LOW | High | Every one is a measured cost in the build or the page, and every fix touches `graph/`, `emit/` or `sources/` — the modules the running build is executing. PR13-2, PR13-3, PR13-7 and PR13-18 are already scheduled as C13-F2.7 in the solver document, where they matter most. | `rebuild20` ends; then PR13-18 first (139.6 s, 45 % of every build's startup) |
| **Documentation, 62 of 76** | DOC13-15…DOC13-76 | MEDIUM–LOW | High–Medium | Cycle 12 raised 23 documentation HIGHs and closed 7; this cycle raises 14 more. The backlog is real and it is prose, not behaviour. Taking 76 rows in the cycle that also lands a service design and four HIGH fixes would make none of them reviewable. The 14 HIGHs are scheduled as C13-10. | Any cycle whose brief is documentation, or the next time a figure in this group is quoted to the owner |
| **Plan bookkeeping** | V13-1…V13-26, V13-33…V13-44 | MEDIUM–LOW | High | Seventeen false ticks and the deferred rows whose exit criteria have fired. Correcting them is bookkeeping about past cycles; none changes behaviour. Scheduled as C13-11. | Cycle 14, before any further plan is archived — `plan/README.md`'s own rule is that a plan is archived on the state of the tree |
| **Architecture, not prerequisites** | ARCH13-1, ARCH13-3, ARCH13-4, ARCH13-6, ARCH13-7, ARCH13-8, ARCH13-9 | MEDIUM | Medium–High | Each is a real structural defect and none is reachable without editing modules the build is running. ARCH13-2 and ARCH13-10 are handled above. | `rebuild20` ends |
| **Test gaps** | TE13-1…TE13-10 except TE13-1 (done as C13-5), C13-11…C13-17 | MEDIUM–LOW | High | Vacuous tests, proved by mutation. Each needs the guard rewritten the way C13-5 rewrote the `esc()` inventory, which took a third of this cycle for one of them. TE13-7 (no test relates the page's `fetch()` targets to the shipped CSP) is the one that would have caught a solver API passing every gate and being blocked live; it is scheduled with the nginx work as C13-F2.10. | Cycle 14, one guard per cycle, each with the mutation recorded |
| **Security, MEDIUM and LOW** | SEC13-3, SEC13-4, SEC13-7, SEC13-9, SEC13-10, SEC13-11…SEC13-18 | MEDIUM–LOW | High–Medium | None is remotely reachable by a visitor: every one is in a build script, a crawler or an operator tool, and the two HIGHs are fixed. SEC13-7 (`googletagmanager.com` in `script-src` is a CSP allow-list bypass) is the owner's call, not ours — it is the analytics the owner chose. | SEC13-9 (no checksum pin, no decompression cap on remote archives) at the next `sources/` cycle; the rest at any security-scoped cycle; SEC13-7 never, unless the owner drops analytics |
| **Page detail and accessibility** | D13-2…D13-11, FCR13-2…FCR13-6, CR13-12, CR13-14, CR13-16, CR13-21, CR13-26 | MEDIUM–LOW | High | The page work this cycle was one HIGH failure path and one feature flag. D13-2 (`.pinhandle` exposed as a button and never focusable) and FCR13-2 (the watchdog arms on `load`, which a module's top-level await may never reach) are the two worth doing first. | Cycle 14's page pass; FCR13-2 sooner if any load-path fetch is added |
| **Tracer and debugger, LOW** | TR13-5…TR13-10, DBG13-8, DBG13-9 | LOW | High | Sentinel and convention mismatches that are latent: each is a defect waiting for a second caller, none is reached today. TR13-3 and TR13-4 are answered in the solver document rather than deferred. | Any cycle touching the module named in the row |
| **Critic, the premise arguments** | C13-19, C13-21, C13-22, C13-23, C13-24, C13-25 | HIGH–MEDIUM | High | These are arguments about what the project should do, not defects. C13-21, C13-22 and C13-24 are carried verbatim into the solver document's "The alternative this cycle is obliged to put in front of the owner", which is where a decision can be taken on them. C13-25 (`src/` is 2 of the last 40 commits) is a true observation about this loop's own behaviour and is recorded rather than actioned. | The owner's answer on C13-F2.5 |

### Findings that are NOT deferred and NOT scheduled, because they are closed

- **ARCH13-10**, in part: `snap_origin` is now a single named function with two
  callers. The remaining half — promoting it to `NodeIndex.snap()` so it is not
  private-field access across a package boundary — stays deferred with the
  architecture group.
- **DBG13-2**: the silent snap. Closed by C13-1, which logs every snapped
  origin with its distance and bounds the share.
- **C13-1, C13-2**: findings against `2026-09-13-c10-requested-features.md`,
  which `2026-09-14-c13-solver-service.md` supersedes. The false claims are
  quoted and corrected there.
- **TR13-2**: superseded by C13-3's fix — the destination-drag path it traces
  ends at the readout that is now moved out of the hidden rail.

---

## Gates, cycle 13

| gate | result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run pytest` (default deselection) | see the Status section |
| `bash scripts/deploy_verify.sh --page-only` | see the Status section |

`GATE_FIXES` for this cycle: 0. No gate was weakened, no threshold lowered and
no test rewritten to pass. One gate (`tests/web/test_esc.py`) was made
**stricter** and that is C13-5, not a gate fix.

---

## The index — all 250 raw findings, with citations

Deduped to 196 distinct across lanes; the raw rows are kept per lane so a
finding can be traced back to the lane that made it and to the agreement
between lanes. This table is the durable record: `.context/reviews/` is not
committed.


#### `architect.md` — 10

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| ARCH13-1 | `src/transport_maps/cli.py:213-253` | HIGH | Medium | the comment that says the per-origin failure contract is complete is false; five of six failure sources still exit wit |
| ARCH13-2 | `src/transport_maps/cli.py:149-185` | HIGH | Medium | both "is something else holding the graph?" guards key on the literal string `build-all`, so a resident solver is invi |
| ARCH13-3 | `src/transport_maps/emit/index.py:249-262` | MEDIUM | Medium | every cross-artefact consistency check in the repository compares lengths; nothing compares content, and `inputsHash`  |
| ARCH13-4 | `src/transport_maps/sources/landmask.py:44-45` | MEDIUM | Medium | a prose constant is part of a multi-hour cache key; two byte-identical 4 M-cell caches on disk prove it has already fi |
| ARCH13-5 | `src/transport_maps/cli.py:321-436` | MEDIUM | Medium | the build has no staging generation, so `dist/` is mixed by construction for the whole of a 39-hour run and a single b |
| ARCH13-6 | `cli.py` | MEDIUM | Medium | has a lazy `sources.roads` fallback that runs inside a forked worker, one keyword argument away from the deadlock `cli |
| ARCH13-7 | `src/transport_maps/validate.py:31-54` | MEDIUM | Medium | the coverage gate counts a journey as "reached" that the shipped array and the page both call unreachable |
| ARCH13-8 | `src/transport_maps/graph/build.py:69-100` | MEDIUM | Medium | the route-network filter is implemented twice in one file, and only one copy is bounded |
| ARCH13-9 | `calibration.toml` | MEDIUM | Medium | is read per edge-builder with no snapshot, so one graph can be weighted from several different reads of a file the bui |
| ARCH13-10 | `src/transport_maps/solve/dijkstra.py:45-47` | LOW | Medium | the one operation a solver service needs most is spelled as private-field access across a package boundary |

#### `code-reviewer.md` — 26

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| CR13-1 | `web/index.html:161` | HIGH | High | , `web/app.js:718-723`, `:4002` | `body.fatal` deletes the element the fatal message is written into, on every viewpor |
| CR13-2 | `sources/routes.py:27,32,72-75` | HIGH | High | A level-3 "Airlines and destinations" swallows its sibling sections, inventing scheduled routes from accident prose |
| CR13-3 | `sources/routes.py:269-280` | HIGH | High | always returns the unstamped legacy `routes.parquet`, so every cache lever in the module is dead |
| CR13-4 | `validate.py:63-119` | MEDIUM | High | , `contour/bands.py:215,244` | `check_bands_cover` cannot detect the band overlap it exists to verify |
| CR13-5 | `sources/landmask.py:51-58` | MEDIUM | High | vs `:171-180` | Raw archives are keyed on a fixed filename while the derived cache is keyed on the URL |
| CR13-6 | `sources/routes.py:33` | MEDIUM | High | silently drops every destination link carrying a `#` fragment |
| CR13-7 | `cli.py:555,577,628-631` | MEDIUM | High | sets `railDetail` from **any** origin having rail files, creating the state its own docstring warns against |
| CR13-8 | `graph/transfers.py:5-15` | MEDIUM | High | omits every non-sovereign territory, so 316 domestic pairs are charged a passport desk |
| CR13-9 | `sources/osm.py:336-345` | MEDIUM | High | vs `:378-383` | `ferry_links()` has no empty-result guard although `rail_routes()` does |
| CR13-10 | `scripts/calibrate_ground.py:134-152` | MEDIUM | High | The missing-API-key `RuntimeError` is swallowed; the script pays N full Dijkstra solves and reports the wrong cause |
| CR13-11 | `scripts/browser_verify.sh:96-98,600-604` | MEDIUM | High | The cleanup kills every agent-browser process that appeared during the run, including another session's |
| CR13-12 | `web/app.js:3420-3431` | MEDIUM | Medium | , `web/index.html:934` | The cap footer is not an `option` inside a `listbox` and is never announced, so a screen read |
| CR13-13 | `sources/routes.py:262-263` | MEDIUM | Medium | stamps two of the four regexes that govern the cached content |
| CR13-14 | `web/boot.js:59-69` | MEDIUM | High | The window-`error` branch applies no origin filter, so a third-party or extension throw blanks the rail |
| CR13-15 | `scripts/adsb_extract.py:5-6,96-112` | MEDIUM | High | "Re-running costs no network at all" is false: the GitHub API is called before the cache is consulted |
| CR13-16 | `web/index.html:822` | MEDIUM | High | , `web/boot.js:28-34`, `web/app.js:36-38` | A page failure is never written to the page's only live region |
| CR13-17 | `tests/web/test_page_affordances.py:56-70` | LOW | High | The nested-scroll-box test asserts nothing when the rule it guards is deleted |
| CR13-18 | `scripts/check_dist.py:100-132` | LOW | High | returns `None` for an unreadable blob and both callers read `None` as clean |
| CR13-19 | `sources/_utils.py:13-34` | LOW | High | passes `nan` to `time.sleep`, aborting the crawl it exists to protect |
| CR13-20 | `scripts/check_ramps.py:77-85,235-246` | LOW | High | The ramp checker exits 0 when its regex parses zero ramps |
| CR13-21 | `web/app.js:2804-2830` | LOW | High | , `web/index.html:537` | The destination drag handle is invisible and the pin does not follow it, so a drag has no spa |
| CR13-22 | `graph/rail.py:62-76` | LOW | High | 's `cell` column ignores the refined grid, contradicting its docstring |
| CR13-23 | `contour/bands.py:185-197` | LOW | High | 's "(excluding the cell itself)" is false for `rim >= 2`, and both shipped LODs use 2 and 3 |
| CR13-24 | `sources/routes.py:327` | LOW | High | reads `ourairports.csv` directly instead of through `airports._download()` |
| CR13-25 | `validate.py:87-89` | LOW | High | Dead branch in `check_bands_cover`'s depth computation |
| CR13-26 | `web/index.html:174-180,197,646,739` | LOW | High | Three dead `.mast p` rules and a comment describing markup that no longer exists |

#### `security-reviewer.md` — 18

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| SEC13-1 | `tests/web/test_esc.py:195-221` | HIGH | High | the sink guard cycle 12 asked for is vacuous for the attack it names · HIGH · confidence High |
| SEC13-2 | `scripts/deploy_verify.sh:113-124` | HIGH | High | output from the deploy server executes on the operator's machine · HIGH · confidence High |
| SEC13-3 | `scripts/browser_verify.sh:49-51` | MEDIUM | High | the browser gate evaluates JavaScript built from the site it is verifying · MEDIUM · confidence High |
| SEC13-4 | `scripts/check_dist.py:126-132` | MEDIUM | High | a leaked API key in a PMTiles metadata blob is a non-blocking warning · MEDIUM · confidence High |
| SEC13-5 | `scripts/deploy_verify.sh:74-78` | MEDIUM | High | the concurrent-build gate reports "no build running" when its own pipeline fails · MEDIUM · confidence High |
| SEC13-6 | `scripts/deploy_verify.sh:159-161` | MEDIUM | High | the live-origin probe silently reverts to a hardcoded slug · MEDIUM · confidence High |
| SEC13-7 | `deploy/worldmap-security-headers.conf:23` | MEDIUM | High | in `script-src` is a CSP allow-list bypass · MEDIUM · confidence High |
| SEC13-8 | `scripts/deploy_verify.sh:186-191` | MEDIUM | High | the deploy still reports the security headers instead of asserting them · MEDIUM · confidence High |
| SEC13-9 | `src/transport_maps/emit/water.py:84-89` | MEDIUM | High | no integrity pin and no decompression cap on any remote archive · MEDIUM · confidence High |
| SEC13-10 | `adsb_extract.py` | MEDIUM | High | builds a cache path and an outbound URL from remote JSON · MEDIUM · confidence High |
| SEC13-11 | `data/origins.toml` | LOW | High | GeoNames fields are string-templated into `data/origins.toml` · LOW · confidence High |
| SEC13-12 | `web/app.js:580-581` | LOW | Medium | assigned from fetched JSON with no scheme check · LOW · confidence Medium |
| SEC13-13 | `web/app.js:88` | LOW | High | mode names index two object literals without `Object.hasOwn` · LOW · confidence High |
| SEC13-14 | `src/transport_maps/sources/roads.py:73` | LOW | High | one `np.load` without an explicit `allow_pickle=False` · LOW · confidence High |
| SEC13-15 | `src/transport_maps/emit/tiles.py:37-38` | LOW | High | predictable shared temp directory for tile staging · LOW · confidence High |
| SEC13-16 | `src/transport_maps/cli.py:127-130` | LOW | High | the lockfile's PID is not constrained to be positive · LOW · confidence High |
| SEC13-17 | `scripts/deploy_verify.sh:25` | LOW | High | is arbitrary shell execution from a gitignored file · LOW · confidence High |
| SEC13-18 | `scripts/browser_verify.sh:5` | LOW | Medium | the browser gate runs without `pipefail`, so no pipeline failure is visible · LOW · confidence Medium |

#### `perf-reviewer.md` — 15

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| PR13-1 | `src/transport_maps/solve/dijkstra.py:9-18` | HIGH | Medium | a full-graph Dijkstra is ~10 s against a 3 s budget, and there is no cheaper primitive |
| PR13-2 | `src/transport_maps/graph/nodes.py:49,51,67-70` | HIGH | Medium | 's string+dict representation is 2.35 GB, 67 % of the service |
| PR13-3 | `src/transport_maps/cli.py:335-336` | HIGH | Medium | cold start rebuilds the whole graph in Python: 3.5 min and an ~11 GB peak, for a 3.4 GiB steady state |
| PR13-7 | `src/transport_maps/cli.py:348-350` | HIGH | Medium | is 776 MB of Python strings and `zone` is 440 MB of `<U8`, built three times each |
| PR13-8 | `src/transport_maps/graph/ground.py:87` | HIGH | Medium | materialises 13.75 M Python tuples to build a centroid array |
| PR13-9 | `src/transport_maps/graph/ground.py:149-152` | HIGH | Medium | gathers two 1.31 GB coordinate copies and runs haversine over 82.1 M rows |
| PR13-10 | `src/transport_maps/graph/build.py:441-449` | MEDIUM | Medium | the duplicate-edge check allocates 1.3 GB and keeps `keys` alive through `tocsr()` |
| PR13-11 | `src/transport_maps/graph/build.py:76-84` | LOW | Medium | and `_transfer_edges` run the identical 68,152-pair loop twice |
| PR13-12 | `web/app.js:3308` | MEDIUM | Medium | the new departure-list cap does not apply to a filtered list, so the worst case cycle 12 measured is still live |
| PR13-13 | `web/app.js:3280-3296` | LOW | Medium | runs 1,464 `lookup()`s and two sorts on every resting render, including before any time array exists |
| PR13-14 | `web/app.js:2831-2834` | MEDIUM | Medium | the two new drag handlers run the pointer pipeline outside the rAF gate |
| PR13-15 | `web/app.js:3723-3733` | LOW | High | arrow-key navigation still rewrites every row's `tabIndex`, now bounded at rest but not when filtering |
| PR13-16 | `.rail.json` | MEDIUM | High | per-visitor bytes per origin switch: ~12.4 MB raw, ~5.9 MB gzipped, unchanged and unbounded by origin count |
| PR13-17 | `src/transport_maps/graph/refine.py:46,50-51` | LOW | Medium | builds `base_index` as a 13.75 M-element Python list of numpy scalars |
| PR13-18 | `src/transport_maps/sources/roads.py:99-140` | HIGH | Medium | runs four uncached 4.09 M-cell Python passes per build: 140 s, 45 % of startup |

#### `critic.md` — 25

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| C13-1 | `plan/2026-09-13-c10-requested-features.md:153-154` | HIGH | High | says the solver has no early termination. scipy has had it since 2014. **HIGH / High |
| C13-2 | `plan/2026-09-13-c10-requested-features.md:164-166` | HIGH | High | promises to reuse a decomposition that does not exist in a per-request shape. **HIGH / High |
| C13-3 | `graph/ground.py:28-29` | MEDIUM | High | states a per-cell edge ratio that is 34% high, and `plan/deferred.md:176` states the opposite error about the same con |
| C13-4 | `tests/test_licence_firewall.py:25-27` | MEDIUM | High | cites a sentence that is not in `CLAUDE.md`, and `deploy/README.md:20` applies it to a different gate. **MEDIUM / High |
| C13-5 | `deploy/README.md:81` | LOW | High | claims a band count this build has never produced. **LOW / High |
| C13-6 | `scripts/deploy_verify.sh:92` | LOW | High | under-states the payload by 5.2 GiB. **LOW / High |
| C13-7 | `graph/ferry.py:25-26` | LOW | High | states an interval-coverage figure the cached extract does not support. **LOW / High |
| C13-8 | `plan/README.md:41,49` | LOW | High | mis-states the ID ranges of the two plans it indexes, and marks two different cycles "current". **LOW / High |
| C13-9 | `plan/deferred.md:647` | MEDIUM | High | C11-D10's own exit criterion has now been missed twice, which makes the ledger's own status line false. **MEDIUM / Hig |
| C13-10 | `tests/web/test_esc.py:195` | HIGH | High | inspects 2 of the 6 HTML sinks, and its allow-list admits `.map(`. **HIGH / High |
| C13-11 | `tests/emit/test_index.py:15` | HIGH | High | rests on a single comparison and stays green when `sorted()` is deleted. **HIGH / High (repeat of TE3-12, severity rai |
| C13-12 | `tests/web/test_design_policy.py:155-163` | MEDIUM | High | measures only the first declaration of each token, so a cascade override ships a light theme green. **MEDIUM / High |
| C13-13 | `see lane file` | MEDIUM | High | The same file's three bans never see an inline `style=` attribute, which the deployed CSP permits. **MEDIUM / High |
| C13-14 | `tests/web/test_app_constants.py:108` | MEDIUM | High | scans only `meta.<name>` dot access. **MEDIUM / High |
| C13-15 | `tests/sources/test_airports.py:29` | MEDIUM | High | bounds IATA codes below only. **MEDIUM / High |
| C13-16 | `tests/emit/test_hover.py:43` | LOW | High | asserts a property of the reader, not of the file. **LOW / High |
| C13-17 | `tests/web/test_vendor.py:28` | LOW | High | still does not descend into `vendor/licences/`. **LOW / High (repeat of C11-D10, unchanged) |
| C13-18 | `contour/grid.py` | HIGH | High | There is no serialized graph anywhere in the repository, so 207 s is not a startup cost but a per-restart, per-deploy, |
| C13-19 | `see lane file` | HIGH | High | One anonymous HTTP request costs 10-11 s of a full core and ~600 MB. That is a DoS primitive, and the site currently h |
| C13-20 | `plan/deferred.md` | MEDIUM | High | F2 optimises 2% of the cost it claims to be about. **MEDIUM / High |
| C13-21 | `see lane file` | HIGH | High | Measured: the model is 98% reciprocal, so `t(P -> X)` is already sitting in a file the page downloads. This was never  |
| C13-22 | `dist/places.json` | HIGH | High | A precomputed departure grid makes every named place on Earth a departure, statically, for one-fifth of the build alre |
| C13-23 | `see lane file` | MEDIUM | High | Caching on the resolved H3 cell id gives a hit rate of approximately zero. **MEDIUM / High |
| C13-24 | `see lane file` | HIGH | Medium | What to do instead, in order. **(recommendation, not a defect) |
| C13-25 | `see lane file` | HIGH | High | The build path has received 2 of the last 40 commits, and it is what gates every feature the owner has asked for. **HI |

#### `test-engineer.md` — 10

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| TE13-1 | `tests/web/test_esc.py:195-222` | HIGH | High | the `esc()` sink inventory cannot see a multi-line or a variable `innerHTML`, and three live-XSS mutations survive all |
| TE13-2 | `scripts/expand_origins.py` | HIGH | High | is the gate that stops the next 39-hour build dying, it has zero tests, and it holds a second private copy of the two- |
| TE13-3 | `tests/web/test_reading_tier_refresh.py` | HIGH | High | claims to catch a new renderer and cannot; its `RENDERERS` set is hard-coded — PROVEN, High confidence, **MEDIUM |
| TE13-4 | `test_cache_provenance.py` | MEDIUM | High | 's `STAMPED` still omits six hashed inputs, and the list is hand-maintained where the repo already has the derived idi |
| TE13-5 | `src/transport_maps/emit/airports_json.py:21-29` | MEDIUM | High | two emitters are never executed by any test; a `fields`/row transposition ships silently — READ, High confidence, **ME |
| TE13-6 | `src/transport_maps/cli.py` | MEDIUM | High | every gate before the origin loop fails as a raw traceback, and nothing tests that; the new pre-flight would inherit i |
| TE13-7 | `deploy/worldmap-security-headers.conf:23` | MEDIUM | High | nothing relates the page's `fetch()` targets to the shipped `connect-src`; a new absolute URL passes every gate and is |
| TE13-8 | `tests/conftest.py:44-47` | MEDIUM | High | the default gate is not hermetic on a cold cache: seven `integration` modules will download gigabytes over the network |
| TE13-9 | `tests/web/test_esc.py:190` | LOW | Medium | the `esc` apostrophe guard's regex is exact-literal and misses two nearby shapes — READ, Medium confidence, **LOW |
| TE13-10 | `adsb_extract.py` | LOW | High | four `scripts/*.py` have no tests at all — READ, High confidence, **LOW |

#### `verifier.md` — 44

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| V13-1 | `plan/archive/2026-09-13-c8-ferry-wait-legend-url.md:309` | MEDIUM | High | · c8 T5.6 is ticked and was never done — a THIRD bad tick the ledger does not record |
| V13-2 | `plan/archive/2026-09-13-c8-ferry-wait-legend-url.md:131` | MEDIUM | High | · c8 T1.11 — the one ferry mutation the cycle named as previously-green is still green |
| V13-3 | `plan/archive/2026-09-13-c8-ferry-wait-legend-url.md:123` | LOW | High | · c8 T1.9 — 3 of the 5 critic objections were recorded, not 5 |
| V13-4 | `plan/archive/2026-09-10-c4-page-deploy-and-licence.md:354` | MEDIUM | High | · c4 U22 — only one of the two "free checks" landed |
| V13-5 | `plan/archive/2026-09-10-c4-page-deploy-and-licence.md:175` | MEDIUM | High | · c4 U9 — the re-benchmark the tick required never happened, and the code says so |
| V13-6 | `plan/archive/2026-09-10-c4-page-deploy-and-licence.md:443` | LOW | High | · c4 U27 — one of the two named assertions landed |
| V13-7 | `plan/2026-09-14-c12-review-findings.md:42` | MEDIUM | High | · c12 C12-1c — the "red before the fix" test never reads origins.toml, and its mutation certificate is false |
| V13-8 | `plan/archive/2026-09-14-c12-requested-features.md:50` | MEDIUM | High | · c12 F1.3 — the `esc()` sink inventory is blind to 3 of the 6 live sinks |
| V13-9 | `plan/2026-09-14-c12-review-findings.md:75-77` | LOW | High | · c12 C12-3a — "deletes code rather than adding it" is false; neither thing was deleted |
| V13-10 | `plan/archive/2026-09-13-c11-design-slop.md:97` | LOW | High | · c11 — "four `<p>` to two" shipped as three, paired differently |
| V13-11 | `plan/2026-09-10-c2-web-ui-detail.md:181-184` | LOW | High | · c2 N24 — ticked inside N23's box, never done |
| V13-12 | `plan/2026-09-10-c2-web-ui-detail.md:146-148` | LOW | High | · c2 N10/D4 — `aria-activedescendant` was ticked and has never existed |
| V13-13 | `plan/archive/2026-09-14-c12-requested-features.md:105` | LOW | High | · c12 F2.1 — "live feedback in `#where`" goes to `#snapped` |
| V13-14 | `plan/archive/2026-09-14-c12-requested-features.md:112` | LOW | Medium | · c12 F2.5 — keyboard "equivalence" is overstated for the new destination handle |
| V13-15 | `plan/2026-09-13-c10-requested-features.md:39` | MEDIUM | High | · F1's own stated precondition was not honoured before F1 shipped |
| V13-16 | `plan/2026-09-13-c10-requested-features.md:1` | LOW | High | · `plan/2026-09-13-c10-requested-features.md:1` — "PLANNED, NOT BUILT" is stale in three of four |
| V13-17 | `plan/README.md` | LOW | High | · `plan/README.md` miscounts cycle 8 and contradicts itself on A3–A8 |
| V13-18 | `plan/deferred.md:596` | HIGH | High | · `plan/deferred.md:596` · CRIT10-1 — the ledger audit it demands has now missed TWO build windows |
| V13-19 | `plan/deferred.md:478` | HIGH | High | · `plan/deferred.md:478` · AB12 — the page gate passes with `node` absent, and I proved it |
| V13-20 | `plan/deferred.md:668` | HIGH | High | · `plan/deferred.md:668` · C12-8 — cycle 13 is open; none of the three items done |
| V13-21 | `plan/deferred.md:669` | HIGH | High | · `plan/deferred.md:669` · C12-11b — cycle 13 is open; the walk is not extended |
| V13-22 | `plan/deferred.md:353` | HIGH | High | · `plan/deferred.md:353` · TR5-2 — fired twice; the rail edge-length gate exists nowhere |
| V13-23 | `contour/bands.py:254-258` | MEDIUM | Medium | · Eleven rows gated on "the commit that starts the corrected rebuild", or on a cycle that has since run |
| V13-24 | `plan/deferred.md:96` | MEDIUM | High | · Four rows whose criterion fired AND whose work is done — they should CLOSE, not reopen |
| V13-25 | `scripts/deploy_verify.sh:10` | MEDIUM | High | · Nine further rows whose criterion has fired |
| V13-26 | `plan/deferred.md:528-559` | MEDIUM | High | · Rows with unfalsifiable, self-blocking, missing or self-contradicting exit criteria |
| V13-27 | `scripts/deploy_verify.sh:56-57` | HIGH | High | · `scripts/deploy_verify.sh:56-57` — the page-asset gate passes on a host without `node`, including on a syntactically |
| V13-28 | `scripts/browser_verify.sh:106` | HIGH | High | · `scripts/browser_verify.sh:106` and `:359` — fixed cold-load sleeps while the payload grows |
| V13-29 | `scripts/browser_verify.sh:179` | MEDIUM | High | · `scripts/browser_verify.sh:179` — `"departing":1` is unanchored, so it cannot fail for a whole class |
| V13-30 | `scripts/browser_verify.sh:176` | MEDIUM | High | · `scripts/browser_verify.sh:176` — `durations` is compared against a literal digit width, not against `rows` |
| V13-31 | `tests/web/test_vendor.py:37` | MEDIUM | High | · `tests/web/test_vendor.py:37` — the vendored-file gate cannot see `web/vendor/licences/` |
| V13-32 | `scripts/check_dist.py:48-52` | MEDIUM | High | · `scripts/check_dist.py:48-52` — `COUNT_CLAIM` only matches a count separated from its noun by a single ASCII space |
| V13-33 | `scripts/browser_verify.sh:464` | LOW | High | a five-way `grep && grep && … || fail=1` with no message; a failure sets `fail` correctly but names none of the five c |
| V13-34 | `scripts/browser_verify.sh:327` | LOW | High | uses `tr -d '\'` where every other line uses `tr -d '\\'`. **Measured on this machine's BSD `tr`: the two are equivale |
| V13-35 | `scripts/deploy_verify.sh:185-188` | MEDIUM | Medium | the CSP-header probe is a REPORT, not an assertion. Self-documented at `:183-184` ("Report (not yet assert…)"). Correc |
| V13-36 | `web/README.md:62` | MEDIUM | High | · `web/README.md:62` — "Every file in `vendor/` appears above" is false |
| V13-37 | `data/origins.toml` | MEDIUM | High | · `docs/superpowers/specs/…:19` — the as-built correction is itself stale |
| V13-38 | `sources/landmask.py:131` | MEDIUM | High | · `docs/superpowers/specs/…` — two superseded design claims are missing from the as-built table |
| V13-39 | `dist/index.html` | MEDIUM | High | · `dist/index.html` still ships all five "more than five hundred cities" claims |
| V13-40 | `deploy/README.md:20` | MEDIUM | High | "the only automated licence gate in the project" — contradicted eleven lines later by its own step 4, and by `tests/te |
| V13-41 | `deploy/README.md:12` | MEDIUM | High | "every origin agrees on `offsets.airports` so two builds cannot be mixed" — describes pre-fix behaviour; `scripts/chec |
| V13-42 | `deploy/README.md:81` | MEDIUM | Medium | "map 7,845 water features and 52 bands, 553 cities" — "52 bands" reads as a band-count claim against the true 37. Medi |
| V13-43 | `web/llms.txt:53` | MEDIUM | High | "`{slug}.r6.bin` (9.55 MB)" — 10,014,228 bytes = 10.01 MB decimal (9.55 MiB), while the four sizes in the paragraph im |
| V13-44 | `index.json` | MEDIUM | High | name artefacts `origins/{iata}.*` — they are `{slug}.*`; `:268` "`index.json` ~20 KB" — actual 39,751 B; the Data Sour |

#### `tracer.md` — 10

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| TR13-1 | `data/origins.toml:6251-6256` | HIGH | Medium | a shipped departure city reads "no scheduled route" at its own coordinate |
| TR13-2 | `web/app.js:4113-4136` | HIGH | Medium | the same click gives two different answers depending on which array has landed |
| TR13-3 | `web/app.js:2022-2031` | MEDIUM | Medium | the page's land test and the solver's land test disagree on 7.8% of "land" |
| TR13-4 | `web/app.js:271` | MEDIUM | Medium | a departure with no precomputed surface cannot be represented |
| TR13-5 | `validate.py:54` | LOW | Medium | the coverage gate and the emitters disagree about what "reached" means |
| TR13-6 | `emit/hover.py:50` | LOW | Medium | one constant, two inclusivities |
| TR13-7 | `emit/hover.py:100` | LOW | High | the hover ordering contract is written out four times |
| TR13-8 | `emit/index.py:320` | LOW | High | the reading tier's filename is a literal while its resolution is a constant |
| TR13-9 | `cli.py:351` | LOW | High | the mode breakdown's test path computes a different road class from its build path |
| TR13-10 | `web/app.js:1585` | LOW | Medium | resolves one column from two different gazetteers |

#### `debugger.md` — 9

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| DBG13-1 | `src/transport_maps/emit/hover.py:115-127` | HIGH | Medium | the reading tier prints "no scheduled route" over 13 named cities and 47 named airports. CONFIRMED in the shipped byte |
| DBG13-2 | `src/transport_maps/solve/dijkstra.py:44-54` | MEDIUM | Medium | an origin can now be silently moved up to 13 km, with no log and no bound. NEW, and created by cycle 12's fix. |
| DBG13-3 | `web/index.html:161` | HIGH | Medium | at ≤860 px, every fatal raised after the layout runs is invisible. CONFIRMED by reading; not browser-executed. |
| DBG13-4 | `scripts/deploy_verify.sh:113-124` | HIGH | Medium | a compromised deploy host gets local command execution on the operator's machine. REPRODUCED. |
| DBG13-5 | `scripts/deploy_verify.sh:56-57` | MEDIUM | Medium | the page gate is green with no parser when `node` is missing. REPRODUCED; the claimed counts are wrong and `node` IS o |
| DBG13-6 | `routes.py` | MEDIUM | Medium | permanently wins, so `routes.py`'s stamped cache can never be created. REPRODUCED on disk. |
| DBG13-7 | `src/transport_maps/cli.py:237-251` | MEDIUM | Medium | a per-origin abort leaves eight files from two builds, and nothing after it can tell. REPEAT of DBG12-6, re-measured;  |
| DBG13-8 | `src/transport_maps/sources/routes.py:188-199` | LOW | Medium | a corrupt or hand-edited crawl cache escapes as a traceback. |
| DBG13-9 | `src/transport_maps/solve/dijkstra.py:6, 48` | LOW | Medium | reaches into two private attributes of another module. |

#### `document-specialist.md` — 76

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| DOC13-1 | `plan/deferred.md:595` | HIGH | High | "the fit wanted roadless terrain infinitely fast" is false, and it ships to visitors |
| DOC13-2 | `plan/README.md` | HIGH | High | names two cycles "current" and calls three shipped features unbuilt |
| DOC13-3 | `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md:24` | HIGH | High | the design spec claims the whole six-class road model is fitted, in the one file the guard cannot see |
| DOC13-4 | `countries.py` | HIGH | High | says two borders are excluded, fourteen lines above the list that contains them |
| DOC13-5 | `data/origins.toml:5-7` | HIGH | High | describes a 553-row file selected by one rule; it has 1,464 rows and two |
| DOC13-6 | `scripts/check_dist.py:63-64` | HIGH | High | cites CLAUDE.md for a sentence CLAUDE.md does not contain |
| DOC13-7 | `web/app.js:1936-1938` | HIGH | High | the reading tier is described as dormant in two files; it has been armed since 2026-09-12 |
| DOC13-8 | `src/transport_maps/sources/landmask.py:155` | HIGH | High | the Antarctic cell count is wrong in two files, and one of them refutes itself |
| DOC13-9 | `emit/borders.py` | HIGH | High | 's docstring is measured against a tolerance the module stopped using, and its two safety ratios are 20× and 2× out |
| DOC13-10 | `graph/nodes.py:33-34` | HIGH | High | the airport-snap count is given as 46, 58 and 25 in three places |
| DOC13-11 | `check_dist.py:358` | HIGH | High | uses the 25× multiplier `roads.py:116` explicitly retracts |
| DOC13-12 | `web/app.js:2973` | HIGH | High | says `.depart-card` is fixed at `top:104`; two other comments in the same repo say the opposite |
| DOC13-13 | `tests/graph/test_ferry_model.py:229-231` | HIGH | High | four false mutation certificates, one of them on a genuinely vacuous test |
| DOC13-14 | `validate.py:59` | HIGH | High | understates the cost it exists to justify by 23× |
| DOC13-15 | `web/index.html:1172-1174` | MEDIUM | High | (MEDIUM, High).** `web/index.html:1172-1174` — the `<noscript>` |
| DOC13-16 | `calibration.toml:139` | MEDIUM | High | (MEDIUM, High).** `calibration.toml:139` `detour_factor = 1.2`. |
| DOC13-17 | `calibration.toml:142-143` | MEDIUM | High | (MEDIUM, High).** `calibration.toml:142-143` `boarding_min = 15.0` |
| DOC13-18 | `calibration.toml` | MEDIUM | High | (MEDIUM, High). NEW.** Two fitted constant groups do not live in |
| DOC13-19 | `validate.py:7` | MEDIUM | High | (MEDIUM, High). NEW.** `validate.py:7` `MIN_COVERAGE = 0.90` carries |
| DOC13-20 | `calibrate/fit.py:15` | MEDIUM | High | (MEDIUM, High). NEW.** `calibrate/fit.py:15` `HOLDOUT_FRACTION = 0.2` |
| DOC13-21 | `emit/index.py:76-78` | MEDIUM | High | (MEDIUM, High).** `emit/index.py:76-78` — *"README.md and |
| DOC13-22 | `web/index.html:53` | MEDIUM | High | (MEDIUM, High).** `web/index.html:53` `"dateModified": "2026-09-10"` |
| DOC13-23 | `web/app.js:3368-3369` | MEDIUM | High | "**Four origin names in the 553-origin set** belong to two cities each (Hyderabad, Suzhou, Fuzhou, Taizhou)" | **13**  |
| DOC13-24 | `web/app.js:1235-1236` | MEDIUM | High | "for the **four names** shared by two cities each" | same | High |
| DOC13-25 | `web/index.html:431` | MEDIUM | High | CSS comment: "Only on the **four names two cities share**" | same | High |
| DOC13-26 | `web/app.js:3387-3389` | MEDIUM | High | "Measured at 4.5 ms … when the site had 157 origins; **it has 553 now** … a list **3.5x smaller** than today's" | 1,46 |
| DOC13-27 | `web/app.js:3487-3489` | MEDIUM | High | "with **553 origins, Seoul is row 364 of 461**, about 9,540 px down a 12,072 px scroll box" | Seoul is row **1,133 of  |
| DOC13-28 | `web/app.js:3557` | MEDIUM | High | "With **553 origins** the results list is **~12,000 px tall**" | ~38,357 px at 1,464 — `browser_verify.sh:28` and `app |
| DOC13-29 | `web/app.js:3222` | MEDIUM | High | , `:3228`, `:3438` | "fine at **553** rows"; "the fallback cityCountry() uses for the **553**"; "Filtering **553 origi |
| DOC13-30 | `web/app.js:294` | MEDIUM | High | "beside layoutForSize() **2,260 lines down**" | `layoutForSize()` is at **3981** — 3,687 lines down | High |
| DOC13-31 | `web/app.js:299` | MEDIUM | High | "**~1,600 lines below** beside markBand() and markSpan()" | `markBand` at **2467** (2,168 below), `markSpan` at **2573 |
| DOC13-32 | `web/app.js:301` | MEDIUM | High | "resize and fonts.ready are wired to refreshScale() at **:499-500**" | lines **558-559** | High |
| DOC13-33 | `web/app.js:1555` | MEDIUM | High | "`cities` is declared **several hundred lines** below this point" | `const cities` is at **3192** — 1,637 lines below  |
| DOC13-34 | `web/app.js:1086` | MEDIUM | High | "see **`commitDraggedOrigin`** for what that costs and how the page says so" | No such identifier exists anywhere in t |
| DOC13-35 | `web/index.html:526-528` | MEDIUM | High | (MEDIUM, High). NEW — the drag feature is undiscoverable and |
| DOC13-36 | `web/app.js:1478` | MEDIUM | High | (MEDIUM, High). NEW.** `web/app.js:1478` `const |
| DOC13-37 | `README.md:92-94` | MEDIUM | High | (MEDIUM, High).** `README.md:92-94` — *"Roadless terrain and local |
| DOC13-38 | `CLAUDE.md:23-24` | MEDIUM | High | (MEDIUM, High).** `CLAUDE.md:23-24` — *"(eleven anchors from |
| DOC13-39 | `CLAUDE.md:52-53` | MEDIUM | High | (MEDIUM, High).** `CLAUDE.md:52-53` — see DOC13-18: two fitted |
| DOC13-40 | `web/llms.txt` | MEDIUM | High | (MEDIUM, High). NEW.** `web/llms.txt` has not been touched since |
| DOC13-41 | `web/llms.txt:3-4` | MEDIUM | High | (MEDIUM, High). NEW.** `web/llms.txt:3-4` — *"showing expected |
| DOC13-42 | `web/llms.txt:113-116` | MEDIUM | High | (MEDIUM, High). NEW.** `web/llms.txt:113-116` and |
| DOC13-43 | `web/README.md:28-34` | MEDIUM | High | (MEDIUM, High).** `web/README.md:28-34` — the MapLibre 6.x warning |
| DOC13-44 | `deploy/README.md:81` | MEDIUM | Medium | (MEDIUM, Medium). NEW.** `deploy/README.md:81` — the record of the |
| DOC13-45 | `deploy/README.md:60-73` | MEDIUM | High | (MEDIUM, High). NEW.** `deploy/README.md:60-73` describes |
| DOC13-46 | `scripts/deploy_verify.sh:92-94` | MEDIUM | High | (MEDIUM, High). NEW.** `scripts/deploy_verify.sh:92-94` — *"The |
| DOC13-47 | `scripts/browser_verify.sh:14` | MEDIUM | High | (MEDIUM, High).** `scripts/browser_verify.sh:14` — *"would have |
| DOC13-48 | `scripts/expand_origins.py:4` | MEDIUM | High | (MEDIUM, High).** `scripts/expand_origins.py:4` — usage line |
| DOC13-49 | `scripts/expand_origins.py:148-151` | MEDIUM | High | (MEDIUM, High).** `scripts/expand_origins.py:148-151` — *"the |
| DOC13-50 | `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md:19` | MEDIUM | High | (MEDIUM, High).** `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md:19` |
| DOC13-51 | `web/app.js` | MEDIUM | High | (MEDIUM, High).** `plan/2026-09-13-c10-requested-features.md:59-62, |
| DOC13-52 | `web/app.js` | MEDIUM | High | (MEDIUM, High).** The twelve `web/app.js` line citations in |
| DOC13-53 | `plan/2026-09-10-c2-gates-and-tests.md:114-115` | MEDIUM | High | (MEDIUM, High).** `plan/2026-09-10-c2-gates-and-tests.md:114-115` |
| DOC13-54 | `tests/test_golden.py:1-3` | MEDIUM | High | (MEDIUM, High).** `tests/test_golden.py:1-3` — *"deliberately loose |
| DOC13-55 | `cli.py:597` | MEDIUM | High | "applied to the **four fields** that describe the ARTIFACTS" | `_CURRENT_INDEX_CONSTANTS` (`cli.py:447-473`) holds **n |
| DOC13-56 | `web/index.html:20` | LOW | Medium | (LOW, Medium).** `web/index.html:20` — `og:image:alt`: *"A dark |
| DOC13-57 | `calibration.toml:268` | LOW | Low | (LOW, Low).** `calibration.toml:268` — *"**240** crossings get a |
| DOC13-58 | `web/README.md:62` | LOW | High | (LOW, High).** `web/README.md:62` — *"Every file in `vendor/` |
| DOC13-59 | `web/llms.txt:129` | LOW | High | (LOW, High).** `web/llms.txt:129` — documents `?from=<slug>` alone. |
| DOC13-60 | `README.md` | LOW | High | (LOW, High).** `README.md` mentions neither the departure-list cap |
| DOC13-61 | `deploy/README.md:48` | LOW | High | (LOW, High).** `deploy/README.md:48` — "it is **step 8**". |
| DOC13-62 | `scripts/check_dist.py:5` | LOW | High | (LOW, High).** `scripts/check_dist.py:5` usage line omits |
| DOC13-63 | `scripts/check_ramps.py:12` | LOW | High | (LOW, High). NEW.** `scripts/check_ramps.py:12` usage line is bare |
| DOC13-64 | `scripts/check_ramps.py:56` | LOW | High | (LOW, High). NEW.** `scripts/check_ramps.py:56` — "the discrepancy |
| DOC13-65 | `scripts/browser_verify.sh:347` | LOW | Medium | (LOW, Medium).** `scripts/browser_verify.sh:347` and |
| DOC13-66 | `plan/deferred.md` | LOW | High | (LOW, High).** `plan/deferred.md`'s ~19 occurrences of 553, the 7 in |
| DOC13-67 | `validate.py:177` | MEDIUM | High | , `cli.py:343` | "recomputing it here cost **~4.8 s** of `roads.cell_class` work per origin" | The 4.8 s figure is sta |
| DOC13-68 | `sources/roads.py:117` | MEDIUM | High | "full pass over the res-5 grid's **548,557** cells" | ~**600,382** distinct res-5 parents of the current stamped res-6 |
| DOC13-69 | `sources/landmask.py:32-34` | MEDIUM | High | "Antarctica has no scheduled service, so **it is excluded**" | It is not. The same comment's preceding clause says so, |
| DOC13-70 | `emit/tiles.py:20` | MEDIUM | High | "z7 measured ~**38%** larger than z6" | **61%**, from the same comment's own figures three lines up: 3.84 MB / 2.38 MB |
| DOC13-71 | `emit/index.py:112-113` | MEDIUM | High | , `:332-333` | "Hyderabad, Suzhou, Fuzhou and Taizhou each appear twice"; "**four** origin names … shared by two citie |
| DOC13-72 | `contour/grid.py:3-4` | MEDIUM | Medium | "leaves every shore an **8 km** hex stair-step" | Every other res-6 figure in the codebase says 6.5 km across (`config |
| DOC13-73 | `graph/ground.py:29` | MEDIUM | High | "Measured at **8.0 per cell** over the res-6/7 universe (**82 M edges over 10.2 M cells**)" | 82,110,682 edges over ** |
| DOC13-74 | `sources/wikidata.py:198-199` | MEDIUM | High | , `tests/sources/test_wikidata.py:3-4`, `tests/sources/test_routes.py:116` | "routes.route_network writes its result t |
| DOC13-75 | `tests/sources/test_landmask.py:65` | MEDIUM | High | "the real `data/build/**land_cells_r5.parquet**` cache" | The path is `land_cells_r{res}_{stamp}.parquet` (`landmask.p |
| DOC13-76 | `sources/landmask.py:138` | MEDIUM | High | docstring "The cell over the South Pole **and its ring**" | The cell and **two** rings: `h3.grid_disk(centre, 2)` at ` |

#### `feature-dev-code-reviewer.md` — 7

| ID | file:line | sev | conf | finding |
|---|---|---|---|---|
| FCR13-1 | `web/app.js:718` | HIGH | Medium | + `web/index.html:161` | On phones and tablets `fatal()` writes its message into `.reading`, which `body.fatal` has ju |
| FCR13-2 | `web/boot.js:121` | MEDIUM | Medium | The 25 s watchdog arms on `load`, which `app.js`'s top-level await never reaches if a fetch hangs. |
| FCR13-3 | `scripts/osm_rail.sh:24` | MEDIUM | Medium | Bare `-f` existence check treats a half-written `-rail.osm.pbf` from a killed osmium run as complete. |
| FCR13-4 | `web/app.js:3937` | LOW | Medium | detaches the legend's band mark and bracket; `pickOcean` re-appends neither. |
| FCR13-5 | `web/app.js:3529` | LOW | Medium | has no timeout or abort; one stalled request blocks every later geocode. |
| FCR13-6 | `web/app.js:3095` | LOW | Medium | runs ~1.32 M haversines synchronously on the load path. |
| FCR13-7 | `scripts/browser_verify.sh:204` | LOW | Medium | matches nothing; `app.js` emits `data-airport`, so the selector is dead. |

## Status

Cycle 13: six tasks done, five scheduled, the rest deferred with exit criteria
above. No finding was dropped. The three lanes that agreed on a NON-finding are
recorded in `.context/reviews/_aggregate.md` so the mixed-resolution grid is not
re-reviewed from scratch next cycle: `tracer` traced base order against native
order against hover order end to end and found no defect, and `debugger`
independently re-derived `emit/hover.py`'s base-7 slot arithmetic and agreed on
every index including the pentagon parent.
