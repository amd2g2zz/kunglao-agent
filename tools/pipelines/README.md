# tools/pipelines — evidence-index tool home

This directory is the `pipelines` category's tool home, containing the
registered tool `build_evidence_index.py` (`build-evidence-index`): the
evidence index builder that scans a workspace's `evidence/` +
`analysis_artifacts/` and writes `evidence/_index.json` + `_INDEX.md`
(eid/path/sha256/source_reliability).

## Relation to the index docs

A worker reads `tools/_index-pipelines.md` first (the pipelines-domain tool
contract entry `### build-evidence-index`); this README explains the
directory itself. The machine contract is `tools/_INDEX.yaml` — the tool is
registered there under the `pipelines` category.

## Disposition record

- #352: the 5 plan-generation templates formerly homed here were deleted
  (audit: zero runtime consumers — read only by tests and an unreachable
  CLI surface). Plan orchestration has no in-tree templates; future plan
  work starts from the registered tool set in `tools/_INDEX.yaml`.
- #340: category id `pipeline`→`pipelines`; tool scripts always live in
  their category directory (hence `build_evidence_index.py` is homed here).

## Constraints

- The `pipelines` category holds registered tools only — no unregistered
  executor code, no new state format created.
