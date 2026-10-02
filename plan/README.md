# Plans

Implementation plans derived from the multi-agent reviews in `.context/reviews/`
(cycle 15: per-agent files plus `_aggregate.md`, with per-agent IDs `CR15-n`,
`PR15-n`, `SEC15-n`, `CRIT15-n`, `VER15-n`, `TE15-n`, `TR15-n`, `ARCH15-n`,
`DBG15-n`, `DOC15-n`, `UX15-n`, merged clusters `AGG15-1…AGG15-77`, scheduled
tasks `C15-1…C15-7` and deferrals `DEF15-1…DEF15-61`; cycle 14: per-agent files
plus `_aggregate.md` with 223 findings clustered `CL-A…CL-O` and tasks
`C14-R1…C14-R11`; cycle 13: per-agent IDs `-13` with clusters `C13-n` and
`V13-n`, plus the solver-service tasks `C13-F2.1…C13-F2.12`; cycle 12:
per-agent IDs `-12` with clusters `C12-n` and the owner's tasks `F1…F3`;
cycle 11: per-agent files plus `_aggregate.md`, with per-agent IDs `UX11-n`,
`CR11-n`, `PR11-n`, `SEC11-n`, `CRIT11-n`, `TE11-n`, `ARCH11-n`, `DOC11-n`,
`DBG11-n`, `VER11-n` and scheduled clusters `C11-n`; cycle 6: per-agent files plus `_aggregate.md` with merged clusters AA1…AA47 and
per-agent IDs CR6-n, PR6-n, SEC6-n, CRIT6-n, VER6-n, TE6-n, TR6-n, ARCH6-n,
DBG6-n, DOC6-n, UX6-n, FCR6-n; cycle 5: `cycle-5/` with clusters Z1…Z10 and the
matching `-5` suffixes; cycle 4: per-agent files plus `_aggregate.md` with merged clusters Y1…Y30 and
per-agent IDs CR4-n, PR4-n, SEC4-n, CRIT4-n, VER4-n, TE4-n, TR4-n, ARCH4-n,
DBG4-n, DOC4-n, UX4-n, FCR4-n; cycle 3: `cycle-3/` with clusters X1…X21 and
per-agent IDs CR3-n, PR3-n, SEC3-n, CRIT3-n, VER3-n, TE3-n, TR3-n, ARCH3-n,
DBG3-n, DOC3-n, UX3-n, FCR3-n; cycle 2: `cycle-2/` with merged IDs K1…S6;
cycle 1: `cycle-1/_aggregate.md` with A1…J9). Finding IDs are stable across cycles: a
cycle-1 ID (C5, D13, F3, G1 …) keeps its name when it is carried into a cycle-2
plan.

**`.context/reviews/` is deliberately NOT committed** (`.gitignore:29`, from
`5cb3f89`): twenty of the cycle-1 and cycle-2 review files quoted this machine's
absolute home path and two quoted the build host's private addresses and
aliases, none of which belong in the repository. The review files are still
written to disk every cycle and still read from disk by the next one -- they are
the working notes -- but **this directory is the durable record.**

So: every review finding is either scheduled in one of the plans here (with a
target cycle), fixed in a commit whose body carries the evidence, or **deferred
with its citation, original severity and confidence, the reason, and the exit
criterion that reopens it**. Nothing is dropped, and nothing needed to act on a
finding lives only in an untracked file. Cycle 3 audited this mechanically: all
142 finding IDs its reviewers raised are named in `plan/`, including thirteen
that had been carried only in the review text.

**Where a deferral lives depends on its cycle, and this is the part the rule
has twice stated wrongly.** Cycles 1-12 deferred into `deferred.md`, under a
`# Cycle n` heading. **Cycles 13 onward defer into that cycle's own findings
file.** The ID scheme is NOT uniform across them, and the previous version of
this paragraph invented one that does not exist:

| Cycle | File | ID scheme | Count |
|---|---|---|---|
| 1-12 | `deferred.md` | per-cycle (`AA`, `AB`, `M8`, `C12-n`, …) | 242 findings in 293 table rows |
| 13 | `2026-09-14-c13-review-findings.md` | **group rows, no `DEF13-n`** (`grep -c DEF13- ` returns 0) | 11 group rows covering ~205 named IDs |
| 14 | `archive/2026-09-15-c14-review-findings.md` | **`AGG14-n`, no `DEF14-n`** | 216 |
| 15 | `2026-09-16-c15-review-findings.md` | `DEF15-1…DEF15-61` | 61 |
| 16 | `2026-09-16-c16-review-findings.md` | `DEF16-1…DEF16-24` | 24 |
| 17 | `2026-09-17-c17-review-findings.md` | `DEF17-1…DEF17-31` | 31 |

`deferred.md` remains the ledger for cycles 1-12 and for anything reopened or
closed across cycles; it is not, and since cycle 13 has not been, the single
file every deferral lives in.

> **Read this before using any `file:line` in the ledger.** Cycle 17 measured
> the citations: of 159 `web/app.js:N` references across the five files, 78 name
> no identifier and **63 of the 81 checkable ones (78 %) do not resolve** to the
> code they quote. The re-anchoring sweep (`AB41`) has been deferred four times
> and its criterion — "the first cycle that makes no change under `web/` or
> `tests/`" — can no longer fire, because there is no cycle 18. **Treat every
> line number here as approximate and re-grep for the quoted code.** This is
> `DEF17-29`; the ledger's other structural problems are `DEF17-30`, which
> records them as the largest single piece of unfinished work in the repository.

Cycle 16 found this the expensive way. `plan/README.md` said "recorded in
`deferred.md`", and the cycle-16 review brief told all eleven lanes to grep
`deferred.md` for prior art. `grep -c 'DEF15-' plan/deferred.md` returns **0**;
the same grep against the cycle-15 findings file returns **137**. Nothing was
lost -- every row exists with its reason and criterion -- but a reviewer
following the stated rule finds nothing for the last three cycles and re-raises
dispositioned findings. **When you write a cycle's brief, point its lanes at that
cycle's findings file as well as at `deferred.md`.**

Cycle 4's designer found one gap in that audit: six cycle-3 designer findings
(A3-A8) reached no table, and the designer's `A1…A8` collide with the build
plan's `A1…A17`. U28 (cycle 4, `0b9c3bc`) recorded both: the gap, and the
cycle-number prefix that ends the collision. It did not schedule the six
findings themselves, and no plan since has. (Reconciled 2026-10-02, C13-11 /
V13-17: this paragraph said "both are scheduled in U28", and the cycle-4
paragraph further down says they "reached no table at all". Both are true of
the findings; only the recording was scheduled.) Cycle-4 IDs are prefixed with the
cycle number (`CR4-n`, `UX4-n` …) so the collision cannot recur.

| Plan | Scope | Status |
|---|---|---|
| `2026-09-17-c17-review-findings.md` | **Cycle 17, the FINAL cycle**: 58 raw findings from the eleven lanes deduped to 34, scheduled (`C17-1…C17-7`) or deferred (`DEF17-1…DEF17-31`). §3 is the handover: every deferred row carries a file, a symptom, an unreduced severity and an exit criterion actionable without this run's context | **cycle 17: current and last.** Its §4 lists what shipped |
| `2026-09-16-c16-review-findings.md` | Cycle 16: all 116 raw findings from the eleven lanes merged to 41, scheduled (`C16-1…C16-8`) or deferred (`DEF16-1…DEF16-24`). §2 carries three findings for the owner | **cycle 16: all eight tasks done** (see its §8 for the commits); its 24 deferrals stand |
| `2026-09-16-c15-review-findings.md` | Cycle 15: all 108 raw findings from the eleven lanes merged to 77, indexed with citations, scheduled (`C15-1…C15-7`) or deferred (`DEF15-1…DEF15-61`) | cycle 15: current. C15-5.6 ticked 2026-10-02; the open box is C15-6.7's `[~]` (the ledger citations to re-point), so it is not archived |
| `2026-09-15-c14-owner-requests.md` | Cycle 14: the owner's two standing requests — carry-on-only luggage, and preferred/excluded transport modes. **The single authority for both**; amend here, do not open a second record | cycle 14: **done** -- carry-on only live 2026-09-26, avoid flights/ferries/trains live 2026-09-27 (fine readings 2026-10-01); weighting dropped by the owner's choice of exclusion only |
| `2026-09-15-c14-rail-service-tiers.md` | Cycle 14: the rail service-tier model, the operator/ref labels and the caption fix (C14-R1…C14-R11). §6 lists what is build-baked | cycle 14: current; **pipeline changes reach the site only after a rebuild** |
| `2026-09-14-c13-solver-service.md` | Cycle 13: the F2 on-demand solver service — the design, the measured footprint, and the graph-free half that was built (C13-F2.1…C13-F2.12) | cycle 13: **built and running** (2026-10-02). The owner chose to build it (F2.5). The solver runs on the web host as systemd `worldmap-solver` behind nginx `/api/solve` (F2.7, F2.9, F2.10), and the runbook is in `deploy/README.md` (F2.11). F2.6 is obsolete, because the build and the solver never share a machine. **Open: F2.8**, since a response is a number rather than an itinerary |
| `2026-09-14-c13-review-findings.md` | Cycle 13: all 250 raw findings from the eleven lanes, indexed with citations, scheduled or deferred (C13-1…**C13-25**) | cycle 13: current. C13-11 is done (2026-10-02): all seventeen V13 ticks re-verified, with a dated correction in each plan where the tick did not hold. C13-8 is obsolete, because the build and the solver never share a machine |
| `2026-09-10-c2-web-ui-detail.md` | Page detail, ease of use, UI and accessibility (the user's brief for this run) | cycle 2 done; tasks still open, carried forward. 2026-10-02: N22 done (U18); N15, D20, D13, R8, C1-C3/C8/C11 verified still open; N24 split out of N23's box as open (V13-11) |
| `2026-09-10-c2-build-robustness.md` | Build correctness, artifact integrity, deploy and verification scripts, performance | cycle 2 done; tasks still open, carried forward |
| `2026-09-10-c2-gates-and-tests.md` | Lint and test gates: red gates, vacuous tests, hygiene | cycle 2 done (W1 recorded); open tasks carried forward. 2026-10-02: the K3/K4/G1 tests are ticked; W1 and F13's TE-20 remain |
| `2026-09-10-c2-docs-attribution-calibration.md` | Attribution, stale docs and comments, calibration provenance, bookkeeping | 2026-10-02: J1's document and `contractVersion` done (`docs/contract.md`); B2's table move done with values unchanged. Open: J1b (the code half of J1), B2b (one threaded calibration loader), and E13 (author email, the owner's call) |
| `2026-09-13-c10-four-live-defects.md` | Cycle 10: the four defects the owner and the deploy's own verification reported, plus the two they uncovered (C10-1…**C10-17**) | cycle 10: current |
| `2026-09-13-c10-requested-features.md` | Cycle 10: four features the owner asked for — draggable markers (F1), an on-demand solver service (F2), many more departure cities (F3), an ETOPS option (F4) | **three of the four have since shipped**: F1 in `6214283`, F3 in `b21e808`, F4 as the documented decision not to build it in `12e68ac`. F2's analysis is superseded by `2026-09-14-c13-solver-service.md`, which corrects three of its load-bearing claims. The file's own "PLANNED, NOT BUILT" heading describes cycle 10, not HEAD |
| `deferred.md` | Findings not scheduled, with reasons and exit criteria; reopened and closed items | living |
| `archive/2026-09-14-c12-review-findings.md` | Cycle 12: everything else the eleven review lanes found, scheduled or deferred (C12-1…**C12-14**) | archived 2026-10-02. Every task is ticked or obsolete with its reason: C12-4 was done as C13-6 and C12-1e as C13-1, and C12-3d/3e are obsolete while the 60-row cap stands. Its deferral table stays readable there |
| `archive/2026-09-10-c2-security-and-policy.md` | Third-party policy, CSP, supply chain, blocked-on-owner items | archived 2026-10-02. The last box, N22/DOC-12, shipped as U18. E3 is done, A6d is won't-do, and the owner decisions E4, SEC-6 and SEC-17 are carried in `deferred.md`. `web/README.md:61` still cites the old path |
| `archive/2026-09-10-c1-*.md` | The five cycle-1 plans: every cycle-1 task done; every unfinished task carried into the matching c2 plan under its original ID | archived (cycle 2) |
| `archive/2026-09-10-c3-page-detail-and-defects.md` | Cycle 3 (T1…T31): 28 done; T24, T26 and T28 carried into the cycle-4 plan as U28, U10 and U11 | archived (cycle 4) |
| `archive/2026-09-10-c4-page-deploy-and-licence.md` | Cycle 4 (U1…U28): all done | archived |
| `archive/2026-09-10-c5-page-defects-and-ui.md` | Cycle 5 (V1…V29): every task done or recorded, each with the mutation that proved it | archived (cycle 6) |
| `archive/2026-09-11-c6-page-defects-privacy-and-licence.md` | Cycle 6 (C6-1…C6-21): all 21 done | archived |
| `archive/2026-09-12-c7-resolution-6-readings.md` | Cycle 7 (C7-1…C7-18): all 18 done | archived (cycle 9) |
| `archive/2026-09-14-c12-requested-features.md` | Cycle 12: the three tasks the owner named — a real test for `esc()`, draggable start and end markers, and the ETOPS decision (F1…F3) | archived (cycle 15); all three landed |
| `archive/2026-09-13-c11-design-slop.md` | The owner's design pass: "remove ai slops from overall designs". Prose, type scale, three false statements, and the gate that keeps the design policy enforced | archived (cycle 15); all ten tasks landed |
| `archive/2026-09-13-c9-page-failure-paths.md` | Cycle 9 (C9-1…C9-31): all 31 done. Archived in cycle 16 after spot-verifying 7 ticks against the TREE -- all 7 hold, including C9-4, whose `outline-offset:-2px` is written in the minified form a naive grep misses | archived (cycle 16) |
| `archive/2026-09-15-c14-review-findings.md` | Cycle 14: all 223 findings from the eleven lanes, clustered CL-A…CL-O; the seven scheduled tasks C14-1…C14-7 all landed in `e7a90c7`/`15870ac`/`5849e0d` | archived (cycle 16). Its `DEF14-n` deferrals stay readable there -- see the routing note above |
| `archive/2026-09-13-c8-ferry-wait-legend-url.md` | Cycle 8 (T1.1…T5.6, 38 tasks): 35 fully done. T5.3 was ticked and half-done (fixed in cycle 9); T2.7 was ticked and not done (carried as M8-14 in `deferred.md`); T5.6 was ticked and never done, and T1.9 recorded three of its five objections (both found by V13-1/V13-3 and corrected in the file on 2026-10-02, C13-11). | archived (cycle 9) |

Four of the five cycle-2 plans do not move to `archive/` yet; the security plan
moved on 2026-10-02, when its last box was ticked. Tasks across the other four
are still open, and the archive convention below applies only when every task is
done or has been carried forward under its ID. `W1` in the gates plan stays open
by design -- it is a recorded warning with an exit criterion, not an unfinished
fix.

Cycles 7 and 8 moved to `archive/` in cycle 9, which is also when their two
mis-ticked tasks were found. **The lesson is in the archive convention itself:
a plan is archived on the state of the TREE, not on the state of its own
checkboxes.** Cycle 9 verified ten of cycle 8's ticks against the code by grep
before archiving it, and two did not hold.

End-of-cycle-3 gate state at `43b99f5`: `uv run ruff check .` all checks passed,
exit 0; `uv run pytest -q` 390 passed, 4 deselected, 5 warnings (all W1), exit 0.

Cycle-5 gate state at `ef31d02`, run independently by two reviewers: `uv run
ruff check .` all checks passed, exit 0; `uv run pytest -q` 460 passed, 4
deselected, 5 warnings (all W1), exit 0.

Cycle 5's reviewers raised 83 findings, 70 after dedupe -- the taper held (269,
112, 137, 78, 70). Twenty-eight are scheduled in the c5 plan; every other one
has a row in `deferred.md` under `# Cycle 5` with its citation, its unchanged
severity and confidence, the reason, and the exit criterion. Cycle-5 IDs carry
the cycle number (`CR5-n`, `UX5-n`, `TR5-n` ...), and the merged clusters are
`Z1`...`Z10` in `.context/reviews/_aggregate.md`.

The cycle also closed the one hole the cycle-3 audit left: **TE4-7** reached no
plan row and no deferred row. It now has one.

Cycle-6 gate state at `dcc99cf`, run independently by two agents (18 min 24 s
and 18 min 41 s, identical figures): `uv run ruff check .` all checks passed,
exit 0; `uv run pytest -q` **495 passed, 4 deselected, 5 warnings** (all W1),
exit 0.

Cycle 6's reviewers raised 60 findings, **47 after dedupe** -- the taper held
and steepened (269, 112, 137, 78, 70, 47). Twenty-one are scheduled in the c6
plan; the other twenty-three have a row in `deferred.md` under `# Cycle 6`.
Four of those are deferred under a rule quoted in their row: two under
CLAUDE.md's standing design policy, two under the orchestrator's prohibition on
touching the deploy host. Cycle-6 IDs carry the cycle number (`CR6-n`, `UX6-n`,
`TR6-n` ...); the merged clusters are `AA1`...`AA47`, and the task IDs are
`C6-1`...`C6-21` (`W` was not reused -- `W1` is the gates plan's recorded
warning).

Cycle 6 landed all 21 of its tasks across twelve signed commits
(`67993e2`…`ca40a83`), each guard shown red under the mutation named in the
plan's progress table. Two of the cycle's OWN new tests were vacuous when first
written -- in both cases an assertion over source text was satisfied by the
comment explaining the code -- and both were caught by running the mutation
rather than by rereading. The rule that follows is in the plan: **an assertion
over source text must strip comments first.** A lint gate was also run as
`ruff check . | tail -2 && git commit`, where the pipeline's exit status is
`tail`'s; two errors shipped and were fixed in `ca40a83`. **Read a gate's own
exit status; never chain it.**

Cycle 6 also corrected three ledger lines rather than leaving them to be
re-derived: `U24(b)`'s premise (the completed rebuild did **not** clear the
`/var/folders/` leak, because the build ran pre-fix code loaded at process
start, so the exit criterion now says *started* after the fix); the c4 claim
that `check_ramps.py:169` was the only writer bypassing `_io.atomic_write`
(`calibrate/ground.py:127` and `scripts/adsb_extract.py:188` also do); and
V21's recorded mutation count (1 red test, not 2).

Cycle-7 gate state at `552baac`: `uv run ruff check .` all checks passed,
exit 0; `uv run pytest -q` recorded in the plan's progress section. Note the
correction to the line above: cycle 6's recorded **495** was taken before that
cycle's own last test landed; two independent reviewers measured **538 passed,
4 deselected** at `c823e31`, and the figure had drifted in the ledger rather
than in the suite.

Cycle 7's reviewers raised **121 findings, 58 after dedupe** — the taper broke
(269, 112, 137, 78, 70, 47, 58), because the reviewers were pointed at a
*design* as well as at the code and 14 of the 58 are about a format that did
not yet exist. Eighteen are scheduled in the c7 plan; every other cluster has a
row in `deferred.md` under `# Cycle 7`. Cycle-7 IDs carry the cycle number
(`CR7-n`, `UX7-n`, `TR7-n` ...); the merged clusters are `AB1`…`AB58` and the
task IDs are `C7-1`…`C7-18`.

The cycle-7 ledger was audited mechanically rather than by eye, the way
cycle 3 audited its own: all **58** merged clusters `AB1`…`AB58` are accounted
for, with **no gaps in the numbering and none unaccounted for** — 21 named in
the c7 plan, 46 carrying a full row in `deferred.md`, and several in both by
design (a cluster the plan handles still gets a deferred row saying where it
went, so it can be traced from either end). Every deferred row was checked to
carry all five required fields: the finding, its unchanged severity and
confidence, the citation, the reason, and the exit criterion. None was thin.

Cycle 7 closed `AA6` (the owner chose readings at resolution 6) and archived
`USER-2` as resolved by the owner — the latter at the two cycle-6 rows that
carried it as well as in the cycle-7 files, because the ledger is read
backwards more often than forwards. It also **did not implement the transport
half of the design it was given**, and the plan carries the account of why:
three independently fatal, separately measured reasons, two of them taken off
the live host. The block layout was implemented exactly as specified.

Three of cycle 7's own new guards were vacuous when first written, in a shape
cycle 6's rule does not cover: **an assertion whose expected value came from
the function under test**, and **assertions satisfied by a link's visible text
rather than its href**. The rule that follows is in the c7 plan: derive the
expectation from the specification or from a second implementation, never from
the code being tested.

Cycle-4 IDs carry the cycle number (`CR4-n`, `PR4-n`, `UX4-n` ...). Cycle 3's
designer used a bare `A1…A8`, which collided with the build plan's `A1…A17`,
and six of those findings reached no table at all -- the one gap in the audit
this file records. The prefix makes the collision impossible.

## Cycle 9

Twelve reviewer lanes, **109 raw findings, 71 after dedupe** (`AC1`…`AC71` in
`.context/reviews/_aggregate.md`). The taper across cycles: 269, 112, 137, 78,
70, 47, 58, ~50, 71. The count rose because three lanes ran measurements earlier
cycles had only reasoned about, and because cycle 8 shipped 38 tasks whose new
code had not yet been read by anyone.

Gate state at `7a1465b`, the cycle's starting HEAD: `uv run ruff check .` all
checks passed, exit 0; `uv run pytest -q` **700 passed, 4 deselected, 5
warnings** in 22 min 37 s, exit 0. The 495 figure carried in this file through
three revisions was stale; 700 is measured.

Thirty-one tasks are scheduled as `C9-1`…`C9-31` in
`2026-09-13-c9-page-failure-paths.md`; every other cluster has a row in
`deferred.md` under the cycle-9 headings or in that plan's own deferred table
(`DEF9-1`…`DEF9-30`), each with citation, unchanged severity and confidence, a
concrete reason and an exit criterion.

The cycle's most valuable result is a negative one, and it is the thing the run
brief asked to be checked first: **the tier-B reading fallback holds.** Seven
lanes verified it independently, one by driving the real fetch through a node
harness across seven failure modes. It does not call `fatal()`, it returns null,
nothing propagates uncaught, and the next origin switch retries.

What the cycle found instead was one reproducible crash on the live page (a
`resize` during the globe's load read a `let` in its temporal dead zone, and
`boot.js` turned that into `body.fatal` over the whole side rail), three
measured accessibility defects, a mixed-build gate blind to the mixed build in
`dist/` right now, and nine test guards that stayed green under mutation.

**Two of cycle 9's own new guards were vacuous when first written**, and both
were caught by running the mutation rather than by rereading — the same lesson
cycles 6 and 7 recorded, in a new shape each time. The shape here, named by the
test-engineer lane and now the **fourth** on the list: *the assertion's scope is
derived from its subject*, so breaking the code removes the assertion rather
than failing it. Three variants were seen: an incidental pattern match
elsewhere in the file, a filter keyed on a literal taken from the subject, and
an "actual" set built by filtering the expected one.

The four rules that now stand, one per cycle:
1. (cycle 6) An assertion over source text must strip comments first.
2. (cycle 7) Derive the expectation from the specification or from a second
   implementation, never from the code being tested.
3. (cycle 8) Read a gate's own exit status; never chain it behind `&&` or pipe
   it into `tail`.
4. (cycle 9) Scope an assertion to its subject explicitly. If deleting the code
   could delete the assertion's reach rather than fail it, the assertion is
   vacuous.

Conventions
- Each task carries the merged finding ID(s) so the provenance can be traced to
  the per-agent review text.
- "Cycle N" is the review-plan-fix cycle in which the task is targeted. Cycle 2
  is this run; later cycles re-read these plans and pick up the next targets.
- Every guard added must be shown to go red under a deliberate mutation
  (CLAUDE.md testing rule); the task's verification line says which mutation.
- Repo rules apply to every task, now or later: GPG-signed commits
  (`git commit -S`), conventional commit with gitmoji, no `Co-Authored-By`,
  fine-grained commits, `git pull --rebase` before push, no `--no-verify`,
  Python ≥ 3.14 via `uv`, IBM Plex Sans / no letter-spacing / no uppercase / no
  tabular-nums / dark theme / measured band colours / legend always visible.
- A plan whose every task is done (or whose unfinished tasks have been carried
  forward under their IDs) moves to `plan/archive/` with its final progress
  section intact. The pre-existing pipeline plan in
  `docs/superpowers/plans/2026-09-03-transport-pipeline.md` stays under `docs/`:
  its ledger (`.superpowers/sdd/…/progress.md`) records 11 of 15 tasks complete
  and Tasks 9, 10, 12, 13 done outside the plan or replaced (E10 in the docs
  plan adds the header that says so).
- Orchestrator constraints for this run: do not start, stop or re-run
  `transport-maps build-all` or `scripts/build_water_tiles.py`; do not delete or
  rewrite files under `dist/` or `data/` outside the sanctioned deploy script.
  Tasks that need a rebuild say so and wait for the orchestrator's rebuild;
  cache-key changes recompute their cache once on the next build and say so.

## Cycle 12

Eleven reviewer lanes (`code-reviewer`, `security-reviewer`, `perf-reviewer`,
`test-engineer`, `critic`, `architect`, `designer`, `verifier`, `tracer`,
`debugger`, `document-specialist`), no agent failures. Per-agent IDs `CR12-n`,
`SEC12-n`, `PR12-n`, `TE12-n`, `CRIT12-n`, `ARCH12-n`, `UX12-n`, `VER12-n`,
`TR12-n`, `DBG12-n`, `DOC12-n`; scheduled clusters `C12-n`.

The cycle's finding was CRITICAL and time-critical: the running 39-hour rebuild
would have died at origin 970 of 1,464 on one unvalidated coordinate, roughly
26 hours in, with a traceback that did not name the slug. Two lanes reached it
independently and it was confirmed a third time by execution. Escalated to the
owner, because stopping a running build is destructive; the code fix that makes
a restart safe landed without waiting.

Two defects were found by building rather than by reviewing, and both are in
`archive/2026-09-14-c12-review-findings.md` under "Found while implementing": the JS
function slicer every test in `tests/web/` uses returns a signature instead of
a body when a parameter is destructured, and a temporal dead zone
`ReferenceError` was written and caught before it shipped — the fourth of a
class CLAUDE.md is written around, and the first that
`test_module_scope_order.py` could not have seen.
