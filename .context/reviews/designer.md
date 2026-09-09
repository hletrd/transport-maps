# Designer (UI/UX) review — cycle 2

**HEAD reviewed:** `bf9e5cc80f06d29b6609d974bef98ac38d8d11f9` (branch `feat/transport-pipeline`).
Sources read in full: `/Users/hletrd/flash-shared/transport-maps/web/index.html` (479 lines),
`/Users/hletrd/flash-shared/transport-maps/web/app.js` (1126 lines), `CLAUDE.md`,
`.context/reviews/cycle-1/designer.md`, `_aggregate.md` sections C and D,
`plan/2026-09-10-c1-web-ui-detail.md`, `web/vendor/fonts.css`, `scripts/browser_verify.sh`,
`dist/index.json` (via the preview server).

**Environment.** `http://127.0.0.1:8899/` (Python SimpleHTTP, Range-capable, no gzip) serving the
working-tree `web/` over the 157-origin `dist/` (the 553-origin rebuild was running; "157" is
expected). `agent-browser 0.22.2`, headless Chromium 153.0.8010.36, one session (`c2design`).
Viewports: 1280x800, 820x1180, 390x844, 844x390, plus 640x400 and 320x256 for the 200 % / 400 %
zoom reflow check. `uv run python scripts/check_ramps.py` was run read-only. No repo file other
than this one was written; nothing under `dist/` or `data/` was touched; no build command was run.

**Finding IDs** continue cycle-1 numbering (UX-24 onward) so the aggregate's existing UX-1…UX-23
references stay unambiguous. Every finding below is backed by text-extractable evidence
(computed styles, boxes, DOM/ARIA reads, Resource Timing, console); screenshots under the
scratchpad are attachments only.

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 2 | UX-24, UX-25 |
| Medium | 7 | UX-26, UX-27, UX-28, UX-29, UX-30, UX-31, UX-32 |
| Low | 10 | UX-33, UX-34, UX-35, UX-36, UX-37, UX-38, UX-39, UX-40, UX-41, UX-42 |

The short version: the twenty cycle-1 items are in and hold up under measurement — every
control and label is in IBM Plex Sans, `--text-3` clears AA on every surface it sits on
(6.13:1 on `--surface`, 4.75:1 on the scrim over the brightest band), focus rings are the accent
on every control, the legend ticks sit on true edges with true values, the grey and the sea are
keyed, Enter/arrows/Escape behave, and the failure paths say what failed. The seven unlabelled
`console.error("Error")` entries (D17) did not reproduce at all (0 console entries across load,
hover, click, three origin switches and a scheme switch). What remains is about the first five
seconds and about touch: the departure city itself is never guaranteed a label on the globe
(Seoul is gazetteer rank 22, the opening budget is 18), a tap on a phone updates the pins but
never the big reading, the Mono scheme paints "no scheduled route" in a grey that is 0.9 ΔE from
one of its own bands, and the focus ring on city rows is clipped to a one-pixel line by the
list's scroll box.

## Regression table — cycle-1 items marked done in the web plan

| Item | Result | Measured evidence (1280x800 unless stated) |
|---|---|---|
| D1 fonts on inputs/list/picker/buttons | Pass | `getComputedStyle().fontFamily` starts `"IBM Plex Sans"` for `#q` (13px/400/lh 19.5), `.btn`/`#locate`/`#find-address` (12px/500), `.results button` (13px/400), `#ramps button` (12px/400), `.results .coord`, `#q::placeholder`. All three faces `loaded` (400/500/600). |
| D2 label typeface + shadow | Pass (subset still open) | z4.6, 59 labels: plain `.lbl` "Tianjin" → Plex 11px 400 `#a4a9b2`, text-shadow `0 0 3px #0a0b0d ×3, 0 1px 2px`; `.lbl.origin` "Beijing" → Plex 11px 500 `#e9e7e4`, same shadow, 14 px tall. `fonts.css` still ships `latin` only; 26 of the 900 label-pool names carry glyphs outside Latin-1 ("İzmir", "Thāne", "Cần Thơ", "Huế", "Rājkot"…) — D2 subset. (`document.fonts.check` cannot detect this: no `unicode-range` is declared, so it returns true for everything.) |
| D3 names on the opening view | Pass, with a gap | `.lbl` count 9 at z1.9 (Istanbul, Lahore, Beijing, Shanghai, Ho Chi Minh City, Mumbai, Guangzhou, Chongqing, Xi'an — all origin buttons). Seoul, the departure city, is not among them → UX-24. |
| D4 Enter / arrows / explicit address search | Pass (semantics open) | `fill #q "tokyo"` → 2 rows; Enter → `#origin-name` "Tokyo", `bands.url` `origins/tokyo.pmtiles`, `#here` cleared, `aria-current` on the Tokyo row. ArrowDown → first row (focus-visible ring), ArrowDown → "HND Tokyo Haneda…", ArrowUp ×2 → back to `#q`. Escape → value "" and 157 rows. "jfk" + Enter → destination JFK, Route opens. `#find-address` button present; no Nominatim request per keystroke. Widget semantics: `#results` role null, `#q` no `aria-expanded/controls`, `#ramps` role null, no `aria-live` anywhere → UX-32 / D4-semantics. |
| C4 legend ticks at true edges | Pass | 8 ticks; `data-min` = 60, 125, 225, 465, 955, 1470, 3020, 4320 — every one is a member of `bandEdgesMin`; labels "1, 2.1, 3.8, 7.8, 15.9, 24.5, 50.3, 72+" equal `edge/60`; `left` = `(i+1)/37` (16.22 %, 29.73 %, 40.54 %, 54.05 %, 67.57 %, 75.68 %, 89.19 %, 97.30 %). No overlap at 1280 (gaps 2–3 px: "15.9" 205–225 / "24.5" 227–248; "50.3" 264–285 / "72+" 288–306) — see UX-35 for legibility; collision at 320 px (UX-36). |
| C6 legend keys for grey and water | Pass | `#keys` → "no scheduled route" swatch `rgb(74,77,80)` = `UNCHARTED`, "open water" swatch `rgb(23,26,34)` = muted `sea`; after switching to Mono the sea swatch and `sphere`/`water` fill both become `#17181b`. Mono's grey problem → UX-26. |
| D5 route copy | Pass | `#route .hint` = "Click anywhere on the chart to set a destination; the route from the departure city appears here. To change the departure, pick a city in the list above, click a city name on the globe, or click near a city and press "Depart from". Only the 157 charted cities…" — matches `map.on("click")` (app.js:786-795) and `.depart` (app.js:772-783). |
| D6 `--text-3` contrast | Pass | `--text-3 #8f96a0`: 6.13:1 on `--surface #131519`, 5.66:1 on `--surface-2`, 6.60:1 on `--bg`, 4.75:1 on the 86 % scrim over band 0 (`#faefc5` → composite `#2c2b27`), 5.73:1 over band 18, 6.51:1 over sea. `--text-2` 7.74 / 6.00 (scrim over band 0). WCAG formula, values read from the DOM. |
| D7 focus-visible rings | Pass (one clip, one inconsistency) | Tab walk: `.lbl.origin`, `.ap`, `.mode`, `#q`, `.btn`, `.results button`, `#ramps button`, `summary` all → `outline solid 2px rgb(228,143,53)` with `:focus-visible` true (accent 7.21:1 on surface). Canvas and `.pins .depart` keep the UA `auto 1px rgb(153,200,255)`. The ring on city rows is clipped by the list → UX-27. |
| D9 color-scheme | Pass | `getComputedStyle(documentElement).colorScheme` → `"dark"`. |
| D10 reduced motion | Needs manual validation | Code: `moveTo` → `jumpTo` when `REDUCED_MOTION.matches` (app.js:414-415), compass `duration: 0` (995), geolocation branch (1117-1121). Harness: `agent-browser set media reduced-motion` + reload → `matchMedia("(prefers-reduced-motion: reduce)").matches` stayed `false`, so the branch could not be exercised (same as cycle 1). Playwright is not installed here. Validate once in a real browser with the OS setting on: after clicking a city `map.isMoving()` must be false and `getCenter()` the city. |
| D18 no weight-300 request | Pass | Font requests: `ibm-plex-sans-latin-400/500/600-normal.woff2` only; `.reading .v` computed `font-weight 400`. |
| C7 loading / no-data vs open water | Pass | With `*tokyo.bin` aborted: during the switch `#where` "Loading the times from Tokyo…", after failure "Times unavailable for Tokyo." (`#time` "—"); console carries one labelled `hover data unavailable: TypeError: Failed to fetch`. Ocean → "Open water.", tip hidden, hover source empty. |
| C10 geolocation only on gesture | Pass | After load `navigator.permissions.query({name:"geolocation"}).state` → `"prompt"`; `#here` "Showing Seoul."; `#locate` "Start from the city nearest me" is the only caller (app.js:1102-1105). |
| C12 tooltips without modeDetail | Pass | `index.json` has no `modeDetail`/`railDetail`; after a click `#legs .mode[data-tip]` = 1 ("highway" → "Motorways and expressways (GRIP4 class 1) at a fitted free-flow speed…"), `.ap` = 4 with airport names; no `.rail.*` requests; 0 4xx other than `/favicon.ico`. |
| D14 visible disclaimer | Pass | `#disclaimer` in `.reading`, `offsetParent` non-null at all four viewports, 10px `#8f96a0`, text "For reference only: estimates from open data and a simplified model, with no warranty." |
| D12 door to door beside figures | Pass | Tip "5 h 11m door to door · Beijing, China"; pins "Door to door 5 h 11m"; legs total "5 h 11m Door to door"; `.legend-cap` "Hours from the departure city, door to door." (4 instances on screen with a route). |
| C9 failure UI | Pass | `*hover_cells.bin` aborted → `#where` "Could not reach ./hover_cells.bin (Failed to fetch).", canvas absent, list empty, one uncaught Error (intended). `*index.json` aborted → "Could not reach ./index.json (Failed to fetch)." visible at (30,620) 274x31. The non-JSON branch (app.js:47) could not be forced (`--body` mock did not apply). |
| E1 page half | Pass | `#n-cities` "157" from `meta.origins.length`; meta/OG/JSON-LD say "hundreds of cities". |
| C2 copy half | Pass | Legs: "1 h 07m Onward from PEK" then "Surface travel over the whole journey:" then "59 min by highway". |
| D17 console errors | Resolved (not reproducible) | `agent-browser console` empty after load, hover burst, click, switches to Tokyo/London/Paris and a scheme change. Cycle-1's seven entries coincided with the `.rail.*` 404s, which the `meta.railDetail` gate (app.js:483) now prevents. |

Still-open cycle-1 items with no new evidence: C3 (hover cell vs outline: the outline is a res-5 hexagon in this dist, `solveRes` 5), C5, D11 (two "Route" headings and the time three times — `h2` "Route" + `#route summary` "Route"; `#time` "5h 11m", pins "5 h 11m", legs total "5 h 11m"), D13 (43 requests / 8.42 MB first load, 2.61 MB per origin switch), D15 (`.ap` tooltip top 562 vs `#legs` top 559 — 3 px), D20.

## Findings

### High

#### UX-24 — The departure city is never guaranteed a label; on the opening view Seoul has none
- **Severity:** High · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:244` (`labelPool = p.places.slice(0, 900)`), `:269` (budget `z < 2.2 ? 18`), `:287-298` (rank-ordered placement); copy `web/index.html:361`.
- **Evidence:** Opening view z1.9, 9 labels, all origins: Istanbul (384,216), Lahore, Beijing (569,382), Shanghai, Ho Chi Minh City, Mumbai, Guangzhou, Chongqing, Xi'an. Seoul projects at (640,400) — the exact centre of the screen, a bright band-0 patch — with no name. `places.json` ranks Seoul **22** and Tokyo **24** (top 20 are Shanghai, Chongqing, Chengdu, Beijing, Guangzhou, Shenzhen, Kinshasa, Istanbul, Lagos, Ho Chi Minh City, Tianjin, Wuhan, Lahore, Xi'an, Mumbai, São Paulo, Mexico City, Hangzhou, Karachi, Delhi), so both fall outside the 18-label budget; London is rank 33, Paris **201**, Osaka 145. After departing from Paris (reduced-motion test) the labels were Istanbul, Lahore, Shanghai, Mumbai, Chongqing, Kinshasa, Lagos, Wuhan, Mexico City — no "Paris" (budget 40 below z3, 120 below z4). The readout says "Click a city name to depart from it" while the one city the visitor is looking at is unnamed.
- **Why it matters:** The first thing a visitor must learn is "this is from Seoul". `#origin-name` says so 700 px away in the rail; on phones the rail is a folded sheet header. The unlabelled bright patch reads as "the map is centred on something" rather than "you are departing from Seoul".
- **Fix (S):** In `showLabels`, place the active origin first regardless of rank: `const first = labelPool.find(l => l.origin?.slug === active?.slug)` and iterate `[first, ...rest]`, or give origin labels `rank = Math.min(rank, 17)`. Keep the collision filter (Tokyo at (708,408) is within `gapX` of Seoul and should still yield). Also render the active origin label in the accent so it is distinguishable from clickable non-active origins (`.lbl.origin[aria-current="true"]{color:var(--accent)}`) — measured accent on band 0 is 1.9:1 without the shadow, so keep the text-shadow and consider a 72 % scrim pill behind the active label only.

#### UX-25 — On touch, a tap updates the pins but never the reading; with the sheet folded a tap does nothing visible and the legend is gone (C13, new evidence)
- **Severity:** High (touch) · **Confidence:** High (mouse-click model; real tap Needs manual validation) · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:705-736` (`#time`/`#where` written only in `mousemove`), `:786-795` (click writes pins/legs only), `:1061-1064` (fold toggle), `web/index.html:339-340` (`.rail.folded > :not(.sheet-toggle){display:none}`).
- **Evidence (390x844 and 820x1180, dispatching mousedown/mouseup/click on the canvas):** sheet open → `#route.open` true, `#legs` visible (14,644,362x169), pins "From Seoul / To Aoyuncun, Chaoyang District, China / Door to door 5 h 11m", **but** `#time` still "38h 56m" and `#where` "near Port-Vila — Shefa, Vanuatu 14.89°S 166.28°E · 33–38 h · from Seoul" — the values of the last `mousemove`, i.e. a different place on a different continent, directly above the pins that say Beijing. Folded → rail 23 px, `#tints`/`#time`/`#keys` all `offsetParent` null; tap → `#route.open` true, `#legs` not visible, rail still 23 px, nothing on screen changes. Same at 820x1180 and 844x390. `.tip{display:none}` below 860 px (index.html:311), so the sheet readout is the only reading on a phone.
- **Why it matters:** The phone reading is either stale or blank ("—") after every tap; the CLAUDE.md legend rule ("always visible") is broken whenever the sheet is folded.
- **Fix (S):** In `map.on("click")`: write the reading (`#time`, `#where`) from the clicked point using the same code path as `mousemove` (factor the readout into `showReading(lat, lng, point)`), then `rail.classList.remove("folded")` + `sheet-toggle[aria-expanded=true]`. Keep the 9 px `#tints` strip inside `.sheet-toggle` while folded (move the node, or render a 4 px copy) so the legend never disappears.

### Medium

#### UX-26 — In the Mono scheme "no scheduled route" is the same colour as a band (ΔE 0.9); three other schemes sit below the 8 target
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (measured) · **Effort:** S
- **Where:** `web/app.js:19` (`UNCHARTED = "#4a4d50"`), `:74-86` (RAMPS), `:167`, `:454-455`; `scripts/check_ramps.py` (measures anchors and sea, not the grey).
- **Evidence:** Expanding each scheme to the 37 painted bands with the page's own OKLab code and measuring ΔE×100 from `#4a4d50`: **mono 0.9** (band 28, L 0.42 vs grey L 0.42), muted 6.1, sand 6.2, warm 6.5, forest 6.9, ice 8.4, twilight 8.8, copper 8.8, lavender 10.6, vivid 11.4, rose 12.2, ember 13.1. WCAG contrast of the grey against the muted last band is 1.5:1 and against band 30 1.03:1. In the Mono screenshot (`c2_desktop_mono_scheme.png`) Siberia's "no route" cells and the 28–32 h bands are one surface, and the legend swatch equals the strip.
- **Why it matters:** The legend entry added in C6 is only useful if the swatch is visually distinct from the ramp. Mono is the scheme a colour-blind visitor is most likely to choose.
- **Fix (S):** Make `uncharted` per scheme (like `sea`), chosen so ΔE ≥ 8 from every one of the 37 bands — for Mono a cool low-chroma tone such as `#3b4656` (hue where the ramp has none) or a hatch (`fill-pattern` from a 4x4 canvas image added with `map.addImage`), and extend `check_ramps.py` to print `min ΔE(uncharted, bands)` per scheme so the rule is measured, per CLAUDE.md.

#### UX-27 — The focus ring on city, airport and address rows is clipped to a 1 px line by the list's scroll box
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/index.html:193-194` (`.results{overflow-y:auto}` → computed `overflow: auto auto`), `:195-199` (`.results button{width:100%}`), `:283-284` (`outline:2px solid; outline-offset:1px`).
- **Evidence:** `#results` box (1011,239) 234 wide; first `button` box (1011,239) 234x26 — identical edges, `padding 0`. The ring extends 3 px beyond the button on the left, right and (first row) top, all outside the scroll container, so only the bottom edge paints (`c2_desktop_focus_result_row.png`: a thin orange underline under "Abu Dhabi"). `:focus-visible` matches and the computed outline is `solid 2px 1px`, i.e. the CSS is right and the container clips it.
- **Why it matters:** WCAG 2.4.7/2.4.11 — the D7 fix is defeated exactly where keyboard users spend the most time (the 157-row list and the arrow-key navigation added in D4).
- **Fix (S):** `.results{padding:3px 3px 3px 0;margin-left:-3px}` or `.results button:focus-visible{outline-offset:-2px}` (ring inside the row; 2 px inset is still 3:1 on `--surface`). The same pattern applies to `.legs` (`overflow:auto`) for `.ap`/`.mode` rings near its edges.

#### UX-28 — After an origin switch the reading keeps the previous origin's figure and "· from Seoul" until the pointer moves
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:458-526` (`paintOrigin` writes `#origin-name` and pins but not `#time`/`#where`).
- **Evidence:** Click "London" in the list; immediately `#origin-name` = "London", `bands.url` swapped in 4 ms, while `#where` = "Beijing — China 39.90°N 116.40°E · 4.3–5 h · from Seoul" and `#time` = "5h 11m" for as long as the pointer rests (the flyTo runs ~2.2 s to `idle`). Pins do say "Door to door loading…" then the new value.
- **Why it matters:** For two seconds the most prominent number on the page belongs to a departure the visitor just left, next to a header naming the new one.
- **Fix (S):** At the top of `paintOrigin`: `$("time").textContent = "—"; $("where").textContent = \`Loading the times from ${o.name}…\`` and restore the idle prompt on `.bin` arrival if no pointer is over the chart; or re-run the readout for the last pointer position when `hoverTimes` lands.

#### UX-29 — "Search address" wraps onto two lines and is 12 px taller than the button above it
- **Severity:** Medium (opening view, primary panel) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/index.html:211-212` (`.qrow{display:flex;gap:8px}`, `.qhint`), `:397-400`.
- **Evidence:** `#find-address` box 87x40 at 1280x800 and 99x40 at 844x390 (two lines of 12 px text in a `line-height:1` button, `c2_desktop_1280x800.png` shows "Search / address"); `#locate` directly above is 186x28. At 820x1180 the button is 107x28 (one line) because the body is wider. The `.qhint` (139x28) takes the flex space first.
- **Fix (S):** `.qrow .btn{flex:none;white-space:nowrap}` and `.qhint{flex:1 1 auto;min-width:0}`; or drop the hint into the placeholder/`title` and give the button the row.

#### UX-30 — Empty local search is still silent; a 1–2 character query plus "Search address" does nothing (D8, current behaviour confirmed)
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:825-867` (`render` has no empty branch), `:879` (`if (q.length < 3) return;`).
- **Evidence:** `fill #q "zzzzq"` → `.results button` 0, `#results.innerHTML === ""`, `#departure .body` collapses to 174 px with nothing under the input. Only Enter (or the button) then yields "No address found for "zzzzq"." (11px `#8f96a0`) with the Nominatim credit. `fill "zz"` + click `#find-address` → no `.addresses` node, no message. The "Address search is unavailable right now." branch (app.js:897) could not be forced in this harness (the abort route on the Nominatim host did not take effect; the real request returned 0 hits) — code-verified only.
- **Fix (S):** In `render()`, when `hits.length + apHits.length === 0` and `f`: append `<li class="head">No charted city or airport matches "zzzzq". Press Enter or "Search address" to look it up.</li>`; in `searchAddress`, for `q.length < 3` show "Type at least three characters." in the same slot.

#### UX-31 — The pointer tooltip is clipped at the bottom edge of the viewport (no vertical flip)
- **Severity:** Medium (desktop only; `.tip` is hidden below 860 px) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:730-734` (horizontal flip only), `web/index.html:236-241` (`position:fixed`).
- **Evidence:** Land under the pointer at (860,792) on a 1280x800 viewport → `#tip` box top 806, bottom 836 (> 800), `hidden:false`; the reading "18h 02m" is on screen only in the readout. Near the right edge the horizontal flip works (pointer (1272,720) → tip 987–1260). `body{overflow:hidden}` so the clipped part is simply lost.
- **Fix (S):** `const h = tip.offsetHeight; tip.style.top = \`${y + 14 + h > innerHeight ? y - h - 12 : y + 14}px\``.

#### UX-32 — Keyboard reach and widget semantics (D4 semantics, measured): 9 label buttons precede the whole UI, 157 rows are tab stops, no live region, `#map` is `role="img"` with focusable content
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:249-259` (label buttons, no `tabindex`), `:851-864` (rows), `web/index.html:352` (`role="img"`), `:396`, `:401`, `:433`.
- **Evidence:** Focusable count 199: canvas, 9 `.lbl.origin` buttons, 4 `summary`, 172 buttons (157 rows + locate, find-address, clear, 12 ramps), 3 inputs, 10 credit links. Tab walk from the top: 1 canvas, 2–10 the nine label buttons (Shanghai … Mumbai), 11+ the `.ap` spans of an open route, then the rail. From `#q`, Route's summary is 159 Tabs away. `Escape` with a route open changes nothing (`#route.open` true, `#legs` visible). ARIA reads: `#results` role null, `#q` `aria-expanded`/`aria-controls` null, `#ramps` role null with `aria-current` on buttons (`type` "submit"), `aria-live` null on `#time`, `#where`, `#pins`, `#legs`, `#here`; `#map` `role="img"` contains `canvas[tabindex=0][role=region]` and the 9 buttons (children of `img` are presentational by spec). Heading structure: one `h1`, and an `h2` "Route" that exists only inside `#legs`; the four panels are `summary` elements, not headings.
- **Fix (S):** `tabindex="-1"` on `.lbl.origin` (still clickable; the list is the keyboard path); roving tabindex on `.results button` (`tabindex=-1` except the first/active, `aria-activedescendant` on `#q`, `role="listbox"`/`"option"`); `#ramps role="radiogroup"` with `role="radio" aria-checked` and `type="button"`; `aria-live="polite"` on `#where` and `#pins`; `#map` → `role="application" aria-roledescription="globe"` or no role; `Escape` anywhere with a route → the Clear action.

### Low

#### UX-33 — Terminology and units are still mixed (D19, instances enumerated)
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence (selector → text):** units — `#time` innerText "5h 11m" (app.js:712, big + `<small>`) vs `.leg .t`/`.pins .val`/`#tip b` "5 h 11m" (app.js:591, 760, 728); "59 min" and "16 min" (app.js:536 `"min"`) vs "h 07**m**" (537); beyond 48 h `#time` "5days 8h" and tip "5 days 8h" (538) while `.legend-cap` says "Hours" and the strip ends at "72+". Vocabulary — "chart" and "globe" both in `#route .hint` (index.html:408-412: "Click anywhere on the chart … click a city name on the globe"), "chart" in `#where` (361) and the coarse-pointer copy (app.js:1078), "globe" in `#settings .hint` (435), "map" only in `#map[aria-label]` (352) and `<noscript>`; "passage" in `#where` (361), app.js:1078 and `#key` (445, 448), "journey" in `.leg .d` (app.js:642) and `#key` (447, 456), "time(s)" in the loading/unavailable copy (app.js:498, 717); "Reckoned"/"reckoning" in `#key` (443, 445). "Departure" is used consistently (good; "origin" does not appear in visible copy).
- **Fix (S):** One noun for the surface ("chart"), one for the quantity ("time" in UI copy; keep "passage" for the title and the Galton line), "journey" only for a route; minutes as "m" everywhere or "min" everywhere; render ≥ 48 h as hours ("128 h") to match the legend, with days in a `title`.

#### UX-34 — "near X" has no distance cap: Antarctica reads "near Port-aux-Français" (≈3,000 km away); the tip says "∞ no route door to door"
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:691-700` (`describe`: `p.km > 60 ? "near …"`), `:725-728` (tip), `:534` (`["∞", "no route"]`).
- **Evidence:** Pointer at 75.00°S 90.00°E → `#time` "∞ no route", `#where` "near Port-aux-Français — Kerguelen, French Southern Territories | 75.00°S 90.00°E · no scheduled route", tip "∞ no route door to door · near Port-aux-Français, French Southern Territories". Port-aux-Français is at 49.35°S 70.22°E, about 3,060 km away. Greenland interior (72°N 40°W) → "near Nuuk" (≈ 640 km).
- **Fix (S):** Above ~250 km show coordinates only (or "Antarctica"/"Greenland" from a small polar table); in the tip, when `min >= UNREACHABLE` print "No scheduled route · <place>" and omit "door to door".

#### UX-35 — Legend tick labels are true but hard to read: no unit, one-decimal values, 2–3 px gaps, "72+" overhangs the strip
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/app.js:178-198` (`TICK_TARGETS_MIN`, `fmtH`, `i - last >= 3`), `web/index.html:156-160`.
- **Evidence:** Labels "1 · 2.1 · 3.8 · 7.8 · 15.9 · 24.5 · 50.3 · 72+" at 10px `#8f96a0`; boxes "15.9" 205–225 vs "24.5" 227–248 (2 px), "50.3" 264–285 vs "72+" 288–306 (3 px); "72+" right edge 306 vs `#tints` right 304; the pair reads as "15.924.5" in `c2_desktop_1280x800.png`. Only three edges are whole hours (60, 300, 4320 → 1, 5, 72).
- **Fix (S):** Keep true edges (policy) but pick targets that exist or are one decimal at most and spaced: e.g. 60, 300 (5 h — exact), 955 (16), 1470 (24.5), 3020 (50), 4320 (72+) — six labels with ≥ 8 px gaps; print "h" on the first label ("1 h") so the unit is on the strip; right-anchor the last label (`transform:translateX(-100%)` when `left > 90 %`). Enforce a minimum pixel gap after measuring `getBoundingClientRect`, not a band-index gap.

#### UX-36 — At 320 px width (400 % zoom) the mast overlaps the compass, tick labels collide and city rows clip
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/index.html:343-348` (landscape rail `width:min(300px,46vw)`), `:306`, `:309`.
- **Evidence (320x256):** `.mast` (10,10,128x49) overlaps `#compass` (125,10,38x38) by 13 px; `tickCollide` true; `summary` 148 > 146 and 29 `.results button` rows `scrollWidth` 120–146 > `clientWidth` 118 (clipped, not wrapped); rail 147 px wide, `railScroll` 529/256. No horizontal page scroll (good). 640x400 (200 %) is clean: no overlaps, no overflow.
- **Fix (S):** Use the bottom-sheet layout below 480 px regardless of orientation (`@media (max-width:479px)`), and let `.results button` wrap (`flex-wrap:wrap` or hide `.coord` under 360 px). WCAG 1.4.10.

#### UX-37 — The one-line description disappears below 860 px, including on the 820 px tablet where the mast has 476 px of room
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/index.html:308` (`.mast p{display:none}`), `:306` (`max-width:58vw`).
- **Evidence:** 820x1180: `.mast p` computed `display:none`, `.mast` 185x32, `max-width` 475.6 px; the sheet's `#where` still reads "Move the pointer…" (the coarse-pointer copy only applies when `(pointer: coarse)` matches). On a tablet the page then says "Isochronic Passage Chart" and nothing else about what it is.
- **Fix (S):** `@media (max-width:860px) and (min-width:600px){.mast p{display:block}}`.

#### UX-38 — No favicon: `/favicon.ico` 404 on every load
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence:** Resource Timing: `/favicon.ico` status 404 (300 B) on each load; no `<link rel="icon">` in `index.html`; no icon file in `web/`.
- **Fix (S):** `<link rel="icon" href="data:image/svg+xml,…">` (an inline SVG of the compass needle, no request), or vendor a 32 px PNG.

#### UX-39 — Origin-label buttons on the globe are 42x13–14 px targets; scheme rows 22 px; sheet handle 22 px (D16, new instance)
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence:** `.lbl.origin` boxes 42x14 (1280x800), 42x13 (phones); `#ramps button` 234x22 with 5 px gaps; `#sheet-toggle` 22 px; `.results button` now 26 px (D16 partially done); checkboxes 15x15 inside a 234x31 label row (acceptable).
- **Fix (S):** `.lbl.origin{padding:5px 6px;margin:-5px -6px}` keeps the visual size and gives a 24 px hit area; `.ramps button{padding:4px 3px}`; handle 28 px.

#### UX-40 — With Departure open and a destination set, Settings and Sources fall below the rail's fold; the colour-scheme list is off-screen even when Settings is opened
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence (1280x800):** rail `scrollHeight/clientHeight` 760/760 at load; 1031/760 after a click (Route open), 1055 with a long address; with Settings also open, `#ramps button` first box at y = **919** (`elementFromPoint` null), so the picker can only be reached by scrolling a `scrollbar-width:thin` rail. `.results{max-height:40vh}` (320 px) is the main consumer.
- **Fix (S):** `.results{max-height:min(40vh,280px)}` and `.rail:has(#route[open]) .results{max-height:22vh}`; or close Departure when a destination is set (the summary still names the city).

#### UX-41 — The search hint is wrong for airport codes
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence:** `.qhint` "Enter departs from the first city match." — `fill "jfk"` + Enter sets the **destination** (pins "To JFK — John F. Kennedy International Airport", Route opens, flyTo z5), because airports are destinations by design (app.js:818-819, 972-973).
- **Fix (S):** "Enter picks the first match: a city to depart from, an airport as destination."

#### UX-42 — Control-style drift: radii 2/3/4/6 px, one UA focus ring, a stale grey, unset button types
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Evidence:** `.panel` 2 px, `.mast` 3 px, `.btn`/`#q` 2 px, `.pins .depart` **6 px** (index.html:253, also a different background/hover), `.ap::after` 4 px (263), `#compass` 50 %. `.pins .depart:focus` shows the UA `auto 1px rgb(153,200,255)` ring while every other control shows the 2 px accent. Compass south needle `#6f757e` (index.html:383) is the pre-D6 `--text-3` (3.94:1 on `--surface`). `.results button` `type` unset and `#ramps button` `type="submit"` (harmless outside a form, but `.depart` sets `type="button"`). `.compass` computed font Arial 13.33px (no text, harmless). `.lbl.origin[title]` duplicates the visible text ("Depart from Istanbul") — good.
- **Fix (S):** One radius token (`--r:2px`), `.pins .depart` restyled as `.btn`, add `.depart` to the focus-visible list, needle grey → `var(--text-3)`, `type="button"` in `render()`/`paintRampPicker()`.

## Information architecture and first-run (what a visitor understands in five seconds)

- **1280x800:** title + one-line description (top-left), a globe with nine named cities, "Departure Seoul" and a city list (right), "— / Move the pointer over the chart to read a passage. Click a city name to depart from it." and the legend (bottom-left). What is clear: it is a travel-time map, there is a list of departure cities, hovering reads a time. What is not: that the bright patch in the middle is Seoul (UX-24); what "1 · 2.1 · 3.8 …" means without a unit (UX-35); that the grey is "no route" is now keyed (C6 pass). The `Route` panel is closed and its purpose ("click anywhere to set a destination") is inside it, so click-to-route is discovered by accident; one sentence in `#where` ("Click anywhere for a route.") would close that gap at zero layout cost.
- **820x1180 / 390x844:** the globe takes 792 / 442 px, the sheet carries reading + legend + four closed panel headers; the subtitle is gone (UX-37); "Move the pointer…" copy shows unless `(pointer: coarse)` (on a real phone it becomes "Tap the chart to read a passage." — but a tap does not write the reading, UX-25). The legend and the disclaimer are on screen unfolded at all three small viewports (`legendOnScreen` true) and gone when folded.
- **844x390:** a 300 px right rail with the reading at the top; Departure open leaves a 101 px list (3 rows) and the rail scrolls 678/390 — usable, cramped; the legend stays on screen (top 118).

## State × viewport matrix

| State | 1280x800 | 820x1180 | 390x844 | 844x390 |
|---|---|---|---|---|
| Loading (before `index.json`) | FCP 156 ms; canvas, 157 rows and 9 labels all present by 373 ms (eval start); bands painted by 624 ms; `map.loaded()` 1.87 s (flyTo). CLS 0.012 (one shift at 197 ms: `#route`/`.qrow`/`#q`) | not re-measured | not re-measured | not re-measured |
| Opening | 9 labels, no Seoul (UX-24); "—"; legend + keys + cap + disclaimer visible | sheet 389 px, all panels closed, reading in sheet | sheet 403 px, 8 labels, globe 442 px | rail 300 px, reading top 22 |
| Hover land | "5h 11m", "Beijing — China / 39.96°N 116.36°E · 4.3–5 h · from Seoul"; tip 215x30 at +16/+14; hexagon 7-point closed ring (6 unique), line 1.5, fill 0.10 | `.tip` display none | `.tip` display none | `.tip` display none |
| Hover ocean | "—", "Open water.", tip hidden, hover source empty | — | — | — |
| Unreachable land (75°S 90°E) | "∞ no route", "… · no scheduled route", tip "∞ no route door to door · near Port-aux-Français…" (UX-34) | — | — | — |
| Click land | Route opens; pins From/To/Door to door; legs 6 rows, 4 `.ap` + 1 `.mode` tooltips; `.reading` grows 239 → 465 px; `#legs` 212 px (no scroll) | legs visible 194 px; sheet grows to 614 px; reading stale (UX-25) | legs 169 px (scrolls: 6 rows), Route header at y 865 (below 844) | legs 78 px (scrolls) |
| Origin switch (list) | source swapped 4 ms, 2.61 MB per origin (bin 181 KB, modes 1.09 MB, json 496 KB, air 181 KB, ~50 pmtiles ranges ≈ 0.67 MB), idle 2.2 s; readout stale (UX-28) | — | — | — |
| Origin `.bin` fails | "Loading the times from Tokyo…" → "Times unavailable for Tokyo."; labelled console error | — | — | — |
| Empty city search | silent (UX-30) | — | — | — |
| Address none / found / unavailable | "No address found for "zzzzq"." / "Addresses" + 6 rows + credit, pick → pins + legs ("11 min by major road / 4 min by highway / 16 min Door to door") / unavailable branch code-only | — | — | — |
| `index.json` / `hover_cells.bin` fail | message in `#where`, no canvas, no list | — | — | — |
| Sheet folded | n/a | 23 px handle; legend, time, keys hidden; tap does nothing visible (UX-25) | same | same |
| 200 % / 400 % zoom (640x400 / 320x256) | clean / mast–compass overlap, tick collision, row clipping (UX-36) | | | |

## Perceived performance

- First load (local, uncompressed): **43 requests, 8,422,983 B transferred** (8.41 MB decoded); largest: `places.json` 1.78 MB, `borders.json` 1.28 MB, `seoul.modes.bin` 1.09 MB, `maplibre-gl.js` 1.05 MB, `hover_cells.bin` 726 KB, `seoul.json` 528 KB, `airports.json` 259 KB, `h3.js` 193 KB, `seoul.bin`/`seoul.air.bin` 182 KB each, six `water.pmtiles` ranges 88–156 KB. `hover_cells.bin` and `index.json` still gate map creation (D13 open). External: gtag + 6 analytics beacons (status 0 in this sandbox).
- Ready: FCP 156 ms; list/labels/canvas ≤ 373 ms; bands painted 624 ms; DCL 88–171 ms; load 171–509 ms across reloads.
- Hover: 120 synthetic `mousemove`s over 2.2 s → readout updated 120/120; frame delta avg 18.6 ms, p95 16.8 ms, max 233 ms (2 frames > 33 ms, first frames), synchronous dispatch cost 20.7 ms total (0.17 ms each).
- Origin switch: source swap 4 ms after click; per-origin bytes 2.61 MB; `idle` at 2.2 s (dominated by the 2 s flyTo).
- Layout shift: CLS 0.012 (good); the one shift is the Route panel moving when `.qrow`/`#n-cities` fill (197 ms).

## Design quality against the brief

The chrome is coherent: one type family at 10–13 px for chrome and 50 px for the reading, weights 400/500/600 carrying the hierarchy without letter-spacing or caps, a near-black ground with the scrim panels (`--bg` at 86 %) and the ramp as the only saturated colour besides the accent. Specific, bounded improvements (all S): the wrapped "Search address" button (UX-29) and the "Showing Seoul." orphan line under it are the first two things in the primary panel and read as unfinished; the legend numerals need a unit and breathing room (UX-35); the readout's `#where` line packs name, coordinates, band and origin into one 12 px line separated by " · " — putting "from Seoul" on its own line (or into the legend cap, dynamic) would let the departure read at a glance; the `.pins .depart` button is the one control with a different radius, background and focus ring (UX-42); the Mono scheme needs its own grey (UX-26). Hover/active states are consistent (`:hover` lifts colour one step, `aria-current` rows go accent 500), disabled state exists only on `#locate` (`disabled` while locating — no visual style beyond the UA's, worth `.btn:disabled{color:var(--text-3)}`). Iconography is limited to the compass and the "+/−" `summary::after` glyphs (14 px `--text-3`, 6.13:1) — adequate.

## CLAUDE.md design-policy checklist

| Rule | Result | Evidence |
|---|---|---|
| IBM Plex Sans everywhere, self-hosted | Pass | Computed `font-family` starts with `"IBM Plex Sans"` on all 37 measured selectors (mast, summary, `#q`, buttons, rows, reading, ticks, cap, disclaimer, keys, legs, rows, ramps, hints, `#key`, tip, `.lbl`, `.lbl.origin`, pins). Only `#map` (MapLibre's Helvetica rule, no text) and `.compass` (Arial UA default, no text). Fonts loaded from `./vendor/*.woff2`; no external font host. Latin subset only (D2 subset open). |
| `letter-spacing` default everywhere | Pass | `letterSpacing: normal` on every measured selector. |
| No `text-transform: uppercase` | Pass | `textTransform: none` on every measured selector; `grep text-transform web/` → none. |
| No `font-variant-numeric: tabular-nums` | Pass | `fontVariantNumeric: normal` on every measured selector. |
| Dark theme | Pass | `--bg #0a0b0d`, `color-scheme: dark`, `theme-color #0a0b0d`. |
| Band colours measurably separable (adjacent ΔE ≈ 8, L monotonic) | Pass for anchors; note | `check_ramps.py`: 12 schemes OK, min anchor ΔE 6.5–8.9, L strictly monotonic 0.95–0.97 → 0.26–0.33, sea L 0.20–0.22. The 37 painted bands are 1.8–2.4 apart (by design, D20). The uncharted grey is not measured by the script — UX-26 (Mono 0.9). |
| Legend always visible, ticks at true boundaries | Pass on desktop and unfolded phone; fail folded | Ticks: 8, each `data-min ∈ bandEdgesMin`, positioned at `(i+1)/37`. Visible at all four viewports unfolded; hidden while the phone sheet is folded (UX-25 / C13). |
| Hexagons drawn as hexagons | Pass | Hover source data: 1 feature, ring of 7 points (6 unique, closed), ≈0.17° across (res 5 in this dist). |
| "Door to door" wherever a figure is presented | Pass | Tip, pins row, legs total, legend cap (UX-34: also printed after "∞ no route"). |

## Final sweep

**Screenshots (attachments, not evidence)** under
`/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-73ee-496f-a42e-4a7a5c8148d1/scratchpad/`:
`c2_desktop_1280x800.png` (opening view), `c2_tablet_820x1180.png`, `c2_mobile_390x844.png`,
`c2_landscape_844x390.png`; also `c2_desktop_route_1280x800.png`, `c2_desktop_ap_tooltip.png`,
`c2_desktop_focus_result_row.png`, `c2_desktop_labels_z46.png`, `c2_desktop_mono_scheme.png`,
`c2_desktop_search_unavailable.png`, `c2_desktop_failure_index_json.png`,
`c2_tablet_folded_after_tap.png`, `c2_mobile_folded_after_tap.png`, `c2_mobile_route_390x844.png`,
`c2_landscape_folded_after_tap.png`, `c2_landscape_departure_open.png`,
`c2_reflow_zoom200_640x400.png`, `c2_reflow_zoom400_320x256.png`.

**Console / errors.** 0 console messages and 0 uncaught errors after load, hover, click, three
origin switches and a scheme change. The only entries seen were the intended ones under fault
injection: one labelled `hover data unavailable: TypeError: Failed to fetch` (aborted `.bin`) and
one uncaught `Error` from `fatal()` (aborted `hover_cells.bin`).

**Not exercised / needs a device.** Real touch tap (the click model above stands in for it);
`prefers-reduced-motion` (emulation did not apply in this harness); the Nominatim "unavailable"
branch; the non-JSON `index.json` branch; Safari/Firefox rendering of `color-mix`,
`backdrop-filter`, `scrollbar-color`.

**Browser cleanup.** `agent-browser --session c2design close` → "Browser closed"; then the
`browser_verify.sh` loop (`/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/|agent-browser" |
grep -vE "grep|Google Chrome\.app" | awk '{print $1}' | while read p; do kill -9 $p; done`) →
**agent-browser left: 0 | Google Chrome untouched: 10**; `agent-browser session list` → "No active
sessions". The user's Google Chrome was not touched. The preview server on 127.0.0.1:8899 was left
running; no other process was started or stopped.
