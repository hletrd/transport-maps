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

5.24.0 is the last 5.x release and carries CVE-2026-85061 (a `DOM.sanitize`
bypass, fixed only in 6.4.1; advisory:
https://advisories.gitlab.com/npm/maplibre-gl/CVE-2026-85061/). It is
unreachable here because `attributionControl` is false and no popup is used;
do not enable either without upgrading or patching (security plan I2). The
vendored bundle carries a one-token local patch (see the hashes table below).

## Vendored file hashes (sha256)

Recorded so that a refresh of `vendor/` is a deliberate act, not a side
effect: recompute with `shasum -a 256 web/vendor/<file>` and update the row
in the same commit.

| file | sha256 |
|---|---|
| maplibre-gl.js | `b2b139c104732232252c74b66bee0ab6302d22a3c98723ac6d07589f9bd1c052` (patched: `removeAttributes` iterates `Array.from(t.attributes)`, CVE-2026-85061; upstream 5.24.0 was `c51e43e844402c587c55f43ff09de18989cacb80850d2ea7365f21088a332b0b`) |
| pmtiles.js | `ea53f031446436ac57b420eeda2cc81092ed8b9b6dcbd15207f1b63495fad0bc` |
| h3.js | `fcaa69b16ddfdd26e8544bf326eeb2c6d25ae3ba94ffa27c0a484cb5318cfd32` |
| fflate.js | `d22d603594fe32208e563d2f2fbe9e53f8addc1c845320786c7de62464c288a8` |
| maplibre-gl.css | `ab1e70d59ec40465bae7e7030da2f3ccf28133fd502e62bd598eefbadfd7a732` |
| fonts.css | `2c6b4a194338790b27cdfa65a3f06ac64c774bd12ed6c2658904105989e0d35b` |

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
bands as `index.json` declares (37 today). Every scheme except Mono rotates
hue as well as lightness — a single hue cannot separate that many bands on a
dark ground; Mono separates by lightness alone. `scripts/check_ramps.py`
measures anchors, the uncharted grey and the sea against space and the darkest
band: adjacent anchors must be at least 6 apart in OKLab ΔE (×100), aiming at
8, lightness strictly monotonic, and each scheme's sea must sit between space
and its darkest band. `tests/web/test_ramps.py` runs it. The interpolated
bands between anchors are necessarily closer than the anchors; the legend and
the readout's band range carry the fine distinctions the colour alone cannot.

## Typography

IBM Plex Sans only (`vendor/fonts.css`, latin subset, weights 400/500/600),
default letter-spacing, no uppercase transforms, no tabular figures — see the
design policy in `CLAUDE.md`. IBM Plex Sans © 2017–2019 IBM Corp., SIL Open
Font License 1.1 (`vendor/OFL.txt`). Place labels are DOM markers so they use
the page's typeface; MapLibre symbol layers would need a glyph server.
