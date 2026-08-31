# Spec: VM channel backend enumeration

## ADDED Requirements

### Requirement: channel backend resolution

The system SHALL resolve the VM channel backend from the `KUNGLAO_CHANNEL`
environment variable with values `vmr` (default when unset) and `ssh`.
Unknown values SHALL fall back to `vmr` and the fallback SHALL be declared
in the vm_reachable detail text. Resolution SHALL never raise.

#### Scenario: unset
- **WHEN** `KUNGLAO_CHANNEL` is unset
- **THEN** the backend is `vmr` with no warning

#### Scenario: ssh selected
- **WHEN** `KUNGLAO_CHANNEL=ssh`
- **THEN** the vm_reachable probe runs the ssh capability path

#### Scenario: unknown value
- **WHEN** `KUNGLAO_CHANNEL=carrier-pigeon`
- **THEN** the backend is `vmr` and the detail contains
  `unknown KUNGLAO_CHANNEL=carrier-pigeon, falling back to vmr`

### Requirement: vmr backend behavior is unchanged

The `vmr` backend SHALL probe `KUNGLAO_VM_HOST` with TCP connects to
`VM_SHELL_PORT` and `FRIDA_PORT` (ProbeTier.LIVENESS) and SHALL produce
byte-identical detail strings to the pre-#698 probe for PASS, FAIL
(including `_vm_fail_fixes` inventory guidance), and unreachable-WARN
outcomes.

#### Scenario: vmr pass detail pinned
- **WHEN** both ports accept TCP under the vmr backend
- **THEN** the item detail equals
  `VM {host} reachable on {VM_SHELL_PORT}+{FRIDA_PORT}` (+ optional
  task_spec suffix) and `probe` is `ProbeTier.LIVENESS`

### Requirement: ssh backend capability probe

The `ssh` backend SHALL verify the channel by executing
`ssh -p {VM_SHELL_PORT} -o BatchMode=yes -o ConnectTimeout=5 {vm_host} true`
(ProbeTier.CAPABILITY) after a TCP pre-check on the shell port. The frida
port SHALL remain a LIVENESS check. Failure details SHALL distinguish
exactly three causes: port unreachable, auth failed, channel dialect
mismatch.

#### Scenario: port unreachable
- **WHEN** the TCP pre-check on `VM_SHELL_PORT` fails
- **THEN** no ssh command runs and the detail names port unreachable

#### Scenario: auth failed
- **WHEN** ssh exits non-zero with `Permission denied` in stderr
- **THEN** the detail names auth failed

#### Scenario: dialect mismatch
- **WHEN** ssh exits non-zero without a permission error
- **THEN** the detail names channel dialect mismatch

#### Scenario: pass
- **WHEN** ssh exits 0 and the frida port accepts TCP
- **THEN** the item is PASS, detail contains `via ssh backend`, and
  `probe` is `ProbeTier.CAPABILITY`

### Requirement: needs-aware ladder unchanged

Backend selection SHALL NOT alter the #449 needs-aware semantics: a
static-only task_spec keeps vm_reachable at WARN on both backends; a
needs_vm task keeps HARD on FAIL.

#### Scenario: ssh backend, static-only
- **WHEN** `KUNGLAO_CHANNEL=ssh`, task_spec is static-only, and the ssh
  probe fails
- **THEN** vm_reachable is WARN (not HARD) with the task_spec basis in the
  detail
