# -*- coding: utf-8 -*-
"""learning-loop ``policy`` — the rl-v2 policy faces (#880-#882).

One module per decision kind family; each face consumes the core
value objects and the q_cells v2 ledger, samples (never argmax), and
stays pure: (state, store, rng) -> receipt, side-effect-free.
"""
