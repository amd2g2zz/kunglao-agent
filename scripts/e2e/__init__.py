# -*- coding: utf-8 -*-
"""e2e — T0.4 gold-standard acceptance harness (runbook productization).

Encodes .claude/e2e-runbook-source.md (the rehearsal-validated dogfood
runbook for eval unit py-derive-v1) as an executable pipeline:

    C1 init -> C2 hooks -> C3 heartbeat -> C4 entry -> C5 analysis gate
    -> C6 dispatch loop -> C7 completion -> ORACLE (replay checker)

Every subprocess lands in per-checkpoint evidence under
<repo>/runs/e2e/<runid>/<step>.json (gitignored), which is also what
--resume reads back. Pure productization layer: the runbook is the spec.
"""
