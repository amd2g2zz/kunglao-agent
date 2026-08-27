# -*- coding: utf-8 -*-
"""Tests for issue #451 tasks ② + ④ — enumerate -> choose negotiation.

Contract (openspec/changes/issue-451-init-negotiation design.md D3/D5):
  * A WARN-degradable missing tool (pefile/floss/die — derived from
    INSTALL_PLANS, never hand-listed) is NO LONGER auto-degraded or
    headless-refused: init enumerates local disk candidates first, then
    pends an install/use-path/skip/degrade menu through the #455 channel
    (stdout pending JSON + exit 8 + --resolve re-entry, decision id
    `install:<item>`).
  * The menu pends ONLY when it is the sole blocker: any non-negotiable
    HARD miss (VM/decompiler/android chain) keeps the #304 human-event
    refusal exit 4 (#448 HUMAN-EVENT-REFUSE → STOP) — byte-for-byte the
    existing contract.
  * --resolve answers drive real outcomes: install runs the platform plan
    + re-probe (task_spec-aware, #449 M1), use-path validates the path and
    degrades with the operator-supplied location recorded, skip keeps the
    FAIL (routes to the exit-4 human event), degrade degrades with a
    "declined via --resolve" note (an actual user choice — never a
    headless auto-decline). Malformed answers fail closed (RC_ERROR).
  * Multiple discovered VM candidates: init stops (exit 4) with the
    candidates enumerated + the OPERATOR named as the picker — never an
    auto-selection.

TDD RED phase: written BEFORE the implementation (toolchain_negotiation
does not exist yet; imports are function-level so RED is test-failure,
not collection-error).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
RC_ERROR = 1
RC_TOOLCHAIN_REFUSE = 4
RC_PENDING_DECISIONS = 8

# sys.path for scripts/ imports (pytest.ini pythonpath already covers it,
# but the function-level imports rely on it being present).
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct import)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_negotiation_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ws_with_sample(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    return ws


def _fake_registry(tmp_path: Path, servers: list[str]) -> Path:
    p = tmp_path / "fake-claude.json"
    p.write_text(json.dumps({"mcpServers": {n: {} for n in servers}}),
                 encoding="utf-8")
    return p


def _hermetic_env(monkeypatch, tmp_path: Path, registry_servers=()) -> Path:
    """Hostile env + isolated MCP registry + deterministic (empty) VM
    inventory; returns the profile root."""
    import toolchain as tc
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    monkeypatch.delenv("KUNGLAO_TOOL_DIRS", raising=False)
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON",
                       str(_fake_registry(tmp_path, list(registry_servers))))
    monkeypatch.setenv(FLAG_NAME, "0")
    monkeypatch.setattr(tc, "_vmrun_exe", lambda: None)
    monkeypatch.setattr(tc, "_vbox_exe", lambda: None)
    return tmp_path / "profile-root"


def _fail_report(*names: str, project_type: str = "windows"):
    """A report whose FAIL items are exactly `names` (HARD tier)."""
    import toolchain as tc
    items = [tc.CheckResult(name=n, status=tc.Status.FAIL,
                            tier=tc.Tier.HARD, detail=f"{n} not found")
             for n in names]
    return tc.ToolchainReport(project_type=project_type, items=items)


def _fake_check_factory(fails: list[str], calls: list | None = None):
    """toolchain.check fake returning a report FAILing exactly `fails`."""
    import toolchain as tc

    def fake_check(ws_arg, project_type=None, caps=False, task_spec=None):
        if calls is not None:
            calls.append("check")
        return _fail_report(*fails, project_type=project_type or "windows")

    return fake_check


# ---------- module surface ----------

def test_negotiable_set_derived_from_install_plans():
    """NEGOTIABLE is DERIVED (kind=auto + degrade=WARN), not hand-listed.
    #477 expanded INSTALL_PLANS 5 -> 17, so the derived set is now every
    auto+WARN item (the issue's '可自动装项全进' requirement); the
    decompiler (HARD degrade) and ida (mcp_url kind) stay excluded."""
    import toolchain_negotiation as neg
    expected = frozenset({
        "pefile", "floss", "die",
        "file", "readelf", "objdump", "docker",
        "jadx", "apktool", "gitnexus", "adb", "aapt",
        "gdbserver", "strace", "ltrace",
    })
    assert neg.NEGOTIABLE == expected
    assert "decompiler" not in neg.NEGOTIABLE
    assert "ida" not in neg.NEGOTIABLE


def test_has_non_negotiable_hard_fail():
    import toolchain as tc
    import toolchain_negotiation as neg
    assert neg.has_non_negotiable_hard_fail(_fail_report("die", "vm_reachable"))
    assert neg.has_non_negotiable_hard_fail(_fail_report("decompiler"))
    assert not neg.has_non_negotiable_hard_fail(_fail_report("die", "floss"))
    # non-FAIL / WARN items never count
    ok = tc.CheckResult(name="docker", status=tc.Status.WARN,
                        tier=tc.Tier.WARN, detail="optional")
    report = tc.ToolchainReport(project_type="windows", items=[ok])
    assert not neg.has_non_negotiable_hard_fail(report)


# ---------- disk enumeration (issue evidence 3) ----------

def test_disk_candidates_enumerates_tool_dirs(tmp_path, monkeypatch):
    """The menu SEARCHES THE DISK before asking: executables named after
    the tool under the configured tool dirs surface as use-path options."""
    import toolchain_negotiation as neg
    tools = tmp_path / "tools"
    die_dir = tools / "die"
    die_dir.mkdir(parents=True)
    exe_name = "die.exe" if os.name == "nt" else "die"
    die_exe = die_dir / exe_name
    die_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    (die_dir / "readme.txt").write_text("noise", encoding="utf-8")

    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tools))
    found = neg.disk_candidates("die")
    assert found == [str(die_exe)], found
    # unknown tool -> no candidates (fail-open, never a crash)
    assert neg.disk_candidates("nosuchtool") == []


def test_disk_candidates_defaults_and_missing_dirs(monkeypatch, tmp_path):
    """Default roots are the machine's common tool dirs; nonexistent roots
    fail open to []."""
    import toolchain_negotiation as neg
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS",
                       str(tmp_path / "definitely" / "not" / "here"))
    assert neg.disk_candidates("die") == []
    assert neg.DEFAULT_TOOL_DIRS  # non-empty default declaration


def test_disk_candidates_bounded_depth_and_count(tmp_path, monkeypatch):
    """Bounded enumeration: depth <= 2 (no whole-disk walk), hit cap
    applies, results deterministic (sorted)."""
    import toolchain_negotiation as neg
    tools = tmp_path / "tools"
    for sub in ("a", "b", "c", "d", "e"):
        d = tools / sub
        d.mkdir(parents=True)
        name = "die.exe" if os.name == "nt" else "die"
        (d / name).write_text("#!/bin/sh\n", encoding="utf-8")
    deep = tools / "a" / "x" / "y"  # depth 3 — must NOT surface
    deep.mkdir(parents=True)
    (deep / ("die.exe" if os.name == "nt" else "die")).write_text(
        "#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tools))
    found = neg.disk_candidates("die")
    assert all(str(deep) not in f for f in found)
    assert len(found) <= 4  # bounded menu — enumeration is triage, not a dump


# ---------- the menu (three-way + enumerated paths) ----------

def test_menu_decision_shape_with_disk_candidates(tmp_path, monkeypatch):
    """install:<item> pending decision: kind=choice; options carry the
    three-way install/skip/degrade PLUS one use-path per disk candidate;
    context carries the exact platform install command."""
    import toolchain_negotiation as neg
    tools = tmp_path / "tools"
    (tools / "die").mkdir(parents=True)
    die_exe = tools / "die" / ("die.exe" if os.name == "nt" else "die")
    die_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tools))

    decisions = neg.negotiation_decisions(_fail_report("die"))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.decision_id == "install:die"
    assert d.kind == "choice"
    assert d.options[0] == "install"
    assert f"use-path:{die_exe}" in d.options
    assert "skip" in d.options and "degrade" in d.options
    assert d.context["disk_candidates"] == [str(die_exe)]
    assert d.context["install_command"]  # exact platform command present
    assert d.default is None  # never a silent default


def test_menu_skips_items_with_answers():
    """Answered items do not re-pend (the --resolve re-entry loop
    terminates)."""
    import toolchain_negotiation as neg
    report = _fail_report("die", "floss")
    decisions = neg.negotiation_decisions(
        report, answers={"install:die": "degrade"})
    assert [d.decision_id for d in decisions] == ["install:floss"]


def test_menu_only_covers_negotiable_items():
    """Non-negotiable HARD misses never become menu decisions (they are
    human events, exit-4 territory)."""
    import toolchain_negotiation as neg
    decisions = neg.negotiation_decisions(_fail_report("die", "vm_reachable"))
    assert [d.decision_id for d in decisions] == ["install:die"]


# ---------- applying --resolve answers ----------

def test_apply_degrade_answer_degrades_with_user_choice_note(tmp_path):
    """'degrade' -> WARN with a note that a REAL user choice is behind it
    (never a headless auto-decline masquerading as one)."""
    import toolchain as tc
    import toolchain_negotiation as neg
    resolved = neg.apply_answers(
        _fail_report("die"), _ws_with_sample(tmp_path), "windows",
        answers={"install:die": "degrade"})
    item = next(i for i in resolved.items if i.name == "die")
    assert item.status == tc.Status.WARN
    assert item.tier == tc.Tier.HARD
    assert "declined via --resolve" in item.detail, item.detail


def test_apply_skip_answer_keeps_fail(tmp_path):
    """'skip' -> the item STAYS FAIL (the human will handle it — it routes
    to the exit-4 human-event refusal, never silently degraded)."""
    import toolchain as tc
    import toolchain_negotiation as neg
    resolved = neg.apply_answers(
        _fail_report("die"), _ws_with_sample(tmp_path), "windows",
        answers={"install:die": "skip"})
    item = next(i for i in resolved.items if i.name == "die")
    assert item.status == tc.Status.FAIL and item.tier == tc.Tier.HARD
    assert resolved.overall_status == tc.Status.FAIL


def test_apply_use_path_validates_and_records(tmp_path, monkeypatch, capsys):
    """'use-path:<p>' -> p must exist (else ValueError fail-closed); on a
    valid p the item degrades WARN with the operator-supplied location in
    the detail + PATH guidance on stderr (#474: supplied != usable)."""
    import toolchain as tc
    import toolchain_negotiation as neg
    ws = _ws_with_sample(tmp_path)
    exe = ws.parent / "die.exe"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(ValueError):
        neg.apply_answers(_fail_report("die"), ws, "windows",
                          answers={"install:die": "use-path:/no/such/die.exe"})

    resolved = neg.apply_answers(
        _fail_report("die"), ws, "windows",
        answers={"install:die": f"use-path:{exe}"})
    item = next(i for i in resolved.items if i.name == "die")
    assert item.status == tc.Status.WARN
    assert str(exe) in item.detail, item.detail
    err = capsys.readouterr().err
    assert "PATH" in err, f"guidance to surface the path must be printed: {err}"


def test_apply_install_answer_runs_plan_and_reprobes(tmp_path, monkeypatch):
    """'install' -> the platform install plan runs (consented via
    --resolve — the per-item form of --assume-yes) and a SUCCESSFUL
    install re-probes the toolchain (task_spec-aware, #449 M1)."""
    import toolchain as tc
    import toolchain_negotiation as neg
    ws = _ws_with_sample(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr("toolchain_install._run_install_plan",
                        lambda name, plan, assume_yes, ws_arg:
                        calls.append(f"install:{name}") or (0, "ok", ""))

    def fake_reprobe(ws_arg, project_type=None, caps=False, task_spec=None):
        calls.append(f"reprobe:{project_type}:{task_spec is not None}")
        return tc.ToolchainReport(project_type=project_type or "windows",
                                  items=[tc.CheckResult(
                                      name="die", status=tc.Status.PASS,
                                      tier=tc.Tier.HARD, detail="present")])

    monkeypatch.setattr("toolchain.check", fake_reprobe)
    resolved = neg.apply_answers(
        _fail_report("die"), ws, "windows",
        answers={"install:die": "install"},
        task_spec={"constraints": {"dynamic_re": "forbidden"}})
    assert calls == ["install:die", "reprobe:windows:True"], calls
    assert resolved.overall_status == tc.Status.PASS


def test_apply_install_failure_degrades_with_guidance(tmp_path, monkeypatch):
    """Install command fails -> the item degrades WARN (official guidance
    path), the run does not crash."""
    import toolchain as tc
    import toolchain_negotiation as neg
    monkeypatch.setattr("toolchain_install._run_install_plan",
                        lambda name, plan, assume_yes, ws_arg:
                        (1, "", "choco missing"))
    resolved = neg.apply_answers(
        _fail_report("die"), _ws_with_sample(tmp_path), "windows",
        answers={"install:die": "install"})
    item = next(i for i in resolved.items if i.name == "die")
    assert item.status == tc.Status.WARN, item


def test_apply_bogus_answer_fails_closed(tmp_path):
    """A malformed answer value is RC_ERROR material, never a silent
    default (#448: UNCLASSIFIED -> ASK posture; never guess)."""
    import toolchain_negotiation as neg
    with pytest.raises(ValueError):
        neg.apply_answers(_fail_report("die"), _ws_with_sample(tmp_path),
                          "windows", answers={"install:die": "maybe"})


def test_apply_bogus_answer_zero_side_effects(tmp_path, monkeypatch):
    """#451 review L-2: a malformed answer round leaves the world
    untouched — NO install executes (even the VALID sibling 'install'
    answer), NO re-probe runs, nothing is written (the workspace tree is
    unchanged), and the input report's items keep their FAIL+HARD state."""
    import toolchain as tc
    import toolchain_negotiation as neg
    ws = _ws_with_sample(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "toolchain_install._run_install_plan",
        lambda name, plan, assume_yes, ws_arg:
        calls.append(f"install:{name}") or (0, "ok", ""))
    monkeypatch.setattr(
        "toolchain.check",
        lambda *a, **k: calls.append("check") or _fail_report("die"))

    report = _fail_report("die", "floss")
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    with pytest.raises(ValueError):
        neg.apply_answers(report, ws, "windows",
                          answers={"install:die": "install",   # valid...
                                   "install:floss": "maybe"})  # bad sibling
    assert calls == [], "validation must precede every install / re-probe"
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert after == before, ("files written on a malformed round: "
                             f"{sorted(set(after) - set(before))}")
    # INSTALL state unchanged: both items stay FAIL+HARD on the input report
    for n in ("die", "floss"):
        item = next(i for i in report.items if i.name == n)
        assert item.status is tc.Status.FAIL and item.tier is tc.Tier.HARD


# ---------- kunglao-init wiring (② menu exit 8 ↔ ④ exit 4 unchanged) ----------

def test_init_die_only_missing_pends_menu_exit_8(tmp_path, monkeypatch,
                                                 capsys):
    """THE #451 acceptance case: a WARN-degradable tool missing, no
    --assume-yes, non-interactive stdin -> NOT exit 4, NOT auto-degraded:
    a structured pending list (exit 8) with the three-way menu. The
    ask-then-install path is still never entered without --assume-yes."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    calls: list[str] = []

    monkeypatch.setattr(mod.toolchain, "check", _fake_check_factory(["die"]))
    monkeypatch.setattr(
        mod.toolchain_install, "ask_then_install",
        lambda *a, **k: calls.append("ask") or a[0])

    rc = mod.run(ws, project_type="windows", profile_root=profile_root)
    out = capsys.readouterr().out
    assert rc == RC_PENDING_DECISIONS, f"die-only miss must pend: {rc}: {out}"
    assert calls == [], "ask_then_install must not run without --assume-yes"
    doc = json.loads(out)
    assert doc["flow"] == "kunglao-init"
    assert [d["decision_id"] for d in doc["decisions"]] == ["install:die"]
    opts = doc["decisions"][0]["options"]
    assert opts[0] == "install" and "skip" in opts and "degrade" in opts
    assert not (ws / "claim-register.yaml").exists(), "zero scaffold on pend"


def test_init_resolve_degrade_answer_proceeds_to_scaffold(
        tmp_path, monkeypatch, capsys):
    """--resolve {'install:die': 'degrade'} on re-entry -> item degraded,
    no FAIL remains -> init proceeds (exit 0, scaffold written)."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    monkeypatch.setattr(mod.toolchain, "check", _fake_check_factory(["die"]))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root,
                 answers={"install:die": "degrade"})
    assert rc == 0, f"degraded report must proceed: {rc}: {capsys}"
    assert (ws / "claim-register.yaml").exists(), "scaffold after degrade"
    assert "[initialized]" in (ws / "claim-register.yaml").read_text(
        encoding="utf-8")


def test_init_resolve_install_answer_installs_and_proceeds(
        tmp_path, monkeypatch):
    """--resolve {'install:die': 'install'} -> the install plan runs (fake
    success) -> re-probe PASS -> init proceeds (exit 0)."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    import toolchain as tc

    state = {"check_calls": 0}

    def check_then_pass(ws_arg, project_type=None, caps=False, task_spec=None):
        state["check_calls"] += 1
        if state["check_calls"] == 1:
            return _fail_report("die", project_type=project_type or "windows")
        return tc.ToolchainReport(
            project_type=project_type or "windows",
            items=[tc.CheckResult(name="die", status=tc.Status.PASS,
                                  tier=tc.Tier.HARD, detail="present")])

    monkeypatch.setattr(mod.toolchain, "check", check_then_pass)
    monkeypatch.setattr("toolchain_install._run_install_plan",
                        lambda name, plan, assume_yes, ws_arg: (0, "ok", ""))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root,
                 answers={"install:die": "install"})
    assert rc == 0, "install-then-pass must proceed to scaffold"
    assert (ws / "claim-register.yaml").exists()


def test_init_mixed_missing_keeps_exit_4(tmp_path, monkeypatch, capsys):
    """④ constitution: a negotiable miss PLUS a non-negotiable HARD miss
    (VM) -> the #304 human-event refusal exit 4 fires FIRST (menu deferred
    to the round after the human fixes the HARD item)."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    monkeypatch.setattr(mod.toolchain, "check",
                        _fake_check_factory(["die", "vm_reachable"]))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root)
    err = capsys.readouterr().err
    assert rc == RC_TOOLCHAIN_REFUSE, f"mixed miss must refuse: {rc}: {err}"
    assert "[FAIL] vm_reachable" in err
    assert not (ws / "claim-register.yaml").exists()


def test_init_resolve_skip_routes_to_human_event(tmp_path, monkeypatch):
    """--resolve 'skip' keeps the item FAIL -> the residual human-event
    refusal (exit 4) carries it (skip = the human takes over)."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    monkeypatch.setattr(mod.toolchain, "check", _fake_check_factory(["die"]))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root,
                 answers={"install:die": "skip"})
    assert rc == RC_TOOLCHAIN_REFUSE, "skip must route to the exit-4 refusal"
    assert not (ws / "claim-register.yaml").exists()


def test_init_bogus_resolve_answer_rc_error(tmp_path, monkeypatch, capsys):
    """Malformed --resolve negotiation answer -> RC_ERROR with a clear
    stderr message (fail-closed, mirrors the intake malformed-answer
    contract) and ZERO scaffold (nothing is written on a bad round)."""
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    monkeypatch.setattr(mod.toolchain, "check", _fake_check_factory(["die"]))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root,
                 answers={"install:die": "maybe"})
    assert rc == RC_ERROR
    assert "install:die" in capsys.readouterr().err
    assert not (ws / "claim-register.yaml").exists(), "zero scaffold on RC_ERROR"
    assert not (ws / "analysis_state.txt").exists(), "zero state on RC_ERROR"


def test_init_vm_multi_candidate_stops_for_operator_choice(
        tmp_path, monkeypatch, capsys):
    """Issue acceptance '多候选时 init 停止等用户选择': multiple discovered
        VMs -> init STOPS (exit 4, zero scaffold) with the candidates
        enumerated + structured options + the OPERATOR named as the picker;
        the environment variable is never auto-set, a candidate is never
        auto-selected. Uses the REAL check so the dynamic inventory-driven
        next_action rides into the refusal output end-to-end."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    profile_root = _hermetic_env(monkeypatch, tmp_path)
    mod = _load_init_module()
    entries = [
        tc.VMInventoryEntry(name="work_env",
                            vmx=str(tmp_path / "vms" / "work_env.vmx"),
                            running=False, snapshots=["base"]),
        tc.VMInventoryEntry(name="Windows 10 x64",
                            vmx=str(tmp_path / "vms" / "win10.vmx"),
                            running=False, snapshots=["hr-6.0"]),
    ]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    rc = mod.run(ws, project_type="windows", profile_root=profile_root)
    err = capsys.readouterr().err
    assert rc == RC_TOOLCHAIN_REFUSE, f"multi-candidate VM must refuse: {err}"
    assert "[FAIL] vm_reachable" in err
    assert "1. work_env" in err and "2. Windows 10 x64" in err, err
    assert "OPERATOR" in err and "never auto-select" in err, err
    assert "action: vm-enumerate" in err, err
    assert "option 1: work_env" in err and "option 2: Windows 10 x64" in err
    assert not (ws / "claim-register.yaml").exists()
    assert os.environ.get("KUNGLAO_VM_HOST") in (None, ""), \
        "init must never auto-set KUNGLAO_VM_HOST"
