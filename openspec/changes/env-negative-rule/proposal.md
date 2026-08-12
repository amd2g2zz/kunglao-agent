# Proposal — env-negative-rule (#56)

## Why

F040 (a2b5e25c, 2026-08-11) showed a `dynamic_re` BP that got 0 hits being
inferred as "HandleCommand NOT on the inject path" — and on that basis
"correcting" the F034/F035 two-tier dispatch model. The provenance self-reported
an environment fault (debuggee PID 6500 WSS reconnect goroutine stalled, never
reconnected), so ALL BPs got 0 hits, not just HandleCommand. Static xref later
proved HandleCommand IS on the path (F049 superseded F040, PROVEN).

Inferring a NEGATIVE conclusion ("not on path" / "does not exist") from an
environment-faulted dynamic miss is the bug. `failure_analysis_gate.py` already
codifies "failed attempt != negative result" via its three-question method
mechanism; this change is the specialization of that principle to
**environmental negative evidence** in the PROVEN-promotion gate.

## What (gap assessment vs #48 — full evidence in design.md)

#48 shipped `scripts/blind_gate.py::check_inference_blind_scope` with the
env-fault diagnostic: when fact text carries `0 hits`/`0 occurrences` AND an
env-fault self-report, the claim cannot be PROVEN on the dynamic miss alone
(static xref mandatory). A synthetic probe of four F040-shape claims against
the #48 code:

| shape | inferential? | allowed? | caught by #48? |
|---|---|---|---|
| routing + "0 hits" + env-fault (F040 literal) | yes | no (STAMP) | yes |
| existence + "0 hits" + env-fault | yes | no (STAMP) | yes (via `0 hits`) |
| existence + "no call captured" + env-fault | **no** | **yes (PROVEN)** | **no — slips through** |
| "absent" + "no calls observed" + env-fault | **no** | **yes (PROVEN)** | **no — slips through** |

So #48 covers the F040 *literal* shape (~60-70% of #56, not the 90% the plan
estimated) but the rule as stated in the issue generalizes further:

1. the trigger vocabulary is `0 hits`/`0 occurrences` only — the issue's
   explicit **无调用捕获** ("no call captured") trigger is not recognized;
2. NEGATIVE-existence conclusions ("does not exist" / "absent") are not in
   `INFERENTIAL_PATTERNS`, so existence claims never reach the env-fault
   diagnostic — they short-circuit as "non-inferential" and pass.

## Residual (this change)

A **code generalization** of #48's gate, plus the doc entry and a regression
test — NOT a new gate function:

- **G1**: broaden the env-fault diagnostic's basis detector so
  "no call captured" / "no calls observed" / 无调用捕获 also trigger it
  (alongside `0 hits`/`0 occurrences`).
- **G2**: broaden `INFERENTIAL_PATTERNS` to flag NEGATIVE-existence conclusions
  ("does not exist" / "absent" / "not present" / 不存在) so existence claims
  reach the diagnostic.
- generalize the env-fault reason message from "cannot establish routing" to
  "cannot establish routing or existence".
- **doc**: add the env-negative rule to `failure-modes-monitoring.md` (F8
  family — self-confident false PROVEN), cross-referenced to #48 and
  `failure_analysis_gate`'s three-question mechanism.
- **test**: `tests/test_env_negative_rule.py` — F040 regression (asserts #48's
  existing rejection holds — acceptance #2) + the existence / generalized-vocab
  cases (the residual) + a complementarity test proving #56 does not duplicate
  #48's byte-anchor gate.

Complementarity: #48 = "BLIND sign-off must cover the inference";
#56 = the env-negative *specialization* (which dynamic-miss vocabulary and
which NEGATIVE conclusion shapes trigger it). Both live in the SAME gate
function and wire points — #56 adds no new gate.

## Non-goals

- Auto-healing / sign-off rewriting (the verifier re-run owns that).
- Dynamic-miss validation in general — ordinary dynamic evidence still passes
  the byte-anchor path; only env-faulted NEGATIVE inferences are blocked.
- Re-running the F040 RCA (analysis-workspace side, not this repo).
