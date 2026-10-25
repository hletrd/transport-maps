# Adaptive data delivery and first contentful paint

Historical rollout record. The subsequent map-loading rollout changed request
priority and loading feedback. See [Site delivery](../../docs/site-delivery.md)
for current behavior and the combined measurement index.

The owner requested the overseas delivery improvements and reported slow
first contentful paint in an actual desktop browser. The main page remains
DNS-only to Seoul. This rollout adds a separate data CDN and reduces the
requests that block first paint.

## Implemented

- `worldmap-data.atik.kr`: proxied A record, data-only nginx site, separate
  ECDSA certificate, fixed-origin CORS and Resource Timing access. Only
  versioned public data and a 16 KiB probe are available; API/page paths 404.
- `delivery.js`: direct startup, post-FCP warm/timed probes, 20%/20 ms CDN
  threshold, five-minute session hint, Save-Data bypass. Requests remain
  pinned to one release. CDN status/body/range failures and bounded timeouts
  retry the same origin URL/range and keep that page direct. Cancellation
  does not retry. PMTiles retains canonical cache keys and ETag handling.
- Publication embeds self-hosted font declarations and MapLibre layout CSS.
  The complete unchanged vendor stylesheet activates after FCP and load;
  native control icon data URLs do not inflate the critical HTML. Ordinary
  HTML/CSS comments are removed from published output, preserving inline
  script bytes for CSP, quoted strings and licence notices.
- Privacy text, operational docs, Cloudflare helper host selection and
  deployment preflight updated. The helper must match the installed SHA256
  before any upload, and every application module must be published.

## Measurements and verification

The final release selects assets `29aa7c6c2ff0c50f6000` and retains dataset
`9b76cbb9-20261021T010348Z-ef047cca24d7852c`. No model or dataset rebuild.

Three ordinary desktop cold-cache loads at 1280×800, without CPU/network
throttling, measured FCP 220, 240 and 156 ms. Each connected directly to
130.162.144.168 over HTTP/2, rendered 60 city rows and the map, and reported
no JavaScript errors. External stylesheet requests were nonblocking and all
route probes started after FCP. Map-ready polling measured 1.24, 1.18 and
3.11 s: first paint and full map readiness are different measurements.

A controlled 390×844 comparison used 4 Mbps download, 4× CPU, HTTP/2,
empty browser cache and 150 ms injected delay on every request. Navigation
TTFB confirmed the delay (161 ms before / 168 ms after). FCP fell from
860 to 340 ms, about 60%. Basic map readiness was 5.83 / 6.01 s and LCP
5.05 / 5.20 s, so this establishes a first-paint gain, not a full-map gain.
Initial transfer remained about 3.15 MB; no initial fine-array downloads.
Standard network emulation had not applied navigation latency consistently,
so only the explicitly injected-delay comparison is used here.

Actual Globalping HTTP probes downloaded the public 16 KiB file, including
DNS/TCP/TLS setup, from the same three probes on repeated runs:

| Probe | Direct repeat | CDN cold | CDN warm (HIT) | Edge |
| --- | ---: | ---: | ---: | --- |
| Buffalo, US | 1196 ms | 1227 ms | 328 ms | ORD |
| Falkenstein, DE | 1269 ms | 1504 ms | 92 ms | FRA |
| Singapore | 527 ms | 780 ms | 236 ms | SIN |

These are downloads, not overseas browser FCP or a global guarantee. Cold
CDN requests were slower in these samples. The operator's normal browser
selected direct, while a controlled test delaying only the direct probe
selected CDN, rendered Tokyo with 20 successful CDN PMTiles 206 responses,
then recovered Paris after a deliberately failed CDN request. The retry
used exactly the same `bytes=0-16383` range and release on the origin,
rendered the map, latched direct and recorded one fallback with no uncaught
JavaScript exceptions. This is failure injection, not an overseas browser.

Validation: 765 page-gate tests, 81 publisher/deploy/Cloudflare tests, ruff,
and the complete live browser gate at 1280×800, 820×1180, 390×844 and
844×390 passed. Deliberate mutations of route selection, release/auth
boundaries, fallback, cancellation, late probes, PMTiles keys, range length,
FCP scheduling, font rebasing, icon deferral, CSP preservation, publisher
checksum, asset manifest and DNS host boundaries were rejected by tests.
Mutations used isolated copies, leaving deployed sources intact.

## Rollout incident and recovery

The first adaptive page upload used an older root-owned publisher, omitting
`delivery.js` from its immutable snapshot. Browser startup failed. The
installed publisher was updated and the page republished; the bad immutable
snapshot was not modified. The initiating SSH shell also lacked
`agent-browser` on PATH. The new preflight checks both conditions before
upload. Final deployment ran the complete browser gate successfully.

nginx and Cloudflare pre-change state is retained under
`/var/backups/worldmap-20261025-adaptive/`, including a credential-free 0600
Cloudflare backup. Source config is in `deploy/`; infrastructure notes are
also maintained in nas-ops. To remove adaptive delivery, remove the CDN meta
tag and deploy through the gates; data then stays direct. Do not enable the
main hostname's proxy to roll back this feature.

References: [render-blocking CSS](https://web.dev/articles/critical-rendering-path/render-blocking-css),
[Paint Timing](https://developer.mozilla.org/en-US/docs/Web/API/PerformancePaintTiming),
[Cloudflare cache status](https://developers.cloudflare.com/cache/concepts/cache-responses/),
[Globalping API](https://globalping.io/docs/api.globalping.io).
