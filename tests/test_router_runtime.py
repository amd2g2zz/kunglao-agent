# -*- coding: utf-8 -*-
"""Router runtime tests (issue #370) — the REAL runtime path, not --help.

CI previously gated the router on `kunglao.py <sub> --help` exit 0 only
(tests/test_release_receipt.py:106-110), which stayed green while 3 of 5
subcommands were broken at runtime:

  - cmd_tick ignored args.workspace and called hbt.main(), which read
    sys.argv[1] == the literal string "tick" as the workspace path;
  - cmd_decide (human mode) and cmd_health called legacy main()s that
    re-parsed the ROUTER's argv via nested argparse -> SystemExit 2.

These tests drive every subcommand via subprocess with an explicit scratch
workspace — the path SKILL.md:91 advertises ("mechanical CLI passthrough").
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "scripts" / "kunglao.py"


def _run_router(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # UTF-8 convention (#317/#320): child output is UTF-8, not locale.
    return subprocess.run(
        [sys.executable, str(ROUTER), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _make_ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    """Minimal workspace (same shape as tests/test_decide_schema_routing._make_ws)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    reg = [{"id": "C-1", "status": "OPEN"}] if claims is None else claims
    (ws / "claim-register.yaml").write_text(
        "claims:\n" + "".join(
            f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
            f"  boundary_type: {c.get('boundary_type', 'positive_observation')}\n"
            f"  evidence_tier_attempted: {c.get('evidence_tier_attempted', 0)}\n"
            f"  promotion_attempts: {c.get('promotion_attempts', 0)}\n"
            f"  depends_on: {c.get('depends_on', '[]')}\n"
            for c in reg
        ), encoding="utf-8")
    return ws


class TestRouterTick:
    def test_tick_uses_explicit_workspace_and_writes_report(self, tmp_path):
        """kunglao.py tick <ws> must run the heartbeat chain against <ws>.

        RED before fix: cmd_tick passed hbt.main() no args, so heartbeat_tick
        resolved sys.argv[1] == "tick" (the router subcommand token) as the
        workspace — producing a bogus tick/ dir next to cwd and exit 1 with a
        workspace-misresolution, never touching the caller's workspace.
        """
        ws = _make_ws(tmp_path)
        r = _run_router("tick", str(ws))
        report = ws / "runs" / ".heartbeat-tick.json"
        assert report.exists(), (
            f"tick did not write {report} — workspace arg ignored "
            f"(rc={r.returncode}, stderr={r.stderr[:300]})"
        )
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["workspace"] == str(ws.resolve()), (
            f"report workspace {data['workspace']!r} != requested {str(ws.resolve())!r}"
        )
        # Documented tick exit semantics: 0 = all OK, 1 = stale/missing hooks
        # (attention required) — never argparse's SystemExit 2.
        assert r.returncode in (0, 1), f"tick rc={r.returncode}: {r.stderr[:300]}"

    def test_tick_does_not_create_bogus_tick_dir_next_to_cwd(self, tmp_path, monkeypatch):
        """The workspace-misresolution side effect: the broken cmd_tick made
        heartbeat_tick probe cwd and could materialize ./tick/ when cwd
        happened to satisfy the probe. After the fix, cwd is never consulted."""
        ws = _make_ws(tmp_path)
        monkeypatch.chdir(tmp_path)
        r = _run_router("tick", str(ws))
        assert not (tmp_path / "tick").exists(), "router tick created a bogus ./tick dir"


class TestRouterDecide:
    def test_decide_human_mode_prints_decision_not_argparse_error(self, tmp_path):
        """kunglao.py decide <ws> (human mode) must print a real decision.

        RED before fix: cmd_decide fell through to cc.main(), whose nested
        argparse re-parsed the ROUTER's argv ("decide <ws>") against
        convergence_check's <ws> --json surface -> SystemExit 2
        ("unrecognized arguments").
        """
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        r = _run_router("decide", str(ws))
        assert r.returncode != 2, (
            f"SystemExit 2 (nested argparse): stderr={r.stderr[:300]}"
        )
        assert "usage:" not in r.stderr, f"argparse usage printed: {r.stderr[:300]}"
        # A real decision: the same token the legacy CLI prints.
        assert "=== CONVERGENCE CHECK:" in r.stdout, f"stdout={r.stdout[:300]}"
        # OPEN claim + free slots -> DISPATCH (matrix), exit 1.
        assert "DISPATCH" in r.stdout
        assert r.returncode == 1

    def test_decide_json_mode_still_works(self, tmp_path):
        """Regression guard: the working sub-path (E3.1 byte-identical JSON)
        must keep passing while human mode is repaired."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        r = _run_router("decide", str(ws), "--json")
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert out["decision"] == "DISPATCH"


class TestRouterHealth:
    def test_health_exits_cleanly_with_health_output(self, tmp_path):
        """kunglao.py health <ws> must run the health assessment.

        RED before fix: cmd_health called ch.main(), whose nested argparse
        re-parsed the ROUTER's argv ("health <ws>") -> SystemExit 2.
        """
        ws = _make_ws(tmp_path)
        # One prior decide turn -> a ledger entry exists -> HEALTHY warming-up.
        # (Ledger note: the router decide --json path calls cc.decide() without
        # the ledger side channel — that is the FROZEN E3.1 byte-identical
        # contract — so seed the ledger via the legacy cc CLI, which owns it.)
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "convergence_check.py"),
             str(ws), "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        assert r.returncode == 1
        r = _run_router("health", str(ws))
        assert r.returncode != 2, (
            f"SystemExit 2 (nested argparse): stderr={r.stderr[:300]}"
        )
        assert "usage:" not in r.stderr, f"argparse usage printed: {r.stderr[:300]}"
        assert "=== CONVERGENCE HEALTH:" in r.stdout, f"stdout={r.stdout[:300]}"
        # 1 ledger snapshot -> warming up -> HEALTHY (exit 0)
        assert r.returncode == 0

    def test_health_no_ledger_exits_no_data(self, tmp_path):
        """Health on a workspace with no ledger exits EXIT_NO_DATA (3) with the
        FAIL line on stderr — the legacy CLI contract, not argparse's 2."""
        ws = _make_ws(tmp_path)
        r = _run_router("health", str(ws))
        assert r.returncode == 3, f"rc={r.returncode}: {r.stderr[:200]}"
        assert ".convergence_ledger.jsonl" in r.stderr
