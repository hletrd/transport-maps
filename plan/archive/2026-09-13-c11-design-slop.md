# Cycle 11 — the design pass: "remove ai slops from overall designs"

**Owner's request, verbatim:** "and please remove ai slops from overall designs".
Standing brief: "for more details, higher quality and design and ease of usage
and UI. Do not overwork."

Source: the eleven-lane review in `.context/reviews/` (cycle 11), aggregated in
`_aggregate.md`. Designer lane weighted and run against the live site at
1280x800, 820x1180, 390x844 and 844x390. Per-agent IDs this cycle: `UX11-n`,
`CR11-n`, `PR11-n`, `SEC11-n`, `CRIT11-n`, `TE11-n`, `ARCH11-n`, `DOC11-n`,
`DBG11-n`, `VER11-n`. Scheduled clusters: `C11-n`.

## What the sweep found, before anything was changed

The bans in `CLAUDE.md` **hold**. Measured on the live page across 2,656
elements: zero `text-transform`, zero non-`normal` `letter-spacing`, zero
`font-variant-numeric: tabular-nums`, zero small caps, zero emoji, no webfont
CDN, Plex 400/500/600 all loading. Hexagons keep MapLibre's default miter join;
`line-join:"round"` appears only on route arcs; no H3 regularisation anywhere.
Zero decorative gradients. Three box-shadows, all functional — the `.lbl` halo is
load-bearing, since labels measure 1.96:1 against a bright band without it.

Accessibility re-measured from real pixels and **not regressed**: worst-case
`--text-3` 4.75:1 over the 86 % scrim on the brightest band, `--line-ctl`
3.10–3.65:1, 24 px targets intact. Nothing in this plan touches any of it.

So the slop is not in the palette or the ornament. It is in **the prose, the
type scale, and three small live defects**. That is what this cycle fixes.

## C11-1 — The page invites you twice, four pixels apart (UX11-1, CRIT11-3). HIGH

`web/app.js:342-343` sets `IDLE_TIME` to "Point anywhere on the globe for the
travel time from your departure city, door to door." `web/index.html:750` sets
`#where` to "Point anywhere for a travel time. Click to set a destination."
They stack directly on top of each other and both open with the same two words.
It is the first thing a first-time visitor reads.

**Fix.** Keep the invitation once, in the large slot where the number will
appear, and make `#where` carry the part the idle line does not: what a click
does. `IDLE_PROMPT` reads `#where`'s initial text, so both change together.
Keep "door to door" — `CLAUDE.md` requires it wherever a figure is presented.

- [x] Cut the duplication; verify `IDLE_PROMPT` still resolves.

## C11-2 — "Showing Seoul." is the fifth statement of the city, and it is exactly the 22 px that clips the licence panel (UX11-2). HIGH

`web/app.js:3753-3755` writes `Showing <city>.` into `#here` on the plain
success path. The city is already named in the masthead-adjacent departure card,
the `Departure` summary's `#origin-name`, the `#where` line and the permalink.

Measured on the live page: rail `scrollHeight` 782 against `clientHeight` 760;
`#key` bottom 802 against rail bottom 780. Hiding `#here` in the live DOM takes
the overflow to 0 and puts `#key` bottom at exactly 780. So the redundant
sentence is also what pushes the licence and privacy panel out of the rail.

**Fix.** Say nothing on the success path. Keep every failure announcement:
the `badSlug` sentence and the `ignored` suffix both still fire, still through
`sayHere`, so they stay both visible and spoken.

- [x] Success path silent; `badSlug` and `URL_REJECTED` paths unchanged.

## C11-3 — Eighteen caption classes at six sizes (UX11-3). HIGH

Small grey text is set at **10, 10.5, 11, 11.5, 12 and 12.5 px** across 37
rules, in half-pixel steps, against only three weights and four colours. Six
sizes that all mean the same thing is the generated look: a scale nobody chose,
arrived at by nudging one rule at a time.

**Fix.** Four steps, declared once as tokens, each rule mapped to one. Collapse
by removing the two steps with the fewest users and folding them into their
neighbour, so the change only shrinks or holds except for one credits
paragraph:

| Token | px | Was |
|---|---|---|
| `--t-micro` | 10.5 | 10, 10.5 |
| `--t-cap` | 11 | 11, 11.5 |
| `--t-ui` | 12 | 12 |
| `--t-lbl` | 12.5 | 12.5 |

`.scale span` stays at 11 px, so no legend tick changes its pruning. `.leg`
stays at 12.5 px, so the measured 76 px `.leg .t` width stays valid.

- [x] Tokens declared and every small-text rule mapped to one.

## C11-4 — Four identical grey paragraphs close the readout (UX11-4). MEDIUM

`.legend-cap`, `.legend-credit`, `.disclaimer` and `.built` are four one-sentence
`<p>`s, all 11 px `var(--text-3)`, with margins 6 / 3 / 4 / 2 — 35 % of the
phone sheet. The uniform rhythm is the tell; the content is not the problem.

**Every statement stays.** The door-to-door caption, the OpenStreetMap credit,
the privacy link and the liability notice are all required, by `CLAUDE.md`, the
OSMF Attribution Guideline or the owner. They are merged into two lines rather
than four: caption with liability notice, credit with build date.

- [x] Four `<p>` to two; all four statements intact; `#built` keeps its id.
      CORRECTION (C13-11 / V13-10, 2026-10-02): shipped as THREE paragraphs, paired
      differently. They are the caption alone; the OpenStreetMap credit with
      Privacy, since the OSMF credit kept its own line; and the liability
      notice with `#built`. All four statements are intact and `#built`
      kept its id. Only the count and the pairing differ from the text.

## C11-5 — Three false or stale statements in the visible prose (DOC11-1..3, CRIT11-2..3). HIGH

All three are in the "Sources and method" panel, in one 1,705-character
paragraph:

1. `web/index.html:966-968` cross-references **in bold** a heading
   "How a journey is put together" that **has never existed** in this page.
   `git log -S` returns only the commit that added the sentence.
2. `web/index.html:975-978` says roadless terrain and local roads are "the
   slowest and the second slowest classes". `SPEED_BY_ROAD_CLASS_KMH =
   [5, 104, 57, 50, 18, 25]`: roadless is slowest at 5 km/h, but **local is
   third** at 25; second is tertiary at 18, which *is* fitted. The sentence
   argues from the false ordering to "so they set the last kilometres of many
   journeys".
3. `web/index.html:962` ships the typo "above it **it** over-states".

- [x] All three corrected against the constants, not against the prose.

## C11-6 — Two prose blocks that exist because someone doubted the UI (CRIT11-4, UX11-5, CRIT11-6). HIGH / MEDIUM

`#route-hint` (`web/index.html:869-875`) is 361 characters. It opens by
repeating the readout's own idle prompt verbatim, then lists three separate
routes to one action. Only its last sentence states a limit — that only the
listed cities have a computed surface, so a departure snaps to the nearest —
and that sentence is the one worth keeping.

The Settings `.hint` (`web/index.html:908-910`) puts globe instructions in
Settings. Its second sentence explains the "Lock to north" checkbox directly
above it and earns its place; its first does not.

- [x] Both trimmed to what states a limit or explains an adjacent control.

## C11-7 — The detail row's last tick overhangs its strip (UX11-6). HIGH

`paintDetail` (`web/app.js:2437-2449`) adds the `.first` class to the leading
tick so it is left-anchored and cannot overhang, and **never adds `.last`**.
`.scale span.last{transform:translateX(-100%)}` exists in the stylesheet and is
used by the main ladder; the detail row does not use it.

Measured: at 390x844 the final tick "13 h 45" runs to x=395 on a 390 px screen
and renders as "13 h 4". At 1280x800 it paints 19 px past the strip onto bare
globe.

- [x] The tick at position 1.0 gets `.last`.

## C11-8 — Two survivors of the typeface rule (UX11-7). LOW

`#key code` (`web/index.html:979-980`) renders `index.json` in the browser's
default `monospace`. `CLAUDE.md` says sans-serif throughout, and a monospace
run on a dark panel reads as a terminal — the same tell the `tabular-nums` ban
exists to prevent. The signal "this is a literal filename" is carried by weight
instead, which is what the policy asks for.

`.compass` (`web/index.html:540`) computes to `Arial` for want of
`font:inherit`. It is inert — the button holds only an SVG — but it is the one
element that would render a non-Plex glyph if text were ever added.

- [x] Both set to inherit; `#key code` carries weight instead of a face.

## C11-9 — Two ARIA strings that misdescribe the page (DOC11-4, DOC11-5). MEDIUM

`web/index.html:837` names the rail "Departure, route and settings" — it omits
the fourth panel, **"Sources and method"**, which holds the entire privacy
statement and every data credit. A screen-reader user given that name has been
told the licence panel is not there.

`web/index.html:717-720`'s comment says "Four now" and that each landmark is
"named by a heading in the outline under the h1". There are **five**, and
`<main aria-label="Globe">` has no heading.

- [x] Rail label names all four panels; the comment matches the markup.

## C11-10 — The design rules have no gate, and every one of them ships green when broken (TE11-1). HIGH

This is the finding that makes the rest of the cycle durable. The test engineer
mutated the page and ran the **deploy page gate** — the gate that actually runs
before a deploy — against each mutation:

| Mutation | Page gate |
|---|---|
| `letter-spacing:.08em` added | **green**, 265 passed |
| `text-transform:uppercase` added | **green** |
| `font-variant-numeric:tabular-nums` added | **green** |
| `--bg` flipped to a light sepia | **green** |
| `--font` swapped to a serif stack **plus a Google Fonts `<link>`** | **green** |
| `<link href="./vendor/fonts.css">` deleted | **green** |

The sepia flip leaves `--text` at **1.06:1** on `--surface` and still passes the
suite's only contrast assertion, which covers `--line-ctl` alone. Deleting the
font stylesheet makes Plex silently fall back — the exact failure `CLAUDE.md`
names as the reason the face is self-hosted.

So the standing design policy has been enforced for eleven cycles by nothing but
each cycle's attention. A cycle whose subject is the design is the right cycle
to give it teeth.

**Fix.** A new `tests/web/test_design_policy.py`. `tests/web/` is run as a
whole directory by `page_gate()` in `scripts/deploy_verify.sh`, so a new file
there is on the deploy path the moment it lands, with no script edit.

Every assertion must be **mutation-verified red** before the commit, per
`CLAUDE.md`'s testing rule.

- [x] Gate written, every assertion mutation-verified.

## Deferred this cycle

Recorded in `plan/deferred.md` under "Cycle 11", each with file and line,
unchanged severity and confidence, a concrete reason and an exit criterion.
Nothing is silently dropped. In summary:

- **C11-D1 / ARCH11-Q1, CR11-1** — the raw-download cache keyed on a bare
  filename. Already carried as `PR10-5`; cycle 11's architect **sharpened the
  severity** (a URL change is a derived MISS rebuilt from the OLD bytes under a
  NEW stamp, so the artifact is permanently *mislabelled*, not merely stale).
  Still build-path and network-gated; this cycle was forbidden from rebuilding.
- **C11-D2 / ARCH11-Q2, CR11-5, DBG11-3** — `index.json` advertises a reading
  tier that may not exist. Blast radius corrected downward by the debugger: one
  doomed 117 KB request per city click for the session, not an unbounded loop.
- **C11-D3 / CR11-6, DBG11-2, SEC11-M4** — `?label=` flagged geocoded, dropped
  from the permalink, falsely credited to Nominatim.
- **C11-D4 / CRIT11-1** — `esc()`, the page's only XSS barrier, has zero tests
  and its one Node harness stubs it to identity.
- **C11-D5 / TE11-2, CR11-7** — `test_cache_provenance.py`'s `any(c.isdigit())`
  assertions are a measured 1-in-2,442 false-failure landmine and redundant;
  its umask pin is inert and actively harmful.
- **C11-D6 / SEC11-M1** — live nginx conf has drifted from the committed one.
- **C11-D7 / PR11-1..3** — brotli-static, vendor cache headers, and the doubled
  `_crosses_antimeridian` pass (≥3.2 CPU-hours per build).
- **C11-D8 / ARCH11-A..I** — nine architecture findings, including three
  `REQUIRED_EXTRAS` with no producer in any entry point.
- **C11-D9 / UX11-8, UX11-9** — the phone-fold layout and the three-scrim
  alignment.
- **C11-D10 / DOC11-M\*** — the remaining doc and comment drift.
- **C11-D11 / DBG11-\*** — the remaining runtime-order defects.

## Not to be reopened

`C10-16` — the flowing dashes stay continuous. Decided by the owner on
2026-09-13 and closed in `plan/deferred.md`. The perf lane referenced it as a
cost multiplier only and did not re-raise it, which is correct.

## Progress

| Task | Status |
|---|---|
| C11-1 invitation said once | done |
| C11-2 "Showing <city>." cut; rail overflow closed | done |
| C11-3 six type sizes to four tokens | done |
| C11-4 four closing paragraphs to two | done, as three (C13-11 / V13-10) |
| C11-5 three false statements corrected | done |
| C11-6 two help blocks trimmed | done |
| C11-7 detail row's last tick anchored | done |
| C11-8 typeface survivors | done |
| C11-9 ARIA rail label and landmark comment | done |
| C11-10 design-policy gate, mutation-verified | done |

## Verification — measured on the deployed page, not asserted

Gates, whole repo:

| Gate | Before | After |
|---|---|---|
| `uv run ruff check .` | exit 0 | exit 0 |
| `uv run pytest` | 761 passed, 4 deselected | **768 passed**, 4 deselected, exit 0 |
| deploy `page_gate` | 267 passed | **274 passed** |

The +7 is `tests/web/test_design_policy.py`. No gate was weakened, no threshold
lowered and no test rewritten to accommodate a change. `GATE_FIXES` this cycle
is 0: nothing was red.

`scripts/deploy_verify.sh --page-only` ran to `ALL CHECKS PASSED`, ending in
`browser_verify.sh` against the live URL: 553 cities, 39 swatches, 12 schemes,
0 console errors, and clean passes at 1280x800, 820x1180, 390x844 and 844x390
including the folded-sheet and rotate-across-860px paths.

Then measured independently, live, with the viewport set through
`agent-browser set viewport` (not the window size — the first attempt read
1280x577 because browser chrome takes 223 px, which would have made every
box metric below wrong):

**C11-2, the rail overflow.** At a true 1280x800, with the default panel state:

| | before (designer lane) | after |
|---|---|---|
| rail scrollHeight − clientHeight | 22 | **0** |
| `#key` bottom | 802 | **780** |
| rail bottom | 780 | 780 |

The licence and privacy panel now ends exactly on the rail's bottom edge
instead of 22 px past it. Same at 820x1180: overflow 0, `#key` bottom 1180,
rail bottom 1180.

**C11-3, the type scale.** Computed `font-size` of every element at or below
12.5 px, at all four viewports:

    before   10, 10.5, 11, 11.5, 12, 12.5     (six)
    after    10.5, 11, 12, 12.5               (four)

**C11-7, the detail row's last tick.** Zoomed in until `#detail` unhides:

| viewport | strip right edge | last tick right edge | overhang |
|---|---|---|---|
| 390x844 | 376 | 376 | **0** (was 395, off a 390 px screen) |
| 1280x800 | 304 | 304 | **0** (was 19 px past the strip) |

The tick carries `class="last"` in both, and the 390x844 label reads
"24 h 30" in full rather than truncating.

**The bans, re-swept live after the changes.** Every element at all four
viewports: zero `text-transform`, zero non-`normal` `letter-spacing`, zero
`font-variant-numeric`. Body family resolves to `"IBM Plex Sans"`. No
horizontal scroll at any viewport.

**Nothing required was lost.** `#built` is populated ("Data built on September
13, 2026"), `.legend-cap` and `.disclaimer` both render at both phone
viewports, the map credit and privacy link are unchanged, and
`?from=atlantis` still announces "No departure city called "atlantis"; showing
Seoul." — the failure path the success path's removal had to leave intact.
