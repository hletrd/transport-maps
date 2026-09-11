# Cycle 6 — the page a visitor uses, two false statements, and the gates that cannot see a broken page

Written from `.context/reviews/_aggregate.md` (cycle 6: 60 raw findings from
twelve reviewers, **47 after dedupe**, merged clusters `AA1`…`AA47`; per-agent
IDs `CR6-n`, `PR6-n`, `SEC6-n`, `CRIT6-n`, `VER6-n`, `TE6-n`, `TR6-n`,
`ARCH6-n`, `DBG6-n`, `DOC6-n`, `UX6-n`, `FCR6-n`).

Task IDs are `C6-n`. Earlier cycles used `A`…`J` (c1), `K`…`S` (c2), `T`/`X`
(c3), `U`/`Y` (c4), `V`/`Z` (c5); `W1` is the recorded warning in the gates
plan and is not reused.

Anchor: `dcc99cf`. The tree moved during the review — six commits landed from
the owner's own session (`f968217`, `c2af2d1`, `f914f00`, `1fb1430`, `a5be9a4`,
`dcc99cf`, the `USER-5…USER-8` defects). All four were re-verified under
measurement by this cycle's debugger and hold.

## The shape of this cycle

The orchestrator asked for a **small** cycle: the few changes that most improve
what a visitor sees and does, plus any genuine correctness or security defect.
Twenty-one tasks are scheduled below and **every one is a one-line, one-rule or
one-function change plus its test**. No refactor, no subsystem rewrite, nothing
that needs a rebuild. Twenty-three of the forty-seven clusters are deferred in
`deferred.md` under `# Cycle 6` with their unchanged severity, a concrete
reason and an exit criterion.

Three of this cycle's findings deserve naming before the tables, because they
are the same failure in three costumes — **the page says something confident,
plausible and wrong, and nothing errors**:

- The tile-failure notice **cannot fire** (`AA1`). Its filter matches none of
  the messages pmtiles.js actually emits, so the blank globe CLAUDE.md's deploy
  rule says has shipped twice would be silent a third time. Measured on the
  real `dist/`: `bandsRendered:0, waterRendered:0, #tiletrouble hidden`.
- The **privacy section is false** (`AA2`). It tells visitors that unticking a
  box "stops the second kind entirely"; the code calls the reverse geocoder
  unconditionally. Live, on the deployed page.
- The list **opens on the wrong rows** and **filtering hides the match**
  (`AA3`, `AA4`). Type `lond` and London itself renders 126 px above the
  visible box while the list shows Stansted.

None of the three would have been found by reading a diff. All three were found
the way `USER-5…USER-8` were: by driving the live site and measuring what came
back.

---

## Tier A — page defects a visitor hits (schedule: cycle 6)

| ID | Finding | Task | Verification (the mutation that must go red) |
|---|---|---|---|
| C6-1 | `AA4` / `UX6-2` — filtering leaves a `scrollTop` the browser clamps to the new maximum; typing `lond` renders London at y 146–172 against a box at y 298–618 and the visible list starts at "STN London Stansted Airport" | Add the `else box.scrollTop = 0` branch at `web/app.js:2091-2097`, so a filtered list starts at its top | Remove the `else`; a test that filters to a short list and asserts `scrollTop === 0` goes red |
| C6-2 | `AA3` / `UX6-1` + `CR6-2` — V6's scroll-to-current measures `offsetTop` against `.rail`, because `.results` has no `position`; Seoul renders 131–176 px above the visible list and `inView()` repeats the error so nothing corrects it | One declaration: `position:relative` on `.results` (`web/index.html:318`) | Delete the declaration; the offset test for the active row goes red |
| C6-3 | `AA5` / `DBG6-1` + `FCR6-2` + `ARCH6-7` — `lastPointer` is written only inside `showReading`, which the pinned branch skips, so clearing a pin and switching city resurrects the dismissed location as a live headline reading for the new city. Worst on touch | `lastPointer = null` at both sites that clear a pin (`clearRoute` `app.js:1880`, the "Depart from X" handler `:1734`) | Restore either assignment; the test that pins, clears, switches origin and asserts the headline is the idle prompt goes red |
| C6-4 | `AA21` / `DBG6-3` + `UX6-6` — on a `{slug}.bin` failure `#time` is never cleared: "Reading the travel times from Nairobi…" sits above "Times unavailable for Nairobi" | Clear `#time` on the failure path | Remove the clear; the failure-path test asserting `#time` no longer says "Reading" goes red |
| C6-5 | `AA25` / `UX6-8` — at 1280×800 choosing a destination puts "Clear" and "Copy link to this journey" at y 972–1000 with `rail.scrollTop === 0` | Apply `openRoutePanel`'s `noScroll` guard only in the small layout | Widen the guard to all layouts; the desktop scroll test goes red |
| C6-6 | `AA8` / `UX6-4` — `.legs{max-height:20vh}` hides 99 px at 390×844 and **209 px, seven of nine legs, at 844×390**, under a 94 %-opaque sticky total that reads as the end | Two `body.smallui` rules letting the itinerary grow into the sheet that already scrolls | Restore the flat `20vh`; the landscape-phone height test goes red |
| C6-7 | `AA22` / `UX6-3` — the one tab stop in the 553-row listbox is the first row, not the current departure, and focusing it resets `scrollTop` 11418 → 0, undoing C6-2 by keyboard | Put the roving `tabindex` on the current departure row | Move it back to row 0; the test asserting the tabbable row is the current origin goes red |
| C6-8 | `AA20` / `CR6-3` — `renderRoute()` resolves every point through `airports`, fetched once with no re-render; unresolved, the globe draws **0 route features** against a full ICN→EWR itinerary, falsifying the code's own "the line and the text cannot disagree" | Re-render the route once `airports` resolves | Drop the re-render; the test that renders a route before `airports` lands and asserts non-zero features goes red |

## Tier B — the failure CLAUDE.md names as this project's recurring one (schedule: cycle 6)

| ID | Finding | Task | Verification |
|---|---|---|---|
| C6-9 | `AA1` / `CR6-1` — `map.on("error")`'s `/pmtiles\|tile\|source/i` filter matches none of pmtiles.js's real messages ("Bad response code: 404", "…supports HTTP Byte Serving"), so `#tiletrouble` never shows and a blank globe stays silent. V3 passed only because its verification fired a synthetic error containing the literal "pmtiles". **No test exists for the feature** | Discriminate on `e.sourceId`, not on the message text; add the missing test with both real message strings | Restore the regex; a test firing a real pmtiles error and asserting `#tiletrouble` is shown goes red |
| C6-10 | `AA30` / `FCR6-1` — `f968217` filtered the resource-error branch on same-origin; the sibling `unhandledrejection` listener (`boot.js:71-74`) has no filter and a `PromiseRejectionEvent` carries no URL to filter on. A blocked GA4 collection `fetch` sets `body.fatal` and hides the whole side rail — the symptom V1 shipped to eliminate, via the other listener | Report an unattributable rejection without declaring the page dead; keep `body.fatal` for rejections that name this origin's own scripts | Restore the unconditional `say()`; the harness step firing a bare "Failed to fetch" and asserting `fatal` is false goes red |

## Tier C — two obligations that are not discretionary (schedule: cycle 6)

| ID | Finding | Task | Verification |
|---|---|---|---|
| C6-11 | `AA2` / `DOC6-1` (High) + `SEC6-2` — **the posted privacy policy is false and it is live.** `index.html:859-861` says unticking "Name the place under the cursor" *"stops the second kind entirely"*; `app.js:1860` calls `reverseGeocode()` unconditionally and `namePlaces` gates only the local `places.json` lookups. Separately, "Show my location" routes the derived city into `?from=`, which GA4 records as `page_location`, while `:852` says the position "is not sent anywhere" | Honour the setting: gate `reverseGeocode()` on `namePlaces`. Correct the locate paragraph to say the chosen city reaches the address bar and therefore the analytics page path | Remove the gate; the test asserting no reverse-geocode call with the box unticked goes red. Delete the sentence; the copy test goes red |
| C6-12 | `AA11` / `DOC6-2` — `web/vendor/`'s four JS bundles reach every visitor with zero copyright notice, licence text or SPDX line; jsDelivr's repack stripped the banners. maplibre-gl 5.24.0 and pmtiles 4.5.0 are BSD-3-Clause, h3-js 4.2.1 Apache-2.0, fflate 0.8.3 MIT — all four require the notice on redistribution. `vendor/LICENSE` → 404 live. The same finding was accepted for the font in cycle 2 (`DOC-15` → `O11`); the JavaScript half was never asked | Ship the four notices beside the bundles and name them where the fonts are named | Delete one notice; `tests/web/test_vendor.py`'s completeness assertion goes red |

## Tier D — accessibility (schedule: cycle 6)

| ID | Finding | Task | Verification |
|---|---|---|---|
| C6-13 | `AA24` / `UX6-7` — `#here`, the only feedback for the locate button's three outcomes, is a plain `<p>` with no `role`/`aria-live`; `#status` never changes. WCAG 2.2 SC 4.1.3 | Give `#here` a live region | Remove it; the ARIA test goes red |
| C6-14 | `AA23` / `UX6-5` — the canvas's accessible name promises "Enter sets a destination". Arrows and ± work; **Enter and Space do nothing** and no map keydown listener exists | Make the promise true or stop making it. Preferred: honour Enter at the view centre, since the brief is ease of use | Remove the handler; the keydown test goes red |

## Tier E — what the page says about itself (schedule: cycle 6)

| ID | Finding | Task | Verification |
|---|---|---|---|
| C6-15 | `AA27` / `CRIT6-4` — `holdout_mae_min` is a **mean** absolute error (`calibrate/fit.py:42`); `index.html` and `llms.txt` both call it a median. CRIT5-2's promised guard never landed with V17 | Say "mean" in both, and pin the accuracy prose to `calibration.toml` with a test | Change the word back; the prose test goes red |
| C6-16 | `AA26` / `CRIT6-6` — the journey line shipped in `214297d` with no key: solid = great circle, dashed = straight-line ground is stated only in a code comment | Name the two line kinds where the itinerary is read | Delete the key; the copy test goes red |
| C6-17 | `AA29` / `CR6-6` — `.reading .trouble{color:var(--text-1)}`; `--text-1` is undefined and the measured computed colour falls through to the inherited `--text` | Use a defined token | Reintroduce an undefined token; the CSS-token test goes red |

## Tier F — gates that cannot see a broken page (schedule: cycle 6)

| ID | Finding | Task | Verification |
|---|---|---|---|
| C6-18 | `AA7` / `TE6-3` + `ARCH6-1` — **nothing in the repository parses `web/app.js`.** A syntax error passes the whole page gate (102 passed) and `check_dist --copy-only` (exit 0), and `deploy_verify.sh` rsyncs it live *before* `browser_verify.sh` runs. `node --check` is itself vacuous on an ES module. Separately `boot.js` is unprobed, and its **absence** disarms the blank-page detector and makes `browser_verify`'s `body.fatal` check pass | Parse both files in the gate by a means that actually fails on a broken ES module; assert `boot.js` is present | Introduce a syntax error in `app.js`; the gate goes red. Delete `boot.js`; the presence assertion goes red |
| C6-19 | `AA14` / `TE6-1` — gutting `greatCircle` or `unwrap` leaves all 94 `tests/web/` tests green, with Seoul→Honolulu drawn **357.8° the wrong way round the globe**. The replacement test is already written and was run red under each mutation | Land the behavioural test for both functions | The two recorded mutations, re-run |
| C6-20 | `AA15` / `TE6-2` + `AA36` / `SEC6-1` — two tests proven vacuous by mutation. CLAUDE.md: *"A test that passes when the code is deliberately broken is worse than none."* (a) `test_every_constant_write_index_derives_is_in_the_refusal_set` re-types the list its docstring says it derives; adding one config-derived scalar keeps 201 green. (b) V19 dropped `"generator_options"` from `PMTILES_METADATA_LEAKS` but never landed the tippecanoe-shaped fixture; re-adding the token leaves all 31 `test_check_dist.py` tests green | Derive (a) from `write_index` itself; land (b)'s fixture | (a) add a scalar → red on `'coarseRes'`; (b) re-add `generator_options` → red |
| C6-21 | `AA10` + `AA31` + `AA12` — `deploy_verify.sh:9-11` says `browser_verify.sh` "is not run from here" while `:155` runs it and owns its exit code; its comments claim a `tests/web/test_water.py` that does not exist, "87 tests" where 114 collect, and "about 14 GB … five-fold" where the measurement is 15.69 GiB and 6.0×; `deploy/README.md:3-33`'s sequence omits the attribution refusal and the free-space pre-flight; and the free-space gate adds back the live set `df` already excludes, demanding **36.1 GiB for a 15.7 GiB `dist`** where V26 specified ×1.3 | Correct the four comment figures and the README sequence; make the pre-flight demand what V26 specified | Set the multiplier above real free space; the gate refuses before any byte moves (V26's own mutation, re-run) |

---

## Deferred — 23 of the 47 clusters

Each has a row in `deferred.md` under `# Cycle 6` carrying its file+line
citation, its **unchanged** severity and confidence, a concrete reason and the
exit criterion that reopens it. The reasons fall into four groups:

- **Needs the orchestrator's rebuild** (`AA9` stale shipped `modeDetail`,
  `AA17` rail line named by lowest `route_id`, `AA18` 91 mislabelled departure
  dots, `AA19` the duplicate-name suffix collapsing). A 16-hour build is not a
  cycle. `AA9` matters most: it is a published-figure default described as
  "fitted", a direct CLAUDE.md provenance breach, unreachable without a rebuild
  because `reindex` carries `modeDetail` forward by design.
- **A visible design change that is the owner's to make** (`AA6` the res-4
  reading against the res-6 ring — 28.0 % of sampled land points read a band
  the map does not paint there; `AA16` the sea-contrast floor measured against
  a colour the page never paints, which five of seventeen seas miss against the
  real ground). CLAUDE.md's design policy is standing and says **do not revisit
  without being asked**. The cheap, non-visible half of `AA16` — wiring
  `oceans()`/`ocean_problems()` into `check_ramps.py`'s `__main__`, which
  today reports nothing and exits 0 — is folded into C6-21's file and lands
  this cycle.
- **A server change nobody has approved** (`AA32` the stray journal file served
  200, `AA33` the installed nginx conf predating the security-header commit).
  The orchestrator's brief forbids touching the host.
- **Real, but a refactor or a subsystem the brief says not to rewrite**
  (`AA13`, `AA28`, `AA34`, `AA35`, `AA37`, `AA38`, `AA39`, `AA40`, `AA41`,
  `AA42`, `AA43`, `AA44`, `AA45`, `AA46`, `AA47`).

Two of these are worth the owner's eye even while deferred:

- **`AA40`** — `water.pmtiles`, 867 MB of static coastline that `build-all`
  never produces, is served `no-cache`: **478,986 bytes per cold load** and
  611,556 bytes of pmtiles re-downloaded in full on a warm reload, because
  Range responses cannot revalidate. The fix is a cache header, which is a
  server change, which is why it is deferred rather than cheap.
- **`AA13`** — `check_dist.REQUIRED_EXTRAS` demands three artifacts
  (`borders.json`, `places.json`, `airports.json`) that **no CLI subcommand or
  script in the repository can produce**. They are referenced only from tests.
  PR4-1's merged `COORD_DP = 4` is therefore unreachable, and the uncompressed
  file costs 241,909 gz bytes off every cold load.

## Two ledger corrections, made in this plan rather than quietly

- **`U24(b)`'s premise is falsified.** Its deferral assumed the leak would
  clear on the completed rebuild. The 553-origin rebuild completed *and
  deployed* and did not: every archive was written up to ~13 h after `64ab007`
  yet still carries `/var/folders/…`, because the whole build ran pre-fix code
  loaded at process start. 553/553 origins plus `water.pmtiles`, confirmed by
  unauthenticated Range GET. The row's exit criterion is rewritten to say the
  build must have **started** after the fix, not finished after it.
- **The c4 plan's claim that `check_ramps.py:169` was "the only writer
  bypassing `_io.atomic_write`" is wrong.** `calibrate/ground.py:127` and
  `scripts/adsb_extract.py:188` also do. Neither touches `dist/`, so no finding
  was raised, but the ledger line is corrected here.
- **V21's recorded mutation does not do what its row says** (`AA37`): `cities
  >= 0` reddens 1 boot test, not 2, and the paired test's "non-vacuous in both
  directions" docstring is false. Recorded, not re-fixed — the guard works;
  the bookkeeping was wrong.

## Not this cycle's, by instruction

`USER-2`, the coastline precision question, is the owner's visual judgement and
**stays open**. The finer grid and the zoom-12 coastline have shipped; whether
that settles it is not a measurement. Three reviewers were told to leave it and
did.

## Progress

- 2026-09-11 cycle 6: plan written from `.context/reviews/_aggregate.md`
  (60 raw findings, 47 after dedupe, clusters `AA1`–`AA47`). Every finding is
  either scheduled above or recorded in `deferred.md` with its citation,
  unchanged severity and confidence, a concrete reason and an exit criterion.

- 2026-09-11 cycle 6 done: **all 21 tasks landed**, across 12 signed commits
  (`67993e2`…`ca40a83`), plus the plan commit `88ebe07`.

  | Task | Commit | The mutation that proved it |
  |---|---|---|
  | C6-1 | `67993e2` | `else if (f)` branch deleted -> red |
  | C6-2 | `67993e2` | `position:relative` deleted from `.results` -> red |
  | C6-3 | `890232f` | `lastPointer = null` dropped from either clear site -> red |
  | C6-4 | `890232f` | `clearTime` dropped from the failure catch -> red |
  | C6-5 | `318b341` | `&& SMALL.matches` dropped -> red |
  | C6-6 | `318b341` | `.legs` capped at `20vh` again -> red |
  | C6-7 | `318b341` | tab stop back on row 1 -> red |
  | C6-8 | `cf6ec55` | the redraw call dropped -> red |
  | C6-9 | `8e0c591` | `e?.sourceId` dropped -> red; layer decision reverted to the URL regex -> red |
  | C6-10 | `c5efaf3` | `say()` called unconditionally -> 2 red; `ourRejection` always false -> 1 red |
  | C6-11 | `f1229a9` | `reverseGeocode` ungated -> red; "not sent anywhere" restored -> red |
  | C6-12 | `550b979` | a licence text deleted -> red; the NOTICE deleted -> red; the page link removed -> red |
  | C6-13 | `318b341` | `announce(text)` dropped from `sayHere` -> red |
  | C6-14 | `318b341` | the globe's keydown listener removed -> red |
  | C6-15 | `550b979` | "median of about 9 minutes" restored -> red |
  | C6-16 | `318b341` | the line key not appended -> red |
  | C6-17 | `318b341` | `--text-1` restored -> red |
  | C6-18 | `5035816` | a syntax error in `app.js` -> red; one in `boot.js` -> red; `boot.js` deleted -> red |
  | C6-19 | `6afcc4a` | `greatCircle` flattened -> 1 red; `unwrap` made identity -> 2 red; the `d > 1e-9` guard deleted -> 1 red |
  | C6-20 | `064399d` | a config-derived scalar added to `write_index` -> red on `'coarseRes'`; `"generator_options"` re-added -> 2 red |
  | C6-21 | `5035816` | "is not run from here" restored -> red; `23/10` restored -> red; a non-existent test named -> red; the hand-typed list restored -> red |

  Every guard above was run red under the mutation named and green after
  reverting it, as CLAUDE.md requires. Nothing was taken on reading.

### Three things this cycle got wrong, and how

Recorded because the corrections are the reusable part.

**Two of this cycle's own new tests were vacuous, and the mutation caught both
after the test read as obviously correct.**

- The airports-redraw test asserted `"renderRoute()" in` the fetch block. The
  *explanatory comment* beside the call contains that string, so it stayed
  green with the code deleted. Comments are stripped before matching now.
- The page-gate test asserted `tests/web/` appeared in `page_gate`. The comment
  explaining why the directory is used contains it. Same fix, same lesson,
  twice in one cycle: **an assertion over source text must strip comments, or
  the prose defending the code becomes the evidence for it.**

**A lint gate was run as `ruff check . | tail -2 && git commit`, and a
pipeline's exit status is its last command's.** `tail` succeeded, ruff's two
RUF007 errors were invisible, and the commit went through carrying them. Fixed
in `ca40a83`. This is the same `&&` trap the cycle-5 record names for pytest,
reached from the other side: **read a gate's own exit status; never chain it
behind anything.**

**One finding's premise did not survive checking.** `UX6-5` said the canvas's
accessible name promises "Enter sets a destination". It does not, at `dcc99cf`
or on the live site: it says "click to set a destination". The finding was
nonetheless real and larger than stated -- a `role="application"` surface that
answers arrows and `+`/`-` but not Enter, telling a keyboard visitor to click.
Fixed by making the promise true rather than by narrowing the name, which is
what the brief ("ease of usage") asks for. Scheduling a fix on an unverified
premise would have produced a worse page and a green test.

### What this cycle did not do

- **`AA6`**, the res-4 reading against the res-6 ring, is the largest remaining
  honesty gap on the page: **28.0 % of sampled land points read a band the map
  does not paint under them.** Its cheap fix is a visible change to the ring,
  which CLAUDE.md's standing design policy puts outside a cycle's reach.
  Deferred with that rule quoted. It is the first thing to raise with the owner.
- **`AA9`**, four shipped route-mode tooltips carrying pre-fix prose including
  a published-figure default described as "fitted", is a CLAUDE.md provenance
  breach that no code change can reach: `reindex` carries `modeDetail` forward
  by design. It clears on the orchestrator's next rebuild.
- **`AA40`**, 478,986 bytes per cold load from serving an 867 MB static
  coastline `no-cache`, is a one-line server change nobody has approved.
- `USER-2`, the coastline, is the owner's judgement and stays open.

## The deploy — refused once, correctly, then clean

`deploy_verify.sh` then `browser_verify.sh`, at `9ce7420`.

**Gates, each run alone and read by its own exit status:** `uv run ruff check .`
all checks passed, exit 0. `uv run pytest -q` -> **537 passed, 4 deselected,
5 warnings in 19 min 10 s, exit 0**. Cycle 5 ended at 495; the 42 added are
this cycle's. The five warnings are the recorded `W1` forked-pool class,
unchanged.

**The first run REFUSED, and one of its three failures was real.** The refusal
is recorded here rather than smoothed over, because the brief is explicit that
a gate failure is a failure until shown otherwise -- and the first instinct was
that the check was flaky. It was not; it reproduced.

| Failure | Whose fault | Outcome |
|---|---|---|
| "the legend's hour ticks are off screen at landscape" (`time:false, legend:false, scale:false` at 844x390) | **the page's — a real regression from C6-6** | landscape cap restored at a measured 30vh (`9ce7420`) |
| "the headline and the itinerary total disagree after a search" | the gate's | total read by `.leg.total .t`, not by counting lines back from the end of `#legs` |
| "errors: 2" in the console | the gate's | the tile-failure probe fires two REAL map errors, which `app.js` console.errors; the probe now runs after the console check |

The regression is worth keeping in the record. `#legs` lives **inside**
`.reading`, so uncapping it made the reading block taller than the 390 px
landscape rail -- and `revealReading()`'s `scrollIntoView({block:"nearest"})`
on an over-tall element aligns its **bottom**, carrying `#time`, `#tints` and
`#scale` off the top. Measured at 844x390 with a nine-leg itinerary (natural
height 418 px): `.reading` is 347 px at 20vh, 386 px at 30vh, 409 px at 36vh,
against a 390 px viewport. 30vh is the largest cap that fits, so that is the
cap -- 117 px of itinerary against the old 78, with the legend kept. Portrait
and tablet stay uncapped and measure clean, so landscape is the exception and
not a reversal of C6-6.

**Second run: `ALL CHECKS PASSED`, exit 0, twice** (the deploy's own step 4 and
the standalone re-run the deploy command chains).

**Live, verified in a browser:**

| | |
|---|---|
| page | `body.fatal` false, canvas present, **553 cities**, 552 durations, 0 clipped, console **0 errors** |
| **C6-2** | current departure **in view**, `parent:"results"`, scrollTop 11,140 — it opened 131-176 px above the box before |
| **C6-1** | filtering to "lond" gives `scrollTop:0` and **London itself first visible**, 0 hidden — the list began at "STN London Stansted Airport" before |
| **C6-9** | both REAL pmtiles messages fire the notice: "Bad response code: 404" -> "The shaded bands could not be loaded"; "archive does not appear to support HTTP Byte Serving" -> "The coastline could not be loaded". Each names the right layer. Neither could fire at all before |
| **C6-12** | `vendor/licences/maplibre-gl.LICENSE.txt` and `h3-js.NOTICE.txt` serve **200**; they were 404 |
| **C6-13** | `?from=atlantis` -> *No departure city called "atlantis"; showing Seoul.* through `sayHere`, so it is announced as well as painted |
| route | Tokyo -> Krasnoyarsk itemised GMP -> PKX -> KJA; headline and total **agree** |
| viewports | 1280x800, 820x1180, 390x844, **844x390** — all four clean, legend on screen at every one |
| bytes | `app.js`, `boot.js`, `index.html`, `llms.txt` all sha256-identical to HEAD |

**Free space:** "190 GiB available, about 20 GiB needed" — C6-21's corrected
1.3x multiplier. The old 2.3x would have demanded 36 GiB for the same payload.

**Page-asset gate: 144 tests**, up from 139; the five added are `test_parses.py`
and the vendor-notice checks, so a syntax error in `app.js` now blocks the
deploy before the rsync rather than after it.

Cleanup: `agent-browser` processes left **0**; the user's Google Chrome
untouched (11 processes, as before).

## A scope change that arrived after the cycle had finished

The orchestrator issued a freeze on `web/` mid-run -- **do not modify anything
under `web/`, do not deploy, record `DEPLOY: none`** -- because the owner was
iterating live with cycle 4 on UI bugs and two agents editing `web/app.js`
while one deploys every few minutes is a collision waiting to happen. That is a
sound call. It arrived after this cycle's 16 commits had landed and after the
second deploy had passed, so it could not be applied to the work it describes.

Recorded here rather than smoothed over, because the ledger has to say what
happened:

- **The deploy is NOT recorded as `none`.** It ran and it succeeded. Writing
  `DEPLOY: none` would put a false line in the record of a cycle whose whole
  subject was pages that say things the code does not do. The instruction is
  noted; the outcome is reported as it was.
- **Ten of the sixteen commits touch `web/`.** They are listed in the progress
  table above and are live.

**Cycle 4's work was not lost, and this was verified rather than assumed.**
This cycle rebased onto `dcc99cf`, so `f968217`, `f914f00`, `1fb1430` and
`a5be9a4` are all ancestors of HEAD, and all four fixes are present **in the
files the server is currently serving**, not merely in the working copy: the
`appReady` watchdog in `boot.js`, `OFF_GLOBE_PX`, the left-anchored dot, and
the pinned-headline branch in `app.js`.

**The collision the freeze exists to prevent did occur during this cycle.**
Cycle 4's six commits landed while the reviewers were running; three of them
reported HEAD moving under them from `056515e` to `dcc99cf` mid-review. Nothing
broke, because each re-anchored on the new HEAD, but that was luck rather than
coordination and it is the argument for the freeze.

**Two things the next agent to touch `web/` needs.**

1. **Pull first.** A deploy from a checkout older than `c129e46` would revert
   the privacy fix (C6-11), the tile-failure notice (C6-9) and the
   departure-list fixes (C6-1, C6-2), all of which are live now.
2. **The landscape phone is the sharp edge.** `#legs` is inside `.reading`, so
   uncapping the itinerary makes the reading block taller than the 390 px rail
   and `revealReading()`'s `scrollIntoView({block:"nearest"})` carries the
   legend off screen. That is what the first deploy refused for. The cap is
   30vh, measured as the largest that fits, and
   `tests/web/test_page_affordances.py` holds it there.

**Nothing needed routing for severity.** Both HIGH `web/` findings this cycle
raised are fixed and verified live: the privacy section that promised a setting
stopped the reverse-geocode while the code called it unconditionally (`AA2`),
and the blank-globe notice whose filter matched none of the messages pmtiles.js
emits (`AA1`). The rest of the UI findings are in `deferred.md` with their
severity and exit criteria, available to whichever cycle picks them up.

From this point the cycle made no further `web/` edits and ran no further
deploys.
