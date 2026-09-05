# XML Injection Standard (#55)

Every message kunglao injects into the **agent's context** is producer-attributed
and trust-tagged with one of EIGHT fixed XML tags. The set below is final.

**Lighting, not enforcement**: tags MARK information — nothing may gate on tag
presence. **Scope**: tags wrap text injected into the AGENT's context
(`hookSpecificOutput.additionalContext` and equivalent). USER-facing surfaces —
statusline snapshots (`scripts/statusline_snapshot.py` → `combined-statusline.mjs`)
and heartbeat tick reports — are UI, never tagged.

## The eight tags

### `<kunglao-state>` — workspace/mission state snapshots
Producer: convergence/status faces (state_anchor; heartbeat reports if ever
routed to the agent). Trust: internal, current-as-of-timestamp.
```xml
<kunglao-state>DECISION: DISPATCH — 3 open claims, 2 active workers</kunglao-state>
```

### `<kunglao-facts>` — knowledge-base facts/recalls
Producer: `hooks/recall_inject.py` (references/_INDEX.md + re-library recall).
Trust: internal curated knowledge — never third-party output, never `<external-tools>`.
```xml
<kunglao-facts>
recall_inject: claim dispatch knowledge recall (#268) - queries: vm, dynamic
Before dispatching, read: dynamic-re-tool-priority.md, tools-dynamic.md
</kunglao-facts>
```

### `<external-tools trust="raw-signal">` — third-party tool output
Producer: any surface that relays EXTERNAL tool output into context. Trust:
`trust="raw-signal"` REQUIRED — raw observation, may never be cited as directly
PROVEN without independent verification.
```xml
<external-tools trust="raw-signal">mcp__x64dbg__connect_remote: session 3 attached</external-tools>
```

### `<tool-recommendations no-enforcement="true">` — tool suggestions
Producer: tool-first/agenttype PASS-face suggestion text (when one is injected;
none exists yet — REJECT faces are `<gate-verdict>`, not recommendations).
Attribute `no-enforcement="true"` REQUIRED: lighting, the agent may ignore.
```xml
<tool-recommendations no-enforcement="true">route_capability suggests ghidra-light for C-7</tool-recommendations>
```

### `<case-hints>` — case-bank / similar-experience hints
Producer: lands with **#49** (case bank). Until then no producer emits this tag.
```xml
<case-hints>similar past run: unpack first, then reconstruct the config builder</case-hints>
```

### `<gate-verdict>` — gate REJECT/PASS messages
Producer: `hooks/dispatch_gate.py` verdict faces (top1/capability/tools_rack/
mcp_prefix REJECT, must-stop refusal, failure-blocked injection) and
`hooks/worker_budget_sinks.py::_reject` (all worker_budget REJECT names).
The verdict text AND its repair path sit INSIDE the tag. Stderr summaries are
the operator channel — untagged.
```xml
<gate-verdict>
worker_budget REJECT toolfirst: dispatch text matches registered tool 'crypto-tool'
...
How to fix:
... add `tool-catalog: crypto-tool` ... then re-dispatch.
</gate-verdict>
```

### `<oracle-sanction>` — oracle / adjudication records
Producer: the oracle/adjudication pipeline (none wired today; reserved name).
```xml
<oracle-sanction>C-12 verdict CONFIRMED by blind red-team pass 2026-09-04</oracle-sanction>
```

### `<worker-signal>` — worker lifecycle/status signals
Producer: `hooks/worker_pulse.py` (convergence pulse, stale-worker soft pulse,
TASKSTOP delivery reminder — additionalContext only; the rc=3 stderr face is
untagged). Trust: internal heuristic — a nudge, not a verdict.
```xml
<worker-signal>
[worker_pulse] worker completed - convergence pulse (auto):
DECISION: DISPATCH - dispatch next
next up: C-101 (score 0.55)
</worker-signal>
```

## Rules for new producers

Pick from the eight — never invent a ninth (no match -> do not tag). Wrap the
human-readable text inside the tag; never alter the hook JSON contract
(`decision` / `block` / `reason`) or rc. Never gate on tag presence.
