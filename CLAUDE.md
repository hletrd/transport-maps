# transport-maps

Global travel-time isochrone map. Python pipeline builds PMTiles + binary time
arrays; a static page renders them on a globe.

## Design policy (standing — do not revisit without being asked)

- **Typeface: IBM Plex Sans.** Sans-serif throughout, self-hosted in
  `web/vendor/`. No serif faces, no webfont CDN (the CSP blocks external font
  hosts, and a face that silently falls back undoes the choice).
- **`letter-spacing` stays at its default everywhere.** Do not set it — not on
  headings, not on labels, not on small caps. If a label looks cramped, change
  size or weight instead.
- **No `text-transform: uppercase`.** Small all-caps micro-labels ("DEPARTURE",
  "ROUTE") are the generic-dashboard tell. Use sentence case and carry the
  hierarchy with weight and colour.
- **No `font-variant-numeric: tabular-nums`.** Monospaced digits read as a
  terminal, not a chart. Plex Sans' proportional figures suit the prose; if a
  column needs aligning, set a width.
- **Dark theme.** Near-black ground (`--bg`), not a light or sepia palette.
- **Band colours must be measurably separable.** Adjacent bands need OKLab ΔE
  of roughly 8; below that they read as one mass. A single hue cannot achieve
  it across eleven bands on a dark ground — rotate hue as well as lightness,
  and keep lightness strictly monotonic. Measure it, do not eyeball it.
- **The legend is always visible**, never folded into a panel, and its ticks sit
  at their true band boundaries — the bands are equal width but the time scale
  is not linear, so evenly spaced labels would misstate the scale.

## Modelling rules

- Time is **door to door**, not gate to gate: ground access, check-in, border
  control where a zone is crossed, and the journey out of the arrival airport
  are all in the number. Say so wherever a figure is presented.
- Calibration constants live in `calibration.toml` and each carries a comment
  saying whether it is **fitted** (and against what) or a **published-figure
  default**. Never silently tune a default to match a handful of hand-picked
  routes: prefer a documented, reproducible error over a hidden one. See
  `scripts/ground_check.py` for the pattern.

## Testing rules

- A test that passes when the code is deliberately broken is worse than none.
  After adding a guard, **mutate the code and confirm the test goes red**. This
  repository has shipped several vacuous tests (cache-warm fixtures, stubs that
  outlive a signature change); assume a new test is vacuous until shown otherwise.
- Derived caches key on `_params_hash` of the constants **and inputs** that
  govern them, never on a bare `.exists()`.

## Deploy rules

- **No deploy is done until it has been opened in a browser.** Twice in this
  project a deploy went out unverified and the live site was blank: once from
  mismatched cached assets, once from a module-load ordering error that threw
  before the map was created -- with no console error visible after the fact.
  `curl` returning 200 proves nothing about whether the page runs. After every
  deploy: open it, confirm the canvas exists and the city list is populated,
  and check the console. For layout changes, check 1280x800, 820x1180,
  390x844 and 844x390.
- **Close browser sessions and kill agent-browser's own Chrome tree afterwards**
  (`~/.agent-browser/browsers/`), never the user's Google Chrome. `agent-browser
  close` ends the page but leaves the daemon and browser running.
- **Never deploy a partial `dist/`.** The per-origin arrays and `hover_cells.bin`
  must come from the same build; mixing them renders a blank globe with no error.
