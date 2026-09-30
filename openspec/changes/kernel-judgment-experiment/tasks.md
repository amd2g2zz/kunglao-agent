# Tasks — kernel-judgment-experiment (EX-7)

## 1. Pre-registration (gate: BEFORE any experiment run)

- [x] 1.1 openspec change `kernel-judgment-experiment`: proposal +
      design (world model, arms, metrics, stopping rule, honesty
      argument, discriminators D1–D4) + this task list
- [x] 1.2 `openspec validate kernel-judgment-experiment --strict`
      exits 0
- [x] 1.3 Independent DESIGN REVIEW (subagent, before code): adjudicate
      metrics, the synthetic outcome model's honesty (no answer leakage
      into policy inputs), the stopping rule, and the pre-registered
      discriminators; record verdict + fixes in the change dir
      (design-review.md; NEEDS-CHANGES → 4 required amendments applied
      pre-run, re-validated)

## 2. Harness (after the design gate)

- [x] 2.1 `experiments/ex7_kernel_judgment.py`: real-kernel imports,
      world construction (3 regimes), 4 arms, paired env RNG, metrics,
      sign tests, discriminator evaluation, real-data replay block,
      results writer
- [x] 2.2 `tests/test_ex7_kernel_judgment.py`: determinism, env
      pairing, micro-run, schema shape pins
- [x] 2.3 ruff clean on touched files; `pytest -q -n 2
      tests/test_ex7_kernel_judgment.py` green (7 passed incl. the
      learning-sensitivity pin; local parallelism at -n 2 per the
      standing E2E-contended ruling)

## 3. The run (once; no re-tuning)

- [x] 3.1 Execute the full grid (3 regimes × 4 arms × 200 seeds ×
      100 acts/class) + the mined-table replay; commit
      `experiments/ex7-results.json` byte-identical to the run.
      DEVIATION (per Decision 9, shipped in the report): run 1 fired
      D1; the trace audit found the defect in the HARNESS (InMemoryStore
      copies its constructor iterable — appends never reached the fold;
      kernel sampled cold the whole run); harness fixed + learning pin
      added + full restart from scratch; run 2 is the committed result
      (byte-identity re-verified by a full rerun)
- [x] 3.2 Apply the pre-registered discriminators to the numbers;
      write `experiments/ex7-kernel-judgment.md` with the verdict
      table; losses stated first (D4 healthy headline + D2 drag
      co-fire; D1/D3/D3′ negative; replay floor NO_SEPARATION)

## 4. Gates + merge

- [ ] 4.1 `python devkit/quality_gates.py --quick` green
- [ ] 4.2 Review gate: independent reviewer PASS on the exact staged
      diff; mint `.review-gate` token; commit (attribution line per
      house convention)
- [ ] 4.3 PR to `dev` (experiment artifacts + this openspec change
      only; no production edits); CI five legs green; merge
