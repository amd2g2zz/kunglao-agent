# Spec delta: dynamic channel abstraction

## Requirement: five first-class channels

`KUNGLAO_CHANNEL` SHALL accept `vmr` (default), `ssh`, `docker`, `adb`,
`local`. Unknown values SHALL fall back to `vmr` without crashing and the
detail SHALL name the offending value.

### Scenario: default path unchanged

- **WHEN** `KUNGLAO_CHANNEL` is unset
- **THEN** behavior is byte-identical to the pre-#698 vmr probe
  (dual-port liveness, PASS detail wording, FAIL inventory footer, probe
  tier LIVENESS)

## Requirement: needs-aware check contract

### Scenario: static-only task, any channel

- **WHEN** task_spec declares `dynamic_re: forbidden`
- **THEN** the dynamic-channel block emits WARN items only
- **AND** no probe subprocess or TCP connection is attempted
- **AND** the detail contains "not required by task_spec" with the basis
  (channel phrase: "dynamic channel unchecked (static-only task)" for
  remote channels, "local static-only channel" for local)

### Scenario: dynamic task, local channel

- **WHEN** the task needs dynamics and `KUNGLAO_CHANNEL=local`
- **THEN** `vm_reachable` is FAIL / HARD with detail exactly
  "local channel forbids dynamic analysis — switch KUNGLAO_CHANNEL to
  vmr/ssh/docker/adb"
- **AND** no probe subprocess or TCP connection is attempted

### Scenario: dynamic task, remote channel

- **WHEN** the task needs dynamics and the channel is vmr/ssh/docker/adb
- **THEN** the probe is capability-level for ssh/docker/adb (real
  execution of a trivial command) and liveness-level for vmr
- **AND** failures carry a backend-tagged, tri-state-classified detail
  (port unreachable / auth failed / dialect mismatch — ssh; daemon
  unreachable / container missing / exec rejected — docker; no device /
  unauthorized / frida port closed — adb)

## Requirement: optional docker execution target

- **WHEN** `KUNGLAO_DOCKER_CONTAINER` is set and the channel is `ssh`
- **THEN** the ssh probe additionally verifies docker-over-ssh
  (`docker version`, then `docker exec <c> true`) with the docker
  tri-state detail
- **WHEN** the channel is `docker`
- **THEN** the daemon check runs directly (`docker version`, DOCKER_HOST
  respected) without requiring `KUNGLAO_VM_HOST`

## Requirement: ssh-mcp static registration

- **WHEN** mcp_probe builds its manifest
- **THEN** `ssh-mcp` is declared (WARN tier, windows/linux types) as the
  execution control plane for the ssh channel
- **AND** it is not demanded by any required group (static declaration;
  CLI ssh is the fallback)
