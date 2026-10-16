#!/usr/bin/env python3
"""Out-of-fold comparison of road-model structures, and the refit of the one
calibration.toml ships, on the journeys scripts/calibrate_ground.py plans and
observes (its `km_x` record: km per class 7, income group 4, driving region 3,
city-scaled band 6, road-density band 8, signed-limit band 4).

    uv run python scripts/fit_ground_structures.py compare SAMPLES.json
    uv run python scripts/fit_ground_structures.py fit SAMPLES.json --out FIT.json

`compare` scores each candidate by the mean over the four strata of the median
|log(observed/predicted)|, five folds by source, each stratum weighted a
quarter in the fit as in the score. `fit` refits the shipped structure on
every journey and prints the constants calibration.toml carries ([ground],
[ground_income], [ground_motorway], [ground_region], [urban] built_up_factor
and core_factor), the ratios by stratum and the core factor fold by fold.

Rebuild 33's structure ("limits, NA, lower-middle = low") was compared here;
rebuild 34 adds the city core (`core=True`): inside half a city's built-up
radius (scaled band 0) roads pay a second factor on top of the built-up one.
"""
import json

import numpy as np
from scipy.optimize import least_squares

STRATA = ("metro", "intercity", "rural", "airport")
NC, NI, NR, NB, ND, NL = 7, 4, 3, 6, 8, 4
BUILT_BANDS = (0, 1)          # inside one built-up radius
MW = 6


def load(path, target="observed_min"):
    d = json.load(open(path))
    J = [r for r in d["journeys"] if r.get(target) and r.get("km_x") is not None]
    km = np.zeros((len(J), NC, NI, NR, NB, ND, NL), dtype=np.float32)
    for n, r in enumerate(J):
        for c, i, g, b, dd, lb, v in r["km_x"]:
            km[n, c, i, g, b, dd, lb] += v
    y = np.array([r[target] for r in J])
    st = np.array([r["stratum"] for r in J])
    src = np.array([f"{r['source'][0]},{r['source'][1]}" for r in J])
    return km, y, st, src, J


class S:
    """regions: driving regions (1 NA, 2 EAsia) with their own multiplier.
    built: one factor inside the built-up radius (classes 1-6).
    dens: groups of density bands, each its own factor, applied 'all', 'built'
      (inside the radius only) or 'outside'.
    mw: 'same' (class 6 penalised like the rest), 'none' (never), 'apart'
      (its own built-up factor, no density factor).
    limits: class 6 speed per signed-limit band (0 none, 1 <95, 2 95-115,
      3 >=115) instead of one.
    mw_scaled: income and region multipliers apply to class 6."""

    def __init__(self, name, regions=(), built=True, dens=(), dens_where="all", mw="same",
                 limits=False, mw_scaled=True, ends=True, inc_merge=False):
        self.name, self.regions, self.built = name, tuple(regions), built
        self.dens, self.dens_where = [tuple(g) for g in dens], dens_where
        self.mw, self.limits, self.mw_scaled, self.ends = mw, limits, mw_scaled, ends
        self.inc_merge = inc_merge

    def collapse(self, km):
        """K[n, c, i, g, inside, dgroup, l]: dgroup len(dens) is 'no group'."""
        inside = np.zeros(NB, bool)
        inside[list(BUILT_BANDS)] = True
        dg = np.full(ND, len(self.dens))
        for k, g in enumerate(self.dens):
            dg[list(g)] = k
        K = np.zeros(km.shape[:4] + (2, len(self.dens) + 1, NL), dtype=np.float64)
        for b in range(NB):
            for d in range(ND):
                K[:, :, :, :, int(inside[b]), dg[d], :] += km[:, :, :, :, b, d, :]
        return K

    def nparams(self):
        n_mw = (NL if self.limits else 1)
        return (4 + n_mw + (2 if self.inc_merge else 3) + len(self.regions) + (1 if self.built else 0) + len(self.dens)
                + (1 if self.mw == "apart" else 0) + (1 if self.ends else 0))

    def start(self):
        th = np.zeros(self.nparams())
        th[:4] = np.log([45, 50, 55, 36])
        th[4:4 + (NL if self.limits else 1)] = np.log(88)
        if self.ends:
            th[-1] = 10.0
        return th

    def unpack(self, th):
        i = 0
        sp = np.array([5.0, 0, 0, 0, 0, 25.0, 0])
        sp[1:5] = np.exp(th[0:4]); i = 4
        n_mw = NL if self.limits else 1
        mw = np.exp(th[i:i + n_mw]) * np.ones(NL); i += n_mw
        mult = np.ones(NI)
        if self.inc_merge:
            mult[0] = np.exp(th[i]); mult[[2, 3]] = np.exp(th[i + 1]); i += 2
        else:
            mult[[0, 2, 3]] = np.exp(th[i:i + 3]); i += 3
        reg = np.ones(NR)
        for g in self.regions:
            reg[g] = np.exp(th[i]); i += 1
        built = np.exp(th[i]) if self.built else 1.0
        i += 1 if self.built else 0
        dens = np.exp(th[i:i + len(self.dens)]); i += len(self.dens)
        mwf = None
        if self.mw == "apart":
            mwf = np.exp(th[i]); i += 1
        end = th[i] if self.ends else 0.0
        return sp, mw, mult, reg, built, dens, mwf, end

    def predict(self, th, K):
        sp, mw, mult, reg, built, dens, mwf, end = self.unpack(th)
        nd = len(self.dens)
        # F[c, inside, dgroup]
        F = np.ones((NC, 2, nd + 1))
        F[1:, 1, :] *= built
        dfac = np.r_[dens, 1.0]
        if self.dens_where == "all":
            F[1:, :, :] *= dfac[None, None, :]
        elif self.dens_where == "built":
            F[1:, 1, :] *= dfac[None, :]
        else:
            F[1:, 0, :] *= dfac[None, :]
        if self.mw == "none":
            F[MW] = 1.0
        elif self.mw == "apart":
            F[MW] = 1.0
            F[MW, 1, :] = mwf
        # 1/V[c, i, g, l]
        V = np.empty((NC, NI, NR, NL))
        for c in range(NC):
            base = mw if c == MW else np.full(NL, sp[c])
            scale = (c in (1, 2, 3, 4)) or (c == MW and self.mw_scaled)
            m = (mult[:, None] * reg[None, :]) if scale else np.ones((NI, NR))
            V[c] = m[:, :, None] * base[None, None, :]
        t = np.einsum("ncigxdl,cxd,cigl->n", K, F, 1.0 / V)
        return 60.0 * t + end


def fit(s, K, y, w):
    th0 = s.start()
    rw = np.sqrt(w)
    lb, ub = np.full(len(th0), -np.inf), np.full(len(th0), np.inf)
    if s.ends:
        lb[-1], ub[-1] = 0.0, 60.0
    return least_squares(lambda th: rw * np.log(np.maximum(s.predict(th, K), 1e-3) / y),
                         th0, bounds=(lb, ub)).x


def weights(st):
    w = np.zeros(len(st))
    for s_ in STRATA:
        m = st == s_
        if m.any():
            w[m] = 1.0 / (len(STRATA) * m.sum())
    return w


def score(y, p, st):
    return {s_: float(np.median(np.abs(np.log(y[st == s_] / p[st == s_])))) for s_ in STRATA}


def folds_of(src, folds=5):
    rng = np.random.default_rng(0)
    srcs = np.unique(src)
    f = dict(zip(srcs.tolist(), rng.permutation(len(srcs)) % folds))
    return np.array([f[x] for x in src])


def oof(s, K, y, st, src, folds=5):
    fold = folds_of(src, folds)
    w = weights(st)
    p = np.empty_like(y)
    for f in range(folds):
        te = fold == f
        p[te] = s.predict(fit(s, K[~te], y[~te], w[~te]), K[te])
    return p


def describe(s, th):
    sp, mw, mult, reg, built, dens, mwf, end = s.unpack(th)
    out = [f"speeds 1-4 {np.round(sp[1:5], 1).tolist()}", f"motorway {np.round(mw, 1).tolist()}",
           f"income {np.round(mult, 3).tolist()}", f"region {np.round(reg, 3).tolist()}",
           f"built-up x{built:.3f}"]
    if len(dens):
        out.append(f"density[{s.dens_where}] " + ", ".join(f"{g}:x{v:.3f}" for g, v in zip(s.dens, dens)))
    if mwf is not None:
        out.append(f"motorway built-up x{mwf:.3f}")
    out.append(f"ends {end:.1f} min")
    return "; ".join(out)


def _run(path, cands, show_best=3):
    km, y, st, src, J = load(path)
    print(f"{len(y)} journeys: " + ", ".join(f"{s_} {int((st == s_).sum())}" for s_ in STRATA))
    res = []
    for s in cands:
        K = s.collapse(km)
        p = oof(s, K, y, st, src)
        e = score(y, p, st)
        ratio = [float(np.median(y[st == s_] / p[st == s_])) for s_ in STRATA]
        res.append((float(np.mean(list(e.values()))), s, e, ratio))
        print(f"{res[-1][0]:.4f}  {s.name:40} " + " ".join(f"{k} {v:.3f}" for k, v in e.items())
              + " | ratio " + " ".join(f"{v:.3f}" for v in ratio), flush=True)
    res.sort(key=lambda t: t[0])
    for sc, s, e, ratio in res[:show_best]:
        K = s.collapse(km)
        th = fit(s, K, y, weights(st))
        print(f"\n{sc:.4f} {s.name}: {describe(s, th)}")
    return res


class Core(S):
    """S with the built-up factor split into the core (scaled band 0) and the
    rest of the radius (band 1): the core pays `core` on top of `built`
    (calibration.toml [urban] core_factor, core_extent = 0.5 radii). Density
    groups are not modelled here."""

    def __init__(self, name, core=True, core_groups=None, **kw):
        super().__init__(name, **kw)
        self.core, self.core_groups = core, core_groups

    def collapse(self, km):
        K = np.zeros(km.shape[:4] + (3, NL))
        K[:, :, :, :, 0] = km[:, :, :, :, 0].sum(axis=4)
        K[:, :, :, :, 1] = km[:, :, :, :, 1].sum(axis=4)
        K[:, :, :, :, 2] = km[:, :, :, :, 2:].sum(axis=(4, 5))
        return K

    def nparams(self):
        return super().nparams() + (1 if self.core else 0)

    def start(self):
        th = super().start()
        if self.core:
            th = np.insert(th, len(th) - (1 if self.ends else 0), 0.0)
        return th

    def split(self, th):
        if not self.core:
            return th, 1.0
        k = len(th) - (2 if self.ends else 1)
        return np.delete(th, k), float(np.exp(th[k]))

    def unpack(self, th):
        return super().unpack(self.split(th)[0])

    def predict(self, th, K):
        base, core = self.split(th)
        sp, mw, mult, reg, built, dens, mwf, end = super().unpack(base)
        F = np.ones((NC, NI, 3))
        F[1:, :, 0] = built * (core if self.core_groups is None else 1.0)
        if self.core_groups is not None:
            F[1:, list(self.core_groups), 0] = built * core
        F[1:, :, 1] = built
        V = np.empty((NC, NI, NR, NL))
        for c in range(NC):
            b = mw if c == MW else np.full(NL, sp[c])
            scale = (c in (1, 2, 3, 4)) or (c == MW and self.mw_scaled)
            m = (mult[:, None] * reg[None, :]) if scale else np.ones((NI, NR))
            V[c] = m[:, :, None] * b[None, None, :]
        t = np.einsum("ncigxl,cix,cigl->n", K, F, 1.0 / V)
        return 60.0 * t + end


CANDS = [
    Core("rebuild 33: limits, NA, lower-middle = low", core=False, regions=(1,), limits=True,
         inc_merge=True),
    Core("rebuild 34: + city core", regions=(1,), limits=True, inc_merge=True),
    Core("+ city core, high income only", core_groups=(0,), regions=(1,), limits=True,
         inc_merge=True),
]
SHIPPED = CANDS[1]


def refit(path, out):
    km, y, st, src, _J = load(path)
    s = SHIPPED
    K = s.collapse(km)
    th = fit(s, K, y, weights(st))
    _, core = s.split(th)
    sp, mw, mult, reg, built, dens, mwf, end = s.unpack(th)
    p, po = s.predict(th, K), oof(s, K, y, st, src)
    e = score(y, po, st)
    print("speeds 1-4", np.round(sp[1:5], 2).tolist(), "motorway by limit", np.round(mw, 2).tolist())
    print("income", np.round(mult, 4).tolist(), "region", np.round(reg, 4).tolist(),
          "built-up", round(float(built), 4), "core", round(core, 4), "ends", round(float(end), 2))
    for s_ in STRATA:
        m = st == s_
        print(f"  {s_:9} n={int(m.sum()):4} in-sample {np.median(y[m] / p[m]):.3f}  out-of-fold "
              f"{np.median(y[m] / po[m]):.3f} |log| {e[s_]:.3f}")
    fold = folds_of(src)
    cores = [s.split(fit(s, K[fold != f], y[fold != f], weights(st[fold != f])))[1] for f in range(5)]
    print("mean out-of-fold |log|", round(float(np.mean(list(e.values()))), 4),
          "| core factor per fold", np.round(cores, 3).tolist())
    if out:
        json.dump({"speeds": sp.tolist(), "motorway_by_limit": mw.tolist(), "income": mult.tolist(),
                   "region": reg.tolist(), "built_up": float(built), "core": core,
                   "end_min": float(end), "oof": e, "core_by_fold": cores}, open(out, "w"), indent=1)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("cmd", choices=("compare", "fit"))
    ap.add_argument("samples")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "compare":
        km, y, st, src, _J = load(a.samples)
        for s in CANDS:
            K = s.collapse(km)
            e = score(y, oof(s, K, y, st, src), st)
            print(f"{np.mean(list(e.values())):.4f}  {s.name:44} "
                  + " ".join(f"{k} {v:.3f}" for k, v in e.items()), flush=True)
    else:
        refit(a.samples, a.out)
