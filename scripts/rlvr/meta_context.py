# -*- coding: utf-8 -*-
"""meta_context.py — the context-feature assembly face (the meta-policy
rewire's feature half).

The meta-policy conditions commit selection on a context-feature
vector; this module owns WHERE the features come from. Every source is
one that already exists in the workspace — nothing is invented here:

  - ``task_spec.yaml``   the task features: the lane (the material
    contract), the dynamic-RE constraint, the depth, the verification
    method, and the model_selection family candidates;
  - ``evidence/die.json`` + ``evidence/apkid.json``  the protection
    salients (the die/probe products): detected packer, obfuscators,
    and the max-section-entropy class;
  - ``runs/env-state.json`` (+ the dispatch-gate probe cache)  the #812
    capability facts, READ-ONLY: a feature face never executes a probe
    (probing is the dispatch gate's narrow face, never the value
    selector's).

The output is a deterministic token list: deduped, sorted, slugged
(lowercase, ``[^a-z0-9]+ -> -``), capped at the episode schema limits
(the same caps the pool validates). Absent sources degrade honestly —
a missing file contributes NO token (absence is not a feature; the
conservative #421 posture). An unreadable source degrades the same
way: feature assembly never raises into the caller.

Token vocabulary (stable, categorical, <= 64 chars):
  ``lane-<lane>``  ``dyn-allowed|dyn-forbidden``  ``depth-<depth>``
  ``verif-<method>``  ``fam-<candidate>``  ``packer-<name>``
  ``obf-<name>``  ``entropy-high|entropy-mid|entropy-low``
  ``cap-<name>-<status>``

Zero telemetry points (Standard 11). Nothing here writes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from rlvr import episode_schema as es

#: entropy classes (documented policy constants, not fitted: the same
#: section-entropy reading the difficulty face uses, bucketed)
ENTROPY_HIGH = 7.0
ENTROPY_MID = 6.0

#: the dynamic-execution-dependent commit prior shift keys on these
#: token shapes (meta_policy.cold_start_prior consumes the contract)
DYN_FORBIDDEN_TOKEN = "dyn-forbidden"
_CAP_FAIL_SUFFIX = "-fail"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(value: object) -> str:
    """One stable feature token body: lowercase, non-alnum -> '-', at
    most the schema's token cap."""
    s = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return s[:es._FEATURE_TOKEN_MAX]


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8",
                                              errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8",
                                                  errors="replace"))
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _task_spec_features(ws: Path) -> list[str]:
    spec = _read_yaml(ws / "task_spec.yaml")
    out: list[str] = []
    lane = str(spec.get("lane") or "").strip()
    if lane:
        out.append(f"lane-{slug(lane)}")
    constraints = spec.get("constraints") or {}
    dyn = str((constraints or {}).get("dynamic_re") or "").strip()
    if dyn:
        out.append(f"dyn-{slug(dyn)}")
    depth = str(spec.get("depth") or "").strip()
    if depth:
        out.append(f"depth-{slug(depth)}")
    verif = str(spec.get("verification_method") or "").strip()
    if verif:
        out.append(f"verif-{slug(verif)}")
    for q in spec.get("primary_questions") or []:
        if not isinstance(q, dict):
            continue
        for cand in q.get("candidates") or []:
            body = slug(cand)
            if body:
                out.append(f"fam-{body}")
    return out


def _die_features(ws: Path) -> list[str]:
    die = _read_json(ws / "evidence" / "die.json")
    derived = die.get("derived") if isinstance(die.get("derived"), dict) \
        else {}
    out: list[str] = []
    packer = derived.get("detected_packer")
    if isinstance(packer, str) and packer.strip():
        out.append(f"packer-{slug(packer)}")
    table = derived.get("section_table") or die.get("section_table") or []
    entropies = []
    for row in table if isinstance(table, list) else []:
        if not isinstance(row, dict) or row.get("entropy") is None:
            continue
        try:
            value = float(row["entropy"])
        except (TypeError, ValueError):  # data noise, not a crash
            continue
        if value == value and value not in (float("inf"),
                                            float("-inf")):
            entropies.append(value)
    if entropies:
        top = max(entropies)
        if top >= ENTROPY_HIGH:
            out.append("entropy-high")
        elif top >= ENTROPY_MID:
            out.append("entropy-mid")
        else:
            out.append("entropy-low")
    return out


def _apkid_features(ws: Path) -> list[str]:
    apkid = _read_json(ws / "evidence" / "apkid.json")
    if apkid.get("status") != "ok":  # unavailable/error = absent
        return []
    summary = apkid.get("summary") if \
        isinstance(apkid.get("summary"), dict) else {}
    out: list[str] = []
    for key, prefix in (("packer", "packer-"), ("obfuscator", "obf-")):
        raw = summary.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            body = slug(item)
            if body:
                out.append(f"{prefix}{body}")
    return out


def _capability_features(ws: Path) -> list[str]:
    """The #812 capability facts, READ-ONLY: the env-state snapshot is
    the single source of truth; the dispatch-gate cache rides as the
    fallback. This face NEVER probes (probing is the dispatch gate's
    face; the conservative posture keeps absence unstamped)."""
    out: list[str] = []
    snapshot = _read_json(ws / "runs" / "env-state.json").get(
        "per_capability")
    if isinstance(snapshot, dict):
        for name, entry in snapshot.items():
            status = entry.get("status") if isinstance(entry, dict) \
                else None
            if isinstance(status, str) and status.strip():
                out.append(f"cap-{slug(name)}-{slug(status)}")
        return out
    cache = _read_json(ws / "runs" / ".capability-probe-cache.json")
    for name, entry in cache.items():
        status = entry.get("status") if isinstance(entry, dict) else None
        if isinstance(status, str) and status.strip():
            out.append(f"cap-{slug(name)}-{slug(status)}")
    return out


def assemble(ws) -> list[str]:
    """The context-feature vector: every real source, deduped, sorted,
    capped at the episode schema limits. Deterministic; never raises;
    absent sources contribute nothing."""
    ws = Path(ws)
    raw = (_task_spec_features(ws) + _die_features(ws)
           + _apkid_features(ws) + _capability_features(ws))
    seen: dict[str, None] = {}
    for token in raw:
        if token.strip():
            seen.setdefault(token, None)
    out = sorted(seen)
    return out[:es._FEATURE_MAX]


def is_dynamic_constrained(features: list[str]) -> bool:
    """True when the vector carries the dynamic-RE-forbidden token —
    the exogenous shift key the cold-start prior consumes."""
    return DYN_FORBIDDEN_TOKEN in {str(f) for f in features}


def has_dynamic_capability_failure(features: list[str]) -> bool:
    """True when any capability fact reports a failed channel (the
    cap-*-fail token shape)."""
    return any(str(f).startswith("cap-")
               and str(f).endswith(_CAP_FAIL_SUFFIX) for f in features)
