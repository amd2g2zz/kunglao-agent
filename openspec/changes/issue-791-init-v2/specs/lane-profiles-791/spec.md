# lane-profiles-791 delta — issue-791-init-v2

## ADDED Requirements

### Requirement: the lane registry is the single source

Every lane-shaped init surface (prescan battery, binary-only promise
faces, obligation artifacts, difficulty factor set, capability
vocabulary) SHALL read its slice from scripts/lane_profile.py. An
unknown lane value SHALL resolve to the malware profile with
exact=False and the resolving caller SHALL emit a loud WARN (fail-open
to the pre-#791 binary yaml, never a guessed new shape).

#### Scenario: every enum lane has a profile

- **WHEN** the registry is consulted for any lane_spec.LANES value
- **THEN** the profile resolves exact=True

#### Scenario: unknown lane fails open loudly

- **WHEN** a task_spec declares a lane outside the registry
- **THEN** the binary battery applies (today's yaml) and a WARN names
  the lane_profile fallback

### Requirement: out-of-lane prescan probes are dropped at init

The promise block SHALL carry ONLY the lane's registry probe battery:
lane:web SHALL produce ZERO apkid/die prescan entries, no
java_reachability and no obfuscation_prior; the T1 first-claim
obligation (#669) SHALL name only in-lane artifacts (web: none).
lane:malware SHALL keep today's battery and obligation byte-for-byte.

#### Scenario: the 51job replay

- **WHEN** init runs on a lane:web workspace
- **THEN** promise.prescan == {}, java_reachability/obfuscation_prior
  are absent, and prescan_obligation.required == []

### Requirement: difficulty is factor-set-shaped and honestly unknown

The calibration output SHALL carry factor_set; a non-binary lane whose
extractors report nothing — or that has no validated weight table —
SHALL calibrate tier=unknown, never easy. Unknown lane SHALL select
today's binary map.

#### Scenario: web at init

- **WHEN** difficulty calibrates on a lane:web workspace with no web
  extractors
- **THEN** factor_set == web, the web families are listed inactive,
  tier == unknown

#### Scenario: binary regression pin

- **WHEN** the locked #15 binary corpus shape calibrates
- **THEN** tiers are unchanged (hard/max on the themida profile)

### Requirement: dispatch never fabricates a capability

A dispatch whose DECLARED tools mechanically require an env capability
that the near-time env-state records DOWN SHALL be REJECTED (evidence
class) with the component and the wake condition, and the rejection
SHALL land one lane_capability_reject row in the unified log.
skip/absent/stale/unreadable state SHALL NOT gate (silence is never
evidence of DOWN). device_root SHALL be in the env-state vocabulary
(android probes emit it honestly: pass/fail/skip).

#### Scenario: the 9x dynamic-trace pathology replay

- **WHEN** env-state records frida_server=down and a dispatch declares
  a frida-family tool
- **THEN** the dispatch REJECTS exit 2 naming frida_server and the
  wake condition

#### Scenario: zero fabricated capability

- **WHEN** the state entry is skip, absent, stale or the file
  unreadable
- **THEN** the gate passes with no opinion
