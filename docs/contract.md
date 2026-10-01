# Pipeline and page contract

**Status:** partial. This file is where `plan/2026-09-10-c2-docs-attribution-calibration.md`
task J1 puts the whole pipeline-to-page contract: the file set, the
`index.json` schema, the binary layouts and the PMTiles layers. That work is
still open. So far the file holds only the two rules task S6 asked to be
written down, because they are the ones a reader of either half cannot see
from that half alone.

## Rules that cross the layer boundary

The design spec says "the frontend never learns how the numbers were made; the
pipeline never learns how they are drawn". Both halves of that sentence are
false, and on purpose. Each rule below couples the two layers. Changing one
side alone breaks the page without an error anywhere.

### 1. The page prints the pipeline's account of how a time was made

- `emit/index.py:mode_detail()` writes `modeDetail` into `index.json`: one
  sentence per surface mode, with the speeds read from the same calibration
  objects the graph uses (`graph/ground.py`, `graph/rail.py`,
  `graph/ferry.py`, `sources/urban.py`).
- The page shows that sentence verbatim as the tooltip on each mode name in
  the itinerary (`web/app.js`, `mode()` inside `renderLegsInto()`). It uses
  its own `MODE_FALLBACK` only for an `index.json` older than the field.
- The keys are the mode names themselves: `emit/modes.py:CHANNELS` (`rail`,
  `ferry`, `highway`, `major road`, `minor road`, `track`), which the page
  reads as `modeChannels` (`MODE_NAMES` in `web/app.js`). If a channel is
  renamed on one side only, the tooltip disappears and the mode name is
  printed bare.
- So a calibration constant is visitor-facing text. Each sentence must say
  whether its speed is fitted or a published-figure default, which is
  CLAUDE.md's calibration rule applied to the page.
  `tests/test_calibration_provenance.py::test_every_speed_in_the_mode_tooltips_says_which_it_is`
  enforces it.
- The prose describes the build the arrays came from, not today's
  `calibration.toml`. `reindex` therefore carries the previous `modeDetail`
  forward instead of re-deriving it
  (`tests/cli/test_reindex.py::test_mode_prose_is_carried_forward_not_resampled`).

### 2. The band geometry is gap-free only under the page's draw order

- `contour/bands.py` emits band *k* as the cumulative region reached within
  its upper edge, minus the cells that sit safely inside band *k-1*. Each band
  polygon therefore covers its own cells plus a one-cell rim of every faster
  band, and neighbouring bands overlap by that rim. That overlap is what makes
  a gap between bands geometrically impossible (see the module docstring and
  the hexagon rules in CLAUDE.md).
- The overlap is correct only if the faster band is painted on top. The page
  does this with the bands layer's `fill-sort-key`, which is `-band`, so a
  faster band has a higher key and draws later. Unreachable land gets -1000
  and goes underneath everything. If that order is reversed or dropped, each
  slower band's rim covers the outer ring of the band inside it, and every
  boundary on the map moves one cell outward. Nothing reports an error.
- The same layer must stay opaque (`fill-opacity: 1`) and not antialiased
  (`fill-antialias: false`). Otherwise the hidden rim shows through, or a
  hairline is drawn along every boundary.
- The bands also run out to sea: `contour/grid.py` adds rings of sea cells,
  more of them for the low-zoom levels (`contour/bands.py` LODS). The page
  inserts the bands layer beneath `water`, so the static `water.pmtiles`
  coastline cuts them back to the shore. Without that layer,
  or with the bands drawn above it, the shore is hex-shaped out at sea
  (CLAUDE.md, deploy rules).
- Guards: `validate.check_bands_cover` checks the pipeline half on the
  emitted geometry. `tests/web/test_app_constants.py` checks that the page's
  bands layer has `fill-sort-key`, `fill-opacity: 1` and
  `fill-antialias: false` and is added before `water`. It checks that the
  sort key is present, but not its sign.
