# Design — init channel default (issue #727)

## D1 Adaptation layer (decoupling from in-flight #698)

#698 (channel matrix v6) develops in a parallel worktree. This card codes
against the **finalized contract**, not #698's tree:

- Contract consumed: `KUNGLAO_CHANNEL = ssh | docker | vmr | adb | local`;
  local = static-only first-class; dynamic+local → HARD REJECT is #698's.
- `init_channel_default.py` probes via its own local implementations. The
  vmr probe mirrors `toolchain._check_vm_channel`'s tcp-pair semantics by
  importing `toolchain._tcp_connect` (stable private helper, same-package
  import pattern used across scripts/). If a future #698 symbol
  (`_check_dynamic_channel`) exists it is preferred via `getattr` —
  **contract-dependency point for the post-#698 reconcile audit**:
  1. probe dispatch table (4 backends)
  2. env name `KUNGLAO_CHANNEL` + its values
  3. `local` semantics (static-only)

## D2 Resolution policy

- No explicit env: probe order `vmr, ssh, docker, adb` (vmr first = current
  default preserved). First available wins; none → `local` +
  `defaulted_to_local=True` + WARN.
- Explicit env value: probe only that channel. Unavailable → the decision
  KEEPS the explicit value (`defaulted_to_local=False`,
  `warn_reason="explicit channel unavailable — fix the environment or "
  "change KUNGLAO_CHANNEL"`). Respect explicit choice; never auto-switch.
- Unknown env value (not in the 4+local set): treated as explicit-and-
  unknown → decision records it verbatim with guidance WARN (no crash);
  #698's matrix will own hard validation later.

## D3 Probes (capability level, fail-open)

| channel | probe | unavailable reasons |
|---|---|---|
| vmr | `_tcp_connect(KUNGLAO_VM_HOST, 9876)` AND frida port (env override `KUNGLAO_VM_SHELL_PORT`/`KUNGLAO_FRIDA_PORT`, defaults 9876/1337) | host unset / tcp fail |
| ssh | `ssh -p <port> -o BatchMode=yes -o ConnectTimeout=5 <host> true` (rc==0) | binary missing / rc!=0 |
| docker | `docker version` (rc==0) | binary missing / daemon down |
| adb | `adb devices` stdout has a device line (`\tdevice\t` or `\temulator\t`) | binary missing / no device |

All `subprocess.run(..., timeout=10, capture_output=True)`; every failure
path returns `(False, reason)` — resolution never raises (init must not
dead-end here, of all places). Tests monkeypatch `subprocess.run`; the vmr
probe is monkeypatched at `_tcp_connect` — zero real network.

## D4 WARN event (fail-open)

New action `channel_default` in `EMIT_ACTIONS` (alphabetical). Emitted via
`kunglao_log.emit(ws, actor="init", action="channel_default", detail=...)`
whenever `defaulted_to_local` or an explicit-unavailable warn exists.
Wrapped in `try/except Exception: pass` — the emit contract (logging never
breaks the caller) applies recursively to this card too.

## D5 Workspace record

`write_init_report(..., channel: dict | None = None)` — keyword-only,
default None → key omitted (byte-identical reports for all existing
callers/tests; INIT_PHASES tuple untouched). Decision dict:
`{"selected": <name>, "defaulted_to_local": bool, "probes": {name: reason}}`.
Integration point: `main()` resolves after the toolchain preflight block,
before scaffold; the decision threads to both `write_init_report` call
sites (success path 2177 + error path 2152) so even a failed init records
what the channel would have been.

## D6 Deliberate non-goals

- local HARD REJECT on dynamic tasks: #698 (joint test deferred there)
- runtime os.environ propagation of the resolved choice: the workspace
  record is the contract; runtime consumers read the record / #698 matrix
