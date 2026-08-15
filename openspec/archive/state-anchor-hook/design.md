# Design — state_anchor hook (#44)

## Design Decisions

### D1. Anchor = compact fired-predicate snapshot, ≤500 chars, inject on every Agent completion

`build_anchor(ws)` reads the SAME mechanical state #45's resume prompt reads
(ledger last SNAPSHOT row, claim-register OPEN / PARTIALLY-VERIFIED ids,
facts/_INDEX partials, in-progress workers), but compressed to a ≤500-char
single block delivered as `additionalContext` on every Agent-tool
completion. The compression rule: keep the decision-relevant fields the loop
acts on (decision, open_count, open ids, partial count, active workers,
blockers, facts_total), truncate the open-ids list from the tail when it
overflows, never raise. This is the per-turn "what am I allowed to know"
re-anchor F5 requires — zero cognition, zero forgetting.

The emission shape mirrors worker_pulse exactly (`hookSpecificOutput.additionalContext`,
JSON to stdout, `ensure_ascii=False`) so the harness injects it identically.

### D2. Drift warning gates on `drift_detected` (the #43 alive-but-stuck signal), not bare rotation

The issue text names the warning trigger as
`signature_rotation(ws) >= ROTATION_WINDOW(3)`. The hook refines this to
`drift_detected(ws)` — i.e. `signature_rotation ≥ ROTATION_WINDOW AND NOT
workers_progressing` — for one reason: a legitimate SATURATED wait (worker
pool full, three workers grinding, ledger signature frozen because nothing
can dispatch) would otherwise cry `⚠ STATE FLAT` on every worker completion.
`drift_detected` is EXACTLY #43's "alive-but-stuck" predicate; the issue
itself calls the warning "the alive-but-stuck signal from #43", which IS
`drift_detected`, not bare rotation. The TDD fixture (rotation=4, no worker)
satisfies both readings identically. The warning text carries N =
`signature_rotation(ws)` so the orchestrator sees the frozen-run length and
directs a re-read of the claim register (the cure).

### D3. Cross-domain reuse: importlib load of `scripts/lib_kunglao.py` under `lib_kunglao_scripts` (single source of truth)

`signature_rotation` / `drift_detected` live in `scripts/lib_kunglao.py`
(#43). `state_anchor.py` lives in `hooks/` — a SEPARATE sys.path domain
(pytest.ini `pythonpath = . hooks scripts tools`; production: each hook
runs with `hooks/` at `sys.path[0]`). A bare `from lib_kunglao import …`
inside the hook resolves to `hooks/lib_kunglao.py` (which does NOT carry
the drift functions) in BOTH pytest and production — see
`tests/test_drift_detection.py` lines 27-33 for the documented ambiguity.

Decision: **load `scripts/lib_kunglao.py` by explicit path under the unique
name `lib_kunglao_scripts`** — the exact pattern
`external_kicker.should_kick` (#43) and `tests/test_drift_detection.py`
already use. The hook caches the module in `sys.modules` so under pytest it
shares one instance with the external_kicker test path; in production each
process loads the same file bytes once.

The load is wrapped in try/except → any failure degrades to "no drift
warning this turn" (FAIL_OPEN, D5). The drift WARNING is a bonus; the anchor
SUMMARY (D1) does not depend on it. See R1/R2 for the rejection of the
byte-for-byte mirror alternative.

### D4. Entry guard + payload parsing mirror worker_pulse

`main()` reads the stdin JSON payload exactly as worker_pulse does
(`payload["tool_name"]`, `payload.get("tool_input", {})`, workspace
resolution). It emits ONLY when:

1. `payload["tool_name"]` lowercased == `"agent"` (the harness lowercases
   tool names — match case-insensitively so a real `Agent` / `AGENT` /
   `agent` value all hit);
2. `_kunglao_active(ws)` (strict activation, 30-min TTL — a stray
   non-kunglao session gets zero injection, same default-inactive contract
   as worker_pulse / dispatch_gate).

Non-agent tools and inactive sessions SKIP (rc 0, empty stdout). This
mirrors worker_pulse's SMART philosophy: narrow + alive-only. The
workspace-resolution + activation helpers reuse `hooks/lib_kunglao.py`
(`resolve_workspace`) and `scripts/hook_activation.py` (`is_active_strict`)
via the same `sys.path.insert` pattern worker_pulse uses.

### D5. FAIL_OPEN at every layer

`build_anchor` wraps ALL file reads + the drift lookup in a single
try/except → returns `""` on any exception (missing ledger, corrupt JSON,
OSError, importlib failure). `main()` wraps the whole body in try/except →
returns 0 on any exception. A state_anchor failure MUST NEVER abort a worker
completion; the worst case is "no anchor injected this turn", which is the
status quo before this hook existed.

### D6. Wire-up is a one-line mirror of worker_pulse's registration

`scripts/wire_up_settings.py` gains a single `_ensure(post, "Agent",
"state_anchor.py")` after the worker_pulse line — same matcher, same
`_entry()` shape, same POSIX-path convention (hooks run via `sh -c`;
Windows backslashes get eaten as escape chars).
`scripts/hook_activation.py::ALL_HOOKS` gains `"state_anchor"` for
consistency (worker_pulse is already listed). The wire-up is TESTED via a
unit test that calls the `_ensure` helper on a TEMP settings dict
(monkeypatch `Path.home()`); the real `~/.claude/settings.json` is never
mutated by the test.

## Rejected alternatives

### R1 (rejected): byte-for-byte mirror `signature_rotation` into `hooks/lib_kunglao.py`

`hooks/lib_kunglao.py` already mirrors `scan_active_workers` from
`scripts/convergence_check.py` (#37 — the documented "byte-for-byte mirrors
across the boundary, not cross-imports" convention; see
`scripts/lib_kunglao.py` header lines 23-27). Mirroring `signature_rotation`
there is the convention-consistent move and was the first candidate.

Rejected for a specific reason: **the drift signal is semantically coupled
between the cure (this hook, warns at rotation ≥ ROTATION_WINDOW) and the
recovery (`external_kicker.should_kick`, escalates at rotation ≥
DRIFT_ESCALATE_ROWS)**. #43's design D4 explicitly couples them — the 3→6-row
gap is the "cure-first window" that must heal before recovery fires. A
mirror forks that coupling: a future edit to
`scripts/lib_kunglao.signature_rotation` (e.g. adding a field to the
signature tuple) that misses the hooks mirror would silently break the
cure/recovery contract — the hook would warn at rotation=3 under signature A
while external_kicker kicks at rotation=6 under signature B, and if A and B
disagree on "identical" the cure-first window is fictional. A mirror test
catches divergence only REACTIVELY (after a window of disagreement). For
SEMANTICALLY COUPLED logic, single-source is strictly safer.

The `scan_active_workers` mirror (#37) is a different case: worker-counting
is a STABLE, DECOUPLED utility (no cure/recovery coupling), so mirror+test
is adequate. Drift detection does not share that character. The carve-out:
**mirrors for stable decoupled utilities, single-source importlib for
cure/recovery-coupled semantics.**

### R2 (rejected): re-derive `signature_rotation` independently inside the hook

Rejected outright — the issue explicitly forbids it ("do NOT re-derive the
signature formula independently (that would fork the drift semantics)").
Re-deriving the signature tuple / window rule by hand would fabricate a
third drift definition alongside `scripts/lib_kunglao.py` and the test
reference; the cure/recovery contract (D3 / R1) cannot survive that. The
build_anchor drift result MUST equal
`scripts/lib_kunglao.signature_rotation` / `drift_detected` exactly (same
fields, same window).

### R3 (rejected): fire on ALL PostToolUse tools, not just Agent

Rejected: the anchor's purpose is to re-anchor belief after a WORKER
completion (the moment the loop's state is most likely to have moved and
most likely to be forgotten while the orchestrator digests the report).
Firing on every Bash / Read / Write would inject the same snapshot dozens
of times per turn (noise) and is not the F5 "forget/refresh per turn"
contract — it is per-WORKER-turn, and Agent-tool completion is the
mechanical proxy for that. Non-agent tools SKIP (D4).

### R4 (rejected): make state_anchor a GATE that rejects when drifted

Rejected: a PostToolUse gate that aborts worker completion on drift would
block the orchestrator from processing a legitimate worker report — the
opposite of helping. The anchor's job is to INJECT belief
(`additionalContext`), not to enforce. The hard recovery on persistent
drift is `external_kicker`'s job (the kick), not the cure layer's.
