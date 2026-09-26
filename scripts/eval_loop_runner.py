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
    6. EXPERIENCE        issue 396 v0.1.6 recording face at worker-return
                         and terminal (see _record_experience): tc journal,
                         situation snapshot, triples.csv — pure recording,
                         zero decision impact.

Budget/cancellation: budget exhaustion is a TERMINAL metric row
(loop.status=exhausted), never a crash, on BOTH kill faces — the runner's
wall-cap SIGKILL (timed_out) and the CLI's own --max-budget-usd stop
(print mode exits rc=1 with a cost report at/over the cap) — whatever the
loop wrote before the kill is still harvested and graded. A sub-budget
rc!=0 exit is a genuine session_error.

Workspace-escape gate (exp3, boundary widened by the P1 audit): the
integrity surface — the harness surface (agents/ hooks/ skills/
scripts/) PLUS the graded surface (eval/v1/tasks/** — ground_truth.json,
per-unit checkers, task specs, chain/reference goldens, targets) — is
hashed BEFORE each session spawn and AFTER its exit; on drift the files
are restored from HEAD (git checkout --), a loud harness_drift event row
lands in <out>/harness-events.jsonl, and the session row is marked
harness_contaminated (diagnostic — the verdict is unaffected, grading
already ran). The graders themselves (scripts/eval_checker.py,
eval_chain_grader.py, eval_dataset.py, eval_targets.py) sit inside
scripts/ and were already covered; the P1 gap was the tasks tree.

Gap-closure mechanizations (exp5, from the distilled cards):
    M1  WALL PARTITION  the runner owns the wall cap, so it COMMUNICATES
        the cap into each session's task prompt as a first-class
        WALL_BUDGET_PARTITION block (solo-attempt hard cap at 50% wall,
        deliverable due before a 300s reserve) — the case-dispatch-budget
        partition contract, not a behavior rule;
    M2  GAP-REDO ROUND  when a session ends with a delivered candidate
        that FAILS the mechanical checker and wall+budget remain, the
        runner spawns ONE gap-redo session in the SAME workspace: the
        prompt carries the checker GAP (GAP-shape only — which faces
        failed and by how much, never the checker's derived answer, per
        the repo's redo discipline); the redo's verdict replaces the
        original (checker-strict); one redo max.

EXP-8 high-ROI injections (same discipline — contract communication in
the prompt, zero new machinery):
    I1  DELIVERABLE SCHEDULE  the wall-partition block grows the
        deliverable-first schedule (draft on disk by 50% wall, improve
        continuously; the CURRENT on-disk state is graded at the cap).
    I2  LAYER_CHECKPOINTS     chain-tier prompts name the grader's exact
        layer_out/ paths (exp4: 13/14 sessions scored 0/N despite real
        peels — the convention was invisible).
    I3  SELF_CHECK            registered families (crypto/kdf/sign) get
        their probe pattern injected (templates/selfcheck/) so a wrong
        deliverable is caught in-session.
    I4  FACTOR SETTLE         one final mission-ledger sample at session
        end — exp4's dispatch-tick face read 0 on all units because the
        last value_m sample predated the late dispatches.
    I5  T1_DIRECT             the T-1 affirmative one-liner (the demoted
        toolfirst advisory never had an affirmative replacement).

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
import re
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

# M1 (exp5): the wall partition the runner COMMUNICATES into each task
# prompt (case-dispatch-budget-partition Rule 1 — orchestrators that
# analyze solo past 60-90% wall dispatch too late to matter; the runner
# owns the cap, so the cap must travel with the task).
SOLO_PARTITION_FRACTION = 0.5     # solo/direct attempt hard cap (of wall)
DELIVERABLE_RESERVE_S = 300.0     # final deliverable due before this much
                                  # residual wall (the checker+harvest tail)

# M2 (exp5): gap-redo round gates. A redo with less than this much wall or
# budget left is dispatch theater (the card's own rule: workers need a
# window that can actually finish) — suppressed, reason recorded.
MIN_REDO_WALL_S = 600.0
MIN_REDO_BUDGET_USD = 1.0

# I5 (exp8): the T-1 affirmative. The toolfirst advisory demotion removed
# the negative gate but never added the affirmative — CC-default 12/12
# proves a direct-execution path exists on every unit; the loop prompt now
# states it (one line, conditional wording; the control arm stays neutral).
T1_DIRECT_LINE = (
    "T1_DIRECT: if a registered tool directly covers this task, execute "
    "it first before any decomposition (tool-catalog: <name> if "
    "applicable).")

# I3 (exp8) + issue 380 P3-5: family -> self-check probe shape, DERIVED from
# the per-family template convention — no hard special-case map keyed on
# family strings (the special-case-instead-of-algorithm disease). A
# family is registered by shipping templates/selfcheck/probe-<shape>.md
# whose header names the shape and the family it is injected for:
#   <!-- probe shape: crypto (pair-match) — injected for family X -->
# Adding family issue 4 is adding a template file — zero code change — and the
# map can never drift from the templates it points at.
SELFCHECK_TEMPLATE_DIR = (Path(__file__).resolve().parent.parent
                          / "templates" / "selfcheck")

_PROBE_HEADER_RE = re.compile(
    r"probe shape:\s*(?P<shape>\S+).*?injected for family\s+(?P<family>\S+)")


def derive_family_probe_shapes(template_dir: Path) -> dict[str, str]:
    """The template-convention reader (issue 380 P3-5): parse every
    probe-*.md header in ``template_dir`` into {family: shape}.
    Fail-open: an absent dir, an unreadable file or a headerless
    template contributes nothing (never raises)."""
    shapes: dict[str, str] = {}
    tdir = Path(template_dir)
    if not tdir.is_dir():
        return shapes
    for p in sorted(tdir.glob("probe-*.md")):
        try:
            head = p.read_text("utf-8", errors="replace")[:512]
        except OSError:
            continue
        m = _PROBE_HEADER_RE.search(head)
        if m:
            shapes[m.group("family")] = m.group("shape")
    return shapes


# I3 (exp8): exactly three registered families today — crypto/kdf/sign.
# Evidence: mod-crypto-l1 delivered a candidate graded 0/20 — a wrong
# deliverable an in-session probe would have caught.
FAMILY_PROBE_SHAPES = derive_family_probe_shapes(SELFCHECK_TEMPLATE_DIR)

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


def _warn_fail_open(op: str, exc: Exception) -> None:
    """issue 380 P3-9: fail-open telemetry degradations keep their liveness
    posture (never raise, never change the return shape) but leave ONE
    trace — the shared _boot.warn idiom: a stderr WARN naming the
    operation + reason, rate-limited to once per op until the reason
    changes (the issue 275 batch-3 pattern). Incident-path prints
    (kill/restore) stay raw and loud ON PURPOSE: every incident's remedy
    failure must be visible, not rate-limited away."""
    from _boot import warn
    warn(op, f"{type(exc).__name__}: {exc}")


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


def build_cc_default_argv(prompt: str, budget_usd: float) -> list[str]:
    """The CC-DEFAULT arm face: the same CLI invocation with the kunglao
    plugin flags REMOVED — default Claude Code harness, default tools,
    no plugin hooks. The only harness variable left vs the bare arm is
    tools + working directory access + multiple turns until the wall."""
    return [
        "claude", "-p", prompt,
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--max-budget-usd", str(budget_usd),
    ]


def launch_session(workspace: Path, prompt: str, *, budget_usd: float,
                   wall_cap_s: float, session_cmd: str | None = None,
                   plugin_dir: Path | None = None,
                   plugin: bool = True) -> dict:
    """THE adapter (harness-neutral): start the real analysis session in
    ``workspace`` cwd under the budget caps, wait, return the session
    record. The production face is `claude -p`; an explicit session
    command (argument or KUNGLAO_LOOP_SESSION_CMD) replaces the argv
    wholesale — only the prompt is appended as the positional (the test
    seam; never used in production). ``plugin=False`` selects the
    CC-DEFAULT face (build_cc_default_argv): same caps, no kunglao
    plugin — the harness-capability-variable arm."""
    workspace = Path(workspace)
    if session_cmd is None:
        session_cmd = os.environ.get(ENV_SESSION_CMD) or None
    if session_cmd:
        argv = shlex.split(session_cmd) + [prompt]
    elif plugin:
        argv = build_claude_argv(prompt, plugin_dir or default_plugin_dir(),
                                 budget_usd)
    else:
        argv = build_cc_default_argv(prompt, budget_usd)
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
        except OSError as exc:
            print(f"[eval_loop_runner] kill fallback failed: {exc}",
                  file=sys.stderr)


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


# ------------------------------------------------------ harness escape gate
# The 2026-09-24 sweep caught a spawned session ESCAPING its workspace: an
# Edit targeting the worktree-level agents/kunglao-redteam.md (a checker
# permission-widening). Workspace isolation is advisory — a
# bypassPermissions session can write anywhere. The gate hashes the
# integrity surface before spawn + after exit, restores drift from HEAD
# and marks the session row (diagnostic; the verdict is unaffected —
# grading already ran).
#
# P1 /simplify audit: the original boundary hashed only agents/
# hooks/ skills/ scripts/ — but the highest-value bypassPermissions
# target is the GRADING surface: flipping eval/v1/tasks/**/ground_truth.json
# or a per-unit checker turns FAIL into PASS with the gate watching the
# wrong asset. The tasks tree is hashed in FULL (not answer-files-only):
# task.yaml thresholds, chain manifests/reference goldens and the target
# samples are grading-validity faces too, and a name allowlist silently
# misses future task files — the same wrong-asset class this gate closes.
# Cost of the wider boundary (shipped walker, 10-run warm mean,
# 2026-09-26): the graded tree adds ~103 ms/call (326 files / ~2.1 MB),
# gate total ~200 ms vs ~97 ms before — two calls per session against
# minutes-long sessions, so stat-first-then-hash was considered and
# rejected as unneeded complexity. Restore scope
# matches hash scope automatically: drift keys are the union relpaths and
# restore_harness() takes repo-root-relative paths either way.
ENV_HARNESS_ROOT = "KUNGLAO_HARNESS_ROOT"
HARNESS_DIRS = ("agents", "hooks", "skills", "scripts")
GRADED_DIRS = ("eval/v1/tasks",)
HARNESS_DRIFT_ACTION = "harness_drift"  # registered: event_taxonomy.EMIT_ACTIONS


def _harness_root() -> Path:
    env = os.environ.get(ENV_HARNESS_ROOT)
    return Path(env) if env else SCRIPT_DIR.parent


def _surface_hashes(root: Path, dirs: tuple[str, ...]) -> dict[str, str]:
    """Scoped sha256 over repo-root-relative trees: <dir>/<rel> ->
    digest. __pycache__ excluded (bytecode is not surface)."""
    out: dict[str, str] = {}
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            out[f"{d}/{p.relative_to(base).as_posix()}"] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def harness_surface_hashes(root: Path | None = None) -> dict[str, str]:
    """Scoped sha256 over the harness surface (agents/ hooks/ skills/
    scripts/): relpath -> digest. __pycache__ excluded (bytecode is not
    surface). Runs before each session spawn and after its exit; any
    delta is a workspace escape by that session."""
    return _surface_hashes(
        Path(root) if root is not None else _harness_root(), HARNESS_DIRS)


def graded_surface_hashes(root: Path | None = None) -> dict[str, str]:
    """P1 audit: scoped sha256 over the GRADING surface (the full
    eval/v1/tasks tree — answer keys, per-unit checkers, task specs,
    chain/reference goldens, targets): relpath -> digest. The tasks tree
    is read-only harness input; any delta is a grading flip attempt."""
    return _surface_hashes(
        Path(root) if root is not None else _harness_root(), GRADED_DIRS)


def integrity_surface_hashes(root: Path | None = None) -> dict[str, str]:
    """The gate's hash input: harness surface ∪ graded surface. Drift
    over either is a workspace escape; restore_harness() consumes the
    same repo-root-relative keys, so restore scope matches hash scope."""
    r = Path(root) if root is not None else _harness_root()
    return {**harness_surface_hashes(r), **graded_surface_hashes(r)}


def harness_drift(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Drifted relpaths between the two surface hashes: changed, added
    AND deleted all count (sorted for determinism)."""
    return sorted(k for k in set(before) | set(after)
                  if before.get(k) != after.get(k))


def restore_harness(drifted: list[str],
                    root: Path | None = None) -> list[str]:
    """Restore the drifted subset to HEAD. Tracked files (modified or
    deleted) come back via `git checkout --`; session-created additions
    (untracked — no HEAD bytes to restore) are removed. Returns the
    paths actually restored; unrestored names stay in the event row."""
    root = Path(root) if root is not None else _harness_root()
    if not drifted:
        return []
    tracked, added = [], []
    for rel in drifted:
        probe = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", rel],
            capture_output=True, text=True)
        (tracked if probe.stdout.strip() else added).append(rel)
    restored: list[str] = []
    if tracked:
        co = subprocess.run(
            ["git", "-C", str(root), "checkout", "--", *tracked],
            capture_output=True, text=True)
        if co.returncode == 0:
            restored.extend(tracked)
        else:
            print(f"[eval_loop_runner] harness restore failed: "
                  f"{(co.stderr or '').strip()[-500:]}", file=sys.stderr)
    for rel in added:
        try:
            (root / rel).unlink()
            restored.append(rel)
        except OSError as exc:
            print(f"[eval_loop_runner] harness addition removal failed "
                  f"({rel}): {exc}", file=sys.stderr)
    return restored


def _harness_drift_event(out: Path, task: str, drifted: list[str],
                         restored: list[str]) -> None:
    """The loud event row: one JSON line per drift incident in
    <out>/harness-events.jsonl (the sweep's grep face)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": "harness-event/1",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": task,
        "action": HARNESS_DRIFT_ACTION,
        "drifted": drifted,
        "restored": restored,
        "unrestored": [f for f in drifted if f not in restored],
        "remedy": "git checkout -- <files> (restore from HEAD); "
                  "session row marked harness_contaminated",
    }
    with (out / "harness-events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def run_session_guarded(workspace: Path, prompt: str, out: Path,
                        task_name: str, *, budget_usd: float,
                        wall_cap_s: float, session_cmd: str | None = None,
                        plugin_dir: Path | None = None,
                        plugin: bool = True,
                        note: str = "") -> tuple[dict, list[str], list[str]]:
    """issue 380 P3-2: THE one guarded spawn — both faces (main + gap-redo)
    route through here so the harness-drift handling can no longer
    diverge (the finding: main printed stdout+stderr, redo printed only
    stderr, and redo contamination never fed the summary counter). Hash
    the harness surface -> launch -> hash again -> on drift restore from
    HEAD + emit the loud event row + the loud log pair. Returns
    (session_record, drifted, restored). ``note`` tags the log lines
    (e.g. " (gap-redo session)")."""
    pre = integrity_surface_hashes()
    rec = launch_session(workspace, prompt, budget_usd=budget_usd,
                         wall_cap_s=wall_cap_s, session_cmd=session_cmd,
                         plugin_dir=plugin_dir, plugin=plugin)
    drifted = harness_drift(pre, integrity_surface_hashes())
    restored: list[str] = []
    if drifted:
        restored = restore_harness(drifted)
        _harness_drift_event(out, task_name, drifted, restored)
        print(f"HARNESS_DRIFT task={task_name}{note} files={len(drifted)} "
              f"restored={len(restored)} action={HARNESS_DRIFT_ACTION} "
              f"(session escaped its workspace; surface restored from "
              f"HEAD; row marked harness_contaminated)", file=sys.stderr)
        print(f"HARNESS_DRIFT task={task_name}{note} files={len(drifted)} "
              f"restored={len(restored)}")
    return rec, drifted, restored


# ---------------------------------------------------------- wall partition
def wall_partition_block(wall_cap_s: float) -> str:
    """M1 (exp5) + I1 (exp8): the WALL_BUDGET_PARTITION contract block.
    The runner owns the wall cap and kills the session tree at it — a
    session that was never told the cap cannot partition its own budget.
    This is contract COMMUNICATION (the harness's enforcement parameters),
    not a behavior rule: what the session does inside the partition is
    still its decision. Rendered from the session's ACTUAL cap.

    I1 (exp8) adds the deliverable schedule: post2 measured 5/5
    deliverers pass vs 7/7 non-deliverers dead, and exp5's arm-kdf
    delivered its candidate AT budget death (0/16 graded on a rush job) —
    so the block now mandates an early on-disk draft that is continuously
    improved; at the cap the CURRENT on-disk state is what gets graded."""
    total = int(round(wall_cap_s))
    solo_cap = int(round(wall_cap_s * SOLO_PARTITION_FRACTION))
    due = max(int(round(wall_cap_s - DELIVERABLE_RESERVE_S)), 0)
    return (
        "WALL_BUDGET_PARTITION (harness contract — the runner enforces "
        "these caps by killing this session's whole process tree; "
        "nothing written after the kill is collected):\n"
        f"- TOTAL WALL CAP: {total}s.\n"
        f"- SOLO/DIRECT ATTEMPT HARD CAP: {solo_cap}s. If the deliverable "
        f"is not complete by then, a worker dispatch MUST occur by "
        f"{solo_cap}s — attach the failure GAP (what was tried, where it "
        "stalls) so the worker does not repeat the dead path.\n"
        f"- DELIVERABLE_SCHEDULE: draft the candidate on disk by "
        f"{solo_cap}s (the 50%-wall mark); continuously improve it after "
        "that; at the cap the CURRENT on-disk state is what gets "
        "graded.\n"
        f"- FINAL DELIVERABLE DUE BY {due}s: write the deliverable file, "
        "verify it exists and is non-empty, and only then spend any "
        "residual window on verification polish.")


# ------------------------------------------------ chain layer checkpoints
def chain_layer_paths(task_dir: Path) -> list[str]:
    """I2 (exp8): the unit's EXACT layer_out/ artifact paths — sourced
    from the same face the dense grader reads (eval_chain_grader walks
    ground_truth's chain layers and checks each op's ``path``), so the
    injected convention matches the grader byte-exactly. Leakage posture:
    ONLY the path strings are lifted — digests, probe payloads and
    expected outputs are never read, so nothing gradeable can travel into
    the prompt. Empty for non-chain units."""
    try:
        gt = json.loads(
            (Path(task_dir) / "ground_truth.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    chain = gt.get("chain")
    if not isinstance(chain, dict) or not isinstance(
            chain.get("layers"), list):
        return []
    out: list[str] = []
    for layer in chain["layers"]:
        if not isinstance(layer, dict):
            continue
        for op in layer.get("ops") or []:
            if not isinstance(op, dict):
                continue
            p = op.get("path")
            if isinstance(p, str) and p and p not in out:
                out.append(p)
    return out


def layer_checkpoints_block(layer_paths: list[str]) -> str:
    """I2 (exp8): the LAYER_CHECKPOINTS block — exp4 measured 13/14 chain
    sessions scoring 0/N despite real peels because the layer_out/
    convention was invisible to the session. The grader defines what it
    reads; the injection names those exact paths."""
    lines = [
        "LAYER_CHECKPOINTS (dense-grading contract — the grader reads "
        "these; a layer counts only if its file exists and verifies):",
        "Write each peeled layer's output to layer_out/ in your "
        "workspace at these EXACT paths (create the directory as needed; "
        "a layer's file missing means the layer scores zero):",
    ]
    lines.extend(f"- {p}" for p in layer_paths)
    return "\n".join(lines)


# ------------------------------------------------------ family self-check
def self_check_block(family: str | None) -> str:
    """I3 (exp8): the SELF_CHECK block for a registered family — the
    family's probe pattern (templates/selfcheck/probe-<shape>.md) injected
    verbatim, so the session can verify its own candidate before
    finalizing. Unregistered families get no block (fail-open: a missing
    template degrades to the one-line directive, never a crash)."""
    shape = FAMILY_PROBE_SHAPES.get(str(family or ""))
    if shape is None:
        return ""
    head = ("SELF_CHECK: before finalizing, run the family probe pattern "
            "below against your candidate — a candidate that fails its "
            "own probe is not a deliverable.")
    try:
        snippet = (SELFCHECK_TEMPLATE_DIR / f"probe-{shape}.md").read_text(
            "utf-8").strip()
    except OSError:
        snippet = ""
    return head + (f"\n\n{snippet}" if snippet else "")


def prompt_injection_blocks(task_dir: Path,
                            task: dict) -> tuple[list[str], str]:
    """I2/I3 (exp8): the per-unit prompt extras as (layer_paths,
    probe_block) — the chain LAYER_CHECKPOINTS paths (chain tier only:
    the ground-truth read is scoped to units whose tier declares the
    dense face) and the family SELF_CHECK block (registered families
    only)."""
    layer_paths = (chain_layer_paths(task_dir)
                   if task.get("tier") == "chain" else [])
    return layer_paths, self_check_block(task.get("family"))


# ------------------------------------------------------- factor settle (I4)
def settle_factor_sample(workspace: Path) -> bool:
    """I4 (exp8): append ONE final factor-vector history sample at session
    end — THROUGH THE SHARED CADENCE GATE (issue 380 P3-7: this used to call
    mission_ledger.value_m() directly, an un-gated second sampler
    distorting the d_slope windows; it now calls mission_ledger.settle(),
    the same gate the heartbeat cockpit's _mission_history_due uses).

    Diagnosis (exp4, all 7 units): dispatch signals landed in
    runs/signals.jsonl (3-10 rows) but the mission-ledger history's last
    point predated them — the init-time sample plus one early tick left
    the cursor behind while the real dispatches happened at 60-90% wall.
    The gate's pending-signals rule keeps the I4 live-effect: a settle
    with NEW signal rows since the newest point's cursor is ALWAYS due,
    so late dispatches are counted; not-due only ever means "nothing
    pending AND a fresh sample" — no accounting is ever dropped.
    Fail-open telemetry: no ledger (cc-default arm) or a degraded sample
    returns False and never breaks the harvest."""
    ws = Path(workspace)
    if not (ws / "runs" / "mission_ledger.yaml").is_file():
        return False
    try:
        import mission_ledger as ml
        return ml.settle(ws) is not None
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        _warn_fail_open("factor_settle", exc)
        return False


# ------------------------------------------------------ experience record
def _record_experience(ws: Path, trigger: str) -> None:
    """issue 396 v0.1.6 RECORDING face (zero decision impact): at the
    worker-return / terminal lifecycle points, journal the session's
    tool-call rows (tc_journal), append one mainline situation snapshot
    (state_signature), and at the terminal regenerate the derived
    (s, a, r) triple view (experience_triples). Runs AFTER measurement
    and settlement faces — pure telemetry, fail-open: any recording
    failure is a WARN, never a broken harvest or a changed verdict."""
    try:
        import experience_triples
        import state_signature
        import tc_journal
        tc_journal.harvest_from_log(ws)
        state_signature.append_snapshot(ws, trigger=trigger)
        if trigger == "terminal":
            experience_triples.extract(ws)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        _warn_fail_open("experience_recording", exc)


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
    # them, e.g. target/derive.py) + the init target under bins/.
    # BYTE-exact copy: native-ladder scaffolds are ELF binaries — a text
    # decode here crashed the whole task (the bare-arm campaign's gap class)
    ws_bins = ws / "bins"
    ws_bins.mkdir()
    entry = task["workspace_scaffold"]["entry"]
    for rel in task["workspace_scaffold"]["files"]:
        src = task_dir / rel
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    (ws_bins / Path(entry).name).write_bytes((task_dir / entry).read_bytes())

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


def init_cc_default_workspace(task_dir: Path,
                              work_root: Path,
                              *, wall_cap_s: float | None = None
                              ) -> tuple[Path, str]:
    """The CC-DEFAULT arm's neutral cwd: NO kunglao-init, no plugin
    scaffold — ONLY the unit's material at its task-relative paths
    (byte-exact; native scaffolds are ELF) plus TASK.md carrying the
    anchors + deliverable contract verbatim. ``wall_cap_s`` (M1) injects
    the runner-owned WALL_BUDGET_PARTITION block into the prompt +
    TASK.md. Returns (workspace, prompt)."""
    task_dir = Path(task_dir)
    task = ds.load_task(task_dir)
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    ws = work_root / f"ws-ccd-{task_dir.name}-" \
        f"{time.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid() % 100000}"
    ws.mkdir()
    for rel in task["workspace_scaffold"]["files"]:
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((task_dir / rel).read_bytes())
    anchors = task["anchors"]
    ws_scaffold = task["workspace_scaffold"]
    files = "\n".join(f"  - {f}" for f in ws_scaffold["files"])
    deliverable_rel = f"{Path(*DELIVERABLE_DIR)}/candidate" \
        f"{_candidate_suffix(task)}"
    prompt = (
        "Solve the reverse-engineering task in THIS working directory. "
        "Work fully autonomously: no questions, no user input.\n\n"
        + (wall_partition_block(wall_cap_s) + "\n\n"
           if wall_cap_s is not None else "")
        + f"GOAL (verbatim): {anchors['goal_verbatim']}\n\n"
        f"SUCCESS CRITERION (verbatim): {anchors['success_criterion']}\n\n"
        f"VERIFICATION METHOD: {anchors['verification_method']}\n\n"
        f"TASK MATERIAL — already in this working directory:\n{files}\n\n"
        f"DELIVERABLE CONTRACT: {ws_scaffold['candidate_contract']}\n\n"
        f"MANDATORY FINAL STEP: before you finish, write the complete "
        f"re-implementation as ONE source file to "
        f"{deliverable_rel} in this workspace (create the directory if "
        f"needed). This file is how the delivered answer is collected.")
    (ws / "TASK.md").write_text(prompt, encoding="utf-8")
    return ws, prompt


# ----------------------------------------------------------------- prompt
def _render_task_prompt(opening: str, task: dict, deliverable_rel: str,
                        extras: list[str], gap_block: str = "") -> str:
    """issue 380 P3-1: the SHARED task-brief renderer — the anchors verbatim +
    the analysis-subject listing + the candidate contract + the mandated
    deliverable tail, preceded by the caller's ``extras`` blocks (each
    followed by a blank line) and, when present, the redo's ``gap_block``.
    Both builders route through here so their ~15-line tails cannot drift
    silently (the finding: build_loop_prompt / build_redo_prompt carried
    byte-identical tails that were maintained twice); the extraction is
    pinned byte-identical to the pre-refactor prompts
    (TestPromptRenderHelperByteIdentity)."""
    anchors = task["anchors"]
    ws = task["workspace_scaffold"]
    files = "\n".join(f"  - {f}" for f in ws["files"])
    injected = "".join(f"{block}\n\n" for block in extras)
    return (
        opening
        + injected
        + (f"{gap_block}\n\n" if gap_block else "")
        + f"GOAL (verbatim): {anchors['goal_verbatim']}\n\n"
        f"SUCCESS CRITERION (verbatim): {anchors['success_criterion']}\n\n"
        f"VERIFICATION METHOD: {anchors['verification_method']}\n\n"
        f"ANALYSIS SUBJECT — the task's material, already in this "
        f"workspace (also under bins/):\n{files}\n\n"
        f"DELIVERABLE CONTRACT: {ws['candidate_contract']}\n\n"
        f"MANDATORY FINAL STEP: before you finish, write the complete "
        f"re-implementation as ONE source file to "
        f"{deliverable_rel} in this workspace (create the directory if "
        f"needed). This file is how the delivered answer is collected.")


def build_loop_prompt(task_dir: Path, task: dict, deliverable_rel: str,
                      *, wall_cap_s: float | None = None,
                      layer_paths: list[str] | None = None,
                      include_t1_direct: bool = True,
                      probe_block: str = "") -> str:
    """The loop brief: the anchors verbatim + the candidate contract + the
    mandated deliverable path, plus the injected contract blocks.

    Leakage posture (issue 380 P3-6 — documented choice: PROCEDURAL, not
    structural). The old docstring claimed "structurally cannot leak
    ground truth: this function never receives it". That stopped being
    true when I2 (exp8) added ``layer_paths`` — path strings lifted from
    the grader's ground_truth.json by chain_layer_paths. The structural
    fix (a whitelisted GraderSurface view type) was rejected: the pinned
    call sites pass plain path lists, so a wrapper type around the same
    strings would be ceremony, not invariant. The invariant is therefore
    PROCEDURAL and pinned by test_chain_prompt_leaks_no_ground_truth:
    chain_layer_paths reads ONLY each op's ``path`` field — digests,
    probe payloads and expected outputs are never read, so nothing
    gradeable can travel into the prompt; thresholds, oracles and the
    checker's derived answers stay checker-side (the same posture as the
    issue 236 bare prompt).

    ``wall_cap_s`` (M1, exp5) injects the runner-owned
    WALL_BUDGET_PARTITION block as a first-class section directly after
    the opening directive — the session cannot partition a cap it was
    never told. ``layer_paths`` (I2, exp8) injects the chain
    LAYER_CHECKPOINTS block (exact grader paths). ``probe_block`` (I3,
    exp8) injects the family SELF_CHECK block. ``include_t1_direct``
    (I5, exp8) adds the T-1 affirmative one-liner."""
    extras: list[str] = []
    if wall_cap_s is not None:
        extras.append(wall_partition_block(wall_cap_s))
    if layer_paths:
        extras.append(layer_checkpoints_block(layer_paths))
    if probe_block:
        extras.append(probe_block)
    if include_t1_direct:
        extras.append(T1_DIRECT_LINE)
    opening = (
        "/kunglao-agent Run the full kunglao-agent orchestrator loop on "
        "THIS workspace (your current directory) until CONVERGED or until "
        "further rounds cannot improve the result. Work fully "
        "autonomously: no questions, no user input — every decision is "
        "yours to make from the anchors below.\n\n")
    return _render_task_prompt(opening, task, deliverable_rel, extras)


# --------------------------------------------------------------- gap redo
def extract_checker_gap(res: dict) -> dict:
    """M2 (exp5): GAP-shape extraction from the checker result — WHICH
    faces failed and by how much, never the checker's derived answer
    (the repo's redo discipline: the redo input is built by the runner's
    gap extraction, DIFF conclusion lines are never pasted). Sources: the
    structured FAILURE rows (codes + count-shaped details) and the
    evidence doc's face aggregates (static: hit/required + missing
    constant NAMES; replay: matched/count). A missing evidence organ
    degrades the gap to the failure rows alone — never a crash."""
    gap: dict = {
        "verdict": res.get("verdict"),
        "failures": [dict(f) for f in (res.get("failures") or [])],
        "static_missing": [],
        "replay": None,
    }
    ev_path = res.get("evidence")
    if not ev_path:
        return gap
    try:
        doc = json.loads(Path(ev_path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return gap
    faces = doc.get("faces") or {}
    static = faces.get("static") or {}
    gap["static_missing"] = [str(m) for m in (static.get("missing") or [])]
    replay = faces.get("replay") or {}
    if replay:
        gap["replay"] = {"matched": replay.get("matched"),
                         "count": replay.get("count")}
    return gap


def render_gap_block(gap: dict) -> str:
    """Render the extracted gap as the redo prompt's first-class CHECKER
    GAP block (GAP-shape only)."""
    lines = [
        "CHECKER GAP (from the mechanical final check of the previously "
        "delivered candidate — gap shape only: which faces failed and by "
        "how much; no expected answers are carried or derivable from "
        f"this block):",
        f"- CHECK RESULT: {gap.get('verdict')}",
    ]
    for f in gap.get("failures") or []:
        lines.append(f"- FAILURE code={f.get('code')} "
                     f"detail=\"{f.get('detail')}\"")
    if gap.get("static_missing"):
        names = ", ".join(gap["static_missing"])
        lines.append(f"- STATIC FACE: candidate is missing these required "
                     f"constant names (names only): {names}")
    if gap.get("replay"):
        r = gap["replay"]
        lines.append(f"- REPLAY FACE: {r.get('matched')}/{r.get('count')} "
                     f"probe pairs reproduced")
    return "\n".join(lines)


def gap_redo_decision(verdict: str | None, session_record: dict, *,
                      wall_cap_s: float, budget_usd: float) -> dict:
    """M2 (exp5): whether ONE gap-redo round may run — pure decision over
    (checker verdict, session spend). Allowed ONLY when a candidate was
    delivered and FAILED the checker (not SKIP/REFUSED: there is no gap
    to hand back) AND wall+budget remain above the dispatch-theater floor
    (MIN_REDO_WALL_S / MIN_REDO_BUDGET_USD). Spend is the session's own
    cost report; a missing report (test seam) reads as zero spent."""
    spend = ((session_record.get("session_cost") or {})
             .get("total_cost_usd"))
    remaining_budget = budget_usd - (float(spend) if spend is not None
                                     else 0.0)
    remaining_wall = wall_cap_s - float(session_record.get("wall_s") or 0.0)
    if (verdict or "").strip().upper() != "FAIL":
        return {"allowed": False, "reason": "not_checker_fail",
                "remaining_wall_s": remaining_wall,
                "remaining_budget_usd": remaining_budget}
    if remaining_wall < MIN_REDO_WALL_S:
        return {"allowed": False, "reason": "wall_exhausted",
                "remaining_wall_s": remaining_wall,
                "remaining_budget_usd": remaining_budget}
    if remaining_budget < MIN_REDO_BUDGET_USD:
        return {"allowed": False, "reason": "budget_exhausted",
                "remaining_wall_s": remaining_wall,
                "remaining_budget_usd": remaining_budget}
    return {"allowed": True, "reason": "checker_fail_within_budget",
            "remaining_wall_s": remaining_wall,
            "remaining_budget_usd": remaining_budget}


def build_redo_prompt(task_dir: Path, task: dict, deliverable_rel: str,
                      gap_block: str, *, wall_cap_s: float,
                      budget_usd: float,
                      layer_paths: list[str] | None = None,
                      probe_block: str = "") -> str:
    """The gap-redo session's brief: same task (anchors + contract +
    deliverable path, the workspace ITSELF carries the prior session's
    state) + the CHECKER GAP block + the wall partition recomputed for
    the redo's own remaining cap. Leakage posture identical to the loop
    prompt: anchors and contract only — the gap adds shape, not answers.
    I2/I3/I5 (exp8): the chain LAYER_CHECKPOINTS block, the family
    SELF_CHECK block and the T1_DIRECT line ride along — the redo is the
    same task under the same prompt contract. (issue 380 P3-1: the shared
    tail renders through _render_task_prompt.)"""
    extras: list[str] = [wall_partition_block(wall_cap_s)]
    if layer_paths:
        extras.append(layer_checkpoints_block(layer_paths))
    if probe_block:
        extras.append(probe_block)
    extras.append(T1_DIRECT_LINE)
    opening = (
        "/kunglao-agent GAP-REDO round in THIS workspace: the previous "
        "session's delivered candidate FAILED the mechanical final "
        "check. Do not restart the analysis from scratch — this "
        "workspace already holds that session's state; target the GAP "
        "below, re-derive the failing faces from the raw target "
        "material, and update the SAME deliverable path. Work fully "
        "autonomously: no questions, no user input.\n\n")
    return _render_task_prompt(opening, task, deliverable_rel, extras,
                               gap_block=gap_block)


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
    except (OSError, json.JSONDecodeError) as exc:
        _warn_fail_open("oracle_face", exc)
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
    except (OSError, yaml.YAMLError) as exc:
        _warn_fail_open("claim_register", exc)
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
    """Candidate artifact suffix for the task's family — the single-source
    contract module (eval_contract) both drivers consume; the checker's
    _validate_candidate resolves the same row."""
    import eval_contract as contract
    return contract.candidate_suffix(task["family"])


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
def _post_cap_status(rec: dict, budget_usd: float) -> str:
    """rc!=0 post-session classification. The CLI-side ``--max-budget-usd``
    stop (print mode exits rc=1 with a cost report at/over the cap) is
    BUDGET EXHAUSTION — the same TERMINAL exhausted row as the runner's
    wall-cap kill, never a crash (the 2026-09-24 sweep mislabeled 9/12
    units this way).

    HEURISTIC, EXPLICITLY DOCUMENTED (issue 380 P3-8): the adapter sees no
    structured budget-stop discriminator to consume — the CLI's json
    result face carries the cost report but no field distinguishing
    "stopped BY the cap" from "crashed WHILE at/over the cap" — so
    ``cost >= budget`` on rc!=0 IS the structured signal consumption,
    with a known mislabel: a genuine crash whose partial spend happens
    to read at/over the cap is classified exhausted. pass@k accounting
    caveat: that inflates the exhausted bucket and deflates session_error
    (both remain non-PASS measurement rows; the verdict is unaffected —
    only the loop.status flavor moves). Any other rc!=0 is a genuine
    session_error."""
    cost = (rec.get("session_cost") or {}).get("total_cost_usd")
    if cost is not None and float(cost) >= budget_usd:
        return "exhausted"
    return "session_error"


def _session_status(rec: dict, budget_usd: float) -> str:
    """Post-session terminal classification (both faces): the runner's
    wall-cap kill (timed_out) and the CLI's own budget stop are EXHAUSTED
    terminal rows; rc=0 completed; anything else a genuine session_error."""
    if rec["timed_out"]:
        return "exhausted"
    if rec["returncode"] == 0:
        return "completed"
    return _post_cap_status(rec, budget_usd)


def run_loop_task(task_ref: str, out: Path, *, budget_usd: float
                  = DEFAULT_BUDGET_USD, wall_cap_s: float
                  = DEFAULT_WALL_CAP_S, session_cmd: str | None = None,
                  plugin_dir: Path | None = None,
                  arm: str = ARM) -> dict:
    """One eval task through the FULL pipeline: init -> real session ->
    harvest -> mechanical check -> results row. ``arm`` selects the
    harness face: "loop" (kunglao-init + plugin session) or "cc-default"
    (neutral cwd + plugin-less session) — same caps, extractor and
    checker either way."""
    out = Path(out)
    tdir = ds.resolve_task_dir(task_ref)
    task = ds.load_task(tdir)
    suffix = _candidate_suffix(task)
    deliverable_rel = f"{Path(*DELIVERABLE_DIR)}/candidate{suffix}"

    layer_paths, probe_block = prompt_injection_blocks(tdir, task)

    try:
        if arm == "cc-default":
            ws, prompt = init_cc_default_workspace(tdir, out / "workspaces",
                                                   wall_cap_s=wall_cap_s)
        else:
            ws = init_workspace(tdir, out / "workspaces")
            prompt = build_loop_prompt(tdir, task, deliverable_rel,
                                       wall_cap_s=wall_cap_s,
                                       layer_paths=layer_paths,
                                       probe_block=probe_block)
    except RuntimeError as exc:
        # structured SKIP row, never a tier-wide crash: one unit's init
        # failure must not take the other units' measurement with it
        row = ds.results_row(
            task_id=tdir.name, family=task["family"],
            checker_kind=task["checker"]["kind"],
            metrics={m: 0 for m in ds.REQUIRED_METRICS},
            verdict="SKIP",
            failures=[{"code": "BAD_TASK",
                       "detail": str(exc)[-1500:]}],
            evidence_ref="", arm=arm)
        row["loop"] = {"status": "init_failed", "metrics": {},
                       "checker_rc": 2, "session": {
                           "returncode": None, "wall_s": 0.0,
                           "timed_out": False,
                           "session_cost": None,
                           "harness_contaminated": False,
                           "harness_drift_files": []},
                       "workspace": None, "deliverable": None,
                       "prompt_sha256": None}
        print(f"VERDICT {tdir.name} SKIP ({arm}: init_failed)")
        return row
    baseline_rounds = count_snapshot_rows(ws)
    rec, drifted, _restored = run_session_guarded(
        ws, prompt, out, tdir.name, budget_usd=budget_usd,
        wall_cap_s=wall_cap_s, session_cmd=session_cmd,
        plugin_dir=plugin_dir, plugin=(arm != "cc-default"))
    contaminated = bool(drifted)
    status = _session_status(rec, budget_usd)

    settle_factor_sample(ws)  # I4 (exp8): late dispatches must be counted
    _record_experience(ws, "worker_return")  # 396 recording (fail-open)
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

    # ---- M2 (exp5): ONE runner-driven gap-redo round. Fires only on a
    # delivered-and-FAILED candidate with wall+budget remaining above the
    # dispatch-theater floor; the redo session reuses the SAME workspace
    # and receives the CHECKER GAP (gap-shape only) built by the runner's
    # own extraction — never the checker stream pasted wholesale.
    # issue 380 P3-4: the reason is stored ONCE — inside the decision (the
    # row-level duplicate gap_redo["reason"] is gone)
    gap_redo: dict = {"ran": False, "decision": None,
                      "session": None, "verdict_replaced": False}
    redo_decision = gap_redo_decision(res["verdict"], rec,
                                      wall_cap_s=wall_cap_s,
                                      budget_usd=budget_usd)
    gap_redo["decision"] = redo_decision
    if redo_decision["allowed"]:
        redo_wall = redo_decision["remaining_wall_s"]
        redo_budget = redo_decision["remaining_budget_usd"]
        redo_prompt = build_redo_prompt(
            tdir, task, deliverable_rel,
            render_gap_block(extract_checker_gap(res)),
            wall_cap_s=redo_wall, budget_usd=redo_budget,
            layer_paths=layer_paths, probe_block=probe_block)
        print(f"GAP_REDO task={tdir.name} starting "
              f"(wall={redo_wall:.0f}s budget={redo_budget:.2f}usd)",
              file=sys.stderr)
        redo_rec, redo_drifted, _redo_restored = run_session_guarded(
            ws, redo_prompt, out, tdir.name, budget_usd=redo_budget,
            wall_cap_s=redo_wall, session_cmd=session_cmd,
            plugin_dir=plugin_dir, plugin=(arm != "cc-default"),
            note=" (gap-redo session)")
        status = _session_status(redo_rec, redo_budget)
        gap_redo["ran"] = True
        gap_redo["session"] = {
            "returncode": redo_rec["returncode"],
            "wall_s": redo_rec["wall_s"],
            "timed_out": redo_rec["timed_out"],
            "session_cost": redo_rec["session_cost"],
            "harness_contaminated": bool(redo_drifted),
            "harness_drift_files": redo_drifted,
            "prompt_sha256": hashlib.sha256(
                redo_prompt.encode("utf-8")).hexdigest(),
        }
        # the redo's ledger rows are the task's ticks too
        settle_factor_sample(ws)  # I4 (exp8): settle once more post-redo
        metrics = harvest(ws, baseline_rounds=baseline_rounds)
        redo_cand = extract_candidate(ws, task)
        if redo_cand is not None:
            # checker-strict: the redo's verdict REPLACES the original
            res = rnr.run_task(tdir, redo_cand, out)
            cand = redo_cand
            gap_redo["verdict_replaced"] = True
        # a redo that lands no gradeable candidate leaves the original
        # FAIL standing: SKIP must stay harness-only per the accounting
        # ruling, and the attempt still ended on a failing deliverable

    _record_experience(ws, "terminal")  # 396 recording (fail-open)

    row = ds.results_row(
        task_id=res["task_id"], family=res["family"],
        checker_kind=res["checker_kind"], metrics=res["metrics"],
        verdict=res["verdict"], failures=res["failures"],
        evidence_ref=res["evidence"], arm=arm)
    row["gap_redo"] = gap_redo["ran"]
    row["loop"] = {
        "status": status,
        "metrics": metrics,
        "checker_rc": res["checker_rc"],
        "session": {
            "returncode": rec["returncode"],
            "wall_s": rec["wall_s"],
            "timed_out": rec["timed_out"],
            "session_cost": rec["session_cost"],
            "harness_contaminated": contaminated,
            "harness_drift_files": drifted,
        },
        "workspace": str(ws),
        "deliverable": str(cand) if cand else None,
        "prompt_sha256": hashlib.sha256(
            prompt.encode("utf-8")).hexdigest(),
        "gap_redo": gap_redo,
    }
    for name, value in res["metrics"].items():
        print(ds.metric_line(f"{tdir.name}.{name}", value))
    print(f"METRIC {tdir.name}.rounds={metrics['rounds']}")
    print(f"METRIC {tdir.name}.loop_dispatch_count="
          f"{metrics['dispatch_count']}")
    print(f"METRIC {tdir.name}.oracle_green_rate="
          f"{metrics['oracle_green_rate']:.4f}")
    print(f"METRIC {tdir.name}.tokens_cost={metrics['tokens_cost']}")
    print(f"METRIC {tdir.name}.gap_redo_ran="
          f"{int(gap_redo['ran'])}")
    print(f"VERDICT {tdir.name} {res['verdict']} "
          f"(loop: {status}, decision={metrics['decision']}"
          f"{', gap_redo' if gap_redo['ran'] else ''})")
    return row


def run_loop_tier(tasks: list[str], out: Path, *, tier: str = "smoke",
                  budget_usd: float = DEFAULT_BUDGET_USD,
                  wall_cap_s: float = DEFAULT_WALL_CAP_S,
                  session_cmd: str | None = None,
                  plugin_dir: Path | None = None,
                  arm: str = ARM
                  ) -> tuple[int, dict]:
    """The tier face: one kunglao-eval-results/1 doc (arm=loop or
    arm=cc-default) — directly comparable with the #236 bare rows (same
    row contract)."""
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
            session_cmd=session_cmd, plugin_dir=plugin_dir, arm=arm))

    summary = {
        "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
        "fail": sum(1 for r in rows if r["verdict"] == "FAIL"),
        "skip": sum(1 for r in rows if r["verdict"] == "SKIP"),
        "refused": sum(1 for r in rows if r["verdict"] == "REFUSED"),
        "exhausted": sum(1 for r in rows
                         if r.get("loop", {}).get("status") == "exhausted"),
        # issue 380 P3-2: BOTH guarded faces count — redo contamination is no
        # longer silently dropped from the tier summary
        "harness_contaminated": sum(
            1 for r in rows
            if r.get("loop", {}).get("session", {})
            .get("harness_contaminated")
            or ((r.get("loop", {}).get("gap_redo") or {})
                .get("session") or {}).get("harness_contaminated")),
        "gap_redo": sum(1 for r in rows if r.get("gap_redo")),
        "wall_seconds": round(time.time() - started, 2),
    }
    doc = {
        "schema": ds.RESULTS_SCHEMA,
        "eval_version": ds.EVAL_TIER_VERSION.get(tier, ds.EVAL_VERSION),
        "tier": tier,
        "arm": arm,
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
          f"gap_redo={summary['gap_redo']} "
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
    ap.add_argument("--arm", default=ARM, choices=("loop", "cc-default"),
                    help="harness face: loop = kunglao-init + plugin "
                         "session (default); cc-default = plain Claude "
                         "Code default harness, no plugin, neutral cwd")
    ap.add_argument("--out", default=str(
        ds.EVAL_ROOT.parent / "runs" / "eval-loop"),
        help="output dir (default: runs/eval-loop/)")
    args = ap.parse_args(argv)
    tasks = [t for t in args.tasks.split(",") if t]
    rc, _doc = run_loop_tier(
        tasks, Path(args.out), tier=args.tier, budget_usd=args.budget_usd,
        wall_cap_s=args.wall_cap_s, session_cmd=args.session_cmd,
        plugin_dir=Path(args.plugin_dir) if args.plugin_dir else None,
        arm=args.arm)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
