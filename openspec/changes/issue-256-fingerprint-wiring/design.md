# issue-256-fingerprint-wiring — design

## Anchors (verified on dev 4c800b5)

| Target | Plan anchor | Measured anchor |
|---|---|---|
| Recorder | `scripts/zero_output_fingerprint.py::record_action` | `scripts/zero_output_fingerprint.py:74`; emits `zero_output_break` via `kunglao_log.emit` at streak >= `ZERO_OUTPUT_N` (3); actor already in `kunglao_log.py` ACTORS (:98), action already in `event_taxonomy.py` EMIT_ACTIONS (:270) |
| Trigger point | `post_check` = "worker action completed" | `hooks/worker_budget_sinks.py:722`; sibling `_emit_tool_calls` (:684) already solves the same discrimination problem on this face |
| Gate | `check_zero_output_circuit` | `hooks/worker_budget_gates.py:1441`; REJECT semantics pinned by `tests/test_canary_gates.py`; zero production callers |
| Production gate list | `pre_check` checks battery | `hooks/worker_budget_sinks.py:492-535` — the ordered tuple list that decides which gates run per dispatch; `worker_budget.py` is a star re-export shim (no second list); hook FILE registry (`wire_up_settings.WIRE_UP_HOOK_FILES`) already carries `worker_budget.py` Pre+Post |
| Test-only contrast | canary tests call the gate directly | `tests/test_canary_gates.py:49/:58` — the only callers |
| Path authority | scripts/ on sys.path in hook subprocess | `hooks/_path_hygiene.py` (`ensure_scripts_path`), invoked at `worker_budget_core` import (:45) — so `import zero_output_fingerprint` inside the helper works in production |

## Decisions

### D1 — record one action per actually-invoked tool, target_type = claim id

`scan_actual_tools(tool_result)` is the only claim-granularity tool source
on this face (`_emit_tool_calls` precedent, #880 v1: per-tool timing not
observable from a completion transcript; same limitation for per-tool
targets). The fingerprint therefore becomes hash(tool | claim) — "same
tool, same claim, repeated with no belief movement" is precisely the
thrash the circuit exists to catch, and a belief move (any fact or
register write) still resets all streaks, so completed work never
accumulates debt.

### D2 — self-contained helper over refactor of _emit_tool_calls

`_record_zero_output_fingerprint(paths, payload, tool_result)` re-derives
worker entry + tools (one state-file read + one regex scan, cheap in a
short-lived hook subprocess) instead of changing `_emit_tool_calls`'s
return contract. Smaller blast radius; the sibling helper stays untouched.

### D3 — visible fail-open (the asymmetry the issue demands)

Recording is observability: any fault degrades to a stderr WARN and
`post_check` still returns 0 (liveness first, `_dispatch_lifecycle`
shape). But a fault must not LOOK like success: the helper validates
`record_action`'s return (dict with a `streak` key). A crashed recorder
AND a silent no-op recorder (returns None) both raise into the same
visible WARN. Enforcement (`zerooutput` gate) is a separate, already
fail-open face — a broken gate must not deadlock the loop (gate-family
stance, `check_zero_output_circuit` docstring).

### D4 — battery position: after `backtrack`

`backtrack` is the coarse stuck-worker breaker; `zerooutput` is its
finer-grained per-action-family twin. Adjacent placement keeps the stall
family together; all earlier gates are fail-open on `_min_paths`, so the
e2e registration test can attribute rc=2 to this gate alone.

### D5 — hygiene constraints honored

- `hooks/` is exempt from `comment_hygiene_lint.py` (R1 tracker-shape
  ban covers scripts/ and tests/ only) — `#256` references allowed in
  hooks comments, forbidden in the new test file's docstrings.
- `scripts/zero_output_fingerprint.py` docstring edit keeps the flagged
  line count at exactly the baseline r1:1 (docstrings count once per
  rule) — no baseline change; ratchet only shrinks.
- `deploy-manifest.yaml` carries sha256 for both touched files →
  `deploy_manifest.py --write` then `--verify` after edits.

## Test map (RED-first, tests/test_fingerprint_wiring_256.py, fast tier)

| Test | Face | RED because |
|---|---|---|
| `test_post_check_records_worker_actions` | two identical no-progress worker completions → streak 2 recorded in the state file (>=1 recorded trigger through the REAL path) | helper absent, state file never written |
| `test_third_identical_action_emits_break_telemetry` | three completions → exactly one `zero_output_break` row (actor/tool/detail) captured via the `kunglao_log.emit` seam | same |
| `test_unclaimed_worker_not_recorded` | no `[active_workers]` entry → no state | discriminator absent |
| `test_zerooutput_gate_registered_in_production_battery` | structural: gate tuple present exactly once in the pre_check battery (#57 precedent) | not in the battery |
| `test_tripped_circuit_rejects_dispatch_e2e` | tripped state + full `pre_check` on minimal paths → rc 2, `REJECT zerooutput` | gate not in battery → rc 0 |
| `test_reject_fixes_carries_zerooutput_guidance` | REJECT_FIXES entry names failure_analysis | KeyError |
| `test_recorder_crash_fails_open_but_visible` | record_action raises → rc 0 AND stderr WARN | no WARN exists |
| `test_noop_recorder_is_detectable` | record_action returns None → rc 0 AND stderr WARN (not silently swallowed) | no WARN exists |

## Review round 2 (adversarial BLOCK, .subagent-review/review-256-wiring.md)

### D6 — the gate derives belief freshness itself (CRITICAL deadlock fix)

The reset in `record_action` is only reachable through a SUCCESSFUL
dispatch, so an enforcement face that trusts the stored ledger
deadlocks: trip → belief move → still REJECT, clearable only by manual
state deletion. `check_zero_output_circuit` now compares the stored
`belief_hash` against the CURRENT `belief_hash(ws)`; on mismatch the
ledger is stale = reset (pass, annotated). The documented repair ("the
streak resets once the workspace belief moves") is now true on the
enforcement face, and the REJECT text names
`runs/zero-output-fingerprint.json` as the manual escape hatch.

### D7 — reject scoped to the tripped (claim, tool-family) (HIGH fix)

The gate takes the dispatched `cid` + `tools` (already parsed in
`pre_check`) and rejects only when `fingerprint(tool_family(t), cid)` is
tripped for a dispatched tool — a thrashing claim can no longer lock
unrelated claims or unrelated tool families out of the workspace, and
the "re-dispatch a DIFFERENT action family" guidance became true.
`tool_family` (new, `scripts/zero_output_fingerprint.py`) collapses
`mcp__<server>__<op>` → `mcp__<server>` so retrying a tripped family
under a sibling operation still counts as repetition — the module's own
"action family" vocabulary, now enforced at the granularity it speaks
in.

### D8 — recorder discipline (MEDIUM fixes)

- `_scan_invoked_tools` (sinks): word-boundary anchored scan (same
  vocabulary as `scan_actual_tools`), so a tool name merely MENTIONED
  in the transcript ("ripgrep", "rev-frida2") is not an invocation.
- Recorder WARN rate-limited once per (ws, reason) until the reason
  changes (`_ZOF_WARN_LAST`); a persistently wedged recorder prints one
  WARN, not one per completion.
- Partial-landing truth: a fault at tool k of n reports
  "k-1/n tools recorded ... from `<tool>` on not counted" — never the
  blanket "recording did not land".
- Belief-carrier limitation noted in the module docstring: progress
  landing outside facts/_INDEX.md + claim-register.yaml reads as
  no-progress by construction (accepted coarse-grained v1).
