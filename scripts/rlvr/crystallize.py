# -*- coding: utf-8 -*-
"""crystallize.py — the settlement writes knowledge back.

The transfer protocol's read faces are wired at the sampler and the
planner; the write face lives here. A settled step is the moment the
evidence is freshest: the claim's method (and tool chain) is on record
in the usage log, the outcome is known, and the step's credit is just
banked. This module turns that context into the two derived
discriminants the shared stores carry — the class-level dead end and
the method broadcast — with the provenance that lets a later settlement
correction revoke them.

Posture: pure derivation over settled facts. An honest gap (no usage
row, no banked credit, no certified answer) writes nothing; a store
failure is fail-open telemetry into the caller's receipt, never a raise
into the settlement. The derived stores are caches — the evidence of
record stays in the step/transition ledgers — so revocation is an
atomic rewrite, not a tombstone.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import warn

#: the dispatch-failure vocabulary — a step settling here declares its
#: method a dead end for this structural class. Mirrors the hooks-side
#: DISPATCH_FAILURE_STATUSES (worker_budget_sinks) — the same three
#: words, owned per tree (a scripts→hooks import would wire the wrong
#: direction).
FAIL_OUTCOMES = frozenset({"blocked", "failed", "error"})

#: the register's decisive failure statuses — a claim the amendment flow
#: flipped to one of these never re-broadcasts, whatever the facts index
#: still says (the resurrection wall). Same set as the pair-amendment
#: face's CASE_FAIL_STATUSES in settle_round_credit.
REGISTER_FAIL = frozenset({"REFUTED", "NEGATIVE"})


def resolve_method(ws, claim: str) -> dict | None:
    """The claim's declared method from its LAST usage row: {family,
    tools}. None when the claim never dispatched through the usage log
    (the honest gap — no fabricated method)."""
    try:
        from method_families import read_usage  # noqa: PLC0415 — lazy
        cid = str(claim or "")
        found = None
        for row in read_usage(ws):
            if str(row.get("claim") or "") != cid:
                continue
            family = str(row.get("family") or "").strip()
            if not family:
                continue
            found = {"family": family,
                     "tools": [str(t) for t in (row.get("tools") or [])
                               if str(t).strip()]}
        return found
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("crystallize.resolve_method",
             f"{type(exc).__name__}: {exc}")
        return None


def _negative_duplicate(ws, claim: str, step_id: str, family: str) -> bool:
    """The replay wall: one negative per (class, family, claim, step)."""
    from rlvr import marl as _marl
    cls = _marl.signature_class(ws)
    for row in _marl.read_negatives():
        if (str(row.get("signature_class") or "") == cls
                and str(row.get("method_family") or "") == family
                and str(row.get("claim_ref") or "") == claim
                and str(row.get("step_ref") or "") == step_id):
            return True
    return False


def _broadcast_duplicate(claim: str, family: str) -> bool:
    """ONE broadcast per (claim, family) — the discriminant is the
    claim's method, so a later certified step on the same claim is a
    duplicate, never fresh prior mass (a per-step key would let an
    N-step claim warm a sibling workspace N times over)."""
    from rlvr import strategy_store as _ss
    for row in _ss.load_rows():
        if (str(row.get("claim") or "") == claim
                and str(row.get("method_family") or "") == family):
            return True
    return False


def crystallize_settlement(ws, *, claim: str, step_id: str,
                           outcome: str,
                           step_credit: float | None = None) -> dict:
    """One settled step → the derived discriminants it earns.

    A dispatch-failure outcome records ONE class-level negative
    attributed to (claim, step) — deduped, so a replayed settlement
    writes nothing. A completed step broadcasts its method only when
    the settle banked a step credit AND the substrate reports a
    certified answer (the cross-task face consumes only positive
    credits — an unbacked broadcast would be an unconsumable row).
    Returns {negative, broadcast, reason}; ``reason`` names the honest
    gap when nothing was written."""
    from rlvr import l1_planner as _l1
    from rlvr import marl as _marl
    out = {"negative": False, "broadcast": False, "reason": None}
    try:
        method = resolve_method(ws, claim)
        if method is None:
            return dict(out, reason="no-method")
        family = method["family"]
        outcome_norm = str(outcome or "").strip().lower()
        if outcome_norm in FAIL_OUTCOMES:
            if _negative_duplicate(ws, str(claim), str(step_id), family):
                return dict(out, reason="duplicate")
            rec = _marl.record_negative(
                ws, method_family=family,
                tool_chain=method.get("tools") or None,
                claim_ref=str(claim), step_ref=str(step_id))
            return dict(out, negative=bool(rec.get("appended")),
                        reason=None if rec.get("appended")
                        else "write-failed")
        if outcome_norm != "completed":
            return dict(out, reason="not-a-settlement")
        if step_credit is None or float(step_credit) <= 0.0:
            return dict(out, reason="no-credit")
        try:
            kc = _l1.knowledge_query(ws, claim)
            certified = (kc.get("answer_strength")
                         == _l1.CERTIFIED_STRENGTH)
            flipped = any(
                f.get("source") == "register"
                and str(f.get("status") or "").upper() in REGISTER_FAIL
                for f in kc.get("faces") or [])
            if flipped:
                certified = False
        except Exception as exc:  # noqa: BLE001 — one face never the write
            warn("crystallize.certified_check",
                 f"{type(exc).__name__}: {exc}")
            certified = False
        if not certified:
            return dict(out, reason="not-certified")
        if _broadcast_duplicate(str(claim), family):
            return dict(out, reason="duplicate")
        rec = _marl.broadcast_solution(
            ws, method_family=family, credit=float(step_credit),
            claim=str(claim), dispatch_id=str(step_id))
        return dict(out, broadcast=bool(rec.get("appended")),
                    reason=None if rec.get("appended")
                    else "write-failed")
    except Exception as exc:  # noqa: BLE001 — never the settlement
        warn("crystallize.settlement", f"{type(exc).__name__}: {exc}")
        return dict(out, reason=f"error:{type(exc).__name__}")


def _rewrite_without(path: Path, drop) -> int:
    """Atomically rewrite one JSONL store without the dropped rows.
    Unparseable lines survive untouched (never delete unknown junk);
    surviving canonical rows keep their exact bytes — the file-level
    shape normalizes (blank separators drop, the final newline lands).
    Returns the removed count; a zero-removal rewrite never touches the
    file. The write rides the canonical atomic face (writer-unique tmp,
    failed writes unlink their tmp, parents created)."""
    try:
        import json
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            kept.append(line)   # unparseable — survive untouched
            continue
        if isinstance(row, dict) and drop(row):
            removed += 1
            continue
        kept.append(line)
    if removed:
        if not kept:
            try:
                path.unlink()
            except OSError as exc:
                warn("crystallize.rewrite",
                     f"{type(exc).__name__}: {exc}")
                return 0
            return removed
        try:
            from _common import atomic_write_text  # noqa: PLC0415 — lazy
            atomic_write_text(path, "\n".join(kept) + "\n", unique=True)
        except OSError as exc:
            warn("crystallize.rewrite", f"{type(exc).__name__}: {exc}")
            return 0
    return removed


def revoke_claim(ws, claim: str) -> dict:
    """Drop every derived row attributed to the claim from BOTH derived
    stores (negatives by ``claim_ref``, broadcasts by ``claim``). The
    discriminant dies with the settlement it was derived from; the
    evidence of record (steps, transitions, amendment rows) is
    untouched. An empty claim is refused at the boundary (it would
    match every unattributed row). Returns per-store removal counts."""
    from rlvr import marl as _marl
    from rlvr import strategy_store as _ss
    cid = str(claim or "").strip()
    if not cid:
        return {"negatives_removed": 0, "broadcasts_removed": 0}
    removed_neg = _rewrite_without(
        _marl.neg_store_path(),
        lambda r: str(r.get("claim_ref") or "") == cid)
    removed_bcast = _rewrite_without(
        _ss.store_path(),
        lambda r: str(r.get("claim") or "") == cid)
    if removed_neg or removed_bcast:
        warn("crystallize.revoke",
             f"claim {cid}: {removed_neg} negative(s), "
             f"{removed_bcast} broadcast(s) revoked")
    return {"negatives_removed": removed_neg,
            "broadcasts_removed": removed_bcast}
