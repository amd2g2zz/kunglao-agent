# Proposal: dynamic channel abstraction — five first-class control planes (#698)

## Why

Issue #698 field report (kunglao-lab, 2026-08-25): a self-hosted docker
container (sshd on 9876, frida-server on 1337) passed the vm_reachable probe
with `KUNGLAO_VM_HOST=localhost` — because `_check_vm_channel` is pure TCP
LIVENESS (`_tcp_connect(9876) and _tcp_connect(1337)`), while the channel
actually carries the vmr-shell protocol. Probe-green / execute-red is not
observable at init. The proposer's self-review narrowed the claim (probe is
needs-aware per #449; vmr-shell is an external skill so dialect coupling
lives in docs) — but the core proposition stands: **no channel abstraction
exists**, and user-supplied environments must impersonate VMware to get a
green probe.

## Arbitration history (v1 → v6, orchestrator + user, 2026-08-26)

The issue text is feedback, not spec — six rounds of arbitration shaped this
card; this proposal records the final ruling only (full evolution in
design.md):

- v1 flat enum `vmr|ssh` → v2 platform mapping → v3 four parallel backends →
  v4 ssh as universal control plane, docker demoted to an ssh driver →
  **v5** docker restored as a DIRECT channel (DOCKER_HOST); purpose
  re-defined: `KUNGLAO_CHANNEL` exists to **give the agent an execution
  control plane for dynamic debugging**; HARD checks apply to dynamic tasks
  only (static-only stays WARN, contract test-pinned) →
  **v6 (final)** adds `local`, a first-class static-only channel.
- Execution-layer routing stays OUT of scope (no code-level remote-exec
  engine): vmr-shell and **ssh-mcp** (upstream verified 2026-08-26:
  npm `ssh-mcp`, 11 tools incl. run-command / sftp-upload / sftp-download /
  sessions, TOML profiles) are skill/MCP-layer control planes; this card
  ships PROBES + static MCP registration + docs only.

## What Changes

1. `KUNGLAO_CHANNEL = vmr (default, byte-identical current behavior) | ssh |
   docker | adb | local`; unknown value → vmr fallback with the offending
   value named in the detail.
2. `scripts/toolchain.py`: `_check_vm_channel` → `_check_dynamic_channel`
   (call sites windows/linux updated; check item NAMES `vm_reachable` /
   `remote_debugger` unchanged for compat).
3. Probe matrix (needs-aware × channel):
   - static-only task, any channel → whole block WARN, **zero probe
     subprocesses** ("dynamic channel unchecked (static-only task)" for
     remote channels; "local static-only channel" for local).
   - dynamic task + `local` → **HARD REJECT**: "local channel forbids
     dynamic analysis — switch KUNGLAO_CHANNEL to vmr/ssh/docker/adb".
   - dynamic task + ssh/docker/vmr/adb → HARD capability-level probe:
     ssh = real `ssh -o BatchMode=yes ... true` (tri-state: port
     unreachable / auth failed / dialect mismatch; optional
     `KUNGLAO_DOCKER_CONTAINER` docker-over-ssh check), docker = direct
     `docker version` + optional `docker exec <c> true` (DOCKER_HOST
     respected by the CLI), vmr = current dual-port liveness byte-identical,
     adb = `adb devices` (no device / unauthorized) + frida liveness.
4. `scripts/mcp_probe.py`: static manifest entry for `ssh-mcp` (WARN tier,
   windows/linux; execution control plane for the ssh channel; CLI ssh is
   the fallback).
5. README: five equivalent channels section ("the goal is to give the agent
   a control plane"); `local` is a first-class choice for simple static
   tasks or environments without dynamic infrastructure — red line: local
   is static-only, any dynamic work must switch channels.

## Out of scope

- Code-level remote command execution / file transfer (skill + ssh-mcp layer).
- mcp_probe runtime liveness verification of ssh-mcp (that is mcp_probe's
  own domain; this card declares the entry statically).
- Android manifest changes (#455: android has NO vm channel by design —
  adb dynamics already flow through the existing device checks).
