# Security & enforcement controls — audit mapping

| Control | Mechanism (file) | Standard concern it covers |
|---|---|---|
| Pre-dispatch structural validation | `hooks/dispatch_gate.py` (protocol parse, top-1 REJECT ledger, capability-card check, tools-rack subset vs agent allowedTools) | least-privilege tool assignment; immutable audit trail |
| MCP namespace allow-list | `hooks/lib_kunglao.py::check_mcp_prefix` (rejects mcp__unknown__/mcp__external__) | tool namespace sandboxing |
| Host/dynamic channel ban | project rules + `HOST_FORBIDDEN_TOOLS` (x64dbg/frida spawn banned host-side) | malware execution isolation (VM-only dynamic) |
| Write boundary | `hooks/write_guard.py` + seven user-data dirs iron rule (claims/facts/runs/hypotheses/notes/evidence/oracle read-only to framework) | data integrity / blast-radius containment |
| Stale-workspace refusal | `scripts/kunglao.py` RC_STALE_WORKSPACE=5 gate (`check-stale`) | version-drift safe-execution |
| Redo blind slice | `dispatch_context --redo-view` + gate leak WARN (`_redo_leak_scan`) | checker-answer contamination prevention |
| Session path hygiene | `hooks/_path_hygiene.py` + conftest resolution-stability guard | import-order tamper resistance |
