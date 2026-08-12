# Downstream contract & modules

> Extracted from SKILL.md for progressive disclosure. Target audience: skill
> maintainers shipping x64dbg/Frida MCP calls, and workers choosing modules.

## Downstream contract for skill maintainers

If you ship a Claude skill that issues x64dbg MCP calls (or Frida MCP / rev-frida calls) — you ship it under this contract; otherwise `hooks/worker_budget.py` will deny every dispatch that uses the skill.

| Tool call | Verdict | Why |
| --- | --- | --- |
| `mcp__x64dbg__connect_remote(host=VM_IP, ...)` | ✅ USE | VM-channel; sample runs in VM |
| `mcp__x64dbg__start_session` | ❌ FORBIDDEN | Launches HOST x64dbg; sample would execute on the host |
| `mcp__x64dbg__connect_to_session` | ❌ FORBIDDEN | Binds to HOST x64dbg |
| `mcp__x64dbg__terminate_session` | ❌ FORBIDDEN | Host-side cleanup; if you never bind host, you never need to terminate |
| `mcp__x64dbg__connect_to_instance` | ❌ FORBIDDEN | Alias host-bind path |
| `mcp__frida__spawn`, `mcp__frida__attach` (against host PID) | ❌ FORBIDDEN | Spawns/attaches on host |
| `rev-frida` against `192.168.20.128:1337` (VM frida-server) | ✅ USE | VM-channel |
| Direct `vmrun` / `qemu-system` / `wine` that runs `bins/` or `extracted/` on host | ❌ FORBIDDEN | Sample-on-host by any other name |

**Skill frontmatter rule**: if your skill's `allowed-tools:` lists any ❌ row, the kunglao-agent hook will reject every dispatch that names your skill. Replace with the ✅ equivalent. For example, replace `mcp__x64dbg__start_session` with `mcp__x64dbg__connect_remote`.

**Skill body rule**: any "Connect and verify state" section must call `mcp__x64dbg__connect_remote(host=VM_IP, ...)` first; never assume the debugger is already bound. The expected setup (launch VM-side x64dbg via `vmr-shell`, confirm port listening, then connect_remote) is in `references/dynamic-re-tool-priority.md`.

**Maintenance rule**: if a downstream skill (`x64dbg-skills/*`, `rev-frida`, etc.) ships with an out-of-date `allowed-tools` frontmatter that includes any ❌ row, **the upstream enforcement is the safety net** — it will refuse the dispatch and ask the worker to fix the tool list. Do NOT remove the upstream hook to "make the downstream work"; instead, fix the downstream's `allowed-tools`.

## Modules available (descriptive — you and workers choose when; see DESIGN §6)

sample-class detection (DIE) · static RE (ghidra-malware/re/light, mcp__ghidra__*, pefile-signature, mal-recon) · dynamic RE **on VM only** (malware-framework Qiling first, rev-frida, mcp__x64dbg__connect_remote, vmr-shell last) — see Hard prohibition #5 + `references/dynamic-re-tool-priority.md` for the host-vs-VM channel split · memory dump (mcp__volatility__*) · verify (malware-veri-notes) · verdict (verdict-scorer agent, optional post-convergence).
