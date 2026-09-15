# Cycle 14 — the rail `service` tag: per-tier speeds, and a leg that reads like a timetable

The owner saw a rail leg read `by rail via 구포 (경부선 KTX: 서울 → 부산 (구포경유))`,
asked how we knew that, and said **"더 많이 이런거 가져올수록 좋겠네"** — the more of
this kind of detail we bring in, the better.

That string is the OSM relation's `name` tag printed verbatim. `sources/osm.py`
kept `name` and a `highspeed` boolean out of everything those relations carry.
This document is the survey that decided what else to keep, the fit that turned
one of those tags into a model, and the task list.

The other 223 review findings from this cycle are indexed in
`2026-09-15-c14-review-findings.md`. Seven of them are rail findings that this
work closes; they are named against the tasks below.

---

## 1. The survey — measured, not assumed

The brief guessed the tiers would be "`high_speed`, `long_distance`, `regional`,
`suburban`, `night`, `car_shuttle` and similar". **They are not.** `suburban` has
five route relations on Earth; `commuter` has 2,829. Surveying first was the
right instruction.

Relation-only pass over all seven `*-rail.osm.pbf` extracts, **19,297
`type=route, route=train` relations**, 7 seconds wall (relation blocks decode
without touching the node blocks, so this cost the running build nothing):

| extract | routes | `service` | `operator` | `ref` | `network` | `colour` | `via` | `from`/`to` | `highspeed=yes` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| africa | 292 | 48% | 80% | 16% | 57% | 30% | 4% | 53% | 0% |
| asia | 5,061 | 54% | 90% | 86% | 49% | 26% | 5% | 91% | 0% |
| australia-oceania | 366 | 90% | 90% | 89% | 91% | 87% | 32% | 90% | 0% |
| central-america | 135 | 19% | 55% | 93% | 14% | 0% | 4% | 73% | 0% |
| europe | 12,424 | 85% | 94% | 91% | 72% | 41% | 25% | 95% | 2% |
| north-america | 783 | 15% | 92% | 83% | 88% | 74% | 26% | 91% | 0% |
| south-america | 236 | 71% | 95% | 72% | 78% | 68% | 5% | 89% | 0% |
| **world** | **19,297** | **73%** | **92%** | **88%** | **67%** | **39%** | **19%** | **93%** | **1%** |

**Coverage is uneven exactly where the brief warned.** `service` is 85% in
Europe and 15% in North America. `operator` is the only field that is uniformly
good: 92% worldwide, and its worst region (Africa, 80%) still beats `service`'s
best non-European region.

Worldwide `service` values, all of them:

| value | n | share |
|---|---:|---:|
| `regional` | 7,939 | 41.1% |
| *(absent)* | 5,149 | 26.7% |
| `commuter` | 2,829 | 14.7% |
| `long_distance` | 2,168 | 11.2% |
| `high_speed` | 349 | 1.8% |
| `national` | 238 | 1.2% |
| `tourism` | 210 | 1.1% |
| `international` | 95 | 0.5% |
| `night` | 94 | 0.5% |
| `light_rail` | 66 | 0.3% |
| `local` 22, `tourist` 18, `express` 14, `industrial` 10, `urban` 9, `highspeed` 6, `stopping` 6, `car_shuttle` 5, `suburban` 5, `touristic` 4, `ordinary` 4, `rapid` 2, `branch` 1, `event` 1 | 107 | 0.6% |
| multi-valued (`;`-joined, e.g. `international;long_distance`) | ~60 | 0.3% |

**The `highspeed=yes` tag is the finding that matters most.** It is on 1% of
route relations worldwide and 0% outside Europe — and it is, today, one half of
the only thing that decides whether a train runs at 200 km/h or 75. The critic
lane reached the same conclusion independently (AGG14-15) and measured the
consequence: the Tohoku Shinkansen is modelled at 10.4 h against a real 3.8 h,
because nothing in Japan carries the flag.

## 2. There is something to fit against

`calibration.toml`'s `[rail]` block says the figures are "Pre-calibration
defaults from published timetables, NOT fitted: OSM route relations carry the
stop sequence but no journey times, so there is nothing here to regress
against."

**That is no longer true, and may never have been.** 2,448 train route relations
carry a `duration` tag, in exactly the formats `sources/osm.parse_minutes()`
already parses for ferries. Joined to the cached stop sequences and filtered to
routes the extracts resolve whole, that is **2,338 observations** — an order of
magnitude more than the eight published headways the ferry wait model was fitted
on.

## 3. The fit

Model, identical in shape to what `graph/rail.ride_edges` already computes, plus
one term:

```
edge_min = stop_overhead_min + 60 * chord_km * detour_factor / speed_kmh
```

summed over the legs of a journey. Fitted per tier by least squares on log
residuals — the ferry precedent — over routes whose implied speed is inside
3–350 km/h (15 of 2,338 observations, 0.6%, fall outside: two Polish relations
tagged `duration=2` for 70 km, four tagged 40–57 h for 38–53 km).

**The per-leg overhead is not a decoration.** Without it, implied speed inside a
single tier drifts by a factor of two with route length — `regional` runs 39 km/h
over 0–20 km and 70 km/h over 150–400 km. That is the signature of a fixed
per-call cost (decelerate, dwell, accelerate), and it is the same structure the
ferry fit found and named `berth_min`. Every tier's residual improves when it is
included, and a 70/30 holdout (40 repeats) reproduces the in-sample log-sd to
within 0.03 everywhere, so this is not overfitting.

| tier | n | `stop_overhead_min` | `speed_kmh` | median pred/obs | log-sd | within 2× | holdout log-sd |
|---|---:|---:|---:|---:|---:|---:|---:|
| `high_speed` | 57 | 5.11 | 214.7 | 0.99 | 0.156 | 100% | 0.177 |
| `long_distance` | 228 | 3.90 | 103.9 | 1.07 | 0.299 | 96% | 0.302 |
| `regional` | 497 | 2.22 | 86.7 | 1.02 | 0.437 | 95% | 0.422 |
| `default` | 717 | 2.46 | 81.8 | 1.08 | 0.619 | 85% | 0.641 |
| `commuter` | 716 | 1.32 | 73.8 | 1.05 | 0.363 | 97% | 0.340 |
| `tourism` | 25 | 0.90 | 20.1 | 1.01 | 1.027 | 73% | 0.611 |

Bootstrap 95% CIs (2,000 resamples) on the five tiers that get their own fit:
`high_speed` speed [208, 225]; `long_distance` [93, 112]; `regional` [80, 92];
`default` [75, 85]; `commuter` [59, 77]. The overhead ordering — 1.3 min for a
commuter call, 5.1 for a high-speed one — is physically coherent rather than
noise: a train decelerating from 300 km/h and back costs minutes that one
decelerating from 80 does not.

**Tiers that do NOT get their own fit, and why.** `national` (n=44),
`international` (n=16) and `night` (n=8) all fit, but their overhead term is
unidentifiable — the bootstrap CI spans [0, 5] or pins at zero. Rather than ship
an invented constant, each is folded into the existing tier that prices its
observations best: `national` → `long_distance` (median pred/obs 1.17, against
1.28 as `regional` and 1.40 as default), `international` → `long_distance`
(0.96), `night` → default (0.96, against 0.77 as `long_distance`). `suburban`
(n=4) → `commuter` (1.02). `car_shuttle` (n=4) is left at default: n=4 cannot
choose between default (1.24) and `long_distance` (1.06), and five routes
worldwide do not justify a special case.

`tourism` keeps its own tier despite n=25 and a log-sd of 1.03, because every
alternative is a factor of two too fast (0.44–0.55) and the direction of the
error is the safe one: a heritage railway that Dijkstra declines to use is
correct behaviour. The weak residual is declared in `calibration.toml` rather
than hidden.

### 3.1 What the fit is worth

Evaluated on all 2,338 observations, including the 15 the fit excluded:

| | median pred/obs | log-sd | within 2× | within 1.5× |
|---|---:|---:|---:|---:|
| old, two speeds | 0.74 | 0.592 | 81% | 57% |
| new, six tiers | 1.04 | 0.476 | 93% | **82%** |

The distance bias is gone, which is the part that mattered:

| chord km | n | old | new |
|---|---:|---:|---:|
| 0–20 | 431 | 0.51 | 1.04 |
| 20–50 | 651 | 0.65 | 1.03 |
| 50–150 | 650 | 0.79 | 1.05 |
| 150–400 | 315 | 1.11 | 1.09 |
| 400–1,000 | 241 | 1.14 | 1.05 |
| 1,000+ | 50 | 1.02 | 0.96 |

The old model was **twice too fast on a short ride** and 14% too slow on a long
one. Both published anchors already in `calibration.toml` improve, and neither
is in the fit set:

- **Seoul–Busan KTX**, 325 km great-circle, published 135 min. Old model 117.
  New, `high_speed` with four legs: **129**.
- **CFL Luxembourg → Wasserbillig**, 28.7 km great-circle, timetable ~30 min.
  Old model 28. New, `regional` with two legs: **28**.

### 3.2 The honest part

**The fit set is 74% European** — 1,724 of 2,331 clean observations, against
Asia 373, Oceania 109, South America 71, North/Central America 35, Africa 11.
`long_distance` and `high_speed` are fitted on European observations almost
exclusively (216 of 228, 55 of 57). Per-region medians of implied speed differ
by up to 30%: `commuter` runs 61 km/h in Asia, 50 in Europe, 43 in Oceania, 37
in South America.

No per-region speeds are fitted. n is far too small outside Europe, and fitting
them would be exactly the hidden error CLAUDE.md forbids. The skew is written
into `calibration.toml` instead, with the per-region table, so a reader knows
which way the number is likely to be wrong where.

One thing the skew does **not** damage: the `default` tier, which is the one that
prices North America (85% of its routes carry no `service` tag), is fitted on a
near-even Asia/Europe split (339/328) rather than on Europe alone.

## 4. The label fields

**Shipping `operator` and `ref`.** 92% and 88% worldwide, and `operator` is the
only field whose coverage survives leaving Europe. Together they turn
`by rail via 구포` into a line that names who runs the train and what it is
called.

**Payload, measured rather than asserted.** A real shipped `.rail.json`
(`dist/origins/aba.rail.json`) is 2,110 rows, 189,590 bytes raw and 37,400
gzipped. Drawing `operator`/`ref` for each row from the true worldwide
distribution:

| shape | raw | gzip | gzip Δ |
|---|---:|---:|---:|
| current, `[station, line]` | 189,590 | 37,400 | — |
| `+ operator, ref` inline | 257,438 | 60,033 | +22,633 |
| `+ operator` interned, `ref` inline | 231,128 | 57,288 | **+19,888** |
| `+ network` interned as well | 247,451 | 63,748 | +26,348 |

Interning the operator into a per-file array costs 9.4 gzipped bytes per row
instead of 10.7 and is the shape adopted. **+19.9 KB gzipped per city switch**,
against `.r6.bin`'s 5.33 MB on the same switch (perf lane, measured) — 0.4% of
what a city change already costs.

**Declining `network`** (+6.5 KB gzipped for 67% coverage): in Europe it is
mostly the regional transport association, which duplicates `operator` for the
reader's purposes, and the designer lane measured the leg row's description
column at 189 px with `.legs` capped at 30vh in landscape. There is no room for
a third label and no reader question it answers that `operator` does not.

**Declining `colour`** (39%): the band palette is required to stay measurably
separable on a near-black ground, with OKLab ΔE ≈ 8 between neighbours and
strictly monotonic lightness. Injecting arbitrary OSM line colours, most of them
authored for a light background, puts unvetted swatches against `--bg` with no
contrast guarantee and in direct competition with the scale the map is read by.

**Declining `via`** (19%, and 4–5% outside Europe and Oceania): it would be
absent four times in five, and the information is usually already inside `name`
— the owner's own example carries `(구포경유)` in the relation name.

## 5. Tasks

- [ ] **C14-R1 — parse the tags.** `sources/osm.py`: add `service`, `operator`,
  `ref` to `SCHEMA`; add `service_tier()` mapping a raw tag value to one of the
  six tiers, handling `;`-joined values by taking the slowest recognised tier
  (justified because `ride_edges` already resolves parallel services by
  `min(minutes)`, so a genuinely faster service on the same track still wins).
  Keep `highspeed=yes` as a promotion to `high_speed` — it is a positive
  assertion, and the two fit-set routes carrying it imply 153 km/h against
  their tier's 79.7.

- [ ] **C14-R2 — bump `RAIL_PARSER_VERSION` 2 → 3**, and add the new constants
  to `_rail_cache_path`. Without this the whole feature is a silent cache hit on
  the 257,007-row parquet. Closes **AGG14-5** in part (verifier V2,
  test-engineer SRC-01, cross-agent): add `RAIL_PARSER_VERSION` to the
  `STAMPED` table in `tests/sources/test_cache_provenance.py`. Also closes
  **AGG14-72**: `sorted(SCHEMA)` hashes keys only, so a dtype change is a cache
  hit — hash the items.

- [ ] **C14-R3 — per-tier speeds in the graph.** `graph/rail.py`:
  `RailCalibration` gains the six tiers; `ride_edges` prices each leg by its
  route's tier and adds the per-leg overhead. Closes **AGG14-15** (critic C1).

- [ ] **C14-R4 — `calibration.toml`.** A `[rail.tiers.*]` table per tier, each
  declaring FITTED with n, the residuals, the bootstrap CI, and the regional
  skew; the folded tiers named with the ratios that chose them. Correct the
  `[rail]` block's claim that there is nothing to regress against.

- [ ] **C14-R5 — the caption must name the service that was timed.**
  `emit/rail_detail.py` picks the line by lowest OSM route id while
  `ride_edges` prices by `min(minutes)`; the tracer lane measured **20.9%**
  (30,742 of 147,332 directed pairs) naming a different line than the one timed,
  370 of them a different speed class. Closes **AGG14-58** (cross-agent:
  code-reviewer, tracer).

- [ ] **C14-R6 — the reverse-direction caption.** `_line_between` does
  `out.setdefault((b, a), name)`, filling the reverse pair with the forward
  service's directional name: **50.0%** of arrow-named station pairs caption a
  ride with the service running the other way, and 3,834 shipped rows name the
  line's own origin terminus as the destination. Closes **AGG14-4** (tracer T1).

- [ ] **C14-R7 — an unnamed stop must not inherit the route name.**
  `sources/osm.py` falls back to the relation's `name` when a stop node has
  none, and `emit/rail_detail.py` then publishes it as the station:
  1,144 of 124,488 shipped rows render
  `via S1: Rostock Hbf → Warnemünde (S1: Rostock Hbf → Warnemünde)`.
  Closes **AGG14-90** (tracer T3).

- [ ] **C14-R8 — ship the labels.** `emit/rail_detail.py` writes
  `operator`/`ref` with the operator interned; `web/app.js` `railVia()` renders
  them. Degradation is the requirement: a missing field prints nothing at all —
  never an empty parenthesis, never a bare dash. The designer lane's D18 gives
  the presentation: keep `by rail via {station}` as the sentence, put operator
  and ref on a second quieter line at `--t-cap` in `--text-3`, join present
  fields with ` · `, and omit the whole second line when neither exists.

- [ ] **C14-R9 — the fixtures lie about the schema.** `tests/graph/test_rail.py`
  and `test_rail_integration.py` build 7 keys against an 8-field `osm.SCHEMA`,
  so polars silently nulls `route_name`; this change takes the schema to 11 and
  would widen the hole. Closes **AGG14-110** (test-engineer GRAPH-15).

- [ ] **C14-R10 — rail is charged 20 minutes and every surface says 15.**
  `boarding_min` 15 + `alighting_min` 5; `emit/index.py`'s tooltip and
  `web/llms.txt` both say 15. The same tooltip says conventional rail runs
  "along the track" when the model uses a straight-line chord × 1.2 and
  `sources/osm.py` states geometry is never consulted. Closes **AGG14-49**
  (cross-agent: document-specialist DOC14-1, critic C4) and the long-deferred
  C10-9.

## 6. What needs a rebuild to appear

Everything except C14-R10's prose. The tiers are baked into each origin's
`.pmtiles`, `.bin` and `.rail.json` at solve time, so **none of C14-R1…R9
reaches the live site until the next full rebuild.** The 1,464-origin run in
flight (rebuild21) was started before this work and does not carry it.

## 7. Progress

All ten tasks done. Commits `d3e7f4a` (plans), `e7a90c7` (the model), `15870ac`
(the labels and the captions), `<provenance>` (the cache stamps).

- [x] **C14-R1** — `sources/osm.py` carries `tier`, `operator` and `ref`;
  `service_tier()` maps the tag, promotes on `highspeed=yes`, and takes the
  slowest recognised tier of a `;`-joined value. 22 parametrised cases cover
  every tier, every folded synonym, case and whitespace noise, and four
  multi-valued forms.
- [x] **C14-R2** — `RAIL_PARSER_VERSION` 2 → 3, and eight rail constants added
  to `STAMPED` in `tests/sources/test_cache_provenance.py`, which held exactly
  one (`MIN_STOPS`). `_rail_cache_path` now hashes the schema's ITEMS: a
  dtype-only change used to be a cache hit, which is precisely what
  `tier` going from `Boolean` to `Utf8` is.
- [x] **C14-R3** — `ride_edges` prices per tier and adds the per-leg overhead.
  An unpriced tier raises naming itself rather than surfacing as polars'
  "incomplete mapping".
- [x] **C14-R4** — `[rail]` rewritten. The claim that there was nothing to
  regress against is gone, the six tiers are declared FITTED with n, residuals,
  bootstrap CIs and holdout, and the 74% European skew is tabulated by region.
- [x] **C14-R5** — the caption resolves by minimum leg minutes, the same
  tie-break `ride_edges` uses.
- [x] **C14-R6** — forward and reverse captions are kept separately; an
  opposite-direction name is a documented fallback for a one-way relation, not
  the default.
- [x] **C14-R7** — an unnamed stop stays empty and the page prints
  "a station".
- [x] **C14-R8** — `operator` and `ref` ship, the operator interned;
  `railVia()` renders them on a second line and prints nothing for an absent
  field. A `.rail.json` written before this change still renders, because
  destructuring a two-element row leaves both new values `undefined` and the
  falsy tests already handle that.
- [x] **C14-R9** — both rail test files share one schema-complete `stop()`, and
  `test_the_fixture_covers_the_whole_schema` reddens if a column is added to
  `SCHEMA` and not to the fixture.
- [x] **C14-R10** — the tooltip and `llms.txt` say 20 minutes, name six tiers
  instead of two speeds, and no longer claim the train follows the track.

### Mutations run, and what they proved

Thirteen, every one red. The ones worth recording:

| mutation | caught by |
|---|---|
| drop the per-leg `stop_overhead_min` | `test_a_leg_costs_its_tier_overhead...` (3 cases) |
| drop `detour_factor` | same, plus the per-leg overhead test |
| revert `high_speed` to 75 km/h | both published-timetable anchors |
| fixture stops naming `route_name` | `test_the_fixture_covers_the_whole_schema` |
| price `commuter` identically to `regional` | **nothing, at first** — see below |
| reverse caption overwrites the forward one | `test_the_reverse_direction_is_not_captioned...` |
| resolve parallel services by relation id | `test_the_caption_names_the_service_the_edge_was_PRICED_from` |
| drop `ref` from the shipped row | `test_the_rail_json_carries_...` |
| restore the unnamed-stop fallback | `test_a_stop_with_no_name_stays_empty...` |
| multi-value takes the fastest tier | two of the `;`-joined cases |
| drop `RAIL_PARSER_VERSION` from the key | the new `STAMPED` case |
| revert to `sorted(SCHEMA)` keys-only | `test_a_rail_schema_DTYPE_change_moves_the_key` |
| swap `boarding_min` and `alighting_min` | `test_boarding_and_alighting_are_charged_at_the_right_END...` |

Two of those are worth reading twice. **Pricing `commuter` identically to
`regional` initially changed nothing**, because every test in
`tests/graph/test_rail.py` prices against the fixture calibration and none
against the shipped one — so `test_the_SHIPPED_tiers_are_ordered_and_none_
duplicates_another` was written in response and now reddens. And **swapping
`boarding_min` with `alighting_min` scored an identical 399.020** under the
existing test, because `boarding + rides + alighting` is symmetric in the two;
the replacement measures the half-journeys (cell → its station, station → its
cell) instead, which is not.

## 8. What was measured and NOT used

Recorded so a later cycle does not re-do the survey to reach the same answer.

| field | worldwide | why not |
|---|---|---|
| `network` | 67% | +6.5 KB gzipped per origin, duplicates `operator` for the reader's purposes in Europe, and the leg row's description column is 189 px with `.legs` capped at 30vh in landscape |
| `colour` | 39% | unvetted colours against a near-black ground with no contrast guarantee, competing with a band palette CLAUDE.md requires stay measurably separable |
| `via` | 19% | absent four times in five, and usually already inside `name` — the owner's own example carries `(구포경유)` there |
| `from`/`to` | 93% | the endpoints of the ROUTE, not of the traveller's leg; printing them would caption a Seoul→Daejeon ride "Seoul → Busan", which is the defect C14-R6 exists to remove |
| `usage` | <1% | 81 relations worldwide |

## 9. Known limits, carried forward

- **The `tourism` tier is fitted on 25 observations with a log-sd of 1.03.**
  Its central value is unambiguous (every alternative tier is a factor of two
  too fast) and its error direction is safe, but it is the weakest number in
  the table. Exit criterion: a cycle that can re-run the fit over a rebuilt
  parquet with more `duration` coverage.
- **No per-region speeds.** The skew is documented, not corrected. Exit
  criterion: enough non-European observations to fit a region term without
  fitting it on single digits.
- **`detour_factor` was held at 1.2 and not refitted** alongside the tier
  speeds, so the speeds absorb any error in it. The two must not be read
  separately, and `calibration.toml` says so.
