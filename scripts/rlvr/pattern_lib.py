#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pattern_lib.py — the expertise layer's loader/matcher/renderer (#518 PR-3).

The F1 ruling's mechanism: give the novice driver the champion's track
map. Patterns are FEATURE-KEYED (observable task shape — surface,
scaffold kinds, languages), never identity-keyed; the store lives under
scripts/rlvr/patterns/ where eval_split_lint polices it for instance
constants and holdout unit-ids. A matched pattern renders its playbook
into the worker dispatch prompt and boosts its family_hint in the
envelope sampler's proposal prior (the #460 feature-conditioned face,
proposal-channel only — outcome data still never enters any prior).

Zero-decision posture: pure functions; a broken store or a failed
extraction degrades to no-match (the prompt is byte-unchanged).
"""
from __future__ import annotations

from pathlib import Path

import yaml

STORE = Path(__file__).resolve().parent / "patterns"
_SCHEMA = "kunglao-pattern/1"
_MATCH_FLOOR = 2.0  # surface hit alone matches; less does not


def load_patterns(root: Path | None = None) -> list[dict]:
    """Every valid pattern in the store, sorted by id. Invalid files are
    skipped (the store is data; a bad row must never break dispatch)."""
    d = Path(root) if root is not None else STORE
    out: list[dict] = []
    for p in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(doc, dict) and _valid(doc):
            out.append(doc)
    return out


def _valid(doc: dict) -> bool:
    if doc.get("schema") != _SCHEMA:
        return False
    if not str(doc.get("id") or "").startswith("PAT-"):
        return False
    pb = doc.get("playbook")
    if not isinstance(pb, dict) or not pb.get("flow"):
        return False
    prov = doc.get("provenance")
    if not isinstance(prov, dict) or not prov.get("mined_from_families"):
        return False
    return isinstance(doc.get("features"), dict)


def features_from_task_str(task_yaml_text: str) -> dict:
    """Observable task shape: surface (family contract row), scaffold
    file kinds, declared language. Absent family degrades surface to ''
    (matches nothing — the absence idiom)."""
    doc = yaml.safe_load(task_yaml_text) or {}
    if not isinstance(doc, dict):
        return {"target_surface": "", "languages": [], "scaffold_kinds": []}
    surface = ""
    family = str(doc.get("family") or "")
    if family:
        try:
            import eval_contract  # noqa: PLC0415 — scripts sibling
            surface = str(eval_contract.require_family(family)["target_surface"])
        except Exception:  # noqa: BLE001 — unknown family matches nothing
            surface = ""
    sc = doc.get("workspace_scaffold") or {}
    if not isinstance(sc, dict):
        sc = {}
    lang = str(sc.get("language") or "")
    return {
        "target_surface": surface,
        "languages": [lang] if lang else [],
        "scaffold_kinds": [str(f) for f in (sc.get("files") or [])],
    }


def features_from_task(task_dir) -> dict:
    p = Path(task_dir) / "task.yaml"
    try:
        return features_from_task_str(p.read_text(encoding="utf-8"))
    except OSError:
        return {"target_surface": "", "languages": [], "scaffold_kinds": []}


def _basename(k: str) -> str:
    return k.rsplit("/", 1)[-1].lower()


def _score(pat: dict, feats: dict) -> float:
    pf = pat.get("features") or {}
    s = 0.0
    surfaces = pf.get("target_surface") or []
    if feats["target_surface"] and feats["target_surface"] in surfaces:
        s += 2.0
    want_langs = {str(x).lower() for x in (pf.get("languages") or [])}
    have_langs = {x.split("/")[0] for x in feats["languages"]}
    if want_langs & have_langs:
        s += 1.0
    want_kinds = {_basename(str(k)) for k in (pf.get("scaffold_kinds") or [])}
    have_kinds = {_basename(str(k)) for k in feats["scaffold_kinds"]}
    if want_kinds & have_kinds:
        s += 1.5
    return s


def match_pattern(patterns: list[dict], feats: dict) -> dict | None:
    """Best pattern above the floor, or None (the prompt stays clean)."""
    best, best_score = None, 0.0
    for p in patterns:
        sc = _score(p, feats)
        if sc > best_score:
            best, best_score = p, sc
    return best if best_score >= _MATCH_FLOOR else None


def render_playbook(pat: dict) -> str:
    pb = pat["playbook"]
    lines = [f"PLAYBOOK {pat['id']} — {pat.get('title', '')}",
             "A mined family pattern applies to this task shape. Follow "
             "the flow; it encodes field-tested discipline.",
             "flow:"]
    for i, step in enumerate(pb.get("flow") or [], start=1):
        lines.append(f"  {i}. {step}")
    for key, val in pb.items():
        if key == "flow":
            continue
        lines.append(f"{key}:")
        if isinstance(val, list):
            lines.extend(f"  - {v}" for v in val)
        else:
            lines.append(f"  {val}")
    return "\n".join(lines)


def family_boost(pat: dict | None) -> dict[str, float]:
    """The sampler's proposal boost for a matched pattern (#460 face:
    proposal-channel only, registry-constrained by the sampler itself)."""
    if not pat:
        return {}
    fam = str(pat.get("family_hint") or "")
    w = pat.get("weight", 1.0)
    return {fam: float(w) if isinstance(w, (int, float)) else 1.0} or {}
