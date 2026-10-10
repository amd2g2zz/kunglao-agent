# design — issue-467-deploy-numpy

## Context

The deployment model (post-#783/#810, 0.1.6 sweep #6):

- CODE flows repo -> deploy-manifest.yaml -> `<ws>/.claude/{hooks,scripts,
  references,templates,tools}` (deploy_workspace_copy at init,
  deployed_refresh at upgrade).
- ENV flows framework install root -> `uv run --project <root>` (its
  pyproject.toml + uv.lock + .venv).
- The framework root is a git clone of the repo: its manifest derives
  from the repo's by construction on update (pull/plugin-update). There
  is no build step that could fork the manifest — the drift in #467 was
  TEMPORAL (stale clone), not a pipeline fork.

Therefore the single-source requirement is satisfied by construction and
the load-bearing fix is the GATE: make the mixed-drift shape
(env root older than the deployed code) fail loud at the moment it is
created, instead of 218 fail-open warns per E2E round.

## Layer choice (why deploy_workspace_copy + CI, not the tick path)

Candidate layers considered:

1. **Heartbeat/statusline runtime** — rejected: the faces are fail-open
   by contract (a face never breaks the snapshot); making them
   fail-closed converts a warn into a broken tool call. The #467 defect
   is a DEPLOYMENT defect and must be refused at deployment time.
2. **hooks_selfcheck per-tick battery** — rejected: the selfcheck runs
   as heartbeat_tick step 0 every tick; the AST scan measures ~5 s over
   hooks+scripts+tools. Wrong cost class for the tick path.
3. **build_hook_entry** — rejected: it is the #445 single SOURCE for
   entry construction, called per hook file at wire time; embedding a
   5 s scan per call (or even cached-once) couples entry-shape logic
   with tree scanning. The deploy face is the natural chokepoint: no
   deploy, no wiring.
4. **deploy_workspace_copy (init) + deployed_refresh (upgrade)** —
   chosen: they are the two writer faces of the deployed surface (the
   #783 D1 contract). The gate runs once per init/upgrade where 5 s is
   noise, and the refusal prevents the broken workspace from ever
   existing.
5. **CI (release-check lint-hygiene leg)** — chosen for the source
   side: repo self-consistency (hard imports covered by repo pyproject)
   catches the code-before-manifest class before any deploy. This
   generalizes release-receipt's substring test into a real scanner.

## Guarded-import policy (the honest exemption)

An Import/ImportFrom node is GUARDED iff an ancestor Try catches
ImportError, ModuleNotFoundError, or bare/Exception. Rationale:

- The repo's degrade-by-design idiom is exactly this shape
  (pytest_timeout, tqdm, rho_llm_backend, tomli, yara, jinja2 lazy
  render). These imports have written-down failure paths; they are
  optional by construction.
- The #467 class is module-level UNGUARDED imports in library modules
  (`scripts/rlvr/*.py: import numpy as np`). A guarded lazy FACE
  (statusline_snapshot's `from winrate_curve import face` inside
  try/except) does not hide the failure: the gate scans the whole tree,
  and winrate_curve + rlvr.winrate carry the unguarded hard imports.
- Verified against the live tree: the hard set is exactly
  {numpy, yaml, pefile, capstone} — all declared in the repo pyproject;
  the guarded-undeclared set is {jinja2(declared anyway), tomli,
  tqdm, pytest_timeout, rho_llm_backend, yara, z3(declared anyway)} —
  all degrade-by-design.

## Name mapping

Import names and distribution names diverge (yaml vs PyYAML, z3 vs
z3-solver). Normalization: PEP 503 (`[-_.]+` -> `-`, lowercase) plus an
explicit alias table for the known mismatches. Declared side parses
`[project].dependencies` requirement strings, takes the name token
before the first `[<>=!;` — the instrument_menu.declared_deps parse
pattern, reused via lazy import (deployed sibling, single parse
implementation); a tolerant line-parse fallback covers a tomllib-less
3.10 floor.

## check() contract

    check(surface_root, env_root=None) -> {
      "ok": bool,
      "surface_root": str, "env_root": str|None,
      "missing": [{"module", "dist", "needed_by": [files...]}],
      "guarded_undeclared": [modules...],
    }

- env_root=None -> the package self-check (surface==env, the CI face).
- env_root pyproject unreadable -> treated as declaring nothing
  (it genuinely cannot serve the surface; the #6 ephemeral-env
  precedent: refuse rather than trust).
- env_root unresolvable (None from _framework_project_root) ->
  WARN + proceed (mirrors build_hook_entry's documented fallback;
  never blocks wiring on a probe failure).

## Wiring postures

- deploy_workspace_copy: gate BEFORE the copy loop (zero partial
  writes), raise RuntimeError on missing. Its docstring already
  promises fail-loud on unreadable manifest — same posture, new
  condition. The message names modules, the env root, and the
  remediation ("update the skill package at <root>, then re-run
  init/upgrade").
- deployed_refresh.refresh: never raises into the migration (D4
  contract) — the gap lands as a kunglao_log warn + a
  `dep_gap=...` part in the returned detail string (day-log
  observable, upgrade proceeds; the workspace's own hook warns then
  carry the incident).

## Cost

One-shot AST scan of ~400 files ≈ 5 s (measured on the live tree),
init/CI only. Per-tick cost: zero (no tick-path wiring).

## Risks / trade-offs

- A user with an intentionally old production install running init
  from a newer repo now gets a REFUSAL instead of a silently broken
  workspace. That is the intended behavior change (#467 acceptance);
  the remediation is mechanical (update the install).
- Tests invoking deploy_workspace_copy resolve the env root to the
  repo tree (fallback chain) — repo self-consistency keeps them green.
- The scanner is text/AST-based, not execution-based: dynamic imports
  are out of scope (documented limitation, none on the third-party
  surface today).
