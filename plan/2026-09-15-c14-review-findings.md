# Cycle 14 -- everything the eleven lanes found, scheduled or deferred

Eleven review lanes ran on 2026-09-15 against `feat/transport-pipeline`.
**255 raw findings, 223 distinct after dedupe: 9 Critical, 43 High, 96 Medium,
75 Low.** Every one of them is in the index at the foot of this file with its
AGG14 id, its file and line, its severity, its confidence and its disposition,
so nothing depends on `.context/reviews/`, which is deliberately not committed
(`.gitignore:29`). **This file is the durable record.**

The lanes were `code-reviewer`, `perf-reviewer`, `security-reviewer`, `critic`,
`verifier`, `test-engineer`, `architect`, `tracer`, `debugger`,
`document-specialist` and `designer`, and all eleven lane files are present in
`.context/reviews/`. Twenty-six findings were raised independently by two or
more of them, and the aggregate's own note on that stands: independent
convergence is the strongest signal in the set. Three of the seven items
scheduled below carry two agreeing lanes (AGG14-5, AGG14-58, AGG14-49); the
other four are single-lane findings that the rail work reaches anyway.

## The cycle's scope, fixed before the reviews ran

The orchestrator fixed this cycle's scope **before** any lane started, so the
reviews could not choose it: the owner's injected TODO was the rail `service`
tag -- **per-tier rail speeds, plus the `operator` and `ref` label fields**.
That work has its own document, **`plan/2026-09-15-c14-rail-service-tiers.md`**,
and nothing about its design, its constants or its tests is repeated here.

Everything else the lanes found is indexed here and mostly deferred, because the
owner's standing instruction is **"do not overwork"**. Cycle 12 raised 212
findings and cycle 13 raised 196; both scheduled a ledger rather than a diff,
and this cycle does the same. The seven items in "Scheduled this cycle" are
there for one reason only: **the rail service-tier work closes or touches them,**
so they are cheaper to take with it than to take later.

## What this cycle cannot do, and why the reasons below keep repeating

A **1,464-origin build is running** and owns `dist/`. It has already died twice,
and the aggregate names the mechanism (AGG14-2). The orchestrator's constraints
for this cycle follow from that, and they are the honest reason behind most of
the deferrals below:

- no `transport-maps build-all`, no `transport-maps reindex`, no
  `scripts/build_water_tiles.py`;
- no writes, deletes or edits under `dist/` or `data/`;
- no `pytest` and no CPU-heavy command -- the machine is the build's.

Three consequences, each of which is cited by name in the tables:

1. **A guard cannot be proved.** CLAUDE.md: *"After adding a guard, mutate the
   code and confirm the test goes red. This repository has shipped several
   vacuous tests; assume a new test is vacuous until shown otherwise."* With no
   suite run, a new guard is exactly the thing that rule forbids shipping. That
   is why the sixty-one remaining rows of CL-C wait for a cycle that can run the
   suite, rather than being written blind now.
2. **A page fix cannot be finished.** CLAUDE.md: *"No deploy is done until it
   has been opened in a browser ... `curl` returning 200 proves nothing about
   whether the page runs."* The deploy needs `dist/`.
3. **A build-path fix cannot reach the build.** The running workers imported
   `contour/`, `graph/`, `emit/` and `sources/` at fork time. An edit now lands
   in the *next* run, unmeasured, 37 hours later -- and editing build inputs
   under a build is how this project lost a previous rebuild.

None of that is a reason to lose a finding, so every one of the 223 is either
scheduled below, scheduled for a **named** future cycle, or deferred with a
concrete reason and an exit criterion that fires.

---

## Scheduled this cycle

Seven items, all of them inside the rail service-tier work's blast radius. The
implementation, its constants and its tests belong to
`plan/2026-09-15-c14-rail-service-tiers.md`; what follows is the finding each
one closes and why it rides with that work rather than waiting.

**Nothing below is ticked.** This document is written before the implementation,
and a tick in this repository means "done, with the mutation recorded" -- cycle
13 found seventeen ticks that did not hold, which is why the bar is that high.

- [ ] **C14-1 -- the high-speed flag is an OSM tagging artefact.** `AGG14-4`
  (Critical / High, `critic`). `sources/osm.py:42-44` decides "high speed" from
  a single relation tag: **537 of 16,781 relations (3.2 %)** carry it, **1.1 %**
  of directed segments, and the coverage is geographically systematic -- Taiwan
  86.6 %, Japan 0 %, India 0 %, North America 0 %, Russia/CIS 0 %. The Tohoku
  Shinkansen is charged **10.4 h against a real 3.8 h**, and over-charging is
  silent: Dijkstra stops selecting rail and re-attributes the leg to road or
  air. This is the finding the owner's TODO is about. Per-tier speeds from the
  `service` tag replace the boolean; the disclosure half is not optional and is
  named in CLAUDE.md -- *"prefer a documented, reproducible error over a hidden
  one."*

- [ ] **C14-2 -- `RAIL_PARSER_VERSION` is missing from the cache-provenance
  table.** `AGG14-5` (Critical / High, `test-engineer` SRC-01 + `verifier` V2,
  independently). `tests/sources/test_cache_provenance.py:186-232` covers 27 of
  35 hashed terms, and `STOP_ROLES`, `PLATFORM_ROLES`, `SCHEMA`,
  `FERRY_SCHEMA`, `_SECTION_RE`, `_CARGO_RE` and `COUNTRIES_URL` can be dropped
  from a cache key with the suite green. It rides this cycle because the
  service-tier parse **changes `SCHEMA` and bumps the rail key** -- exactly the
  mutation the missing case would hide. Derive the table by AST walk rather than
  re-typing it; `tests/cli/test_reindex.py:409-438` already does this for
  `write_index`. (The `STAMPED` completeness guard itself, AGG14-41, is cycle
  16 -- this item covers the rail terms only.)

- [ ] **C14-3 -- the rail fixtures build seven keys against an eight-field
  schema.** `AGG14-90` (Medium / Medium, `test-engineer` GRAPH-15).
  `tests/graph/test_rail.py:10-16` and `tests/graph/test_rail_integration.py:21-25`
  pass `schema=SCHEMA` with `route_name` absent; polars does not raise, it
  silently nulls the column, so every rail consumer is tested against a frame no
  real extract produces. The service-tier work adds more fields to that schema,
  so the double has to follow it now or the drift compounds. Add
  `assert set(stop(...).keys()) == set(SCHEMA)` so the next addition fails
  loudly.

- [ ] **C14-4 -- an unnamed stop node inherits the route's name, and ships as a
  station.** `AGG14-110` (Medium / High, `tracer` T3). `sources/osm.py:92`
  falls back to the relation name; **1,144 of 124,488 shipped rows across 60
  origins have `station == line`**, and the page renders `by rail via S1:
  Rostock Hbf -> Warnemuende (S1: Rostock Hbf -> Warnemuende)`. The fix is a
  schema change -- a nullable stop name distinct from the route name -- which is
  the same schema the `operator`/`ref` fields are being added to, and the same
  `RAIL_PARSER_VERSION` bump.

- [ ] **C14-5 -- half the arrow-named captions name the opposite direction.**
  `AGG14-15` (High / High, `tracer` T1). `emit/rail_detail.py:56-57` fills both
  directed keys with one directional string: **55,500 of 111,051 arrow-named
  pairs (50.0 %)**, and **3,834 shipped rows name the line's own origin
  terminus** -- the traveller alighted where the named train departs from. It
  rides with the label work because it is the same map, built in the same loop
  the `operator`/`ref` fields are threaded through. Store direction with the
  name; do not drop the reverse key, which would lose the line name on half the
  network.

- [ ] **C14-6 -- the caption names one train and the edge is priced by
  another.** `AGG14-58` (Medium / High, `code-reviewer` C11 + `tracer` T2).
  `graph/rail.py:103-107` resolves parallel services by `min(minutes)`;
  `emit/rail_detail.py:52-57` resolves them by lowest OSM route id. **30,742 of
  147,332 directed pairs (20.9 %)** are captioned with a different service from
  the one whose minutes they carry, **370 of them in a different speed class**.
  Per-tier speeds make that worse, not better -- more services on a segment
  differ in price -- so the tiebreak has to move into `ride_edges` in the same
  change: one decision, one place.

- [ ] **C14-7 -- rail is charged 20 minutes and every surface says 15.**
  `AGG14-49` (High / High, `document-specialist` DOC14-1 + `critic` C4).
  `graph/build.py:273-274` stacks `boarding_min = 15.0` and
  `alighting_min = 5.0`; `web/llms.txt:29-30` and `dist/index.json`'s
  `modeDetail.rail` both say 15, and the same sentence claims "along the track"
  for a straight-line chord x 1.2. This is `C10-9`, raised as HIGH and
  user-facing in cycle 10 and still open, and it is the row the whole
  `DOC10-M*` batch in `plan/deferred.md:595` is deferred behind. It closes here
  because the service-tier work rewrites that prose anyway. **Closing it fires
  the exit criterion on thirteen deferred rows** -- see AGG14-222.

**Carried advisory, not a finding.** `designer` D18 answers where a new rail
label belongs: a second, quieter line inside `.d` at `--t-cap` in `--text-3`,
fields joined with ` - `, the whole line omitted when both are empty, and no
micro-label, no uppercase, no `letter-spacing`, no tabular figures for a line
number. It is recorded in the rail document, not here.

---

## Will not do -- findings against a standing owner decision

One row, and one near-miss. Both are recorded rather than actioned, because the
rules they run into are the owner's, not ours.

- **AGG14-223 (Low / Medium, `document-specialist`)** -- `CLAUDE.md:22-24`
  says *"(eleven anchors from near-white to near-black span about 70, so ~7 per
  step is the ceiling)"*, and `scripts/check_ramps.py:39-56`, the gate that
  measures it, passes four of twelve schemes that exceed it. The contradiction
  is real and it is recorded. **It will not be actioned.** CLAUDE.md's design
  policy is prefixed *"Design policy (standing -- do not revisit without being
  asked)"*, and `plan/deferred.md` already gives DOC5-8's remaining half exactly
  this disposition: that file is the owner's standing policy and this run treats
  it as binding input, not working material. Neither `check_ramps.py` nor the
  ramps are touched to make the sentence true. Exit: the owner revises
  CLAUDE.md.

- **Not a contradiction, recorded so it is not mistaken for one.** `verifier`'s
  AGG14-79 lists *"Hexagons are drawn as hexagons. No corner rounding"* and
  *"H3 cells are not regular hexagons ... do NOT try to regularise them"* as
  documented behaviours with **no test**. That is a request for a guard, not for
  a change: pinning the measured figures (median 1.04, worst 1.17, Seoul 1.15,
  110 deg to 126 deg, 1,343 m / 454 m / 190 m) is permitted and useful.
  Regularising a cell is not, and nothing proposes it.

**No lane proposed anything else against the standing decisions.** The designer
lane checked each one explicitly and reports them held: no `letter-spacing`,
`text-transform`, `tabular-nums`, `tnum`, `small-caps`, `font-variant` or
`toUpperCase` anywhere outside the explanatory comments and the vendored
MapLibre CSS; the ground is `--bg #0a0b0d` with `--text` at 14.81:1; the legend,
its ticks, its keys and its credit sit outside every `<details>` and the folded
phone sheet spares them; and the flowing dashes (owner decision **C10-16**,
closed) are gated on `prefers-reduced-motion` and `document.hidden` only -- no
duration, no stop -- so they stay continuous. The designer's own words: *"Correct;
I am not proposing a change."* Three of this cycle's design findings (AGG14-129,
AGG14-198, AGG14-200) are fixes that must stay **inside** the policy's channels,
and their rows say so.

---

## Deferred, with exit criteria

Deferral rules read before writing this section. `CLAUDE.md` is the only rule
file. `plan/README.md` states that every finding is scheduled, fixed with
evidence in a commit body, or recorded with its citation, **original severity
and confidence**, the reason and the exit criterion. Nothing below is
downgraded, and nothing is dropped: **216 rows here plus 7 scheduled above is
223.**

**Security, correctness and data-loss findings are not deferred indefinitely.**
All nine Criticals and all forty-three Highs are either scheduled this cycle or
scheduled for a named cycle: **cycle 15** is the first cycle after
`dist/.build.lock` clears (the build path), **cycle 16** is the first cycle that
can run `uv run pytest` (the guards), **cycle 17** is the first cycle whose
deploy is not `--page-only` (the page, the deploy gates and the privacy defect),
**cycle 18** is the documentation sweep. Medium and Low rows carry a plain
deferral with the reason and the criterion that reopens them. Rows are grouped
by the aggregate's clusters; every finding is in exactly one cluster.

### CL-A -- Rail modelling and rail detail (8 of 14)

Six of this cluster's fourteen rows are scheduled above; these eight are the rail work this cycle's TODO does **not** reach. Three of them (AGG14-12, 13, 14) change emitted numbers and therefore need a rebuild, which is the one thing this cycle cannot have.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-12 | High | High | `calibration.toml:126-133` vs `graph/rail.py:98-101` | cycle 15 | Correcting `detour_factor` re-prices every rail edge on Earth, and the per-tier speeds this cycle adds change the arithmetic the anchor must be re-derived against; landing both together makes neither attributable. | The service-tier speeds are merged and `dist/.build.lock` is gone. Re-derive the `[rail]` anchor against the tiered speeds and record the signed error, per CLAUDE.md's calibration rule. |
| AGG14-13 | High | High | `graph/build.py:263-275`; `graph/nodes.py:1-19` | cycle 15 | An arrival/departure split at stations moves `base = len(cells) + 2*len(codes)` and therefore every emitted ordinal in every per-origin artifact. It cannot land without a rebuild, and a rebuild is running. | `dist/.build.lock` is gone and a rebuild window is open. Take it with AGG14-35, which is the same node layout. |
| AGG14-14 | High | High | `sources/osm.py:1-11,86-94`; `graph/rail.py:92-104` | cycle 15 | A length bound and a drop counter delete edges, so they change every emitted time. This cycle's parser change is deliberately label-only so the two stay separable and measurable. | The first rebuild after the service-tier parse lands. `plan/deferred.md:353` (TR5-2) has already fired twice asking for this gate, so it goes first in cycle 15. |
| AGG14-37 | High | High | `tests/graph/test_rail.py:40-46,70-74` | cycle 16 | Replacing a 70-minute window with something that can detect a wrong `detour_factor` needs the suite run and the mutation shown red; this cycle is forbidden from running pytest. | The first cycle that can run `uv run pytest`. Pair it with AGG14-12 so the tightened window and the corrected factor are proved against each other. |
| AGG14-111 | Medium | High | `emit/rail_detail.py:24-41,94-106` | deferred | `last_station_per_node` propagating across a flight is a different mechanism from the label fields this cycle adds; editing both loops in `emit/rail_detail.py` in one commit would make a caption regression unattributable. | The next cycle that opens `emit/rail_detail.py` after the service-tier captions land. The propagation has to be cut at the airport-node range, which is what AGG14-187's `node_kind()` primitive is for. |
| AGG14-112 | Medium | High | `emit/rail_detail.py:111-113`; `scripts/check_dist.py:315-332`; `web/app.js:1936` | deferred | Pairing `.rail.bin` with `.rail.json` needs a per-origin fingerprint, which does not exist yet (AGG14-76), and `check_dist.py` is in the deploy path this cycle must not disturb. | AGG14-76 lands a per-origin build identity in cycle 15; assert `max(ordinal) < len(stations)` in the same commit. |
| AGG14-188 | Low | High | `graph/rail.py:69-76` | deferred | Both columns are dead today, so the defect is latent: a wrong resolution and a nondeterministic name that nothing reads. | The moment any caller reads `stations().cell` or `stations().name`. The service-tier plan must check this before it plumbs a label through that function, which is why the row is named there too. |
| AGG14-191 | Low | High | `graph/build.py:346,350` | deferred | Both ferry drops are correct; only the log line names the wrong reason, and `graph/build.py` is imported by every live worker. | The lock clears and `_ferry_edges`' drop accounting is next touched. Take it with AGG14-71, which questions the same premise. |

### CL-B -- Calibration provenance and model disclosure (6 of 6)

The hinge is AGG14-11, and it is scheduled: twelve model constants live in code, `calibration.toml` never names them, and the provenance gate only reads the toml. CLAUDE.md's calibration rule is the reason it is not deferrable -- *"Calibration constants live in `calibration.toml` and each carries a comment saying whether it is fitted ... or a published-figure default."*

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-11 | High | High | `graph/ground.py:17-25`; `sources/urban.py:28-33`; `graph/ferry.py:53,109,114`; `graph/build.py:29`; `tests/test_calibration_provenance.py:20-28`; `README.md:95` | cycle 15 | Twelve constants have to move from code into `calibration.toml` and into `inputsHash`, which changes the cache key of every ground edge - an edit no running build can absorb. | `dist/.build.lock` is gone. It goes first in cycle 15: AGG14-107 (resume) cannot be built until `inputsHash` covers the constants that price the graph. |
| AGG14-69 | Medium | High | `graph/headway.py:21-32` | deferred | `headway.py`'s three semantics are a modelling decision about what "leave now" means per mode, not a defect with one right answer; changing any of them re-prices a mode. | The cycle that takes AGG14-13 - rail's wait semantics and its interchange cost are the same question - or an owner decision on what the map means by "leave now". |
| AGG14-70 | Medium | High | `graph/build.py:182-207` vs `web/index.html:1021-1023`, `web/llms.txt:23-25` | deferred | The code is defensible; the page sentence is not. Correcting the sentence belongs to the user-facing prose sweep that AGG14-49 unblocks this cycle. | The documentation cycle (18), with AGG14-132 and AGG14-133: all three are one paragraph of `web/index.html`'s method panel. |
| AGG14-71 | Medium | Medium | `graph/build.py:338-348`; `graph/ground.py:80-142` | deferred | The ferry drop is probably right in most cases; showing it wrong needs a crossing-by-crossing count over `data/` caches the running build is writing. | The lock clears and the ferry-versus-ground overlap can be counted. Take it with AGG14-191, the mis-attributed reason line. |
| AGG14-132 | Medium | High | `web/index.html:1094-1096` | deferred | A page-copy correction whose only verification is a browser pass, and the deploy is blocked by the build holding `dist/`. | The documentation cycle (18), or the first deploy after the rebuild - whichever is first. |
| AGG14-133 | Medium | High | `web/index.html:1058-1061`; `web/llms.txt:26-29`; `graph/ferry.py:192-195` | deferred | Same paragraph, same constraint: the year-averaged headway needs one sentence in `index.html`, `llms.txt` and `modeDetail.ferry`, and the last of those is an `index.json` rewrite under `dist/`. | The documentation cycle (18). `emit/index.py`'s string can land earlier but only ships on a re-index. |

### CL-C -- Vacuous, mis-aimed and brittle tests (61 of 62)

The largest cluster, and the one CLAUDE.md targets directly: *"A test that passes when the code is deliberately broken is worse than none. After adding a guard, mutate the code and confirm the test goes red."* **That rule is why none of these can land this cycle:** a guard written now could not be shown red, because the orchestrator forbids running pytest while the build has the machine. Writing sixty-one unverified guards would add sixty-one new findings rather than close any. The four Criticals and fourteen Highs are therefore scheduled for cycle 16 -- the first cycle that can run the suite -- rather than deferred without a date; the remaining 27 Medium and 16 Low rows follow in the same cycle, one guard at a time, each with its mutation recorded.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-6 | Critical | High | `tests/sources/test_airports.py:1-31` | cycle 16 | Proving the fixture is warm needs a cold `data/build/`, which is exactly what the running build is filling; the network-marker fix needs the suite run. | The first cycle that can run `uv run pytest` against a scratch `BUILD` root. Redirect `config.BUILD` in `conftest.py` the way `config.CACHE` already is, and add a `PARSER_VERSION` to the stamp. |
| AGG14-7 | Critical | High | `tests/graph/test_ferry.py:245-257` | cycle 16 | The mutation is already recorded (137 min sailing against a 45 min threshold), but re-proving it red requires running the suite, which this cycle cannot do. | The test cycle (16). The fixture needs a sailing shorter than the threshold, and the mutation must be shown red before the commit. |
| AGG14-8 | Critical | High | `tests/graph/test_build.py` (whole file) | cycle 16 | Direct tests for `_air_edges`, `_access_edges` and `_transfer_edges` mean building a fixture graph and running it - CPU the running build owns. | The test cycle (16), after the lock clears. This is the largest unguarded surface in the repository, so it goes first among the test items. |
| AGG14-9 | Critical | High | `tests/emit/test_itinerary.py:52-71` | cycle 16 | Making one airport reachable changes what every other assertion in the file sees, so the whole file has to be re-run. | The test cycle (16). Assert a real `node - first_arrival` ordinal against a hand-computed value, with AGG14-40. |
| AGG14-32 | High | High | `sources/wikidata.py:64-102`; `tests/sources/test_wikidata.py`; `tests/sources/test_routes.py:67-113` | cycle 16 | The resolver is covered only by `network`-marked tests; giving it offline coverage means recording fixtures from live Wikidata, which is network the orchestrator has not sanctioned this cycle. | The test cycle (16): record a fixture for the normalize/redirect collapse that lost ICN->NRT, and stop stubbing `_resolve_batch` wholesale. |
| AGG14-33 | High | High | `tests/graph/test_rail_integration.py:28-44` | cycle 16 | A second-country, second-zone fixture has to be built and both mutations - the closed-border `continue` and the zone charge - shown red. No suite run this cycle. | The test cycle (16). Take it with AGG14-36, the same file. |
| AGG14-34 | High | High | `tests/graph/test_air.py:16-20` | cycle 16 | The tolerance sits 2 min above its floor, so any change has to be measured against a refit, and a refit reads calibration inputs under `data/`. | The test cycle (16). Derive the bound from `cruise_kmh`'s stated uncertainty rather than from the current output. |
| AGG14-35 | High | High | `graph/nodes.py:249-264` | cycle 16 | Reaching the station-indexing branch needs a caller that passes `rail_routes` - the same node-layout change as AGG14-13, which needs a rebuild. | Cycle 15 lands AGG14-13; the guard follows in cycle 16 with the dropped-station counter asserted. |
| AGG14-36 | High | High | `tests/graph/test_rail_integration.py:47-70` | cycle 16 | Making the swap detectable needs an asymmetric fixture - a path with two boardings and one alighting - built and run. | The test cycle (16), in one commit with AGG14-33. |
| AGG14-38 | High | High | `tests/emit/test_rail_detail.py:57-77` | cycle 16 | Opening `.rail.json` in the test means writing a real one, and this cycle's caption changes move its contents. | The test cycle (16), after the service-tier captions land. Assert endianness, the ordinal range and the `[station, line]` column order. |
| AGG14-39 | High | High | `tests/emit/test_modes.py:84-92` | cycle 16 | Same shape as AGG14-38: the size-only assertion has to become a decode, shown red under the reversed-channel mutation. | The test cycle (16). The mutation is already named - reverse the channel order and write big-endian. |
| AGG14-40 | High | High | `tests/emit/test_routes_json.py:22-34` | cycle 16 | Asserting a non-sentinel `prev` needs a fixture whose solve actually reaches an airport, which is the fixture AGG14-9 has to build anyway. | The test cycle (16), with AGG14-9. |
| AGG14-41 | High | High | `tests/emit/test_build_identity.py:68-79` | cycle 16 | The guard has to derive `called` from the source instead of from `STAMPED`; that AST walk is the same one AGG14-5 needs, and this cycle is only doing the rail half of that table. | The test cycle (16). Reuse the `ast.Name` extraction this cycle writes for `RAIL_PARSER_VERSION`. |
| AGG14-42 | High | High | `tests/emit/test_build_identity.py:20-29`; `tests/emit/test_index.py:171-210` | cycle 16 | Un-monkeypatching `_git_head` makes the test depend on the working tree's HEAD; seeing what else that breaks needs a suite run. | The test cycle (16). Assert that two different HEADs give two different `buildId`s. |
| AGG14-43 | High | High | `emit/airports_json.py:22-26`; `tests/web/test_app_constants.py:52-90` | cycle 16 | Pinning `build()`'s positional `zip` against `FIELDS` is a new reflection test that must be shown red under a name/country swap. | The test cycle (16), with AGG14-94, which is the same emitter's missing atomic-write coverage. |
| AGG14-44 | High | High | `tests/web/test_etops_is_not_a_control.py:54-69` | cycle 16 | Checking grep's exit status changes what the guard reports, and this cycle cannot run it to see whether it is already red. | The test cycle (16). Add a positive control so the guard cannot pass by matching nothing - `plan/README.md` rule 3. |
| AGG14-45 | High | High | `tests/web/test_reading_tier_refresh.py:36-64` | cycle 16 | Three defects in one file, one of which turns red on correct code; untangling them needs the suite. | The test cycle (16). Delete the file if it is still redundant with its sibling once the slice is fixed. |
| AGG14-46 | High | High | `tests/web/test_design_policy.py:63-70,95-131` | cycle 16 | Extending the design-policy gate to inline `style=` attributes will name whatever the page carries today, and `tests/web/` cannot be run this cycle. | The test cycle (16). The mutation is recorded - letter-spacing, uppercase and tabular figures on `#origin-name` - and must go red. |
| AGG14-66 | Medium | High | `tests/web/test_csp.py:20-35` | deferred | Pinning `default-src`, `object-src`, `base-uri`, `form-action`, `frame-ancestors` and the host list means asserting the file the deploy installs, and the deploy is blocked. | The test cycle (16) for the assertions; anything that changes the installed policy waits for a cycle whose deploy is not `--page-only`. |
| AGG14-74 | Medium | High | `tests/web/test_design_policy.py:144,169` | deferred | Reading the last declaration instead of the first changes what both checks measure; a suite run is needed to see whether the page still passes. | The test cycle (16), with AGG14-46 - same file, same gate. |
| AGG14-75 | Medium | High | `tests/web/test_design_policy.py:72-86` | deferred | Adding `web/boot.js` to the design-policy fixture may name real violations in a file nobody has scanned, and no suite can be run this cycle. | The test cycle (16), with AGG14-46 and AGG14-74. |
| AGG14-77 | Medium | High | `tests/contour/test_bands.py:127-137` | deferred | Adding the `integration` mark changes what the default gate deselects, and the cover-gate test reads the build's own caches, which the build is writing. | The lock clears, then the test cycle (16). |
| AGG14-78 | Medium | High | `tests/test_golden.py:33-52` | deferred | Tightening `test_golden.py` needs a door-to-door number this cycle's rail changes will move. | The first cycle after the service-tier speeds ship and a rebuild has produced new Seoul->Tokyo numbers. Set the band from the measured value, not from Phase A. |
| AGG14-79 | Medium | High | CLAUDE.md, `web/README.md` vs `tests/`, `scripts/*.sh` | deferred | Sixteen documented behaviours with no test is one work item per behaviour, not a fix, and four of them are CLAUDE.md prose rules with no mechanical subject. | One behaviour per cycle from the test cycle (16) onward, starting with `browser_verify.sh`'s water probe, which CLAUDE.md's deploy rule names explicitly. |
| AGG14-80 | Medium | High | `tests/sources/test_cache_provenance.py:239-253` | deferred | The test re-implements `cell_country`'s key in its own body, so it goes red on correct code the moment AGG14-118's version tag lands - which is cycle 15 work. | Cycle 15 adds the version tag; this guard must be fixed in the same commit or it reddens the gate. |
| AGG14-81 | Medium | High | `tests/test_cli.py:171,191,346` | deferred | Hardcoded artifact counts (`== 7`, `== 14`) are this repository's recorded gate-fails-on-correct-code shape, and the rail work may add an eighth artifact. | The service-tier commit if it adds an artifact; otherwise the test cycle (16) - derive the count from the emitter list rather than typing it. |
| AGG14-82 | Medium | High | `tests/cli/test_reindex.py:215,228` | deferred | A bare `monkeypatch.undo()` restoring the real `config.CACHE` is how 358 stray parquet files came back once; proving the scoped fix means running the suite and watching the real cache directory. | The test cycle (16). Scope the undo, and confirm no file appears under the real `config.CACHE` during the run. |
| AGG14-83 | Medium | High | `tests/graph/test_build.py:95-104,114-130` | deferred | Lower bounds on counts of upstream data defects go red when the upstream improves; relaxing them needs a suite run against the current Wikidata snapshot. | The test cycle (16). Assert the handling of a rejected pair, not the number of them. |
| AGG14-84 | Medium | High | `tests/graph/test_build.py:133-142` | deferred | Both halves are structurally true; replacing them means deciding what the airport-connectivity gate should assert, which reads the graph. | The lock clears, then the test cycle (16), with AGG14-85. |
| AGG14-85 | Medium | High | `tests/graph/test_nodes.py:34-47` | deferred | Same shape as AGG14-84, and the upper bound moves with the source gate it is supposed to be independent of. | The test cycle (16), with AGG14-84. |
| AGG14-86 | Medium | High | `tests/solve/test_origin_snap.py:82-113` | deferred | The docstring carries a false mutation certificate; correcting it means making the test call `_solve_one`, which builds a graph. | The test cycle (16). This is the false-certificate class `plan/README.md` rule 4 was written for, so the corrected certificate must be re-run, not re-read. |
| AGG14-87 | Medium | High | `tests/graph/test_air.py:91-127` | deferred | Pinning `KNEE_KM`'s lower side re-opens the question the 400 km knee commit settled, and the evidence for the knee is in `calibration.toml`, not in the test. | The test cycle (16). Pin both sides from the fitted knee's stated interval. |
| AGG14-88 | Medium | High | `tests/graph/test_ferry.py:174-192` | deferred | A partially off-mask fixture has to be constructed before `MAX_OFF_MASK_FERRY_FRACTION` is the thing under test. | The test cycle (16). |
| AGG14-89 | Medium | High | `tests/graph/test_build.py:36-39` | deferred | Deleting two assertions that restate a `RuntimeError` is trivial, but the file is `integration`-marked and the suite cannot be run. | The test cycle (16), with AGG14-173, which is the same file's marking defect. |
| AGG14-91 | Medium | High | `tests/emit/test_atomic_writes.py:21-31` | deferred | Proving `atomic_write` leaves the target untouched needs a pre-existing target in the fixture, and `_io.py` is imported by every live worker. | The test cycle (16). The mutation is named: add `path.unlink()` before `mkstemp` and the three tests must go red. |
| AGG14-92 | Medium | High | `tests/emit/test_reading.py:30-41,93-98,300-305` | deferred | Every reading fixture has `fine = np.zeros(..., bool)`, so exercising the split-cell branch means rebuilding the fixtures - and the reading tier is what the running build is emitting. | The lock clears, then the test cycle (16); pin the resolution argument, not only the function name. |
| AGG14-93 | Medium | High | `tests/emit/test_water.py` vs `web/app.js:777` | deferred | Cross-checking `water.LAYER` against the page's hardcoded `"source-layer": "water"` is a two-line guard, but `dist/water.pmtiles` and the deploy that would prove it are both off-limits. | The test cycle (16). CLAUDE.md's deploy rule names this file explicitly, so the guard is cheap and overdue. |
| AGG14-94 | Medium | High | `tests/emit/test_atomic_writes.py:59-81`; `emit/{borders,places,airports_json}.py` | deferred | Covering the four uncovered emitters means changing how three of them bind `atomic_write` at import - a source change in the emit path the build is running. | The lock clears, then the test cycle (16). `emit/places.py` needs a test file at all, which AGG14-151 also wants. |
| AGG14-95 | Medium | High | `tests/contour/test_grid.py:34-43`; `contour/grid.py:44,97,128` | deferred | `grid.universe`'s cache test and `native_edges`' missing one both key on caches the running build is reading. | The lock clears, then the test cycle (16), with AGG14-186 - the same hand-rolled key convention. |
| AGG14-96 | Medium | High | `tests/contour/test_bands.py:16-30`; `contour/bands.py:58,312,322` | deferred | Testing edge inclusivity on the shipped `band_indices` rather than on the unused `band_of` is small, but the suite cannot be run. | The test cycle (16). Assert an on-edge cell's band directly, so `side="left"`->`"right"` reddens it. |
| AGG14-97 | Medium | Medium | `emit/index.py:341-342`; `web/app.js:2098` | deferred | `reading_parent_count` has no test anywhere, and adding one writes an index fixture whose format the rebuild's `index.json` may still move. | The test cycle (16), after the rebuild's `index.json` is final. |
| AGG14-98 | Medium | High | `tests/emit/test_water.py:26-45` | deferred | The two tests are conjointly an equality gate against the file's own comment saying it should be an inequality; deciding which is right needs the tileset. | The lock clears and `water.pmtiles` can be inspected; then the test cycle (16). |
| AGG14-99 | Medium | High | `web/app.js:120-121,1855-1859` | deferred | Exercising the page's mixed-build refusal needs a node harness that feeds it wrong byte lengths - new harness work, not a guard edit. | The test cycle (16). This is the page's only defence against AGG14-76, so it goes with it. |
| AGG14-100 | Medium | Medium | `tests/web/test_etops_is_not_a_control.py:98` | deferred | The scan covers comments and docstrings against the same file's stated policy, and it is unanchored; changing it changes what the ETOPS premise guard sees. | The test cycle (16). Strip comments first - `plan/README.md` rule 1 - and anchor the pattern. |
| AGG14-101 | Medium | High | 18 of 34 files in `tests/web/` | deferred | Eighteen of thirty-four `tests/web/` files skip green when `node` resolves through a per-shell fnm path; proving the fix means running the suite from a bare `sh -c`, which is CPU this cycle does not have. | The test cycle (16). Resolve `node` explicitly and fail loudly when it is absent, which is also half of AGG14-24. |
| AGG14-167 | Low | High | `tests/test_licence_firewall.py:74` | deferred | A vacuous assertion two lines below a `pytest.skip` that guarantees it - trivial, but it sits in the licence firewall, whose other half (AGG14-162) needs a policy decision. | The test cycle (16), with AGG14-162. |
| AGG14-168 | Low | Medium | `tests/sources/test_cache_provenance.py:135-158,296-345` | deferred | `any(c.isdigit())` carries a ~1/1182 false-red rate per constant change, and five subprocesses depend on pytest's CWD; both fixes need the suite to confirm. | The test cycle (16). |
| AGG14-169 | Low | Medium | `tests/calibrate/test_fit.py:29-42` | deferred | A noiseless fixture accepting `rel=0.15` admits a systematically biased estimator; tightening it means re-running the fit. | The test cycle (16). Its sibling already earns its tolerance by adding noise - copy that. |
| AGG14-170 | Low | Medium | `tests/graph/test_ground.py:36-78` | deferred | The assertions omit the zone-crossing `extra` and pick their pair by scanning from index 0, so a land-mask refresh reddens them on correct code - and the land mask is a `data/` cache the build is writing. | The lock clears, then the test cycle (16). |
| AGG14-171 | Low | High | `tests/graph/test_nodes.py:24-31` | deferred | True by construction; replacing it with a real assertion - ICN's cell contains ICN's coordinate - needs the index built. | The test cycle (16). |
| AGG14-172 | Low | High | `tests/solve/test_origin_snap.py:57` | deferred | `assert ring[pos] in ring` is a tautology whose real content is "did not raise". | The test cycle (16). Say so explicitly, or assert the snapped cell. |
| AGG14-173 | Low | High | `tests/graph/test_build.py:7,42-92` | deferred | Removing a module-wide `integration` mark changes which tests the default gate runs, and this cycle cannot run it. | The test cycle (16), with AGG14-89. |
| AGG14-174 | Low | High | `tests/graph/test_ferry.py:109-113`; `tests/graph/test_build.py:81-92` | deferred | `MIN_FERRY_KM` has no test at all and `IMPLAUSIBLE_LONGHAUL_KM` is exercised only 6,000 km past its threshold. | The test cycle (16). Pin each constant just inside and just outside. |
| AGG14-175 | Low | High | `tests/graph/test_build.py:107-111` | deferred | The fixture calls `build.build_graph` a second time, duplicating a multi-minute assembly - exactly the CPU this cycle is forbidden to spend. | The lock clears, then the test cycle (16); both out-params fit in one call. |
| AGG14-176 | Low | High | `tests/contour/test_bands.py:100,113` | deferred | Nine-significant-figure h3 coordinates fail on an h3 point release while naming no defect; loosening them is safe but needs the suite. | The test cycle (16). |
| AGG14-177 | Low | High | `tests/emit/test_hover.py:43-48` | deferred | `raw.dtype.itemsize == 2` is tautological because the test created `raw` as `<u2`, and endianness is not checked here at all. | The test cycle (16), with AGG14-39 - both are the emit-binary shape. |
| AGG14-178 | Low | Medium | `tests/emit/test_index.py:15-20`; `tests/emit/test_reading.py:189-199` | deferred | Two-element fixtures make `np.diff(...) > 0` a single comparison and an empty diff vacuously true, and the page binary-searches both files. | The test cycle (16). Use at least four elements and assert the diff is non-empty. |
| AGG14-179 | Low | High | `tests/web/test_reading_tier_fallback.py:326-341` | deferred | A biconditional passes when both sides are deleted; replacing it means asserting the call happens, which needs the harness. | The test cycle (16). |
| AGG14-180 | Low | High | `tests/web/test_vendor.py:38,208` | deferred | `assert fit is not None` cannot fail, and the one-directional subset lets a hash recorded for a deleted vendor file survive unflagged. | The test cycle (16), with AGG14-134 - the same enumeration's other half. |
| AGG14-181 | Low | Medium | `tests/web/test_reading_slot.py:87,98` | deferred | Hard-coded pentagon child counts undo the fixture two dozen lines above that deliberately reads both resolutions from `config`. | The test cycle (16). |
| AGG14-182 | Low | Medium | `tests/web/test_route_geometry.py:220` | deferred | The map stub returns one recorder for any source id, so writing features into the wrong source passes; fixing the stub touches every test that uses it. | The test cycle (16). |

### CL-D -- Cache invalidation and derived-cache keying (6 of 6)

CLAUDE.md's *"Derived caches key on `_params_hash` of the constants **and inputs** that govern them, never on a bare `.exists()`"* applied and mis-applied. Every one of these changes a cache key, and a changed key means the next build re-derives that cache. That is a cost worth paying once, at the start of a build window -- not five times, and not under a build that is reading the caches.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-60 | Medium | High | `sources/roads.py:99-140` | deferred | Caching `roads.cell_class` introduces a derived-cache key the running build would then miss on, and the pass it removes is 36 s x 4 inside that build. | The lock clears. Take it first in cycle 15's performance pass - it is 45 % of every build's startup, and its sibling `road_class_grid()` shows the key shape. |
| AGG14-68 | Medium | High | `sources/{landmask,airports,roads,countries,urban}.py`; `emit/{places,water,borders}.py`; `scripts/expand_origins.py` | deferred | Checksumming every downloaded dataset re-keys every derived cache in `sources/` and `emit/`, so the next build re-derives all of them - a cost worth paying exactly once, at the start of a build window. | The lock clears and a rebuild is scheduled. Land the checksums in that window so one re-derivation is paid, not several. |
| AGG14-72 | Medium | High | `sources/osm.py:303-305,317-319` | deferred | `sorted(SCHEMA)` stamps column names only; adding dtypes changes the rail cache path, and this cycle is already changing that path for `RAIL_PARSER_VERSION`. | The service-tier parse bumps the rail key; add the dtypes to the same bump so only one cache miss is paid. If that window is missed, the next `sources/osm.py` change. |
| AGG14-118 | Medium | High | `sources/countries.py:96-116,140-177`; `sources/urban.py:76-94` | deferred | Memoising `cell_country` and its ~300 MB key construction changes a cache key the running build reads three times per run. | The lock clears. Take it in cycle 15's performance pass with AGG14-80, whose test re-implements this key and will redden when it changes. |
| AGG14-166 | Low | High | `_io.py:92-104` | deferred | `_reject_unordered` stopping at depth 6 is proven by execution, but reaching depth 7 needs a caller that nests that deep and none does today. | The next cycle that touches `_io.params_hash`, or the first stamp that nests deeper than six levels - whichever is first. |
| AGG14-186 | Low | Medium | `contour/grid.py:44,90` | deferred | `contour/` hand-rolls sha256 with a manually bumped `GRID_VERSION`; unifying it on `_io.params_hash` re-keys the grid caches the build is reading right now. | The lock clears, with AGG14-95, which tests those same keys. |

### CL-E -- Build robustness: transactions, resume, locks, atomic writes (19 of 19)

What a 39-hour build that has died twice most needs, and every row is in the code that build is running. The six Highs are scheduled for cycle 15 rather than deferred; the rest of the cluster follows in the same cycle, sequenced behind them.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-10 | High | High | `cli.py:300-320` | cycle 15 | A per-origin transaction changes how every artifact is written, and doing that under a build that is writing them is how this project lost a previous rebuild. `dist/` held three half-written origins during the review. | `dist/.build.lock` is gone. Architect's design - a `{slug}.done` carrying `inputsHash` - lands with AGG14-107 and AGG14-104. |
| AGG14-17 | High | High | `cli.py:249-256`; `emit/index.py:97-125,330-337` | cycle 15 | Widening `_preflight_origins`'s `except` reads `data/origins.toml` and changes the pre-flight inside the build this cycle must not restart. | The lock clears. Catch `KeyError` and `TypeError`, name the slug, and validate `name` before the solve rather than at `write_index`. |
| AGG14-18 | High | High | `solve/dijkstra.py:35-45`; `graph/nodes.py:89-95`; `scripts/expand_origins.py:113,134` | cycle 15 | Rejecting an out-of-range origin coordinate before h3 normalises it changes which origins solve, and the running build has already accepted whatever the roster holds. | The lock clears. Range-check latitude and longitude in `snap_origin`, then re-run the pre-flight over the 1,464-row roster and report what it rejects. |
| AGG14-19 | High | High | `cli.py:720-739` | cycle 15 | A hang detector needs a heartbeat from the worker - a change to `_consume` and to the worker loop that is running. | The lock clears. The repository's own recorded three-hour deadlock is the test case; a worker that stops reporting must be killed and named. |
| AGG14-20 | High | High | `validate.py:186-193`; `emit/modes.py:48-51` | cycle 15 | Removing the lazy fork-unsafe fallbacks in `validate.py` and `emit/modes.py` changes import order inside the worker, and the only defence today is that the caller happens to pass the kwarg. | The lock clears. Make the kwarg required and delete the fallback, so the deadlock cannot be one keyword argument away. |
| AGG14-21 | High | High | `cli.py:112-138`; `_io.py:23-31` | cycle 15 | The lock records a bare pid on a shared NFS mount - and the lock in question is the one the running build holds, so it cannot be changed underneath it. | The lock clears. Record host and boot id; a foreign host must say "another machine holds this" rather than advise deleting a live build's lock. |
| AGG14-55 | Medium | High | `cli.py:464,468` vs `:417,513` | deferred | `hover_cells.bin` and `reading_parents.bin` are rewritten before the first origin solves and unconditionally, including under `--limit`/`--only`; changing that writes under `dist/`. | The lock clears. Gate both writes on a full run, which is also what makes `--only` safe - AGG14-79 names it as an untested documented behaviour. |
| AGG14-76 | Medium | High | `scripts/check_dist.py:369,372-382,451`; `emit/index.py:263-265` | deferred | Per-origin build identity means a new field in every artifact and a new check in `check_dist.py` - a deploy-path change while a build is producing those artifacts. | The lock clears and a rebuild is scheduled: the identity must be written by the build that produces the files, so it lands immediately before one, with AGG14-112 and AGG14-99. |
| AGG14-104 | Medium | High | `cli.py:634-661,711` vs `scripts/check_dist.py:296-338` | deferred | Three definitions of "publishable" collapse into one predicate shared by `_reindex`, `check_dist.py` and the CLI, and `_reindex` cannot be exercised while the build owns `dist/`. | The lock clears. One predicate, called from all three, with the `.rail.*` pair included and `railDetail` set from all origins rather than any. |
| AGG14-106 | Medium | High | `cli.py:308,369,464,468` vs `:556,796` | deferred | A `--dist` staging tree is the standard answer to "never deploy a partial dist/", and it can be neither built nor tested while `dist/` is held. | The lock clears. It is a prerequisite for AGG14-107 and for any deploy that swaps rather than overwrites. |
| AGG14-107 | Medium | High | `plan/` (no entry), `cli.py:400,418` | deferred | Resume is blocked by five things, four of which are themselves cycle-15 items; sequencing it first would build it on a completion record that does not exist. | AGG14-11, AGG14-10, AGG14-21, AGG14-104 and AGG14-106 have landed. Graph persistence is explicitly not a blocker - 310 s against 38 h. |
| AGG14-108 | Medium | High | `cli.py:108-133,154-183`; `scripts/deploy_verify.sh:74` | deferred | Generalising `_acquire_lock` into a shared namespace changes the lock the running build is holding. | The lock clears, in one commit with AGG14-21 - both change the same file's staleness rule. Cycle 13 scheduled this as C13-8 and it is still open. |
| AGG14-109 | Medium | High | `cli.py:291,309,317,437-457,483-484`; `emit/rail_detail.py:89` | deferred | Typing the worker context changes `_solve_one`'s signature in the module the workers have already imported. | The lock clears. A frozen dataclass, and a `KeyError` rather than `.get` for `rail_tables` - the key whose silent absence drops station naming from every origin. |
| AGG14-113 | Medium | High | `_io.py:46-55` | deferred | The cleanup `unlink` outside a try is reached only on a write failure, and adding `fsync` changes the write path every worker is using right now. | The lock clears. Wrap the cleanup, add `fsync` before `os.replace`, and cover the NFS `ESTALE` case in the test. |
| AGG14-114 | Medium | High | `_io.py:43`; `emit/tiles.py:46-61`; `cli.py:378` | deferred | Sweeping `.tmp` leftovers means deleting files under `dist/`, which this cycle is forbidden to touch. | The lock clears. Sweep at build start, and make `check_dist.py` name the remedy rather than refuse the whole deploy with none. |
| AGG14-115 | Medium | High | `scripts/build_water_tiles.py:13`; `scripts/expand_origins.py:141` | deferred | Making `build_water_tiles.py` and `expand_origins.py` take the build lock changes the lock protocol under a build that holds it. | The lock clears, with AGG14-21 and AGG14-108 - one lock change, not three. |
| AGG14-116 | Medium | High | `scripts/expand_origins.py:141`; `calibrate/ground.py:125`; `scripts/adsb_extract.py:188`; `emit/water.py:58`; `scripts/osm_rail.sh:40` | deferred | Five non-atomic writers include an append to `data/origins.toml`, and `data/` is off-limits this cycle. | The lock clears. Route all five through `_io.atomic_write`, the roster append first, since a crash there makes every later build unparseable. |
| AGG14-192 | Low | High | `cli.py:123-137` | deferred | A lock read inside its own create window prints a misleading remedy; the fix is in the lock code the running build holds. | The lock clears, with AGG14-21. |
| AGG14-193 | Low | High | `cli.py:196,733-739`; `_build_all`'s `finally` | deferred | A `MemoryError` returning as a bare traceback and a SIGKILLed parent skipping `finally` are both properties of the supervisor that is currently running. | The lock clears. Wrap worker exceptions in `GateFailure`, and make the lock self-describing so a skipped `finally` is diagnosable - which is AGG14-21. |

### CL-F -- Build performance and memory (12 of 12)

Perf-reviewer's measured ordering stands and is not re-litigated here: AGG14-1, AGG14-2 and AGG14-3 take the build from a measured 37.5 h to roughly 25 h **and** remove the memory pressure that killed it twice. All three are scheduled for cycle 15. Nothing in this cluster can be measured while a build is using the machine, which is also why none of it can be done now.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-1 | Critical | High | `contour/bands.py:65-67,106-107` | cycle 15 | `contour/bands.py` is imported by all five live workers: an edit cannot reach the running processes, and a wrong one would not surface until the next 37-hour run. | `dist/.build.lock` is gone. It goes first in cycle 15 - a hoist of a build-constant answer out of a per-cell loop, worth ~6.8 h of wall clock, and the smallest change in the set. |
| AGG14-2 | Critical | High | `contour/bands.py:164-182,290-333`; `validate.py:108-109`; `emit/tiles.py:79-83`; `emit/modes.py:52` | cycle 15 | Replacing the dict/shapely round-trip rewrites the band emitter - the mechanism behind both build deaths, and the last module that should change under a running build. | The lock clears. Take it second, after AGG14-1, and measure worker RSS before and after; 0.63 -> 3.38 GB is the recorded shape. |
| AGG14-3 | Critical | High | `emit/hover.py:98-128,139-142`; `emit/{itinerary:58,66,modes:91,97,rail_detail:86,94}.py` | cycle 15 | The res-4 parent list and the duplicated `_cell_pos` are rebuilt four times per origin inside the emit path the build is executing. | The lock clears. Build both once per worker and pass them in, then re-measure the ~38 s and ~600 MB. |
| AGG14-26 | High | High | `graph/ground.py:99-169` | cycle 15 | `ground.hex_edges` builds 8-10 GB of numpy temporaries in the build's parent process - the process holding the lock. | The lock clears. Chunk the centroid gathers and the haversine, and record the new peak; with AGG14-117, the other half of that peak. |
| AGG14-30 | High | High | `emit/itinerary.py:21-46`; `emit/modes.py:32-80`; `emit/rail_detail.py:24-41` | cycle 15 | Three argsorts and three Python tree walks per origin live in the three emitters the build is running. | The lock clears. One walk shared by the three emitters, and a uint16 accumulator instead of the 493 MB float64. |
| AGG14-31 | High | High | `validate.py:43-47` | cycle 15 | `check_coverage`'s 10.2 M `cell_to_latlng` calls rebuild a build-constant mask inside the per-origin gate. | The lock clears. Hoist the mask to build scope - which is also what makes AGG14-56's predicate fix affordable. |
| AGG14-59 | Medium | High | `contour/bands.py:254-262` | deferred | `_coarse_features` rebuilds a 4.5 M-element object array per origin for an origin-independent mapping; it is the same hoist as AGG14-1 and belongs in the same commit. | The lock clears, with AGG14-1 and AGG14-3. |
| AGG14-63 | Medium | Medium | `contour/bands.py:233` | deferred | Python string refcounts make each worker privately copy ~653 MB; fixing it means changing how `idx.cells` is represented, which AGG14-30 and the solver service also want. | The lock clears, after AGG14-2, so the remaining peak can be attributed to one cause. |
| AGG14-117 | Medium | High | `graph/build.py:426-449` | deferred | The duplicate-edge check's 656 MB `np.unique` doubles graph assembly's peak, in the parent process the build is running. | The lock clears, with AGG14-26 - one pass over `graph/build.py`'s peak, answering a boolean without sorting 656 MB. |
| AGG14-155 | Low | Medium | `cli.py:76-96` | deferred | Raising the worker cap is only safe once the memory findings land; today's measured peak is 3.4 GB x 5 on a 32 GB machine at 94 % swap. | AGG14-1, AGG14-2 and AGG14-3 have landed and the new peak is measured. Then set the cap from measured RSS, not from a cell-count threshold - and correct AGG14-213's comment in the same commit. |
| AGG14-156 | Low | High | `validate.py:196-222` | deferred | 61,000 one-element numpy haversine calls are ~15-20 us of dispatch each: real, but small beside the items above it in this cluster. | The lock clears; take it in cycle 15's performance pass once the large items are measured, so the gain is attributable. |
| AGG14-157 | Low | High | `emit/rail_detail.py:48-50`; `graph/rail.py:66,73,88`; `scripts/check_dist.py:299-345` | deferred | Four polars `map_elements` UDFs are build-path work, and the 293 MB `json.loads` is in the deploy gate this cycle must not disturb. | The lock clears for the UDFs. The `check_dist.py` half waits for a cycle whose deploy is not the one being changed - the rule cycle 13 recorded. |

### CL-G -- Web runtime failure paths and URL state (7 of 7)

Each of these ends in a page that is wrong or blank with nothing in the console -- the failure CLAUDE.md's deploy rule was written after: *"No deploy is done until it has been opened in a browser ... `curl` returning 200 proves nothing about whether the page runs."* That rule is exactly why they are scheduled rather than done: the proof is a browser session against a deploy, and the deploy is blocked.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-22 | High | High | `tests/web/test_module_scope_order.py:42`; `web/app.js:69,119,747` | cycle 16 | Re-anchoring the `_AWAIT` regex to app.js:69 turns the guard red for every binding declared between :69 and :747; it will name real work, and this cycle cannot run the suite to see how much. | The test cycle (16). Fix the regex first, then take whatever the guard names - this is the guard that exists because of a shipped temporal-dead-zone crash. |
| AGG14-23 | High | High | `web/app.js:4256-4262`; `web/boot.js:69-79,131-138`; `web/index.html:161` | cycle 17 | Both halves are page-runtime changes whose only proof is a browser, and CLAUDE.md's deploy rule forbids calling a page change done until it has been opened - which needs a deploy, which needs `dist/`. | `dist/.build.lock` is gone and a deploy runs. Move `appReady` to the end of the module, time-bound boot.js's capturing `error` listener, then check 1280x800, 820x1180, 390x844 and 844x390. |
| AGG14-25 | High | High | `web/app.js:865,1504,3417-3435` | cycle 17 | Three empty `catch`es; the visitor-visible one paints zero route features beside a complete itinerary. Proving the fix needs the page loaded against a real `airports.json`. | The page-and-deploy cycle (17). Report the failure in `#status` instead of swallowing it, and verify in a browser per CLAUDE.md's deploy rule. |
| AGG14-54 | Medium | High | `web/app.js:4308-4311` vs `:1643-1645,3094-3111` | deferred | `geocoded: Boolean(requestedPin.label)` is backwards - a one-line fix whose only verification is a shared-URL round trip in a browser. | The page cycle (17), with AGG14-153: both are `?at=`/`?to=` parsing. |
| AGG14-150 | Low | High | `sources/urban.py:92-94`; `web/app.js:1513-1514` | deferred | Two unwrapped planar longitude deltas; the `sources/urban.py` half changes a derived cache the running build is reading. | The lock clears for the `urban.py` half. The `app.js` half goes with the page cycle (17) - Fiji, Anadyr and the western Aleutians are the test cases. |
| AGG14-152 | Low | High | `web/app.js:1227-1286` | deferred | `solvePoint` not checking `signal.aborted` and admitting `NaN` are both on the solver relay path, and no solver service is resident yet. | The page cycle (17), or the first cycle that makes the solver resident - whichever is first. |
| AGG14-153 | Low | High | `web/app.js:1672-1681` | deferred | `Number("")` is 0, so `?at=37.5665,126.978,` opens on the whole globe instead of being rejected as the docstring promises. | The page cycle (17), with AGG14-54. |

### CL-H -- Deploy and release gates (7 of 7)

Five gates that report rather than assert, or exit 0 on failure. Cycle 13 recorded the rule that governs all of them and it still holds: **changing a gate in the same cycle that runs it makes the next failure unattributable.** This cycle runs none of them, so it can prove nothing about them either.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-24 | High | High | `scripts/browser_verify.sh:106,203-221,228-462,430,599` | cycle 17 | `browser_verify.sh` is the gate CLAUDE.md's deploy rule rests on, and cycle 13 recorded the reason not to touch it in a cycle that runs it: the next failure becomes unattributable. This cycle cannot run it at all. | A cycle whose deploy is not `--page-only` and which is not itself changing the gate: poll `appReady`, read `agent-browser errors`, replace the ~20 fixed sleeps with waits, and add a `trap`. |
| AGG14-57 | Medium | High | `scripts/deploy_verify.sh:67-84,169-199` | deferred | Same rule: `deploy_verify.sh` is the gate that would have to run to prove the change, and its lock probe is TOCTOU against a lock that is currently held. | The first cycle whose deploy is not `--page-only`. Probe `{slug}.json`, `reading_parents.bin` and `.r6.bin`, sample more than one origin of 1,464, and fail rather than fall back to `seoul`. |
| AGG14-64 | Medium | High | `scripts/deploy_verify.sh:201-206` | deferred | The CSP check prints `ABSENT` and exits 0 - a two-line fix in a script this cycle must not run. | The first cycle whose deploy is not `--page-only`. Set `live_fail`, and move the check above the gate that reads it. |
| AGG14-67 | Medium | Medium | `scripts/check_dist.py:72-73,117-133,380-404,455-468` | deferred | The build host's home directory can only be removed from `water.pmtiles` by rebuilding the tileset, and `scripts/build_water_tiles.py` is explicitly off-limits this cycle. | The lock clears and the water tiles are next rebuilt. Strip the metadata blob and promote the gate's `warn` to `bad` in the same commit. |
| AGG14-73 | Medium | High | `scripts/check_dist.py:393-397`; `tests/web/test_check_dist.py:57-59` | deferred | The `REQUIRED_EXTRAS` refusal is the half of CLAUDE.md's deploy rule that names `water.pmtiles`; testing it means a fixture that removes one, which changes the deploy gate. | The test cycle (16) for the fixture; any change to the gate itself waits for a non-`--page-only` deploy. |
| AGG14-121 | Medium | High | `scripts/osm_rail.sh:20,33,45,48` | deferred | Re-running `osm_rail.sh` re-downloads continental extracts - network and `data/` writes this cycle must not spend. | The lock clears and the next rail extract is taken, which the service-tier parse will force since the parquet key changes. Add `-e`, a failure counter, and make `[ALL DONE]` conditional then. |
| AGG14-122 | Medium | High | `scripts/check_ramps.py:79-85,217-246` | deferred | A reorder in `app.js` yields zero parsed schemes and `--respace` then rewrites the file byte-identically reporting success; the fix has to be proved by running the script over the real ramps. | The test cycle (16). Refuse on zero parsed schemes, and assert the parsed count against `tests/web/test_ramps.py`'s pinned twelve. |

### CL-I -- Pipeline correctness, error handling and silent success (17 of 17)

Emitters and sources that ship an empty, truncated or unvalidated artifact as success. AGG14-27 is the live one -- every build today takes the legacy `routes.parquet` path above both integrity gates -- and it is scheduled for cycle 15 with AGG14-28 and AGG14-29.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-27 | High | High | `sources/routes.py:267-280` vs `:309-319` | cycle 15 | This is the live path today: every build reads the legacy parquet above both integrity gates. Correcting it re-crawls or re-keys the route network - the most expensive thing that can be done to a build that is running. | The lock clears. Cycle 13 scheduled this as C13-7 and its rule still holds: fix it together with AGG14-72's key fields, or not at all. |
| AGG14-28 | High | High | `sources/osm.py:336-345` | cycle 15 | The emptiness guard is three lines, but it changes what a cache miss does, and the ferry parquet is one the running build is reading. | The lock clears. Mirror `rail_routes`' guard exactly and add the zero-row fixture, so a filter change cannot cache an empty ferry network as success. |
| AGG14-29 | High | High | `scripts/adsb_extract.py:55,182-196` | cycle 15 | `doc.get("trace") or []` makes the >50 % refusal unfireable, and re-running `adsb_extract.py` is network plus a calibration-input write under `data/`. | The lock clears. Distinguish a missing key from an empty trace, then re-run the extract with the refusal armed and record the unreadable count. |
| AGG14-53 | Medium | High | `emit/hover.py:131-135`; `emit/modes.py:100`; `emit/routes_json.py:33`; `web/app.js:2621-2665` | deferred | Truncation against rounding is a one-line choice, but changing it moves every printed minute and therefore needs a re-emit under `dist/`. | The lock clears and a re-emit is scheduled. Make `emit/` and `routes_json` agree, and assert a band-edge cell so the legend mark, the painted band and the printed minute are proved to agree. |
| AGG14-56 | Medium | High | `validate.py:31-54` vs `emit/hover.py:50` | deferred | Fixing the predicate changes whether the coverage gate passes for origins the running build has already published. | The lock clears. Use the `UNREACHABLE` sentinel instead of `np.isfinite` and re-run the gate over the finished build; AGG14-31's hoisted mask makes that affordable. |
| AGG14-105 | Medium | High | `emit/{places,airports_json,borders}.py`; `scripts/check_dist.py:28` | deferred | Giving `places.json`, `airports.json` and `borders.json` a caller means adding a command that writes under `dist/`. | The lock clears. Add one `emit-static` command, move the downloads into `sources/` where they belong, and have `check_dist.py` name the command it needs rather than a file. |
| AGG14-119 | Medium | High | `emit/water.py:117-142` vs `emit/tiles.py:126-133` | deferred | The only way to exercise a discarded tippecanoe stderr is to run the water build, which is off-limits this cycle. | The lock clears and the water tiles are next rebuilt, with AGG14-67 and AGG14-160. Mirror `emit/tiles.py`'s stderr handling and assert the output is non-empty. |
| AGG14-120 | Medium | High | `scripts/calibrate_ground.py:134-140`; `calibrate/ground.py:50-64` | deferred | `except RuntimeError: break` turns "GOOGLE_ROUTES_API_KEY is not set" into "only 0 usable samples"; confirming the corrected message means running the calibration script. | The next calibration cycle, or the first time `scripts/calibrate_ground.py` runs for any reason. |
| AGG14-123 | Medium | High | `emit/borders.py:72,74-84`; `emit/water.py:89` | deferred | Adding the empty-FeatureCollection guard changes emitters the running build is using, and two bare `next()` calls raise `StopIteration` with no message. | The lock clears. Copy `emit/places.py`'s guard into `borders.py` and `water.py`, and replace both `next()` calls with a named failure. |
| AGG14-149 | Low | High | `sources/routes.py:327` vs `sources/airports.py:23-47` | deferred | Reproducing the failure means pruning `data/cache/`, which this cycle must not touch. | The lock clears. Route `_wikipedia_titles` through `airports._download()` so a pruned cache re-downloads instead of raising from inside a multi-hour crawl. |
| AGG14-151 | Low | High | `emit/places.py:57-66` | deferred | One malformed GeoNames row aborts `places.json`, and the emitter has no test file at all (AGG14-94), so the fix would ship unguarded. | The test cycle (16) gives `emit/places.py` a test file; the `KeyError`/`ValueError` guard lands with it. |
| AGG14-165 | Low | High | `graph/headway.py:18,29-30` | deferred | `NO_SERVICE` is unreachable because both callers floor their frequency first, so the defect is latent - but if it ever fired, `10**7` would pass `build_graph`'s check and overflow uint16. | The cycle that takes AGG14-69 and decides what `headway.py`'s semantics actually are; delete the constant or make it raise, in the same commit. |
| AGG14-189 | Low | High | `emit/itinerary.py:18,65-70` vs `emit/rail_detail.py:107-110` | deferred | `NO_AIRPORT = 0xFFFF` has no overflow guard where `NO_RAIL` raises for the identical case, but 65,535 airports is far from today's 4,008, so it is latent. | The next cycle that touches `emit/itinerary.py`, or the first time the airport table exceeds 32,768 rows - whichever is first. |
| AGG14-190 | Low | High | `emit/modes.py:24,27`; `emit/index.py:214-215` | deferred | Renaming the "track" channel changes a user-facing label and `index.json`'s `modeDetail`, which is a re-index under `dist/`. | The documentation cycle (18), with AGG14-131 - both are the mode-breakdown's copy, and only the hover tooltip currently corrects it. |
| AGG14-194 | Low | High | `cli.py:330-350` | deferred | Widening `_log_reading_cost`'s `except` changes the build's own failure path at the last statement before `index.json` is written. | The lock clears. Catch `Exception` there, which is what the comment already claims it does. |
| AGG14-195 | Low | High | `cli.py:603-609,671` | deferred | `_reindex` cannot be run while the build owns `dist/`, so a corrected error path could not be exercised. | The lock clears, with AGG14-104's single publishability predicate - `_reindex` is the caller that needs it most. |
| AGG14-196 | Low | High | `sources/routes.py:129,237-251` | deferred | Reproducing a revision-deleted article means running the crawl: network and hours, and it writes under `data/`. | The lock clears and the next route crawl runs - which AGG14-27's key change will force. Fix the misleading `failed: ... done` pair in the same commit. |

### CL-J -- Web design, layout and accessibility (16 of 16)

Four of these (AGG14-48, 124, 130, 208) are one defect repeated an element at a time: the folded phone sheet was fixed for `#time` and not for the sentences that qualify it. All of them are measured in a browser and none can be verified without one. CLAUDE.md's viewport list -- 1280x800, 820x1180, 390x844, 844x390 -- is the acceptance criterion for the whole cluster.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-47 | High | High | `web/index.html:466-472,478-487` | cycle 17 | Twelve colour-scheme and six ocean radios measure 1.30:1 against SC 1.4.11's 3:1; the fix is CSS but its proof is a browser pass at four viewports, which needs a deploy. | The page-and-deploy cycle (17). Extend the `--line-ctl` control-boundary fix to the radios and re-measure both the border and the selected ring. |
| AGG14-48 | High | High | `web/index.html:718-719,828,836` | cycle 17 | The folded phone sheet shows a large figure attributed to a city the reader did not choose, with the correction suppressed - a user-facing wrong statement whose fix can only be verified at 390x844. | The page cycle (17). Take it in one commit with AGG14-124, AGG14-130 and AGG14-208: the same defect at three more elements. |
| AGG14-124 | Medium | High | `web/index.html:718-719,859` | deferred | The same folded-sheet defect one element further along: `#where` carries the only "- from Seoul", under a caption that then names no city. | The page cycle (17), in one commit with AGG14-48, AGG14-130 and AGG14-208. |
| AGG14-125 | Medium | High | `web/index.html:692-698,748-770` | deferred | The landscape block does not override the grab handle, so folding hides the panels and leaves the 300 px column; measuring that needs 844x390 in a browser. | The page cycle (17). |
| AGG14-126 | Medium | High | `web/index.html:162-166,916` | deferred | A 22 px overflow with `white-space:nowrap` forces a horizontal scrollbar on the whole rail; the fix is an ellipsis and the proof is a browser at 390x844. | The page cycle (17). |
| AGG14-127 | Medium | High | `web/index.html:243-253,667`; `web/app.js:371-376` | deferred | The idle prompt measures 69 px against a `min-height:50px` that a comment says reserves the number's height; the legend jumps 19 px and only a browser shows it. | The page cycle (17). Measure the idle line, the committed line and the cold-load sequence before changing the reserve. |
| AGG14-128 | Medium | High | `web/index.html:788-790,197,646,739` | deferred | Three dead `.mast p` rules remain after the standfirst was removed, so re-adding a `<p>` would be silently invisible on every phone. Whether the page should name itself above the fold is a design decision, not a defect fix. | The page cycle (17): delete the rules, or restore a standfirst if the owner wants one. Do not add copy on our own initiative. |
| AGG14-129 | Medium | High | `web/index.html:358-368` | deferred | `.legs h2` runs the hierarchy backwards in exactly the two channels CLAUDE.md's design policy says to use, so the fix must stay inside those channels. | The page cycle (17). Raise weight and lightness only - no uppercase, no letter-spacing, no size trick that breaks the scale. |
| AGG14-130 | Medium | High | `web/index.html:718-719,873,1044` | deferred | The Privacy link sits in the always-visible legend credit precisely so it is always reachable, and its target is inside a `display:none` `<details>` when the sheet is folded. | The page cycle (17), with AGG14-48. |
| AGG14-197 | Low | High | `web/index.html:255` | deferred | `.reading .at` reserves 31.2 px for an idle line that measures 36 px and a committed one that can run to four lines - a reserve that holds for nothing that occurs. | The page cycle (17), with AGG14-127 - the same reserved-height arithmetic. |
| AGG14-198 | Low | High | `web/index.html:211-213` | deferred | `.reach dd{width:5.5ch}` is a no-op without `text-align:right`; the two places that got it right show the fix, and the comment beside it correctly refuses tabular figures. | The page cycle (17). Add `text-align:right`, keep the width, and keep the policy note. |
| AGG14-199 | Low | High | `web/index.html:440-441` | deferred | 63.8 px against 66.2 px for `120 h 59 min`, and `flex:none` sends the overflow left into a city name that cannot move. | The page cycle (17). Widen the column to the measured worst case, or shorten the format. |
| AGG14-200 | Low | Med-High | `web/index.html:477-489` | deferred | "Match the scheme" wraps in a 60 px ocean button and drags its whole flex row ~13 px taller; "Deep blue" fits with 0.2 px to spare. | The page cycle (17). Shorten the label - not the letter-spacing, which the design policy fixes at its default. |
| AGG14-201 | Low | Med-High | `web/index.html:328,334` | deferred | Links are the only interactive elements with no `--accent` focus ring, and inside `#key`'s scroll box the UA ring can be clipped the way `.results button`'s once was. | The page cycle (17). Reuse the clipping fix `.results button` already carries. |
| AGG14-202 | Low | Med-High | `web/index.html:922`; `web/app.js:3881-3913` | deferred | `#q` drives a `role="listbox"` with only `aria-controls`; the combobox pattern needs `role`, `aria-expanded` and `aria-autocomplete` together, and its proof is a screen-reader pass. | The page cycle (17). Announce the "Showing N of 1,464" footer unconditionally in the same change. |
| AGG14-208 | Low | Medium | `web/index.html:718,1113-1114` | deferred | The promised tier disclosure is appended to `#where` only, and `revealReading()` does not unfold the sheet, so on a folded phone the sentence that explains the number is hidden. | The page cycle (17), with AGG14-48, AGG14-124 and AGG14-130. |

### CL-K -- Security and privacy (9 of 9)

One visitor-facing privacy defect (AGG14-16, scheduled for cycle 17) and a set of hardening items. The XSS surface was traced end to end and found closed; the residual is escalation depth and supply chain. Nothing here is remotely reachable by a visitor except AGG14-16.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-16 | High | High | `web/app.js:4341-4368,1691,1623-1665`; `web/index.html:1149-1158` | cycle 17 | A visitor-facing privacy defect, but the fix is in the page and its proof is a browser session plus a deploy, and the deploy is blocked by the build holding `dist/`. Shipping a privacy fix that nobody has opened in a browser is the failure CLAUDE.md's deploy rule was written after. | The page-and-deploy cycle (17), first item in it. Round or omit the coordinate before it reaches `?at=`, and move the guard next to the write rather than 25,000 characters away. |
| AGG14-65 | Medium | Medium | `deploy/worldmap-security-headers.conf:24` | deferred | `www.googletagmanager.com` in `script-src` is a documented CSP allow-list bypass, and cycle 13 recorded the standing answer: it is the analytics the owner chose, so it is the owner's call, not ours. | The owner drops analytics, or pins a container id. The `blob:` redundancy can ride any other CSP edit. |
| AGG14-158 | Low | High | `sources/roads.py:73` | deferred | One `np.load` without an explicit `allow_pickle=False`, on a file under a shared NFS build tree that the running build is writing. | The lock clears. Make it explicit, as `contour/grid.py:47,100` already do. |
| AGG14-159 | Low | High | `web/app.js:28-29,606-611` | deferred | Two hardening items on a surface that was traced end to end and found closed; the `esc()` half can be tested without a deploy, the `href` half cannot be seen without one. | The test cycle (16) for the apostrophe case in `test_esc.py`; the page cycle (17) for the scheme check on credit links. |
| AGG14-160 | Low | Medium | `emit/water.py:87-88` | deferred | `extractall()` with no member or size budget into `config.CACHE`: Zip Slip is not reachable in CPython and the archive is a legitimate 1.5 GB, so the exposure is unbounded decompression only. | The lock clears and `emit/water.py` is next touched, with AGG14-67 and AGG14-119. Add a size budget then. |
| AGG14-161 | Low | Medium | `scripts/adsb_extract.py:95-120` | deferred | `urlopen` on a URL taken from a JSON body with no scheme allowlist, in an operator tool that is run by hand. | The next cycle that runs the ADS-B extract, with AGG14-29 - both are the same script trusting remote JSON. |
| AGG14-162 | Low | Medium | `tests/test_licence_firewall.py:17-22`; `scripts/check_dist.py:184-186` | deferred | A nine-token provider-name denylist structurally cannot see a record dump, and `check_dist.py` has no allowlist of publishable files; deciding what may be published is a policy question with an owner-set answer already in `deploy/README.md`. | The test cycle (16) for the vacuous assertion half (AGG14-167). The allowlist waits for a cycle whose deploy is not the one being changed. |
| AGG14-163 | Low | High | `web/vendor/maplibre-gl.js:1-3`; `pyproject.toml` | deferred | Upgrading MapLibre or bounding ten `>=` dependencies changes what the page and the build run, and neither can be verified while the build runs and the deploy is blocked. | The lock clears and a deploy can be opened in a browser. Bump MapLibre off the end-of-life line and add upper bounds in the same commit, then re-check the hand-patch. |
| AGG14-164 | Low | Medium | `sources/routes.py:326-335` | deferred | A pipe character in a community-edited `wikipedia_link` injects titles into a MediaWiki batch, and `_refuse_partial` already turns that into a loud abort rather than silent corruption. | The lock clears and the next route crawl runs (AGG14-27, AGG14-196). The filter is one line. |

### CL-L -- Architecture and boundaries (6 of 6)

Prerequisites and accelerants for the solver service rather than live defects. Every one of them edits a module the running build has imported, and none of them changes an answer the map gives today.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-102 | Medium | High | `emit/index.py:152-215`; `graph/{air:33,rail:37,ferry:126,ground:34}.py` | deferred | A calibration layer means one loader instead of four and no lazy graph imports inside `emit/index.py`; all of those modules are executing in the running build. | The lock clears. It is the natural home for AGG14-11's twelve constants and should land with them, not after. |
| AGG14-103 | Medium | High | `graph/ground.py:156`; `graph/rail.py:55`; `web/app.js:3257`; `scripts/adsb_extract.py:41`; `scripts/expand_origins.py:87-90`; `graph/build.py:82` | deferred | The six implementations agree within 15 m, so the defect is duplication rather than a wrong answer - except `expand_origins.py:90`, whose bare 6371 decides a 40 km duplicate cutoff for the roster. | The lock clears. Unify on one helper and re-run `expand_origins.py`'s dedup to see whether the roster changes; correct the `app.js` comment that claims the bare radius was eliminated. |
| AGG14-183 | Low | High | `emit/routes_json.py:15-16`; `emit/modes.py:29` vs `emit/hover.py:50` | deferred | Moving the `-9999` sentinel out of `emit/` and collapsing `MAX_MINUTES`' second copy is a boundary change for a solver service that is not resident yet. | The first cycle that makes the solver resident, or the lock clearing plus AGG14-187's `node_kind()` primitive - whichever is first. |
| AGG14-184 | Low | High | `validate.py:3-5,41,73-75,179-194`; `solve/dijkstra.py:6`; `emit/itinerary.py:63` | deferred | `validate.py` presents as a leaf while being the second-highest module in the tree, with four function-local imports and a reach into `ground._land_border_min`. | The lock clears, with AGG14-102 - one pass over the package's import graph rather than two. |
| AGG14-185 | Low | High | `sources/_utils.py:6,61-67,88` | deferred | `atomic_write` and `params_hash` are re-exported under private names to seven modules, so the repository's most important invariant reads as private-to-that-module. | The lock clears. A mechanical rename across `sources/`, with the two aliases put back together. |
| AGG14-187 | Low | High | `emit/modes.py:32-…`; `emit/itinerary.py:36-45` | deferred | Adding a `node_kind()` primitive touches both emit loops the build is running, and it changes the four call sites that currently re-derive the node layout. | The lock clears. It is the prerequisite for AGG14-111 and for a solver that can answer an itinerary rather than only a number. |

### CL-M -- Documentation drift (39 of 39)

Thirty-nine rows, thirteen of which are the `DOC10-M*` batch deferred behind a single unscheduled task -- and that task is AGG14-49, which this cycle closes. The batch's own evidence line has since gone stale (AGG14-222), so the sweep that moves it has to re-check the premise rather than re-defer it. Two sub-groups should each be one pass: the res-5 figures (AGG14-136, 137, 138, 139, 142, 218) and the `plan/` hygiene rows (AGG14-145, 146, 147, 148, 219, 220, 221, 222).

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-50 | High | High | `docs/superpowers/specs/…design.md:9-11` | cycle 18 | The "As built" table misses five superseded claims, the largest being "leave now" semantics - and "leave now" is itself contested by AGG14-69, so the table cannot be completed until that question has an answer. | The documentation cycle (18), after AGG14-69 is settled. The spec is the document the design claims are read from, so it goes early in that cycle. |
| AGG14-51 | High | High | `sources/countries.py:32-34` vs `:48-49` | cycle 18 | A docstring naming India-Pakistan and Russia-Ukraine as excluded sits fourteen lines above the set that contains them. Comment-only, but `sources/countries.py` is imported by the running build and this cycle's diff is the rail parse. | The documentation cycle (18) - or any earlier commit that touches `sources/countries.py`, since the change is comment-only. |
| AGG14-52 | High | High | `emit/borders.py:5-16` vs `:31-46` | cycle 18 | Every figure in `emit/borders.py`'s module docstring describes the configuration the file explicitly rejected, so it needs re-measuring against the shipped borders rather than editing. | The documentation cycle (18). Re-measure the vertex count and both gzip figures from the deployed `borders.json`, then restate the 29 px arithmetic from the tolerance the file actually uses. |
| AGG14-131 | Medium | High | `web/index.html:1109-1110` | deferred | "The mode of the last leg" is really six modes over the whole journey; one sentence in `web/index.html`, whose only proof is a deploy. | The documentation cycle (18), with AGG14-190 - the same breakdown, described wrongly in two places. |
| AGG14-134 | Medium | High | `web/README.md:62`; `tests/web/test_vendor.py:37,90` | deferred | "Every file in `vendor/` appears above" is false for the seven files in `vendor/licences/`, and the enumeration and the test that pins it (AGG14-180) are one job. | The test cycle (16) for the enumeration; the README sentence lands with it. |
| AGG14-135 | Medium | High | `README.md:92-93`; `graph/ground.py:21-23`; `calibrate/ground.py:119` | deferred | The README describes a support guard dropping the roadless fit when it is the `recip > 0` sign filter; restating it means restating the fit, which AGG14-11 is moving into `calibration.toml`. | AGG14-11 lands in cycle 15; correct the README in the same commit so the sentence and the constant move together. |
| AGG14-136 | Medium | High | `validate.py:174`; `cli.py:334,434,455,466`; `contour/bands.py:28`; `emit/hover.py:156`; `emit/index.py:113,332` | deferred | "553 origins" in nine comments against a 1,464-row roster, in files the running build is executing; every "x553" cost statement understates by 2.65x. | The lock clears. One sweep with AGG14-137, AGG14-138, AGG14-139, AGG14-142 and AGG14-218 - all of them res-5 or 553-era figures. |
| AGG14-137 | Medium | High | `graph/ground.py:28-31` | deferred | "8.0 per cell" is 5.97 over 13.75 M, and as written the figure would overflow the `EDGE_SLOTS_PER_CELL = 8` cap the sentence exists to justify. | The res-5 sweep with AGG14-136; re-derive from the current universe before restating the cap's rationale. |
| AGG14-138 | Medium | High | `validate.py:34-39` | deferred | `check_coverage`'s Antarctica arithmetic is res-5; at res 6 it is ~365,000 cells and the two points of headroom the sentence claims do not exist. | The res-5 sweep with AGG14-136, and with AGG14-56, which decides what the gate counts as covered. |
| AGG14-139 | Medium | High | `validate.py:175-177`; `cli.py:433-434` vs `sources/roads.py:115-119` | deferred | "~4.8 s per origin" is a res-5 figure that two files repeat while a third already carries the 7.5x correction. | The res-5 sweep with AGG14-136; take the corrected figure from `sources/roads.py`, and with AGG14-60, which removes the cost entirely. |
| AGG14-140 | Medium | High | `emit/index.py:112-115,331-333` | deferred | "Four origin names appear twice"; the 1,464-row roster has thirteen, and the sentence governs a disambiguation the page performs. | The res-5 sweep with AGG14-136 - the same roster-size correction, in two files. |
| AGG14-141 | Medium | High | `graph/build.py:31-33` vs `graph/nodes.py:33-34,178` | deferred | "124 of 68,152 pairs, all downstream of the 25 dropped airports" is pre-res-6 and is contradicted by its own sibling comment. | The res-5 sweep with AGG14-136; re-count against the current index. |
| AGG14-142 | Medium | High | `validate.py:57-60` | deferred | "3.6 million vertices" is res-5 arithmetic; the native LOD now sweeps ~82.5 M, so the tradeoff being justified is ~23x larger than stated. | The res-5 sweep with AGG14-136. Cycle 13 raised this as DOC13-14 and it is still open. |
| AGG14-143 | Medium | High | `web/app.js:2080-2085` | deferred | The reading tier is described as dormant "until the next full build advertises readingRes"; it has been armed since 2026-09-12. Cycle 13 raised it as DOC13-7. | The documentation cycle (18), or the next `web/app.js` commit - it is one comment. |
| AGG14-144 | Medium | High | `tests/test_licence_firewall.py:25`; `scripts/check_dist.py:79` | deferred | Two files cite CLAUDE.md for a sentence it does not contain, which is a fabricated citation to the one document this repository treats as binding. | The documentation cycle (18). Rewrite both citations to name the real source. Do **not** add the sentence to CLAUDE.md to make the citation true - that file is the owner's. |
| AGG14-145 | Medium | High | `plan/README.md:41,43,51` | deferred | Three understated ID ranges make `plan/README.md`'s "nothing was dropped" audit lie in the safe-looking direction - but the orchestrator forbids modifying existing plan files this cycle. | The next `plan/README.md` edit, which is also when this cycle's two documents are indexed. Re-count each range from the plan file rather than from the previous README line. |
| AGG14-146 | Medium | High | `plan/deferred.md:670` | deferred | C12-10's exit criterion fired and the row was never swept, while its two siblings were correctly re-raised as V13-20/V13-21. | The next `plan/deferred.md` sweep. AGG14-145 to AGG14-148 and AGG14-219 to AGG14-222 are that sweep, and it is one job. |
| AGG14-147 | Medium | High | `plan/deferred.md:497` vs `deploy/worldmap-security-headers.conf:23`, `deploy/README.md:79-89` | deferred | AB35 is open on a dead premise: the snippet now names all four analytics hosts and has been installed since 2026-09-13. | The next ledger sweep - close the row rather than re-defer it. |
| AGG14-148 | Medium | High | `plan/deferred.md:96` | deferred | E1's data half describes a 157-origin res-5 served build, so a reader cannot tell whether the row is live or stale. | The next ledger sweep; restate the data half at the current build or split the row. |
| AGG14-203 | Low | High | `web/index.html:38` | deferred | The JSON-LD tells crawlers that airports, rail stations and ferry crossings are listed in `index.json`; none of the three is. | The documentation cycle (18). It ships to crawlers, so it goes early in that cycle. |
| AGG14-204 | Low | High | `web/index.html:1112-1114` | deferred | The coarse-reading fallback is presented as a closed list of two causes; there are four, and `app.js` already names three of them. | The documentation cycle (18). |
| AGG14-205 | Low | High | `web/llms.txt:53` | deferred | One binary size amid five decimal figures in the same paragraph; cycle 13 raised it as V13-43 and it is still open. | The documentation cycle (18). |
| AGG14-206 | Low | High | `web/index.html:53` | deferred | A hand-written `dateModified` two days behind `builtAt`, while the visible build date beside it is derived correctly. | The documentation cycle (18). Derive it from the build or delete the field. |
| AGG14-207 | Low | High | `web/index.html:933` | deferred | The static city-list caption omits "door to door" - the one place the file's copy disagrees with the CLAUDE.md rule its own comment cites. | The documentation cycle (18), early: CLAUDE.md's modelling rule names exactly this surface. |
| AGG14-209 | Low | High | `web/index.html:1043-1084` | deferred | "What this does not know" mentions neither the >=90 % coverage gate nor the legend's "no scheduled route" grey, both of which the page shows figures for. | The documentation cycle (18), with AGG14-56, which decides what "covered" means before the sentence can be written. |
| AGG14-210 | Low | Medium | `web/README.md:70-73` vs `scripts/deploy_verify.sh:83-84` | deferred | The README enumerates eight copied files while the deploy mirrors all of `web/` minus an exclude list: accurate today, silently stale on the first addition. | The documentation cycle (18). Describe the rule, not the list. |
| AGG14-211 | Low | Medium | `docs/…design.md:117-128` | deferred | The spec's licensing table omits Natural Earth, GeoNames, HydroLAKES and adsb.lol, all of which ship - and the redistribution rule hangs off that table. | The documentation cycle (18), first among the documentation items, because it is the licence surface. |
| AGG14-212 | Low | High | `cli.py:677-678` vs `:527-553` | deferred | "The four fields"; `_CURRENT_INDEX_CONSTANTS` holds nine. Cycle 13 raised it as DOC13-55. | The documentation cycle (18), or the next `cli.py` commit - derive the count rather than typing it. |
| AGG14-213 | Low | High | `cli.py:78` vs `:90` | deferred | "Bounded by RAM, not by cores", followed by `min(cores - 2, 8, n_origins)`, which the core term binds on a <=10-core machine. | AGG14-155 changes the cap; correct the comment in that commit so the sentence and the arithmetic move together. |
| AGG14-214 | Low | High | `config.py:55` vs `:60`, `graph/ferry.py:15`, `calibration.toml:154` | deferred | The band ratio is quoted as "about 1.155" where its own edges give 1.1526, as two other files already say. | The documentation cycle (18). |
| AGG14-215 | Low | High | `emit/tiles.py:16-21` | deferred | "z7 measured ~38 % larger than z6" is contradicted by the same comment's own figures three lines up. Cycle 13 raised it as DOC13-70. | The documentation cycle (18). |
| AGG14-216 | Low | High | `calibration.toml:293-294` vs `graph/build.py:215-259,354` | deferred | `[land_border]` says the charge is on the ground edge; `_border_rules` applies it to every surface edge, rail and ferry included. | The documentation cycle (18) - or AGG14-11's calibration pass in cycle 15, which rewrites that block anyway. |
| AGG14-217 | Low | High | `sources/_utils.py:72-73`; `sources/wikidata.py:199-201` | deferred | Both docstrings still describe `routes.parquet` as the cache returned forever after; it is now the warned legacy fallback. | AGG14-27 lands in cycle 15 and makes the sentence true or false for good; correct both docstrings there. |
| AGG14-218 | Low | Medium | `sources/landmask.py:155` | deferred | "42,704 cells, 0 failures" for the Antarctic wedges matches neither res 5 nor res 6. | The res-5 sweep with AGG14-136; re-measure rather than re-typing a remembered figure. |
| AGG14-219 | Low | High | `plan/deferred.md:1-3` | deferred | `deferred.md`'s scope line says "cycle-1 and cycle-2" in a file carrying headings through cycle 12 plus "Closed in cycle 13". | The next ledger sweep, with AGG14-146. |
| AGG14-220 | Low | High | `plan/deferred.md:44,100,326,436,437,497,524` | deferred | Seven stale citations, including `graph/rail.py:113` in a 107-line file - named by AB41 as its own example and still uncorrected. | The next ledger sweep. Apply AB41's own convention to the replacements: cite the commit and name the identifier, not only the line. |
| AGG14-221 | Low | High | `plan/deferred.md:103` | deferred | One row's finding text occupies the ID column - the only five-cell row in a file of 212 six-cell and 40 seven-cell rows, so any mechanical audit of the ledger miscounts. | The next ledger sweep; fix it before the next audit, not after. |
| AGG14-222 | Low | High | `plan/deferred.md:595` | deferred | DOC10-M*'s "what held up" line still cites 553 origins, so a thirteen-row batch is being re-deferred on a premise nobody re-checked - and AGG14-49, the row the batch waits on, closes this cycle. | The next ledger sweep, immediately after the rail-service work lands AGG14-49. The batch then moves or gets a new, current reason. |
| AGG14-223 | Low | Medium | `CLAUDE.md:22-24` vs `scripts/check_ramps.py:39-56` | will not do | CLAUDE.md's "~7 per step is the ceiling" is contradicted by `scripts/check_ramps.py`, which four of twelve schemes exceed - but CLAUDE.md is the owner's standing design policy and this run treats it as binding input, not working material. The same disposition `plan/deferred.md` records for DOC5-8's remaining half. Recorded, not actioned. | The owner revises CLAUDE.md. Nothing in `web/` or `scripts/` changes on our initiative. |

### CL-N -- Payload weight and page delivery (2 of 2)

5.33 MB per city switch is the whole mobile story; everything else on the page's critical path adds up to 703 KB. Both rows need either the deploy host or a re-emit under `dist/`.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-61 | Medium | High | `deploy/worldmap.atik.kr.conf:66-72`; `emit/hover.py:239-251` | deferred | `gzip_static` or brotli for the 10 MB reading tier is an nginx change on the deploy host, which the orchestrator has not sanctioned and which cannot be verified without a deploy. | The first cycle whose deploy is not `--page-only`. Pre-compress at build time so nginx serves a static artifact rather than re-compressing 5.33 MB per city switch. |
| AGG14-62 | Medium | Medium | `emit/routes_json.py:19-62` | deferred | Making `{slug}.json` columnar like `rail_detail` changes 293 MB of `dist/` and the page's parser together. | The lock clears and a re-emit is scheduled: emitter and parser in one commit, with AGG14-157's `json.loads` cost re-measured afterwards. |

### CL-O -- Carried notes (1 of 1)

Six items code-reviewer explicitly filed as notes rather than findings, carried so none is lost on the next pass.

| ID | sev | conf | file:line | disposition | why not this cycle | exit criterion |
|---|---|---|---|---|---|---|
| AGG14-154 | Low | High/Med | see below | deferred | Six items code-reviewer filed as notes rather than findings. They span five modules, four of which the running build is executing, and one (`wire.parse_query`'s vacuous `MAX_QUERY_CHARS`) belongs to a solver service that is not resident. | Each rides the next commit that touches its module; carry this row until all six are named individually. `cli._build_all_locked` accepting a negative `--limit` and reading it as "all but the last N" while still setting `partial` goes first. |

---

## The index -- all 223 findings

Deduped from 255 raw findings across the eleven lanes. This table is the durable
record: `.context/reviews/` is not committed, so a finding that is not here is
lost. Severity and confidence are the aggregate's, unchanged. Disposition is
this document's.

| ID | sev | conf | file:line | finding | disposition |
|---|---|---|---|---|---|
| AGG14-1 | Critical | High | `contour/bands.py:65-67,106-107` | `_crosses_antimeridian` runs twice per cell per band per LOD — ~83 s/origin, ~6.8 h of wall clock, for a build-constant answer | scheduled-cycle-15 |
| AGG14-2 | Critical | High | `contour/bands.py:164-182,290-333`; `validate.py:108-109`; `emit/tiles.py:79-83`; `emit/modes.py:52` | The whole band FeatureCollection is materialised as Python dicts then round-tripped back to shapely — multi-GB per worker, the mechanism behind both build deaths (absorbs debugger D3) | scheduled-cycle-15 |
| AGG14-3 | Critical | High | `emit/hover.py:98-128,139-142`; `emit/{itinerary:58,66,modes:91,97,rail_detail:86,94}.py` | The res-4 parent list and a duplicate of `NodeIndex._cell_pos` are rebuilt 4× per origin over 10.2 M cells — ~38 s and ~600 MB transient each (absorbs code-reviewer C2) | scheduled-cycle-15 |
| AGG14-4 | Critical | High | `sources/osm.py:42-44`; `graph/rail.py:100`; `calibration.toml:125-136` | The high-speed flag is a single OSM relation tag with 3.2 % coverage and 0 % in Japan/India/N. America/Russia; Tohoku Shinkansen is charged 10.4 h against 3.8 h real, and none of it is disclosed | scheduled-this-cycle (C14-1) |
| AGG14-5 | Critical | High | `tests/sources/test_cache_provenance.py:186-232` | The `STAMPED` cache-provenance table covers 27 of 35 hashed terms; `RAIL_PARSER_VERSION`, `SCHEMA`, `FERRY_SCHEMA`, `_CARGO_RE` and four more can be dropped from a cache key with the suite green (absorbs verifier V2) | scheduled-this-cycle (C14-2) |
| AGG14-6 | Critical | High | `tests/sources/test_airports.py:1-31` | Every test in the file reads a warm `data/build/` parquet, so `scheduled_airports`'s filter/dedup/sort never runs; the stamp carries no `PARSER_VERSION`, and on a cold tree the tests do a live HTTP fetch with no `network` marker | scheduled-cycle-16 |
| AGG14-7 | Critical | High | `tests/graph/test_ferry.py:245-257` | The ferry immigration-zone test passes with the entire zone-crossing branch deleted (verified: 137 min sailing vs a 45 min threshold) | scheduled-cycle-16 |
| AGG14-8 | Critical | High | `tests/graph/test_build.py` (whole file) | `build._air_edges`, `_access_edges` and `_transfer_edges` are never called directly by any test — the largest unguarded surface, where door-to-door time is assembled | scheduled-cycle-16 |
| AGG14-9 | Critical | High | `tests/emit/test_itinerary.py:52-71` | The fixture makes every airport unreachable, so `write_itinerary`'s ordinal arithmetic (`node - first_arrival`) is executed by no test in the repo | scheduled-cycle-16 |
| AGG14-10 | High | High | `cli.py:300-320` | A per-origin artifact is seven files with no transaction; `dist/` held three half-written origins during the review (732/731/729), and the one missing only `.rail.*` passes `_reindex` (absorbs code-reviewer C4's rollback note) | scheduled-cycle-15 |
| AGG14-11 | High | High | `graph/ground.py:17-25`; `sources/urban.py:28-33`; `graph/ferry.py:53,109,114`; `graph/build.py:29`; `tests/test_calibration_provenance.py:20-28`; `README.md:95` | Twelve model constants — including the two largest FITTED sets, which price every ground edge on Earth — live in code, `calibration.toml` never names them, the provenance gate only reads the toml, and `inputsHash` does not cover them (absorbs critic C2, critic C8, DOC14-16) | scheduled-cycle-15 |
| AGG14-12 | High | High | `calibration.toml:126-133` vs `graph/rail.py:98-101` | The `[rail]` anchor is derived from an endpoint great-circle the code never uses; the stated error has the wrong sign, and the same mistake shows `detour_factor` double-counts curvature by 10–20 % on 11+-stop routes | scheduled-cycle-15 |
| AGG14-13 | High | High | `graph/build.py:263-275`; `graph/nodes.py:1-19` | Stations have no arrival/departure split, so changing trains costs exactly zero minutes (air charges ≥35 min for the same act), and no test asserts anything about it | scheduled-cycle-15 |
| AGG14-14 | High | High | `sources/osm.py:1-11,86-94`; `graph/rail.py:92-104` | OSM relation member order is taken as authoritative with no length bound, drop counter or gate: 999 "consecutive" hops exceed 200 km (max 1,604 km), and each is a strict shortcut Dijkstra always takes | scheduled-cycle-15 |
| AGG14-15 | High | High | `emit/rail_detail.py:56-57` → `web/app.js:2421-2429,2499` | `setdefault` fills both directed keys with one directional name: 55,500 of 111,051 arrow-named pairs (50.0 %) caption the service running the opposite way; 3,834 shipped rows name the line's own origin terminus | scheduled-this-cycle (C14-5) |
| AGG14-16 | High | High | `web/app.js:4341-4368,1691,1623-1665`; `web/index.html:1149-1158` | "Show my location" lets the camera sync write the visitor's position to 5 dp into `?at=` and thence the clipboard and the analytics page location, contradicting the page's own privacy statement; the only guard is a 2,000-char window 25,000 chars away | scheduled-cycle-17 |
| AGG14-17 | High | High | `cli.py:249-256`; `emit/index.py:97-125,330-337` | `_preflight_origins` catches only `ValueError`, so a malformed `origins.toml` row escapes as a bare `KeyError`/`TypeError` naming no slug — or, for a missing `name`, only at `write_index` after the full solve (absorbs code-reviewer's `load_origins` note) | scheduled-cycle-15 |
| AGG14-18 | High | High | `solve/dijkstra.py:35-45`; `graph/nodes.py:89-95`; `scripts/expand_origins.py:113,134` | h3 normalises rather than raising, so a swapped or out-of-range origin coordinate that lands on land is solved and published with every gate green | scheduled-cycle-15 |
| AGG14-19 | High | High | `cli.py:720-739` | `_consume` detects a worker that dies, never one that hangs — the repo's own recorded three-hour deadlock keeps its pid and is undetectable | scheduled-cycle-15 |
| AGG14-20 | High | High | `validate.py:186-193`; `emit/modes.py:48-51` | Two fork-only functions have lazy fallbacks into polars/pyogrio and rasterio, whose thread pools do not survive a fork; the only defence is that today's caller passes the kwarg | scheduled-cycle-15 |
| AGG14-21 | High | High | `cli.py:112-138`; `_io.py:23-31` | `dist/.build.lock` records a bare pid on a shared NFS mount, so another machine judges staleness against its own process table and is told to delete a live build's lock | scheduled-cycle-15 |
| AGG14-22 | High | High | `tests/web/test_module_scope_order.py:42`; `web/app.js:69,119,747` | The guard's `_AWAIT` regex resolves to app.js:747; the module's first suspension is line 69, so every binding declared in between is wrongly treated as safe | scheduled-cycle-16 |
| AGG14-23 | High | High | `web/app.js:4256-4262`; `web/boot.js:69-79,131-138`; `web/index.html:161` | `appReady` is set 108 lines before the module ends, blinding boot.js's watchdog; and boot.js's capturing `error` listener has no time bound, so a late throw deletes the side rail from a page that is drawing perfectly | scheduled-cycle-17 |
| AGG14-24 | High | High | `scripts/browser_verify.sh:106,203-221,228-462,430,599` | The deploy's browser gate samples `body.fatal` ten seconds before the watchdog can fire, never reads `agent-browser errors`, never polls `appReady`, carries ~20 fixed sleeps against growing data, has three assertions satisfiable by an empty page, and has no `trap` (absorbs test-eng WEB-05) | scheduled-cycle-17 |
| AGG14-25 | High | High | `web/app.js:865,1504,3417-3435` | `borders.json`, `places.json` and `airports.json` all fail into empty `catch`es; a failed `airports.json` paints zero route features beside a complete itinerary with nothing said anywhere | scheduled-cycle-17 |
| AGG14-26 | High | High | `graph/ground.py:99-169` | `ground.hex_edges` builds ~8–10 GB of numpy temporaries in the build's parent process — two simultaneous 1.31 GB centroid gathers plus four 656 MB arrays inside `haversine_km` | scheduled-cycle-15 |
| AGG14-27 | High | High | `sources/routes.py:267-280` vs `:309-319` | `route_network()` returns the legacy `routes.parquet` *above* both integrity gates (20,000-pair floor, sanity pairs) — and that is the live path today, since no `routes_<hash>.parquet` exists | scheduled-cycle-15 |
| AGG14-28 | High | High | `sources/osm.py:336-345` | `ferry_links` has no emptiness guard (its rail sibling does), so a filter change writes and permanently caches a zero-row parquet as success and every ferry crossing silently disappears | scheduled-cycle-15 |
| AGG14-29 | High | High | `scripts/adsb_extract.py:55,182-196` | `doc.get("trace") or []` means an upstream key rename yields `unreadable == 0`, the >50 % refusal cannot fire, and the script reports success on an empty calibration input | scheduled-cycle-15 |
| AGG14-30 | High | High | `emit/itinerary.py:21-46`; `emit/modes.py:32-80`; `emit/rail_detail.py:24-41` | Three independent `argsort`s and three pure-Python tree walks over 10.2 M nodes per origin (~37 s), plus a 493 MB float64 accumulator that only ever becomes uint16 | scheduled-cycle-15 |
| AGG14-31 | High | High | `validate.py:43-47` | `check_coverage` makes 10.2 M `h3.cell_to_latlng` calls per origin to rebuild a build-constant "north of 60°S" mask the frontend already memoises | scheduled-cycle-15 |
| AGG14-32 | High | High | `sources/wikidata.py:64-102`; `tests/sources/test_wikidata.py`; `tests/sources/test_routes.py:67-113` | The Wikidata title→QID resolver is executed only by three `@pytest.mark.network` tests the default gate deselects; every offline test stubs `_resolve_batch` wholesale, so the normalize/redirect collapse that once lost ICN→NRT is unguarded (absorbs verifier V5) | scheduled-cycle-16 |
| AGG14-33 | High | High | `tests/graph/test_rail_integration.py:28-44` | `_rail_edges`'s two border rules are reached only by a Paris/Nevers/Lyon fixture — one country, one zone — so deleting both the closed-border `continue` and the zone charge leaves every rail test green | scheduled-cycle-16 |
| AGG14-34 | High | High | `tests/graph/test_air.py:16-20` | `block_time_min(8880,…) == approx(750, abs=80)` sits 2 min above its floor, so a sub-1 % refit of the fitted `cruise_kmh` fails on correct code while an 11 % error escapes upward | scheduled-cycle-16 |
| AGG14-35 | High | High | `graph/nodes.py:249-264` | No caller of `nodes.build_index()` passes `rail_routes`, so the station-indexing branch and its dropped-station counter never execute; `base = len(cells) + 2*len(codes)` can be halved with the suite green | scheduled-cycle-16 |
| AGG14-36 | High | High | `tests/graph/test_rail_integration.py:47-70` | Swapping `boarding_min` and `alighting_min` is undetectable: every test sums one of each along a path, so the total is symmetric under the swap | scheduled-cycle-16 |
| AGG14-37 | High | High | `tests/graph/test_rail.py:40-46,70-74` | The only rail-vs-timetable test has a 70-minute window admitting `detour_factor` 0.77–1.36, and its sibling asserts a ratio algebraically forced by `np.where` (absorbs critic C9) | scheduled-cycle-16 |
| AGG14-38 | High | High | `tests/emit/test_rail_detail.py:57-77` | The only assertion is `st_size == 2*len(parents)`; `.rail.json` is written and never opened, so wrong endianness, a constant ordinal, or a swapped `[station, line]` column order all pass | scheduled-cycle-16 |
| AGG14-39 | High | High | `tests/emit/test_modes.py:84-92` | Size-only assertion on `write_modes`: reversing the channel order *and* writing big-endian still satisfies it (verified) | scheduled-cycle-16 |
| AGG14-40 | High | High | `tests/emit/test_routes_json.py:22-34` | No test asserts a non-sentinel `prev`, so `"prev": None` unconditionally — which breaks every route breakdown on the page — leaves all four tests green | scheduled-cycle-16 |
| AGG14-41 | High | High | `tests/emit/test_build_identity.py:68-79` | The build-identity completeness guard builds `called` by iterating `STAMPED`, so `called ⊆ STAMPED` always and the direction its docstring claims to check is unreachable (absorbs verifier V1) | scheduled-cycle-16 |
| AGG14-42 | High | High | `tests/emit/test_build_identity.py:20-29`; `tests/emit/test_index.py:171-210` | `_git_head` is monkeypatched to a constant and `STAMPED` holds only `config.*`, so deleting `_git_head()` from `params_hash` stays green and two commits share a `buildId` | scheduled-cycle-16 |
| AGG14-43 | High | High | `emit/airports_json.py:22-26`; `tests/web/test_app_constants.py:52-90` | `FIELDS` is pinned against the page's reads but nothing pins `build()`'s positional `zip` against `FIELDS`, so swapping name/country or transposing lat/lon ships green | scheduled-cycle-16 |
| AGG14-44 | High | High | `tests/web/test_etops_is_not_a_control.py:54-69` | The ETOPS premise guard's entire signal is "grep printed nothing" and grep's exit status is never checked, so a moved `src/` or a typo in the pattern disarms it permanently and silently | scheduled-cycle-16 |
| AGG14-45 | High | High | `tests/web/test_reading_tier_refresh.py:36-64` | Three defects in one file: dead code at :40-42, a slice that starts at the marker instead of walking back (so a harmless reorder turns it **red on correct code**), and no comment stripping — fully redundant with its sibling | scheduled-cycle-16 |
| AGG14-46 | High | High | `tests/web/test_design_policy.py:63-70,95-131` | The design-policy gate reads only `<style>` blocks and `app.js`, never an inline `style=` attribute; adding letter-spacing, uppercase and tabular figures to `#origin-name` survives all four bans (mutation-verified) | scheduled-cycle-16 |
| AGG14-47 | High | High | `web/index.html:466-472,478-487` | The twelve colour-scheme and six ocean radios were left out of the `--line-ctl` control-boundary fix: borders measure 1.30:1 and the selected ring 1.57:1 against SC 1.4.11's 3:1 | scheduled-cycle-17 |
| AGG14-48 | High | High | `web/index.html:718-719,828,836` | The folded phone sheet keeps `#time` but hides `#snapped` and `#tiletrouble` — a large figure attributed to a city the reader did not choose, with the correction suppressed | scheduled-cycle-17 |
| AGG14-49 | High | High | `web/llms.txt:29-30`; `emit/index.py:166-169`; `graph/build.py:273-274` | Every rail journey pays 20 minutes (`boarding_min` + `alighting_min`) while every user-facing surface says 15, and the same sentence claims "along the track" for a straight-line chord × 1.2 (absorbs critic C4) | scheduled-this-cycle (C14-7) |
| AGG14-50 | High | High | `docs/superpowers/specs/…design.md:9-11` | The design spec's "As built" table promises to list every superseded claim and misses five, including the document's single largest divergence — "leave now" semantics | scheduled-cycle-18 |
| AGG14-51 | High | High | `sources/countries.py:32-34` vs `:48-49` | The docstring names India–Pakistan and Russia–Ukraine as deliberately *excluded* from `CLOSED_BORDERS`; both are in the set fourteen lines below | scheduled-cycle-18 |
| AGG14-52 | High | High | `emit/borders.py:5-16` vs `:31-46` | The whole module docstring — vertex count, both gzip figures, the "213-242 KB saving", the "29 px" arithmetic — describes the 1.1 km / 4 dp configuration the file explicitly rejected | scheduled-cycle-18 |
| AGG14-53 | Medium | High | `emit/hover.py:131-135`; `emit/modes.py:100`; `emit/routes_json.py:33`; `web/app.js:2621-2665` | `.astype("<u2")` truncates while `routes_json` rounds, so at every band edge the printed minute, the painted band and the legend mark disagree, and leg rows can exceed the door-to-door total (absorbs tracer T9) | deferred |
| AGG14-54 | Medium | High | `web/app.js:4308-4311` vs `:1643-1645,3094-3111` | The `?to=` restore sets `geocoded: Boolean(requestedPin.label)` — backwards — so a shared `?label=` is stripped from the address bar in the same tick, and a gazetteer label is added instead | deferred |
| AGG14-55 | Medium | High | `cli.py:464,468` vs `:417,513` | `hover_cells.bin` and `reading_parents.bin` are rewritten before the first origin is solved and unconditionally, including under `--limit`/`--only`, so a smoke test re-indexes 552 origins' arrays against a new cell ordering | deferred |
| AGG14-56 | Medium | High | `validate.py:31-54` vs `emit/hover.py:50` | The coverage gate's predicate is `np.isfinite`, but the emitters ship the `UNREACHABLE` sentinel above 65,534 minutes — a 70,000-minute cell counts as covered and renders as "no scheduled route" | deferred |
| AGG14-57 | Medium | High | `scripts/deploy_verify.sh:67-84,169-199` | The live deploy probe omits `{slug}.json`, `reading_parents.bin` and `.r6.bin`, asserts status only, probes a single origin of 1,464, falls back to `seoul` when index.json is unreadable, and is TOCTOU against the build lock (absorbs debugger C6) | deferred |
| AGG14-58 | Medium | High | `emit/rail_detail.py:52-57` vs `graph/rail.py:103-107` | The caption picks a line by lowest OSM route id while the edge is priced by `min(minutes)`: 30,742 of 147,332 directed pairs (20.9 %) are captioned with a different service, 370 of them in a different speed class (absorbs tracer T2) | scheduled-this-cycle (C14-6) |
| AGG14-59 | Medium | High | `contour/bands.py:254-262` | `_coarse_features` rebuilds a 4.5 M-element `dtype=object` parent array and `np.unique`s it per origin — a Python-level sort costing 7–11 s for an origin-independent mapping | deferred |
| AGG14-60 | Medium | High | `sources/roads.py:99-140` | `roads.cell_class` is uncached and runs a ~36 s, 4.09 M-cell footprint pass four times per build, while its sibling `road_class_grid()` and `urban_mask` are both cached | deferred |
| AGG14-61 | Medium | High | `deploy/worldmap.atik.kr.conf:66-72`; `emit/hover.py:239-251` | The 10 MB reading tier is gzipped on the fly at nginx's default level 1 with no `gzip_static` or brotli — 5.33 MB per city switch, re-compressed on every uncached request | deferred |
| AGG14-62 | Medium | Medium | `emit/routes_json.py:19-62` | `{slug}.json` ships ~8,000 airport nodes as verbose per-object JSON (529 KB raw × 553 = 293 MB of `dist/`) where `rail_detail` already uses a columnar shape | deferred |
| AGG14-63 | Medium | Medium | `contour/bands.py:233` | `np.array(idx.cells, dtype=object)` and the other full Python iterations touch every h3 string's refcount, so each worker privately copies ~653 MB inside its first origin instead of sharing it copy-on-write | deferred |
| AGG14-64 | Medium | High | `scripts/deploy_verify.sh:201-206` | The CSP check prints `ABSENT` and exits 0 — it never sets `live_fail`, and it sits below the gate that reads it | deferred |
| AGG14-65 | Medium | Medium | `deploy/worldmap-security-headers.conf:24` | `script-src` allows the whole of `www.googletagmanager.com` (a documented CSP bypass, since it serves `gtm.js` for any container id), giving back most of what hashing the inline bootstrap bought; `blob:` there is probably redundant with `worker-src` | deferred |
| AGG14-66 | Medium | High | `tests/web/test_csp.py:20-35` | The only guard on the only copy of the policy asserts two properties of it: nothing pins `default-src`, `object-src`, `base-uri`, `form-action`, `frame-ancestors`, the absence of `unsafe-eval`, or the external-host list | deferred |
| AGG14-67 | Medium | Medium | `scripts/check_dist.py:72-73,117-133,380-404,455-468` | The deployed `water.pmtiles` carries the build host's home directory in its metadata blob, fetchable with one ranged GET, and the gate that detects it appends to `warn`, not `bad` | deferred |
| AGG14-68 | Medium | High | `sources/{landmask,airports,roads,countries,urban}.py`; `emit/{places,water,borders}.py`; `scripts/expand_origins.py` | No downloaded dataset has a checksum, and every derived-cache stamp keys the **URL** rather than the bytes, so a replaced or poisoned upstream file is adopted once and then read from cache forever (absorbs debugger E11) | deferred |
| AGG14-69 | Medium | High | `graph/headway.py:21-32` | The module docstring asserts one "leave now" semantics for a function used under three: air pays no wait on the first leg, ferry pays the full expected wait, rail pays none at all — a 3.5-day gap on identical service frequencies | deferred |
| AGG14-70 | Medium | High | `graph/build.py:182-207` vs `web/index.html:1021-1023`, `web/llms.txt:23-25` | The page promises "the expected wait for the next departure"; the code uses the unweighted median expected wait across all of that airport's outbound routes, capped at 100 min | deferred |
| AGG14-71 | Medium | Medium | `graph/build.py:338-348`; `graph/ground.py:80-142` | A ferry is dropped because a ground edge "duplicates" it, but `ground_adjacent` tests H3 adjacency only and `hex_edges` invents a road between any two adjacent land cells — the strait may have no crossing at all | deferred |
| AGG14-72 | Medium | High | `sources/osm.py:303-305,317-319` | `sorted(SCHEMA)` stamps the column *names* only; changing `pl.Int64`→`pl.Int32` or `pl.Boolean`→`pl.Utf8` leaves the cache path identical | deferred |
| AGG14-73 | Medium | High | `scripts/check_dist.py:393-397`; `tests/web/test_check_dist.py:57-59` | The `REQUIRED_EXTRAS` refusal — the half of CLAUDE.md's deploy rule that names `water.pmtiles` — has no test; the fixture writes all four every time and no test ever removes one | deferred |
| AGG14-74 | Medium | High | `tests/web/test_design_policy.py:144,169` | The near-black-ground and Plex-font checks read `_declarations(...)[0]`, but CSS honours the *last* declaration: appending a light-sepia `:root` block leaves both green while the page renders at luminance 0.85 | deferred |
| AGG14-75 | Medium | High | `tests/web/test_design_policy.py:72-86` | The design-policy `script` fixture reads `web/app.js` only; `web/boot.js` is a shipped, CSP-hashed page script that does real DOM work and is excluded by omission (absorbs designer D2) | deferred |
| AGG14-76 | Medium | High | `scripts/check_dist.py:369,372-382,451`; `emit/index.py:263-265` | No per-origin artifact carries a build identity: the `offsets` pair is the only cross-build fingerprint, it is blind to anything that changes times without changing counts, `buildId` is decorative, and `{slug}.pmtiles` has no fingerprint at all (absorbs test-eng WEB-04, debugger C4) | deferred |
| AGG14-77 | Medium | High | `tests/contour/test_bands.py:127-137` | The one real-solve cover-gate test calls itself "the gate the build runs" but is deselected by default *and* is not marked `integration`, so it would run against a scratch cache rather than the build's own (absorbs test-eng EMIT-17) | deferred |
| AGG14-78 | Medium | High | `tests/test_golden.py:33-52` | The suite's only end-to-end door-to-door assertion still carries its Phase-A tolerances (Seoul→Tokyo admitted anywhere in 2–12 h), unchanged since the first commit through rail, ferries and several calibrations; a 2× model error passes | deferred |
| AGG14-79 | Medium | High | CLAUDE.md, `web/README.md` vs `tests/`, `scripts/*.sh` | Sixteen documented behaviours have no test at all — `browser_verify.sh`'s water probe, the no-corner-rounding rule, the whole-cell LOD margins, the H3-irregularity measurements, the four deploy viewports, the city-list check, `--respace`'s output, "never per keystroke", the vendored version numbers, the font cache headers, `--only` rewriting `hover_cells.bin`, and the door-to-door surface set | deferred |
| AGG14-80 | Medium | High | `tests/sources/test_cache_provenance.py:239-253` | The country-key test re-implements `cell_country`'s cache key in its own body, so adding a version tag (as recommended elsewhere) makes it die with a bare `AssertionError: computed` on correct code | deferred |
| AGG14-81 | Medium | High | `tests/test_cli.py:171,191,346` | Hardcoded per-origin artifact counts (`== 7`, `== 14`) turn three tests red simultaneously the moment an eighth artifact is added — this repo's recorded gate-fails-on-correct-code shape | deferred |
| AGG14-82 | Medium | High | `tests/cli/test_reindex.py:215,228` | Bare `monkeypatch.undo()` also undoes `conftest._hermetic_cache`, restoring the real `config.CACHE` for the rest of the test — how 358 stray parquet files came back once | deferred |
| AGG14-83 | Medium | High | `tests/graph/test_build.py:95-104,114-130` | `assert 1 <= len(rejected_air_pairs)` and `0 < len(unknown_airport_pairs)` put strict lower bounds on counts of *upstream data defects*: if Wikidata fixes its P238 errors the gate goes red on improved data | deferred |
| AGG14-84 | Medium | High | `tests/graph/test_build.py:133-142` | Neither half of the airport-connectivity test can fail: `0 <= len(isolated)` is structurally true and the upper bound is already raised by the call on the line above | deferred |
| AGG14-85 | Medium | High | `tests/graph/test_nodes.py:34-47` | Same shape — `0 <=` is vacuous and the upper bound moves with the source gate, so raising `MAX_DROPPED_AIRPORT_FRACTION` from 0.02 to 0.5 keeps it green | deferred |
| AGG14-86 | Medium | High | `tests/solve/test_origin_snap.py:82-113` | The docstring records a mutation (dropping `_solve_one`'s `except ValueError`) that cannot redden it: the test never calls `_solve_one`, it re-implements the try/except in its own body | deferred |
| AGG14-87 | Medium | High | `tests/graph/test_air.py:91-127` | Four tests pin `air.KNEE_KM`'s upper side only — it can be lowered from 400 to 270 with all four green, readmitting most of the short-range blow-up the commit exists to stop | deferred |
| AGG14-88 | Medium | High | `tests/graph/test_ferry.py:174-192` | The off-mask-ferry fixture is 100 % off-mask, so `MAX_OFF_MASK_FERRY_FRACTION` can be changed from 0.20 to 0.95 and still raise; the value that decides real detection is unpinned | deferred |
| AGG14-89 | Medium | High | `tests/graph/test_build.py:36-39` | `np.isfinite(csr.data).all()` and `(csr.data > 0).all()` restate a `RuntimeError` `build_graph` already raises before returning | deferred |
| AGG14-90 | Medium | Medium | `tests/graph/test_rail.py:10-16`; `tests/graph/test_rail_integration.py:21-25` | Stale test double: `stop()` builds seven keys against an eight-field `sources/osm.SCHEMA`; polars silently nulls `route_name`, so rail consumers are tested against a frame no real extract produces | scheduled-this-cycle (C14-3) |
| AGG14-91 | Medium | High | `tests/emit/test_atomic_writes.py:21-31` | `atomic_write`'s "on any failure the target is left untouched" is never proven: `out` does not exist before the failing write, so adding `path.unlink()` before `mkstemp` leaves all three tests green | deferred |
| AGG14-92 | Medium | High | `tests/emit/test_reading.py:30-41,93-98,300-305` | Every reading-layout fixture has `fine = np.zeros(..., bool)`, so the split-cell branch never runs; the `inspect.getsource` guard pins the function name but not its resolution argument | deferred |
| AGG14-93 | Medium | High | `tests/emit/test_water.py` vs `web/app.js:777` | `water.LAYER` is never cross-checked against the page's hardcoded `"source-layer": "water"`; renaming it renders no coastline, with no console error and every test green | deferred |
| AGG14-94 | Medium | High | `tests/emit/test_atomic_writes.py:59-81`; `emit/{borders,places,airports_json}.py` | The "every emitter publishes atomically" parametrization covers 7 of 11, and three of the missing four bind `atomic_write` at import so the monkeypatch technique could not reach them anyway; `emit/places.py` has no test file at all | deferred |
| AGG14-95 | Medium | High | `tests/contour/test_grid.py:34-43`; `contour/grid.py:44,97,128` | `grid.universe`'s cache test varies only the cell list, so dropping `rings` or `GRID_VERSION` from the key stays green; `grid.native_edges` has no cache test at all and its `.npz` does not key on `SOLVE_RES` | deferred |
| AGG14-96 | Medium | High | `tests/contour/test_bands.py:16-30`; `contour/bands.py:58,312,322` | Edge inclusivity is pinned on `band_of`, which nothing in `src/` calls; the shipped `band_indices` is never tested at a boundary, so `side="left"`→`"right"` moves every on-edge cell with the suite green | deferred |
| AGG14-97 | Medium | Medium | `emit/index.py:341-342`; `web/app.js:2098` | No test anywhere passes `reading_parent_count`, so deleting the block silences the page's only guard against a `reading_parents.bin` from a different build | deferred |
| AGG14-98 | Medium | High | `tests/emit/test_water.py:26-45` | The file's own comment says the zoom gate is deliberately an inequality, but the two tests are conjointly an equality gate — raising the page's `maxZoom` reddens a merely conservative tileset | deferred |
| AGG14-99 | Medium | High | `web/app.js:120-121,1855-1859` | The page's runtime mixed-build refusal for `.bin`/`.air.bin`/`.modes.bin` is executed by no test; deleting the byte-length throw leaves all 398 web tests green and renders plausible wrong times | deferred |
| AGG14-100 | Medium | Medium | `tests/web/test_etops_is_not_a_control.py:98` | The `engine\|aircraft\|equipment` scan covers comments and docstrings, contradicting the same file's stated policy, and is unanchored so `engineering` trips it | deferred |
| AGG14-101 | Medium | High | 18 of 34 files in `tests/web/` | `node` resolves through a per-shell fnm multishell path, so in CI, a cron shell or a bare `sh -c` more than half the web suite — including `test_parses.py` — skips green and silently | deferred |
| AGG14-102 | Medium | High | `emit/index.py:152-215`; `graph/{air:33,rail:37,ferry:126,ground:34}.py` | There is no calibration layer: `calibration.toml` is opened by four independent loaders in `graph/`, and `emit/index.mode_detail()` lazily imports three graph modules plus `sources` at call time to render prose from them | deferred |
| AGG14-103 | Medium | High | `graph/ground.py:156`; `graph/rail.py:55`; `web/app.js:3257`; `scripts/adsb_extract.py:41`; `scripts/expand_origins.py:87-90`; `graph/build.py:82` | Six great-circle implementations, five hand-written; they agree within 15 m but `expand_origins.py:90` still uses the bare 6371 that a live comment claims was eliminated, and it decides a 40 km duplicate cutoff | deferred |
| AGG14-104 | Medium | High | `cli.py:634-661,711` vs `scripts/check_dist.py:296-338` | "Is this origin publishable?" has three definitions and the publisher's is the weakest: `_reindex` ignores `.rail.*` entirely and sets `railDetail` from *any* origin, so it writes an `index.json` the deploy gate refuses and blames `reindex` for (absorbs code-reviewer C9) | deferred |
| AGG14-105 | Medium | High | `emit/{places,airports_json,borders}.py`; `scripts/check_dist.py:28` | Three artifacts the deploy gate requires have no caller anywhere outside `tests/` — they must be produced by hand from a REPL — and all three also download from inside `emit/`, which is `sources/`'s job (absorbs debugger E13) | deferred |
| AGG14-106 | Medium | High | `cli.py:308,369,464,468` vs `:556,796` | `_solve_one` hard-codes `config.DIST` and `_reindex`'s `dist` parameter is dead at the CLI, so no build can be written to a staging tree and swapped in — the standard answer to "never deploy a partial `dist/`" | deferred |
| AGG14-107 | Medium | High | `plan/` (no entry), `cli.py:400,418` | A 39-hour build that dies restarts from zero and has died twice; resume is unscheduled, blocked by five things (no completion record, no per-origin identity, no host in the lock, no callable publishability predicate, no `--dist`) — but **not** by graph persistence, which costs 310 s against 38 h | deferred |
| AGG14-108 | Medium | High | `cli.py:108-133,154-183`; `scripts/deploy_verify.sh:74` | `build-all` and a resident solver are mutually invisible: concurrency is detected by matching the literal string `"build-all"` in `ps` output, where the fix is to generalise the already-tested `_acquire_lock` into a shared lock namespace | deferred |
| AGG14-109 | Medium | High | `cli.py:291,309,317,437-457,483-484`; `emit/rail_detail.py:89` | The worker context is an untyped eight-key dict in a module global, read with a mix of `[]` and `.get`; a renamed `rail_tables` key silently drops station naming from every origin while `check_dist` sees a correctly-sized paired file set (absorbs debugger A5) | deferred |
| AGG14-110 | Medium | High | `sources/osm.py:92`; `emit/rail_detail.py:75-76` | An unnamed `stop_position` node inherits the relation's name, so the shipped "station" column can hold a service name — 1,144 of 124,488 rows across 60 origins have `station == line` | scheduled-this-cycle (C14-4) |
| AGG14-111 | Medium | High | `emit/rail_detail.py:24-41,94-106` | `last_station_per_node` propagates through airport nodes, so a cell reached by flying after a rail access leg is captioned with the station on the far side of the flight — 570 of 5,704 rail-attributed cells from Paris, worst 8,426 km | deferred |
| AGG14-112 | Medium | High | `emit/rail_detail.py:111-113`; `scripts/check_dist.py:315-332`; `web/app.js:1936` | `.rail.bin` and `.rail.json` are never checked as a pair: nothing asserts `max(ordinal) < len(stations)` or that both came from one build, so a stale `.rail.json` names a different real station for every rail cell with no error | deferred |
| AGG14-113 | Medium | High | `_io.py:46-55` | `atomic_write`'s cleanup `unlink` is outside a try, so an `ESTALE`/`EIO` from the cleanup replaces the real write failure in every NFS error in the project; there is also no `fsync` before `os.replace` | deferred |
| AGG14-114 | Medium | High | `_io.py:43`; `emit/tiles.py:46-61`; `cli.py:378` | Nothing sweeps `.tmp` leftovers from `dist/` — `sweep_scratch` covers only the local tippecanoe staging dir — so every SIGTERM/OOM abort leaves files that later make `check_dist` refuse the whole deploy with no remedy | deferred |
| AGG14-115 | Medium | High | `scripts/build_water_tiles.py:13`; `scripts/expand_origins.py:141` | Two scripts write published or hashed state without taking or checking `dist/.build.lock`, although the lock's own docstring names both as the reason it exists | deferred |
| AGG14-116 | Medium | High | `scripts/expand_origins.py:141`; `calibrate/ground.py:125`; `scripts/adsb_extract.py:188`; `emit/water.py:58`; `scripts/osm_rail.sh:40` | Five non-atomic writes outside `_io.atomic_write`, including an append to `data/origins.toml` (a crash makes every later build unparseable) and a fixed `.part` download name | deferred |
| AGG14-117 | Medium | High | `graph/build.py:426-449` | The duplicate-edge check builds a 656 MB key array and `np.unique`s it (sorting a second 656 MB copy) to answer a boolean, doubling the graph assembly's peak | deferred |
| AGG14-118 | Medium | High | `sources/countries.py:96-116,140-177`; `sources/urban.py:76-94` | `cell_country` is a multi-GB parent-process pass called three times per build with no memoisation, and even a cache *hit* builds a ~150 MB string plus a ~150 MB bytes copy to compute the key | deferred |
| AGG14-119 | Medium | High | `emit/water.py:117-142` vs `emit/tiles.py:126-133` | `water.py` captures tippecanoe's stderr and discards it, and never checks the output is non-empty — the operator gets a bare exit status after a multi-minute run on a 1.5 GB input | deferred |
| AGG14-120 | Medium | High | `scripts/calibrate_ground.py:134-140`; `calibrate/ground.py:50-64` | `except RuntimeError: break` discards the message, so "GOOGLE_ROUTES_API_KEY is not set" — the mistake the docstring anticipates — ends as "only 0 usable samples; refusing to fit" | deferred |
| AGG14-121 | Medium | High | `scripts/osm_rail.sh:20,33,45,48` | No `-e`, no failure counter, and `[ALL DONE]` unconditionally: all seven continents can print `[FAIL]` and the script still exits 0 | deferred |
| AGG14-122 | Medium | High | `scripts/check_ramps.py:79-85,217-246` | The `RAMPS` regex pins key order, so a reorder in `app.js` yields zero parsed schemes, `bad` stays 0 and the script exits 0 having enforced nothing — and `--respace` then rewrites `app.js` byte-identically and reports success | deferred |
| AGG14-123 | Medium | High | `emit/borders.py:72,74-84`; `emit/water.py:89` | An empty FeatureCollection ships as valid JSON that passes the existence gate and draws no borders with no error (`emit/places.py` guards exactly this); two sites use bare `next()` so a layout change raises `StopIteration` with no message | deferred |
| AGG14-124 | Medium | High | `web/index.html:718-719,859` | Folded, the sheet hides `#where` — the only element carrying "· from Seoul" — under a caption reading "Hours from the departure city, door to door" that then names no city | deferred |
| AGG14-125 | Medium | High | `web/index.html:692-698,748-770` | The grab handle stays live in landscape, where the landscape block does not override it: folding hides the panels but leaves the 300 px column exactly as wide, so the globe gains nothing | deferred |
| AGG14-126 | Medium | High | `web/index.html:162-166,916` | "Santo Domingo de los Colorados" overflows the Departure `summary` by 22 px with `white-space:nowrap` and no ellipsis, forcing a horizontal scrollbar on the whole rail and pushing the disclosure marker out of view | deferred |
| AGG14-127 | Medium | High | `web/index.html:243-253,667`; `web/app.js:371-376` | The idle prompt measures 69 px against a `min-height:50px` that a comment claims reserves the number's height, so the legend and ticks jump 19 px when the first reading lands (and ~18→69→50 px on a cold load) | deferred |
| AGG14-128 | Medium | High | `web/index.html:788-790,197,646,739` | The masthead standfirst was removed but its three CSS rules remain: above the fold the page is named only by a 19th-century term of art, and re-adding a `<p>` would be silently invisible on every phone | deferred |
| AGG14-129 | Medium | High | `web/index.html:358-368` | `.legs h2` ("Journey to Reykjavík") is smaller, dimmer and barely heavier than the rows it heads — hierarchy running backwards in exactly the two channels the design policy says to use | deferred |
| AGG14-130 | Medium | High | `web/index.html:718-719,873,1044` | The Privacy link sits in the always-visible legend credit precisely so it is always reachable, but its target is inside a `display:none` `<details>` when the phone sheet is folded, so it silently does nothing | deferred |
| AGG14-131 | Medium | High | `web/index.html:1109-1110` | "the mode of the last leg" is really minutes spent in each of six surface modes over the whole journey, access leg included | deferred |
| AGG14-132 | Medium | High | `web/index.html:1094-1096` | "A flight's time is a function of the great-circle distance and nothing else" ignores size-dependent taxi at both ends and the border charge on a zone-crossing flight — and contradicts the same page at :1033 | deferred |
| AGG14-133 | Medium | High | `web/index.html:1058-1061`; `web/llms.txt:26-29`; `graph/ferry.py:192-195` | The ferry wait is half the *year-averaged* headway (the interval divided by `service_fraction`), and no user-facing surface says so | deferred |
| AGG14-134 | Medium | High | `web/README.md:62`; `tests/web/test_vendor.py:37,90` | "Every file in `vendor/` appears above" is false: the seven files in `vendor/licences/` are served to visitors and pinned by nothing, because the enumeration filters the top level only | deferred |
| AGG14-135 | Medium | High | `README.md:92-93`; `graph/ground.py:21-23`; `calibrate/ground.py:119` | "the fit wanted roadless terrain infinitely fast, which its guard refuses" — the fit returned a *negative* reciprocal and it is the `recip > 0` sign filter that drops it, not the support guard | deferred |
| AGG14-136 | Medium | High | `validate.py:174`; `cli.py:334,434,455,466`; `contour/bands.py:28`; `emit/hover.py:156`; `emit/index.py:113,332` | "553 origins" in nine comments against a 1,464-row roster, so every "×553" cost statement understates by 2.65× — and `cli.py:216,226` say 1,464 in the same file | deferred |
| AGG14-137 | Medium | High | `graph/ground.py:28-31` | "Measured at 8.0 per cell (82 M edges over 10.2 M cells)" is 5.97 over 13.75 M — and as written, 8.04 would overflow the `EDGE_SLOTS_PER_CELL = 8` cap the sentence exists to justify | deferred |
| AGG14-138 | Medium | High | `validate.py:34-39` | `check_coverage`'s Antarctica arithmetic ("~43,500 cells", "about 92 %", "two points of headroom") is res-5; at res 6 it is ~365,000 cells and ~97.3 %, so the stated rationale does not hold | deferred |
| AGG14-139 | Medium | High | `validate.py:175-177`; `cli.py:433-434` vs `sources/roads.py:115-119` | "~4.8 s per origin" of `roads.cell_class` work is a res-5 figure; a third file supplies the 7.5× correction (≈36 s) that the two repeating it have not taken | deferred |
| AGG14-140 | Medium | High | `emit/index.py:112-115,331-333` | "four origin names appear twice"; the 1,464-row roster has thirteen duplicated names | deferred |
| AGG14-141 | Medium | High | `graph/build.py:31-33` vs `graph/nodes.py:33-34,178` | "124 of 68,152 pairs, all downstream of the 25 dropped airports" is pre-res-6 and contradicted by its sibling ("about a dozen atolls of 4,008 dropped, 58 snapped") | deferred |
| AGG14-142 | Medium | High | `validate.py:57-60` | "the full 3.6 million vertices would cost minutes" is res-5 arithmetic; the native LOD now sweeps ~82.5 M, so the tradeoff being justified is ~23× larger than stated | deferred |
| AGG14-143 | Medium | High | `web/app.js:2080-2085` | The reading tier is described as dormant "until the next full build advertises readingRes"; `dist/index.json` has carried `readingRes: 6` and every `.r6.bin` since 2026-09-12 | deferred |
| AGG14-144 | Medium | High | `tests/test_licence_firewall.py:25`; `scripts/check_dist.py:79` | Both files cite CLAUDE.md for a sentence it does not contain — `grep -i licen CLAUDE.md` returns nothing — a fabricated citation to the one document the repo treats as binding | deferred |
| AGG14-145 | Medium | High | `plan/README.md:41,43,51` | Three ID ranges are understated (C13 →25 not 11, C12 →14 not 11, C10 →17 not 14) — the one error shape that makes the "nothing was dropped" audit lie in the safe-looking direction | deferred |
| AGG14-146 | Medium | High | `plan/deferred.md:670` | C12-10's exit criterion ("or cycle 13, whichever is first") fired and the row was never swept, while its two siblings were correctly re-raised as V13-20/V13-21 | deferred |
| AGG14-147 | Medium | High | `plan/deferred.md:497` vs `deploy/worldmap-security-headers.conf:23`, `deploy/README.md:79-89` | AB35 is still open on a dead premise: the snippet now names all four analytics hosts and has been INSTALLED since 2026-09-13 | deferred |
| AGG14-148 | Medium | High | `plan/deferred.md:96` | E1's data half describes a 157-origin res-5 served build; `dist/index.json` has been 553/res-6 since 2026-09-12, so a reader cannot tell whether the row is live or stale | deferred |
| AGG14-149 | Low | High | `sources/routes.py:327` vs `sources/airports.py:23-47` | `_wikipedia_titles` reads `data/cache/ourairports.csv` directly, which `scheduled_airports()` materialises only on a cache miss — a pruned cache gives a bare `FileNotFoundError` from inside the crawl | deferred |
| AGG14-150 | Low | High | `sources/urban.py:92-94`; `web/app.js:1513-1514` | Two planar longitude deltas are unwrapped, so a cell at 179.9°E and a city at 179.9°W compute as ~35,000 km apart — Fiji, Anadyr and the western Aleutians never mark urban, and `nearestPlace` names the wrong side of the ocean | deferred |
| AGG14-151 | Low | High | `emit/places.py:57-66` | A truncated GeoNames row makes `r["lat"]` raise `KeyError`, which `except ValueError` does not catch, and the `pop` parse sits outside the `try` — one malformed line aborts `places.json` instead of dropping one town | deferred |
| AGG14-152 | Low | High | `web/app.js:1227-1286` | `solvePoint` never checks `signal.aborted` before wiring its relay (so an already-cancelled request runs a full solve) and its `typeof body.minutes !== "number"` guard admits `NaN` | deferred |
| AGG14-153 | Low | High | `web/app.js:1672-1681` | `Number("")` is 0, so `?at=37.5665,126.978,` parses as zoom 0 and opens on the whole globe instead of being rejected as the docstring promises | deferred |
| AGG14-154 | Low | High/Med | see below | Six items code-reviewer recorded as "notes, not findings", carried here so none is lost: `countries.cell_country:110-116` names `hit_geom`/`hit_point` backwards (usage correct, invites a wrong fix); `bands._slowest_within:185-197` docstring false for `rim>=2`; `modes.mode_minutes_per_node:71` attributes passport-desk minutes to a road channel whose tooltip states a road speed; `check_dist.pmtiles_metadata_text:100-103` raises `struct.error` on a <40-byte file; `wire.parse_query:157` applies `MAX_QUERY_CHARS` vacuously when a `getter` is supplied; `cli._build_all_locked` accepts a negative `--limit` and reads it as "all but the last N" while still setting `partial` | deferred |
| AGG14-155 | Low | Medium | `cli.py:76-96` | The worker cap is a hard-coded cell threshold (`5 if n_cells > 3M else 8`) for a failure that is a memory property; measured peak is 3.4 GB × 5 on a 32 GB machine at 94 % swap | deferred |
| AGG14-156 | Low | High | `validate.py:196-222` | `check_monotonic_ground` calls numpy haversine on 1-element arrays inside a nested loop — ~61,000 iterations of ~15–20 µs dispatch overhead for ~50 ns of arithmetic | deferred |
| AGG14-157 | Low | High | `emit/rail_detail.py:48-50`; `graph/rail.py:66,73,88`; `scripts/check_dist.py:299-345` | Four polars `map_elements` Python UDFs over ~257,000 stops where a pure expression would run in Rust; separately, `check_dist` `json.loads` 293 MB of `{slug}.json` on every deploy to read two fields | deferred |
| AGG14-158 | Low | High | `sources/roads.py:73` | `np.load` without an explicit `allow_pickle=False`, inconsistent with `contour/grid.py:47,100`, on a file under a shared NFS build tree | deferred |
| AGG14-159 | Low | High | `web/app.js:28-29,606-611` | Two hardening items on an otherwise closed XSS surface: `esc()` does not escape `'` (so the helper's documented attribute-safety contract holds for one quoting style only, and `test_esc.py` has no apostrophe case), and the credits links assign `s.url` to `href` with no scheme check | deferred |
| AGG14-160 | Low | Medium | `emit/water.py:87-88` | `extractall()` with no member or size budget into `config.CACHE`; Zip Slip is not reachable in CPython, but unbounded decompression would not look anomalous beside a legitimate 1.5 GB archive | deferred |
| AGG14-161 | Low | Medium | `scripts/adsb_extract.py:95-120` | `urllib.request.urlopen` on a URL taken from a JSON body with no scheme allowlist — `urlopen` also handles `file:` and `ftp:` | deferred |
| AGG14-162 | Low | Medium | `tests/test_licence_firewall.py:17-22`; `scripts/check_dist.py:184-186` | The licence firewall is a nine-token provider-name denylist and structurally cannot see a record dump (e.g. `ground_samples.json`), and `check_dist` has no allowlist of publishable files — it refuses only names matching `STRAY` | deferred |
| AGG14-163 | Low | High | `web/vendor/maplibre-gl.js:1-3`; `pyproject.toml` | The vendored MapLibre is a correctly hand-patched 5.24.0 on an end-of-life line; there is no CI, no dependency-audit step in `deploy_verify.sh`, and all ten runtime dependencies use unbounded `>=` | deferred |
| AGG14-164 | Low | Medium | `sources/routes.py:326-335` | A community-edited OurAirports `wikipedia_link` containing `|` injects extra titles into a 50-title MediaWiki batch; `_refuse_partial` turns it into a loud abort rather than corruption, and the filter is one line | deferred |
| AGG14-165 | Low | High | `graph/headway.py:18,29-30` | `NO_SERVICE` is unreachable — both callers floor their frequency first — so its comment describes behaviour that never occurs; if it ever fired, `10**7` would pass `build_graph`'s check and overflow uint16 | deferred |
| AGG14-166 | Low | High | `_io.py:92-104` | `_reject_unordered` stops recursing at depth 6, so a set nested at depth 7 reaches `repr` and reinstates the `PYTHONHASHSEED` dependence the guard exists to prevent (proven by execution) | deferred |
| AGG14-167 | Low | High | `tests/test_licence_firewall.py:74` | `assert len(files) > 0` two lines below a `pytest.skip` that already guarantees it — the vacuous-assertion pattern, inside the file whose subject is vacuous passes | deferred |
| AGG14-168 | Low | Medium | `tests/sources/test_cache_provenance.py:135-158,296-345` | The stamp predicates rely on `any(c.isdigit())` in the hex group (~1/1182 chance of a false red per constant change), and five subprocesses use a relative `sys.path.insert(0,'src')` that depends on pytest's CWD | deferred |
| AGG14-169 | Low | Medium | `tests/calibrate/test_fit.py:29-42` | `test_recovers_known_frequency_coefficients` builds noiseless data then accepts `rel=0.15`, admitting a systematically biased estimator; its sibling earns its tolerance by adding noise | deferred |
| AGG14-170 | Low | Medium | `tests/graph/test_ground.py:36-78` | The final assertions omit the zone-crossing `extra` term and pick their pair by scanning from index 0, so a land-mask refresh can turn them red on correct code | deferred |
| AGG14-171 | Low | High | `tests/graph/test_nodes.py:24-31` | `assert idx.airport_cell_index("ICN") < idx.n_cells` is true by construction — no mutation short of a rewrite fails it | deferred |
| AGG14-172 | Low | High | `tests/solve/test_origin_snap.py:57` | `assert ring[pos] in ring` is a tautology; the test's real content is "did not raise" | deferred |
| AGG14-173 | Low | High | `tests/graph/test_build.py:7,42-92` | A module-wide `integration` mark covers three tests that need no caches, which also opts them out of `conftest._hermetic_cache` for no reason | deferred |
| AGG14-174 | Low | High | `tests/graph/test_ferry.py:109-113`; `tests/graph/test_build.py:81-92` | `MIN_FERRY_KM = 1.0` has no test at all and `IMPLAUSIBLE_LONGHAUL_KM = 8000` is exercised only at 14,000 km, so changing it to 12,000 passes | deferred |
| AGG14-175 | Low | High | `tests/graph/test_build.py:107-111` | The `unknown_airport_pairs` fixture calls `build.build_graph` a second time, duplicating a multi-minute assembly and discarding the matrix, when both out-params fit in one call | deferred |
| AGG14-176 | Low | High | `tests/contour/test_bands.py:100,113` | Two h3 boundary coordinates pinned to nine significant figures — premise tests that fail on an h3 point release while naming no actionable defect | deferred |
| AGG14-177 | Low | High | `tests/emit/test_hover.py:43-48` | `assert raw.dtype.itemsize == 2` is tautological (the test created `raw` as `<u2`), and endianness is not checked here | deferred |
| AGG14-178 | Low | Medium | `tests/emit/test_index.py:15-20`; `tests/emit/test_reading.py:189-199` | Both sortedness guards run on two-element fixtures, so `np.diff(...) > 0` is a single comparison and an empty diff would be vacuously true — the page binary-searches both files | deferred |
| AGG14-179 | Low | High | `tests/web/test_reading_tier_fallback.py:326-341` | `assert (call in settle) == (call in read)` is a biconditional: deleting `renderLegs()` from both sides passes green | deferred |
| AGG14-180 | Low | High | `tests/web/test_vendor.py:38,208` | `assert fit is not None` on an imported module cannot fail under any mutation, and `expected <= set(recorded)` is one-directional so a hash recorded for a deleted vendor file is never flagged | deferred |
| AGG14-181 | Low | Medium | `tests/web/test_reading_slot.py:87,98` | `len(kids) == 286` / `differ == 285` hard-code pentagon child counts, undoing the fixture two dozen lines above that deliberately reads both resolutions from `config` | deferred |
| AGG14-182 | Low | Medium | `tests/web/test_route_geometry.py:220` | The map stub returns the same recorder for any source id and flattens everything into one array, so writing the air features into the ground source (or a nonexistent one) passes every assertion | deferred |
| AGG14-183 | Low | High | `emit/routes_json.py:15-16`; `emit/modes.py:29` vs `emit/hover.py:50` | scipy's `-9999` predecessor sentinel is declared in `emit/` rather than `solve/` — the layer a solver service may not import — and `MAX_MINUTES` has a second copy whose own comment says "one constant, not two copies" | deferred |
| AGG14-184 | Low | High | `validate.py:3-5,41,73-75,179-194`; `solve/dijkstra.py:6`; `emit/itinerary.py:63` | `validate.py` presents as a foundational leaf at the package root while being the second-highest module in the tree, with all four package imports function-local and one reaching a private `ground._land_border_min`; `solve` likewise imports a private `_nearest_land` | deferred |
| AGG14-185 | Low | High | `sources/_utils.py:6,61-67,88` | `atomic_write` and `params_hash` are re-exported under private names to seven modules — the repo's most important invariant reading as private-to-that-module — and the two aliases are split by an unrelated function | deferred |
| AGG14-186 | Low | Medium | `contour/grid.py:44,90` | `contour/` hand-rolls `hashlib.sha256` with a manually bumped `GRID_VERSION`/`NATIVE_VERSION` instead of `_io.params_hash`, the one place the set-rejection guard therefore does not apply | deferred |
| AGG14-187 | Low | High | `emit/modes.py:32-…`; `emit/itinerary.py:36-45` | Leg classification exists only inside two emit loop bodies as open-coded node-index range arithmetic; there is no `classify_edge()`/`node_kind()` primitive, so the layout is re-derived at four call sites and a solver can answer a number but not an itinerary | deferred |
| AGG14-188 | Low | High | `graph/rail.py:69-76` | `rail.stations()` computes `cell` at `SOLVE_RES` rather than through `cell_at`, so it is wrong for every station inside a split urban cell, and `name` comes from an unordered `group_by`; both columns are currently dead, so it is a trap | deferred |
| AGG14-189 | Low | High | `emit/itinerary.py:18,65-70` vs `emit/rail_detail.py:107-110` | `NO_AIRPORT = 0xFFFF` has no overflow guard where `NO_RAIL` explicitly raises: above 65,535 airports a real ordinal would silently wrap and state positively that no flight was involved (absorbs debugger E6) | deferred |
| AGG14-190 | Low | High | `emit/modes.py:24,27`; `emit/index.py:214-215` | No GRIP4 class maps to a track, so the channel labelled "track" holds roadless terrain and the page prints "by track" for ground with no mapped road; only the hover tooltip corrects it | deferred |
| AGG14-191 | Low | High | `graph/build.py:346,350` | `ground_adjacent` is tested before `is_closed`, so a ferry between adjacent cells across a sealed border is logged under "duplicates a ground edge"; both drops are correct, only the reason line is wrong | deferred |
| AGG14-192 | Low | High | `cli.py:123-137` | A lock read inside its create window (the file exists but the pid is not written yet) reports "is STALE: pid None … remove the lock file to build again" | deferred |
| AGG14-193 | Low | High | `cli.py:196,733-739`; `_build_all`'s `finally` | A worker raising `MemoryError` returns through `imap` as a plain traceback rather than a named `GateFailure`, and a SIGKILLed *parent* skips the `finally: lock.unlink()`, leaving a lock that AGG14-21 then makes un-diagnosable | deferred |
| AGG14-194 | Low | High | `cli.py:330-350` | `_log_reading_cost`'s comment says every failure is swallowed so a build that solved 553 origins is not lost to a log line; only `OSError` is caught, at the last statement before `index.json` | deferred |
| AGG14-195 | Low | High | `cli.py:603-609,671` | `_reindex` catches only `ValueError`, so a `null` or list-shaped `index.json` raises a `TypeError` that never mentions index.json | deferred |
| AGG14-196 | Low | High | `sources/routes.py:129,237-251` | A failed Wikipedia batch prints `failed: …` immediately followed by `done (N airports cached)`; and a revision-deleted article raises `KeyError` past both handlers, killing a multi-hour crawl and discarding the in-flight batch | deferred |
| AGG14-197 | Low | High | `web/index.html:255` | `.reading .at` reserves 31.2 px for an idle line that measures 36 px and a committed one that can run to four lines — the reserve holds for nothing that occurs | deferred |
| AGG14-198 | Low | High | `web/index.html:211-213` | `.reach dd{width:5.5ch}` is a no-op: the `dd` is left-aligned in a `1fr` track, so the width changes nothing and the decimal points stay ragged; the two places that got it right also set `text-align:right` | deferred |
| AGG14-199 | Low | High | `web/index.html:440-441` | `.results .rowtime` is 63.8 px against 66.2 px for `120 h 59 min`, and with `flex:none` + `text-align:right` the overflow runs left into a city name that cannot get out of the way | deferred |
| AGG14-200 | Low | Med-High | `web/index.html:477-489` | "Match the scheme" wraps to two lines in a 60 px ocean button and drags its whole flex row ~13 px taller; "Deep blue" fits with 0.2 px to spare | deferred |
| AGG14-201 | Low | Med-High | `web/index.html:328,334` | Links are the only interactive elements with no `--accent` focus ring, and inside `#key`'s scroll box the UA ring can be clipped the way `.results button`'s once was | deferred |
| AGG14-202 | Low | Med-High | `web/index.html:922`; `web/app.js:3881-3913` | `#q` drives a `role="listbox"` with only `aria-controls` — no `role="combobox"`, `aria-expanded` or `aria-autocomplete`; the `.listmore`/`.empty` rows are `role="none"` and the "Showing N of 553" footer is announced only when a filter is active | deferred |
| AGG14-203 | Low | High | `web/index.html:38` | The JSON-LD says airports, rail stations and ferry crossings are "listed in index.json"; they are not — airports come from `airports.json`, stations from `{slug}.rail.json`, ferries never reach the client | deferred |
| AGG14-204 | Low | High | `web/index.html:1112-1114` | The coarse-reading fallback is presented as a closed list of two causes; there are four (in flight, absent from the build, Save-Data, padding slot) | deferred |
| AGG14-205 | Low | High | `web/llms.txt:53` | "`{slug}.r6.bin` (9.55 MB)" is MiB amid five decimal figures; the file is 10,014,228 B | deferred |
| AGG14-206 | Low | High | `web/index.html:53` | Hand-written JSON-LD `dateModified` of 2026-09-10 against a `builtAt` of 2026-09-12 (the visible build date is derived correctly) | deferred |
| AGG14-207 | Low | High | `web/index.html:933` | The static city-list caption omits "door to door" — the one place the file's copy disagrees with the rule its own comment cites | deferred |
| AGG14-208 | Low | Medium | `web/index.html:718,1113-1114` | On a folded phone sheet the promised "the line under it says so" tier disclosure is hidden, because it is appended to `#where` only and `revealReading()` does not unfold | deferred |
| AGG14-209 | Low | High | `web/index.html:1043-1084` | "What this does not know" mentions neither the ≥90 % coverage gate nor the legend's "no scheduled route" grey, both of which the page shows figures for | deferred |
| AGG14-210 | Low | Medium | `web/README.md:70-73` vs `scripts/deploy_verify.sh:83-84` | The README enumerates eight copied files; the deploy mirrors all of `web/` minus an exclude list — accurate today, silently stale the first time a file is added | deferred |
| AGG14-211 | Low | Medium | `docs/…design.md:117-128` | The spec's licensing table — the document the redistribution rule hangs off — omits Natural Earth, GeoNames, HydroLAKES and adsb.lol, all of which ship | deferred |
| AGG14-212 | Low | High | `cli.py:677-678` vs `:527-553` | "the four fields"; `_CURRENT_INDEX_CONSTANTS` holds nine | deferred |
| AGG14-213 | Low | High | `cli.py:78` vs `:90` | "Bounded by RAM, not by cores", then `min(cores - 2, 8, n_origins)` — on a ≤10-core machine the core term binds | deferred |
| AGG14-214 | Low | High | `config.py:55` vs `:60`, `graph/ferry.py:15`, `calibration.toml:154` | The band ratio is quoted as "about 1.155" where its own edges give 1.1526, as two other files say | deferred |
| AGG14-215 | Low | High | `emit/tiles.py:16-21` | "z7 measured ~38 % larger than z6"; the same comment's figures (3.84 MB vs 2.38 MB) make dropping z7 −38 % and adding it +61 % | deferred |
| AGG14-216 | Low | High | `calibration.toml:293-294` vs `graph/build.py:215-259,354` | `[land_border]` says the charge is on the ground edge; `_border_rules` applies it to every surface edge, rail and ferry included | deferred |
| AGG14-217 | Low | High | `sources/_utils.py:72-73`; `sources/wikidata.py:199-201` | Both describe `routes.parquet` as the cache returned forever after; it is now the warned legacy fallback and the cache is `routes_{stamp}.parquet` | deferred |
| AGG14-218 | Low | Medium | `sources/landmask.py:155` | "Measured: 42,704 cells, 0 failures" for the Antarctic wedges matches neither res 5 (52,558) nor res 6 (~365,000) | deferred |
| AGG14-219 | Low | High | `plan/deferred.md:1-3` | The scope line says "cycle-1 and cycle-2"; the file carries headings through cycle 12 plus "Closed in cycle 13", and cycle 13's own deferrals live elsewhere | deferred |
| AGG14-220 | Low | High | `plan/deferred.md:44,100,326,436,437,497,524` | Stale citations: `graph/rail.py:113` in a 107-line file (named by AB41 as its own example and still uncorrected), `deploy/snippets/…` for a file at `deploy/…`, four archived plans at pre-archive paths, and an attribution line that has moved | deferred |
| AGG14-221 | Low | High | `plan/deferred.md:103` | One row's finding text occupies the ID column — the only 5-cell row in a file of 212 six-cell and 40 seven-cell rows | deferred |
| AGG14-222 | Low | High | `plan/deferred.md:595` | DOC10-M*'s "what held up" evidence line still cites 553 origins; the roster is 1,464, so the batch is being re-deferred on a premise nobody re-checked | deferred |
| AGG14-223 | Low | Medium | `CLAUDE.md:22-24` vs `scripts/check_ramps.py:39-56` | CLAUDE.md's "~7 ΔE per step is the ceiling" is contradicted by the gate that measures it (four of twelve schemes exceed it; there was no ceiling) — recorded only; CLAUDE.md is the owner's standing policy | deferred (will not do) |

### Disposition counts

| disposition | rows |
|---|---:|
| scheduled-this-cycle | 7 |
| scheduled-cycle-15 (build path, after the lock clears) | 19 |
| scheduled-cycle-16 (guards, first cycle that can run the suite) | 20 |
| scheduled-cycle-17 (page, deploy gates, privacy) | 6 |
| scheduled-cycle-18 (documentation sweep) | 3 |
| deferred, with exit criterion | 167 |
| deferred, will not do (owner's standing policy) | 1 |
| **total** | **223** |

By severity: all **9 Critical** and all **43 High** are scheduled -- 4 of them
this cycle, 48 for a named cycle, none deferred. The 96 Medium and 75 Low rows
are 3 scheduled this cycle and 168 deferred: 167 with an exit criterion, and
AGG14-223 recorded as will-not-do against the owner's standing design policy.

---

## Status

Cycle 14: seven items scheduled, all of them inside the rail service-tier work's
blast radius; 48 findings scheduled for a named cycle; 167 deferred with a
concrete reason and an exit criterion; one recorded as will-not-do against the
owner's standing design policy, with the rule quoted. **No finding was dropped,
and none was downgraded.**

Three things this document asserts that the next cycle should check rather than
trust:

1. **The exit criterion on most of these rows is one event** -- the running
   build finishing or being stopped, and `dist/.build.lock` disappearing. That
   makes cycle 15 large by construction. It should be ordered the way the
   aggregate orders it: AGG14-1 first (a hoist, ~6.8 h of wall clock), then
   AGG14-2 and AGG14-3, then AGG14-11, and only then the resume work that
   depends on AGG14-11.
2. **Closing AGG14-49 this cycle fires an exit criterion on thirteen deferred
   rows** (`plan/deferred.md:595`, the `DOC10-M*` batch). AGG14-222 records that
   the batch's own evidence line is stale, so the sweep must re-check the
   premise rather than re-defer on it.
3. **`plan/README.md` and `plan/deferred.md` were not edited this cycle** -- the
   orchestrator forbade touching existing plan files -- so AGG14-145 through
   AGG14-148 and AGG14-219 through AGG14-222 are still open against those files,
   and this document's own index entry is not yet in the README's plan table.
   That is the first bookkeeping item of the next cycle.
