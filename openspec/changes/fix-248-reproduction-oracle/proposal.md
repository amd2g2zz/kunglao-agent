# fix-248-reproduction-oracle — method-selection split (post2 slim scope)

## Why

Issue #248 (owner-amended 2026-09-12, folk-in design; SLIMMED by owner
ruling 2026-09-18 — post2 scope note on the issue, "exclude items with
slip tendency"): an algorithm-class folk ask ("这些参数是怎么生成的") can
legally take `verification_method: replay-evidence` (`oracle_anchors.py`
places reproduction and replay-evidence in the SAME admissible set,
`REPLAY_ORACLE_METHODS`), so a captured-parameter replay success can be
booked against a generation-side proposition with an acceptance-side
observation. The confusion begins at METHOD SELECTION (the two methods
are peer-selectable for the same folk ask, `oracle_anchors.py`), so the
post2 fix operates there. Zero user expertise required: the SYSTEM
derives the method from the verbatim goal.

## What Changes (post2 = deterministic method-selection split only)

1. **Intake pinning + separate admission** (`scripts/oracle_anchors.py`):
   generation-language detection (`is_generation_language`: 怎么生成 /
   怎样生成 / 如何生成 / 怎么算 / 如何计算 / 什么原理 / 什么算法 / 如何构造 /
   how is it computed / what algorithm ... — interrogative forms only;
   bare declarative passives like "is computed" are deliberately NOT
   markers, they also occur in acceptance statements) classifies the
   goal as algorithm-class. `derive_verification_method` pins
   `reproduction` for algorithm-class goals; `intake_method_gate`
   REFUSES `replay-evidence` (or `static`/`manual`) for an
   algorithm-class goal — reproduction and replay-evidence now have
   SEPARATE admission where they were peers. `validate_values` refuses
   to LAND the weak selection (the pre-write face kunglao-init /
   kunglao-upgrade already call).
2. **Settle by need** (`scripts/settle_by_need.py`, new): acceptance-side
   observations (`replay-observation` evidence class) may settle
   input-contract / param-sufficiency claims only (`need:
   yes_no_with_evidence`); generation-side propositions (algorithm-class
   needs: `model_selection`, `protocol_description`) admit
   `reproduction` evidence only. `settle_attempt` returns the routing: a
   replay observation cited by an algorithm-class claim is re-routed to
   the input-contract claim; the algorithm claim stays open. Unknown
   evidence classes fail closed. Library + tests only today — the
   settle-path wiring is a follow-up.

## Moved to #259 (v0.1.6) — cut from post2 by the slim ruling

The closed-book reproduction admission/verdict machinery:
`scripts/replay_equivalence.py` reproduction_client execution
(`admission_errors`, `load_ws_client`), verifier-sampled novel inputs
(`sample_novel_input`, `novel_input_pair`), the recorded novel-input
floor and its schema-lint face, and the source-derived reference
adapter. In-flight implementations of all of it (code, tests, experiment
notes) are preserved on WIP commit `6c0b410` of branch
`fix/248-reproduction-oracle` for salvage — this branch carries NONE of
it (`replay_equivalence.py` is unchanged by this change).

## Out of scope (one-line hooks)

Held-out calibration -> #135; nonstationary expiry -> #199; #215 keyword
widening -> separate judgment.

## Impact

- Additive: new functions in `oracle_anchors.py`, one new module
  `settle_by_need.py`. `replay_equivalence.py` is UNCHANGED.
- Risk: a generation-language FALSE POSITIVE misfiles an acceptance-class
  goal as algorithm-class and refuses its observational selection at
  intake. Mitigations: markers are interrogative-only (declarative
  passives never classify) and the refusal reason names the refused
  method explicitly so the operator can correct the goal text.
