# -*- coding: utf-8 -*-
"""rlvr/source_reliability.py — the learned source-reliability Betas.

Which evidence source to trust cannot be enumerated: pseudocode vs
assembly, a hook trace vs a syscall capture, a MITM capture vs the
server-side record — reference frames keep changing, and a hand-written
trust table goes stale on the first new tool. People learn reliable
frames from massive experience; this module learns the same way. Every
evidence item labels its producing tool (``source``) and its reference
frame (``reference_class``, the taxonomy raw > derived > inferred — a
LABEL keyed into the posterior, never a trust ranking), and the
reliability of the labeled class is the Beta

    Beta(alpha, beta | source_class, context_class)

folded from invalidation events — the only teacher: evidence REFUTED by
later evidence -> beta += 1; evidence CONFIRMED -> alpha += 1; no event
-> Beta(1, 1) (the uniform prior is the absence of a rule). Reads back
off exact (source_class, context_class) cell -> source-class marginal
across contexts (the generalization face) -> prior, naming the
answering face; ``theta`` is one stdlib betavariate Thompson draw, so
posterior width IS the exploration engine (uncertain sources draw wide,
settled-bad ones effectively never retried). ``reliability_weight`` is
the per-item credit face (theta when labeled, 1.0 when not: "weighted
... if available"); the composition itself lives in ``rlvr.step_credit``.

Store: append-only ``source-reliability.jsonl`` under the SHARED store
root (strategy_store.store_root(), env override KUNGLAO_POSTERIOR_STORE)
— tool trust is cross-engagement knowledge, so a later engagement
inherits it. Reads tolerate a missing or dirty store; writes are
loud-result dicts through the shared append primitive and never raise
into the producer.
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping
from pathlib import Path

from harness_common import utc_now_z as _utc_now
from kunglao_log import iter_jsonl, warn

from rlvr import q_cells as _qc  # the shared append primitive
from rlvr.posteriors import PRIOR_ALPHA_DEFAULT, PRIOR_BETA_DEFAULT

SCHEMA = "source-reliability/1"
STORE_REL = "source-reliability.jsonl"

#: the reference-frame taxonomy (labels only — never a trust ranking)
REFERENCE_CLASSES = ("raw", "derived", "inferred")

#: the unnamed context bucket; a read without a context answers from the
#: source-class marginal across ALL buckets (the generalization face)
DEFAULT_CONTEXT = "default"

CONFIRMED = "confirmed"
REFUTED = "refuted"

_EVENT_ADDS = {CONFIRMED: (1.0, 0.0), REFUTED: (0.0, 1.0)}


def store_path() -> Path:
    """The SHARED reliability store — one file under the same guarded
    root as the posterior store (env KUNGLAO_POSTERIOR_STORE override).
    Shared, not per-workspace: what one engagement learns about a
    tool's reliability is what the next engagement should inherit."""
    from rlvr import strategy_store as _ss  # noqa: PLC0415 — lazy
    return _ss.store_root() / STORE_REL


# --------------------------------------------------------------- labels

def evidence_labels(source, reference_class) -> dict:
    """Build (or validate) an evidence item's labels: {source,
    reference_class}. Raises ValueError on a missing source or a
    reference_class outside the taxonomy — the write faces refuse
    loudly instead of recording garbage."""
    src = str(source or "").strip()
    ref = str(reference_class or "").strip().lower()
    if not src:
        raise ValueError("source: non-empty tool name required")
    if ref not in REFERENCE_CLASSES:
        raise ValueError(f"reference_class: one of {REFERENCE_CLASSES} "
                         f"required, got {reference_class!r}")
    return {"source": src, "reference_class": ref}


def source_class_of(source: str, reference_class: str) -> str:
    """The Beta's source key: tool + reference frame, one class. The
    same tool in two frames (a raw listing vs decompiled pseudocode) is
    two classes, learned apart."""
    return f"{source}|{reference_class}"


def _resolve(evidence_or_source, reference_class=None) -> tuple | None:
    """(source, reference_class) from a mapping carrying the labels, or
    from a positional pair; None when missing or outside the taxonomy
    (callers refuse loudly — this face never raises)."""
    source = ref = None
    if isinstance(evidence_or_source, Mapping):
        source = evidence_or_source.get("source")
        ref = evidence_or_source.get("reference_class")
    else:
        source = evidence_or_source
        ref = reference_class
    try:
        labels = evidence_labels(source, ref)
    except ValueError:
        return None
    return labels["source"], labels["reference_class"]


def _norm_context(context_class) -> str:
    ctx = str(context_class or "").strip()
    return ctx or DEFAULT_CONTEXT


def has_source_labels(evidence) -> bool:
    """True when the item carries valid source labels (``source`` +
    ``reference_class``). The cheap probe composition faces use to skip
    the store read for unlabeled evidence ("weighted ... if
    available")."""
    return _resolve(evidence, None) is not None


# ------------------------------------------------- the write faces (events)

def record_outcome(evidence, outcome, *, context_class=None, by=None,
                   ts=None) -> dict:
    """Append ONE invalidation event (the only teacher): ``outcome``
    "confirmed" (alpha += 1) or "refuted" (beta += 1) for the evidence
    item's source class. ``by`` records the later evidence's eid (audit
    only — a refuter is never auto-credited). Loud result dict; invalid
    labels or outcome are refused, nothing raises into the producer."""
    outcome = str(outcome or "").strip()
    if outcome not in _EVENT_ADDS:
        return {"recorded": False,
                "reason": f"outcome: one of {tuple(_EVENT_ADDS)} required, "
                          f"got {outcome!r}"}
    resolved = _resolve(evidence, None)
    if resolved is None:
        reason = ("evidence: {source, reference_class} with "
                  f"reference_class in {REFERENCE_CLASSES} required")
        warn("rlvr.source_reliability.record_outcome", reason)
        return {"recorded": False, "reason": reason}
    source, ref = resolved
    alpha_add, beta_add = _EVENT_ADDS[outcome]
    row = {
        "schema": SCHEMA,
        "ts": ts or _utc_now(),
        "source": source,
        "reference_class": ref,
        "source_class": source_class_of(source, ref),
        "context_class": _norm_context(context_class),
        "event": outcome,
        "alpha_add": alpha_add,
        "beta_add": beta_add,
        "by": str(by) if by else None,
    }
    appended = _qc._append_row(store_path(), row)
    return {"recorded": bool(appended),
            "reason": None if appended else "write-failed",
            "row": row}


def record_refutation(evidence, *, refuted_by=None, context_class=None,
                      ts=None) -> dict:
    """Evidence REFUTED by later evidence -> its source class's beta
    += 1 (the source produced evidence that was overturned)."""
    return record_outcome(evidence, REFUTED, context_class=context_class,
                          by=refuted_by, ts=ts)


def record_confirmation(evidence, *, confirmed_by=None, context_class=None,
                        ts=None) -> dict:
    """Evidence CONFIRMED by later evidence -> its source class's alpha
    += 1 (the source's evidence held up)."""
    return record_outcome(evidence, CONFIRMED, context_class=context_class,
                          by=confirmed_by, ts=ts)


# ------------------------------------------------- the read faces (fold)

def _read_events() -> list[dict]:
    """Tolerant read: schema-filtered rows in file order. Missing store
    -> []; corrupt lines skip."""
    try:
        text = store_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict)
            and str(r.get("schema") or "") == SCHEMA]


class ReliabilityView:
    """The folded knowledge state: Beta counts per (source_class,
    context_class) cell and per source_class marginal (all contexts
    pooled). Raw event rows are never rewritten."""

    def __init__(self, cells: dict, marginals: dict):
        self._cells = cells          # {(source_class, ctx): [a, b, n]}
        self._marginals = marginals  # {source_class: [a, b, n]}

    def posterior(self, evidence_or_source, reference_class=None, *,
                  context_class=None) -> dict:
        """The read with backoff: the exact (source_class,
        context_class) cell when it has observations; else the
        source-class marginal pooled across all contexts; else the
        uniform prior. ``basis`` names which face answered. An
        unlabeled input reads the prior."""
        prior = [PRIOR_ALPHA_DEFAULT, PRIOR_BETA_DEFAULT, 0.0]
        resolved = _resolve(evidence_or_source, reference_class)
        if resolved is None:
            return self._doc(None, None, prior, "prior")
        source, ref = resolved
        sc = source_class_of(source, ref)
        ctx = _norm_context(context_class)
        if context_class is not None:
            cell = self._cells.get((sc, ctx))
            if cell is not None and cell[2] > 0:
                return self._doc(sc, ctx, cell, "cell")
        marg = self._marginals.get(sc)
        if marg is not None and marg[2] > 0:
            return self._doc(sc, ctx, marg, "marginal")
        return self._doc(sc, ctx, prior, "prior")

    @staticmethod
    def _doc(source_class, context_class, counts, basis) -> dict:
        a, b, n = counts
        total = a + b
        return {
            "source_class": source_class,
            "context_class": context_class,
            "alpha": float(a),
            "beta": float(b),
            "n": float(n),
            "mean": a / total,
            "width": math.sqrt(a * b / (total * total * (total + 1.0))),
            "basis": basis,
        }

    def theta(self, evidence_or_source, reference_class=None, *,
              context_class=None, rng: random.Random | None = None
              ) -> float:
        """One Thompson draw from the read posterior (stdlib
        betavariate; rng=None -> random.Random(0), the anchor-
        deterministic default). The exploration engine is the posterior
        width, never a rule."""
        post = self.posterior(evidence_or_source, reference_class,
                              context_class=context_class)
        if rng is None:
            rng = random.Random(0)
        return rng.betavariate(post["alpha"], post["beta"])


def fold(events: list[dict] | None = None) -> ReliabilityView:
    """Fold the event store (or an explicit event list — the replay
    face) into the reliability view. Only schema'd rows with a known
    event vocabulary contribute; raw rows stay untouched."""
    rows = _read_events() if events is None else [
        r for r in events
        if isinstance(r, dict) and str(r.get("schema") or "") == SCHEMA]
    cells: dict[tuple[str, str], list] = {}
    marginals: dict[str, list] = {}
    for row in rows:
        adds = _EVENT_ADDS.get(str(row.get("event") or ""))
        sc = str(row.get("source_class") or "")
        if adds is None or not sc:
            continue
        ctx = _norm_context(row.get("context_class"))
        for key, book in (((sc, ctx), cells), (sc, marginals)):
            slot = book.get(key)
            if slot is None:
                slot = [PRIOR_ALPHA_DEFAULT, PRIOR_BETA_DEFAULT, 0.0]
                book[key] = slot
            slot[0] += adds[0]
            slot[1] += adds[1]
            slot[2] += 1.0
    return ReliabilityView(cells, marginals)


# -------------------------------------------------- the credit-weight face

def reliability_weight(evidence, *, context_class=None,
                       rng: random.Random | None = None,
                       view: ReliabilityView | None = None) -> float:
    """The credit face for one evidence item: a Thompson draw of its
    source's reliability when the item carries labels; 1.0 when they
    are absent ("weighted ... if available"). ``view`` lets a caller
    reuse one fold across many items; the composition itself
    (step_credit * theta) lives in rlvr.step_credit."""
    if _resolve(evidence, None) is None:
        return 1.0
    if view is None:
        view = fold()
    return view.theta(evidence, context_class=context_class, rng=rng)


__all__ = ["SCHEMA", "STORE_REL", "REFERENCE_CLASSES", "DEFAULT_CONTEXT",
           "CONFIRMED", "REFUTED", "store_path", "evidence_labels",
           "source_class_of", "has_source_labels", "record_outcome",
           "record_refutation", "record_confirmation", "ReliabilityView",
           "fold", "reliability_weight"]
