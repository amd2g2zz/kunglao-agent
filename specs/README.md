# specs/ — Executable Spec Layer

Two-layer spec rule (revised 2026-08-15, issue #355 — the old layer-1
dependency on an untracked `.research-tree-alignment/` directory broke
fresh clones and is retired):

- **Layer 1 — frozen design sources (read-only)**: the historical master
  specs live at `docs/design/archive/` (`design-spec.md` — architecture and
  algorithms; `module-design.md` — submodule contracts; the refactor plan
  is preserved in git history). These are HISTORICAL records of the
  pre-v0.1 `kong-agent` era, kept for citation traceability. For current
  behavior, the authoritative sources are `CHANGELOG.md` (v0.1 delivery
  record + internal version mapping), root `SKILL.md` (operative runtime
  contract), and `openspec/archive/` (delivered change proposals).
- **Layer 2 — executable specs (this directory + schemas/)**: each phase's
  `phase-N/contract.md` excerpts (with source line numbers, no
  retranscription) from the layer-1 master docs, plus `schemas/*.json`
  (JSON Schema as code).

## Freeze ritual (Step 0 of every phase)

Every contract.md header carries:
`FROZEN @ phase-N, change conditions: ① first write a RED test proving the
current state violates the new contract ② change contract.md + schemas/
③ write the change back into one of the layer-1 master documents ④ all in
the same commit`

**The only legitimate entry point for a contract change is a RED test.**
Without test backing, specs do not move.

## Golden master change flow

`tests/fixtures/golden/expected/` is the pre-refactor behavioral baseline
and is authoritative.

- Behavior change that is **legitimate** (new contract allows it) → follow
  the freeze ritual: RED test → change the spec →
  `python tools/auxiliary/capture_golden.py --refresh` → same commit.
- Behavior change that is **unexpected** (regression) → `--refresh` is not
  allowed; fix the implementation instead.

## Phase-0 standing decisions (guard against relitigation)

1. **Zero migration of legacy tests**: the pre-existing `test_*.py` files
   stay where they are, covered by pytest's `testpaths`; direct-run
   `if __name__ == "__main__"` mode remains (manual-run compatibility).
2. **Change lifecycle**: OpenSpec (`openspec/changes/` →
   `openspec/archive/` on delivery) is the change-tracking mechanism —
   adopted after the phase-0 evaluation. (The original phase-0 note
   rejected OpenSpec for the CLI-stdout-JSON contract surface; the repo
   adopted it anyway for change-proposal lifecycle, which is what it
   actually tracks.)
3. **Timestamp normalization**: golden replay normalizes `(ISO-UTC)`
   timestamps to `<TS>` (capture/replay crossing second boundaries);
   everything else is byte-exact.
