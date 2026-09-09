# Plans

Implementation plans derived from the multi-agent reviews in `.context/reviews/`
(cycle 2: per-agent files plus `_aggregate.md` with merged IDs K1…S6; cycle 1:
`cycle-1/_aggregate.md` with A1…J9). Finding IDs are stable across cycles: a
cycle-1 ID (C5, D13, F3, G1 …) keeps its name when it is carried into a cycle-2
plan.

Every review finding is either scheduled in one of the plans here (with a target
cycle) or recorded in `deferred.md` with its citation, original severity and
confidence, the reason, and the exit criterion that reopens it. Nothing is
dropped.

| Plan | Scope | Status |
|---|---|---|
| `2026-09-10-c2-web-ui-detail.md` | Page detail, ease of use, UI and accessibility (the user's brief for this run) | in progress (cycle 2) |
| `2026-09-10-c2-build-robustness.md` | Build correctness, artifact integrity, deploy and verification scripts, performance | in progress (cycle 2) |
| `2026-09-10-c2-gates-and-tests.md` | Lint and test gates: red gates, vacuous tests, hygiene | in progress (cycle 2) |
| `2026-09-10-c2-docs-attribution-calibration.md` | Attribution, stale docs and comments, calibration provenance, bookkeeping | in progress (cycle 2) |
| `2026-09-10-c2-security-and-policy.md` | Third-party policy, CSP, supply chain, blocked-on-owner items | in progress (cycle 2) |
| `deferred.md` | Findings not scheduled, with reasons and exit criteria; reopened items | living |
| `archive/2026-09-10-c1-*.md` | The five cycle-1 plans: every cycle-1 task done; every unfinished task carried into the matching c2 plan under its original ID | archived (cycle 2) |

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
