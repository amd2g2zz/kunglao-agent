# Acceptance — spec amendments for the §8.2 mismatches (2026-10-19)

Acceptance document for the six spec amendments that close the §8.2
MISMATCH ledger of `kunglao-technical-doc.md` (six rows: M1.4, M1.5, M1.6,
M3.4, M4.2, M4.5 — code evolved on owner rulings, spec text stayed frozen).
Every check below is a plain command with an expected output; nothing here
requires new tooling.

## 1. What to accept — amendment map (change dir → ruling recorded → implementing code)

| # | Amendment (§8.2 row) | Spec home | New semantics recorded | Implementing code |
|---|---|---|---|---|
| 1 | M1.4 | `openspec/archive/issue-496-decision-teeth/proposal.md` §Amendment 1 | strategy log is an always-on recorder: every pass writes a row; markerless = `strategy: "default", declared: false` (owner review 2026-10-10) | `hooks/dispatch_gate.py:975-1023` |
| 2 | M1.5 | `openspec/archive/issue-496-decision-teeth/proposal.md` §Amendment 2 | the teeth are FAIL_CLOSED: scorer/audit errors reject (owner ruling 2026-09-28: "a gate that cannot see must not wave the dispatch through"); rank-None on a healthy audit still passes | `hooks/dispatch_gate.py:544-585`, `736-791` |
| 3 | M1.6 | `docs/design/loop-engineering.md` §6.5 amendment + §9 row 1 | F1 ("gate reads activity_ts") SUPERSEDED by #754: liveness is tick-continuity via the shared evaluator; activity_ts stays the kicker's signal | `hooks/worker_budget_sinks.py:421-485`, `scripts/rlvr/liveness.py:261` |
| 4 | M3.4 | `openspec/changes/issue-691-rl-output-path/proposal.md` §W2 Amendment (+ pointer note in `specs/rl-output-path-691/spec.md`) | never-reject scoped to the DECLARED case; UNDECLARED + sampler material = one REJECT carrying the draw; cold sampler = honest gap (owner directive 2026-10-18) | `hooks/worker_budget_sinks.py:822-895` |
| 5 | M4.2 | `openspec/archive/issue-753-upgrade-safety/proposal.md` §Amendment A | dirty state on the migration path is committed AS the snapshot; RC 6 = no-snapshot face + early-exit refresh face; "no snapshot → no migration" stands | `scripts/kunglao_upgrade.py:1403-1482`, `1484-1497`, `2188-2191`, `1284-1298` |
| 6 | M4.5 | `openspec/archive/issue-753-upgrade-safety/proposal.md` §Amendment B (recorded home of the #764 refinement — #764 has no own spec dir) | iron rule append-tolerant for kunglao event logs: order-preserving prefix check; rewrites/reorders/deletions still trip rc=4 | `scripts/kunglao_upgrade.py:1055-1085`, `980-999` |

## 2. How to accept — machine-checkable commands

### 2.1 Spec-coverage gate (zero violations attributable to the six)

```
uv run python devkit/spec_coverage.py | grep -cE "issue-496|issue-691|issue-753|loop-engineering|764"
```

Expected output: `0`. (The gate scans open changes only; all three touched
openspec dirs are closed/archived, so the six must never appear in the
violation list. The pre-existing migration debt — 29 open changes /
58 violations — is out of this batch's scope and tracked in
`kunglao-technical-doc.md` §15.)

### 2.2 Pointer resolution — each cited file:line exists and carries the claimed semantics

Run each command; the expected fragment must appear in the output.

```
sed -n '981p' hooks/dispatch_gate.py      # M1.4: "local-fix (owner review 2026-10-10): the marker was an OPT-IN gate with"
sed -n '990p' hooks/dispatch_gate.py      # M1.4: strategy = m.group(1) if m else "default"
sed -n '556,557p' hooks/dispatch_gate.py  # M1.5: "REJECT (fail-closed, owner ruling 2026-09-28:" / "a gate that cannot see must not wave the dispatch through"
sed -n '563p;573p' hooks/dispatch_gate.py # M1.5: two "return _gate_error_reject(" FAIL_CLOSED faces
sed -n '745p' hooks/dispatch_gate.py      # M1.5: "REJECT (fail-closed, owner ruling 2026-09-28); an unreadable register"
sed -n '440,441p' hooks/worker_budget_sinks.py  # M1.6: "#533 F-H2 semantics kept: TICK data only — activity_ts stays" / "the kicker's signal"
sed -n '485p' hooks/worker_budget_sinks.py      # M1.6: "return (False, f'#754 continuous-tick liveness REJECT - {detail}')"
sed -n '261p' scripts/rlvr/liveness.py    # M1.6: "def evaluate_tick_continuity(state: dict, *,"
sed -n '873p' hooks/worker_budget_sinks.py      # M3.4: "override (sample_deviation). This supersedes the 2026-10-14"
sed -n '874p' hooks/worker_budget_sinks.py      # M3.4: "# "never rejects" amendment FOR THE UNDECLARED CASE ONLY (owner"
sed -n '881,889p' hooks/worker_budget_sinks.py  # M3.4: the UNDECLARED "return (_reject(" block with the sampled family guidance
sed -n '1413p' scripts/kunglao_upgrade.py # M4.2: "point the #753 ruling demanded, and committing beats refusing."
sed -n '1484p' scripts/kunglao_upgrade.py # M4.2: "def _refuse_no_snapshot(ws: Path) -> int:"
sed -n '2191p' scripts/kunglao_upgrade.py # M4.2: "return _refuse_no_snapshot(ws)"
sed -n '2116p' scripts/kunglao_upgrade.py # M4.2: early-exit refresh "return _refuse_dirty(ws, dirty_n)"
sed -n '1082p' scripts/kunglao_upgrade.py # M4.5: "if pre_lines == post_lines[:len(pre_lines)]:"
sed -n '982p' scripts/kunglao_upgrade.py  # M4.5: "only this tool's own lines (actor=kunglao_upgrade) and the TTL"
```

Loop form (every line must print output — an empty line is a FAIL;
`read` splits the pair, so this runs identically under bash and zsh):

```
printf '%s\n' \
  "981p hooks/dispatch_gate.py" "990p hooks/dispatch_gate.py" \
  "556,557p hooks/dispatch_gate.py" "563p hooks/dispatch_gate.py" \
  "573p hooks/dispatch_gate.py" "745p hooks/dispatch_gate.py" \
  "440,441p hooks/worker_budget_sinks.py" "485p hooks/worker_budget_sinks.py" \
  "261p scripts/rlvr/liveness.py" "873p hooks/worker_budget_sinks.py" \
  "874p hooks/worker_budget_sinks.py" "881,889p hooks/worker_budget_sinks.py" \
  "1413p scripts/kunglao_upgrade.py" "1484p scripts/kunglao_upgrade.py" \
  "2191p scripts/kunglao_upgrade.py" "2116p scripts/kunglao_upgrade.py" \
  "1082p scripts/kunglao_upgrade.py" "982p scripts/kunglao_upgrade.py" \
| while read -r linespec file; do
    test -n "$(sed -n "$linespec" "$file")" || echo "POINTER FAIL: $linespec $file"
  done; echo "pointer sweep done"
```

Expected tail: `pointer sweep done` with no `POINTER FAIL` lines.

### 2.3 Amendment-presence checks (the six sections are in the tree)

```
grep -c "### Amendment 1 — .*always-on recorder" openspec/archive/issue-496-decision-teeth/proposal.md   # expect 1
grep -c "### Amendment 2 — .*FAIL_CLOSED" openspec/archive/issue-496-decision-teeth/proposal.md          # expect 1
grep -c "SUPERSEDED" docs/design/loop-engineering.md                                                     # expect 3
grep -c "## W2 Amendment (2026-10-19" openspec/changes/issue-691-rl-output-path/proposal.md              # expect 1
grep -c "AMENDMENT 2026-10-19 (W2" openspec/changes/issue-691-rl-output-path/specs/rl-output-path-691/spec.md  # expect 1
grep -c "### Amendment A — B1" openspec/archive/issue-753-upgrade-safety/proposal.md                     # expect 1
grep -c "### Amendment B — " openspec/archive/issue-753-upgrade-safety/proposal.md                       # expect 1
```

## 3. How the connection works — invariants and integration contracts

| Amendment | Invariant cited (devkit/invariants/registry.json) | Integration contract face |
|---|---|---|
| M1.4 (strategy rows) | INV-001 `loop-sampler-exit` — the default row is the anomaly signal the invariant speaks of | dispatch ALLOW tail writer; one `runs/strategy-log.jsonl` row per pass; consumed by the `rl-sampler-exit` fingerprint |
| M1.5 (fail-closed teeth) | recorded under INV-001's gate posture (the shared 2026-09-28 ruling; no invariant owns top1/capability directly) | PreToolUse main chain order must-stop → failure-blocked → top1 → capability → strategy-log; `REJECT top1`/`REJECT capability` + exit 2 + trace events |
| M1.6 (tick continuity) | none of INV-001..008 owns heartbeat liveness; the design-doc amendment records the supersession, invariant-facing effects ride the D-domain faces | `check_heartbeat_alive` in the dispatch pre-check battery; reject fingerprint `#754 continuous-tick liveness REJECT` |
| M3.4 (W2 exit) | INV-001 `loop-sampler-exit` — the amendment IS the W2 wiring; fingerprint expects `strategy: "sampled"` rows | pre_check method-family face; `methodfamily` REJECT (exit 2) with sampled family + propensity + prior_source; DECLARED deviations keep `sample_deviation`-only |
| M4.2 (snapshot commit) | INV-008 `upgrade-transactional-flow` — redefines the snapshot leg: snapshot by construction or refuse | `upgrade()` non-dry-run transaction at scripts/kunglao_upgrade.py:2188; `[event] snapshot ok`; RC 6 on no-snapshot and early-exit-refresh faces |
| M4.5 (append tolerance) | INV-006 `iron-log-append-tolerance` — registry check `uv run pytest tests/test_upgrade_iron_log_764.py -q` | post-digest reconciliation at scripts/kunglao_upgrade.py:2246-2260; `[event] iron-rule fail` + rc 4 on true violation |

## 4. Assembly acceptance — re-check after ALL Phase 1 modules land

The documentation must still match the implementation once every Phase 1
module is merged. Run, from the repo root, on the assembled tree:

```
uv run python devkit/spec_coverage.py | grep -cE "issue-496|issue-691|issue-753|loop-engineering|764"
# expect: 0

uv run pytest tests -q -n 4 -k "doc or docs or contract or spec"
# expect: all passed (baseline 791 passed, 70 skipped — drift in either
# direction must be explained, never ignored)

uv run python devkit/quality_gates.py --quick
# expect: ALL gates pass (Requirement Correctness / Engineering Quality /
# Test Effectiveness)

uv run pytest tests/test_upgrade_iron_log_764.py -q
# expect: all passed (INV-006's registry check)

# pointer sweep from §2.2 — expect "pointer sweep done", no POINTER FAIL
```

Green on all five proves the assembled whole is internally consistent:
the specs name the invariants, the invariants pin the checks, and the
checks resolve to code that still says what the amendments claim.
