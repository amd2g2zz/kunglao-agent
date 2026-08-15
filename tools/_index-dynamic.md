# dynamic domain index (tool layer)

> Domain: VM dynamic debugging / runtime analysis. When a worker is dispatched to dynamic-debugging (x64dbg/Frida) tasks, read this file first, then load on demand. Dynamic tools are VM-only (192.168.20.128), always. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml).
>
> This domain's tools are provided over **MCP + VM channels** and are NOT registered in `_INDEX.yaml` (they are not local .py scripts): x64dbg via `mcp__x64dbg__*`, Frida via `mcp__frida__*` (VM `192.168.20.128:1337`). Frida hook templates live in `templates/frida/`.

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `x64dbg-remote` | VM-side x64dbg remote debugging (registers/memory/breakpoints/single-step) | Read when single-step/breakpoint dynamic validation is needed; not for problems solvable statically (VM cost is high) |
| `frida-remote` | VM-side Frida instrumentation (hook/API call capture/anti-hook detection) | Read when runtime hook/instrumentation validation is needed; the host channel is forbidden (hard ban) |

## Contract entries

### x64dbg-remote

- **Purpose**: Remotely connect to x64dbg on the VM over MCP for runtime register/memory/call-stack validation.
- **Usage**:
  ```bash
  mcp__x64dbg__connect_remote(host=192.168.20.128)   # connect_remote only; start_session/connect_to_session/connect_to_instance/terminate_session are forbidden on the host
  ```
- **Inputs**: A process already attached on the VM side (after connecting, read registers/memory/breakpoints via MCP tool arguments).
- **Outputs**: Runtime register/memory/call-stack readings (tool return values).
- **exit code**: N/A (MCP call; failure surfaces as a call error/timeout, no shell exit code).
- **when_not**: Not for problems solvable statically; the host channel is forbidden across the board (CLAUDE.md hard constraint).

### frida-remote

- **Purpose**: Spawn/attach the target process on the VM over MCP and inject a Frida hook script.
- **Usage**:
  ```bash
  mcp__frida__spawn   # or mcp__frida__attach (VM-only: 192.168.20.128:1337)
  ```
- **Inputs**: VM target process/binary + hook script (generated from `templates/frida/` templates).
- **Outputs**: Runtime data from hook hits (call counts/arguments/return values).
- **exit code**: N/A (MCP call; failure surfaces as a call error/timeout, no shell exit code).
- **when_not**: Not for problems solvable by static analysis; the host channel is forbidden across the board (hard ban #5).
