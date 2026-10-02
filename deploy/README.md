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
   count (it must come from `index.json`). **It also refuses an `index.json`
   whose `attribution` block does not credit every source the pipeline
   consumes** -- the only automated licence gate in the project, and the reason
   the nine credits reach the live site at all. It WARNS, without blocking, on
   a build-host path in a PMTiles metadata blob;
3. assembles the page into the build output — `web/vendor/` mirrored with
   `--delete`, the rest of `web/` (everything but `web/README.md`) on top — so
   `index.html`, `app.js`, `boot.js`, `llms.txt` and `vendor/` sit beside
   `index.json`, `hover_cells.bin` and `origins/`;
4. runs the page-asset gate over what it has just assembled. It runs in BOTH
   modes — `--page-only` publishes `web/` and nothing else, so before it did,
   that path shipped ungated. The gate refuses on **nine** conditions, not the
   four this list carried until cycle 17: the licence firewall (on `web/` as
   well as `dist/`), the vendored-bundle hash pins, the CSP inline-script hash,
   and the attribution and privacy obligations — plus, since `c2d11f5`, a
   repo-wide `uv run ruff check .`, any test reporting `deselected`, `xfailed`,
   `xpassed` or `error` (pytest exits 0 on all four, so the stage would
   otherwise report success while checking less than it claims), a **floor on
   the passed count**, and any skip whose reason does not carry the
   `needs a built dist/` sentinel — a skip because nothing is built has stopped
   checking nothing, a skip for any other reason is a check that silently
   stopped running;
5. checks free space on the server before moving a byte -- `df -Pk` over the
   connection rsync is about to use, against the measured payload plus 30 %.
   `--delay-updates` stages the new set beside the old one, and running out
   mid-rename leaves exactly the mixed `dist/` step 1 exists to prevent, on the
   server, where no gate can see it. A server that will not answer is a
   warning, not a refusal;
6. rsyncs `dist/` to the server with `--delete --delete-delay --delay-updates`,
   explicit modes and `deploy/rsync-excludes.txt`, logging to a temp file;
7. curls the live files, including two byte-range requests against a
   `.pmtiles`, and ASSERTS each status (200, or 206 on the range probes) rather
   than printing it; then reports whether the security headers are present;
8. runs `scripts/browser_verify.sh` against the deployed URL. Under
   `set -euo pipefail` its exit code is the deploy's, so a page that does not
   RUN fails the deploy. CLAUDE.md: "No deploy is done until it has been opened
   in a browser... `curl` returning 200 proves nothing about whether the page
   runs." This script therefore does not leave that stage to the operator; it
   is step 8, and the header of `deploy_verify.sh` said otherwise until cycle 6.

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
- The CSP was rehearsed and is INSTALLED (2026-09-13). Rehearsal: `dist/` served
  locally with the policy injected as a meta tag, page opened, map 7,845 water
  features and 52 bands, 553 cities, address search reaching Nominatim and
  returning results, zero CSP refusals, zero console errors. Install: the
  snippet at `/etc/nginx/snippets/`, included at server level and inside all
  five locations that set their own `add_header`, six now-duplicated
  server-level headers removed, `nginx -t` passed, reload, and the live page
  re-opened with the same result. All six headers verified present on `/`,
  `app.js` and `origins/seoul.bin` -- the `.bin` and `.pmtiles` locations are
  the ones that used to drop them. Backup at
  `/etc/nginx/worldmap.atik.kr.bak.*` on the host.

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

The CSP names exactly the two third-party runtime calls the page makes:
Nominatim (address search, only on request) and the Google tag (loader by host,
inline bootstrap by hash, collection endpoints in `connect-src`/`img-src`). The
page's third call, `/api/solve`, is same-origin and is covered by `'self'`. The
CSP also allows `blob:`, which MapLibre 5 needed for its workers. MapLibre 6
does not, and dropping it is a separate change, to be made and verified on the
server (`deploy/worldmap-security-headers.conf`). Changing the inline gtag snippet in `web/index.html` changes
its hash; recompute it (`sha256` of the exact script text, base64) and update
the snippet, or the tag stops loading silently. Google signals are off; enabling
them would need the extra hosts `https://*.g.doubleclick.net
https://*.google.com` in the CSP, which does not list them.

## The on-demand solver

The page can time a journey from the exact point the visitor dropped, not only
from the nearest charted city. That number comes from a resident solver on the
web host (`src/transport_maps/service/`). It returns minutes only, with no legs
(`plan/2026-09-14-c13-solver-service.md`, C13-F2.8). The map, the bands and
every charted time are static files and do not depend on it. When the solver
is down, the page says the service is not ready and keeps working.

### Where it runs

- **Host:** atik.kr, the web host itself, with 5 GB of RAM and 3 aarch64
  cores. The build never runs here; it runs on the owner's Mac. The solver
  and a build therefore never share a machine.
- **Unit:** systemd `worldmap-solver`, from `deploy/worldmap-solver.service`,
  installed to `/etc/systemd/system/`. It runs as `ubuntu` at `Nice=10`,
  capped at `CPUQuota=150%` and `MemoryMax=2500M`, with `Restart=on-failure`.
  It listens on `127.0.0.1:8787` only.
- **Files:** everything lives under `/home/ubuntu/worldmap-solver`:
  - `app/transport_maps/` holds the service code: `__init__.py`,
    `config.py`, `snap.py` and `service/`. Nothing in it imports the graph
    package.
  - `.venv/` holds numpy, scipy and h3, pinned to the versions the build
    checkout runs.
  - `current/` is the solver bundle (`service/bundle.py`): the CSR graph and
    cell ids as `.npy`, about 1.2 GB, plus `meta.json`, which carries the
    build's `buildId`. **Only `current/` is kept.** A deploy stages the next
    bundle as `bundle.new/` beside it, so allow about twice the bundle's size
    in free disk.
- **Measured on this host, 2026-10-02:** 1.1 s to map the bundle at start,
  6-7 s per solve, 1.2 GB peak resident. It answers one solve at a time.
  Other requests wait in a listen backlog of 4.

### nginx

`location = /api/solve` in `deploy/worldmap.atik.kr.conf` proxies to the unit:

- `limit_req zone=worldmap_solver` allows 6 requests a minute per address,
  with a burst of 3 (`nodelay`). Past that, nginx answers `busy` itself, as
  `503` with `Retry-After: 15`, in the wire format the page reads
  (`@solver_busy`). The solver never sees those requests.
- A `502`, `503` or `504` from upstream becomes `unavailable`, `503` with
  `Retry-After: 60` (`@solver_unavailable`). That covers the unit being
  stopped, starting, or past the backlog.
- `proxy_connect_timeout 2s` and `proxy_read_timeout 60s`. The 60 s read
  timeout is the only deadline: the process has none of its own, so a solve
  that runs past it finishes unseen while nginx has already answered
  `unavailable`.
- `access_log off`. The query string is the visitor's departure point and
  destination, to about a metre, and the page's Privacy section promises they
  go to this server and no further. The unit logs no points either (below).
- The security-header snippet is included here as in every other location.

### Shipping it, and the order relative to the site

    bash scripts/deploy_solver.sh [BUNDLE_DIR]    # default: data/build/solver

The script ships four things, then proves a solve:

1. the service code;
2. the pinned dependencies, into the host's venv;
3. the bundle, to `bundle.new/`;
4. the unit and the nginx site, each only when it differs. nginx is
   installed only after `nginx -t` passes, and rolled back if it fails.

It then swaps `bundle.new/` in as `current/` and restarts the unit. It polls
Seoul -> Gumi through nginx until `"status":"ok"` and a number come back. If
they do not, it restores the previous bundle and fails. Once the solve
succeeds it deletes the previous bundle.

**`index.json` arms the page only for a bundle from the same build.**
`build-all` writes `data/build/solver/` and, only if that bundle's `buildId`
is its own, a `solver` field in `index.json` (`emit/index._solver_matches`).
`deploy_verify.sh`'s `solver_gate` then refuses to publish an `index.json`
that offers the solver while the host's `current/meta.json` names another
build. After a full build the order is therefore:

    bash scripts/deploy_solver.sh       # first: the bundle the new index.json names
    bash scripts/deploy_verify.sh       # then the site; solver_gate checks the pair

A `--page-only` deploy does not touch `index.json`, so it needs neither step.

### Operating it

    ssh atik.kr systemctl status worldmap-solver
    ssh atik.kr sudo systemctl restart worldmap-solver     # re-maps current/, ~1 s
    ssh atik.kr sudo systemctl stop worldmap-solver        # page says "not ready"; map unaffected
    ssh atik.kr sudo journalctl -u worldmap-solver -n 100  # add -f to follow

**What the log holds.** One line when the bundle is mapped, with its time and
`meta.json`. One line when it starts serving. Then one line per request,
`solve <status> in <seconds> s`. **That is the status and the duration only.**
The handler overrides `http.server`'s default request logging, which would
print the URL and with it both points. Keep it that way: a log line with a
coordinate in it would break the Privacy promise just as an access log would.

**A health check** is a real solve, because no separate health endpoint
exists:

    curl -s 'https://worldmap.atik.kr/api/solve?from=37.56650,126.97800&to=36.10000,128.40000'

Expect `"status":"ok"` and a `"minutes"` value. Each call uses one of the six a
minute that nginx allows your address.

### Rolling back

Re-run the deploy with an older bundle:

    bash scripts/deploy_solver.sh /path/to/older/solver

The host keeps only `current/`, and every full build overwrites
`data/build/solver/`. So a bundle you may want to return to has to be copied
aside before the next build, for example to
`data/build/solver-<buildId>/`.

**A bundle rollback alone breaks the same-build rule.** The live
`index.json` still names the newer build in `solver`, so the page would
offer exact departures computed on a different graph from the map beside
them. Do one of two things:

- roll the site back to the `dist/` that bundle came from, so the two
  `buildId`s match again; `solver_gate` checks that on the way out; or
- stop the unit until a matching pair is ready. The page then reports the
  service as not ready, and everything else keeps working.

## Range requests

PMTiles reads byte ranges. The server must answer 206; nginx does by default.
A server without it fails with "Check that your storage backend supports HTTP
Byte Serving" — Python's `http.server` is one such.

## TLS

Let's Encrypt via certbot, auto-renewing. HSTS is set without `preload`, which
is a registry submission and hard to reverse.
