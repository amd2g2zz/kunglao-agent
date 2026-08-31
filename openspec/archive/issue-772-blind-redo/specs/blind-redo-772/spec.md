# blind-redo-772 delta specification

## ADDED Requirements

### Requirement: redo prompts carry GAP shapes, never the verifier's derived answer

The orchestrator MUST blind the re-dispatch channel symmetrically to the
verifier BLIND slice: a redo prompt MUST carry only WHERE the prior attempt
diverged (field mismatch / challenged assumption / alternative method
direction) and MUST NOT carry the red team's derived values, anchors, or
conclusion lines. The REDO slice (`build_redo_context`) is the mechanical
filter face for this requirement.

#### Scenario: REDO slice strips derived values

- GIVEN a red-team DIFF file `runs/verify-redteam-C-005.md` containing
  "producer claimed anchor 3494" and "actual anchor 3446"
- WHEN `build_redo_context(ws, diff)` produces its slice
- THEN the serialized slice contains neither "3446" nor "3494"
- AND it contains the divergence shape (divergence_class + field pointer)

#### Scenario: independent derivation body withheld

- GIVEN the DIFF carries a "My independent derivation" section and machine_check
  fences with expected/actual literals
- WHEN the REDO slice is built
- THEN the derivation section body and fence contents are absent from the slice
- AND withheld sections are marked as deliberately cut, not silently lost

#### Scenario: claim/fact references survive scrubbing

- GIVEN gap text cites C-007 and F018 bookkeeping ids alongside magnitudes
- WHEN the slice is built
- THEN the id references remain intact
- AND all >=3-digit magnitudes and 0x/hex tokens are redacted

#### Scenario: missing DIFF fails open

- GIVEN a workspace without the referenced DIFF file
- WHEN build_redo_context is called
- THEN an honest error-marked empty slice is returned and nothing raises

### Requirement: the maker-checker contract states the redo direction in three places

The skill contract layer MUST state the redo-blindness rule at all three faces:
SKILL.md §1b guardrails, agents/kunglao-worker.md redo semantics, and
agents/kunglao-redteam.md output readership — each pinned by a text assertion.

#### Scenario: SKILL.md guardrails clause

- GIVEN `skills/kunglao-agent/SKILL.md` §1b compact text
- WHEN read
- THEN it states verifiers must be BLIND and re-dispatches must be GAP-ONLY,
  carrying WHERE it diverged but never the verifier's derived answer
- AND the body introduces no bare issue-number refs

#### Scenario: worker contract anti-cheat rule

- GIVEN `agents/kunglao-worker.md`
- WHEN read
- THEN it states 你收到的是 GAP 不是答案 with the独立重推 requirement
- AND it declares matching a DIFF-seen value without independent derivation
  to be a FAIL, not a pass

#### Scenario: redteam output readership note

- GIVEN `agents/kunglao-redteam.md` output-format section
- WHEN read
- THEN it names the orchestrator adjudication layer as the DIFF reader
- AND it requires full conclusion lines because leak protection lives in the
  dispatch_context REDO slice, not in the red-team writer

### Requirement: leaking value strings into a redo prompt draws a WARN

hooks/dispatch_gate.py MUST warn when a redo-marked dispatch prompt overlaps
the latest verify-redteam DIFF on >=4-digit numbers or >=16-char hex strings,
and MUST keep exit code 0: heuristic false positives are too costly for REJECT,
so the orchestrator self-checks via build_redo_context instead.

#### Scenario: overlap trips WARN with rc=0

- GIVEN a dispatch prompt marked redo/重做 that contains a >=4-digit number or
  >=16-char hex string also present in the latest `runs/verify-redteam-*.md`
- WHEN hooks/dispatch_gate.py processes the Agent payload
- THEN stderr and hookSpecificOutput carry a redo-leak WARN naming the overlap
- AND the exit code stays 0 (WARN never REJECT — heuristic false positives)

#### Scenario: clean GAP-only prompt stays silent

- GIVEN a redo-marked prompt built from GAP shapes only
- WHEN the gate runs
- THEN no redo-leak warning is emitted

#### Scenario: fail-open without DIFF evidence

- GIVEN no workspace or no verify-redteam files on disk
- WHEN the gate runs a redo-marked prompt
- THEN the face sleeps silently and dispatch proceeds
