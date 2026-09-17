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
- **Note:** Oresund measured 2 components BEFORE any rule. That bridge is
  already missing from the model — a separate, pre-existing gap, not caused by
  anything here.
