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
- **Band colours must be measurably separable.** Each scheme is eleven
  anchors interpolated to the 37 bands; adjacent ANCHORS need OKLab ΔE of at
  least 6 (eleven anchors from near-white to near-black span about 70, so ~7
  per step is the ceiling), lightness strictly monotonic, and the scheme's sea
  colour between space and its darkest band. `scripts/check_ramps.py`
  measures all of it and `tests/web/test_ramps.py` enforces it; `--respace`
  re-samples a ramp evenly along its own path. Measure it, do not eyeball it.
- **Hexagons are drawn as hexagons.** No corner rounding: it moved every band
  boundary differently per polygon and opened gaps. The margins that keep
  bands overlapping are counted in whole cells (`contour/bands.py` LODS).
- **H3 cells are not regular hexagons, and that is not a bug to fix.** A
  sphere cannot be tiled with regular hexagons: H3 lays them on an
  icosahedron's twenty faces and projects back, so cells are squashed near a
  face edge. Measured: median longest/shortest edge 1.04 worldwide, worst
  1.17, and Seoul sits near that worst case at 1.15 with interior angles from
  110° to 126°. Rendering adds almost nothing (34.5% of corners depart from
  ±60° in raw H3, 36.7% after tiling). Do NOT try to regularise them: moving a
  vertex breaks the edge it shares with its neighbour and reopens the holes
  between bands, which is the same failure corner-rounding caused. Higher
  resolution does not change the ratio, only the absolute error (1,343 m at
  res 5, 454 m at res 6, 190 m at res 7).
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
- **`dist/water.pmtiles` is static and not produced by `build-all`.** It is the
  coastline drawn above the bands (`scripts/build_water_tiles.py`). Without it
  the page shows no error -- the shore just goes back to being hex-shaped one
  cell out to sea. `deploy_verify.sh` refuses to deploy without it and
  `browser_verify.sh` asks the map whether water features actually rendered.
