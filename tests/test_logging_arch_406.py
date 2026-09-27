# -*- coding: utf-8 -*-
"""tests/test_logging_arch_406.py — the logging-architecture batch
(v0.1.6): the warn() centralization + ledger persistence + day-file
retention + named-op contracts, pinned failing-first per the maker dispatch.

Contracts pinned here:
  1. warn() has ONE implementation (scripts/kunglao_log.py); migrated
     modules import it — no module-level `def warn` copies and no private
     `_WARN_LAST` dicts remain outside the documented skip set
     (kunglao_log = the host, _boot = the issue-292-blessed boot-scoped copy,
     _scriptlib = the make_warn factory, and the init/toolchain files
     owned by the parallel maker).
  2. Dedupe is PROCESS-WIDE per (op, last-reason): two different modules
     warning the same (op, reason) in one process now collapse to one
     stderr line — the documented semantics change.
  3. warn() ALSO persists a ledger row (action=warn, actor=telemetry) via
     the emit face when a workspace is resolvable (explicit registration
     or cwd walk-up marker), one row per dedupe window — the stderr print
     stays. kunglao_log never raises on this path.
  4. The emit-failure face is self-dogfooded (warn, not a raw print) and
     cannot recurse (the ledger face is re-entrancy guarded).
  5. Day-file retention: emit prunes kunglao-<date>.jsonl day files beyond
     LOG_DAY_RETENTION (newest kept), never touches foreign files,
     fail-open.
  6. Named ops: heartbeat_touch / recall_inject / kunglao_log CLI carry
     dotted, operation-descriptive warn ops — no `main`/`_trace`-shape
     opaque names.
  7. Raw stderr WARN prints are standardized onto warn() outside the
     parallel-maker-owned files (ratchet scan).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import kunglao_log as kl  # noqa: E402

#: files allowed to keep a module-level warn implementation / state, with
#: the reason each skip exists (the logging-arch batch dispatch + issue 292 guard).
WARN_DEF_ALLOWED = {
    "scripts/kunglao_log.py",     # the canonical host
    "scripts/_boot.py",           # boot-scoped copy: dependency-free import
                                  # order rule (issue 292 guard blessing)
    "scripts/_scriptlib.py",      # make_warn factory (warn is nested)
    "scripts/heartbeat_tick.py",  # parallel maker owns (init/tick batch)
    "scripts/kunglao-init.py",    # parallel maker owns
    "scripts/kunglao_upgrade.py",  # parallel maker owns
    "scripts/toolchain_install.py",  # parallel maker owns
}

#: raw stderr WARN prints allowed to remain (same ownership skip set).
RAW_WARN_ALLOWED = {
    "scripts/kunglao-init.py",
    "scripts/toolchain.py",
    "scripts/toolchain_install.py",
    "scripts/toolchain_negotiation.py",
    "scripts/kunglao_upgrade.py",
    # devkit tool with no scripts/ import surface (importlib-based loader);
    # owned by the parallel hygiene batch — lands with their sweep.
    "devkit/quality_gates.py",
}


@pytest.fixture(autouse=True)
def _fresh_warn_state(monkeypatch):
    """Fresh canonical dedupe state per test: warn assertions here are
    per-test and order-independent."""
    monkeypatch.setattr(kl, "_WARN_LAST", {}, raising=False)
    yield


@pytest.fixture
def warn_ws(tmp_path, monkeypatch):
    """A workspace registered for the warn ledger face."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    monkeypatch.setattr(kl, "_WARN_WS_OVERRIDE", [ws], raising=False)
    return ws


def _warn_rows(ws: Path) -> list[dict]:
    out = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return [r for r in out if r.get("action") == "warn"]


# ----------------------------------------------------- 1. one implementation

def test_no_module_level_warn_copies_outside_the_skip_set():
    """The centralization ratchet: only the documented files still define
    warn at module level; every migrated module imports the canonical one."""
    offenders = []
    for base in (SCRIPTS, HOOKS):
        for p in sorted(base.glob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            has_def = any(isinstance(n, ast.FunctionDef) and n.name == "warn"
                          for n in tree.body)
            has_state = any(
                isinstance(n, (ast.Assign, ast.AnnAssign))
                and any(isinstance(t, ast.Name) and t.id in
                        ("_WARN_LAST", "_B3_WARN_LAST")
                        for t in ([n.target] if isinstance(n, ast.AnnAssign)
                                  else n.targets))
                for n in tree.body)
            rel = p.relative_to(ROOT).as_posix()
            if (has_def or has_state) and rel not in WARN_DEF_ALLOWED:
                offenders.append(rel)
    assert not offenders, (
        f"module-level warn copies outside the skip set: {offenders}")


def test_migrated_modules_expose_the_canonical_warn():
    """Spot-pins: migrated modules' `warn` IS kunglao_log.warn (same
    function object) — one implementation, not a re-binding wrapper."""
    import mechanism_scheduler as ms
    import statusline_snapshot as sls
    assert ms.warn is kl.warn
    assert sls.warn is kl.warn


def test_no_import_cycle_kunglao_log_stays_leaf():
    """kunglao_log must not import any migrated module (import-cycle
    guard): a fresh subprocess import pulls in none of them."""
    import subprocess
    code = (
        "import sys; import kunglao_log; "
        "banned = ('mechanism_scheduler', 'statusline_snapshot', "
        "'rollup', 'convergence_check', 'heartbeat_touch', "
        "'worker_budget_sinks', 'harness_common_ban_placeholder'); "
        "leaked = [m for m in banned if m in sys.modules]; "
        "assert not leaked, leaked; print('ok')"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(SCRIPTS),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# ------------------------------------------------ 2. process-wide dedupe

def test_dedupe_is_process_wide_across_modules(capsys):
    """THE documented semantics change: two modules warning the same
    (op, reason) in one process collapse to ONE stderr line."""
    import mechanism_scheduler as ms
    kl.warn("shared_op_406", "same reason")
    ms.warn("shared_op_406", "same reason")
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if "WARN (fail-open)" in ln]
    assert len(lines) == 1, lines


def test_dedupe_refires_when_reason_changes(capsys):
    kl.warn("op", "r1")
    kl.warn("op", "r1")
    kl.warn("op", "r2")
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if "WARN (fail-open)" in ln]
    assert len(lines) == 2


def test_stderr_message_carries_caller_module_tag(tmp_path, capsys):
    """The console face keeps the module token the old per-module copies
    printed, derived from the caller's file — diagnosability preserved."""
    import mechanism_scheduler as ms
    blocked = tmp_path / "blocker"
    blocked.write_text("not a directory", encoding="utf-8")
    ms._write_state(blocked / "ws", {})
    err = capsys.readouterr().err
    assert "[kunglao-agent] mechanism_scheduler WARN (fail-open): " in err


# ------------------------------------------------- 3. ledger persistence

def test_warn_persists_one_ledger_row_per_dedupe_window(warn_ws, capsys):
    kl.warn("ledger_op", "boom")
    kl.warn("ledger_op", "boom")   # deduped: no second row, no second print
    kl.warn("ledger_op", "boom2")  # changed reason: new window
    rows = _warn_rows(warn_ws)
    assert len(rows) == 2, rows
    assert rows[0]["detail"].endswith("ledger_op: boom")
    assert rows[0]["actor"] == "telemetry"
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if "WARN (fail-open)" in ln]
    assert len(lines) == 2, "console face must stay"


def test_warn_without_workspace_is_stderr_only(tmp_path, monkeypatch, capsys):
    """No registered ws + no discoverable marker: stderr only, never a
    stray ledger file, never a raise."""
    empty = tmp_path / "noworkspace"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(kl, "_WARN_WS_OVERRIDE", [], raising=False)
    kl.warn("orphan_op", "x")
    assert capsys.readouterr().err != ""
    assert not (empty / "runs").exists()


def test_warn_ledger_row_joins_the_schema(warn_ws):
    """The row is a normal emit row: trace/epoch inheritance and the
    stable-schema null keys all apply (it IS an emit row, not a sidecar)."""
    kl.warn("schema_op", "r")
    (row,) = _warn_rows(warn_ws)
    for key in ("ts", "actor", "action", "detail", "null_reasons",
                "trace_id", "epoch"):
        assert key in row, row


# --------------------------------------------------- 4. self-dogfood face

def test_emit_failure_self_dogfoods_warn_and_cannot_recurse(
        tmp_path, capsys, monkeypatch):
    """runs/logs exists as a FILE -> every write fails: emit returns False,
    the failure surfaces through the standardized warn face (once per
    dedupe window), and the ledger face's re-entrancy guard stops the
    warn->emit->warn cycle."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    ws = blocker / "ws"
    monkeypatch.setattr(kl, "_WARN_WS_OVERRIDE", [], raising=False)
    for _ in range(3):
        assert kl.emit(ws, "orchestrator", "tool_call") is False
    err = capsys.readouterr().err
    assert "WARN (fail-open)" in err
    assert "cannot write" in err
    # dedupe collapsed the three failures into one warn line
    lines = [ln for ln in err.splitlines() if "WARN (fail-open)" in ln]
    assert len(lines) == 1, lines


def test_lifecycle_unknown_phase_dogfoods_warn(tmp_path, capsys):
    kl.emit_lifecycle(tmp_path / "ws", "orchestrator", "not-a-phase")
    err = capsys.readouterr().err
    assert "WARN (fail-open)" in err
    assert "unknown lifecycle phase" in err


# ---------------------------------------------------- 5. retention / cap

def _seed_day_files(ws: Path, days: int) -> None:
    d = ws / "runs" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(days):
        (d / f"kunglao-2026-08-{i:02d}.jsonl").write_text("{}\n",
                                                          encoding="utf-8")


def test_retention_constant_is_declared_with_headroom():
    """The cap is a named constant, sane, and documented."""
    assert kl.LOG_DAY_RETENTION == 30
    src = (SCRIPTS / "kunglao_log.py").read_text(encoding="utf-8")
    assert "LOG_DAY_RETENTION" in src


def test_emit_prunes_old_day_files(tmp_path):
    ws = tmp_path / "ws"
    _seed_day_files(ws, kl.LOG_DAY_RETENTION + 5)
    kl._PRUNED_DAY.clear()
    assert kl.emit(ws, "orchestrator", "tool_call") is True
    logs = ws / "runs" / "logs"
    day_files = sorted(logs.glob("kunglao-*.jsonl"))
    assert len(day_files) == kl.LOG_DAY_RETENTION
    # the newest seeded file survives; the 5 oldest are gone
    assert (logs / "kunglao-2026-08-34.jsonl").exists()
    assert not (logs / "kunglao-2026-08-00.jsonl").exists()


def test_prune_never_touches_foreign_files(tmp_path):
    ws = tmp_path / "ws"
    _seed_day_files(ws, 3)
    logs = ws / "runs" / "logs"
    foreign = logs / "kunglao_init-2026-08-01.log"
    foreign.write_text("x\n", encoding="utf-8")
    other = logs / "init-2026-08-01.log"
    other.write_text("x\n", encoding="utf-8")
    kl._PRUNED_DAY.clear()
    kl.emit(ws, "orchestrator", "tool_call")
    assert foreign.exists() and other.exists()


def test_prune_fail_open(tmp_path, monkeypatch):
    """Unlink failure never breaks emit (warn + continue posture)."""
    ws = tmp_path / "ws"
    _seed_day_files(ws, kl.LOG_DAY_RETENTION + 2)
    real_unlink = Path.unlink

    def _boom(self, *a, **k):
        raise OSError("denied")

    monkeypatch.setattr(Path, "unlink", _boom)
    kl._PRUNED_DAY.clear()
    assert kl.emit(ws, "orchestrator", "tool_call") is True
    assert real_unlink  # keep the reference alive for linters
    monkeypatch.undo()


def test_prune_day_logs_direct_api(tmp_path):
    ws = tmp_path / "ws"
    _seed_day_files(ws, 40)
    removed = kl.prune_day_logs(ws, keep=30)
    assert removed == 10
    assert len(list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))) == 30


# ------------------------------------------------------- 6. named ops

def _warn_op_literals(rel: str) -> set[str]:
    src = (HOOKS / rel).read_text(encoding="utf-8")
    return set(re.findall(r'warn\(\s*"([^"]+)"', src)) if (
        re := __import__("re")) else set()


def test_heartbeat_touch_ops_are_named():
    ops = _warn_op_literals("heartbeat_touch.py")
    assert ops, "heartbeat_touch must still call warn"
    for op in ops:
        assert op.startswith("heartbeat_touch."), op
    assert not ({"main", "main_2", "_write_statusline_snapshot",
                 "_write_statusline_snapshot_2",
                 "_write_statusline_snapshot_3"} & ops)


def test_recall_inject_ops_are_named():
    """Scope: the audit's opaque `_trace`/`_trace_2` ops become named;
    recall_inject's other ops were already operation-descriptive."""
    ops = _warn_op_literals("recall_inject.py")
    assert {"recall_inject.trace_emit", "recall_inject.trace_metrics"} <= ops
    for op in ops:
        assert not op.startswith("_"), op
        assert op != "main", op


def test_kunglao_log_cli_ops_are_named():
    src = (SCRIPTS / "kunglao_log.py").read_text(encoding="utf-8")
    ops = set(__import__("re").findall(r'warn\(\s*"([^"]+)"', src))
    assert not ({"main", "main_2"} & ops), ops


# -------------------------------------------- 7. raw WARN standardization

def test_no_raw_stderr_warn_prints_outside_the_skip_set():
    """The ratchet: every stderr print whose text carries warn/warning is
    migrated onto the canonical warn() — except the parallel-maker-owned
    files (init/toolchain batch lands their migration separately)."""
    offenders = []
    for base in (SCRIPTS, HOOKS, ROOT / "devkit"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not any(
                        isinstance(k.value, ast.Attribute)
                        and k.value.attr == "stderr"
                        for k in node.keywords):
                    continue
                text = ast.unparse(node)
                if "warn" not in text.lower():
                    continue
                if "fail-open" in text.lower():
                    continue
                rel = p.relative_to(ROOT).as_posix()
                if rel in RAW_WARN_ALLOWED:
                    continue
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"raw stderr WARN prints remain: {offenders}"


def test_raw_warn_content_survives_the_migration(capsys):
    """Spot-pin: a migrated face keeps its message content (deploy_shim's
    installed-ledger write failure)."""
    import deploy_shim
    deploy_shim.warn("installed_ledger_write",
                     "deploy-shim: WARNING installed-ledger write failed (x)")
    err = capsys.readouterr().err
    assert "installed-ledger write failed" in err
    assert "WARN (fail-open)" in err
