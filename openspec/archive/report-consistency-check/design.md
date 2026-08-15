# Design — cross-chapter report-INTERNAL consistency checker (#57)

## Design Decisions

### D1. Layering: report-INTERNAL, complementary to #50 (report↔binary) and numeric-fidelity (rule)

#57 occupies a distinct layer from the existing report-quality gates:

| Layer | Issue / rule | What it reads | Catches |
|---|---|---|---|
| Report ↔ binary byte-exact | #50 (`tools/disasm_constant_check.py`) | report code listing `field=value` + capstone disasm of the PE site | a report listing assertion that diverges from the binary bytes |
| Report ↔ fact cross-layer | #50 (report mode) | report listing vs fact `expected:` map | a report value that diverges from the verified fact |
| Numeric-fidelity (rule) | `~/.claude/rules/common/numeric-fidelity.md` | a number + its caliber/unit as it flows fact → anchor → report | a multi-caliber number collapsed to one caliber in the report |
| Report-INTERNAL cross-chapter (THIS) | #57 | the report markdown ALONE (no binary, no fact file) | two chapters of the SAME report contradicting each other |

#50 needs the binary AND the fact file; it cannot catch two prose chapters contradicting
each other (neither chapter is a `field=value` listing vs bytes). numeric-fidelity governs
a single number's caliber as it crosses layers; it does not scan prose chapters for
routing-polarity flips. The a2b5e25c problem-3 failures live entirely IN the report
(§3.3 vs §3.4 vs §4.1; §5.4 vs §6.1.3; §1.1 vs §2.3) — no binary read, no fact lookup
would surface them. #57 reads the report markdown alone precisely because the failure
lives there. See R1.

### D2. Chapter segmentation: markdown `## N.N` headers + fenced code blocks as evidence regions

The real report (`report_work/chapters/chNN_sNN.md`) uses `## N.N <title>` for sections
and `### N.N.N <title>` for sub-sections (confirmed against ch03_s03.md = "## 3.3 DPAPI
解密能力..."). Segmentation rule:

- A line matching `^#{2,3}\s+(\d+(?:\.\d+){1,2})\s+(.+)$` starts a new chapter with id
  `§<number>` and title. Lines before the first header = `§preamble`.
- Fenced code blocks (``` ... ```) inside a chapter are tracked as a separate `code_text`
  region for the "zero code evidence" sub-check (group B). Prose = chapter body minus
  fenced blocks.

This is robust to the real report's format and to the synthetic fixture (which uses the
same `## N.N` convention). Sub-section numbers (`### 6.1.3`) are normalized to their
section id for cross-chapter grouping but the full number is kept in evidence (so group B
evidence shows `§6.1.3`, not `§6.1`).

### D3. Polarity engine: the shared primitive behind CC1 and CC3

Both CC1 (symbol polarity) and CC3 (mechanism-topic polarity) reduce to the same
primitive: **a referent token (symbol or mechanism noun) appears in ≥2 chapters with
conflicting polarity.** Polarity is derived mechanically from the referent's local
context:

- **NEGATIVE** iff a negator-routing pattern matches within a ±12-char window of the
  referent occurrence. Routing negators: `不经过|未经过|不再经过|未经|绕过|跳过|bypass|
  skip|not.{0,6}through|does\s+not.{0,6}route|not.{0,6}go\s+through`. Mechanism negators
  (broader): `不依赖|不使用|未使用|无需|不需要|不落盘|does\s+not.{0,6}(rely|use)|
  not.{0,6}(rely|use)|never.{0,6}(uses|relies|writes)`.
- **POSITIVE** otherwise (the referent is named as the handler / function / channel /
  mechanism being used or evidenced). A bare mention in a code-listing title or body is
  POSITIVE (the listing asserts the function IS the subject).
- **CONFLICT-acknowledged** iff the occurrence's chapter carries an explicit `CONFLICT`
  marker (HTML comment `<!-- CONFLICT: ... -->` or a `CONFLICT:` label) — the pair is
  then reported with `acknowledged: true` and excluded from `inconsistency_count`.

The window size (12 chars) covers the fixture's `不经过通用的 HandleCommand` (the
adjective `通用的` sits between the negator and the symbol). The per-occurrence
classification is table-driven (extensible constants), so new negators cost one line.

### D4. The 3 fixture groups are the calibration set (recall), the clean fixture is the precision guard

| Group | Referent(s) | Chapters | Polarity / pattern | Detector |
|---|---|---|---|---|
| A — HandleCommand routing | `HandleCommand`, `func12` | §3.3 (NEG 不经过), §3.4 (POS code title `HandleCommand.func12`), §4.1 (POS 先经过 func12) | token `HandleCommand` flips NEG→POS across chapters | CC1 |
| B — named pipe vs shared memory | `命名管道` (pipe), `共享内存` (shm) | §5.4 (both POS, "命名管道或共享内存"), §6.1.3 (shm POS via code) | exclusive pair {pipe, shm} both POS | CC3 exclusive-mechanism sub-check |
| C — registry persistence | `注册表`/`registry`, `Run`/`Startup` | §1.1 (NEG 不依赖注册表), §2.3 (POS Run-key table), summary (POS 通过 Run/Startup) | token `注册表`/`Run` flips NEG→POS across chapters | CC3 topic-polarity |
| Amplification — F035 → §1.1 | config-storage NEG + persistence-mechanism NEG | F035 chapter (env vars 不落盘), §1.1 (持久化 不依赖注册表) | narrow-caliber NEG restated as broad-caliber NEG | CC2 |

Group A is caught on the literal token `HandleCommand` (NEG in §3.3, POS in §3.4) — no
alias table needed. `func12` is additional POS context in §3.4/§4.1. Group C is caught on
the literal token `注册表`/`Run` (NEG in §1.1, POS in §2.3). Group B needs the exclusive-
pair sub-check because the named pipe is NOT negated in §6.1.3 — it is merely absent while
shared memory is evidenced. The amplification needs CC2's caliber-keyword pair.

### D5. Heuristic, not semantic — documented recall/precision tradeoff

The detector uses regex/keyword patterns only. It does NOT call an LLM, does NOT read the
binary, does NOT consult the fact base. The tradeoff:

- **Precision risk (false positive)**: a consistent report that happens to use a negator
  near a symbol in one chapter and not in another. Mitigations: (a) CC1/CC3 fire only on
  a literal polarity FLIP (both POS and both NEG co-occurrences are consistent, not
  conflicts); (b) CC2's exclusive-mechanism sub-check fires only when BOTH members of a
  configured exclusive pair are POSITIVE (a report saying "shared memory, NOT named pipe"
  has pipe=NEG, shm=POS → no flag); (c) CC2 amplification is reported as a `potential`
  warning (not a hard inconsistency) because mechanical check cannot judge intent — the
  human decides whether the caliber was preserved or amplified. The clean-fixture test
  (RED c) is the regression guard.
- **Recall risk (false negative)**: a contradiction phrased in words the regex does not
  cover. Mitigation: the pattern sets are table-driven module constants (easy to extend);
  each inconsistency's evidence carries the matched span + chapter so a miss is
  diagnosable. Acceptance #1 requires only that the 3 fixture groups + amplification fire
  on THIS regression fixture, not every conceivable phrasing.

The deliberate stance: prefer a detector that fires loudly on the 3 documented groups +
amplification (recall on the calibration set) and quietly on a clean consistent report
(precision), with the pattern tables extensible for future instances and the CONFLICT
marker as the author's acknowledged-tension escape hatch.

### D6. The exclusive-mechanism pair list is small, explicit, and documented

The exclusive-pair table (group B) is the most fixture-shaped part of the detector. It is
kept as a small module constant, not inferred:

```
EXCLUSIVE_MECHANISM_PAIRS = [
    ({"命名管道", "named pipe", "named-pipe", "pipe"},        # POS = "is a channel"
     {"共享内存", "shared memory", "shared-memory", "shm"}),   # POS = "is a channel"
]
```

Both members POSITIVE ⇒ flag (exclusive transports cannot both be the channel). One NEG
("not named pipe, uses shared memory") ⇒ no flag. This is honest: the detector does not
discover transport mechanisms in general; it flags a configured exclusive pair when the
report asserts both. Extending to new domains (e.g. encryption: `RSA` vs `AES` as "the"
algorithm) is one tuple.

### D7. CC2 amplification is a WARNING, CC1/CC3 are INCONSISTENCIES

Mechanical distinction: CC1/CC3 are byte-level polarity contradictions (the report says X
and not-X about the same referent — a definite error unless CONFLICT-marked). CC2 is a
caliber drift (the report says a narrow-caliber negative here and a broad-caliber negative
there — it MIGHT be a grounded generalization or an amplification; the mechanical check
cannot tell). So CC2 evidence enters the report as `severity: "potential"` and is counted
separately under `amplification_count`, NOT under `inconsistency_count`. The CLI still
exits 1 when ONLY CC2 fires (the reviewer must look), but the JSON makes the distinction
machine-readable so a future caller can treat CC2 as a warning gate and CC1/CC3 as a hard
gate.

### D8. Pure stdlib, importable + CLI-runnable

No third-party imports (the report is markdown text, no yaml / no pefile / no capstone).
`check(text) -> dict` is the importable entry; `main()` is the CLI. The JSON report shape
is stable so the hr-report pipeline (follow-up, out of scope here) can consume it:
`{inconsistency_count, amplification_count, acknowledged_count, inconsistencies: [{id,
name, referent, chapters: [{chapter, polarity, span}], severity, note}], amplifications:
[...], acknowledged: [...]}`.

## Rejected alternatives

### R1 (rejected): extend #50 to also read two report chapters

Rejected: #50's contract is `field=value` listing assertions vs PE bytes / fact expected
map. Two prose chapters contradicting each other is NOT a listing-vs-bytes question; it is
a same-referent-polarity question. Forcing #50 to parse free prose would dilute its
byte-exact contract and require the binary/fact inputs that a prose-internal check does
not need. #57 reads the report ALONE. Different input, different question. #57 is
complementary by construction (D1).

### R2 (rejected): reuse hr-report skill's g6_contradiction_check.py

Rejected for THIS PR's scope: (a) it lives in a different repo (hr-report skill), so
modifying it is cross-repo scope the issue explicitly defers; (b) the issue states it was
UNENFORCED in the a2b5e25c pipeline and only catches token repetition / local context,
not cross-chapter routing polarity or caliber amplification; (c) a kunglao-agent tool can
be called by ANY report pipeline (documented contract in references/report-checks.md)
without coupling kunglao-agent to hr-report internals. The hr-report pipeline wiring is a
follow-up noted in the PR body.

### R3 (rejected): LLM-based cross-chapter semantic consistency

Rejected: the issue scopes the check as mechanical ("可机械化的检查项"). A regex/keyword
detector is deterministic, fast, offline, and CI-runnable; an LLM call would add cost,
latency, and non-determinism to a gate that must give the same answer on the same report.
Experiment H-D (an LLM CAN find the tensions when given the cross-chapter window) proves
the capability exists but does not make an LLM the right gate — a mechanical pre-filter
that surfaces the calibrated patterns deterministically is the right first layer (an LLM
reviewer can run downstream). The recall gap vs an LLM is real (D5) but bounded by
table-driven extensibility.

### R4 (rejected): collapse CC1 and CC3 into one "polarity contradiction" check

Rejected: CC1 and CC3 share the polarity ENGINE (D3) but differ in referent type (function
symbols vs mechanism topics) and CC3 additionally carries the exclusive-mechanism sub-
check (D6). Collapsing loses the diagnostic distinction the issue drew (issue check 1 =
symbol consistency; issue check 3 = conflicting conclusions converge) and would merge
group A evidence with group B/C evidence, making the JSON harder for a reviewer to triage.
Keeping CC1 / CC2 / CC3 as distinct ids maps 1:1 to the issue's 3 check items while sharing
the engine under the hood.
