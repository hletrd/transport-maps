# Plans

Implementation plans derived from the multi-agent review in `.context/reviews/`
(per-agent files plus `_aggregate.md`, which carries the merged finding IDs used
below: A1…A18, B1…B3, C1…C13, D1…D20, E1…E15, F1…F14, G1…G2, H1…H14, I1…I5,
J1…J9).

Every review finding is either scheduled in one of the plans here (with a target
cycle) or recorded in `deferred.md` with its citation, original severity and
confidence, the reason, and the exit criterion that reopens it. Nothing is
dropped.

| Plan | Scope | Status |
|---|---|---|
| `2026-09-10-c1-web-ui-detail.md` | Page detail, ease of use, UI and accessibility (the user's brief for this run) | in progress (cycle 1) |
| `2026-09-10-c1-gates-and-tests.md` | Lint and test gates: red tests, vacuous tests, lint debt, marker registration | in progress (cycle 1) |
| `2026-09-10-c1-build-robustness.md` | Build-all failure modes, artifact consistency, verification scripts | in progress (cycle 1) |
| `2026-09-10-c1-docs-attribution-calibration.md` | Attribution, stale docs and comments, calibration provenance | in progress (cycle 1) |
| `2026-09-10-c1-security-and-policy.md` | XSS escaping, security headers, third-party policy, supply chain | in progress (cycle 1) |
| `deferred.md` | Findings not scheduled, with reasons and exit criteria | living |

Conventions
- Each task carries the merged finding ID(s) so the provenance can be traced to
  the per-agent review text.
- "Cycle N" is the review-plan-fix cycle in which the task is targeted. Cycle 1
  is this run; later cycles re-read these plans and pick up the next targets.
- Every guard added must be shown to go red under a deliberate mutation
  (CLAUDE.md testing rule); the task's verification line says which mutation.
- Repo rules apply to every task, now or later: GPG-signed commits
  (`git commit -S`), conventional commit with gitmoji, no `Co-Authored-By`,
  fine-grained commits, `git pull --rebase` before push, no `--no-verify`,
  Python ≥ 3.14 via `uv`, IBM Plex Sans / no letter-spacing / no uppercase / no
  tabular-nums / dark theme / measured band colours / legend always visible.
- A plan whose every task is done moves to `plan/archive/` with its final
  progress section intact. The pre-existing pipeline plan in
  `docs/superpowers/plans/2026-09-03-transport-pipeline.md` is not archived: its
  own ledger (`.superpowers/sdd/…/progress.md`) records 13 of 15 tasks done and
  its checkboxes were never ticked (finding E10, scheduled in the docs plan).
- Orchestrator constraints for this run: do not start, stop or re-run
  `transport-maps build-all` or `scripts/build_water_tiles.py`; do not delete or
  rewrite files under `dist/` or `data/` outside the sanctioned deploy script.
  Tasks that need a rebuild say so and wait for the orchestrator's rebuild.
