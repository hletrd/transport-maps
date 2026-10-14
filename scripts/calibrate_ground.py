#!/usr/bin/env python3
"""Sample real driving journeys and fit the ground model's road speeds and
urban penalty.

    uv run python scripts/calibrate_ground.py plan    --out data/build/ground_plan3.json
    source ~/.config/transport-maps/env
    uv run python scripts/calibrate_ground.py observe --plan data/build/ground_plan3.json \\
                                                      --out data/build/ground_samples3.json
    uv run python scripts/calibrate_ground.py fit     --samples data/build/ground_samples3.json

Three steps because they want different machines: `plan` builds the ground
graph (about 10 M cells, ~13 GB) and walks every sampled journey's path, with
no network; `observe` asks Google Routes for each journey's driving time and
needs the API key and nothing else; `fit` is arithmetic.

One Dijkstra per SOURCE town, not per journey: solving once and taking many
destinations off the same tree turns a prohibitive 1,000 solves into 50.

Each journey is recorded as kilometres per GRIP4 road class per distance band
from the nearest city of [urban] pop_min or more (calibrate/ground.py
DIST_BANDS_KM), unweighted -- so the fit can try the urban penalty at every
radius on a band edge and per class group, rather than inheriting the one the
graph was weighted with. Two kinds of journey: between populated places
(8-600 km), and from a populated place to its nearest medium or large airport,
the access leg every flown journey on the map starts and ends with.

Earlier runs, both fitted with the OLS in calibrate/ground.fit_speeds and
kept in data/build/ (gitignored): 1,383 journeys (ground_samples.json) fitted
the urban factor, 2,998 (ground_samples2.json) the per-class speeds. They
recorded class kilometres already multiplied by the urban factor, so they
cannot fit a different penalty; this format replaces them. Nothing from any
of them reaches dist/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from transport_maps import config
from transport_maps.calibrate import ground as gfit

N_CLASSES = 6
FOLDS = 5
N_BANDS = len(gfit.DIST_BANDS_KM) + 1
NAMES = ["roadless", "highway", "primary", "secondary", "tertiary", "local"]


def _towns(path) -> np.ndarray:
    gaz = json.loads(path.read_text(encoding="utf-8"))
    return np.array([[r[3], r[4]] for r in gaz["places"]], dtype=float)


def _airports(path) -> np.ndarray:
    table = json.loads(path.read_text(encoding="utf-8"))
    return np.array([[r[3], r[4]] for r in table["airports"] if r[5] in ("medium", "large")],
                    dtype=float)


def plan(args) -> None:
    import gc

    import h3
    import scipy.sparse as sp

    from transport_maps.graph import ground as gmodel
    from transport_maps.graph import nodes
    from transport_maps.sources import countries, urban

    # As build-all does (cli._build_all): with the collector on, Python 3.14's
    # young collections scan the whole old heap, and a 10 M-cell index made a
    # 40-minute setup of a 15-minute one.
    gc.disable()
    rng = np.random.default_rng(args.seed)
    towns = _towns(args.places)
    airports = _airports(args.airports)
    print(f"  {len(towns):,} populated places, {len(airports):,} medium/large airports")

    idx = nodes.build_index()
    classes = gmodel.cell_class(idx).astype(np.int64)
    speeds = gmodel.cell_speed_kmh(idx, classes)
    country = countries.cell_country(idx.cells)
    zone = gmodel.cell_zones(country)
    r, c, d = gmodel.hex_edges(idx, speeds=speeds, country=country, zone=zone)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    centroids = np.array([h3.cell_to_latlng(x) for x in idx.cells[: idx.n_cells]])

    # Distance from each cell to the nearest city of [urban] pop_min or more,
    # by the same equirectangular measure sources/urban.urban_mask uses.
    plat, plon = urban._places()
    near = np.full(len(centroids), np.inf)
    coslat = np.cos(np.radians(centroids[:, 0]))
    for la, lo in zip(plat, plon):
        dd = np.hypot((centroids[:, 0] - la) * 111.0, (centroids[:, 1] - lo) * 111.0 * coslat)
        np.minimum(near, dd, out=near)
    band = gfit.band_of(near)

    def walk(pred, src, dst):
        km = np.zeros((N_CLASSES, N_BANDS))
        n, guard = int(dst), 0
        while n != src and pred[n] >= 0 and guard < 6000:
            p = int(pred[n])
            if zone[p] != zone[n]:
                return None              # a border: Google does not wait at one
            seg = gmodel.haversine_km(centroids[p][None, :], centroids[n][None, :])[0]
            km[classes[n], band[n]] += seg
            n, guard = p, guard + 1
        return km if n == src else None

    rows = []
    for s in range(args.sources):
        town = towns[rng.integers(0, len(towns))]
        src = idx.try_cell_index(idx.cell_at(town[0], town[1]))
        if src is None:
            continue
        minutes, pred = sp.csgraph.dijkstra(csr, indices=[src], return_predecessors=True)
        minutes, pred = minutes[0], pred[0]
        here = centroids[src]
        picks = []
        box = (np.abs(towns[:, 0] - town[0]) < 6.0) & (np.abs(towns[:, 1] - town[1]) < 6.0)
        cand = sorted({j for t in towns[box]
                       if (j := idx.try_cell_index(idx.cell_at(t[0], t[1]))) is not None
                       and j != src and np.isfinite(minutes[j])})
        if cand:
            cand = np.array(cand)
            km = gmodel.haversine_km(np.repeat(here[None, :], len(cand), axis=0), centroids[cand])
            cand = cand[(km >= 8.0) & (km <= 600.0)]
            if len(cand):
                picks += [("towns", int(j)) for j in
                          rng.choice(cand, size=min(args.per_source, len(cand)), replace=False)]
        da = gmodel.haversine_km(np.repeat(here[None, :], len(airports), axis=0), airports)
        k = int(np.argmin(da))
        if 3.0 <= da[k] <= 150.0:
            j = idx.try_cell_index(idx.cell_at(*airports[k]))
            if j is not None and np.isfinite(minutes[j]):
                picks.append(("airport", int(j)))
        for kind, dst in picks:
            km = walk(pred, src, dst)
            if km is None or km.sum() < 3.0:
                continue
            rows.append({"source": s, "kind": kind,
                         "from": [round(float(v), 5) for v in here],
                         "to": [round(float(v), 5) for v in centroids[dst]],
                         "km": np.round(km, 3).tolist(),
                         "model_min": round(float(minutes[dst]), 2)})
        print(f"  source {s + 1}/{args.sources}: {len(rows)} journeys", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"bands_km": list(gfit.DIST_BANDS_KM), "journeys": rows}),
                        encoding="utf-8")
    print(f"  wrote {len(rows)} journeys to {args.out}")


def observe(args) -> None:
    import httpx

    planned = json.loads(args.plan.read_text(encoding="utf-8"))
    budget = gfit.RequestBudget(args.max_requests)
    done, unrouted = [], 0
    with httpx.Client() as client:
        for row in planned["journeys"]:
            try:
                got = gfit.drive_minutes(client, budget, tuple(row["from"]), tuple(row["to"]))
            except RuntimeError:
                break
            except httpx.HTTPError as exc:
                print(f"  request failed: {exc}")
                continue
            gfit.sleep_between()
            if got is None:
                unrouted += 1
                continue
            done.append({**row, "observed_min": round(got, 2)})
            if len(done) % 50 == 0:
                print(f"  {len(done)} observed, {budget.used} requests", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({**planned, "journeys": done, "requests": budget.used,
                                    "unrouteable": unrouted}), encoding="utf-8")
    print(f"  {len(done)} journeys observed, {budget.used} requests, {unrouted} unrouteable;"
          f" wrote {args.out}")


def _stats(obs, pred):
    r = obs / pred
    return (f"median {np.median(r):.3f}  p10 {np.percentile(r, 10):.2f}  p90 "
            f"{np.percentile(r, 90):.2f}  |log| {np.median(np.abs(np.log(r))):.3f}")


def fit(args) -> None:
    data = json.loads(args.samples.read_text(encoding="utf-8"))
    rows = data["journeys"]
    if tuple(data["bands_km"]) != gfit.DIST_BANDS_KM:
        raise SystemExit(f"{args.samples} has bands {data['bands_km']}, this code {gfit.DIST_BANDS_KM}")
    km = np.array([r["km"] for r in rows])
    y = np.array([r["observed_min"] for r in rows])
    kind = np.array([r["kind"] for r in rows])
    src = np.array([r["source"] for r in rows])
    # Five folds by SOURCE: journeys from one town share most of their roads,
    # so holding out single journeys would score a structure on roads it was
    # fitted on.
    rng = np.random.default_rng(0)
    sources = np.unique(src)
    fold_of = dict(zip(sources.tolist(), rng.permutation(len(sources)) % FOLDS))
    fold = np.array([fold_of[s] for s in src])
    towns, access = kind == "towns", kind == "airport"
    # Each kind carries half the weight, in the speed fit and in the score:
    # 53 access journeys against 700 between towns would otherwise leave the
    # access leg -- in every flown journey twice -- to whatever suits the rest.
    w = np.where(access, 0.5 / access.sum(), 0.5 / towns.sum())
    print(f"  {len(y)} journeys ({int(access.sum())} airport access), {len(sources)} sources, "
          f"{FOLDS} folds by source")

    fixed = np.array([5.0, np.nan, np.nan, np.nan, np.nan, 25.0])
    current = np.array([5.0, 104.0, 57.0, 50.0, 18.0, 25.0])
    one = np.zeros(N_CLASSES, dtype=int)
    two = np.array([0, 0, 1, 1, 1, 1])          # highway apart from the rest

    def report(label, p):
        print(f"    {label:9} towns {_stats(y[towns], p[towns])}")
        print(f"    {'':9} access {_stats(y[access], p[access])}")

    print("\n  shipped: speeds 104/57/50/18, radius 40, x2.0 every class")
    report("", gfit.predict(km, current, 40.0, one, np.array([2.0])))

    def score(radius, groups, factors):
        """Out-of-fold predictions; the mean of the two journey kinds' median
        |log| error, so 53 airport-access journeys weigh as much as 700
        between towns -- the access leg is in every flown journey twice."""
        p = np.empty_like(y)
        for k in range(FOLDS):
            test = fold == k
            sp_ = gfit.fit_log(km[~test], y[~test], radius, groups, factors, fixed, w[~test])
            p[test] = gfit.predict(km[test], sp_, radius, groups, factors)
        e = np.abs(np.log(y / p))
        return 0.5 * (np.median(e[towns]) + np.median(e[access])), p

    results = []
    for radius in (0.0, *gfit.DIST_BANDS_KM):
        grids = [(one, [(f,) for f in np.arange(1.0, 3.01, 0.1)])]
        if radius > 0:
            grids.append((two, [(a, b) for a in np.arange(1.0, 2.51, 0.1)
                                for b in np.arange(1.0, 3.01, 0.1)]))
        for groups, grid in grids:
            for f in grid:
                factors = np.round(np.array(f), 2)
                err, _ = score(radius, groups, factors)
                results.append((err, radius, tuple(factors.tolist()), groups))
                if radius == 0:
                    break                       # no urban band: the factor is moot
    results.sort(key=lambda t: t[0])
    print("\n  best out-of-fold structures (mean of towns' and access' median |log|):")
    for err, radius, f, groups in results[:10]:
        print(f"    {err:.3f}  radius {radius:>4.0f}  factors {f}")
    for want in ((40.0, (2.0,)),):
        hit = [r for r in results if r[1] == want[0] and r[2] == want[1]]
        if hit:
            print(f"    {hit[0][0]:.3f}  radius {want[0]:>4.0f}  factors {want[1]}  (the shipped structure)")

    err, radius, f, groups = results[0]
    factors = np.array(f)
    speeds = gfit.fit_log(km, y, radius, groups, factors, fixed, w)
    _, oof = score(radius, groups, factors)
    print(f"\n  chosen: radius {radius:.0f} km, factors {f}; speeds refitted on all {len(y)}:")
    for i, n in enumerate(NAMES):
        print(f"    {n:10}{speeds[i]:>8.1f} km/h{'   (fixed)' if i in gfit.FIXED_CLASSES else ''}")
    report("in-sample", gfit.predict(km, speeds, radius, groups, factors))
    report("out-fold", oof)
    p = gfit.predict(km, speeds, radius, groups, factors)
    tert = km[:, 4].sum(axis=1) / km.sum(axis=(1, 2))
    for lo, hi in ((0, 0.05), (0.05, 0.3), (0.3, 1.01)):
        m = (tert >= lo) & (tert < hi)
        if m.any():
            print(f"    tertiary share {lo}-{hi}: n={int(m.sum())} {_stats(y[m], p[m])}")
    print(f"  km share per class {np.round(km.sum(axis=(0, 2)) / km.sum(), 3).tolist()}")


def _path(s: str) -> Path:
    """A path as given, relative ones from the repository root."""
    return Path(s) if Path(s).is_absolute() else config.ROOT / s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--sources", type=int, default=60)
    a.add_argument("--per-source", type=int, default=16)
    a.add_argument("--seed", type=int, default=3)
    a.add_argument("--places", type=_path, default=config.DIST / "places.json")
    a.add_argument("--airports", type=_path, default=config.DIST / "airports.json")
    a.add_argument("--out", type=_path, default=config.BUILD / "ground_plan3.json")
    o = sub.add_parser("observe")
    o.add_argument("--plan", type=_path, default=config.BUILD / "ground_plan3.json")
    o.add_argument("--out", type=_path, default=config.BUILD / "ground_samples3.json")
    o.add_argument("--max-requests", type=int, default=1200)
    f = sub.add_parser("fit")
    f.add_argument("--samples", type=_path, default=config.BUILD / "ground_samples3.json")
    args = ap.parse_args()
    {"plan": plan, "observe": observe, "fit": fit}[args.cmd](args)


if __name__ == "__main__":
    main()
