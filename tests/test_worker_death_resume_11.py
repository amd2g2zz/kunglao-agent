# -*- coding: utf-8 -*-
"""RED tests for issue #11 — worker-death event + artifact snapshot = resume path.

Pain point (issue #11): a worker that dies mid-claim (API disconnect, crash)
leaves the claim half-done with NO structured signal — the orchestrator must
manually diff the worker's scratch output to figure out what was produced and
how to resume. backtrack_gate (#38) owns slow/HUNG workers (they still write
status files); #11 is about workers that are GONE (no more writes, ever).

Contract under test (composes with the existing stuck machinery — no
parallel detector):

  1. DETECTION — hooks/lib_kunglao.scan_active_workers (THE canonical
     liveness scan, #444) classifies a stuck worker as ``dead`` when its
     silence exceeds liveness_policy.DEAD_WORKER_MINUTES (2x STUCK_MINUTES:
     one full stuck interval past the stuck line = nothing will ever write
     again). The frozen ``(active, stuck)`` shape (#37) is preserved — the
     ``dead`` key is ADDITIVE on stuck entries.
  2. DEATH EVENT — scripts/worker_death.py writes one JSON record per dead
     worker at runs/.worker-death-<stem>.json (dot-file machine-report
     convention: .stuck-report.md / .env-check.json) capturing claim id,
     worker id, last activity ts, and the SNAPSHOT of files the worker
     produced (已完成产物清单: paths + mtimes inside the dispatch window).
  3. RESUME CONTRACT — the IN_PROGRESS claim flips back to OPEN (the #607
     reopen, now death-aware) with a history line referencing the death
     record, and the orchestrator guidance (stuck report + decide summary +
     heartbeat loop prompt) says: dispatch a RESUME claim referencing the
     artifact list — continue-from, NOT redo-from-zero.

Guards: live worker -> no death event (no false positives); stuck-but-not-
dead worker -> stuck report only; already-terminal claim -> no death event;
death record is idempotent across scans.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402
import worker_death as wd  # noqa: E402
import liveness_policy as lp  # noqa: E402
from _hooks_path import load_hooks_lib  # noqa: E402

LIB = load_hooks_lib()


# ---------- fixtures ---------------------------------------------------------

def _ws(base: Path) -> Path:
    ws = base / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _reg(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


def _ts(ws: Path) -> None:
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - id: q1\n    q: what is it\n    need: model_selection\n",
        encoding="utf-8")


def _worker(ws: Path, name: str, age_min: float,
            status: str = "in-progress") -> Path:
    """Write runs/worker-status-<name>.md backdated by age_min minutes."""
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(
        f"claim C-1 | step x | status: {status}\n", encoding="utf-8")
    old = time.time() - age_min * 60
    os.utime(p, (old, old))
    return p


def _artifact(ws: Path, rel: str, age_min: float) -> Path:
    """Write a worker-produced file at <ws>/<rel>, backdated age_min."""
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"produced by dead worker ({rel})\n", encoding="utf-8")
    old = time.time() - age_min * 60
    os.utime(p, (old, old))
    return p


def _dispatch_ctx(ws: Path, claim_id: str, age_min: float) -> Path:
    """Write runs/dispatch-context-<nid>.json with dispatch_ts backdated."""
    nid = claim_id.replace("-", "")
    p = ws / "runs" / f"dispatch-context-{nid}.json"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_min * 60))
    p.write_text(json.dumps({"claim_id": claim_id, "dispatch_ts": ts}),
                 encoding="utf-8")
    return p


def _dead_stuck_entry(stem: str, age_min: int = 45) -> dict:
    return {"worker": stem, "age_min": age_min, "dead": True}


# ---------- 1. detection: liveness policy + scan classification --------------

def test_liveness_policy_declares_dead_threshold() -> None:
    """#11: DEAD_WORKER_MINUTES lives in liveness_policy (THE #597 single
    source) and is the harder stuck criterion: 2x STUCK_MINUTES."""
    assert hasattr(lp, "DEAD_WORKER_MINUTES"), (
        "liveness_policy.DEAD_WORKER_MINUTES missing (#11)")
    assert lp.DEAD_WORKER_MINUTES > lp.STUCK_MINUTES, (
        "death must be a HARDER criterion than stuck (#11)")
    assert lp.DEAD_WORKER_MINUTES == 2 * lp.STUCK_MINUTES, (
        "adjudicated value: one full stuck interval past the stuck line")


def test_scan_active_workers_marks_dead_additively(tmp_path: Path) -> None:
    """#11: scan_active_workers stuck entries gain a ``dead`` flag.

    FROZEN shape preserved (#37): (active, stuck) with worker/age_min keys;
    ``dead`` is additive. 25 min = stuck only; 45 min = stuck AND dead.
    """
    ws = _ws(tmp_path)
    _worker(ws, "warm", age_min=25)
    _worker(ws, "gone", age_min=45)
    active, stuck = LIB.scan_active_workers(ws)
    by_stem = {s["worker"]: s for s in stuck}
    assert "worker-status-warm" in by_stem and "worker-status-gone" in by_stem
    assert by_stem["worker-status-warm"]["dead"] is False
    assert by_stem["worker-status-gone"]["dead"] is True
    # frozen keys still present
    assert by_stem["worker-status-gone"]["age_min"] >= 40


def test_scan_fresh_worker_not_dead(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _worker(ws, "alive", age_min=5)
    active, stuck = LIB.scan_active_workers(ws)
    assert stuck == [], "fresh worker is neither stuck nor dead"


# ---------- 2. death event: record + artifact snapshot ------------------------

def test_death_record_written_with_artifact_snapshot(tmp_path: Path) -> None:
    """#11 core: dead worker (dispatch record + stale activity + produced
    files) -> death event JSON containing the produced-file list (paths+ts)."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _ts(ws)
    _dispatch_ctx(ws, "C-1", age_min=60)          # dispatch anchor: -60m
    _artifact(ws, "facts/F001-heat.md", age_min=50)   # inside window
    _artifact(ws, "runs/plan-c400.md", age_min=44)    # inside window
    _artifact(ws, "notes/n-c1.md", age_min=30)        # inside window
    _artifact(ws, "facts/_scaffold-old.md", age_min=70)  # BEFORE dispatch -> out
    _worker(ws, "C-1", age_min=45)                    # last activity: -45m

    snap = cc._DecideInputs(
        workspace=ws, opens=[], partials=[], active=1,
        stuck=[_dead_stuck_entry("worker-status-C-1")],
        done_violations=[], free_slots=2, blockers=[], failure_blocked_ids=[],
        orphans=[], unverified_pqs=[], pq_note_gaps=[], pq_error=None,
        blocked_claims=[], unblocked_open=[], failure_blocked_open=[])
    cc._act_stuck_workers(snap)

    rec_path = ws / "runs" / ".worker-death-worker-status-C-1.json"
    assert rec_path.exists(), f"death record missing at {rec_path}"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    assert rec["claim_id"] == "C-1"
    assert rec["worker"] == "worker-status-C-1"
    assert rec["last_activity_ts"], "death record must carry last activity ts"
    arts = {a["path"]: a for a in rec["artifacts"]}
    assert "facts/F001-heat.md" in arts, "in-window fact missing from snapshot"
    assert "runs/plan-c400.md" in arts, "in-window plan missing from snapshot"
    assert "notes/n-c1.md" in arts, "in-window note missing from snapshot"
    assert "facts/_scaffold-old.md" not in arts, \
        "pre-dispatch file must NOT be in the snapshot"
    for a in rec["artifacts"]:
        assert a["mtime_ts"], "each snapshot entry needs its mtime ts"


def test_death_record_excludes_worker_state_and_machine_files(
        tmp_path: Path) -> None:
    """Snapshot = the worker's PRODUCTS. Worker-status protocol files, runs/
    dot-file machine reports (.stuck-report.md) and logs are never artifacts."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _ts(ws)
    _artifact(ws, "runs/logs/kunglao-2026.jsonl", age_min=44)
    (ws / "runs" / ".stuck-report.md").write_text("x", encoding="utf-8")
    _worker(ws, "C-1", age_min=45)

    snap = cc._DecideInputs(
        workspace=ws, opens=[], partials=[], active=1,
        stuck=[_dead_stuck_entry("worker-status-C-1")],
        done_violations=[], free_slots=2, blockers=[], failure_blocked_ids=[],
        orphans=[], unverified_pqs=[], pq_note_gaps=[], pq_error=None,
        blocked_claims=[], unblocked_open=[], failure_blocked_open=[])
    cc._act_stuck_workers(snap)

    rec = json.loads(
        (ws / "runs" / ".worker-death-worker-status-C-1.json")
        .read_text(encoding="utf-8"))
    paths = [a["path"] for a in rec["artifacts"]]
    assert not any(p.startswith("runs/worker-status-") for p in paths)
    assert not any(p.startswith("runs/logs/") for p in paths)
    assert not any(Path(p).name.startswith(".") for p in paths)


def test_death_record_anchor_fallback_chain(tmp_path: Path) -> None:
    """Window anchor: dispatch-context JSON > claim dispatched_at >
    claim created_at > approximate (flagged, never silent)."""
    ws = _ws(tmp_path)
    _ts(ws)
    _worker(ws, "C-2", age_min=45)

    # (a) no anchors at all -> approximate, flagged in the record
    _reg(ws, [{"id": "C-2", "status": "IN_PROGRESS"}])
    snap = cc._DecideInputs(
        workspace=ws, opens=[], partials=[], active=1,
        stuck=[_dead_stuck_entry("worker-status-C-2")],
        done_violations=[], free_slots=2, blockers=[], failure_blocked_ids=[],
        orphans=[], unverified_pqs=[], pq_note_gaps=[], pq_error=None,
        blocked_claims=[], unblocked_open=[], failure_blocked_open=[])
    cc._act_stuck_workers(snap)
    rec = json.loads(
        (ws / "runs" / ".worker-death-worker-status-C-2.json")
        .read_text(encoding="utf-8"))
    assert rec["dispatch_anchor"] == "approximate", (
        "unknown dispatch anchor must be flagged approximate, not silent")

    # (b) claim dispatched_at anchor
    _reg(ws, [{"id": "C-2", "status": "IN_PROGRESS",
               "dispatched_at": "2026-09-04T00:00:00Z"}])
    wd.write_death_records(ws, [_dead_stuck_entry("worker-status-C-2")],
                           force=True)
    rec = json.loads(
        (ws / "runs" / ".worker-death-worker-status-C-2.json")
        .read_text(encoding="utf-8"))
    assert rec["dispatch_anchor"] == "claim_dispatched_at"

    # (c) dispatch-context JSON wins over the claim field
    _dispatch_ctx(ws, "C-2", age_min=60)
    wd.write_death_records(ws, [_dead_stuck_entry("worker-status-C-2")],
                           force=True)
    rec = json.loads(
        (ws / "runs" / ".worker-death-worker-status-C-2.json")
        .read_text(encoding="utf-8"))
    assert rec["dispatch_anchor"] == "dispatch_context"


# ---------- 3. resume contract ------------------------------------------------

def test_decide_writes_death_record_and_reopens_claim(tmp_path: Path) -> None:
    """#11 e2e: dead worker + IN_PROGRESS claim -> BLOCKED, death record on
    disk, claim flipped OPEN with a death-record-referencing history line."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"},
              {"id": "C-2", "status": "OPEN", "blocked": True}])
    _ts(ws)
    _dispatch_ctx(ws, "C-1", age_min=60)
    _artifact(ws, "facts/F001-heat.md", age_min=50)
    _worker(ws, "C-1", age_min=45)

    decision = cc.decide(ws)
    assert decision["decision"] == "BLOCKED", decision
    assert (ws / "runs" / ".worker-death-worker-status-C-1.json").exists()

    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    c1 = next(c for c in reg["claims"] if c["id"] == "C-1")
    assert c1["status"] == "OPEN", \
        f"dead worker's claim must be re-dispatchable (OPEN), got {c1['status']}"
    hist = "\n".join(c1.get("history") or [])
    assert ".worker-death-" in hist, \
        "reopened claim history must reference the death record"


def test_resume_guidance_present_in_report_and_summary(tmp_path: Path) -> None:
    """The orchestrator must be TOLD what to do: stuck report + decide
    summary carry the death-resume instruction (continue-from, not redo)."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _ts(ws)
    _dispatch_ctx(ws, "C-1", age_min=60)
    _artifact(ws, "facts/F001-heat.md", age_min=50)
    _worker(ws, "C-1", age_min=45)

    snap = cc._decide_inputs(ws)
    summary = cc._act_stuck_workers(snap)

    report = (ws / "runs" / ".stuck-report.md").read_text(encoding="utf-8")
    assert ".worker-death-" in report, \
        "stuck report must point at the death record"
    assert "resume" in report.lower(), "report must carry resume guidance"
    assert ".worker-death-" in summary, "summary must point at the death record"
    assert "resume" in summary.lower(), "summary must carry resume guidance"
    assert "not redo" in summary.lower() or "continue from" in summary.lower()


def test_heartbeat_loop_prompt_carries_death_resume_instruction() -> None:
    """#11: the tick prompt (orchestrator decision contract) must say what a
    worker-death event means: dispatch a RESUME claim, continue-from."""
    from heartbeat_loop_prompt import build_prompt
    prompt = build_prompt("/tmp/ws-nonexistent-11")
    assert ".worker-death-" in prompt, \
        "heartbeat loop prompt must reference the death-record surface"
    assert "resume" in prompt.lower()


# ---------- 4. guards ---------------------------------------------------------

def test_live_worker_no_death_event(tmp_path: Path) -> None:
    """No false positives: fresh worker -> no death record, claim untouched."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _ts(ws)
    _worker(ws, "C-1", age_min=5)

    cc.decide(ws)
    assert not (ws / "runs" / ".worker-death-worker-status-C-1.json").exists()
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    assert reg["claims"][0]["status"] == "IN_PROGRESS"


def test_stuck_not_dead_no_death_event(tmp_path: Path) -> None:
    """20-40 min = backtrack_gate's territory (#38): stuck report fires, but
    NO death record — death is reserved for the gone-worker band."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"},
              {"id": "C-2", "status": "OPEN", "blocked": True}])
    _ts(ws)
    _worker(ws, "C-1", age_min=25)

    cc.decide(ws)
    assert (ws / "runs" / ".stuck-report.md").exists(), "still #595 stuck"
    assert not (ws / "runs" / ".worker-death-worker-status-C-1.json").exists(), \
        "stuck-but-alive worker must not produce a death event"


def test_terminal_claim_no_death_event(tmp_path: Path) -> None:
    """A dead worker file over an already-terminal claim is debris, not a
    half-done claim — no death event, nothing to resume."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "PROVEN"}])
    _ts(ws)
    _artifact(ws, "facts/F001-heat.md", age_min=50)
    _worker(ws, "C-1", age_min=45)

    snap = cc._decide_inputs(ws)
    cc._act_stuck_workers(snap)
    assert not (ws / "runs" / ".worker-death-worker-status-C-1.json").exists(), \
        "terminal claim must not get a death event"


def test_death_record_idempotent_across_scans(tmp_path: Path) -> None:
    """Two scans, one death record: no duplicates, no content rewrite."""
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "IN_PROGRESS"}])
    _ts(ws)
    _dispatch_ctx(ws, "C-1", age_min=60)
    _artifact(ws, "facts/F001-heat.md", age_min=50)
    _worker(ws, "C-1", age_min=45)
    entry = _dead_stuck_entry("worker-status-C-1")

    p1 = wd.write_death_records(ws, [entry])
    first = (ws / "runs" / ".worker-death-worker-status-C-1.json")
    body1 = first.read_bytes()
    mtime1 = first.stat().st_mtime_ns

    p2 = wd.write_death_records(ws, [entry])
    body2 = first.read_bytes()
    mtime2 = first.stat().st_mtime_ns

    assert len(p1) == 1 and len(p2) == 0, \
        "second scan must write nothing (idempotent by existing record)"
    assert body1 == body2 and mtime1 == mtime2, \
        "existing death record must not be rewritten"
    records = list((ws / "runs").glob(".worker-death-*.json"))
    assert len(records) == 1, "exactly one death record per dead worker"


def test_missing_claim_no_death_event(tmp_path: Path) -> None:
    """No claim register match -> nothing resumable -> no death record."""
    ws = _ws(tmp_path)
    _ts(ws)
    _worker(ws, "C-9", age_min=45)
    assert wd.write_death_records(
        ws, [_dead_stuck_entry("worker-status-C-9")]) == []
    assert not (ws / "runs" / ".worker-death-worker-status-C-9.json").exists()
