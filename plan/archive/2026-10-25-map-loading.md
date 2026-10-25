# First map and departure-change loading

The owner reported slow first-view detail, slow departure changes, an
unexplained grey globe, and a request taking five seconds to first response.
They also asked whether HTTP/3 and Server Push could accelerate PMTiles.

## Diagnosis

Actual browser PMTiles responses negotiated h3. Both worldmap virtual hosts
have `http3 on`; the nginx http-level default remains off for other sites.
Cloudflare supports visitor-to-edge HTTP/3, not edge-to-origin HTTP/3.
Server Push is not a practical browser delivery strategy: Chrome removed
HTTP/2 Push and HTTP/3 push is not widely implemented. No blanket protocol
or proxy switch was made.

On the operator connection, fresh direct requests generally received first
bytes in 30–40 ms. One TCP connection took 1.01 s, with TTFB 1.28 s including
that handshake. The host had load 0.07, about 10 GB available memory, no swap
activity and 99–100% idle CPU during sampling. Loopback HTTPS requests also
responded in about 40 ms including TLS. This does not reproduce or dismiss
the owner's reported five-second request; its URL/Timing breakdown is still
needed to distinguish a particular route, connection or resource queue.

Browser traces did reproduce delayed PMTiles headers behind concurrent
place-name and route downloads, despite fast individual static requests.
Some PMTiles directory requests repeated byte ranges already received in the
initial 16 KiB header read. A cold CDN probe had additional connection/cache
cost; the normal browser selected the direct route. The diagnostic curl Range
request to modes.bin was a whole-file, uncompressed 200 from the CDN, unlike
the application's normal compressed whole-file fetch, so its 16.5-second
download is not used as an application benchmark.

## Changes

- Register PMTiles and start its shared header promise before MapLibre's
  asynchronous source loading; prioritize its fetches and the basic time
  array. Reuse header-contained directory bytes with a matching strong ETag.
- Defer place names, airport/rail metadata and route breakdowns until map
  sources and tiles have rendered, the camera has stopped and basic times
  are available. Cancellation removes superseded work. Failures and a
  12-second ceiling release optional work rather than withholding it forever.
- Show the selected city's loading state over the globe. At five seconds,
  explain the wait and keep city selection available. Errors stop the
  animation and offer retry. Reduced motion follows the existing policy;
  the existing status region carries announcements. A header alone does not
  count as ready: `areTilesLoaded()` can be true before source metadata arrives,
  so source/style readiness and an actual render are also required.

## Verification

Controlled before/after/after/before comparison: 1280×800, HTTP/2, 4 Mbps
download, 150 ms injected request delay and browser cache disabled. Both
variants' page code was served through the same browser interception harness;
data and vendor requests used the real server. Map-ready times were 5605.5,
3942.3, 3937.0 and 5589.0 ms: about 30% faster for the tested first map.
PMTiles requests fell from 18 to 15 without changing tile bytes or resolution.
FCP was 280, 388, 288 and 284 ms; this change targets map readiness.

Unthrottled h3 preview: initial map 893 ms, Tokyo change 217 ms and London
981 ms. Earlier h3 samples were variable (Tokyo 1.26–1.60 s); the controlled
comparison above is the stronger performance evidence, not a worldwide claim.

Browser fault injection held Seoul's header for over five seconds. The loader
remained visible, optional downloads stayed at zero before map readiness,
and the delayed map subsequently rendered. Loading notices were visible and
unobscured at 1280×800, 820×1180, 390×844 and 844×390. A deliberately failed
Tokyo tile displayed retry, then recovered with no uncaught exceptions.
There were no duplicate header-contained directory requests.

Seven isolated mutations of source readiness, time readiness, queue abort,
failure release, directory reuse, ETag matching and cached-request abort were
rejected by tests. Targeted tests and ruff passed. The final deployment gate
passed 771 tests, and the complete live browser gate passed all four sizes,
city changes, routes, searches, permalinks and console checks. The delayed
header, failure and retry tests were repeated against the actual deployed
assets, without substituting application code, and passed.

Deployed assets: `849f028cff33c26c2b60`. Dataset remains
`9b76cbb9-20261021T010348Z-ef047cca24d7852c`. The installed publisher matches
source and includes `loading.js`. No nginx/DNS/Cloudflare policy or model
change was required for this rollout. The owner's exact five-second TTFB
remains unverified pending the affected request URL and timing breakdown.

References: [Chrome Push retirement](https://developer.chrome.com/blog/removing-push),
[Cloudflare HTTP/3 scope](https://developers.cloudflare.com/speed/optimization/protocol/http3/),
[PMTiles cloud storage](https://docs.protomaps.com/pmtiles/cloud-storage).
