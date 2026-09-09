#!/usr/bin/env python3
"""Sample real driving journeys and fit the per-road-class ground speeds.

    source ~/.config/transport-maps/env
    uv run python scripts/calibrate_ground.py --sources 50 --per-source 40

One Dijkstra per SOURCE, not per sample: the ground graph has 600k nodes, so
solving once and taking many destinations off the same tree turns a
prohibitive 2,000 solves into 50.

For each sampled journey the path is walked to accumulate kilometres per GRIP4
road class, which is exactly the design matrix the fit needs -- the model's
predicted time is the sum of `distance / speed[class]`, linear in reciprocal
speed.
"""

from __future__ import annotations

import argparse
import json

import h3
import httpx
import numpy as np
import scipy.sparse as sp

from transport_maps import config
from transport_maps.calibrate import ground as gfit
from transport_maps.graph import ground as gmodel
from transport_maps.graph import nodes
from transport_maps.sources import roads, urban


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=int, default=50)
    ap.add_argument("--per-source", type=int, default=40)
    ap.add_argument("--out", default="data/build/ground_samples.json")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    # Sample between REAL TOWNS, not random land cells. A pilot over uniform
    # land cells came back 73% unrouteable: most of Earth's land is Siberia,
    # Sahara and small islands, where Google has no road network to route on.
    # The shipped gazetteer is 7,342 populated places, which is exactly the
    # population of journeys the ground model is meant to predict.
    gaz = json.loads((config.DIST / "places.json").read_text(encoding="utf-8"))
    towns = np.array([[r[3], r[4]] for r in gaz["places"]], dtype=float)
    print(f"  sampling between {len(towns):,} populated places")

    idx = nodes.build_index()
    # Read the class directly. Reverse-mapping from the cell's speed broke as
    # soon as the urban factor existed: 36 / 2 = 18 km/h is nobody's class.
    classes = roads.cell_class(idx.cells).astype(np.int64)
    # The model halves speed in built-up cells, so a kilometre there costs as
    # much time as two kilometres of open road. Weighting the design matrix the
    # same way means the fit recovers FREE-FLOW class speeds, consistent with
    # how the model then applies them, rather than a blend of the two regimes.
    urban_w = np.where(urban.urban_mask(idx.cells) & (classes > 0),
                       urban.URBAN_CONGESTION_FACTOR, 1.0)

    r, c, d = gmodel.hex_edges(idx)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    centroids = np.array([h3.cell_to_latlng(x) for x in idx.cells])

    budget = gfit.RequestBudget()
    rows: list[list[float]] = []
    obs: list[float] = []
    skipped_no_route = 0

    with httpx.Client() as client:
        for s in range(args.sources):
            town = towns[rng.integers(0, len(towns))]
            src = idx.try_cell_index(h3.latlng_to_cell(town[0], town[1], config.SOLVE_RES))
            if src is None:
                continue
            minutes, pred = sp.csgraph.dijkstra(
                csr, indices=[src], return_predecessors=True)
            minutes, pred = minutes[0], pred[0]

            reachable = np.where(np.isfinite(minutes[: idx.n_cells]))[0]
            if len(reachable) < 200:
                continue
            km = gmodel.haversine_km(
                np.repeat(centroids[src][None, :], len(reachable), axis=0),
                centroids[reachable])
            band = reachable[(km >= gfit.MIN_KM) & (km <= gfit.MAX_KM)]
            if len(band) == 0:
                continue
            # Restrict destinations to cells that themselves hold a town, so
            # both ends of every sampled journey are somewhere with roads.
            in_band = set(band.tolist())
            near = towns[
                (np.abs(towns[:, 0] - town[0]) < 6.0)
                & (np.abs(towns[:, 1] - town[1]) < 6.0)
            ]
            cand = []
            for t in near:
                j = idx.try_cell_index(h3.latlng_to_cell(t[0], t[1], config.SOLVE_RES))
                if j is not None and j in in_band:
                    cand.append(j)
            if not cand:
                continue
            cand = np.array(sorted(set(cand)))
            picks = rng.choice(cand, size=min(args.per_source, len(cand)), replace=False)

            for dst in picks:
                if budget.used >= budget.limit:
                    break
                # Walk the path, accumulating kilometres per road class.
                per_class = np.zeros(len(gmodel.SPEED_BY_ROAD_CLASS_KMH))
                n = int(dst)
                guard = 0
                while n != src and pred[n] >= 0 and guard < 4000:
                    p = int(pred[n])
                    seg = gmodel.haversine_km(centroids[p][None, :], centroids[n][None, :])[0]
                    per_class[classes[n]] += seg * urban_w[n]
                    n = p
                    guard += 1
                if n != src or per_class.sum() < gfit.MIN_KM:
                    continue

                a = tuple(centroids[src])
                b = tuple(centroids[int(dst)])
                try:
                    got = gfit.drive_minutes(client, budget, a, b)
                except RuntimeError:
                    break
                except httpx.HTTPError as exc:
                    print(f"  request failed: {exc}")
                    continue
                gfit.sleep_between()
                if got is None:
                    skipped_no_route += 1
                    continue
                rows.append(per_class.tolist())
                obs.append(got)

            print(f"  source {s + 1}/{args.sources}: {len(rows)} samples, "
                  f"{budget.used} requests, {skipped_no_route} unrouteable",
                  flush=True)
            if budget.used >= budget.limit:
                break

    if len(rows) < 50:
        raise SystemExit(f"only {len(rows)} usable samples; refusing to fit")

    X = np.array(rows)
    y = np.array(obs)
    out = config.ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    gfit.save(out, {"class_km": X.tolist(), "observed_min": y.tolist(),
                    "requests": budget.used, "unrouteable": skipped_no_route})

    speeds = gfit.fit_speeds(X, y)
    predicted_now = (X / gmodel.SPEED_BY_ROAD_CLASS_KMH).sum(axis=1) * 60.0
    print(f"\n  {len(y):,} samples, {budget.used} requests, "
          f"{skipped_no_route} unrouteable (South Korea has no Google routing)")
    print(f"  current model is {np.median(y / predicted_now):.2f}x too fast (median)")
    print(f"\n  {'class':10}{'current':>10}{'fitted':>10}")
    names = ["roadless", "highway", "primary", "secondary", "tertiary", "local"]
    for i, n in enumerate(names):
        cur = gmodel.SPEED_BY_ROAD_CLASS_KMH[i]
        f = speeds[i]
        print(f"  {n:10}{cur:>9.0f}{'' if np.isnan(f) else f'{f:>10.0f}'}"
              f"{'   (no coverage)' if np.isnan(f) else ''}")
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
