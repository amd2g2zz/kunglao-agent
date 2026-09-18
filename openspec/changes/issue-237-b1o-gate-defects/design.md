# design — issue-237-b1o-gate-defects

## Anchor verification (issue vs code, 2026-09-18 @ 6e8cec2)

| Issue anchor | Reality | Drift |
|---|---|---|
| D1 `scripts/plan_drift_detector.py:417` | CONFIRMED at line 417: `answered = any(c.get("answers_question") == qid and status in TERMINAL_STATUSES ...)` | none — exact terminal match, no chain walk |
| D3 `:155` | CONFIRMED: `extract_verified_claim_ids` at line 154 | since #827 it is no longer bare existence — `credible_redteam_files` adds verdict-marker + burst-cluster content screening (line ~211 anchor is now inside that screen). Still no dispatch linkage and no maker!=checker — the defect stands |
| D2 B1o on PreToolUse:Agent | CONFIRMED as `_plan_drift_auto` in `hooks/dispatch_gate.py` (subprocess `plan_drift_detector.py --auto`, rc 2 -> BLOCKED), called from `main()` for every parsed-claim dispatch with no agent-based exemption | the blocker lives in the hook wire-up, not the detector CLI (whose operator exit codes stay 0/1/2) |

## D1: in-progress credit

`question_progress(qid, claims, deps_path)` returns one of:

- `terminal` — existing rule unchanged (any answering claim in
  `status_defs.TERMINAL`, which already includes REFUTED/NEGATIVE dead-ends).
- `in-progress` — an answering claim exists at a non-terminal status, OR an
  OPEN claim's transitive `claim_deps` ancestors contain a qid-answering
  claim (cycle-safe walk, visited-set).
- `none` — nothing answers qid and no open chain reaches an answerer: only
  this state is drift.

Edges are the union of `claim_deps.yaml` `depends_on` (child -> [parents],
the MISSING_DEP_LINK DAG owner) and the register's per-claim `depends_on`
fields, so workspaces that never materialized the deps file still credit.

Note: because the direct branch credits an answering claim at ANY status, a
registered answerer is always credited directly; the chain walk adds the
issue's "walk to sub-question claims" semantics for register shapes where
the answering claim appears only as a deps ancestor. Strictly more live than
the old rule — fail-open toward liveness is the point of the fix (this is
the deadlock card, not a strictness card).

## D2: verifier pass-through (both PreToolUse:Agent drift faces)

Condition: dispatch target agent names a verifier-class marker
(`kunglao-redteam` / `verdict-scorer`, the #57 `blind_gate`
VERIFIER_AGENT_MARKERS set) AND the dispatch claim is PROVEN in the register.
PROVEN is the UNVERIFIED_EVIDENCE precondition (the class fires only for
PROVEN claims), so it is the cheap intersection test with the flagged set
without re-running the detector in-process.

The condition and the agent identity are SINGLE-SOURCED in
`hooks/lib_kunglao.py` (`VERIFIER_REMEDIATION_AGENTS`,
`resolve_dispatch_agent`, `is_verifier_remediation_dispatch`) because TWO
hook faces ride the same dispatch and either can resurrect the deadlock:

- `dispatch_gate` `main()` skips `_plan_drift_auto` for remediation
  dispatches and emits a `drift_verifier_passthrough` trace row (fail-open
  posture, word registered in `event_taxonomy.EMIT_ACTIONS` — the #459
  controlled vocabulary is CI-anchored);
- `worker_budget` `pre_check`'s own `check_plan_drift` gate (the second
  B1o face — it rejects on ANY drift rc, 1 or 2) is skipped for the same
  dispatches. Without this, the honest path passed the first hook and
  died at the second, and the #461 corroboration row could never be
  written through a rejected dispatch.

`resolve_dispatch_agent` is the ONE shared agent resolver (probe order:
`tool_input.subagent_type` -> `tool_input.name` -> v1 `meta.agent`). The
#461 row's `detail` used to build from `name` only, so a
subagent_type-shaped verifier dispatch passed D2 while its row recorded
`agent=?` — no verifier marker, D3 corroboration could never land (review
H1). The row now carries the shared-resolver identity (`row_agent`);
the agenttype gate and worker-id bookkeeping keep their legacy name-only
value — their contracts are unchanged by this card.

A verifier dispatch on a non-PROVEN claim is ordinary traffic and stays
under both drift gates.

Accepted limitation: a PROVEN-claim verifier dispatch also bypasses the
block on unrelated drift classes in the same workspace (e.g. ORPHAN_CLAIM).
Allowing honest-path traffic never repairs those classes but also never
worsens them; re-blocking verifier traffic would resurrect the deadlock.

## D3: provenance binding (detector)

`corroborated_verified_ids(workspace)` = `extract_verified_claim_ids` (the
#827 content screen, untouched — `write_gate.py` and
`tests/test_redteam_antitemplate_827.py` pin it) INTERSECT the set of claim
ids with at least one corroborating unified-log row. A row corroborates
claim C iff:

1. `action` contains `dispatch` (the #461 dispatch-lifecycle face);
2. row `claim` == C in canonical form (`_normalize_cid`);
3. hook-attributed: `actor` starts with `hook:` — a self-attested row
   (actor `worker:*` / `verifier:*`) does not corroborate the record.
   This is deliberately stricter than the #57 `blind_gate` contract,
   which also accepts `verifier:`-prefixed actors;
4. a verifier-class marker is named in actor or detail (`agent=`).

**Honesty about the strength of pin 3 (review H2): it is a process bar,
NOT authenticity.** `kunglao_log.emit()` takes the actor as free text and
`validate_actor` never gates emission at runtime (it anchors a static
repo-literal scan only); `runs/` is a worker-writable surface (inside
write_guard's worker surface set, plain-append 0o644 JSONL). An adversary
that hand-crafts one `hook:worker_budget`-actor row — knowing the schema —
fully corroborates a self-minted record. What the pin buys: the adversary
must move from trivially creating a file to deliberately forging an audit
row (schema knowledge + intent), and lazy/accidental self-minting — the
field-incident shape — is still caught. Row-record AUTHENTICITY binding
(ts/trace-state cross-check; record-mtime >= row-ts ordering) is NOT
attempted here; it extends follow-up issue #263 (item 2).

Fail-closed on every missing piece: no `runs/logs/` day files, no rows, or
no match -> the record does not count -> UNVERIFIED_EVIDENCE fires. This is
coherent: the honest path (D2 pass-through -> real dispatch -> #461 row)
writes the corroboration itself. Cost note: the row scan is claim-prefiltered
per line like `blind_gate`; pathological log growth degrades the `--auto`
subprocess into its existing #102 crash face (fail-open, observed).

Not chosen: orchestrator-held signatures (review-gate key infra) — the
issue offers it as an alternative to log corroboration; key infra is the
heavier lift and the #461 hook corridor already produces the needed rows.

## Re-pinned contracts

- `tests/test_plan_drift_unverified.py` no-drift expectations now require a
  corroborating log row (documented contract change, mirrors the fix-233
  re-pin pattern).
- `tests/test_redteam_antitemplate_827.py` pins `credible_redteam_files` /
  `extract_verified_claim_ids` unit semantics — unchanged, stays green.
- `event_taxonomy.EMIT_ACTIONS` grows by one word
  (`drift_verifier_passthrough`) — sorted, unique, annotated.
