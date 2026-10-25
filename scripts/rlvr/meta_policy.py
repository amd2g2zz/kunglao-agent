# -*- coding: utf-8 -*-
"""meta_policy.py — the meta-policy learner face: commit selection
conditioned on the context vector, the cold-start prior, the three
knob groups, the envelope block (the single dispatch interface), and
the utility-chain measurement.

The commit choice is the loop's decision point: WHICH commit action
(the six-commit vocabulary — select / persist / tune / switch / verify
/ deliver) the orchestrator/worker takes next. Selection reads the P1
value table (`pool_indexer.value_table` — the pool's derived view,
never a store): every commit action is scored by the reward/cost
statistics of pool episodes whose context features OVERLAP the current
vector (deterministic overlap weighting, n-shrinkage toward the prior).

THE COLD-START PRIOR — `cold_start_prior` is the ONLY face on the
meta-policy path that consults the family bandit statistics: the
shrunk family posterior mean tilts the persist/switch axis (a winning
family favors persisting; a losing one favors switching) and exogenous
dynamic-constraint features tilt tune down. Until the pool has
coverage the prior IS the policy — the bandit's demoted role
(contextual successor: #806 axis). No dispatch face consults the
bandit alone; the demotion is grep-pinned by
tests/test_meta_policy_825.py.

THE THREE KNOBS (only these are learnable; everything else is
principled structure):
  (a) value-table weights  W_REWARD / W_COST / W_PRIOR / N_SHRINK
  (b) utility-score weights  W_CITATION / W_RETRIEVAL
  (c) retrieval threshold/count (the context budget)  RETRIEVE_MAX /
      MIN_UTILITY
plus the two component-ablation switches (RETRIEVAL / VALUE_TABLE =
0). Env-overridable, documented defaults, nothing fitted at runtime.

`envelope_block` builds the meta-policy block of the dispatch envelope
(schema `meta-policy/1`: commit + context + budget) — the SINGLE
interface the executor receives; `render_block` is its prompt-side
text face. The utility chain (retrieved -> cited -> improved) is
measured on the episode via `stamp_retrieved` / `record_citation` /
`utility_chain` (additive optional fields the episode/1 validator
tolerates).

Zero telemetry points (Standard 11): refusals raise to the caller;
nothing emits. No storage: every value traces to the pool or the
bandit read faces at call time.
"""
from __future__ import annotations

import os

from rlvr import episode_schema as es
from rlvr import meta_context as mc
from rlvr import pool_indexer

#: the decision points and the action menu each one chooses over
#: (the attribution three-way persist/tune/switch IS the commit-boundary
#: action space; episode start selects the approach)
PHASE_ACTIONS: dict[str, tuple[str, ...]] = {
    "episode_start": ("select",),
    "commit_boundary": ("persist", "tune", "switch"),
    "blocked": ("persist", "tune", "switch"),
}

#: prior constants (documented policy constants, not fitted)
DYN_SHIFT = 0.25     # the dynamic-constraint penalty on `tune`

ENVELOPE_SCHEMA = "meta-policy/1"
RENDER_MARKER = "kunglao meta-policy"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value == value else default  # NaN -> default


def _env_int(name: str, default: int) -> int:
    value = _env_float(name, float(default))
    return max(0, int(value))


def knobs() -> dict:
    """The three learnable knob groups + the ablation switches, read
    from the environment with documented defaults."""
    return {
        # (a) value-table weights
        "w_reward": _env_float("KUNGLAO_META_W_REWARD", 1.0),
        "w_cost": _env_float("KUNGLAO_META_W_COST", 0.5),
        "w_prior": _env_float("KUNGLAO_META_W_PRIOR", 1.0),
        "n_shrink": _env_float("KUNGLAO_META_N_SHRINK", 4.0),
        # (b) utility-score weights
        "w_citation": _env_float("KUNGLAO_META_W_CITATION", 2.0),
        "w_retrieval": _env_float("KUNGLAO_META_W_RETRIEVAL", 1.0),
        # (c) retrieval threshold / count (the context budget)
        "retrieve_max": _env_int("KUNGLAO_META_RETRIEVE_MAX", 3),
        "min_utility": _env_float("KUNGLAO_META_MIN_UTILITY", 0.0),
        # component-ablation switches (exact "0" = the component off)
        "retrieval": os.environ.get("KUNGLAO_META_RETRIEVAL", "1") != "0",
        "value_table": os.environ.get("KUNGLAO_META_VALUE_TABLE",
                                      "1") != "0",
        # the four-knob component-ablation set (the P3 switches)
        "attribution": os.environ.get("KUNGLAO_META_ATTRIBUTION",
                                      "1") != "0",
        "playbook": os.environ.get("KUNGLAO_META_PLAYBOOK", "1") != "0",
    }


def cold_start_prior(ws, features: list[str], *,
                     family: str | None = None) -> dict[str, float]:
    """The cold-start prior over the six commits: the family bandit's
    shrunk posterior mean tilts persist/switch; exogenous dynamic
    constraints tilt tune down. THE ONLY bandit consult on the meta
    path — a demoted prior, never a central dispatch decision."""
    prior: dict[str, float] = {a: 0.0 for a in es.COMMIT_ACTIONS}
    if family:
        from rlvr import q_cells as _bandit  # the confined consult
        success = failure = 0.0
        try:
            fold = _bandit.fold(_bandit.default_store(ws))
            success, failure = fold.family_mass(str(family))
        except Exception:  # noqa: BLE001 — a broken bandit is a zero prior
            success, failure = 0.0, 0.0
        mean = (1.0 + float(success)) / (2.0 + float(success)
                                         + float(failure))
        delta = abs(mean - 0.5) * 2.0
        if delta > 0.0:
            if mean > 0.5:  # a winning family favors persisting
                prior["persist"] += delta
                prior["switch"] -= delta
            else:           # a losing one favors switching
                prior["switch"] += delta
                prior["persist"] -= delta
    if mc.is_dynamic_constrained(features) \
            or mc.has_dynamic_capability_failure(features):
        prior["tune"] -= DYN_SHIFT
    return prior


def _overlap_weight(cell_features: tuple[str, ...],
                    features: list[str]) -> float:
    """Deterministic cell weight: the fraction of the cell's feature
    tuple present in the current vector (0 = no evidence transfer)."""
    if not cell_features:
        return 0.0
    want = {str(f) for f in features}
    have = {str(f) for f in cell_features}
    return len(want & have) / len(have)


def select_commit(ws, features: list[str], *, family: str | None = None,
                  actions: tuple[str, ...] | None = None) -> dict:
    """The context-conditional commit selection: value-table scores
    (overlap-weighted, n-shrunk toward the prior) over `actions`
    (default: the full six-commit vocabulary, canonical order)."""
    k = knobs()
    features = [str(f) for f in features or []]
    actions = tuple(actions) if actions else es.COMMIT_ACTIONS
    prior = cold_start_prior(ws, features, family=family)

    scores = {a: 0.0 for a in actions}
    source = "prior"
    if k["value_table"]:
        table = pool_indexer.value_table(ws)
        stats: dict[str, dict] = {a: {"wn": 0.0, "sr": 0.0, "sc": 0.0}
                                  for a in actions}
        for (cell_features, action), cell in table.items():
            if action not in stats:
                continue
            weight = _overlap_weight(cell_features, features)
            if weight <= 0.0:
                continue
            row = stats[action]
            row["wn"] += weight * float(cell["n"])
            row["sr"] += weight * float(cell["n"]) \
                * float(cell["mean_reward"])
            row["sc"] += weight * float(cell["n"]) \
                * float(cell["mean_cost"])
        covered = False
        for action in actions:
            row = stats[action]
            n_eff = row["wn"]
            if n_eff <= 0.0:
                # zero coverage: the prior IS the score at conf = 0
                scores[action] = k["w_prior"] * prior.get(action, 0.0)
                continue
            covered = True
            conf = n_eff / (n_eff + max(k["n_shrink"], 1e-9))
            empirical = (k["w_reward"] * (row["sr"] / n_eff)
                         - k["w_cost"] * (row["sc"] / n_eff))
            scores[action] = (conf * empirical
                              + (1.0 - conf) * k["w_prior"]
                              * prior.get(action, 0.0))
        source = "value_table" if covered else "prior"
    else:
        source = "prior_ablated"
        for action in actions:
            scores[action] = k["w_prior"] * prior.get(action, 0.0)

    order = {a: i for i, a in enumerate(es.COMMIT_ACTIONS)}
    best = min(actions, key=lambda a: (-scores[a], order.get(a, 99)))
    return {"action": str(best), "scores": {a: scores[a] for a in actions},
            "source": source, "features": features}


# ------------------------------------------------------- envelope face

def episode_phase(ws, claim) -> str:
    """The dispatch-time phase rule: a claim with no pool episode yet is
    at episode_start (the pattern-recognition retrieval); a claim whose
    episode exists is AT a commit boundary (the persist/tune/switch
    decision rides the retrieved evidence)."""
    from rlvr import episode_pool  # noqa: PLC0415 — lazy, in-package
    if episode_pool.episode_path(ws, str(claim)).is_file():
        return "commit_boundary"
    return "episode_start"


def envelope_block(ws, claim, *, phase: str, family: str | None = None) \
        -> dict:
    """THE SINGLE dispatch interface (schema meta-policy/1): commit
    selection + retrieved context + the context budget, the block the
    kunglao_dispatch envelope carries to the executor."""
    if phase not in PHASE_ACTIONS:
        raise ValueError(
            f"envelope_block: phase {phase!r} not in "
            f"{sorted(PHASE_ACTIONS)}")
    k = knobs()
    features = mc.assemble(ws)
    selection = select_commit(ws, features, family=family,
                              actions=PHASE_ACTIONS[phase])
    from rlvr import meta_retrieval  # noqa: PLC0415 — lazy (cycle-free)
    context = meta_retrieval.assemble(ws, features, phase=phase, knobs=k)
    block = {"schema": ENVELOPE_SCHEMA,
             "claim": str(claim),
             "phase": phase,
             "features": features,
             "commit": {"action": selection["action"],
                        "scores": selection["scores"],
                        "source": selection["source"]},
             "context": context}
    # the additive P3 enrichment: the dead-path reading, the surprise
    # re-examination, and the tune/switch contract fields. enrich_block
    # is itself fail-open (it never raises into the dispatch path) —
    # the episode_start select face stays exactly the P2 shape.
    from rlvr import commit_semantics  # noqa: PLC0415 — lazy
    block = commit_semantics.enrich_block(ws, claim, block)
    return block


def render_block(block: dict) -> str:
    """The prompt-side text face of the envelope block (the marker the
    executor greps). Deterministic; summaries only."""
    commit = block.get("commit") or {}
    lines = [f"[{RENDER_MARKER}] claim={block.get('claim')} "
             f"phase={block.get('phase')} "
             f"commit={commit.get('action')} "
             f"(source={commit.get('source')})"]
    # the additive P3 faces (rendered only when present)
    attribution = commit.get("attribution") or {}
    if attribution:
        lines.append(f"attribution: available={attribution.get('available')} "
                     f"method={attribution.get('method')} "
                     f"ref={attribution.get('ref')}")
    tune = commit.get("tune") or {}
    if tune:
        lines.append(f"tune: class={tune.get('class')} "
                     f"same_class={tune.get('same_class')} "
                     f"requires={','.join(tune.get('requires') or [])}")
    dead = commit.get("dead_path") or {}
    if dead:
        over = " OVER CAP" if dead.get("over_cap") else ""
        lines.append(f"dead-path: class={dead.get('class')} "
                     f"attempts={dead.get('attempts')}/{dead.get('cap')}"
                     f"{over}")
    reex = commit.get("reexamination") or {}
    if reex:
        lines.append(f"reexamination: {reex.get('summary') or ''}")
    features = block.get("features") or []
    if features:
        lines.append("features: " + ", ".join(str(f) for f in features))
    context = block.get("context") or {}
    cases = context.get("cases") or []
    for case in cases:
        summary = str(case.get("summary") or "")
        lines.append(f"case {case.get('claim')} "
                     f"(utility {float(case.get('utility') or 0.0):.2f})"
                     + (f" {summary}" if summary else ""))
    for group in context.get("playbook") or []:
        feats = ", ".join(str(f)
                          for f in group.get("context_features") or [])
        for fragment in group.get("fragments") or []:
            lines.append(f"playbook[{feats}]: {fragment}")
    if not cases and not context.get("playbook"):
        lines.append("cases: none (cold pool)")
    return "\n".join(lines)


# --------------------------------------------------- the utility chain

def stamp_retrieved(doc: dict, case_ids) -> dict:
    """Record the episode-start retrieved case ids on the episode (the
    chain's first link). Additive field; episode/1 tolerates it."""
    doc["retrieved"] = [str(c) for c in (case_ids or [])]
    return doc


def record_citation(doc: dict, seq: int, case_ids) -> dict:
    """Record the cited case ids on ONE commit entry (the chain's
    second link). Refuses an unknown seq."""
    for commit in doc.get("commits") or []:
        if commit.get("seq") == seq:
            commit["cited"] = [str(c) for c in (case_ids or [])]
            return doc
    raise ValueError(f"record_citation: no commit seq={seq!r}")


def utility_chain(doc: dict) -> dict:
    """The tracked chain retrieved -> cited -> outcome-improved: the
    utility measurement that feeds the knob learning."""
    retrieved = {str(c) for c in doc.get("retrieved") or []}
    cited: set[str] = set()
    for commit in doc.get("commits") or []:
        cited.update(str(c) for c in (commit.get("cited") or []))
    r = (doc.get("reward") or {}).get("r")
    improved = isinstance(r, (int, float)) \
        and not isinstance(r, bool) and float(r) > 0.0
    return {"retrieved": len(retrieved), "cited": len(cited),
            "cited_from_retrieved": len(cited & retrieved),
            "improved": improved}
