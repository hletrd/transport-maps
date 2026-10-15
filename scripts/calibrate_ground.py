#!/usr/bin/env python3
"""Sample real driving journeys and fit the ground model's road speeds,
income multipliers and urban penalty.

    uv run python scripts/calibrate_ground.py plan    --out data/build/ground_plan4.json
    uv run python scripts/calibrate_ground.py observe --plan data/build/ground_plan4.json \\
                                                      --out data/build/ground_samples4.json
    uv run python scripts/calibrate_ground.py fit     --samples data/build/ground_samples4.json

Three steps because they want different machines: `plan` builds the ground
graph (about 10 M cells, ~13 GB) and walks every sampled journey's path, with
no network; `observe` asks Google Routes for each journey's driving time and
needs the API key (GOOGLE_ROUTES_API_KEY) and nothing else; `fit` is
arithmetic.

One Dijkstra per SOURCE, not per journey: solving once and taking many
destinations off the same tree turns a prohibitive 1,400 solves into ~180.

Two designs, so every stratum the map is read in is in the fit:

* towns: the endpoints of ground_samples3.json (rebuild 30) -- random
  populated places to random places 8-600 km away and to their nearest
  medium or large airport. Re-planned here so each carries the features
  below, and re-observed so all journeys share one target.
* metro: from the centre of a city of 1 M or more (Natural Earth pop_max), to
  its nearest medium or large airport, to towns 15-150 km out and to one 5-15
  km out. rebuild 30's sample had almost none of these (a random town is
  rarely a city centre), and the 2026-10-14 audit's errors are all there:
  London -> LHR 23 min against Google's 45.

Each journey is recorded as kilometres per road class x World Bank income
group x distance band, in two band sets: km to the nearest city of [urban]
pop_min (calibrate/ground.DIST_BANDS_KM) and that distance in the city's own
built-up radius (SCALED_BANDS). The path is the one the SHIPPED model finds;
a structure that would route differently is scored on the shipped routes.

The target is Google's TYPICAL-TRAFFIC duration for a Tuesday 10:00 (local
solar time) departure: the map's time is door to door, and a traveller meets
daytime traffic, not the empty network `staticDuration` describes (both are
recorded; one TRAFFIC_AWARE call returns both).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from transport_maps import config
from transport_maps.calibrate import ground as gfit

N_CLASSES = 7                  # GRIP4's 0-5, then the OSM motorway class
FOLDS = 5
NAMES = ["roadless", "highway", "primary", "secondary", "tertiary", "local"]
STRATA = ("metro", "intercity", "rural", "airport")


def _towns(path) -> np.ndarray:
    gaz = json.loads(path.read_text(encoding="utf-8"))
    return np.array([[r[3], r[4]] for r in gaz["places"]], dtype=float)


def _airports(path) -> np.ndarray:
    table = json.loads(path.read_text(encoding="utf-8"))
    return np.array([[r[3], r[4]] for r in table["airports"] if r[5] in ("medium", "large")],
                    dtype=float)


def _crow_km(a, b) -> np.ndarray:
    a, b = np.atleast_2d(a), np.atleast_2d(b)
    la1, lo1, la2, lo2 = map(np.radians, (a[:, 0], a[:, 1], b[:, 0], b[:, 1]))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(h))


def _designs(args) -> list[tuple[str, tuple[float, float], list[tuple[str, tuple[float, float]]]]]:
    """(design, source point, [(kind, destination point)]) per source."""
    import pyogrio

    from transport_maps.sources import urban

    rng = np.random.default_rng(args.seed)
    towns, airports = _towns(args.places), _airports(args.airports)
    out = []
    old = json.loads(args.previous.read_text(encoding="utf-8"))["journeys"]
    by_src = defaultdict(list)
    for r in old:
        by_src[(r["source"], tuple(r["from"]))].append((r["kind"], tuple(r["to"])))
    for (_s, here), dests in sorted(by_src.items()):
        out.append(("towns", here, dests))

    _m, t = pyogrio.read_arrow(f"/vsizip/{urban._download().resolve()}")
    lat = np.array(t.column("latitude").to_pylist(), float)
    lon = np.array(t.column("longitude").to_pylist(), float)
    pop = np.array(t.column("pop_max").to_pylist(), float)
    big = np.flatnonzero(pop >= args.metro_pop)
    for k in rng.choice(big, size=min(args.metros, len(big)), replace=False):
        here = (float(lat[k]), float(lon[k]))
        dests = []
        da = _crow_km(np.array([here] * len(airports)), airports)
        j = int(np.argmin(da))
        if 5.0 <= da[j] <= 100.0:
            dests.append(("airport", tuple(airports[j])))
        dt = _crow_km(np.array([here] * len(towns)), towns)
        far = np.flatnonzero((dt >= 15.0) & (dt <= 150.0))
        near = np.flatnonzero((dt >= 5.0) & (dt < 15.0))
        for j in rng.choice(far, size=min(3, len(far)), replace=False):
            dests.append(("towns", tuple(towns[j])))
        for j in rng.choice(near, size=min(1, len(near)), replace=False):
            dests.append(("towns", tuple(towns[j])))
        if dests:
            out.append(("metro", here, dests))
    return out


def plan(args) -> None:
    import gc

    import h3
    import scipy.sparse as sp

    from transport_maps.graph import ground as gmodel
    from transport_maps.graph import nodes
    from transport_maps.sources import countries, urban

    # As build-all does (cli._build_all): with the collector on, Python 3.14's
    # young collections scan the whole old heap.
    gc.disable()
    designs = _designs(args)
    print(f"  {len(designs)} sources: "
          f"{sum(d == 'towns' for d, _, _ in designs)} towns, {sum(d == 'metro' for d, _, _ in designs)} metro")

    idx = nodes.build_index()
    # The motorway class under --rule (sources/motorways.RULES), so each rule
    # is planned on the paths it would give.
    from transport_maps.sources import motorways

    classes = gmodel.cell_class(idx, args.rule).astype(np.int64)
    limit_band = motorways.limit_band_of(motorways.motorway_limit(idx, args.rule or motorways.RULE))
    country = countries.cell_country(idx.cells)
    income = countries.cell_income_group(country)
    region = countries.cell_driving_region(country)
    if args.fit:
        # Route under a fitted candidate rather than calibration.toml, so a
        # refit can be re-planned on its own paths (and observed minutes
        # rejoined with `join`, at no new requests).
        base = idx.base_cells if len(getattr(idx, "base_cells", [])) else idx.cells
        s_, _pop = urban.scaled_city_distance(list(base))
        if len(getattr(idx, "base_cells", [])):
            from transport_maps.graph import refine

            s_ = refine.expand(s_, idx)
        speeds = gfit.cell_speeds_from_fit(json.loads(args.fit.read_text(encoding="utf-8")),
                                           classes, income, gfit.scaled_band_of(s_))
    else:
        speeds = gmodel.cell_speed_kmh(idx, classes, country=country)
    zone = gmodel.cell_zones(country)
    r, c, d = gmodel.hex_edges(idx, speeds=speeds, country=country, zone=zone)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    plat, plon = urban._places()

    walks = []                     # (design, kind, source point, dest point, path cells)
    for n, (design, here, dests) in enumerate(designs):
        src = idx.try_cell_index(idx.cell_at(*here))
        if src is None:
            continue
        minutes, pred = sp.csgraph.dijkstra(csr, indices=[src], return_predecessors=True)
        minutes, pred = minutes[0], pred[0]
        for kind, to in dests:
            dst = idx.try_cell_index(idx.cell_at(*to))
            if dst is None or not np.isfinite(minutes[dst]) or dst == src:
                continue
            path, k, ok = [dst], dst, True
            while k != src and pred[k] >= 0 and len(path) < 6000:
                p = int(pred[k])
                if zone[p] != zone[k]:
                    ok = False             # a border: Google does not wait at one
                    break
                path.append(p)
                k = p
            if ok and k == src:
                walks.append((design, kind, here, to, np.array(path[::-1]), float(minutes[dst])))
        print(f"  source {n + 1}/{len(designs)}: {len(walks)} journeys", flush=True)

    # Features for the cells the paths use only: a few hundred thousand, not
    # ten million.
    cells = np.unique(np.concatenate([w[4] for w in walks]))
    ids = [idx.cells[i] for i in cells]
    cent = np.array([h3.cell_to_latlng(x) for x in ids])
    near = np.full(len(cells), np.inf)
    coslat = np.cos(np.radians(cent[:, 0]))
    for la, lo in zip(plat, plon):
        np.minimum(near, np.hypot((cent[:, 0] - la) * 111.0, (cent[:, 1] - lo) * 111.0 * coslat),
                   out=near)
    scaled, city_pop = urban.scaled_city_distance(ids)
    from transport_maps.sources import roads

    b_d = gfit.density_band_of(roads.cell_road_density(ids))
    pos = {int(v): i for i, v in enumerate(cells)}
    b_abs = gfit.band_of(near)
    b_s = gfit.scaled_band_of(scaled)
    b_z = gfit.size_band_of(city_pop)

    rows = []
    for design, kind, here, to, path, model_min in walks:
        at = np.array([pos[int(v)] for v in path])
        seg = np.r_[0.0, gmodel.haversine_km(cent[at[:-1]], cent[at[1:]])]
        km_abs = np.zeros((N_CLASSES, gfit.N_INCOME, len(gfit.DIST_BANDS_KM) + 1))
        km_s = np.zeros((N_CLASSES, gfit.N_INCOME, len(gfit.SCALED_BANDS) + 1, gfit.N_SIZES))
        cl, inc, rg, lb = classes[path], income[path], region[path], limit_band[path]
        np.add.at(km_abs, (cl[1:], inc[1:], b_abs[at[1:]]), seg[1:])
        np.add.at(km_s, (cl[1:], inc[1:], b_s[at[1:]], b_z[at[1:]]), seg[1:])
        # Sparse: class, income, driving region, scaled band, density band,
        # signed-limit band (motorway cells; 0 elsewhere), km.
        km_x: dict[tuple, float] = defaultdict(float)
        lbm = np.where(cl == gmodel.MOTORWAY_CLASS, lb, 0)
        for key, km in zip(zip(cl[1:].tolist(), inc[1:].tolist(), rg[1:].tolist(),
                               b_s[at[1:]].tolist(), b_d[at[1:]].tolist(), lbm[1:].tolist()),
                           seg[1:].tolist()):
            km_x[key] += km
        if seg.sum() < 3.0:
            continue
        if kind == "airport":
            stratum = "airport"
        elif design == "metro":
            stratum = "metro"
        else:
            stratum = "rural" if min(near[at[0]], near[at[-1]]) > 20.0 else "intercity"
        rows.append({"design": design, "kind": kind, "stratum": stratum,
                     "source": [round(v, 5) for v in here],
                     "from": [round(float(v), 5) for v in cent[at[0]]],
                     "to": [round(float(v), 5) for v in cent[at[-1]]],
                     "dest": [round(v, 5) for v in to],
                     "km_abs": np.round(km_abs, 3).tolist(), "km_s": np.round(km_s, 3).tolist(),
                     "km_x": [[*k, round(v, 3)] for k, v in sorted(km_x.items())],
                     "model_min": round(model_min, 2)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"bands_km": list(gfit.DIST_BANDS_KM),
                                    "scaled_bands": list(gfit.SCALED_BANDS),
                                    "density_bands": list(gfit.DENSITY_BANDS),
                                    "regions": ["other", *countries.DRIVING_REGIONS],
                                    "journeys": rows}),
                        encoding="utf-8")
    print(f"  wrote {len(rows)} journeys to {args.out}: "
          + ", ".join(f"{s} {sum(r['stratum'] == s for r in rows)}" for s in STRATA))


def observe(args) -> None:
    import httpx

    planned = json.loads(args.plan.read_text(encoding="utf-8"))
    budget = gfit.RequestBudget(args.max_requests)
    done, unrouted = [], 0
    with httpx.Client() as client:
        for row in planned["journeys"]:
            try:
                got = gfit.drive_times(client, budget, tuple(row["from"]), tuple(row["to"]),
                                       gfit.weekday_morning_utc(row["from"][1]))
            except RuntimeError:
                break
            except httpx.HTTPError as exc:
                print(f"  request failed: {exc}")
                continue
            gfit.sleep_between()
            if got is None:
                unrouted += 1
                continue
            done.append({**row, "observed_min": round(got[0], 2), "static_min": round(got[1], 2)})
            if len(done) % 100 == 0:
                print(f"  {len(done)} observed, {budget.used} requests", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({**planned, "journeys": done, "requests": budget.used,
                                    "unrouteable": unrouted}), encoding="utf-8")
    print(f"  {len(done)} journeys observed, {budget.used} requests, {unrouted} unrouteable;"
          f" wrote {args.out}")


def join(args) -> None:
    """Observed minutes from earlier samples onto a re-planned file, matched
    on the journey's two end cells: a re-plan that records more per journey
    need not pay for the same calls again."""
    planned = json.loads(args.plan.read_text(encoding="utf-8"))
    seen = {(tuple(r["from"]), tuple(r["to"])): r
            for r in json.loads(args.samples.read_text(encoding="utf-8"))["journeys"]}
    done = []
    for row in planned["journeys"]:
        hit = seen.get((tuple(row["from"]), tuple(row["to"])))
        if hit is not None:
            done.append({**row, "observed_min": hit["observed_min"], "static_min": hit["static_min"]})
    args.out.write_text(json.dumps({**planned, "journeys": done}), encoding="utf-8")
    print(f"  {len(done)} of {len(planned['journeys'])} planned journeys matched; wrote {args.out}")


def structures(n_classes: int = 6) -> list[gfit.Structure]:
    """The candidates. For a 6-class sample (no motorway class, rebuild 31):
    'r30' is rebuild 30's one factor within 20 km of any city; the rest add
    income multipliers and/or scale the penalty by each city's built-up
    radius (band indices into SCALED_BANDS: 0 <0.5, 1 0.5-1, 2 1-1.5,
    3 1.5-2, 4 2-3, 5 beyond), end minutes and so on. For a 7-class sample
    (an OSM motorway class): rebuild 31's structure and its two nearest
    rivals, each with the motorway class merged into GRIP4's highways (the
    rebuild-31 model on the same paths), at its own income-scaled speed, or
    at its own speed with no income multiplier."""
    s = []
    if n_classes == 7:
        for core, ring, hw in (((0, 1), (), False), ((0, 1), (), True), ((0,), (1, 2), False)):
            groups = [core] + ([ring] if ring else [])
            label = f"scaled core{core} ring{ring} +income{' hw-apart' if hw else ''} ends"
            for mw, kw in (("merged", {"motorway_merged": True}),
                           ("motorway", {"motorway_income": True}),
                           ("motorway flat", {"motorway_income": False})):
                s.append(gfit.Structure(f"{label} | {mw}", "scaled", groups, income=True,
                                        highway_apart=hw, ends=True, n_classes=7, **kw))
        return s
    s.append(gfit.Structure("r30", "abs", [(0, 1, 2)], income=False))
    s.append(gfit.Structure("r30+income", "abs", [(0, 1, 2)], income=True))
    for core, ring in (((0, 1), ()), ((0, 1), (2,)), ((0, 1), (2, 3)), ((0, 1), (2, 3, 4)),
                       ((0,), (1, 2)), ((0,), (1, 2, 3))):
        groups = [core] + ([ring] if ring else [])
        label = f"scaled core{core} ring{ring}"
        for inc in (False, True):
            s.append(gfit.Structure(label + (" +income" if inc else ""), "scaled", groups, income=inc))
        s.append(gfit.Structure(label + " +income hw-apart", "scaled", groups, income=True,
                                highway_apart=True))
        s.append(gfit.Structure(label + " +income sizes", "scaled", groups, income=True,
                                sizes=True))
        s.append(gfit.Structure(label + " +income hw-apart sizes", "scaled", groups, income=True,
                                highway_apart=True, sizes=True))
        s.append(gfit.Structure(label + " +income ends", "scaled", groups, income=True,
                                ends=True))
        s.append(gfit.Structure(label + " +income hw-apart ends", "scaled", groups, income=True,
                                highway_apart=True, ends=True))
    for core, ring in (((0, 1), ()), ((0,), (1, 2))):
        groups = [core] + ([ring] if ring else [])
        s.append(gfit.Structure(f"scaled core{core} ring{ring} +income-split ends", "scaled", groups,
                                income=True, ends=True, income_split=True))
    s.append(gfit.Structure("r30 ends", "abs", [(0, 1, 2)], income=False, ends=True))
    s.append(gfit.Structure("r30+income ends", "abs", [(0, 1, 2)], income=True, ends=True))
    return s


#: Rebuild 31's shipped road model (calibration.toml before the motorway
#: class) as a Structure and its parameters, so a sample can score it as it
#: is: speeds 73.1/59.6/57.0/35.5, income x1.261/0.813/0.712 (high, lower
#: middle, low), x1.39 inside one built-up radius, 13.8 end minutes. A
#: motorway cell is priced as the GRIP4 highway it was.
R31_THETA = np.r_[np.log([73.1, 59.6, 57.0, 35.5]), np.log([1.261, 0.813, 0.712]), np.log(1.39), 13.8]


def r31(n_classes: int) -> gfit.Structure:
    return gfit.Structure("rebuild 31", "scaled", [(0, 1)], income=True, ends=True,
                          n_classes=n_classes, motorway_merged=True)


def _err(y, p):
    return np.median(np.abs(np.log(y / p)))


def fit(args) -> None:
    data = json.loads(args.samples.read_text(encoding="utf-8"))
    rows = [r for r in data["journeys"] if r.get(args.target)]
    km_by = {"abs": np.array([r["km_abs"] for r in rows]), "scaled": np.array([r["km_s"] for r in rows])}
    y = np.array([r[args.target] for r in rows])
    stratum = np.array([r["stratum"] for r in rows])
    src = np.array([f"{r['source'][0]},{r['source'][1]}" for r in rows])
    # Five folds by SOURCE: journeys from one place share most of their roads.
    rng = np.random.default_rng(0)
    sources = np.unique(src)
    fold_of = dict(zip(sources.tolist(), rng.permutation(len(sources)) % FOLDS))
    fold = np.array([fold_of[s] for s in src])
    # Each stratum carries a quarter of the weight, in the fit and the score.
    w = np.zeros(len(y))
    for s_ in STRATA:
        m = stratum == s_
        if m.any():
            w[m] = 1.0 / (len(STRATA) * m.sum())
    n_classes = km_by["scaled"].shape[1]
    fixed = np.array([5.0, np.nan, np.nan, np.nan, np.nan, 25.0, np.nan])[:n_classes]
    print(f"  {len(y)} journeys, target {args.target}; "
          + ", ".join(f"{s} {int((stratum == s).sum())}" for s in STRATA)
          + f"; {len(sources)} sources, {FOLDS} folds by source")

    def by_stratum(p):
        return {s_: _err(y[stratum == s_], p[stratum == s_]) for s_ in STRATA if (stratum == s_).any()}

    def oof(st):
        km = km_by[st.bands]
        p = np.empty_like(y)
        for k in range(FOLDS):
            test = fold == k
            th = gfit.fit_structured(km[~test], y[~test], st, fixed, w[~test])
            p[test] = st.predict(km[test], th, fixed)
        return p

    # Rebuild 31's constants, scored as they are (no refit).
    p_ship = r31(n_classes).predict(km_by["scaled"], R31_THETA, fixed)
    results = [("rebuild 31 constants (not refitted)", by_stratum(p_ship), None)]
    for st in structures(n_classes):
        p = oof(st)
        results.append((st.name, by_stratum(p), st))
        e = results[-1][1]
        print(f"    {np.mean(list(e.values())):.3f}  {st.name:44} "
              + "  ".join(f"{k} {v:.3f}" for k, v in e.items()), flush=True)
    results.sort(key=lambda t: np.mean(list(t[1].values())))
    print("\n  out of fold, median |log(observed/predicted)| by stratum (mean first):")
    for name, e, _st in results[:8] + [r for r in results if r[2] is None]:
        print(f"    {np.mean(list(e.values())):.3f}  {name:44} "
              + "  ".join(f"{k} {v:.3f}" for k, v in e.items()))
    # The best out of fold, unless --structure names one: a structure within
    # a few thousandths of the best and with fewer constants is the one to
    # ship, and that is a judgement the score alone does not make.
    best = next(r for r in results if r[2] is not None
                and (args.structure is None or r[0] == args.structure))
    st = best[2]
    th = gfit.fit_structured(km_by[st.bands], y, st, fixed, w)
    sp_, mu, fa = st.unpack(th, fixed)
    p = st.predict(km_by[st.bands], th, fixed)
    p_oof = oof(st)
    print(f"\n  chosen: {st.name}; refitted on all {len(y)}:\n    {st.describe(th, fixed)}")
    for s_ in STRATA:
        m = stratum == s_
        if m.any():
            print(f"    {s_:9} n={int(m.sum()):4}  in-sample median obs/pred {np.median(y[m] / p[m]):.3f}"
                  f"  out-of-fold {np.median(y[m] / p_oof[m]):.3f} |log| {_err(y[m], p_oof[m]):.3f}"
                  f"   shipped {np.median(y[m] / p_ship[m]):.3f} |log| {_err(y[m], p_ship[m]):.3f}")
    if args.out:
        args.out.write_text(json.dumps({"structure": st.name, "theta": th.tolist(),
                                        "speeds": sp_.tolist(), "income": mu.tolist(),
                                        "factor": fa.tolist(), "end_min": st.end_minutes(th),
                                        "groups": [list(g) for g in st.groups],
                                        "highway_apart": st.highway_apart, "sizes": st.sizes,
                                        "scaled_classes": list(st.scaled),
                                        "oof": {s_: float(v) for s_, v in by_stratum(p_oof).items()},
                                        "oof_ratio": {s_: float(np.median(y[stratum == s_] / p_oof[stratum == s_]))
                                                      for s_ in STRATA if (stratum == s_).any()}},
                                       indent=1))


def _path(s: str) -> Path:
    """A path as given, relative ones from the repository root."""
    return Path(s) if Path(s).is_absolute() else config.ROOT / s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--previous", type=_path, default=config.BUILD / "ground_samples3.json")
    a.add_argument("--metros", type=int, default=150)
    a.add_argument("--metro-pop", type=float, default=1_000_000.0)
    a.add_argument("--seed", type=int, default=4)
    a.add_argument("--places", type=_path, default=config.DIST / "places.json")
    a.add_argument("--airports", type=_path, default=config.DIST / "airports.json")
    a.add_argument("--out", type=_path, default=config.BUILD / "ground_plan4.json")
    a.add_argument("--rule", default=None, help="sources/motorways.RULES; its RULE if omitted")
    a.add_argument("--fit", type=_path, default=None,
                   help="route under this fit's speeds (fit --out), not calibration.toml's")
    o = sub.add_parser("observe")
    o.add_argument("--plan", type=_path, default=config.BUILD / "ground_plan4.json")
    o.add_argument("--out", type=_path, default=config.BUILD / "ground_samples4.json")
    o.add_argument("--max-requests", type=int, default=2200)
    f = sub.add_parser("fit")
    f.add_argument("--samples", type=_path, default=config.BUILD / "ground_samples4.json")
    f.add_argument("--target", choices=("observed_min", "static_min"), default="observed_min")
    f.add_argument("--out", type=_path, default=None)
    f.add_argument("--structure", default=None, help="fit this named structure, not the best")
    j = sub.add_parser("join")
    j.add_argument("--plan", type=_path, required=True)
    j.add_argument("--samples", type=_path, required=True)
    j.add_argument("--out", type=_path, required=True)
    args = ap.parse_args()
    {"plan": plan, "observe": observe, "fit": fit, "join": join}[args.cmd](args)


if __name__ == "__main__":
    main()
