#!/usr/bin/env python
"""Refit (and audit) the `[rail.tiers]` speeds against OSM `duration` tags.

`calibration.toml`'s `[rail]` block used to say there was nothing to regress
against, because OSM route relations carry a stop sequence and no journey
times. That is true of most of them and false of 2,448: they carry a `duration`
tag, in the same formats `sources/osm.parse_minutes()` already parses for
ferries. This script is what produced the figures in that block, and running it
is how a reader checks them -- the pattern `scripts/ground_check.py` sets and
CLAUDE.md names.

    uv run python scripts/fit_rail_tiers.py                   # audit the shipped figures
    uv run python scripts/fit_rail_tiers.py --refit           # print a fresh fit
    uv run python scripts/fit_rail_tiers.py --refit --vmax    # + line speed and the
                                                              #   track network's factor

Since rebuild 30 it reads `rail_routes()`, which keeps each relation's parsed
`duration`, the stops it lists, its tier as the graph prices it (promoted on
high-speed track) and its member track's line speed -- the observations and
the tiering are then exactly the graph's.

NOTHING here writes to `calibration.toml`. Refitting is a human decision: the
residuals below are not all flattering, and `tourism` in particular rests on 25
observations. See the `[rail]` block for what is and is not claimed.
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transport_maps import config  # noqa: E402
from transport_maps.graph.rail import load_rail_calibration  # noqa: E402
from transport_maps.sources import osm  # noqa: E402

# A `duration` implying a speed outside this band is a tagging error, not a
# train: 15 of 2,338 observations (0.6%) fall outside it -- two Polish
# relations tagged `duration=2` for 70 km, four tagged 40-57 h for 38-53 km.
# The same shape of filter as `graph/ferry.trusted_duration_min`, which rejects
# a ferry `duration` by implied speed for the same reason.
MIN_IMPLIED_KMH, MAX_IMPLIED_KMH = 3.0, 350.0
# Below this a chord sum is dominated by the stop positions' own scatter.
MIN_ROUTE_KM = 1.0


def _haversine_km(lat1, lon1, lat2, lon2):
    r1, r2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = r2 - r1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(r1) * np.cos(r2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def observations(extracts_dir: Path) -> list[dict]:
    """One row per route relation that carries a usable `duration`.

    Read from `rail_routes()` itself since rebuild 30, which keeps each
    relation's `duration`, the number of stops it lists, its tier AS THE GRAPH
    PRICES IT (promoted where its track is high-speed) and its track profile.
    A route the extracts resolve only PARTLY is dropped rather than used: its
    chord sum covers fewer stops than the tagged duration describes, so the
    implied speed would be too low by whatever share of the route is missing.
    The track network's links (negative ids) carry no duration and are not
    observations.
    """
    routes = osm.rail_routes(extracts_dir=extracts_dir).filter(
        pl.col("route_id") > 0).sort("route_id", "seq")
    grouped = routes.group_by("route_id", maintain_order=True).agg(
        pl.col("lat"), pl.col("lon"), pl.first("tier"), pl.first("duration_min"),
        pl.first("stops_listed"), pl.first("route_name"), pl.first("vmax_kmh"),
        pl.first("vmax_cover"), pl.first("member_km"), pl.first("hs_share"))

    rows, dropped = [], collections.Counter()
    for g in grouped.iter_rows(named=True):
        minutes = g["duration_min"]
        if minutes is None:
            dropped["no usable duration tag"] += 1
            continue
        if minutes <= 0:
            dropped["duration non-positive"] += 1
            continue
        lat, lon = g["lat"], g["lon"]
        if g["stops_listed"] and len(lat) < g["stops_listed"]:
            dropped["stop sequence truncated by the extract"] += 1
            continue
        la, lo = np.asarray(lat, float), np.asarray(lon, float)
        km = float(_haversine_km(la[:-1], lo[:-1], la[1:], lo[1:]).sum())
        if km < MIN_ROUTE_KM:
            dropped[f"chord sum under {MIN_ROUTE_KM:g} km"] += 1
            continue
        rows.append({"route_id": g["route_id"], "tier": g["tier"], "km": km,
                     "obs_min": minutes, "legs": len(la) - 1, "name": g["route_name"],
                     "vmax": g["vmax_kmh"], "cover": g["vmax_cover"] or 0.0,
                     "member_km": g["member_km"], "hs_share": g["hs_share"]})
    return rows, dropped


def _predict(overhead, speed, km, legs, detour):
    return overhead * legs + 60.0 * km * detour / speed


def _residuals(sub, overhead, speed, detour):
    km = np.array([r["km"] for r in sub])
    legs = np.array([r["legs"] for r in sub], float)
    obs = np.array([r["obs_min"] for r in sub])
    ratio = _predict(overhead, speed, km, legs, detour) / obs
    lg = np.log(ratio)
    return (float(np.median(ratio)), float(np.std(lg)),
            float(np.mean((ratio > 0.5) & (ratio < 2.0))))


def _fit(sub, detour):
    """Least squares on LOG residuals -- the same criterion the ferry fit used.

    A coarse grid then Nelder-Mead: the surface is smooth but not convex in
    `overhead` near zero, and a pure local search from a bad start walks into
    the boundary.
    """
    from scipy.optimize import minimize

    km = np.array([r["km"] for r in sub])
    legs = np.array([r["legs"] for r in sub], float)
    ly = np.log(np.array([r["obs_min"] for r in sub]))

    def loss(p):
        pred = _predict(max(p[0], 0.0), max(p[1], 5.0), km, legs, detour)
        return float(np.mean((np.log(np.maximum(pred, 1e-6)) - ly) ** 2))

    best = (math.inf, (0.0, 60.0))
    for overhead in np.arange(0.0, 8.01, 0.25):
        for speed in np.arange(10.0, 320.0, 2.0):
            v = loss((overhead, speed))
            if v < best[0]:
                best = (v, (overhead, speed))
    res = minimize(loss, np.array(best[1]), method="Nelder-Mead",
                   options={"xatol": 1e-3, "fatol": 1e-8, "maxiter": 4000})
    return max(res.x[0], 0.0), max(res.x[1], 5.0)


def _fit_k(obs, base, legs, grid=np.arange(0.2, 1.21, 0.02)):
    """(overhead, k) minimising log residuals of `legs*overhead + base/k`."""
    from scipy.optimize import minimize

    ly = np.log(obs)

    def loss(p):
        pred = legs * max(p[0], 0.0) + base / max(p[1], 0.05)
        return float(np.mean((np.log(np.maximum(pred, 1e-6)) - ly) ** 2))

    best = min((loss((o, k)), (o, k)) for o in np.arange(0.0, 8.01, 0.25) for k in grid)
    res = minimize(loss, np.array(best[1]), method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-9, "maxiter": 4000})
    o, k = max(res.x[0], 0.0), max(res.x[1], 0.05)
    lg = np.log((legs * o + base / k) / obs)
    return o, k, float(np.std(lg)), float(np.median(np.exp(lg)))


# The share of a relation's track whose `maxspeed` is mapped before its line
# speed is believed over its tier's. Below half, the mean speaks for a part of
# the route only.
VMAX_COVER = 0.5


def vmax_study(clean, detour) -> None:
    """Does the track's own line speed predict a `duration` better than the tier?

    Per tier, on the relations whose member track is at least VMAX_COVER
    mapped with `maxspeed`: the tier model (one speed, fitted) against a
    line-speed model, running speed `k x` the harmonic-mean `maxspeed` of the
    relation's own track. Same observations, same criterion; a lower log-sd is
    the only argument for the second.

    Then the factor the track network uses: on `high_speed` relations, a
    `duration` against the relation's whole member track at line speed,
    `legs x overhead + 60 x member_km / vmax / k`.
    """
    print()
    print(f"line speed against tier, relations with maxspeed on >= {VMAX_COVER:.0%} of track")
    print(f"{'tier':<16}{'n':>6}{'tier sd':>9}{'line sd':>9}{'k':>7}{'ovh':>7}{'med':>7}")
    for tier in reversed(osm.RAIL_TIERS):
        sub = [r for r in clean if r["tier"] == tier and r["vmax"] and r["cover"] >= VMAX_COVER]
        if len(sub) < 8:
            continue
        km = np.array([r["km"] for r in sub]); legs = np.array([r["legs"] for r in sub], float)
        obs = np.array([r["obs_min"] for r in sub]); vmax = np.array([r["vmax"] for r in sub])
        o_t, v_t = _fit(sub, detour)
        sd_t = float(np.std(np.log(_predict(o_t, v_t, km, legs, detour) / obs)))
        base = 60.0 * km * detour / vmax
        o, k, sd, med = _fit_k(obs, base, legs)
        rng = np.random.default_rng(0)
        ks = [_fit_k(obs[i], base[i], legs[i], grid=np.arange(0.3, 1.21, 0.05))[1]
              for i in (rng.integers(0, len(sub), len(sub)) for _ in range(300))]
        print(f"{tier:<16}{len(sub):>6}{sd_t:>9.3f}{sd:>9.3f}{k:>7.3f}{o:>7.2f}{med:>7.2f}"
              f"   k 95% CI [{np.percentile(ks, 2.5):.3f}, {np.percentile(ks, 97.5):.3f}]")
    sub = [r for r in clean if r["tier"] == "high_speed" and r["vmax"] and r["member_km"]
           and r["cover"] >= VMAX_COVER]
    if len(sub) >= 8:
        obs = np.array([r["obs_min"] for r in sub]); legs = np.array([r["legs"] for r in sub], float)
        base = np.array([60.0 * r["member_km"] / r["vmax"] for r in sub])
        o, k, sd, med = _fit_k(obs, base, legs)
        print(f"\ntrack network factor on high_speed relations, n={len(sub)}: "
              f"k {k:.3f}, overhead {o:.2f} min/leg, log-sd {sd:.3f}, med p/o {med:.2f}")
        rng = np.random.default_rng(0)
        ks = []
        for _ in range(500):
            idx = rng.integers(0, len(sub), len(sub))
            ks.append(_fit_k(obs[idx], base[idx], legs[idx], grid=np.arange(0.4, 1.21, 0.05))[1])
        print(f"  bootstrap 95% CI on k: [{np.percentile(ks, 2.5):.3f}, {np.percentile(ks, 97.5):.3f}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refit", action="store_true",
                    help="fit fresh constants instead of auditing the shipped ones")
    ap.add_argument("--extracts", type=Path, default=config.CACHE / "osm")
    ap.add_argument("--vmax", action="store_true",
                    help="also test line speed from the track's maxspeed against the tiers")
    args = ap.parse_args()

    rows, dropped = observations(args.extracts)
    print(f"route relations with a usable duration: {len(rows):,}")
    for reason, n in dropped.most_common():
        print(f"  dropped, {reason}: {n:,}")

    detour = load_rail_calibration().detour_factor
    clean = [r for r in rows
             if MIN_IMPLIED_KMH <= 60.0 * detour * r["km"] / r["obs_min"] <= MAX_IMPLIED_KMH]
    print(f"inside the {MIN_IMPLIED_KMH:g}-{MAX_IMPLIED_KMH:g} km/h plausibility band: "
          f"{len(clean):,} ({len(rows) - len(clean)} rejected)")

    by = collections.defaultdict(list)
    for r in clean:
        by[r["tier"]].append(r)

    cal = load_rail_calibration()
    print()
    print(f"{'tier':<16}{'n':>6}{'overhead':>10}{'speed':>8}"
          f"{'med p/o':>9}{'log-sd':>8}{'<2x':>7}")
    for tier in reversed(osm.RAIL_TIERS):
        sub = by.get(tier, [])
        if not sub:
            print(f"{tier:<16}{0:>6}   (no observations in this extract set)")
            continue
        if args.refit:
            overhead, speed = _fit(sub, detour)
        else:
            overhead = cal.tiers[tier].stop_overhead_min
            speed = cal.tiers[tier].speed_kmh
        med, sd, within = _residuals(sub, overhead, speed, detour)
        print(f"{tier:<16}{len(sub):>6}{overhead:>10.2f}{speed:>8.1f}"
              f"{med:>9.2f}{sd:>8.3f}{100 * within:>6.0f}%")

    # The whole set under the shipped constants, against the two-speed model it
    # replaced, so the claim in `[rail]` can be checked in one run.
    km = np.array([r["km"] for r in clean])
    obs = np.array([r["obs_min"] for r in clean])
    new = np.array([_predict(cal.tiers[r["tier"]].stop_overhead_min,
                             cal.tiers[r["tier"]].speed_kmh,
                             r["km"], r["legs"], detour) for r in clean])
    old = 60.0 * km * detour / np.where(
        np.array([r["tier"] == "high_speed" for r in clean]), 200.0, 75.0)
    print()
    for label, pred in (("old, two speeds", old), ("shipped tiers", new)):
        ratio = pred / obs
        print(f"  {label:<18} med p/o {np.median(ratio):5.2f}  "
              f"log-sd {np.std(np.log(ratio)):5.3f}  "
              f"within 2x {100 * np.mean((ratio > 0.5) & (ratio < 2)):3.0f}%  "
              f"within 1.5x {100 * np.mean((ratio > 1 / 1.5) & (ratio < 1.5)):3.0f}%")
    print()
    print(f"  {'chord km':<12}{'n':>6}{'old':>8}{'new':>8}   (median predicted/observed)")
    for lo, hi in ((0, 20), (20, 50), (50, 150), (150, 400), (400, 1000), (1000, 10 ** 9)):
        m = (km >= lo) & (km < hi)
        if m.sum() < 5:
            continue
        print(f"  {f'{lo}-{hi}':<12}{m.sum():>6}"
              f"{np.median(old[m] / obs[m]):>8.2f}{np.median(new[m] / obs[m]):>8.2f}")

    if args.vmax:
        vmax_study(clean, detour)

    # Regional composition, because the fit is 74% European and the [rail]
    # block says so. Re-derived here rather than asserted.
    print()
    print("  observations by region of the route's first stop:")
    routes = osm.rail_routes(extracts_dir=args.extracts)
    first = routes.filter(pl.col("seq") == 0).select("route_id", "lat", "lon")
    loc = {int(a): (b, c) for a, b, c in zip(first["route_id"], first["lat"], first["lon"])}
    region = collections.Counter()
    for r in clean:
        la, lo = loc.get(r["route_id"], (0.0, 0.0))
        if lo < -30:
            name = "S.America" if la < -12 else "N/C.America"
        elif la < 35 and -20 < lo < 52:
            name = "Africa"
        elif lo > 100 and la < 0:
            name = "Oceania"
        elif lo > 40:
            name = "Asia"
        else:
            name = "Europe"
        region[name] += 1
    total = sum(region.values())
    for name, n in region.most_common():
        print(f"    {name:<14}{n:>6}  {100 * n / total:5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
