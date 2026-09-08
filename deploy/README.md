# Deployment — worldmap.atik.kr

Static hosting on nginx. `dist/` (the pipeline's output) plus `web/` (the page,
its vendored libraries and fonts) are rsynced to `/var/www/worldmap`.

    rsync -a --delete dist/ atik.kr:/var/www/worldmap/

## Caching is load-bearing, not an optimisation

Every artifact except the fonts is rewritten by a rebuild, and they must change
**together**:

- `app.js` addresses elements that only the matching `index.html` contains
- `hover_cells.bin` must hold exactly as many entries as each `origins/*.bin`

A browser holding one old file and one new one renders a blank globe with no
console error. That shipped once: after a redesign, visitors got new HTML with a
cached old `app.js`, which threw on a missing element and killed the map before
it was created. Hence `no-cache` on html/js/json/bin/pmtiles — ETags make the
revalidation a 304, so the cost is a round trip, not a re-download.

`.woff2` is the one genuinely immutable asset and is cached for a year.

## Range requests

PMTiles reads byte ranges. The server must answer 206; nginx does by default.
A server without it fails with "Check that your storage backend supports HTTP
Byte Serving" — Python's `http.server` is one such.

## TLS

Let's Encrypt via certbot, auto-renewing. HSTS is set without `preload`, which
is a registry submission and hard to reverse.
