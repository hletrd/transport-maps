# Third-party notices

Every file in `web/vendor/` is redistributed to each visitor of this site, so
each carries its upstream licence's notice requirement with it. The bundles
here were taken from jsDelivr, whose repack strips the source banners, which is
how four of them came to be served with no copyright notice at all.

The texts in this directory are the upstream ones, fetched from each project's
own repository at the version pinned in `web/README.md`. They are not
paraphrased or summarised: BSD-3-Clause, Apache-2.0 and MIT each require the
notice to be reproduced verbatim on redistribution.

| Vendored file | Project | Version | Licence | Text |
|---|---|---|---|---|
| `maplibre-gl.js`, `maplibre-gl.css` | MapLibre GL JS | 5.24.0 | BSD-3-Clause | `maplibre-gl.LICENSE.txt` |
| `pmtiles.js` | PMTiles | 4.5.0 | BSD-3-Clause | `pmtiles.LICENSE.txt` |
| `h3.js` | h3-js | 4.2.1 | Apache-2.0 | `h3-js.LICENSE.txt`, `h3-js.NOTICE.txt` |
| `fflate.js` | fflate | 0.8.3 | MIT | `fflate.LICENSE.txt` |
| `ibm-plex-sans-latin-*.woff2`, `fonts.css` | IBM Plex Sans | — | OFL 1.1 | `../OFL.txt` |

Apache-2.0 section 4(d) requires the NOTICE file's attribution text to be
carried with any derivative distribution, which is why `h3-js.NOTICE.txt` is
here alongside the licence and not folded into it.

The font's OFL text stays at `../OFL.txt`, where `web/README.md` has pinned its
hash since cycle 2. Moving it would break that pin for no benefit.
