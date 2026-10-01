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
| fonts.css | `ca06ffa19cbf1148916985a311fb10def2a7f34504e667ecc015dbf30f9ab1aa` |
| ibm-plex-sans-latin-400-normal.woff2 | `3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e` |
| ibm-plex-sans-latin-500-normal.woff2 | `0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203` |
| ibm-plex-sans-latin-600-normal.woff2 | `8960851d691c054ed38e259bdcf1a6190d157b4203ed5bb32c632a863fb8ec2f` |
| ibm-plex-sans-latin-ext-400-normal.woff2 | `c93d2a12aaa280f68b9ab7b726ff8dfedda67c99ef9abed047c1847a1cc6d583` |
| ibm-plex-sans-latin-ext-500-normal.woff2 | `2846035d85100f84c79393f80f1442d4ee720129ab8b3ffa8969aae281db8c6c` |
| ibm-plex-sans-latin-ext-600-normal.woff2 | `b25dfd4f979e442ae1e25cd0894463434cf01ba21ac1a35d39f4a82bd4cc060e` |
| OFL.txt | `7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da` |
| licences/README.md | `8c1826ebbd28d7ebb77dcc11c114f831492637cbdffebc9c729de19ea4f95054` |
| licences/fflate.LICENSE.txt | `0a1df3a083d0c010560aa342e87959c8c1070e6fd54545741f083f22d0c8b551` |
| licences/h3-js.LICENSE.txt | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| licences/h3-js.NOTICE.txt | `a265b8d138fa9064bbe12c1e9d6785705bdc91a3655b241b1fd01a7a0ead6663` |
| licences/index.html | `679b99d8f16f457605f7a874b49064dedb519f98bd52818d84508ea9c77c354f` |
| licences/maplibre-gl.LICENSE.txt | `ee5fc05a0677eaf69601d2c7db0d9ecd6cc27c3abc1d0733bc9ed34707cf8ef2` |
| licences/pmtiles.LICENSE.txt | `0371c38f338835f7fc13ed71176f3d92144e22c8b736a31cced57adbbeb647b3` |

Every file in `vendor/` appears above, including the licence texts under
`vendor/licences/`; `tests/web/test_vendor.py` walks the tree RECURSIVELY
rather than reading a hard-coded list (it used `iterdir()` until cycle 15,
which could not see the subdirectory at all while this sentence claimed it
could), so a newly vendored file fails the gate
until its hash is recorded here. The six font faces are served
`immutable, max-age=31536000` and are named by family, subset and weight, not by
content, so a swapped face would be cached for a year with no other signal.

## Where each file came from

The hashes above pin what is on disk. This table records what it was taken
from, checked against upstream on 2026-10-02. The four `.js` bundles are
jsDelivr `+esm` builds, which jsDelivr generates on demand (each file's own
header says not to use SRI on it), so they have no stable upstream hash to
compare. For those the provenance is the original file each header names.

| file | upstream | matches upstream byte for byte |
|---|---|---|
| maplibre-gl.js | jsDelivr `+esm` of `/npm/maplibre-gl@5.24.0/dist/maplibre-gl.js` | no: one-token CVE-2026-85061 patch, upstream hash in the table above |
| pmtiles.js | jsDelivr `+esm` of `/npm/pmtiles@4.5.0/dist/esm/index.js` | no: its `fflate` import is rewritten to `./fflate.js` |
| h3.js | jsDelivr `+esm` of `/npm/h3-js@4.2.1/dist/browser/h3-js.es.js` | generated, see above |
| fflate.js | jsDelivr `+esm` of `/npm/fflate@0.8.3/esm/browser.js` | generated, see above |
| maplibre-gl.css | `https://cdn.jsdelivr.net/npm/maplibre-gl@5.24.0/dist/maplibre-gl.css` | yes |
| ibm-plex-sans-latin-{400,500,600}-normal.woff2, ibm-plex-sans-latin-ext-{400,500,600}-normal.woff2 | `https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/` (IBM Plex Sans 3.201; 5.2.5 to 5.3.0 ship the same bytes) | yes |
| OFL.txt | `LICENSE.txt` of github.com/IBM/plex (also `@ibm/plex-sans@1.1.0`) | yes |
| fonts.css | written here | not applicable |
| licences/ | each package's own licence text; see `licences/README.md` | |

The faces are fontsource's subsets of IBM Plex Sans, not IBM's own split
files from `@ibm/plex-sans`. The latin faces were already fontsource's, and
latin-ext must come from the same build (3.201, identical vertical metrics)
and the same subsetting, or the two subsets' `unicode-range`s would neither
meet nor match the glyphs, and a name mixing both would set in two builds.

## Deploy

`scripts/deploy_verify.sh` copies `index.html`, `boot.js`, `app.js`,
`llms.txt`, `robots.txt`, `sitemap.xml`, `preview.png` and `vendor/` into the
pipeline's
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

IBM Plex Sans only (`vendor/fonts.css`, latin and latin-ext subsets, weights
400/500/600; latin-ext is fetched only for a name that uses it),
default letter-spacing, no uppercase transforms, no tabular figures — see the
design policy in `CLAUDE.md`. IBM Plex Sans © 2017–2019 IBM Corp., SIL Open
Font License 1.1 (`vendor/OFL.txt`). Place labels are DOM markers so they use
the page's typeface; MapLibre symbol layers would need a glyph server.
