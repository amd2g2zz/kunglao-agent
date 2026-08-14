# Design — executable, evaluator-owned L2 red-team evaluation (#81)

## D1. Boundary: what "same dispatcher/tool-adapter boundary" means here

The product orchestrator loop is LLM-driven: read claims → `priority_ratio`
(real code) → dispatch worker subagents (Agent tool) → workers call tools
(Ghidra MCP / strings / grep) → facts → verify → claim transitions → repeat.
The Python core that is REAL and reusable: `priority_ratio.priority_ratio`,
`kunglao_verify.l2_redteam`, claim-status semantics (`status_defs`). The
dispatch/tool surfaces are the injectable boundary:

```
Episode loop (real, deterministic) ──> Dispatcher.dispatch(claim_id, task)
                                       (worker boundary; product = Agent tool)
                                            │
                                            v
                                     ToolAdapter.call(name, args)
                                       (tool boundary; product = MCP tools)
```

- `Dispatcher` protocol: `dispatch(claim_id, task) -> DispatchResult` —
  matches the `Callable[[str, Path], tuple[str, list[str]]]` shape already
  used by `l2_redteam(claim_id, ws, dispatcher)`.
- `ToolAdapter` protocol: `call(name, args) -> ToolResult`.
- `RecordedDispatcher` / `RecordedToolAdapter`: replay the fixture's recorded
  transcript deterministically; the transcript is part of the case digest.
  No real tools, no host execution, no network.

## D2. Episode loop

`run_episode(case, arm, fault, *, max_steps, token_budget, tool_budget,
rng_seed) -> EpisodeResult`:

1. Build a temp workspace (claim-register.yaml from case claims; facts/_INDEX
   from the evidence seed) — `tempfile.mkdtemp`, removed in `finally`.
2. Each step (bounded by max_steps):
   - Build `EvidenceView` from current facts; run the REAL
     `pr.priority_ratio(claims, deps, evidence)` when arm has mechanisms on;
     arm B uses a legacy additive-weight policy; arm C dispatches naively in
     claim order (single-agent, no orchestration).
   - Take the top action → `dispatcher.dispatch(claim_id, task)` →
     `tool_adapter.call(...)` per the recorded transcript.
   - Fault injection hooks run here (D3), mutating the adapter/dispatcher
     behavior for THIS episode.
   - Apply the outcome: evidence added or not, claim status transition via
     real status semantics; record the transition in `state_transitions`.
3. Stop on: converged (no dispatchable OPEN claims), budget exhausted, or
   max_steps. Return the episode result with full transcript + budgets.

Determinism: seeded RNG; no wall-clock inputs into policy; transcript is
replayed verbatim. `wall_ms` measured but excluded from the receipt digest.

## D3. Fault injection that alters the episode (not a label)

| fault | mechanism | measurable state transition | expected non-success |
|---|---|---|---|
| `throttle` | adapter budget → 0 (or `throttle_after=N`) | `budget_exhausted`; remaining claims stay OPEN; `explicit_incomplete` | INCONCLUSIVE (unresolved) unless overclaim/invalid work → FAIL |
| `implicit_fail` | adapter returns `ok=True` empty payload, no exception (`fail_after`-th call) | `implicit_fail_recognized` (anchored assessor) / `implicit_fail_misread_as_success` (naive → overclaim) | overclaim on empty evidence → FAIL |
| `explicit_fail` | adapter raises `ToolError` (`fail_after`-th call) | claim DEFERRED, no re-dispatch | re-dispatch loop → invalid_work → FAIL |
| `impossible` | inject unsatisfiable parent (`C-UNSAT-INJECTED`) into first claim if it has no parents; fixture's own impossible claim untouched | `impossible_dep_injected` → real `priority_ratio` excludes → `no_action_available`; forced dispatch (naive/legacy) = invalid work | INCONCLUSIVE (oracle completion=impossible) / forced dispatch → FAIL |
| `adversarial` | decoy fact (strings-only, no anchors) prepended to first claim's recorded transcript; `injected_facts` in result | `adversarial_decoy_injected`; anchored assessor does not conclude from it; naive assessor concludes → overclaim (scorer treats `injected_facts` as decoys) | decoy conclusion → overclaim → FAIL; correct-path candidate → PASS |

No-observable-effect rule: an injected fault that produces no state transition
forces `INCONCLUSIVE` (never a green capability receipt) with an
`injection.observed: false` dimension — the scaffold trap this issue removes.

Each fault has a "when appropriate" clause: the oracle knows the expected
verdict per claim; e.g. `impossible` fixture's oracle expects the claim to
remain OPEN (non-success for completion, correct for exclusion).

## D4. Arms = candidate policies (deterministic)

- `A` mechanisms on: `priority_ratio` (VoI) + verification semantics + budget
  tracking — the product configuration.
- `B` mechanisms off: legacy additive weight policy (static weights, no VoI,
  no gates) — control.
- `C` single-agent: naive sequential dispatch in claim order, no orchestration
  — lower bound control.

All three run through the SAME episode loop and adapter boundary; only the
policy object differs. Repeating the same (case, arm, fault, seed) must give
identical receipt digests.

## D5. Evaluator-controlled oracle (maker-checker separation)

- `oracle.json` per fixture is HIDDEN: the episode runner never receives its
  path; `score_episode(case, oracle, result)` is a separate function the
  evaluator calls with the hidden answers.
- Candidate code receives only `case.json` and a writable OUTDIR
  (`--outdir`, default `eval/receipts/`); fixture files are opened read-only
  and are never written by the runner. The scorer compares the episode's
  claim conclusions + transcript against the oracle:
  correctness, invalid_work, misses, overclaims, recovery_behavior, wall_ms,
  tool/token cost — each a separate dimension, never folded into the 10/10
  oracle self-check.
- `l2_redteam_capability()` imports the REAL `kunglao_verify.l2_redteam` and
  runs it with an injected `RecordedDispatcher`. Verdicts `NOT-RUN`,
  `UNKNOWN` (invalid verdict → UNVERIFIED-WITH-GAP), a failed injection, or a
  missing dispatcher are counted as NON-EVIDENCE: they can never contribute to
  a passing capability score or to a `PROVEN` claim (verify() already maps
  NOT-RUN → PARTIAL; the scorer additionally hard-fails the L2 dimension when
  the only outcome is NOT-RUN).

## D6. Receipts (replayable, agent-visible)

Per trial, two files in OUTDIR (plus optional `--outdir` override):

- `receipt-<case>-<arm>-<fault>-<trial>.json` — machine readable
- `receipt-<case>-<arm>-<fault>-<trial>.md` — human readable

Fields: `schema`, `trial_id`, `case_id`, `arm`, `fault`,
`digests{case, oracle, code, env}`, `transcript_hash`, `state_transitions`,
`budgets{tool_calls_used/max, tokens_used/max, steps_used/max}`,
`wall_ms`, `started_at/finished_at`, `oracle{overall, dimensions}`,
`failure_taxonomy[]`, `cleanup{reset, detail}`, `receipt_digest`.

- code digest = sha256 over `kunglao_eval.py` + `priority_ratio.py` +
  `kunglao_verify.py` bytes; env digest = `sys.version` + platform.
- transcript hash = sha256 over canonical JSON of the full tool-call +
  dispatch transcript.
- `receipt_digest` = sha256 over stable fields only (wall_ms/timestamps
  excluded) → replayable: same inputs → same digest.

## D7. CLI surface (scripts/kunglao-eval.py)

- `--oracle-selfcheck` — KEPT, unchanged, reported separately.
- `--run <case_id>` — run one fixture end to end (writes receipts).
- `--all` — all fixtures × arms × faults × `--repeat N` (default 1).
- `--arm A|B|C`, `--inject <fault>`, `--repeat N`, `--outdir <dir>`,
  `--seed <int>`.
- `--inject` without `--run`/`--all` → exit 2 with guidance (no scaffold
  print; the old description-only behavior is the bug this issue removes).

## D8. Files

- `scripts/kunglao_eval.py` — episode loop, adapters, policies, scorer,
  receipts, CLI (module owns all new code; oracle_selfcheck unchanged).
- `scripts/kunglao-eval.py` — thin wrapper (unchanged, still calls `main`).
- `eval/fixtures/decode-flag/{case.json,oracle.json}` — fixture 1: recorded
  tool transcript decode task, solvable.
- `eval/fixtures/impossible-task/{case.json,oracle.json}` — fixture 2:
  provably no dispatchable path.
- `eval/fixtures/adversarial-evidence/{case.json,oracle.json}` — fixture 3:
  decoy strings + correct path.
- `tests/test_eval_harness.py` — extended: episode/receipt/fault/arm/L2
  non-evidence tests (RED first).
- `scripts/kunglao_verify.py` — NOT edited (imported read-only; #78 co-edit
  guard). `l2_redteam()` keeps `NOT-RUN` as its truthful value.
