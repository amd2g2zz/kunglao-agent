# -*- coding: utf-8 -*-
"""Tests for #700 — assembly history (v0.1.3 closure batch).

Two arbitrated gaps (the original jsonl proposal was superseded by #534's
report — see openspec/changes/issue-700-assembly-history/proposal.md):

1. init-report archive rotation: runs/.init-report.json is overwritten on
   every init (#534 docstring: "Idempotent: overwrites any prior report")
   — a failed cycle destroys the previous cycle's telemetry. Rotation
   archives the prior report to runs/.init-report.{n}.json (n = max+1)
   before the fresh write, pruned to KUNGLAO_INIT_REPORT_KEEP (default 5).
2. per-item install events: ask_then_install's consent/install/degrade
   transitions were invisible to the runs/logs/kunglao-*.jsonl timeline —
   three EMIT_ACTIONS words (install_attempt / install_declined /
   install_failed) answer "which tool was attempted when" reusing the
   existing tool/detail kwargs (no new schema).

TDD RED phase: these fail before the scripts/kunglao-init.py rotation
helper and the scripts/toolchain_install.py emit call sites land.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import event_taxonomy
import kunglao_log
import toolchain as tc
import toolchain_install as ti

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

DEFAULT_KEEP = 5
KEEP_ENV = "KUNGLAO_INIT_REPORT_KEEP"
ACTOR = "toolchain_install"
_ARCHIVE_RE = re.compile(r"\.init-report\.(\d+)\.json$")


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen blocks direct import)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_700_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(*fails: str) -> tc.ToolchainReport:
    """HARD-tier report with the named items failing
    (tests/test_toolchain_install.py fixture pattern)."""
    items = []
    for name in ("pefile", "die", "floss", "decompiler", "ida"):
        status = tc.Status.FAIL if name in fails else tc.Status.PASS
        items.append(tc.CheckResult(name=name, status=status, tier=tc.Tier.HARD,
                                    detail="probe detail"))
    return tc.ToolchainReport(project_type="windows", items=items)


def _seed_reports(runs: Path, current: str, archives: int) -> None:
    """Pre-place the live report plus `archives` numbered siblings."""
    (runs / ".init-report.json").write_text(current, encoding="utf-8")
    for n in range(1, archives + 1):
        (runs / f".init-report.{n}.json").write_text(f'{{"seed": "{n}"}}',
                                                     encoding="utf-8")


def _archive_names(runs: Path) -> list[str]:
    """Numeric archive names, sorted numerically (non-numeric excluded)."""
    numbered = []
    for p in runs.iterdir():
        m = _ARCHIVE_RE.fullmatch(p.name)
        if m:
            numbered.append((int(m.group(1)), p.name))
    return [name for _, name in sorted(numbered)]


def _never_installed(name, plan, assume_yes, ws):
    raise AssertionError("this branch must never run an install")


# ---------- init-report archive rotation (write_init_report) ----------

def test_second_write_archives_prior_report(tmp_path, capsys):
    """2.1: a fresh write_init_report moves the prior report to
    runs/.init-report.1.json (content preserved) and announces exactly
    one archive line on stderr."""
    mod = _load_init_module()
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    first = mod.write_init_report(ws, phases=[{"name": "scaffold"}],
                                  overall="FAIL", exit_code=4)
    prior = json.loads(first.read_text(encoding="utf-8"))
    capsys.readouterr()  # discard the first write's stream

    second = mod.write_init_report(ws, phases=[], overall="PASS", exit_code=0)
    assert second == ws / "runs" / ".init-report.json"
    assert json.loads(second.read_text(encoding="utf-8"))["overall"] == "PASS"
    archive = ws / "runs" / ".init-report.1.json"
    assert archive.exists(), "prior report must be archived, not destroyed"
    assert json.loads(archive.read_text(encoding="utf-8")) == prior
    err = capsys.readouterr().err
    announced = [line for line in err.splitlines()
                 if "archiv" in line.lower() and ".init-report." in line]
    assert len(announced) == 1, err


def test_rotation_prunes_to_default_keep(tmp_path, monkeypatch):
    """2.2: rotation bounds archives to KEEP (default 5), deleting oldest
    first; non-numeric siblings are never counted, never deleted."""
    mod = _load_init_module()
    monkeypatch.delenv(KEEP_ENV, raising=False)
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    _seed_reports(runs, '{"seed": "current"}', DEFAULT_KEEP)
    stray = runs / ".init-report.abc.json"  # non-numeric sibling: untouched
    stray.write_text("user file", encoding="utf-8")

    mod.write_init_report(ws, phases=[], overall="PASS", exit_code=0)

    assert _archive_names(runs) == [
        f".init-report.{n}.json" for n in range(2, DEFAULT_KEEP + 2)], \
        _archive_names(runs)
    assert json.loads((runs / ".init-report.6.json").read_text(
        encoding="utf-8"))["seed"] == "current"
    assert stray.read_text(encoding="utf-8") == "user file"


def test_keep_env_override_and_invalid_fallback(tmp_path, monkeypatch):
    """2.3: KUNGLAO_INIT_REPORT_KEEP=2 keeps 2 newest; 'abc' / '0' fall
    back to the default (a mistyped env var must not break rotation)."""
    mod = _load_init_module()

    monkeypatch.setenv(KEEP_ENV, "2")
    runs = tmp_path / "keep2" / "runs"
    runs.mkdir(parents=True)
    _seed_reports(runs, '{"seed": "current"}', DEFAULT_KEEP)
    mod.write_init_report(runs.parent, phases=[], overall="PASS", exit_code=0)
    assert _archive_names(runs) == [".init-report.5.json",
                                    ".init-report.6.json"], \
        _archive_names(runs)

    for bad in ("abc", "0"):
        monkeypatch.setenv(KEEP_ENV, bad)
        runs = tmp_path / f"bad-{bad}" / "runs"
        runs.mkdir(parents=True)
        _seed_reports(runs, '{"seed": "current"}', DEFAULT_KEEP)
        mod.write_init_report(runs.parent, phases=[], overall="PASS",
                              exit_code=0)
        assert _archive_names(runs) == [
            f".init-report.{n}.json" for n in range(2, DEFAULT_KEEP + 2)], \
            f"KEEP={bad!r} must fall back to {DEFAULT_KEEP}: " \
            f"{_archive_names(runs)}"


def test_archive_failure_never_breaks_write(tmp_path, monkeypatch):
    """2.4: history rotation must not break init — when the archive step
    raises (I/O error, pathological sibling), the fresh report is still
    written and the target path returned (spec: rotation never breaks)."""
    mod = _load_init_module()
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / ".init-report.json").write_text('{"seed": "prior"}',
                                            encoding="utf-8")

    def boom(target):
        raise OSError("simulated archive I/O failure")

    monkeypatch.setattr(mod, "archive_previous_init_report", boom)
    out = mod.write_init_report(ws, phases=[], overall="PASS", exit_code=0)
    assert out == ws / "runs" / ".init-report.json"
    assert json.loads(out.read_text(encoding="utf-8"))["overall"] == "PASS"


# ---------- per-item install events (ask_then_install → kunglao_log) ----------

def _read_events(ws: Path) -> list[dict]:
    p = kunglao_log.log_path(ws)
    assert p.exists(), f"no kunglao_log event stream at {p}"
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines()]


def _quiet_reprobe(monkeypatch):
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type:
                        tc.ToolchainReport(project_type=project_type,
                                           items=[]))


def test_install_attempt_and_failed_events(tmp_path, monkeypatch):
    """2.5: a consented install that fails leaves install_attempt then
    install_failed on the day's timeline with tool=<item>; the failed
    detail is the head of the error (first line, 120-char cap)."""
    long_line = "brew failed: " + "z" * 300
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws:
                        (1, long_line + "\nsecond line", ""))
    _quiet_reprobe(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    r = ti.ask_then_install(_report("die"), ws=ws, project_type="windows",
                            assume_yes=True)

    item = next(i for i in r.items if i.name == "die")
    assert item.status == tc.Status.WARN, item  # loop still degrades
    rows = _read_events(ws)
    actions = [(row["action"], row.get("tool")) for row in rows]
    assert ("install_attempt", "die") in actions, actions
    assert ("install_failed", "die") in actions, actions
    assert actions.index(("install_attempt", "die")) < \
        actions.index(("install_failed", "die")), actions
    attempt = next(row for row in rows if row["action"] == "install_attempt")
    assert attempt["actor"] == ACTOR
    assert attempt["detail"] == f"via {ti.INSTALL_PLANS['die'].kind}"
    failed = next(row for row in rows if row["action"] == "install_failed")
    assert failed["detail"] == long_line[:120], failed["detail"]
    assert "second line" not in failed["detail"]


def test_install_declined_event_on_no_consent(tmp_path, monkeypatch):
    """2.6: the headless no-consent degrade emits install_declined (with a
    reason) — and never an install_attempt (nothing was attempted)."""
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws: (1, "", "unreached"))
    _quiet_reprobe(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    ti.ask_then_install(_report("pefile"), ws=ws, project_type="windows",
                        assume_yes=False)

    rows = _read_events(ws)
    declined = [row for row in rows if row["action"] == "install_declined"]
    assert declined, rows
    assert declined[0]["tool"] == "pefile"
    assert declined[0]["actor"] == ACTOR
    assert declined[0]["detail"], "decline reason required (spec: 'a reason')"
    assert not any(row["action"] == "install_attempt" for row in rows)


def test_install_declined_event_on_ida_mcp_url(tmp_path, monkeypatch):
    """2.7: the IDA mcp_url non-auto-installable degrade emits
    install_declined too — both no-real-choice paths are visible."""
    monkeypatch.setattr(ti, "_run_install_plan", _never_installed)
    _quiet_reprobe(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    ti.ask_then_install(_report("ida"), ws=ws, project_type="windows",
                        assume_yes=True)

    rows = _read_events(ws)
    declined = [row for row in rows
                if row["action"] == "install_declined" and row["tool"] == "ida"]
    assert declined, rows
    assert declined[0]["detail"]


def test_emit_failure_never_breaks_install_loop(tmp_path, monkeypatch):
    """2.8 (D4): observability is fail-open at the call site — a broken
    emit channel must not abort the install loop (the item still
    degrades), and the loop must actually route its events through it."""
    emitted: list[tuple] = []

    def broken_emit(*args, **kwargs):
        emitted.append(args)
        raise RuntimeError("log channel broken")

    monkeypatch.setattr(kunglao_log, "emit", broken_emit)
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws: (1, "out", "err"))
    _quiet_reprobe(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    r = ti.ask_then_install(_report("die"), ws=ws, project_type="windows",
                            assume_yes=True)

    item = next(i for i in r.items if i.name == "die")
    assert item.status == tc.Status.WARN, item  # loop completed
    assert emitted, "the loop must route its events through kunglao_log.emit"


# ---------- taxonomy registration (spec Constraint) ----------

def test_install_event_words_registered():
    """The three words ship in EMIT_ACTIONS (sorted, unique) BEFORE any
    call site — unregistered emit words are red per #459."""
    for word in ("install_attempt", "install_declined", "install_failed"):
        assert word in event_taxonomy.EMIT_ACTIONS, word
    assert event_taxonomy.EMIT_ACTIONS == sorted(
        set(event_taxonomy.EMIT_ACTIONS))
