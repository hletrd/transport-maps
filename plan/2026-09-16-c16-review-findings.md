# Cycle 16 — review findings: scheduled, deferred, indexed

Source: `.context/reviews/` — eleven lanes run concurrently against
`feat/transport-pipeline` @ `c2ee764`, merged in `.context/reviews/_aggregate.md`.
**116 raw findings, 41 distinct after dedupe** (66 new, 36 known-with-new-evidence,
14 known-restated). Per-lane IDs are `CR16-n`, `PR16-n`, `SEC16-n`, `CRIT16-n`, `VER16-n`,
`TE16-n`, `TR16-n`, `ARCH16-n`, `DBG16-n`, `DOC16-n`, `UX16-n`; merged clusters are
`AGG16-1…AGG16-41`; this cycle's scheduled tasks are `C16-1…C16-8` and its deferrals
`DEF16-1…DEF16-24`.

Every one of the 41 is dispositioned in §4 or §5 below. Nothing is dropped.

**Agent-type note for provenance:** the named review agent types are not registered in this
session. All eleven lanes were run as `general-purpose` agents carrying the lane mandate.
No lane was dropped; no lane failed.

---

## 1. What this cycle can and cannot do

The same 38-hour `build-all` holds `dist/.build.lock` (~15 h 30 m elapsed when the reviews
ran, ~500 origins remaining, ETA ≈ 14:10 local on 16 Sep from a reconstruction of 612
`.rail.json` mtimes). The orchestrator's constraints are unchanged: no writes under `dist/`
or `data/`, no second build, no `reindex`, deploys are PAGE-ONLY, and nothing in
`src/transport_maps/**` can be verified against the live site.

**This cycle's reviews changed what the pending owner decision is about.** See §2.

---

## 2. For the owner — three findings that are not this cycle's to act on

### 2.1 The running build will not republish `index.json` (AGG16-16, HIGH, verified)

`/bin/ps` shows the in-flight process is `build-all --only "$(cat …)"`, resuming 1,099 of
1,464 origins. `src/transport_maps/cli.py:417`:

```python
partial = limit is not None or bool(only)
```

and `:513-515`:

```python
    if partial:
        print("partial build (--limit / --only): index.json left untouched")
        return
    index.write_index(origins, config.DIST / "index.json", …)
```

The early return sits **before** `index.write_index`. I read both regions myself rather
than relaying the lanes' claim. `README.md:40-43` documents the behaviour, so this is
working as designed — but **six cycle-15 exit criteria name "the rebuild republishes
`index.json`" as the event that reopens them** (DEF15-1, DEF15-3, DEF15-11, DEF15-12,
DEF15-32, DEF15-43) and **none of them can fire from this run.** Only DEF15-15 correctly
names `reindex`.

Consequence for the owner: finishing the build is necessary but not sufficient. A
`reindex` must follow it, and DEF15-15 records that `reindex` republishes the *previous*
build's `inputsHash`/`buildId`/`builtAt` unconditionally — so the `reindex` that closes
those six criteria is the same call DEF15-15 warns is the one that could ship a
calibration-mixed `dist/` under one build stamp. **Those two facts belong together in the
decision and had not been put together before this cycle.**

### 2.2 The running build carries the pre-tier rail model (AGG16-17, HIGH, verified ×3)

Three independent confirmations, none of which required disturbing the build:

- No `rail_routes-*.parquet` in `data/cache/` carries a `tier` column — all are
  `[…, 'highspeed', 'route_name']`.
- `dist/origins/abeokuta.rail.json` (15 Sep 19:37) is `{"fields":["station","line"],…}` —
  the pre-`15870ac` two-field shape.
- `calibration.toml` still held `highspeed_kmh = 200.0` / `conventional_kmh = 75.0` at the
  build's checkout; the tier commits `e7a90c7`/`15870ac`/`5849e0d` landed 21:40–22:21 the
  same evening, eleven hours into the run.

This was already known in outline. What is **new** is the consequence: `dist/index.json`'s
`modeDetail.rail` still reads "high-speed lines at 200 km/h, conventional at 75 km/h" and
`web/app.js:2538` renders it as the tooltip on the rail row — while cycle 15's C15-6 copy,
one click away in the same panel, now says six tiers at 74–215 km/h. **Both are on screen
at once today, and §2.1 means the rebuild alone will not reconcile them.**

A near-miss worth recording: `5849e0d` *removed* the `[rail]` keys the running build's
`RailCalibration` requires, eleven hours into the run. It survived only because no module
reached by `_solve_one` reads `calibration.toml`. A `TypeError` in a forked worker was one
call away. (TR16-5, carried as `C11-D8` with new evidence.)

### 2.3 Machine headroom, not code, is the most likely remaining death (AGG16-18)

Swap 5,617 of 7,168 MB used; 67 MB free pages; five workers at ~12 GB RSS on 32 GB. The
timing itself is healthy: median 449 s per origin, p90 483 s, max 604 s, **no origin above
2× median**, throughput rising 35 → 43 per hour over 15 h. `/private/tmp/rebuild21.log`
contains **zero** warnings, exceptions or retries in 614 success rows.

The hour-26 death is **identified and closed**: `kota-kinabalu` (C12-1), and the live log
proves the fix works in production — line 9 reads `1 of 1099 origin(s) snapped to the
nearest land cell (kota-kinabalu 2.0 km)` and the city built cleanly 583 rows later. No
prior cycle could say that.

### 2.4 Two standing owner questions, reported again and not re-opened

- **AGG16-20** — CLAUDE.md's "~7 per step is the ceiling" is measured false (10 of 12
  schemes exceed it, vivid at 9.6). The *rule* (ΔE ≥ 6) holds and is enforced; only the
  parenthetical arithmetic is wrong. **Fourth cycle running.** CLAUDE.md is the owner's file
  and this cycle does not edit it unasked.
- **AGG16-21** — map labels at 11 px are below 4.5:1 on 34 of 37 bands; 1.00:1 for the
  departure button. Every remedy is a visible change to the band ramp, which is standing
  design policy. An owner design decision, with the measurement attached.

---

## 3. Scheduled this cycle

Eight tasks. All page-side, test-side, gate-side or doc-side — all verifiable without the
rebuild, per the owner's brief ("deploy per cycle and make sure to test every cycle").

### C16-1 — Typing a city's exact name can depart from a different city
**From AGG16-1 (UX16-1) · Severity HIGH · Confidence High · LIVE · REGRESSION from C15-1**

`web/app.js:3610,3620-3622`:

```js
const matched = f ? cities.filter((c) => (c.skey ?? c.key).includes(f)) : cities;
```

`cities` is sorted `a.name.localeCompare(b.name)` once at `:3499` and never re-ordered.
The airport path twelve lines below has a **four-tier ranker** (`rankAirport`, exact code →
prefix → word boundary → substring, then airport size, then name length). The city path has
**none**. `:4027`'s Enter handler clicks row 1.

C15-1 dropped the apostrophe family from `fold()` — correctly, and it fixed a real defect —
but that made `xi'an` fold to `xian`, which is a substring of `feng·xian·g`. I reproduced it
by lifting the real `fold()` out of `web/app.js` and running it over the shipped
`dist/index.json`:

```
xi'an | fold=xian | hits=4 | FIRST=Fengxiang (fengxiang) | all: Fengxiang / Xi'an / Xiangyang / Xinxiang
```

A visitor types the exact, correctly-spelled name of a city of 13 million, presses Enter,
and departs from a district of Shanghai. Cycle 15's own verification recorded `Xi’an → 4`
as a pass: **it counted hits and never asked which was first.**

Scanning all 553 shipped names for "the exact name does not rank first", `Xi'an` is the one
genuine case (the other four are same-name duplicate cities). The rebuild takes the list to
1,464 and the collision surface with it.

- [ ] **C16-1.1** Give the city path a ranker with the same shape as `rankAirport`: exact
      folded key first, then prefix, then word-boundary (`(" " + key).includes(" " + f)` —
      the test the comment at `:3490` already says the ranking step performs), then any
      substring. Rank **once** into a temporary and sort on the stored rank, exactly as the
      airport path does; the comment at `:3640` records why (O(n log n) evaluations cost
      4.5× there).
- [ ] **C16-1.2** Break ties within a rank the way the list already implies: alphabetical.
      Do not invent a popularity signal — `index.json` ships none.
- [ ] **C16-1.3** A test over the **shipped** origin names asserting the general property,
      not the instance: for every origin name, folding that exact name and ranking must put
      that origin first. This is the guard cycle 15 lacked.
- [ ] **C16-1.4** Mutate and confirm RED: remove the ranker, and C16-1.3 must fail naming
      `Xi'an`. Record the result.

**Explicitly NOT in scope:** DEF15-36 (search typeable before listeners exist). Cycle 15
deferred it to avoid two changes to the search path in one cycle, and that reason is *more*
binding now that C16-1 is a High live regression in the same path. Re-deferred in §5 with
its original severity and the measurement UX16 added (a **14.6-second** window on Slow 3G).

### C16-2 — The deploy gate refuses the one mode documented not to need `dist/`
**From AGG16-2 (CR16-1, VER16-4, TE16-1, DBG16-6) · Severity HIGH · Confidence High · four-lane agreement**

`scripts/deploy_verify.sh:103-108` (C15-2) refuses the deploy on **any** skip in the page
gate. In the same twelve commits, C15-1 and C15-3 added four `dist/`-conditional skips *to
that gate's own file set*: `tests/web/test_origin_near.py:106,113`,
`test_search_fold.py:118`, `test_city_label_dots.py:251`, joining
`tests/test_licence_firewall.py:73`. Measured with `dist/` hidden: **21 passed / 0 skipped
→ 14 passed / 7 skipped.** `dist/` is gitignored, so that is every clone.

`--page-only` is documented at `deploy_verify.sh:17-19` as "web/ only: no dist gate" — the
mode for "a page fix while a rebuild owns dist/", which is precisely this cycle's situation.
It also contradicts `tests/test_licence_firewall.py:118-123`, which asserts that a skip is
the *correct* answer for an unbuilt tree.

- [ ] **C16-2.1** Distinguish the two kinds of skip. A skip whose reason is "no built
      `dist/`" is expected in `--page-only` and must not refuse; any other skip must still
      refuse, because that is the hole C15-2 correctly closed. Use pytest's own machinery
      (`-rs` short summary, or a marker) rather than parsing prose.
- [ ] **C16-2.2** Mutate and confirm RED both ways: a non-`dist/` skip must still refuse,
      and a `--page-only` run on a tree with no `dist/` must succeed. Two mutations, both
      recorded.

### C16-3 — The deploy gate counts one word and asserts no floor
**From AGG16-3 (VER16-1, DBG16-6) · Severity HIGH · Confidence High · PROVEN**

`scripts/deploy_verify.sh:97`:

```sh
skipped=$(grep -oE '[0-9]+ skipped' "$out" | tail -1 | cut -d' ' -f1 || true)
```

`skipped` and nothing else. The verifier lane lifted the real `page_gate()` out of the
script and ran it under bash with stubs. The controls behave — node absent refuses, a skip
refuses, a failure refuses — but:

```
3 passed, 421 deselected in 0.10s   rc=0  PASSED (gate said OK)
1 passed in 0.01s                   rc=0  PASSED (gate said OK)
421 passed, 19 xfailed in 30.00s    rc=0  PASSED (gate said OK)
```

Reachable **today**: `pyproject.toml:47` already carries `-m 'not network and not
real_multi_band'`, so one `pytestmark = pytest.mark.network` on `tests/web/test_parses.py`
— the gate's own comment calls it "why this stage is worth having at all" — removes it from
the deploy gate silently. Confirmed with a real pytest run: `1 passed, 2 deselected`,
exit 0. A `tests/web/` that collects nothing also exits 0, because the other two paths
collect.

- [ ] **C16-3.1** Refuse on `deselected`, `xfailed`, `xpassed` and `error` as well as
      `skipped`.
- [ ] **C16-3.2** Assert a **floor on the passed count**. The gate currently proves that
      nothing failed; it must prove that something ran. Derive the floor from the collected
      count rather than hard-coding a number that drifts.
- [ ] **C16-3.3** Mutate and confirm RED: add a `pytestmark` that deselects
      `tests/web/test_parses.py` and the gate must refuse. Revert immediately.
- [ ] **C16-3.4** While in this function: **nothing in the repo runs `ruff`** — no CI, no
      pre-commit, zero references in either deploy script (VER16-5). The configured `select`
      is adequate (the four correctness rules it omits fire on nothing at HEAD); the gap is
      that it is never invoked. One line in `page_gate()`.

### C16-4 — A false statement about the model is live on the site
**From AGG16-4 (DOC16-1, CRIT16-3) · Severity HIGH · Confidence High · LIVE**

`web/index.html:1086-1094`, echoed at `web/llms.txt:37-40`, says the Shinkansen error has
"two causes, and neither is speed", and that "the per-stop allowance for the other fifteen
dominates the journey". Two lanes computed it separately from `graph/rail.py:148`'s own
formula and `calibration.toml`'s own figures, and agreed on the shape:

| Quantity | Value | Share |
|---|---|---|
| Journey as priced | 621.3 min | — |
| Running time (650 km chord × 1.2 ÷ 81.8 km/h) | 572.1 min | **92.1%** |
| Per-stop allowance, all 20 legs | 49.2 min | 7.9% |
| The fifteen *extra* calls | 36.9 min | **5.9%** |
| Error removed by correcting the tier alone | 301.1 of 431.3 min | **69.8%** |
| Error removed by correcting the stop count alone | 36.9 min | **8.6%** |

*(Corrected during implementation. The review's table paired "~37 min" with "17.8%" and
those come from two different worlds: 36.9 min is 8.6% of the 431.3-minute error, while
17.8% is the `15 x 5.11 = 76.7` min that dropping the calls saves **after** the tier is also
corrected. The shipped copy quotes 9%, the share that matches the minutes beside it.
Correcting both still lands near 4 h, so a better tag alone would not reach the published
time — which the new copy says.)*

So the allowance does not dominate anything, and the second cause the paragraph names — the
`highspeed` tag sitting on the ways rather than the route — **is** a speed error.
`calibration.toml:256-257` never claims domination; the paragraph misreads its own citation,
and `calibration.toml`'s own "if it were tiered high_speed **5.3 h**" contradicts it.

- [ ] **C16-4.1** Rewrite the paragraph to say what the arithmetic says: the dominant cause
      is that the relations carry no `service` tag, so all three price at the default tier;
      the stop count is a second, smaller contributor. Give the two shares.
- [ ] **C16-4.2** Make the same correction in `web/llms.txt`, which carries the same claim.
- [ ] **C16-4.3** A test pinning the shipped prose against `calibration.toml`'s figures, so
      the next person to retune the rail block is told the copy has gone stale. `check_dist`
      already reads page copy for exactly one thing (a hard-coded city count); this is the
      second.

### C16-5 — Four accessibility and copy defects whose exit criteria have fired
**From AGG16-5, AGG16-9, AGG16-10, AGG16-11 · Severity MED-HIGH to LOW**

Grouped because they are one pass over `web/index.html` and its ARIA, and because three of
the four are cycle-15 deferrals whose exit criterion fired when cycle 15 shipped.

- [ ] **C16-5.1** (AGG16-5, UX16-2, **MED-HIGH**, **WCAG 2.2 SC 2.4.11 hard failure**) Tab
      in the itinerary lands focus **100% under** the sticky `.leg.total` — 5 of 5
      `elementFromPoint` samples, at 1280×800 *and* 844×390. `.legs` is a scroll box with no
      `scroll-padding-bottom`. One declaration. **Mutation:** remove it and the focus probe
      must go red.
- [ ] **C16-5.2** (AGG16-9, DEF15-35 **FIRED**, MEDIUM) 553 `role="option"` rows carry no
      `aria-selected`; selection is carried by the word "departing" (SC 4.1.2). Its exit
      criterion was "the next page cycle, immediately after C15-1 and C15-4 have been
      browser-verified" — both were, in cycle 15 §8.
- [ ] **C16-5.3** (AGG16-10, DEF15-37 **FIRED**, MEDIUM) `web/index.html:822-823` — three
      bare percentages precede the sentence that defines them. Exit criterion was "with the
      next page-copy pass, after C15-6"; this is that pass (C16-4).
- [ ] **C16-5.4** (AGG16-11, DEF15-58 **FIRED**, LOW) `web/sitemap.xml:4` `lastmod` and the
      JSON-LD `dateModified` both still say 2026-09-10 against a page changed 2026-09-16.
      Exit criterion was "the next page-copy pass, with DEF15-37". `sitemap.xml` is the one
      deployed file no test opens — add the assertion at the same time, or the date goes
      stale again next cycle.

### C16-6 — The licence page's pointer to the data credits does not work
**From AGG16-6 (DOC16-2) · Severity MED-HIGH · Confidence High · LIVE**

C15-6.5 changed `web/vendor/licences/index.html:93` to link `../../#key`, and the ledger
verified only that "the id exists". But `web/index.html:1040` is `<details id="key">` with
no `open`, and the HTML ancestor-revealing algorithm opens only an **ancestor** `details`,
never the target itself. `web/app.js:4115-4127` is a click listener on in-page anchors —
useless for a cross-document arrival — and `grep -n hash web/app.js` returns nothing.

A visitor following the compliance page's pointer to the data credits still sees none.

- [ ] **C16-6.1** Point at `../../#credits`, which is *inside* `#key` and therefore has an
      ancestor `details` for the algorithm to open. (Verify the id before relying on it —
      that is the mistake this task exists to correct.)
- [ ] **C16-6.2** A test in `tests/web/test_attribution_and_privacy.py`, which already
      parses `index.html`: every cross-document fragment link from `web/vendor/licences/`
      must name an id that is either outside a closed `<details>` or inside one. **Mutation:**
      point it back at `#key` and the test must go red.

### C16-7 — Three gates that cannot fail, all proven by mutation
**From AGG16-8, AGG16-13, AGG16-14, AGG16-15 · Severity MEDIUM · test-side, ships now**

CLAUDE.md: "A test that passes when the code is deliberately broken is worse than none."

- [ ] **C16-7.1** (AGG16-8, **DEF15-20 FIRED**, VER16-3) Three mutations, each proven:
      neutering `check_dist`'s `water.pmtiles` refusal → `test_check_dist.py` **48 passed**;
      dropping the three JSON extras from `REQUIRED_EXTRAS` → **48 passed**; deleting
      `browser_verify.sh`'s water block → `test_deploy_script.py` **12 passed**. CLAUDE.md
      names `water.pmtiles` a deploy invariant and nothing guards its guard.
      **Correction for whoever implements this:** deleting the *whole* `REQUIRED_EXTRAS`
      loop *does* go red, but only via an unrelated gzip-metadata test. Anyone who tries
      that mutation first will wrongly conclude the guard exists.
- [ ] **C16-7.2** (AGG16-13, ARCH16-2) `tests/emit/test_build_identity.py:74-79`:
      `called = {n for n in STAMPED if f"config.{n}" in body}` is a subset of `STAMPED` by
      construction, so `assert called == set(STAMPED)` restates the loop above it. A
      `config.X` added to `params_hash` with no table row stays green. The failure message
      prints the symmetric difference **labelled backwards**. The pattern was then copied to
      `tests/sources/test_cache_provenance.py`'s 34-row `STAMPED` **without even the
      one-directional half**. Fix both; mutate both.
- [ ] **C16-7.3** (AGG16-14, TE16-3) `tests/web/test_search_fold.py:118` reads
      `dist/index.json` (553 names) when `data/origins.toml` (1,464, checked in) is
      available, and its comment claims a fallback the code lacks. Run over all 1,464: **0
      misses** — so the guard will not go red when the build finishes. Read the checked-in
      file. This also removes one of C16-2's `dist/`-conditional skips.
- [ ] **C16-7.4** (AGG16-15, CR16-3) `tests/web/test_module_scope_order.py:144-152`
      truncates a listener registration at the first newline, so `web/app.js`'s one
      multi-line pre-await listener — `map.on("error", …)`, the only one that fires *during*
      the 20-second load window — contributes **zero** seeds. Replaying the test's own
      regexes: `noteTileTrouble: False`, `announce: False`. Cycle 15 wired `announce(say)`
      into exactly that region; it is safe only because `announce` happens to be a hoisted
      `function` rather than an arrow `const` like its neighbour two lines above. Seed from
      the handler **body**.

### C16-8 — The repo's three-way disposition rule is false for three cycles
**From AGG16-12 (ARCH16-1, CRIT16-5, CRIT16-6, SEC16-2, PR16) · Severity MEDIUM · five lanes**

`plan/README.md:33-37` states that every review finding is "scheduled in one of the plans
here, fixed in a commit whose body carries the evidence, or recorded in `deferred.md`".
Measured:

```
grep -c 'DEF15-' plan/deferred.md            → 0
grep -c 'DEF15-' plan/2026-09-16-c15-…md     → 137
last block heading in plan/deferred.md        → "# Cycle 12"
```

Cycles 13, 14 and 15 each deferred into their own per-cycle findings file. **Nothing is
lost** — every row exists, with citation, severity, reason and exit criterion — but the
routing rule the README states is not the one the repo follows, and that had a live cost
this cycle: `_cycle16_brief.md:45` told all eleven lanes to grep `deferred.md` for prior
art, and a lane doing exactly that gets zero hits for the last three cycles.

Two smaller ledger defects found alongside it, both real:

- `SEC15-1` was carried as **"DEF15-61a"** — an ID in **no table**, absent from
  `deferred.md`, and colliding with the unrelated `DEF15-61`. Its stated rationale ("same-
  origin content this project writes") is **false**: `emit/places.py:64-65` writes GeoNames'
  community-edited `name`/`region`/`country` verbatim, and those are exactly what the two
  unpinned `esc()` calls guard.
- All three of cycle 15 §3's ledger actions were recorded as done and **not performed**
  (M8-14 still at `deferred.md:28`, AB53 unchanged, SEC-8(a) uncorrected), and both of §3's
  citations are 24 lines stale.

- [ ] **C16-8.1** Correct `plan/README.md` to describe the rule the repo actually follows —
      a per-cycle findings file is a fourth, legitimate disposition — and say where each
      cycle's deferrals live, so the next brief points its lanes at the right file.
- [ ] **C16-8.2** Give `SEC15-1` a real ID and a real row, at its original severity. Correct
      its rationale: the content is not same-origin-authored.
- [ ] **C16-8.3** Perform cycle 15 §3's three unperformed ledger actions, or record
      explicitly that they were not performed and why. Do not re-tick them.
- [ ] **C16-8.4** Correct `plan/deferred.md:670`: "`blob:` is redundant in `script-src`" is
      **wrong** — Safari does not implement `worker-src`, so the one-token deletion would
      break MapLibre there. A CSP change made on that row would have broken the site in
      Safari.

---

## 4. Plans archived this cycle

Per `plan/README.md`'s own convention — *a plan is archived on the state of the TREE, not on
the state of its own checkboxes* — each was spot-verified by grep before moving.

| Plan | Ticks | Verified |
|---|---|---|
| `2026-09-13-c9-page-failure-paths.md` | 31/31 | 7 sampled, **7 hold**: C9-1 (`let bandMark` at `app.js:342`), C9-3 (`check_dist.py:339-346` checks the offsets pair), C9-4 (`.mapbtn:focus-visible{…outline-offset:-2px}` at `index.html:612` — the minified form, which a naive grep misses), C9-21 (`df -Pk '$DEPLOY_ROOT'` quoted at `deploy_verify.sh:165`), C9-22, C9-24 (`test_cli.py:230-237`, per-line), C9-26 |
| `2026-09-15-c14-review-findings.md` | 7/7 | The rail parser work landed in `e7a90c7`/`15870ac`/`5849e0d`; C14-7's 20-minute figure is in `calibration.toml:290` with its arithmetic |

`2026-09-15-c14-rail-service-tiers.md` stays **open**: 11 of 21, and DOC16-3 found a real
gap in it — the ledger says "all three surfaces now say the same thing … plus a separate
20 km/h tier for heritage lines", but `emit/index.py:180-189` never got that clause (its
`git show` is +3/−1 and adds only the "where it carries one" text). Recorded as **DEF16-3**.

`2026-09-16-c15-review-findings.md` stays **open**: C15-5.5 and C15-6.7 are recorded not
done, and §5 below carries three further audit findings against its ticks.

---

## 5. Deferred — every remaining finding, with reason and exit criterion

Severity and confidence are the values the lane assigned. **None is downgraded to justify
deferral.** Deferred work stays bound by repo policy when picked up.

| ID | Finding | Cite | Sev | Conf | Reason | Exit criterion |
|---|---|---|---|---|---|---|
| DEF16-1 | `emit/index.py` writes `readingRes`/`readingParentsUrl`/`readingUrlSuffix` **unconditionally** while only `readingParentCount` is guarded, so a `reindex` over a pre-tier build makes `app.js:108`'s designed `READING_RES ?? null` fallback unreachable and substitutes a **404 per origin switch, forever** (the catch clears the memo, so it retries). `check_dist` cannot see it — its whole reading block sits inside `if parents_path.exists():` | `emit/index.py:340-348,360-362`; `cli.py` reindex path; `app.js:108` | MEDIUM | High | Build-path. `emit/index.py` is imported by the build running right now, and `reindex` is its publish path — the same code §2.1 says the owner must run next. Changing it mid-flight is the forbidden disturbance | The build is not running, **and before the next `reindex`** — with DEF15-15, which is the same call |
| DEF16-2 | `reading_parents.bin` / `*.r6.bin` 404 is **silent end to end**: not in `deploy_verify`'s probe list, not asserted by `browser_verify`, console warn unseen. `index.json` carries `readingRes: 6` today, so readings silently drop to res-4 — which `app.js` itself measures as differing at **96.4% of land points, p99 5 h** | `deploy_verify.sh` probes; `browser_verify.sh:431`; `app.js:108` | MED-HIGH | High | The gate half is real and shippable, but it is the same console-visibility mechanism as C16-7's `browser_verify` work and the same probe list C16-2/C16-3 are already rewriting. Three independent edits to the deploy gate in one cycle would make none of them attributable | The cycle after C16-2 and C16-3 have shipped and been browser-verified |
| DEF16-3 | `emit/index.py:180-189`'s `modeDetail.rail` never got the heritage-tier clause the c14 ledger says all three surfaces carry, so the itinerary tooltip will still disagree with the page after the rebuild | `emit/index.py:180-189`; `plan/2026-09-15-c14-rail-service-tiers.md:828-836` | MED-HIGH | High | Build-baked: `modeDetail` is written into `index.json` by the pipeline. Not covered by DEF15-3, which is about a different sentence in the same field | The rebuild **and** the `reindex` of §2.1; land with DEF15-3 as one pass over `modeDetail.rail` |
| DEF16-4 | `contour/grid.native_edges`'s cache key omits `idx.fine`. **Demonstrated: 24 of 120 edges lost and 6 cells mis-marked incomplete from a cache hit.** No test executes either cache branch; `contour/grid.py`'s two caches are the only `config.BUILD` caches outside the `_params_hash`/STAMPED regime | `contour/grid.py` | MEDIUM | High | A **direct CLAUDE.md invariant violation** ("caches key on `_params_hash` of the constants **and inputs**"), so **not deferred on merit**. Same blocker as DEF15-5: changing a cache key invalidates `data/cache/`, which the running build is reading | The build is not running. Land with DEF15-5's five re-keys as one cache-provenance pass |
| DEF16-5 | `calibrate/fit.py` has **no runnable producer** — nothing in `src/` or `scripts/` imports it — so `[airborne]`'s FITTED `cruise_kmh = 844` / `climb_descent_penalty_min = 15.0` cannot be reproduced from the tree. The design specified `fit.write_calibration()` and `calibrate/fr24.py`; `fr24.py` was replaced by `adsb_extract.py` and the join was never rebuilt | `calibrate/fit.py`; `scripts/adsb_extract.py:10`; `calibration.toml` `[airborne]` | MEDIUM | High | A CLAUDE.md provenance violation ("fitted … and against what"), so **not deferred on merit**. Identical in kind to DEF15-9 and DEF15-31, and settling it means re-running a fit against data the live build holds open — the reasoning cycle 14 applied to the Shinkansen pass, respected | The build is not running. With DEF15-9 and DEF15-31, as one provenance pass over `calibration.toml` and its three fitters |
| DEF16-6 | `test_calibration_provenance.py` checks a table's *label* but never that a table marked FITTED names a **producer that exists** | `tests/test_calibration_provenance.py` | MEDIUM | High | The guard's whole value is catching DEF16-5's and DEF15-9's contradictions, and those cannot be corrected until the fits can be re-run. Tightening it first goes red against blocks nobody can yet fix — the same reason DEF15-8 was deferred | With DEF16-5 and DEF15-8/DEF15-9, as one pass |
| DEF16-7 | `logging.basicConfig` carries no `%(asctime)s`/`%(process)d`: **1,642 rows across five runs, zero timestamps, no dates.** rebuild17 and rebuild19 record no ending at all | `cli.py` logging setup | MEDIUM | High | `cli.py` is the running build's entry point. This is the module the orchestrator's rule most directly protects | The build is not running. First task of the next build-path cycle, with DEF15-13/14 |
| DEF16-8 | stdout/stderr interleave with different buffering, so **log order is not chronological** — proven: the `rail: included…` line sits at position 1 in rebuild18 and position 7 in rebuild21 with identical content. The serial solve path never flushes | `cli.py`; `/private/tmp/rebuild*.log` | LOW | High | Same file and same blocker as DEF16-7 | With DEF16-7 |
| DEF16-9 | `dist/water.pmtiles` is **three emitter changes stale** and leaks absolute paths: header `max_zoom = 12` vs `MAX_ZOOM = 11`; `--detect-shared-borders` vs the current `--no-simplification-of-shared-nodes`; `/Users/hletrd/…` plus the macOS per-user confidential temp segment in `name`/`description`/`generator_options`, reachable with one `Range: 0-4095` GET. **All 960 archives in `dist/` decoded: exactly 1 leaks**, so the per-origin `cwd=scratch` fix works | `dist/water.pmtiles`; `emit/water.py:113-142`; `check_dist.py:145-159` | MEDIUM | High | The remedy is one command — `scripts/build_water_tiles.py` — and that command **writes under `dist/`**, which the orchestrator forbids while the build runs. Adding the `check_dist` zoom/path assertion *without* regenerating would turn the gate red and block every deploy this cycle, including this one | The build is not running. Then regenerate `water.pmtiles` and land the `check_dist` header assertion **in the same commit**, so the guard and the fixed artifact arrive together |
| DEF16-10 | `wire.parse_query`'s `getter` parameter has **zero callers and zero tests**; `MAX_QUERY_CHARS` bounds `query`, not what the getter returns; a getter returning a list raises `AttributeError`, which `handle`'s blanket `except` reports as **503 + `Retry-After: 60`** — a 400-class bug as an outage. `RETRY_AFTER_S` is emitted as a header `solvePoint` never reads | `service/wire.py`; `web/app.js` `solvePoint` | MED-HIGH | High | The solver service is designed-not-built (`plan/2026-09-14-c13-solver-service.md`: 4 of 12, nothing resident started). Same reason as DEF15-22 and DEF15-25, unchanged | The solver service gains its first resident process |
| DEF16-11 | A shared permalink restores **only settings that were not the defaults**: `syncPermalink` omits `scheme`/`sea`/`north`/`places` when they equal the program default, and the read side treats absence as "use your own localStorage". Two readers, one link, different colour scheme *and* a different pin label. The comment at `app.js:390-401` promises the opposite | `web/app.js:390-401`, `:4446` | MED-HIGH | High | Genuinely shippable and only deferred on bounded scope: C16-1 already changes the search path and C16-5 changes four things in the page's ARIA and copy. A fifth independent page change in one cycle would make none individually verifiable — the reason cycle 15 gave for DEF15-35, applied consistently | The next page cycle, immediately after C16-1 and C16-5 have been browser-verified |
| DEF16-12 | `settle()` runs **5× per origin switch** and guards only 1 of its 4 consumers: ~24 forced synchronous layouts, 3.27 ms of 90,740-cell scanning, ~490 `lookup()`, ~486 `map.unproject`, ~264 DOM nodes per switch, five-sixths redundant | `web/app.js` `settle()` | HIGH | High | Page-side and the cheapest half is one substitution (`refreshScale()` → `scheduleScaleRefresh()`, exactly what C15-3.1 did for `resize`). Deferred only because C16-1 rewrites the function that *triggers* an origin switch; measuring a switch-path perf change in the same cycle that changes what a switch selects would confound both | Immediately after C16-1 ships and is browser-verified; same lane, with DEF15-39 |
| DEF16-13 | `clearHighlight()` has no "already clear" guard while `highlight()` eight lines above does, so **every pointer frame** over sea, off-globe, or over not-yet-loaded land posts a MapLibre GeoJSON worker update | `web/app.js` `clearHighlight()`, `renderRoute`'s `clear()` | MEDIUM | High | One line each, and real — but it is the pointer path, which is also DEF15-45's (`nearestPlace` twice per frame) and DEF15-2's. Landing one pointer-path change per cycle makes each measurable; landing three makes none | With DEF15-45 and DEF15-2, as one pointer-path pass, after C16-1 |
| DEF16-14 | `pmtiles.Protocol.tiles` is an **unbounded `Map`**: each visited origin leaves a `PMTiles` instance with its own 100-entry directory cache, never released. Measured 9 leaf dirs / 33,085 entries per archive ≈ 150–400 KB retained per visited city | `web/app.js` pmtiles protocol setup | MEDIUM | High | Only bites a session that visits many cities, and the eviction policy is a judgement call (how many origins should stay warm?) that is worth making deliberately rather than beside four other page changes | A page-perf cycle, with DEF16-12 |
| DEF16-15 | `airports.find()` linear-scans 4,008 rows **~75 times per `renderLegs()`** — and there is a **fifth** scan site nobody listed (`app.js:3649`, 4,008 `toLowerCase()` allocations per keystroke) that the same one-line `bySlug` fix removes | `web/app.js:2291,2396,2489,3846,3649` | LOW | High | Carried from **DEF15-40**, whose exit criterion ("any cycle touching `renderLegs()`") has **not** fired — cycle 15's fifteen `app.js` hunks touch nothing in `renderLegs`/`renderRoute`/`legsTo`. New evidence raises the multiplier and adds a site; the criterion is unchanged | Any cycle touching `renderLegs()`. The `:3649` site fires earlier: land it with C16-1, which is in that function |
| DEF16-16 | Unbounded decompression at **four** sites, not the one the existing deferral scopes: `sources/roads.py:40,47` and `emit/places.py:50-51` run on every cold-cache `build-all` | `sources/roads.py:40,47`; `emit/places.py:50-51`; `emit/water.py` | LOW | High | Build-path; both modules are imported by the running build. Verified **not** Zip Slip (fixed destinations; `adsb_extract.py` never unpacks to disk), which bounds the severity | The build is not running; land with DEF15-5's `sources/` pass, which touches the same files |
| DEF16-17 | `scripts/osm_rail.sh:31-37` feeds a **server-supplied `%{url_effective}`** to a second `curl` unvalidated | `scripts/osm_rail.sh:31-37` | LOW | High | A maintainer-only script against a hard-coded host, not visitor-reachable — the same trust boundary cycle 9 recorded for `adsb_extract.py` as DEF9-29 and cycle 15 re-affirmed as DEF15-50. Never examined in fifteen cycles, so it is recorded now at its true severity | The Shinkansen `highspeed` pass is scheduled (it re-cuts this extract); pin it with DEF15-29's selector work, in the same cycle |
| DEF16-18 | The inline-script CSP hash is pinned only against the repo's `index.html`, while the conf is an **out-of-band operator install**. Confirmed the hash currently matches both `web/` and `dist/` — so it is one edit away from silently blocking the live inline script, with no gate able to see it | `deploy/worldmap-security-headers.conf`; `tests/web/test_csp.py` | LOW | High | The orchestrator's constraint 5 forbids touching `deploy/worldmap-security-headers.conf`, which is correct in the repo and awaiting operator action: *"Do not try to work around it."* The **test half** is untouched by that rule but is worthless without the conf half | The operator installs the current headers file; then pin the hash from both sides in one commit |
| DEF16-19 | C15-3.2's 60-row filter cap truncates the **country** search added for the 1,464-origin roster: measured on `data/origins.toml`, CN has 160 origins and IN 82, so 100 Chinese cities are unreachable by `china`/`cn`, and the footer's "Keep typing to narrow it" is advice a country query cannot act on | `web/app.js` `UNFILTERED_CAP` path | MEDIUM | High | Cannot be observed until the rebuild publishes 1,464 origins — at the shipped 553 no origin carries a country and the interaction cannot appear. C16-1 changes the same slice, so the fix belongs with the measurement | The rebuild publishes 1,464 origins; then re-measure and cap per-group rather than globally |
| DEF16-20 | `railVia` prints OSM names verbatim: live on Seoul→Busan the itinerary reads `via 구포 (경부선 KTX: 서울 → 부산 (구포경유))` as a bare text node under `<html lang="en">` — **WCAG SC 3.1.2**. Corrects cycle 15's "no Language-of-Parts exposure" clean | `web/app.js` `railVia`; `.rail.json` captions | MEDIUM | High | The page cannot know the language of an OSM string — `.rail.json` ships no language tag, so an honest `lang` attribute needs a pipeline change and the rebuild. Guessing from the script would be wrong for the Latin-script cases that are the majority | The rebuild carries a language tag on rail captions, **or** the owner accepts script-detection as an approximation. Raise it as the pipeline question it is |
| DEF16-21 | When `app.js` fails to load, `#status` is **empty at every viewport**; the "could not start" message is 12 px of `--text-2` filed in a region named "Travel time reading" | `web/index.html` `#status`; `web/boot.js` | MEDIUM | High | This is the fatal-error surface C15-4 rewrote. Cycle 15's changes to it have been browser-verified once; a second rewrite in the next cycle, beside C16-5's four ARIA and copy changes, would make neither attributable | The next page cycle, with DEF16-11, after C16-5 is verified |
| DEF16-22 | C15-5.1 is **ticked as a class fix and shipped as an instance fix**: `hermetic_build` is opt-in, used by **1** of 6 BUILD-cached entry points against **7** hand-rolled `monkeypatch(config, "BUILD")` sites. Proven in-process: patching `roads._ensure_raster`/`landmask._land_parts` to raise, both builders return without entering — reversing `roads.py:77`'s `range(N_TYPES, 0, -1)` is not in the cache stamp and leaves four tests green. Carries **DEF15-54** (exit criterion "C15-5.1 lands", **FIRED**) | `tests/conftest.py` `hermetic_build`; `tests/sources/*`; `config.py:5-9` | MEDIUM | High | Genuinely shippable and the safe fix is small (~10 lines: a directory-scoped autouse `tests/sources/conftest.py`; the suite-wide cost that justified opt-in does not apply to those 11 files). Deferred only because C16-7 already makes four independent changes to the test suite's guards, and a fifth — one that changes what every `tests/sources/` test can see — would make the four unattributable | The cycle after C16-7 lands and the suite is green. Land the autouse fixture **and** write `config.py`'s `CACHE`-vs-`BUILD` rule down in the same pass, which is DEF15-54's other half |

| DEF16-23 | **`esc()`'s sink inventory cannot follow a value through a helper hop**, so `describe()` and `mode()` are invisible to it and three `esc()` calls can be deleted with the guard staying green. Carried out of cycle 15 as **"DEF15-61a"** -- an ID that appears in **no deferral table**, is absent from `plan/deferred.md`, and **collides with the unrelated DEF15-61**. This row replaces it | `tests/web/test_esc.py:300-350`; `web/app.js` `describe()`, `mode()`; `emit/places.py:64-65` | MEDIUM | Med-High | Cycle 15's stated reason was bounded scope (a fifth test-harness change beside four others), which is sound and applies again this cycle -- C16-7 already makes four changes to the suite's guards. **But cycle 15's rationale also called the path "same-origin content this project writes", and that is false:** `emit/places.py:64-65` writes GeoNames' community-edited `name`/`region`/`country` **verbatim**, and those are exactly what the two unpinned `esc()` calls in `describe()` guard. The severity is unchanged; the reason for deferring is bounded scope alone, not the absence of third-party content | The cycle after C16-7 lands, with DEF15-26 (the untested ramp maths), which touches the same file's slicing machinery |

| DEF16-24 | **`browser_verify.sh` cannot see the error surface cycle 15 built.** Its console check greps `/error|exception/i`; C15-4's nine `okOr` calls print `"places.json: HTTP 404 Not Found"` and five siblings pass `err.message` (a string), so **14 lines are invisible to it**. The one line it does catch works only because it happens to pass an Error *object*. `agent-browser errors` is never read anywhere in the repository | `scripts/browser_verify.sh:431`; `web/app.js` `okOr` sites | MED-HIGH | High | **Scheduled in §3's table and then not given a task — recorded here rather than dropped, which is the rule.** This cycle has already made two independent changes to the deploy gate (C16-2/C16-3's `page_gate` rewrite, and the `ruff check` it now runs) and one to `browser_verify.sh`'s guard set (C16-7.1). DEF16-2's reasoning applies to itself: three independent edits to the deploy path in one cycle would make none of them attributable, and this one changes what can stop a deploy | The cycle after C16-2/C16-3 have shipped and been browser-verified — the same criterion as DEF16-2, and they should land together as one pass over what the browser stage can see |

### Re-deferred from cycle 15, unchanged, exit criterion re-stated

| ID | Status this cycle |
|---|---|
| **DEF15-36** | **Exit criterion FIRED** ("immediately after C15-1 ships and is verified"). **Re-deferred**, at its original MEDIUM / Med-High, for the reason cycle 15 gave and which binds harder now: C16-1 is a HIGH live regression in the same search path, and two changes to it in one cycle would confound the browser verification of both. UX16 upgraded the evidence from reasoned to measured: a **14.6-second** window on Slow 3G, end state captured. **New exit criterion: immediately after C16-1 ships and is browser-verified.** |
| **DEF15-2** | **Exit criterion FIRED** ("a trace shows >16 ms frames **or** C15-3 has shipped and been verified"). Re-deferred: the designer re-measured **CLS 0.0349, FCP 84 ms, LCP 296 ms with no jank** live, so the cost the row exists to catch is still not observable. **Flagged as structurally self-renewing:** cycle 9's DEF9-22 said "or C9-1 has shipped"; C9-1 shipped six cycles ago and the row was re-deferred anyway with the clause re-pointed at C15-3. **A criterion that can be satisfied by the next cycle's unrelated work is not a criterion.** Replace it with the measurement half only: a trace showing >16 ms frames on a non-Apple GPU. New evidence to use when it fires: `onNearSide` calls `map.getCenter()` **900× per frame** and reads `window.innerWidth/Height` up to 1,800×; those hoists are provably behaviour-preserving and separable from the risky `collides` rewrite. |
| **DEF15-27** | **Exit criterion was "re-measure and report the trend."** Done — see §6. **The trend is zero.** Recommend bounding or dropping the criterion; re-measuring a flat number every cycle is ceremony. |
| **DEF15-53** | Exit criterion has **NOT** fired (no layout change to the settings group). Unchanged. |
| **DEF15-4, DEF15-21, DEF15-26, DEF15-28, DEF15-29, DEF15-38, DEF15-45, DEF15-48, DEF15-51, DEF15-52, DEF15-55, DEF15-56, DEF15-57, DEF15-59, DEF15-60, DEF15-61** | Unchanged, reasons and criteria intact. DEF15-38 and DEF15-61 are restated to the owner in §2.4. |
| **The 44 build-blocked cycle-15 deferrals** (DEF15-1, -3, -5…-19, -22…-25, -30…-34, -39…-44, -46, -47, -49, -50 and the rest) | Unchanged. **But six of them (DEF15-1, -3, -11, -12, -32, -43) name an exit criterion — "the rebuild republishes `index.json`" — that §2.1 proves this run cannot satisfy.** Their criterion is corrected to "the rebuild **and the `reindex` that follows it**", which is a different and later event. That correction is the single most consequential bookkeeping result of this cycle. |

---

## 6. DEF15-27 re-measured (the brief's assigned deliverable)

Three lanes measured it with three different scripts and got 28/126, 34/141 and 35/143 —
which is itself a finding about ad-hoc measurement. Like-for-like on **one** script across
both revisions:

| Revision | Top-level `app.js` functions | Named in no `tests/web/` file |
|---|---|---|
| `fc1008e` (cycle 15 HEAD) | 141 | **35** |
| `c2ee764` (cycle 16 HEAD) | 143 | **35** |

**The untested set is the identical 35 names at both revisions** — none gained a test, none
newly lost one — despite cycle 15 adding 47 tests. Cycle 15's stated 33/139 reconciles
exactly: the newer scan additionally counts `$` and `showLabels`, both untested, so
**33 → 33 like-for-like.** Two functions were added (`lowerBoundLat`, `okOr`) and **both
arrived with tests**.

The useful half: cross-referencing the 35 against the 152 lines cycle 15 changed in
`app.js`, **not one of the 35 had its body edited**. DEF15-27's mechanism — "each function
gains a test when a finding touches it" — is **untested, not failing**. C16-1 will touch the
search-ranking path and should be expected to move the number; if it does not, the mechanism
is failing and the row should be re-scoped rather than re-measured.

---

## 7. Negative results recorded so the next cycle need not redo them

- `/private/tmp/rebuild21.log`: **zero** warnings, exceptions or retries in 614 success rows.
- The hour-26 death is `kota-kinabalu` (C12-1), and the live log **proves the fix works in
  production**. Closed.
- The cell universe is **byte-identical across rebuild17–21** and `hover_cells.bin` is still
  exactly 90,740 ids: **DEF15-16's silent reordering corruption has not occurred** in this
  `dist/`.
- `web/vendor/` == `dist/vendor/` by sha256; `preview.png` carries zero metadata chunks;
  pmtiles 4.5.0 and h3-js 4.2.1 carry no advisory (neither checked before); the page's
  static outbound set is exactly two hosts; `reverseGeocode` is correctly gated by the
  setting the privacy text promises.
- `pyproject.toml`'s dependencies are exact: `pyarrow` looks orphaned but is required by
  `pyogrio.read_arrow`, used in five modules.
- `ruff`'s configured `select` is adequate — B006, B023, B018 and E712 fire on **nothing** at
  HEAD. The gap is that **nothing invokes ruff**, which C16-3.4 fixes.
- `Intl.Collator` is **1.4× slower** than `localeCompare` here; the new `fold()` costs <1 ms
  total; **0 of 26** test slicers over-capture at HEAD, so DEF15-55 is maintainability, not
  correctness.
- `cli.py:483` uses `get_context("fork")`, giving a second independent confirmation of §2.2.
- All three non-monkeypatch global mutations in the test suite are properly `try/finally`
  guarded.
- Six of cycle 15's seven new tests are genuinely non-vacuous; three are exemplary (the rail
  pricing guard documents its own vacuous first attempt).
- `emit/places.py`/`airports_json.py` outputs **are** gate-required and page-fetched, so
  DEF15-28's blocking question is answered: "delete what is not reachable" does not apply.
- No structural regression from cycle 15's seven tasks; the layering is sound (no import
  cycles, `SystemExit` confined to `cli.py`, `scripts/`→`src/` coupling thin).

---

## 8. Progress

| Task | Status | Commit | Mutation evidence |
|---|---|---|---|
| **C16-1** search ranking | **done** | `d73ffc4` | Flattening `rankCity` to `return 0` reddens 4 tests and names **20 of 1,464** cities that then depart from somewhere else (Xi'an→Fengxiang, London→East London, Quito→Iquitos, Salem→Jerusalem, Cali→Aguascalientes, +15). Only Xi'an is reachable at today's 553 |
| **C16-2** `--page-only` skip refusal | **done** | `c2d11f5` | Reverting to C15-2's blanket refusal → 2 failed. A non-sentinel skip still refuses; a sentinel skip while `dist/index.json` exists also refuses |
| **C16-3** gate: deselect/floor/ruff | **done** | `c2d11f5` | Deleting the deselect loop → 1 failed; deleting the floor → 1 failed; dropping the ruff call → 1 failed; rewording the sentinel in `conftest.py` only → 1 failed. **The first deselect test was VACUOUS and is recorded as such** |
| **C16-4** false rail statement | **done** | `20c7e6e` | 7 mutations, none green; restoring the whole pre-cycle-16 paragraph reddens 6 of 7. The plan's own 17.8% figure was wrong and is corrected in §3 |
| **C16-5** four a11y + copy fixes | **done** | `ee947b2` | 8 mutations, all red. One docstring figure written from expectation, corrected to the measurement |
| **C16-6** licence-page fragment | **done** | `9711bdc` | Pointing the link back at `#key` → 1 failed. The fix was **measured in Chromium**, not argued from the spec — whose own prose states the opposite of its algorithm |
| **C16-7** four vacuous gates | **done** | `965daa7`, `68435c4` | 12 mutations across the four. Found a real gap: `routes._SECTION_RE`/`_CARGO_RE` reach the stamp with no table rows |
| **C16-8** ledger routing rule | **done** | `864bb6f` | n/a (documentation); the `grep -c 'DEF15-' plan/deferred.md → 0` measurement is in the commit body |

**Not done, and recorded rather than dropped:** AGG16-7 appears in §3's scheduled
table and was never given a `C16-n` task. It is now **DEF16-24** in §5, at its
original Med-High severity, deferred on the same bounded-scope reasoning as
DEF16-2 — this cycle has already made three changes to the deploy path.
