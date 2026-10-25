# Site delivery and discoverability

Owner request: apply the performance and search improvements in sequence,
including HTTP/3 on nginx and Cloudflare.

- [x] Enable nginx HTTP/3 and verify the negotiated protocol and live map.
- [x] Enable Cloudflare proxying and HTTP/3; preserve client IP rate limiting.
- [x] Publish immutable, versioned assets and dataset URLs with atomic release selection.
- [x] Configure CDN caching for PMTiles and versioned files; bypass APIs.
- [x] Fetch detailed readings and route overrides by region instead of worldwide arrays.
- [x] Improve the title, description and readable HTML for interactive world isochrone searches.
- [x] Verify deployed behavior at all four project viewports and repeat loading measurements.

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

Regional delivery is live. Existing arrays were indexed in 266 s without a
solver rebuild. Twelve live CDN readings across six places, with and without
flights, matched independently read original times, airports and mode totals;
they required 406,196 decoded bytes in total. Initial page measurements made
zero detailed-array requests and transferred about 3.09 MB, versus 9.78 MB in
the initial desktop run (about 68% less). Latency did not improve proportionally:
the measured Cloudflare route reached LAX and the first document still went to
the origin. The mobile layout shift remains a separate existing issue.

The browser checks caught two arrival races: regional row refresh overwrote a
committed screen-reader announcement, and the former 10-second permalink poll
expired on a slow CDN load. Both are corrected and behavior-tested, including
mutations. The permalink now restores on array arrival and respects a newer
city or destination. Range status/offset/length, final regions, late aborted
responses, directory boundaries and unknown slots are tested. The full deploy
gate and all four viewport/browser checks passed.

Origin Range Requests are now restricted to PMTiles, `.r6.bin` and `.over.bin`.
Enabling them for ordinary whole-file binaries had removed compression; a
fresh transport namespace and scoped rule restored hover_cells.bin to 125,075
wire bytes with gzip instead of 725,920. The cache configuration now has four
rules. An intentional broad-range mutation fails the regression cases for
coarse arrays, the directory and JSON. The publisher retains old snapshots.

The published title is now `Interactive World Isochrone Map | Isochronic
Passage Chart`. Search/social descriptions, the WebApplication description and
alternate name, an explanatory HTML section, the noscript introduction and
repository/llms summaries describe the interactive world isochrone map. The
canonical URL remains the root and sitemap lastmod is 2026-10-25. Structured
JSON and XML parsed successfully and the live HTML contains the intended
title, canonical and readable introduction. Search rankings/indexing have not
been claimed or verified. The final deploy gate passed 731 tests and the full
browser check passed all four viewports, searches, permalink restoration,
screen-reader announcements, folded-sheet behavior and console checks.

Final single-run measurements with browser cache cleared:

| Metric | Initial desktop, direct origin | Final desktop, Cloudflare | Initial mobile simulation | Final mobile simulation |
| --- | ---: | ---: | ---: | ---: |
| LCP | 0.76 s | 5.66 s | 5.99 s | 5.28 s |
| Basic map and city times ready | 1.43 s | 6.65 s | 6.70 s | 7.25 s |
| Initial transfer | 9.78 MB | 3.09 MB | — | 3.10 MB |
| Initial fine-array requests | 2 | 0 | 2 | 0 |

The final runs reached LAX; payload reduction is established, an improvement
in local load time is not. These are lab observations, not field percentiles.
Mobile settings were 4 Mbps down, 150 ms latency and 4x CPU slowdown. The
initial mobile transfer total is omitted because its override request did not
complete during that measurement. Mobile CLS remains 0.197 from the existing
late bottom-sheet layout, so no claim of passing all Core Web Vitals is made.

Regional routing check: the operator's Korean IPv4 connection reached LAX,
while the Seoul origin reached ICN; both trace responses said KR and WARP off.
Official Cloudflare documentation says ingress cannot be pinned by zone or
account; Regional Services controls decryption/processing regions instead.
An independent final QUIC client also verified the original server directly:
ALPN h3, robots.txt 200, and a PMTiles 206 response with exactly 127 bytes.

Operational constraint: existing snapshots remain available. A future full
rebuild needs space alongside retained data; the current disk may require
expansion or an explicitly planned retirement of old releases. No paid
Cloudflare service was enabled.
