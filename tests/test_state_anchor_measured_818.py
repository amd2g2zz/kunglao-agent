# -*- coding: utf-8 -*-
"""tests/test_state_anchor_measured_818.py — the per-turn state re-anchor
in the MEASURED leg (issue #818 coverage climb).

The existing pins (tests/test_state_anchor.py) live in the fast tier,
which the CI measured-set leg does not execute (`-m "not fast"`) — so
the anchor's real behavior is invisible to the coverage floor. This file
re-pins the core faces on REAL fixture workspaces in the measured leg:
the anchor composition + cap, the drift prefix from the single-source
drift lib, the machine-readable payload, and the process_event gate
chain (tool gate, workspace resolve, strict activation, fail-open).
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import state_anchor as sa  # noqa: E402  (hooks/ on pytest path)
from _factories import write_hook_state  # noqa: E402


def ts(minutes_ago: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def future_iso(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)
            ).isoformat().replace("+00:00", "Z")


def snap(decision="DISPATCH", open_ids=("C-1",), **extra) -> dict:
    row = {"ts": ts(), "decision": decision,
           "open_count": len(open_ids), "open_ids": list(open_ids),
           "partial_count": 0, "active_workers": 0, "blockers": [],
           "facts_total": 2}
    row.update(extra)
    return row


def seed_ws(tmp_path: Path, rows: list, claims=("C-1",)) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".convergence_ledger.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    lines = ["claims:"]
    for cid in claims:
        lines.append(f"- id: {cid}")
        lines.append("  status: OPEN")
    (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")
    return ws


def activate(ws: Path, hook="state_anchor") -> Path:
    write_hook_state(ws, active_hooks=[hook], ts=ts(), tier="none",
                     phase="IDLE", user_override={},
                     expires_at=future_iso(30))
    return ws


# ---------- build_anchor: composition + cap ----------

def test_anchor_carries_decision_counts_and_open_ids(tmp_path) -> None:
    ws = seed_ws(tmp_path, [snap(decision="DISPATCH", open_ids=["C-1",
                                                               "C-2"])],
                 claims=["C-1", "C-2"])
    anchor = sa.build_anchor(ws)
    assert anchor.startswith("[state_anchor]")
    assert "decision=DISPATCH" in anchor
    assert "open_count=2" in anchor
    assert "facts=2" in anchor
    assert "C-1, C-2" in anchor
    assert len(anchor) <= sa.ANCHOR_CAP


def test_anchor_without_snapshot_is_silent(tmp_path) -> None:
    ws = seed_ws(tmp_path, [])
    assert sa.build_anchor(ws) == ""


def test_anchor_outcome_rows_are_events_never_snapshots(tmp_path) -> None:
    ws = seed_ws(tmp_path, [snap(), {"ts": ts(), "type": "outcome"}])
    payload = sa.build_anchor_payload(ws)
    assert payload["round"] == 1   # only the SNAPSHOT row counted


def test_anchor_drift_prefix_from_identical_signature_run(
        tmp_path) -> None:
    # three identical decision-relevant signatures + zero worker movement
    # -> the cure layer's STATE FLAT warning rides the anchor
    ws = seed_ws(tmp_path, [snap() for _ in range(3)])
    anchor = sa.build_anchor(ws)
    assert "STATE FLAT" in anchor
    assert "re-read claim-register" in anchor
    # a moving worker suppresses the drift warning (liveness wins)
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    p = runs / "worker-status-w1.md"
    p.write_text(f"[{ts()}] step: x | status: in-progress\n",
                 encoding="utf-8")
    assert "STATE FLAT" not in sa.build_anchor(ws)


def test_register_open_ids_fallback_when_snapshot_lacks_ids(
        tmp_path) -> None:
    ws = seed_ws(tmp_path, [{"ts": ts(), "decision": "DISPATCH",
                             "open_count": None, "partial_count": 0,
                             "active_workers": 0, "blockers": [],
                             "facts_total": None}],
                 claims=["C-9"])
    facts = ws / "facts"
    facts.mkdir()
    (facts / "F001.md").write_text("x", encoding="utf-8")
    anchor = sa.build_anchor(ws)
    assert "open_count=1" in anchor      # derived from the register scan
    assert "C-9" in anchor
    assert "facts=1" in anchor           # counted from facts/ when absent


# ---------- _compose: the 500-char budget ----------

def test_compose_truncates_open_ids_from_the_tail(tmp_path) -> None:
    many = [f"C-{i:03d}" for i in range(1, 60)]
    text = sa._compose("", 1, "DISPATCH", len(many), 0, 0, [], 0, many)
    assert len(text) <= sa.ANCHOR_CAP
    assert text.endswith(", ...")          # tail truncation marker
    assert text.startswith("[state_anchor]" )


def test_compose_hypothesis_segment_drops_first_under_pressure(
        tmp_path) -> None:
    many = [f"C-{i:03d}" for i in range(1, 60)]
    hyps = [{"claim_id": f"C-{i:03d}", "hyp_id": f"H-{i:03d}"}
            for i in range(1, 20)]
    text = sa._compose("", 1, "DISPATCH", len(many), 0, 0, [], 0, many,
                       hyp_pointers=hyps)
    assert len(text) <= sa.ANCHOR_CAP
    # the ids list survives; the hyp segment (if present) is structured
    if "hyps=" in text:
        assert "H-001(C-001)" in text


def test_compose_hyp_segment_caps_at_ten_pointers() -> None:
    hyps = [{"claim_id": f"C-{i:03d}", "hyp_id": f"H-{i:03d}"}
            for i in range(1, 15)]
    text = sa._compose("", 1, "DISPATCH", 1, 0, 0, [], 0, ["C-1"],
                       hyp_pointers=hyps)
    assert f"hyps={len(hyps)}" in text          # total count is honest
    assert text.count("(") <= sa.HYP_SEGMENT_CAP
    assert "+4" in text                          # the tail-overrun face


# ---------- build_anchor_payload ----------

def test_payload_shape_round_decision_open_ids(tmp_path) -> None:
    ws = seed_ws(tmp_path, [snap(decision="VERIFY", open_ids=["C-1"])])
    d = ws / "hypotheses"
    d.mkdir()
    (d / "H-1.md").write_text(
        "---\nid: H-1\nclaim_id: C-1\ncompetitor_group: x\n"
        "candidates: [a]\nstatus: open\nschema_rev: 1\n---\nbody\n",
        encoding="utf-8")
    payload = sa.build_anchor_payload(ws)
    assert payload["round"] == 1
    assert payload["decision"] == "VERIFY"
    assert payload["open_ids"] == ["C-1"]
    assert payload["hypothesis_pointers"] == [{"claim_id": "C-1",
                                               "hyp_id": "H-1"}]


# ---------- process_event: the gate chain ----------

def test_process_event_non_agent_tool_is_silent(tmp_path, capsys) -> None:
    ws = activate(seed_ws(tmp_path, [snap()]))
    assert sa.process_event({"tool_name": "Bash", "cwd": str(ws)}) == 0
    assert capsys.readouterr().out == ""


def test_process_event_case_insensitive_agent_gate(tmp_path, capsys) -> None:
    ws = activate(seed_ws(tmp_path, [snap()]))
    rc = sa.process_event({"tool_name": "Agent", "cwd": str(ws)})
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"].startswith(
        "[state_anchor]")
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_process_event_unresolvable_workspace_is_silent(
        tmp_path, capsys) -> None:
    activate(seed_ws(tmp_path, [snap()]))
    assert sa.process_event({"tool_name": "agent",
                             "cwd": str(tmp_path / "void")}) == 0
    assert capsys.readouterr().out == ""


def test_process_event_inactive_session_sleeps(tmp_path, capsys) -> None:
    # workspace resolves but the strict activation is absent -> sleeps
    ws = seed_ws(tmp_path, [snap()])
    assert sa.process_event({"tool_name": "agent", "cwd": str(ws)}) == 0
    assert capsys.readouterr().out == ""


def test_process_event_expired_activation_sleeps(tmp_path, capsys) -> None:
    ws = seed_ws(tmp_path, [snap()])
    write_hook_state(ws, active_hooks=["state_anchor"], ts=ts(),
                     tier="none", phase="IDLE", user_override={},
                     expires_at="2000-01-01T00:00:00Z")
    assert sa.process_event({"tool_name": "agent", "cwd": str(ws)}) == 0
    assert capsys.readouterr().out == ""


def test_main_unparseable_stdin_fails_open(capsys) -> None:
    assert sa.main(io.StringIO("{broken")) == 0
    assert capsys.readouterr().out == ""


def test_main_empty_stdin_silent(capsys) -> None:
    assert sa.main(io.StringIO("")) == 0
    assert capsys.readouterr().out == ""


def test_build_anchor_never_raises_on_corrupt_ledger(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".convergence_ledger.jsonl").write_text(
        "{corrupt\n[[[\nnot json\n", encoding="utf-8")
    assert sa.build_anchor(ws) == ""
    assert sa._last_snapshot(ws) == (None, 0)


def test_count_facts_counts_only_fact_files(tmp_path) -> None:
    ws = tmp_path / "ws"
    facts = ws / "facts"
    facts.mkdir(parents=True)
    (facts / "F001.md").write_text("x", encoding="utf-8")
    (facts / "F002.md").write_text("x", encoding="utf-8")
    (facts / "_INDEX.md").write_text("x", encoding="utf-8")
    (facts / "notes.md").write_text("x", encoding="utf-8")
    assert sa._count_facts(ws) == 2
