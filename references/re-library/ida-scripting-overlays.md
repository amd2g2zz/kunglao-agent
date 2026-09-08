---
name: ida-scripting-overlays
description: Correction overlays for driving IDA programmatically — the failure signatures that repeat when an agent scripts or queries IDA, and the modern-module fixes for each. Use when the ida-decompile lane returns an empty function list, when an IDA query or snippet fails with a legacy-module AttributeError, when Hex-Rays decompilation fails and the failure channel is unclear, when writing or reviewing any ida_* scripting snippet, or when an old script must be ported to the current IDA API (9.x breaks audited). Not for debugger-tier (dbg_*) work, UI/kernel-window scripting, Ghidra scripting, or bulk whole-binary disassembly.
---

# IDA Scripting Correction Overlays (legacy-call recovery + headless discipline + API breaks)

Consumer: the agent driving the IDA lane (`tools/_index-static.md`, the
ida-decompile row) — today through the lane's bridge-discovery and decompile
calls, and through any scripting-grade execution surface (arbitrary Python
evaluated inside the IDA process) when the environment exposes one. The
behavior change this card causes: the agent stops emitting legacy module
calls that fail on contact, waits for autoanalysis before querying, guards
both Hex-Rays failure channels instead of one, and reaches for the post-9.x
module surface first instead of porting at failure time.

These are CORRECTION overlays, not a tutorial. Core iteration/xref/byte/decompile
patterns are training-rich and are not repeated here — a generic prior is
sufficient for them. What follows is the narrow set where the generic prior
systematically fails.

## When to Use

- An IDA-lane query returns an empty function list or empty segments and the
  sample is known to contain code.
- A scripting snippet fails with an `AttributeError` on `idc` (or an old
  CamelCase call) — the module surface moved under the snippet.
- Hex-Rays decompilation fails and the next move depends on WHY it failed.
- Writing or reviewing any `ida_*` snippet before it runs once.
- Porting a script written against an older IDA API to the current one.

when_not: Not when the dynamic lane (x64dbg/frida) owns the question; not for
`ida_kernwin` UI/dialog scripting (no consumer in a headless/bridge loop); not
for Ghidra-side scripting; not for IDA's debugger surface.

## Overlay 1 — legacy `idc` calls: the failure signature is the old name itself

Default prior: models emit `idc.MakeFunction`, `idc.SegStart`, `idc.GetString`
fluently — the pre-7.x CamelCase surface, removed when `idc` was split into
the modern `ida_*` modules. The signature is reliable: a CamelCase `idc.*` or
`idaapi.*` call usually means the whole snippet was written against the legacy
surface, so fix the family, not the one call the traceback flagged.

| Failure signature (legacy call emitted) | Modern replacement |
|---|---|
| `idc.SegStart` / `idc.SegName` / `idc.NextSeg` | `idc.get_segm_start` / `idc.get_segm_name` / `idc.get_next_seg` |
| `idc.MakeCode` / `idc.MakeFunction` | `idc.create_insn` / `idc.add_func` |
| `idc.MakeStr` / `idc.GetString` | `idc.create_strlit` / `idc.get_strlit_contents` |
| `idc.GetFunctionName` / `idc.LocByName` | `idc.get_func_name` / `idc.get_name_ea_simple` |
| `idc.GetInputFile` / `idc.GetFlags` | `ida_nalt.get_input_file_path` / `idc.get_full_flags` |
| `idaapi.GetFunctionName` and other `idaapi` CamelCase | the matching `ida_*` module function, not `idaapi` |
| batch iteration over functions via `idc` loops | `idautils.Functions()` (yields every function ea) |

Expectation (hypothesis, not a guarantee): replacing the flagged call AND its
CamelCase neighbors clears the error class in one pass; a snippet that
 mixes legacy and modern calls usually has more legacy calls than the
 traceback shows.

## Overlay 2 — headless discipline: an empty result usually means analysis has not run

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

## Overlay 3 — Hex-Rays edges: the failure channel depends on the layer you call

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

## Overlay 4 — rule-10 version-compat audit (IDA 9.x breaks, verified 2026-09)

| Old (pre-9.0) | Break | Modern replacement |
|---|---|---|
| `ida_idaapi.get_inf_structure()` then attribute access (`.procname`, `.max_ea`, `.is_32bit()`) | function removed in 9.0 | `ida_ida.inf_get_procname()` / `inf_get_max_ea()` / `inf_is_32bit_exactly()` (+ `inf_set_*` mirror) |
| `ida_struct` module (struct member access) | module REMOVED in 9.0 | `ida_typeinf`: `tinfo_t` + `udt_type_data_t` + `udm_t`; `idc.get_member_name`-class wrappers for the simple face |
| `ida_enum` module | module REMOVED in 9.0 | `ida_typeinf` `enum_type_data_t` + `edm_t`; `idc.add_enum` / `idc.get_enum_member` wrappers |
| `idc.find_text` / `idc.find_binary` | removed in 9.0 | `ida_bytes.find_string` / `find_bytes` / `bin_search` |
| `soff` byte offsets on struct members (`udm_t`) | offsets now in BITS | byte offset = `udm.offset // 8`; size = `udm.size // 8` |
| `ida_typeinf.get_ordinal_qty` | renamed | `get_ordinal_count` / `get_ordinal_limit` |
| pre-7.x `idc` CamelCase (`Get*`/`Set*`/`Make*`) | removed in 7.x (long-standing) | snake_case `idc.*` / the matching `ida_*` module (overlay 1) |

Audit note: this table records the break directions, not every removed
symbol; treat each row as a porting START point and re-verify against the
installed SDK reference when the exact signature matters.

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

ida_auto.auto_wait()                      # overlay 2: drain queues FIRST
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
idc.qexit(0)                              # overlay 2: batch scripts must exit
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Query trusted | analysis-wait call precedes the first query in every headless path |
| Legacy call replaced | the whole CamelCase family rewritten, not just the traceback frame |
| Failure handled | both decompile channels guarded; MERR code read before the next move |
| Port landed | each rewritten call traced to a compat-audit row or SDK reference |
| Batch exits | qexit/exit reached on success AND on the failure paths |

## Cross-references

- The lane this card serves: [kunglao-toolshelf.md](kunglao-toolshelf.md)
- Byte-level primitives behind several replacements: [tools.md](tools.md)
- Evidence discipline for anything a snippet produces: [verification-safety.md](verification-safety.md)
- Treating decompile-failure patterns as hypothesis families: [falsifier-library.md](falsifier-library.md)
