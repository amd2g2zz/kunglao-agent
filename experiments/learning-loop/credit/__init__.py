# -*- coding: utf-8 -*-
"""learning-loop ``credit`` — the credit assignment faces (#883).

Pure numpy computation over trajectories: discounted returns, the
advantage with its decision-time baseline, terminal shaping, the
EMxPG-style confidence modulation, and the spawn-chain lineage
flowback. Nothing here writes the ledger — the loop consumes the
receipts and lands them through the standard append faces (the
R_t / A_t columns ride the result rows, #879).
"""
