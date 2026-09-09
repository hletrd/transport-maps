# Designer (UI/UX) review — cycle brief: "more details, higher quality and design and ease of usage and UI. Do not overwork."

Reviewed target: the CURRENT `web/` served over the local `dist/` at `http://127.0.0.1:8899/`
(Range-capable, Python SimpleHTTP, no gzip). Live site `https://worldmap.atik.kr/` used only
for comparison (it is behind the working tree; where a defect also exists live it is noted).
Browser: `agent-browser --session c1design`, headless Chromium, viewports 1280x800, 820x1180,
390x844, 844x390. Every finding below is backed by text-extractable evidence (computed styles,
boxes, DOM counts, resource timing, console, network) — screenshots are attachments only:
`/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-73ee-496f-a42e-4a7a5c8148d1/scratchpad/design_*.png`.

Sources read in full: `/Users/hletrd/flash-shared/transport-maps/web/index.html` (432 lines),
`/Users/hletrd/flash-shared/transport-maps/web/app.js` (999 lines), `CLAUDE.md`,
`dist/index.json`, `web/vendor/fonts.css`, `web/vendor/maplibre-gl.css` (first rule),
`scripts/check_ramps.py`, `scripts/browser_verify.sh`.

Read-only review: no repo file was modified other than this document. No build, deploy or
`dist/` / `data/` writes. `scripts/check_ramps.py` was run WITHOUT `--respace` (read-only mode).

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 5 | UX-1, UX-2, UX-3, UX-4, UX-5 |
| Medium | 9 | UX-6, UX-7, UX-8, UX-9, UX-10, UX-11, UX-12, UX-13, UX-14 |
| Low | 9 | UX-15, UX-16, UX-17, UX-18, UX-19, UX-20, UX-21, UX-22, UX-23 |

Ranked by user impact per unit of effort. Everything in the High block is an S-effort CSS or
copy fix that a first-time visitor will feel immediately. **All five High findings also exist
on the live site** (same `font:` shorthand in the live HTML, same label thresholds and legend
code in the live `app.js`).

The one-paragraph version: the page's chrome is well designed and the dark theme, legend and
route summary are of real quality, but three things undercut it on first contact — (1) an
invalid CSS `font` shorthand silently drops IBM Plex Sans from every button, the search box and
the city list (they render in Arial/system-ui), (2) place labels on the globe are drawn in
MapLibre's Helvetica Neue and are illegible on the bright bands right around the departure
city, exactly where the readout tells you to "click a city name", and (3) at the opening zoom
there are no city names at all. Behind those: Enter in the search box does nothing and the
city list is 157 tab stops, the legend's "72+" tick sits at the 67 h edge and collides with
"48", and the Route panel's instructions describe a click model the code does not implement.

Design-policy compliance (CLAUDE.md): `letter-spacing`, `text-transform`,
`font-variant-numeric` are all at defaults on every measured element (h1, summary, legend
ticks, legend cap, readout, rowlabel) — compliant. Dark theme compliant. Legend always visible
on desktop — compliant; on phones it disappears when the sheet is folded (UX-9). Typeface
policy is VIOLATED in two places (UX-1, UX-2). Legend-tick policy is violated in one (UX-5).
Ramps: `scripts/check_ramps.py` passes all 12 schemes (min anchor ΔE 6.5–8.9, lightness
strictly monotonic). Note for the record: after interpolation to 37 bands, adjacent-band ΔE is
1.8–2.7 for every scheme (computed with the same OKLab code) — that is by design ("read as a
gradient") but it means the "≈8 between adjacent bands" sentence in CLAUDE.md now describes
the 11 anchors, not the 37 painted bands. Not a finding; worth one line in the policy.

---

## Findings (ordered by impact per effort)

### UX-1 — Invalid `font: … inherit` shorthand drops IBM Plex Sans from the search box, city list, scheme picker, Clear button and address results
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (local and live)
- **Evidence:** `getComputedStyle(...).fontFamily` at 1280x800: `.results button` → `Arial` (13.3333px), `#q` → `Arial` (13.3333px), `#ramps button` → `Arial` (13.3333px), `.btn` → `Arial`, `.results .addresses button` → `Arial`. Meanwhile `.mast h1`, `summary`, `#time`, `.scale span`, `.tip` → `"IBM Plex Sans", -apple-system, …`. `document.fonts` reports all three Plex faces `loaded`, so the font is present — the declarations are simply discarded. Live HTML contains the same four shorthands (`curl … | grep 'font:[0-9]* [0-9.]*px/[0-9.]* inherit'` → 4 matches).
- **Where:** `web/index.html:181` (`.results button{… font:400 13px/1.4 inherit …}`), `:189` (`#q{… font:400 13px/1.5 inherit …}`), `:208` (`.ramps button{… font:400 12px/1.2 inherit …}`), `:251` (`.btn{… font:500 12px/1 inherit …}`).
- **Why it is a problem:** CSS-wide keywords (`inherit`) are not valid as a component inside a shorthand, so the whole `font` declaration is invalid and the UA stylesheet's `font: -webkit-small-control` / 13.333px Arial wins. The result is a typeface mix on the page's most-used controls — the exact failure the CLAUDE.md policy warns about ("a face that silently falls back undoes the choice"). It also silently changes size (13px → 13.33px, 12px → 13.33px) and weight (the Clear button loses its 500).
- **Failure scenario:** A visitor types in the search box and reads the 157-city list — the two things they touch first — in Arial while the headings around them are Plex. On macOS the list renders in Helvetica; the mismatch is obvious next to the Plex summaries.
- **Suggested fix (policy-compliant):** Replace each shorthand with longhands, e.g. `.results button{font:inherit;font-weight:400;font-size:13px;line-height:1.4}` (and likewise `#q` 13px/1.5, `.ramps button` 12px/1.2, `.btn` 500 12px/1). `font:inherit` on its own is valid and already used correctly at `:230` and `:232`. Add a one-line check to `scripts/browser_verify.sh`: `getComputedStyle(document.querySelector('#q')).fontFamily` must start with `"IBM Plex Sans"` — that check would have caught this on the last two deploys.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-2 — Globe place labels render in MapLibre's Helvetica Neue, and origin-city labels have no text shadow, so names are unreadable on the bright bands around the departure
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (local and live)
- **Evidence (zoom 4.6 over Japan/Korea, 55 labels, 11 origin labels):** plain `.lbl` computed `fontFamily` → `"Helvetica Neue", Arial, Helve…`, 11px, `textShadow` present; `.lbl.origin` (Shanghai) → `fontFamily` `"Helvetica Neue"…`, **12px** (not the 11px `.lbl` sets), weight 500, `textShadow: none`, colour `#e9e7e4`, drawn on band 16 (`#da7668`) → contrast **2.51:1**. Root cause chain: `#map` computed font is `"Helvetica Neue", Arial…` from `web/vendor/maplibre-gl.css:1` (`.maplibregl-map{font:12px/20px Helvetica Neue,Arial,Helvetica,sans-serif;…}`); `.lbl` sets no `font-family` (`index.html:226`) and `.lbl.origin{font:inherit; … text-shadow:inherit}` (`:229-231`) inherits the marker div's font and its `text-shadow: none`. Worst case measured from the ramp: `#e9e7e4` on band 0 `#faefc5` = **1.07:1**; `#a4a9b2` on band 0 = 2.05:1, on band 3 `#ef9b6a` = 1.08:1. The `design_labels_z46.png` capture shows "Seoul", "Goyang-si", "Incheon" effectively invisible on the cream/peach bands.
- **Where:** `web/index.html:226-231`; `web/app.js:160-186` (label DOM markers; comment at 162-163 claims "markers render in the page's own typeface").
- **Why it is a problem:** (a) Typeface policy violation on every label on the globe. (b) The readout's own instruction is "Click a city name to depart from it" — but the names nearest the departure sit on the brightest bands and are the least legible. (c) Origin labels are the only clickable labels and are the least protected (no shadow).
- **Failure scenario:** Visitor zooms into Korea from the Seoul view, sees a cream blob with faint smudges where Suwon/Incheon should be, never finds a clickable name, and falls back to the list.
- **Suggested fix:** `font-family:inherit` would not help (the marker's parent chain resolves to MapLibre's Helvetica rule); set the family explicitly on the label itself: `.lbl,.lbl.origin{font-family:"IBM Plex Sans",-apple-system,system-ui,sans-serif}`, and since `.lbl.origin{font:inherit}` resets the family, keep that declaration after it or replace `font:inherit` with `font-size:11px;font-weight:500`. Replace `text-shadow` with a small scrim pill that works on any band: `.lbl{padding:1px 5px;border-radius:2px;background:color-mix(in srgb,var(--bg) 72%,transparent);color:var(--text)}` and `.lbl.origin{color:var(--text);font-weight:500}` — measured `#e9e7e4` on the scrim-over-cream composite `#48463d` is 7.7:1. This also removes the size drift (origin 12px vs plain 11px). Optionally add the `latin-ext` Plex subset (see UX-20) so "Thāne", "İzmir" don't fall back mid-word once labels are in Plex.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-3 — The opening view has zero city names, but the first line of copy says "Click a city name to depart from it"
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (local and live)
- **Evidence:** after a clean load: `document.querySelectorAll(".lbl").length` → **0**, `map.getZoom()` → **1.9**, `#where` → "Move the pointer over the chart to read a passage. Click a city name to depart from it." Label budget is `n = z < 2.2 ? 0 : …` (`app.js:189`) and every origin switch flies to `zoom: 1.9` (`app.js:433`). Live `app.js` has the same two constants (grep lines 183 and 412 of the live file).
- **Where:** `web/app.js:189`, `web/app.js:433`, `web/index.html:338`.
- **Why it is a problem:** The primary "click to depart" affordance is invisible in the state 100% of visitors start in, so the instruction reads as broken. Discovery of the whole click-to-depart interaction depends on the visitor zooming in by ≥0.3 for a reason the page never gives.
- **Failure scenario:** New visitor reads the hint, scans the globe, sees no names, concludes the map has none, and uses only the list — or leaves.
- **Suggested fix (either, S):** (a) show a small budget at the opening zoom: `z < 1.5 ? 0 : z < 2.2 ? 25 : …` — the 25 largest cities are far apart enough for the existing collision filter; or (b) keep the budget and change the copy to match the state: "Move the pointer over the chart to read a time. Zoom in and click a city name, or pick one on the right, to depart from it." Prefer (a) plus (b)'s "or pick one on the right".
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-4 — Enter in the search box does nothing; the city list is 157 tab stops with no arrow-key navigation
- **Severity:** High · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `fill #q "tokyo"` → 3 result buttons, first "Tokyo 35.7, 139.7"; `press Enter` → `#origin-name` still "Seoul", `map.getSource("bands").url` still `origins/seoul.pmtiles`. `press ArrowDown` in `#q` → `document.activeElement` still `q`. Focusable elements in DOM order: 178, of which 157 are `.results button`; index distance from `#q` to `#route summary` = **158 Tabs**. The only listener on `#q` is `input` (`app.js:870`); there is no `keydown` handler anywhere in `app.js`. (Escape in `#q` does clear it — native `type=search`.)
- **Where:** `web/app.js:870`, `web/app.js:728-770` (`render`), `web/index.html:365-366`.
- **Why it is a problem:** "Type a city, press Enter" is the universal search contract; here it silently fails. Keyboard users cannot reach the Route/Settings panels without 158 Tabs.
- **Failure scenario:** Visitor types "lon", presses Enter, nothing happens; they retype, press Enter again, then reach for the mouse. A keyboard-only user never finds Settings.
- **Suggested fix:** On `keydown` in `#q`: `Enter` → click the first `.results button` (city, or airport when the query is a 3-letter code — same ordering `render()` already computes); `ArrowDown`/`ArrowUp` → move a roving `tabindex` through the result buttons (`tabindex=-1` on all but the active one, `aria-activedescendant` on `#q`); `Escape` → native clear. Give the input `role="combobox" aria-expanded aria-controls="results"` and the list `role="listbox"`. About 25 lines.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-5 — Legend ticks are placed at the wrong band edges: "72+" sits at the 67 h edge although an exact 72 h edge exists, "4" at 3.75 h, "48" at 50.3 h — and "48"/"72+" collide into "4872+"
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (local and live)
- **Evidence:** `dist/index.json.bandEdgesMin` (36 edges, 37 bands) = `[30,35,40,45,55,60,70,80,95,110,125,145,170,195,225,260,300,350,400,465,535,620,715,825,955,1100,1270,1470,1695,1960,2260,2615,3020,3485,4025,4320]`. Rendered `.scale span` `style.left`: "1"→16.22% (edge 5 = 60 min ✓), "2"→29.73% (edge 10 = 125 = 2.08 h), "4"→40.54% (edge 14 = **225 = 3.75 h**), "8"→54.05% (edge 19 = 465 = 7.75 h), "16"→67.57% (edge 24 = 955 = 15.9 h), "24"→75.68% (edge 27 = 1470 = 24.5 h), "48"→89.19% (edge 32 = **3020 = 50.3 h**), "72+"→94.59% (edge 34 = **4025 = 67.1 h**) — while edge 35 = 4320 = exactly 72 h is unlabelled. Bounding boxes at 1280x800: "48" 268.4–280.4 px, "72+" 280.2–298.2 px → touching (0.2 px overlap); in `design_desktop_1280x800.png` and `design_labels_z46.png` they read as one token "4872+". Cause: `SHOWN_HOURS.find(h => |hours-h|/h < 0.08)` accepts the FIRST edge within 8 % (`app.js:137`) and the de-duplication `findIndex` (`:138`) then rejects the exact edge that comes later.
- **Where:** `web/app.js:132-143`.
- **Why it is a problem:** CLAUDE.md: "its ticks sit at their true band boundaries … evenly spaced labels would misstate the scale." These ticks do sit on boundaries, but the boundary each is labelled with is up to 6.8 % away from the number printed, and the top-of-scale marker is on the wrong band. The colliding pair makes the top of the legend unreadable at the default desktop width.
- **Failure scenario:** A reader compares a violet cell to the legend, sees the "48" tick, and calls the journey "under two days" when the band edge is 50.3 h; anything past 67 h is read as "72+".
- **Suggested fix:** Choose the edge with the smallest relative error (argmin over EDGES, not first-within-tolerance): `const i = EDGES.reduce((b,e,k) => Math.abs(e/60-h)/h < Math.abs(EDGES[b]/60-h)/h ? k : b, 0)` per shown hour; label with the true edge value formatted to two significant figures when it differs by more than 2 % (`"1", "2.1", "3.8", "7.8", "16", "24", "50", "72+"`), or pick SHOWN_HOURS that exist on the ladder. With the exact 72 h edge used, "72+" moves to 97.3 % and clears "48" by 7 px; additionally right-align the last label (`transform:translateX(-100%)`) so it never leaves the strip. Add a unit test in `tests/` that asserts every rendered tick's edge is within 2 % of its label (this legend has now shipped with the wrong top tick to production).
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-6 — Route panel copy describes a click model the code does not implement, and the page claims 553 cities while 157 ship
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `#route .hint` renders "Click the chart to drop an origin, then click again for a destination. The origin snaps to the nearest charted city, because only those 553 have a computed surface." The `map.on("click")` handler (`app.js:689-698`) ALWAYS sets `pinB` (destination) and opens the Route panel; the departure changes only through the "Depart from X" button (`app.js:675-686`) or an origin label. `grep -c 553 web/index.html` → 7 (lines 15, 23, 31, 41, 42, 375, 421) and `web/llms.txt:3`; `dist/index.json` and live `index.json` both have **157** origins; the live HTML says "157 cities" (5 occurrences). Commit `39a9b42` moved the copy to 553 ahead of the data.
- **Where:** `web/index.html:373-375`, `:15`, `:23`, `:31`, `:41-42`, `:421`; `web/llms.txt:3`.
- **Why it is a problem:** The one paragraph that explains the core interaction is wrong in its first clause, and the number that establishes the dataset's credibility is inflated 3.5× in the meta description, Open Graph, JSON-LD and noscript fallback.
- **Failure scenario:** Visitor clicks once expecting to set an origin, sees "To: <place>" appear instead, clicks again "for a destination" and overwrites it. A journalist quoting the page writes "553 cities".
- **Suggested fix:** Hint → "Click anywhere on the chart to set a destination; the route from the departure city appears below the legend. To depart from somewhere else, click a city name on the chart or pick one above." Derive the city count at build time (the pipeline already writes `index.json`) or read it at runtime into the hint (`meta.origins.length`); keep static meta tags honest until the 553 build actually ships.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-7 — `--text-3` (#6f757e) fails AA on every surface it is used on, and drops to 2.0:1 on the readout scrim over bright bands
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence (WCAG relative-luminance contrast, computed from the hex values read from the DOM):** `#6f757e` on `--surface #131519` → **3.94:1**; on `--bg #0a0b0d` → 4.24:1; on the `.reading` scrim (`color-mix(bg 74%, transparent)`) composited over band 0 `#faefc5` → backdrop `#48463d` → **2.04:1**; over a mid band `#cf6a6a` → `#3d2425` → 3.06:1; over sea → 4.13:1. Elements using it (computed `color: #6f757e`): `.scale span` 10px, `.legend-cap` 10.5px, `.leg .t` (the leg DURATIONS) 12.5px, `.here` 11px, `.results .coord` 10.5px, `.hint` 10.5px, unselected `#ramps button` names, `#q::placeholder`, `#key .src` 10px, `.addresses .head` 11px. For comparison `--text-2 #a4a9b2` is 7.74:1 on surface and 4.01:1 on the scrim over cream.
- **Where:** `web/index.html:85` (`--text-3`), `:132` (`.reading` scrim 74 %), `:147-151`, `:160`, `:186`, `:193`, `:236-237`, `:248`, `:272`.
- **Why it is a problem:** WCAG 1.4.3 requires 4.5:1 for text under ~18.7px; the legend's own numbers and the route's durations — data, not decoration — are below it everywhere and near-illegible when the globe under the readout is bright (the initial Seoul view puts bright bands under the bottom-left corner as you pan).
- **Failure scenario:** On a laptop in daylight the legend ticks (10px, 3.9:1) and the leg durations vanish; a low-vision user cannot read the scale at all.
- **Suggested fix:** `--text-3: #858b94` (measured **5.32:1** on surface, 4.1:1 on an 86 % scrim over cream) and raise the `.reading`/`.mast` scrim to `color-mix(in srgb, var(--bg) 86%, transparent)` (the `.tip` already uses 86 %). Keep `--text-2` for the leg durations (`.leg .t{color:var(--text-2)}`) since they are data. Bump `.scale span` to 10.5px.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-8 — Focus is invisible on the search box; `.ap`/`.mode` and origin labels remove the outline
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `focus #q` → `document.activeElement.id === "q"`, computed `outlineStyle: none`, `borderColor #343941` (unfocused `#282c33`): the only focus change is a border going from 1.21:1 to 1.45:1 against `--surface-2` — a **1.21:1** difference between states. `focus "#legs .ap"` → `outlineStyle: none` (tooltip appears as the only cue). `focus ".lbl.origin"` → `outlineStyle: none`, `textDecorationLine: underline` (underline only). Result buttons and ramp buttons keep the UA `outline: auto 1px` (fine).
- **Where:** `web/index.html:189` (`outline:none`), `:191` (`#q:focus{border-color:var(--line-2)}`), `:245` (`.ap:focus,.mode:focus{outline:none}`), `:231`.
- **Why it is a problem:** WCAG 2.4.7 / 2.4.11: the focus indicator must be visible and at least 3:1 against the unfocused state. Keyboard users cannot tell whether the search box has focus.
- **Suggested fix:** `#q:focus-visible{border-color:var(--accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 35%,transparent)}` (accent `#e48f35` is 7.2:1 on surface); `.ap:focus-visible,.mode:focus-visible{outline:1px solid var(--accent);outline-offset:2px}`; `.lbl.origin:focus-visible{outline:1px solid var(--accent);outline-offset:1px}` in addition to the underline. Use `:focus-visible` so mouse clicks stay clean.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-9 — On phones, tapping the chart while the sheet is folded opens the Route panel inside the hidden sheet (nothing visible happens), and folding hides the legend
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (mouse click at 390x844; touch tap Needs manual validation on a device)
- **Evidence (390x844):** click `#sheet-toggle` → `.rail.folded`, rail height **23 px**, `#tints` `offsetParent` null (legend hidden), `#time` hidden. Dispatch a click on the canvas → `#route.open === true` but `#route` `offsetParent` null (`routeVisible:false`, `pinsVisible:false`), `.rail` still `folded`. Cause: `map.on("click")` sets `$("route").open = true` (`app.js:694`) but never clears `folded`; `.rail.folded > :not(.sheet-toggle){display:none}` (`index.html:316`). Unfolded, the route block is visible (`legsBox top 589, h 169`, rail 439 px tall, globe keeps 405 px).
- **Where:** `web/app.js:689-698`, `web/app.js:936-948`, `web/index.html:310-317`.
- **Why it is a problem:** The only feedback for a tap in the folded state is a faint hexagon outline; the readout the sheet is supposed to carry (`.tip{display:none}` on small screens, `index.html:288`, "the sheet readout carries the value") is hidden. Also, while folded, the always-visible legend is not visible — a CLAUDE.md policy tension.
- **Failure scenario:** Phone user folds the sheet to see the globe, taps Japan, sees nothing, taps again, gives up.
- **Suggested fix:** In the click handler, `document.querySelector(".rail").classList.remove("folded")` and sync `aria-expanded`; keep the 9 px `.tints` strip visible inside the folded handle (move the `#tints` node into `.sheet-toggle` while folded, or draw a 4 px copy) so the legend never disappears. Also note that on a real touch device the big readout `#time`/`#where` is only written by `mousemove` (`app.js:611-639`); the `click` path never writes it — validate on a device that a tap updates the big number (the pins row does show "Time 5 h 03m", so the value is present, but not in the readout).
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-10 — Unreachable land is painted a grey the legend never explains
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence:** At the opening Seoul view `queryRenderedFeatures({layers:["bands"]})` → 53 features, **4 with `band === -1`** painted `UNCHARTED #4a4d50` (`app.js:17`, `bandColorExpression` `:368-372`). `#tints` contains only the 37 ramp slivers; `.legend-cap` = "Hours from the departure city, door to door." No swatch, no word for grey. Contrast of `#4a4d50` against the muted sea `#171a22` is 2.04:1 and against the last band `#3a2c4b` 1.5:1 — it is visually a "far end of the scale" tone unless labelled. Hovering does say "∞ no route" / "no scheduled route" (`app.js:446`, `:590`), but only on hover.
- **Where:** `web/index.html:340-344`, `web/app.js:17`.
- **Why it is a problem:** Colour-only encoding without a legend entry (WCAG 1.4.1) and a first-run comprehension gap: is grey "very far" or "no data"?
- **Suggested fix:** Add one line under the legend: a 9×14 px swatch of `#4a4d50` followed by "No scheduled route" in `.legend-cap` style; keep the swatch colour in one constant shared with `UNCHARTED`.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-11 — Route detail is thinner than the code intends: mode tooltips never render (no `modeDetail` in `index.json`) and rail station naming 404s on every origin
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence:** After clicking Beijing from Seoul, `#legs` = "1 h 25m To GMP, and through the airport | 2 h 32m Fly GMP → PEK | 1 h 06m Onward from PEK, of which: | 51 min by highway | 5 h 03m Door to door"; `#legs .ap` count 4 (tooltips "Seoul Gimpo International Airport, KR"…), `#legs .mode` count **0**. `dist/index.json` has no `modeDetail` key (live `index.json` neither), so `mode()` (`app.js:508-511`) returns the bare word — "highway", "major road", "track" are bold but carry no dotted underline and no explanation; the affordance is inconsistent next to the airport codes. `origins/<slug>.rail.bin` and `.rail.json` → **404** for every origin (2 per switch; 0 of 157 origins have them in `dist/origins`), so `railVia()` (`app.js:646-653`) never adds "via <station> (<line>)". `scripts/browser_verify.sh` requires `"mode":[1-9]` — it would fail against this dist.
- **Where:** `web/app.js:396-401`, `:508-511`, `:646-653`; pipeline side (`index.json` emitter) out of this review's scope.
- **Why it is a problem:** The brief asks for more detail; the UI already has the slots for it (mode explanations, rail station/line) and they are empty, and the 404s show as red in every visitor's devtools.
- **Suggested fix:** (a) Emit `modeDetail` in `index.json` (one sentence per mode: what "highway"/"major road"/"minor road"/"track" mean in the road model, that "rail" is OSM route relations at published speeds, that "ferry" includes waiting) — or, until the emitter does, ship a `MODE_FALLBACK` object in `app.js` so the tooltips exist now. (b) Only fetch `.rail.*` when `index.json` advertises them (`meta.railDetail === true`) to remove the two 404s per origin. (c) The 1 h 06 m "onward" of which 51 min is "by highway" leaves 15 min unexplained — add the airport-egress row ("through the airport, 15 min") so the legs sum visibly to the total.
- **Effort:** S (a-fallback, b, c) / M (a-emitter) · **Fits this cycle's brief:** yes

### UX-12 — Empty and failed search states are silent
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (empty state); Nominatim failure Confirmed by code, not reproducible in this harness
- **Evidence:** `fill #q "zzzzq"` → `.results button` count 0, `#results.innerHTML === ""`, the panel body collapses to 87 px with no text. `render()` (`app.js:728-770`) has no empty branch; `searchAddress` returns silently on network error (`app.js:792 catch { return; }`) and on zero hits (`:797`); `reverseGeocode` likewise (`:841`). (An `agent-browser network route --abort` on the Nominatim host did not take effect in this session — both glob syntaxes tried — so the failure UI was reviewed from code only.) The address search also has a 900 ms debounce plus network latency with no "searching…" cue, so for 1–2 s a typed street name shows an empty list.
- **Where:** `web/app.js:728-770`, `:778-822`, `:826-842`.
- **Why it is a problem:** "Nothing" is indistinguishable from "still loading", "no such city", and "offline".
- **Suggested fix:** In `render()`, when `hits.length === 0 && apHits.length === 0` insert a `.here`-styled `<li>` "No charted city or airport matches “zzzzq”. Searching addresses…" (when `q.length >= 4`) and let `searchAddress` replace it with "No address found" or "Address search is unavailable right now (OpenStreetMap Nominatim)". Also change the placeholder (`index.html:365`) to "City, airport code or address…" so the dual behaviour is explained before the first result appears.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-13 — No `color-scheme: dark`: native controls and scrollbars render light on the dark page
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `getComputedStyle(document.documentElement).colorScheme` → `"normal"`. `:root` (`index.html:82-87`) declares no `color-scheme`; only `accent-color` on the two checkboxes (`:199`) and `scrollbar-color` on `.rail`/`.results`/`.legs` (Firefox-syntax `scrollbar-width/scrollbar-color`, honoured by Chromium 121+ but not older Safari) mitigate it. The `type=search` input's native clear (×) glyph, `<details>` marker fallback, and any UA-styled scrollbar in `.rail` therefore use the light palette.
- **Where:** `web/index.html:82-87`.
- **Suggested fix:** `:root{color-scheme:dark}` plus `<meta name="color-scheme" content="dark">` in `<head>`. One line each; also makes the Chrome autofill/clear affordances match the theme.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-14 — No `prefers-reduced-motion` handling: every origin change, address pick and geolocation answer is a 1–3 s `flyTo` arc
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed by code (browser emulation of the media query did not take effect in this harness: `set media reduced-motion` → `matchMedia("(prefers-reduced-motion: reduce)").matches === false`)
- **Evidence:** `grep -n prefers-reduced-motion web/index.html web/app.js` → no matches. `flyTo` at `app.js:433` (`speed 0.75, curve 1.5`), `:848`, `:858`, `:994`; `easeTo` `:875`. After clicking "Tokyo" the map was still `isMoving()` 600 ms later.
- **Where:** `web/app.js:433`, `:848`, `:858`, `:875`, `:994`.
- **Why it is a problem:** WCAG 2.3.3; the globe's `flyTo` arc is a large full-screen motion that vestibular-sensitive users opt out of at OS level, and the page ignores the opt-out.
- **Suggested fix:** `const REDUCE = matchMedia("(prefers-reduced-motion: reduce)"); const go = (o) => REDUCE.matches ? map.jumpTo(o) : map.flyTo(o);` and route the five calls through it (`easeTo` → `duration: 0`). Also cap `atmosphere-blend` changes if any animate.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-15 — Two blocks headed "Route" with different content are on screen at once, and the time is shown three times
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Evidence:** With a destination set, the rail's `#route` panel (summary text "Route", `index.html:371`) shows "From / To / Time / Depart from Osaka / Clear", and the readout's `#legs` renders an `<h2>` "Route" (`app.js:559-560`) with the leg list. The time appears in `#time` (big), in the pins row ("Time 3 h 10m") and as the "Door to door" total. On the 390x844 sheet the legs block ("Route") sits directly above the "Route" summary.
- **Where:** `web/index.html:370-379`, `web/app.js:556-561`, `:655-672`.
- **Suggested fix:** Rename the legs heading to "Itinerary" (or "How the time is made up") and drop the "Time" row from the pins (the big readout and the itinerary total already carry it); keep "Depart from X" and "Clear" where they are. Optionally move the "Clear" and "Depart from" buttons into the itinerary block so a destination is managed in one place.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-16 — "Door to door" is asserted but explained only inside a closed panel; the departure city is named far from the legend
- **Severity:** Low · **Confidence:** Medium · **Status:** Confirmed
- **Evidence:** The phrase appears in `.legend-cap` ("Hours from the departure city, door to door.") and in the legs total; the explanation lives in `#key` (`index.html:403-414`), which is closed by default on every viewport (`details` states after load: `key:false`). The departure city's name is visible only in the rail summary ("Departure Seoul") 700 px away from the legend; the mast subtitle never says from where. The readout's hover line does say "· from Seoul" (good).
- **Where:** `web/index.html:331-334`, `:343`, `:403-414`.
- **Suggested fix:** Make the legend caption dynamic and self-explaining: "Hours from **Seoul**, door to door — includes getting to the airport, check-in, connections and the last mile" (second clause in `--text-3`, or as `title=` on the phrase). Update it in `paintOrigin`. This puts the answer to "from where?" and "what does door to door mean?" in the one element that is always visible.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-17 — Startup serialises map creation behind a 726 KB fetch, and a first load is 45 requests / 8.4 MB (2.1 MB per origin switch)
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Evidence (Resource Timing, local, uncompressed):** `index.json` 12 KB → `hover_cells.bin` 725,572 B (both `await`ed at top level, `app.js:27` and `:38-40`) BEFORE `new maplibregl.Map` (`:252`), then `await map.on("load")` (`:267`) before `paintOrigin` (`:981`). Then in parallel: `places.json` 1,778,347 B, `borders.json` 1,278,886 B, `airports.json` 259,222 B, `seoul.json` 497,578 B, `seoul.modes.bin` 1,088,208 B, `seoul.bin` 181,618 B, `seoul.air.bin` 181,618 B, `maplibre-gl.js` 1,054,110 B, `h3.js` 192,740 B, `app.js` 43,589 B. Total 8,384,673 B over 45 requests. Live nginx serves all of these with `content-encoding: gzip` and `cache-control: no-cache` (revalidates every visit). Locally DCL 91 ms / load 505 ms; on a 4G link the two serialised fetches cost roughly 0.5–1 s before the first frame can start.
- **Where:** `web/app.js:27`, `:38-40`, `:252-267`; `web/index.html:72-73` (preloads, which do help).
- **Suggested fix (S):** Start the `hover_cells.bin` fetch without awaiting, create the map, and `await` the buffer just before the first `lookup()` (guard `lookup` on `hoverCells`). Consider lazy-loading `places.json` after the first origin paints (labels and hover naming can appear a second later). The per-origin 2.1 MB (`modes.bin` at 1.09 MB is six Uint16 per cell) is a pipeline question — a `Uint8` minute-bucket or only fetching `.modes.bin` on first click would halve it — outside this brief.
- **Effort:** S (reorder) / M (lazy places, smaller modes) · **Fits this cycle's brief:** partially (reorder only)

### UX-18 — ARIA: `#map` is `role="img"` yet contains a focusable region and up to 157 buttons; no live region for the route; ramp picker and results lack widget semantics
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `#map` has `role="img" aria-label="Interactive globe…"` (`index.html:329`); the accessibility snapshot lists inside it `region "Map" focusable [tabindex]` (MapLibre's canvas, `tabindex="0"`) and, when zoomed, `button "Seoul"` etc. (`#map button` count 11 at z4.6). Children of `role="img"` are presentational by spec. `#time`, `#where`, `#pins`, `#legs` all have `aria-live === null`. `#ramps` has no `role`, its buttons use `aria-current` (`app.js:897`) rather than `aria-pressed`/`radio`; `#q` has no `aria-expanded`/`aria-controls`, `#results` no `role` (all `null`).
- **Where:** `web/index.html:329`, `:336-347`, `:365-366`, `:396`; `web/app.js:893-908`.
- **Suggested fix:** `#map` → `role="application" aria-roledescription="globe"` (or drop the role and let MapLibre's region carry it); `#pins` and `#legs` → `aria-live="polite"`; `#ramps` → `role="radiogroup"` with `role="radio" aria-checked`; combobox/listbox on the search (see UX-4). Origin-label buttons should be `tabindex="-1"` (reachable by click and from the list) so they do not precede the whole UI in the Tab order (Tab 2–4 after load at z4.6 landed on three label buttons before the compass).
- **Effort:** S · **Fits this cycle's brief:** yes (bundle with UX-4)

### UX-19 — The only disclaimer is inside `<noscript>`; the visible page has none (dead `.disclaimer` CSS)
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `document.querySelector(".disclaimer")` → null; no visible element contains "For reference only" (`[...p,div].some(e => e.offsetParent && innerText.includes(...))` → false), while `document.body.textContent.includes("For reference only")` → true only because `<noscript>` text (`index.html:425-426`) is in `textContent` — which is what `scripts/browser_verify.sh` checks, so that check is vacuous. CSS `#key .disclaimer{…}` (`index.html:273-274`) styles nothing.
- **Where:** `web/index.html:273-274`, `:403-414`, `:425-426`.
- **Suggested fix:** Add `<p class="disclaimer"><b>For reference only.</b> Estimates from a simplified model; no warranty of accuracy.</p>` at the end of `#key .body` (the CSS is already there), and make the verify script check `offsetParent`.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-20 — Only the `latin` Plex subset is shipped; 25 of the 900 label-pool names and 3,569 of 34,135 gazetteer names contain glyphs outside it
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed (latent until UX-2 is fixed)
- **Evidence:** `web/vendor/fonts.css` declares three faces all pointing at `ibm-plex-sans-latin-*.woff2` with no `unicode-range` and no `latin-ext`/`vietnamese` files. Checking every gazetteer name against Fontsource's `latin` unicode-range: 3,569 names fall outside, 25 in the top-900 label pool ("İzmir", "Thāne", "Rājkot", "Cần Thơ", "Huế", "Kalyān", "Ra’s Bayrūt", "Ghāziābād"…). All 157 origin names are covered. Today this is masked because labels are in Helvetica (UX-2); once they are in Plex, "Th**ā**ne" renders with one system-font glyph.
- **Where:** `web/vendor/fonts.css`, `web/index.html:74-75`.
- **Suggested fix:** Add the `latin-ext` (and `vietnamese`) subsets for weights 400/500 with proper `unicode-range` descriptors (~30 KB each, loaded only when a glyph needs them). No CDN — vendor them as the others are.
- **Effort:** S · **Fits this cycle's brief:** yes (with UX-2)

### UX-21 — Airport-code and mode tooltips can be clipped by the scrolling `#legs` box
- **Severity:** Low · **Confidence:** Medium · **Status:** Likely (measured margin 3 px)
- **Evidence:** `.legs{overflow-y:auto}` (`index.html:154-156`) → computed `overflowX: auto` too, so the box clips. Hovering the first `.ap` (GMP): `::after` height 32.19 px, `min-width 180px`, positioned `bottom: calc(100% + 5px)` → tooltip top **605 px vs `#legs` top 602 px** (3 px clear). A three-line name ("Bandaranaike International Airport, Colombo, LK" at 180 px wraps to 3 lines ≈ 46 px) would be cut at the top; a code near the right edge overflows `#legs` right (tooltip right measured 293 vs box right 304 — 11 px spare only for a short name).
- **Where:** `web/index.html:154-156`, `:239-244`.
- **Suggested fix:** Give `.legs` `overflow:visible` and cap its height with a wrapper, or `padding-top:56px; margin-top:-46px` trick; simpler: render the tooltip below the code (`top:calc(100% + 5px)`) for the first two rows via `:nth-child(-n+3) .ap::after`, and add `right:0;left:auto` for `.ap:last-child`.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-22 — Target sizes: city rows 23 px, scheme rows 23 px, sheet handle 22 px, checkboxes 15 px
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Evidence:** `get box` → `.results button` height **23** px (`padding:4px 0`, `index.html:182`), `#ramps button` **23** px (`:208`), `#sheet-toggle` **22** px (`:311-313`), `#lock-north` 15×15 (`:199`; its `<label for>` is clickable, so the effective target is the 234×31 row — acceptable). Rows are stacked with no gap, so the WCAG 2.5.8 "spacing" exception (24 px circles must not intersect) narrowly fails for the two lists.
- **Where:** `web/index.html:182`, `:208`, `:311-315`.
- **Suggested fix:** `padding:5px 0` on `.results button` (→25 px) and `padding:4px 3px` on `.ramps button`; make the sheet handle 28 px with the bar centred.
- **Effort:** S · **Fits this cycle's brief:** yes

### UX-23 — Seven unlabelled `console.error("Error")` entries on a clean load, five per origin switch
- **Severity:** Low · **Confidence:** Low · **Status:** Needs manual validation
- **Evidence:** `agent-browser console` after a clean reload at 1280x800: 7 × `[error] Error` (JSON: `{"text":"Error","type":"error"}` — empty message). After switching to Paris: 5 more. A `map.on("error")` listener installed before the switch captured **0** events, so they are not MapLibre error events. The only 4xx resources are `origins/<slug>.rail.bin`/`.rail.json` (2 per origin, UX-11). The count roughly tracks the number of per-origin fetches; the most likely source is the PMTiles protocol rejecting aborted range requests during `flyTo`, logged via `console.error(err)` by the pmtiles/maplibre glue, but I could not confirm the origin from the harness.
- **Where:** unknown (not in `app.js` — its only `console.error` is `app.js:409` with a message).
- **Suggested fix:** Reproduce in DevTools with "Preserve log", read the stack; if they are `AbortError`s from cancelled tiles, filter them in the `pmtiles` protocol wrapper. `browser_verify.sh` counts `error` lines and would fail on this.
- **Effort:** S · **Fits this cycle's brief:** partially

---

## Final sweep

**Keyboard-only pass (1280x800).** Tab 1 → MapLibre canvas (`region "Map"`, `tabindex=0`); ArrowRight pans (centre lng 130 → 132.9) — works. With labels on screen, Tabs 2–4 land on origin-label buttons inside `#map` before anything else. Then `#compass` (UA outline), `#departure summary`, `#q` (no visible focus — UX-8), 157 result buttons (UA outline, fine), `#route summary`, `#clear-pins`, `#settings summary`, two checkboxes, 12 scheme buttons, `#key summary`. Enter on a summary toggles it (native). Enter in `#q`: no-op (UX-4). ArrowDown in `#q`: no-op. Escape in `#q`: clears (native). Escape elsewhere: no handler (none needed for `<details>`, but there is no way to dismiss the route summary from the keyboard other than tabbing to "Clear"). `.ap` focus shows the tooltip but no ring (UX-8).

**Viewports.** All four: canvas present, no horizontal scroll, no overlap between `.mast`, `.rail`, `#compass`; `#time` and `#tints` visible; measured boxes:
- 1280x800: `.mast` (14,14,269×80), `.reading` (14,602,306×184; 367 tall with a route), `.rail` (996,20,264×760 — scrolls 853/760 with Departure+Route open), `#compass` (938,734,46×46), `#tints` 274×9 (37 × 7.4 px slivers).
- 820x1180: bottom sheet `.rail` (0,850,820×330), `.reading` inside the sheet (parent `.rail`), handle 22 px, all four `<details>` closed, `.tip` `display:none`, globe keeps 850 px.
- 390x844: sheet (0,496,390×348), `.mast` 185×32, `#compass` 38×38 at (342,10), `#time` 34 px; folded → 23 px handle only (legend hidden, UX-9); with a route the sheet is 439 px and scrollable, `#legs` 169 px.
- 844x390: right rail 300 px (l=544) full height, `.reading` 158 px inside it, `#compass` at (496,10) clear of the rail; with Departure open the rail scrolls 536/390 and `#results` is capped at 101 px (~4 rows) — usable but cramped.
- Text overflow scan (`scrollWidth > clientWidth` on `.mast, summary, .pins .val, .reading .at, .legend-cap, .results button, .leg .d, #here`): only `.leg .d` while an `.ap` tooltip is hovered (the absolute `::after`), no real overflow. Long names ("Bandar Seri Begawan", "Washington, D.C.", "Gangnam-daero, Dogok-dong, Dogok 1(il)-dong") wrap correctly.

**`prefers-reduced-motion`.** Not honoured anywhere (UX-14). Emulation via `agent-browser set media` did not apply in this harness (`matchMedia` stayed false), so this is a code finding.

**Console / errors.** `errors` (uncaught): none. `console`: 7 × "Error" on load, 5 per origin switch (UX-23). No MapLibre `error` events.

**404s.** Exactly two per origin: `origins/<slug>.rail.bin`, `origins/<slug>.rail.json` (300-byte 404 bodies; 4 after two switches) — UX-11. No other 4xx (`performance.getEntriesByType("resource")` filtered by `responseStatus >= 400`).

**Typography policy (computed).** `letter-spacing: normal`, `text-transform: none`, `font-variant-numeric: normal` on `.mast h1`, `summary`, `#time`, `.scale span`, `.legend-cap`, `.rowlabel`. `#time` asks for weight 300 which is not vendored (400/500/600) — renders at 400; harmless, dead value. Typeface violations: UX-1, UX-2.

**Colour ramps.** `python3 scripts/check_ramps.py` → all 12 OK (min anchor ΔE 6.5–8.9; L monotonic 0.95–0.97 → 0.26–0.33; sea L 0.20–0.22). Legend paints 37 spans from the same interpolation; switching to "Vivid" recoloured `#tints`, `bands` and `sphere` (`#15122c`) and persisted `localStorage.ramp` — works.

**States exercised.** Initial (Seoul, geolocation denied → "Location unavailable — showing Seoul."); hover on land ("5h 03m", "Beijing — China / 39.96°N 116.36°E · 4.3–5 h · from Seoul", `.tip` "5 h 03m Beijing, China" at (602,395) 139×30); hover on ocean ("—", "Open water.", tip hidden); click on land (Route panel opens, pins "From Seoul / To Beitaipingzhuang, Haidian District, China / Time 5 h 03m / Depart from Beijing"; legs with 4 airport tooltips, 0 mode tooltips); origin switch via list (Tokyo, London, Paris — data ready in 12–31 ms locally, tiles by 260 ms); click-to-depart button; city search ("tokyo" → 3 rows), airport code ("jfk" → "JFK John F. Kennedy International Airport | US · destination"), empty query ("zzzzq" → nothing), address search ("Gangnam-daero, Seoul" → 6 Nominatim rows, "Addresses" header 11px `#6f757e`, credit line) and address pick (flyTo z8, legs "15 min by highway / 15 min Door to door"); Clear; scheme switch; Sources panel (credits string correct, 7 sources with licences); sheet fold/unfold on phone; landscape rail scroll.

**Not exercised / needs a device.** Real touch tap (whether the big readout updates on tap — `#time` is only written in `mousemove`); geolocation-granted path; a missing-origin `.bin` error state (code shows "Hover data unavailable for X."); Nominatim outage (harness could not block the host); Safari/Firefox rendering of `color-mix`, `backdrop-filter`, `scrollbar-color`.

## Coverage

| Area | Covered | Evidence type |
|---|---|---|
| Information architecture / first-run copy | yes | DOM text, label counts, screenshots |
| Click-to-depart affordance | yes | `.lbl` counts at z1.9/z4.6, computed label styles, `title` attrs |
| Search (city / airport / address) | yes | result rows, Nominatim rows, Enter/Escape/Arrow behaviour |
| Legend (visibility, ticks vs `bandEdgesMin`, 12 schemes) | yes | tick `left%` vs edges, tick boxes, `#tints` widths, ramp script |
| Route summary (`#legs`, `.ap`/`.mode` tooltips, door-to-door) | yes | innerText, tooltip counts, `::after` metrics |
| Unreachable / ocean / loading / error states | partial | rendered-feature bands, "Open water.", code paths for errors |
| Keyboard, focus, ARIA | yes | activeElement traces, computed outlines, snapshot roles |
| WCAG contrast / targets / motion | yes | computed hex + ratios, boxes, grep + `isMoving()` |
| Responsive (4 viewports, fold, landscape) | yes | boxes, overlap tests, screenshots |
| i18n (non-Latin names, long names) | yes | unicode-range scan of `places.json`, overflow scan |
| Perceived performance | yes | Resource Timing, top-level await order, live gzip headers |
| Dark-theme consistency | yes | `colorScheme` computed, `accent-color`, scrollbar rules |
| Typography policy | yes | computed `font-family`/`letter-spacing`/`text-transform`/`font-variant-numeric` |
| Live-site comparison | yes | `curl` of live `index.html`, `app.js`, `index.json`, headers |

## Browser cleanup performed

- `agent-browser --session c1design close` → "Browser closed".
- `agent-browser session list` afterwards → one remaining session, `cycle26`, which belongs to another agent. Per the rules I therefore did **not** kill the agent-browser daemon or its Chrome tree, and did not touch Google Chrome.
- No process was started or stopped other than my own `c1design` browser page. The local preview server on `127.0.0.1:8899` was left running.
- Screenshots (attachments, not evidence): `design_desktop_1280x800.png`, `design_labels_z46.png`, `design_tablet_820x1180.png`, `design_mobile_390x844.png`, `design_mobile_folded.png`, `design_mobile_route.png`, `design_landscape_844x390.png`, `design_landscape_departure_open.png` under the scratchpad directory named at the top.
