# Cycle 15 — review findings: scheduled, deferred, indexed

Source: `.context/reviews/` — eleven lanes run concurrently against
`feat/transport-pipeline` @ `fc1008e`, merged in `.context/reviews/_aggregate.md`.
**108 raw findings, 77 distinct after dedupe.** Per-lane IDs are `CR15-n`, `PR15-n`,
`SEC15-n`, `CRIT15-n`, `VER15-n`, `TE15-n`, `TR15-n`, `ARCH15-n`, `DBG15-n`, `DOC15-n`,
`UX15-n`; merged clusters are `AGG15-1…AGG15-77`; this cycle's scheduled tasks are
`C15-1…C15-7`.

Every one of the 77 is dispositioned in §5 below. Nothing is dropped.

---

## 1. What this cycle can and cannot do

A 38-hour `build-all` holds `dist/.build.lock` (13 h 22 m elapsed when the reviews ran,
~608 origins remaining). It has already died twice — an NFS `ESTALE` drop, and a bad
origin that raised at hour 26. The orchestrator's constraints for this cycle:

- **No writes under `dist/` or `data/`.** No second build, no `reindex`.
- **Deploys are PAGE-ONLY.** `dist/` holds 553 origins from an *older* build and
  `dist/index.json` still says 553. Cycle 14's rail work is baked into per-origin
  artifacts and reaches the site only after a future rebuild.
- **Therefore any fix in `src/transport_maps/**` cannot be verified against the live
  site this cycle**, and claiming one is live would be false.

That single constraint decides most of the scheduling below. It is not a quality
judgement about the deferred items — several carry higher severity than what is
scheduled. It is that a build-path fix landed this cycle is a fix nobody can observe
until the rebuild, and the owner's brief is "deploy per cycle and make sure to test
every cycle."

**An owner decision is pending and is not this cycle's to make:** whether to let the
running build finish (Wednesday afternoon, 1,464 cities, old rail model) or restart it to
pick up the cycle-14 rail tiers. Nothing here acts on either branch.

---

## 2. Scheduled this cycle

Seven tasks, all page-side or test-side, all verifiable without the rebuild.

### C15-1 — The search cannot find a city whose name contains an apostrophe
**From AGG15-12 (UX15-1, UX15-2) · Severity High · Confidence High**

`web/app.js:3386`:

```js
const fold = (s) => String(s).normalize("NFD").replace(/\p{M}/gu, "").replace(/ı/g, "i").toLowerCase();
```

`fold()` folds accents and dotless i and nothing else. The shipped data uses **both**
U+0027 and U+2019, so the fold is not even self-consistent. Measured live on the deployed
site by the designer lane:

| Typed | Hits |
|---|---|
| `Lu'an` (U+0027, what a keyboard produces) | **0** |
| `Lu’an` (U+2019) | 1 |
| `Tai'an`, `Xi’an`, `Huai’an`, `N’Djamena` | **0** |
| `Washington DC` | **0** |

A visitor typing the apostrophe their keyboard emits gets an empty list. The comment
above `fold()` advertises exactly this class of forgiveness ("so 'Sao Paulo', 'Zurich' and
'Bogota' match São Paulo, Zürich and Bogotá") and then does not deliver it for the one
punctuation mark that actually varies by keyboard.

- [ ] **C15-1.1** Extend `fold()` to drop the apostrophe family (U+0027, U+2019, U+02BC,
      U+2018, U+0060, U+00B4) entirely rather than normalising between them, so `Luan`,
      `Lu'an` and `Lu’an` all collapse to one key. Dropping beats mapping: it also makes
      the name findable by someone who omits the mark.
- [ ] **C15-1.2** Drop `.`, `,` and collapse runs of whitespace, which is what
      `Washington DC` → `Washington, D.C.` needs. Keep `-` folded to a space rather than
      deleted, so `Port-au-Prince` still matches `Port au Prince` both ways.
- [ ] **C15-1.3** A test over the **shipped** `index.json` origin names: for every origin
      whose name contains a character in the dropped set, assert that the ASCII-typed form
      finds it. This is the guard that would have caught the defect — the current tests
      assert on names that happen to be clean.
- [ ] **C15-1.4** Mutate and confirm RED: revert `fold()` to its current body and the new
      test must fail. Record the result in the test file.

**Explicitly NOT in scope:** searching a city in its own script (서울, 東京, Москва,
القاهرة all return 0). `index.json` ships no native names, so that needs a pipeline
change and a rebuild. Deferred as **DEF15-1** in §4 with its exit criterion, at the
designer's original Med-High severity.

**Also in scope, because it is the same keystroke:** UX15-2's second half — pressing Enter
on a zero-hit search **silently converts the departure request into a destination**
(`web/app.js:3429`, `web/index.html:933`). A search that found nothing must say so rather
than doing something else.

- [ ] **C15-1.5** Zero-hit Enter announces "No departure city called …" instead of
      re-targeting. The string already exists for the `?from=` failure path.

### C15-2 — `deploy_verify.sh`'s page gate exits 0 on 19 skipped test files
**From AGG15-6 (VER15-10) · Severity High · Confidence High · PROVEN**

`scripts/deploy_verify.sh:38-58,89,147`. `page_gate()` ends in:

```sh
uv run pytest -q -p no:cacheprovider \
  tests/test_licence_firewall.py tests/web/ tests/emit/test_water.py
```

pytest exits **0** when tests skip. 22 files under `tests/web/` need `node`; without it
**19 skip**, `page_gate()` returns success, and the rsync proceeds. The skipped set
includes the **only parse of `app.js`** and the **only legend-tick enforcement** — and the
gate's own comment says `test_parses.py` "is why this stage is worth having at all:
nothing else in the repository parses app.js, and a syntax error in it would otherwise be
rsynced live before step 4 ever opened a browser."

Proven by the verifier lane: `test_parses.py` → `3 skipped, exit=0`.

**This is not hypothetical here.** `node` on this machine resolves to
`/Users/hletrd/.local/state/fnm_multishells/7847_1788527848615/bin/node` — an fnm
*per-shell-session* path. A deploy run from launchd, cron, a fresh non-interactive shell,
or any session other than the one fnm initialised has no `node` on `PATH`, and the gate
CLAUDE.md added after two live blank-page incidents becomes decorative without printing a
word about it.

- [ ] **C15-2.1** `page_gate()` refuses on skips: capture pytest's summary and exit
      non-zero if any test in the page set skipped, naming the count and the reason.
- [ ] **C15-2.2** Check for `node` up front and fail with a direct message
      ("node is not on PATH; the page gate cannot parse app.js — refusing to deploy")
      rather than letting 19 files quietly skip.
- [ ] **C15-2.3** Test in `tests/test_deploy_script.py` that the gate refuses a skipping
      run. Mutate: remove the guard, confirm the test goes RED.

### C15-3 — Three measured page-side performance costs
**From AGG15-13 (PR15-1, PR15-2, PR15-3) and AGG15-54 (PR15-6) · Severity High · Confidence High**

Taken in ascending order of risk, and only the three whose measurement is unambiguous.

- [ ] **C15-3.1** **Throttle the `resize` listeners.** `web/app.js:586`, `:991-996`,
      `:4032` run `refreshScale()` unthrottled — 44 DOM nodes, two forced layouts, 81
      lookups per event, three listeners — while the *identical map path* at `:2838-2844`
      is already debounced at 160 ms. Reuse that debounce. This is a one-line-per-listener
      change against an inconsistency the file already documents.
- [ ] **C15-3.2** **Cap the filtered city list.** `web/app.js:3495-3503,3556-3609`: the
      capped path keeps 60, the *filtered* path is uncapped — one character builds ~1,097
      rows and **~6,600 DOM nodes per keystroke**. Apply the existing cap to both paths.
- [ ] **C15-3.3** **Hoist `dottedCityRows` off the load path.** `web/app.js:3290-3302,
      3318-3325`, entered at `:1419`: O(gazetteer rows × origins) = **1,317,600 haversine
      calls in one synchronous task** during load. Precompute once, or defer past first
      paint.
- [ ] **C15-3.4** Measure each before and after in the browser and record the numbers in
      this file. A perf change with no measurement is not a perf change.

**Deferred from this task:** PR15-2 (~405,000 collision comparisons per animation frame,
`web/app.js:1453-1502`). It is real and High, but it is the same label-collision code that
cycle 9 deferred as `DEF9-22` on the grounds that no dropped frames were ever measured —
and the designer lane this cycle again measured **CLS 0.033, FCP 112 ms** with no jank.
Carried as **DEF15-2** with the original High severity and the same exit criterion cycle 9
set: a trace showing >16 ms frames.

### C15-4 — The page's error surface is invisible to a screen reader and points the wrong way
**From AGG15-38, AGG15-39, AGG15-40, AGG15-45, AGG15-46 · Severity Medium-High**

- [ ] **C15-4.1** `#tiletrouble` is a status message in **no live region**
      (`web/app.js:713-731,1324`): a screen reader hears "Travel times from Seoul are
      ready" while the globe is blank. WCAG 2.2 SC 4.1.3. Move it into the
      already-connected `role="status"` region.
- [ ] **C15-4.2** "The travel times below are still correct" renders **91 px under**
      "Travel times unavailable", and "below" points at the **colour key** at every
      viewport (`web/app.js:713-731`). Fix the copy to name what it means.
- [ ] **C15-4.3** Six per-origin fetches turn an HTTP error status into `null` and return
      in **total silence** (`web/app.js:1877,1924-1925,1993,1997,2001`). This is the
      remaining silent-blank-page path behind the two incidents CLAUDE.md records. Route
      them through `noteTileTrouble()` so a failure is at least legible.
- [ ] **C15-4.4** Cycle 14's D15 is **half-fixed**: the folded sheet still opens a
      `display:none` panel and **now strands focus on `<body>`**
      (`web/app.js:3992-4004`, `web/index.html:709`).
- [ ] **C15-4.5** The globe wears the **1 px UA focus ring on the viewport edge**, 440 px
      of it behind the sheet at 390×844. Add `canvas:focus-visible` (and the same for the
      links at `web/index.html:611-612`).
- [ ] **C15-4.6** Verify each in the browser at all four viewports. 4.1 and 4.4 need an
      accessibility snapshot, not a screenshot.

### C15-5 — Five tests proven vacuous by mutation
**From AGG15-7, AGG15-24, AGG15-26, AGG15-3 (test half) · Severity Critical (test integrity)**

CLAUDE.md: *"A test that passes when the code is deliberately broken is worse than none…
assume a new test is vacuous until shown otherwise."* Each of these was **run**, not
inferred.

| Mutation applied | Test file | Result |
|---|---|---|
| `airports.py`: `== "yes"`→`!= "no"`, delete the 3-char IATA filter, `keep="first"`→`"last"`, delete `.sort("iata")` — **all four at once** | `tests/sources/test_airports.py` | **4 passed, GREEN** |
| `emit/rail_detail.py:166`: drop `* cal.detour_factor` | `tests/emit/test_rail_detail.py` | **19 passed, GREEN** |
| `emit/rail_detail.py:165-166`: drop **both** `stop_overhead_min` and `detour_factor` | `tests/emit/test_rail_detail.py` | **19 passed, GREEN** |
| `service/wire.py`: move the `MAX_QUERY_CHARS` check **below** `parse_qs` | `tests/service/test_wire.py` | **39 passed, GREEN** |

- [ ] **C15-5.1** **Root cause first.** `tests/conftest.py:44-48` makes `config.CACHE`
      hermetic but **never `config.BUILD`**, so any test whose subject writes a derived
      artifact to `data/build/` silently reads whatever the last real build left there.
      Make `config.BUILD` hermetic too. This is what made the airports test vacuous, and
      it is a class, not an instance.
- [ ] **C15-5.2** `tests/sources/test_airports.py` builds its own fixture and actually
      exercises the filter. Re-run the four-way mutation and confirm **RED**. Also declare
      the test's network dependence (an `integration`/`network` marker) — on a cold clone
      it would attempt a live fetch with nothing saying so.
- [ ] **C15-5.3** `tests/emit/test_rail_detail.py` pins `_line_between`'s pricing against
      `rail.ride_edges`. Re-run both mutations and confirm **RED**.
- [ ] **C15-5.4** `tests/service/test_wire.py:111-123` —
      `test_an_enormous_query_is_refused_before_it_is_parsed` documents a `parse_qs` spy
      **that does not exist**; it proves "refused", not "before parsed". Add the spy, or
      rename the test to what it checks. Confirm RED under the reordering mutation.
- [ ] **C15-5.5** `tests/web/test_esc.py:300-350` — **three `esc()` calls can be deleted
      with every gate green** because the sink inventory cannot see through `describe()`
      (`web/app.js:2861-2869`) and `mode()` (`:2492-2495`) to the sink at `:2904`. Teach
      the inventory those two hops. Confirm RED by deleting one `esc()`.
- [ ] **C15-5.6** Every one of the above records its mutation and its RED/GREEN result in
      the test file itself, per CLAUDE.md. **If a mutation stays GREEN, say so in the file
      rather than deleting the test.**

### C15-6 — Documentation that ships and is wrong
**From AGG15-5 (page half), AGG15-62, AGG15-63, AGG15-64, AGG15-70 · Severity Medium**

- [ ] **C15-6.1** The page's "Sources and method" panel (`web/index.html:1038,1069`) was
      never updated for the new rail model; `web/llms.txt` was. The two now contradict each
      other on the live site. Update the panel. **Page-side, so it ships this cycle**
      — unlike the `index.json.modeDetail.rail` half, which is build-baked (deferred as
      **DEF15-3**).
- [ ] **C15-6.2** Two claims in that same copy are false as written and must be corrected
      wherever they appear: "six service tiers from each route's own OSM `service` tag" is
      **false for 26.7% of relations** (the tag is absent and they fold to a default), and
      "six service tiers, 74–215 km/h" **excludes `tourism` at 20.1 km/h**, which the model
      applies.
- [ ] **C15-6.3** Rail's largest documented error reaches no reader, while air's and
      ferry's are tabulated on the page — and rail's is now the largest of the three (the
      Shinkansen 10.4 h against a published 3.1 h). Add it, with the arithmetic already
      written in `calibration.toml`. This is CLAUDE.md's "prefer a documented, reproducible
      error over a hidden one" applied to the one mode that hides it.
- [ ] **C15-6.4** `plan/README.md` indexes **none** of cycle 14's three plans and its
      status column is a cycle behind; three ID ranges are understated. Bring it to HEAD
      and add this file.
- [ ] **C15-6.5** `web/vendor/licences/index.html:93` links the data credits through
      `#sources`; **no such `id` exists** in `web/index.html`. A dead link on a shipped
      compliance page.
- [ ] **C15-6.6** `web/README.md:62-66` "Every file in `vendor/` appears above" is false —
      `iterdir()` cannot see the seven files under `vendor/licences/`
      (`tests/web/test_vendor.py:38`). Fix the claim and the test's reach together.
- [ ] **C15-6.7** `plan/deferred.md`: the ledger sweep's trigger **fired twice and the
      sweep did not happen**, and the edit **invalidated the sweep's own citations**
      (AB41's `graph/rail.py:113` now resolves to unrelated code). Re-point the citations.

### C15-7 — `Permissions-Policy` leaves every Privacy Sandbox advertising API at its default
**From AGG15-49 (SEC15-3) · Severity Medium · Confidence Medium**

`deploy/worldmap-security-headers.conf:29` does not name `browsing-topics`,
`attribution-reporting`, `join-ad-interest-group` or `run-ad-auction`, so all four sit at
their default `*` allowlist. That is the one advertising surface **CSP structurally cannot
reach**, while `web/index.html:1135` states the page has no advertising. The page's own
privacy claim should be enforced by the header, not only asserted in prose.

- [ ] **C15-7.1** Add the four to the `Permissions-Policy` `()` deny list.
- [ ] **C15-7.2** Assert the header in `tests/web/test_attribution_and_privacy.py` so the
      claim and the header cannot drift apart.

---

## 3. Closed by this cycle's measurement

Recorded so no later cycle re-opens them by inertia. Evidence in
`.context/reviews/_aggregate.md` §D.

| Item | Was | Measured | Disposition |
|---|---|---|---|
| **M8-14** | Legend build-date line overshoots the landscape rail by **19 px** at 844×390 | `#built` bottom **300.1** against a rail bottom edge of **390** → overshoot **0 px** | **CLOSE.** Fixed structurally by `6b309d2` merging the build date into `#disclaimer`, not by re-tuning margins. Its exit criterion is satisfied. Remove the row from `deferred.md`. |
| **fflate advisory** (`deferred.md:571`) | GHSA-px8p-9vwx-vf98 open | Vendored fflate **is 0.8.3**, which **is** the fix | **CLOSE the fflate half.** The MapLibre half stays: sanitizer has exactly one, **dead**, call site; target now 6.7.0. |
| **SEC-8(a)** (`deferred.md:646`) | An apostrophe-escaping remedy recorded in cycle 14 | The apostrophe is already guarded by a stronger invariant; **applying the recorded fix turns two tests red** (demonstrated) | **CORRECT the ledger.** The remedy as written is wrong at this tree. |
| **Cycle 14 D8** | Claimed a legend jump on desktop | Desktop does **not** jump; the jump is **35 px at 844×390** | **CORRECT** → now scheduled as part of the page work, tracked as DEF15-4 if not landed. |
| **`_walk_back_hops`** | Exercised by nothing (cycle 14) | Fixed | **CLOSED.** |
| **SRC-01** | 8 governing names unstamped | **3 remain** | **NARROWED** → DEF15-5. |

---

## 4. Deferred, with exit criteria

Rules obeyed, in the repo's own words. `CLAUDE.md` is the only rule file at the root.
Every row keeps its **original severity and confidence — never downgraded to justify the
deferral** — cites file and line, gives a concrete reason, and states what reopens it.
Deferred work stays bound by every repo rule when picked up: GPG-signed conventional
commits with gitmoji, no `--no-verify`, no force-push, Python ≥ 3.14 via `uv`, and the
standing design policy.

**The run-level constraint that bounds nearly every row below** is the orchestrator's, not
a quality judgement: *no writes under `dist/` or `data/`; no second build; deploys are
page-only; `dist/` holds an older 553-origin build.* A build-path fix landed now is a fix
nobody can observe until the rebuild.

### Not deferrable, and not deferred

No security, correctness or data-loss finding is deferred here without a repo rule or the
run constraint quoted against it. Specifically:

- **AGG15-1** (build identity, High), **AGG15-2** (`hover_cells.bin` key integrity, High),
  **AGG15-9** (NFS `atomic_write`, High), **AGG15-10** (origin identity in errors, High)
  and **AGG15-11** (seven enumerations of the per-origin artifact set, High) are **data-
  integrity findings and are NOT closed by deferral**. They are deferred **only** on the
  orchestrator's explicit constraint that this cycle must not disturb the running build,
  and each carries the strongest exit criterion in the table: *the rebuild finishes or the
  owner restarts it*. They are the first work of the next build-path cycle, ahead of
  everything else in this table.
- **AGG15-7** (cache-warm vacuous test, Critical) is **scheduled**, not deferred — C15-5.
- **AGG15-6** (deploy gate exits 0 on skips, High) is **scheduled** — C15-2.
- **AGG15-12** (search finds nothing, High) is **scheduled** — C15-1.

### The table

| ID | Finding | File:line | Sev | Conf | Reason | Exit criterion |
|---|---|---|---|---|---|---|
| DEF15-1 | No city is searchable in its own script (서울/東京/Москва/القاهرة all 0 hits) | `web/app.js:3386` | MED-HIGH | High | `index.json` ships no native names. Indexing them is a pipeline change, so it is unverifiable this cycle and would ship a search that works only for the 553 origins the old build published | A rebuild publishes native names in `index.json`; then index them in `fold()`'s key and test against the shipped names |
| DEF15-2 | ~405,000 label-collision comparisons and ~1,800 `map.project` calls per animation frame | `web/app.js:1453-1502` | HIGH | High | Same code cycle 9 deferred as `DEF9-22` for the same reason, and the reason still holds: the designer lane measured **CLS 0.033, FCP 112 ms** live with no dropped frames. Changing the label path in the same cycle as C15-3's three throttles would make neither attributable | A trace shows >16 ms frames on a non-Apple GPU, **or** C15-3 has shipped and been verified — cycle 9's own criterion, unchanged |
| DEF15-3 | `modeDetail.rail`'s tier sentence is false for 26.7% of relations and is **build-baked** into `index.json` | `emit/index.py:165-187,327` | MEDIUM | High | The page half ships this cycle (C15-6.1/6.2). This half is written by the pipeline into `index.json` and cannot reach the site without a rebuild | The rebuild republishes `index.json` |
| DEF15-4 | Legend jumps **35 px** at 844×390 on the first reading | `web/index.html:678,243-246` | MEDIUM | High | Corrects cycle 14's D8, which mis-located it on desktop. The landscape rail block is the same one `M8-14` warns against re-tuning twice in one cycle, and C15-4 already changes the page's error surface | A page cycle that has not otherwise touched the landscape rail; measure the jump before and after |
| DEF15-5 | Five of six derived caches key on the source **URL** and never on the downloaded **bytes**; one live bare `.exists()`; 3 names still unstamped | `sources/airports.py:40`, `roads.py:61`, `landmask.py:178`, `countries.py:97`, `urban.py:76`, `routes.py:270-281` | MEDIUM | High | A **direct CLAUDE.md invariant violation** ("caches key on `_params_hash` of the constants **and inputs**… never a bare `.exists()`") and not deferred on merit. Changing cache keys invalidates `data/cache/` — which the running build is reading. Doing it now would either be ignored or would corrupt the build | The build is not running. Then re-key all five on input bytes (size+mtime at minimum, as `osm.py` already does) in one pass, with the completeness guard from DEF15-8 |
| DEF15-6 | Painted base band and printed reading use two different rules for **39.3%** of the grid (1,609,988 of 4,091,715 cells) while `config.py` asserts they agree | `config.py:26-38` vs `bands.py:316-322` vs `hover.py:226-233` | MEDIUM | High | Build-path: changing either rule changes every published array. Unverifiable this cycle and would invalidate the running build's output | The rebuild finishes; then decide which rule is correct, change one, and re-measure the split |
| DEF15-7 | The band-coverage gate cannot fail on the overlap property it exists to prove (passes with every `rim`=0, every `rings`=0, and the parent underlay deleted) | `validate.py:63-119` | MEDIUM | High | Proven vacuous by mutation, so it is real. But it runs inside the build, and a gate that starts refusing mid-build would abort the run the orchestrator forbids disturbing | The build is not running. Then move the check to the post-tippecanoe artifact and re-prove with the same three mutations |
| DEF15-8 | Calibration provenance guard checks **table headers only**: a retuned value, a new unlabelled constant and a mislabelled provenance all stay green; "immediately above" is unbounded (`[rail]`'s label is 156 lines up) | `tests/test_calibration_provenance.py:24,53-63` | MEDIUM | High | Test-side and shippable in principle, but the fix's whole value is catching AGG15-4's contradictions, and those cannot be corrected until `fit_rail_tiers.py` can reproduce its own table (DEF15-9). Tightening the guard first would just go red against a block nobody can yet fix | Land with DEF15-9, as one pass over the `[rail]` block and its gate |
| DEF15-9 | The `[rail]` fit block gives **three different sizes for its own fit set** (2,338/2,331/2,323); the per-tier `n` sums to 2,240 where it must sum to `clean`; the script groups **post-fold** while the table is **pre-fold**, so `--refit` cannot reproduce the shipped constants | `calibration.toml:159-173,180,188-194,217-218`; `scripts/fit_rail_tiers.py:83,91,185,207-220,234` | HIGH | High | The cycle's clearest CLAUDE.md provenance violation, and **not deferred on merit**. Settling it requires re-running the fit, which reads the rail extract the running build has open, and re-running a fit beside a live build is exactly what cycle 14 declined to do for the Shinkansen pass. Same reasoning, respected | The build is not running. Then re-run `fit_rail_tiers.py`, reconcile pre/post-fold, and rewrite the block so the script reproduces it exactly |
| DEF15-10 | Both `[rail]` anchors (and the test guarding them) price the **endpoint great circle with per-leg overheads**; the Seoul–Busan error is reported with the **wrong sign** | `calibration.toml:196-200`; `tests/graph/test_rail.py:186-210`; `graph/rail.py:131-148` | HIGH | High | Same block and same blocker as DEF15-9; correcting the anchors without correcting the fit set would produce a third inconsistent version of the same table | With DEF15-9, one pass |
| DEF15-11 | The itinerary **books border-control minutes as road, rail or ferry travel**; 242,392 ground edges carry the 45-minute charge and no channel or tooltip names it | `graph/ground.py:121-122,152`; `build.py:258-259,354`; `emit/modes.py:64-76`; `web/app.js:2503-2516` | MEDIUM | High | Against CLAUDE.md's door-to-door disclosure rule, so **not deferred on merit**. The fix needs a new channel in the per-origin mode arrays — build-baked, invisible until the rebuild | The rebuild; land the channel and the page's tooltip together so the disclosure and the number arrive at once |
| DEF15-12 | Rail caption names a service the edge was **not priced on**: 29,309 of 119,973 directed keys (**24.4%**) captioned with a slower service; 63 hops over 5 min, worst **237 min** | `emit/rail_detail.py:158-176,205-206` vs `graph/build.py:244-248` | MED-HIGH | High | The residual of AA17. Build-baked — the captions ship inside per-origin `.rail.json`. The **test half is scheduled** (C15-5.3) so the divergence cannot widen unnoticed while the fix waits | The rebuild; fix the direction handling and republish. C15-5.3's guard must be in place first |
| DEF15-13 | `atomic_write` makes an unguarded per-write NFS `mkdir` with no `ESTALE`/`EINTR` retry (the rebuild20 death); the lock release is itself an unguarded NFS call that **masked the real error and left the lock behind** | `_io.py:34-55` (mkdir at `:42`); `cli.py:389-390,716-717` | HIGH | High | **Data-integrity, not deferred on merit.** Deferred solely on the orchestrator's "never disturb the running build": editing the module the live build imports is the one change most likely to kill it | The build is not running. **First task of the next build-path cycle**, with DEF15-14 |
| DEF15-14 | Nothing names the failing origin (the hour-26 death); `_other_builds()` reports the build's **own `sh`/`uv run` ancestors** and advises reaping them | `cli.py:149-185,282-321,382-387,720-739` | HIGH | High | Same blocker as DEF15-13. Note the tool actively contradicts the standing operating rule "never kill anything matching `build-all`" | With DEF15-13, first task of the next build-path cycle |
| DEF15-15 | `reindex` republishes the **previous** build's `inputsHash`/`buildId`/`builtAt` unconditionally; the drift gate knows only nine *format* constants; `check_dist` compares `buildId` to nothing. **Live evidence: `index.json` names a 12 Sep build beside a 15 Sep `hover_cells.bin`** | `cli.py:527-553,666-675`; `emit/index.py:267-283`; `check_dist.py:369,451`; `tests/emit/test_build_identity.py:74-77` | HIGH | High | **Data-integrity, not deferred on merit.** `reindex` is the publish path for the build now running; changing it mid-flight is precisely the forbidden disturbance. Carried from `DEF9-26` | The build is not running, **and before the next `reindex` runs** — this is the gate that would let a calibration-mixed `dist/` ship under one build stamp |
| DEF15-16 | `hover_cells.bin` keys four per-origin arrays and is checked for **length only**; a `--only` resume rewrites it, re-keying every array from earlier chunks; `web/app.js` **binary-searches** it with no ascent check | `check_dist.py:245-255` vs `:287-294`; `cli.py:459-468`; `web/app.js:2158,2170` | HIGH | High | **Data-integrity, not deferred on merit.** The current build has already been resumed twice, so the precondition is live. The `check_dist` half is safe to land now; the `cli.py` resume half is not | Split: land the `check_dist` resolution+ascent probe as soon as a cycle has gate budget; the resume half when the build is not running |
| DEF15-17 | Per-origin artifact set hand-enumerated in **seven places**, already divergent three ways; eight files per origin with no transaction, and the file a resume keys on is written **second**; `check_dist` requires three files no runnable path produces | `cli.py:308-318,615,639-652`; `emit/index.py:331,345-346`; `check_dist.py:28,296-321`; `tests/emit/test_atomic_writes.py:59-72`; `deploy_verify.sh:180-181`; `web/app.js` (6 sites) | HIGH | High | **Data-integrity, not deferred on merit.** Centralising the enumeration touches every emitter the build is running right now | The build is not running. With DEF15-13/14, as one build-path pass |
| DEF15-18 | `write_pmtiles`: 650 MB staged **outside** the `try`, **no subprocess timeout**, tippecanoe **orphaned by `Pool.terminate()`**, `.pmtiles-journal` never swept | `emit/tiles.py:43,79-83,90-111` | MED-HIGH | High | The mechanism behind the recorded "8 orphaned workers ate 11 GB of swap". Build-path; `emit/tiles.py` is executing continuously right now | The build is not running |
| DEF15-19 | The four `REQUIRED_EXTRAS` are checked for **existence only**: a 0-byte `places.json` and a header-valid, tile-empty `water.pmtiles` both pass | `check_dist.py:393-404` | MEDIUM | High | Gate-side and cheap, but it belongs with DEF15-16's `check_dist` work so the gate is strengthened once and measured once, not twice in two cycles against a `dist/` nobody can rebuild | With DEF15-16's `check_dist` half |
| DEF15-20 | The `water.pmtiles` refusal and the water browser check both **work** and **neither is tested**: deleting either leaves both test files green | `check_dist.py:393-404`; `tests/web/test_check_dist.py:57-59`; `tests/test_deploy_script.py` | MEDIUM | High | Test-side and shippable, but `tests/test_deploy_script.py` is the file C15-2 is already rewriting; two independent changes to it in one cycle would make neither attributable | The cycle after C15-2 lands |
| DEF15-21 | **Nothing derives the page's actual outbound hosts**, so neither `connect-src`/`img-src` nor the posted privacy policy is held to the code, in either direction | `deploy/worldmap-security-headers.conf:11-23`; `tests/web/test_csp.py:34`; `browser_verify.sh:127,431` | MEDIUM | High | Real, and the fix is a genuine new capability (a request log from a live page run, diffed against the CSP). Too large to add beside C15-2's gate change without confounding the deploy path this cycle | A cycle whose scope is the deploy gate itself; land with DEF15-20 |
| DEF15-22 | `SOLVER_WIRE_VERSION` is a literal in **three files, pinned by none**; the source comment claims a cross-language guard that does not exist | `web/app.js:1183-1189`; `service/wire.py:34`; `tests/service/test_wire.py:314-333`; `tests/web/test_solver_client.py:177,242-251` | MEDIUM | High | The solver service is designed-not-built (`plan/2026-09-14-c13-solver-service.md`: 4 of 12 done, nothing resident started). A version guard for a wire nothing speaks is bookkeeping ahead of need | The solver service gains its first resident process, or the wire format changes |
| DEF15-23 | The res-4 hover ordering addressing four per-origin arrays is **hand-copied into three emitters that already import `_representative_children` from its owner** | `emit/hover.py:98-100` vs `itinerary.py:58`, `modes.py:91`, `rail_detail.py:285` | MEDIUM | High | Pure de-duplication with no behaviour change — which is exactly the change that is invisible if it is wrong. Build-path, and the emitters are executing now | The build is not running; land with DEF15-17's enumeration work, which touches the same four files |
| DEF15-24 | `README.md` documents a scratch-`dist/` safety instruction **the CLI cannot perform**; the documented smoke test **overwrites published origins in place** | `README.md:40-43` vs `cli.py:308,762-778`, `config.py:5,9` | MEDIUM | High | New evidence on AGG14-106. The honest fix is a `--dist` flag, which is a CLI change to the running build's entry point | The build is not running; then either add the flag or correct the README to say what is actually safe |
| DEF15-25 | `wire.handle` **swallows every unexpected exception and logs it nowhere** | `service/wire.py:214-242` | MEDIUM | High | Same reason as DEF15-22: no resident process runs this code, so the swallowed exception has no operator to hide from yet | The solver service gains its first resident process |
| DEF15-26 | `web/app.js`'s `expandRamp`/`hexToOklab`/`oklabToHex` paint all 37 bands and **no test names them**; measured drift against `check_ramps.expand` today: **0.178 ΔE max**, adjacent separation up to **0.28 lower** than measured | `web/app.js:226-256` vs `check_ramps.py:129-131` | MEDIUM | High | The drift is real but far inside the ΔE ≥ 6 floor (measured min 6.5), so no shipped ramp is out of policy today. The fix — one ramp implementation, tested once — is worth doing properly rather than beside C15-3's page work | A cycle with page-test budget, **or** any change to either ramp implementation, whichever comes first |
| DEF15-27 | **33 of 139** top-level `app.js` functions named in no web test, incl. the ramp maths and `cssEscape` | `web/app.js` | MEDIUM | High | A coverage gap, not a defect. Writing 33 tests is precisely the "overwork" the owner's brief excludes; the valuable subset is already scheduled (C15-1.3, C15-5.5) or carried (DEF15-26) | Each function gains a test when a finding touches it. Re-measure the 33 next cycle and report the trend |
| DEF15-28 | `emit/places.py` has **zero tests**: GeoNames column positions, rank ordering and `fields`-vs-positional emission all unguarded | `emit/places.py:31-74` | MEDIUM | High | Compounded by AGG15-11's finding that `emit/places.py` has **zero importers anywhere** — before writing its tests, the cycle must establish whether it is live code at all | Resolve with DEF15-17 whether `places.py`/`airports_json.py`/`borders.py` are reachable; test what is, delete what is not |
| DEF15-29 | `scripts/osm_rail.sh`'s `osmium tags-filter` selectors are pinned against `sources/osm.py`'s parse predicates by **nothing** | `scripts/osm_rail.sh:40-41` | MEDIUM | High | Directly relevant before any Shinkansen `highspeed`-off-ways work, which is itself deferred (it needs a third pass over 4.2 GB of PBF, which cycle 14 declined to run beside a live build — reasoning respected) | The Shinkansen `highspeed` pass is scheduled; pin the selectors in the same cycle, before the extract is re-cut |
| DEF15-30 | Shinkansen prices at **10.4 h against a published 3.1 h** because all three relations carry no `service` tag; the critic finds the deferral rests on a **false premise and an overstated cost** | `calibration.toml:263-271`; `plan/2026-09-15-c14-rail-service-tiers.md:431-438` | HIGH | High | The orchestrator's brief explicitly instructs respecting cycle 14's reasoning for not running the third PBF pass beside a live build, and that reasoning is sound regardless of the premise's wording. **The critic's point is about the stated premise, not the schedule** — so the premise is corrected in the record now, and the fix stays scheduled | The build is not running; then run the `highspeed=yes`-off-ways pass with DEF15-29, and correct the premise text in `calibration.toml` in the same commit |
| DEF15-31 | Ground and urban constants' provenance names a **holdout and a joint fit no code performs** | `graph/ground.py:17-25`; `sources/urban.py:28-33`; `calibrate/ground.py:30-32,96-122`; `scripts/ground_check.py:9-11,29-35` | MEDIUM | High | A CLAUDE.md provenance violation, so **not deferred on merit**. Same blocker as DEF15-9: settling it means re-running a fit against data the live build holds open | With DEF15-9, as one provenance pass over `calibration.toml` |
| DEF15-32 | **No data source's licence text or URI is linked from any shipped surface**, against CC BY 4.0 §3(a)(1); GRIP4's required citation is truncated and reaches no shipped surface | `emit/index.py:33-96`; `web/app.js:606-612`; `README.md:82-84` | MEDIUM | Med-High | A licence-compliance finding and **not deferred on merit**. The source table is written into `index.json` by the pipeline, so the fix is build-baked — the page can only render what the build gives it. `check_dist.py:227-243` is the hook: it refuses on a missing source *name* but not on a missing *licence* | The rebuild; add licence URI to the source table, render it on the page, and extend `check_dist` to refuse a source with no licence URI |
| DEF15-33 | Every rebuilt asset is `Cache-Control: no-cache` although `index.json` carries an **unused `buildId`**; 2.7 MB gzipped plus a byte-ranged 27.8 MB archive revalidate **every visit** | `deploy/worldmap.atik.kr.conf:51-84`; `emit/index.py:251-283` | MEDIUM | High | The fix is content-addressed URLs keyed on `buildId` — but DEF15-15 establishes that `buildId` is **carried forward unconditionally and is currently wrong on disk**. Caching on a stale identifier would serve stale arrays forever, turning a perf win into a correctness bug | DEF15-15 lands and `buildId` is trustworthy. Strictly after, never with |
| DEF15-34 | **Four `backdrop-filter: blur()` overlays** composited over a continuously repainting WebGL canvas, one following the pointer | `web/index.html:194,204,241,506` | MEDIUM | Medium | Confidence is Medium and the designer measured no jank live (CLS 0.033, FCP 112 ms). Removing blur is a visible design change and the design policy is standing — not a change to make on an unconfirmed cost | A trace shows compositing cost on a non-Apple GPU; then raise it with the owner as a design question, not a perf fix |
| DEF15-35 | 553 `role="option"` rows carry **no `aria-selected`**; selection is carried by the word "departing" (SC 4.1.2) | `web/index.html:940`; `web/app.js:3542,3558,3787` | MEDIUM | High | Genuinely shippable and only deferred on bounded scope: C15-4 already changes five things in the same error/ARIA surface, and C15-1 changes the list rendering these rows live in. Landing a sixth ARIA change in the same cycle would make none of them individually verifiable | The next page cycle, immediately after C15-1 and C15-4 have been browser-verified |
| DEF15-36 | Search box **typeable before any listener exists** (3 top-level awaits); startup `render()` **drops the typed filter but keeps the text** | `web/app.js:69,119,747,3867,3952` | MEDIUM | Med-High | Same surface as C15-1, and the fix (disable until wired, or replay the buffered value) interacts with C15-1's fold change. Two changes to the search path in one cycle would confound the browser verification of both | Immediately after C15-1 ships and is verified; same lane |
| DEF15-37 | **Three bare percentages precede the sentence that defines them** | `web/index.html:806-811` | MEDIUM | High | Copy-only and safe, but C15-6 already rewrites the adjacent "Sources and method" prose; sequencing them avoids two prose diffs against the same panel in one cycle | With the next page-copy pass, after C15-6 |
| DEF15-38 | Map labels at 11 px over the ramp are **below 4.5:1 on 34 of 37 bands**; **1.00:1** for the departure button | `web/index.html:512-513,552` | MEDIUM | High | Real WCAG failures, and **not deferred on merit**. But every remedy — halo, plate, or shifting the label palette — is a visible change to the map's appearance over the band ramp, whose colours are a **standing design policy** measured by `check_ramps.py`. This is an owner design decision, not a unilateral fix | Raise with the owner as a design question with the 34/37 measurement attached. On approval, implement and re-run `scripts/check_ramps.py` |
| DEF15-39 | `capCities()` looks up **every** matched city to keep 60, **twice** per origin switch; survivors looked up again | `web/app.js:3473-3493,3590` | MEDIUM | High | Same function C15-3.2 caps. Deferred to avoid two independent edits to one function in one cycle | With the next page-perf pass, after C15-3 is measured |
| DEF15-40 | `airports.find()` **linear-scans 4,008 rows ~75 times per `renderLegs()`** in a file that already builds `bySlug` for the same problem | `web/app.js:2291,2396,2489,3846` | LOW | High | Low severity and measured small; the `bySlug` idiom makes it a clean fix whenever the itinerary panel is next opened | Any cycle touching `renderLegs()` |
| DEF15-41 | `station_key()` recomputed over **257,000 rail stops four times per build** | `graph/rail.py:89-93,119-123`; `emit/rail_detail.py:142-144,269-272` | LOW | High | Build-path; a site cycle 14's PERF-13 missed | The build is not running |
| DEF15-42 | The deploy gate **parses 1.05 GB** of `{slug}.json` + `{slug}.rail.json` per run at 1,464 origins | `check_dist.py:334-345` | LOW | High | Only bites at 1,464 origins, which no `dist/` has yet held | The rebuild publishes 1,464 origins and the gate's runtime is measured |
| DEF15-43 | `places.json` ships repeated region/country strings; columnar + interned is **21% smaller gzipped, 31% cheaper to parse** | `emit/places.py`; `web/app.js:1366-1375` | LOW | High | A format change on both sides of the language boundary, build-baked, for a Low-severity win | The rebuild; land with any other `places.json` format work |
| DEF15-44 | `check_coverage` **rebuilds the 13.7 M-cell Antarctica mask (and a ~99 MB masked copy) once per origin** instead of once per build | `validate.py:43-48` | LOW | High | Build-path; `validate.py` is executing on every origin right now | The build is not running |
| DEF15-45 | `nearestPlace()` called twice per pointer frame | `web/app.js:2968-2976,2855-2869` | LOW | High | The perf lane measured it small and said so | Any cycle touching the pointer path |
| DEF15-46 | `mode_minutes_per_node`'s `cell_class` fallback derives the class on the **mixed** grid, not the base grid the graph was weighted with | `emit/modes.py:48-51` vs `graph/ground.py:48-49` | LOW | High | Latent — the fallback is not currently reached. Build-path | The build is not running, or the fallback becomes reachable |
| DEF15-47 | `reindex` **flips `graph.rail` from a correct `false` to `true`** because `write_rail_detail` ships `.rail.bin` even for a road-and-air build | `cli.py:657,707-708` | LOW | High | `reindex` is the running build's publish path (see DEF15-15) | With DEF15-15 |
| DEF15-48 | `expand_origins.py` carries the **same short-row `KeyError`** as cycle 14's C8 in `emit/places.py`, over the same GeoNames extract, **with no `try` at all** | `scripts/expand_origins.py:53,108-113` | LOW | High | A maintainer-only script, run when the origin list is expanded — not on the build or deploy path | The next origin-list expansion, or any cycle with script-hardening budget |
| DEF15-49 | `_reject_unordered`'s `_depth < 6` cap is untested and real: a depth-7 nested set is **accepted and its digest is seed-dependent** (`b14ced28` vs `d2e49ab4`) | `_io.py:92-104` | LOW | High | `_io.py` is imported by the running build. No current caller nests to depth 7, so the defect is unreachable today | The build is not running; land with DEF15-13, which is the same file |
| DEF15-50 | A remote GitHub `tag_name` is **joined to a filesystem path with no validation** | `scripts/adsb_extract.py:110` (read at `:100-103`) | LOW | High | Second half of the trust assumption cycle 14 recorded as SEC-10, and carried as `DEF9-29`: `adsb_extract.py` is an **offline maintainer-only tool** with a hard-coded repo, not visitor-reachable. The precondition for exploitation is that the maintainer points it at a hostile repo | `adsb_extract.py` gains a configurable repo, or is ever run against untrusted input — cycle 9's criterion, unchanged |
| DEF15-51 | Tautological conjunct: `"tip"` is a substring of `"legtip"` | `tests/web/test_state_writers.py:104` | LOW | High | A weak assertion in a test that is otherwise sound | Any cycle touching `test_state_writers.py` |
| DEF15-52 | `check_ramps.py`'s `__main__` **never calls `oceans()`/`ocean_problems()`** | `scripts/check_ramps.py:217-232` | LOW | High | The functions pass when called by hand (verifier ran them: all 5 oceans pass), so no ocean colour is out of policy — but the CLI does not check them | Any cycle touching `check_ramps.py`; one line |
| DEF15-53 | Checkboxes sit **139.5 px / 29.3 px** from their labels; passes SC 2.5.8 only via the spacing exception | `web/index.html:981-987` | LOW | High | Passes the criterion as written. Recorded because the margin is thin, not because it fails | Any layout change to the settings group; re-measure then |
| DEF15-54 | `data/cache/` vs `data/build/` has **no stated rule**; param-keyed derived artifacts sit on both sides, beside irreplaceable raw downloads | `config.py:6-9`; `sources/osm.py:389,410`, `countries.py:98`, `urban.py:78`, `emit/water.py:81` | LOW | High | A convention gap that will bite whenever someone clears a cache directory. `config.BUILD` is also the root cause of C15-5.1's vacuous-test class, so C15-5 documents the distinction as a side effect | C15-5.1 lands; then write the rule down in `config.py` and audit the placements once |
| DEF15-55 | `web/app.js` has no module boundary: **13 distinct JavaScript slicers at 20 call sites in the tests**, 7 of them the naive variant one file documents as wrong | `web/app.js` (4,385 lines); `tests/web/` (20 sites) | MEDIUM | High | The architect deliberately proposed **no rewrite** — the owner's brief is "do not overwork". The tractable half is the test-side slicer duplication, not the source split | A cycle whose explicit scope is the test harness; consolidate to one slicer, leave `app.js` alone |
| DEF15-56 | The design spec's As-built rail **correction** row has itself gone stale (200/75 km/h) | `docs/…design.md:26` | MEDIUM | High | Carried from `DEF9-24`, which defers the spec's ten stale claims as one pass — correcting one row now would leave nine and re-open the same file next cycle | With `DEF9-24`: revise the spec against what shipped, in one pass, after the build-path cycle |
| DEF15-57 | `rsync-excludes.txt` claims a refusal `check_dist.py` **does not implement** | `deploy/rsync-excludes.txt:2-4` vs `check_dist.py:31` | LOW | High | Documentation-only; belongs with DEF15-19/20's `check_dist` pass so the claim and the code are reconciled once | With DEF15-19 |
| DEF15-58 | Stale `lastmod`; `sitemap.xml` is **the one deployed file no test opens** | `web/sitemap.xml:4` | LOW | High | Deferred only on bounded scope; C15-6 already changes shipped page copy | The next page-copy pass, with DEF15-37 |
| DEF15-59 | The "only automated licence gate" citation is wrong about `deploy/README.md` too | `tests/test_licence_firewall.py:25`; `check_dist.py:79` | LOW | High | Comment-only, in the file DEF15-32's licence work will touch | With DEF15-32 |
| DEF15-60 | A plan's completion record ships an **unfilled `<provenance>` placeholder** and the wrong task count | `plan/2026-09-15-c14-rail-service-tiers.md:303-304` | LOW | High | Bookkeeping in a cycle-14 plan; C15-6.4 rewrites `plan/README.md` and may as well not touch a second plan file in the same commit | With the next plan-hygiene pass; or fold into C15-6.4 if it proves trivial |
| DEF15-61 | CLAUDE.md's "**~7 per step is the ceiling**" is **measured false**: 10 of 12 schemes exceed it, vivid at 9.6. The **floor of 6 HOLDS** (min 6.5) | `CLAUDE.md:22-24` | LOW | High | A statement of fact inside the standing design policy. The policy's *rule* (ΔE ≥ 6) holds and is enforced; only the parenthetical arithmetic is wrong. **CLAUDE.md is the owner's file and this cycle does not edit it unasked** | Report to the owner with the measurement; edit only on their word. Carried as CRIT10-5 / AGG14-223 / DOC5-8 — reported three cycles running, still unactioned |

---

## 5. The index — all 77 findings and their disposition

| AGG | Lane IDs | Sev | Disposition |
|---|---|---|---|
| AGG15-1 | ARCH15-5, DBG15-5, VER15-6, VER15-1 | High | DEF15-15 |
| AGG15-2 | DBG15-4, VER15-5, CR15-3 | High | DEF15-16 |
| AGG15-3 | TE15-1, CR15-1, TR15-4 | Med-High | **C15-5.3** (test half) + DEF15-12 (fix) |
| AGG15-4 | CRIT15-3, CRIT15-8, DOC15-1/2/3 | High | DEF15-9 |
| AGG15-5 | CRIT15-6/7, DOC15-4/5/6/13 | Med-High | **C15-6.1/6.2/6.3** (page half) + DEF15-3 (build half) |
| AGG15-6 | VER15-10 | High | **C15-2** |
| AGG15-7 | TE15-3, TE15-5 | Critical | **C15-5.1/5.2** |
| AGG15-8 | VER15-7/8/9 | Medium | DEF15-5 |
| AGG15-9 | DBG15-8, DBG15-2 | High | DEF15-13 |
| AGG15-10 | DBG15-3, DBG15-1 | High | DEF15-14 |
| AGG15-11 | ARCH15-3, DBG15-9, VER15-4 | High | DEF15-17 |
| AGG15-12 | UX15-1, UX15-2 | High | **C15-1** (+ DEF15-1 for own-script) |
| AGG15-13 | PR15-1, PR15-2, PR15-3 | High | **C15-3.1/3.3** (+ DEF15-2 for PR15-2) |
| AGG15-14 | TR15-2 | Medium | DEF15-6 |
| AGG15-15 | TR15-3 | Medium | DEF15-11 |
| AGG15-16 | TR15-1 | Medium | DEF15-7 |
| AGG15-17 | CRIT15-2 | High | DEF15-10 |
| AGG15-18 | CRIT15-1 | High | DEF15-30 |
| AGG15-19 | CRIT15-5 | Medium | DEF15-31 |
| AGG15-20 | TR15-5 | Low | DEF15-46 |
| AGG15-21 | CRIT15-4, DOC15-12 | Medium | DEF15-8 |
| AGG15-22 | VER15-3 | Medium | DEF15-19 |
| AGG15-23 | VER15-2 | Medium | DEF15-20 |
| AGG15-24 | SEC15-1 | Medium | **C15-5.5** |
| AGG15-25 | SEC15-2 | Medium | DEF15-21 |
| AGG15-26 | TE15-2 | Medium | **C15-5.4** |
| AGG15-27 | TE15-4 | Medium | DEF15-26 |
| AGG15-28 | TE15-6 | Medium | DEF15-29 |
| AGG15-29 | TE15-10 | Medium | DEF15-28 |
| AGG15-30 | TE15-8 | Medium | DEF15-27 |
| AGG15-31 | ARCH15-1 | Medium | DEF15-22 |
| AGG15-32 | ARCH15-2 | Medium | DEF15-23 |
| AGG15-33 | ARCH15-4 | Medium | DEF15-55 |
| AGG15-34 | ARCH15-7 | Medium | DEF15-24 |
| AGG15-35 | DBG15-6 | Med-High | DEF15-18 |
| AGG15-36 | DBG15-10 | Medium | DEF15-25 |
| AGG15-37 | ARCH15-6 | Low | DEF15-54 |
| AGG15-38 | DBG15-7 | Med-High | **C15-4.3** |
| AGG15-39 | UX15-3 | Med-High | **C15-4.2** |
| AGG15-40 | UX15-4 | Medium | **C15-4.1** |
| AGG15-41 | UX15-5 | Medium | DEF15-35 |
| AGG15-42 | UX15-6 | Medium | DEF15-4 |
| AGG15-43 | UX15-7 | Medium | DEF15-36 |
| AGG15-44 | UX15-8 | Medium | DEF15-37 |
| AGG15-45 | UX15-9 | Medium | **C15-4.4** |
| AGG15-46 | UX15-10 | Medium | **C15-4.5** |
| AGG15-47 | UX15-11 | Medium | DEF15-38 |
| AGG15-48 | CR15-6 | Low | DEF15-43 (same `places.json` pass) |
| AGG15-49 | SEC15-3 | Medium | **C15-7** |
| AGG15-50 | SEC15-4 | Low | DEF15-50 |
| AGG15-51 | DOC15-7, DOC15-14 | Medium | DEF15-32 |
| AGG15-52 | PR15-4 | Medium | DEF15-33 |
| AGG15-53 | PR15-5 | Medium | DEF15-39 |
| AGG15-54 | PR15-6 | Medium | **C15-3.2** |
| AGG15-55 | PR15-8 | Medium | DEF15-34 |
| AGG15-56 | PR15-7 | Low | DEF15-40 |
| AGG15-57 | PR15-11 | Low | DEF15-41 |
| AGG15-58 | PR15-12 | Low | DEF15-42 |
| AGG15-59 | PR15-9 | Low | DEF15-43 |
| AGG15-60 | CR15-2 | Low | DEF15-44 |
| AGG15-61 | PR15-10 | Low | DEF15-45 |
| AGG15-62 | CRIT15-10, DOC15-10 | Medium | **C15-6.4** |
| AGG15-63 | DOC15-9 | Medium | **C15-6.7** |
| AGG15-64 | CRIT15-9 | Medium | **C15-6.6** |
| AGG15-65 | DOC15-8 | Medium | DEF15-56 |
| AGG15-66 | CRIT15-11 | Low | DEF15-60 |
| AGG15-67 | DOC15-11 | Low | DEF15-57 |
| AGG15-68 | DOC15-14 | Low | DEF15-32 |
| AGG15-69 | DOC15-15 | Low | DEF15-58 |
| AGG15-70 | DOC15-16 | Low | **C15-6.5** |
| AGG15-71 | DOC15-17 | Low | DEF15-59 |
| AGG15-72 | CR15-4 | Low | DEF15-47 |
| AGG15-73 | CR15-5 | Low | DEF15-48 |
| AGG15-74 | TE15-9 | Low | DEF15-49 |
| AGG15-75 | TE15-7 | Low | DEF15-51 |
| AGG15-76 | VER15-11 | Low | DEF15-52 |
| AGG15-77 | UX15-12 | Low | DEF15-53 |

### Disposition counts

| | Count |
|---|---|
| Scheduled this cycle (`C15-1…C15-7`, 33 tasks) | **21 findings** |
| Deferred with exit criteria (`DEF15-1…DEF15-61`) | **56 findings** |
| Total dispositioned | **77 / 77** |

Of the deferred, **44 are blocked on the running build** and name "the build is not
running" or "the rebuild republishes" as their exit criterion. That is one constraint, not
forty-four judgements.

---

## 6. Status

**Planned.** Nothing in §2 is implemented yet. Progress is recorded against each
checkbox as it lands, with the mutation evidence CLAUDE.md requires.
