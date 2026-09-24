# Adjacent land cells are joined across water

**Reported by the owner:** "tinian 까지 saipan 을 거쳐서 highway 로 갈 수 있다고
하는데 뭐지?" Saipan and Tinian are separate islands. The Saipan Channel is about
8 km of open sea with no bridge and no causeway; the crossing is by ferry or by
a short flight.

Same class as the earlier Mauritius report. NOT FIXED. Four candidate rules were
measured and all four rejected; the measurements are below so the next attempt
does not repeat them.

## The defect, measured

| | |
|---|---|
| Saipan south cell | `864f4b437ffffff` (15.128, 145.675) |
| Tinian north cell | `864f4b427ffffff` (15.082, 145.633) |
| centroid separation | **6.74 km**, across ~8 km of open sea |
| `h3.are_neighbor_cells` | **True** -> `ground.hex_edges` joins them |
| `refine.ground_adjacent` | **True** -> `emit/modes` books the hop as ROAD |
| GRIP4 class, both cells | 2 -> channel **"major road"**, 57 km/h |
| charged time | **7.1 minutes** to drive across the strait |

## Root cause

A cell is "land" if it contains ANY land. At `SOLVE_RES` 6 the cells are about
7.4 km across, so two cells on opposite shores of a strait narrower than a cell
can be H3 neighbours. `hex_edges` joins every adjacent pair of land cells and
never asks whether land is continuous between them.

It is a double defect. The phantom ground edge is created, AND `build_graph`
then refuses the real OSM ferry across the same gap as a duplicate of a ground
edge -- `ground_adjacent` is the test both use. So the model invents a road and
suppresses the crossing that actually exists.

## Four rules measured and REJECTED

Connected-component counts over the land cells in each box, before and after the
rule. Wanted: Saipan+Tinian 2 (separate islands), Messina 2 (ferry only, no
bridge), Honshu/Shikoku 1 (genuinely bridged -- Great Seto, Shimanami Kaido).

| rule | Saipan (want 2) | Messina (want 2) | Japan (want 1) |
|---|---|---|---|
| different land polygon | — | — | cuts 31/58 pairs at the **Oresund bridge** |
| midpoint is water | — | — | cuts 16/58 at Oresund |
| midpoint water AND no road | **2** ✓ | 1 ✗ | **3** ✗ splits the Inland Sea |
| 3-9 samples, 0.30-0.70 of the hop | 1 ✗ | 1 ✗ | 1-2 |

Two findings worth keeping:

1. **Sampling the ends re-admits the islands' own coastal roads**, so a wide
   window cuts nothing. Narrowing it to the middle then loses genuine bridges,
   which are also roads in the middle. There is no window that separates them:
   the sweep at 0.50 / 0.40-0.60 / 0.35-0.65 / 0.30-0.70 never scored the three
   cases correctly at once.
2. **Cutting the one offending edge is not enough.** With the midpoint rule the
   Saipan-Tinian edge IS cut, yet at wider windows the islands stay in one
   component: several cell pairs span that channel, not one. Any real fix must
   cut the whole crossing consistently, so a per-pair heuristic is fragile by
   construction.

## What the fix actually needs

The discriminator is not geometric. "Is there a fixed link here" is a fact about
the world, and OSM already carries it: ways tagged `bridge=yes` / `tunnel=yes`
carrying a highway. The repo already parses OSM PBF for rail and ferry
(`sources/osm.py`), so the shape is known -- a third pass collecting fixed links,
cached behind a `_params_hash` like the others, and `hex_edges` cutting an
adjacent pair whose connecting segment is water unless a fixed link covers it.

Restoring the suppressed ferry follows for free: once the ground edge is gone,
`build_graph` stops refusing the crossing as a duplicate.

## Two more rules measured and rejected, and the reason none can work

| rule | Saipan (want 2) | Messina (want 2) | Japan (want 1) |
|---|---|---|---|
| shared hexagon boundary sampled for land or road | 1 ✗ | 1 ✗ | 2 ✗ |
| OSM ferry crosses the gap | **no ferry exists** ✗ | 13 ferry ways ✓ | n/a |

The shared-boundary rule was the best-formed candidate -- the shared edge is
exactly where land or a bridge must cross -- and it still fails, because at a
coastline the GRIP4 raster shows a road on the boundary from the island's own
coastal road, and the boundary clips land on one side.

The ferry signal is the mirror image: it correctly identifies Messina (13 ways,
including `Messina - Villa San Giovanni`) and is useless for the reported case,
because **OSM has no ferry way across the Saipan Channel at all**. So the two
cheap signals cover disjoint cases and neither covers the one the owner hit.

**Why no heuristic on the data currently on disk can work.** The discriminator
is "does a fixed link exist here", and nothing in the repo's inputs answers it:

- GRIP4 is a rasterised road-density product. At a coastline it shows road on
  both shores, so any sample near the gap reads as roaded whether or not a span
  exists. It cannot distinguish a bridge from two coastal roads facing each other.
- The OSM extracts on disk are `*-rail.osm.pbf`, filtered by `scripts/osm_rail.sh`
  to `r/type=route,route=train`, `w/railway=rail`, `n/railway=station,halt`,
  `w/route=ferry`, `n/amenity=ferry_terminal`. **There are no highways in them
  at all**, and the script `rm`s the raw extract after filtering.

## The one path that works, and what it costs

Keep `w/bridge=yes` and `w/tunnel=yes` when filtering, then cut an adjacent land
pair whose shared boundary is water unless a fixed link covers it. That requires
re-downloading the full Geofabrik extracts: roughly 70 GB over the seven regions,
about 2.5-3 hours at the script's own 8 MB/s rate limit, on 1.1 TB of free disk.
The filter change itself is one line in `scripts/osm_rail.sh`; the parser is the
shape of `_ferries()`, and the cache needs its own `_params_hash` version.

Restoring the suppressed ferry still follows for free, and Messina would then be
fixed by either signal independently.

**Do not attempt another geometric heuristic.** Six have now been measured
(polygon identity, midpoint-water, midpoint-water-and-roadless, multi-sample at
four windows, shared boundary, ferry presence). The failure is not in the
formulation; it is that the input does not contain the fact.

## Implemented (2026-09-21): landmass identity + OSM fixed links

The rule that works, with no threshold anywhere:

> Two adjacent land cells are **severed** when their base cells' hexagons touch
> no land part in common AND no bridge or tunnel passes from one into the other.

Validated before implementation on real extracts, by named crossings:

| case | result | wanted |
|---|---|---|
| Great Seto Bridge, Honshu -> Shikoku | joined | joined |
| Akashi-Kaikyo, Kobe -> Awaji | joined | joined |
| Naruto Bridge, Awaji -> Shikoku | joined | joined |
| Shodoshima (ferry only) | cut | cut |
| Saipan -> Tinian (the owner's report) | cut | cut |

**A correction to the method above.** The rejection tables earlier in this file
score Japan against "one connected component". That target was never verified:
it is what the defective graph produced, and most Seto Inland Sea islands are
ferry-only, so the right answer was never one. The earlier rejections of the
midpoint rules for "splitting Japan" were judged against it and may have been
unfair to them. The conclusion stands on the named-crossing table instead.

| file | what |
|---|---|
| `sources/fixed_links.py` | bridge/tunnel ways carrying a highway or railway, C++-filtered (`KeyFilter`, `IdFilter`); kept only if they span >1 FINE_RES cell; per-region parquet keyed on parser constants AND source extract; returns None unless ALL seven regions are covered, settled before anything is parsed |
| `sources/landmask.py` | `land_cell_landmasses`: the parts each land cell touches, by the same polyfill as `land_cells`; Antarctic wedges share one id; pole cells map to `()` (never severed) |
| `graph/landmass.py` | `linked_pairs`, `severed_pairs` |
| `graph/nodes.py` | `NodeIndex.severed`, empty unless fixed-link data is complete -- optional like rail |
| `graph/refine.py` | `ground_joined(idx, u, v)`: the one definition of "joined" |
| `graph/ground.py` | `hex_edges` builds no road across a severed pair |
| `graph/build.py` | the ferry dedupe uses `ground_joined`, so a severed strait KEEPS its real ferry |
| `emit/modes.py` | a hop across a severed pair is booked as ferry, not road |
| `scripts/check_fixed_links.py` | the named crossings against the real built index |

Tests: `tests/sources/test_fixed_links.py` (15), `tests/graph/test_landmass.py`
(15). Seventeen mutations were run, each confirmed RED. One test was found
vacuous and rewritten: the antimeridian guard's first test looked up only the
two end cells, so with the guard deleted the long-way-round samples all missed
the lookup, the chain broke on its own, and the test stayed green.

### Stated limits (not defects of this change)

- **A strait narrower than a cell stays joined.** Parts are judged per base
  cell and carried down to fine children, so a base cell straddling a strait
  touches both shores. Messina (~3 km) is the known case, and the
  Helsingor-Helsingborg narrows (~4 km, ferry only) are why the graph joins
  Zealand to Sweden at all -- see the Oresund correction below. Severity MEDIUM,
  confidence High. Exit criterion: parts judged per FINE_RES cell in split
  regions, re-validated on the named crossings.
- **A bridge that spans a water cell adds no edge.** It links two cells that
  were never neighbours, so there was no road to protect and this change adds
  none. Measured cut before AND after this rule: the Great Belt, the
  Confederation Bridge, and the Oresund Bridge within 0.2 deg of it. This is a
  PRE-EXISTING gap, not one this change opens: long bridges and tunnels have never been in
  the ground graph. Severity MEDIUM, confidence High. Exit criterion: fixed
  links whose consecutive graph cells are non-adjacent become explicit ground
  edges, costed at the link's own length and road class; re-check Oresund,
  Great Belt and Confederation Bridge in `scripts/check_fixed_links.py`, which
  already reports them.

### Result on the real index (2026-09-22)

`scripts/check_fixed_links.py` against the index built from all seven verified
extracts: **22,121 adjacent cell pairs severed** worldwide, every judged case as
expected, 67 s once the caches exist. Each case was also run with `severed`
cleared, which is what says whether the rule did it:

| case | before | after |
|---|---|---|
| Great Seto, Akashi-Kaikyo, Naruto, Bosphorus, Kanmon, Geoga | joined | joined |
| **Saipan -> Tinian** (the owner's report) | joined | **cut** |
| **Shodoshima** (ferry only) | joined | **cut** |
| Paris -> Brussels (control) | joined | joined |
| Messina | joined | joined |
| Oresund | joined | joined |
| Great Belt | cut | cut |
| Confederation Bridge | cut | cut |

Exactly two cases changed, and both are the fix. No bridge was cut by it. The
Great Belt looked like a possible regression until the before column showed it
was always cut.

**Why one test run took 67 minutes.** `integration` tests are part of the gate
here and build the real index from the real cache. The first one to run after
the seventh extract arrived paid the one-time cost: the five uncached regions
parsed 17:18-17:35, and the landmass ids for ~4 million cells were written at
18:10. Both are cached now. It was not the network share, which was the first
guess. It also means the integration tests passed with severing active on real
data.

### First real parse, and a corrupted extract (2026-09-21)

| region | links kept | time | peak RSS |
|---|---|---|---|
| australia-oceania | 2,728 (2,263 highway, 465 railway) | 6 s | 2.2 GB |
| asia | 192,183 (144,523 highway, 47,660 railway) | 81 s | 6.3 GB |

The C++ filters (`KeyFilter`, `IdFilter`) made the parse ~30-40x faster than
the pure-Python probe (Oceania 234 s -> 6 s; Asia 41 min -> 81 s). On the
cached Oceania links: zero in the Saipan Channel, 23 at the Auckland Harbour
Bridge (the Northern Motorway it carries, and the City Rail Link tunnels).

**Europe failed to decompress, and the cause was the download script.**
Geofabrik rebuilds `<region>-latest` daily. The script re-resolved `-latest` on
every restart and resumed the old `.part` from wherever it now pointed, so the
reboot-and-restart sequence appended one day's bytes onto another's. Measured by
comparing each extract's PBF header date with the exact size of that day's
dated file:

| extract | header | on disk vs that day's file |
|---|---|---|
| australia-oceania | 2026-09-16 | exact |
| asia | 2026-09-16 | exact |
| **europe** | **2026-09-18** | **9.9 MB longer: a splice** |
| north-america | 2026-09-20 | exact |
| south-america | 2026-09-20 | exact |

The first fix pinned the redirect target, and was itself wrong: for europe,
`-latest` redirects to a MIRROR path that is also named `europe-latest`, so it
pinned nothing. Nor would the size check have caught it -- a splice ends with
the last day's bytes, so its total length is exactly that of the `-latest` file
at the end. The fix that holds: the script reads the day from
`<region>-updates/state.txt`, pins `download.geofabrik.de/<region>-<YYMMDD>.osm.pbf`
(a name that never changes) beside the `.part`, resumes only that URL, and
finalises only when the size equals that dated file's length. A `.part` with no
recorded source is refused rather than resumed.

The spliced file was moved aside, not deleted: `data/cache/osm/europe.osm.pbf.spliced`
(35,015,204,476 B), plus a few MB of `.moving-latest` partials. Removing them is
the owner's call. `scripts/osm_rail.sh` resumes the same unsafe way; there a
splice fails loudly in `osmium tags-filter` rather than silently, so it is
recorded here and not changed.

### Measured on the shipped artifacts (rebuild25, Seoul), and one thing it does NOT fix

Seoul's newly built files against the live ones, read out of the reading tier
(res-6 per cell), which is what the bands are drawn from:

| cell | live | rebuilt | change |
|---|---|---|---|
| Saipan, airport side | 7 h 48 | 7 h 48 | 0 |
| Saipan, south tip | 7 h 48 | 7 h 48 | 0 |
| Tinian north | 7 h 54 | **9 h 42** | **+108 min** |
| Tinian centre | 7 h 56 | 9 h 36 | +100 min |
| Tinian south | 8 h 10 | 9 h 39 | +89 min |

Tinian was 6 minutes past Saipan -- the phantom drive. It is now ~1 h 50 past
it: the SPN->TIQ flight plus airport time at both ends. Saipan is untouched.

**The hover readout over Tinian still shows Saipan's answer.** At HOVER_RES 4 a
cell is ~22 km across and Saipan and Tinian share ONE (`844f4b5ffffffff`). Its
centre child is water, so `hover._representative_children` falls back to the
FASTEST child, which is on Saipan because Saipan has the airport. Measured:
that cell reads 460 min (7 h 40) in both the live and the rebuilt array, +0.

So after this rebuild the BAND over Tinian is correct and visibly darker than
Saipan, while hovering it reports a neighbouring island's journey. That is a
display-resolution limit, not a modelling one, and it predates this change:
any res-4 cell holding two islands has always reported the faster.

- Severity LOW-MEDIUM, confidence High (measured). It is the owner's original
  complaint only in part: the model no longer claims a highway, but the number
  under the cursor is still Saipan's.
- Exit criterion: for a hover cell whose children span more than one landmass,
  the page resolves the reading tier (res 6, already shipped, already fetched
  on origin switch) at the cursor instead of the hover array -- no new artifact
  and no rebuild. Verify that hovering Tinian reads ~9 h 40 while Saipan reads
  ~7 h 48.

### Not yet done

- ~~The other four extracts are downloading~~ -- done 2026-09-22; all seven
  verified against their dated files' exact lengths.
- ~~`scripts/check_fixed_links.py` not yet run~~ -- run; see the result above.
- ~~No rebuild has carried this~~ -- rebuild25 (1,464/1,464, 0 errors, exit
  09-24 10:04) deployed 2026-09-24, ALL CHECKS PASSED, 0 console errors, four
  viewports. Read back from the LIVE seoul.r6.bin: Saipan 7 h 48, Tinian north
  9 h 42, Tinian centre 9 h 36. The hover-readout limit above still applies.

## Status

- **Severity: MEDIUM-HIGH, confidence High.** User-visible and wrong; the number
  shown is a road time for a sea crossing. Not deferred for lack of importance
  but because every measured fix was a net regression.
- **Not in `rebuild23`** (started 11:05, rail service tiers only). Shipping an
  unvalidated graph change into a 37-hour build would have traded a phantom road
  in the Marianas for broken bridges in Japan.
- **Exit criterion:** a fixed-link source exists and, on the four labelled boxes
  above, scores Saipan+Tinian 2, Messina 2, Oresund unchanged, Honshu/Shikoku 1.
  Only then rebuild.
- **Note, corrected 2026-09-22:** "Oresund measured 2 components" came from a
  box that stopped short of Helsingor. Copenhagen and Malmo ARE joined in the
  graph, before and after this rule, but not by the bridge: within 0.2 deg of it
  they are cut. The join is 40 km north, across the ~4 km Helsingor-Helsingborg
  narrows, which only ferries cross -- a phantom of the narrow-strait limit.

---

# Appendix: the KTX label residue (separate defect, recorded here to keep it alive)

Verified against the LIVE `seoul.rail.json` after the rail-tier build deployed
2026-09-19. The systematic AA17 defect is fixed -- labels now follow the service
the leg was priced from -- but one case remains:

| station | label shipped | correct? |
|---|---|---|
| 동대구 | `경부선 KTX: 서울 → 부산` | yes, the plain corridor |
| 밀양 | `경부선 KTX: 서울 → 부산 (구포경유)` | yes, only that route serves it |
| 구포 | `경부선 KTX: 서울 → 부산 (구포경유)` | yes by definition |
| **부산** | `경부선 KTX: 서울 → 부산 (수원경유)` | **no** -- a detour variant where the plain corridor also serves the station |

Cycle 17's `619d804` ("name the corridor, not a detour variant, on a single-hop
ride") addressed this shape but does not cover the destination station here.

- Severity LOW, confidence High. The label is a real service that does reach
  부산, so the figure is not wrong; the naming is just less useful than the plain
  corridor the owner asked for ("그냥 경부선 호남선은 왜 안떠?").
- Exit criterion: for a station served by both a plain corridor relation and a
  `(...경유)` variant at equal cost, the plain one is named. Verify on the live
  `seoul.rail.json` that 부산 reads `경부선 KTX: 서울 → 부산`.
- Needs no rebuild if fixed in `emit/rail_detail.py` alone AND re-emitted; but
  re-emitting per-origin rail files is a build step, so it rides the next build.
