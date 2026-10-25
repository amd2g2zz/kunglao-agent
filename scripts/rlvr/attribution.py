# -*- coding: utf-8 -*-
"""rlvr/attribution.py — the LEARNED attribution model (issue 826, P3
of the #806 axis).

The senior-expert capability that replaces hand-built failure
classifiers: context -> outcome feature importance, computed as
DETERMINISTIC COUNTING STATISTICS over the P1 pool at call time —
per-feature failure contrast and presence lift, pure stdlib, no fitted
parameters, no model calls, no storage (a derived view: regenerate =
identical report).

TWO FACES:

  FEATURE IMPORTANCE — `feature_importance(ws)`: for every context
  feature, the failure rate among episodes carrying it, the presence
  contrast p(feature | failure) - p(feature | success), and the lift
  against the pool's base failure rate. Ranked by |contrast|
  descending (token asc tie-break). Features with EXACTLY zero
  contrast are demoted to `exogenous` — environment noise kept as
  PRIOR INPUT, never named as causes (the #421 demotion: exogenous
  features are an input face, not a verdict face).

  METHOD ATTRIBUTION — `method_attribution(ws, doc)`: WHY one failed
  episode failed, over the vocabulary
    hypothesis_wrong  (the environment is proven workable: verified
                       successes share this episode's features)
    tool_mismatch     (the episode carries a capability-failure fact
                       or a feature that has NEVER succeeded in this
                       pool — the learned signal)
    depth_insufficient(verified partial progress on a failed
                       completion — trust-derived milestone progress)
  deterministic precedence tool > depth > hypothesis, per-signal
  evidence carried in the report (NOT a binary accident/failure flag).

`report(ws, doc=None)` renders schema `attribution-report/1`;
`report_ref` derives the stable 16-hex digest the switch commit rides
(a switch without an attribution reference is RED — see
commit_semantics). Zero telemetry points (Standard 11); settlement/
verifier semantics only ever CALLED.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rlvr import episode_pool as pool
from rlvr import reward_signal as rs

ATTRIBUTION_SCHEMA = "attribution-report/1"

#: the method-attribution vocabulary (three causes, not a binary flag)
METHOD_HYPOTHESIS = "hypothesis_wrong"
METHOD_TOOL = "tool_mismatch"
METHOD_DEPTH = "depth_insufficient"

#: the capability-failure token shape (the #812 capability vocabulary)
_CAP_FAIL_SUFFIX = "-fail"


def _is_verified_success(doc: dict) -> bool:
    return (doc.get("outcome", {}).get("status") == "completed"
            and bool(doc.get("outcome", {}).get("verified")))


def feature_importance(ws) -> dict:
    """The learned feature ranking: per-feature failure statistics over
    the pool, |contrast|-ranked. Deterministic; writes nothing."""
    docs = pool.load_all(ws)
    total = len(docs)
    fails = [d for _p, d in docs
             if d.get("outcome", {}).get("status") == "failed"]
    succs = [d for _p, d in docs if _is_verified_success(d)]
    base_rate = (len(fails) / total) if total else 0.0

    rows: dict[str, dict] = {}
    for label, group, in (("fail", fails), ("ok", succs)):
        for doc in group:
            for f in doc.get("context_features") or []:
                f = str(f)
                cell = rows.setdefault(f, {"n": 0, "n_fail": 0})
                cell["n"] += 1
                if label == "fail":
                    cell["n_fail"] += 1

    features: list[dict] = []
    exogenous: list[str] = []
    denom_fail, denom_ok = len(fails), len(succs)
    for f, cell in rows.items():
        n = cell["n"]
        fail_rate = (cell["n_fail"] / n) if n else 0.0
        p_fail = (cell["n_fail"] / denom_fail) if denom_fail else 0.0
        n_ok = n - cell["n_fail"]
        p_ok = (n_ok / denom_ok) if denom_ok else 0.0
        contrast = p_fail - p_ok
        lift = (fail_rate / base_rate) if base_rate > 0.0 else 0.0
        row = {"feature": f, "n": n, "n_fail": cell["n_fail"],
               "fail_rate": fail_rate, "contrast": contrast, "lift": lift}
        features.append(row)
        if contrast == 0.0:
            exogenous.append(f)  # no outcome contrast: prior input, not a cause
    features.sort(key=lambda r: (-abs(r["contrast"]), r["feature"]))
    exogenous.sort()
    return {"schema": ATTRIBUTION_SCHEMA,
            "episodes": total,
            "base_fail_rate": base_rate,
            "features": features,
            "exogenous": exogenous}


def _carries_capability_failure(doc: dict) -> list[str]:
    return [str(f) for f in doc.get("context_features") or []
            if str(f).startswith("cap-") and str(f).endswith(_CAP_FAIL_SUFFIX)]


def method_attribution(ws, doc: dict) -> dict:
    """WHY this episode failed: the three-way method verdict with
    per-signal evidence. Deterministic precedence tool > depth >
    hypothesis. Non-failure episodes attribute honestly (no method)."""
    ws = Path(ws)
    status = doc.get("outcome", {}).get("status")
    if status != "failed":
        return {"schema": ATTRIBUTION_SCHEMA, "claim": str(doc.get("claim")),
                "method": None,
                "note": "method attribution applies to failed episodes"}

    feats = [str(f) for f in doc.get("context_features") or []]
    feat_set = set(feats)
    signals: dict[str, dict] = {
        METHOD_TOOL: {"fired": False, "evidence": []},
        METHOD_DEPTH: {"fired": False, "evidence": []},
        METHOD_HYPOTHESIS: {"fired": False, "evidence": []},
    }

    # tool_mismatch — the direct capability-failure fact...
    cap_fails = _carries_capability_failure(doc)
    if cap_fails:
        signals[METHOD_TOOL]["fired"] = True
        signals[METHOD_TOOL]["evidence"] = cap_fails
    # ...or the learned signal: a feature that has NEVER succeeded here
    importance = feature_importance(ws)
    succ_feats: set[str] = set()
    for _path, other in pool.load_all(ws):
        if _is_verified_success(other):
            succ_feats.update(str(f) for f in
                              other.get("context_features") or [])
    never_succeeded = [f for f in feats if f not in succ_feats]
    for f in never_succeeded:
        row = next((r for r in importance["features"]
                    if r["feature"] == f), None)
        if row is not None and row["contrast"] > 0.0 \
                and row["fail_rate"] >= 1.0:
            signals[METHOD_TOOL]["fired"] = True
            if f not in signals[METHOD_TOOL]["evidence"]:
                signals[METHOD_TOOL]["evidence"].append(f)

    # depth_insufficient — verified partial progress on a failed task
    progress = rs.milestone_progress(ws, str(doc.get("claim")),
                                     doc.get("milestones") or [])
    if progress > 0.0:
        signals[METHOD_DEPTH]["fired"] = True
        signals[METHOD_DEPTH]["evidence"] = [
            f"verified milestone progress {progress:.2f} with no completion"]

    # hypothesis_wrong — the environment is proven workable
    shared = sorted(feat_set & succ_feats)
    if shared:
        signals[METHOD_HYPOTHESIS]["fired"] = True
        signals[METHOD_HYPOTHESIS]["evidence"] = [
            "verified successes share features: " + ", ".join(shared),
            *shared,
        ]

    method = METHOD_TOOL if signals[METHOD_TOOL]["fired"] else (
        METHOD_DEPTH if signals[METHOD_DEPTH]["fired"] else (
            METHOD_HYPOTHESIS if signals[METHOD_HYPOTHESIS]["fired"]
            else None))
    return {"schema": ATTRIBUTION_SCHEMA, "claim": str(doc.get("claim")),
            "method": method, "signals": signals,
            "exogenous": list(importance["exogenous"])}


def report(ws, doc: dict | None = None) -> dict:
    """The full attribution report (schema attribution-report/1):
    feature importance + the exogenous demotion + the method verdict
    when a (failed) episode document is given. Deterministic."""
    ws = Path(ws)
    importance = feature_importance(ws)
    out = dict(importance)
    out["schema"] = ATTRIBUTION_SCHEMA
    if doc is not None:
        out["method"] = method_attribution(ws, doc)
        out["claim"] = str(doc.get("claim"))
    return out


def report_ref(report: dict) -> str:
    """The stable 16-hex digest a switch commit rides as its
    `attribution_ref` (blind lane changes are RED — commit_semantics)."""
    canonical = json.dumps(report, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def knob_on() -> bool:
    """The component-ablation switch (the third of four knobs)."""
    import os  # noqa: PLC0415 — leaf face, keeps module import-light
    return os.environ.get("KUNGLAO_META_ATTRIBUTION", "1") != "0"
