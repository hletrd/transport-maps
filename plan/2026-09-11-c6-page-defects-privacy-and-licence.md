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
