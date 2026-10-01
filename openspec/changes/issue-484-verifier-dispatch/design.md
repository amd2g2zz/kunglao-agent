Design (self-reviewed against #462 kernel actuation and #476 wave cage — both read):
1. New _run_verifier_act mirrors _run_dispatch_act with a V-prefixed prompt file and the verifier contract block (maker-checker: verifier NEVER writes facts; register edits via YAML-safe python, absorbing the #482 hand-written-YAML lesson into the contract text).
2. Single verifier act per decision (no wave — verification is light); same per-act rollback.
3. After the act: attempt promote_claims([claim]) via the existing repo gate; refusals recorded in detail["promotions"], non-fatal.
4. Convergence path: promoted claims flip convergence_check's decision toward CONVERGED; verdict face runs post-loop as today.
