# Frontend — `worldmap.atik.kr`

A single static page: a MapLibre globe painting per-origin isochrone bands from
the PMTiles the pipeline emits.

## Self-contained by design

Nothing is fetched from a CDN at runtime. MapLibre, PMTiles, h3-js, fflate and
both font families are vendored under `vendor/`, so the deployed site works
behind a strict `script-src 'self'` CSP and has no third-party dependency.

`vendor/` is generated, not hand-edited. To refresh it, re-download each package
from jsdelivr and rewrite any `/npm/...` imports to local siblings.

## Pinned versions, and why

| package | version | note |
|---|---|---|
| maplibre-gl | **5.24.0** | NOT 6.x — see below |
| pmtiles | 4.5.0 | |
| h3-js | 4.2.1 | |
| fflate | 0.8.3 | transitive dep of pmtiles |

**Do not upgrade MapLibre to 6.x without testing tile loading.** Two things break:
its ESM bundle drops the default export (needs `import * as`), and more
importantly pmtiles 4.x's `addProtocol` handler is called once for the source
metadata and then never for tiles, so the map renders an empty globe with no
console error. MapLibre 5.24 has globe projection and works correctly.

## Deploy

Copy `index.html`, `app.js` and `vendor/` alongside the pipeline's `dist/`
output, so `index.json`, `hover_cells.bin` and `origins/` are siblings.

The server must support HTTP Range requests — PMTiles reads byte ranges, and a
server without them fails with "Check that your storage backend supports HTTP
Byte Serving". nginx does this by default; Python's `http.server` does not.

## Colour ramp

Eleven sequential steps of a single blue hue, brightest = fastest. Validated for
strictly monotonic OKLCH lightness (0.905 -> 0.433) with the darkest step at
2.41:1 against the `#0a0c10` surface, clearing the 2:1 floor for ordinal ramps
on dark. It is deliberately one hue: a rainbow ramp would imply categories where
there is only magnitude.
