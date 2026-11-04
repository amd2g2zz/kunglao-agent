# -*- coding: utf-8 -*-
"""learning-loop ``settlement`` — the per-dispatch settlement faces (#884).

Three verification layers arrive as data; each dispatch settles on its
OWN spend; rollouts aggregate Σ + terminal; the draft/commit two-phase
keeps crash-resilience without rewriting the append-only ledger.
"""
