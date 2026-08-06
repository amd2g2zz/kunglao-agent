
**Heuristic**: are you writing to facts/ AND claim-register.yaml atomically? If yes -> use the WAL (write-ahead log) protocol; if no -> you're not in a multi-writer scenario and can skip this.
# WAL Protocol (DESIGN §14)

## Intent log (analysis_state.txt `[intents]` segment)

Before dispatch, orchestrator appends intent:
```
intent_id=iN | claim_id=C-NN | worker_id=wN | fact_id=F<hash> | status=in_flight
```
Worker writes fact (filename = fact_id, idempotent).
Orchestrator marks intent `status=completed`.

## fact_id = content-sha256

`scripts/content_hash.py fact_id(claim, reproduce, expected)`:
```
'F' + sha256(sha256(claim) || sha256(reproduce) || sha256(expected))[:16]
```
Each field hashed independently (fixed 32 bytes) → unambiguous, no separator.
Re-dispatch same work → same fact_id → same file (idempotent, no collision).

## Atomicity

- Intent log + active_workers: atomic rename (tmp → rename) via `_atomic_write` in `hooks/worker_budget.py`
- Fact writes: filename = fact_id (content-addressed; last-write-wins is safe)

## Cold-restart reconciliation

`scripts/reconcile_intents.py reconcile(state_path, facts_dir)`:
- `in_flight` intent → re-dispatch (idempotent — safe whether worker wrote the fact or not)
- fact file with len-17 id (content-hash) + NO intent at all → orphan → `blockers/orphan-<id>.md`
- pre-existing ordinal facts (F001, len 4) are exempt (predate kunglao-agent)
