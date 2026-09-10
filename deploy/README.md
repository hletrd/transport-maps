# Deployment — worldmap.atik.kr

Static hosting on nginx. `scripts/deploy_verify.sh` does the whole thing and
refuses to ship an inconsistent build:

1. refuses while a `build-all` is running — its lock, or a matching process
   ABOVE 1 % CPU (orphans of a killed build sit at 0.0 % for days and must not
   block every deploy);
2. runs `scripts/check_dist.py` — every origin's arrays agree in length with
   `hover_cells.bin` (widths from the emitters), `index.json` carries
   `bandEdgesMin`, `hoverCellCount` and `modeChannels` (a missing one names
   `transport-maps reindex` as the remedy), `{slug}.json` is present, valid,
   and carries real `offsets`, every origin agrees on `offsets.airports` so two
   builds cannot be mixed, `.rail.bin` and `.rail.json` ship together and
   `.rail.json` has its `stations` list, every `.pmtiles` header is sane,
   `index.json` lists exactly the origins of `data/origins.toml`, no stray
   `*-journal`/`.tmp`/dotfile is present, and the page copy states no city
   count (it must come from `index.json`). It also WARNS, without blocking, on
   a build-host path in a PMTiles metadata blob;
3. assembles the page into the build output — `web/vendor/` mirrored with
   `--delete`, the rest of `web/` (everything but `web/README.md`) on top — so
   `index.html`, `app.js`, `boot.js`, `llms.txt` and `vendor/` sit beside
   `index.json`, `hover_cells.bin` and `origins/`;
4. runs the page-asset gate over what it has just assembled: the licence
   firewall (on `web/` as well as `dist/`), the vendored-bundle hash pins, the
   CSP inline-script hash, and the attribution and privacy obligations. This
   runs in BOTH modes — `--page-only` publishes `web/` and nothing else, so
   before it did, that path shipped ungated;
5. rsyncs `dist/` to the server with `--delete --delete-delay --delay-updates`,
   explicit modes and `deploy/rsync-excludes.txt`, logging to a temp file;
6. curls the live files, including two byte-range requests against a
   `.pmtiles`, and ASSERTS each status (200, or 206 on the range probes) rather
   than printing it; then reports whether the security headers are present.

The order of 3 and 4 matters and was wrong until cycle 3: the gate used to run
before the page was merged in, so `index.html`, `app.js`, `llms.txt` and
`vendor/` — the assets that actually ship — were scanned by nothing.

`scripts/deploy_verify.sh --page-only` ships `web/` alone, without the
`dist/` gate and without `--delete`, for a page fix while a rebuild owns
`dist/`; the page reads every newer `index.json` field with a fallback, so an
older build stays valid. Host, server root and site URL come from
`deploy/.env` (see `deploy/.env.example`); the defaults are the live site.

`scripts/browser_verify.sh` then opens the live site (or a local preview,
given its URL) in a browser and checks the canvas, the city list and legend
counts (read from the deployed `index.json`, never hard-coded), the
departure label, the coast and borders layers, a route with surface modes
and tooltips, address search, click-to-depart, zoom 3, the city list's
door-to-door times, a searched destination agreeing with its itinerary, globe
labels carrying their own accessible names, the `?from=`/`?to=` permalink and
an unknown slug, the console, four viewports with a route open (including the
legend's hour ticks and the departure card not overlapping the reading), the
bottom-sheet handle after a return to desktop, and — on a phone — that a tap
leaves the answer and the whole legend on screen, and that the folded sheet
still shows the band strip, the ticks, the keys and the door-to-door caption. It kills only the browser
processes it started. **A deploy is not done until that has passed**
(CLAUDE.md).

## Before deploying

- Run `uvx pip-audit` (not installed in the venv; run it ad hoc) and
  `uv run pytest tests/test_licence_firewall.py`.
- The CSP has never been rehearsed against the page on a server (SEC-19).
  That rehearsal is owed before the first install: serve `dist/` behind
  `deploy/worldmap-security-headers.conf`, open the page and confirm the map,
  the address search and the Google tag all load with no CSP report in the
  console.

## Caching is load-bearing, not an optimisation

Every artifact except the fonts is rewritten by a rebuild, and they must change
**together**:

- `app.js` addresses elements that only the matching `index.html` contains
- `hover_cells.bin` must hold exactly as many entries as each `origins/*.bin`

A browser holding one old file and one new one renders a blank globe with no
console error. That shipped once: after a redesign, visitors got new HTML with a
cached old `app.js`, which threw on a missing element and killed the map before
it was created. Hence `no-cache` on html/js/json/txt/xml/css/png/bin/pmtiles —
ETags make the revalidation a 304, so the cost is a round trip, not a
re-download. `css` and `png` were missing from that list once: they matched no
location, fell through to `location /` with no `Cache-Control` at all, and a
revalidated `maplibre-gl.js` beside a heuristically cached old
`maplibre-gl.css` is exactly the mismatch above.

`.woff2` is the one asset cached for a year. The font files are named by
family/subset/weight, not by content — bump the filename when Plex is
refreshed, or the old face is served for a year.

## Security headers: the `add_header` inheritance trap

nginx `add_header` does **not** merge across levels. A `location` that sets any
header of its own (here: `Cache-Control`) inherits **none** of the `add_header`
lines from the `server` block. With the headers declared once at server level,
the live site served no Content-Security-Policy, HSTS, `nosniff` or
`X-Frame-Options` on `/`, `app.js`, `index.json`, any `.bin` or `.pmtiles` —
only on files no location matched (`robots.txt`, `preview.png`, 404s).

The headers therefore live in `deploy/worldmap-security-headers.conf` and are
`include`d at server level **and** inside every location. Install both files:

    scp deploy/worldmap-security-headers.conf atik.kr:/etc/nginx/snippets/
    scp deploy/worldmap.atik.kr.conf atik.kr:/etc/nginx/sites-available/worldmap
    ssh atik.kr 'nginx -t && systemctl reload nginx'

and verify on a page asset, not on the root alone:

    curl -sI https://worldmap.atik.kr/app.js | grep -iE 'content-security|strict-transport|x-frame|x-content'

The CSP names exactly the two runtime calls the page makes — Nominatim (address
search, only on request) and the Google tag (loader by host, inline bootstrap by
hash, collection endpoints in `connect-src`/`img-src`) — plus `blob:` for
MapLibre's workers. Changing the inline gtag snippet in `web/index.html` changes
its hash; recompute it (`sha256` of the exact script text, base64) and update
the snippet, or the tag stops loading silently. Google signals are off; enabling
them would need the extra hosts `https://*.g.doubleclick.net
https://*.google.com` in the CSP, which does not list them.

## Range requests

PMTiles reads byte ranges. The server must answer 206; nginx does by default.
A server without it fails with "Check that your storage backend supports HTTP
Byte Serving" — Python's `http.server` is one such.

## TLS

Let's Encrypt via certbot, auto-renewing. HSTS is set without `preload`, which
is a registry submission and hard to reverse.
