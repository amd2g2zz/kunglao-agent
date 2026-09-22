#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_loop_runner.py — the loop arm runner (issue #334).

Runs the FULL kunglao framework loop as an autonomous end-to-end
evaluation task: the loop launch is a REAL Claude Code + kunglao-plugin
session doing real analysis — NO loop simulation, no scripted dispatches,
no mocked telemetry. The runner's ONLY jobs:

    1. FRESH WORKSPACE   kunglao-init into a per-run workspace dir with
                         the task's three anchors (#191: goal_verbatim /
                         success_criterion / verification_method — landed
                         verbatim through the --resolve intake answers) and
                         the target as the analysis subject (bins/ + the
                         scaffold's relative layout);
    2. REAL SESSION      headless `claude -p` with the workspace as cwd,
                         the plugin loaded (--plugin-dir), permissions
                         bypassed (autonomous), the USD budget cap wired
                         (--max-budget-usd) and a wall-clock cap the
                         runner enforces by killing the session's whole
                         process group;
    3. WAIT + HARVEST    after session exit, read the ledgers the loop
                         actually WROTE and compute the loop metrics FROM
                         THOSE FILES: converged (convergence_check
                         decision), rounds (.convergence_ledger.jsonl
                         snapshot rows — the priority_ratio.round_index
                         tick axis), dispatch count + factor vectors (#12,
                         runs/mission_ledger.yaml), oracle case green rate
                         (runs/oracle-status.json), PROVEN claims
                         (claim-register.yaml), token spend
                         (runs/cost_events.jsonl + the session's own cost
                         report), the #136 task_terminal_settlement row
                         (runs/logs/kunglao-*.jsonl);
    4. FINAL CHECK       the task's mechanical checker (the #299 face) on
                         the loop's deliverable (a small extractor maps the
                         workspace's answer into candidate form);
    5. RESULTS           kunglao-eval-results/1 rows with arm=loop —
                         comparable with the #236 bare rows.

Budget/cancellation: budget exhaustion (wall cap kill) is a TERMINAL
metric row (loop.status=exhausted), never a crash — whatever the loop
wrote before the kill is still harvested and graded.

Harness neutrality: the session launch goes through ONE thin adapter
(launch_session / build_claude_argv) — the pi face swaps at v0.2 by
replacing the adapter alone. Tests drive the seam with an env/cmd-
overridable session command (a stub that writes a plausible ledger —
clearly labeled test-only); the PRODUCTION path invokes the real `claude`
CLI. PRIVACY: smoke-tier tasks only — synthetic, constructed targets.

Usage:
  eval_loop_runner.py --tasks py-derive-v1 [--tier smoke]
                      [--budget-usd 2.0] [--wall-cap-s 1800]
                      [--session-cmd CMD] [--plugin-dir DIR] [--out DIR]

Exit: 0 run completed (arm FAIL/exhausted rows are measurements, the #236
convention); 2 refusal (unknown task).

stdlib + yaml only (the repo's runtime deps).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_dataset as ds
import eval_targets as tg
import eval_smoke_runner as rnr
import tuition_curve

try:  # repo runtime dep (eval_dataset already requires it)
    import yaml
except ImportError:  # pragma: no cover - env guard, mirrors eval_dataset
    yaml = None

ARM = "loop"
ENV_SESSION_CMD = "KUNGLAO_LOOP_SESSION_CMD"

DEFAULT_BUDGET_USD = 2.0
DEFAULT_WALL_CAP_S = 1800.0
INIT_TIMEOUT_S = 300.0
CONV_TIMEOUT_S = 120.0

# the loop prompt's mandated deliverable (the extractor's primary face)
DELIVERABLE_DIR = ("runs", "deliverables")

# fallback extractor scan order (deterministic; after the primary path)
FALLBACK_SCAN_DIRS = ("runs/deliverables", "deliverables", "scratch",
                      "analyses", "evidence")
# checker-internal artifacts that are never candidates
_EXCLUDE_PREFIXES = ("harness-", "probes-", "license-config-")

DEFAULT_TYPES = {"darwin": "macos", "linux": "linux"}

RC_OK, RC_REFUSED = 0, 2


def _fail(msg: str) -> None:
    print(f"FAILURE code=BAD_TASK detail={msg}", file=sys.stderr)
    print("VERDICT REFUSED", file=sys.stderr)


# ----------------------------------------------------------------- launch
def default_plugin_dir() -> Path:
    """The repo root (holds .claude-plugin/plugin.json)."""
    return SCRIPT_DIR.parent


def build_claude_argv(prompt: str, plugin_dir: Path,
                      budget_usd: float) -> list[str]:
    """The PRODUCTION session face: the real `claude` CLI's documented
    flags (claude 2.1.270): -p print mode; --plugin-dir loads the
    kunglao plugin for this session; --permission-mode bypassPermissions
    runs the loop autonomously (no human consent round mid-eval);
    --output-format json yields the machine-parseable result + cost
    report; --max-budget-usd is the CLI-side spend cap (print mode)."""
    return [
        "claude", "-p", prompt,
        "--plugin-dir", str(plugin_dir),
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--max-budget-usd", str(budget_usd),
    ]


def launch_session(workspace: Path, prompt: str, *, budget_usd: float,
                   wall_cap_s: float, session_cmd: str | None = None,
                   plugin_dir: Path | None = None) -> dict:
    """THE adapter (harness-neutral): start the real analysis session in
    ``workspace`` cwd under the budget caps, wait, return the session
    record. The production face is `claude -p`; an explicit session
    command (argument or KUNGLAO_LOOP_SESSION_CMD) replaces the argv
    wholesale — only the prompt is appended as the positional (the test
    seam; never used in production)."""
    workspace = Path(workspace)
    if session_cmd is None:
        session_cmd = os.environ.get(ENV_SESSION_CMD) or None
    if session_cmd:
        argv = shlex.split(session_cmd) + [prompt]
    else:
        argv = build_claude_argv(prompt, plugin_dir or default_plugin_dir(),
                                 budget_usd)
    started = time.time()
    timed_out = False
    # start_new_session: the child leads its own process group so the
    # wall-cap kill reaps the whole session tree (claude spawns helpers)
    try:
        proc = subprocess.Popen(
            argv, cwd=str(workspace), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        # a session that cannot even start is a TERMINAL record, never a
        # crash: the run_loop_task face turns this into session_error
        return {
            "argv": argv,
            "returncode": None,
            "wall_s": round(time.time() - started, 3),
            "timed_out": False,
            "launch_error": str(exc),
            "stdout_tail": "",
            "stderr_tail": f"session launch failed: {exc}",
            "session_cost": None,
        }
    try:
        out, err = proc.communicate(timeout=wall_cap_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, err = proc.communicate()
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "wall_s": round(time.time() - started, 3),
        "timed_out": timed_out,
        "stdout_tail": (out or "")[-4000:],
        "stderr_tail": (err or "")[-2000:],
        "session_cost": _session_cost(out or ""),
    }


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _session_cost(stdout_text: str) -> dict | None:
    """Parse the claude --output-format json result: the session's own
    cost report (total_cost_usd + token usage). Tolerant: any non-JSON
    output -> None (the ledger-side token face still harvests)."""
    for line in stdout_text.splitlines():
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            doc = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and (
                "total_cost_usd" in doc or "usage" in doc):
            usage = doc.get("usage") or {}
            return {
                "total_cost_usd": doc.get("total_cost_usd"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
    return None


# ------------------------------------------------------------------- init
def _default_type() -> str:
    return DEFAULT_TYPES.get(sys.platform, "linux")


def init_workspace(task_dir: Path, work_root: Path,
                   *, project_type: str | None = None) -> Path:
    """FRESH workspace: kunglao-init with the task's three anchors landed
    verbatim (the --resolve intake answers, one invocation — the exit-8
    pending channel is pre-filled) and the target present as the analysis
    subject (bins/<entry> for init's target alignment + the scaffold's
    relative layout so the anchor's file references resolve)."""
    task_dir = Path(task_dir)
    task = ds.load_task(task_dir)
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    ws = work_root / f"ws-{task_dir.name}-{time.strftime('%Y%m%dT%H%M%SZ')}" \
        f"-{os.getpid() % 100000}"
    ws.mkdir()

    # scaffold files at their task-relative paths (the goal text references
    # them, e.g. target/derive.py) + the init target under bins/
    ws_bins = ws / "bins"
    ws_bins.mkdir()
    entry = task["workspace_scaffold"]["entry"]
    for rel in task["workspace_scaffold"]["files"]:
        src = task_dir / rel
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    (ws_bins / Path(entry).name).write_text(
        (task_dir / entry).read_text(encoding="utf-8"), encoding="utf-8")

    answers = ws / ".k334-intake-answers.json"
    answers.write_text(json.dumps(
        {f: task["anchors"][f] for f in ds.ANCHOR_FIELDS}), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "kunglao-init.py"), str(ws),
         "--type", project_type or _default_type(),
         "--lane", "algorithm",
         "--target", Path(entry).name,
         "--resolve", str(answers),
         "--no-mcp"],
        capture_output=True, text=True, timeout=INIT_TIMEOUT_S)
    if proc.returncode != 0:
        raise RuntimeError(
            f"kunglao-init failed rc={proc.returncode} for {task_dir.name}: "
            f"{(proc.stderr or proc.stdout or '')[-1500:]}")
    return ws


# ----------------------------------------------------------------- prompt
def build_loop_prompt(task_dir: Path, task: dict, deliverable_rel: str) -> str:
    """The loop brief: the anchors verbatim + the candidate contract + the
    mandated deliverable path. Structurally cannot leak ground truth: this
    function never receives it (same leakage posture as the #236 bare
    prompt — thresholds, oracles and the checker's existence stay
    checker-side)."""
    anchors = task["anchors"]
    ws = task["workspace_scaffold"]
    files = "\n".join(f"  - {f}" for f in ws["files"])
    return (
        "/kunglao-agent Run the full kunglao-agent orchestrator loop on "
        "THIS workspace (your current directory) until CONVERGED or until "
        "further rounds cannot improve the result. Work fully "
        "autonomously: no questions, no user input — every decision is "
        "yours to make from the anchors below.\n\n"
        f"GOAL (verbatim): {anchors['goal_verbatim']}\n\n"
        f"SUCCESS CRITERION (verbatim): {anchors['success_criterion']}\n\n"
        f"VERIFICATION METHOD: {anchors['verification_method']}\n\n"
        f"ANALYSIS SUBJECT — the task's material, already in this "
        f"workspace (also under bins/):\n{files}\n\n"
        f"DELIVERABLE CONTRACT: {ws['candidate_contract']}\n\n"
        f"MANDATORY FINAL STEP: before you finish, write the complete "
        f"re-implementation as ONE source file to "
        f"{deliverable_rel} in this workspace (create the directory if "
        f"needed). This file is how the delivered answer is collected.")


# ---------------------------------------------------------------- harvest
def is_converged_decision(decision: str | None) -> bool:
    return (decision or "").strip().upper() == "CONVERGED"


def _iter_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8",
                               errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _convergence_face(ws: Path) -> tuple[bool, str]:
    """The real convergence_check face (subprocess, --json). Fail-closed
    on unreadable output: the decision is not converged unless the checker
    itself says CONVERGED."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "convergence_check.py"),
             "--json", str(ws)],
            capture_output=True, text=True, timeout=CONV_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"UNREADABLE ({type(exc).__name__})"
    doc: dict = {}
    out_lines = (proc.stdout or "").splitlines()
    start = next((i for i, ln in enumerate(out_lines)
                  if ln.strip().startswith("{")), None)
    if start is not None:
        try:
            doc = json.loads("\n".join(out_lines[start:]))
        except json.JSONDecodeError:
            doc = {}
    decision = doc.get("decision") if isinstance(doc, dict) else None
    if decision is None:
        return False, f"UNREADABLE (rc={proc.returncode})"
    return is_converged_decision(str(decision)), str(decision)


def count_snapshot_rows(ws: Path) -> int:
    """RAW snapshot rows in <ws>/.convergence_ledger.jsonl (a snapshot row
    carries no "type" key and does carry "open_count" — the
    priority_ratio.round_index contract; event rows are not ticks). Init
    writes NO ledger row: every snapshot row is a loop tick (or a
    convergence_check invocation); the runner's rounds metric subtracts the
    post-init launch baseline so only the session's own ticks count."""
    n = 0
    for row in _iter_jsonl(Path(ws) / ".convergence_ledger.jsonl"):
        if "type" not in row and "open_count" in row:
            n += 1
    return n


def _factor_face(ws: Path) -> tuple[int, int, float]:
    """#12 factor vectors: (vector count, dispatch sum, last cumulative
    cost_tokens)."""
    vectors: list[dict] = []
    try:
        led = yaml.safe_load(
            (ws / "runs" / "mission_ledger.yaml").read_text("utf-8")) or {}
        vectors = [v for v in (led.get("mission", {}).get("history") or [])
                   if isinstance(v, dict)]
    except (OSError, yaml.YAMLError):
        vectors = []
    count = len(vectors)
    dispatch = sum(int((v.get("events") or {}).get("dispatch") or 0)
                   for v in vectors)
    last_cost = 0.0
    for v in vectors:
        ct = v.get("cost_tokens")
        if isinstance(ct, (int, float)):
            last_cost = float(ct)
    return count, dispatch, last_cost


def _oracle_face(ws: Path) -> tuple[int, int]:
    """(green, total) case statuses from runs/oracle-status.json."""
    green = total = 0
    try:
        status = json.loads(
            (ws / "runs" / "oracle-status.json").read_text("utf-8"))
        for case in (status.get("cases") or {}).values():
            total += 1
            if str(case.get("status") or "").lower() == "pass":
                green += 1
    except (OSError, json.JSONDecodeError):
        pass
    return green, total


def _proven_face(ws: Path) -> int:
    """PROVEN claim count from claim-register.yaml."""
    proven = 0
    try:
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text("utf-8")) or {}
        for c in (reg.get("claims") or []):
            if str((c or {}).get("status") or "").upper() == "PROVEN":
                proven += 1
    except (OSError, yaml.YAMLError):
        pass
    return proven


def _terminal_face(ws: Path) -> bool:
    """The #136 task_terminal_settlement row in the kunglao logs."""
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return False
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        if any(row.get("action") == "task_terminal_settlement"
               for row in _iter_jsonl(p)):
            return True
    return False


def harvest(workspace: Path, *, baseline_rounds: int = 0) -> dict:
    """Loop metrics FROM THE LEDGER FILES the real loop wrote. Every face
    reads one organ; a missing organ is a zero metric (an exhausted run
    legitimately lacks later organs) — never a crash, never an invented
    number. ``baseline_rounds`` is the post-init snapshot count: the
    rounds metric reports the LOOP's ticks (the delta), not init's."""
    ws = Path(workspace)
    # tick count FIRST: the convergence_check face itself appends a
    # snapshot row on every invocation — the harvest probe's own row must
    # never count as a loop tick
    rounds = max(count_snapshot_rows(ws) - baseline_rounds, 0)
    converged, decision = _convergence_face(ws)

    factor_vectors, dispatch_count, factor_cost_tokens = _factor_face(ws)
    green, total = _oracle_face(ws)
    try:
        tokens_cost = float(tuition_curve.cost_state(ws)["spent"])
    except (OSError, KeyError, ValueError, TypeError):
        tokens_cost = 0.0

    return {
        "converged": converged,
        "decision": decision,
        "rounds": rounds,
        "dispatch_count": dispatch_count,
        "factor_vectors": factor_vectors,
        "factor_cost_tokens": factor_cost_tokens,
        "oracle_cases_green": green,
        "oracle_cases_total": total,
        "oracle_green_rate": (green / total) if total else 0.0,
        "proven_claims": _proven_face(ws),
        "tokens_cost": tokens_cost,
        "terminal_row": _terminal_face(ws),
    }


# -------------------------------------------------------------- extractor
def _candidate_suffix(task: dict) -> str:
    lang = tg.FAMILIES[task["family"]]["language"]
    return {"go": ".go", "javascript": ".js", "python": ".py"}[lang]


def extract_candidate(workspace: Path, task: dict) -> Path | None:
    """Map the loop's answer into checker-candidate form. Primary: the
    deliverable path the loop prompt mandates (runs/deliverables/
    candidate<suffix>). Fallback: a deterministic scan of the workspace's
    delivery-facing dirs for a source file of the family's language
    (checker-internal harness/probe artifacts excluded). None = no
    gradeable answer (the row says so, never a crash)."""
    ws = Path(workspace)
    suffix = _candidate_suffix(task)
    primary = ws / Path(*DELIVERABLE_DIR) / f"candidate{suffix}"
    if primary.is_file() and primary.stat().st_size > 0:
        return primary
    for d in FALLBACK_SCAN_DIRS:
        base = ws / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob(f"*{suffix}")):
            if not p.is_file() or p.stat().st_size == 0:
                continue
            if p.name.startswith(_EXCLUDE_PREFIXES):
                continue
            return p
    return None


# ------------------------------------------------------------------- runs
def run_loop_task(task_ref: str, out: Path, *, budget_usd: float
                  = DEFAULT_BUDGET_USD, wall_cap_s: float
                  = DEFAULT_WALL_CAP_S, session_cmd: str | None = None,
                  plugin_dir: Path | None = None) -> dict:
    """One eval task through the FULL pipeline: init -> real session ->
    harvest -> mechanical check -> results row (arm=loop)."""
    out = Path(out)
    tdir = ds.resolve_task_dir(task_ref)
    task = ds.load_task(tdir)
    suffix = _candidate_suffix(task)
    deliverable_rel = f"{Path(*DELIVERABLE_DIR)}/candidate{suffix}"

    ws = init_workspace(tdir, out / "workspaces")
    baseline_rounds = count_snapshot_rows(ws)
    prompt = build_loop_prompt(tdir, task, deliverable_rel)
    rec = launch_session(ws, prompt, budget_usd=budget_usd,
                         wall_cap_s=wall_cap_s, session_cmd=session_cmd,
                         plugin_dir=plugin_dir)
    if rec["timed_out"]:
        status = "exhausted"
    elif rec["returncode"] == 0:
        status = "completed"
    else:
        status = "session_error"

    metrics = harvest(ws, baseline_rounds=baseline_rounds)
    cand = extract_candidate(ws, task)

    if cand is not None:
        res = rnr.run_task(tdir, cand, out)
    else:
        res = {
            "task_id": tdir.name, "family": task["family"],
            "checker_kind": task["checker"]["kind"],
            "metrics": {m: 0 for m in ds.REQUIRED_METRICS},
            "verdict": "SKIP",
            "failures": [{"code": "BAD_CANDIDATE",
                          "detail": "the loop wrote no gradeable "
                                    f"deliverable ({deliverable_rel})"}],
            "evidence": "", "checker_rc": 2,
        }

    row = ds.results_row(
        task_id=res["task_id"], family=res["family"],
        checker_kind=res["checker_kind"], metrics=res["metrics"],
        verdict=res["verdict"], failures=res["failures"],
        evidence_ref=res["evidence"], arm=ARM)
    row["loop"] = {
        "status": status,
        "metrics": metrics,
        "checker_rc": res["checker_rc"],
        "session": {
            "returncode": rec["returncode"],
            "wall_s": rec["wall_s"],
            "timed_out": rec["timed_out"],
            "session_cost": rec["session_cost"],
        },
        "workspace": str(ws),
        "deliverable": str(cand) if cand else None,
        "prompt_sha256": hashlib.sha256(
            prompt.encode("utf-8")).hexdigest(),
    }
    for name, value in res["metrics"].items():
        print(ds.metric_line(f"{tdir.name}.{name}", value))
    print(f"METRIC {tdir.name}.rounds={metrics['rounds']}")
    print(f"METRIC {tdir.name}.loop_dispatch_count="
          f"{metrics['dispatch_count']}")
    print(f"METRIC {tdir.name}.oracle_green_rate="
          f"{metrics['oracle_green_rate']:.4f}")
    print(f"METRIC {tdir.name}.tokens_cost={metrics['tokens_cost']}")
    print(f"VERDICT {tdir.name} {res['verdict']} "
          f"(loop: {status}, decision={metrics['decision']})")
    return row


def run_loop_tier(tasks: list[str], out: Path, *, tier: str = "smoke",
                  budget_usd: float = DEFAULT_BUDGET_USD,
                  wall_cap_s: float = DEFAULT_WALL_CAP_S,
                  session_cmd: str | None = None,
                  plugin_dir: Path | None = None
                  ) -> tuple[int, dict]:
    """The tier face: one kunglao-eval-results/1 doc, arm=loop — directly
    comparable with the #236 bare rows (same row contract)."""
    started = time.time()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    all_dirs = ds.iter_task_dirs(tier=tier)
    known = {d.name for d in all_dirs}
    unknown = [t for t in tasks if t not in known]
    if unknown:
        _fail(f"unknown task(s): {unknown}")
        return RC_REFUSED, {}
    selected = [d for d in all_dirs if not tasks or d.name in tasks]

    rows: list[dict] = []
    for tdir in selected:
        rows.append(run_loop_task(
            tdir.name, out, budget_usd=budget_usd, wall_cap_s=wall_cap_s,
            session_cmd=session_cmd, plugin_dir=plugin_dir))

    summary = {
        "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
        "fail": sum(1 for r in rows if r["verdict"] == "FAIL"),
        "skip": sum(1 for r in rows if r["verdict"] == "SKIP"),
        "refused": sum(1 for r in rows if r["verdict"] == "REFUSED"),
        "exhausted": sum(1 for r in rows
                         if r.get("loop", {}).get("status") == "exhausted"),
        "wall_seconds": round(time.time() - started, 2),
    }
    doc = {
        "schema": ds.RESULTS_SCHEMA,
        "eval_version": ds.EVAL_TIER_VERSION.get(tier, ds.EVAL_VERSION),
        "tier": tier,
        "arm": ARM,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": rows,
        "summary": summary,
    }
    results_path = out / (
        f"eval-results-{time.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{os.getpid() % 100000}.json")
    results_path.write_text(json.dumps(doc, indent=2) + "\n",
                            encoding="utf-8")
    print(f"RESULTS {results_path}")
    print(f"SUMMARY pass={summary['pass']} fail={summary['fail']} "
          f"skip={summary['skip']} exhausted={summary['exhausted']} "
          f"wall_seconds={summary['wall_seconds']}")
    return RC_OK, doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_loop_runner.py",
        description="#334 loop arm: REAL Claude Code + kunglao-plugin "
                    "sessions, ledger harvest, mechanical final check.")
    ap.add_argument("--tasks", default="",
                    help="comma-separated task ids (default: whole smoke "
                         "tier)")
    ap.add_argument("--tier", default="smoke", choices=sorted(ds.TIERS))
    ap.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD,
                    help="session USD cap (--max-budget-usd, print mode)")
    ap.add_argument("--wall-cap-s", type=float, default=DEFAULT_WALL_CAP_S,
                    help="session wall-clock cap (the runner kills the "
                         "session tree past it; exhausted = terminal row)")
    ap.add_argument("--session-cmd", default=None,
                    help="TEST/OVERRIDE ONLY: replacement session command "
                         "(prompt appended as the positional); the "
                         "production face is the real claude CLI")
    ap.add_argument("--plugin-dir", default=None,
                    help="kunglao plugin dir (default: this repo root)")
    ap.add_argument("--out", default=str(
        ds.EVAL_ROOT.parent / "runs" / "eval-loop"),
        help="output dir (default: runs/eval-loop/)")
    args = ap.parse_args(argv)
    tasks = [t for t in args.tasks.split(",") if t]
    rc, _doc = run_loop_tier(
        tasks, Path(args.out), tier=args.tier, budget_usd=args.budget_usd,
        wall_cap_s=args.wall_cap_s, session_cmd=args.session_cmd,
        plugin_dir=Path(args.plugin_dir) if args.plugin_dir else None)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
