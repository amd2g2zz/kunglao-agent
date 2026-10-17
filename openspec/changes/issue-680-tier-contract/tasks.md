# tasks — issue-680-tier-contract

## 1. RED tests (first)

- [x] `tests/test_tier_contract_680.py` — mismatch REJECT with correct
  value in guidance; match allows; `agent-reasoning:` deviation allows
  with stderr record; uncheckable claim allows; verifier-remediation
  dispatch skips tiercons (D2 mirror); eta writer raises to
  max(eta, tier) and never lowers; rank_feeds carries additive `tiers`;
  `Action.to_dict()` carries `tier`; the C-007 acceptance-claim shape
  dispatches at its computed tier
- [x] RED verified: 5 failed / 4 passed before implementation
  (9 tests at RED; the verifier-remediation test joined at GREEN when
  the D2 skip landed)

## 2. Tier consistency gate (T2)

- [x] `hooks/worker_budget_core.py`: import `action_tier` from
  priority_ratio (`_action_tier`, None on partial deploy)
- [x] `hooks/worker_budget_gates.py::check_tier_consistency` — mismatch
  REJECTs with the derived value; `agent-reasoning:` records + allows;
  no-claim / not-in-register / unavailable-scorer allow
- [x] `hooks/worker_budget_sinks.py`: wired as `tiercons` in the pre_check
  battery BEFORE the ladder gate, skipped for verifier-remediation
  dispatches (#237 D2 mirror); REJECT_FIXES guidance entry
  (`action_tier` keyword); REJECT_NAMES registry updated

## 3. eta writer (T3)

- [x] `hooks/worker_budget_sinks.py::_write_eta_at_dispatch` — ALLOW-tail
  writer `max(eta, tier)` via ws_yaml canonical renderer, fail-open, at the
  approval point next to `_flip_claim_in_progress`

## 4. Decision-surface surfacing (T4)

- [x] `scripts/priority_ratio.py::_emit_rank_feeds` payload gains
  additive `tiers` key (existing keys untouched)
- [x] `Action.to_dict()` carries `tier` (additive); #12 frozen capture
  updated for the additive key (scores/order unchanged)

## 5. Fixture repairs the new gate surfaced

- [x] `tests/test_worker_budget.py`: `_healthy_ws` default eta 1->0
  (matches the default tier-1 envelope); `tier` scenario reshaped to the
  ladder-invariant shape (consistent envelope + lagging OTHER claim);
  devreason/agenttype etas aligned; the T3 VM-channel scenario declares
  tier=3 in the PROMPT envelope (was parked in the deprecated desc
  channel); `tiercons` added to REJECT_NAMES / REJECT_FIX_KEYWORDS
- [x] `tests/_tiers.py`: `test_tier_contract_680` registered FAST

## 6. Verification

- [x] `uv run python -m pytest tests/test_tier_contract_680.py -q -n 2`
  -> 10 passed
- [x] neighboring suites green (priority_ratio / worker_budget / gate /
  pre_check consumer / decide families; the 2 tier_census failures are
  pre-existing full-collection artifacts, verified identical on dev)
- [x] `uv run ruff check` clean on the touched files
- [x] `openspec validate issue-680-tier-contract` exit 0
