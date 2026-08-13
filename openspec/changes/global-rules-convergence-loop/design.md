# Design — global-rules-convergence-loop (#46)

## Design Decisions

### D1. Distilled file lives at `rules/kunglao-convergence-loop.md`

The always-on rule file goes into the repo `rules/` dir (repo-owned, versioned, reviewable) — the same layout the issue prescribes. Deployment to `~/.claude/rules/common/` is a separate setup-script issue (sync + manifest verification); this issue only ships the source file. The file is a **distillation** — not a copy — of SKILL.md's convergence section, written in the style of the existing global rules (`maker-checker.md` / `numeric-fidelity.md`: short, imperative, Chinese prose with English technical terms).

Why not update `~/.claude/rules/common/` directly from this PR: the global rules channel is not in this repo's git; shipping the file through the repo keeps it under review and lets the setup script handle installation idempotently.

### D2. Content = the 9-point issue outline, mapped to testable markers

| # | Outline point | Marker (test-asserted) |
|---|---|---|
| 1 | Identity: RE orchestrator, not analyst | `orchestrator` + `不是分析师` |
| 2 | #1 invariant: first tool of every round | `每轮第一个工具` + `convergence_check` |
| 3 | Decision table: DISPATCH/SATURATED/BLOCKED/CONVERGED | all 4 tokens + `DISPATCH_VERIFIER` |
| 4 | 5 behaviors, one line each | `self-recovery`, `specialist-first`, `cost-is-noise`, `poll-workers`, `false-completion-trap` |
| 5 | Maker-checker split, pointer to global rule | `maker-checker` + `worker=maker` |
| 6 | Tool boundary: never call analysis tools directly | `永不直接` + `ghidra` + `x64dbg` + `frida` |
| 7 | Hard prohibitions | `反问`, `cascade`, `declare done` + `OPEN` |
| 8 | File map | `claim-register.yaml`, `facts/_INDEX.md`, `.convergence_ledger.jsonl`, `scripts/` |
| 9 | Pointers to full contract | `SKILL.md` + `references/` |

Each marker is a short fixed string (or token set) so the contract test is deterministic, not LLM-judged.

### D3. Distillation guard = 80-char shared-substring check vs the reference

"Distill ≠ copy" is enforced mechanically: no 80+ char substring of `rules/kunglao-convergence-loop.md` may appear in `references/convergence-loop.md`, once an allowlist of shared vocabulary is masked out. The allowlist covers legitimate repeats: script paths/invocations (`convergence_check.py`, `convergence_health.py`, `failure_analysis_gate.py`, the full `python <skill_dir>/scripts/...` command lines), file names, decision tokens, and the 5 behavior labels. An 80-char window is long enough that a paraphrased sentence never trips it; a verbatim copied sentence always does.

### D4. Line budget <150 with headroom

Issue acceptance: <150 lines. Target ≈105-115 lines (9 sections + header + pointers), leaving headroom so a later minor addition (e.g. a 10th section) does not immediately break the contract test. The test asserts `< 150` on total lines of the final file.

## Rejected Alternatives

- **R1: copy the reference's prose into the rules file** (fastest path to "coverage"). **Rejected** — the issue explicitly demands 蒸馏 ≠ 复制; verbatim blocks defeat the purpose (a 8825-byte reference compressed to a rule file = the same "转述失真" risk the maker-checker rules exist to prevent). D3 mechanically forbids it.
- **R2: write the distilled file directly into `~/.claude/rules/common/` from this PR**. **Rejected** — out of scope (setup-script issue owns deployment); also untestable in CI since the global rules dir is outside the repo.
- **R3: make the rules file a pure English restatement of SKILL.md**. **Rejected** — the existing global rules (`maker-checker.md`, `numeric-fidelity.md`) are Chinese prose + English technical tokens; the distilled file should match the channel's established style.
- **R4: modify SKILL.md / references/convergence-loop.md to cross-link the new file**. **Rejected** — issue explicitly says neither file changes. The new file points *at* them; they do not need to point back.

## File layout

| File | Action | Purpose |
|---|---|---|
| `rules/kunglao-convergence-loop.md` | CREATE | distilled always-on convergence-loop rules (<150 lines) |
| `tests/test_convergence_rules_file.py` | CREATE | TDD contract tests (exists / line count / markers / no verbatim copy) |
| `openspec/changes/global-rules-convergence-loop/*` | CREATE | SDD artifacts |
