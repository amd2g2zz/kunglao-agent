---
name: ida-scripting-overlays
description: Correction overlays for driving IDA programmatically — the headless analysis-wait discipline (an empty result usually means analysis has not run, not that the data is absent) and the Hex-Rays failure-channel edges (exception vs None depending on the layer you call, with MERR-code triage). Use when the ida-decompile lane returns an empty function list, when decompilation fails and the next move depends on why it failed, or when driving a batch/headless IDA scripting session. Not for debugger-tier (dbg_*) work, UI/kernel-window scripting, Ghidra scripting, bulk whole-binary disassembly, or porting/compatibility work against older IDA versions.
---

# IDA Scripting Correction Overlays (headless analysis-wait discipline + Hex-Rays failure channels)

Consumer: the agent driving the IDA lane (`tools/_index-static.md`, the
ida-decompile row) — today through the lane's bridge-discovery and decompile
calls, and through any scripting-grade execution surface (arbitrary Python
evaluated inside the IDA process) when the environment exposes one. The
behavior change this card causes: the agent waits for autoanalysis before
trusting any query result, and guards both Hex-Rays failure channels instead
of one — so an empty list reads as a diagnosis (analysis not drained) rather
than as absence of data, and a decompile failure names its code before the
next move is chosen.

These are CORRECTION overlays, not a tutorial. Core iteration/xref/byte/decompile
patterns are training-rich and are not repeated here — a generic prior is
sufficient for them. What follows is the narrow set where the generic prior
systematically fails.

## When to Use

- An IDA-lane query returns an empty function list or empty segments and the
  sample is known to contain code.
- Hex-Rays decompilation fails and the next move depends on WHY it failed.
- A batch/headless scripting session is being driven end-to-end (wait,
  query, decompile, exit) and each stage's failure mode matters.

when_not: Not when the dynamic lane (x64dbg/frida) owns the question; not for
`ida_kernwin` UI/dialog scripting (no consumer in a headless/bridge loop); not
for Ghidra-side scripting; not for IDA's debugger surface; not a compatibility
layer for running old IDA versions.

## Overlay 1 — headless discipline: an empty result usually means analysis has not run

Default: open a database (or attach a scripting session) and query immediately.
That fails silently in batch/headless contexts: autoanalysis is queued, not
done, so `idautils.Functions()` yields nothing, segment lists come back empty,
and decompilation reports "not a function" — the data is not absent, it is
not yet ANALYZED. The empty-list signature in a headless context is a missing
wait, not a wrong path.

| Failure signature | Likely diagnosis | Fix |
|---|---|---|
| `idautils.Functions()` yields nothing on a code-bearing sample | autoanalysis queued, not drained | `ida_auto.auto_wait()` before the first query |
| one function/region stale while the rest is analyzed | region never planned | `ida_auto.plan_and_wait(ea_start, ea_end)` for that range |
| batch script never exits after the work is done | batch session still alive | end the script with `idc.qexit(0)` |
| decompiler unusable in batch although licensed | Hex-Rays plugin not initialized in the script context | `ida_hexrays.init_hexrays_plugin()` first; treat False as a licensing/setup finding |

Expectation: after the wait, the previously-empty query returns data; if it
is still empty the hypothesis is wrong and the load/path itself is the
finding (wrong file, corrupt database) — do not loop more waits.

## Overlay 2 — Hex-Rays edges: the failure channel depends on the layer you call

Default prior: wrap `decompile()` in nothing and index the result directly.
That fails two different ways depending on the layer, and the fix differs:

- Stock `ida_hexrays.decompile(ea)` signals failure by RAISING
  (`DecompilationFailure`, carrying a `hexrays_failure_t`: an `MERR_*` code,
  a message, and `errea` — the address that killed it). Expectation: an
  unguarded call aborts the whole batch loop on the first hard function.
- Wrapper layers (bridge/evaluation surfaces often catch the exception and
  return `None` instead). Expectation: the same failure surfaces as a
  `None`/`AttributeError: 'NoneType'` downstream instead of an exception.

Fix shape: guard BOTH channels — `try/except` for the stock face and a
`is None` check for wrapper faces — and read the `MERR_*` code before
deciding the next move. Two codes change the plan rather than the loop:
`MERR_LICENSE` (no decompiler license — switch lanes, do not retry) and
oversize-function errors (split the range or accept partial coverage and
record the gap).

Local variables and the ctree (hypothesis-level shapes, verify against the
installed API): the decompiled function object exposes its locals as a list
of `lvar_t` (name, width, is-argument flag) — enough for rename/retype
candidate lists without walking the tree. When the question is expression-
level (call targets, constant arguments), subclass the ctree visitor
(`ctree_visitor_t` in fast mode, override `visit_expr`, return 0 to keep
walking) instead of regex-ing the pseudocode text — the tree carries types
the text does not.

## Worked example (synthetic)

Values invented; shapes transferable. The listing composes the overlays in
the order a real query needs them: wait, then enumerate, then decompile with
both failure channels guarded.

```python
# Synthetic: module name and addresses are invented for shape only.
import ida_auto
import ida_hexrays
import idautils
import idc

ida_auto.auto_wait()                      # overlay 1: drain queues FIRST
if not ida_hexrays.init_hexrays_plugin():
    idc.qexit(2)                          # licensing/setup finding, not a retry

for fva in idautils.Functions():
    try:
        cf = ida_hexrays.decompile(fva)   # stock face: raises on failure
    except ida_hexrays.DecompilationFailure:
        continue                          # record + move on; do not abort batch
    if cf is None:                        # wrapper face: failure as None
        continue
    lvars = cf.get_lvars()                # lvar face: name/width/is-arg list
    args = [lv.name for lv in lvars if lv.is_arg_var]
    print(hex(fva), idc.get_func_name(fva), args)
idc.qexit(0)                              # overlay 1: batch scripts must exit
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Query trusted | analysis-wait call precedes the first query in every headless path |
| Failure handled | both decompile channels guarded; MERR code read before the next move |
| Batch exits | qexit/exit reached on success AND on the failure paths |

## Cross-references

- The lane this card serves: [kunglao-toolshelf.md](kunglao-toolshelf.md)
- Byte-level primitives behind the query faces: [tools.md](tools.md)
- Evidence discipline for anything a snippet produces: [verification-safety.md](verification-safety.md)
- Treating decompile-failure patterns as hypothesis families: [falsifier-library.md](falsifier-library.md)
