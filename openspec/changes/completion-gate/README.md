# completion-gate

Code-owned completion gate (#55): a Stop hook + `task-oracle.yaml` that makes
"done" a CODE verdict, not LLM discretion. The structural fix for the
premature-termination class (#54 detects; #55 blocks).

Complementary to #43 (runtime drift), #44 (per-turn state anchor), #54
(declaration detector). See `proposal.md` / `design.md`.
