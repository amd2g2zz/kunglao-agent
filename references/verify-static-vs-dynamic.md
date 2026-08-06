
**Heuristic**: does your evidence come from a static artifact (file bytes) or a dynamic trace (frida / x64dbg / emulation)? Pick the matching verification: static = run reproduce + byte-exact; dynamic = re-run + normalized trace diff.
# VERIFY: Static vs Dynamic (DESIGN §12, §10)

## Static claims (evidence from decompile / strings / bytes)

Orchestrator runs the fact's `reproduce:` command (read-only grep/python/xxd), byte-exact compares to `expected:`.

## Dynamic claims (evidence from emulation / trace)

Orchestrator RE-RUNS the same dynamic tool with the SAME inputs, takes NORMALIZED trace, diffs.

- Use `scripts/normalize_trace.py normalize(trace, tool)` → `[(api_name, args_hash[:8]), ...]`
- Pointers (`0x[hex]+`) stripped from args before hashing; non-pointer args (paths) kept
- `tool ∈ {qiling, frida}` — qiling eats `report.to_dict()` JSON; frida eats call-log text

## Non-deterministic tools (real network / real VM)

Claim caps at `confidence=single-source-dynamic`, MUST defer pending static corroboration.

## Line: reproduce ≠ collect

Re-running a worker-specified tool + inputs is VERIFICATION (orchestrator's job). Selecting new tools / inputs for primary analysis is the WORKER's job (orchestrator purity, DESIGN §4).

## Orchestrator-authored composite notes

Orchestrator may write composite notes (synthesis) but they MUST pass `verify-note.py` (independent verifier subagent). No self-stamping.
