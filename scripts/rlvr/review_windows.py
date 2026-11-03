# -*- coding: utf-8 -*-
"""rlvr/review_windows.py — the three-window review + attribution bridge
(card P3 of the learning-loop live-wire program).

Learning without reviewing one's own trajectory is blind writing; a
terminal label without attribution is a weak signal. This module is the
retrospective half of the loop: it reads a validated `step/1`
trajectory through step_record's three windows (CALLED, never
re-implemented) and turns the review into landed attribution rows.

The three windows:
  - ``index_window`` — the action->conclusion table (the
    what-did-we-try ledger) with the tried-action list, so the next
    action cannot quietly repeat a refuted one;
  - ``segment_window`` — last confirmed anchor -> deviation (the
    what-broke-and-why window); THE primary source for attribution;
  - ``tree_window`` — the alive-hypothesis chain (the belief-state
    replay), with an optional delta against a prior episode's final
    belief state (new / died / carried — the delta is the only thing
    worth writing about a known family).

The attribution bridge (the owner's model): method memory eats STEP
rewards, strategy memory eats the MISSION reward plus its attribution —
a verified technique in a failed mission still enters the pool, while
the strategy face answers for the chaining decision. The two ledgers
stay separate by construction: ``land_attributions`` writes one
``method_memory`` row whose signals carry step rewards only, and one
``strategy_memory`` row whose signals carry the mission reward only.

Hard rules, all refusing loudly via ``AttributionRefused``:
  - anchored: an attribution must cite trajectory anchors (step-index
    refs plus the hypothesis identities the conclusion itself cites) —
    the P1 validator's contraction rule is the single source;
  - falsifiable: every landed attribution states the condition a
    future step or mission could use to refute it (following the
    lesson and failing the same way marks the attribution itself down
    — meta-learning on attribution). A contraction-quiet step is
    neutral, states no falsifier, and never lands;
  - 已会零写: when the pool's memory face says the family is already
    mastered (pool_scheduler.retire_reasons, called not modified), the
    review writes NOTHING — learning is a means, not the goal;
  - idempotent: landing rides ledger.record's dedupe, so a second
    landing over the same mission appends no rows.
"""
from __future__ import annotations

from rlvr import ledger
from rlvr import pool_scheduler
from rlvr import step_record

#: the two ledger kinds this bridge owns (open-enum, registered below)
KIND_METHOD = "method_memory"
KIND_STRATEGY = "strategy_memory"

#: signal source stamp on every landed signal
SOURCE = "review_windows/1"

ledger.register_kind(KIND_METHOD,
                     "step-reward attribution rows (review bridge, P3)")
ledger.register_kind(KIND_STRATEGY,
                     "mission-reward attribution rows (review bridge, P3)")


class AttributionRefused(ValueError):
    """A review face refuses to attribute or to land. The message names
    the missing anchor, the absent falsifier, or the missing reward
    (fail-closed, machine-readable)."""


# ------------------------------------------------------------- windows

def index_window(steps) -> dict:
    """The what-did-we-try ledger: step_record's index_view plus the
    ordered tried-action list and the actions tried more than once
    (the anti-repetition face). Pure; no mutation."""
    rows = step_record.index_view(steps)
    seen: list[str] = []
    for r in rows:
        action = str(r.get("action") or "")
        if action and action not in seen:
            seen.append(action)
    counts: dict[str, int] = {}
    for r in rows:
        action = str(r.get("action") or "")
        counts[action] = counts.get(action, 0) + 1
    repeated = [a for a in seen if counts[a] > 1]
    return {"rows": rows, "tried_actions": seen, "repeated": repeated}


def segment_window(steps) -> dict | None:
    """The what-broke-and-why window: step_record's segment (last
    confirmed anchor -> deviation) with the step indices re-attached.
    None when the trajectory holds no confirmed anchor."""
    seg = step_record.segment_view(steps)
    if seg is None:
        return None
    rows = [{"i": seg["anchor"] + k, "action": s.get("action"),
             "conclusion": s.get("conclusion")}
            for k, s in enumerate(seg["steps"])]
    return {"anchor": seg["anchor"], "deviation": seg["deviation"],
            "rows": rows}


def tree_window(steps, prior_alive=None) -> dict:
    """The belief-state replay: step_record's tree_view chain, the final
    alive set, and — when a prior episode's belief state is given — the
    only delta worth writing: hypotheses new to this trajectory, ones
    the prior held that this one killed, and ones carried through."""
    chain = step_record.tree_view(steps)
    alive = chain[-1]["alive"] if chain else []
    out = {"chain": chain, "alive": list(alive), "delta": None}
    if prior_alive is not None:
        prior = [str(a) for a in prior_alive]
        out["delta"] = {
            "new": [a for a in alive if a not in prior],
            "died": [a for a in prior if a not in alive],
            "carried": [a for a in alive if a in prior],
        }
    return out


# --------------------------------------------------------- attribution

def _cite_identities(step: dict) -> list[str]:
    """The hypothesis identities this step's conclusion cites, in
    registry order — the mechanical anchor test (word-bounded id, or
    salient claim terms), borrowed from step_record's own faces."""
    conclusion = str(step.get("conclusion") or "")
    cterms = step_record._salient_terms(conclusion)
    cited: list[str] = []
    for hyp in step.get("hypotheses") or []:
        if not isinstance(hyp, dict):
            continue
        ident = step_record._hyp_identity(hyp)
        if not ident or ident in cited:
            continue
        if step_record._id_in_text(ident, conclusion) or \
                step_record._salient_terms(
                    step_record._hyp_claim(hyp)) & cterms:
            cited.append(ident)
    return cited


def _falsifier_text(verdict: str, cited: list[str], step: dict) -> str | None:
    """The stated condition a future step could refute this attribution
    with: the cited hypothesis's own kill-experiment clause, bound to
    the step's reusable-when conditions."""
    if verdict == "neutral" or not cited:
        return None
    kills = []
    for hyp in step.get("hypotheses") or []:
        if not isinstance(hyp, dict):
            continue
        ident = step_record._hyp_identity(hyp)
        if ident not in cited:
            continue
        kill = step_record._first_str(
            hyp, step_record._KILL_KEYS) or "its kill test"
        kills.append(f"{ident}: {kill}")
    conditions = "; ".join(str(c) for c in step.get("reusable_when") or [])
    if verdict == "gain":
        return ("kill test bound to this gain — if a later step runs "
                f"({'; '.join(kills)}) and it passes under the same "
                f"conditions ({conditions}), the hypothesis dies and "
                "this gain attribution is wrong")
    return ("kill test bound to this refutation — if a later step shows "
            f"({'; '.join(kills)}) passing after all under the same "
            f"conditions ({conditions}), the hypothesis revives and this "
            "refutation is wrong")


def attribute_step(step, index=None) -> dict:
    """Attribute ONE validated step. verdict is 'refutation' when the
    conclusion carries a refute marker (contradiction outranks), 'gain'
    when only a confirm marker fires, 'neutral' when it decides
    nothing. Anchors cite the step's index and the hypothesis identities
    the conclusion itself references; the falsifier names the kill
    experiment that a future step could turn against this attribution.
    A neutral step states no falsifier — it is honest noise, never
    landed. Refuses (AttributionRefused) a step that cites no
    hypothesis of its own."""
    try:
        step_record.validate_step(step)
    except step_record.StepRecordError as exc:
        raise AttributionRefused(str(exc)) from exc
    conclusion = str(step.get("conclusion") or "")
    if step_record._REFUTE_RE.search(conclusion):
        verdict = "refutation"
    elif step_record._CONFIRM_RE.search(conclusion):
        verdict = "gain"
    else:
        verdict = "neutral"
    cited = _cite_identities(step)
    if not cited:
        raise AttributionRefused(
            "attribution refused: the conclusion cites none of the "
            "step's hypotheses — no anchor, nothing to attribute")
    anchors = []
    if index is not None:
        anchors.append(f"step-{index}")
    anchors.extend(cited)
    return {"verdict": verdict, "anchors": anchors,
            "falsifiable": verdict != "neutral",
            "falsifier": _falsifier_text(verdict, cited, step)}


def _mission_reward(episode: dict) -> float:
    """The settled mission reward: the stamped float, else the reward
    block's r. Nothing else counts — the strategy face eats the MISSION
    reward, so an episode without one refuses."""
    reward = episode.get("reward")
    if isinstance(reward, (int, float)) and not isinstance(reward, bool):
        return float(reward)
    block = episode.get("reward_block") or {}
    r = block.get("r") if isinstance(block, dict) else None
    if isinstance(r, (int, float)) and not isinstance(r, bool):
        return float(r)
    raise AttributionRefused(
        "episode carries no mission reward — the strategy face eats the "
        "mission reward, refusing to attribute without it")


def attribute_mission(steps, episode: dict) -> dict:
    """Attribute a WHOLE mission. The METHOD face is one entry per
    non-neutral step, each carrying that step's own reward; the
    STRATEGY face is one entry carrying the mission reward and the
    segment verdict (refutation when the mission failed, gain when it
    completed), anchored inside the suspect segment — never on the
    preparation steps. Refuses a trajectory with no confirmed anchor
    (nothing to cite) and an episode without a mission reward."""
    if not isinstance(episode, dict):
        raise AttributionRefused("episode: not a mapping")
    steps = list(steps)
    mission = str(episode.get("id") or episode.get("claim") or "").strip()
    if not mission:
        raise AttributionRefused("episode: no id or claim to anchor the "
                                 "attribution to")
    segment = segment_window(steps)
    if segment is None:
        raise AttributionRefused(
            "trajectory holds no confirmed anchor — the strategy "
            "attribution has nothing to cite, refusing")
    method: list[dict] = []
    for i, step in enumerate(steps):
        a = attribute_step(step, index=i)
        if a["verdict"] == "neutral":
            continue
        a["i"] = i
        a["reward"] = float((step.get("reward") or {}).get("value") or 0.0)
        method.append(a)
    completed = str((episode.get("outcome") or {}).get("status")
                    or "").strip().casefold() == "completed"
    anchor_step = steps[segment["anchor"]]
    strategy = {
        "verdict": "gain" if completed else "refutation",
        "anchors": [f"step-{segment['anchor']}"]
        + ([f"step-{segment['deviation']}"]
           if segment["deviation"] is not None
           else [f"step-{len(steps) - 1}"]),
        "falsifiable": True,
        "falsifier": _falsifier_text(
            "gain" if completed else "refutation",
            _cite_identities(anchor_step), anchor_step),
        "reward": _mission_reward(episode),
        "segment": {"anchor": segment["anchor"],
                    "deviation": segment["deviation"]},
    }
    return {"mission": mission,
            "claim": str(episode.get("claim") or mission),
            "method_attribution": method,
            "strategy_attribution": strategy}


# ------------------------------------------------------------- landing

def _require_landable(attribution: dict) -> None:
    """Every landed entry must be falsifiable and anchored — checked
    BEFORE any write, so a refusal leaves no half-landed rows."""
    if not isinstance(attribution, dict):
        raise AttributionRefused("attribution: not a mapping")
    method = attribution.get("method_attribution")
    strategy = attribution.get("strategy_attribution")
    if not isinstance(method, list) or not method:
        raise AttributionRefused(
            "attribution: no method entries — nothing falsifiable to "
            "land")
    if not isinstance(strategy, dict):
        raise AttributionRefused("attribution: no strategy entry")
    for entry in list(method) + [strategy]:
        if not isinstance(entry, dict) or not entry.get("falsifiable"):
            raise AttributionRefused(
                "attribution refused: an entry states no falsifiable "
                "condition — a future step could neither confirm nor "
                "kill it, so it never lands")
        if not entry.get("anchors"):
            raise AttributionRefused(
                "attribution refused: an entry cites no trajectory "
                "anchors")


def land_attributions(ws, attribution: dict, family: str = "",
                      pool_state: dict | None = None,
                      ts: str | None = None) -> dict:
    """Land a mission's attribution through the ledger's ONE write
    face: a method_memory identity row (step-reward signals only) and a
    strategy_memory row (mission-reward signal only). The family's
    memory face is consulted first — an already-mastered family writes
    NOTHING. Idempotent through record()'s dedupe: relanding the same
    attribution appends no rows."""
    _require_landable(attribution)
    if pool_state is not None and str(family).strip():
        reason = pool_scheduler.retire_reasons(
            {"family": str(family)}, pool_state)
        if reason == "learned":
            return {"written": 0, "reason": "already-mastered",
                    "method": None, "strategy": None}
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    ts = ts or utc_now_z()
    mission = str(attribution.get("mission") or "")
    anchor = str(attribution.get("claim") or mission)
    method_signals = [
        {"type": f"step_{e['verdict']}", "source": SOURCE,
         "value": float(e["reward"]), "ts": ts, "i": e["i"],
         "anchors": list(e["anchors"]), "falsifier": e["falsifier"]}
        for e in attribution["method_attribution"]]
    strategy = attribution["strategy_attribution"]
    strategy_signals = [{
        "type": "mission_attribution", "source": SOURCE,
        "value": float(strategy["reward"]), "ts": ts,
        "verdict": strategy["verdict"],
        "anchors": list(strategy["anchors"]),
        "falsifier": strategy["falsifier"]}]
    method_row = ledger.record(ws, KIND_METHOD, anchor, method_signals,
                               rollout_id=f"method/{mission}", ts=ts)
    strategy_row = ledger.record(ws, KIND_STRATEGY, anchor,
                                 strategy_signals,
                                 rollout_id=f"strategy/{mission}", ts=ts)
    written = int(bool(method_row.get("appended"))) \
        + int(bool(strategy_row.get("appended")))
    return {"written": written, "reason": None,
            "method": method_row, "strategy": strategy_row}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
