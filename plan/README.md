# Plans

Implementation plans derived from the multi-agent reviews in `.context/reviews/`
(cycle 3: per-agent files plus `_aggregate.md` with merged clusters X1…X21 and
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

| Plan | Scope | Status |
|---|---|---|
| `2026-09-10-c2-web-ui-detail.md` | Page detail, ease of use, UI and accessibility (the user's brief for this run) | cycle 2 done; cycle 3 open |
| `2026-09-10-c2-build-robustness.md` | Build correctness, artifact integrity, deploy and verification scripts, performance | cycle 2 done; cycle 3 open |
| `2026-09-10-c2-gates-and-tests.md` | Lint and test gates: red gates, vacuous tests, hygiene | cycle 2 done (W1 recorded); cycle 3 open |
| `2026-09-10-c2-docs-attribution-calibration.md` | Attribution, stale docs and comments, calibration provenance, bookkeeping | cycle 2 done; cycle 3 open |
| `2026-09-10-c2-security-and-policy.md` | Third-party policy, CSP, supply chain, blocked-on-owner items | cycle 2 done; cycle 3 open |
| `2026-09-10-c3-page-detail-and-defects.md` | Cycle 3: page detail, ease of use, UI, and the defects the cycle-3 review confirmed (T1…T31) | cycle 3: 28 of 31 done; T26, T28 carried; T19's run against `dist/` waits for the rebuild |
| `deferred.md` | Findings not scheduled, with reasons and exit criteria; reopened items | living |
| `archive/2026-09-10-c1-*.md` | The five cycle-1 plans: every cycle-1 task done; every unfinished task carried into the matching c2 plan under its original ID | archived (cycle 2) |

None of the five moves to `archive/` yet: each carries an unfinished
**Cycle 3** section, and the archive convention below applies only when
every task is done or has been carried forward under its ID. `W1` in the
gates plan stays open by design -- it is a recorded warning with an exit
criterion, not an unfinished fix.

End-of-cycle-2 gate state at `29c6330`: `uv run ruff check .` all checks
passed; `uv run pytest -q` 356 passed, 4 deselected, 5 warnings (all W1),
exit 0.

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
