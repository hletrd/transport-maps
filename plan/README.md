# Plans

Implementation plans derived from the multi-agent reviews in `.context/reviews/`
(cycle 4: per-agent files plus `_aggregate.md` with merged clusters Y1…Y30 and
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
target cycle), fixed in a commit whose body carries the evidence, or recorded in
`deferred.md` with its citation, original severity and confidence, the reason,
and the exit criterion that reopens it. Nothing is dropped, and nothing needed
to act on a finding lives only in an untracked file. Cycle 3 audited this
mechanically: all 142 finding IDs its reviewers raised are named in `plan/`,
including thirteen that had been carried only in the review text.

Cycle 4's designer found one gap in that audit: six cycle-3 designer findings
(A3-A8) reached no table, and the designer's `A1…A8` collide with the build
plan's `A1…A17`. Both are scheduled in U28. Cycle-4 IDs are prefixed with the
cycle number (`CR4-n`, `UX4-n` …) so the collision cannot recur.

| Plan | Scope | Status |
|---|---|---|
| `2026-09-10-c2-web-ui-detail.md` | Page detail, ease of use, UI and accessibility (the user's brief for this run) | cycle 2 done; 37 tasks open across the five, carried to cycle 5 |
| `2026-09-10-c2-build-robustness.md` | Build correctness, artifact integrity, deploy and verification scripts, performance | cycle 2 done; 37 tasks open across the five, carried to cycle 5 |
| `2026-09-10-c2-gates-and-tests.md` | Lint and test gates: red gates, vacuous tests, hygiene | cycle 2 done (W1 recorded); open tasks carried to cycle 5 |
| `2026-09-10-c2-docs-attribution-calibration.md` | Attribution, stale docs and comments, calibration provenance, bookkeeping | cycle 2 done; 37 tasks open across the five, carried to cycle 5 |
| `2026-09-10-c2-security-and-policy.md` | Third-party policy, CSP, supply chain, blocked-on-owner items | cycle 2 done; 37 tasks open across the five, carried to cycle 5 |
| `2026-09-10-c4-page-deploy-and-licence.md` | Cycle 4: the page a visitor reads, the three defects that would break the deploy, and two licence obligations (U1…U28) | cycle 4: open |
| `deferred.md` | Findings not scheduled, with reasons and exit criteria; reopened items | living |
| `archive/2026-09-10-c1-*.md` | The five cycle-1 plans: every cycle-1 task done; every unfinished task carried into the matching c2 plan under its original ID | archived (cycle 2) |
| `archive/2026-09-10-c3-*.md` | Cycle 3 (T1…T31): 28 done; T24, T26 and T28 carried into the cycle-4 plan as U28, U10 and U11 | archived (cycle 4) |

The five cycle-2 plans do not move to `archive/` yet: 37 tasks across them are
still open, and the archive convention below applies only when every task is
done or has been carried forward under its ID. `W1` in the gates plan stays open
by design -- it is a recorded warning with an exit criterion, not an unfinished
fix.

End-of-cycle-3 gate state at `43b99f5`: `uv run ruff check .` all checks passed,
exit 0; `uv run pytest -q` 390 passed, 4 deselected, 5 warnings (all W1), exit 0.

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
