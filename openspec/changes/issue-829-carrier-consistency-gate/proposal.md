# No cross-carrier consistency gate: four state layers drift independently (#830)

Child of #825.

## Why

The incident's remediation itself proved the gap: after the register was corrected (15 PROVEN → INFERRED), an arbiter found 6 residue classes spread across the other carriers:

- `facts/_INDEX.md` still listed 14+ VERIFIED rows, duplicate F014 lines, and **F010 (primary q1 fact) entirely missing** — nothing compares the index to the register.
- `notes/*.md` retained orchestrator-bulk-flipped `verify_status: passes` (16 files) — the exact layer `convergence_check.py` C0 reads; the next loop would have re-judged CONVERGED from the fake-green notes.
- `facts/F015.md` frontmatter held `status: VERIFIED` + `verified: false` + `verified_by: ...pending` simultaneously (the status flip touched only the register).
- register YAML carried duplicated keys (title:/boundary_type: twice for 5 claims) — YAML parse silently takes the last.
- `verified_by` strings still cited the quarantined (renamed) redteam files — dangling references unchecked.
- `global_plan.txt` kept the stale 15-PROVEN roster with its original "not perfidy" verdicts — no amendment semantics.

Each carrier has its own lint (facts via lint_facts, register via R1) but **no pairwise gate**: register↔facts status, register↔_INDEX rows, notes.verify_status↔facts.verified, verified_by↔file existence.

## What Changes

- `lint_workspace` (or new `carrier_consistency_gate.py`) hard-errors on:
  (a) claim PROVEN in register but its fact not VERIFIED, and vice versa;
  (b) _INDEX row status ≠ fact frontmatter status;
  (c) notes verify_status=passes without fact verified:true on the cited claim;
  (d) `verified_by` citing a non-existent file;
  (e) duplicate YAML keys (strict loader).
- Run from write_guard for register/_INDEX/notes carriers, and from convergence_check before CONVERGED is even considered.