# -*- coding: utf-8 -*-
"""Issue 210 — the decompiler face is XOR, not AND.

The owner-confirmed symptom: the decompiler face BEHAVED as an XOR
(`_probe_local_ida()` early-returns, Ghidra runs only on an IDA miss) but
was WIRED as an AND — three independent registry entries
(`decompiler` / `ghidra` / `ida`), no SKIPPED semantics, and a satisfied
lane still walked the loser as a missing item ("install ghidra") in the
fix-string registry.

Contract pinned here (issue acceptance):
  1. ONE logical family keyed `decompiler`; the candidate supplies are
     `ida-pro-vm` (MCP), `idat64` (local IDA ladder), `analyzeHeadless`
     (Ghidra, local binary or the registered ghidra MCP bridge).
  2. `_check_decompiler` emits ONE item per init, always named
     `decompiler`, carrying `supply` (canonical winner | `none`) and
     `skipped` (the pre-empted siblings — informational, never FAIL, never
     a separate missing item) plus the strategy/path/reachable evidence in
     the detail.
  3. Registries (REQUIRED_TOOLS next-actions, ownership tiers, CHECK_SETS,
     FIXES) carry ONE family key, not three.
  4. The exit-8 PendingDecision CHOICE stays (three options) when no
     supply exists; the pure-DEX `has_native_so=False` WARN stays free (no
     HARD blocker, no choice).

Fixture-driven: the three supply probes and the MCP registry read are
monkeypatched, so the module never depends on the machine's real IDA /
Ghidra / MCP state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

import toolchain as tc  # noqa: E402  (pytest.ini pythonpath = scripts)

FAMILY = "decompiler"
SUPPLY_IDA_MCP = "ida-pro-vm"
SUPPLY_IDA_CLI = "idat64"
SUPPLY_GHIDRA = "analyzeHeadless"
SUPPLY_NONE = "none"
FAMILY_NAMES = {FAMILY, "ghidra", "ida"}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws-210"
    w.mkdir()
    return w


def _reqs(lane: str | None = None) -> "tc.Requirements":
    """Requirements for the undeclared / declared-lane cases (task_spec
    shape the callers use), never the host's env."""
    tools: dict = {"mcp_servers": []}
    if lane is not None:
        tools["decompiler_lane"] = lane
    return tc.requirements_from_task_spec(
        {"constraints": {"dynamic_re": "forbidden"}, "tools": tools})


def _run(monkeypatch, ws: Path, *, registered=(), ida=None, ghidra=None,
         has_native_so=None, lane=None, caps=False, ida_calls=None,
         ghidra_calls=None) -> "tc.ToolchainReport":
    """Run _check_decompiler with all three supply probes stubbed."""
    monkeypatch.setattr(tc.mcp_probe, "registered_names",
                        lambda *a, **k: set(registered))

    def _fake_ida(*a, **k):
        if ida_calls is not None:
            ida_calls.append(1)
        return (ida, "PATH" if ida else "")

    def _fake_ghidra(*a, **k):
        if ghidra_calls is not None:
            ghidra_calls.append(1)
        return ghidra

    monkeypatch.setattr(tc, "_probe_local_ida", _fake_ida)
    monkeypatch.setattr(tc, "_probe_ghidra", _fake_ghidra)
    report = tc.ToolchainReport(project_type="windows")
    tc._check_decompiler(report, ws, has_native_so=has_native_so, caps=caps,
                         reqs=_reqs(lane))
    return report


def _only(report: "tc.ToolchainReport") -> "tc.CheckResult":
    """The single decompiler item; fails loudly on a parallel ida/ghidra
    item (the AND-shaped residue this issue removes)."""
    names = [i.name for i in report.items]
    assert names.count(FAMILY) == 1, f"expected ONE {FAMILY} item: {names}"
    assert not (set(names) & {"ghidra", "ida"}), \
        f"no parallel ida/ghidra items allowed (XOR family): {names}"
    return next(i for i in report.items if i.name == FAMILY)


# ---------- acceptance: the four supply shapes ----------


class TestSupplyShapes:
    def test_ida_ladder_hit_is_one_item_with_supply(
            self, monkeypatch, ws, tmp_path):
        idat = tmp_path / "IDA" / "idat64"
        idat.parent.mkdir()
        idat.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        idat.chmod(0o755)
        report = _run(monkeypatch, ws, ida=idat)

        item = _only(report)
        assert item.status is tc.Status.PASS, item
        assert item.supply == SUPPLY_IDA_CLI, item
        assert item.skipped == (SUPPLY_IDA_MCP, SUPPLY_GHIDRA), item
        # evidence fields survive in the detail (path + strategy + wiring)
        assert str(idat) in item.detail
        assert "PATH" in item.detail
        assert f"supply={SUPPLY_IDA_CLI}" in item.detail
        assert f"skipped=[{SUPPLY_IDA_MCP}, {SUPPLY_GHIDRA}]" in item.detail

    def test_ghidra_probe_hit_is_one_item_with_supply(
            self, monkeypatch, ws, tmp_path):
        ah = tmp_path / "ghidra" / "support" / "analyzeHeadless"
        report = _run(monkeypatch, ws, ghidra=ah)

        item = _only(report)
        assert item.status is tc.Status.PASS, item
        assert item.supply == SUPPLY_GHIDRA, item
        assert item.skipped == (SUPPLY_IDA_MCP, SUPPLY_IDA_CLI), item
        assert "analyzeHeadless" in item.detail

    def test_mcp_registration_wins_and_ladder_never_runs(
            self, monkeypatch, ws):
        ida_calls, ghidra_calls = [], []
        report = _run(monkeypatch, ws, registered=[SUPPLY_IDA_MCP],
                      ida_calls=ida_calls, ghidra_calls=ghidra_calls)

        item = _only(report)
        assert item.supply == SUPPLY_IDA_MCP, item
        assert item.skipped == (SUPPLY_IDA_CLI, SUPPLY_GHIDRA), item
        assert "via MCP (ida-pro-vm)" in item.detail
        assert not ida_calls and not ghidra_calls, \
            "the local ladder must not run once an MCP supply won"

    def test_ghidra_mcp_bridge_maps_to_the_ghidra_supply(
            self, monkeypatch, ws):
        """The registered `ghidra` MCP bridge is the Ghidra XOR branch
        (same supply path as the local analyzeHeadless binary)."""
        report = _run(monkeypatch, ws, registered=["ghidra"])
        item = _only(report)
        assert item.supply == SUPPLY_GHIDRA, item
        assert item.skipped == (SUPPLY_IDA_MCP, SUPPLY_IDA_CLI), item

    def test_no_supply_fails_with_unchanged_choice(self, monkeypatch, ws):
        report = _run(monkeypatch, ws)
        item = _only(report)
        assert item.status is tc.Status.FAIL, item
        assert item.tier is tc.Tier.HARD
        assert item.supply == SUPPLY_NONE, item
        assert item.skipped == (), "nothing was skipped — every supply missed"
        pd = item.pending_decision
        assert pd is not None
        assert pd.decision_id == "decompiler_lane"
        assert pd.kind == "choice"
        assert set(pd.options) == {
            "install-local-ida", "install-ghidra", "skip-decompiler-lane"}

    def test_choice_question_names_the_three_supply_paths(
            self, monkeypatch, ws):
        report = _run(monkeypatch, ws)
        q = _only(report).pending_decision.question
        assert "idat64" in q and "analyzeHeadless" in q and "ida-pro-vm" in q


# ---------- the pure-DEX free-skip nuance survives ----------


class TestPureDexNuance:
    def test_pure_dex_no_supply_is_warn_without_choice(
            self, monkeypatch, ws):
        report = _run(monkeypatch, ws, has_native_so=False)
        item = _only(report)
        assert item.status is tc.Status.WARN, item
        assert item.tier is tc.Tier.HARD
        assert item.supply == SUPPLY_NONE
        assert item.pending_decision is None, \
            "pure-DEX is freely skippable — never a user choice"
        assert report.exit_code != 8


# ---------- XOR exclusivity: the loser probe is never consulted ----------


class TestXorExclusivity:
    def test_ida_win_never_probes_ghidra(self, monkeypatch, ws, tmp_path):
        idat = tmp_path / "idat64"
        ghidra_calls = []
        _run(monkeypatch, ws, ida=idat, ghidra_calls=ghidra_calls)
        assert ghidra_calls == [], "IDA XOR Ghidra: no Ghidra probe after IDA"

    def test_ghidra_win_only_after_ida_miss(self, monkeypatch, ws, tmp_path):
        ida_calls = []
        _run(monkeypatch, ws, ghidra=tmp_path / "ah", ida_calls=ida_calls)
        assert ida_calls, "the ladder runs first (IDA XOR Ghidra order)"

    def test_skipped_never_becomes_a_fail(
            self, monkeypatch, ws, tmp_path):
        """Acceptance 3: skipped siblings are informational — in every
        winning shape the report carries ONE item, no FAIL, and the skipped
        names never surface as items of their own."""
        for kwargs in ({"ida": tmp_path / "idat64"},
                       {"ghidra": tmp_path / "ah"},
                       {"registered": [SUPPLY_IDA_MCP]}):
            report = _run(monkeypatch, ws, **kwargs)
            assert all(i.name == FAMILY for i in report.items), report.items
            assert all(i.status is not tc.Status.FAIL
                       for i in report.items), report.items
            item = report.items[0]
            assert item.skipped, "a winner always pre-empts the siblings"
            assert item.supply not in item.skipped


# ---------- registry census: 3 -> 1 ----------


class TestRegistryCensus:
    def test_one_family_key_per_registry(self):
        from report_render import FIXES
        assert set(tc._STATIC_NEXT_ACTIONS) & FAMILY_NAMES == {FAMILY}
        assert set(tc._OWNER_BY_NAME) & FAMILY_NAMES == {FAMILY}
        assert set(FIXES) & FAMILY_NAMES == {FAMILY}
        for project_type in ("windows", "linux", "android"):
            assert set(tc.CHECK_SETS[project_type]) & FAMILY_NAMES == {FAMILY}, \
                project_type

    def test_family_next_action_lists_three_paths(self):
        na = tc._STATIC_NEXT_ACTIONS[FAMILY]
        assert na.action in tc.NEXT_ACTION_VERBS
        assert set(na.options) == {SUPPLY_IDA_CLI, SUPPLY_GHIDRA,
                                   SUPPLY_IDA_MCP}
        blob = (na.command or "").lower()
        assert "idat64" in blob and "ghidra" in blob and "ida-pro-vm" in blob

    def test_family_item_derives_next_action(self):
        """The FAIL face keeps a machine-parseable next action (no registry
        entry left behind for the skipped siblings)."""
        item = tc.CheckResult(name=FAMILY, status=tc.Status.FAIL,
                              tier=tc.Tier.HARD, detail="none",
                              supply=SUPPLY_NONE)
        na = tc.next_action_for(item)
        assert na is not None and na.action in tc.NEXT_ACTION_VERBS

    def test_owner_tier_is_lane_conditional_for_the_family_only(self):
        assert tc.owner_for(FAMILY) is tc.OwnerTier.LANE_CONDITIONAL
        # the legacy per-supply names are not registry keys any more — they
        # fall to the agent-do default rather than implying an AND face
        assert tc.owner_for("ghidra") is tc.OwnerTier.AGENT_DO
        assert tc.owner_for("ida") is tc.OwnerTier.AGENT_DO

    def test_family_names_absent_from_source_scanned_check_face(self):
        """No CheckResult literal may be emitted under the legacy per-supply
        names (the item name surface is the family key alone)."""
        import inspect
        scanned = set(re.findall(
            r'CheckResult\(\s*name=["\']([A-Za-z0-9_:-]+)["\']',
            inspect.getsource(tc)))
        assert FAMILY in scanned
        assert not (scanned & {"ghidra", "ida"}), sorted(scanned)


# ---------- render face: one decompiler line, structured JSON ----------


class TestRenderFace:
    def test_human_output_has_one_decompiler_line(
            self, monkeypatch, ws, tmp_path):
        for kwargs in ({"ida": tmp_path / "idat64"},
                       {"ghidra": tmp_path / "ah"},
                       {"registered": [SUPPLY_IDA_MCP]},
                       {}):
            report = _run(monkeypatch, ws, **kwargs)
            lines = [ln for ln in tc.format_human(report).splitlines()
                     if re.match(r"^\s*\[(PASS|FAIL|WARN)\] \[(HARD|WARN)\] "
                                 + FAMILY + r":", ln)]
            assert len(lines) == 1, tc.format_human(report)

    def test_json_exposes_supply_and_skipped(self, monkeypatch, ws,
                                             tmp_path):
        report = _run(monkeypatch, ws, ida=tmp_path / "idat64")
        data = json.loads(tc.format_json(report))
        assert len(data["checks"]) == 1, data["checks"]
        check = data["checks"][0]
        assert check["name"] == FAMILY
        assert check["supply"] == SUPPLY_IDA_CLI
        assert check["skipped"] == [SUPPLY_IDA_MCP, SUPPLY_GHIDRA]

    def test_family_fix_text_lists_three_paths(self):
        from report_render import FIXES
        fix = FIXES[FAMILY].fix.lower()
        assert "idat64" in fix and "ghidra" in fix and "ida-pro-vm" in fix
        assert "x-or" in fix or "xor" in fix


# ---------- lane constraints preserved (issue 202) ----------


class TestLanePreserved:
    def test_mcp_lane_never_consults_the_local_ladder(
            self, monkeypatch, ws):
        ida_calls, ghidra_calls = [], []
        report = _run(monkeypatch, ws, registered=[SUPPLY_IDA_MCP], lane="mcp",
                      ida_calls=ida_calls, ghidra_calls=ghidra_calls)
        item = _only(report)
        assert item.supply == SUPPLY_IDA_MCP, item
        assert not ida_calls and not ghidra_calls

    def test_mcp_lane_unregistered_fails_supply_none(
            self, monkeypatch, ws):
        report = _run(monkeypatch, ws, lane="mcp")
        item = _only(report)
        assert item.status is tc.Status.FAIL
        assert item.supply == SUPPLY_NONE

    def test_local_lane_ghidra_fallback_supplies_the_family(
            self, monkeypatch, ws, tmp_path):
        report = _run(monkeypatch, ws, ghidra=tmp_path / "ah", lane="local")
        item = _only(report)
        assert item.status is tc.Status.PASS
        assert item.supply == SUPPLY_GHIDRA
