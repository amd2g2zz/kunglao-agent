# issue-733-arming-shape-law — ONE shape law for oracle-case `expected`

## Why

The arming gate (`settle_round_credit._arming_field_present`, the #678
T5 fields) and the runner's loader (`oracle_runner._parse_expected`)
disagreed on the `expected` shape: the gate accepted a MAPPING with
`evidence_refs`, the loader accepts a non-empty LIST of
`{field, value, evidence_refs}` entries. The shapes are mutually
exclusive, so **no case doc could be both armed and runner-loadable** —
proved against the live workspace, where all four armed docs are in the
non-loadable class (`load_cases` refuses the set) while the posterior
legs happily observed them.

Two definitions of "a real case" is the drift: the runner is the
executor and owns the contract, so its shape is the law, and every other
consumer must read it rather than re-derive a rival.

## What Changes

1. **ONE shape law** — `oracle_runner.expected_shape_error(raw)`
   returns the first shape fault or None: a non-empty list of mappings,
   each with a non-empty string `field` and a `value`, where every entry
   is either an explicit `pending-observation` or anchors its
   expectation with at least one `evidence_refs` entry. `_parse_expected`
   delegates its shape half to it (messages verbatim, wrapped with the
   same path/cid prefix) and keeps the #126 workspace-resolution half.
2. **The arming gate delegates** — `_arming_field_present`'s
   `expected` branch is the same predicate. Consequence, intended: the
   old mapping shape is no longer armed. A doc is armed iff it is
   runner-shape-complete.
3. **Fixtures migrate** — the synthetic armed-case fixtures in
   `test_reward_source_678`, `test_rl_output_path_691` and
   `test_late_arm_oracle_730` now write the canonical shape.

## Non-goals

- **Re-authoring the live workspace's four case docs** — that is a data
  migration requiring per-case domain judgement (which stage field/value
  each hypothesis predicts, or an explicit `pending-observation`
  marker). The repo-side law lands first; the data migration follows it
  and is flagged in the issue.
- **Full loadability parity for the arming gate** — the gate checks
  SHAPE only. The loader additionally resolves evidence refs against the
  workspace (#126) and cross-lints hypotheses (#126 amendment); those
  remain the loader's job.
- **The #108/#126 refusal semantics** — unchanged; only their shape
  half moved into the shared predicate.

## Historical note

An earlier design (and #730's spec) justified the arming gate with
"arming means the runner can load it and run its mutations" — that
sentence was false under the shape mismatch and is hereby superseded:
arming now means runner-SHAPE-completeness, and this delta states the
limit honestly.
