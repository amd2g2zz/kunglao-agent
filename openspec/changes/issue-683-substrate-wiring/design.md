# design — issue-683-substrate-wiring

## Decision 1: the row table is the registry (one list, two consumers)

Two independent lists of hook FILES was the defect: the self-check keyed
on one, the deployed writer keyed on the other, and nothing ever
compared them. The fix is structural, not a comparison test:

```
wire_up_settings.WIRE_UP_HOOK_WIRING   # (event, matcher, file) rows — THE list
        ├── WIRE_UP_HOOK_FILES = frozenset(f for _, _, f in rows)   # the file set
        ├── hook_activation._DEPLOYED_WIRING = rows                 # deployed writer
        └── ORCHESTRATOR_MCP_MATCHER lives beside the row that uses it
            (hook_activation re-exports it: #601 consumers pin the old name)
```

Direction rationale: the REGISTRY (data) must not depend on the WRITER,
so the rows live in `wire_up_settings` (leaf imports: `kunglao_log`,
stdlib) and the writer imports the registry — never the reverse (that
would make `env_check`/`hooks_selfcheck`/`external_kicker` pull the
whole activation module and risk an import cycle).

`WIRE_UP_HOOK_FILES` stays a `frozenset` with its historical name: four
importers (`env_check.HOOK_FILES` identity, the two `derive_hook_subset`
validators, the count anchors) consume it unchanged.

## Decision 2: the canonical writer keeps its imperative shape

`register_hooks` stays an explicit `_ensure` sequence (ordering
comments are load-bearing — `env_check_gate` FIRST; per-gate rationale
lives inline). It does NOT iterate the row table, because:

- matcher-less events (`Stop`, `SessionStart`, ...) go through
  `_ensure_stop` (basename-dedupe semantics), not `_ensure`;
- a loop would erase the curated comments the codebase treats as the
  gate-by-gate documentation.

Instead the two substrate registrations read their matchers FROM the
table (`_post_rows(hook_file)`), so a matcher literal has one home, and
`tests/test_substrate_wiring_683.py::test_register_hooks_adds_every_
deployed_wiring_entry` pins reachability: any future row the canonical
writer cannot reach fails the contract test (the pre-#683 drift shape).

## Decision 3: REJECT telemetry at the chokepoint, not per gate

All `pre_check` battery failures (`workers`, `max_retries`, `cap`,
`tier`, `heartbeat`, `drift`, `snapshot`, `devreason`, `methodfamily`,
...) funnel through `_reject(name, msg, paths)`. One append there covers
every gate — adding rows inside individual gates would be 25 call sites
and would drift the first time a new gate joins.

- Row writer: `gate_telemetry.append_row(ws, gate, rc, msg=...)` — the
  decorator path (`_record`) delegates to it, so the shape
  (`{ts, gate, rc, rc_meaning}` + truncated `msg`) has one home.
- `gate` is `worker_budget.<name>` (producer-qualified: the shared file
  also holds `backtrack_gate`, `claim_expiry`, ... rows).
- `rc` is 2 — the exit code `_reject` actually returns; `rc_meaning`
  derives from the shared vocabulary (`hard_block`). `guardian_kpi.
  reject_rate` counts it in `overall_reject_rate = (rejects +
  hard_blocks) / rows` and groups it under the producer-qualified gate.
- Fail-open: no `runs/` → no row (test environments stay
  uninstrumented); no workspace key → no row; any exception → ONE
  rate-limited `warn("reject_telemetry", ...)` and the REJECT still
  fires with unchanged rc/exit semantics (#270/#55 unchanged).

## Why not `runs/gate-rejections.jsonl`

`dispatch_gate`'s #603 durability uses a separate ledger because its
consumer (`kunglao_resume`) renders a REJECT summary keyed to top-1
claims. The worker_budget face asked for the EXISTING gate-telemetry
face (post-#670 audits read it via `guardian_kpi.reject_rate`), so this
card writes there — one file per workspace for gate rates, no second
ledger to reconcile.

## Failure modes considered

| Failure | Behavior |
|---|---|
| registry grows, writer not updated | `selfcheck_registration` FAILS (coverage leg keys off the derived set) → `HookWiringSelfcheckError` — never a silent OK |
| row table edited, matcher re-typed in writer | contract test matcher-level assert fails |
| subset tables not updated on growth | `derive_hook_subset` raises at import (#381, both consumers) |
| telemetry ledger unwritable / no runs/ | warn-once or silent skip; verdict byte-identical |
| partial deploy (no `gate_telemetry` module) | ImportError caught → warn-once; REJECT unchanged |
