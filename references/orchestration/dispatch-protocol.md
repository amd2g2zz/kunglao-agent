# Dispatch Protocol — issue #452 (structured dispatch protocol)

## Why

`hooks/dispatch_gate.py` currently parses the prompt with the regex `[T<N> tools=...] claim <C-NN>`:
- on parse failure it `return 0` (silent) — **recognition failure emits no observable signal**
- no version field; a minor regex change breaks it (MITRE L2-9)
- when the orchestrator's prompt format changes, the gate fails silently

Design goals:
- **Observable**: recognition failure must emit an observable signal (stderr / hookSpecificOutput)
- **Evolvable**: versioned; new versions add fields without breaking old callers
- **Machine-parseable**: JSON > regex; the gate tries JSON first

## Protocol v1 (new)

JSON prefix embedded in the Agent tool prompt:
```json
{"kunglao_dispatch": {"version": 1, "claim": "C-409", "tier": 1,
  "tools": ["pe_analyze", "strings-classify"], "agent": "ghidra-light"}}
```
Fields:
- `version`: protocol version (integer)
- `claim`: required, format `C-\d+`
- `tier`: required, 1 / 2 / 3
- `tools`: optional, string list
- `agent`: optional, worker name (e.g. `ghidra-light` / `floss-filter`)
- `task`: optional, free-text task description
- **`reversible`: optional, boolean (#447 mechanical-first, LLM backstops recall)** — the agent explicitly
  declares whether this dispatch is irreversible. `"reversible": false` is a **language-independent** must-stop
  signal: `hooks/dispatch_gate.py` HARD_PAUSEs on the structural field directly, no natural-language
  inference. Default = true (ordinary dispatch).

  Who decides reversible's value: the mechanical layer runs first (a command-grammar hit on `vmrun delete` /
  `git push --force` is irreversible regardless of the declaration); on a mechanical recall miss (wording matches
  no pattern), the orchestrator's semantic judgment backstops — recognizing irreversible means declaring
  `reversible: false`, landing the semantic judgment back in a structured field. **Judge semantically, execute
  mechanically.**

- **`trace_id`: optional, #879 trace identity layer** — mission chain id, format
  `tr-<mission>-<seq>` (`scripts/kunglao_log.TRACE_ID_RE` single source). All ledger lines of the same
  mission (dispatch→worker→settlement) join on it; invariant within a mission
  ("a mission keeps its trace_id"), seq increments only on mission restart. If the orchestrator declares a legal
  value, the gate reuses it; missing → dispatch_gate assigns one mission-stably
  (`runs/.trace-state.json`, emits a `trace_allocated` line); illegal declared value → stderr
  WARN + reassignment. Worker return channel: worker-status line `| trace: <id>` +
  fact frontmatter `trace_id:` (same channel as the claim id). Unattributed rate = share of ledger lines missing
  trace_id (`kunglao_log.unattributed_rate`).

## Protocol v0 (compat)

`[T<N> tools=a,b] claim C-NN ...` — the existing regex form, **still supported**.

## Parse order

1. **First**: JSON prefix parse (`version: 1` → v1 path)
2. **Fallback**: v0 regex (`[T<N> tools=...]` → v0 path)
3. **Failure**: emit a warning (breaks the silent return 0), return 0

## The recognition-failure signal

When the gate fails to parse:
- **stderr**: write `dispatch_gate: unrecognized dispatch protocol (v0/v1 both failed)`
- **hookSpecificOutput.additionalContext**: inject "dispatch gate inactive" information so the
  orchestrator sees the gate did not fire (the original silent behavior hid this fact)

> Injected-message format (#55): gate verdicts (REJECT/HARD_PAUSE/correction injection) are wrapped in
> `<gate-verdict>`, knowledge recall in `<kunglao-facts>` —
> the eight-tag standard: [xml-injection-standard.md](../contracts/xml-injection-standard.md).

## Compatibility

- v0 prompts keep working
- v1 prompts take precedence
- old callers need no migration; new callers may choose v1

## Dispatch prompt markers (#496 decision teeth, declarative)

Three in-prompt markers are consumed by `hooks/dispatch_gate.py`, all through the declarative channel of
"judge semantically, execute mechanically" (prose enumeration is never exhaustive; markers are enumerable):

- **`agent-reasoning: <reason>`** — when the dispatch target is not priority_ratio's (#499 sole authoritative
  scorer, via `worker_budget.check_priority`) top-1, this marker **must** be carried
  (same discipline as the #310 agenttype gate): no marker → REJECT (exit 2); marker present → allow and
  leave a trail (unified log `runs/logs/kunglao-*.jsonl`, action=`priority_deviation`).
- **`capability-disproof: <family> (why it failed)`** — when the target claim (including its
  `obstacle_for` parent chain) has a #495 `validated_capability` proving a tool family
  (frida/ghidra/x64dbg/...) and this dispatch declares a **disjoint** tool family, the marker **must** be carried
  naming the disproven family: trajectory-1 example — frida✓ in hand, switch to xposed, must show frida✗.
  No marker → REJECT; marker present → allow and leave a trail (action=`capability_switch`).
- **`[strategy <id>]`** — optional (mechanism reserved, not forced): when carried, the dispatch allow-path
  appends a line to `runs/strategy-log.jsonl`; historical failures of the same strategy (derived via #495
  `covers_attempt`, no new writers) lower that claim's ratio-novelty score — the same play failing repeatedly ranks
  lower.

## See

- `hooks/dispatch_gate.py` — implementation
- `hooks/lib_kunglao.py` — `parse_dispatch(text)` shared parsing
- `scripts/priority_ratio.py` — capability-card pure criteria + strategy novelty consumption (#496)
- `openspec/changes/issue-452-dispatch-protocol/` — full spec/design
- `openspec/changes/issue-496-decision-teeth/` — decision-teeth spec/design
