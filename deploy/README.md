# Deployment — worldmap.atik.kr

nginx serves immutable frontend and dataset releases on the Seoul origin.
The main hostname stays DNS-only; the optional public-data hostname is
proxied. See [Site delivery](../docs/site-delivery.md) for current release IDs,
loading behavior, protocol scope, measurements and slow-request diagnostics.

## Choose the deployment scope

Run from the repository root. Host, document root and URL come from
`deploy/.env` (see [.env.example](.env.example)).

| Change | Command | Dataset source |
| --- | --- | --- |
| Frontend only | `scripts/deploy_verify.sh --page-only` | Reuse the complete dataset already on the server |
| Complete rebuilt dataset | `scripts/deploy_verify.sh` | Validated local `dist/` |
| Dataset built on h200 | `scripts/deploy_from_h200.sh` | Validated build-host `dist/`, transferred directly |

Never full-deploy an old operator-machine `dist/` to ship a page fix. Full
builds require consistent hover layouts, every origin/variant, the coastline,
borders and the matching solver bundle where advertised. A partial build is
not a release.

## Before deploying

The shell needs `uv`, Python, Node, rsync, SSH and `agent-browser`. The deploy
refuses before upload if the browser executable is missing or the installed
publisher differs from local source. If the publisher changed, install the
matching root-owned helper first using the commands below.

Audit the project's runtime requirements, rather than only the isolated
`uvx` tool environment:

```sh
uv export --locked --format requirements.txt --no-dev --no-emit-project \
  --output-file /tmp/worldmap-runtime-requirements.txt
uvx pip-audit -r /tmp/worldmap-runtime-requirements.txt
```

[`pip-audit` supports requirements-file audits](https://github.com/pypa/pip-audit#usage).
The deploy script runs ruff and the licence firewall itself. Review findings
before deploying; do not treat an audit-tool error as a passing audit.

## What the script verifies and publishes

1. Check publisher SHA256 and browser availability. A build-host deployment
   uses the existing `BROWSER_VERIFY=by-caller` contract and immediately runs
   the browser check from the operator's machine.
2. In full mode, refuse a running/inconsistent build, run `check_dist.py`,
   check solver identity, and assemble `web/` into the complete dataset.
   Page-only mode validates the page copy without replacing dataset files.
3. Run ruff, the licence firewall, all `tests/web/` and the water tests. The
   gate checks vendor pins, module syntax/publication, CSP, attribution and
   UI rules. Unexpected skips, deselections, xfails, errors, a missing test
   count or too few passing tests fail the gate. Only explicitly marked
   unbuilt-`dist/` skips are accepted in a checkout without a built dataset.
4. Full mode measures changed transfer size and requires staging space plus
   30%. Retained immutable snapshots prevent the legacy chunked fallback
   from freeing old blocks. An unavailable free-space reading is currently
   logged as a warning; an insufficient measured value refuses the deploy.
5. Upload files while excluding the public `index.html`. Full mode stages
   replacements with rsync; page-only mode uploads `web/` without deletion.
   Protected release directories are retained. Upload the raw HTML as
   `.release-index.html`, then invoke the installed publisher to select the
   new page atomically.
6. Verify live files, status codes, byte ranges and security headers, then
   run the complete browser gate. An HTTP 200 alone does not complete a deploy.

The browser gate covers the canvas, timed city rows, coast and borders,
routes, tooltips, address search, departure changes, permalinks, console,
legend, folded sheet and layout at 1280×800, 820×1180, 390×844 and 844×390.
For delivery/loading changes, additionally delay a tile response and fail one
request: the loading notice must remain visible, retry must recover, and
optional downloads must wait. Only close the browser sessions/processes
created for the check.

## Immutable release URLs

The public HTML selects `/assets/<content-hash>/` for scripts, styles and fonts
and `/data/<build-id>-<manifest-hash>/` for one complete dataset. The publisher
writes the HTML atomically after both snapshots exist. Its `worldmap-data-root`
meta tag pins all data fetches, including map tiles and mode variants, to that
dataset. The source page without this tag still works against a local `dist/`.

`scripts/publish_release.py` runs on the web host after rsync and before the live
checks. Install the root-owned helper and its restricted-key gate before using
the deployment scripts:

```sh
scp scripts/publish_release.py deploy/worldmap-deploy-gate.sh atik.kr:/tmp/
ssh atik.kr 'sudo mkdir -p /usr/local/lib/worldmap && sudo install -m 644 /tmp/publish_release.py /usr/local/lib/worldmap/publish_release.py && sudo install -m 755 /tmp/worldmap-deploy-gate.sh /usr/local/bin/worldmap-deploy-gate'
```

The deploy preflight compares the installed publisher's SHA256 with the local
source before uploading anything. Update the helper first when its source
changes. The publisher must include every top-level browser module in
`PAGE_FILES`; the syntax tests enforce this. The browser executable must also
be available before publication (the build-host caller has its existing
`BROWSER_VERIFY=by-caller` contract).

Publication embeds the font declarations and MapLibre layout CSS in the HTML,
rebasing font URLs to the immutable asset directory. Native control icon
backgrounds are deferred in the complete, unchanged vendor stylesheet. That
stylesheet becomes active only after FCP and its load event. The publisher
removes ordinary HTML/CSS comments from the page, preserving script bytes,
quoted CSS strings and licence notices. Source files and vendor pins remain
unchanged. This removes both render-blocking stylesheet requests.

rsync stages the raw page as `.release-index.html`, leaving the selected page
intact until publication. Asset snapshots copy the small page files; data
snapshots hard-link the completed dataset on the same filesystem. Later uploads
must replace files (`--delay-updates`), never modify their contents in place.
`assets/` and `data/` are protected from rsync deletion. Existing release paths
are never overwritten or automatically removed.

Versioned responses use `public, max-age=31536000, immutable`; errors use
`no-store`. PMTiles remain unencoded so Range requests receive 206. HTML and
unversioned compatibility paths retain `no-cache`. Cloudflare must explicitly
make the versioned paths eligible for caching, including `.pmtiles` and JSON.
Keep `/api/` outside those cache rules.

The first hard-linked snapshot costs directory metadata rather than another
copy of the dataset. Subsequent full rebuilds need storage for both generations:
the old snapshot keeps replaced files allocated. A low-space deploy now refuses
before uploading when snapshots exist; the legacy chunked fallback cannot free
that space. Expand storage or explicitly retire an obsolete release first.
Page-only deployments reuse the dataset snapshot.

The publisher also prepares regional route directories from `.over.bin` and
adds `readingRanges` to the completed index. This is a one-time scan of existing
slot arrays, not a graph rebuild. Later page deploys reuse directories whose
source mtime and layout match. Versioned `.r6.bin` and `.over.bin` are served
unencoded for byte-range access. The browser fetches detail only for a resting
pointer or chosen destination; complete-array loading remains the fallback for
older dataset indexes. See `docs/contract.md` for the directory layout.

## Cloudflare

`worldmap.atik.kr` currently uses DNS-only delivery to the Seoul origin. The
Cloudflare proxy was disabled on 2026-10-25 after the operator's Korean route
went through LAX and map loading regressed. The origin still serves HTTP/3,
immutable release URLs and regional detail requests.

`worldmap-data.atik.kr` is a separate proxied A record pointing to the same
origin. Its nginx site serves only immutable `/data/` releases, the fixed
16 KiB `/delivery-probe-v1.bin`, and certificate challenges. `/api/` and page
paths return 404. Install `worldmap-data.atik.kr.conf` and
`worldmap-data-cors.conf`; the latter allows only the main page's origin and
exposes range/ETag/timing headers. The CSP allows this hostname for connections
only. Its separate ECDSA Let's Encrypt certificate is renewed by Certbot's
webroot authenticator with `nginx -t && systemctl reload nginx` as deploy hook.

The browser chooses a data path without blocking first paint and retries CDN
failures on the identical origin release. Selection thresholds, timeouts,
session hints and browser diagnostics are documented in
[Data route selection](../docs/site-delivery.md#data-route-selection).

The retained Cloudflare settings are HTTP/3 on, Full TLS and Rocket Loader off.
The cache rules apply to proxied traffic; the main hostname stays direct.
Zone settings also affect other hosts. The setup script verifies TLS without
changing it globally.

`deploy/cloudflare-cache-rules.json` scopes rules to these two hostnames: cache
`/assets/`, cache `/data/`, enable Origin Range Requests only for `.pmtiles`,
`.r6.bin` and `.over.bin`, and bypass `/api/`. Other binary files keep whole-file
gzip compression; a fifth rule caches the CDN probe. Enabling origin ranges
on whole-file binaries would force identity encoding and enlarge startup
downloads. The origin's cache headers determine freshness. Origin Range Requests avoid fetching
an entire PMTiles file on a cold range request; Cloudflare may fetch a larger
aligned range than the browser asked for.

Before enabling the proxy, install `deploy/worldmap-cloudflare-realip.conf` as
`/etc/nginx/snippets/worldmap-cloudflare-realip.conf`. It trusts
`CF-Connecting-IP` only from Cloudflare's published address ranges, so solver
limits still apply per visitor and direct requests cannot spoof their IP.
Refresh the ranges from `https://api.cloudflare.com/client/v4/ips` when needed.

`scripts/configure_cloudflare.py --host worldmap-data.atik.kr --token-file PATH --zone-id ZONE --backup PATH`
previews the change. Add `--apply` to write the rules while preserving the DNS
proxy and protocol settings. `--enable-proxy` enables only the selected DNS
record and, if necessary, enables HTTP/3 for the entire zone. Never enable
the main record as part of data-host setup. It preserves unrelated cache
rules and DNS targets, backs up the original state to a new private file, and
does not enable the proxy if cache configuration fails. The token requires DNS
Edit, Zone Read, Zone Settings Edit and Cache Rules Edit for this zone. Never
commit it. Verify cache HITs, API bypass and PMTiles 206 responses after changes.

## Recovery

For a page regression, use an isolated checkout of the last verified
application revision, install its matching publisher and run the page-only
deploy with the complete browser gate. Reuse the current complete dataset;
do not overwrite immutable asset files or copy a few files into an existing
release directory.

To turn off adaptive data delivery, remove the `worldmap-data-cdn` meta tag
from the page template and deploy through the same gates. New page loads then
use the origin; the independent after-FCP stylesheet activation still works.
Keep the data hostname available to existing tabs. Enabling the main site's
proxy is not a rollback for this feature.

| Origin backup directory | Historical state |
| --- | --- |
| `/etc/nginx/worldmap-backup-20261025-http3/` | Before origin HTTP/3 |
| `/var/backups/worldmap-20261025-release/` | Before immutable publication; original Cloudflare settings and the main-record proxy rollback |
| `/var/backups/worldmap-20261025-adaptive/` | Before data-host rollout; nginx/header/helper backups and private, credential-free `cloudflare-before.json` |

These are dated snapshots, not interchangeable current configurations.
Compare them with current source before restoring individual settings: an
early header file may omit the data-host CSP permission, and an early vhost
may omit versioned caching or API routes. Validate nginx before a graceful
reload and verify the page, ranges and APIs afterwards. Preserve unrelated
zone rules and domains. Cache purges do not repair mismatched immutable files.

## Unversioned compatibility caching

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

On unversioned compatibility paths, `.woff2` is the exception cached for a
year; change its basename when replacing a face. Published font URLs include
the asset content hash and therefore change automatically with the content.

## Security headers: the `add_header` inheritance trap

With the current default inheritance, a `location` that sets any header of
its own (here: `Cache-Control`) inherits none of the server's `add_header`
directives. Before this was fixed, the live site served no Content-Security-Policy, HSTS, `nosniff` or
`X-Frame-Options` on `/`, `app.js`, `index.json`, any `.bin` or `.pmtiles` —
only on files no location matched (`robots.txt`, `preview.png`, 404s).

The headers therefore live in `deploy/worldmap-security-headers.conf` and are
`include`d at server level **and** inside every location. Back up the active
files before installing changes. For the main vhost and shared headers:

```sh
scp deploy/worldmap-security-headers.conf deploy/worldmap.atik.kr.conf atik.kr:/tmp/
ssh atik.kr 'sudo install -m 644 /tmp/worldmap-security-headers.conf /etc/nginx/snippets/worldmap-security-headers.conf && sudo install -m 644 /tmp/worldmap.atik.kr.conf /etc/nginx/sites-available/worldmap.atik.kr && sudo nginx -t && sudo systemctl reload nginx'
```

and verify on a page asset, not on the root alone:

    curl -sI https://worldmap.atik.kr/app.js | rg -i 'content-security|strict-transport|x-frame|x-content'

The CSP allows the public-data CDN, Nominatim (address search, only on request)
and the Google tag (loader by host,
inline bootstrap by hash, collection endpoints in `connect-src`/`img-src`). The
solver APIs are same-origin and covered by `'self'`.
Scripts and workers no longer allow `blob:`: MapLibre 5 needed it for its
workers, MapLibre 6 loads its worker from `vendor/` (dropped 2026-10-06, after
a report-only run of the stricter policy on the live page). Changing the inline gtag snippet in `web/index.html` changes
its hash; recompute it (`sha256` of the exact script text, base64) and update
the snippet, or the tag stops loading silently. GA4 posts its hits to
`analytics.google.com` and `www.google.com`, so `connect-src` lists
`https://*.google.com`, as Google's CSP guide does for Analytics without
advertising features (added 2026-10-06; until then every hit was refused).
Ads linking would also need `https://*.g.doubleclick.net`, which the CSP does
not list.

## Deploying from the build host

`scripts/deploy_from_h200.sh` runs the full `scripts/deploy_verify.sh` ON h200,
against the build's own `dist/`, so the build goes to the web host in one hop.
From the operator's machine every changed byte crossed aws-proxy twice: rebuild
28 (2026-10-06) took ~2.5 h to pull 110 GB at ~13 MB/s and ~3.3 h to push
144 GiB, where h200 reaches the web host directly at ~160 MB/s (measured
uploading 1.5 GB). Every gate still runs, on h200; the page is then opened from
the operator's machine (`browser_verify.sh`), whose status is the script's.
The solver bundle still goes through `scripts/deploy_solver.sh` from here.

h200 is shared, so its key can do only what `deploy_verify.sh` asks of the web
host. On the web host, `ubuntu`'s `authorized_keys` names it as

    from="14.63.187.16",restrict,command="/usr/local/bin/worldmap-deploy-gate" ssh-ed25519 ... worldmap-deploy@h200

and `deploy/worldmap-deploy-gate.sh`, installed root-owned at that path, lets
through rsync confined to `/var/www/worldmap` (`rrsync`) and the four read-only
checks, each matched as a whole string and run as written in the gate. A shell,
a path outside the root, `..`, or a check with anything appended is refused;
`tests/test_deploy_gate.py` reads the checks out of `deploy_verify.sh`, so a
new one fails there before it fails a deploy. Install or update it with

    scp deploy/worldmap-deploy-gate.sh atik.kr:/tmp/wdg.sh
    ssh atik.kr 'sudo install -m 755 -o root -g root /tmp/wdg.sh /usr/local/bin/worldmap-deploy-gate'

The key is `/default/worldmap/.deploy-ssh/id_ed25519` on h200 (mode 600), with
the web host's host key pinned in `known_hosts` beside it. If h200's egress
address changes (`curl ifconfig.me` there), the `from=` clause refuses the key
until it is updated. To revoke it, delete that line from `authorized_keys`.

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

`location = /api/solve` and `location = /api/map` in `deploy/worldmap.atik.kr.conf`
proxy to the unit, with the same rules (one limit zone shared by both):

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

**Legs need the node counts.** A bundle's `meta.json` carries `nAirports` and
`nStations` from 2026-10-02 on, and the service then answers each solve with
its legs as well as its minutes. A bundle written before that (the
`52660de5` rebuild's among them) has neither: it still answers the number,
with no legs. Before shipping one, give it the counts from the dist/ of the
same build, which refuses a dist/ whose `buildId` or node offsets do not
match:

    uv run python -m transport_maps.service.bundle add-counts data/build/solver dist

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

**The whole map from one point** (`/api/map`, the page's "map from the point
you chose"):

    curl -s 'https://worldmap.atik.kr/api/map?from=37.80000,127.25000' | head -c 200

Expect `"status":"ok"`, `"mapVersion":1` and `"count"` equal to the site's
hover cells (90,740 today); `times` is base64 of that many uint16, in
`hover_cells.bin`'s order. The service keeps the last two shortest-path trees
(166 MB each), so a `/api/solve` from the same point right after a map answers
from memory. `scripts/deploy_solver.sh` ships `dist/hover_cells.bin` beside the
bundle, and the service refuses to start if its own order differs from it.

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

HTTP/3 is enabled for both `worldmap.atik.kr` and `worldmap-data.atik.kr`
alongside HTTPS over TCP. The host's default virtual host owns `reuseport`
on UDP 443 for IPv4 and IPv6; both sites' QUIC listeners share those sockets.
Keep `Alt-Svc` in the shared header snippet
so responses from locations with their own `Cache-Control` advertise HTTP/3.
The explicit `http3 on` overrides the host's global `http3 off`.
The installed nginx includes `--with-http_v3_module`; both the host firewall
and the cloud network must allow UDP 443. Verify the negotiated protocol in a
browser, as the host's curl does not include HTTP/3 support.

On the proxied data hostname, HTTP/3 can connect visitors to Cloudflare;
Cloudflare does not support HTTP/3 to the origin. The origin's HTTP/2 listener
remains available to the edge and to direct visitors. Main-host direct access
can negotiate HTTP/3; verify the actual protocol rather than inferring it
from `Alt-Svc` alone. The two hostnames have separate Certbot certificates.
