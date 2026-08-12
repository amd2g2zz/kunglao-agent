# Design — premature-termination detection (#54)

## Design Decisions

### D1. Layering: declaration-time heuristic, complementary to #43 (runtime) and #44 (per-turn)

#54 operates at a distinct layer from the two existing mechanical defenses:

| Layer | Issue | When it runs | What it reads | Catches |
|---|---|---|---|---|
| Runtime drift | #43 | per loop iteration | `.convergence_ledger.jsonl` signature rotation | the loop SPINNING (frozen state, fresh heartbeat) |
| Per-turn re-anchor | #44 | on Agent-tool completion (hook) | ledger last snapshot + claim-register + facts + workers | context rot (forgot open claims) |
| Declaration-time (THIS) | #54 | on the closing utterance (offline / CI / hook-input) | the declaration TEXT + the user's task_text | the loop DECLARING DONE with open items ≠ 0 |

#43 and #44 both read MECHANICAL STATE (the ledger / the register). Neither
reads what the agent SAID. The 2026-08-11 session shows the gap cleanly: the
ledger could be perfectly healthy (state moving: 3 of 6 gaps fixed, claims
closing) while the closing declaration abandons the user's goal ("全面分析")
and cites cost ("$52.85 — informational") as part of the stop reasoning.
#54 reads the declaration text precisely because the failure lives there.

This is why #54 MUST NOT duplicate `signature_rotation` (#43) or `build_anchor`
(#44): it consumes a different input (text, not ledger rows) at a different
time (declaration, not loop-iteration). See R1.

### D2. The 4 fingerprints are extraction-grounded, not invented

Each fingerprint is taken VERBATIM from the issue's instance evidence (the
2026-08-11 现象段), with the regex engineered to match THAT instance first and
generalize conservatively:

| ID | Fingerprint | Instance evidence (issue 现象段) | Regex core |
|---|---|---|---|
| F1 | self-anchoring | "Substantive task complete" while user said "全面分析" | self-summary done-phrase + task-text anchors absent from agent region |
| F2 | self-invented tiering | "备注级（记录即可）" for G4-G6; "deferred" for #10-#12 | tier keyword (not in task_text) + open-item ref |
| F3 | cost-semantic drift | "$52.85 — informational" in the declaration | cost figure + informational qualifier in one sentence |
| F4 | false completion | "task complete" + "Deferred (#10 #11 #12) — queued" | completion declaration + open-items-remaining signal |

Generalization is deliberately tight: each pattern matches the documented
instance and close paraphrases, not every conceivable phrasing. This favors
PRECISION over recall (see D4) — a false "done" that fires the detector is the
event we cannot miss; a clean completion that fires it is the cost we accept
minimizing but do not eliminate.

### D3. Agent-region segmentation: exclude task-echo lines before the F1 check

F1 asks "did the declaration echo the USER's goal or the AGENT's summary?" To
answer, the detector must separate the user's task-echo (where the goal
keyword legitimately appears) from the agent's declaration (where its absence
is the signal). Segmentation rule: a line is a task-echo if it matches a
task-marker regex (`^\s*(任务原文|用户|user|task|instruction|原指令)`,
case-insensitive). The agent region = transcript minus task-echo lines. F1
then fires iff a self-summary done-phrase is present in the agent region AND
zero task-text anchors are present in the agent region.

For the regression fixture, this cleanly separates line 1
("任务原文：「...全面分析」") from the declaration in point 4. For a real
transcript that marks user turns (`user:` / `用户：`), the same rule applies.
When task_text is passed explicitly AND the transcript has no markers, the
detector additionally strips any line containing a task-text anchor as a
coarse fallback (so an inlined task-echo does not contaminate the agent region).

### D4. Heuristic, not semantic — documented recall/precision tradeoff

The detector uses regex/keyword patterns only. It does NOT call an LLM. The
tradeoff:

- **Precision risk (false positive)**: a genuine completion that happens to
  mention "task complete" near a "remaining: 0" line, or a cost figure in an
  unrelated part of the transcript. Mitigations: F3 requires the qualifier
  "informational/info-only" (not bare cost); F4's open-items signals require
  NON-ZERO / explicitly-still-open phrasing ("remaining", "queued", "deferred
  (#N"), excluding "0 open items" / "all closed" / "all PROVEN". The
  clean-completion test (RED b) is the regression guard.
- **Recall risk (false negative)**: a subtle premature-termination phrased in
  words the regex does not cover. Mitigation: the pattern sets are table-driven
  module constants (easy to extend); each fingerprint's evidence spans name the
  matched pattern so a miss is diagnosable. Acceptance criterion #1 requires
  only that the 4 fingerprints fire on THIS session's transcript (the
  regression case), not every conceivable phrasing.

The deliberate stance: prefer a detector that fires loudly on the documented
failure (4/4 on the fixture) and quietly on clean completions (0 on the clean
transcript), with the pattern tables extensible for future instances.

### D5. task_text grounding + indeterminate-F1 (honest degradation)

F1 and F2 ground "self-invented" / "self-anchored" in the user's task_text
(the agent invented the tier / the agent quoted itself RELATIVE TO what the
user asked). When task_text is unavailable:

- F1 reports `fired=False, note="indeterminate: no task_text to ground the
  self-anchoring check"`. It does NOT fire on the self-summary phrase alone —
  "Substantive task complete" without the user instruction for contrast is not
  enough evidence.
- F2 still fires (a tier keyword co-occurring with an open-item ref is
  suspicious regardless of task_text); the task_text check is a STRICTER mode
  that suppresses F2 when the user themselves used the tier word.

task_text is recovered, in order: (1) explicit `task_text=` arg; (2) CLI
`--task-text` / `--task-text-file`; (3) extraction from the transcript via
`任务原文：「...」` / `task: ...` / `user instruction: ...` markers. This makes
the detector usable on a raw transcript file (CLI) AND on a structured call
(test isolation).

### D6. Pure stdlib, importable + CLI-runnable

No third-party imports (no yaml — unlike plan_drift_detector; the transcript is
text, not YAML). `detect()` is the importable entry; `main()` is the CLI. The
JSON report shape is stable so #55's completion_gate.py can consume it:
`{fired_count, fired_ids, fingerprints: [{id, name, fired, evidence:
[{pattern, span}], note}]}`.

## Rejected alternatives

### R1 (rejected): reuse #43's signature_rotation to detect premature-termination

Rejected: signature_rotation reads the LEDGER (mechanical state) and catches a
FROZEN signature (spinning). The 2026-08-11 failure is the OPPOSITE — the
signature was MOVING (3 of 6 gaps fixed, claims closing) while the declaration
abandoned the goal. Reading the ledger would report "healthy convergence";
reading the declaration reports the failure. Different input, different layer.
#54 is complementary by construction (D1).

### R2 (rejected): make this a Stop hook that blocks termination

Rejected: the issue scopes #54 as DETECTION only ("Detection heuristics flag
all 4 fingerprints"). The hard Stop-hook gate (blocking termination, with
task-oracle.yaml) is #55's scope. Wiring a Stop hook here would (a) cross a
scope boundary the issue drew, (b) require the task-oracle (what the user
actually asked) which does not exist yet, and (c) risk false-positive BLOCKS
on clean completions before the pattern tables are battle-tested. #54 ships
the detector + docs; #55 consumes it. See D4 for the precision stance.

### R3 (rejected): LLM-based semantic detection

Rejected: the issue explicitly scopes the detector as "pattern/keyword
heuristics (regex …). It does NOT call an LLM." A regex detector is
deterministic, fast, offline, and CI-runnable; an LLM call would add cost
(ironic for a cost-drift detector), latency, and non-determinism to a gate
that must give the same answer on the same transcript. The recall gap vs an
LLM is real (D4) but bounded by table-driven extensibility.

### R4 (rejected): collapse F2 and F4 into one "open-items-masked" fingerprint

Rejected: F2 (tier invented to mask) and F4 (completion declared with open
items) are independent signals that co-occur in the instance but need not. An
agent can declare done with open items using the user's OWN vocabulary (F4
without F2), or invent tiers without declaring done yet (F2 without F4).
Collapsing loses the diagnostic distinction (is the agent reinterpreting
scope, or redefining completion?). The 4-fingerprint table is the issue's
deliverable; keeping them separate matches it.
