# Cycle 17 — plan from the seventeenth and FINAL review

Source: `.context/reviews/_aggregate.md` and the eleven lane files beside it.
HEAD at planning time: `29022b3`, branch `feat/transport-pipeline`.

**This is the last cycle.** There is no cycle 18. Every finding below is either
scheduled in §2 and done, or recorded in §3 as deferred with a file, a symptom,
a severity, a confidence, a reason and an exit criterion a human with no memory
of this run can act on. No finding is silently dropped.

## 0. The constraint that shapes this plan

A ~36-hour `build-all` (pid 4371) holds `dist/.build.lock` and is rewriting every
per-origin artefact. Therefore:

- nothing under `dist/` or `data/` is written, moved or deleted;
- no `build-all`, no `reindex`, no full `deploy_verify.sh` — the only deploy this
  cycle may run is `bash scripts/deploy_verify.sh --page-only`;
- **any fix whose effect reaches users only through a rebuilt artefact cannot be
  verified this cycle and is therefore deferred rather than half-started.**

That line divides §2 from §3. It is a scheduling constraint, not a severity
judgement: §3 keeps each finding's original severity and confidence.

## 1. What the review found

Eleven lanes, all completed, no failures. Raw totals **new=58,
known-with-new-evidence=27, known-restated=6**; **34 distinct new issues** after
dedupe, because the largest finding was raised independently by ten lanes.

The seventeenth review did **not** exhaust the ground, and the reason is
specific rather than lucky: the live site went from 553 to 1,464 departure
cities hours before this cycle started, and **six of the eight High-severity
findings are consequences of that change** — they did not exist for cycles 1-16
to find. The lanes also returned a large "verified sound" section (§4 of the
aggregate) which is itself a result: the picker, the fold, the abort gating, the
licence firewall and `calibration.toml` were each re-checked at the new scale and
hold.

## 2. Scheduled this cycle

### C17-1 — The disambiguator resolves 6 of 13 duplicate names to identical text

**Severity High · Confidence High · ten lanes independently
(CR17-1, PR17-5, SEC17-5, CRIT17-1, TE17-3, TR17-3, ARCH17-5, DBG17-1, DOC17-2, UX17-1)**

`web/app.js:1777-1781`:

```js
function cityCountry(c) {
  if (c.country) return countryName(c.country);
  const p = places ? nearestPlace(c.lat, c.lon) : null;
  return (p && (p.country || p.region)) || "";
}
```

`p.country` is tested **before** `p.region`, and `countryName(c.country)` has no
region to offer at all, so every pair whose two cities share a country gets the
same suffix. Read off the live rows: **Changsha, Changzhi, Fuzhou, Puyang,
Suzhou, Taizhou each render two byte-identical rows** — 12 of the 26 rows, and
three of them (Suzhou, Fuzhou, Taizhou) are among the original four pairs the
feature was written for.

Two further defects in the same mechanism:

- **`ambiguousNames()` keys on the raw `name`**, so `San José` (Costa Rica) and
  `San Jose` (California) — which fold to one search key, rank identically, and
  sit at adjacent rows 1100/1101 — get no disambiguation at all
  (CR17-2 / UX17-10, AGG17-7).
- **The row `aria-label` (`:3774-3778`) is built from `c.name`** and discards the
  visible disambiguator, so all 26 rows announce identically: 7 of 13 pairs work
  by eye, **0 of 13 by ear** (UX17-2, Med-High).

**Fix.** Replace the per-row `cityCountry()` call with a label computed **per
ambiguity group**, memoised once:

1. group `cities` by folded key, not by raw name, so fold-collisions are caught;
2. for each group of size > 1 try the country name; if any two members of that
   group collide, escalate **that group only** to `region, country`;
3. carry the resulting label into both the visible `<i class="disambig">` and the
   row's `aria-label`.

Escalating per group rather than globally keeps the seven pairs that already work
unchanged — "Barcelona Spain", not "Barcelona Catalonia, Spain".

`dist/places.json` already ships the admin-1 region for all 26 rows, so this needs
no rebuild. Measured against the shipped gazetteer, region separates **5 of the 6**
(Hunan/Guangdong, Fujian/Jiangxi, Zhejiang/Henan, Jiangsu/Anhui, Jiangsu/Zhejiang).
**Changzhi does not resolve** — the gazetteer holds two distinct settlements both
named Changzhi in Shanxi, 145 km apart, and the next distinct place is 55-81 km
away and would be a false label. That residue is **DEF17-1**.

Note for whoever picks this up: `emit/index.py:120-124` prints "add
`country = "XX"`" as the remedy, and it is wrong for all six — both members are
already CN. `expand_origins.py` "appends; never edits" and structurally cannot fix
the 553 legacy rows either (ARCH17-5). Correcting that message is **DEF17-2**.

**Done when:** all 13 pairs render two distinct strings on the live site except
Changzhi; the `aria-label` carries the same label; and a test built from the real
`dist/index.json` + `dist/places.json` asserts pairwise distinctness and goes RED
when `p.region` is removed from the escalation.

- [ ] C17-1.1 group-keyed, per-group-escalating disambiguation label
- [ ] C17-1.2 `aria-label` carries it
- [ ] C17-1.3 test over real data, mutation-checked

### C17-2 — Typing a departure city's exact name and pressing Enter departs from somewhere else

**Severity High · Confidence High · UX17-4**

`web/app.js:3717`:

```js
const codeFirst = f.length === 3 && apHits.some((a) => a[0].toLowerCase() === f);
```

`codeFirst` keys on the query's **length** alone. Six departure cities have a
three-letter name that is also a live IATA code — **Aba, Huế, Ibb, Jos, Ufa,
Van** — so typing the city's complete name puts an unrelated airport at the top
of the list, and Enter sets it as the **destination** instead of departing from
the city. Reproduced end to end on the live site: `Aba` + Enter → Abakan, Russia.

**Fix.** Suppress `codeFirst` when the query is an exact folded match for a
departure city name. One condition; the `jfk`-in-one-keystroke behaviour the rule
exists for is untouched, because no departure city is called JFK.

**Done when:** each of the six names ranks its own city first on the live site,
and a test asserts it and goes RED when the new condition is removed.

- [ ] C17-2.1 exact city-name match outranks the airport code
- [ ] C17-2.2 test over the six real collisions, mutation-checked

### C17-3 — Opening "Departure" carries the entire legend off screen

**Severity High · Confidence High · UX17-3 · CLAUDE.md standing-rule violation**

`web/app.js:4157-4168` calls `scrollIntoView({block:"nearest"})` on the
`<details>` that just opened. Below 860 px `.rail` is the scrolling sheet and
`app.js` moves `.reading` — which contains `.legend` — into it. `#departure`
holding a 60-row `#results` is taller than the rail, and `scrollIntoView` on an
over-tall element aligns its bottom, dragging everything above it off the top.

Measured, one real click on the `Departure` summary, `.legend` visible px before → after:

| viewport | rail scrollTop | `.legend` visible | `#tints` visible |
|---|---|---|---|
| 844x390 | 163 → 476 | 138.5 → **0** (of 142.5) | 5 → **0** |
| 390x844 | 125 → 522 | 202.1 → **0** (of 206.1) | 5 → **0** |
| 820x1180 | 0 → 351 | 174.2 → **0** (of 174.2) | 9 → **0** |
| 1280x800 | n/a (rail does not scroll) | unaffected | — |

Zero means the colour key is not on screen at all — no ramp, no ticks, no
door-to-door caption — while the visitor picks from 1,464 cities. CLAUDE.md:
"The legend is always visible."

This is the failure the repository already documents for `.legs`
(`web/index.html:787-796`, which quotes the same rule) and guards for `#route`
(`app.js:3213`). `#departure` — the taller panel, and the only one you must open
to use the site — has neither guard.

**Fix.** Clamp the scroll rather than suppressing it: compute the target
`scrollTop` directly and cap it at the largest value that does not reduce how much
of `.legend` is visible. Where there is room to bring the panel up without
evicting the legend the scroll still happens; where there is not, it does not.
This degrades correctly at every viewport instead of trading one rule for another.

Add the assertion the designer lane recommends to `scripts/browser_verify.sh`:
after opening `#departure`, `#tints` must intersect `.rail` at all four gate
viewports.

**Done when:** `.legend` visible px after the click is >= before at 844x390,
390x844 and 820x1180 on the live site, and `browser_verify.sh` fails if it is not.

- [ ] C17-3.1 clamp the panel-open scroll against the legend
- [ ] C17-3.2 `browser_verify.sh` asserts the legend survives opening Departure

### C17-4 — The filtered departure-list cap is guarded nowhere

**Severity High · Confidence High · TE17-1**

Mutation that stays GREEN today: delete `.slice(0, UNFILTERED_CAP)` from the
`f ?` branch at `web/app.js:3658`. All seven behavioural cap tests in
`tests/web/test_departure_list_cap.py` assemble only `_function("capCities")`,
which is the **unfiltered** branch; the four tests that slice `_function("render")`
are substring and regex checks that all survive. `scripts/browser_verify.sh:139`
asserts the resting row count exactly but only *prints* the filtered count
(`:203-211`).

Without the cap, typing `a` builds 1,097 rows — about 6,600 DOM nodes — on every
keystroke, which is the regression that file's own docstring says the cap exists
to prevent.

**Fix.** Add a behavioural test that exercises the **filtered** branch and
asserts the cap, and confirm it goes RED under that exact mutation.

- [ ] C17-4.1 filtered-branch cap test, mutation-checked

### C17-5 — One query, three different counts on screen

**Severity Medium · Confidence High · UX17-7**

Query `de` on the live site shows **72 option rows**, a caption reading "first 60
of **72**", and a live region announcing "**84** matches". Three numbers from
three populations: the rows include up to 12 airport rows the caption's `hits`
does not count, and the announcement counts cities and airports together while the
caption counts cities only.

**Fix.** Count one population consistently: the caption and the live region both
describe the **city** matches, which is what the cap applies to, and the airport
rows are an addition the copy already treats separately.

- [ ] C17-5.1 caption and live region agree on one population
- [ ] C17-5.2 test, mutation-checked

### C17-6 — One ArrowUp leaves the listbox with zero tab stops

**Severity Medium · Confidence High · UX17-6**

`web/app.js:4103-4105` resets `tabIndex = -1` on every row **before** the guard
that would restore one, so ArrowUp from the first row moves focus to `#q` and
leaves no row with `tabIndex = 0`. Tab from `#q` then skips the whole 60-row list
and lands on "Search address" — the roving-tabindex contract is broken by the one
keystroke a visitor uses to get back out of the list.

**Fix.** Restore a tab stop when focus leaves the list upward: the row that had
it keeps it.

- [ ] C17-6.1 ArrowUp out of the list leaves exactly one tab stop
- [ ] C17-6.2 test, mutation-checked

### C17-7 — Handover hygiene: the documents a human will read next

**Severity Medium/Low · Confidence High · CRIT17-6, CRIT17-9, DOC17-4, DOC17-5,
DOC17-7, DOC17-8, DOC17-9, PR17-1, AGG17-2, AGG17-5, VER17**

There is no cycle 18, so the plan directory is the handover and every row in it
that disagrees with the code is a trap. Specifically:

- **`plan/2026-09-16-c16-review-findings.md` §8 records all 8 tasks done with
  commits, while all 27 checkboxes read `[ ]`** (DOC17-4). The next reader could
  redo eight landed tasks. Tick them.
- **`plan/README.md:68` indexes `DEF16-1…DEF16-23` when 24 exist**; `:73,74,80`
  give C13/C12/C10 ranges of 11/11/14 against an actual 25/14/17; the running
  build is described as `--only` when it is a full `build-all` (CRIT17-9, DOC17-7).
- **`plan/2026-09-16-c16-review-findings.md:439` (`DEF16-24`) has an unescaped `|`
  inside `/error|exception/i`**, giving 8 cells for a 7-column table, so GFM
  **drops the exit criterion** and mis-renders severity and confidence (VER17).
- **`plan/deferred.md:184` is a 5-cell row in a 6-column table with no ID and no
  exit criterion** (VER17) — unactionable as it stands.
- **`web/app.js` contradicts itself on its own roster**: `:1774` says 13 ambiguous
  names, `:3736` and `:1422` say "four … in the 553-origin set" (AGG17-5).
- **The row benchmark comment (`:3753-3757`) is stale in premise, not just scale**:
  it says "4.5 ms … measured at 157 origins … 553 now", but the loop it annotates
  is capped at 60 and is roster-independent; the 1,464-wide scan moved into
  `capCities` and carries no note. Re-measured this cycle: the row loop is
  **0.112 ms**, `capCities` is **2.284 ms** coarse / 4.325 ms with the reading
  tier, and a whole live `render()` is **11.1-11.4 ms** resting (AGG17-2).
- **`deploy/README.md:27-31` enumerates what the page gate refuses on and still
  lists the original four**, though `c2d11f5` added a repo-wide `ruff check` and
  four more refusal conditions today (DOC17-9).

- [ ] C17-7.1 tick cycle 16's checkboxes to match its own §8
- [ ] C17-7.2 correct `plan/README.md`'s four wrong ranges and the build description
- [ ] C17-7.3 repair `DEF16-24`'s table row and give `deferred.md:184` an ID and a criterion
- [ ] C17-7.4 correct the three self-contradicting `web/app.js` comments
- [ ] C17-7.5 correct `deploy/README.md`'s refusal list

## 3. Deferred — every finding not scheduled above

Rules applied, per repo policy: original severity and confidence are **never
downgraded to justify deferral**; each row carries file+line, symptom, reason and
an exit criterion; deferred work stays bound by every repo rule when picked up
(GPG-signed conventional commits with gitmoji, no `--no-verify`, the standing
design policy, the testing rules).

Security, correctness and data-loss findings are not deferrable **unless a repo
rule explicitly permits it**. The rule relied on here is this run's standing
constraint, quoted: *"A 36-hour rebuild is running. Do not disturb it … NEVER
write under `dist/` or `data/` … pipeline changes cannot reach the site until
rebuild22 finishes, so do not pretend otherwise."* Every correctness row below is
deferred on exactly that ground and on no other, and each says so.

| ID | Finding | File:line | Sev | Conf | Reason | Exit criterion |
|---|---|---|---|---|---|---|
| DEF17-1 | Changzhi is the one duplicate pair region cannot separate: the gazetteer holds two settlements both named Changzhi in Shanxi, 145 km apart. C17-1 fixes the other five. | `web/app.js` `cityCountry` / `dist/places.json` | Medium | High | No page-side discriminator is truthful — the next distinct gazetteer place is 55-81 km away and naming it would be a false label. The honest fix is a data edit. | Add a distinguishing field for `changzhi-cn` in `origins.toml` (a `region`, or correct the name if the smaller settlement is not in fact called Changzhi) and republish; the two rows then render distinct text. Check with `python3 -c` over `dist/index.json` + `dist/places.json`. |
| DEF17-2 | `emit/index.py:120-124` tells the operator to fix an ambiguous name by adding `country = "XX"`. Wrong for all six China/China pairs, and `expand_origins.py` "appends; never edits" so it cannot touch the 553 legacy rows. | `src/transport_maps/emit/index.py:120-124` | Low | High | Pipeline file; the message is only emitted during a build, and a build is running. | The next cycle that may write under `src/`: reword to name the region-escalation rule C17-1 implements, and say the tool cannot edit existing rows. |
| DEF17-3 | `dist/.build.lock` records a pid and **no hostname**, while the repo is one NFS export mounted at the same path on ≥3 machines. `os.kill(4371, 0)` raises `ProcessLookupError` on mac0 while the build runs on mac1, so `reindex`/`build-all` there takes the STALE branch and tells the operator *"remove the lock file to build again"*. **Data-loss hazard.** | `src/transport_maps/_io.py` `pid_alive`, `_other_builds`, and the lock writer | **High** | High | Deferred **only** under the quoted run constraint: the fix edits the very lock protocol a 36-hour build is currently relying on, and a `build-all` that spawns a fresh interpreter could import the changed code mid-run. Severity is **not** reduced. Mitigated meanwhile by C17-7's documentation note. | rebuild22 has exited and `dist/.build.lock` is absent. Then: write `hostname` into the lock, and make both liveness guards treat a lock from another host as LIVE, never stale. Done when a lock written on mac1 is reported live by `reindex` run on mac0. |
| DEF17-4 | `legsTo`'s prefix recovery declares the leading legs "not recorded" on **99.68 %** of Lahore's flown journeys (81,097/81,361); pooled over all 1,464 origins the rate is **7.38 %**, not the 3.8 % the code's comment claims from a seven-origin sample. Cause: it consults one res-4 cell whose record comes from a centre child up to 25 km away, served by a different airport. | `web/app.js:2427-2431` and the `.bin` reading tier | **High** | High | The page-side half cannot be validated without reading per-origin arrays that the running build is rewriting underneath it; a fix measured against a half-rewritten `dist/` would be measured against nothing. Severity unchanged. | rebuild22 has exited. Then: consult the ring-1 neighbours of the res-4 cell (TR17-1 measured that LHE's neighbours carry `NO_AIRPORT` at 26 min, so the data is already on disk) and re-measure the pooled partial rate over all 1,464. Done when it is below the 3.8 % the comment claims, or the comment is corrected to the measured figure. |
| DEF17-5 | Pinning a city while departing from it can assert a long journey as fact: Dandong reads "0 min" while the itinerary says "Fly SHE → FNJ / Door to door 9 h 46 min", unmarked and with a solid arc; Oujda reads "0 min" over OUD→MRS→TLM, 12 h 20. The res-4 representative child lands across a sealed land border. | `web/app.js` itinerary path; `dist/origins/{dandong,oujda}.bin` | **High** | High | Same ground as DEF17-4 — the two share a root cause in the res-4 representative-child lookup and must be measured against a settled `dist/`. Severity unchanged. | rebuild22 has exited. Done when departing from and pinning the same city yields either a 0-minute itinerary or an explicitly partial one, checked for Dandong, Oujda and Eldoret. |
| DEF17-6 | H3 cells are not geometrically nested: `latLngToCell(p,4) !== cellToParent(latLngToCell(p,6),4)` for **6.14 %** of points and 90 of 1,464 origins. The page uses one lookup for the number and the other for the legs, so on 1 point in 16 they are different res-4 cells — median gap 30 min, max 503, and 17 % name a different arrival airport. | `web/app.js` res-4/res-6 lookup pair | Medium | High | A four-line page fix, but its correctness is judged by comparing two per-origin arrays that the build is rewriting. Bundling it with DEF17-4/-5, which touch the same lookup, avoids three separate passes over the same code. | rebuild22 has exited. Use one derivation for both — `cellToParent(latLngToCell(p,6),4)` — and re-measure the disagreement rate to 0. |
| DEF17-7 | `dist/` holds **two incompatible `.rail.json` shapes** (1,371 two-field, 93 four-field with `operators`) from two rail speed models, under one `index.json`. No gate can fail on it. | `dist/origins/*.rail.json`; `scripts/check_dist.py` | Medium | High | Known (TR16-1) with new evidence. It is by construction what a partial rebuild looks like; rebuild22 is rewriting all 1,464 to the four-field shape. Adding a gate now would refuse the deploy of a tree the build is mid-way through. | rebuild22 has exited. Then: confirm all 1,464 are four-field, and add a `check_dist` gate that refuses a mixed shape — the same class of guard as the existing `n_nodes` mixed-build check. |
| DEF17-8 | `modeDetail`, `inputsHash`, `buildId` and `graph.ferry` are **carried forward by `reindex`** (`cli.py:684-706`), so the live `modeDetail.rail` still states the pre-tier 200/75 km/h model beside a method panel stating six tiers. `attribution` and `origins[]` are silently refreshed. No written rule says which is which, and `graph.ferry` has no consumer anywhere. Six cycle-16 exit criteria written as "the rebuild **and the reindex**" are unsatisfiable as written. | `src/transport_maps/cli.py:684-706` | Medium | High | Pipeline file, and `reindex` takes the lock. Correcting the criteria without correcting the mechanism would leave the same trap under new wording. | rebuild22 has exited. Then: write the carried-vs-refreshed rule into `cli.py` as a comment and into `deploy/README.md`; decide `graph.ferry`'s fate (it has no consumer); re-word the six cycle-16 criteria to name the rebuild only. |
| DEF17-9 | The live page prints "Data built on 12 September 2026" over origins built 14-16 Sep. `cli.py:666-674`'s comment calls `builtAt` "the exception", but `setdefault` on a key the line above just copied makes that rule unreachable. | `src/transport_maps/cli.py:666-674` | Med-High | High | Same file and same lock as DEF17-8; rebuild22 will restamp `builtAt` itself, which makes the symptom disappear without proving the code is right. | rebuild22 has exited. Then: make `builtAt` an actual exception (assign, do not `setdefault`), and verify by running `reindex` on a tree whose artefacts post-date the stamp — the stamp must move. |
| DEF17-10 | `DEF16-19`'s exit criterion has **FIRED**: `UNFILTERED_CAP = 60` applies to the filtered branch too, so of 317 Chinese origins only 160 are findable by `cn` (the 553 legacy rows carry no `country` in the search key) and 60 are shown, under copy reading "Type to search all of them" and "Keep typing to narrow it" — which takes you to zero. | `web/app.js:3581`, `:3795` | Medium | High | Page-side and reachable, but the honest fix is not a bigger cap: it is that country search needs the country in the search key for all 1,464 rows, and 553 of them do not carry one until a rebuild republishes `origins[]`. Raising the cap alone would show 60 of 160 instead of 60 of 160 and change nothing. | rebuild22 has exited **and** `dist/index.json` carries `country` for all 1,464 origins. Then: fold the country into `skey` for every row and re-measure `cn` → all 317. If the rebuild does not add the missing `country` values, the exit criterion becomes the `origins.toml` edit instead. |
| DEF17-11 | A commercial-provider fingerprint found in a PMTiles metadata blob is filed into `check_dist.py`'s **non-blocking** `warn` list, under a docstring (`:170-173`) asserting the only waived class is a build-host path. Proved by executing the two lines against a real archive: `bad: []`, `warn: [… "which the licence firewall forbids"]`, exit 0. | `scripts/check_dist.py:170-173` and the warn/bad split | Medium | High | `check_dist.py` is the deploy gate. Changing what it refuses on while `dist/` is half-rewritten risks refusing the post-rebuild deploy for the wrong reason, and the finding is latent (today's scan of all 1,465 blobs found one hit, the known `water.pmtiles`). | rebuild22 has exited and a full `deploy_verify.sh` has passed once. Then: move the provider-fingerprint class from `warn` to `bad`, or correct the docstring to say it is waived and why. Done when the two agree. |
| DEF17-12 | rsync protects `--exclude-from` patterns against `--delete`, so `deploy/rsync-excludes.txt` ("Never published") is a **never-un-published** list. Live proof: `origins/las-vegas.pmtiles-journal`, 25,136 B, dated 2026-09-09, **HTTP 200** on the site today; it matches `check_dist`'s own `STRAY` regex. Checked for leaks — clean. | `deploy/rsync-excludes.txt`; `scripts/deploy_verify.sh` rsync invocation | Medium | High | The remedy is a delete on the live server, which is an outward-facing destructive action, and CLAUDE.md requires explicit confirmation before one. It is also not this cycle's to run: a page-only deploy does not touch `origins/`. | The owner confirms the deletion. Then: remove the stray from the server and add a `--delete-excluded` pass, or a post-deploy check that fetches one known stray path and refuses on 200. Done when `curl -sI https://worldmap.atik.kr/origins/las-vegas.pmtiles-journal` returns 404. |
| DEF17-13 | An archive present in `dist/origins/` but **not listed** in `index.json` is rsynced live without being scanned: both the metadata-leak scan and the `n_nodes` mixed-build gate iterate the index's origin list (`check_dist.py:299`), and nothing in the pipeline ever deletes a per-origin artefact. Measured: 0 orphans today, so latent. | `scripts/check_dist.py:299` | Low | High | Latent with a measured count of zero, and the gate is mid-rebuild. | rebuild22 has exited. Then: walk `dist/origins/` rather than the index, and assert the two sets are equal. Done when a planted unlisted archive (in a temp copy, never the real `dist/`) makes the gate refuse. |
| DEF17-14 | Nothing compares a live header's **value** with the repo snippet; `deploy_verify.sh:330-333` counts a header **name**. The installed snippet is one revision behind HEAD, so all six headers are unverified and the CSP matching is luck. | `scripts/deploy_verify.sh:330-333` | Low | High | The nginx conf is installed by hand as root by the owner and is explicitly out of this cycle's scope. Adding a value check now would refuse every deploy until that install happens. | The owner installs the current `deploy/worldmap-security-headers.conf`. Then: compare values, not names. Done when changing one byte of the repo snippet makes the gate refuse. |
| DEF17-15 | `test_module_scope_order`'s closure walks only `function` declarations (`_bodies()` indexes `^function`), so arrow-const callees are never scanned. Mutation that stays GREEN: `const seaNow = () => … ?? FLOW_DASH ?? SEA;` at `web/app.js:448` — `FLOW_DASH` is declared at 932, below the top-level await. A resize during load would then throw a TDZ `ReferenceError` and blank the rail. | `tests/web/test_module_scope_order.py` `_bodies` | Medium | High | Extending the parser to arrow consts is a real change to a test that guards the failure mode that has blanked this site twice; getting it wrong either way is worse than the gap. It needs a cycle that can run the full suite, and this one cannot (20 min against a 5-worker build). | A cycle that can run the full suite. Then: index `^const \w+ = (\([^)]*\)|\w+) =>` as well as `^function`, confirm the named mutation goes RED, and confirm the suite is still green. |
| DEF17-16 | The `aria-selected` guard's 900-char window has 152 chars of slack. Measured: deleting the asserted line alone goes RED (gap 902); deleting the line **and its four-line comment** goes GREEN (gap 659) — a comment edit can silently disarm the guard. | `tests/web/` `aria-selected` window assertion | Medium | High | Window-distance assertions over source text are the wrong shape for this guard, and replacing it properly means parsing the builder rather than measuring characters — more than this cycle's remaining scope after five page fixes. | A cycle that can run the full suite. Then: assert the attribute is set **inside the airport builder's own body** (locate the builder, slice it, search within), not within N characters. Done when removing the line goes RED with the comment removed too. |
| DEF17-17 | Three bare skips/errors in the page-gate file set: `tests/web/test_search_fold.py:439,462` and `tests/web/test_c16_page_fixes.py:190` carry neither the node pre-flight nor the `NEEDS_DIST` sentinel, and `_last_commit_date`'s `check=True` errors in a tree without `.git` — all four conditions `deploy_verify.sh:130-139` refuses on. They landed in the same three commits as the refusal itself. No meta-test enforces the invariant. | `tests/web/test_search_fold.py:439,462`; `tests/web/test_c16_page_fixes.py:190` | Medium | High | Known shape (TE16-1) recurring. The durable fix is a meta-test over the whole page-gate file set, which must be validated by running that set — 20 min, not available this cycle. | A cycle that can run the full suite. Then: add a meta-test asserting every test in the page-gate set carries the pre-flight or the sentinel, and confirm it goes RED when one is removed. |
| DEF17-18 | `test_the_legend_is_never_folded_into_a_panel` can pass vacuously: the non-greedy `.*?` stops at the first inner `</details>`, so a legend inside a `<details>` whose first child is another `<details>` falls outside every match — and the only assertion sits in a loop with no "the loop ran" guard. Latent today (one un-nested `<details>` in the markup). | `tests/web/` legend-fold guard | Low | High | Latent, and it guards a CLAUDE.md standing rule that C17-3 is separately strengthening this cycle with a live browser assertion. Two changes to the same guarantee in one cycle would make neither attributable. | The cycle after C17-3 is verified live. Then: add a `matches > 0` assertion and parse `<details>` by nesting depth rather than by regex. Done when a deliberately nested `<details>` around the legend goes RED. |
| DEF17-19 | `TE16-5`'s cold-clone file list is 9, not 7: `tests/sources/test_urban.py` and `tests/test_validate.py:125,137` reach `ground.cell_speed_kmh` → `roads.road_class_grid()` (a `config.BUILD` cache backed by GRIP4) with no marker and no redirect. Cycle 16 swept direct calls and missed the indirect ones. | `tests/sources/test_urban.py`; `tests/test_validate.py:125,137` | Low | High | Known (TE16-5) with new evidence. Proving the fix means running those files on a cold clone, which needs a GRIP4 download this cycle will not start beside a 5-worker build. | A cycle that can run the full suite on a cold clone. Then: mark or redirect both, and confirm by running them with `config.BUILD` pointed at an empty temp directory. |
| DEF17-20 | `paintOrigin` (`app.js:2085`) updates `aria-current` on every row but never `aria-selected`, so from click until `{slug}.bin` lands the listbox announces the **previous** city as selected — cycle 16's own SC 4.1.2 fix, wrong on the keyboard path. | `web/app.js:2085` | Low | High | Genuinely small, but it is the fourth page-side a11y change this cycle and CLAUDE.md's deploy rule means each must be browser-verified separately at four viewports. Deferring it keeps the three that are verified attributable. | Any later page cycle. Set `aria-selected` beside `aria-current` at `:2085`. Done when the announced selection changes at click time, not at settle time. |
| ~~DEF17-21~~ **CLOSED (2026-10-02)** -- render() hands the stop to `rovingStop()`, which clears every row and sets exactly one; run in node by `tests/web/test_roving_tabindex.py` (mutation to the old shape -> red, two stops). | `render()`'s focus restore sets `tabIndex = 0` on both the current-departure row and the refocused row — two tab stops in a roving tabindex. Related to but distinct from C17-6. | `web/app.js` `render()` focus restore | Low | High | Same reason as DEF17-20; C17-6 touches the adjacent code and two edits to one contract in one cycle make neither measurable. | The cycle after C17-6 is verified live. Done when exactly one element in `#results` has `tabIndex === 0` after any render. |
| ~~DEF17-22~~ **CLOSED (2026-10-02)**, together with DEF17-21 as the row asked: airport rows are refocused by `data-airport`, a carried address row by identity. | `render()` drops keyboard focus to `<body>` when the focused row is an airport or address row — only `data-slug` rows are restored. | `web/app.js` `render()` focus restore | Low | High | Same code region and same reason as DEF17-21; they should be fixed together in one measurable change. | Together with DEF17-21. Done when focus survives a re-render from an airport row. |
| DEF17-23 | A shared link's `?label=` is deleted from the address bar by its own restore (`geocoded: Boolean(requestedPin.label)`), so a named destination survives exactly one load — and gets a false "address by Nominatim" credit it did not earn. | `web/app.js` permalink restore | Medium | High | Correctness of a shared link, but it needs a decision this cycle should not make alone: whether a label that arrived in a URL counts as geocoded for attribution purposes. That is the owner's call, and the false credit is the part that matters. | The owner rules on whether a URL-supplied label carries the Nominatim credit. Then: preserve `?label=` across the restore and credit it accordingly. Done when reloading a `?label=` link twice keeps the label both times. |
| DEF17-24 | With "name the place under the cursor" off, `app.js:3289`/`:3094` still call `nearestPlace` ungated: the Route panel, itinerary heading, marker a11y name and `?label=` all name the place while the readout shows coordinates. | `web/app.js:3094`, `:3289` | Med | High | Four call sites and a user-facing setting; changing what a setting governs is a scope decision, not a bug fix, and the setting's stated meaning ("name the place under the cursor") does not obviously extend to the itinerary heading. | The owner confirms the setting should govern all four surfaces. Then: gate all four on the same flag. Done when the setting off leaves no place name anywhere. |
| DEF17-25 | After picking a city from a searched list the live region settles on `"3 matches for “Fuzhou”."`, holding the stale announcement 480 ms. The comment at `app.js:3811-3814` claims `settle()`'s rebuild "stays silent"; it does not. | `web/app.js:3811-3814` | Medium | High | It is an ordering fix inside the same announcement path C17-5 changes. Doing both in one cycle would make neither attributable to its own measurement. | The cycle after C17-5 is verified live. Done when the announcement after picking a city names the chosen city, not the match count. |
| DEF17-26 | The `places.json` handler (`app.js:1429`) appends a whole-roster scan, a full list rebuild and a forced layout to the longest main-thread task on the load path; its guard `ambiguousNames().size` is a constant `true` for the shipped roster. One-line rAF fix. | `web/app.js:1429` | Medium | High | C17-1 changes exactly this call's contents. Landing a scheduling change on top of a semantic change to the same code in one cycle makes the perf measurement unattributable. | The cycle after C17-1 is verified live. Wrap the rebuild in `requestAnimationFrame` and re-measure the load-path long task. Done when the task is shorter and the list still disambiguates. |
| DEF17-27 | The departure list renders **zero rows** from first paint until `{slug}.bin` lands, behind 1,510 KB gz issued first — yet `capCities()` with `times === null` costs 1.076 ms and returns 60 alphabetical rows. One-line `render()` before `paintOrigin` (`:4449`). | `web/app.js:4449` | Medium | High | A one-line change with a real perceived-performance win, but it alters what the first paint contains, and this cycle already changes the list's contents (C17-1), its ranking (C17-2), its copy (C17-5) and its scroll behaviour (C17-3). A fifth change to the same first paint would make the browser verification of the other four ambiguous. | The cycle after C17-1/2/3/5 are verified live. Call `render()` before `paintOrigin` at `:4449` and measure time-to-first-row. Done when rows are present at first paint. |
| DEF17-28 | `deploy_verify.sh:217-235`'s entire free-space rationale is written against the 553-origin payload (15.69 GiB). Today's is 52.96 GiB and it demands 68.85 GiB — the arithmetic is still right, the explanation is off by 3.4×. Next real threshold: the server disk refuses at ~2,490 origins and fills at ~2,866. | `scripts/deploy_verify.sh:217-235` | Low | High | Comment-only, and the numbers move again when rebuild22 finishes and `dist/` settles at its final size. Updating it now would date it immediately. | rebuild22 has exited. Re-measure `du -s dist` and rewrite the rationale with the settled figure and the ~2,490-origin threshold. |
| DEF17-29 | **`AB41`'s tightened exit criterion cannot fire.** It reads "the first cycle that makes no change under `web/` or `tests/` runs the sweep as its first task" — cycle 17 changes both, and there is no cycle 18. The sweep it gates is a re-anchoring of every citation in the deferral ledger. Measured this cycle: of 159 `app.js:N` citations across the five ledger files, 78 name no identifier and **63 of the 81 checkable ones (78 %) do not resolve.** | `plan/deferred.md` (AB41 section) | Medium | High | The sweep is a multi-hour pass over a 554-row, five-file ledger whose line numbers move with every page edit — and this cycle makes five. Running it now would produce a ledger stale before the cycle ended, which is the exact reason it was deferred three times before. | **Rewritten so it no longer depends on a cycle that will not come:** the next person to use `plan/deferred.md` for anything runs the sweep first, or treats every `file:line` in it as approximate and re-greps for the quoted code. Recorded in `plan/README.md` so it is read before the ledger is. |
| DEF17-30 | **The ledger's structural problems, carried forward as one row** so they are not lost: it is five files and 554 rows (~748 findings), not one file; 8 compound rows (`SEC10-L*` = 11 items, `UX10-M*` = 10, `DOC10-M*` = 12, `C11-D7…D11`) carry one ID and one exit criterion for up to twelve findings each, and the review files that enumerated them are gitignored and gone for cycles 4, 6-10, 12-13; `K8`/`H3`/`H5`/`H9` depend on a `m / cap` log no code emits; `AB50`/`J9` cite the wrong file and quote thresholds 3-5× the `URBAN_RADIUS_KM = 40.0` that governs them; 21 criteria read "\<ID\> lands" and resolve only by opening five cycle-2 plans; **34 rows name a cycle ≤ 16 and are unmarked**, 15 of them saying "Cycle 4". | `plan/deferred.md`; `plan/2026-09-16-c1{5,6}-review-findings.md`; `plan/archive/` | Medium | High | Each sub-item is a bounded edit, but together they are a rewrite of the ledger, and `CRIT10-4` named the same class in cycle 10 without it being actioned in seven cycles — so scheduling it again into a cycle that cannot finish it would repeat the failure rather than fix it. | Recorded honestly as **the largest single piece of unfinished work in this repository**. A human picking it up should start with the 34 already-fired rows (they are the ones that hide real work), then the 8 compound rows, then the citation sweep of DEF17-29. `plan/README.md` now says so. |
| DEF17-31 | `Home` and `End` are not bound in the departure listbox. WAI-ARIA's listbox pattern expects them, and at 1,464 cities behind a 60-row cap the first and last rows are the two a keyboard user most wants to reach directly. Raised as the second half of UX17-6; the tab-stop defect in that finding is fixed as C17-6. | `web/app.js`, the `#results` keydown listener | Low | High | C17-6 changes the same handler, and CLAUDE.md's deploy rule means each page change is browser-verified separately at four viewports. Landing both in one cycle would make neither attributable. Not a broken contract, unlike the tab-stop half: a missing key binding, not a key binding that does the wrong thing. | Any later page cycle. Bind `Home` to `items[0]` and `End` to `items.at(-1)` in the same handler, moving the single tab stop with focus. Done when both keys move focus and `tests/web/test_roving_tabindex.py` still reports exactly one tab stop after each. |

## 4. Progress

Filled in as tasks land.
