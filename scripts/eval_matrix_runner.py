#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_matrix_runner.py — the WS5 seven-arm capability matrix harness (B2 multi-sample + B3 uniform-scheduler arms included).

MEASUREMENT PREP ONLY: this is ORCHESTRATION — it launches the existing
per-unit arm runners (scripts/eval_loop_runner.py: the full loop face,
the bare control face, and the warm-context attribution face the matrix
reuses as-is) and tracks the runs. It makes ZERO model calls of its
own: every LLM-facing minute belongs to the child runner sessions, and
the real matrix run is an owner-visible act (the harness ships with a
--dry-run self-check; no matrix execution happens at review time).
The readout face lives in scripts/eval_matrix_report.py (--report).

The seven arms (docs/design/ws5-five-arms.yaml, the arm registry):

    cc-bare            bare Claude Code (the runner's cc-default face)
    cc-warm-context    cc-default + the train-store text render
                       (the RL-vs-context attribution arm)
    cc-multisample     B2 — bare CC sampled N times at the kunglao
                       arms' total budget: the arm's optional
                       sampling: {mode: multi-sample, samples: N,
                       budget_each: X} protocol (N x X must equal the
                       matrix budget — the same-cost contract). The
                       launcher expands one arm to N child rows per
                       unit, each capped at X; the readout aggregates
                       pass@k at equal cost.
    kunglao-cold       the full loop against a materialized EMPTY store
    kunglao-uniform    B3 — the harness without learning: the loop with
                       KUNGLAO_SCHEDULER=uniform (flat priors, the
                       learned state never influences family selection,
                       the propensity still rides the envelope)
    kunglao-warm       the full loop reading a warm posterior-store copy
    kunglao-warm-no-l1 kunglao-warm with recall ablated (KUNGLAO_RECALL=0)

Arms differ ONLY in declared faces (runner face, store kind, env). The
launcher is HERMETIC: KUNGLAO_RECALL / KUNGLAO_EXPANSION /
KUNGLAO_PREDICT_BEFORE_TRY are stripped from the inherited environment
before each arm's declared env merges — ambient shell state can never
contaminate an arm. Store isolation: warm arms read an ISOLATED per-run
COPY of the configured warm store (arms never share a live store), the
cold arm reads a materialized empty store dir, and the store env is
unset entirely for arms that declare store: none.

Faces:
  launch (default)  arms x units -> one child runner per (arm, unit),
                    per-run logs under <out>/<arm>/<unit>/, a progress
                    JSON at <out>/progress.json (schema
                    ws5-matrix-progress/1) rewritten as runs finish;
                    --max-parallel bounds concurrent children.
  --dry-run         lists what WOULD launch (per-run child argv, corpus
                    resolution, env face, store materialization) and
                    writes the progress JSON with every run "planned".
                    No session starts, no run dir is created.
  --report          readout over COMPLETED runs (the
                    scripts/eval_matrix_report.py face): per arm x unit
                    matrix of final_status, budget consumed,
                    transitions, facts, and the 80/20 gate primitives.

The 80/20 gate face (readout module): honest primitives — the umbrella
defines the target as "regret-weighted decision points" without a
binding per-decision definition, so the harness emits primitives, not
a verdict. Redefining the gate is the owner's call; the primitives do
not move.

Usage:
  eval_matrix_runner.py [--config docs/design/ws5-five-arms.yaml]
                        [--units id,id] [--arms id,id]
                        [--budget-usd F] [--wall-cap-s S]
                        [--corpus-root DIR] [--warm-store DIR]
                        [--warm-context-from DIR]
                        [--session-cmd CMD] [--plugin-dir DIR]
                        [--max-parallel N] [--out DIR]
                        [--dry-run] [--report] [--progress]

Exit: 0 completed (measurement rows are measurements, not run
failures); 2 refusal (bad config, unresolvable unit, missing warm
source on a warm arm).

stdlib + yaml only (the repo's runtime deps).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml

from eval_matrix_report import (  # the readout face (one-way import)
    build_report,
    newest_results_doc,
    print_report,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
RUNNER_SCRIPT = SCRIPT_DIR / "eval_loop_runner.py"

SCHEMA_PROGRESS = "ws5-matrix-progress/1"
DEFAULT_CONFIG = REPO_ROOT / "docs" / "design" / "ws5-five-arms.yaml"
DEFAULT_OUT = REPO_ROOT / "runs" / "ws5-matrix"
DEFAULT_OUT_REL = "runs/ws5-matrix"

# the cross-task posterior store (the WS2 carrier): the env var the loop
# reads the store root through, and the store file name inside it
STORE_ENV = "KUNGLAO_POSTERIOR_STORE"
STORE_FILE = "posterior-store.jsonl"
# the operator-local corpus root env (the blocked-path measurement face)
EVAL_ROOT_ENV = "KUNGLAO_EVAL_ROOT"
# hermeticity: stripped from the inherited env before arm env merges
STRIPPED_ENV = ("KUNGLAO_RECALL", "KUNGLAO_EXPANSION",
                "KUNGLAO_PREDICT_BEFORE_TRY", "KUNGLAO_SCHEDULER")

VALID_FACES = ("loop", "cc-default", "cc-warm-context")
VALID_STORES = ("none", "cold", "warm")
VALID_CORPORA = ("repo", "operator")
# the B2 face: a cc arm's optional sampling protocol — N independent
# samples of the same face at N x budget_each, which must equal the
# matrix budget (same-cost is the whole point: pass@k at equal cost,
# never at a discount)
VALID_SAMPLING_MODES = ("multi-sample",)

RC_OK, RC_REFUSED = 0, 2

_PROGRESS_LOCK = threading.Lock()


class ConfigError(ValueError):
    """The arm registry is malformed — refuse, never guess."""


# ---- the arm registry -----------------------------------------------------

def _validate_arm(i: int, arm) -> tuple[str, str]:
    """One arm entry's structural validation -> (id, runner_face)."""
    where = f"arms[{i}]"
    if not isinstance(arm, dict):
        raise ConfigError(f"{where} must be a mapping")
    aid = str(arm.get("id") or "")
    if not aid:
        raise ConfigError(f"{where} missing id")
    face = arm.get("runner_face")
    if face not in VALID_FACES:
        raise ConfigError(
            f"{where} runner_face must be one of {VALID_FACES}, "
            f"got {face!r}")
    store = arm.get("store")
    if store not in VALID_STORES:
        raise ConfigError(
            f"{where} store must be one of {VALID_STORES}, got "
            f"{store!r}")
    # the registry cannot declare an ambiguous loop arm: the loop
    # face READS the posterior store, so a loop arm must say which
    # store state it measures (cold empty copy vs warm copy); the
    # cc faces never read it and must say none
    if face == "loop" and store not in ("cold", "warm"):
        raise ConfigError(
            f"{where}: a loop arm declares store cold|warm "
            f"(got {store!r} — an unset store would silently read "
            "the repo default)")
    if face != "loop" and store != "none":
        raise ConfigError(
            f"{where}: cc faces never read the store (got "
            f"{store!r})")
    env = arm.get("env") or {}
    if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in env.items()):
        raise ConfigError(f"{where} env must be a str->str mapping")
    sampling = _validate_sampling(i, arm)
    if sampling and face == "loop":
        raise ConfigError(
            f"{where}: cc faces own the sampling protocol (a loop arm "
            "is single-draw by design — the multi-sample rebuttal is a "
            "bare-CC experiment)")
    return aid, face


def _validate_sampling(i: int, arm) -> dict:
    """One arm's optional sampling protocol -> the normalized block ({}
    when the arm declares none). Multi-sample is the B2 face: N
    independent child runs of the SAME face at N x budget_each."""
    where = f"arms[{i}]"
    sampling = arm.get("sampling")
    if sampling is None:
        return {}
    if not isinstance(sampling, dict):
        raise ConfigError(f"{where} sampling must be a mapping")
    mode = sampling.get("mode")
    if mode not in VALID_SAMPLING_MODES:
        raise ConfigError(
            f"{where} sampling.mode must be one of "
            f"{VALID_SAMPLING_MODES}, got {mode!r}")
    samples = sampling.get("samples")
    if not isinstance(samples, int) or isinstance(samples, bool) \
            or samples < 2:
        raise ConfigError(
            f"{where} sampling.samples must be an integer >= 2, got "
            f"{samples!r}")
    budget_each = sampling.get("budget_each")
    if not isinstance(budget_each, (int, float)) \
            or isinstance(budget_each, bool) or budget_each <= 0:
        raise ConfigError(
            f"{where} sampling.budget_each must be a positive number, "
            f"got {budget_each!r}")
    return {"mode": str(mode), "samples": samples,
            "budget_each": float(budget_each)}


def _check_same_cost(arms: list, budget: dict) -> None:
    """The B2 same-cost contract: a multi-sample arm's total spend
    (samples x budget_each) must equal the matrix budget — pass@k
    answers "is it just more sampling?" only AT EQUAL COST, so a
    discounted or inflated B2 arm refuses the whole matrix."""
    budget_usd = float(budget.get("budget_usd", 2.0))
    for i, arm in enumerate(arms):
        sampling = arm.get("sampling") or {}
        if not sampling:
            continue
        total = sampling["samples"] * float(sampling["budget_each"])
        if abs(total - budget_usd) > 1e-9 * max(1.0, budget_usd):
            raise ConfigError(
                f"arms[{i}] ({arm.get('id')}): the same-cost contract "
                f"violated — {sampling['samples']} x "
                f"{sampling['budget_each']} = {total} != the matrix "
                f"budget {budget_usd} (pass@k at equal cost, never at "
                "a discount)")


def _validate_unit(i: int, unit) -> tuple[str, str, str]:
    """One unit entry's structural validation -> (id, corpus, tier)."""
    where = f"units[{i}]"
    entry = {"id": unit} if isinstance(unit, str) else unit
    if not isinstance(entry, dict) or not entry.get("id"):
        raise ConfigError(f"{where} must carry an id")
    corpus = entry.get("corpus", "repo")
    if corpus not in VALID_CORPORA:
        raise ConfigError(
            f"{where} corpus must be one of {VALID_CORPORA}, got "
            f"{corpus!r}")
    if not entry.get("tier"):
        raise ConfigError(f"{where} missing tier")
    return str(entry["id"]), str(corpus), str(entry["tier"])


def load_config(path: Path) -> dict:
    """Parse + validate the declarative arm registry. Raises ConfigError
    on any structural fault — the registry is the experiment's contract,
    a malformed arm refuses the whole matrix rather than degrading."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config unreadable: {exc}") from exc
    if doc.get("schema") != "ws5-five-arms/1":
        raise ConfigError(
            f"schema must be ws5-five-arms/1, got {doc.get('schema')!r}")

    arms = doc.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ConfigError("arms must be a non-empty list")
    seen: set[str] = set()
    for i, arm in enumerate(arms):
        aid, _face = _validate_arm(i, arm)
        if aid in seen:
            raise ConfigError(f"duplicate arm id {aid!r}")
        seen.add(aid)

    units = doc.get("units")
    if not isinstance(units, list) or not units:
        raise ConfigError("units must be a non-empty list")
    seen_u: set[str] = set()
    for i, unit in enumerate(units):
        uid, _corpus, _tier = _validate_unit(i, unit)
        if uid in seen_u:
            raise ConfigError(f"duplicate unit id {uid!r}")
        seen_u.add(uid)

    budget = doc.get("budget") or {}
    if not isinstance(budget, dict):
        raise ConfigError("budget must be a mapping")
    warm = doc.get("warm_up") or {}
    if not isinstance(warm, dict):
        raise ConfigError("warm_up must be a mapping")
    _check_same_cost(arms, budget)
    return doc


def config_units(doc: dict) -> list[dict]:
    """Normalized unit entries ({id, corpus, tier}) in declared order."""
    return [{"id": str(u if isinstance(u, str) else u["id"]),
             "corpus": "repo" if isinstance(u, str) else str(
                 u.get("corpus", "repo")),
             "tier": "release" if isinstance(u, str) else str(u["tier"])}
            for u in doc.get("units", [])]


def config_arms(doc: dict) -> list[dict]:
    """Normalized arm entries in declared order."""
    return list(doc.get("arms", []))


# ---- unit resolution ------------------------------------------------------

def _unit_exists(root: Path, tier: str, unit: str) -> bool:
    return (Path(root) / "v1" / "tasks" / tier / unit / "task.yaml") \
        .is_file()


def resolve_unit(unit: dict, operator_root: Path | None) -> tuple[bool, str]:
    """Path-existence check for one unit entry against its declared
    corpus. The child runner does the authoritative resolution; this is
    the plan-time honesty check (a dry-run names unresolvable units
    instead of discovering them mid-matrix). Returns (ok, detail)."""
    if unit["corpus"] == "repo":
        root = REPO_ROOT / "eval"
    else:
        if operator_root is None:
            return False, (f"operator corpus requested but no root: set "
                           f"{EVAL_ROOT_ENV} or --corpus-root")
        root = operator_root
    if _unit_exists(root, unit["tier"], unit["id"]):
        return True, str(root)
    return False, f"no task.yaml under {root}/v1/tasks/{unit['tier']}"


# ---- run planning ---------------------------------------------------------

@dataclass(frozen=True)
class RunPlan:
    """One (arm, unit) cell of the matrix — everything needed to launch
    and to account for the run. A multi-sample arm expands to
    sample_count plans per unit (sample_index 0..N-1), each capped at
    budget_each, each its own run dir s0..s{N-1}."""
    arm_id: str
    runner_face: str
    unit: str
    tier: str
    corpus: str
    run_dir: Path
    store_kind: str
    env_extra: tuple[tuple[str, str], ...]  # frozen mapping face
    sample_index: int = 0
    sample_count: int = 1
    budget_each: float | None = None


def plan_runs(doc: dict, out: Path, *, arms_filter: list[str] | None,
              units_filter: list[str] | None) -> list[RunPlan]:
    """The cartesian matrix (arms x units), declared order, optionally
    filtered. Filters name registry ids — an unknown id refuses."""
    arms = config_arms(doc)
    units = config_units(doc)
    if arms_filter:
        known = {a["id"] for a in arms}
        unknown = [a for a in arms_filter if a not in known]
        if unknown:
            raise ConfigError(f"unknown arm id(s): {unknown}")
        arms = [a for a in arms if a["id"] in set(arms_filter)]
    if units_filter:
        known = {u["id"] for u in units}
        unknown = [u for u in units_filter if u not in known]
        if unknown:
            raise ConfigError(f"unknown unit id(s): {unknown}")
        units = [u for u in units if u["id"] in set(units_filter)]
    plans: list[RunPlan] = []
    for arm in arms:
        sampling = arm.get("sampling") or {}
        samples = int(sampling.get("samples", 1)) if sampling else 1
        budget_each = (float(sampling["budget_each"])
                       if sampling else None)
        for unit in units:
            base = Path(out) / arm["id"] / unit["id"]
            # the B2 expansion: one registry arm becomes N child runs
            # per unit, each its own sample dir, each capped at
            # budget_each so the arm's total equals the matrix budget
            for k in range(samples):
                plans.append(RunPlan(
                    arm_id=arm["id"],
                    runner_face=arm["runner_face"],
                    unit=unit["id"],
                    tier=unit["tier"],
                    corpus=unit["corpus"],
                    run_dir=base / f"s{k}" if samples > 1 else base,
                    store_kind=arm["store"],
                    env_extra=tuple(sorted(
                        (arm.get("env") or {}).items())),
                    sample_index=k,
                    sample_count=samples,
                    budget_each=budget_each))
    return plans


# ---- child construction (pure — the launch shape the tests pin) ----------

def child_env(plan: RunPlan, base: dict | None = None, *,
              operator_root: str | None = None) -> dict:
    """The child runner's environment: inherited state MINUS the
    ablation faces, plus the arm's declared env (which wins), plus the
    store face (cold = a materialized empty dir, warm = an isolated
    copy of the warm store, none = unset). Deterministic and pure —
    materialization happens separately at launch time."""
    env = dict(base if base is not None else os.environ)
    for name in STRIPPED_ENV:
        env.pop(name, None)
    env.pop(STORE_ENV, None)
    if plan.store_kind in ("cold", "warm"):
        env[STORE_ENV] = str(plan.run_dir / "store")
    if plan.corpus == "operator":
        if not operator_root:
            raise ConfigError(
                f"unit {plan.unit} runs on the operator corpus but no "
                f"root is configured ({EVAL_ROOT_ENV} / --corpus-root)")
        env[EVAL_ROOT_ENV] = str(operator_root)
    else:
        env.pop(EVAL_ROOT_ENV, None)
    for key, value in plan.env_extra:
        env[key] = value
    return env


def child_argv(plan: RunPlan, *, budget_usd: float, wall_cap_s: float,
               session_cmd: str | None = None,
               plugin_dir: Path | None = None,
               warm_context_from: Path | None = None) -> list[str]:
    """The child runner argv: one (arm, unit) through the existing
    per-unit face — same caps, extractor and checker either way."""
    argv = [sys.executable, str(RUNNER_SCRIPT),
            "--tier", plan.tier,
            "--tasks", plan.unit,
            "--arm", plan.runner_face,
            "--budget-usd", str(budget_usd),
            "--wall-cap-s", str(wall_cap_s),
            "--out", str(plan.run_dir)]
    if plan.runner_face == "cc-warm-context":
        if warm_context_from is None:
            raise ConfigError(
                f"arm {plan.arm_id} renders the train-store context but "
                "no source workspace is configured (--warm-context-from "
                "/ warm_up.warm_context_source)")
        argv += ["--warm-context-from", str(warm_context_from)]
    if session_cmd:
        argv += ["--session-cmd", session_cmd]
    if plugin_dir:
        argv += ["--plugin-dir", str(plugin_dir)]
    return argv


# ---- store materialization ------------------------------------------------

def warm_source_fault(plan: RunPlan, warm_source: Path | None) -> str | None:
    """Why a warm arm cannot honestly launch with this source (None = no
    fault). Shared by the dry-run face (predict the refusal) and the
    materializer (enforce it) — the dry-run's shape and the launch's
    behavior can never disagree."""
    if plan.store_kind != "warm":
        return None
    if warm_source is None:
        return (f"arm {plan.arm_id} declares store warm but the registry "
                "names no warm_up.store_source (and no --warm-store "
                "override) — the warm claim would be false, refusing")
    if not (Path(warm_source) / STORE_FILE).is_file():
        return f"warm store source has no {STORE_FILE}: {warm_source}"
    return None


def materialize_store(plan: RunPlan, warm_source: Path | None) -> Path:
    """The run's isolated store dir. cold: an EMPTY dir (the store read
    face no-ops over zero rows). warm: an isolated COPY of the configured
    warm store — arms never share a live store, so one arm's settlement
    writes can never contaminate another arm's reads mid-matrix."""
    store_dir = plan.run_dir / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    if plan.store_kind == "warm":
        fault = warm_source_fault(plan, warm_source)
        if fault:
            shutil.rmtree(store_dir)
            raise ConfigError(fault)
        shutil.copy2(Path(warm_source) / STORE_FILE,
                     store_dir / STORE_FILE)
    return store_dir


# ---- progress -------------------------------------------------------------

def _run_row(plan: RunPlan, status: str, **extra) -> dict:
    row = {"arm": plan.arm_id, "unit": plan.unit, "tier": plan.tier,
           "corpus": plan.corpus, "status": status,
           "run_dir": str(plan.run_dir)}
    if plan.sample_count > 1:
        row["sample"] = plan.sample_index
        row["sample_count"] = plan.sample_count
        row["budget_each"] = plan.budget_each
    row.update(extra)
    return row


def write_progress(out: Path, doc: dict) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "progress.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def read_progress(out: Path) -> dict | None:
    p = Path(out) / "progress.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---- launch ---------------------------------------------------------------

def _launch_one(plan: RunPlan, *, budget_usd: float, wall_cap_s: float,
                session_cmd: str | None, plugin_dir: Path | None,
                warm_source: Path | None, warm_context_from: Path | None,
                operator_root: str | None, dry_run: bool) -> dict:
    """One matrix cell. Dry-run: record the would-launch shape and touch
    nothing. Real: materialize the store, spawn the child runner, wait,
    record the outcome. Returns the row appended to the progress doc."""
    ok, detail = resolve_unit(
        {"id": plan.unit, "corpus": plan.corpus, "tier": plan.tier},
        Path(operator_root) if operator_root else None)
    row = _run_row(plan, "planned", corpus_root=detail)
    if not ok:
        row["status"] = "unresolvable"
        row["detail"] = detail
        return row
    # the B2 face: a sample row rides budget_each, never the matrix
    # budget — the same-cost contract makes N x budget_each the total
    per_run_budget = (plan.budget_each if plan.budget_each is not None
                      else budget_usd)
    try:
        argv = child_argv(plan, budget_usd=per_run_budget,
                          wall_cap_s=wall_cap_s, session_cmd=session_cmd,
                          plugin_dir=plugin_dir,
                          warm_context_from=warm_context_from)
    except ConfigError as exc:
        row["status"] = "refused"
        row["detail"] = str(exc)
        return row
    env = child_env(plan, operator_root=operator_root)
    row["argv"] = argv
    row["store"] = plan.store_kind
    row["store_env"] = env.get(STORE_ENV)
    row["declared_env"] = dict(plan.env_extra)
    fault = warm_source_fault(plan, warm_source)
    if fault:
        # the dry-run predicts the launch: a warm arm without a usable
        # source WOULD refuse — the shape and the behavior never disagree
        row["status"] = "refused"
        row["detail"] = fault
        return row
    if dry_run:
        return row
    try:
        materialize_store(plan, warm_source)
    except (ConfigError, OSError) as exc:
        row["status"] = "refused"
        row["detail"] = str(exc)
        return row
    plan.run_dir.mkdir(parents=True, exist_ok=True)
    log_path = plan.run_dir / "runner.log"
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(argv, env=env, stdout=log,
                              stderr=subprocess.STDOUT, cwd=str(REPO_ROOT))
    row["status"] = "done" if proc.returncode == 0 else "child_error"
    row["child_rc"] = proc.returncode
    row["wall_s"] = round(time.time() - started, 2)
    doc = newest_results_doc(plan.run_dir)
    if doc and doc.get("rows"):
        child_row = doc["rows"][0]
        row["verdict"] = child_row.get("verdict")
        loop = child_row.get("loop") or {}
        row["loop_status"] = loop.get("status")
        session = loop.get("session") or {}
        cost = (session.get("session_cost") or {}).get("total_cost_usd")
        row["budget_usd"] = cost
        row["session_wall_s"] = session.get("wall_s")
        row["workspace"] = loop.get("workspace")
        row["results_ref"] = str(sorted(
            plan.run_dir.glob("eval-results-*.json"))[-1])
    return row


def _update_progress(out: Path, progress: dict) -> None:
    with _PROGRESS_LOCK:
        progress["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime())
        write_progress(out, progress)


def launch(plans: list[RunPlan], out: Path, *, budget_usd: float,
           wall_cap_s: float, session_cmd: str | None,
           plugin_dir: Path | None, warm_source: Path | None,
           warm_context_from: Path | None, operator_root: str | None,
           max_parallel: int, dry_run: bool) -> dict:
    """The whole matrix: plan -> per-cell launch -> progress JSON. The
    progress doc is the run's spine: --report reads it (and falls back
    to scanning run dirs when a cell predates the spine)."""
    out = Path(out)
    progress = {"schema": SCHEMA_PROGRESS,
                "config": str(DEFAULT_CONFIG),
                "dry_run": dry_run,
                "budget_usd": budget_usd,
                "wall_cap_s": wall_cap_s,
                "max_parallel": max_parallel,
                "runs": []}
    rows = progress["runs"]
    if max_parallel > 1 and not dry_run:
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = [pool.submit(_launch_one, plan, budget_usd=budget_usd,
                                   wall_cap_s=wall_cap_s,
                                   session_cmd=session_cmd,
                                   plugin_dir=plugin_dir,
                                   warm_source=warm_source,
                                   warm_context_from=warm_context_from,
                                   operator_root=operator_root,
                                   dry_run=dry_run)
                       for plan in plans]
            for fut in futures:
                rows.append(fut.result())
                _update_progress(out, progress)
    else:
        for plan in plans:
            rows.append(_launch_one(
                plan, budget_usd=budget_usd, wall_cap_s=wall_cap_s,
                session_cmd=session_cmd, plugin_dir=plugin_dir,
                warm_source=warm_source,
                warm_context_from=warm_context_from,
                operator_root=operator_root, dry_run=dry_run))
            _update_progress(out, progress)
    _update_progress(out, progress)
    return progress


# ---- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_matrix_runner.py",
        description="the WS5 seven-arm capability matrix harness — "
                    "orchestration only, zero model calls of its own")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="the declarative arm registry")
    ap.add_argument("--units", default="",
                    help="comma-separated unit ids (default: the "
                         "registry's list)")
    ap.add_argument("--arms", default="",
                    help="comma-separated arm ids (default: all arms)")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="per-run session USD cap (default: the "
                         "registry's budget block)")
    ap.add_argument("--wall-cap-s", type=float, default=None,
                    help="per-run session wall cap in seconds (default: "
                         "the registry's budget block)")
    ap.add_argument("--corpus-root", default=None,
                    help=f"the operator-local corpus root (default: "
                         f"${EVAL_ROOT_ENV})")
    ap.add_argument("--warm-store", default=None,
                    help="dir holding the prepared warm "
                         f"{STORE_FILE} (overrides "
                         "warm_up.store_source)")
    ap.add_argument("--warm-context-from", default=None,
                    help="train workspace for the cc-warm-context arm "
                         "(overrides warm_up.warm_context_source)")
    ap.add_argument("--session-cmd", default=None,
                    help="TEST/OVERRIDE ONLY: passed through to the "
                         "child runner's session seam")
    ap.add_argument("--plugin-dir", default=None,
                    help="kunglao plugin dir for the loop arms "
                         "(default: the child runner's own default)")
    ap.add_argument("--max-parallel", type=int, default=1,
                    help="concurrent child runners (default 1 = "
                         "sequential)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"matrix output dir (default: {DEFAULT_OUT_REL}"
                         "/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what WOULD launch; no session starts, "
                         "no run dir is created")
    ap.add_argument("--report", action="store_true",
                    help="readout over completed runs; no launching")
    ap.add_argument("--progress", action="store_true",
                    help="print the current progress JSON; no launching")
    args = ap.parse_args(argv)

    out = Path(args.out)

    if args.report:
        report = build_report(out, read_progress(out))
        print_report(report)
        print(f"REPORT {out / 'report.json'}")
        return RC_OK

    if args.progress:
        doc = read_progress(out)
        if doc is None:
            print(f"NO PROGRESS at {out / 'progress.json'}")
            return RC_REFUSED
        print(json.dumps(doc, indent=2))
        return RC_OK

    try:
        doc = load_config(Path(args.config))
        plans = plan_runs(doc, out,
                          arms_filter=[a for a in args.arms.split(",")
                                       if a],
                          units_filter=[u for u in args.units.split(",")
                                        if u])
    except ConfigError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return RC_REFUSED

    budget = (args.budget_usd if args.budget_usd is not None
              else float((doc.get("budget") or {}).get("budget_usd", 2.0)))
    wall = (args.wall_cap_s if args.wall_cap_s is not None
            else float((doc.get("budget") or {}).get("wall_cap_s", 1800)))
    operator_root = args.corpus_root or os.environ.get(
        EVAL_ROOT_ENV) or None
    if operator_root and not Path(operator_root).is_dir():
        print(f"REFUSED: corpus root is not a dir: {operator_root}",
              file=sys.stderr)
        return RC_REFUSED
    warm_up = doc.get("warm_up") or {}
    warm_source = (Path(args.warm_store) if args.warm_store
                   else (Path(warm_up["store_source"])
                         if warm_up.get("store_source") else None))
    warm_context_from = (
        Path(args.warm_context_from) if args.warm_context_from
        else (Path(warm_up["warm_context_source"])
              if warm_up.get("warm_context_source") else None))

    progress = launch(plans, out, budget_usd=budget, wall_cap_s=wall,
                      session_cmd=args.session_cmd,
                      plugin_dir=Path(args.plugin_dir)
                      if args.plugin_dir else None,
                      warm_source=warm_source,
                      warm_context_from=warm_context_from,
                      operator_root=operator_root,
                      max_parallel=max(1, args.max_parallel),
                      dry_run=args.dry_run)
    runs = progress["runs"]
    refused = sum(1 for r in runs if r["status"] in ("refused",
                                                     "unresolvable"))
    print(f"PROGRESS {out / 'progress.json'} "
          f"({len(runs)} runs: "
          f"{sum(1 for r in runs if r['status'] == 'planned')} planned, "
          f"{sum(1 for r in runs if r['status'] == 'done')} done, "
          f"{sum(1 for r in runs if r['status'] == 'running')} running, "
          f"{sum(1 for r in runs if r['status'] == 'child_error')} "
          f"child_error, {refused} refused)")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
