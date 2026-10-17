# tasks — issue-686-crystallization-writeback

## 1. The RED contract

- [ ] `tests/test_crystallization_686.py`: the pins below
- [ ] confirmed RED before implementing

## 2. The faces

- [ ] `marl.record_negative` gains optional `claim_ref` / `step_ref`
      (only-when-present row keys); `marl.read_negatives()` public read
- [ ] `crystallize.resolve_method` — the claim's last usage row
      (family + tools), honest None
- [ ] `crystallize.crystallize_settlement` — failed step → deduped
      class negative with provenance; completed step + certified answer
      + banked credit → method broadcast with provenance
- [ ] `crystallize.revoke_claim` — atomic rewrite of both derived
      stores, per-store counts
- [ ] `settle_step` wires the write-back cage (after the credit face)
- [ ] `reconcile_case_settlements` revokes a flipped claim's derived
      rows

## 3. Gates

- [ ] new tests green; neighbors (705 marl / 690 step grain / 742 case
      amendment / 730 q cells) green
- [ ] ruff; formal-code; comment-hygiene; Family-K delegation shape
- [ ] manifest registration; openspec validate
- [ ] review-gate mint; CI green
