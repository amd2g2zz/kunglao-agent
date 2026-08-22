# Workspace manifest (#538)

Every carrier that `kunglao-init` MUST materialize for a fresh workspace,
with provenance (who writes, who reads). This table is the contract: init
scaffolds every row eagerly (no lazy ambiguity — "absent" must never mean
"not yet decided"), and `.workspace-manifest.json` (written at the end of
scaffold) is the disk-side snapshot `kunglao-resume` (#466) diffs against
("init had N carriers; missing now: {list}").

Code anchors: `scripts/kunglao-init.py` (`SCAFFOLD_DIRS`, `CARRIER_READMES`,
`SCAFFOLD_FILES`), `tools/_lib/workspace_manifest.py` (writer/reader),
`tools/_lib/index_schema.py` (the single `_INDEX` parser).
Test anchor: `tests/test_workspace_carriers_538.py`.

## Carrier table

| Path | Zone | Writer | Reader | Notes |
|---|---|---|---|---|
| `facts/` | contract | init, workers | `update_index.py`, `fact_contradiction_gate.py`, gates | `F<NNN>-<slug>.md` fact files |
| `notes/` | contract | verifier notes (agent prompt) | `convergence_check.py` note layer, `lint-notes.py` | results layer — 可改正的分析结果层 (#528 corrected semantics); hypotheses do NOT live here |
| `analyses/` | contract | agent prompt | agent prompt, `priority_ratio.py` | longer-form analysis (`failure-*.yaml` per #496) |
| `evidence/` | contract | agent prompt | agent prompt, `build_evidence_index.py`, export | raw binary evidence (pcap, captures, scripts) |
| `blockers/` | contract | `convergence_check.py`, init | resume brief, `kunglao-status` | blocker-*.md files |
| `runs/` | contract | init, every command | `kunglao-resume.py`, `kunglao-status.py` | worker status, plans, digests |
| `runs/logs/` | contract | init, `kunglao_log.py` | `kunglao_log.tail`, `event_taxonomy.py` | daily `kunglao-<date>.jsonl` event stream (#538 C-3: no longer lazy) |
| `hypotheses/` | contract | init, `hypothesis_store.py` (#528) | `digest_build.py` sec_g (cold-start digest), `state_anchor.py` hyps segment | hypothesis layer `H-*.md`: open → refuted/superseded state machine (refuted needs `refuting_fact_id`, superseded needs `superseded_by`); writer landed with #528 |
| `claim-register.yaml` | contract | init, `kunglao-record.py` | `worker_budget.py`, `digest_build.py`, gates | register of record |
| `facts/_INDEX.md` | contract | init (empty header), `update_index.py` | shared parser (`tools/_lib/index_schema.py`) | single 4-column schema (W-5) |
| `scratch/` | free-zone | agent prompt | agent prompt, export tool (zones it separately) | non-contract artifacts (12-field scripts, FINDINGS.md) — init does not diff it |
| `.workspace-manifest.json` | contract | init (scaffold end) | `kunglao-resume` (#466) diff | carrier snapshot (schema_rev v1) |

Not carriers (explicitly OUT of the scaffold, per #530):

- `failure-registry.yaml` — template deleted in #530 (zero writers ever existed).
- `progress.txt` — human-only narrative log; not scaffold state (downgraded in #530).
- `task_spec_snapshot.yaml` — the forever-3B stub was deleted in #538 (C-4);
  intake writes a real snapshot or the file does not exist; resume handles
  both cases.

## Stubs each carrier ships with (self-describing)

Every agent-facing carrier ships a README stub so an agent landing cold
knows what the directory is for ("本文件由 init 创建; X 落于此当…"):

- `notes/README.md` — results layer; corrections keep a `supersedes:` chain
  (#528); hypotheses go to `hypotheses/`, not here.
- `analyses/README.md` — longer-form analysis; failure records for #496.
- `evidence/README.md` — raw evidence only; indexed by
  `build_evidence_index.py` (eids assigned in path order).
- `hypotheses/README.md` — hypothesis layer (#528): `H-*.md` with the
  open → refuted/superseded state machine; writer `hypothesis_store.py`.
- `scratch/README.md` — the free-zone declaration (below).
- `facts/_INDEX.md` — header-only empty index (single schema, W-5).

## free-zone: `scratch/` (C-5)

`scratch/` is deliberately OUTSIDE the carrier contract:

- Agents may write anything here without ceremony (exploration scripts,
  one-off findings dumps like FINDINGS.md).
- init does not diff it and never deletes from it.
- The export tool (拆分 F) bundles it under its own zone, separate from
  contract carriers.
- Nothing under `scratch/` may be load-bearing for gates or convergence —
  if a script becomes load-bearing it must graduate to a contract carrier
  (usually `analyses/` or `evidence/`).

## _INDEX single schema (W-5)

One format, one parser (`tools/_lib/index_schema.py`), used by BOTH
`scripts/update_index.py` and `scripts/digest_build.py`:

```
F<id> | <status> | <claim_id> | <one-line conclusion>
```

- status ∈ the fact-status set (`references/schema.md`):
  `PROVEN | INFERRED | NEGATIVE | REFUTED | OPEN | DEFERRED | VERIFIED`
- Any other value in the status column is rejected on parse AND on write
  (upsert refuses; the file is never created from a malformed row).
- See `tools/_lib/index_schema.py` for the full validation set.
