# -*- coding: utf-8 -*-
"""tests/test_toolchain_apkid_209.py — android init surfaces the apkid probe.

Contract (issue 209, owner rulings):
- apkid is a TOOL, not source: init probes PRESENCE only and never executes
  scripts/apkid_scanner.py — the agent decides whether/when to run it at
  first claim.
- _check_android emits exactly one apkid item, WARN tier, so it can never
  enter the HARD exit-4 refusal set (refuse_toolchain filters tier==HARD).
- the item detail carries the first-claim recommendation verbatim, and the
  kunglao-init post-toolchain summary mirrors it when the project is
  android and the probe is not PASS.
- windows / linux reports stay slim: no apkid item at all.

Everything is monkeypatched (_shutil_which / _run_cmd): no PATH dependence,
no real tool execution, no reads of the developer's ~/.claude.json.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

import toolchain as tc  # noqa: E402  (pytest.ini pythonpath = scripts)

PHRASE = ("apkid recommended for apk fingerprinting "
          "(packer / obfuscator / anti-*); agent to run on first claim")

_INIT_MOD = None


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen blocks direct import)."""
    global _INIT_MOD
    if _INIT_MOD is None:
        spec = importlib.util.spec_from_file_location(
            "kunglao_init_apkid_209", SCRIPTS / "kunglao-init.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _INIT_MOD = mod
    return _INIT_MOD


@pytest.fixture
def hermetic_env(monkeypatch, tmp_path):
    """Stub the probe execution surface; pin the MCP registry to a tmp file."""
    fake = tmp_path / "fake-claude.json"
    fake.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    monkeypatch.setattr(tc, "_run_cmd",
                        lambda args, timeout=10: (0, "stub 1.0", ""))


def _stub_which(monkeypatch, found: tuple[str, ...] = ()) -> None:
    def _which(name: str):
        return f"/stub-bin/{name}" if name in found else None
    monkeypatch.setattr(tc, "_shutil_which", _which)


def _android_report(tmp_path: Path) -> tc.ToolchainReport:
    report = tc.ToolchainReport(project_type="android")
    tc._check_android(report, tmp_path)
    return report


def _warn_item(name: str, status: tc.Status) -> tc.CheckResult:
    return tc.CheckResult(name=name, status=status, tier=tc.Tier.WARN,
                          detail="stub detail")


# ---------- android report carries the apkid probe item ----------

def test_android_report_carries_apkid_warn_item(hermetic_env, monkeypatch,
                                                tmp_path):
    _stub_which(monkeypatch)  # apkid absent from the stubbed PATH
    report = _android_report(tmp_path)
    apkid = [i for i in report.items if i.name == "apkid"]
    assert len(apkid) == 1, "android report must carry exactly one apkid item"
    item = apkid[0]
    assert item.tier == tc.Tier.WARN, item
    assert item.status == tc.Status.WARN, item
    assert PHRASE in item.detail, item


def test_android_apkid_found_passes_with_recommendation(hermetic_env,
                                                        monkeypatch, tmp_path):
    _stub_which(monkeypatch, found=("apkid",))
    report = _android_report(tmp_path)
    item = next((i for i in report.items if i.name == "apkid"), None)
    assert item is not None
    assert item.status == tc.Status.PASS, item
    assert item.tier == tc.Tier.WARN, item
    assert PHRASE in item.detail, item


def test_apkid_item_never_in_hard_refusal_set(hermetic_env, monkeypatch,
                                              tmp_path):
    """Mirror refuse_toolchain's HARD set: apkid must stay out of it in both
    probe states — the WARN tier is exactly what keeps init from exit 4."""
    for found in ((), ("apkid",)):
        _stub_which(monkeypatch, found=found)
        report = _android_report(tmp_path)
        apkid = next((i for i in report.items if i.name == "apkid"), None)
        assert apkid is not None, found
        hard_refusals = [i for i in report.items
                         if i.status == tc.Status.FAIL
                         and i.tier == tc.Tier.HARD]
        assert apkid not in hard_refusals, (found, apkid)


def test_windows_and_linux_reports_stay_slim(hermetic_env, monkeypatch,
                                             tmp_path):
    _stub_which(monkeypatch)  # nothing on PATH
    for checker, ptype in ((tc._check_windows, "windows"),
                           (tc._check_linux, "linux")):
        report = tc.ToolchainReport(project_type=ptype)
        checker(report, tmp_path)
        assert [i for i in report.items if i.name == "apkid"] == [], ptype


# ---------- kunglao-init post-toolchain summary face ----------

def test_init_summary_prints_recommendation_on_android_warn():
    mod = _load_init_module()
    report = tc.ToolchainReport(project_type="android",
                                items=[_warn_item("apkid", tc.Status.WARN)])
    lines = mod.apkid_summary_lines(report)
    assert len(lines) == 1, lines
    assert PHRASE in lines[0], lines


def test_init_summary_silent_when_pass_or_absent():
    mod = _load_init_module()
    passed = tc.ToolchainReport(
        project_type="android", items=[_warn_item("apkid", tc.Status.PASS)])
    assert mod.apkid_summary_lines(passed) == []
    assert mod.apkid_summary_lines(
        tc.ToolchainReport(project_type="android", items=[])) == []


def test_init_summary_silent_off_android():
    mod = _load_init_module()
    for ptype in ("windows", "linux", "web", "macos"):
        report = tc.ToolchainReport(
            project_type=ptype, items=[_warn_item("apkid", tc.Status.WARN)])
        assert mod.apkid_summary_lines(report) == [], ptype


def test_init_main_wires_the_summary_face():
    """Wiring pin: the toolchain gate (init run()) must actually call the
    summary face — a helper nobody calls would pass every pure-function
    test above."""
    mod = _load_init_module()
    assert "apkid_summary_lines(report)" in inspect.getsource(mod.run)
