# eval — #299 evaluation dataset (constructed targets, held out)

This tree holds the system's capability-measurement dataset: tasks with
**verifiable ground truth**, distinct from unit tests (which verify code
correctness). The per-task pattern is the battle autoresearch.sh face: a
run emits `METRIC <name>=<value>` lines, the verdict is arithmetic-level
evidence, evidence is auto-archived, failures emit structured signals.

## Layout (versioned)

```
eval/
  README.md            this file — the discipline contract
  v1/
    VERSION            "eval-v1" (single version token)
    CHANGELOG.md       per-version changelog
    tasks/
      smoke/           the smoke tier (3-5 constructed targets, minutes-scale)
        <task-id>/
          task.yaml          the task unit (schemas/eval-task-v1.json)
          target/            the constructed target artifact
          ground_truth.json  construction-known manifest + captured pairs
          checker.py         standalone mechanical-checker shim
      release/         the #332 native ladder (eval-v1.1, 12 units:
                       arm-native-kdf / win-pe-kdf / smc-x86 /
                       mod-crypto-native at rungs L0/L1/L2 (+L2p UPX);
                       real arm64/PE/x86_64 artifacts + reference.py
                       self-check candidate; mod-crypto core lives in
                       scripts/eval_crypto.py)
```

Versioning: an eval set is **versioned** (`eval-v1`); churn (new variants,
tier growth) mints a new version dir + changelog entry — never a silent
in-place mutation of a version already used for a claim.

## Held-out discipline (contamination)

**Eval tasks NEVER enter the #298 distillation corpus.** The path contract
is pinned in `scripts/eval_dataset.py`:

- `EVAL_CORPUS_PREFIXES = ("eval/",)` — every prefix is off-limits as a
  distiller source;
- `filter_distiller_sources(paths)` is the only sanctioned source-list
  builder for a distiller: it drops eval-corpus paths before anything
  downstream can see them. The distiller does not exist yet; the contract
  is documented and tested on the constants (see
  `tests/test_eval_dataset_299.py`) so the consumer lane inherits the
  guard, not a loophole.

Every landed task unit also self-declares its contamination block:
`held_out: true`, `distiller_excluded: true`, `provenance: constructed`.

## Task sources — three, contamination-aware

| source | status in this lane | ground truth |
|---|---|---|
| constructed | **THIS LANE** — fresh parametric variants of known mechanism families (`scripts/eval_targets.py`), constants mutated per seed: memorization useless | by construction |
| historical replay | #294 lane — not this lane | replay evidence |
| public corpus | NOT this lane (provenance-marked, prefer held-out) | provenance |

## Tiers

| tier | shape | cadence |
|---|---|---|
| smoke | 3-5 constructed targets, minutes-scale | runnable per release train |
| release | #332 native ladder: real arm64/PE/x86_64 artifacts, rungs L0/L1/L2 (+L2p UPX), minutes-scale | runnable per release train |
| (later) | historical replay | #294 |
| (later) | public corpus held-out | later lane |

## Baselines on the same set

- **bare-LLM** (#236): the arm wiring is #236's lane; this lane provides
  the task set + the execution surface — `checker.py` per task unit, or
  `eval_smoke_runner.py --arm bare-llm --candidate-for task=path`.
- **1/k guessing**: emitted arithmetically as `guess_pass_p = 2^-space_bits`
  (`--baselines`).
- **historical self**: the #294 replay lane, not this lane.

## Checker contract (every task)

- METRIC emission: `ttc_seconds`, `dispatch_count`,
  `pass_at_k_contribution`, `converged`;
- arithmetic verdict (threshold ceil-math — the #301 C2 pair-match shape);
- evidence auto-archive (`kunglao-eval-evidence/1` JSON under the run
  out-dir);
- structured failure signals (`FAILURE code=<enum> detail=...`).

Results rows are shaped for the #295 evidence bar
(`kunglao-eval-results/1`): a config-change PR attaches them as replay/eval
evidence.

## Privacy

No real workspace/target data lives in this tree: every target is a
seeded construction (`scripts/eval_targets.py`), and each task unit
carries its seed so it can be re-minted byte-identically.
