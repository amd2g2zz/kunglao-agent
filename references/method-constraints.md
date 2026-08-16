
**Heuristic**: are you about to call a stage-3 tool (x64dbg / frida / emulation) on tier-1 evidence? If yes -> run tier-1 (static, grep, strings, DIE) first. Tier gate enforces this.
# Method Constraints (kunglao-agent §6a reference)

When dispatching a worker, the orchestrator **MUST** include method constraints
in the dispatch description for scenarios where the wrong method is
catastrophically slow or breaks the target. The full table is below; copy the
matching constraint into the worker's `[T<N> tools=...]` prompt.

## Constraint table (by scenario)

| Scenario | Constraint to prescribe |
|---|---|
| Go binary dynamic RE | "Use hardware breakpoints + `go(pass_exceptions=true)` + `wait_for_event`. Do NOT use `trace_into`/`step_into`/`step_over` — Go has billions of instructions; single-stepping is infeasible." |
| Go binary frida | "Use Interceptor counters only. Do NOT use Stalker (crashes Go's M:N scheduler). Do NOT use per-hit `console.log` (floods marshal queue)." |
| Deep-path host ops | "Use relative paths from cwd. Do NOT `cd` to deep paths (times out)." |
| x64dbg `set_breakpoint` | "Pass literal hex address. Do NOT pass expressions (fails silently)." |
| `/api/exec` JSON | "Use forward-slash paths. Do NOT use backslash paths (JSON parser rejects)." |
| Go binary frida `NativeFunction` | "Call in synchronous context. Do NOT call inside `setTimeout` callbacks (TypeError)." |
| VM channel | "Use `mcp__x64dbg__connect_remote(host=VM_IP, 27066, 27067)` ONLY. Never `start_session`/`connect_to_session` (host-bind path)." |
| **RVA / VA / file-offset math (verifier)** | **NEW 2026-07-30**: "RVA → file offset: subtract section delta `RawAddr - VirtualAddr` (`.text` = -0xA00; `.rdata` = -0x400 for this binary). Runtime VA = image_base + RVA (live debugging only, NOT for file mapping). DO NOT add image_base (0x140000000) to RVAs when computing section offsets — this was V-3's bug that reported false FAIL on F049." |
| **Go dispatch mechanism (verifier)** | **NEW 2026-07-30**: "Go binaries use map lookup for dispatch, NOT `LEA + MOV ECX + CALL runtime.strequal` linear scans. The `runtime.eqstring` helper pattern at RVA 0x380c0d is a hash-map key comparator, not the dispatch site. Confirm dispatch mechanism via Ghidra decompile before claiming 'strequal dispatch'." |
| **Worker file paths (orchestrator post-check)** | **NEW 2026-07-30**: "After worker reports success, verify the output file exists at the EXACT absolute path expected (e.g. `<project_root>/facts/F004.md`). W-18 reported success but wrote to a wrong-path directory. The orchestrator MUST `ls` the expected path before accepting the report." |

## Why this is here

§1 says "Do NOT prescribe how a worker works" — but this is **too absolute**.
A Go-binary single-step trace or a `Bash cd <deep-path>` is not "implementation
choice" — it is **catastrophic method failure**. The orchestrator MUST inject
the constraint when the target type is known. kunglao-worker agent already knows
most of these (see its system prompt), so dispatch-side prescription is only
needed for one-off overrides or workers other than `kunglao-worker`.

## Cross-reference

- kunglao-agent SKILL.md §6a (this file is the backing reference)
- kunglao-worker agent system prompt (the worker-side mirror of these constraints)
- references/re-library/anti-analysis.md (anti-analysis bypass ladders when
  constraints conflict with target anti-RE)
- references/guardrails.md §1b (verifier mechanism — the 5 failure types caught by the §1b verifier pass, each mapping to one of the NEW 2026-07-30 rows above)