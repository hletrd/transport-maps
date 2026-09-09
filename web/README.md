# Frontend — `worldmap.atik.kr`

A single static page: a MapLibre globe painting per-origin isochrone bands from
the PMTiles the pipeline emits.

## Self-hosted by design

No script, style or font is fetched from a CDN. MapLibre, PMTiles, h3-js,
fflate and IBM Plex Sans are vendored under `vendor/`, so the deployed site
works behind a strict `script-src 'self'` CSP for its own code. Two runtime
calls do leave the browser, and the CSP in `deploy/` names exactly those:
OpenStreetMap's Nominatim for address search and click-to-address (only on an
explicit search or a click, never per keystroke — its usage policy forbids
autocomplete), and the Google tag for page-view counting.

`vendor/` is generated, not hand-edited. To refresh it, re-download each package
from jsdelivr and rewrite any `/npm/...` imports to local siblings.

## Pinned versions, and why

| package | version | note |
|---|---|---|
| maplibre-gl | **5.24.0** | NOT 6.x — see below |
| pmtiles | 4.5.0 | |
| h3-js | 4.2.1 | |
| fflate | 0.8.3 | transitive dep of pmtiles |

**Do not upgrade MapLibre to 6.x without testing tile loading.** Observed on
6.x: its ESM bundle drops the default export (needs `import * as`), and
pmtiles 4.x's `addProtocol` handler is called once for the source metadata and
then never for tiles, so the map renders an empty globe with no console error.
The root cause of the second symptom has not been isolated; retest tile
loading end to end before any upgrade. MapLibre 5.24 has globe projection and
works correctly.

## Deploy

`scripts/deploy_verify.sh` copies `index.html`, `app.js`, `llms.txt`,
`robots.txt`, `sitemap.xml`, `preview.png` and `vendor/` into the pipeline's
`dist/` (so `index.json`, `hover_cells.bin` and `origins/` are siblings) and
rsyncs that to the server; see `deploy/README.md`.

The server must support HTTP Range requests — PMTiles reads byte ranges, and a
server without them fails with "Check that your storage backend supports HTTP
Byte Serving". nginx does this by default; Python's `http.server` does not.

## Colour schemes

Twelve schemes, each eleven anchor colours interpolated in OKLab to as many
bands as `index.json` declares (37 today). Every scheme rotates hue as well as
lightness: a single hue cannot separate that many bands on a dark ground.
`scripts/check_ramps.py` measures each scheme — adjacent anchors must be at
least 6 apart in OKLab ΔE (×100), aiming at 8, lightness strictly monotonic,
and the scheme's own sea darker than its darkest band — and
`tests/web/test_ramps.py` runs it. The interpolated bands between anchors are
necessarily closer than the anchors; the legend and the readout's band range
carry the fine distinctions the colour alone cannot.

## Typography

IBM Plex Sans only (`vendor/fonts.css`, latin subset, weights 400/500/600),
default letter-spacing, no uppercase transforms, no tabular figures — see the
design policy in `CLAUDE.md`. Place labels are DOM markers so they use the
page's typeface; MapLibre symbol layers would need a glyph server.
