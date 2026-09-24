"""Which station, line, operator and service number a rail leg used, per cell.

"By rail, 3 h" is the aggregate; this names the last station alighted at, the
line that reached it, who runs it and what the service is called -- "KTX
경부선 to Busan, Korail, 101". One uint16 per hover cell (181,480 bytes over
90,740 cells) indexes a per-origin table of the stations actually used, which
is a few thousand rows rather than the 257,000 stops in the network.

`operator` and `ref` were added because the owner asked for more of this kind
of detail. Coverage measured over all 19,297 train route relations: `operator`
92%, `ref` 88%, and `operator` is the only one of the candidate fields whose
coverage survives leaving Europe. `network` (67%), `colour` (39%) and `via`
(19%) were measured and declined; `2026-09-15-c14-rail-service-tiers.md` says
why for each. The cost is +19.9 KB gzipped per origin against `.r6.bin`'s
5.33 MB on the same city switch.
"""

from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path

import h3
import numpy as np
import polars as pl

from transport_maps import _io, config

NO_RAIL = 0xFFFF
# Ordinal for "this route carries no `operator` tag". 8% of route relations
# worldwide, and 20% in Africa, so it is the common case somewhere and the page
# must render it as an absence rather than as a blank label.
NO_OPERATOR = -1


def last_station_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray) -> np.ndarray:
    """For every node, the station node it was last reached through (-1: none).
    One pass in distance order, as for airports in itinerary.py."""
    n = len(minutes)
    last = np.full(n, -1, dtype=np.int64)
    first_station = idx.n_cells + 2 * len(idx.airports)
    finite = np.isfinite(minutes)
    for node in np.argsort(np.where(finite, minutes, np.inf), kind="stable"):
        node = int(node)
        if not finite[node]:
            break
        if node >= first_station:
            last[node] = node
            continue
        prev = int(predecessors[node])
        if prev >= 0:
            last[node] = last[prev]
    return last


# How far back along the traveller's own rail path to look when several
# services tie for a hop. Eight is past the point where any tie survives: the
# owner's case is settled by ONE preceding hop, and the longest tie chain
# measured over the real network is three. The walk is O(1) work per step over
# a chain already in memory, so the cap is about bounding a pathological input,
# not about cost.
PATH_LOOKBACK_HOPS = 8


def _route_stop_counts(routes: pl.DataFrame) -> dict[int, int]:
    """`route_id` -> how many stops the route calls at.

    Used ONLY as the last tie-break in `pick_route`, among services that
    already tie for fastest and that the traveller's own path could not
    separate. See the note there for why that is a presentation choice and not
    a second, competing definition of which train set the time.
    """
    counts = routes.group_by("route_id").len()
    return {int(r): int(n) for r, n in zip(counts["route_id"], counts["len"])}


def _route_labels(routes: pl.DataFrame) -> dict[int, tuple]:
    """`route_id` -> `(name, operator, ref)`.

    Held once per ROUTE rather than once per station pair. There are 16,781
    routes and 147,332 directed pairs, so keying the strings here and the ids
    on the pairs is also the smaller of the two, which matters because this
    whole structure is inherited by every forked worker.
    """
    have = set(routes.columns)
    out: dict[int, tuple] = {}
    first = routes.group_by("route_id", maintain_order=True).first()
    for rid, name, operator, ref in zip(
            first["route_id"],
            first["route_name"] if "route_name" in have else first["route_id"],
            first["operator"] if "operator" in have else first["route_id"],
            first["ref"] if "ref" in have else first["route_id"]):
        out[int(rid)] = (name if "route_name" in have else "",
                         operator if "operator" in have else "",
                         ref if "ref" in have else "")
    return out


def _line_between(routes: pl.DataFrame, cal) -> dict[tuple[str, str], tuple[int, ...]]:
    """`(from, to)` -> the route ids that TIE for fastest over that hop.

    Three things this gets right that earlier versions did not.

    **The caption names a service that could have set the time.**
    `ride_edges` resolves parallel services on a shared segment by
    `min(minutes)`; this used to resolve them by `setdefault` over
    `group_by("route_id")`, which keeps the LOWEST OSM RELATION ID. Those are
    unrelated orderings. Measured over the whole network, 119,973 directed hops
    a route actually runs: **5,168 (4.31%) were captioned with a strictly
    slower service than the one the traveller was charged for, and 3,647 of
    those with a train of the wrong speed class.** Under this rule the same
    count is 0, by construction rather than by luck -- the candidate set IS the
    set of routes achieving the minimum. (`plan/deferred.md` AA17 quotes 10.35%
    for the same defect; that is the share of shipped ROWS, weighted by how
    often each hop ends a journey, and needs a build to measure. 4.31% is the
    share of hops in the network, which does not.)

    **A tie is kept as a tie.** Taking the single minimum was not enough, and
    the owner found the case that proves it. `경부선 KTX: 서울 → 부산 (구포경유)`
    (relation 11208904, seven stops) and `경부선 KTX: 서울 → 부산` (11214334,
    four stops) share exactly one hop, 대전 -> 동대구. Both are `high_speed`,
    so over the same two stations they cost the SAME minutes to four decimal
    places -- `minutes < best` is false, the first seen wins, and the first
    seen is the lower relation id. The detour variant therefore captioned the
    hop every time. Every route achieving the minimum is now kept, and the
    choice among them is made where there is something to choose with.

    **The reverse direction is not filled with the forward name.** OSM route
    names are directional -- `경부선 KTX: 서울 → 부산`, `東急東横線: 横浜 => 渋谷`
    -- and `setdefault((b, a), name)` filled the reverse key from the forward
    service. Measured: of 147,332 entries the old table held, exactly 73,666
    (50.0%) came from a service running the OPPOSITE way, and 58,528 of the
    117,056 arrow-named entries were among them. Only 27,359 of those hops are
    genuinely one-way in OSM; for the rest a correctly-directed relation
    existed and was passed over. Forward is now kept strictly, and an
    opposite-direction service is a documented fallback for the 27,359 -- where
    it is the best available answer rather than a wrong one.
    """
    from transport_maps.graph.rail import _haversine_km, station_key

    df = routes.sort(["route_id", "seq"]).with_columns(
        pl.struct("lat", "lon").map_elements(lambda s: station_key(s["lat"], s["lon"]),
                                             return_dtype=pl.Utf8).alias("station"))
    # A tie is an equality between floats produced by the same arithmetic on
    # the same inputs, so it is exact -- but rounding keeps that true when two
    # relations place "the same" station on coordinates metres apart, which is
    # the normal case in OSM. A hundredth of a minute is 0.6 seconds.
    quant = 2
    fwd: dict[tuple[str, str], tuple[float, list[int]]] = {}
    rev: dict[tuple[str, str], tuple[float, list[int]]] = {}
    for rid, g in df.group_by("route_id", maintain_order=True):
        route_id = int(rid[0] if isinstance(rid, tuple) else rid)
        st = g["station"].to_list()
        lat, lon = g["lat"].to_list(), g["lon"].to_list()
        tier = g["tier"][0] if "tier" in g.columns else None
        t = cal.tiers.get(tier) if tier is not None else None
        for i, (a, b) in enumerate(pairwise(st)):
            if a == b:
                continue
            if t is None:
                minutes = 0.0
            else:
                km = float(_haversine_km(lat[i], lon[i], lat[i + 1], lon[i + 1]))
                minutes = round(
                    t.stop_overhead_min + 60.0 * km * cal.detour_factor / t.speed_kmh, quant)
            for store, key in ((fwd, (a, b)), (rev, (b, a))):
                best = store.get(key)
                if best is None or minutes < best[0]:
                    store[key] = (minutes, [route_id])
                elif minutes == best[0]:
                    best[1].append(route_id)
    out = {k: tuple(v[1]) for k, v in fwd.items()}
    for k, v in rev.items():
        out.setdefault(k, tuple(v[1]))
    return out


def _walk_back_hops(idx, predecessors, node, first_station) -> list[tuple[str, str]]:
    """The traveller's last rail hops, nearest the destination first.

    This is the discriminator the per-hop view does not have. Where several
    services tie over one hop, the one the traveller was actually ON is the one
    that also serves the hop BEFORE it: riding 서울 -> 대전 -> 동대구, only the
    four-stop `경부선 KTX: 서울 → 부산` covers both, because the seven-stop
    variant calls at 광명 in between and so has no 서울 -> 대전 hop at all.
    """
    hops: list[tuple[str, str]] = []
    while len(hops) < PATH_LOOKBACK_HOPS and node >= first_station:
        prev = int(predecessors[node])
        if prev < first_station:
            break
        hops.append((idx.stations[prev - first_station],
                     idx.stations[node - first_station]))
        node = prev
    return hops


def pick_route(hops: list[tuple[str, str]], lines: dict, stop_counts=None) -> int | None:
    """Which tied service the traveller rode, from their own sequence of hops.

    Scored by how many CONSECUTIVE hops back from the destination a candidate
    also serves. Candidates are only ever the routes that tie for fastest over
    the final hop, so this decides presentation among services that are
    genuinely interchangeable on time -- it can never name a slower train than
    the one the traveller was charged for, which is the property AA17 is about.

    **The last resort, and why it is not the rule in disguise.** A single-hop
    ride has no preceding hop to score with: board at 대전, alight at 동대구,
    and both KTX services serve exactly that and nothing else of the journey.
    Something has to choose, and it has to be deterministic or the same journey
    captions differently between builds. Fewest stops wins, then lowest
    relation id.

    Choosing the service that makes the fewest calls is a PRESENTATION choice
    among names that are equally true: `경부선 KTX: 서울 → 부산` describes the
    corridor, `경부선 KTX: 서울 → 부산 (구포경유)` describes a variant of it,
    and a reader on a 대전 -> 동대구 leg is told something useful by the first
    and something irrelevant by the second. It is deliberately the LAST rule
    rather than the first: used on its own it would be exactly the "reduce the
    symptom while letting the label and the time diverge again" trap, because
    the shortest service is not generally the fastest one. Applied only to
    routes already tied for fastest AND already indistinguishable on the
    traveller's path, it cannot move the named service away from the one that
    set the time -- there is nothing left for it to move away from.
    """
    if not hops:
        return None
    candidates = lines.get(hops[0])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    counts = stop_counts or {}
    best, best_key = None, None
    for rid in candidates:
        depth = 0
        for hop in hops[1:]:
            also = lines.get(hop)
            if not also or rid not in also:
                break
            depth += 1
        # Deeper path coverage first; then fewest stops; then lowest id.
        key = (-depth, counts.get(rid, 0), rid)
        if best_key is None or key < best_key:
            best, best_key = rid, key
    return best


def lookup_tables(routes: pl.DataFrame | None, cal=None) -> dict:
    """Everything the per-origin writer needs, as plain dicts.

    Built ONCE in the build's parent process. The writer runs in forked
    workers, and polars' thread pool does not survive a fork: a worker that
    touches a DataFrame blocks on the pool's lock forever, which is exactly
    how the first mixed-resolution build sat for three hours with eight idle
    processes and no output.

    `cal` is the rail calibration, needed only to score which of several
    services on a shared segment is the one the edge was priced from. It is
    loaded here when the caller does not supply it, so the parent pays the
    tomllib read once rather than every forked worker.
    """
    if routes is None:
        return {"lines": {}, "stop_names": {}, "route_label": {}, "route_stops": {}}
    from transport_maps.graph.rail import load_rail_calibration, station_key

    stop_names: dict[str, str] = {}
    for lat, lon, nm in zip(routes["lat"].to_list(), routes["lon"].to_list(), routes["name"].to_list()):
        # A stop with no name of its own stays empty rather than taking the
        # first named route through it; `railVia` degrades on the empty string.
        stop_names.setdefault(station_key(lat, lon), nm or "")
    return {"lines": _line_between(routes, cal or load_rail_calibration()),
            "route_label": _route_labels(routes),
            "route_stops": _route_stop_counts(routes),
            "stop_names": stop_names}


def boarded_within(idx, predecessors, hops, first_station) -> bool:
    """Whether `hops` reaches back to where the traveller boarded.

    `_walk_back_hops` stops at PATH_LOOKBACK_HOPS; a ride longer than that is
    traced only in part, and a station missing from a PART of the path says
    nothing about whether the train called there.
    """
    if not hops:
        return False
    if len(hops) < PATH_LOOKBACK_HOPS:
        return True
    boarding = idx.station_index(hops[-1][0])
    return int(predecessors[boarding]) < first_station


# "(수원경유)" / "(via Suwon)": a qualifier naming where a variant of a line
# calls. Anchored at the END of the name, where OSM puts it.
_VIA = (re.compile(r"\s*\(([^()]*?)\s*경유\)\s*$"), re.compile(r"\s*\(via ([^()]+)\)\s*$", re.I))


def drop_false_via(line: str, path_stations: set[str], complete: bool) -> str:
    """The line's name without a "via X" qualifier the traveller never passed.

    The owner's case, traced on a real Seoul solve: the path into 부산 rides
    서울역 -> 대전 on the plain KTX and then 대전 -> 부산 as ONE hop, which only
    `경부선 KTX: 서울 → 부산 (수원경유)` has -- OSM's relation for it lists no
    stop at 동대구, so its hop is non-stop and the fastest. Naming that service
    for the leg is AA17's rule and stays; saying "via 수원" to someone whose
    path never went near 수원 is simply false for THIS journey. The corridor
    name is what is true, so that is what is printed.

    Only when the path was traced to the boarding station (`complete`):
    otherwise X may be on the untraced part and the qualifier may be right.
    """
    if not complete:
        return line
    for pattern in _VIA:
        m = pattern.search(line)
        if m:
            vias = [v.strip() for v in re.split(r"[,·/]", m.group(1)) if v.strip()]
            if vias and not all(v in path_stations for v in vias):
                return line[:m.start()].rstrip()
            return line
    return line


def write_rail_detail(idx, minutes: np.ndarray, predecessors: np.ndarray,
                      tables: dict | None, out_bin: Path, out_json: Path, *,
                      parents: list[str] | None = None,
                      rep: dict[int, int] | None = None) -> None:
    """`.rail.bin`: uint16 per hover cell into `.rail.json`'s station table.
    `tables` is `lookup_tables(routes)`; None or empty means no rail."""
    from .hover import _representative_children

    if parents is None:
        parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    chosen = np.full(len(parents), NO_RAIL, dtype=np.int64)
    table: list[list] = []
    # Operator names repeat across nearly every row -- one railway runs hundreds
    # of a city's reachable stations -- so they are interned into their own
    # array and the row carries an ordinal. Measured on a real 2,110-row table:
    # inline costs 10.7 gzipped bytes a row, interned 9.4, and the raw file is
    # 26 KB smaller. NO_OPERATOR (-1) is "OSM did not say", which the page
    # prints as nothing at all rather than as an empty bracket.
    operators: list[str] = []
    op_index: dict[str, int] = {}
    if tables and tables.get("lines") and len(idx.stations):
        first_station = idx.n_cells + 2 * len(idx.airports)
        last = last_station_per_node(idx, minutes, predecessors)
        lines, stop_names = tables["lines"], tables["stop_names"]
        route_label = tables.get("route_label") or {}
        index: dict[tuple, int] = {}
        if rep is None:
            rep = _representative_children(idx, parents, minutes[: idx.n_cells])
        for p, pos in rep.items():
            node = int(last[pos])
            if node < 0:
                continue
            station = idx.stations[node - first_station]
            # The traveller's OWN last hops, not just the final one. Several
            # services can tie for fastest over one hop; the hop before it is
            # what says which of them this journey was on.
            hops = _walk_back_hops(idx, predecessors, node, first_station)
            rid = pick_route(hops, lines, tables.get("route_stops"))
            line, operator, ref = route_label.get(rid, ("", "", "")) if rid is not None \
                else ("", "", "")
            passed = {stop_names.get(s, "") for hop in hops for s in hop}
            line = drop_false_via(line, passed,
                                  boarded_within(idx, predecessors, hops, first_station))
            key = (station, line, operator, ref)
            if key not in index:
                if operator and operator not in op_index:
                    op_index[operator] = len(operators)
                    operators.append(operator)
                index[key] = len(table)
                table.append([stop_names.get(station, ""), line,
                              op_index.get(operator, NO_OPERATOR), ref])
            chosen[p] = index[key]
    if len(table) >= NO_RAIL:
        # np.minimum used to fold any index past the sentinel into "no rail"
        # silently; a table that large is a bug, not a build.
        raise ValueError(f"rail table has {len(table):,} rows; uint16 holds {NO_RAIL - 1:,}")
    _io.write_bytes(out_bin, chosen.astype("<u2").tobytes())
    _io.write_text(out_json, json.dumps(
        {"fields": ["station", "line", "operator", "ref"],
         "operators": operators, "stations": table},
        ensure_ascii=False, separators=(",", ":")))
