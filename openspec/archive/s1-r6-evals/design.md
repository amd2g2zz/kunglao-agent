# Design — evals/evals.json skill-creator evals (#117)

## Schema Reference

The skill-creator manual defines `evals/evals.json` (see
`skill-creator/references/schemas.md`) with this structure:

```json
{
  "skill_name": "...",
  "evals": [
    {
      "id": 1,
      "prompt": "...",
      "expected_output": "...",
      "files": ["..."],
      "expectations": ["..."]
    }
  ]
}
```

## Eval Design

### Eval 1: Convergence loop dispatch (id=1)

**Prompt**: Run convergence check on a workspace with one OPEN claim (C-001) that has
evidence_tier_attempted=0 and no blockers. The claim-register.yaml lists C-001 with
status OPEN and boundary_type positive_observation. priority.py should rank it as the
top action.

**Expected output**: The orchestrator dispatches a worker for C-001 before the round ends,
following priority.py ordering. No idle loop; convergence_check returns DISPATCH (exit 1).

**Expectations**:
- The convergence check reads claim-register.yaml and identifies C-001 as OPEN
- The orchestrator dispatches a worker agent for C-001 (priority.py first result)
- No claims remain OPEN without dispatch in the same round
- The transcript includes a dispatch event for C-001

### Eval 2: Maker-checker verification (id=2)

**Prompt**: A kunglao-worker agent has produced `facts/F050.md` with a conclusion and
anchors for claim C-050. Run blind verification: the verifier (a different agent or
script) must independently reproduce the evidence and compare, without reading F050's
conclusion text, then mark the claim as PROVEN only on exact match.

**Expected output**: The verifier runs the reproduction commands from the anchors,
compares the actual output to the expected values, and issues a passes verdict. The
worker's self-declared PROVEN status is NOT accepted without independent verification.

**Expectations**:
- The verifier is a different agent/context than the worker that produced F050
- The verifier reads only the anchors (commands + expected) from F050, not the conclusion
- The verifier independently executes the anchor commands and compares output
- The claim transitions to PROVEN only after the verifier's independent passes result
- No self-stamping: the worker's own verification does not promote the claim

### Eval 3: Verdict correctness/completeness -- B4-2 decoupled (id=3)

**Prompt**: Given a converged workspace where all claims are PROVEN and the
task_spec asks for maliciousness and attribution, run the verdict scorer. The B4-2
contract requires maliciousness and attribution to be DECOUPLED: maliciousness is a
6-dimension score producing classification, and attribution uses Admiralty+ACH+Diamond.
The task_spec specifies `pq_coverage: true` and `maliciousness: true` and
`attribution: false` (attribution explicitly disabled).

**Expected output**: The verdict-scorer produces a verdict.json with a
`maliciousness` section containing a 6-dimension classification score, and a
`pq_coverage` summary. No attribution section is present (disabled by task_spec).

**Expectations**:
- Verdict output contains a `maliciousness` object with dimension scores
- Verdict output contains a `pq_coverage` summary
- Verdict output does NOT contain an `attribution` section
- The classification field in maliciousness is one of: clean, benign, suspicious, malicious
- All evidence files used are listed in the verdict's evidence_manifest

## Test Design

`tests/test_evals_schema.py` performs mechanical validation:
1. File exists at `evals/evals.json`
2. Valid JSON parse
3. Top-level `skill_name` is "kunglao-agent"
4. `evals` array has >= 3 entries
5. Each eval has required keys: id (int), prompt (str), expected_output (str),
   expectations (list of str, len >= 1)
6. `files` key is optional but when present must be a list of strings

No behavioral testing -- the schema guard ensures structural compliance with
the skill-creator contract. Behavioral coverage is provided by the existing
`tests/test_eval_harness.py` and `eval/fixtures/`.
