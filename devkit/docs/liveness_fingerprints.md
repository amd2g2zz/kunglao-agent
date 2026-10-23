# Liveness Fingerprints (issue #772)

The development mechanism's missing feedback edge, as data. For every
system face that claims to decide, learn, or gate, this spec names the
LEDGER EVIDENCE that proves the face fired in a real run. The machine
list is `devkit/liveness_fingerprints.json` (schema
`liveness-fingerprints/1`); this document is its human-readable
single source. The product-side round-closure auditor derives its
zero-activity blocker from the same list (derivation, not import —
devkit is never imported by the product).

## Reading a fingerprint

| field | meaning |
|---|---|
| `id` | stable identifier, cited by invariants and PRs |
| `face` | what the face claims to do, with the issue that owns the wiring |
| `ledger` | workspace-relative evidence location; `runs/logs/latest` = the newest `runs/logs/kunglao-*.jsonl` |
| `check` | machine check: `jsonl_count` (row field equality via `all_of`, substring via `contains`, non-empty field via `field_nonempty`, minimum `min`) or `file_glob_min` (glob + `min` + any-of substrings) |

## The rule

A PR that touches a face must keep its fingerprint green (`--ledger`
mode on a live workspace). A release train runs `--smoke` (headless
run on the smoke workspace, then the same fingerprints). A fingerprint
that cannot pass anywhere means the face is decorative — the exact
failure class of the 2026-10-18 rc2 wave (six escaped defects, all
repo-green, all live-dead).

## Key granularity (raised 2026-10-23)

rl-posterior-moved counts only posterior-store rows carrying a NON-EMPTY
arm key (`arm_key` or `arm`): case-level movement — key-less rows,
dispatch-pending structural mass, or credits with no arm attribution —
does NOT satisfy the sentinel. The two 2026-10 production runs broadcast
same-value mass to case cells with arm=NULL while the family dimension
never moved; the sentinel now reads that shape RED. Synthetic fixtures
for this face live in devkit/production_shapes/ and are replayed by
devkit/production_replay_gate.py.

## blind-settlement-wired (#802, 2026-10-24)

Production settlements carry SETTLER-IDENTITY rows from the blind path:
a `settlement-wire/1` row (runs/settlement.jsonl, non-empty `identity`)
proves a ruling was consumed through the blind face
(rlvr.settlement_wire.settle_parked — parked blind-settlement-input/1
doc, sha re-check, scalar.validate_verdict_doc stack, claims_store
mint). The unblinded settle_step judgment is eval-only
(KUNGLAO_EVAL_SETTLE); a settlement event that did NOT settle still
lands its row with `settled: false` — refusals are loud, never silent.
Content-hash dedupe: the same event on an unchanged workspace appends
once.

## Seeds (2026-10-18)

rl-sampler-exit, rl-admission-consumed, rl-posterior-moved,
oracle-armed, settle-credit. The first three are expected RED on the
archived pre-wiring ctf-1 snapshot (that red is the regression pin
for #773's executor wiring); oracle-armed and settle-credit define
the reward-source and settlement faces.
