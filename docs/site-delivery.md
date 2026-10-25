# Site delivery and loading

Current behavior checked on 2026-10-25 against application commit `d9025d5`
and the deployed release. Use this page for architecture and measurements,
[deploy/README.md](../deploy/README.md) for operating procedures, and
[web/README.md](../web/README.md) for frontend and vendor details.

## Current deployment

| Item | Current state |
| --- | --- |
| Page, scripts, fonts and APIs | `worldmap.atik.kr`, DNS-only to Seoul |
| Optional public-data CDN | `worldmap-data.atik.kr`, proxied to the same origin |
| Origin | `atik.kr`, `130.162.144.168`, nginx root `/var/www/worldmap` |
| Assets | `/assets/849f028cff33c26c2b60/` |
| Dataset | `/data/9b76cbb9-20261021T010348Z-ef047cca24d7852c/` |
| Authoritative selection | Origin's `.release.json`; HTML pins the same asset and data directories |
| Protocols | Both map virtual hosts enable HTTP/3 and HTTP/2; other sites retain their own settings |
| Cloudflare zone settings | HTTP/3 on, Full TLS, Rocket Loader off |
| Latest application validation | 771 deployment-gate tests and the complete four-viewport browser check passed |

The main hostname stays direct after a Korean connection reached Cloudflare
LAX and regressed. The separate data hostname serves versioned `/data/`, a
fixed 16 KiB probe and certificate challenges; page and API paths return 404.
CORS and Resource Timing access allow the main site's origin. Code, fonts
and computation coordinates remain on the main hostname.

HTTP/3 was observed on actual PMTiles requests. Browsers may still negotiate
HTTP/2. Cloudflare's HTTP/3 setting covers visitors to its edge;
[HTTP/3 to origins is unsupported](https://developers.cloudflare.com/speed/optimization/protocol/http3/).
Server Push is not used: [Chrome removed HTTP/2 Push and documents limited
HTTP/3 Push implementation](https://developer.chrome.com/blog/removing-push).
The application starts required range requests early instead of downloading
entire PMTiles archives.

## Request and loading flow

1. HTML embeds first-paint font and map-layout CSS. The complete vendor
   stylesheet activates after FCP and after loading. Published comment removal
   preserves inline script bytes for CSP and leaves vendor files intact.
2. The page pins one dataset. PMTiles headers and the basic travel-time array
   start before optional route downloads. Directory bytes inside the initial
   16 KiB are reused only with the same strong ETag.
3. A notice names the loading city and shows elapsed time. It stays until
   source/style metadata, rendered tiles, camera movement and basic times are
   ready. A header response or an empty tile queue alone is insufficient.
4. Place names, airport/rail metadata and route breakdowns start after that
   gate, with low fetch priority. Switching cities cancels queued old-city
   work. A map error or a 12-second ceiling releases optional work without
   falsely marking the map ready.
5. At five seconds the notice explains the wait; failures stop its animation
   and offer retry. Reduced-motion preferences are respected. The existing
   `#status` remains the single live region for announcements.

Fine readings and route overrides load by region when needed; there is no
initial worldwide fine-array download. Model, resolution, tile bytes and
door-to-door interpretation are unchanged.

| Component | Responsibility |
| --- | --- |
| [`app.js`](../web/app.js) | Map/city requests, PMTiles registration and optional-data scheduling |
| [`loading.js`](../web/loading.js) | Loading/retry notice, readiness and cancellation |
| [`delivery.js`](../web/delivery.js) | Route selection, origin retry, PMTiles source and header-byte reuse |
| [`detail.js`](../web/detail.js) | Regional fine readings and route overrides |
| [`publish_release.py`](../scripts/publish_release.py) | Immutable snapshots, critical CSS and atomic page publication |

## Data route selection

A fresh session starts direct without waiting for measurements. Subsequent
navigations may reuse a five-minute session hint. After FCP, each path gets a
warm-up and a timed 16 KiB probe: 64 KiB total per page. Save-Data disables
the CDN and probes. Resource Timing excludes JavaScript callback delays.
With both measurements valid, CDN needs more than a 20% improvement and at
least a 20 ms advantage; an available path can also beat an unavailable one.

Only plain GET/HEAD requests for the selected public dataset can change hosts,
without cookies or referrers. APIs, other releases, query strings, Request
objects and custom/authenticated headers retain native fetch behavior. The
page discloses Cloudflare's processing and the session hint.

CDN errors, invalid JSON/ranges, a 1.8-second header timeout, a three-second
body stall or a 30-second whole-body limit retry the identical canonical URL
and range on the origin. That page then stays direct. Caller cancellation
does not retry. PMTiles retains one cache key across both paths.

Successful versioned responses are immutable for a year; errors are
`no-store`. HTML and unversioned compatibility files revalidate. PMTiles and
regional `.r6.bin`/`.over.bin` remain unencoded for ranges; whole-file binaries
retain gzip. Old release directories remain available to open tabs.

## Performance evidence

These are separate lab comparisons, not one end-to-end benchmark or a
worldwide guarantee. FCP measures first content; map readiness measures
usable tiles and city times; TTFB measures response waiting.

| Measurement | Conditions | Result | Record |
| --- | --- | --- | --- |
| FCP | 390×844, HTTP/2, 4 Mbps, 150 ms injected delay, 4× CPU, cold cache | 860 → 340 ms | [FCP rollout](../plan/archive/2026-10-25-adaptive-delivery-and-fcp.md) |
| Desktop FCP | 1280×800, operator connection, unthrottled, cold cache | 156–240 ms across three loads | [FCP rollout](../plan/archive/2026-10-25-adaptive-delivery-and-fcp.md) |
| First map ready | 1280×800, HTTP/2, 4 Mbps, 150 ms injected delay; before/after/after/before | 5.61 / 3.94 / 3.94 / 5.59 s; about 30% faster | [Map-loading rollout](../plan/archive/2026-10-25-map-loading.md) |
| Initial PMTiles requests | Same map-loading comparison, unchanged data | 18 → 15 | [Map-loading rollout](../plan/archive/2026-10-25-map-loading.md) |

The map comparison substituted both variants' page code through the same
browser harness while data and vendor requests used the real server. The FCP
change alone did not improve full-map readiness; the later request ordering
change did. The owner subsequently confirmed a noticeable speed improvement.

Actual US, German and Singapore probe nodes found warm CDN downloads faster
than Seoul for the 16 KiB probe; cold CDN samples were slower. These were HTTP
downloads including connection setup, not overseas browser FCP. See the
[regional measurements](../plan/archive/2026-10-25-adaptive-delivery-and-fcp.md).

Delayed-header and failed-tile browser tests verify that loading stays visible,
optional requests wait and retry recovers without uncaught exceptions. The
notice was checked at 1280×800, 820×1180, 390×844 and 844×390. Unit guards were
mutation-tested; the deployed page passed the complete browser gate.

## Diagnosing another slow request

The owner clarified that the five-second first response was the main document,
`https://worldmap.atik.kr/`, not PMTiles. This is separate from the map-data
download improvements. The five-second root response has not been reproduced.

A 2026-10-25 root-only follow-up measured 25–41 ms to first byte across 12
curl requests using ordinary DNS, a pinned origin address, IPv4 and HTTP/1.1.
The initial browser HTTP/2 navigation took 24 ms; three subsequent HTTP/3
root navigations took 25.8, 36.5 and 109.8 ms, all to `130.162.144.168`.
Both local and public DNS returned the origin A record, with no AAAA or HTTPS
record returned in these checks. Loopback HTTPS took 44 ms including TLS,
and host load was low. No runtime configuration was changed for this check.

An earlier sample took 1.28 s, including 1.01 s establishing TCP. Neither
these measurements nor the owner's speed confirmation identifies the cause
of the original delay. If it recurs, capture the slow root request's Protocol,
Remote Address and Timing breakdown before changing protocols or enabling
the main site's proxy.

In DevTools, record URL, Protocol, Remote Address, status, cache state and
Timing. Distinguish queueing, DNS/TCP/TLS, waiting for headers and content
download. For ranges retain `Range`, `Content-Range`, encoding and
`CF-Cache-Status` too. Browser diagnostics:

```js
window.__dataDelivery?.getState()
document.querySelector('meta[name="worldmap-data-root"]')?.content
```

For an independent curl measurement, substitute the affected public URL and
preserve the browser's Range header when applicable:

```sh
curl --compressed -sS -o /dev/null \
  -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} first=%{time_starttransfer} total=%{time_total} http=%{http_version} ip=%{remote_ip}\n' \
  'https://worldmap.atik.kr/'
```

Curl's `time_starttransfer` includes connection setup; compare its individual
fields with the browser's waiting time. A fast curl request does not rule out
browser congestion, a cold CDN miss or an intermittent connection. Rollback
and backup locations are in the [deployment runbook](../deploy/README.md#recovery).
