# fail-closed-verification-gates

## What
Required verification gates must FAIL CLOSED when unavailable, instead of the
current fail-open behavior that permits terminal promotion without verification.
Four promotion/verification paths currently manufacture a passing result when a
mandatory checker is missing:

1. `claim_migrator()` catches `ImportError` from the BLIND, contradiction, and
   inference gates and CONTINUES toward `PROVEN` — scripts/kunglao_record.py.
2. The hook-side direct-edit backstop (`compare_register_change_proven_gate`)
   permits an unreadable register AND an unavailable `blind_gate` —
   hooks/worker_budget.py.
3. The disassembly post-gate writes `{"ok": true, "skipped": ...}` for an
   import error or ANY exception — scripts/kunglao_verify.py.
4. `l2_redteam()` already distinguishes an absent dispatcher as `NOT-RUN` —
   the correct truthfulness model the mandatory local gates must follow.

## Why
Maker-checker (production/verification separation) is the core integrity rule
of this skill: `PROVEN`/`VERIFIED` must mean the claim was independently
verified. A checker that silently disappears must not turn into a green light.
An unverifiable promotion is worse than no promotion — it poisons the
convergence ledger, the report evidence map, and downstream detection rules
with an unverified terminal state. `l2_redteam` returning `NOT-RUN` shows the
system already has the correct policy for the dispatcher layer; the local gate
layer must match it.

## Scope
- scripts/kunglao_record.py `claim_migrator`: PROVEN-path gates classified as
  required; unavailable/raising gate → migration refused, original claim state
  preserved, explicit non-success receipt returned.
- hooks/worker_budget.py `compare_register_change_proven_gate`: unreadable
  register (with a before-snapshot) and unavailable `blind_gate` →
  Write/Edit blocked; contradiction/inference gate imports become required too.
- scripts/kunglao_verify.py `verify` disasm post-gate: unavailable/raising
  checker → `disasm.ok=false` + audit receipt; a would-be `VERIFIED` overall
  downgraded to `UNVERIFIED-WITH-GAP`.
- schemas/verify-output.json: `overall` enum gains `UNVERIFIED-WITH-GAP`.
- tests: RED mutation tests for all three paths; regression tests for the
  available-checker paths (nothing breaks when everything is present).
- NOT touched: scripts/convergence_check.py (#77), scripts/external_kicker.py
  (#79), release files (#80), scripts/kunglao_eval.py (#81),
  memory/scripts/distill.py (#82).

## Acceptance
- Mutation tests (missing module, ImportError, checker exception, corrupt
  register, missing sign-off, malformed binary) show NO `PROVEN`/`VERIFIED`
  terminal state is written when a required gate is unavailable.
- A supplied binary with an unavailable disassembly checker yields a
  non-passing verification result, NEVER `disasm.ok=true`.
- Direct register edits cannot bypass the required BLIND gate when the
  hook/checker is unavailable.
- Optional observability checks may remain non-blocking, but their receipts use
  `UNKNOWN`/`SKIPPED` rather than a success value, and they cannot affect
  promotion.
- Normal available-checker paths remain covered by regression tests (nothing
  breaks when everything is available).
- `openspec validate fail-closed-verification-gates` PASS.
