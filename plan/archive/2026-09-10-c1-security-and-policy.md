> Archived 2026-09-10 (cycle 2). Every cycle-1 task in this plan is done; every
> unfinished cycle-2/3 task was carried into `plan/2026-09-10-c2-security-and-policy.md`
> under its original ID (see `.context/reviews/_aggregate.md` for the cycle-2
> evidence). This file is kept for provenance and is not updated further.

# Plan: escaping, security headers, third-party policy, supply chain

Source findings: `_aggregate.md` E3, E4, I1–I5. Per-agent detail:
`security-reviewer.md` (SEC-*), `document-specialist.md` (DOC-2, DOC-3),
`critic.md` (CRIT-5, CRIT-13), `verifier.md` (VER-6), `architect.md` (ARCH-12),
`code-reviewer.md` (CR-5).

Security findings are not deferred. Where a step needs the owner (a change on
the production server), the repo-side change lands now and the server-side
step is recorded as blocked-on-owner below, per the global rule that
production and firewall/header changes require explicit confirmation.

## Cycle 1 (this run)

- [x] **I1** Escape every external string before `innerHTML`: GeoNames place,
      region and country names, OurAirports names, Nominatim display names,
      rail station and line names (`app.js:596-601,614-624,730` and the route
      summary). One `esc()` helper; or build the nodes with `textContent`.
      Check: a place named `<img src=x onerror=alert(1)>` in a fixture renders
      as text.
- [x] **E3 (repo half)** `deploy/worldmap.atik.kr.conf`: move the security
      headers into an `include deploy/security-headers.conf` (or repeat them)
      inside every `location` that sets `Cache-Control`, so nginx's
      `add_header` inheritance no longer drops them; extend the CSP to what
      the page actually does (`connect-src 'self' https://nominatim.openstreetmap.org
      https://www.google-analytics.com https://*.google-analytics.com`,
      `script-src 'self' blob: https://www.googletagmanager.com`, `img-src`
      for the tag's beacon) and keep `frame-ancestors 'none'`. `deploy/README.md`
      documents the inheritance trap and how to verify with `curl -sI`.
      Server-side deployment of the conf: **blocked on owner** (see below).
- [x] **E4 (bounded)** Address search becomes explicit (Enter or a button) —
      done in the web plan's D4 task — with a Nominatim attribution line under
      results and a visible disclosure sentence in the about panel that the
      page talks to Nominatim (address search) and Google Analytics.
- [x] **E4 (docs)** `web/README.md`, `llms.txt` and the JSON-LD stop claiming
      "no runtime API calls / no third party".

## Cycle 2

- [ ] **I2** MapLibre GL JS 5.24.0 carries CVE-2026-85061. Check for a 5.x patch
      release (web search); if one exists, vendor it and re-run the tile-load
      check `web/README.md` describes; if none, patch the `removeAttributes`
      loop in the vendored bundle (a one-line snapshot of the live
      `NamedNodeMap`) and record the patch and its hash in `web/README.md`.
      Keep `attributionControl: false` until then and note it as the
      mitigation.
- [ ] **I3** Licence firewall on the deploy path: `deploy_verify.sh` runs
      `tests/test_licence_firewall.py` against `dist/` before rsync; add the
      Google Routes token names to `FORBIDDEN`; scan `.bin`-adjacent JSON and
      `.txt` too (`tests/test_licence_firewall.py:11-72`).
- [ ] **I4** Exclude dotfiles, `*-journal` and `tmp*` from the deploy rsync; add
      `location ~ /\. { deny all; }` to the nginx conf; set artifact modes
      explicitly (0644) in `_utils._atomic_write`.
- [ ] **I5** Remove the unused `selectolax` dependency (confirm with
      `git grep`), add `uv run pip-audit` (or `uv audit` when available) to
      the gate list, and record vendored JS hashes.
- [ ] **G2/SEC-9** Record size/ETag for raw downloads and verify on re-use.

## Blocked on owner (recorded, not deferred)

- **E3 (server half)** Deploy the corrected nginx conf to `atik.kr` and confirm
  with `curl -sI https://worldmap.atik.kr/` that CSP/HSTS/nosniff/XFO are
  present on `/`, `/app.js`, `/index.json`, a `.bin` and a `.pmtiles`. This
  is a production server change: the global rule requires explicit
  confirmation before modifying production environments or header/firewall
  configuration, so it is recorded here with the exact command for the owner:
  `scp deploy/worldmap.atik.kr.conf atik.kr:/etc/nginx/sites-available/worldmap && ssh atik.kr 'nginx -t && systemctl reload nginx'`.
  Exit criterion: headers observed live; then close E3.
- **E4 (policy)** Whether to keep public Nominatim (explicit search is within
  the policy) or self-host / switch provider is the owner's call; the bounded
  fix is in. Exit criterion: owner confirms the provider.
- **SEC-6** Whether the Google tag needs a consent banner depends on the
  audience/jurisdiction; the disclosure sentence is in. Exit criterion: owner
  decides on consent.

## Progress

- 2026-09-10 cycle 1: plan written; cycle-1 tasks implemented in the cycle-1 commits.
- 2026-09-10 cycle 1 done: I1 (f943964 esc() on every dataset string), E3 repo half (03988a5 snippet + includes + CSP), E4 bounded (1305ba7 explicit search) and docs (e11c830). Server-side header install remains blocked on owner.
