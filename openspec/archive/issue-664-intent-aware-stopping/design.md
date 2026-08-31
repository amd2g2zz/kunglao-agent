# Design — intent-aware strategic stopping (#664)

## D1. Where the check lives and when it fires

Inside `scripts/completion_gate.py::judge()`, AFTER the exit-1
unresolved-items check and BEFORE exit-0 PASS. Precedence becomes
`3 > 2 > 1 > 4 > 0`:

- exit 3 (no anchor) / exit 2 (unsigned defer) / exit 1 (items remain)
  all keep priority — they are strictly more actionable.
- exit 4 (intent unmatched) fires exactly when the oracle would otherwise
  PASS: items closed, defers signed — the moment "done" is declared. That
  is the only moment the intent question matters, and firing there cannot
  mask an item-level defect.

## D2. Anchor extraction — reuse #54 F1, do not reinvent

`premature_termination_detect._extract_anchors(task_text)` is the
canonical task-anchor extractor (CJK runs ≥3, ASCII tokens ≥5, minus the
ANCHOR_STOPLIST). Coverage text = "\n".join of every PQ id and question
text from `task_spec.yaml` (any parse shape `_parse_primary_questions`
accepts — reuse convergence_check's canonical parser for schema parity,
same-package import precedent established by #662's seeder).

Unmatched anchor: an anchor whose lowercased form appears nowhere in the
lowercased coverage text. ≥1 unmatched anchor → exit 4 with the anchors
named in the reason.

Empty anchor set (e.g., task_text is all stoplist/noise) → check skipped
(there is nothing user-salient to match).

## D3. Workspace access via oracle.workspace_path (#147 precedent)

`judge()` is "oracle-pure" by design, EXCEPT the #147 global-contradiction
recompute which reads `oracle["workspace_path"]` → `facts/`. The intent
check follows the identical pattern: `oracle["workspace_path"]` →
`task_spec.yaml`. This keeps judge's dependency surface explicit (the
oracle names its workspace) rather than smuggling a workspace argument
through the shim.

## D4. Fail-open layers (all skip the check, never block)

- oracle lacks `workspace_path` → skip (pre-#147 oracles)
- workspace lacks `task_spec.yaml` → skip
- task_spec malformed / no primary_questions → skip (convergence's INVALID
  and PQ gates own that layer — #77)
- task_text yields zero anchors → skip
- anchor-module import failure → skip (mirrors the #54-folding guard
  already in judge)

Fail-open rationale: the intent check is a delivery-completeness backstop,
not a correctness gate. Blocking on a missing PQ layer would fail every
legacy/pre-init workspace at Stop time — the worst possible posture.
False negatives (a skipped check) are recoverable by the reviewer; false
positives at scale are not.

## D5. Stop-shim propagation (no change needed)

`hooks/completion_gate.py::process_event` treats judge exit 0 as pass and
EVERY non-zero exit as block (the `if code == 0: return 0` /
`print(...decision block...); return code` pair). Exit 4 propagates
unchanged; the shim docstring's exit-code table gains the 4 row
(documentation contract, no logic).

## D6. CLI surface

`main()` verdict map gains `4: "INTENT_UNMATCHED"` (JSON `verdict` field)
alongside PASS / INCOMPLETE / UNSIGNED_DEFER / NO_ANCHOR.

## D7. Test strategy (RED-first)

- RED1: anchor in task_text absent from PQ text, items all closed → (4,
  INTENT_UNMATCHED), anchors named in reason
- RED2: anchors covered by PQ text → verdict unchanged (PASS on clean oracle)
- RED3: no workspace_path → skipped (clean oracle still PASSes)
- RED4: no task_spec / malformed → skipped, no crash
- RED5: precedence — unresolved items + unmatched anchor → exit 1 (not 4)
- RED6: CLI JSON verdict label INTENT_UNMATCHED

## D8. Out of scope

- Semantic/NLU intent matching (anchor-substring is the mechanical floor;
  embedding-based coverage is a future issue if false negatives bite)
- verdict.json reconciliation (the check reads task_spec directly;
  wiring evidence/verdict.json into the comparison is follow-up scope)
- #634 park/idle states (loop cost — different layer)
