# tasks — issue-249-stalled-remedy

## 1. RED (TDD)

- [x] 1.1 tests/test_stalled_remedy_249.py (fast): the STALLED verdict
  JSON carries the invokable `remedy` (operator decompose, stuck claims,
  dispatch marker, mint command); the action string carries the same
  literals; #2 wording pins survive.
- [x] 1.2 fast: HEALTHY / NO_DATA / SPINNING output shapes untouched
  (remedy is STALLED-only; SPINNING out of scope).
- [x] 1.3 fast: cross-face marker sync (lib constant == detector prose
  literal) — a drift fails loudly.
- [x] 1.4 fast: `stalled_state` mirrors the verdict (stuck ids + flatlined
  open ids + remedy), None (fail-closed) off-STALLED / no ledger.
- [x] 1.5 fast: lib predicate channels — A (marker + stuck), B (marker +
  fresh register-OPEN claim absent from the flatlined set); narrowness —
  no marker never passes, marker alone not enough, channel B requires
  register OPEN and fails closed on unreadable register / empty state /
  blank claim.
- [x] 1.6 fast: the rc=1 face — remedy dispatch admitted, ordinary
  dispatch blocked, marked-but-not-stuck blocked, legacy 1-arg call
  blocked, state-verdict drift fails closed, lib outage fails closed,
  SPINNING rc=2 never exempt, crashed rc=4 fail-open preserved.
- [x] 1.7 fast: the sinks battery forwards (claim, payload, prompt) to the
  health gate.
- [x] 1.8 tests/test_stalled_remedy_full_cycle_249.py (slow): the pinned
  full cycle — HEALTHY -> STALLED (real CLI) -> ordinary dispatch REJECT
  (real pre_check) -> remedy dispatch admitted -> real ladder + real
  `mint_sibling_claims` -> marked sub-claim dispatch admitted -> unmarked
  dispatch stays REJECT -> parent retires SUPERSEDED -> real ledger row ->
  real CLI HEALTHY -> ordinary dispatch admitted.

## 2. GREEN

- [x] 2.1 scripts/convergence_health.py: STALLED_REMEDY_MARKER /
  STALLED_REMEDY_MINT_CMD constants (lib-sync pinned), STALLED action
  carries the invokable remedy, `remedy` key on the STALLED verdict JSON
  only, `stalled_state()` single state source for the exemption face,
  `_human` remedy line, docstring/exit-code comment updated.
- [x] 2.2 hooks/lib_kunglao.py: STALLED_REMEDY_MARKER +
  `is_stalled_remedy_dispatch(ws, claim_id, payload, prompt_text,
  stuck_ids, flatlined_open_ids)` — marker-gated, state-intersected,
  fail-closed.
- [x] 2.3 hooks/worker_budget_core.py: `_stalled_remedy_exemption`
  (lib predicate + detector state, fail-closed on every unresolvable
  input) + `check_convergence_health` optional (claim_id, payload,
  prompt_text) with the exemption INSIDE the rc=1 face only.
- [x] 2.4 hooks/worker_budget_sinks.py: pre_check forwards the dispatch
  context to the health gate.
- [x] 2.5 tests/_tiers.py: test_stalled_remedy_249 -> FAST_MODULES;
  test_stalled_remedy_full_cycle_249 -> SLOW_MODULES.

## 3. Verify

- [x] 3.1 ruff clean on all touched files (line-length 100).
- [x] 3.2 convergence_health + worker_budget + dispatch_gate 237 +
  obstacle-ladder regression suites green (-n 8).
- [x] 3.3 full fast tier green (-n 8).
- [x] 3.4 comment_hygiene_lint from repo root clean.
- [x] 3.5 deploy_manifest --write / --verify consistent.
- [x] 3.6 openspec validate clean.

## 4. Round-2 review fixes (BLOCK -> PASS)

- [x] 4.1 HIGH — channel B provenance pin: the sub-claim's depends_on
  must reference a stuck claim (operator-agnostic: issue-234 siblings and
  issue-241 splits both depend_on their stuck parent). Pins: the exploit
  shape (fresh unrelated OPEN + marker -> REJECT, predicate AND gate
  face, and in the full cycle S6b) and the real minted sibling ->
  ADMITTED (real mint_sibling_claims in the fast module + full-cycle S6).
- [x] 4.2 MEDIUM — remedy-depth escalation: every admit appends an
  operator-action telemetry row (assess excludes typed rows from the
  trajectory); stalled_state counts consecutive cycles per stuck claim
  inside the current stuck episode; at depth >= 2 the follow-through
  channel closes (channel A survives). Pinned: counting, episode reset,
  other-claim rows ignored, gate-face closure with channel A surviving.
- [x] 4.3 MEDIUM — dedicated tests for the two disclosed fail-closed
  arms: state-exception and predicate-exception both confirmed blocking.
- [x] 4.4 design.md Decision 1 false-invariant sentence corrected;
  Decision 1b documents the escalation semantics.
