
**Heuristic**: are you about to use x64dbg / Frida / vmr-shell? If yes, use the **VM-channel** only (mcp__x64dbg__connect_remote to <VM_IP>:27066/27067, or rev-frida via VM frida-server <VM_IP>:1337; `<VM_IP>` = the live lease from env discovery — `KUNGLAO_VM_HOST` / vmr-shell discovery, never a cached address). **DO NOT** call mcp__x64dbg__start_session (host-channel) or mcp__frida__spawn/attach on host - that loads the sample on the host machine, bypassing the workspace safety boundary (Hard prohibition #5).
# Dynamic-RE Worker Dispatch Checklist (DESIGN §8.6, v1.8.1; DESIGN.md now at docs/design/archive/DESIGN.md)

> **Upstream contract** (see SKILL.md §"VM-channel launch sequence" + §Hard prohibitions #5 + §"Downstream contract for skill maintainers"): any x64dbg / Frida MCP call must be VM-channel, lead with `mcp__x64dbg__connect_remote`. The kunglao-agent `HOST_FORBIDDEN_TOOLS` hook denies every dispatch that lists `start_session` / `connect_to_session` / `terminate_session` / `connect_to_instance` / frida `spawn` / frida `attach`. There is no per-engagement opt-out — the rule is structural.

## Tool priority (call-site stepping class)

1. **`mcp__x64dbg__*`** — set_breakpoint on entry → step_into → read_memory / get_register to capture params
   - **⚠️ TWO MODES — pick the right one (safety-critical, corrected 2026-07-28):**
     - **`connect_remote(host, req_rep_port, pub_sub_port)`** ← **USE THIS.** Connects via ZeroMQ to a **VM** x64dbg that has the `x64dbg-automate` plugin active and listening. The sample executes **inside the VM**; the host MCP server only relays ZMQ control frames. This is the correct VM-debugging mechanism.
     - **`start_session(...)` / `connect_to_session(...)`** ← **FORBIDDEN for in-scope samples.** These launch / bind a **HOST** x64dbg (the machine the MCP server runs on). Even if you pass a "VM path", it is resolved on the HOST, so the sample would execute **on the host**, bypassing `block_malware_exec` (that PreToolUse hook matches Bash only, NOT MCP tool calls).
   - **Do NOT misread `list_sessions` returning clean as "bridge up".** It only does LOCAL lockfile discovery on the host — it never probes the VM and proves nothing about `connect_remote`. This exact misread caused the 2026-07-28 incident (worker fired `start_session`; sample nearly ran on host; stopped, no execution). Verify the bridge via VM `netstat` or by attempting `connect_remote`.
   - **VM is fully pre-configured for `connect_remote`** (verified 2026-07-28, sample `488d2dd8`; VM-internal paths below are provisioning examples — locate the live install via vmr-shell):
     - plugin `x64dbg-automate.dp64` + ZeroMQ `libzmq-mt-4_3_5.dll` @ `<VM_X64DBG_DIR>\release\x64\plugins\`
     - `[XAutomate]` in `...\release\x64\x64dbg.ini`: `BindAddress=0.0.0.0`, `ReqRepPort=69BA` (hex = **27066**), `PubSubPort=69BB` (hex = **27067**) — verify actual listen ports via VM `netstat -an` after launch
     - sample @ `<VM_SAMPLES_DIR>\<sha>.exe`; PE64 → use `x64/x64dbg.exe`, NOT the `x96dbg.exe` launcher
   - **Correct launch sequence** (x64dbg is a GUI app — launch it inside the VM via vmr-shell, then connect from the host):
     1. `vmr-shell exec-cmd 'start "x64dbg" "<VM_X64DBG_DIR>\release\x64\x64dbg.exe" "<VM_SAMPLES_DIR>\<sha>.exe"'`
     2. wait ~10 s for the automate plugin to bind
     3. confirm VM `netstat -an` shows `0.0.0.0:27066` + `0.0.0.0:27067` LISTENING
     4. `mcp__x64dbg__connect_remote(host=<VM_IP>, req_rep_port=27066, pub_sub_port=27067)`
     5. drive breakpoints / step via the other `mcp__x64dbg__*` tools
   - **Do NOT ask the user for the path or report "x96dbg.exe not installed"** (anti-pattern, historical DESIGN.md §9 rule 5 — now at docs/design/archive/DESIGN.md). Path + ports + bind are all known above. If `connect_remote` fails, the VM x64dbg isn't listening — launch it via vmr-shell (step 1), don't punt to the user with A/B/C options.
2. **`rev-frida`** — hook the API by name; capture call counts + serialized args
3. **`vmr-shell`** — detonate sample in VM; tcpdump / procmon / regshot for OS-level IO
4. **`malware-framework` (Qiling)** — unicorn emulation (often NEGATIVE for Go runtime; first-pass triage only)

## Why x64dbg first for call-site stepping

- Runs on the **real CPU** of the VM/process → immune to garble CFF (opaque predicates, not_found:NNNNN markers) and reflective thunk band resolution.
- Registers/args at the entry of a callee are the **actual payload** the sample transmitted — no decompiler re-labeling.
- Works for any reflective-load target once the loader resolves it (LoadLibraryW + GetProcAddress → real address → set BP → step).
- Frida hook frames sit ABOVE the callee entry — anti-hook samples can bypass.

## When NOT to use x64dbg

- Need to enumerate **all** reflective API resolutions in a window (Frida batch-call counters win).
- Need to capture network/file/registry writes (use VM + tcpdump/procmon, not debugger).
- Need to handle anti-debug (self-debugging, INT 2D, PEB->BeingDebugged) — VM stealth is better.

## Dispatch description format

```
[T3 tools=mcp__x64dbg__set_breakpoint,mcp__x64dbg__step_into,mcp__x64dbg__read_memory] claim C-NN <task>
```

The `tools=` list **must** include x64dbg MCP names when the task is call-site stepping. `hooks/worker_budget.py` `check_tools_allowed` does not enforce this preference; the orchestrator must list it explicitly in the dispatch.

## Anti-pattern (in-session)

iter 2.2 of `488d2dd8...` sample: 30-second Frida window produced 74 unique API resolutions but **no step-into CryptUnprotectData** to see `pDataIn`/`pDataOut`. User complaint: "为啥不用x64db去调试呢？是不是skill出了问题了？". Fix: when tier-3 dispatch targets a specific reflective API, orchestrator MUST include x64dbg tools and instruct worker to step in.

## Failure mode: x64dbg-automate plugin desync (event flood) — 2026-08-05

**Observed (C-326, sample `488d2dd8`, on a live VM lease):** setting syscall-level breakpoints
(`NtAllocateVirtualMemory` / `NtMapViewOfSection`) on a Go binary flooded the plugin — the Go
heap-alloc storm (runtime `makeslice`/`newobject` churn) hit the syscall BPs thousands of times,
overwhelming the x64dbg-automate ZMQ control channel. Plugin desynced; `connect` began returning
"Resource temporarily unavailable"; the construction-capture attempt was lost after ~20 min.

**Symptoms to recognize:**
- BP hit counts climbing orders of magnitude faster than expected (thousands in seconds)
- `connect`/`read_memory` returning "Resource temporarily unavailable" mid-session
- Plugin stops answering although the debuggee is paused

**Prevention (check BEFORE arming syscall-level BPs):**
- **Never set BPs on hot syscalls on Go binaries** (`NtAllocateVirtualMemory`, `NtMapViewOfSection`,
  `NtCreateFile`, `NtDelayExecution`). Go runtime calls these at 1/s–1000/s rates; the flood
  desyncs x64dbg-automate (same class as F036's rpc-serialization wedge — toolchain bug, not
  sample countermeasure).
- **Prefer hardware write BPs on a specific address** (e.g. `set_breakpoint(addr, HW)` / x64dbg
  `bphw addr, w`) over syscall BPs. If HW BP cannot be armed because the page isn't mapped yet
  (plugin rejects), fall back to a **software BP at the user-code write site** (the function that
  performs the write), not the syscall.
- If you must observe allocation: hook the **user-code caller** (e.g. `runtime.newobject`'s callers
  in the sample), not the ntdll syscall.

**Recovery once desynced:**
1. **Stop immediately** — don't retry `connect` in a loop (each retry burns ~1 min of wall-clock).
2. **Save what you have FIRST** — captured dumps/registers are already in hand; write them to the
   status file + evidence before any reconnect attempt (state-loss = HARD STOP, §1c).
3. Reconnect: `mcp__x64dbg__disconnect` (if available) → wait ~5 s → `connect_remote` again. If
   that fails twice, the plugin process itself may be wedged — restart the VM-side x64dbg via
   vmr-shell (`start "x64dbg" "<VM_X64DBG_DIR>\release\x64\x64dbg.exe" ...`) and
   reconnect (fresh plugin bind).
4. **Re-arm with a quieter strategy** — per Prevention above. If no quiet strategy exists for the
   observation, **record the partial capture honestly** (what was captured, what the flood cost)
   rather than burning more wall-clock on the same doomed path.
5. Log the incident in the worker status (`plan_vs_actual` + failure block): what BPs, what flooded,
   what was saved. This feeds the kunglao-agent improvement loop.

**Also 2026-08-05 (C-322/C-326/C-328 sessions):** the VM's DHCP lease **drifts on every snapshot
revert**. Any concrete IP in this file's examples is stale-by-default — **discover the live lease
first** (env discovery: `KUNGLAO_VM_HOST` / `vmr_client discover.sh` / `vmr_server health` on the
live IP) before `connect_remote`; cached IPs will time out.

recall_useful: pending
