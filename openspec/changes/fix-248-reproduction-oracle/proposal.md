# fix-248-reproduction-oracle — algorithm claims settle on reproduction, not endpoint observations

## Why

Issue #248 (owner-amended 2026-09-12, folk-in design): an algorithm-class folk ask
("这些参数是怎么生成的") can legally take `verification_method: replay-evidence`
(`oracle_anchors.py` places reproduction and replay-evidence in the SAME admissible
set, `REPLAY_ORACLE_METHODS`), so a captured-parameter replay success settles a
generation-side proposition ("algorithm known") with an acceptance-side observation.
The artifact is internally consistent (copy-both-sides passes all consistency checks)
and the blind red-team re-derives exactly the acceptance fact — the discriminating bit
(compute S for a novel x without the source) is never measured.

## Mandatory experiment (ran BEFORE admission implementation)

Mock web-signer fixture (toy signer `sha256_hex(f"{appkey}|{ts}|{nonce}")`, three
captured parameter pairs, declared `variables` domains, reference-from-source as an
adapter interface with a stub). Proposed machinery:

- verifier samples a NOVEL input from the declared domains (not any captured input);
- reference output comes FROM THE SOURCE (adapter; stub in tests);
- candidates are executed closed-book on the novel input.

Results (seed 248):

- replay-only submission (echo table of captured signatures): novel-input pair MISS
  — structurally cannot pass, it has no computation to produce output for an
  unseen input.
- closed-book client (implements the algorithm): novel-input pair MATCH.
- wrong-algorithm near-miss (md5): MISS — the mutation-family discriminator holds.

DISCRIMINATING PROPERTY HOLDS. Proceeded to implementation.

## What Changes

Three logical pieces, zero user expertise required (system derives from the verbatim goal):

1. **Intake pinning** (`scripts/oracle_anchors.py`): generation-language detection
   (`is_generation_language`: 怎么生成 / 怎样生成 / 如何生成 / 怎么算 / 如何计算 /
   什么原理 / 什么算法 / 如何构造 / how is it computed / what algorithm / how is it
   generated / how is it constructed ...) classifies the goal as algorithm-class.
   `derive_verification_method` pins `reproduction` for algorithm-class goals;
   `intake_method_gate` REFUSES `replay-evidence` (or `static`/`manual`) for an
   algorithm-class goal. Users speak folk; the method is derived.
2. **Admission executes closed-book** (`scripts/replay_equivalence.py`, new faces):
   the replay artifact schema gains `reproduction_client` (workspace-relative path
   loadable by the existing `oracle_runner.load_client`). `admission_errors(ws, doc)`
   refuses an artifact without a runnable client (the copy-both-sides artifact that
   passed before); loads and EXECUTES the client on every captured pair — recomputed
   output != recorded `repro_output` is a FABRICATION refusal; the mutation gate runs
   on the recomputed rows. `sample_novel_input` samples a fresh combination from the
   artifact's declared `variables` domains; `novel_input_pair(doc, reference_source)`
   obtains the reference FROM THE SOURCE via the `reference_source` adapter (stub in
   tests; server submit / browser debug-anchoring in production — the judge's
   privilege) and requires the closed-book reproduction to match. Captured-parameter
   replay structurally cannot pass a novel-input pair (experiment above).
3. **Settle by need** (`scripts/settle_by_need.py`, new): acceptance-side observations
   (`replay-observation` evidence class) may settle input-contract / param-sufficiency
   claims only; generation-side propositions (algorithm-class needs) admit
   `reproduction` evidence only. `settle_attempt` returns the routing: a replay
   observation cited by an algorithm-class claim is re-routed to the input-contract
   claim; the algorithm claim stays open.

## Out of scope (one-line hooks)

Held-out calibration -> #135; nonstationary expiry -> #199; #215 keyword widening ->
separate judgment.

## Impact

- Additive: new functions in `oracle_anchors.py` / `replay_equivalence.py`, one new
  module `settle_by_need.py`. Existing artifacts without `reproduction_client` now
  refuse at the new admission face (`equivalence_verdict` unchanged in shape; the new
  face is invoked by admission/tests per the issue acceptance block).
- Risk: false refusals for workspaces whose artifacts predate the field — refusal
  reason names the missing runnable client explicitly.
