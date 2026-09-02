#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_log — structured JSONL event log (#287 observability).

One JSON object per line, appended to runs/logs/kunglao-<YYYY-MM-DD>.jsonl
under the workspace. Worker, orchestrator, and hook events share ONE schema:

  ts          ISO8601 UTC timestamp (auto, Z suffix)
  actor       who did it (#879 vocabulary: orchestrator / worker:<name> /
              verifier:<name> / hook:<name> / subagent:<type>; legacy names
              adopted in LEGACY_ACTORS)
  action      what happened (dispatch / tool_call / artifact_written / verify / ...)
              — #459: emit-side words come from the controlled vocabulary
              event_taxonomy.EMIT_ACTIONS (CI-anchored, unregistered = red)
  claim       claim id the event concerns (or null)
  tool        tool name for tool events (or null)
  artifact    artifact id / path written or read (or null)
  duration_ms integer milliseconds the action took (or null)
  exit        integer exit / verdict code (or null)
  detail      free-text detail (or null)
  matched_rule gate rule id / glob a WARN/REJECT face matched (#601, or null)
  trace_id    mission chain id `tr-<mission>-<seq>` (#879, or null — the
              nulls ARE the un-attributed rate)

Design contract:
  - stdlib only (json / os / sys / datetime / pathlib).
  - deterministic output: sort_keys + compact separators + ensure_ascii=False.
  - NEVER raises on write failure — emit degrades to a stderr warning and
    returns; logging must never break analysis.

#459 read side: `kunglao_log.py --tail <ws> [N]` prints the most recent N
events (default 20, merged across all day files, JSON lines) — the minimal
answer to "诊断不可解释": one command reconstructs what just happened.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RC_USAGE = 64  # bad invocation (missing workspace / N < 1) — fail fast
DEFAULT_TAIL = 20

# ------------------------- #879 trace identity ------------------------------
# trace_id: the mission-scoped chain id (`tr-<mission>-<seq>`). Identity is
# anchored on three layers (issue #879): mission (trace_id STABLE for the
# whole mission) / claim (C-NN immutable + state machine) / span (append-only
# ledger). The seq disambiguates mission restarts on the same workspace name.
TRACE_ID_RE = re.compile(r"^tr-[a-z0-9][a-z0-9._-]*-\d+$")
TRACE_STATE = Path("runs") / ".trace-state.json"
_MISSION_MAX = 48

# actor vocabulary (#879): the strict forms new emitters must use. `hook:<name>`
# is already the established shape (hook:dispatch_gate / hook:worker_budget).
ACTOR_RE = re.compile(
    r"^(?:orchestrator"
    r"|worker:[A-Za-z0-9._-]+"
    r"|verifier:[A-Za-z0-9._-]+"
    r"|subagent:[A-Za-z0-9._:-]+"
    r"|hook:[A-Za-z0-9._-]+)$")

# Adoption discipline mirrors #459 EMIT_ACTIONS ("words already emitted by
# real producers were incorporated verbatim"): pre-existing actor literals are
# adopted here instead of mass-rewriting ~50 emit sites. The CI anchor
# (scan_actor_literals, anchored by tests/test_trace_identity_879.py) makes
# every NEW literal vocabulary-or-red; legacy names stop growing.
LEGACY_ACTORS = frozenset({
    "anomaly_detector", "ask_for_direction", "ask_for_direction_gate",
    "backtrack_loop",  # #882 retrospective-loop host (retro_report/retro_policy faces)
    "bash_fact_guard", "blind_gate", "carrier_consistency", "cockpit_summary",
    "complete_teardown", "completion_gate", "convergence_check",
    "decision_pending", "digest_build", "dispatch_context", "dual_gate",
    "env_check", "env_check_gate", "env_repair_l1", "env_state_probe",
    "event_taxonomy", "external_kicker", "failure_analysis",
    "failure_analysis_gate", "heartbeat_tick", "heartbeat_touch",
    "hypothesis_seeder", "infeasible_proposal", "infeasible_signal",
    "hook", "hook_activation", "hypothesis", "init", "kunglao-decide",
    "kunglao_record", "kunglao_resume", "kunglao_status", "kunglao_upgrade",
    "kubectl_test", "lessons_telemetry", "lint", "log_setup", "loop_state",
    "migrate_facts", "mission_ledger", "mission_stall", "notes_writer",
    "nursery", "operator", "orchestrator_tool_guard", "outcome_capture",
    "plan_drift", "plan_drift_detector", "priority", "priority_ratio",
    "queue", "recall_inject", "refutation_propagate", "rho_checkpoint",
    "rollup", "retract_claim", "rho_verifier", "scan_worker_budget",
    "statusline_snapshot",  # #883 per-tick statusline health-snapshot writer
    "telemetry", "think_seat", "toolchain_install", "tuition_curve",
    "update_index", "upgrade", "user", "user_signal", "verdict_scorer",
    "verify_status_watch", "verifier", "violation_capture",
    "wire_up_settings", "worker", "worker_budget",
    "zero_output_fingerprint",
})

_REPO_SHA: str | None = None
_REPO_SHA_RESOLVED = False


def _repo_sha() -> str | None:
    """Cached git SHA of the running checkout (subprocess, #818 batch-1).

    None on any failure (not a repo / git missing / timeout) — logging must
    never block analysis."""
    global _REPO_SHA, _REPO_SHA_RESOLVED
    if _REPO_SHA_RESOLVED:
        return _REPO_SHA
    _REPO_SHA_RESOLVED = True
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
        sha = out.stdout.strip() if out.returncode == 0 else ""
        _REPO_SHA = sha or None
    except Exception:
        _REPO_SHA = None
    return _REPO_SHA


def log_path(ws: Path) -> Path:
    """runs/logs/kunglao-<date>.jsonl — one file per UTC day."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(ws) / "runs" / "logs" / f"kunglao-{day}.jsonl"


from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)


def emit(ws, actor: str, action: str, *, claim: str | None = None,
         tool: str | None = None, artifact: str | None = None,
         duration_ms: int | None = None, exit: int | None = None,
         detail: str | None = None,
         arm: str | None = None, epoch: int | None = None,
         hypothesis_ref: str | None = None,
         matched_rule: str | None = None,
         trace_id: str | None = None,
         version: str | None = None) -> None:
    """Append one structured event line. Never raises — write failure degrades
    to a stderr warning so logging can never break analysis.

    #818 batch-1: arm/epoch/hypothesis_ref per #823 attribution contract;
    version auto-fills with the checkout git SHA when omitted (None on
    failure). Absent optional fields are explicit null keys — stable schema,
    old consumers use .get().

    #601: matched_rule — the gate rule id / namespace glob a WARN/REJECT face
    matched (e.g. must_stop_chmod_permissive, jadx, mcp__ghidra__*). Additive
    in the #818 batch-1 style: absent -> explicit null key, old consumers
    keep working via .get().

    #879: trace_id joins the row into its mission chain
    (`tr-<mission>-<seq>`, mission-stable per #879 identity layer); null on
    legacy rows — the gap IS the un-attributed rate signal."""
    event = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "claim": str(claim) if claim is not None else None,
        "tool": str(tool) if tool is not None else None,
        "artifact": str(artifact) if artifact is not None else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "exit": int(exit) if exit is not None else None,
        "detail": str(detail) if detail is not None else None,
        "arm": str(arm) if arm is not None else None,
        "epoch": int(epoch) if epoch is not None else None,
        "hypothesis_ref": str(hypothesis_ref) if hypothesis_ref is not None else None,
        "matched_rule": str(matched_rule) if matched_rule is not None else None,
        "trace_id": str(trace_id) if trace_id is not None else None,
        "version": str(version) if version else _repo_sha(),
    }
    line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    p = log_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"[kunglao_log] warning: cannot write {p}: {exc}", file=sys.stderr)


def _all_rows(ws: Path) -> list[dict]:
    """Every parseable row across ALL day files, chronological order.

    Shared by tail / unattributed_rate / actor_violations — one read path,
    one tolerance rule (unparseable lines are skipped)."""
    logs = Path(ws) / "runs" / "logs"
    rows: list[dict] = []
    if not logs.is_dir():
        return rows
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def tail(ws, n: int = DEFAULT_TAIL) -> list[dict]:
    """The most recent n events across ALL day files, chronological order.

    Read-only: creates/modifies nothing. Day files sort by name (= date), so
    file order is stream order; within a file, append order is stream order.
    Unparseable lines are skipped (same tolerance event_taxonomy applies).
    n <= 0 returns [] (the CLI rejects it earlier; the function degrades)."""
    return _all_rows(ws)[-n:] if n > 0 else []


# ------------------- #879 trace identity helpers ---------------------------

def validate_trace_id(value) -> bool:
    """True iff value is a well-formed `tr-<mission>-<seq>` trace id."""
    return bool(value) and isinstance(value, str) and \
        bool(TRACE_ID_RE.match(value))


def _sanitize_mission(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-")
    return (lowered or "mission")[:_MISSION_MAX]


def mission_id(ws: Path) -> str:
    """Mission identity for trace ids: `task_spec.yaml` `mission:` when
    declared, else the workspace dir name (sanitized). Best-effort, never
    raises."""
    try:
        import yaml  # stdlib-adjacent; kunglao_log stays import-light
        spec = yaml.safe_load(
            (Path(ws) / "task_spec.yaml").read_text(encoding="utf-8",
                                                    errors="replace"))
        m = (spec or {}).get("mission") if isinstance(spec, dict) else None
        if isinstance(m, str) and m.strip():
            return _sanitize_mission(m)
    except Exception:  # noqa: BLE001 — identity is best-effort, never fatal
        pass
    return _sanitize_mission(Path(ws).name)


def new_trace_id(mission: str, seq: int) -> str:
    """`tr-<mission>-<seq>` — the #879 pinned format (seq zero-padded 4)."""
    return f"tr-{_sanitize_mission(mission)}-{int(seq):04d}"


def allocate_trace_id(ws, mission: str | None = None) -> tuple[str, bool]:
    """Mission-stable trace allocation (the #879 identity guarantee).

    The SAME mission reuses its trace_id ("mission(trace_id 不变)"); a NEW
    mission (or a corrupted/absent state file) bumps the seq. State lives in
    runs/.trace-state.json — best-effort, fail-open: allocation must never
    break dispatch (on state failure the seq restarts at 1; the id stays
    format-valid). Returns (trace_id, created) — created=True only when a
    NEW id was minted (the durable trace_allocated row fires on that face
    only)."""
    ws = Path(ws)
    if mission is None:
        mission = mission_id(ws)
    seq = 0
    reuse = None
    try:
        state = json.loads(
            (ws / TRACE_STATE).read_text(encoding="utf-8"))
        seq = int(state.get("seq") or 0)
        if str(state.get("mission") or "") == mission:
            prior = state.get("trace_id")
            if validate_trace_id(prior):
                reuse = prior
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        seq = 0
    if reuse:
        return reuse, False
    seq += 1
    tid = new_trace_id(mission, seq)
    try:
        (ws / TRACE_STATE).parent.mkdir(parents=True, exist_ok=True)
        (ws / TRACE_STATE).write_text(
            json.dumps({"mission": mission, "seq": seq, "trace_id": tid},
                       ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
    except OSError:
        pass  # fail-open: the id is still returned, state just lags
    return tid, True


def validate_actor(actor) -> tuple[bool, str]:
    """Strict #879 actor vocabulary: `orchestrator` |
    `worker:<name>` | `verifier:<name>` | `hook:<name>` | `subagent:<type>`.

    Returns (ok, reason). Emission is NEVER gated on this (logging must not
    break analysis) — the mechanical faces are the repo-wide literal anchor
    (scan_actor_literals) and the ledger query (--check-actors)."""
    if actor is None:
        return False, "actor is None"
    a = str(actor)
    if not a:
        return False, "actor is empty"
    if ACTOR_RE.match(a):
        return True, ""
    head = a.split(":", 1)[0]
    if a in LEGACY_ACTORS:
        return True, ""  # adopted (see LEGACY_ACTORS note)
    if ":" in a:
        return False, f"bad {head!r} form or unknown prefix (vocabulary: " \
                      f"orchestrator/worker:/verifier:/hook:/subagent:)"
    return False, f"unknown actor {a!r} (vocabulary: orchestrator/worker:" \
                  f"/verifier:/hook:/subagent:; legacy names via " \
                  f"LEGACY_ACTORS)"


def scan_actor_literals(root: Path) -> dict[str, set[str]]:
    """Repo-wide #879 actor CI anchor: every actor literal in scripts/*.py +
    hooks/*.py must be vocabulary-valid OR adopted (LEGACY_ACTORS). Mirrors
    the #459 EMIT_ACTIONS anchor shape (unknown literal = red)."""
    known_forms = {
        "orchestrator", "worker:kunglao-worker", "verifier:kunglao-redteam",
        "hook:dispatch_gate", "hook:worker_budget", "subagent:general-purpose",
    }
    violations: dict[str, set[str]] = {}
    for sub in ("scripts", "hooks"):
        sdir = Path(root) / sub
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.py")):
            text = p.read_text(encoding="utf-8", errors="replace")
            found: set[str] = set()
            for m in re.finditer(
                    r'(?:\bactor\s*=\s*|\.emit\(\s*[^,()]+,\s*|(?<![\w.])emit\(\s*[^,()]+,\s*)["\']([^"\']+)["\']',
                    text):
                found.add(m.group(1))
            bad = {a for a in found
                   if not (ACTOR_RE.match(a) or a in LEGACY_ACTORS)}
            bad -= known_forms
            if bad:
                violations[f"{sub}/{p.name}"] = bad
    return violations


def unattributed_rate(ws) -> dict:
    """#879 acceptance: how much of the ledger is NOT joinable to a mission
    chain — rows with a null trace_id as a fraction of all rows. The cockpit
    "未归因率" field's data source (#882 downstream)."""
    rows = _all_rows(Path(ws))
    total = len(rows)
    unattr = sum(1 for r in rows if not r.get("trace_id"))
    return {"rows": total,
            "attributed": total - unattr,
            "unattributed": unattr,
            "rate": round(unattr / total, 4) if total else 0.0}


def actor_violations(ws) -> list[dict]:
    """Ledger rows whose actor is neither vocabulary-valid nor adopted —
    the query face behind `--check-actors` (garbage values are visible)."""
    out: list[dict] = []
    for r in _all_rows(Path(ws)):
        actor = r.get("actor")
        if actor is None:
            continue
        ok, _ = validate_actor(actor)
        if not ok:
            out.append({"ts": r.get("ts"), "actor": actor,
                        "action": r.get("action")})
    return out


def main(argv: list[str] | None = None) -> int:
    """Read-only diagnostic CLI. `--tail <ws> [N]` → JSON lines on stdout;
    `--check-actors <ws>` → ledger actor violations (rc 1 on any)."""
    ap = argparse.ArgumentParser(
        prog="kunglao_log.py",
        description="unified event log (sink read side)")
    ap.add_argument("--tail", metavar="WORKSPACE", default=None,
                    help="print the most recent N events of this workspace "
                         f"(default {DEFAULT_TAIL}), JSON lines, read-only")
    ap.add_argument("--check-actors", metavar="WORKSPACE", default=None,
                    help="scan the ledger for actor values outside the #879 "
                         "vocabulary (and not adopted); rc 1 on violations")
    ap.add_argument("n", nargs="?", type=int, default=DEFAULT_TAIL,
                    help=f"how many events (default {DEFAULT_TAIL})")
    args = ap.parse_args(argv)
    if args.tail is None and args.check_actors is None:
        ap.print_help(sys.stderr)
        return RC_USAGE
    if args.check_actors is not None:
        ws = Path(args.check_actors)
        if not ws.is_dir():
            print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
            return RC_USAGE
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        viols = actor_violations(ws)
        for v in viols:
            print(f"ACTOR-VIOLATION {v['ts']} actor={v['actor']!r} "
                  f"action={v['action']!r}")
        print(f"checked; {len(viols)} violation(s)")
        return 1 if viols else 0
    ws = Path(args.tail)
    if not ws.is_dir():
        print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
        return RC_USAGE
    if args.n < 1:
        print(f"FAIL: N must be >= 1 (got {args.n})", file=sys.stderr)
        return RC_USAGE
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    for row in tail(ws, args.n):
        # canonical form = the emit serialization (sort_keys, compact,
        # ensure_ascii=False) so tail output round-trips with the file bytes
        print(json.dumps(row, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
