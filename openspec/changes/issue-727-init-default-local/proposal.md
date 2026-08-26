# Init auto-defaults channel to local (#727)

## Why

User directive 2026-08-26: init must not dead-end on environment. When all
four remote channels (ssh/docker/vmr/adb) are unavailable, init auto-defaults
the workspace channel to `local` (static-only first-class citizen per the #698
v6 matrix) plus a WARN event — instead of blocking at a HARD gate. Honest
degradation with an explicit trail beats another question round (#449
intake-first posture).

## What Changes

- New `scripts/init_channel_default.py` (adaptation layer, #698-decoupled):
  - `REMOTE_CHANNELS = ("vmr", "ssh", "docker", "adb")`
  - capability-level probes per backend (vmr = tcp liveness pair mirroring
    `toolchain._check_vm_channel`; ssh = `ssh -o BatchMode=yes ... true`;
    docker = `docker version`; adb = `adb devices` device-line scan) — all
    fail-open, never raise, no real network in tests (subprocess mocked)
  - `resolve_init_channel(ws)`: no explicit `KUNGLAO_CHANNEL` → probe vmr
    (current default) then ssh/docker/adb → first available wins → none →
    `local` + `defaulted_to_local=True`; explicit channel → probe only it,
    unavailable → keep the explicit choice (never auto-switch), WARN with
    fix guidance
  - `emit_channel_decision(ws, decision)`: fail-open kunglao_log emit of the
    WARN (`channel_default` action) — logging must never break init
- `event_taxonomy.EMIT_ACTIONS` + `channel_default` (alphabetical; the
  existing adoption anchor checks membership, not a fixed count)
- `kunglao-init.py`: resolve the channel after the toolchain preflight,
  before scaffold; record the decision as a top-level `channel` block in
  `runs/.init-report.json` (backward-compatible: `write_init_report(...,
  channel=None)` omits the key when absent — INIT_PHASES untouched)
- #698 interplay: dynamic-task + local HARD REJECT is #698's domain and is
  deliberately NOT implemented here (joint test deferred, noted in the issue)

## Acceptance (mirrors issue)

1. all-remote-unavailable (mocked) → init-side resolution returns `local`,
   defaulted flag set, WARN event lands in runs/logs/kunglao-*.jsonl
2. a reachable ssh (mocked) → selects ssh, no default degradation
3. explicit `KUNGLAO_CHANNEL=ssh` + unavailable → stays ssh, guidance WARN,
   no auto-switch
4. emit failure never breaks resolution (fail-open pinned)
5. `.init-report.json` carries the channel block; no absolute-path literals
   anywhere; tests monkeypatch every subprocess (zero real connections)

## Out of scope

- KUNGLAO_CHANNEL matrix itself, local HARD REJECT (#698)
- ssh-mcp registration (#698), runtime env propagation of the channel choice
