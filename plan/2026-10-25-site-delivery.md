# Site delivery and discoverability

Owner request: apply the performance and search improvements in sequence,
including HTTP/3 on nginx and Cloudflare.

- [x] Enable nginx HTTP/3 and verify the negotiated protocol and live map.
- [x] Enable Cloudflare proxying and HTTP/3; preserve client IP rate limiting.
- [x] Publish immutable, versioned assets and dataset URLs with atomic release selection.
- [x] Configure CDN caching for PMTiles and versioned files; bypass APIs.
- [ ] Fetch detailed readings and route overrides by region instead of worldwide arrays.
- [ ] Improve the title, description and readable HTML for interactive world isochrone searches.
- [ ] Verify deployed behavior at all four project viewports and repeat loading measurements.

Initial evidence: desktop cold load used about 9.8 MB, including 5.13 MB for
Seoul's fine readings and 1.57 MB for its route overrides. The mobile simulation
(4 Mbps download, 150 ms latency, CPU slowed 4x) reached the basic map and
travel-time list in 6.70 s, compared with 1.43 s without throttling. These are
single local browser runs, not field percentiles.

The upgraded origin has 4 aarch64 cores and 12 GB RAM. nginx 1.30.6 already
includes HTTP/3, and the default virtual host binds UDP 443. The local `dist/`
is older than production; never publish its dataset over the live build.

The NAS DNS token can edit the `worldmap.atik.kr` record but receives 403 from
zone settings and cache rules. A token with the required scopes was requested;
independent origin and application work continues.

HTTP/3 verification: nginx's global `http3 off` initially rejected QUIC ALPN;
the site now explicitly sets `http3 on`. An external aioquic client negotiated
`h3`, received 200 for robots.txt and 206 with exactly 127 bytes for a PMTiles
range. Chromium also negotiated `h3`, rendered the canvas and 60 city rows,
set appReady and reported no console errors. Backups are in
`/etc/nginx/worldmap-backup-20261025-http3/` on atik.kr. The CSP tests passed (5).

Immutable publication is live. The page asset gate passed 716 tests; the
publisher and deployment tests passed 66. Three publisher mutations (symlinks,
replacement preserving old bytes, and directory traversal permissions) went
red. The first live check found mkdtemp's 0700 permissions carried into the
snapshot: changed to 0755, repaired the live directories, and added the guard.
The full browser verification then passed all four viewports, searches,
permalinks, route readings, folded-sheet checks and console checks. Versioned
assets return immutable cache headers; the versioned PMTiles probe returned
206 and the exact requested range. No dataset was replaced with the stale
local dist. The first publication uses production build
`9b76cbb9-20261021T010348Z`.

Cloudflare proxying is enabled. HTTP/3 was already on; TLS remains Full and
Rocket Loader remains off. Three hostname-scoped cache rules cache the two
immutable namespaces (Origin Range Requests on for data) and bypass `/api/`.
Verified an asset MISS followed by HIT, PMTiles 206/HIT with the exact range,
and a malformed API request returning 400/no-store/DYNAMIC without invoking a
solve. Chromium connected through the edge over h3 with the map, 60 city rows,
loaded tiles and no console errors. This probe reached LAX; do not infer
worldwide latency or Korea edge routing from one connection. The public DNS
change was visible via Google's resolver while the local resolver retained
the previous record temporarily. The API helper's three tests passed, and
dropping preservation of unrelated rules made its regression test fail.
