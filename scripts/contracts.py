#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contracts.py — cross-process contract registry (#102, split from #95 A5).

Root cause of the #102 drift family: producers and consumers each defined
the same byte-level contract in separate comments (event field name, exit
codes, subprocess rc sets). When one side moved, the other silently read
fabricated zeros or misattributed a crash as a pass. This module is the
single source both sides import; a contract change lands here FIRST.

Scope discipline (#102 review note): this file only REGISTERS contracts
that already exist in shipped code — it invents nothing. Each block names
its owning face. Declarations are alignment obligations, not runtime
enforcement: consumers import their face, and the cross-parser contract
test (tests/test_contracts_drift_102.py) pins the round trip.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Exit-code registry — the CONSUMER CONTRACT (#99 wording, moved here by
# #102). scripts/convergence_check.py imports these names (the definition
# lives ONLY here; convergence_check's `cc.EXIT_*` attributes are this
# module's objects). Every rc-based consumer — hooks that branch on 0-4,
# kunglao-decide, external tick loops — reads the same bytes. Before adding
# a value: keep the registry distinct AND update skills/kunglao-agent/
# SKILL.md's decision table (the human-facing copy of this contract).
# ---------------------------------------------------------------------------

# --- convergence_check face (scripts/convergence_check.py decide() rc) ----
EXIT_CONVERGED = 0
EXIT_DISPATCH = 1
EXIT_VERIFY = 2
EXIT_SATURATED = 3
EXIT_BLOCKED = 4
EXIT_PARK = 5  # #634: suspended on external gates — legal idle with wake_condition
EXIT_MISSING_WORKSPACE = 64  # convergence_check.main(): no claim-register.yaml
# #99: the check itself crashed (malformed YAML, unexpected error). 64 is
# taken by MISSING_WORKSPACE; 65 is the next free byte. A crash must NEVER
# share EXIT_DISPATCH's byte — pre-#99 a malformed register exited rc=1,
# which rc-based consumers read as "dispatch now" while stdout was empty.
# On this exit: stdout carries {"decision": "CRASHED"}, stderr the traceback.
EXIT_CRASHED = 65

# --- plan_drift_detector --auto face (#602 integration remap) -------------
# The ONLY bytes --auto may exit with: 0 no-drift (proceed) / 2 drift-severe
# (BLOCKED) / 3 WARN-only (SATURATED). Any OTHER rc is not a contract value
# — it is a detector crash (rc=1: unhandled exception, e.g. a malformed
# claim-register.yaml) or an unknown drift. hooks/dispatch_gate.
# _plan_drift_auto must take the explicit crash face on everything outside
# this set (#102: fail-open dispatch, OBSERVED degradation — never a silent
# fall-through).
PLAN_DRIFT_AUTO_RCS = frozenset({0, 2, 3})

# ---------------------------------------------------------------------------
# Event field schema
# ---------------------------------------------------------------------------

# The field carrying the event word in the kunglao_log stream
# (scripts/kunglao_log.py emit(): "action": action). The ledger stream's
# sibling face (kunglao_record.record_event) writes the SAME controlled
# word in `event_type`; event_taxonomy's ledger branch reads BOTH fields
# through LEDGER_EVENT_MAP. #102 drift instance 1: the taxonomy keyed on
# `event_type` only, so every kunglao_log-shaped row classified as None —
# seven main-stream classes read as fabricated zeros in statusline/digest.
EVENT_FIELD = "action"
