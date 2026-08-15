## Context

kunglao-agent is a convergence-driven RE orchestrator that verifies reverse engineering analysis correctness and completeness against `task_spec.primary_questions`. The current `agents/verdict-scorer.md` was inherited from a separate mal-recon project and implements Stage 6 maliciousness scoring (6-dim -> classification) and threat attribution (Admiralty+ACH+Diamond -> named actor). Both capabilities are out of scope -- kunglao-agent does NOT do threat classification, attribution, or CTI.

The verdict-scorer must be rewritten as a pure PQ-coverage verifier that answers: "Did the analysis answer every primary_question with sufficient evidence?"

## Goals / Non-Goals

**Goals:**
- Replace the entire verdict-scorer spec with a PQ-coverage verifier
- Output `evidence/verdict.json` with the v11 `analysis_verdict` schema
- Enforce confidence band requirements (never more lenient than convergence C0a/C0b)
- Detect contradictions via read-only consumption of `fact_contradiction_gate.py` output
- Preserve the `degraded[]` self-honesty convention (fail-closed per #78)
- Preserve `self_audit` block
- Keep frontmatter `allowedTools`/`disallowedTools` unchanged
- Add contract tests that verify the new schema and absence of banned terms

**Non-Goals:**
- Do NOT touch `agents/verdict-redteam.md` (separate issue #107)
- Do NOT touch SKILL.md module inventory (separate issue #108/109)
- Do NOT touch DESIGN.md or task_spec.yaml (separate issue #109)
- Do NOT add a JSON schema file under `schemas/` -- the schema lives in the agent markdown
- Do NOT implement contradiction detection logic (reuse `fact_contradiction_gate.py`)

## Decisions

### D1: Keep frontmatter tool list unchanged
**Decision**: The `allowedTools` (Read, Grep, Write, sequential-thinking) and `disallowedTools` (Edit, NotebookEdit, Bash, WebFetch, WebSearch) remain identical.
**Rationale**: The tools are appropriate for the new PQ-coverage role -- reading task_spec, claim-register, facts, contradiction output, and writing verdict.json. No new tools are needed.

### D2: Input files change from evidence/*.json to task_spec + claim-register + facts
**Decision**: Replace the old evidence-file inputs (cti-vt.json, cti-correlated.json, die.json, floss-filtered.json, static-ghidra.json, etc.) with task_spec.yaml, claim-register.yaml, and facts/*.md.
**Rationale**: The new role reads structural analysis artifacts, not raw evidence files. This aligns with convergence_check.py patterns already in the codebase.

### D3: Contradiction detection is delegated, not reimplemented
**Decision**: The verdict-scorer reads the output of `fact_contradiction_gate.py` rather than reimplementing contradiction detection.
**Rationale**: DRY -- the gate already exists and is maintained separately. The verdict-scorer is a read-only consumer.

### D4: schema_version format uses date-vNN pattern
**Decision**: `2026-08-12-v11` as the schema_version.
**Rationale**: Follows the existing pattern (v10 was `2026-07-29-v10`). The version jump from v10 to v11 signals the breaking schema change.

### D5: No JSON schema file under schemas/
**Decision**: The JSON schema lives only in the agent markdown specification.
**Rationale**: Per issue scope -- adding a separate schema file is not required unless an existing test depends on it.

## Risks / Trade-offs

- **Downstream schema break**: Any code consuming `evidence/verdict.json` expecting the old classification/attribution keys will break. This is intentional and documented in the provenance note.
- **confidence_band field may not exist in all workspaces**: The verdict-scorer must handle missing confidence_band gracefully (treat as degraded, not as failure to find the fact).
- **fact_contradiction_gate.py output format is assumed stable**: If the gate's output format changes, the verdict-scorer's parsing may break. Mitigation: the spec instructs the agent to read the gate's text output, not parse a specific machine format.
