# -*- coding: utf-8 -*-
"""Evidence settles by NEED (piece 3 of the reproduction-oracle card).

Owner ruling: replay success is NOT illegal — it is good evidence for a
DIFFERENT claim class; it was booked into the wrong account. This module
owns the booking:

  - acceptance-side observations (``replay-observation`` evidence class:
    "replay succeeded", "endpoint returned 200") may settle ONLY
    input-contract / param-sufficiency claims — questions whose ``need``
    is ``yes_no_with_evidence``;
  - generation-side propositions (the algorithm-class needs:
    ``model_selection``, ``protocol_description``) admit
    ``reproduction`` evidence ONLY;
  - a replay observation cited by an algorithm-class claim is
    RE-ROUTED to the input-contract claim and the algorithm claim
    STAYS OPEN.

The question's existing ``need`` field (primary_questions vocabulary,
shared with convergence_check) decides admissibility — the
caller passes the question-id -> need map; nothing new is derived from
user vocabulary here.
"""
from __future__ import annotations

REPLAY_OBSERVATION_CLASS = "replay-observation"
REPRODUCTION_CLASS = "reproduction"

#: needs whose claims are input-contract / param-sufficiency propositions:
#: an acceptance-side observation is admissible evidence for them.
INPUT_CONTRACT_NEEDS = ("yes_no_with_evidence",)

#: needs whose claims are generation-side propositions: only reproduction
#: evidence settles them.
GENERATION_SIDE_NEEDS = ("model_selection", "protocol_description")

#: where a mis-booked replay observation goes instead.
INPUT_CONTRACT_ROUTE = "input-contract"


def _need_for(claim: dict, questions: dict) -> str:
    qid = (claim or {}).get("answers_question")
    return str((questions or {}).get(qid) or "").strip()


def settle_attempt(claim: dict, observation: dict,
                   questions: dict) -> dict:
    """Decide whether one ``observation`` may settle one ``claim``.

    ``questions`` maps question id -> need (the task_spec
    primary_questions map). Returns a routing decision dict::

        {"settled": bool, "claim_stays_open": bool,
         "reroute_to": str | None, "reason": str}

    - reproduction evidence settles generation-side and input-contract
      claims alike (it is the strict oracle);
    - a replay observation settles an input-contract claim;
    - a replay observation against a generation-side claim does NOT
      settle it: the claim stays open and the observation is re-routed
      to the input-contract account;
    - unknown evidence classes settle nothing (fail closed).
    """
    obs_class = str((observation or {}).get("class") or "").strip()
    need = _need_for(claim, questions)
    is_input_contract = need in INPUT_CONTRACT_NEEDS
    is_generation_side = need in GENERATION_SIDE_NEEDS
    base = {"settled": False, "claim_stays_open": True,
            "reroute_to": None, "reason": ""}

    if obs_class == REPRODUCTION_CLASS:
        return {**base, "settled": True, "claim_stays_open": False,
                "reason": ("reproduction evidence settles the "
                           f"{need or 'untyped'} claim (#248)")}

    if obs_class == REPLAY_OBSERVATION_CLASS:
        if is_input_contract:
            return {**base, "settled": True, "claim_stays_open": False,
                    "reason": ("acceptance-side observation settles an "
                               "input-contract claim "
                               f"(need={need}) (#248)")}
        if is_generation_side:
            return {**base, "settled": False, "claim_stays_open": True,
                    "reroute_to": INPUT_CONTRACT_ROUTE,
                    "reason": ("replay observation cannot settle a "
                               "generation-side proposition "
                               f"(need={need}) — re-routed to the "
                               "input-contract claim; the algorithm "
                               "claim stays open (#248)")}
        return {**base, "reason": (f"untyped need for the claim's "
                                   f"question — no admissibility "
                                   f"decision (#248)")}

    return {**base, "reason": (f"evidence class {obs_class!r} is not "
                               f"admissible here — claim stays open "
                               f"(#248)")}
