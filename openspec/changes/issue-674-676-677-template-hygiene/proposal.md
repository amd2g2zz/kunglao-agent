# issue-674-676-677-template-hygiene — three template-hygiene fixes

## Why

Three shipped defects share one seam — the workspace template machinery's
hygiene contracts:

1. **issue 674** — the workspace-deployed copy of `template_version.py`
   resolves its root as `<ws>/.claude`, where neither repo version asset
   exists by design. Every ws-side consumer that left `skill_version=None`
   raised `RuntimeError` instead of returning a verdict, crashing the
   version-consistency gate of the deployed `convergence_check.py` — the
   exact form the injected constitution instructs at session start.
2. **issue 676** — the rendered `global_plan.txt` carries the open thread
   only (terminal claims are filtered out by construction), while the
   plan-drift detector flagged every register claim absent from the plan.
   Terminal claims therefore fired `ORPHAN_CLAIM` after EVERY re-render
   and the B1o blocker refused dispatch forever (field-evidenced on a live
   workspace: repair held only until the next projection write).
3. **issue 677** — `ws_yaml.py` is the single sanctioned mutator of the
   registers, but its `safe_load -> safe_dump` round-trip drops every
   comment: the leading header block — the template-version stamp AND the
   marker family riding the same block (e.g. `[initialized]`) — was
   stripped by every sanctioned status write, faulting the stamp contract
   on the next selfcheck.

## What Changes

1. **`template-version-receipt/1`** — `read_skill_version()` gains the
   deploy receipt as a third source: `pyproject.toml` →
   `.claude-plugin/plugin.json` → `deployed-manifest.json:source_version`
   → raise (guard unchanged). The skill tree never resolves the receipt
   (its root ships `deploy-manifest.yaml`, a different asset), so
   in-tree behavior is byte-identical.
2. **`plan-drift-terminal/1`** — `ORPHAN_CLAIM` exempts register claims
   whose status is in the canonical TERMINAL set: an unlogged frontier
   item is by definition not terminal, and every other class keeps
   auditing terminal claims (`UNVERIFIED_EVIDENCE` for PROVEN,
   `STALE_NEXT_STEP` for next-step sections).
3. **`ws-yaml-header/1`** — every sanctioned `set`/`append`/`del`
   re-prepends the file's leading comment header byte-identically above
   the canonical body; a register header without a stamp keeps the
   existing value-recovery chain (file → same-dir `CLAUDE.md` → active
   skill version). A sanctioned write leaves `verify_stamps() == {}`.

## What NOT changed

- The renderer keeps its open-thread semantics (no settled section in the
  rendered face); the detector-side exemption is the single owner for the
  terminal-claim seam. A complementary renderer-side settled section is
  recorded in design.md as an open option, not taken here.
- `UNVERIFIED_EVIDENCE` semantics (issue 241 reality check) untouched.
- Non-header comments inside YAML bodies keep being dropped — only the
  leading block is contractual.

## Out of scope

- The gate's generic fix text ("add claim … to global_plan.txt") on
  rendered faces — cosmetic, cross-cutting, tracked by its own seam.
- Baseline-ledger housekeeping for unrelated files (the emit-run
  tightening of `hooks/round_closure.py` was deliberately not carried).
