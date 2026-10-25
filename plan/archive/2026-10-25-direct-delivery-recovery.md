# Direct delivery recovery

Historical recovery record. The main hostname remains direct, and a separate
adaptive data CDN was subsequently deployed. See
[Site delivery](../../docs/site-delivery.md) for the current state.

The owner reported severe map loading delays after the Cloudflare rollout and
asked how overseas access would work without it.

The Korean operator connection still reached Cloudflare LAX, while a direct
request to the Seoul origin returned in about 32 ms. The worldmap A record's
proxy flag was changed to false, preserving its address `130.162.144.168` and
the zone's other records and settings. Google's public DNS returned the origin
address, and ordinary HTTPS requests subsequently returned nginx responses.
The pre-change record is backed up on the origin at
`/var/backups/worldmap-20261025-release/cloudflare-before-direct.json`.

The recovery keeps origin HTTP/3, immutable browser caching, regional data
loading and SEO. Overseas visitors now connect directly to Seoul too. No
separate CDN hostname or automatic route selection has been implemented.
Those would require their own cross-region performance validation; a blanket
proxy switch must not be presented as a demonstrated performance gain.

One desktop run with browser cache cleared and the origin address selected
explicitly measured:

| Metric | Cloudflare LAX run | Direct recovery run |
| --- | ---: | ---: |
| Document first byte | 1.32 s | 0.030 s |
| LCP | 5.66 s | 0.468 s |
| Basic map and city times ready | 6.65 s | 0.864 s |
| Initial transfer | 3.09 MB | 3.08 MB |

The globe, 60 displayed city rows and tiles loaded, with no console errors and
no initial fine-array requests. This is a single local lab comparison, not a
worldwide speed guarantee. The supplementary mobile emulation did not apply
the requested latency to navigation consistently, so its timing is not used
for the recovery claim. Overseas browser latency was not established.

The setup helper now preserves DNS proxying and edge protocol settings by
default; re-enabling them requires `--enable-proxy`. Tests cover both initial
proxy states, and removing that opt-in guard makes the regression test fail.
Privacy and operational documentation describe the current DNS-only mode.
The targeted tests passed (38), and the page deployment gate and all four
viewport/browser checks passed.
