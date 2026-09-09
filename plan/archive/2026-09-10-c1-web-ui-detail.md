> Archived 2026-09-10 (cycle 2). Every cycle-1 task in this plan is done; every
> unfinished cycle-2/3 task was carried into `plan/2026-09-10-c2-web-ui-detail.md`
> under its original ID (see `.context/reviews/_aggregate.md` for the cycle-2
> evidence). This file is kept for provenance and is not updated further.

# Plan: page detail, ease of use, UI and accessibility

Source findings: `.context/reviews/_aggregate.md` sections C and D, plus E1
(page copy) and the copy half of C2. Per-agent detail: `designer.md` (UX-*),
`critic.md` (CRIT-*), `code-reviewer.md` (CR-*), `tracer.md` (TR-*),
`debugger.md` (DBG-*), `perf-reviewer.md` (PR-*), `verifier.md` (VER-*).

Files: `web/index.html`, `web/app.js`, `web/llms.txt`, `web/vendor/fonts.css`.
Design policy in `CLAUDE.md` is binding for every change here.

Verification for the whole plan: the page must be opened in a browser after
deploy (CLAUDE.md deploy rule) — `scripts/browser_verify.sh` covers the four
viewports; each task lists its own text-extractable check.

## Cycle 1 (this run) — bounded, S-effort, user-visible

- [x] **D1** Fix the four invalid `font: … inherit` shorthands so the search box,
      city list, scheme picker, `.btn` and address results render in IBM Plex
      Sans. `web/index.html:181,189,208,251` → `font-family:inherit; font-weight;
      font-size; line-height` written out. Check: `getComputedStyle(q).fontFamily`
      starts with "IBM Plex Sans".
- [x] **D2** Give globe labels the page typeface and a text shadow: `.lbl` gets
      `font-family:var(--font)` (`index.html:226-231`) and a dark
      `text-shadow`; origin labels keep weight 500. Check: computed
      `fontFamily`/`textShadow` on `.lbl.origin`.
- [x] **D3** Make the opening view show city names: raise the label budget at the
      landing zoom (`app.js:189`) or land `flyTo` at a zoom where the budget is
      non-zero (`app.js:433`). Check: `document.querySelectorAll(".lbl").length > 0`
      after load at 1280×800.
- [x] **D4 + E4 (bounded)** Enter in the search box acts: with a filter typed, Enter
      departs from the first matching city; when the filter matches no city,
      Enter runs the address search. Arrow keys move through the result list.
      Address search moves from search-as-you-type to explicit (Enter or a
      "Search address" button), which also satisfies the Nominatim policy
      (E4). Check: keydown Enter on `#q` changes `map.getSource("bands").url`
      or populates `.addresses`.
- [x] **C4** Legend ticks: place each label on the edge whose value equals the
      round hour exactly when one exists (72 h = 4320 exists), and label the
      others with the true edge value (e.g. "3¾ h" or "225 min" rather than
      "4"); keep enough spacing that "48" and "72+" cannot collide.
      `app.js:129-143`. Check: each `.tick` `data-min` equals a value in
      `meta.bandEdgesMin` and its label equals that value formatted.
- [x] **C6** Add a legend entry for the "no scheduled route" tone (`UNCHARTED`)
      and for open water. `app.js:122-127`, `index.html:340-344`.
- [x] **D5** Rewrite the Route panel instructions to describe the real
      interaction (click a destination; change departure via the list, an
      origin label, or "Depart from here"). `index.html:373-375`.
- [x] **D6** Raise `--text-3` to a value that clears 4.5:1 on `--panel` and
      re-check the readout scrim (`index.html:85,132`). Measure with the
      WCAG formula in the commit message.
- [x] **D7** Visible focus: replace `outline:none` on `#q`, `.ap`, `.mode`,
      `.lbl.origin` with a `:focus-visible` ring (`index.html:189,191,231,245`).
- [x] **D9** Add `color-scheme: dark` on `:root` (`index.html:82-87`).
- [x] **D10** Honour `prefers-reduced-motion: reduce`: `flyTo`/`easeTo` become
      `jumpTo` (or `duration: 0`) at `app.js:433,848,858,875,994`.
- [x] **D18** Stop requesting IBM Plex Sans 300 (`index.html:136`); use 400 with
      a lighter colour or vendor the 300 face. Chosen: weight 400.
- [x] **C7** Distinguish "loading" / "no data for this departure" from "Open
      water." (`app.js:464-468,618-626`).
- [x] **C10** Gate geolocation behind a user gesture (a "Use my location"
      button) instead of prompting on load (`app.js:956-998`).
- [x] **C12** When `index.json` has no `modeDetail` (the shipped 157-origin
      build), fall back to built-in explanations so tooltips still render;
      do not fetch `.rail.bin/.rail.json` when `index.json` does not advertise
      them (`app.js:396-401,508-511,646-653`). Check: `.mode[data-tip]` non-empty
      on the local preview.
- [x] **D14** Show the disclaimer in the visible page (one line under the legend
      or in the about panel head), not only in `<noscript>`
      (`index.html:273-274,425-426`).
- [x] **D12** State "door to door" beside every figure: the readout caption, the
      Route "Time" row, the leg tooltip (`index.html:331-343`, `app.js:556`).
- [x] **E1 (page half)** Derive every visible city count from `meta.origins.length`
      at runtime; make the static meta/JSON-LD copy count-free ("hundreds of
      departure cities") until the 553-origin build ships (`index.html:15,23,31,41-42,375,421`,
      `app.js:722` comment, `llms.txt:3`).
- [x] **C2 (copy half)** Relabel "Onward from X, of which:" to what the numbers
      are (surface travel across the whole journey) until per-leg accounting
      lands (`app.js` route summary).
- [x] **C9** Wrap the two top-level awaits (`index.json`, `hover_cells.bin`) so a
      404, non-JSON body or odd byte length shows a visible message instead
      of a blank globe (`app.js:27,38-40`).

## Cycle 2

- [ ] **C5** Origin-switch generation counter: one `loadOrigin(o)` that awaits all
      per-origin fetches and discards results when `gen !== originGen`
      (`app.js:396-431`). Check: fire two switches back to back with the first
      delayed; the second wins.
- [ ] **D8** Empty and failed search states: "No city or address matches" for the
      local list (`app.js:728-770`). The address half (searching / no address
      found / unavailable) landed in cycle 1 with D4.
- [ ] **D11** One "Route" heading; show the time once (`index.html:370-379`,
      `app.js:556-561,655-672`).
- [ ] **D13 (reorder)** Create the map before `hover_cells.bin` arrives; fetch
      `.modes.bin`/`.json` lazily on first click (`app.js:27,38-40,252-267`).
- [ ] **C13** Phone sheet: tapping the chart while the sheet is folded unfolds it
      (or shows the reading in the always-visible strip); the legend never
      folds away (CLAUDE.md legend rule; `app.js:689-698,932-960`,
      `index.html:310-317`). Check at 390×844: after a tap, `#legs` is visible
      and `#tints` bounding box is on screen with the sheet folded.
- [ ] **D2 (subset)** Vendor the `latin-ext`/`cyrillic`/`greek` Plex subsets so
      non-Latin label names do not fall back (`web/vendor/fonts.css`).
- [ ] **D15** Keep tooltips inside the viewport: flip above/below on overflow
      (`index.html:154-156,239-244`).
- [ ] **D16** Target sizes ≥ 24 px for city rows, scheme rows, sheet handle,
      checkboxes (`index.html:182,208,311-315`).
- [ ] **D19** Terminology pass: one word each for map/chart, departure/origin,
      passage/time; hours everywhere including above 48 h
      (`index.html:333-411`, `app.js:444-451,594`).
- [ ] **D4 (semantics)** `#map` role, listbox/option semantics for results,
      radiogroup for schemes, an `aria-live="polite"` region for the reading
      (`index.html:329,336-347,365-366,396`, `app.js:893-908`).
- [x] **D17** Closed in cycle 2: 0 console entries across load, hover, click, three origin switches and a scheme change (designer); the seven entries were the `.rail.*` 404s C12 removed.

## Cycle 3+

- [ ] **C3** Hover outline and reading from the same cell: ship the split-cell
      set (a sorted uint64 array of split base cells) so the page can outline
      the res-7 cell where the surface was refined; look the time up from the
      res-6/7 cell rather than the res-4 parent's representative child.
      Needs an emitter change and a rebuild (`app.js:34-35,334-342,453-468`,
      `emit/index.py`). Waits for the orchestrator's rebuild.
- [ ] **C1** Route chain through surface transfers between airports: include the
      cell hops (or a "surface transfer" marker) in `routes.json` so `legsTo`
      does not stop at the first cell (`routes_json.py:31-39`, `app.js:473-489`).
      Needs a rebuild.
- [ ] **C2 (accounting)** Per-leg surface minutes in `modes.bin` (onward-only) so
      "of which" is a true breakdown (`modes.py:71`). Needs a rebuild.
- [ ] **C8** One rounding rule for hover, routes and modes minutes
      (`hover.py:67-69`, `routes_json.py:27`, `modes.py:108`). Needs a rebuild.
- [ ] **C11** Filter dropped/isolated airports out of the search; disambiguate
      duplicate picker names with region (`app.js` search).
- [ ] **D20** State one separation threshold in `app.js`, CLAUDE.md and
      `check_ramps.py`, and measure the 37 interpolated bands, not only the
      anchors (`app.js:5-12,90-97`, `scripts/check_ramps.py`).
- [ ] **D13 (lazy)** Smaller per-origin leg data; lazy `places.json`.

## Progress

- 2026-09-10 cycle 1: plan written. Cycle-1 tasks implemented in the cycle-1 commits (see git log for `web/`); each check recorded in the commit body.
- 2026-09-10 cycle 1 done: all twenty cycle-1 tasks shipped in a261141, b7da35f, 1305ba7, d84217f, f943964, e11c830 (web/); verified on the local preview with agent-browser (fonts, ticks, keys, labels, Enter, address search, route tooltips, console clean); **not deployed** (the consistency gate refused mid-rebuild, see the build plan) — the post-deploy `browser_verify.sh` run is still owed. Corrected in cycle 2 (VER-28, DOC-6).
