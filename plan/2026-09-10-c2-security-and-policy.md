# Plan (cycle 2): escaping, headers, third-party policy, supply chain

Source findings: `.context/reviews/_aggregate.md` section Q, L5, L13, plus every
unfinished task carried from
`plan/archive/2026-09-10-c1-security-and-policy.md` (I2, I3, I4, I5, G2/SEC-9;
blocked-on-owner E3 server half, E4 policy, SEC-6 consent). Per-agent detail:
`security-reviewer.md` (SEC-18…27 with the DOM-write table and live headers),
`critic.md` (CRIT-20), `document-specialist.md` (DOC-4, DOC-12), `architect.md`
(ARCH-9, ARCH-14, ARCH-15), `debugger.md` (DBG-9).

Security findings are not deferred. Where a step needs the owner (a change on
the production server), the repo-side change lands now and the server-side
step is recorded as blocked-on-owner, per the global rule that production and
header/firewall changes require explicit confirmation.

I1 (escaping) is verified complete this cycle: every dataset string that
reaches `innerHTML` passes `esc()`; the remaining sinks are numeric, static or
`textContent`; no URL/hash/`postMessage` input exists (security-reviewer's
DOM-write table).

## Cycle 2 (this run)

- [x] **Q1** Nominatim rate: one request per 1,100 ms across search and reverse
      with the latest click winning; no reverse request for water/unreachable
      clicks; results cached by rounded coordinate; the reverse-geocoded label
      carries "address by Nominatim © OpenStreetMap contributors" (SEC-18,
      CR-12). Implemented in the web plan (M11 + Q1); recorded here as the
      policy item. Check: ten rapid clicks → at most one Nominatim request per
      1.1 s in the network log.
- [x] **Q3 / I2** Patch the vendored `maplibre-gl.js` `removeAttributes` loop to
      iterate `Array.from(t.attributes)` (CVE-2026-85061; no 5.x fix exists —
      5.24.0 is the last 5.x, fixed only in 6.4.1); record the advisory, the
      pre- and post-patch sha256 in `web/README.md`; keep
      `attributionControl: false` and pin it with a test (gates plan P11)
      (SEC-22, CRIT-20, DOC-4). The 6.x migration with the tile-loading retest
      is a separate cycle-3 task.
- [x] **I3** `deploy_verify.sh` runs `tests/test_licence_firewall.py` against
      `dist/` before rsync; `FORBIDDEN` gains the Google Routes token names;
      the scan covers `.txt`, `.bin`-adjacent JSON and `.md` (SEC-8).
- [x] **L5 / I4** rsync excludes, stray refusal, `0o644`, nginx dotfile/temp
      deny — implemented in the build plan (L5); recorded here as the security
      item. Live evidence: `/origins/las-vegas.pmtiles-journal` returns 200
      today (SEC-20).
- [x] **Q6 / I5** Remove `selectolax` from `pyproject.toml` (no imports) and
      `uv.lock`; record the six vendored sha256s in `web/README.md` with a test
      that recomputes them; document `uvx pip-audit` (not installed in the venv;
      nothing is installed this cycle) in the deploy checklist (SEC-25, DOC-22).
- [x] **Q5** `object-src 'none'` and `report-to` placeholder in the CSP snippet;
      `deploy/README.md` notes the extra hosts Google signals would need
      (SEC-24). `script-src blob:` stays until Q2's rehearsal proves the worker
      loads under `worker-src` alone.
- [x] **Q7 / A17** Slug validation in `load_origins`; `expand_origins.py` shares
      `_SLUG_RE` and escapes names — implemented in the build plan (A17).
- [x] **Q8 / J5** Script paths and the process-kill scope — build plan L10.
- [x] **L13** CSP hash test — gates plan.
- [x] **G2 / SEC-9 (bounded)** `expand_origins.py` uses `follow_redirects` and an
      atomic write; Wikimedia `User-Agent` strings carry a contact URL
      (`routes.py:23`, `wikidata.py:20`); `_retry_after_seconds` is capped.
      The full download provenance (URL hash, ETag/size) stays in the build
      plan's G2 (cycle 3).

## Cycle 3

- [x] **Q2** Rehearse the CSP before installing it: serve a scratch copy of
      `dist/` behind nginx with the snippet, or inject the policy as a
      `<meta http-equiv>` into a scratch `index.html` served by the preview,
      and run `browser_verify.sh` against it; then `deploy_verify.sh` step 3
      asserts `content-security-policy` and `strict-transport-security` on
      `/`, `/app.js`, `/index.json`, `/hover_cells.bin` and a `.pmtiles`
      (SEC-19).
      *2026-10-02:* the rehearsal half is overtaken -- the snippet is installed
      and the live site serves all six headers; `browser_verify.sh` passes
      under that CSP today. The assert half is done and wider than asked:
      `check_security_headers` reads every `add_header` value from
      `deploy/worldmap-security-headers.conf` and requires each of CSP, HSTS,
      X-Frame-Options, Referrer-Policy, Permissions-Policy (the four
      advertising APIs included) and X-Content-Type-Options to be present and
      exactly equal on `/`, `app.js`, `index.json`, `hover_cells.bin`,
      `water.pmtiles` and the first origin's `.pmtiles`; a mismatch exits 1.
      Passes against the live site; `tests/test_deploy_script.py` drives it
      with a stub `curl`, six mutants.
- [x] **Q4 / A18** `adsb_extract.py`: sanitised tag, https + host allow-list,
      size cap (SEC-23). Tag and asset names are one `[A-Za-z0-9][A-Za-z0-9._-]`
      component; each asset URL must be this repo's https download path; a
      redirect may only go to https on GitHub's asset hosts; a part over 4 GB or
      a day over 16 GB is refused before download and the declared size caps
      the bytes received. `tests/sources/test_adsb_extract.py`, nine mutants.
- [x] **I2 (6.x)** Try MapLibre 6.9.0 with pmtiles 4.5.0 on the preview with
      the tile-loading retest `web/README.md` describes.
      *2026-10-02:* done on 6.11.2, the latest 6.x (npm tarball, sha512
      matching the registry's `dist.integrity`); pmtiles stays 4.5.0, still the
      latest, and needs no change. The old "handler never called for tiles"
      symptom does not reproduce. What 6.x required: `import * as maplibregl`
      (no default export); three ES modules, vendored with upstream's `.mjs`
      renamed to `.js` so the nginx `.js` cache and MIME rules still cover them
      (one import specifier rewritten in two files); `setWorkerUrl` pointing at
      `vendor/maplibre-gl-worker.js` before the Map; the WebGL guard narrowed to
      WebGL2. CVE-2026-85061 is fixed upstream (6.4.1), so the local patch is
      gone and `test_vendor.py` now pins the upstream fix. Verified against the
      main `dist/` served read-only with the production CSP: at 1280x800,
      820x1180, 390x844 and 844x390 the canvas exists, 60 cities list, bands and
      water render (queryRenderedFeatures > 0 at load and at z6.5, z7.5, z9.5),
      a click gives a reading and the route panel, console and page errors
      empty; `browser_verify.sh` passes in full; the 1280x800 renders differ
      from 5.24.0's by at most 0.02% of pixels. Not deployed. CSP unchanged
      (the page also ran with `blob:` removed; that tightening is left to a
      server-side change).
- [ ] **N22 / DOC-12** Attribution visibility (owner judgement, web plan).

## Blocked on owner (recorded, not deferred)

- **E3 (server half)** Install `deploy/worldmap.atik.kr.conf` +
  `deploy/worldmap-security-headers.conf` on `atik.kr` and confirm with
  `curl -sI` that CSP/HSTS/nosniff/XFO are present on `/`, `/app.js`,
  `/index.json`, a `.bin` and a `.pmtiles`. Live today: none of the six headers
  on any page asset; the old CSP only on `robots.txt`, `.css`, `.png` and 404s.
  Production change; the exact commands are in `deploy/README.md:49-51`. Exit
  criterion: headers observed live.
- **A6d (server layout)** The `root /var/www/worldmap/current;` change for
  versioned releases goes with the same install.
- **E4 (policy)** Keep public Nominatim (explicit search + throttled reverse
  is within policy after Q1) or self-host: owner's call; Q1's request-rate
  evidence is the input.
- **SEC-6 (consent)** Whether the Google tag needs a consent banner.
- **SEC-17 (licence read)** Whether `conditionsOfAccess` with per-source
  licences satisfies CC BY-SA for the Wikipedia-derived network.

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 security plan (now archived) under its
  original ID.
- 2026-09-10 cycle 2 done: Q1 9d0a401 (one Nominatim queue, 1.1 s spacing, latest click wins, cache by rounded coordinate, credit beside the label; no request for water or unreached clicks); Q3/I2 773eafe (one-token patch, hashes recorded, tests red when unpatched); I3, L5/I4, Q5, Q8/J5 0e74b2b; Q6/I5 773eafe; Q7/A17 269e17c + 379d607; L13 c4b7295; G2 bounded 379d607. Blocked-on-owner items unchanged (E3 server half: live headers still absent on page assets).
- 2026-09-10 cycle 2 closed at `29c6330`: every Cycle 2 task above is ticked; the Cycle 3 section stays open, so this plan is not archived. Both gates green on the whole repo at that commit (ruff clean; pytest 356 passed, 4 deselected, 5 warnings, exit 0) -- recorded in `plan/2026-09-10-c2-gates-and-tests.md`.
