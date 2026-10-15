# -*- coding: utf-8 -*-
"""marl.py — the MARL knowledge-transfer protocol (#705).

Owner ruling 2026-10-15: MARL over SMDP. Workers are LEARNING AGENTS,
not stateless tools — "一个 subagent 学会了，其它没有必要从头开始学".
Learning is project-scope (the RE domain), generalizes (never
case-specific), and never overfits (learned posteriors, never a rule
table).

This module is the three-face transfer protocol the ruling demands:

  1. **Warm-start inheritance** — lives in ``q_cells.cell_posterior``:
     the leave-one-out anchor is ``family_aggregate − local``, so a cold
     agent cell inherits its peers' mass by construction (no new
     plumbing, no forced pooling).

  2. **Negative knowledge (CLASS level)** — ``record_negative`` /
     ``negative_pools`` below. A failed tool chain records under
     ``(signature_class, agent_type, method_family)``, where the CLASS
     is a digest over the workspace's mined STRUCTURAL feature tokens —
     never the instance signature, never a case identity. Two workspaces
     with the same structural shape collide and share the dead end; two
     instances of the same binary at different loop phases do not.
     Read back as failure mass that raises the arm's β (a dead end is a
     failure pseudo-count, never a deletion — the mean need not fall for
     a cell whose own failures already sit below the anchor mean); it is
     threaded through ``sample_method_family(negative_pools=...)`` as an
     additive receipt block under the one SHRINK_CAP.

  3. **Solution broadcast (METHOD level)** — ``broadcast_solution``: a
     PROVEN claim's METHOD enters the shared posterior store. The
     answer text NEVER rides the row — the ``answer`` kwarg is accepted
     and DELIBERATELY DROPPED so a careless caller cannot leak it
     through this face. Other agents may use the broadcast as a prior
     but must still verify (verification credit ≠ solve credit).

Every write is fail-open telemetry (a store failure never breaks the
producer); every read degrades to the inert empty face with one
rate-limited warn.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from kunglao_log import iter_jsonl, warn

from rlvr import q_cells

NEG_SCHEMA = "marl-negative/1"
NEG_REL = "marl-negative.jsonl"

#: the inert class — a workspace with no mined features degrades here,
#: never a fabricated bucket (fail-open).
UNKNOWN_CLASS = "unknown"


def neg_store_path() -> Path:
    """The SHARED negative-knowledge store — one file under the same
    guarded root as the posterior store (env
    ``KUNGLAO_POSTERIOR_STORE`` override, else the prior_store_root
    patterns dir). Shared, not per-workspace: the whole point of
    class-level negative knowledge is that workspace B inherits
    workspace A's dead end for the SAME structural class."""
    from rlvr import strategy_store as _ss  # noqa: PLC0415 — lazy
    return _ss.store_root() / NEG_REL


def _class_of(ws=None, *, features=None) -> str:
    """The CLASS digest implementation (the module's private face — the
    public ``signature_class`` is a thin alias, and the parameter named
    ``signature_class`` on the read face never shadows this)."""
    try:
        if features is None:
            if ws is None:
                return UNKNOWN_CLASS
            from rlvr import feature_prior as _fp  # noqa: PLC0415 — lazy
            features = _fp.features_from_workspace(ws)
        from rlvr import feature_prior as _fp  # noqa: PLC0415 — lazy
        toks = sorted(_fp.feature_tokens(features or {}))
        if not toks:
            return UNKNOWN_CLASS
        return hashlib.sha256(
            "|".join(toks).encode("utf-8")).hexdigest()[:12]
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("marl.signature_class",
             f"{type(exc).__name__}: {exc} (class={UNKNOWN_CLASS})")
        return UNKNOWN_CLASS


def signature_class(ws=None, *, features=None) -> str:
    """The CLASS-level abstraction — a stable digest over the mined
    STRUCTURAL feature tokens (feature_prior.feature_tokens), never the
    instance signature or a case identity. This is what makes negative
    knowledge generalize: two workspaces with the same structural shape
    land in the same class.

    ``features`` (an already-extracted features object) short-circuits
    the workspace extraction — the test/replay face. No mined tokens →
    the inert ``UNKNOWN_CLASS`` (fail-open, one warn)."""
    return _class_of(ws, features=features)


def _read_neg_rows() -> list[dict]:
    """Tolerant read: schema-filtered rows, oldest first. Missing file →
    [], corrupt lines skip."""
    p = neg_store_path()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict)
            and str(r.get("schema") or "") == NEG_SCHEMA]


def _tool_chain_token(tool_chain) -> str | None:
    """The tool chain's STRUCTURAL shape (sorted tokens, pipe-joined) —
    auditable, never the raw call text (case-text must not ride the
    class-level record)."""
    if not tool_chain:
        return None
    try:
        toks = sorted({str(t).strip() for t in tool_chain if str(t).strip()})
        return "|".join(toks) or None
    except TypeError:
        return None


def record_negative(ws, *, method_family: str,
                    agent_type: str | None = None,
                    tool_chain=None, features=None) -> dict:
    """Append one CLASS-level negative observation: this structural class
    + this approach = low success. The class rides the row (never
    re-derived at read time, so a later workspace of the same class
    inherits the dead end). ``features`` is the caller's ALREADY-MINED
    features for THIS workspace (the dispatch face holds them in hand) —
    production callers omit it and the class derives from ``ws``; the
    read face derives the same way, so record and read agree by
    construction. Fail-open: an unwritable store yields no row and never
    raises."""
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    cls = signature_class(ws, features=features)
    row = {
        "schema": NEG_SCHEMA,
        "ts": utc_now_z(),
        "signature_class": cls,
        "agent_type": str(agent_type) if agent_type else None,
        "method_family": str(method_family),
        "tool_chain": _tool_chain_token(tool_chain),
        "fails": 1,
    }
    appended = q_cells._append_row(neg_store_path(), row)
    return {"appended": bool(appended), "reason": None if appended
            else "write-failed", "signature_class": cls, "row": row}


def negative_pools(ws, families, *, agent_type: str | None = None,
                   signature_class: str | None = None) -> dict:
    """The read face — class-level dead ends as failure-mass pools.

    Pooled ACROSS agent types within the class (the whole point: when one
    agent learns a dead end the others inherit it). ``agent_type`` is an
    optional narrowing filter, never the default. ``signature_class``
    overrides the workspace's own class — the cross-workspace read (a
    different workspace of the same class reads the same dead ends).

    Returns {family → FeaturePool(success=0.0, failure=λ·fails, rows)} —
    the sampler's duck type. A dead end is pure failure mass: it raises
    the cell's β (never deletes it, never collapses the arm to zero
    probability). Families without negative rows are absent (a zero-mass
    pool is a no-op at the anchor)."""
    try:
        cls = signature_class or (_class_of(ws)
                                  if ws is not None else UNKNOWN_CLASS)
        rows = _read_neg_rows()
        wanted = set(families)
        from rlvr import meta_arms as _ma  # noqa: PLC0415 — the temper
        acc: dict[str, tuple[float, int]] = {}
        for r in rows:
            if str(r.get("signature_class") or "") != cls:
                continue
            if agent_type and str(r.get("agent_type") or "") != str(agent_type):
                continue
            fam = str(r.get("method_family") or "")
            if fam not in wanted:
                continue
            fails = r.get("fails")
            n = fails if isinstance(fails, int) and not isinstance(
                fails, bool) and fails > 0 else 1
            s, c = acc.get(fam, (0.0, 0))
            acc[fam] = (s + _ma.LAMBDA * n, c + 1)
        if not acc:
            return {}
        from rlvr import feature_prior as _fp  # noqa: PLC0415 — duck type
        return {fam: _fp.FeaturePool(0.0, mass, rows)
                for fam, (mass, rows) in sorted(acc.items())}
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("marl.negative_pools", f"{type(exc).__name__}: {exc}")
        return {}


def broadcast_solution(ws, *, method_family: str, credit,
                       agent_type: str | None = None,
                       claim: str | None = None,
                       answer: str | None = None,
                       arm_key: str | None = None,
                       feature_key: str | None = None,
                       fingerprint: str | None = None) -> dict:
    """The SOLUTION BROADCAST face: a PROVEN claim's METHOD enters the
    shared posterior store so other agents can warm-start from it.

    Method-only by construction: the row carries the method family, the
    proving agent, the claim ID and the credit. The optional ``answer``
    kwarg is accepted and DELIBERATELY DROPPED — the broadcast face
    cannot leak the answer even if a careless caller passes it. Other
    agents may use the broadcast as a prior but MUST still verify
    (verification credit ≠ solve credit — only solve credit updates the
    Beta).

    Delegates to the existing guarded store write face
    (``strategy_store.append_store_row``): the holdout filter precedes
    the append and a store failure is fail-open telemetry, never a raise
    into the producer. ``answer`` is intentionally unused."""
    del answer  # #705: method-only — the answer never rides the row
    try:
        from rlvr import strategy_store as _ss  # noqa: PLC0415 — lazy
        return _ss.append_store_row(
            ws, method_family=method_family, status="proven",
            credit=credit, arm_key=arm_key, feature_key=feature_key,
            fingerprint=fingerprint, agent_type=agent_type,
            claim=claim)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("marl.broadcast_solution", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "reason": f"error:{type(exc).__name__}"}
