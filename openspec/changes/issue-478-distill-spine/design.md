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

## PR2 — adaptive retention, analogy transfer, landing wiring (adjudicated)

Design review before code (coordinator self-review, disclosed — the PR1
quota-wall precedent; the merge-time gate still requires the independent
reviewer). Three adjudications:

### Adaptive retention — precedence-disclosed, never a fixed dial
`retention(product, signals)` is PURE: no workspace access; the four
signals arrive as data. Precedence (safety first, deterministic):
1. baseline — corroboration >= 2 → skeleton, else rich;
2. weak verification (`strength != "byte-exact"`) → rich — never
   compress what is weakly verified;
3. `source_trust is None or < 0.5` → rich — trust is EARNED by landing;
   an unknown source never licenses compression;
4. never-exercised (`retrievals == 0 and rederive_events == 0`) → rich
   — no exercise evidence tightens;
5. `rederive_events > 0` → skeleton — runtime proved reconstruction.
Returns `{detail_level, actions, signals_snapshot}`; the snapshot IS the
retention block (tpass stamps `product["retention"]` with it). Skeleton
actions license dropping `form.prose` only (the one field promote_form
already demoted) — applied post-dedup, where the stored `_hash` is
already fixed, so exact-dup detection is unaffected. Wiring: tpass gains
an optional `signals=` kwarg and recomputes retention for BOTH the new
product and the merged-into prior (the corroboration-compresses path);
dedup's merged outcome now rides the prior as `product`. Telemetry is
read at T-pass time by the caller via `reconstruction_telemetry(ws,
product)` (audit stream `runs/logs/kunglao-*.jsonl`: rederive =
tool_call rows naming a steps[].tool_ref; retrievals = recall_injected
rows naming the product + tool_call rows naming its landed tool);
`signals_for(ws, product, verification_strength=...)` assembles the lot.

### Analogy transfer — layers, holes, hypothesis
`analogy_layers(payload, feature_match)` → `{kept, holes, aligned_dims,
similarity}`: source dims = problem_signature/signature_tokens;
similarity = feature_prior.jaccard (the #460-B pure face — its pools
are outcome masses, not needed here); case-surface dropped (de_case's
job), methodology always kept, technique-family kept iff similarity >=
FEATURE_ALIGN_FLOOR (0.5); mismatch dims = holes, sorted. Decision-entry
sources (signature_tokens) ride the same face.
`transfer_hypothesis(ws, product, *, feature_match=None)` writes the
run-local plan `runs/distill-hypotheses/<safe-name>.json`: a playbook/1
whose steps are the methodology layer, each carrying the mismatch holes
and `unverified: true`, plus a hypothesis block (status HYPOTHESIS,
transferred_from, layers_kept, similarity). feature_match absent AND no
pre-adjudicated `product["analogy"]` → SpineOrderError (a transfer
without feature adjudication is a skipped stage). Adjudication is the
RUNTIME worker's: works → trust_event(landed=True) (PR1's +1 face) +
provenance "transferred, verified on our sample"; fails →
trust_event(landed=False) (the falsify→blacklist path) + obstacle row +
decision-entry negative. PR2 ships the plan writer; the reward faces
already exist.

### Landing — the #474 tier-1 path, no second face
`land(ws, kind, product)` is the spine's single landing call:
1. inlet guard — validate_product non-empty → refuse (unknown kind or
   malformed product never lands);
2. trust gate — blacklisted source → refuse (PR1 gate wired in);
3. shared ledger, fail-closed parity — a corrupt ledger refuses; a
   COLD workspace (no ledger file) mints one via #474's own
   reinit_run (existing ledgers are never touched);
4. product store — runs/distill-products/<name>.json (the store
   trust_event's batch demotion reads);
5. code-form products — stage the inputs #474's land_candidate needs
   (runs/distill-attempts/<kebab>/<kebab>.py copied from
   provenance.script_path + report.json carrying capability/methods/
   provenance) and CALL online_distill.land_candidate — the landing
   itself (tools-local write, manifest, count_landed) stays #474's;
   oracle satisfaction is the T-pass verify verdict, stamped
   oracle_self_declared by #474 as designed;
6. prose-only products — online_distill.count_landed (the shared
   landed counter, never a spine-local write);
7. trust_event(ws, source, landed=True).
Returns `{landed, reason?, product_path?, tool_path?, manifest_path?,
tool_landing?}` — every refusal carries its reason; a missing script
downgrades to store-only with the reason recorded, never silent.

### The complete-toolchain closing (owner challenge 2026-10-02, PR2 addendum)
Owner perception: online distillation 「只提供了文本提示，没有提供完整的工具链」
(only text prompts, no complete toolchain). Verified half-right:
land_candidate DOES write a real executable + provenance manifest, but
NOTHING registers or surfaces it — the next worker's discovery face
(tool-search --find, the #476 SINGLE search entry, whose citation the
instrument menu REQUIRES before hand-rolling a script) reads only
repo-level indexes. File-landing != toolchain. PR2 closes exactly
this — distill -> verify -> land -> REGISTER -> discoverable-by-consumer:
  (a) the run-local registry IS the manifest shelf: tool-search --find
      gains a FOURTH source — <ws>/tools-local/*.manifest.json (both
      distill-manifest/1 and harvest-manifest/1), scanned at query
      time (no third store, no registration write). Workspace
      resolution: explicit --ws, else the cwd walk-up presence probe
      (task_spec.yaml / runs / tools-local markers — the kunglao_log
      idiom). Hits project kind=run-local, type=tool, consume=invoke,
      carry the manifest capability tag, and score under the SAME
      lexical (never-semantic, never-gating) contract.
  (b) usage metadata rides the manifest: land_candidate stamps a
      usage block {invoke: "python tools-local/<name>.py
      <sample-path>", verified: oracle verdict (self-declared)} —
      additive to distill-manifest/1; spine landings inherit it by
      routing through the same call.
  (c) consumer proof: the NEXT worker face is tool-search --find (the
      ritual instrument_menu enforces via citation_defects) — a landed
      tool must surface there with its usage line, and the
      `tool-search: <kw> -> <hit>` citation row must parse
      (instrument_menu.tool_search_citations). No workspace resolvable
      -> no run-local hits fabricated (absence stays silent).

### Review-round fixes (independent reviewer FAIL -> fixed, 2026-10-02)
The merge-gate reviewer's HIGH finding, verified by its executed probe:
on a merge, tpass stamped the merged-into prior with the INCOMING
payload's signal assembly (wrong-source trust, false corroboration) —
the corroboration-compresses scenario could not fire through the
documented signals_for -> tpass flow. Adjudicated fix: the merged
product keeps ITS OWN last snapshot's source signals (its own source's
trust/verification/telemetry — trust attribution is per-source); only
corroboration refreshes, always from the post-dedup product (truth
over caller assembly). A composition test now pins the documented
flow end to end (seeded audit retrieval -> rich first landing ->
merge -> skeleton, snapshot corroboration 2, source_trust the prior's).
Also landed from the same review: script-path containment (traversal
out of workspace/repo never reaches the shelf, existent or not —
defense in depth for #458's external inlet); an existing-but-unreadable
trust ledger now refuses landing fail-closed (PR1's load_trust
fail-open semantics stay read-face only); store writes are idempotent
per content hash (re-landing never double-counts the ledger or trust)
and a different product under a taken name refuses loudly
(store-name-collision) instead of silently overwriting; nameless
products get a content-hash store filename; code-form-with-empty-
script gets its own label. The telemetry heuristic's lexical
approximation (a generic tool_ref like "replay" matches unrelated
calls) is accepted as designed — it only ever loosens retention, never
gates landing, and the design's "absence degrades to conservative"
rule bounds it.
