# design — issue-654-batch-repair

## Context

#654's six remaining findings come from the #601 three-lens audit.
Wave 1 (#662) took the cheap subset; this wave takes the rest with each
fix direction as named in the lens comments. All five touched modules
are telemetry/learning-layer faces — the house fail-open posture (a
finding refuses the row, never the producer) holds everywhere.

## Decisions

### D1 — 1-F3 wall shape: refuse-and-preserve, not delete

The live incident is an orchestrator PARKED envelope parked in the
`incremental_reward`-owned namespace (`status: PARKED_NOT_LAUNCHED`,
carrying a wake plan). The harm is the CONSUME (append_transition
unlinks the stash — the wake plan dies). So the wall refuses and
preserves: a stash doc carrying a foreign `schema` or any `status`
field is not launch state; the settle returns None with ONE warn and
the file stays. Legacy stashes carry neither field → byte-identical
back-compat (the #550 rule). `record_launch` stamps
`schema: "dispatch-launch/1"` so future docs self-identify.

### D2 — 1-F9 invalidation is a marker on the row, not a delete

The Phase-1 posture ("attribution is history — scratch cleanup under
runs/ must not erase it") is load-bearing. Retraction writes
`retracted: true` INTO the row file (history preserved in place);
`read()`/`face()` exclude retracted rows so the state signature and the
termination floor see current truth. The pairing key is the additive
optional `env_key` field (record-time input, never guessed at read
time) matched against the #475 env-state single source
(`runs/env-state.json`, `per_capability.<key>.status == "pass"`).
Unkeyed rows are skipped by the sweep — never guessed. The sweep is a
library face (like wave-1's orphan sweep), wired by the caller at the
closure seam; it never breaks the caller.

### D3 — 4-L6 re-certification: check only what still exists

`read()` re-runs `_marker_ok` when the cited artifact still exists:
present-but-shapeless means the artifact was rewritten after the row
landed → uncertified → excluded (ONE warn). Artifact GONE → the row
stays (D2 posture). This re-check is exactly the audit's "read() never
re-checks" hole; it cannot distinguish a well-forged shape (the named
red-team residual) and does not pretend to.

### D4 — 4-L5 anchor: the engine's own parser defines the scaffold

The mandated checker output is the `verdict:` frontmatter line — the
engine itself parses it three times (checkpoints.py:1308, 1518, 1553).
`MANDATED_CHECKER_MARKERS = ("verdict",)` in prediction_ledger; a
discriminator is scaffold-aimed when its token set intersects the
mandated marker tokens (so `verdict:`, `verdict: verified`,
`the verdict line` all refuse). The constant is the extension point for
future scaffold lines (the audit's `replay-` example joins only if the
scaffold actually mandates it — not fabricated).

### D5 — 5-F4 authorship: required at register, checked at settle

`register(ws, claim_id, statement, discriminator, actor)` — actor is
required (boundary-validation precedent: empty statement raises). The
row stamps `registered_by`. `settle`/`settle_matching` refuse pending
rows without `registered_by` (ONE warn): the 5-F4 trigger — a raw
JSONL append via Bash — mints rows the settle face will never honor,
so the forged-pending-then-settle exploit banks nothing. register()
currently has NO production caller (dormant face; wiring is #567's) —
the signature change breaks no production path, only tests.

### D6 — 4-L8: skip the no-draw rows, cross-check the two carriers

The behavior-policy indicator already exists on the receipt
(`declared: True` from `_stamp_ope_propensity`) and rides the audit
stream (the emit happens after the propensity stamp). policy_compare
skips declared rows (π=1.0 by fiat carries no draw receipt; mixing
them violates the SNIPS assumption the module docstring states) and
counts them. For sampled rows, the propensity reaches disk through TWO
independent carriers — the audit envelope and the transition row (via
the launch stash) — stamped from the same receipt at the same dispatch;
the comparator cross-checks them and refuses mismatches (a corrupted
carrier can no longer move the verdict silently). ESS and the
skip-count breakdown land in the report for honesty.

## Risks

- obstacles read() shape re-check could drop rows whose artifacts are
  post-processed (marker stripped) — that IS the finding; tests pin the
  gone-artifact case stays.
- prediction register signature change — tests updated; no production
  caller (D5).
- policy_compare skip semantics change report counts — the report
  schema stays `policy-compare/1` (additive counters), verdict logic
  unchanged.
