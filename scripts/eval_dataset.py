#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_dataset.py — evaluation-dataset core (the eval-dataset card) (schema contract + validator).

The per-task capability-measurement pattern (battle autoresearch.sh: a run
emits ``METRIC <name>=<value>``, the verdict is arithmetic-level evidence,
evidence is auto-archived, failures emit structured signals) generalized
into a versioned dataset. This module owns the CONTRACT face:

  - path constants + versioning (eval-v1; VERSION/changelog live under
    ``eval/v1/``);
  - the held-out path contract: eval-corpus prefixes are distiller-
    excluded — the distiller's corpus (not yet built) must source
    through ``filter_distiller_sources``, which never returns eval paths;
  - the task-unit validator (mirrors schemas/eval-task-v1.json): anchors
    (goal_verbatim / success_criterion / verification_method — the three-anchor intake contract),
    workspace scaffold, checker contract (runner-style: METRIC emission,
    arithmetic verdict, evidence archive), metric set, contamination block;
  - the checker ARITHMETIC core shared by every oracle face: threshold
    ceil-math, METRIC-line formatting, failure codes, the evidence-
    bar results-row shape, and the 1/k-guessing probability
    (p = 2^-space_bits — arithmetic, no run needed).

Task units live at ``eval/<version>/tasks/<tier>/<task_id>/``. The smoke
tier carries constructed targets only (scripts/eval_targets.py mints
them); historical replay (the historical-replay lane) and the public corpus are later lanes and
refuse validation as smoke-tier sources.

stdlib only.
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "eval"

# ---- versioning ----------------------------------------------------------
# per-tier corpus versions live in TIER_EVAL_VERSION (below, vocabulary)

# ---- held-out path contract (distiller-lane exclusion) -------------------
# Every prefix here is OFF-LIMITS as a distillation-corpus source: eval
# tasks never enter the distiller's corpus, so capability claims and the data
# they were tuned on never share a source. The distiller does not exist
# yet; the contract is pinned on these constants (see
# tests/test_eval_dataset_299.py) so the consumer lane inherits the guard.
EVAL_CORPUS_PREFIXES: tuple[str, ...] = ("eval/",)


def filter_distiller_sources(paths: list[str]) -> list[str]:
    """The ONLY sanctioned source-list builder for a distiller: drops every
    eval-corpus path (and any future eval prefix) before anything downstream
    can see it."""
    return [p for p in paths
            if not any(p == px.rstrip("/") or p.startswith(px)
                       for px in EVAL_CORPUS_PREFIXES)]


# ---- vocabulary ----------------------------------------------------------
ANCHOR_FIELDS: tuple[str, ...] = (
    "goal_verbatim", "success_criterion", "verification_method")
# mirrors oracle_anchors.METHOD_OPTIONS (the three-anchor contract) —
# restated here without the
# import to keep this module stdlib-only (yaml aside) and import-order-safe
VERIFICATION_METHODS: tuple[str, ...] = (
    "reproduction", "replay-evidence", "static", "manual")

TIERS: tuple[str, ...] = ("smoke", "release")
# per-tier corpus version (#332 bump): the smoke corpus stays eval-v1; the
# release tier lands at eval-v1.1 (same v1 directory, changelog-appended —
# never mutated in place per the eval version rules)
TIER_EVAL_VERSION: dict[str, str] = {"smoke": "eval-v1", "release": "eval-v1.1"}
EVAL_VERSION = "eval-v1"
SOURCES: tuple[str, ...] = ("constructed", "historical-replay", "public-corpus")
CHECKER_KINDS: tuple[str, ...] = ("constant-hit", "pair-match", "replay-roundtrip")
ORACLE_KINDS: tuple[str, ...] = CHECKER_KINDS
REQUIRED_METRICS: tuple[str, ...] = (
    "ttc_seconds", "dispatch_count", "pass_at_k_contribution", "converged")

FAILURE_CODES: frozenset[str] = frozenset({
    "CONSTANT_MISS",     # static face: candidate misses embedded constants
    "PAIR_MISMATCH",     # replay face: too few pairs reproduce
    "TOOLCHAIN_MISSING", # replay face: go/node absent -> SKIP, never FAIL
    "BAD_CANDIDATE",     # candidate artifact missing / wrong shape -> refusal
    "BAD_TASK",          # task unit malformed / unknown -> refusal
})

RESULTS_SCHEMA = "kunglao-eval-results/1"
EVIDENCE_SCHEMA = "kunglao-eval-evidence/1"


# ---- corpus access -------------------------------------------------------
def iter_task_dirs(tier: str = "smoke", version: str = "v1") -> list[Path]:
    """All task-unit directories under eval/<version>/tasks/<tier>/, sorted."""
    base = EVAL_ROOT / version / "tasks" / tier
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and (d / "task.yaml").is_file())


def resolve_task_dir(task: str, tier: str | None = None,
                     version: str = "v1") -> Path:
    """A task id (searched across tiers when ``tier`` is None — the
    checker resolves release and smoke units by id alike) or an explicit
    task-dir path."""
    p = Path(task)
    if p.is_dir():
        return p
    tiers = [tier] if tier else list(TIERS)
    for t in tiers:
        for tdir in iter_task_dirs(t, version):
            if tdir.name == task:
                return tdir
    raise FileNotFoundError(
        f"unknown task {task!r} (tiers={tiers}, version={version})")


def load_task(tdir: Path) -> dict:
    return yaml.safe_load((Path(tdir) / "task.yaml").read_text(encoding="utf-8"))


# ---- validator (the executable mirror of schemas/eval-task-v1.json) ------
def _validate_identity(task: dict, errors: list[str]) -> None:
    if task.get("schema") != "kunglao-eval-task/1":
        errors.append(f"schema must be kunglao-eval-task/1, got {task.get('schema')!r}")
    if not task.get("task_id") or not isinstance(task.get("task_id"), str):
        errors.append("task_id must be a non-empty string")
    tier = task.get("tier")
    if tier not in TIERS:
        errors.append(f"tier must be one of {TIERS}, got {tier!r}")
    want_version = TIER_EVAL_VERSION.get(tier)
    if want_version is not None and task.get("eval_version") != want_version:
        errors.append(
            f"eval_version must be {want_version} for tier {tier!r}, "
            f"got {task.get('eval_version')!r}")
    source = task.get("source")
    if source not in SOURCES:
        errors.append(f"source must be one of {SOURCES}, got {source!r}")
    if tier == "smoke" and source != "constructed":
        errors.append(
            f"smoke tier carries constructed targets only, got source={source!r}")
    if not isinstance(task.get("seed"), int):
        errors.append("seed must be generator-stamped (int)")


def _validate_anchors(task: dict, errors: list[str]) -> None:
    anchors = task.get("anchors")
    if not isinstance(anchors, dict):
        errors.append("anchors must be a mapping")
        return
    for field in ANCHOR_FIELDS:
        v = anchors.get(field)
        if not v or not isinstance(v, str):
            errors.append(f"anchor {field} missing/blank (refuse analysis entry, #191)")
    method = anchors.get("verification_method")
    if method is not None and method not in VERIFICATION_METHODS:
        errors.append(f"verification_method {method!r} outside the #191 enum")


def _validate_scaffold(task: dict, errors: list[str]) -> None:
    ws = task.get("workspace_scaffold")
    if not isinstance(ws, dict):
        errors.append("workspace_scaffold must be a mapping")
        return
    if not ws.get("language"):
        errors.append("workspace_scaffold.language missing")
    files = ws.get("files")
    if not files or not isinstance(files, list):
        errors.append("workspace_scaffold.files must be a non-empty list")
    elif ws.get("entry") and ws["entry"] not in files:
        errors.append(f"workspace_scaffold.entry {ws.get('entry')!r} not among files")
    if not ws.get("candidate_contract"):
        errors.append("workspace_scaffold.candidate_contract missing "
                      "(the #236 control arm's execution surface)")


def _validate_checker(task: dict, errors: list[str]) -> None:
    checker = task.get("checker")
    if not isinstance(checker, dict):
        errors.append("checker must be a mapping")
        return
    kind = checker.get("kind")
    if kind not in CHECKER_KINDS:
        errors.append(f"checker.kind must be one of {CHECKER_KINDS}, got {kind!r}")
    oracles = checker.get("oracles")
    if not oracles or not isinstance(oracles, list):
        errors.append("checker.oracles must be a non-empty list")
        oracles = []
    else:
        off = [o for o in oracles if o not in ORACLE_KINDS]
        if off:
            errors.append(f"checker.oracles outside the enum: {off}")
        if kind not in oracles:
            errors.append(f"checker.kind {kind!r} must be armed in checker.oracles")
    metrics = checker.get("metrics")
    missing = [m for m in REQUIRED_METRICS if not metrics or m not in metrics]
    if missing:
        errors.append(f"checker.metrics missing required metric(s): {missing}")
    thresholds = checker.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("checker.thresholds must be a mapping")
        return
    if "constant-hit" in oracles and \
            not isinstance(thresholds.get("min_constant_hits"), int):
        errors.append(
            "thresholds.min_constant_hits required when constant-hit armed")
    if any(o in oracles for o in ("pair-match", "replay-roundtrip")):
        ratio = thresholds.get("min_pair_ratio")
        if not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
            errors.append("thresholds.min_pair_ratio must be in (0, 1] when a "
                          "replay face is armed")
    if not checker.get("entrypoint"):
        errors.append("checker.entrypoint missing (the mechanical checker shim)")


def _validate_truth_and_contamination(task: dict, errors: list[str]) -> None:
    gt = task.get("ground_truth")
    if not isinstance(gt, dict):
        errors.append("ground_truth must be a mapping")
    else:
        if gt.get("file") != "ground_truth.json":
            errors.append("ground_truth.file must be ground_truth.json")
        bits = gt.get("space_bits")
        if not isinstance(bits, int) or bits < 1:
            errors.append("ground_truth.space_bits must be a positive int "
                          "(the 1/k guessing baseline is 2^-space_bits)")
    cont = task.get("contamination")
    if not isinstance(cont, dict):
        errors.append("contamination must be a mapping")
        return
    if cont.get("held_out") is not True:
        errors.append("contamination.held_out must be true (eval NEVER feeds #298)")
    if cont.get("distiller_excluded") is not True:
        errors.append("contamination.distiller_excluded must be true")
    if cont.get("provenance") != "constructed":
        errors.append("contamination.provenance must be 'constructed' "
                      "(smoke lane: constructed targets only)")


def validate_task(task: dict) -> tuple[bool, list[str]]:
    """Structural validation of one task unit. Returns (ok, errors)."""
    if not isinstance(task, dict):
        return False, ["task unit is not a mapping"]
    errors: list[str] = []
    _validate_identity(task, errors)
    _validate_anchors(task, errors)
    _validate_scaffold(task, errors)
    _validate_checker(task, errors)
    _validate_truth_and_contamination(task, errors)
    return not errors, errors


# ---- checker arithmetic core --------------------------------------------
def min_pairs_for(ratio: float, count: int) -> int:
    """The pair-match threshold: ceil(ratio * count) — the case-admission C2 shape
    (>= 11 of 14 at 0.78) generalized."""
    return math.ceil(ratio * count)


def metric_line(name: str, value) -> str:
    """The autoresearch.sh-style emission: ``METRIC <name>=<value>``."""
    if isinstance(value, float):
        return f"METRIC {name}={value:g}"
    return f"METRIC {name}={value}"


def arithmetic_verdict(hits: int, min_constant_hits: int,
                       pairs_matched: int, pair_count: int,
                       min_pair_ratio: float) -> tuple[bool, list[dict]]:
    """The arithmetic-level verdict over both oracle faces. Only armed
    faces (positive thresholds / count > 0) contribute failures."""
    failures: list[dict] = []
    if min_constant_hits > 0 and hits < min_constant_hits:
        failures.append({
            "code": "CONSTANT_MISS",
            "detail": f"constant-hits {hits}/{min_constant_hits} (static face)",
        })
    if pair_count > 0:
        need = min_pairs_for(min_pair_ratio, pair_count)
        if pairs_matched < need:
            failures.append({
                "code": "PAIR_MISMATCH",
                "detail": f"pairs {pairs_matched}/{pair_count} match "
                          f"(threshold {need} at ratio {min_pair_ratio})",
            })
    return not failures, failures


def guess_pass_p(space_bits: int) -> float:
    """1/k guessing on a task whose answer space is ``space_bits`` wide:
    p = 2^-space_bits. The guess-1ofk baseline emits this per task — pure
    arithmetic, no run required."""
    return 2.0 ** (-space_bits)


def results_row(*, task_id: str, family: str, checker_kind: str,
                metrics: dict, verdict: str, failures: list,
                evidence_ref: str, arm: str,
                guess_pass_p: float | None = None) -> dict:
    """One results row, shaped for the evidence bar: a config-change
    PR attaches these rows (replay/eval evidence) to its description."""
    row = {
        "task_id": task_id,
        "family": family,
        "checker_kind": checker_kind,
        "metrics": {m: metrics.get(m, 0) for m in REQUIRED_METRICS},
        "verdict": verdict,
        "failures": list(failures),
        "evidence_ref": evidence_ref,
        "arm": arm,
    }
    if guess_pass_p is not None:
        row["guess_pass_p"] = guess_pass_p
    return row
