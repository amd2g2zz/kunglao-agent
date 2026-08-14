# Proposal — executable, evaluator-owned L2 red-team evaluation (#81)

## Why

The eval module explicitly defers real measurement:

- `scripts/kunglao_eval.py` L1-L5: "真实测量 deferred".
- Four of five fault types only return a description containing
  `scaffold - real injection deferred` (L29-L56); they do not change a running
  system.
- The command surface only self-checks, prints an arm configuration, or prints
  an injected-fault description (L119-L137); `tests/test_eval_harness.py` L1-L5
  states A/B/C measurement is deferred.
- `l2_redteam()` returns `NOT-RUN` when no externally supplied dispatcher
  exists (`scripts/kunglao_verify.py` L349-L365).

`--oracle-selfcheck` → "oracle selfcheck: 10/10" validates priority-function
examples only — not a task episode, tool dispatch, failure recovery, report
truthfulness, hard-sample handling, wall time, or token/tool cost. There is no
evaluator-owned receipt that can show whether the agent plans and adapts on
difficult RE cases, recovers from faults, avoids redundant work, or has an
overclaim rate below a defined threshold. `NOT-RUN` and scaffold output can be
mistaken for completed evaluation.

## Scope

1. Safe, isolated fixture corpus under `eval/fixtures/<case-id>/` — synthetic
   cases only (decode-flag with recorded transcript, provably impossible task,
   adversarial evidence with decoy strings + correct path). Each case carries a
   PUBLIC `case.json` (claims/deps/evidence seed/recorded tool transcript) and
   a HIDDEN `oracle.json` (expected outcome + failure taxonomy) readable only by
   the scorer. **No malware samples are executed on the host.**
2. Real bounded episodes: a deterministic episode loop in
   `scripts/kunglao_eval.py` runs candidate policy + the REAL `priority_ratio`
   core + real claim-status semantics through an injectable dispatcher/tool
   adapter (recorded transcript, not real tools). Arms A (mechanisms on) / B
   (mechanisms off) / C (single-agent) select the candidate policy.
3. Each fault type (throttle / implicit_fail / explicit_fail / impossible /
   adversarial) ALTERS an actual episode and the observed state transition is
   captured instead of a label.
4. Evaluator-controlled oracle: `OracleScorer` scores the episode output
   independently; hidden fixtures and scorer inputs are not writable by the
   candidate. Scoring dimensions (correctness / invalid work / misses /
   overclaims / time / cost / recovery) are reported SEPARATELY from the
   10/10 oracle self-check, which is kept unchanged.
5. Replayable receipts: machine-readable JSON + human-readable summary with
   case/environment/code digests, tool-call transcript hash, oracle outcome,
   failure taxonomy, wall time, token/tool budgets, cleanup/reset result.
   Same inputs → same receipt digests (wall time excluded from the digest).
6. `NOT-RUN` / `UNKNOWN` / failed injection / missing dispatcher = non-evidence:
   the capability score never passes on them; a failed fixture/injection
   produces `FAIL` or `INCONCLUSIVE`, never a green capability receipt.

## Non-goals

- No real malware execution, no VM, no network — fixtures are synthetic only.
- No change to the product orchestrator loop itself (`scripts/kunglao.py`,
  heartbeat, hooks — owned by other issues). `scripts/kunglao_verify.py` is
  imported read-only; `l2_redteam()` keeps `NOT-RUN` as its truthful value.
- No A/B/C statistical significance claim — trials are bounded and
  deterministic; the harness provides evidence, not an effect-size verdict.
- No pyproject/CI work (issue #80 owns that).

## Acceptance (from issue #81)

- ≥3 safe fixtures and repeated A/B/C trials execute end to end with replayable
  receipts.
- Throttle, implicit failure, explicit failure, impossible task, adversarial
  evidence each cause a measurable state transition and a non-success result
  when appropriate.
- `NOT-RUN`, `UNKNOWN`, a failed injection, or a missing dispatcher cannot
  contribute to a passing capability score or `PROVEN` claim.
- Correctness, invalid/redundant work, misses, overclaims, time, token/tool
  cost, recovery behavior reported separately from the oracle self-check.
- A failed fixture/injection produces `FAIL` or `INCONCLUSIVE`, never a green
  capability receipt.
