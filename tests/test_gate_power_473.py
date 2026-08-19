# -*- coding: utf-8 -*-
"""TDD RED — issue #473: gate-chain power-on.

RED contract (dev baseline 8bae2b8, 2026-08-19): the 2026-08-18 worker
closing-escape narration (four steps, sanitized below) fires ZERO-to-one
fingerprints on the baseline tables; a fresh kunglao-init workspace has no
task-oracle.yaml; the heartbeat tick report has no oracle field; no
imperative rule exists.

Sanitized fixture (SYNTHETIC test data, quoted from the issue's 现象段):
  step 1 self-completion   "我能继续的事都已经做了"        (F4 semantic)
  step 2 invented tier     "需要 1-2 小时纯人工 RE"        (F2 handoff + time cost)
  step 3 cost stop reason  "Session 边界再次到这"          (cost-as-stop framing)
  step 4 user imperative   "你能继续的路: Ghidra GUI 手动跟 30 分钟, 把字节码 dump 给我"
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import premature_termination_detect as pt  # noqa: E402

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# ---------------------------------------------------------------------------
# Fixture — the sanitized 2026-08-18 four-step closing escape.
# ---------------------------------------------------------------------------
ESCAPE_FIXTURE = """\
我能继续的事都已经做了。当前剩余的工作需要 1-2 小时纯人工 RE。
Session 边界再次到这，继续投入的成本已经超过收益。
你能继续的路: Ghidra GUI 手动跟 30 分钟，把字节码 dump 给我。
"""

CLEAN_CLOSURE = (
    "All claims PROVEN, 0 open items. The user's 're-analyze every gap' goal "
    "is fully met; delivering the fact base now."
)


# ===========================================================================
# (a) The escape narration fires >= 3 fingerprints (RED on baseline: 0)
# ===========================================================================

def test_escape_fixture_fires_at_least_3_fingerprints():
    report = pt.detect(ESCAPE_FIXTURE)
    assert report["fired_count"] >= 3, report


def test_escape_fixture_fires_the_handoff_and_time_cost_families():
    """The firing set must include the NEW families this change adds: F2
    handoff tiering and F3 time-cost drift (baseline misses both)."""
    report = pt.detect(ESCAPE_FIXTURE)
    fired = set(report["fired_ids"])
    assert "F2" in fired, f"F2 handoff tiering missing: {report}"
    assert "F3" in fired, f"F3 time-cost drift missing: {report}"


def test_escape_fixture_fires_f4_semantic_completion():
    """"我能继续的事都已经做了" is a completion declaration — F4 must fire
    on the semantic-equivalent phrase (baseline: literal phrases only)."""
    report = pt.detect("我能继续的事都已经做了。G1-G6 中还有 G4 未关闭。")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F4"]["fired"] is True, report


def test_time_cost_figure_fires_f3_under_qualifier():
    report = pt.detect("需要 1-2 小时纯人工 RE — informational only.")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F3"]["fired"] is True, report


def test_bare_time_estimate_without_stop_qualifier_stays_quiet():
    """Precision guard: a bare time report ("the scan took 30 分钟") is NOT
    a stop reason — same D4 rule as the bare currency figure."""
    report = pt.detect("The scan took 30 分钟 in total. Facts recorded.")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F3"]["fired"] is False, report


# ===========================================================================
# (b) Clean completion stays zero (precision guard)
# ===========================================================================

def test_clean_completion_fires_zero():
    report = pt.detect(CLEAN_CLOSURE, task_text="re-analyze every gap")
    assert report["fired_count"] == 0, report


def test_clean_cjk_completion_fires_zero():
    """A clean Chinese closure with zero-open phrasing must not trip the new
    CJK tables (我能做的都做了 must NOT fire when zero-open is asserted)."""
    transcript = (
        "全部 5 项 claim 已 PROVEN，没有遗留项，0 open。我能做的都做了，"
        "现在交付事实库。"
    )
    report = pt.detect(transcript, task_text="全面重检当前分析")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F4"]["fired"] is False, report


# ===========================================================================
# (d) Imperative rule — F5 user-delegation escape
# ===========================================================================

def test_imperative_plus_open_items_fires_f5():
    report = pt.detect(
        "G4 未关闭。你能继续的路: 把字节码 dump 给我。")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id.get("F5", {}).get("fired") is True, report


def test_imperative_with_zero_open_stays_quiet():
    report = pt.detect(
        "全部完成，0 open items，没有遗留。把结果打包给用户即可。")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    f5 = by_id.get("F5", {})
    assert f5.get("fired") is False, report


def test_f5_in_escape_fixture():
    """The step-4 imperative ("你能继续的路…dump 给我") + open signals fires
    F5 within the full fixture."""
    report = pt.detect(ESCAPE_FIXTURE)
    fired = set(report["fired_ids"])
    assert "F5" in fired, report


# ===========================================================================
# (f) Tool-rebuttal duty — needs-human declarations demand evidence
# ===========================================================================

def test_needs_human_declaration_requires_tool_search_evidence():
    report = pt.detect("剩余工作需要 1-2 小时纯人工 RE，无法自动化。")
    assert "tool_search_zero_hit" in (report.get("require_evidence") or []), report


def test_no_needs_human_assertion_no_evidence_duty():
    report = pt.detect("The static pass finished; dispatching the dynamic pass next.")
    assert not report.get("require_evidence"), report


# ===========================================================================
# (c) init leaves a non-empty task-oracle.yaml (RED on baseline: absent)
# ===========================================================================

def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    return ws


def _run_init(ws: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    argv += ["--type", "windows", "--skip-toolchain",
             "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    if not (ws.parent / "fake-claude.json").exists():
        (ws.parent / "fake-claude.json").write_text("{}", encoding="utf-8")
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def test_init_leaves_nonempty_task_oracle(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == 0, r.stderr
    oracle = ws / "task-oracle.yaml"
    assert oracle.exists(), "init must register the task-oracle skeleton (#473)"
    data = yaml.safe_load(oracle.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "oracle skeleton must parse non-empty"
    assert data.get("registered_ts"), data
    assert data.get("open_items") == []
    assert data.get("deferrals") == []


def test_init_does_not_clobber_backfilled_oracle(tmp_path):
    """Idempotency: a backfilled (Phase-0-completed) oracle survives a
    --force re-init — the skeleton write only fills absence."""
    ws = _mk_ws(tmp_path)
    assert _run_init(ws).returncode == 0
    oracle = ws / "task-oracle.yaml"
    data = yaml.safe_load(oracle.read_text(encoding="utf-8"))
    data["task_text"] = "user verbatim task"
    oracle.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                      encoding="utf-8")
    assert _run_init(ws, ["--force"]).returncode == 0
    after = yaml.safe_load(oracle.read_text(encoding="utf-8"))
    assert after.get("task_text") == "user verbatim task", after


# ===========================================================================
# (e) heartbeat tick reports oracle registration
# ===========================================================================

def _make_tick_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "tws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _tick(ws: Path) -> tuple[dict, str]:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    report = json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return report, r.stdout


def test_tick_reports_missing_oracle(tmp_path):
    ws = _make_tick_ws(tmp_path)
    report, stdout = _tick(ws)
    assert report.get("oracle_registered") is False, report
    assert "task-oracle" in stdout, stdout


def test_tick_reports_registered_oracle(tmp_path):
    ws = _make_tick_ws(tmp_path)
    (ws / "task-oracle.yaml").write_text(
        "task_text: 用户提供的原话任务描述（backfill 完成）\nregistered_ts: 2026-08-19T00:00:00Z\n",
        encoding="utf-8")
    report, stdout = _tick(ws)
    assert report.get("oracle_registered") is True, report
    assert "task-oracle" not in stdout, stdout


def test_tick_reports_marker_skeleton_as_unregistered(tmp_path):
    """#473 review HIGH-1: the init skeleton marker is NOT a registered
    oracle — backfill pending must keep the nag line firing (otherwise the
    gate would sit silently unpowered on every freshly-inited workspace)."""
    ws = _make_tick_ws(tmp_path)
    (ws / "task-oracle.yaml").write_text(
        "task_text: pending-user-input-backfill\nregistered_ts: 2026-08-19T00:00:00Z\n",
        encoding="utf-8")
    report, stdout = _tick(ws)
    assert report.get("oracle_registered") is False, report
    assert "task-oracle" in stdout, stdout


def test_completion_gate_refuses_skeleton_marker():
    """#473 review HIGH-1: judge() must treat the skeleton marker as a
    missing anchor (exit 3), never as a legal task_text (the pre-#473
    fail-closed semantics for oracle-less workspaces)."""
    import completion_gate as cg
    code, reason = cg.judge({
        "task_text": "pending-user-input-backfill",
        "open_items": [], "deferrals": []})
    assert code == 3, f"skeleton marker must refuse (exit 3), got {code}: {reason}"
    assert "backfill" in reason.lower(), reason


# ===========================================================================
# SKILL.md contract — Phase 1 carries the oracle backfill step
# ===========================================================================

def test_skill_md_names_oracle_backfill():
    text = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "task-oracle.yaml" in text, (
        "Phase 1 must name the oracle backfill step (#473)")


# ===========================================================================
# 故障注入验收（fault injection, 2026-08-19 用户要求）— 故意损坏 oracle 骨架的
# 三个通道，验证检测/降级路径诚实：门对损坏输入的行为必须是可观察的，
# 不是静默通过。每条注入对应一个真实故障面（半写入/截断/权限）。
# ===========================================================================

def test_fault_injection_empty_oracle_reports_unregistered(tmp_path):
    """注入: oracle 文件存在但为空（半写入/截断故障）→ tick 必须报
    oracle_registered=False 并输出催告行（零字节文件不算已注册）。"""
    ws = _make_tick_ws(tmp_path)
    (ws / "task-oracle.yaml").write_text("", encoding="utf-8")
    report, stdout = _tick(ws)
    assert report.get("oracle_registered") is False, (
        f"empty oracle must read as unregistered: {report}")
    assert "task-oracle" in stdout, stdout


def test_fault_injection_unreadable_oracle_fails_open_to_unregistered(tmp_path):
    """注入: oracle 存在但不可读（权限故障）→ _oracle_registered 的
    OSError 防护必须 fail-open 为 False 并催告（不 crash tick）。"""
    import heartbeat_tick as ht
    ws = _make_tick_ws(tmp_path)
    oracle = ws / "task-oracle.yaml"
    oracle.write_text("task_text: x\n", encoding="utf-8")
    oracle.chmod(0o000)
    try:
        assert ht._oracle_registered(ws) is False, (
            "unreadable oracle must fail-open to False, never raise")
    finally:
        oracle.chmod(0o644)  # tmp_path cleanup needs the bit back


def test_fault_injection_detector_survives_malformed_declaration():
    """注入: 收尾声明传入畸形输入（None/非字符串/二进制噪声）→ detect
    不 crash（completion_gate 的 except 兜底之外，detector 自身要稳），
    返回结构合法的 report（fired_count 是 int）。"""
    import premature_termination_detect as ptd
    for bad in ("", "\x00\x01\x02", "�" * 100, "\n" * 50):
        report = ptd.detect(bad)
        assert isinstance(report.get("fired_count"), int), bad[:20]
        assert isinstance(report.get("fingerprints"), list), bad[:20]
    # 2026-08-18 四步逃逸叙述在 detector 正常路径上的对照（同输入必须稳定触发）
    report = ptd.detect(
        "我能继续的事都已经做了。当前剩余的工作需要 1-2 小时纯人工 RE。"
        "Session 边界再次到这。你能继续的路: Ghidra GUI 手动跟 30 分钟, "
        "把字节码 dump 给我。")
    assert report["fired_count"] >= 3, report["fired_ids"]
