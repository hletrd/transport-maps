# Cycle 5 — the page a visitor actually gets, and the defects that break it

Derived from the twelve cycle-5 reviews in `.context/reviews/` (per-agent files
plus `_aggregate.md`, clusters Z1…Z10, per-agent IDs `CR5-n`, `PR5-n`, `SEC5-n`,
`CRIT5-n`, `VER5-n`, `TE5-n`, `TR5-n`, `ARCH5-n`, `DBG5-n`, `DOC5-n`, `UX5-n`,
`FCR5-n`). 83 raw findings, 70 after dedupe.

The user's brief for this run is "more details, higher quality and design and
ease of usage and UI. Do not overwork." The orchestrator asked cycle 5 to be
smaller than cycle 4 and to prefer the handful of changes that most improve what
a visitor sees and does, plus any genuine correctness defect. This plan is that
handful: **29 tasks**, against cycle 4's 28 and cycle 3's 31, and almost all of
them are one to fifteen lines.

Everything not scheduled here is recorded in `plan/deferred.md` with its
citation, its original severity and confidence, the reason, and the exit
criterion that reopens it. Nothing is dropped.

## The one finding that should not have survived four cycles

Three reviewers found **Z1** independently — the tracer called it Critical, the
debugger and the second-opinion reviewer High. `web/boot.js` was added in cycle 4
to catch the failure CLAUDE.md names as this project's recurring one. It catches
a different thing as well: **any** third-party subresource failure. The page
loads exactly one, the Google Analytics tag, and when a content blocker kills it
the guard hides the entire side rail on a page whose globe is drawing perfectly.

That is a guard that breaks the site for a large, ordinary population of
visitors — ad-blocker users, Pi-hole households, corporate networks, everyone in
mainland China. It is V1, it lands first, and it gets a browser test.

---

## Tier A — page defects a visitor hits (schedule: cycle 5)

| # | Task | Findings | Files | Verification (the mutation that must go red) |
|---|---|---|---|---|
| **V1** | Ignore cross-origin subresource failures in `boot.js`'s resource-error branch. The guard exists for *this* origin's files; a blocked `googletagmanager.com/gtag/js` must not set `body.fatal`, must not hide `.rail`, and must not latch `shown`. | Z1 = `TR5-1` Critical/High, `DBG5-1` High/High, `FCR5-1` High/High | `web/boot.js:34-42` | Point `index.html:7` at an unreachable host, load the page, assert `body.fatal` is absent and `.results button[data-slug]` is non-empty. Revert the origin test and it must go red. |
| **V2** | Guard `paintOrigin` against being called for the city already active. Put the guard **inside** `paintOrigin`, not at the fifth call site, so a sixth cannot reintroduce it. U13 is ticked and only its `#tip` half shipped. | Z2 = `VER5-6` Low-Med/High, `FCR5-2` Medium/High | `web/app.js` results-list handler + `paintOrigin` | Remove the early return; clicking the `aria-current="true"` row must again fly the camera to the world view and re-fetch. |
| **V3** | Give the tile-failure notice its own element instead of borrowing `#where`, and stop latching `tileTroubleShown` per session. Also stop `settle()` deciding whether to restore the idle prompt by string-matching `#where.textContent`. | Z3 = `TR5-5` Medium/High, `DBG5-3` Medium/High; `DBG5-8` Low/High | `web/app.js` `noteTileTrouble`, `settle` | Fire a synthetic map `error` with "pmtiles", then move the pointer: the notice must survive. Restore the `#where` write and it must vanish. |
| **V4** | Make the `requestIdleCallback` fallback time-aware. `timeRemaining: () => 8` is a constant, so the budget check never trips and the whole 90,740-cell pass runs in one task — on every Safari and every iPhone, on the load path, against the code's own 50.3 ms measurement. | Z4 = `PR5-1` Medium/High, `DBG5-5` Medium/High | `web/app.js:113-121` | Restore the constant and assert the shim's `timeRemaining()` decreases across a slice. |
| **V5** | Keep keyboard focus on the departure row across `settle()`'s `render()`, and make the row's disambiguation not depend on `places.json` winning a race against `{slug}.bin`. | `DBG5-4` Medium/High, `CR5-4` Medium/High | `web/app.js` `render`, `settle` | Delete the focus restore; tab to a city row, wait for `settle()`, and `document.activeElement` must fall back to `<body>`. |

## Tier B — ease of use and UI, the user's brief (schedule: cycle 5)

The designer measured each of these at 1280×800, 820×1180, 390×844 and 844×390
against a local server. Ranked by improvement per unit of effort. **None of them
touches the CLAUDE.md design policy**: no `letter-spacing`, no uppercase, no
tabular figures, no new legend tick, dark theme throughout.

| # | Task | Findings | Files | Verification |
|---|---|---|---|---|
| **V6** | Scroll the departure list to the current departure. Seoul is row 364 of 461, ~9,540 px down a 12,072 px box whose `scrollTop` is 0. Today the list opens on "Aba". | `UX5-1` High/High | `web/app.js` `render` | Load with `?from=seoul`; the active row's `offsetTop` must be within the scroll viewport. |
| **V7** | `prepend` the address-search result list instead of `append`, and re-resolve the container each time so a concurrent `render()` cannot leave the write in a detached node. A short query currently writes its message at viewport y 12,326 in a box that ends at 471 — the button reads as broken. | `UX5-2` High/High, `CR5-6` Low/Medium | `web/app.js` `searchAddress` | Search with a two-character query; the message must be visible without scrolling. |
| **V8** | One caption above the departure list saying what the times measure and in which direction. A row's accessible name is "London 15 h 15 min" — the time **to** London — and activating it **departs from** London. The only direction statement and the only "door to door" live in a `title`, invisible on touch. CLAUDE.md: "say so wherever a figure is presented." | Z5 = `UX5-3` High/High, `CRIT5-5` Medium/High, `VER5-2` Medium/High | `web/index.html`, `web/app.js` | Assert the caption text is in the DOM and is not inside a `title` attribute. |
| **V9** | Mark the current reading on the legend strip. `bandRangeOf` already computes the band index and discards it. Adds a marker, **not a tick** — CLAUDE.md's rule that ticks sit at true band boundaries is untouched. | `UX5-4` Medium/High | `web/app.js`, `web/index.html` | Hover a cell; the marker's left offset must track the band index. |
| **V10** | Paint the two legend swatches with their real default fills and put a placeholder in `#time`. During 1.59 MB gzipped of blocking fetches the page shows a legend naming two colours it does not paint, under an empty 50 px slot. | `UX5-9` Medium/High | `web/index.html` | Load with the network throttled; the legend must not name an unpainted colour. |
| **V11** | `position: sticky` on the phone grab handle. At 390×844 `revealReading()` leaves the handle at y 378-406 above a rail starting at 405. | `UX5-5` Medium/High | `web/index.html` | At 390×844, reveal the reading; the handle must stay in view. |
| **V12** | Give the map canvas a real accessible name via MapLibre's `locale` (`Map.Title`). The focused canvas is announced as "Map"; `#map`'s 190-character description is never read. WCAG 4.1.2. | `UX5-6` Medium/High | `web/app.js` | Accessibility snapshot: the canvas's name must not be the bare string "Map". |
| **V13** | Announce the departure-filter result count, and resolve `#status` when the arrays land. Filtering 461→0 announces nothing today, and `#status` still read "Loading travel times" long after loading finished. WCAG 4.1.3. | `UX5-7` Medium/High | `web/app.js` | Filter to zero results; `#status` must carry a count. |
| **V14** | Bring the Settings checkboxes and the origin labels to a 24 px hit area. Measured 15×15 px and 23 px below 860 px, against N18/D16's ticked "24 px hit area" claim. WCAG 2.5.8. | `UX5-10` Medium/High | `web/index.html` | Computed height of both targets must be ≥ 24 px at 390×844. |
| **V15** | A visible "Copy link" beside "Clear". `grep` finds no share affordance at all, so U11's `?to=` permalink is unreachable by a visitor who does not read the address bar. | `UX5-8` Medium/High | `web/index.html`, `web/app.js` | The control must exist and write `location.href` to the clipboard. |

| **V29** | Move the analytics tag from the head's first subresource to after every preload. Measured: 190,810 B gzipped on the wire and 579,003 B of JavaScript to parse, plus two extra third-party connection setups, all queued ahead of `index.json` and `hover_cells.bin` -- the two files the page needs before it can draw anything. `async` governs execution, never the order the preload scanner discovers a tag in. | `PR5-2` Medium/High | `web/index.html` | The `<script src=googletagmanager>` index in `document.head.children` must exceed the first `rel=preload` index. |

## Tier C — what the page says about itself (schedule: cycle 5)

| # | Task | Findings | Files | Verification |
|---|---|---|---|---|
| **V16** | Four copy corrections in one commit: `llms.txt`'s connection cap ("about an hour to an hour and a half" against the code's 55 min – 1 h 40); "more than a hundred cities" → a wording true of 553 that still satisfies `check_dist.COUNT_CLAIM`'s ban on a hard number; `boot.js` added to `web/README.md`'s deployed-asset list; the contrast figure at `index.html:101-102` (says 2.0:1, measured 3.0). | Z7 = `VER5-1` Low/High + `DOC5-4` Low/High; `DBG5-6` High/High; `DOC5-5` Low/High; `DOC5-7` Low/High | `web/llms.txt`, `web/index.html`, `web/README.md` | `grep` for each old string returns nothing; the licence-firewall and `check_dist` gates stay green. |
| **V17** | Say what the model does not know, where the figure is. The project measured its own error and publishes none of it: `holdout_mae_min = 9.3`, a signed-bias table, a 0.977 ground fit; and `calibration.toml:21-25` says the airborne fit is valid 150–6,000 km while 5.67 % of route legs lie outside it carrying 23.1 % of all modelled airborne minutes — i.e. the intercontinental readings are the extrapolated ones. Also fix "X % has no scheduled route **from here**": the figure is a property of the destination cell, identical from every origin, so the wording is wrong, not the arithmetic. | `CRIT5-2` High/High, `CRIT5-3` High/High, `CRIT5-1` High/High, `CRIT5-4` Medium/High | `web/index.html`, `web/llms.txt`, `web/app.js` reach summary | The hold-out error and the extrapolation limit must appear in the page's own prose, not only in `calibration.toml`. |

## Tier D — pipeline correctness (schedule: cycle 5)

| # | Task | Findings | Files | Verification |
|---|---|---|---|---|
| **V18** | Extend `reindex`'s drift refusal to every constant `write_index` derives from — `HOVER_RES` above all, the binary-search key the page uses. Drift republishes an index under which `cellIndex` misses every id and **the page reads "Open water." over all land**, past `check_dist` and past `hoverCellCount`. Add `config.UNREACHABLE` to `build_identity`'s `inputsHash`. | Z6 = `CR5-1` Medium/High + `ARCH5-1` Medium/High; `CR5-2` Low/High | `src/transport_maps/cli.py:390-394,505-513`, `src/transport_maps/emit/index.py:203-210` | Move `HOVER_RES` in `config.py` and run `reindex`: it must refuse. Remove the field from the refusal tuple and it must republish. |
| **V19** | Two repairs to the PMTiles metadata-leak detector: drop `"generator_options"` from `PMTILES_METADATA_LEAKS` (tippecanoe writes it unconditionally, so a **perfectly clean** archive trips the detector and the warning carries zero signal), and order the truncated report by severity rather than alphabetically by filename, so `water.pmtiles` — the only archive carrying `/Users/<username>` and the only one `build-all` can never fix — is not the one that falls off the list. | `SEC5-2` Medium/High, `SEC5-1` Low/High | `scripts/check_dist.py:42-43,297-302`, `tests/web/test_check_dist.py` | Build a clean tippecanoe archive in the scratchpad; the detector must stay silent. Restore the tuple entry and the new fixture must go red. |
| **V20** | `map.keyboard.enableRotation()` where `enable()` is written. MapLibre keeps `_enabled` and `_rotationDisabled` separate, so unticking "Lock to north" restores mouse and touch bearing but never keyboard bearing or pitch. | `CR5-3` Low/High | `web/app.js:621-634` | Untick the box and press `Shift+ArrowLeft`; the bearing must change. |

## Tier E — tests that go red under a stated mutation (schedule: cycle 5)

CLAUDE.md: "assume a new test is vacuous until shown otherwise." Each of these
names the mutation it must catch, and each mutation is performed and reverted
before the commit lands.

| # | Task | Findings | Files | Mutation |
|---|---|---|---|---|
| **V21** | A real browser test for `boot.js` — the guard against the failure CLAUDE.md names as recurring is pinned today by three `substring in BOOT` checks. `if (cities > 0)` → `if (cities >= 0)` leaves the watchdog permanently inert and the suite green. `boot.js` is a 62-line classic-script IIFE with no imports and no awaits, so F5's stated blocker does not apply: this is the cheapest real browser test in the repo, and it is also V1's regression test. | `TE5-2` High/High, `ARCH5-5` Medium/High | new `tests/web/`, `scripts/browser_verify.sh` | `cities > 0` → `cities >= 0`; and the V1 origin test removed. |
| **V22** | Assert `check_dist.main()`'s **exit code** — the only thing `deploy_verify.sh` reads — and the refusal messages that are asserted by nothing today, two of which are exactly the states `reindex` can produce. | `TE5-7` High/High | `tests/web/test_check_dist.py` | Delete `sys.exit(1)` from `check_dist.main()`. |
| **V23** | Cover `solve/dijkstra.py`'s `directed=True` and its `with_predecessors=True` branch. Both existing fixtures are upper-triangular, so `directed=False` gives byte-identical output; and the predecessors branch — the only one `cli.py:216` uses in production — is entered by no test at all. | `TE5-1` High/High | `tests/solve/` | `directed=True` → `False`; and drop `with_predecessors`. |
| **V24** | Make the privacy-policy test assert the **real** localStorage keys (`ramp`, `lockNorth`, `namePlaces`), not the checkbox element ids it names today (`lock-north`, `show-places`). As written it is a bare substring clause that bounds nothing: adding `localStorage.setItem("visitor-id", …)` makes the posted privacy policy false and leaves all 460 tests green. | Z8 = `VER5-5` Low/High + `TE5-5` Medium/High | `tests/web/test_attribution_and_privacy.py` | Add a fourth `setItem` with a key the policy does not name. |
| **V25** | Add `tests/web/test_ramps.py` — the band-colour separation measurement CLAUDE.md mandates — and `tests/emit/test_water.py` to `deploy_verify.sh`'s `page_gate()`, whose file list is hand-typed and omits them. A test's teeth should not depend on its filename. | `TE5-4` Medium/High, `ARCH5-6` Medium/Medium | `scripts/deploy_verify.sh` | Break a ramp's monotonic lightness; `--page-only` must refuse. |

## Tier F — deploy readiness (schedule: cycle 5)

| # | Task | Findings | Files | Verification |
|---|---|---|---|---|
| **V26** | A free-space pre-flight in `deploy_verify.sh`. The pending payload is ≈15.7 GB against ≈2.6 GB live — ~6×, never rehearsed — and `--delay-updates` stages the new payload **plus** the old set, so peak is ~18 GB. There is no `df` check anywhere, and running out mid-rename produces the exact mixed `dist/` the gate exists to prevent. Read-only `df` over the existing ssh connection; refuse below payload × 1.3. | `CRIT5-6` Medium/High | `scripts/deploy_verify.sh` | Set the threshold above the real free space; the deploy must refuse before any byte moves. |
| **V28** | Refuse an `index.json` whose `attribution` does not name every entry of `emit.index.ATTRIBUTION`. **HydroLAKES lakes (CC BY 4.0) are drawn on the live map and credited nowhere**: the live `index.json` carries 7 entries, the deployed `app.js` has no `PAGE_CREDITS`, the deployed `index.html` no `legend-credit`. Confirmed by a Range request against the live `water.pmtiles`, whose `generator_options` names `lakes.geojson`. The repo's code is already correct, so **this cycle's deploy is the remedy** — which makes shipping it a licence obligation. The gate is what stops it recurring. | `DOC5-1` High/High | `scripts/check_dist.py`, `tests/web/test_check_dist.py` | Drop one entry from a fixture `index.json`'s `attribution`; `check_dist` must refuse and name the missing source. |
| **V27** | Record, do not weaken. `dist/origins/las-vegas.pmtiles-journal` exists on disk and matches `check_dist`'s `STRAY` regex, which runs **before** the rsync that excludes it, so the next **full** deploy hard-fails on it. This was I4/L5/SEC3-1, a nice-to-have; it is now a blocker. The orchestrator's standing constraint forbids deleting files under `dist/`, and CLAUDE.md requires confirmation before a destructive step, so **this task does not delete it**: it records the blocker, states the one-line owner action, and refuses to loosen `STRAY` to make a deploy pass. | `I4`/`L5`/`SEC3-1`, promoted by `TR5-3` | — | The gate stays exactly as strict as it is. |

---

## Progress

_Updated as the cycle runs._

| Task | State | Commit | Mutation shown red |
|---|---|---|---|
| V1 | done | `dbc6864` | `ourOwn(url)` deleted -> 2 boot tests red |
| V2 | done | `23c9b83` | early return removed -> camera flies to world view |
| V3 | done | `2372a14` | `#where` write restored -> notice vanishes on mousemove |
| V4 | done | `9965905` | constant `timeRemaining` restored -> shim never yields |
| V5 | done | `e3101c5` | focus restore deleted -> `activeElement` falls to `<body>` |
| V6 | done | `e3101c5` | scroll block deleted -> list opens on "Aba" |
| V7 | done | `23be1c4` | `prepend` -> `append` puts the message at y 12,326 |
| V8 | done | `1ddfced` | caption removed -> direction lives only in a `title` |
| V9 | done | `54f97cc` | `markBand` removed -> the strip has no reading |
| V10 | done | `54f97cc` | em dash restored -> `test_the_idle_readout...` red |
| V11 | done | `5fbf4a3` | measured at 390x844 by the designer, not re-measured here |
| V12 | done | `5fbf4a3` | `locale` removed -> canvas is named "Map" |
| V13 | done | `5fbf4a3` | announce removed -> filtering to zero is silent |
| V14 | done | `5fbf4a3` | `min-height` removed -> 15x15 and 23 px targets |
| V15 | done | `5fbf4a3` | control removed -> no share surface at all |
| V16 | done | `4879a46` | old strings restored -> `grep` finds them again |
| V17 | done | `4d8e081` | section removed -> zero matches for hold-out in `web/` |
| V18 | done | `c82dadc` | `hoverRes` dropped -> 2 red; `UNREACHABLE` dropped -> 1 red |
| V19 | done | `8232d6e` | `generator_options` restored -> a clean archive warns |
| V20 | done | `83fb802` | verified against the vendored `KeyboardHandler` source |
| V21 | done | `dbc6864` | `cities > 0` -> `>= 0` -> 2 red |
| V22 | done | `8232d6e` | `sys.exit(1)` deleted -> 2 exit-code tests red |
| V23 | done | `b562f0f` | `directed=False` -> 1 red; `return_predecessors=False` -> 1 red |
| V24 | done | `83fb802` | a fourth `setItem` -> red |
| V25 | done | `83fb802` | gate now runs `tests/web/` whole; `test_ramps` reached |
| V26 | done | `83fb802` | threshold above real free space -> refuses before any byte moves |
| V27 | recorded | - | no code change by design; see below |
| V29 | done | `pending` | gtag at head index 33, first preload at 21; page verified in a browser |
| V28 | done | `8232d6e` | attribution block deleted -> `test_an_index_that_drops_a_credit` red |

### V27 — the stray journal file, recorded rather than removed

`dist/origins/las-vegas.pmtiles-journal` exists on disk. `check_dist`'s
`STRAY` regex (`scripts/check_dist.py:28`) matches `.*-journal`, and that scan
runs **before** the rsync whose exclude list would have dropped it, so the next
**full** deploy hard-fails on it. It was I4 / L5 / SEC3-1, a nice-to-have; it is
now a blocker.

**This task deliberately changes nothing.** Two rules apply and they agree:

- the orchestrator's standing constraint for this run forbids deleting or
  rewriting files under `dist/` outside what `reindex` and the deploy do;
- CLAUDE.md's destructive-action rule requires confirmation before a delete.

And weakening `STRAY` to let a journal file through would be exactly the
"do not weaken a gate to make a deploy pass" failure the run brief names.

The owner action is one line, and it is theirs to run:

```
rm dist/origins/las-vegas.pmtiles-journal
```

It is a tippecanoe temp file left behind by an interrupted origin build. The
corresponding `las-vegas.pmtiles` should be confirmed present and well-formed
first (`uv run python scripts/check_dist.py --dist dist` reports it either way).

### Two things this cycle found and did NOT do

**The rail data about to ship carries a known defect.** `TR5-2`: the in-flight
build read the pre-fix parquet, so 199-226 of each origin's ~2,000 named rail
stations sit on a fabricated adjacency, and the tooltip names the line from the
same spliced sequence the edge was booked from -- so both are wrong together.
The code fix landed in `87aec6f`; only the data is stale. The orchestrator has
decided to ship it, on the stated ground that what is live carries the same
defect and is a day older. Recorded in `deferred.md` with a rail edge-length
gate as the exit criterion.

**`dist/` is mid-rebuild as this plan closes.** `index.json` says `solveRes: 5`,
`hoverRes: 4` and 157 origins while 461 `{slug}.json` on disk are res-6. That is
the state `reindex` exists to correct and V18 now refuses to correct wrongly.

### Evidence from running the gate against the real `dist/` (17:41, mid-rebuild)

`uv run python scripts/check_dist.py --dist dist --web web`, read-only, with the
build still running. Three of this cycle's tasks are confirmed on the actual
artifacts rather than on a fixture:

**V19 — the grouped warning report.** `water.pmtiles` is now the *first* line:

```
  WARNINGS (not blocking):
    1 x metadata contains '/users/': a build-host path served to every visitor  [water.pmtiles]
    157 x metadata contains '/var/folders/': ...  [abu-dhabi.pmtiles, abuja.pmtiles and 155 more]
```

Under the old `sorted(set(warnings))[:8]` those 158 warnings printed as eight
filenames beginning with "a", and the one archive carrying a `/users/` path --
the only one `build-all` can never fix -- was never shown. It is now
unmissable, and the 157 are one line instead of an unreadable truncation.

**V28 — the attribution gate, on the live index:**

```
    index.json attribution does not credit GeoNames, HydroLAKES, which the
    pipeline consumes and whose licence requires it.
```

That is `DOC5-1` reproduced against the artifact that is serving the public site
right now. HydroLAKES is CC BY 4.0 and its lakes are drawn on the live map.
**This cycle's deploy is the remedy**, which is why shipping it is an
obligation rather than a nicety.

**V27 — the stray, confirmed as a blocker:**

```
    stray file origins/las-vegas.pmtiles-journal (an aborted writer's leftover)
```

The other three problems (157 of 553 origins, no `modeChannels`, no
`hoverCellCount`) are the mid-rebuild state and are what `reindex` exists to
resolve once the build exits.

`deploy_verify.sh`'s step-1 guard was also checked against the live process
table and correctly identifies the four busy workers, so it will refuse a
mixed `dist/` without being asked to.
