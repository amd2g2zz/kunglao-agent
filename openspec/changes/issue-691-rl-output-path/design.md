# design — issue-691-rl-output-path

## D1 — the gate's own draw is the reconciliation authority (anti-spoof)

The envelope is LLM-authored, so the recorded sample cannot come from
it. `_method_family_gate` recomputes the draw at dispatch time via
`rlvr.strategy_store.reconcile_declaration(ws, declared)`: the same
prior chain, seed (`q_cells_seed_state`) and sampler kwargs that
`method_lead` renders into the digest — recomputed, not trusted. The
comparison is therefore against what the sampler WOULD choose at
dispatch state, which is the only number the envelope cannot move. A
state change between decide-time and dispatch-time shows up honestly as
a recorded deviation, not a lie in either direction.

## D2 — propensity semantics: the draw probability of the DECLARED family

`propensity = w(declared) / Σ w(candidates)` from the receipt's own
candidate weights — the exact probability of the proportional draw
(`u ≤ cumulative`), rounded to 6dp. Three regimes, all honest:

- declared == sampled (sampler-chosen): the true behavior propensity of
  the taken action (1.0 for a sole candidate);
- declared ∈ candidates but not drawn: its sub-1.0 mass (how plausible
  the deviation was under the sampler);
- declared ∉ candidates: **0.0** — the draw could never have chosen it.
  Not a gap: a real number OPE can skip on (`p > 0` guard), unlike null.

`null` is reserved for the genuine gaps: no proposal material at all
(cold workspace — `method_sample` returns None), no declaration, or a
sampler failure (ONE rate-limited warn carrying the error class). The
row always carries the three keys (explicit nulls — stable-schema
discipline); `append_usage_row` validates the boundary (bool/NaN/
out-of-[0,1] → null, never a raise).

## D3 — deviation is a recorded decision, never a new gate

The 2026-10-14 acceptance amendment: "NOT add another rule gate —
exception paths must be decisions with recorded reasons, never a new
prefix bypass." So `deviates: bool` only chooses whether ONE
`sample_deviation` event (registered in `event_taxonomy.EMIT_ACTIONS`)
is emitted — declared, sampled, propensity, prior_source, and the
`agent-reasoning:` text when the prompt declares one (the prefix that
excuses the top-1 claim rank elsewhere never silences this record).
The gate's return contract is untouched: vocabulary validation remains
its only REJECT face, and every reconciliation miss degrades to the
all-None gap view (fail-open; a sampler failure is one rate-limited
warn — the cold/no-declaration gaps are silent, the honest gap). The dispatch
passes with or without the deviation; what changes is that the
deviation is visible as a recorded row + event instead of invisible.

## D4 — ONE draw implementation, two faces, labeled provenance

`method_sample(fp)` is the single draw path: labeled prior chain
(history → explicit intake `llm-prior` → cross-task store) + the same
seed + the same feature/warm/death kwargs, returning the receipt with an
additive `prior_source` (history | llm_prior | store). `method_lead`
delegates (`str(receipt["family"])`), so the advisory lead the
orchestrator reads and the gate's reconciliation can never disagree on
the same state. `_proposal_prior` keeps its exact signature/behavior
(measured history only — its tests pin the dict); the labeled face
wraps it and adds the intake-prior branch, which only fires where the
old chain had no candidates to lose. The `prior_source` label rides the
strategy_store wrapper, never `sample_method_family`'s kernel receipt —
the bit-exact receipt faces stay byte-identical.

## D5 — T4 verifies the landed path, not a new writer

`record_case_settlements` (settle_round_credit), `PosteriorLedger`
(#106) and `priority_ratio.case_face` (#107 linkage) already landed as
code — the live gap was workspace arming (#678: `oracle/cases/` never
created). The verification test therefore builds the arming itself
(register + oracle cases), settles through the REAL writer
(`record_case_settlements`, +1 alpha/beta per pass), and pins the
end-to-end claim: the ledger file appears with moved posteriors, the
feeds say `Thompson Beta over 1 linked` (never cold-start), and the
rank order flips (leader dragged to Beta(1,41), trailer boosted to
Beta(41,1) — the flip is overwhelming under the deterministic
per-claim forks, not hoped-for). If this test ever fails, the output
path into claim ranking is broken — which is exactly the acceptance
criterion the issue names.

## D6 — additivity everywhere it touches contracts

Usage rows: three new explicit-null keys (old readers use `family` /
`cell` by key). Events: one new registered word. Kernel receipt:
untouched. `rank_feeds`: untouched (the constraint is satisfied
vacuously — this card adds no field to it). Gate return contract:
untouched. The only behavioral delta outside telemetry is `method_lead`'s
prior chain gaining the intake-prior branch for workspaces with NO
measured history and an explicit `runs/llm-prior.json` — where the old
chain returned the store fallback or None (pinned by
test_method_lead_falls_back_to_the_cross_task_store, which carries no
intake doc and is unchanged).
