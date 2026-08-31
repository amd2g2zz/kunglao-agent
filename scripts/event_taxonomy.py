# -*- coding: utf-8 -*-
"""event_taxonomy.py — 25-class event taxonomy for kunglao event sources (#309, merged #287).

Absorbed idea: amruth-sn/kong events.py:19-62 (a fixed event classification
taxonomy), re-implemented for kunglao's EXISTING sources — no new state
format, no TUI (explicitly rejected: the Claude Code base ships its own
interface). Output feeds the Claude-native interface:

    statusline JSON (statusline_json) — compact counts + alerts
    per-round digest (round_digest_text) — short mechanical text

Sources scanned (all pre-existing; row contracts mirror the PRODUCERS, not a
new vocabulary — every mapping value below is emitted by real code):
    <ws>/ledger.jsonl                 kunglao_record event stream
    <ws>/runs/logs/kunglao-*.jsonl    kunglao_log event stream (same contract)
    <ws>/.convergence_ledger.jsonl    convergence snapshot / outcome rows
    <ws>/runs/worker-status-*.md      worker log; last `status:` line wins
                                      (lib_kunglao convention); vocab =
                                      in-progress / done / blocked
                                      (agents/kunglao-worker.md; convergence_check)
    <ws>/claim-register.yaml          claim status states (state-derived view)
    <ws>/blockers/*.md                active = file WITHOUT "INVALIDATED" marker
                                      (convergence_check._active_blockers);
                                      resolved = INVALIDATED marker or file in
                                      blockers/.resolved/ (stale_blocker_prune)
    <ws>/runs/verify-redteam-*.md     red-team verdict activity
    failure_analysis_gate             gate_blocked = scan_workspace entries with
                                      state == "BLOCKED" (same source priority.py
                                      consumes for its failure-blocked set)

Taxonomy (25 classes):
    ledger stream      : fact_written, fact_verified, claim_promoted,
                         claim_refuted, failure_recorded, intent_opened,
                         intent_closed
    convergence ledger : snapshot, outcome_passed, outcome_partial,
                         outcome_failed, operator_action
    workers            : worker_started (first status line is in-progress —
                         the worker contract's opening line), worker_step
                         (last line in-progress, fresh), worker_completed
                         (last done), worker_failed (last blocked),
                         worker_stuck (last in-progress, heartbeat stale
                         > STUCK_MINUTES — liveness_policy, #597)
    claim states       : claim_partial, claim_deferred, claim_superseded,
                         claim_dead
    blockers/gates     : blocker_opened (active blocker file),
                         blocker_resolved (INVALIDATED / .resolved/),
                         gate_blocked (failure-analysis gate BLOCKED entries)
    red-team           : redteam_verdict
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

def _worker_protocol():
    """hooks/lib_kunglao.py — THE worker-liveness protocol owner (#444), by
    path under the unique name lib_kunglao_hooks (bare `import lib_kunglao`
    is ambiguous under pytest — scripts/lib_kunglao.py shares the name)."""
    import importlib.util
    name = "lib_kunglao_hooks"
    lib = sys.modules.get(name)
    if lib is None:
        path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return lib


# real worker heartbeat convention: the stuck threshold is owned by
# scripts/liveness_policy.py (#597 — THE liveness-minutes single source;
# restating a hard number here would rot silently when the value changes).
from liveness_policy import STUCK_MINUTES  # noqa: E402
STUCK_SECONDS = STUCK_MINUTES * 60

# ---------------------------------------------------------------------------
# taxonomy (25 classes)
# ---------------------------------------------------------------------------

FACT_WRITTEN = "fact_written"
FACT_VERIFIED = "fact_verified"
CLAIM_PROMOTED = "claim_promoted"
CLAIM_REFUTED = "claim_refuted"
FAILURE_RECORDED = "failure_recorded"
INTENT_OPENED = "intent_opened"
INTENT_CLOSED = "intent_closed"
SNAPSHOT = "snapshot"
OUTCOME_PASSED = "outcome_passed"
OUTCOME_PARTIAL = "outcome_partial"
OUTCOME_FAILED = "outcome_failed"
WORKER_STARTED = "worker_started"
WORKER_STEP = "worker_step"
WORKER_COMPLETED = "worker_completed"
WORKER_FAILED = "worker_failed"
WORKER_STUCK = "worker_stuck"
CLAIM_PARTIAL = "claim_partial"
CLAIM_DEFERRED = "claim_deferred"
CLAIM_SUPERSEDED = "claim_superseded"
CLAIM_DEAD = "claim_dead"
BLOCKER_OPENED = "blocker_opened"
BLOCKER_RESOLVED = "blocker_resolved"
GATE_BLOCKED = "gate_blocked"
REDTEAM_VERDICT = "redteam_verdict"
OPERATOR_ACTION = "operator_action"

ALL_EVENT_TYPES = [
    FACT_WRITTEN, FACT_VERIFIED, CLAIM_PROMOTED, CLAIM_REFUTED, FAILURE_RECORDED,
    INTENT_OPENED, INTENT_CLOSED,
    SNAPSHOT, OUTCOME_PASSED, OUTCOME_PARTIAL, OUTCOME_FAILED, OPERATOR_ACTION,
    WORKER_STARTED, WORKER_STEP, WORKER_COMPLETED, WORKER_FAILED, WORKER_STUCK,
    CLAIM_PARTIAL, CLAIM_DEFERRED, CLAIM_SUPERSEDED, CLAIM_DEAD,
    BLOCKER_OPENED, BLOCKER_RESOLVED, GATE_BLOCKED, REDTEAM_VERDICT,
]

# ---------------------------------------------------------------------------
# #459 controlled emit-action vocabulary (the WRITE side word table)
# ---------------------------------------------------------------------------
# ALL_EVENT_TYPES above classifies workspace STATE (25 classes, pinned by
# test_catalog_has_exactly_25_types — do not extend casually). EMIT_ACTIONS
# is the sibling contract for the write side: every kunglao_log.emit(...,
# action=...) call site must draw its word from this list. Anchored by
# tests/test_event_stream_adoption.py — a literal outside the list turns the
# suite red (issue #459 acceptance: "action 字段 100% 来自受控词表").
#
# Registration discipline mirrors the 25-class table: one word per EMIT FACE
# (not per module), lowercase snake_case; detail carries the free text, the
# exit field carries the rc. Words already emitted by real producers were
# incorporated verbatim (grep 2026-08-20):
#   claim_migrate  kunglao_record.py        register migration mirror
#   verify         kunglao_verify.py        verification verdict mirror
#   converge       convergence_check.py     per-round DECISION
#   failure_blocked failure_analysis_gate  BLOCKED, stale-coverage flavor
#   dispatch       worker_budget.py         #461 dispatch linkage event
#   priority_deviation dispatch_gate.py    #496 top-1 deviation, excused
#   capability_switch   dispatch_gate.py    #496 card switch, disproof shown
# #459 adopted faces:
#   ask_back / must_stop / must_ask / ladder_required /
#   death_verdict_rejected / plan_stall    ask_for_direction_gate TYPE A-E
#   top1_reject / capability_reject        dispatch_gate #496 REJECT faces
#   stale_plan_on_new_evidence             plan_drift_detector class-7 WARN
#   analysis_recorded / analysis_blocked    failure_analysis_gate #495 face
#   write_blocked        write_guard.py / worker_budget  #532 carrier write refusal
#   lesson_citation / lesson_burn / lesson_match / lesson_deprecated
#                                 lessons_telemetry #526 CBM + tombstone face
#   lesson_stage_transition failure_analysis_gate nursery draft→active (#525)
#   install_attempt / install_declined / install_failed
#                                toolchain_install #700 per-item install events
#   git_snapshot_skipped  kunglao_upgrade.py / kunglao-init.py  #739 git snapshot WARN faces
EMIT_ACTIONS = [
    "agents_refresh",     # #755 A2 upgrade L2 subagents re-copy face
    "analysis_blocked",
    "analysis_recorded",
    "apkid_candidates",   # #669 hypothesis_seeder apkid→competitor_group extension
    "ask_back",
    "bet_filed",          # #711 falsifiable-bet filing face (think seat)
    "bet_settled",        # #711 bet settlement (confirmed/refuted) face
    "capability_reject",
    "capability_switch",
    "carrier_drift",      # #829 cross-carrier consistency gate: register/_INDEX/notes/facts drift face
    "channel_default",    # #727 init channel degradation/guidance WARN
    "claim_migrate",
    "claim_revive",       # #634 PARK → OPEN revival (mission_stall.revive)
    "claudemd_merge",     # #755 G3 collect-and-merge rebuild face
    "converge",
    "death_verdict_rejected",
    "decide_fail_open",   # #569 kunglao-decide._conservative_blocked exception face
    "decision_snapshot",  # #818 batch-1: decide() per-verdict input snapshot
    "dispatch",
    "env_incident",       # #718 violation_capture traceback/env-crash face
    "env_ledger_refresh",  # #755 A5 env-manifest ledger backfill/refresh face
    "failure_blocked",
    "git_anchor_skipped",  # #753 pre-migration rollback anchor untakeable (git missing/failed) — kunglao_upgrade
    "git_snapshot_skipped",  # #739 WARN faces — kunglao_upgrade (snapshot untakeable: git missing/failed) + kunglao-init (workspace snapshot skip)
    "hypothesis_seed",    # #662 PQ scaffold seeding
    "hypothesis_superseded",  # #759 note-supersedes-hypothesis wiring (K3)
    "infeasible_candidate",  # #823 A4 doomed-trajectory early-stop signal
    "infeasible_filed",     # #815 gated INFEASIBLE proposal filed (DEFERRED)
    "infeasible_woken",     # #815 wake face: infeasible-DEFERRED revived
    "install_attempt",    # #700 toolchain_install per-item install events
    "install_declined",   # #700 toolchain_install per-item install events
    "install_failed",     # #700 toolchain_install per-item install events
    "install_reference_scan",  # #752 upgrade end-step sweep — stale cross-install refs reported+rewired (WARN-only face)
    "ladder_required",
    "lesson_burn",
    "lesson_citation",
    "lesson_deprecated",
    "lesson_match",
    "lesson_stage_transition",  # #525 lessons nursery draft → active
    "mcp_scaffold_refresh",  # #755 A4 .mcp.json init-parity backfill face
    "mission_snapshot",   # #823-P1 mission ledger coverage/value checkpoint
    "mission_stall",      # #634 mission-level stall fingerprint (ΔV_m flat × K)
    "must_ask",
    "must_stop",
    "plan_stall",
    "priority_deviation",
    "proven_waiver_used",  # #819 justified waiver consumed by the PROVEN evidence gate
    "redo_leak_warn",     # #772 dispatch_gate redo-prompt value-overlap WARN face
    "reject",             # hooks/env_check_gate teammate-pollution reject face (#233)
    "renew",              # #619 hook_activation TTL renewal face
    "rho_checkpoint",     # #823 P2 N-arm V/D/ETA shadow signal face
    "rollup_sweep",       # #762 tick-side mechanical rollup of terminal claims
    "skill_install_staleness",  # #755 A1 executing-install git-lag face
    "stale_plan_on_new_evidence",
    "taint_candidates",   # #692 WP5 hypothesis_seeder dexdc-taint->competitor extension
    "toolchain_manifest_check",  # #755 A6 toolchain-manifest face (code reality)
    "top1_fail_open",     # #569 dispatch_gate._top1_enforcement FAIL_OPEN face
    "top1_reject",
    "upgrade",            # #726 kunglao_upgrade summary (N->M migration)
    "upgrade_item",       # #726 per-item migration telemetry
    "uv_sync",            # #755 A7 install-venv sync face (WARN-only)
    "verify",
    "verify_status_change",  # #718 verify_status_watch disk-vs-stream reconciliation
    "violation_sed_tamper",  # #718 violation_capture out-of-band carrier rewrite
    "write_blocked",
    "write_guard_waiver_used",  # #820 waiver consumption audit face
    "zero_output_break",  # #823 A4 same-type action thrash circuit face
]

LEDGER_EVENT_MAP = {
    "fact_written": FACT_WRITTEN,
    "fact_verified": FACT_VERIFIED,
    "claim_promoted": CLAIM_PROMOTED,
    "claim_refuted": CLAIM_REFUTED,
    "failure_recorded": FAILURE_RECORDED,
    "intent_opened": INTENT_OPENED,
    "intent_closed": INTENT_CLOSED,
}

OUTCOME_RESULT_MAP = {
    "passes": OUTCOME_PASSED, "confirmed": OUTCOME_PASSED,
    "partial": OUTCOME_PARTIAL, "unverified": OUTCOME_PARTIAL,
    "unverified-with-gap": OUTCOME_PARTIAL,
    "fails": OUTCOME_FAILED, "refuted": OUTCOME_FAILED,
}

# The REAL worker status vocabulary (agents/kunglao-worker.md:54,
# convergence_check._active_workers docstring, worker_pulse:169-188,
# lib_kunglao "last status line wins"). No producer writes any other value.
WORKER_STATUS_MAP = {
    "in-progress": WORKER_STEP,
    "done": WORKER_COMPLETED,
    "blocked": WORKER_FAILED,
}

CLAIM_STATUS_MAP = {
    "PROVEN": CLAIM_PROMOTED, "VERIFIED": CLAIM_PROMOTED,
    "REFUTED": CLAIM_REFUTED,
    "PARTIALLY-VERIFIED": CLAIM_PARTIAL, "PARTIAL": CLAIM_PARTIAL,
    "PARTIALLY_VERIFIED": CLAIM_PARTIAL,
    "DEFERRED": CLAIM_DEFERRED,
    "SUPERSEDED": CLAIM_SUPERSEDED,
    "DEAD": CLAIM_DEAD,
}


def classify_event(event: dict, source: str) -> str | None:
    """Classify one event row from a known source; None when unclassifiable."""
    if source == "ledger":
        return LEDGER_EVENT_MAP.get(event.get("event_type", ""))
    if source == "convergence":
        row_type = event.get("type") or SNAPSHOT
        if row_type == SNAPSHOT:
            return SNAPSHOT
        if row_type == "outcome":
            return OUTCOME_RESULT_MAP.get(str(event.get("result", "")).strip().lower())
        if row_type == "operator_action":
            return OPERATOR_ACTION
        return None
    return None


def classify_worker_status(status: str) -> str | None:
    return WORKER_STATUS_MAP.get((status or "").strip().lower())


def classify_claim_status(status: str) -> str | None:
    return CLAIM_STATUS_MAP.get((status or "").strip().upper())


# ---------------------------------------------------------------------------
# source scanning
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _claim_statuses(ws: Path) -> list[str]:
    """Block-scoped claim status extraction (stdlib-only, mirrors kunglao_status)."""
    p = ws / "claim-register.yaml"
    if not p.exists():
        return []
    statuses: list[str] = []
    in_claim = False
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            in_claim = True
        elif in_claim and s.startswith("status:"):
            statuses.append(s.split(":", 1)[1].strip().strip("'\""))
            in_claim = False
    return statuses


def _worker_events(ws: Path) -> list[str]:
    """Classify worker status files by the REAL contract:

    - append-only log lines ("[HH:MM] step: ... | status: in-progress" or a
      dedicated "status: done" line — both shapes are the protocol)
    - FIRST status line == in-progress -> worker_started (the worker contract's
      opening line is literally "step: started ...")
    - LAST status line wins (lib_kunglao protocol, #444): in-progress ->
      step (fresh) or stuck (heartbeat stale > STUCK_SECONDS); done ->
      completed; blocked -> failed
    """
    runs = ws / "runs"
    if not runs.is_dir():
        return []
    now = time.time()
    out: list[str] = []
    parse_tokens = _worker_protocol().parse_worker_status_tokens
    for p in sorted(runs.glob("worker-status-*.md")):
        try:
            tokens = parse_tokens(p.read_text(encoding="utf-8", errors="replace"))
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if not tokens:
            continue
        first, last = tokens[0], tokens[-1]
        if first == "in-progress":
            out.append(WORKER_STARTED)
        if last == "in-progress":
            out.append(WORKER_STUCK if now - mtime > STUCK_SECONDS else WORKER_STEP)
        else:
            kind = WORKER_STATUS_MAP.get(last)
            if kind:
                out.append(kind)
    return out


def _blocker_events(ws: Path) -> list[str]:
    """Classify blockers by the REAL lifecycle (no `state:` frontmatter exists):

    - blockers/*.md without "INVALIDATED" marker = active blocker
      (convergence_check._active_blockers)
    - blockers/*.md with INVALIDATED marker, or any file under
      blockers/.resolved/ = resolved (stale_blocker_prune moves + marks)
    """
    bdir = ws / "blockers"
    if not bdir.is_dir():
        return []
    out: list[str] = []
    for p in sorted(bdir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INVALIDATED" in text.upper():
            out.append(BLOCKER_RESOLVED)
        else:
            out.append(BLOCKER_OPENED)
    resolved_dir = bdir / ".resolved"
    if resolved_dir.is_dir():
        for p in sorted(resolved_dir.glob("*.md")):
            if p.is_file():
                out.append(BLOCKER_RESOLVED)
    return out


def _gate_blocked_count(ws: Path) -> int:
    """Failure-analysis gate BLOCKED entries — the same source priority.py
    consumes for its failure-blocked dispatch set (failure_analysis_gate.
    scan_workspace); a claim with a failed attempt and no current analysis
    is BLOCKED by the gate. 0 on any error (scan is best-effort)."""
    try:
        import failure_analysis_gate as fag
        return sum(1 for b in fag.scan_workspace(Path(ws))
                   if b.get("state") == "BLOCKED")
    except Exception:
        return 0


def classify_workspace(ws: Path) -> dict[str, int]:
    """Scan all pre-existing sources; return {event_type: count}.

    State-derived views (claim register statuses, blocker files, gate scan)
    count each CURRENT state once; streams count every row. Pure read-only —
    creates no files. Every taxonomy class is always present (0 when unseen).
    """
    counts: Counter = Counter()

    for p in [ws / "ledger.jsonl"]:
        for row in _read_jsonl(p):
            kind = classify_event(row, "ledger")
            if kind:
                counts[kind] += 1
    logs = (ws / "runs" / "logs")
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            for row in _read_jsonl(p):
                kind = classify_event(row, "ledger")
                if kind:
                    counts[kind] += 1
    for row in _read_jsonl(ws / ".convergence_ledger.jsonl"):
        kind = classify_event(row, "convergence")
        if kind:
            counts[kind] += 1

    for kind in _worker_events(ws):
        counts[kind] += 1
    for st in _claim_statuses(ws):
        kind = classify_claim_status(st)
        if kind:
            counts[kind] += 1
    for kind in _blocker_events(ws):
        counts[kind] += 1
    counts[GATE_BLOCKED] += _gate_blocked_count(ws)

    runs = ws / "runs"
    if runs.is_dir():
        for p in sorted(runs.glob("verify-redteam-*.md")):
            if p.is_file():
                counts[REDTEAM_VERDICT] += 1
    # stable contract: every taxonomy class always present (0 when unseen)
    return {t: counts.get(t, 0) for t in ALL_EVENT_TYPES}


# ---------------------------------------------------------------------------
# Claude-native interface outputs
# ---------------------------------------------------------------------------

_ALERT_TYPES = (WORKER_STUCK, WORKER_FAILED, BLOCKER_OPENED, GATE_BLOCKED,
                OUTCOME_FAILED, CLAIM_DEAD)


def statusline_json(ws: Path) -> dict:
    """Compact statusline payload for the Claude native interface."""
    counts = classify_workspace(ws)
    alerts = [f"{kind}={counts[kind]}" for kind in _ALERT_TYPES if counts.get(kind)]
    return {"schema": "kunglao-event-statusline/1", "workspace": str(ws),
            "counts": counts, "alerts": alerts}


def round_digest_text(ws: Path) -> str:
    """Short per-round digest (mechanical, no LLM, <=10 lines)."""
    counts = classify_workspace(ws)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"round digest | {now} | workspace: {ws}"]
    top = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append(f"events: {top or '(none)'}")
    alerts = [f"{kind}={counts[kind]}" for kind in _ALERT_TYPES if counts.get(kind)]
    lines.append(f"alerts: {'; '.join(alerts) or '(none)'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="event_taxonomy.py",
        description="25-class event taxonomy over kunglao sources")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="print statusline JSON instead of the round digest")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value input lines (kunglao_verify parseable)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if args.reproduce:
        print(f"workspace={ws}")
        return 0
    if args.json:
        print(json.dumps(statusline_json(ws), ensure_ascii=False, indent=2))
    else:
        print(round_digest_text(ws), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
