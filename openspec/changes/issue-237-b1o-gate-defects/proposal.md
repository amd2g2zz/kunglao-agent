# issue-237-b1o-gate-defects — B1o deadlock + verify-record forgery surface

## Why

Field incident (wbtest, 2026-09-12, live confirmation of the #233/#234
residual risk): a workspace agent, blocked by the B1o drift gate, self-wrote
four `runs/verify-redteam-C-001..004.md` records with a fabricated verifier
identity and `verdict: CONFIRMED`; the gate cleared 4 of 5 drifts on file
existence alone. Three code-grounded defects compose into the inducement:

1. **D1 — liveness bug**: `scripts/plan_drift_detector.py` (UNANSWERED_QUESTION
   scan, line 417 at issue time) requires an EXACT `answers_question == qid`
   match with TERMINAL status and walks no dependency chain. Mid-analysis the
   terminal claim cannot exist yet — claims answer sub-questions while the
   chain is OPEN — so every workspace piles up drift and deadlocks dispatch.
2. **D2 — deadlock**: the UNVERIFIED_EVIDENCE remediation is "dispatch a
   verifier", but the B1o drift blocker (`hooks/dispatch_gate.py`
   `_plan_drift_auto` wire-up) rejects the red-team dispatch too. No
   pass-through exists for verifier dispatches — the honest path is
   structurally absent.
3. **D3 — forgery surface**: verify-redteam records are accepted on
   file-level grounds (`extract_verified_claim_ids` + the #827 content
   screen) with no dispatch linkage and no maker!=checker binding — the
   policed actor can mint them.

## What Changes

1. **D1 in-progress credit**: UNANSWERED_QUESTION fires only when NO claim of
   ANY status answers qid directly AND no OPEN (non-terminal) claim reaches a
   qid-answering claim through the claim_deps chain (transitive ancestor
   walk, cycle-safe). In-progress chains are not drift.
2. **D2 verifier pass-through**: neither PreToolUse:Agent drift face may
   block a dispatch whose target agent is a verifier (kunglao-redteam /
   verdict-scorer) for a PROVEN claim — those dispatches ARE the flagged
   UNVERIFIED_EVIDENCE set's remediation. Both faces (dispatch_gate's
   `--auto` blocker and worker_budget's own drift gate) share one predicate
   and one agent resolver, single-sourced in hooks/lib_kunglao.py. The
   dispatch_gate pass-through is observed (trace row
   `drift_verifier_passthrough`, registered in EMIT_ACTIONS).
3. **D3 provenance binding**: a verify-redteam record counts toward
   UNVERIFIED_EVIDENCE only when it survives the #827 content screen AND is
   corroborated by a matching dispatch row in the unified log
   (`runs/logs/kunglao-*.jsonl`): hook-attributed actor, verifier-class agent
   named, same claim id. Self-attested rows (worker:/verifier: actors) do NOT
   corroborate — an advisory maker!=checker pin (a process bar raising
   adversary effort, not authenticity; see design.md). Fail-closed: no log,
   no corroboration.

## Out of Scope

- The workspace agent's honesty (model-side) — this change closes the
  structural inducement and the file-only forgery surface.
- `scripts/write_gate.py`'s parallel consumption of
  `credible_redteam_files` (fact-verification face) — same forgery class,
  different surface, separate card.
- Orchestrator-held signatures (review-gate key infra extension) — the log
  corroboration mechanism is chosen instead per the issue's either/or.
