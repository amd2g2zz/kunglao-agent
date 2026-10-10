# design — issue-438-minor-tail

## Verified anchors (2026-09-30, branch fix/438-minor-tail off origin/dev fc9095ce)

| Question | Actual | Drift |
|---|---|---|
| question_claims reads strict UTF-8 | scripts/rlvr/scalar.py — read_text(encoding="utf-8") under except (OSError, yaml.YAMLError); UnicodeDecodeError escapes (reproduced RED: 0xff byte raises) | none |
| Module error idiom for the register read | missing / unparseable register -> set() with no warn (docstring: "degrades to an empty set"); fact_artifacts reads fact files with errors="replace" and skips OSError/YAMLError files via continue | none — clean-empty matches |
| stage_milestone consumers | repo-wide grep: the yaml declaration + test pins only (a behavior test that rides the answers_question leg, and the declaration pin itself) — ZERO code readers in scalar.py / scalar_settlement.py / reward_settlement.py | none — declaration-only confirmed |
| README row drift | scripts/README.md scalar_settlement.py row documents "credited artifacts (oracle-verified OR cited-by-deliverable OR oracle-backed refutations)" — the pre-433 formula; no cap mention | none |
| scalar_settlement.py identity | re-export shim; the settlement body lives at scripts/rlvr/scalar.py (issue 420 Phase 2) | none |

## Decision 1: clean-empty, not skip-and-warn (decode tolerance)

The tolerant-read face already defines the idiom: a missing or
unparseable register returns the empty set with no warn — the register
is not a settlement obligation; its absence merely disables the
claim-provenance citation channel and the deliverable face is
unaffected. A decode error is the same class of data problem (bad
bytes on disk, not a settlement anomaly), so it joins the same
degradation. A warn here would be a NEW telemetry surface inconsistent
with the sibling faces: fact_artifacts already tolerates undecodable
fact files silently (errors="replace") and skips unreadable ones with
continue. UnicodeDecodeError is added to the existing except tuple;
the docstring names the undecodable case.

## Decision 2: remove, not wire (stage_milestone leg)

Wiring the leg requires a machine-recorded stage-milestone signal; none
exists (no fact-frontmatter field, no oracle face names "milestone"),
and the settlement contract admits only machine-recorded signals — a
wired leg would mean inventing reward machinery inside a minor tail.
The ladder's own source comment documents the assumption that makes
the leg redundant: a milestone artifact is stage use by construction,
so it enters through the citation leg. With zero enforcement
consumers, the declaration over-promises: an unlinked milestone
actually settles the exploration-option trace while the table promises
full — under-credit only, but a contract that lies. Removal plus an
honest note sentence describing the mechanism is the fix; settlement
values are unchanged by construction (nothing read the leg), so the
rules version stays 3. The SAME honesty applies to the code-side and
test-side ladder descriptions: the FIRST-MATCH comment block at the
ladder head (scripts/rlvr/scalar.py) and the value-ladder docstring in
tests/test_round_credit_alignment_433.py both enumerated a
stage-milestone arm — after the yaml removal they would contradict the
table they describe, so both are reworded to state the mechanism (no
declared arm; milestones ride the cited/used-toward-stage arm;
unlinked milestones settle the exploration-option trace) instead of
listing a declared arm that no longer exists. (Design-review defect 1:
the change would otherwise leave its own authoritative ladder
description lying — the exact failure mode it exists to fix.)

## Decision 3: README row documents the enforced behavior

The rewritten LEVEL 2 fragment uses the contract's own vocabulary
(verified = admission ticket, cited-toward-stage = value condition,
the single citation chokepoint `_artifact_cited`), names the cap
constant and value (`CITED_CAP_DEFAULT = 2`), the deterministic
id-sort selection (no preference channel), the demotion reason
(`cited_over_cap`, one trace total per demotion class), and the
late-cite rescue path. A test pins the row's vocabulary so it cannot
drift again without going red (the repo had no docs-contract pin on
this row — the drift survived three semantic changes because nothing
checked it). The pin derives the cap VALUE from the module
(`CITED_CAP_DEFAULT = <ss.CITED_CAP_DEFAULT>`), so a constant change
(the declared yaml-promotion follow-up) forces the row to follow or
the pin goes red — name-only pinning would leave exactly the drift
hole this change kills (design-review defect 3).

## Design review (independent, pre-implementation)

Adversarial architect review of the three decisions against the actual
code returned FAIL with three defects, all folded in above: (1) the
code-side ladder comment and the 433 test docstring still enumerated
the stage-milestone arm as declared — reworded to the mechanism
sentence; (2) the spec's general no-declaration-only-legs SHALL was
unenforceable as stated — the requirement is scoped to the concrete
stage_milestone removal; (3) the README pin checked the cap constant
name but not its value — the pin now asserts the rendered module
value. All three decisions (clean-empty decode tolerance, remove-not-
wire, README pin placement in the cap's own test file) were confirmed
SOUND against the code by the same review.
