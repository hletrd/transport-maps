# Cycle 14 — two owner requests, recorded and not implemented

Both arrived mid-run, by message, while cycle 14 held the working tree. Neither
is scheduled here: each changes what the solver charges an edge, and cycle 14's
brief was the rail tiers. This file exists so neither is lost, per the run rule
that a user-injected TODO is never dropped.

Recorded by the orchestrator after cycle 14 returned, because the cycle did not
record them. The working tree was clean and the cycle finished before this was
written, so nothing here raced its commits.

---

## R1 — carry-on only, no checked baggage

**Owner's words:** "and please note to add option to not include luggage in
airport. if only carry-onss are carried it save much time."

The request is well founded: the model already charges baggage time, in two
named constants, and `calibration.toml` says so in its own comments.

| constant | large | medium | small | what its comment says it covers |
|---|---|---|---|---|
| `[processing_min]` | 70 | 55 | 40 | check-in, bag drop, security, walk to gate |
| `[disembark_min]` | 30 | 22 | 15 | "Deplane, walk, and **wait at the belt**. No border component." |
| `[border_min]` | 45 | 35 | 25 | emigration + immigration — **no baggage component** |
| `[connection_min]` | 75 | 50 | 35 | minimum connection time — **no baggage component** |

All four are published-figure defaults, not fitted. Carry-on removes the belt
wait outright and some share of check-in; it touches neither of the lower two.

### Three traps, in the order they will be hit

**1. The split does not exist in the data.** `processing_min` is ONE number
covering bag drop AND security AND the walk. There is no bag component to
subtract. Whoever builds this must either declare new constants with stated
provenance, or state plainly in the file that the split is an assumption and
what it is. Inventing the number quietly is precisely what CLAUDE.md forbids:
"Never silently tune a default to match a handful of hand-picked routes: prefer
a documented, reproducible error over a hidden one."

**2. The bands are a with-bags answer and stay one.** The coloured isochrones
come from a solve that charged checked baggage. A client-side adjustment can
honestly restate the time for the itinerary already on screen — the page knows
which airports and their sizes — but it cannot change the colours underneath
without a rebuild or the on-demand solver. A control that changes the number
while the map means something else must SAY so on the page. Shipping it silent
is the same class of defect as the rail caption cycle 14 just fixed: a true
number attached to the wrong thing.

**3. It is not separable from R2.** Both change edge costs and both change which
route wins — a shorter airport dwell can make a two-flight itinerary beat a
one-flight one, so the saving is not a constant that can be subtracted per
airport in the general case. Design them together.

- [ ] **R1.1** Decide and document the bag share of `processing_min`, with
      provenance, or record why it cannot be split.
- [ ] **R1.2** Decide where it evaluates: page-side for the selected itinerary
      (cheap, honest only if disclosed) or solver-side (correct, needs R2's
      service).
- [ ] **R1.3** If page-side, the disclosure text is part of the deliverable, not
      a follow-up.

---

## R2 — preferred and excluded modes

**Owner's words:** "add filter (not prefered way to move) and select for
prefered way."

The owner's decision, relayed to cycle 14 and restated here so it survives:

**Exclusion is precomputable; weighting is not.** Excluding a mode is one more
map — `build_graph` already accepts `rail_routes=None` and `ferry_links=None`,
so "no flights", "no ferries", "no trains" are three more builds of the same
shape as the current one. Weighting is a continuum: "prefer rail 1.5x" has no
finite set of precomputed answers. That makes weighting the on-demand solver's
headline feature rather than a build-time artifact (cycle 13's design:
3.40 GiB resident, 207 s cold start — see `2026-09-14-c13-solver-service.md`).

**A weighted solve changes the winning route,** so everything derived from the
path must follow it: the itinerary, the mode breakdown, and the rail naming
cycle 14 just corrected. A weighting control that re-colours the bands but
leaves the itinerary from the unweighted solve would reintroduce exactly the
mismatch that made 20.9% of rail captions wrong.

- [ ] **R2.1** Exclusion: decide whether the three extra builds are worth the
      storage and hours, or whether exclusion also waits for the solver.
- [ ] **R2.2** Weighting: solver-side only. Do not attempt a page-side
      approximation — there is no sound one.
- [ ] **R2.3** Whichever ships, the itinerary, modes and rail naming are
      recomputed from the same solve that produced the colours.

---

## Status

Neither is scheduled for a cycle. Both are blocked on the same decision — does
the on-demand solver get built — which is the owner's, not a cycle's. Exit
criterion for both rows: that decision is made, either way.
