## Why
Three consecutive E2E rounds (7B/7C-1/7C-3) deadlocked on the same chain: workers produce (13 facts, crackme_reimpl.py written), but scripts/e2e/checkpoints.py:714 handles DISPATCH_VERIFIER by ranking claims then doing NOTHING — the verifier never runs, claims never promote, convergence never returns CONVERGED, the loop spins to the idle-circuit-breaker.

## What Changes
DISPATCH_VERIFIER decisions dispatch a VERIFIER act: a claude -p run with the maker-checker contract (verify the claim's facts/artifacts against the workspace's verification faces — replay equivalence, oracle probes, byte-exact; NEVER write facts), landing runs/verification-<claim>.md; the loop then attempts promote_claims through the #819 gate (refusals are honest, not failures). Same wave/rollback/budget semantics as worker acts.
