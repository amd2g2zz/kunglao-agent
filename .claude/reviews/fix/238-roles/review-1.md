REVIEWER=r1-code-review
VERDICT=APPROVED
F2 read/write boundary: SKILL.md orchestrator section now distinguishes 读状态 (claim-register/plan, always allowed) from 读证据 (evidence/*, allowed) vs 读证据+写fact (maker behavior — worker or synthesis:true + source). The 2026-08-12 callgraph.txt→F006-F008 incident shape is named explicitly. Wording keeps the existing claim-register/verify-note conventions intact; line count 496 ≤ 500 contract cap verified by test. No existing section semantics changed.
