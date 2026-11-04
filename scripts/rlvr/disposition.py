# -*- coding: utf-8 -*-
"""rlvr/disposition.py — the episode disposition algebra.

Every rollout ends in exactly one **evidence-gated** disposition, assigned by
a total precedence (first match wins):

    SOLVED > OUT_OF_SCOPE > CENSORED_ENV > ATTEMPTED_EXHAUSTED >
    INFRA > FAILED > SURRENDER

The classifier is pure: no I/O, no model call, no clock. The caller assembles
the record (session fields, act outcomes, authorization, the route-attempt
ledger, wall evidence, the recorded strategic action) and persists the row
under ``runs/disposition/<episode>.json``; the consumer mapping (reward,
measurement, learning) reads the row, never a second classifier.

Record shape (absent keys read as None/False; ``authorized`` is REQUIRED and
must be a bool — a dispatch without authorization context is invalid):

    {
      "claim": str,
      "authorized": bool,
      "oracle_pass": bool,
      "wall": {"session_bound": bool, "corroborated": bool} | None,
      "ledger": {"routes": [str], "attempted": [str], "budget": number,
                 "budget_exhausted": bool} | None,
      "act_outcomes": [str],          # ordered; the LAST act terminated the episode
      "session": {"returncode": int | None, "timed_out": bool,
                  "liveness": "alive" | "dead" | None},
      "strategic_action": "FIGHT" | "BYPASS" | "INVEST" | None,
      "completion_claimed": bool,
    }

Evidence gates (spec: openspec/changes/redteam-tdd-bidirectional-critique/
specs/episode-disposition):
  SOLVED              oracle/verifier pass
  OUT_OF_SCOPE        authorization excludes the target
  CENSORED_ENV        session-bound AND corroborated environment wall
  ATTEMPTED_EXHAUSTED route ledger covers the declared routes, or budget out
  INFRA               the terminating act was refused by the environment
  FAILED              execution failure (timeout kill / nonzero exit /
                      liveness loss) or an unverified completion claim
  SURRENDER           authorized, in-scope, unfinished, and no earlier gate
"""
from __future__ import annotations

#: the closed disposition vocabulary, in precedence order (first match wins)
DISPOSITIONS = (
    "SOLVED",
    "OUT_OF_SCOPE",
    "CENSORED_ENV",
    "ATTEMPTED_EXHAUSTED",
    "INFRA",
    "FAILED",
    "SURRENDER",
)

#: the strategic vocabulary recorded before termination (the strategic face)
STRATEGIC_ACTIONS = ("FIGHT", "BYPASS", "INVEST")

#: the legacy session ladder classes the mapping table accepts
LEGACY_CLASSES = ("terminal", "censored_env", "agent_death")


def _result(disposition: str, gate: str) -> dict:
    """The classifier's return shape: the disposition plus the gate that
    matched (audit face; consumers branch on the disposition only)."""
    return {"disposition": disposition, "gate": gate}


def _wall_corroborated(wall) -> bool:
    """Censoring requires BOTH legs: the blocker is session-bound and the
    wall fact is corroborated by a harness-side check. One leg is not
    evidence (the anti-laundering rule in interruption.py). Flags are
    strict booleans — the string "false" is not corroboration."""
    if not isinstance(wall, dict):
        return False
    return wall.get("session_bound") is True and wall.get("corroborated") is True


def _ledger_exhausted(ledger) -> bool:
    """ATTEMPTED_EXHAUSTED needs the route ledger to cover every declared
    route, or the declared budget to be spent. A malformed ledger never
    counts as exhaustion (fail toward an honest gap): the budget flag
    pays only with a recorded positive budget beside route/attempt lists."""
    if not isinstance(ledger, dict):
        return False
    routes = ledger.get("routes")
    attempted = ledger.get("attempted")
    if not isinstance(routes, list) or not isinstance(attempted, list):
        return False
    if not routes:
        return False
    if ledger.get("budget_exhausted") is True:
        budget = ledger.get("budget")
        return (isinstance(budget, (int, float))
                and not isinstance(budget, bool) and budget > 0)
    return set(str(r) for r in routes) <= set(str(a) for a in attempted)


def _execution_failed(session) -> bool:
    """Timeout kill, nonzero exit, or a dead liveness verdict at exit."""
    if not isinstance(session, dict):
        return False
    if session.get("timed_out") is True:
        return True
    returncode = session.get("returncode")
    if returncode is not None and returncode not in (0,):
        return True
    return str(session.get("liveness") or "").strip().lower() == "dead"


def classify_episode(record: dict) -> dict:
    """Classify one episode -> {"disposition", "gate"}.

    Raises ValueError when ``authorized`` is missing or not a bool: the
    disposition contract starts with an explicit authorization context
    (a missing context must never be silently treated as authorized).
    """
    if not isinstance(record, dict):
        raise ValueError("disposition record must be a dict")
    authorized = record.get("authorized")
    if not isinstance(authorized, bool):
        raise ValueError(
            "disposition record requires an explicit bool `authorized`")

    # 1. SOLVED — an oracle/verifier pass outranks every other signal.
    if record.get("oracle_pass") is True:
        return _result("SOLVED", "oracle_pass")

    # 2. OUT_OF_SCOPE — the target is outside the declared authorization.
    if authorized is False:
        return _result("OUT_OF_SCOPE", "authorization")

    # 3. CENSORED_ENV — a session-bound AND corroborated wall.
    if _wall_corroborated(record.get("wall")):
        return _result("CENSORED_ENV", "wall")

    # 4. ATTEMPTED_EXHAUSTED — the ledger (or the budget) is complete.
    if _ledger_exhausted(record.get("ledger")):
        return _result("ATTEMPTED_EXHAUSTED", "route_ledger")

    # 5. INFRA — the terminating act was refused by the environment.
    outcomes = record.get("act_outcomes") or []
    if isinstance(outcomes, list) and outcomes:
        if str(outcomes[-1]).strip().upper() == "BLOCKED":
            return _result("INFRA", "blocked_act")

    # 6. FAILED — execution failure, or a completion claim without a pass.
    if _execution_failed(record.get("session")):
        return _result("FAILED", "execution_failure")
    if record.get("completion_claimed") is True:
        return _result("FAILED", "unverified_completion")

    # 7. SURRENDER — in-scope, unfinished, no earlier gate met.
    return _result("SURRENDER", "unfinished")


def legacy_disposition(session_class: str, oracle_pass: bool) -> str:
    """The published legacy map (session ladder -> disposition).

    terminal + pass -> SOLVED; terminal without a pass -> FAILED
    (unverified completion); censored_env -> CENSORED_ENV; agent_death ->
    FAILED. Unknown classes raise (fail closed).
    """
    cls = str(session_class or "").strip().lower()
    if cls == "terminal":
        return "SOLVED" if oracle_pass is True else "FAILED"
    if cls == "censored_env":
        return "CENSORED_ENV"
    if cls == "agent_death":
        return "FAILED"
    raise ValueError(f"unknown legacy session class: {session_class!r}")
