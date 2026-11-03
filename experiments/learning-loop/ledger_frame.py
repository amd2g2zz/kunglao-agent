# -*- coding: utf-8 -*-
"""ledger_frame.py — the trajectory ledger's pandas projection (#879).

The pandas load/query face over the rl-v2 unified ledger: the WHOLE
multi-schema trajectory stream (q-cell-obs + q-cell-action +
q-cell-result rows of ``runs/experience.jsonl``) as ONE DataFrame.

Lives in the experiment tree, NOT in the deployed rlvr package: the
dep-surface gate (#467) requires every deployed import to be declared
by the framework env project, and the projection's only consumer is
analysis (loop_sim, the policy faces) — the store faces stay
dependency-light on the dispatch-gate hook path.

Row order = append order; one column per ledger field
(``COLUMNS``, deterministic order); absent fields load as the honest
gap (NaN), never a fabricated zero; ``schema`` is the row-kind
discriminator. Query shape::

    df = ledger_frame.trajectory_dataframe(ws)
    df[df["rollout_id"] == "ro-1"]
    df[df["schema"] == q_cells.SCHEMA_RESULT_V2]
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import q_cells  # noqa: E402 — the store face (scripts/)

#: the deterministic column order of the projection — the TRUE union
#: of the three row kinds' fields (obs rows carry the full additive
#: column set; v2 rows the trajectory set; armed runs add ``seal``).
COLUMNS = (
    # shared + v2 action rows
    "schema", "ts", "source", "kind", "rollout_id", "step_id",
    "target", "params", "budget", "policy_version", "state_snapshot",
    # v2 result rows
    "r_t", "R_t", "A_t", "verified", "cost", "verdict",
    "evidence_refs", "summary",
    # obs rows (q-cell-obs/1) — the full additive column set
    "signature_hash", "method_family", "claim", "agent",
    "dispatch_id", "fingerprint", "credit", "arm_key", "action_type",
    "phi_delta", "credit_kind", "recipe_id", "recipe_propensity",
    "recipe_source", "failure_delta", "reason", "reward",
    "confidence_band", "tier", "tools", "propensity",
    "sampled_family", "prior_source",
    # the write seal (armed runs)
    "seal")


def trajectory_dataframe(ws):
    """Load the workspace's trajectory ledger into one pandas
    DataFrame (the plan's task 0.3 load/query face)."""
    import pandas as pd  # noqa: PLC0415 — lazy: analysis-only import
    rows = q_cells.trajectory_rows(ws)
    table = [{col: row.get(col) for col in COLUMNS} for row in rows]
    return pd.DataFrame(table, columns=list(COLUMNS))
