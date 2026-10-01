Design (data structures first, per house ruling):

## Product schemas (JSON, one file per product under runs/distill-products/)
- playbook/1: {schema, name, problem_signature (feature tokens), steps: [{n, tool_ref, expected_evidence, known_traps, holes: [uncertain dims]}], provenance: {source, runs, first_ts, last_verified}, corroboration: int, retention: {detail_level: rich|skeleton, signals_snapshot}}
- decision-entry/1: {schema, signature_tokens, method_family, applicability, failure_modes: [{kind, cause, evidence}], statistics_consistency: bool|null, source_trust_ref}
- usage-card rides the #477 harvest manifest (extension field) or a shelf entry patch — no third store.
- lesson: unchanged (rollup's library).
- Source trust ledger runs/distill-trust.json: {source_id: {products_landed, products_falsified, trust: float, blacklisted: bool}}

## T-pass (fixed order, one function per stage, pure)
1. de_case(payload, provenance) -> payload: strip absolute paths, sample-specific bytes, transient env quirks; keep method (policy: anything not transferable is dropped, not rewritten).
2. promote_form(payload) -> (payload, form): if a code form is derivable (script exists / synthesizable), attach it; prose demoted to second-class metadata.
3. tag(payload, shelf) -> payload: capability tag, when/when_not (grown from decision-entry negatives — obstacles join here), version stamps (dependency/platform surfaces, O3).
4. verify(product_kind, payload, fixture) -> {ok, evidence}: playbook → replay to the same milestones on ≥1 fixture; usage-card → byte-exact pinned env; decision-entry → cross-check settlement statistics (contradiction flagged, not merged); lesson → general+self-start bar.
5. dedup(payload, existing) -> action: content-hash; near-dup by (kind, signature_tokens) → merge corroboration+1 (adaptive compression input).

## Adaptive retention (four signals — never a fixed dial)
detail_level = f(corroboration: first-of-kind=rich/multi=skeleton; source_trust; verification_strength: byte-exact=full/weak=thin; reconstruction_telemetry: runtime re-derive events loosen, never-retrieved tightens). Telemetry source: the audit stream (worker acts re-deriving known things) — read at T-pass time, not live.

## Analogy transfer (the owner's vuln scenario)
Layer-wise: case surface (dropped) / technique family (kept when features align — Jaccard pools from #460-B) / methodology (kept). Mismatch dims become explicit holes. Deployed as HYPOTHESIS plan (run-local only); step outcomes adjudicate: works → product + provenance "transferred, verified on our sample" + trust+1; fails → obstacle row + decision-entry negative + trust−1.

## Landing (L)
Existing #474 API only (run-local → post-run promotion gate). No second landing path. Budget ledger shared.

## Host integration
rollup (lessons) and #477 (harvest) call the T-pass for their products; #458's external candidates enter at de_case. Adoption is incremental — each producer migrates in its own PR after the spine lands.
