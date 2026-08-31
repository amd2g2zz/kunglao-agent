# Design — verifier identity binding

## Threat model

The gate cannot trust workspace-local files as proof of independence: the
orchestrator session has write access to all of them. The only signal the
maker cannot cheaply forge is **a subagent dispatch artifact whose creation
the parent session did not perform** — the Agent tool result record.

## Binding options

A. **Dispatch-ledger check** (chosen): `hooks/dispatch_gate.py` already
   observes every Agent dispatch. Extend it to append
   `runs/dispatch-ledger.jsonl` {ts, agent_type, claim_id, task_id}. The
   R1 rule then requires, for `verify_status: passes`, a ledger entry with
   `agent_type == "kunglao-redteam"` and `claim_id` match, ts after the
   fact's `verified_by` maker timestamp.
   - Weakness: orchestrator can hand-write ledger lines. Mitigate: ledger
     append happens inside the hook process (maker cannot write to it via
     normal tools — the file is hook-owned, chmod/mark it).
B. **Process-boundary nonce**: redteam agent receives a nonce from the
   hook and must echo it in its output file; nonce validity checked at R1.
   - Stronger, but requires prompt plumbing through Agent dispatch.
C. **Cross-session only**: require the verifier record's mtime to fall
   outside any session window that wrote the fact. Fragile (sessions
   overlap in this incident family).

Chosen: A for landing speed, B as hardening follow-up.

## Non-goals

- Detecting a *lying* independent verifier (content quality) — that is L2
  semantics, out of scope for identity binding.
- Rate-limiting verifier dispatches.
