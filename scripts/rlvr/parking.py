# -*- coding: utf-8 -*-
"""rlvr/parking.py — the PARKED claim state + the minimal escrow stub
(issue #955, chain link 3).

When the interruption classifier (rlvr.interruption) calls a rollout
``censored_env``, the claim's disposition is neither terminal nor
clawed-back: its PROVISIONAL mass (the banked settlement credit + the
#712 step credits banked before the crash — real measurements under
potential-based per-step credit) moves to a PARKED-mass ledger and the
claim's register status becomes ``PARKED``:

  - not confirmed  — the mass never reconciles into a terminal reward
                     while parked (the #712 audit Gap-2 hang, made
                     explicit and observable instead of silent);
  - not clawed back— the pre-crash ΔV banked are real; censoring only
                     removes information, it never adds wrong signal;
  - decaying       — the escrowed mass decays toward zero on the
                     #667 parameters (owner sign-off pending).

THE ESCROW STUB: face 3's escrow CHANNEL design is drafted in the #667
amendment (owner sign-off pending). This module is the STUB the
sign-off parameterizes: a parked-mass ledger
(``runs/parked-mass.jsonl``, schema ``parked-mass/1``, append-only) +
the decay parameter table below, flagged ``escrow_design: #667`` so the
sign-off can swap the parameters WITHOUT reshaping (the row contract
and the pure ``decayed()`` face are the stable surface; rate, class
vocabulary and any channel split are #667's to own).

State touched:
  runs/parked-mass.jsonl    the escrow ledger (park / release rows)
  claim-register.yaml       the claim's ``status: PARKED`` +
                            ``wake_condition`` — written ONLY through
                            the ws_yaml single-writer seam (#516)

Status semantics: PARKED joins status_defs.SUSPENDED (#634's suspension
family) — NOT terminal (revivable), NOT dispatchable, NOT open-frontier
work; every status_defs consumer picks that up from the one set. Like
PARK, a PARKED claim must carry a non-empty wake_condition (carrier
rule (f)); the env-repair ladder IS the wake path — its resume protocol
is UNPARK (this module's ``unpark_claim``), after which the banked
credits survive and the post-repair segments reconcile normally (#955
links 6/11).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from kunglao_log import warn  # canonical warn: ONE implementation
from rlvr import learning_seal as _seal  # #799: the row seal
from rlvr import q_cells  # the mass read faces (banked + step totals)

#: the parked-mass ledger (workspace-relative; its own ledger — the
#: #667 sign-off decides whether the escrow channel migrates into the
#: consolidated store families)
PARKED_MASS_REL = "runs/parked-mass.jsonl"
SCHEMA = "parked-mass/1"

#: the #667 amendment this stub defers to (rides every park row)
ESCROW_DESIGN = "#667"

#: decay parameters — escrow_design: #667 (OWNER-TUNABLE). The sign-off
#: swaps these values (or grows the class vocabulary); the row shape and
#: the pure decay face below stay fixed. Determinism: ``decayed()`` is a
#: pure function of (mass, ticks, class) — no clock read, no float drift
#: beyond the 6-dp grid every rlvr mass rides.
DECAY_PARAMS: dict[str, dict] = {
    "default": {"decay_class": "exponential", "rate_per_tick": 0.05},
}
DEFAULT_DECAY_CLASS = "default"

#: the claim register's parked status (status_defs.SUSPENDED member)
PARKED = "PARKED"


# ------------------------------------------------------------- decay face

def decayed(mass: float, ticks: int, decay_class: str = DEFAULT_DECAY_CLASS
            ) -> float:
    """The escrowed mass after ``ticks`` elapsed, on the #667 parameters
    (pure — the determinism surface). Unknown class parks the mass at its
    nominal value (an unknown parameter class never fabricates decay)."""
    params = DECAY_PARAMS.get(decay_class) or {}
    try:
        rate = float(params.get("rate_per_tick") or 0.0)
        n = int(ticks)
    except (TypeError, ValueError):
        return round(float(mass), 6)
    if n <= 0:
        return round(float(mass), 6)
    value = float(mass) * max(0.0, 1.0 - rate) ** n
    return round(max(0.0, value), 6)


# --------------------------------------------------------------- mass read

def provisional_mass(ws, claim_id: str) -> float:
    """The claim's unreconciled provisional mass: the fold-banked
    settlement success mass (q_cells.banked_mass) + the #712 step-credit
    mass (q_cells.step_credit_totals) — both read from the SAME
    append-only log the fold consumes (never a parallel tally). An
    UNREADABLE ledger raises (a protocol face refuses to park against a
    fabricated 0 — banked_mass's None means "skip this pass", and
    parking on a skipped read would silently zero the escrow)."""
    did = str(claim_id or "")
    banked = q_cells.banked_mass(ws, did)
    if banked is None:
        raise ValueError(
            f"rlvr.parking: unreadable experience ledger for {did!r} "
            "— refusing to park against an unread mass")
    steps = q_cells.step_credit_totals(ws, did)
    return round(banked[0] + steps[0], 6)


# ------------------------------------------------------------- the ledger

def _append_row(ws, row: dict) -> None:
    """One parked-mass/1 row, append-only (the consolidated-ledger row
    discipline: O_APPEND single write, schema stamp + #799 seal on
    every row — an unsealed escrow row is forgeable the same way a
    q-cell row is, so the same seal discipline applies)."""
    path = Path(ws) / PARKED_MASS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    row = _seal.sign_row(row)
    data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def escrow_rows(ws) -> list[dict]:
    """Every parked-mass/1 row, append order; absent/dirty file -> []
    (fail-open read). The learner read face: armed, only seal-valid
    rows survive (a forged escrow row can never drive the balance —
    same trust posture as the q-cell fold)."""
    path = Path(ws) / PARKED_MASS_REL
    if not path.is_file():
        return []
    from kunglao_log import iter_jsonl
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
    except OSError as exc:
        warn("rlvr.parking", f"escrow read failed: {exc}")
        return []
    rows = [row for row in iter_jsonl(lines, source="parking.escrow_rows")
            if isinstance(row, dict) and row.get("schema") == SCHEMA]
    return _seal.trusted_rows(rows, op="rlvr.parking.escrow_rows")


def open_park_row(ws, claim_id: str) -> dict | None:
    """The claim's LATEST unreleased park row (None = not parked)."""
    hit = None
    for row in escrow_rows(ws):
        if str(row.get("claim_id") or "") != str(claim_id):
            continue
        if row.get("event") == "park":
            hit = row
        elif row.get("event") == "release":
            hit = None
    return hit


def escrow_balance(ws) -> float:
    """Nominal escrow mass currently parked: Σ park.mass − Σ release.mass
    (per-claim LIFO matching; the DECAYED value is ``decayed()``'s job —
    this face is the conservation operand)."""
    open_mass = 0.0
    for row in escrow_rows(ws):
        try:
            mass = float(row.get("mass") or 0.0)
        except (TypeError, ValueError):
            continue
        if row.get("event") == "park":
            open_mass += mass
        elif row.get("event") == "release":
            open_mass -= mass
    return round(open_mass, 6)


# ------------------------------------------------------- register mutation

def _claim_index(register: dict, claim_id: str) -> int:
    """The claim's index in the register's claims list (ValueError when
    absent — the caller's error, loudly, never a silent no-op).

    TOCTOU note (accepted): the index is read from OUR load and the
    ws_yaml write re-loads the file — a concurrent writer between the
    two could shift the list. ACCEPTED by design: ws_yaml is the
    single-writer seam (#516), so every sanctioned writer serializes
    through the same tool face; no parallel writer exists to race with
    (the #516 corruption class this closes is HAND-EDITED yaml, which
    the write gate refuses outright)."""
    for idx, c in enumerate(register.get("claims") or []):
        if str(c.get("id") or "") == str(claim_id):
            return idx
    raise ValueError(f"rlvr.parking: unknown claim {claim_id!r}")


def _ws_set(ws, dotted: str, value: str) -> None:
    """One register write through the ws_yaml single-writer seam
    (#516). Non-zero exit -> ValueError (the seam refused the write —
    never a silent partial park)."""
    import ws_yaml
    rc = ws_yaml.main(["set", str(Path(ws) / "claim-register.yaml"),
                       dotted, value])
    if rc != 0:
        raise ValueError(
            f"rlvr.parking: ws_yaml set {dotted!r} refused (exit {rc})")


def _ws_del(ws, dotted: str) -> None:
    """One register key removal through the seam; a missing path (exit 5)
    is already-clean, anything else refused."""
    import ws_yaml
    rc = ws_yaml.main(["del", str(Path(ws) / "claim-register.yaml"), dotted])
    if rc not in (0, 5):
        raise ValueError(
            f"rlvr.parking: ws_yaml del {dotted!r} refused (exit {rc})")


def _load_register(ws) -> tuple[dict, Path]:
    path = Path(ws) / "claim-register.yaml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"rlvr.parking: unreadable claim register: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("rlvr.parking: claim register is not a mapping")
    return doc, path


# --------------------------------------------------------------- the faces

def park_claim(ws, claim_id: str, reason_code: str) -> dict:
    """PARK one censored claim: flip the register status to PARKED +
    write the wake_condition FIRST, then escrow its provisional mass (a
    park row in runs/parked-mass.jsonl), emit the claim_park event.

    ORDERING: the register writes come FIRST — a refused _ws_set then
    aborts with NO park row (a retry is clean); an escrow-append
    failure after a landed register write rolls the register BACK
    (compensating release: prior status restored, wake_condition
    dropped) before re-raising. Either failure order leaves the claim
    consistent — never the wedge (open park row + OPEN status + a
    retry that refuses on the double-park guard).

    Refuses a double park (ValueError — an escrowed mass must never
    double-count). Returns the receipt {claim_id, mass, reason_code,
    prior_status, decay_class, escrow_design}."""
    ws = Path(ws)
    claim_id = str(claim_id)
    if open_park_row(ws, claim_id) is not None:
        raise ValueError(
            f"rlvr.parking: claim {claim_id!r} is already PARKED")
    register, _reg_path = _load_register(ws)
    idx = _claim_index(register, claim_id)
    prior_status = str((register.get("claims") or [])[idx].get("status")
                       or "OPEN")
    mass = provisional_mass(ws, claim_id)
    _ws_set(ws, f"claims.{idx}.status", PARKED)
    _ws_set(ws, f"claims.{idx}.wake_condition",
            f"env-repair ladder resume: {reason_code}")
    row = {
        "schema": SCHEMA,
        "event": "park",
        "ts": _now(),
        "claim_id": claim_id,
        "mass": mass,
        "reason": str(reason_code),
        "decay_class": DEFAULT_DECAY_CLASS,
        "prior_status": prior_status,
        "escrow_design": ESCROW_DESIGN,
    }
    try:
        _append_row(ws, row)
    except OSError as exc:
        # compensating release: the register flipped but the escrow
        # row never landed — restore the pre-park register state so a
        # retry is clean (never the wedged half-park). Best-effort with
        # a loud warn per failed leg; the ORIGINAL failure is what
        # re-raises (a rollback refusal must not mask it — a refused
        # rollback leaves the claim visibly PARKED, recoverable by
        # hand through the seam, which is the honest state).
        warn("rlvr.parking",
             f"escrow append failed ({exc}); rolling the register back")
        try:
            _ws_set(ws, f"claims.{idx}.status", prior_status)
            _ws_del(ws, f"claims.{idx}.wake_condition")
        except (ValueError, OSError) as rb_exc:  # noqa: BLE001 — loud, then original
            warn("rlvr.parking",
                 f"rollback refused ({rb_exc}); claim stays PARKED — "
                 "recover through the ws_yaml seam")
        raise
    try:
        import kunglao_log
        kunglao_log.emit(ws, "rlvr.parking", "claim_park", claim=claim_id,
                         detail=json.dumps(
                             {"mass": mass, "reason": str(reason_code),
                              "prior_status": prior_status},
                             ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — never breaks the park
        warn("rlvr.parking", f"claim_park emit failed: {exc}")
    return {"claim_id": claim_id, "mass": mass,
            "reason_code": str(reason_code),
            "prior_status": prior_status,
            "decay_class": DEFAULT_DECAY_CLASS,
            "escrow_design": ESCROW_DESIGN}


def unpark_claim(ws, claim_id: str) -> dict:
    """UNPARK one repaired claim (#955 link 6): a release row restores
    the escrowed mass to the claim (mass conservation — the balance
    returns to zero), the register status returns to the park row's
    prior_status (default OPEN) and the wake_condition clears. Refuses
    an unpark of a claim that is not PARKED (ValueError). Returns the
    receipt {claim_id, restored_mass, restored_status}."""
    ws = Path(ws)
    claim_id = str(claim_id)
    park_row = open_park_row(ws, claim_id)
    if park_row is None:
        raise ValueError(
            f"rlvr.parking: claim {claim_id!r} is not PARKED")
    register, _reg_path = _load_register(ws)
    idx = _claim_index(register, claim_id)
    restored_status = str(park_row.get("prior_status") or "OPEN")
    row = {
        "schema": SCHEMA,
        "event": "release",
        "ts": _now(),
        "claim_id": claim_id,
        "mass": float(park_row.get("mass") or 0.0),
        "park_ref_ts": park_row.get("ts"),
        "escrow_design": ESCROW_DESIGN,
    }
    _append_row(ws, row)
    _ws_set(ws, f"claims.{idx}.status", restored_status)
    _ws_del(ws, f"claims.{idx}.wake_condition")
    try:
        import kunglao_log
        kunglao_log.emit(ws, "rlvr.parking", "claim_unpark",
                         claim=claim_id,
                         detail=json.dumps(
                             {"restored_mass": row["mass"],
                              "restored_status": restored_status},
                             ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — never breaks the unpark
        warn("rlvr.parking", f"claim_unpark emit failed: {exc}")
    return {"claim_id": claim_id, "restored_mass": row["mass"],
            "restored_status": restored_status}


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415
    return utc_now_z()
