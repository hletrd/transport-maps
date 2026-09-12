# Cycle 7 — readings at resolution 6, and the eight high-severity defects

Derived from `.context/reviews/_aggregate.md` (clusters `AB1`…`AB58`, 121 raw
findings from eleven reviewers, 58 after dedupe) and from the owner's decision
on `AA6`.

Task IDs are `C7-1`…`C7-18`.

---

## The decision, and why the validated design changed shape

The owner was asked to choose on `AA6` — the hover reading is a res-4 cell
about 45 km across while the painted bands are res 6/7, so 28.0 % of sampled
land points read a band the map does not paint under them, median 17.2 km
between the point pointed at and the point measured, and Hong Kong and
Shenzhen share one reading cell whose value point is in the Pearl River
estuary.

**The owner chose readings at resolution 6, matching the painted base grid**,
and added: *"I have a lot of traffic budget. Just take care of performance on
mobile network and mobile devices."*

The orchestrator pre-validated a design and asked for it to be implemented
*unless a concrete reason was found that it cannot work*. A concrete reason was
found, in the transport half only. The block **layout** is implemented exactly
as specified. The **range-fetch transport** is not, and this section is the
required account of why.

### What survives, verified here rather than taken on trust

A res-3 cell contains 343 res-6 cells, and the child slot can be computed
arithmetically from the H3 id, so **no cell-id list is needed for the values**
— the 32.7 MB index the owner was worried about disappears, exactly as the
design intended. Verified in this repo against the real land-cell universe
(`data/build/land_cells_r6_74c3737a.parquet`, 4,091,715 cells):

| | |
|---|---|
| res-6 land cells | 4,091,715 |
| res-3 parents holding land | 14,598 |
| slot = `d4·49 + d5·7 + d6`, range | 0…342 |
| distinct `(parent, slot)` keys | **4,091,715 of 4,091,715 — a bijection** |
| res-4 parents of those cells | 90,740 — *exactly* `hover_cells.bin` |

The digit form is used rather than `cell_to_child_pos`, because of AB4: two
res-3 parents are **pentagons** — `830800fffffffff` (Norwegian coast) and
`833000fffffffff` (Bohai/Liaodong, which contains the departure city **Dalian**)
— and they have **286** children, not 343. `cell_to_child_pos` and digit order
disagree for those. The digit form is a bijection over all of them, and the
block stride stays the constant 343 with the 57 missing slots padded. Confirmed
by five reviewers independently (PR7-3, CRIT7-2, TR7-16, TE7 §3, DBG7).

That the res-4 parents of the res-6 land set are *exactly* `hover_cells.bin` is
the fact that makes the two tiers safe to hold at once: they describe the same
universe at two resolutions, and neither can silently cover ground the other
does not.

### What cannot work: the range-fetch transport

Three independent, measured reasons. Each alone is disqualifying.

**AB1 — nginx cannot byte-range a gzipped response, and `.bin` is gzipped.**
`deploy/worldmap.atik.kr.conf:65-71` sets `gzip on` for `location ~* \.bin$`.
Two reviewers measured the live host with only `Accept-Encoding` varying and
got the same answer: `gzip` returns **HTTP 200 with the whole file**;
`identity` returns 206. Browsers always send `gzip` and **cannot be made not
to** — `Accept-Encoding` is a forbidden header name in Fetch, so `fetch()`
cannot override it. A range-fetched `.bin` would return the entire array and
the page would read slot 0 for every point on Earth: a globe of plausible
wrong times, no console error. Twelve lines below, the `.pmtiles` block states
this rule correctly and sets `gzip off` — which is why PMTiles ranging works
and a new `.bin` ranging would not. The existing range probes at
`scripts/deploy_verify.sh:161-162` cannot see it: `curl -r` sends no
`Accept-Encoding`, so they test a path no browser takes. The server config is
out of scope this cycle by the orchestrator's own constraint, so the transport
must work against the config as it stands.

**AB2 — two existing features read the whole array, so per-view fetching
multiplies rather than divides the cost.** The departure card's reach
percentages scan every entry on every settle (`web/app.js:1015-1046`), and the
departure list calls `lookup()` once per city for 553 cities (`:2131`).
Measured: those cities fall in **517 distinct res-3 parents** — 517 range
requests per origin switch for a figure that costs nothing today — and the
reach scan needs all 14,598. Measured ceiling on a 2.5 ms-RTT link: 200
parallel range requests take 622 ms, and parallelism above ~20 buys nothing.
On a mobile network that is seconds per city switch, repeated on every reload
because everything is `no-cache`. The design was adopted to protect mobile
latency; ranging would spend it.

**AB3 — one ordinal addresses four arrays.** `cellIndex()` (`web/app.js:1336`)
returns a single res-4 ordinal used for `origin.times`, `origin.air` (`:1438`),
`origin.modes` (`:1498`) and `origin.rail.idx` (`:1462`). Re-emitting all four
at res 6 is 90.1 MB raw per origin and ~49.8 GB over 553. The res-4 grid
cannot be *replaced*; it can only be *joined*.

### What is implemented instead

**The same block layout, fetched whole, as a second tier.**

- **Tier A** stays exactly as it is: `dist/origins/{slug}.bin`, res-4, 181,480 B.
  It keeps addressing the air, modes and rail arrays, the charted mask and the
  reach percentages. Nothing about it changes, so nothing that depends on it
  can regress.
- **Tier B** is new: `dist/origins/{slug}.r6.bin`, the 14,598 × 343 × uint16
  block array, **10,014,228 B**, fetched **whole, once per origin, lazily,
  after tier A has settled**, and aborted on origin change by the
  `AbortController` the loader already has.
- **The block directory** is `dist/reading_parents.bin`: the 14,598 sorted
  res-3 parent ids as uint64, **116,784 B**, **17,789 B gzipped**, fetched
  **once for the whole site** and shared by every origin — the block set is
  identical across origins, only the values differ. This is the one thing the
  orchestrator asked to be considered and the answer is yes.
- `lookup()` reads tier B when it is present and tier A until then, so the
  reading is *never worse than today* and never blocks on the new file.

This keeps the design's whole point — arithmetic addressing, no per-origin
cell-id list, readings on the painted base grid — and drops only the transport
that the server config and the page's own consumers rule out.

### What it costs, measured

Raw sizes are measured exactly. The gzipped figure is **modelled**, and is
labelled as such because the true number cannot be known until the orchestrator
rebuilds — no res-6 minute field for a real origin exists on disk, and
`build-all` is out of scope this cycle.

| | bytes | note |
|---|---|---|
| tier B per origin, raw | 10,014,228 | measured exactly; 18.3 % padding |
| tier B per origin, on the wire | ~3.5–5.2 M | **modelled**, see below |
| block directory, once per site | 116,784 raw / 17,789 gzipped | measured exactly |
| per view, after the origin is loaded | **0** | tier B is resident; a reading is one binary search plus one array read |
| peak client memory added | 10.0 MB | one `Uint16Array`, evicted on origin change |
| decode cost | **0** | a typed-array view over the buffer; no parse |
| added requests per origin switch | **1** | against 517 for the ranged design |
| added requests on the critical path | **0** | tier B starts after tier A settles |

The wire estimate comes from two independent methods that agree. The true res-4
neighbour gradient was measured over 243,234 real adjacent pairs
(mean |Δ| 114.6 min, median 49); scaling by the 7× linear step from res 4 to
res 6 and re-compressing the real block layout gives **5.2 MB** at gzip level 6
— a random-walk residual, so an over-estimate of the entropy a shortest-path
field actually has. The `architect`'s independent DPCM model, validated to
2.9 % against the measured res-4 array, gives **3.5–4 MB**. The measured
extremes bracket it: a piecewise-constant field (residual ≡ 0) gives 0.34 MB
and the raw array is 10.01 MB. `C7-6` makes the build print the true figure so
the rebuild settles it rather than leaving an estimate in the record.

For scale, the measured res-4 array compresses 181,480 → 130,808 B (ratio
0.721 at level 6, 0.726 at level 1 — the server does not set
`gzip_comp_level`, so level 1 is what it serves).

### What this still does not fix, stated plainly

**In refined areas the painted band is res 7 and the reading is res 6, so the
reading and the paint still do not agree exactly there.** A res-6 cell has
seven res-7 children; where `graph/refine.py` split a cell, the map paints
sub-cells the reading averages over. This is a real, remaining discrepancy, it
is not being papered over, and `C7-9` puts it in the page's own words rather
than leaving the page silent about its precision as it is today (AB15). Outside
refined areas — most of the world — the reading is now on exactly the grid the
band is painted from.

**Tier B covers the headline time only.** The arrival airport, the mode
breakdown and the rail detail stay on tier A, because AB3 prices res-6 for all
four at 90.1 MB per origin. So the big number is res-6 and the breakdown under
it is res-4. `C7-9` says so on the page.

### Options considered and rejected

- **Range-fetch per view** — the validated design. Rejected for AB1, AB2, AB3
  above, each independently fatal.
- **Replace tier A with tier B** — rejected for AB3 (90.1 MB/origin) and AB30
  (the reach percentage would count the 18.3 % padding as unreachable land and
  print ~20 % where the truth is 1.851 %).
- **Res-5 middle ground** — 1.2 MB/origin, but it is not what the owner chose,
  and it would leave the reading a resolution away from the paint after a cycle
  spent on precision.
- **Residual coding against tier A** (int8 or int16 deltas) — roughly halves
  the wire cost, and was rejected on the testing rule: it adds a second
  sentinel scheme, an escape path for cells whose parent is unreachable, and
  two ways to be silently wrong, to save bytes the owner has explicitly said
  are not the constraint. Recorded here so a later cycle does not re-derive it.
- **`.bin.gz` precompressed with client-side `DecompressionStream`** — the
  `architect`'s recommendation, and better on the wire. Rejected because
  `.bin.gz` matches neither `location ~* \.bin$` nor any other rule and falls
  through to `location /`, which sets **no `Cache-Control` and no security
  headers** — the exact regression the conf's own comment at `:55-57` records
  having shipped once. Serving `.bin` keeps `no-cache`, keeps the security
  snippet, and lets nginx gzip it with no client code at all.

---

## Tasks

### The feature

| ID | Task | Findings | Verification (the mutation that must go red) |
|---|---|---|---|
| C7-1 | `config.py`: add `READING_RES = 6`, `READING_PARENT_RES = 3`, `READING_SLOTS = 343`, each with the comment saying what it governs | AB4 | change `READING_SLOTS` to 342 → the round-trip test fails |
| C7-2 | `emit/hover.py`: `reading_parents(idx)` returns the sorted res-3 parents; `reading_slot(cell)` is the digit form; `write_reading(idx, cell_minutes, out)` writes the padded block array | AB4 | emit a cell whose slot is computed with `cell_to_child_pos` instead → the pentagon round-trip test fails |
| C7-3 | `emit/index.py`: `write_reading_parents()` writes `dist/reading_parents.bin`; `index.json` gains `readingRes`, `readingSlots`, `readingParentCount`, `readingParentsUrl`, `readingUrlSuffix` | AB9, AB26 | drop `readingParentCount` → `check_dist` refuses |
| C7-4 | `cli.py`: write the directory once per build beside `hover_cells.bin`; write `{slug}.r6.bin` per origin; add the four fields to `_CURRENT_INDEX_CONSTANTS` so `reindex` refuses a stale one | AB26, AB27 | move `READING_RES` and run `reindex` → it must refuse |
| C7-5 | `check_dist.py`: refuse a `dist/` whose `reading_parents.bin` is not a whole number of uint64s, whose count disagrees with `index.json`, or any of whose `{slug}.r6.bin` is not `readingParentCount × 686` | AB17, AB31 | truncate one `.r6.bin` by two bytes → `check_dist` exits non-zero |
| C7-6 | The build logs the real gzipped size of the first `.r6.bin` it writes, so the rebuild replaces this plan's modelled estimate with a measured one | this plan's own estimate | — (a log line, not a guard) |
| C7-7 | `web/app.js`: load `reading_parents.bin` at boot; fetch `{slug}.r6.bin` lazily after tier A settles, abortable; `readingAt(lat, lon)` binary-searches the directory and reads `block·343 + slot` | AB1, AB2, AB3 | make `readingAt` ignore the slot → the JS round-trip test fails |
| C7-8 | `lookup()` prefers tier B and falls back to tier A; the **reach percentages and the charted mask stay on tier A** | AB30 | point the reach scan at tier B → the padding test fails |
| C7-9 | The hover ring is drawn at the resolution actually read, and the reading says which grid it came from and that the breakdown below it is coarser | AB15, and AA6's deferred half | — (visual; covered by the browser gate) |
| C7-10 | Guards: the page refuses a `.r6.bin` whose length disagrees with the directory, exactly as `checked()` already does for the other five arrays | AB11 | delete the new length check → the new test fails |

### High-severity defects the review turned up

Scheduled under the orchestrator's "this plus any genuine HIGH-severity
defect". Everything else is deferred.

| ID | Task | Findings | Verification |
|---|---|---|---|
| C7-11 | `web/app.js:2626`: return the departure card to `.topleft` instead of `document.body`, so crossing 860 px upward cannot orphan it to (0,0) under the masthead | AB5 (VER7-1 + UX7-1, measured identically by both) | resize 820×1180 → 1280×800 and assert the card's parent and rect; revert the fix → red |
| C7-12 | `browser_verify.sh`: run the full overlap check after the resize-up, not only the sheet-toggle probe — the gate that could not see AB5 | AB5 | — (the gate itself; C7-11's mutation proves it) |
| C7-13 | `web/app.js:2560, 2584`: give `#oceans` the same arrow-key roving-tabindex handler `#ramps` already has | AB6 (WCAG 2.1.1 Level A) | ArrowRight from the checked radio must move `document.activeElement`; revert → red |
| C7-14 | Ship an index at `vendor/licences/` and stop excluding it from the server rsync, so the page's own link to the notices is not a 403 | AB7 (three agents; BSD-3 §2, Apache-2.0 §4) | `deploy_verify.sh` requests the URL and refuses on non-200; remove the index → red |
| C7-15 | `web/app.js:1634`: `=== null` for open water, so "Travel times unavailable." survives more than one mouse move | AB20 (reproduced) | move the pointer onto land after a failed fetch; the notice must stand |
| C7-16 | `web/app.js:1166`: rebuild the city list on the failure path, so a failed origin does not leave the previous city's times with the new departure marked as a destination | AB19 (reproduced) | fail the fetch and assert the list caption names the new city |
| C7-17 | `emit/index.py` / `cli.py`: actually emit `inputsHash` and `buildId` — `cli.py:500` forwards identity keys only `if k in previous`, so they can never appear — and test that `params_hash` covers the resolutions and the band ladder | AB9, AB10 | drop `SOLVE_RES` from the `params_hash` call → the new test fails |
| C7-18 | Correct the five source documents that say the road model is wholly fitted, where `graph/ground.py:17-24` keeps published-figure defaults for two classes | AB14 (CLAUDE.md calibration rule) | — (documentation; the artifact half is AB13, which needs the rebuild) |

---

## Progress

*(filled in as the work lands)*
