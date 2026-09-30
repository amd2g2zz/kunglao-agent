# Design — issue-461-attribution-state (Phase 1)

## Context

The kernel learns over state signatures; a failed act currently
leaves prose only. Phase 1 gives failures a structured, evidence-born
cause object and puts it in the state. Phase 2 (post-462) turns
cause-bearing failure states into option-death posteriors — out of
scope here. The owner's explicit boundary: attribution is an EVIDENCE
artifact produced by intervention; it is never a verdict and never a
mandatory checklist (rule-gates were rejected — behavior must emerge
from state + termination + outcome correlation, not enforcement).

Adjacent surfaces (checked for contradiction in review):
- blocker schema v2 (`scripts/blocker_lint.py`, issue 340) — the
  differential-probe discipline for env attributions; obstacle/1
  extends the same idea to act failures but WITHOUT a write gate (the
  blocker gate exists because a blocker is an inherited premise; an
  obstacle row is kernel food, not a premise). The PROBE_MARKERS
  discipline is REUSED (lazy import) for artifact-shape validation.
- evidence-index / provenance-gate (archived specs) — raw evidence
  registered under evidence/ for fact citation. CONSEQUENCE (review
  CRITICAL): the obstacle registry does NOT live under evidence/ —
  `tools/pipelines/build_evidence_index.py` sweeps evidence/
  recursively (SCAN_DIRS, name-only derivation exclusions) and would
  index obstacle rows as raw evidence, letting a fact satisfy
  provenance by citing the derived attribution row instead of raw
  probe bytes — the exact F023 class the gate rejects. Registry home:
  runs/obstacles/ (beside q-cell-log / posterior-store /
  situation-stream — the kernel-telemetry tree).
- failure-analysis family (`scripts/failure_analysis_gate.py`,
  issue 495 obstacle-claim promotion via ask_for_direction
  --identified-obstacle; the #234 obstacle ladder): an "obstacle
  claim" is a REGISTER claim that licenses death declarations under
  the three-state charter. An obstacle/1 row is NOT a claim, is never
  promoted, and licenses nothing; a claim MAY cite an OBS row as
  evidence later. Vocabulary disambiguation is stated in the spec and
  the worker doc.
- 396 freeze — recording faces are never imported by decision faces.
- kernel-actuation (issue 462, in flight) — owns q_cells/compose/hook
  wiring; this change touches neither. Interactions disclosed below.

## Data structures

### obstacle/1 row (one JSON file per obstacle)

Path: `<ws>/runs/obstacles/OBS-<n>.json`, n zero-padded to 3
(facts/F<NNN> idiom), minted by EXCLUSIVE CREATE (os.open O_EXCL; a
concurrent producer that loses the race re-tries at n+1 — never
overwrite). read() sorts by PARSED n (not lexicographic), so the
999→1000 rollover cannot disorder the registry.

```json
{
  "schema": "obstacle/1",
  "id": "OBS-001",
  "ts": "2026-09-30T08:00:00Z",
  "kind": "detection_trigger",
  "cause": "frida attach detected: process exits 30s after attach (probe rc=1, ptrace stop)",
  "evidence_path": "runs/probes/20260930-frida-isolation.txt",
  "method_family": "dynamic-trace",
  "claim": "C-12",
  "dispatch_id": "d-3"
}
```

Field contract:

| field            | rule                                                            |
|------------------|-----------------------------------------------------------------|
| schema           | constant "obstacle/1"                                           |
| id               | OBS-<n>, stem-unique, exclusive-create minted                    |
| ts               | ISO-8601 UTC (harness_common.utc_now_z; injectable for tests)   |
| kind             | closed enum KINDS = missing_env_entry / detection_trigger /     |
|                  | encryption_layer / tool_limit / other                           |
| cause            | single line, non-empty, <= 200 chars (machine-checkable: names  |
|                  | the env entry / trigger / layer — the one-liner a probe rc      |
|                  | discriminates, not prose)                                       |
| evidence_path    | workspace-relative POSIX path, no parent segments, no absolute  |
|                  | paths; file EXISTS at record time AND carries a probe-execution |
|                  | marker (blocker_lint.PROBE_MARKERS via lazy import — command /  |
|                  | rc= / uid= / -> shapes; error prose alone is rejected)          |
| method_family    | the failed act's declared family, recorded VERBATIM — the       |
|                  | registry gate (method_families.yaml, issue 432) stays the       |
|                  | enforcement face; this producer records, never rejects on       |
|                  | vocabulary (the #462 prior-intersection posture)               |
| claim/dispatch_id| optional join keys (q_cells observation-row precedent)          |

No status field, no verdict field — deliberately unpronounceable as a
conclusion. Not an obstacle claim; licenses no terminal state.

Integrity posture: record-time checks are structural + artifact
existence + probe-marker shape; read() re-validates STRUCTURE only
(schema/kind/required fields; invalid rows skipped tolerantly).
Artifact existence is NOT re-checked at read time — a row is history;
scratch cleanup under runs/ must not erase attribution from state.
Hand-edited well-formed rows enter the digest as training noise (the
Phase-2 posterior outvotes noise); Phase 1 adds no checksums —
disclosed, accepted.

### Library faces (scripts/rlvr/obstacles.py)

- `KINDS`, `SCHEMA`, `OBSTACLES_REL = "runs/obstacles"`
- `validate_obstacle(row, ws) -> list[str]` — the boundary check
  (pure; ws consulted for evidence_path existence + marker shape)
- `record(ws, *, kind, cause, evidence_path, method_family, claim=None,
  dispatch_id=None, ts=None) -> dict` — loud-result fail-open
  (posteriors.record idiom: `{"appended": bool, "reason"/"errors": ...,
  "row"/"path": ...}`, never raises); exclusive-create mint
- `read(ws) -> list[dict]` — tolerant, parsed-n sorted; corrupt or
  structurally invalid rows skipped
- `face(ws) -> {"present": bool, "count": int, "kinds": str}` — the
  state digest; kinds is the sorted `kind=count` pattern
  (claim_pattern idiom), "" when none
- CLI: `record` and `face` subcommands (q_cells __main__ precedent),
  argparse, JSON result to stdout. The helper is the SANCTIONED
  producer (protocol); it is not claimed to be the only possible
  writer — write_guard does not adjudicate runs/obstacles/ in Phase 1
  and no gate enforces the protocol.

### State capture (scripts/rlvr/state.py)

- `snapshot()` gains key `"obstacles": obstacles.face(ws)` — lazy
  `from rlvr import obstacles` inside a reader function (the
  `_probe_signal_progress` lazy-import precedent; state.py stays
  dependency-light at import time).
- `signature_str()` gains the segment before the reserved sides tail:
  `...|ph=<phase>|ob=<kinds pattern>|sd=-` (`-` when the pattern is
  empty). SCHEMA advances to `state-sig/2` (the eight-segment form;
  append-only streams keep historical seven-segment rows under their
  own tag; new dims insert before the reserved sd tail, so sides
  never re-keys and future dims need no further version bump).
  Module docstring face table gains the obstacle row.
- `v_anchor()` — UNTOUCHED. No obstacle dim, no weight (W_OBSTACLES
  deliberately does not exist: attribution is not progress).
- RE-KEY DISCLOSURE: adding ob= changes every signature string/hash —
  safe because the kernel is runtime-inert (issue 462 section audit:
  zero runtime observe consumers); landing the key BEFORE the wiring
  is the correct order. 462's tests compute hashes through the face,
  never literals (verified on the 462 branch).
- DRIFT DISCLOSURE (review defect 4): ob= is cumulative — every
  recorded failure advances the signature. The q-cell fold joins
  under each row's RECORDED hash, so banking is unaffected; a
  compose-time cell_count read at the CURRENT signature on a
  failure-rich session may see zero dispatch rows (the dispatch-time
  signatures are older ob= states). That drift is the Phase-2 feed
  material (cause-bearing state evolution), disclosed to the 462
  owner here and in the PR; the ordering dependency (this change
  should reach dev before or with 462's wiring merge) is a sequencing
  note in the PR, not a mechanical gate.

### Worker protocol (agents/kunglao-worker.md)

New subsection under "Failure report protocol": the intervention
protocol — isolate → artifact (runs/probes/<slug>.txt carrying
command + exit code + verbatim bytes — the probe-marker shape the
record face validates) → helper record → cite OBS id in the failure
block. Evidence-first (REFLECT grounding: intervention beats verbal
reflection — the artifact is an experiment result). Relationships to
the existing failure surfaces: the `## failure` block cites the OBS
id under what_I_tried; ONE probe artifact may serve both the obstacle
row's evidence_path and a blocker's probe_evidence when the same
experiment backs an ESCALATE; failure_analysis_gate is untouched in
Phase 1 (no gate reads OBS rows). agents/*.md hygiene: no tracker
tokens, no dates. A doc-shape test pins the protocol section.

### Trap experiment (experiments/ex4_attribution_trap.py)

Declared-synthetic five-step scenario, replayed through the REAL
obstacles.record + state.signature faces on a temp workspace, over
REGISTERED family tokens (the #432 production Q-key vocabulary — the
training shape must be keyed on vocabulary that can occur in
production; review defect 2 fix):

| step | act (method_family — registered) | outcome    | obstacle kind        |
|------|----------------------------------|------------|----------------------|
| 1    | dynamic-trace (frida)            | detected   | detection_trigger    |
| 2    | replay-harness-verification (unidbg) | env error | missing_env_entry   |
| 3    | static-decompile (jadx)          | tool limit | tool_limit           |
| 4    | obfuscation-peeling (config)     | encrypted  | encryption_layer     |
| 5    | crypto-core-identification (decryptor) | success | (none — breakthrough)|

Outputs experiments/ex4-results.json: the four (kind, family) rows,
per-step signature strings, and the manifest of synthetic probe
artifacts. Deterministic (fixed ts per step). Naming disclosure: this
is the issue's "E2 data-production" experiment; the repo experiment
sequence EX-2/EX-3 is taken, so it ships as EX-4 (an unrelated "EX-4"
string appears once in a test_workguard_434.py docstring as a plan
label — no collision in the experiments/ registry).

## Key decisions

1. **runs/obstacles/ per-obstacle files, not evidence/ and not JSONL**
   — review CRITICAL fix (index-sweep inversion, above); per-file
   also matches the kernel-registry tree and keeps each artifact
   independently citable/inspectable.
2. **No write gate** — unlike blockers (inherited premises), obstacle
   rows feed a learner; wrong rows are training noise the Phase-2
   posterior outvotes, not a poisoned premise. Validation at the
   producer boundary only (structure + artifact existence + probe
   shape).
3. **Obstacle kinds, not free-text, in the signature** — the signature
   is a discretized key (issue 386); the kind multiset is the
   discriminable, bounded vocabulary. cause/evidence_path detail rides
   the registry rows for the Phase-2 fold, not the key.
4. **Recording-only posture** — the freeze test gains a
   full-module-string wall (decision faces never import
   rlvr.obstacles under any import form; the top-level-name-only
   check would miss `from rlvr import obstacles` — review defect 5
   fix, mirroring the settlement-rules direction's existing surgery).
5. **Export map + registration** — rlvr/__init__ gains the obstacles
   faces (module + docstring bullet); scripts/rlvr/README.md package
   tree + face map + scope; scripts/README.md row; deploy-manifest
   re-mint (deploy_manifest.py --write — the scaffold set is the
   AST import-closure, so the lazy state.py import registers the new
   module automatically); tests/_tiers.py fast registration.

## Risks / trade-offs

- Signature re-key + schema tag bump (disclosed above) — safe
  pre-wiring; would be a breaking change post-462.
- Worker adoption is voluntary (no gate) — by design; under-production
  is the Phase-2 attribution-dispatch problem, not a Phase-1 defect.
- kind=other as an escape hatch — bounded enum keeps keys finite;
   mis-bucketed rows are a data-quality concern the posterior treats
   as noise.
- Hand-edited rows / cleaned probe artifacts — integrity posture
   disclosed above (structural read validation only).

## Test plan (spec → tests)

- tests/test_rlvr_obstacles_461.py — Req 1 scenarios: minimal mint,
  unknown kind, missing artifact, no-probe-marker artifact,
  traversal/absolute, empty/multiline/over-long cause, tolerant read,
  concurrent-mint semantics (exclusive create); Req 3 scenario 1: the
  three canonical failure-signature fixtures with expected rows;
  Req 3 scenario 2: CLI/library equivalence (one validation path);
  Req 3 scenario 3: worker-contract doc-shape pin.
- tests/test_state_signature_396.py — re-pin the two byte pins to the
  state-sig/2 ob= format; new obstacle-face/signature cases (Req 2:
  bare workspace, canonical pattern, different-causes-different-hashes,
  V untouched, corrupt-row tolerance).
- tests/test_experience_freeze_396.py — full-module-string recording
  wall over the obstacle module (Req 2 recording-only clause).
- tests/test_ex4_attribution_trap_461.py — Req 4: expected sequence
  (registered tokens), signature evolution, determinism
  (byte-identical result document).
- RED-first: all of the above fail before implementation.

## Design review (adversarial, 2026-09-30)

Independent adversarial review (architect subagent, read-only) vs the
adjacent specs/contracts (provenance-gate, evidence-index,
write-guard, three-state charter, blocker lint, the 396 freeze, and
the in-flight 462 branch incl. strategy_store/q_cells).

Outcome: FAIL → fixed. 13 defects (1 CRITICAL, 1 HIGH, 6 MEDIUM, 5
LOW), all addressed in this design/spec revision:

1. CRITICAL evidence-index inversion → registry relocated to
   runs/obstacles/ (above).
2. HIGH EX-4 families outside the closed registry → re-keyed to the
   five registered tokens; producer posture clarified (records
   verbatim, registry gate stays the enforcement face).
3. MEDIUM obstacle-claim vocabulary collision → explicit
   disambiguation (not a claim, never licenses death; a claim may
   cite OBS rows later).
4. MEDIUM undisclosed 462 compose drift → DRIFT DISCLOSURE section +
   PR sequencing note.
5. MEDIUM freeze-wall mechanics → full-module-string test design.
6. MEDIUM failure-surface overlap → relationships defined (failure
   block cites OBS; one artifact may serve blocker probe_evidence;
   failure_analysis untouched).
7. MEDIUM nominal probe lineage → PROBE_MARKERS artifact-shape check
   at record time (+ spec scenario).
8. MEDIUM weak Req-3 anchors → doc-shape pin added, single-producer
   claim weakened to sanctioned-producer.
9. LOW mint TOCTOU/rollover → O_EXCL mint + parsed-n sort.
10. LOW fabricated/stale rows → integrity posture disclosed
    (structural read validation only).
11. LOW schema-tag staleness → state-sig/2 bump + reserved-tail
    convention.
12. LOW cause bound drift → 200-char bound in spec + scenario.
13. LOW mandatory-checklist pressure → "ONE probe" count dropped;
    no-gate clause retained.

Verified clean by the same review: boundary axis (no verdict fields,
no gates, no claim/settlement consumer, no Phase-1 termination
semantics — OBS citations cannot license a Type E death declaration);
re-key cannot break 462's pinned acceptance (no literal
signatures/hashes on the 462 branch; the fold joins recorded hashes);
file boundary vs 462 respected; the state_signature shim covers the
changed faces; ob= collides with no existing segment; experiments/
filename free.
