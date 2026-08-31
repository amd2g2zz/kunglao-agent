# Tasks: #698 dynamic channel abstraction

## 1. SDD
- [x] proposal (v6 final arbitration; history in design D0)
- [x] design D1-D9 (matrix D3, probe semantics D4, ssh-mcp D5, compat D6)
- [x] spec delta (specs/dynamic-channel/spec.md)

## 2. RED — tests/test_dynamic_channel_698.py
- [ ] enum parse: unset→vmr, ssh/docker/adb/local, unknown→vmr+note
- [ ] ssh probe: tri-state detail, command shape, frida liveness, PASS+tier
- [ ] docker-over-ssh optional container tri-state
- [ ] docker direct: daemon / container missing / exec rejected / pass
- [ ] adb: no device / unauthorized / pass
- [ ] vmr PASS byte-identical + LIVENESS
- [ ] static-only: zero subprocess probes, WARN, pinned substrings
- [ ] dynamic + local: HARD REJECT exact detail, zero subprocesses
- [ ] static + local: WARN local-static-only + basis
- [ ] mcp manifest ssh-mcp entry (WARN, windows/linux, static declaration)

## 3. GREEN
- [ ] toolchain.py: _channel_backend + _vm_probe_{vmr,ssh,docker,adb} +
      _check_dynamic_channel (rename, matrix D3), call sites ×2
- [ ] mcp_probe.py: ssh-mcp manifest entry
- [ ] README.md: five-channel section (local first-class) + env table rows
- [ ] regression: test_toolchain*.py test_toolchain_needs_first.py green

## 4. Gates
- [ ] devkit/quality_gates.py all 7 (Gate 2 ledger: 6 host reds expected)

## 5. Segments (stage → sha → orchestrator mint → commit)
- [ ] S1 docs: openspec 4 files
- [ ] S2 RED: tests/test_dynamic_channel_698.py
- [ ] S3 GREEN: toolchain.py + mcp_probe.py + README.md
