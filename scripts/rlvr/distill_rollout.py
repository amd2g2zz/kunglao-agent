# -*- coding: utf-8 -*-
"""rlvr/distill_rollout.py — the distill_rollout settlement rows
(the rollout ruling: distillation IS a rollout — worthless attempts are
harmful and must be settled like any other rollout).

THE ROW — schema `distill-rollout/1` in the consolidated SETTLEMENT
family ("how it closed"), appended through consolidated_ledger.append
(append-only, schema-stamped, flock). The word `distill_rollout` is
EMIT_ACTIONS-registered (the event stream's vocabulary; sorted+unique
pins apply).

THE GRADED SPECTRUM (the issue's lineage):
    consumed + helped        0.5-1.0   0.5 + 0.5 * strength
    consumed + neutral       0.1-0.5   0.1 + 0.4 * strength
    never consumed           0.01      flat
    adverse (misled + detour evidence) 0.0 flat — EVIDENCE-GATED: an
                               adverse ruling without a detour-evidence
                               reference is refused (the 0 face pays
                               only on evidence, never on assertion)

Attempt rows: an admitted item's attempt IS the act's +1; an abandoned
attempt pays ABANDON_REWARD = 0.01 with the reason kept. Reward history
folds into per-strategy priors (the same accounting family as the
rotation-induction prior feed / Thompson rank) — the distillation STRATEGY itself
gets optimized. Zero telemetry refusal paths: the emit is fail-open, the
ledger append reports the health bit. Settlement/verifier semantics are
only ever CALLED (never modified).
"""
from __future__ import annotations

from pathlib import Path

from kunglao_log import emit  # the canonical event face; never raises

ROW_SCHEMA = "distill-rollout/1"

#: policy constants (documented, not fitted) — the issue's reward bands
ABANDON_REWARD = 0.01
ADVERSE_REWARD = 0.0
NEVER_REWARD = 0.01
HELPED_BASE = 0.5
HELPED_SPAN = 0.5
NEUTRAL_BASE = 0.1
NEUTRAL_SPAN = 0.4


class SettlementRefused(ValueError):
    """The settlement refused: an adverse ruling without detour
    evidence, or a strength outside [0, 1]."""


def _utc_now_z() -> str:
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        return utc_now_z()
    except Exception:  # noqa: BLE001 — the row needs a clock stamp
        import datetime
        return datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(ws, row: dict) -> None:
    """The fail-open event face (the word is EMIT_ACTIONS-registered).
    kunglao_log.emit never raises — a write failure degrades to a stderr
    warning inside the logger, so settlement can never be blocked by
    observability."""
    emit(Path(ws), actor="distill-engine", action="distill_rollout",
         artifact=str(row.get("item") or ""),
         detail=(f"kind={row.get('kind')} "
                 f"reward={float(row.get('reward') or 0.0):.2f} "
                 f"product={row.get('product') or ''}"))


def _append_row(ws, row: dict) -> dict:
    from rlvr import consolidated_ledger  # noqa: PLC0415 — lazy
    row = dict(row, schema=ROW_SCHEMA, ts=_utc_now_z())
    from kunglao_log import warn
    if not consolidated_ledger.append(ws, "settlement", row):
        warn("distill_rollout.append",
             "the settlement-family append refused the row")
    _emit(ws, row)
    return row


# ------------------------------------------------------ attempt rows

def record_attempt(ws, item_id: str, *, strategy: str, score,
                   product: str | None, reason: str = "") -> dict:
    """One distillation attempt's row: an admitted item pays +1 with the
    product card path; an abandoned attempt pays ABANDON_REWARD with the
    reason kept. The score is required (an unscored attempt is not an
    attempt — scoring always runs before the row)."""
    if score is None or not isinstance(score, (int, float)) \
            or isinstance(score, bool):
        raise ValueError("record_attempt: the score is required — "
                         "scoring runs before the row")
    admitted = product is not None
    row = {
        "kind": "attempt",
        "item": str(item_id),
        "strategy": str(strategy),
        "score": float(score),
        "product": str(product) if product else "abandoned",
        "reward": 1.0 if admitted else ABANDON_REWARD,
        "reason": str(reason or ("" if admitted else "abandoned")),
    }
    return _append_row(ws, row)


# -------------------------------------------------- consumption bands

def settle_band(*, consumed: bool, helped: bool, adverse: bool,
                strength: float = 0.0,
                detour_evidence: str = "") -> dict:
    """The graded spectrum: band + reward for one consumption outcome.
    Adverse is EVIDENCE-GATED (a detour-evidence reference is required);
    strength outside [0, 1] is refused. Pure."""
    if not isinstance(strength, (int, float)) or isinstance(strength, bool) \
            or not (0.0 <= float(strength) <= 1.0):
        raise SettlementRefused(
            f"strength must be in [0, 1], got {strength!r}")
    if adverse:
        if not str(detour_evidence or "").strip():
            raise SettlementRefused(
                "adverse requires a detour-evidence reference — the 0 "
                "reward pays only on evidence, never on assertion")
        return {"band": "adverse", "reward": ADVERSE_REWARD}
    if not consumed:
        return {"band": "never-consumed", "reward": NEVER_REWARD}
    if helped:
        return {"band": "consumed+helped",
                "reward": HELPED_BASE + HELPED_SPAN * float(strength)}
    return {"band": "consumed-neutral",
            "reward": NEUTRAL_BASE + NEUTRAL_SPAN * float(strength)}


def record_settlement(ws, item_id: str, *, consumed: bool, helped: bool,
                      adverse: bool, strength: float = 0.0,
                      detour_evidence: str = "") -> dict:
    """One consumption settlement: the band + the ledger row + the emit.
    Refuses (SettlementRefused) without the adverse evidence."""
    band = settle_band(consumed=consumed, helped=helped, adverse=adverse,
                       strength=strength,
                       detour_evidence=detour_evidence)
    row = {
        "kind": "settlement",
        "item": str(item_id),
        "band": band["band"],
        "reward": float(band["reward"]),
        "consumed": bool(consumed),
        "helped": bool(helped),
        "adverse": bool(adverse),
        "strength": float(strength),
        "detour_evidence": str(detour_evidence or ""),
        "product": "",
        "reason": "",
    }
    return _append_row(ws, row)


# ------------------------------------------------------ the prior fold

def strategy_priors(ws) -> dict[str, dict]:
    """Reward history folded by source_strategy: {strategy: {n,
    mean_reward}} over every `distill-rollout/1` attempt row — the same
    accounting family as the rotation-induction prior feed; the distillation
    STRATEGY itself gets optimized. Deterministic; writes nothing."""
    from rlvr import consolidated_ledger  # noqa: PLC0415 — lazy
    rows = [r for r in consolidated_ledger.read(ws, "settlement")
            if r.get("schema") == ROW_SCHEMA]
    sums: dict[str, dict] = {}
    for row in rows:
        s = str(row.get("strategy") or "self")
        cell = sums.setdefault(s, {"n": 0, "sum": 0.0})
        cell["n"] += 1
        cell["sum"] += float(row.get("reward") or 0.0)
    return {s: {"n": c["n"], "mean_reward": c["sum"] / c["n"]}
            for s, c in sorted(sums.items())}
