# Tasks — issue-462-kernel-actuation

- [x] W3 RED: load_store real-face tests + the AST stale-import
      tripwire (IdentityStore/PosteriorsStore may never return to
      load_store) — failed pre-implementation
- [x] W3 GREEN: rlvr/strategy_store.py (method_lead / decayed_weight /
      cell_count over the landed faces); silent degrade closed
- [x] W3 review follow-ups: proposal prior counts proposals never
      outcomes (dispatch-source filter, negative-control pinned);
      docstring corrections
- [x] W5 RED: TestSettlementFeed462 (settle→observe→credit non-None→
      fold mass; honest gap; no double-bank; clamping) — failed
      pre-implementation
- [x] W5 GREEN: q_cells.observe_settlement + the settle_round_credit
      bank (first-successful-settlement guard); review fix: guard tests
      settlement presence (retry-after-recorded-unsettled pinned)
- [x] W4 RED: kernel-samples envelope test — failed pre-implementation
- [x] W4 GREEN: _sample_envelope_family + envelope/receipt wiring in
      the dispatch act; review fixes: registry intersect (retired
      tokens never ride the prior) + the fail-open regression pin
- [x] W1+W6 RED: TestKernelRoundClosure462 (T2 built+drained at
      production closure; strategy composed+versioned with a real
      lead; compose-face failure stays fail-open) — failed
      pre-implementation
- [x] W1+W6 GREEN: round_closure kernel faces (compose host + T2),
      mechanisms registry entry; review fixes: writer-unique atomic
      persist, the strengthened fail-open pin (cage isolation proven)
- [x] W2 RED: seam emission/determinism/self-heal/workguard-integration/
      cold-silence tests — failed pre-implementation
- [x] W2 GREEN: write_seam derived projection + _atomic_write_text
      migration; review fixes: broad seam cage + errors=replace,
      unconditional cold silence (budget telemetry cannot break it),
      corrected telemetry fixture (the real cost_events.jsonl face)
- [x] §9 integration: two decision events with different evidence
      produce visibly different injected content citing the new ledger
      row (the REAL chain: settle → fold → compose → seam)
- [x] freshness-merge dev (#459 parallel dispatch): W4 sampler
      byte-identical inside _launch_dispatch; all reviewed files
      byte-identical; baselines re-minted as a pair
- [x] CI hygiene: the two atomic-cleanup handlers made non-silent (the
      #275 house rule — baseline registration rejected by the ratchet);
      deploy manifest byte-fresh
- [x] openspec change created; validate --strict green; requirement →
      implementation → test mapping table in the PR body
