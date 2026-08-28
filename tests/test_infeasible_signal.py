# -*- coding: utf-8 -*-
"""A4 ② (#823): infeasible early-stop signal — doomed trajectory detector.

Fires `infeasible_candidate` (event only, shadow posture) when BOTH:
  - V ≈ 0 for K consecutive rho_checkpoint rounds, AND
  - the marginal discovery rate is 0 (terminal-fact count unchanged
    across those rounds).
This is the #815 anti-dead-horse face: declaring a channel infeasible is
the SKILL layer's job (obstacle +3 pruning semantics); this module only
produces the mechanical signal.
"""
import json
import sys
from pathlib import Path

import infeasible_signal as isg


def _mk_ws(tmp: Path, v_series, terminal_count=2) -> Path:
    ws = tmp / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs" / "logs").mkdir(parents=True)
    rows = [f"F{i + 1:03d} | PROVEN | C-{i + 1:03d} | x" for i in range(terminal_count)]
    (ws / "facts" / "_INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    with (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").open("w", encoding="utf-8") as f:
        for v in v_series:
            f.write(json.dumps({
                "ts": "2026-08-28T00:00:00Z", "actor": "rho_checkpoint",
                "action": "rho_checkpoint", "claim": None, "tool": None,
                "artifact": None, "duration_ms": None, "exit": None,
                "detail": json.dumps({"v": v})}) + "\n")
    return ws


def test_flat_v_and_zero_discovery_fires(tmp_path):
    ws = _mk_ws(tmp_path, [0.05, 0.05, 0.05], terminal_count=2)
    out = isg.evaluate(ws)
    assert out["infeasible_candidate"] is True
    assert out["v_flat_rounds"] >= isg.K_ROUNDS


def test_rising_v_does_not_fire(tmp_path):
    ws = _mk_ws(tmp_path, [0.05, 0.2, 0.5], terminal_count=2)
    assert isg.evaluate(ws)["infeasible_candidate"] is False


def test_flat_v_but_still_discovering_does_not_fire(tmp_path):
    # terminal count keeps growing → the channel yields, not infeasible
    ws2 = tmp_path / "ws"
    (ws2 / "runs" / "logs").mkdir(parents=True)
    (ws2 / "facts").mkdir(parents=True)
    (ws2 / "facts" / "_INDEX.md").write_text(
        "F001 | PROVEN | C-001 | x\nF002 | PROVEN | C-002 | x\n"
        "F003 | PROVEN | C-003 | x\n", encoding="utf-8")
    assert isg.evaluate(ws2, v_series=[0.05, 0.05, 0.05],
                        prev_terminal_count=2)["infeasible_candidate"] is False


def test_event_emitted_on_fire(tmp_path):
    ws = _mk_ws(tmp_path, [0.05, 0.05, 0.05], terminal_count=2)
    before = len((ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").read_text(
        encoding="utf-8").splitlines())
    isg.evaluate(ws)
    lines = (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == before + 1
    assert json.loads(lines[-1])["action"] == "infeasible_candidate"
