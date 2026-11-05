# -*- coding: utf-8 -*-
"""rlvr/direction.py — the oracle-probe density direction face (#954, Type-3).

Directions are FIRST-CLASS ARMS above method families: one Beta posterior
(α, β) per direction over "this direction pays", fed by mechanically
reconciled outcomes — a bandit-grade direction-value accumulator. NO
critic, NO learned judge, NO value function, NO in-flight retrieval (the
owner's 2026-11-02 rulings, hard). Claim-terminal reconciliation stays
the only reward authority; this layer only accumulates the direction
posterior the racing/elimination faces read.

The three faces:

  posterior arithmetic
      ``runs/direction-state.jsonl`` (the #958 censoring substrate —
      this module adds SIBLING row types to the shared file, it does
      not collide with ``direction-censor/1``):

        direction-register/1   {ts, direction, source, situation_tags,
                                alpha, beta}   — the prior + re-arm
        direction-obs/1        {ts, direction, outcome, reason?} — one
                                reconciled outcome (success | failure)
        direction-eliminate/1  {ts, direction, alpha, beta, mean,
                                reason}      — the racing elimination

      The posterior is a FOLD over the append-only rows (never a mutable
      tally that could drift from its own log — the censoring streak
      posture): the LAST register row rebases (α, β) and clears the
      counts (re-registration re-arms an eliminated direction), then
      each direction-obs row adds +1 to α (success) or β (failure).

  censoring (the #958 seam, MANDATORY)
      The observation feed routes through
      ``censoring.posterior_observations`` — ``censored: true`` rows
      drop out BEFORE any update, by construction. A direction with a
      trailing censor streak at K is FROZEN (``censoring.frozen``): it
      is never eliminated and never raceable; a live observation row
      breaks the freeze.

  per-step credit + racing elimination
      ``step_credit_delta`` wraps ``probe_face.probe_delta`` (THE ΔV
      seam — the direction face wires nowhere else): per-step credit =
      ΔV of the unit's mechanical probe reading. ``observe_step`` banks
      the deltas in-process; ``settle_step`` at claim-terminal converts
      the banked total into ONE outcome observation (total ΔV > 0 ->
      success, < 0 -> failure, flat/empty -> silence). Elimination
      (``maybe_eliminate``) fires ONLY on posterior collapse
      (``collapse``): β mass strictly above COLLAPSE_BETA_MASS with the
      posterior mean strictly below COLLAPSE_MEAN_FLOOR — and a
      direction with NO failure observations is NEVER eliminated (the
      anti-premature-surrender leg: racing must not kill silent-true
      arms, #951 config 4's lesson).

Loop integration is FLAG-GATED: ``KUNGLAO_DIRECTION=1`` enables the
face (default OFF — zero behavior change; exact "1", the feature_prior
convention inverted). When ON: ``maybe_register`` seeds directions at
rollout init (playbook groups first — the #960 situation features;
else the task_spec primary questions), ``on_step`` prices each probe
milestone, ``on_claim_terminal`` settles the bank and races the
elimination gate (one stderr line + one direction-eliminate/1 row).
An exogenous env death never reaches on_claim_terminal — the loop
records ``censoring.observe_censored`` and the posterior stays silent.

stdlib + PyYAML only (house eval-script rule).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from kunglao_log import iter_jsonl, warn

from _common import seq_sum  # the canonical leaf (the q_cells precedent)

from rlvr import censoring  # the shared substrate + the mandatory filter
from rlvr import learning_seal as _seal  # #799: the row seal
from rlvr import probe_face  # THE ΔV seam (consumed, never modified)

#: the single activation flag (default OFF — the inert-landing discipline)
FLAG_ENV = "KUNGLAO_DIRECTION"

#: sibling row types on the SHARED #958 state file (no schema collision:
#: censoring.state_rows filters to direction-censor/1 only, this module
#: filters to its own three stamps — one file, disjoint read faces)
SCHEMA_REGISTER = "direction-register/1"
SCHEMA_OBS = "direction-obs/1"
SCHEMA_ELIMINATE = "direction-eliminate/1"
DIRECTION_STATE_REL = censoring.DIRECTION_STATE_REL  # runs/direction-state.jsonl

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
_OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_FAILURE)

#: Beta(1,1) — the wide cold-start prior (the q_cells base precedent)
BASE_ALPHA = 1.0
BASE_BETA = 1.0

#: posterior collapse = the racing elimination gate. Policy constants
#: (NOT fitted; the ADR-001 governance pattern): β mass strictly above
#: 4.0 AND posterior mean strictly below 0.2 — with the BASE(1,1) prior
#: that is four net failures (α=1, β=5, mean 1/6). Both bounds are
#: EXCLUSIVE at the boundary (β == 4.0 or mean == floor never collapse).
COLLAPSE_BETA_MASS = 4.0
COLLAPSE_MEAN_FLOOR = 0.2

_SCHEMAS = (SCHEMA_REGISTER, SCHEMA_OBS, SCHEMA_ELIMINATE)

# in-process provisional step bank (#712 posture: provisional banking,
# claim-terminal reconciliation) — (ws, direction) -> [deltas]
_STEPS: dict[tuple[str, str], list[float]] = {}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ------------------------------------------------------------- boundaries

def enabled() -> bool:
    """The face is ON only when the declared switch parses true (default
    OFF — the flag-off tree is byte-inert: no rows, no stderr, no
    reads)."""
    import runtime_switches  # noqa: PLC0415 — leaf face, import-light
    return runtime_switches.get_bool(FLAG_ENV)


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415
    return utc_now_z()


def _clean_direction(direction) -> str:
    d = str(direction or "").strip()
    if not d:
        raise ValueError("rlvr.direction: direction must be non-empty")
    return d


def _slug(value) -> str:
    """Dependency-light redeclaration of meta_context.slug (the
    TERMINAL_FACT_STATUSES precedent): lowercase, non-alnum -> '-'."""
    return _SLUG_RE.sub("-", str(value or "").lower()).strip("-")


def _num(value, fallback: float) -> float:
    """Fail-closed prior read: a non-numeric/non-positive register field
    falls back to the base (a forged/malformed prior cannot go negative)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    v = float(value)
    return v if v > 0.0 else fallback


def _finite(x) -> float:
    """Fail-closed step-delta normalization: non-numeric / NaN / ±inf
    banks 0.0 (a broken reading prices work at zero, never a guess)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return 0.0
    v = float(x)
    return v if v == v and v not in (float("inf"), float("-inf")) else 0.0


def _normalize_outcome(outcome) -> str:
    if outcome is True:
        return OUTCOME_SUCCESS
    if outcome is False:
        return OUTCOME_FAILURE
    oc = str(outcome or "").strip().lower()
    if oc in _OUTCOMES:
        return oc
    raise ValueError(
        f"rlvr.direction: outcome must be a bool or one of "
        f"{list(_OUTCOMES)}, got {outcome!r:.60}")


# ------------------------------------------------------------- store faces

def _append_row(ws, row: dict) -> bool:
    """The censoring append tail, mirrored: #799 seal + O_APPEND write,
    ONE warn on refusal, never a raise into the producer."""
    try:
        path = Path(ws) / DIRECTION_STATE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        row = _seal.sign_row(row)
        import json
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except OSError as exc:
        warn("rlvr.direction", f"append failed: {type(exc).__name__}: {exc}")
        return False


def state_rows(ws) -> list[dict]:
    """This module's rows from the shared state file, append order
    (fail-open read; the #799 learner read face — armed, only seal-valid
    rows survive). The #958 direction-censor/1 rows are NOT returned:
    they belong to censoring's read face."""
    path = Path(ws) / DIRECTION_STATE_REL
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
        rows = [row for row in iter_jsonl(lines, source="rlvr.direction")
                if isinstance(row, dict) and row.get("schema") in _SCHEMAS]
    except OSError as exc:
        warn("rlvr.direction", f"read failed: {exc}")
        return []
    return _seal.trusted_rows(rows, op="rlvr.direction.state_rows")


def observations(ws) -> list[dict]:
    """THE MANDATED #958 SEAM: every posterior consumer reads through
    ``censoring.posterior_observations`` — censored rows drop out HERE,
    before any update, by construction (a censored sample updates
    nothing: no Beta draw, no failure mass)."""
    return censoring.posterior_observations(state_rows(ws))


# ------------------------------------------------------------- the faces

def new_direction(ws, direction: str, *, source: str = "",
                  situation_tags=(), alpha: float = BASE_ALPHA,
                  beta: float = BASE_BETA, ts=None) -> dict:
    """Register one direction: the direction-register/1 row carrying its
    Beta prior + situation tags (the #960 playbook features, when the
    seed came from there). Re-registration REBASES: the fold takes the
    last register row as the prior and drops the accumulated counts —
    the re-arm face an eliminated direction returns through."""
    d = _clean_direction(direction)
    row = {
        "schema": SCHEMA_REGISTER,
        "ts": ts or _now(),
        "direction": d,
        "source": str(source or ""),
        "situation_tags": [_slug(t) for t in (situation_tags or ())
                           if str(t).strip()],
        "alpha": _num(alpha, BASE_ALPHA),
        "beta": _num(beta, BASE_BETA),
    }
    return {"appended": _append_row(ws, row), "row": row}


def observe_outcome(ws, direction: str, outcome, *, reason=None,
                    ts=None) -> dict:
    """One reconciled outcome: +1 α (success) or +1 β (failure) at the
    fold. ``outcome`` accepts a bool or the closed string vocabulary —
    anything else is a ValueError (the boundary never invents a
    vocabulary entry). A real observation also appends the #958 seam's
    ``censored: false`` live-marker row (``censoring.observe_live``) —
    the counterpart that breaks the direction's trailing censor run,
    completing the freeze semantics."""
    d = _clean_direction(direction)
    row = {
        "schema": SCHEMA_OBS,
        "ts": ts or _now(),
        "direction": d,
        "outcome": _normalize_outcome(outcome),
        "reason": str(reason) if reason else None,
    }
    out = {"appended": _append_row(ws, row), "row": row}
    censoring.observe_live(ws, d)
    return out


def fold(ws, direction: str, rows=None) -> dict:
    """The raw fold: ``{alpha, beta, success, failure}`` over the
    censored-filtered rows (the LAST register row rebases). Pure over
    an explicit ``rows`` list when supplied (still censor-filtered —
    the seam is not bypassable)."""
    d = _clean_direction(direction)
    rows = censoring.posterior_observations(
        state_rows(ws) if rows is None else list(rows))
    alpha = beta = None
    success = failure = 0.0
    for row in rows:
        if str(row.get("direction") or "").strip() != d:
            continue
        schema = row.get("schema")
        if schema == SCHEMA_REGISTER:
            alpha = _num(row.get("alpha"), BASE_ALPHA)
            beta = _num(row.get("beta"), BASE_BETA)
            success = failure = 0.0
        elif schema == SCHEMA_OBS:
            oc = str(row.get("outcome") or "")
            if oc == OUTCOME_SUCCESS:
                success += 1.0
            elif oc == OUTCOME_FAILURE:
                failure += 1.0
    if alpha is None:
        alpha, beta = BASE_ALPHA, BASE_BETA
    return {"alpha": round(alpha + success, 6),
            "beta": round(beta + failure, 6),
            "success": success, "failure": failure}


def posterior(ws, direction: str, rows=None) -> tuple[float, float]:
    """The direction's Beta posterior (α, β) — the fold's read face."""
    f = fold(ws, direction, rows)
    return (f["alpha"], f["beta"])


def collapse(ws, direction: str, *, rows=None,
             beta_mass: float = COLLAPSE_BETA_MASS,
             mean_floor: float = COLLAPSE_MEAN_FLOOR) -> bool:
    """The posterior-collapse predicate — the ONLY elimination signal.

    True iff the direction HAS failure observations (zero failure rows
    -> never collapsed: the anti-premature-surrender leg, a silent-true
    arm keeps the wide posterior and stays raceable), β is strictly
    above ``beta_mass``, and the posterior mean α/(α+β) is strictly
    below ``mean_floor``. Both bounds are exclusive at the boundary."""
    f = fold(ws, direction, rows)
    if f["failure"] <= 0.0:
        return False
    if f["beta"] <= beta_mass:
        return False
    return (f["alpha"] / (f["alpha"] + f["beta"])) < mean_floor


def raceable(ws, direction: str) -> bool:
    """The racing gate: not collapsed AND not censor-frozen (#955 — a
    frozen direction keeps its posterior and stops receiving budget,
    but is never eliminated)."""
    d = _clean_direction(direction)
    return not collapse(ws, d) and not censoring.frozen(ws, d)


def _eliminated_since_register(rows: list[dict], d: str) -> bool:
    """Idempotence read: a direction-eliminate/1 row with NO later
    register row means the direction is already out (a re-registration
    re-arms it)."""
    eliminated = False
    for row in rows:
        if str(row.get("direction") or "").strip() != d:
            continue
        if row.get("schema") == SCHEMA_REGISTER:
            eliminated = False
        elif row.get("schema") == SCHEMA_ELIMINATE:
            eliminated = True
    return eliminated


def maybe_eliminate(ws, direction: str, *, reason: str = "") -> bool:
    """Racing elimination, gated on posterior collapse ONLY. A frozen
    direction is never eliminated (#955: the freeze is not a verdict);
    a direction with no failure observations is never eliminated. Fires
    exactly one stderr line + one direction-eliminate/1 row (idempotent
    until a re-registration re-arms the direction)."""
    d = _clean_direction(direction)
    if censoring.frozen(ws, d):
        return False
    if not collapse(ws, d):
        return False
    if _eliminated_since_register(state_rows(ws), d):
        return True
    alpha, beta = posterior(ws, d)
    row = {
        "schema": SCHEMA_ELIMINATE,
        "ts": _now(),
        "direction": d,
        "alpha": alpha,
        "beta": beta,
        "mean": round(alpha / (alpha + beta), 6),
        "reason": str(reason or "posterior-collapse"),
    }
    appended = _append_row(ws, row)
    sys.stderr.write(
        f"[rlvr.direction] eliminated direction {d!r} "
        f"(posterior collapse: alpha={alpha}, beta={beta}, "
        f"reason={row['reason']}, appended={appended})\n")
    return True


# --------------------------------------------- per-step credit (the seam)

def step_credit_delta(ws, t0_reading, t1_reading) -> float:
    """THE direction-level per-step credit: ΔV of the unit's mechanical
    probe face — a pure wrap of ``probe_face.probe_delta`` (the ONE
    seam; this module modifies nothing behind it)."""
    return probe_face.probe_delta(ws, t0_reading, t1_reading)


def observe_step(ws, direction: str, delta) -> dict:
    """Bank one per-direction step delta (provisional, in-process —
    the #712 step-bank posture). Writes NOTHING: the state file only
    ever carries claim-terminal outcomes."""
    d = _clean_direction(direction)
    bank = _STEPS.setdefault((str(ws), d), [])
    bank.append(_finite(delta))
    return {"direction": d, "delta": bank[-1],
            "steps": len(bank), "total": round(seq_sum(bank), 6)}


def step_tally(ws, direction: str) -> dict:
    """The banked-tally read face (no consumption): {steps, total}."""
    bank = _STEPS.get((str(ws), _clean_direction(direction)), [])
    return {"steps": len(bank), "total": round(seq_sum(bank), 6)}


def settle_step(ws, direction: str, *, reason=None) -> dict:
    """Claim-terminal reconciliation: the banked ΔV total becomes ONE
    outcome observation — total > 0 -> success, < 0 -> failure, flat or
    empty -> SILENCE (no observation: a direction that moved the probe
    potential not at all updates nothing). Consumes the bank."""
    d = _clean_direction(direction)
    bank = _STEPS.pop((str(ws), d), [])
    if not bank:
        return {"settled": False, "reason": "no-steps", "direction": d}
    total = round(seq_sum(bank), 6)
    if total == 0.0:
        return {"settled": False, "reason": "flat",
                "steps": len(bank), "total": 0.0, "direction": d}
    outcome = OUTCOME_SUCCESS if total > 0 else OUTCOME_FAILURE
    why = reason or f"probe-dv total {total} over {len(bank)} steps"
    out = observe_outcome(ws, d, outcome, reason=why)
    return {"settled": True, "outcome": outcome, "steps": len(bank),
            "total": total, "appended": out["appended"], "direction": d}


# ----------------------------------------------------- loop integration

def _playbook_groups(ws) -> list[dict]:
    """The #960 playbook section face (lazy import — the #826 compressed
    view: quality-axiom groups with situation features). Seam for tests."""
    from rlvr import playbook  # noqa: PLC0415
    return playbook.compressed_view(ws)


def _question_seeds(ws) -> list[tuple[str, str, list[str]]]:
    """The fallback seed face: the task_spec primary questions — one
    direction per question id (the claim register's question spine)."""
    try:
        import yaml  # noqa: PLC0415 — probe_face already pins the dep
        spec = yaml.safe_load(
            (Path(ws) / "task_spec.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        spec = {}
    if not isinstance(spec, dict):
        spec = {}
    seeds: dict[str, tuple[str, str, list[str]]] = {}
    for q in spec.get("primary_questions") or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "").strip()
        if not qid:
            continue
        seeds[f"pq:{qid}"] = (f"pq:{qid}", "primary-question",
                              [f"pq-{_slug(qid)}"])
    return [seeds[k] for k in sorted(seeds)]


def _seed_directions(ws) -> list[tuple[str, str, list[str]]]:
    """Rollout-init seeds: playbook sections first (the #960 situation
    preconditions — a group's situation features ARE the direction's
    tags), else the primary questions. Groups without kept fragments
    are not directions (no method content). Deterministic order."""
    seeds: dict[str, tuple[str, str, list[str]]] = {}
    try:
        groups = _playbook_groups(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open: seeds never break init
        warn("rlvr.direction", f"playbook seed read failed: {exc}")
        groups = []
    for group in groups or []:
        feats = [_slug(t) for t in (group.get("context_features") or [])
                 if str(t).strip()]
        frags = [str(f) for f in (group.get("fragments") or [])
                 if str(f).strip()]
        if not feats or not frags:
            continue
        name = "pb:" + "|".join(feats)
        seeds[name] = (name, "playbook", feats)
    if seeds:
        return [seeds[k] for k in sorted(seeds)]
    return _question_seeds(ws)


def maybe_register(ws) -> dict:
    """Rollout-init direction registration. Flag OFF: an inert receipt
    and NOTHING else (no reads, no writes — the zero-behavior pin)."""
    if not enabled():
        return {"enabled": False, "registered": []}
    registered = [new_direction(ws, name, source=source,
                                situation_tags=tags)["row"]
                  for name, source, tags in _seed_directions(ws)]
    return {"enabled": True, "registered": registered}


def on_step(ws, direction: str, t0_reading, t1_reading) -> dict:
    """One probe milestone: price the step credit through the ΔV seam
    and bank it. Flag OFF: inert."""
    if not enabled():
        return {"enabled": False}
    delta = step_credit_delta(ws, t0_reading, t1_reading)
    return {"enabled": True, **observe_step(ws, direction, delta)}


def on_claim_terminal(ws, direction: str, *, reason=None) -> dict:
    """Claim-terminal reconciliation: settle the step bank into the
    posterior, then race the elimination gate. An EXOGENOUS env death
    never reaches here — the loop records censoring.observe_censored
    and this face stays untouched (the posterior keeps its silence).
    Flag OFF: inert."""
    if not enabled():
        return {"enabled": False}
    return {"enabled": True,
            "settle": settle_step(ws, direction, reason=reason),
            "eliminated": maybe_eliminate(ws, direction)}
