# Security review — transport-maps, cycle 2

Reviewer: security-reviewer (read-only pass). Date: 2026-09-10.
HEAD reviewed: `bf9e5cc80f06d29b6609d974bef98ac38d8d11f9` (branch `feat/transport-pipeline`; working tree clean at review time).
Scope: OWASP Top 10 as it applies to a static map page plus a data pipeline — XSS sinks, CSP and headers, third-party policy, supply chain, secrets, path handling, deploy publication, SSRF/URL handling, deserialisation, archive extraction, subprocess, disclosure files.
Finding IDs continue cycle 1's sequence (SEC-1 … SEC-17 are cycle-1 IDs; new findings start at SEC-18) so an ID means one thing across cycles.

Every claim below was validated from the code in this checkout, from HEAD requests against the public site, or from a web search made today. Nothing was run from the pipeline, nothing under `dist/`/`data/` was written, no packages were installed, no browser was used.

## Inventory (every file read in full unless marked *grep*)

- Page: `/Users/hletrd/flash-shared/transport-maps/web/app.js` (1126 lines), `web/index.html` (479), `web/llms.txt`, `web/robots.txt`, `web/sitemap.xml`, `web/README.md`, `web/vendor/fonts.css`; `web/vendor/maplibre-gl.js`, `pmtiles.js`, `h3.js`, `fflate.js`, `maplibre-gl.css` (*grep*: banners, imports, `removeAttributes`/`sanitize`, external `url(`/`https://`; sha256 recorded below).
- Deploy: `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap.atik.kr.conf`, `deploy/worldmap-security-headers.conf`, `deploy/README.md`.
- Scripts: `/Users/hletrd/flash-shared/transport-maps/scripts/adsb_extract.py`, `browser_verify.sh`, `build_water_tiles.py`, `calibrate_ground.py`, `check_ramps.py`, `deploy_verify.sh`, `expand_origins.py`, `ground_check.py`, `osm_rail.sh`.
- Sources: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/__init__.py`, `_utils.py`, `airports.py`, `countries.py`, `landmask.py`, `osm.py`, `roads.py`, `routes.py`, `urban.py`, `wikidata.py`.
- Emit: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/__init__.py`, `airports_json.py`, `borders.py`, `hover.py`, `index.py`, `itinerary.py`, `modes.py`, `places.py`, `rail_detail.py`, `routes_json.py`, `tiles.py`, `water.py`.
- CLI and config: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py`; `config.py` and `calibrate/ground.py` (*grep*: paths, API-key handling).
- Project: `/Users/hletrd/flash-shared/transport-maps/pyproject.toml`, `.gitignore`, `uv.lock` (names/versions only), `tests/test_licence_firewall.py`, `data/origins.toml` (*programmatic*: slug regex and markup scan over all 553 entries).
- Context: `CLAUDE.md`, `.context/reviews/cycle-1/_aggregate.md` (sections E, I), `.context/reviews/cycle-1/security-reviewer.md`, `plan/2026-09-10-c1-security-and-policy.md`, `git log ac191db..HEAD`.
- Live host (read-only HEAD/GET, no ssh): headers for `/`, `/app.js`, `/index.json`, `/hover_cells.bin`, `/origins/seoul.pmtiles`, `/vendor/maplibre-gl.js`, `/robots.txt`, `/.git/HEAD`, `/.index.json.tmp`; status of `/vendor/`, `/origins/`, `/origins/las-vegas.pmtiles-journal`; bodies of `/` and `/app.js` grepped for third-party hosts.
- Local state (read-only): `dist/` top-level listing and modes, `dist/origins` mode histogram, stray-file `find` over `dist/` and `web/`, `~/.config/transport-maps/` listing (metadata only).

## Summary

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 0 | — |
| High | 0 | — |
| Medium | 4 | SEC-18, SEC-19, SEC-20, SEC-22 |
| Low | 5 | SEC-23, SEC-24, SEC-25, SEC-26, SEC-27 |
| Still open from cycle 1 (one line each) | 9 | SEC-7, SEC-8/I3, SEC-9, SEC-11 (partial), SEC-12, SEC-13, SEC-15, SEC-16/I5, SEC-17 |
| Closed by cycle 1 (verified) | 5 | SEC-3/I1, SEC-5, SEC-14, SEC-6 (disclosure half), SEC-1/SEC-2 (repo half) |

The five that matter most, in order: **SEC-19** (the corrected CSP has never been exercised against the page; its first test will be production), **SEC-20** (the deploy gate still cannot fail on a missing header or a stray file — a sqlite journal is being served from the live host right now), **SEC-18** (reverse geocoding on every map click against a per-application 1 req/s policy), **SEC-22** (MapLibre CVE-2026-85061 has no 5.x fix; patch the vendored bundle), and the blocked-on-owner **E3 server half**, which the live headers show is still uninstalled.

No secrets were found in the tracked tree. The Routes API key is read from the environment only (`calibrate/ground.py:59`), sent only as `X-Goog-Api-Key` (`:77`), and `~/.config/transport-maps/env` is mode 0600.

---

## XSS: every DOM-write site in `web/app.js`

`esc()` is defined at `app.js:31-32` and escapes `& < > "` (not `'`; every attribute it feeds is double-quoted, so that is sufficient today). No URL, hash or `postMessage` input reaches the page at all (`grep` for `location.hash|location.search|URLSearchParams|window.name|postMessage|document.write|eval|new Function|insertAdjacentHTML|outerHTML` finds none), so the only external strings are dataset strings.

| Line | Sink | Interpolated values | Status |
| --- | --- | --- | --- |
| 596 | template → `innerHTML` at 660 | `a[1]`, `a[2]` (OurAirports name/country from `airports.json`), `code` (IATA from `origins/{slug}.json`) | all `esc()` |
| 600 | template → 660 | `tip` = `meta.modeDetail[name]` (index.json) `esc()`; `name` from the static list at 610 | escaped / static |
| 615 | template → 660 | `mode(name)` (see 600); `railVia(i)` (OSM station + line from `.rail.json`) wrapped in `esc()` | escaped |
| 625, 642, 650 | static strings | — | static |
| 627, 631, 632, 638, 646 | template → 660 | `ap(code)` (escaped, see 596); `dur()` numeric | escaped / numeric |
| 660 | `ds.innerHTML = text` | the rows composed above | covered |
| 700 (`describe`) → 719 | template → `innerHTML` at 714 | `lead`/`where` = GeoNames name, region, country from `places.json` | `esc()` on both |
| 712 | `$("time").innerHTML` | `big`, `unit` from `fmtTime()` | numeric / static |
| 714-720 | `$("where").innerHTML` | `esc(active.name)` (origins.toml via index.json), `describe()`, `fmtCoord()` numeric, `band` from `bandRangeAt()` (numbers and two literals) | escaped / numeric |
| 728 | `tip.innerHTML` | `big`/`unit` numeric; `where` (GeoNames) in `esc()` | escaped |
| 1060 | `t.innerHTML = "<span></span>"` | — | static |
| 448 | `setAttribute("transform", …)` | `map.getBearing()` | numeric |
| 219-221 | `a.href = s.url`, `a.textContent`, `append()` | `meta.attribution[].url/name/licence` (index.json, generated from the constant `ATTRIBUTION` in `emit/index.py:22-78`) | `href` is unvalidated (a `javascript:` URL would need a repo edit and is blocked by the CSP once it is live); text via `textContent` |
| 251, 254, 498, 524, 767, 776, 842, 845, 857, 860, 885, 897-898, 906, 909, 914, 1078, 1095, 1110, 1123 | `textContent` / `append(string)` | GeoNames, OurAirports, Nominatim `display_name`, origin names | safe by construction |
| 839, 854, 903-904, 1016 | `dataset.*` | airport code, slug, Nominatim lat/lon and `display_name` | attribute storage; consumed via `textContent` (942 → 759-767) |
| 463, 484-512 | fetch / `pmtiles://` URLs | `o.slug` from index.json | first-party; see SEC-26 for slug validation |

Conclusion: **I1 is complete.** Every dataset string that reaches `innerHTML` passes through `esc()`, and the remaining sinks are numeric, static, or `textContent`.

---

## Findings

### Medium

### SEC-18 — Reverse geocoding fires on every map click; the Nominatim limit is per application, not per visitor

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:786-795` (`map.on("click")` → `reverseGeocode(lat, lng)` unconditionally), `:921-937` (`fetch(`${NOMINATIM}/reverse?…`)` with no throttle; `reverseSeq` discards stale *responses* but never suppresses a *request*), `:759` (the label is shown in the Route panel with no attribution beside it — the only Nominatim credit is under search results, `:912-915`, and in the closed Sources panel, `:204-208`).
- **Why it is a problem:** the OSMF Nominatim usage policy (fetched today) sets "an absolute maximum of 1 request per second" and states that limits apply per application with the combined traffic of all users required to stay within them. "Click anywhere on the chart to set a destination" (`index.html:408`) is the page's primary interaction, so every click by every visitor is one Nominatim request; a single visitor clicking around the globe exceeds 1 req/s on their own, and the site as a whole exceeds it with a handful of concurrent visitors. Cycle 1's E4 fix addressed the *search* pattern (autocomplete, now explicit at `:965-990`); the click pattern was not part of it and is the larger source of requests.
- **Failure scenario:** OSMF throttles or blocks the site's Referer; `reverseGeocode` swallows the error (`:936`), so the visible effect is that addresses quietly stop appearing — and, since the same policy covers the search endpoint, address search stops too, exactly the silent loss `web/README.md:10-14` now promises not to have.
- **Fix:** (1) a minimum spacing of 1,100 ms between Nominatim requests (search and reverse combined) with the latest click winning; (2) reverse-geocode on request rather than on every click — a small "Get address" action in the pins box, or only while the Route panel is open — the gazetteer name from `places.json` is already shown instantly; (3) cache by rounded coordinate so repeated clicks near one place cost nothing; (4) put "address by Nominatim © OpenStreetMap contributors" beside the reverse-geocoded label, as the search list already does; (5) record the aggregate request rate as the trigger for the owner's provider decision (E4 policy).

### SEC-19 — The corrected CSP has never been exercised against the page; its first test will be production

- **Severity:** Medium  **Confidence:** High (that it is untested) / Medium (that it will break something)  **Status:** Needs manual validation  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap-security-headers.conf:18` (the new policy), `deploy/README.md:53-55` (verification is `curl -sI … | grep`, presence only), `scripts/deploy_verify.sh:57-62` (status codes only), `scripts/browser_verify.sh:75` (console error count, but only after the deploy).
- **Evidence:** HEAD requests today show the live host sends **no** CSP on `/`, `/app.js`, `/index.json`, `/hover_cells.bin`, `/origins/seoul.pmtiles`, `/vendor/maplibre-gl.js` (only `cache-control: no-cache`); the pre-fix CSP (`connect-src 'self'`, no gtag hosts, no hash) appears only on `/robots.txt` and 404s; the live `/` body contains none of `googletagmanager.com`, `google-analytics`, `G-…`, and the live `/app.js` contains no `nominatim.openstreetmap.org`. So no version of this page has ever been rendered under any CSP: not the old one, not the new one. The new policy adds five things at once — an inline-script hash, `blob:` workers, the gtag loader host, the GA collection hosts, and Nominatim — and the page's failure mode when any of them is wrong is the documented blank globe (MapLibre's worker is a blob URL: `web/vendor/maplibre-gl.js` creates it from an embedded source string; if `worker-src blob:` were mis-parsed, no tile ever renders).
- **What I did verify statically:** the hash in the snippet equals sha256 of the exact inline script text in `web/index.html:6-11` (`sha256-pCkIJ0WqstDvWvix9v7v2C15fx9jgy6oPf71TIqllqU=`, recomputed; identical in `dist/index.html`); `worker-src 'self' blob:` and `script-src … blob:` cover the worker; `connect-src 'self'` covers the PMTiles range fetches and `./*.json|.bin`; `font-src 'self'` matches `web/vendor/fonts.css` (all `url(./…)`); `maplibre-gl.css` has no external `url(`; `style-src 'unsafe-inline'` is needed by the `<style>` block and the five `style=` attributes; the Google hosts match Google's own CSP guide for GA4 (script `www.googletagmanager.com`, img/connect `*.google-analytics.com`, connect `*.analytics.google.com`) except the `*.google.com` / `*.g.doubleclick.net` entries the guide lists, which are only used by Google-signals/ads features (see SEC-24).
- **Fix:** rehearse before installing. Either serve a scratch copy of `dist/` behind nginx with the snippet (a one-container nginx is enough), or inject the same policy as `<meta http-equiv="Content-Security-Policy">` into a scratch copy of `index.html` (meta CSP ignores `frame-ancestors` and `report-*`, everything else is enforced) and run `scripts/browser_verify.sh http://127.0.0.1:8899/`: the canvas, water features, route, address search and zero console errors together prove the policy fits the page. Then make `deploy_verify.sh` step 3 assert `content-security-policy` and `strict-transport-security` on `/`, `/app.js`, `/index.json`, `/hover_cells.bin` and a `.pmtiles`, and add a `report-to`/`Reporting-Endpoints` pair so a future violation is visible somewhere other than a visitor's console.

### SEC-20 — The deploy gate still cannot fail on a missing header, a stray file or a truncated JSON sidecar; a sqlite journal is being served from the live host now

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (live)  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/scripts/deploy_verify.sh:54-55` (`rsync -a --exclude 'README.md' web/ dist/` then `rsync -a --delete --info=progress2 dist/ atik.kr:/var/www/worldmap/ 2>&1 | tail -c 200`), `:9-37` (checks `.bin/.air.bin/.modes.bin/.rail.bin` lengths and `.pmtiles` existence; never opens `{slug}.json` or `{slug}.rail.json`), `:57-62` (HTTP status only); `deploy/worldmap.atik.kr.conf:75-77` (no `location ~ /\.` deny, no `*-journal|*.tmp|*.part` deny); `src/transport_maps/sources/_utils.py:76,85` (`.<name>.XXXX.tmp` inside the target dir; mode `0o666 & ~umask`).
- **Evidence:** `dist/origins/las-vegas.pmtiles-journal` (25 KB, 9 Sep 07:03, a sqlite rollback journal from a tippecanoe run that died before `emit/tiles.py` moved to local temp staging) is in `dist/` today, and `curl -I https://worldmap.atik.kr/origins/las-vegas.pmtiles-journal` returns **200**: the previous deploy shipped it and nginx serves it. `dist/` and `dist/origins` are otherwise uniformly `0644` (796 files), so the mode concern is latent (umask-dependent), not present.
- **Why it is a problem:** `--delete` mirrors `dist/` exactly, so anything a crashed build leaves behind (`.index.json.abcd.tmp`, `*.pmtiles-journal`, `water.pmtiles.part`, a macOS `.DS_Store` in `web/`) is published, and the gate cannot notice. A truncated `{slug}.json` from a build killed mid-`write_text` (`emit/routes_json.py:57`, `rail_detail.py:109`, `index.py:140` and `hover.py:72` all write in place, not through `_atomic_write`) passes step 1, deploys, and the page then silently shows no route (`app.js:512-519` swallows the parse error). `tail -c 200` leaves a failed partial sync with 200 bytes of diagnostics. This is I4 + SEC-7 with the "would be served" now observed.
- **Fix:** `rsync -a --delete --delete-delay --delay-updates --chmod=D755,F644 --exclude '.*' --exclude '*.tmp' --exclude '*.part' --exclude '*.partial' --exclude '*-journal' dist/ …` (drop `| tail -c 200`; log to a file); before the transfer, `find dist \( -name '.*' -o -name '*-journal' -o -name '*.tmp' -o -name '*.part*' \) -print -quit | grep . && exit 1`; parse every `origins/*.json` and `*.rail.json` with `json.load` in step 1; `location ~ /\. { deny all; }` and `location ~* \.(tmp|part|partial|journal)$ { deny all; }` in the conf; `os.chmod(tmp_path, 0o644)` in `_atomic_write` (these are public artifacts; there is no case for group/other write); route the seven direct writers through `_atomic_write`.

### SEC-22 — MapLibre GL JS 5.24.0 carries CVE-2026-85061 and no 5.x fix exists or will; patch the vendored bundle and pin the mitigation with a test

- **Severity:** Medium (unchanged from SEC-4/I2)  **Confidence:** High  **Status:** Confirmed present, not reachable as configured  **Effort:** S (patch) / M (6.x migration)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/vendor/maplibre-gl.js` (banner: `maplibre-gl@5.24.0`; sha256 `c51e43e8…88a332b0b`). The vulnerable loop is present verbatim: `static removeAttributes(t){for(const{name:n,value:a}of t.attributes)pe.isPossiblyDangerous(n,a)&&t.removeAttribute(n)}` — iteration over the live `NamedNodeMap` while removing from it — reached from `sanitize(t){…pe.clean(n),n.innerHTML}` in the attribution control's update.
- **What the web search established today:** GitHub advisory GHSA-jrc7-96c5-q579 / CVE-2026-85061, published 2026-08-19, affected `<= 6.4.0`, patched `6.4.1`; the advisory mentions no backport; MapLibre's April-2026 newsletter names 5.22–5.24 as the final 5.x releases; npm `latest` is 6.9.0. **There is no 5.x patch release and none is coming.** The advisory's stated workaround is sanitising the attribution string before it reaches MapLibre.
- **Mitigating facts (re-verified):** `web/app.js:344` `attributionControl: false`; `web/index.html:107` hides `.maplibregl-ctrl-attrib`; no `AttributionControl` is added anywhere; the only attribution input would be the PMTiles metadata `attribution` field, which is first-party. **No test guards any of this** (`grep attributionControl tests/` is empty).
- **Fix:** (a) patch the vendored file: `for(const{name:n,value:a}of Array.from(t.attributes))` — one token — and record the patch, the pre- and post-patch sha256 and the advisory ID in `web/README.md`; (b) add a test that asserts `attributionControl: false` in `app.js`, that no `AttributionControl` is constructed, and that `web/vendor/maplibre-gl.js` contains `of Array.from(t.attributes))` (mutate the vendored file to prove it goes red, per `CLAUDE.md`); (c) keep the 6.x migration as a separate task with the tile-loading retest `web/README.md:28-34` describes — pmtiles 4.5.0 plus MapLibre 6.9.0 should be tried before assuming the 6.x blocker still holds.

### Low

### SEC-23 — `adsb_extract.py` downloads whatever URL the GitHub API hands it, with any scheme, to a path built from the tag name

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (extends SEC-13)  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/scripts/adsb_extract.py:96-104` (`rel["tag_name"]`, `a["browser_download_url"]` taken verbatim from the API JSON), `:110` (`target = cache / f"{tag}.tar"` — tags may contain `/` and `..`), `:116-121` (`urllib.request.urlopen(u, timeout=900)` for every asset, unbounded size; `urllib` also opens `file://` and `ftp://`).
- **Failure scenario:** a compromised or spoofed release (the request itself is TLS, so this needs the upstream account or GitHub) can make the script write outside `~/adsb-cache` or read a local file into the archive; more realistically, a mis-tagged release fills the disk.
- **Fix:** `re.sub(r"[^A-Za-z0-9._-]", "_", tag)`; `urlsplit(u).scheme == "https"` and host in `{"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}`; cap total bytes (the daily archives have a known size class); the streaming `tarfile` reader with `extractfile` only (`:149-157`) is correct and should stay.

### SEC-24 — CSP hardening: `script-src blob:` is broader than needed, `object-src` is unspecified, no reporting, and the GA host list will silently drop optional Google beacons

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap-security-headers.conf:18`.
- **Why:** `worker-src 'self' blob:` already covers MapLibre's worker in every browser that ships globe projection, so `blob:` in `script-src` only widens what an injected script could load; `object-src` falls back to `default-src 'self'` (same-origin plugins allowed — set `'none'`); there is no `report-to`, so the first sign of a violation is a visitor's console (see SEC-19); Google's GA4 CSP guide (fetched today) lists `https://*.g.doubleclick.net https://*.google.com https://*.google.<TLD>` for connect/img when Google signals or ads linking are on — the property is presumably plain, but if that is ever switched on the beacons vanish without a trace.
- **Fix:** `script-src 'self' https://www.googletagmanager.com 'sha256-…'; worker-src 'self' blob:; object-src 'none'; …; report-to csp` plus a `Reporting-Endpoints: csp="https://…"` header (or `report-uri` to a tiny endpoint / a hosted collector); document in `deploy/README.md` that enabling Google signals requires the extra hosts. Note the inline gtag bootstrap could move into `app.js` (drop the hash and the inline script entirely); `deploy/README.md:60-62` already warns that editing the snippet changes the hash.

### SEC-25 — Supply-chain status: unused `selectolax` still declared, no recorded vendor hashes, no audit step; the locked Python set is clean against this year's advisories

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (I5 still open)  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/pyproject.toml:20` (`selectolax>=0.4.11`; `git grep selectolax -- src scripts tests` finds no use); `web/README.md:16-26` (no hashes); no `pip-audit`/`osv-scanner` anywhere; `.venv` has no `pip_audit` module (so the brief's audit could not be run without installing).
- **Sweep (today):** vendored: maplibre-gl 5.24.0 `c51e43e8…`, pmtiles 4.5.0 `ea53f031…`, h3-js 4.2.1 `fcaa69b1…`, fflate 0.8.3 `d22d6035…`, fonts.css `2c6b4a19…`, maplibre-gl.css `ab1e70d5…` (sha256 prefixes; full values in the final-sweep table). Web search found no advisories for pmtiles 4.5.0, h3-js 4.2.1 or fflate 0.8.3; MapLibre is SEC-22. Python (from `uv.lock`, 33 packages): `urllib3 2.7.0` is the fixed version for CVE-2026-44431 (header leak on cross-origin redirect) and CVE-2026-44432 (decompression DoS) — both fixed in 2.7.0, so the lock is clean; `requests 2.34.2` is past CVE-2026-25645 (fixed 2.33.0); `pyarrow 25.0.1` has no advisory I could find (the only published one is CVE-2023-47248, fixed in 14.0.1). `requests`/`urllib3` enter only through `osmium`. The jsDelivr banners on all four vendored bundles say "Do NOT use SRI with dynamically generated files" — that applies to re-downloading, not to pinning the bytes you have.
- **Fix:** remove `selectolax`; add a `vendor.lock` (or a table in `web/README.md`) with the sha256 of each vendored file and a test that recomputes them; add `uvx pip-audit` (or `osv-scanner --lockfile uv.lock`) to the pre-deploy checklist; add `integrity=` to the three `modulepreload` links and the `app.js` script tag (same-origin SRI is valid and catches a half-written upload).

### SEC-26 — Origin slugs are still validated only on `solve --name`; `expand_origins.py` still writes names into TOML unescaped

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (SEC-12 still open)  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:32-42` (`_SLUG_RE` applied by argparse only, `:244`), `:100,116-124` (`out / f"{slug}.pmtiles"` … from `origins.toml` unchecked), `src/transport_maps/emit/index.py:81-88` (`load_origins` checks uniqueness only); `scripts/expand_origins.py:97-98` (`name = "{o["name"]}"`, no escaping). Note `_SLUG_RE` also allows a leading `-`, contrary to its own comment at `:32-33` (harmless: every path is absolute).
- **Evidence:** all 553 slugs in `data/origins.toml` match `^[A-Za-z0-9_-]+$` today; three names contain `'` (`Xi'an`, `Huai'an`, `N'Djamena`), which is legal in a TOML basic string and safe in every DOM sink (text or double-quoted attribute); a name containing `"` or `\` would make `expand_origins.py` emit invalid TOML (loud failure, not silent).
- **Fix:** apply `_SLUG_RE.fullmatch` to every slug in `load_origins` and raise; write names with `json.dumps(name)` (valid TOML basic-string quoting for these cases) or `tomli_w`.

### SEC-27 — Verification scripts: fixed `/tmp` paths, a broad `kill -9`, an absolute home path

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (SEC-15 still open)  **Effort:** S
- **Where:** `/Users/hletrd/flash-shared/transport-maps/scripts/browser_verify.sh:18` (`cd /tmp`), `:74,86` (`/tmp/verify_*.png`), `:89` (kills every process whose command line matches `\.agent-browser/|agent-browser` except `Google Chrome.app` — broader than "agent-browser's own Chrome tree"); `scripts/deploy_verify.sh:6` (`cd /Users/hletrd/flash-shared/transport-maps`).
- **Fix:** `cd "$(dirname "$0")/.."`; `mktemp -d`; match the executable path under `~/.agent-browser/browsers/` or the PIDs agent-browser reports.

### Still open from cycle 1 (no new evidence; one line each)

- **SEC-7** — deploy is `rsync -a --delete` in place, non-atomic; `--delete-delay --delay-updates` still absent (`scripts/deploy_verify.sh:55`). Folded into SEC-20's fix.
- **SEC-8 / I3** — licence firewall unchanged: `FORBIDDEN` names no provider actually used, `.json/.geojson/.toml` only, not run by `deploy_verify.sh`; `calibrate_ground.py:38,152` still lets `--out` point anywhere (`tests/test_licence_firewall.py:11-15`, `scripts/deploy_verify.sh`).
- **SEC-9** — downloads still have no hash/size record; `Retry-After` still unbounded (`sources/_utils.py:13-34`); `expand_origins.py:43-45` still `httpx.get` without `follow_redirects` and a non-atomic `write_bytes`; Wikimedia `User-Agent` still has no contact (`routes.py:23`, `wikidata.py:20`); `osm_rail.sh:33-38` still ignores Geofabrik's `.md5`.
- **SEC-11** — partially fixed: `index.json` and `hover_cells.bin` are now checked (`app.js:42-52`, byte length a multiple of 8) and a failure is shown; the per-origin arrays are still never compared to `hoverCells.length` (`app.js:494, 506, 510`).
- **SEC-12** — see SEC-26.
- **SEC-13** — see SEC-23.
- **SEC-15** — see SEC-27.
- **SEC-16 / I5** — see SEC-25.
- **SEC-17** — the JSON-LD now says `conditionsOfAccess` with per-source licences (`web/index.html:59`) rather than a single ODbL `license`, which is the more defensible form; whether that satisfies CC BY-SA for the Wikipedia-derived network is still a legal read, owner's call.

### Closed by cycle 1 (verified from the code)

- **SEC-3 / I1** — every dataset string escaped (table above).
- **SEC-5** — Nominatim search is explicit only: `render()` at `app.js:825-867` never calls `searchAddress`; the two callers are Enter with no local match (`:970-973`) and the button (`:990`). Attribution under results (`:912-915`). The reverse-geocode pattern remains: SEC-18.
- **SEC-6 (disclosure half)** — the Sources panel (`web/index.html:449-452`), `web/llms.txt:60-63` and `web/README.md:10-14` name Nominatim and Google Analytics; the `deploy/worldmap.atik.kr.conf:2-3` comment is correct. Consent is the owner's decision as recorded.
- **SEC-14** — geolocation is on a button only (`app.js:1097-1126`); nothing prompts on load.
- **SEC-1 / SEC-2 (repo half)** — see the regression table.

### Blocked on owner (status only, with today's evidence)

- **E3 server half** — still not installed: the live host sends none of the six headers on any page asset and the pre-fix CSP on `/robots.txt` and 404s. The live build also predates both third-party calls, so installing the *new* conf cannot break the *current* live page; it is the next deploy (which carries gtag and Nominatim) that must go out under the new policy — hence SEC-19's rehearsal. The install commands in `deploy/README.md:49-51` are the right ones (the conf file replaces the old server-level lines wholesale).
- **E4 policy / SEC-6 consent / SEC-17 licence** — unchanged; SEC-18 adds the aggregate-rate evidence to the E4 decision.

---

## Regression check (cycle-1 fixes claimed done)

| Item | Claim (plan) | What I checked | Result |
| --- | --- | --- | --- |
| I1 (f943964) | one `esc()` on every dataset string before `innerHTML` | every DOM-write site in `app.js` (table above); `esc()` covers `& < > "`; no attribute is single-quoted | **Complete** |
| E3 repo half (03988a5) — headers in every location | snippet included at server level and in each `location` with its own `add_header` | `worldmap.atik.kr.conf:29,41,45,52,64,72`; `location /` (`:75-77`) sets no header of its own and inherits the server-level include; `.css`/`.png` fall to it and get the headers | **Complete** for the conf |
| E3 repo half — CSP matches the page | hosts and hash reflect gtag + Nominatim + blob workers | hash recomputed from `index.html:6-11` = snippet value; hosts match Google's GA4 guide and `app.js:874,890,924`; `blob:` worker; fonts/CSS local | **Complete**, hardening in SEC-24 |
| E3 — "documents how to verify with `curl -sI`" | `deploy/README.md` | `:53-55` presence check only; no rehearsal, no gate | **Incomplete** — SEC-19, SEC-20 |
| E4 bounded (1305ba7) | search explicit; attribution; disclosure | `app.js:965-990, 912-915`; `index.html:449-452` | **Complete** for search; reverse geocode per click not covered — SEC-18 |
| E4 docs (e11c830) | README, llms.txt, JSON-LD stop claiming "no third party" | `web/README.md:6-14`, `llms.txt:60-63`, `index.html:59` | **Complete** |
| Live host | (blocked on owner) | HEAD on six page paths + robots + two 404s | Old conf still live; page assets bare |

## Final sweep

| Check | Result |
| --- | --- |
| Secrets in tracked files (`git grep` for Google/GitHub/Slack/OpenAI token shapes, `api_key=`, `secret=`, `password=`, private-key headers; `web/vendor`, `uv.lock` excluded) | none |
| Hosts, emails, usernames, absolute paths in tracked files | `worldmap.atik.kr`/`atik.kr` (public site, deploy target — by design); `pyproject.toml:7` placeholder email `01@0101010101.com` (E13, owner); `scripts/deploy_verify.sh:6` absolute home path (SEC-27); no IPs, no Tailscale addresses, no other emails |
| Untracked/ignored state | `.env` absent; `~/.config/transport-maps/env` mode `-rw-------`; `.claude/`, `.superpowers/`, `__pycache__` ignored and untracked (147 tracked files, none matching `.env|.pem|.key|.DS_Store`) |
| Routes API key | `calibrate/ground.py:59` from `GOOGLE_ROUTES_API_KEY`; sent only as `X-Goog-Api-Key` (`:77`); never printed |
| `shell=True`, `os.system`, `os.popen` | none; `emit/tiles.py:41-61` and `emit/water.py:102-123` are list-form `subprocess.run(check=True)` with constant flags plus pipeline-generated absolute paths; `osm_rail.sh:42-44` `osmium tags-filter` with paths from a fixed list under `$OSM_DIR` |
| `eval` / `new Function` / `document.write` / `insertAdjacentHTML` / `outerHTML` | none in `app.js`; none in the four vendored bundles (grep) |
| URL / hash / `postMessage` / `window.name` input on the page | none |
| Unsafe deserialisation | `np.load(..., allow_pickle=False)` explicit in `contour/grid.py:45,98`; `sources/roads.py:71` relies on the safe default — make it explicit; no `pickle`, `marshal`, `yaml` anywhere; `tomllib`/`json` only |
| Archive extraction | `emit/water.py:79` `ZipFile.extractall` (stdlib strips absolute paths and `..` — zip-slip safe; upstream is osmdata/HydroLAKES over TLS); `roads.py:40-47`, `places.py:50-51`, `expand_origins.py:46-47` read members into memory only; `adsb_extract.py:149-157` streams `tarfile` via `extractfile`, never extracts to disk |
| Path handling | cache names are constants or the basename of constant URLs (`places.py:36`, `water.py:50`, `urban.py:40`); slug gap — SEC-26; upstream tag/URL — SEC-23; `_atomic_write` temp file lives in the target directory (SEC-20) |
| Network clients | TLS verification default-on everywhere (no `verify=False`); timeouts on every `httpx` call (`calibrate_ground.py:73` creates `httpx.Client()` without one but `calibrate/ground.py` passes `timeout=` per request); `follow_redirects=True` on every source (can follow https→http; SEC-9); Nominatim from the browser with the site's origin as Referer (`Referrer-Policy: strict-origin-when-cross-origin`) and `Accept-Language` (CORS-safelisted, no preflight) |
| Third-party policy | Nominatim policy fetched today: 1 req/s per application, no autocomplete, attribution, identifying Referer/UA — search compliant, reverse-geocode SEC-18; Google tag disclosed on the page and in llms.txt; GA4 CSP guide fetched — see SEC-19/SEC-24 |
| Live headers (HEAD, read-only) | `/`, `/app.js`, `/index.json`, `/hover_cells.bin`, `/origins/seoul.pmtiles`, `/vendor/maplibre-gl.js`: `server: nginx` (no version), `cache-control: no-cache`, **no security headers**; `/robots.txt` and 404s: old CSP + HSTS + nosniff + XFO + Referrer-Policy + Permissions-Policy; `/vendor/` 403, `/origins/` 403, `/.git/HEAD` 404, `/.index.json.tmp` 404, `/origins/las-vegas.pmtiles-journal` **200** |
| robots / sitemap / llms.txt disclosure | `robots.txt` allows everything and points at the sitemap; `sitemap.xml` lists `/` only; `llms.txt` links `index.json` (public by design); no internal paths, hostnames or build details leak; JSON-LD names the author by choice |
| Dependency audit | `pip_audit` is not installed in `.venv`, so no audit was run (nothing installed, per the constraints). Locked versions: h3 4.5.0, httpx 0.28.1, numpy 2.5.2, osmium 4.3.1, polars 1.44.1, pyarrow 25.0.1, pyogrio 0.13.0, rasterio 1.5.1, scipy 1.18.1, selectolax 0.4.11, shapely 2.1.2; transitive: requests 2.34.2, urllib3 2.7.0, certifi 2026.7.22, httpcore 1.0.9, anyio 4.15.0, idna 3.19, h11 0.16.0; dev: pytest 9.1.1, ruff 0.16.5. Web-searched today: urllib3 2.7.0 = fix release for CVE-2026-44431/-44432 (clean); requests 2.34.2 past CVE-2026-25645 (clean); pyarrow 25.0.1 no advisory found; pmtiles/h3-js/fflate no advisory found; maplibre-gl 5.24.0 → CVE-2026-85061, fixed only in 6.4.1 (SEC-22) |
| Vendored file hashes (sha256, for `web/README.md` / a `vendor.lock`) | `maplibre-gl.js c51e43e844402c587c55f43ff09de18989cacb80850d2ea7365f21088a332b0b`; `pmtiles.js ea53f031446436ac57b420eeda2cc81092ed8b9b6dcbd15207f1b63495fad0bc`; `h3.js fcaa69b16ddfdd26e8544bf326eeb2c6d25ae3ba94ffa27c0a484cb5318cfd32`; `fflate.js d22d603594fe32208e563d2f2fbe9e53f8addc1c845320786c7de62464c288a8`; `maplibre-gl.css ab1e70d59ec40465bae7e7030da2f3ccf28133fd502e62bd598eefbadfd7a732`; `fonts.css 2c6b4a194338790b27cdfa65a3f06ac64c774bd12ed6c2658904105989e0d35b` |
| Tests guarding the mitigations | none reference `attributionControl`, the CSP hosts, `security-headers`, or the rsync excludes (`grep` over `tests/`) — SEC-22(b), SEC-19, SEC-20 |
| Coverage | every file in the inventory above was read line by line; the four vendored bundles and `maplibre-gl.css` by grep; nothing in the brief's list was skipped |

Sources consulted today: [GitHub advisory GHSA-jrc7-96c5-q579](https://github.com/advisories/GHSA-jrc7-96c5-q579), [GitLab advisory CVE-2026-85061](https://advisories.gitlab.com/npm/maplibre-gl/CVE-2026-85061/), [MapLibre newsletter April 2026](https://maplibre.org/news/2026-05-02-maplibre-newsletter-april-2026/), [npm maplibre-gl latest](https://registry.npmjs.org/maplibre-gl/latest), [Google tag CSP guide](https://developers.google.com/tag-platform/security/guides/csp), [OSMF Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/), [urllib3 CVE-2026-44431](https://www.sentinelone.com/vulnerability-database/cve-2026-44431/), [urllib3 CVE-2026-44432](https://www.sentinelone.com/vulnerability-database/cve-2026-44432/), [requests CVE-2026-25645](https://www.sentinelone.com/vulnerability-database/cve-2026-25645/), [pyarrow advisories (GitLab)](https://advisories.gitlab.com/pkg/pypi/pyarrow/).
