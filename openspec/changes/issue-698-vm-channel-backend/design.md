# Design: dynamic channel abstraction (#698)

## D0 — Arbitration evolution (why v6 looks like this)

| Round | Model | Rejected because |
|---|---|---|
| issue text | probe upgrade only | no abstraction; acceptance asked for exec dispatch |
| v1 | flat `vmr\|ssh` | not enough backends for real environments |
| v2 | platform→backend mapping (win=vmr, linux=docker, android=adb) | over-constrained: platform ≠ channel; ssh VMs legitimate |
| v3 | four parallel backends | docker treated as independent peer — but how do you reach a REMOTE docker? |
| v4 | ssh universal, docker = ssh driver | user correction: docker IS directly reachable via DOCKER_HOST / local daemon; demoting it to an ssh passenger was wrong |
| v5 | ssh/docker/vmr/adb peers; purpose = agent execution control plane; dynamic-only HARD | user addition: a local (no-infra) option was missing |
| **v6** | + `local` static-only first-class channel | FINAL |

## D1 — Purpose

`KUNGLAO_CHANNEL` answers ONE question: **which control plane does the agent
use for dynamic debugging?** Everything else (static toolchain) is
channel-independent. Five equivalent answers; environment self-selects.

## D2 — Enum & fallback

```python
_raw = (KUNGLAO_CHANNEL or "").strip().lower()
"" | "vmr"  -> vmr          # default; current behavior byte-identical
"ssh"       -> ssh
"docker"    -> docker
"adb"       -> adb
"local"     -> local
other       -> vmr + warn note naming the value in the detail
```

Rationale: unset must stay vmr — the pinned `byte_identical` test and every
existing deployment depend on it; ssh being "the universal control plane"
is a README-level recommendation, not a default change.

## D3 — needs-aware × channel matrix (the contract)

| task \ channel | vmr | ssh | docker | adb | local |
|---|---|---|---|---|---|
| static-only | WARN, no probes | WARN, no probes | WARN, no probes | WARN, no probes | WARN, no probes ("local static-only channel") |
| dynamic (needs_vm) | HARD liveness probe (byte-identical) | HARD capability probe | HARD capability probe | HARD capability probe | **HARD REJECT** (fixed detail, no probes) |

- static-only fast path skips ALL probes (TCP + subprocess): a static task
  must not spawn ssh/adb/docker processes. Detail keeps the pinned
  "not required by task_spec ({basis})" suffix; the leading phrase is
  "dynamic channel unchecked (static-only task)" (remote) or
  "local static-only channel" (local).
- dynamic + local: vm_reachable = FAIL/HARD, detail exactly
  "local channel forbids dynamic analysis — switch KUNGLAO_CHANNEL to
  vmr/ssh/docker/adb"; remote_debugger cascade FAILs likewise. No probes,
  no VM inventory — the reject is a policy decision, not a discovery.
- The remote_debugger cascade structure (needs_vm ? FAIL/WARN : WARN) is
  preserved for every branch; existing pins (`not required by task_spec`
  on both items) hold.

## D4 — Probe semantics per backend

- **vmr** — current code path extracted verbatim into `_vm_probe_vmr`:
  `_tcp_connect(VM_SHELL_PORT) and _tcp_connect(FRIDA_PORT)`, PASS detail
  `VM {host} reachable on {p}+{p}`, probe tier LIVENESS, FAIL path through
  `_vm_fail_fixes` unchanged (vmrun inventory footer is vmr-specific and
  stays there only).
- **ssh** — CAPABILITY: TCP pre-check on VM_SHELL_PORT (fail → "port
  unreachable"), then `_run_cmd(["ssh","-p",port,"-o","BatchMode=yes",
  "-o","ConnectTimeout=5",host,"true"])`; rc==255 + "permission denied" →
  "auth failed"; other rc → "channel dialect mismatch (rc, head of
  output)". Frida port stays LIVENESS ("ssh ok but frida port closed").
  Optional `KUNGLAO_DOCKER_CONTAINER`: `ssh ... docker version` →
  "docker daemon unreachable"; `ssh ... docker exec <c> true` →
  "container missing" (No such container/object) | "docker exec rejected".
- **docker** — DIRECT channel, no ssh, no KUNGLAO_VM_HOST required:
  `_run_cmd(["docker","version"])` (DOCKER_HOST env is consumed by the
  docker CLI itself — remote daemon support is free); optional
  `KUNGLAO_DOCKER_CONTAINER` → `docker exec <c> true` with the same
  tri-state. No frida liveness (frida reachability through a container
  publish is topology-dependent; the exec check is the honest capability).
- **adb** — `adb devices`: rc≠0 or empty device list → "no device";
  "unauthorized" → "unauthorized (accept the debugging prompt)"; device
  online + `_tcp_connect(KUNGLAO_VM_HOST or 127.0.0.1, FRIDA_PORT)` →
  "frida port closed" (fix hint: adb forward). CAPABILITY tier.

PASS details carry the backend tag ("via ssh backend …", "via adb backend
…"); **vmr PASS detail stays byte-identical** (no tag) — v6 "vmr 现行为
不变" outranks the generic tagging rule.

## D5 — Execution layer (out of code, declared)

ssh-mcp (github.com/tufantunc/ssh-mcp, verified 2026-08-26): npm `ssh-mcp`,
TOML profile config, tools `run-command` / `read-command` /
`privileged-command` / `sftp-upload` / `sftp-download` / session suite /
`signal-process`. Registered as a static WARN-tier manifest entry in
mcp_probe.py (windows/linux) — probe does NOT verify its liveness
(mcp_probe's own domain). CLI ssh remains the fallback path. vmr-shell
skill keeps the snapshot/revert workflow (its irreplaceable value);
remote exec for docker/adb flows through the existing skill layer.

## D6 — Compat invariants

- Item names `vm_reachable` / `remote_debugger` unchanged (pinned by
  tests/test_toolchain_install.py invariant list and needs_first helpers).
- Function renamed `_check_vm_channel` → `_check_dynamic_channel`; two
  call sites (windows/linux manifests); android NEVER_CHECKS unchanged.
- `test_check_no_task_spec_vm_hard_byte_identical` (no task_spec, no
  channel, no host) must stay green with zero output drift: default vmr
  path is untouched code, only extracted.

## D7 — Test plan (RED first)

1. enum parse table (unset/vmr/ssh/docker/adb/local/unknown+note)
2. ssh tri-state + command shape; frida-closed; PASS detail + tier
3. docker-over-ssh optional container tri-state
4. docker direct: daemon fail / container missing / exec rejected / pass
5. adb: no device / unauthorized / pass
6. vmr byte-identical PASS + LIVENESS tier
7. static-only: zero subprocess probes (mock _run_cmd + _tcp_connect
   assert not called), WARN, pinned substrings
8. dynamic + local: HARD REJECT exact detail; zero subprocesses
9. static + local: WARN "local static-only channel" + basis suffix
10. mcp manifest: ssh-mcp entry fields; not demanded by any group

## D8 — README

New subsection under Configuration: five equivalent channels table
(channel / what it drives / prerequisites), local framed FIRST-CLASS
("choose local when static tooling answers the primary questions, or no
dynamic infrastructure exists — red line: static-only; switch channels for
any dynamic work"), ssh-mcp pointer, DOCKER_HOST/KUNGLAO_DOCKER_CONTAINER
notes, vmr dual-role note (any guest OS; snapshot rollback is its unique
value — a Linux VM may be driven by vmr OR ssh).

## D9 — Failure open-closed posture

All probes fail-closed for dynamic tasks (a lying green costs a session);
the whole block degrades to WARN-only for static tasks (a lying red blocks
nothing). Unknown channel values never crash — fallback + note.
