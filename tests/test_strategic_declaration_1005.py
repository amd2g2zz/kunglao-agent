# -*- coding: utf-8 -*-
"""Dispatch-time strategic route declaration (issue-1005, S5 face).

Pins the declaration face the dispatch seam owns, on top of the episode
face that already exists in ``rlvr.strategic_action``:

  - a dispatch whose prompt declares a strategic route (``[strategy
    FIGHT]`` with the route in the closed set) writes EXACTLY ONE
    ``strategic-action/1`` row into the unified experience ledger via
    the consolidated family append, carrying ``{claim, route,
    propensity, declared: true, trace_id, ts}``;
  - a dispatch with NO route declaration writes the honest gap row
    (``declared: false``, ``route: null``, ``propensity: null``) —
    silence must never be the norm;
  - repeated dispatches APPEND (history preserved, no dedupe — the
    LAST row is the live face, mirroring the strategy-log reader);
  - at settle time the absence maps toward SURRENDER per the existing
    disposition algebra: the mapping helper is a pure function over the
    row and the seven-word vocabulary is consumed, never extended;
  - the sampler reconciliation prefers the declaration row as the
    declared face and keeps the envelope family face as the fallback;
  - the declaration rows stay consumable by the disposition producer
    (``disposition_fields`` maps the declaration shape onto the two
    strategic fields the episode record copies).

The behavior-policy propensity is the route's Laplace-smoothed share of
the workspace's PRIOR declared dispatch rows over the recent
declaration window (the uniform prior over the closed set falls out on
a cold workspace; a never-declared route stays strictly inside (0, 1)),
and it is computed BEFORE the dispatch's own row appends, so a choice
never raises its own propensity.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rlvr.consolidated_ledger as consolidated_ledger  # noqa: E402
import rlvr.disposition as disposition  # noqa: E402
import rlvr.strategic_action as strategic_action  # noqa: E402
import worker_budget_sinks as sinks  # noqa: E402

TS = "2026-11-05T12:00:00Z"
STAMP = "strategic-action/1"
EXPERIENCE_REL = Path("runs") / "experience.jsonl"
ENVELOPE = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1",'
            ' "tier": 1, "tools": ["grep"]}}\n')


# ---------- workspace + gate harness (the decision-teeth shape) ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")


def _declaration_ws(root: Path) -> Path:
    """One OPEN claim, no PQ linkage, no hypotheses carrier — every gate
    face sleeps or passes so the ALLOW tail is the only live path."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write_yaml(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "statement": "background work",
         "promotion_attempts": 0},
    ]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    (ws / "runs").mkdir()
    from _factories import write_hook_state
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


def _run_gate(root: Path, ws: Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), errors="replace",
    )


def _experience_rows(ws: Path) -> list[dict]:
    path = ws / EXPERIENCE_REL
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if str(row.get("schema") or "") == STAMP:
            rows.append(row)
    return rows


def _append_row(ws: Path, *, route, declared, claim: str = "C-1",
                propensity=None, trace_id="tr-m-1") -> dict:
    """One declaration row appended through the module face (the setup
    helper for reader-side pins)."""
    if declared:
        propensity = 0.5 if propensity is None else propensity
    row = strategic_action.build_declaration_row(
        claim=claim, route=route, propensity=propensity, declared=declared,
        trace_id=trace_id, ts=TS)
    assert strategic_action.append_declaration(ws, row)["appended"] is True
    return row


# ---------- the writer at the dispatch seam ----------

class TestDispatchWritesTheDeclarationRow:
    def test_declared_route_writes_exactly_one_row(self, tmp_path) -> None:
        root = tmp_path / "declared"
        ws = _declaration_ws(root)
        r = _run_gate(root, ws, ENVELOPE + "background sweep [strategy FIGHT]")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1, f"exactly one row, got {rows}"
        row = rows[0]
        assert row["schema"] == STAMP
        assert row["claim"] == "C-1"
        assert row["route"] == "FIGHT"
        assert row["declared"] is True
        assert isinstance(row["propensity"], (int, float)) \
            and 0.0 <= row["propensity"] <= 1.0
        assert isinstance(row["trace_id"], str) and row["trace_id"]
        # the identity timestamp is the house ISO-8601 UTC second stamp
        datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ")

    def test_undeclared_dispatch_writes_the_explicit_gap_row(
            self, tmp_path) -> None:
        root = tmp_path / "gap"
        ws = _declaration_ws(root)
        r = _run_gate(root, ws, ENVELOPE + "background sweep")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1, "absence must be an explicit row, never none"
        row = rows[0]
        assert row["schema"] == STAMP
        assert row["claim"] == "C-1"
        assert row["declared"] is False
        assert row["route"] is None
        assert row["propensity"] is None

    def test_non_route_strategy_marker_declares_no_route(
            self, tmp_path) -> None:
        """A `[strategy <id>]` marker naming a strategy id (not one of the
        closed route words) is not a route declaration — the row stays the
        honest gap, never a fabricated route."""
        root = tmp_path / "marker"
        ws = _declaration_ws(root)
        r = _run_gate(root, ws,
                      ENVELOPE + "background sweep [strategy first-pass]")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1
        assert rows[0]["declared"] is False
        assert rows[0]["route"] is None

    def test_repeated_dispatch_appends_history(self, tmp_path) -> None:
        root = tmp_path / "history"
        ws = _declaration_ws(root)
        assert _run_gate(root, ws, ENVELOPE + "sweep [strategy BYPASS]"
                         ).returncode == 0
        assert _run_gate(root, ws, ENVELOPE + "sweep [strategy FIGHT]"
                         ).returncode == 0
        rows = _experience_rows(ws)
        assert len(rows) == 2, "history is preserved, no dedupe"
        assert [row["route"] for row in rows] == ["BYPASS", "FIGHT"]
        live = strategic_action.latest_declaration(ws, "C-1")
        assert live is not None and live["route"] == "FIGHT", \
            "the LAST row is the live face"

    def test_propensity_is_the_prior_share_not_the_post_choice_face(
            self, tmp_path) -> None:
        """The behavior propensity is computed BEFORE the dispatch's own
        append: the first declared dispatch draws the cold uniform prior,
        the second same-route dispatch sees the smoothed share of the
        first row."""
        root = tmp_path / "prior"
        ws = _declaration_ws(root)
        assert _run_gate(root, ws, ENVELOPE + "sweep [strategy FIGHT]"
                         ).returncode == 0
        assert _run_gate(root, ws, ENVELOPE + "sweep [strategy FIGHT]"
                         ).returncode == 0
        first, second = _experience_rows(ws)
        assert first["propensity"] == pytest.approx(
            round(1.0 / len(strategic_action.STRATEGIC_ACTIONS), 6))
        # Laplace-smoothed share of the one-row history: (1+1)/(1+3)
        assert second["propensity"] == pytest.approx(0.5)


# ---------- the pure builder ----------

class TestDeclarationRowBuilder:
    def test_declared_row_shape(self) -> None:
        row = strategic_action.build_declaration_row(
            claim="C-1", route="FIGHT", propensity=0.5, declared=True,
            trace_id="tr-m-1", ts=TS)
        assert row == {"schema": STAMP, "claim": "C-1", "route": "FIGHT",
                       "propensity": 0.5, "declared": True,
                       "trace_id": "tr-m-1", "ts": TS}

    def test_gap_row_shape(self) -> None:
        row = strategic_action.build_declaration_row(
            claim="C-1", route=None, propensity=None, declared=False,
            trace_id=None, ts=TS)
        assert row == {"schema": STAMP, "claim": "C-1", "route": None,
                       "propensity": None, "declared": False,
                       "trace_id": None, "ts": TS}

    def test_route_must_be_in_the_closed_set_or_null(self) -> None:
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route="PANIC", propensity=0.5, declared=True,
                trace_id=None, ts=TS)
        # the closed set is the strategic vocabulary, never a local copy
        assert strategic_action.STRATEGIC_ACTIONS == \
            disposition.STRATEGIC_ACTIONS

    def test_propensity_must_be_in_the_unit_interval(self) -> None:
        for bad in (-0.01, 1.01, "0.5", True, None):
            with pytest.raises(strategic_action.StrategicActionError):
                strategic_action.build_declaration_row(
                    claim="C-1", route="FIGHT", propensity=bad,
                    declared=True, trace_id=None, ts=TS)

    def test_declared_true_requires_route_and_propensity(self) -> None:
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route=None, propensity=0.5, declared=True,
                trace_id=None, ts=TS)
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route="FIGHT", propensity=None, declared=True,
                trace_id=None, ts=TS)

    def test_declared_false_requires_the_null_face(self) -> None:
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route="FIGHT", propensity=None, declared=False,
                trace_id=None, ts=TS)
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route=None, propensity=0.5, declared=False,
                trace_id=None, ts=TS)

    def test_claim_is_required_and_trace_id_is_optional(self) -> None:
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="  ", route=None, propensity=None, declared=False,
                trace_id=None, ts=TS)
        row = strategic_action.build_declaration_row(
            claim="C-1", route=None, propensity=None, declared=False,
            trace_id=None, ts=TS)
        assert row["trace_id"] is None

    def test_ts_is_calendar_validated(self) -> None:
        with pytest.raises(strategic_action.StrategicActionError):
            strategic_action.build_declaration_row(
                claim="C-1", route=None, propensity=None, declared=False,
                trace_id=None, ts="2026-11-05 12:00:00")


# ---------- append history + the live face ----------

class TestAppendHistoryAndLiveFace:
    def test_appends_preserve_history_no_dedupe(self, tmp_path) -> None:
        _append_row(tmp_path, route="FIGHT", declared=True)
        _append_row(tmp_path, route="FIGHT", declared=True)
        _append_row(tmp_path, route=None, declared=False)
        rows = strategic_action.declaration_rows(tmp_path)
        assert len(rows) == 3, "append history, never dedupe"
        assert [row["declared"] for row in rows] == [True, True, False]

    def test_appends_land_in_the_consolidated_experience_file(
            self, tmp_path) -> None:
        row = _append_row(tmp_path, route="INVEST", declared=True)
        rows = consolidated_ledger.read(
            tmp_path, "experience", schema_prefix=STAMP)
        assert row in rows

    def test_latest_declaration_is_the_last_row(self, tmp_path) -> None:
        _append_row(tmp_path, route="BYPASS", declared=True)
        gap = _append_row(tmp_path, route=None, declared=False)
        assert strategic_action.latest_declaration(tmp_path) == gap
        declared = _append_row(tmp_path, route="FIGHT", declared=True,
                               trace_id="tr-m-9")
        assert strategic_action.latest_declaration(tmp_path) == declared
        # claim-scoped: only that claim's rows are considered
        assert strategic_action.latest_declaration(tmp_path, "C-1") == \
            declared
        _append_row(tmp_path, route="INVEST", declared=True, claim="C-2")
        assert strategic_action.latest_declaration(
            tmp_path, "C-2")["claim"] == "C-2"
        assert strategic_action.latest_declaration(
            tmp_path, "C-1")["route"] == "FIGHT"

    def test_latest_declaration_reads_none_on_a_cold_workspace(
            self, tmp_path) -> None:
        assert strategic_action.latest_declaration(tmp_path) is None
        assert strategic_action.declaration_rows(tmp_path) == []

    def test_route_propensity_is_the_prior_share(self, tmp_path) -> None:
        assert strategic_action.route_propensity(tmp_path, "FIGHT") == \
            pytest.approx(round(1.0 / 3.0, 6))
        _append_row(tmp_path, route="FIGHT", declared=True)
        _append_row(tmp_path, route="FIGHT", declared=True)
        _append_row(tmp_path, route="INVEST", declared=True)
        _append_row(tmp_path, route=None, declared=False)  # never counts
        # Laplace smoothing: (hits + alpha) / (total + alpha * K)
        assert strategic_action.route_propensity(
            tmp_path, "FIGHT") == pytest.approx(round(3.0 / 6.0, 6))
        assert strategic_action.route_propensity(
            tmp_path, "INVEST") == pytest.approx(round(2.0 / 6.0, 6))
        assert strategic_action.route_propensity(tmp_path, None) is None

    def test_route_propensity_is_never_zero_for_a_declared_route(
            self, tmp_path) -> None:
        """A route the workspace never declared keeps a positive
        propensity under any history — a probability-0 draw for a taken
        action is invalid for IPS (the propensity-coherence family's
        pathology)."""
        _append_row(tmp_path, route="FIGHT", declared=True)
        _append_row(tmp_path, route="FIGHT", declared=True)
        share = strategic_action.route_propensity(tmp_path, "BYPASS")
        assert share is not None
        assert 0.0 < share < 1.0
        assert share == pytest.approx(round(1.0 / (2.0 + 3.0), 6))
        # the smoothing never saturates either: a single-route history
        # keeps the taken route strictly inside (0, 1) too
        solo = strategic_action.route_propensity(tmp_path, "FIGHT")
        assert solo is not None and 0.0 < solo < 1.0

    def test_route_propensity_prior_is_over_the_recent_window(
            self, tmp_path) -> None:
        """The prior share is computed over the last
        DECLARATION_HISTORY_MAX declared rows (the recent-window behavior
        policy): a marker route outside the window does not move the
        share, and the live face still resolves."""
        cap = strategic_action.DECLARATION_HISTORY_MAX
        assert cap >= 1
        for _ in range(2):
            _append_row(tmp_path, route="FIGHT", declared=True)
        for _ in range(cap):
            _append_row(tmp_path, route="INVEST", declared=True)
        rows = strategic_action.declaration_rows(tmp_path)
        assert len(rows) == cap, "the reader face stays capped"
        live = strategic_action.latest_declaration(tmp_path)
        assert live is not None and live["route"] == "INVEST"
        # the two FIGHT rows aged out of the window: the window holds
        # only INVEST, so FIGHT rides the smoothing floor alone
        assert strategic_action.route_propensity(
            tmp_path, "FIGHT") == pytest.approx(
            round(1.0 / (cap + 3.0), 6))
        assert strategic_action.route_propensity(
            tmp_path, "INVEST") == pytest.approx(
            round((cap + 1.0) / (cap + 3.0), 6))
        # widening the window admits the aged-out rows again (the cap is
        # the parameter, not a hard wall)
        assert strategic_action.route_propensity(
            tmp_path, "FIGHT", history_max=cap + 5) == pytest.approx(
            round(3.0 / (cap + 2.0 + 3.0), 6))


# ---------- the settle-side absence mapping ----------

class TestAbsenceMapsTowardSurrender:
    def test_absence_and_gap_rows_map_to_surrender(self) -> None:
        assert strategic_action.absence_disposition(None) == "SURRENDER"
        gap = strategic_action.build_declaration_row(
            claim="C-1", route=None, propensity=None, declared=False,
            trace_id=None, ts=TS)
        assert strategic_action.absence_disposition(gap) == "SURRENDER"

    def test_declared_rows_map_nothing_here(self) -> None:
        declared = strategic_action.build_declaration_row(
            claim="C-1", route="BYPASS", propensity=0.4, declared=True,
            trace_id=None, ts=TS)
        assert strategic_action.absence_disposition(declared) is None
        episode = strategic_action.build_row(
            episode_id="ep-1", claim="C-1", action="BYPASS",
            propensity=0.4, ts=TS)
        assert strategic_action.absence_disposition(episode) is None

    def test_the_word_is_the_disposition_vocabulary_own(self) -> None:
        """The residual word is imported from the disposition algebra's
        vocabulary — the seven-word set is consumed, never extended."""
        assert strategic_action.SURRENDER == "SURRENDER"
        assert strategic_action.SURRENDER in disposition.DISPOSITIONS
        assert len(disposition.DISPOSITIONS) == 7
        # the residual gate is the unfinished face of the algebra
        assert disposition.GATE_FOR_DISPOSITION[
            strategic_action.SURRENDER] == ("unfinished",)

    def test_the_residual_derivation_never_raises_on_a_refactored_algebra(
            self, monkeypatch) -> None:
        """If the algebra ever drops the unfinished gate, the derivation
        degrades to the documented sentinel (one warn) instead of
        crashing the package import (the disposition producer imports
        this module at module level)."""
        monkeypatch.setattr(disposition, "GATE_FOR_DISPOSITION",
                            {"SOLVED": ("oracle_pass",)})
        monkeypatch.setattr(disposition, "DISPOSITIONS", ("SOLVED",))
        assert strategic_action._derive_residual_word() == "SURRENDER"
        # and the normal derivation still consults the live table
        monkeypatch.setattr(disposition, "GATE_FOR_DISPOSITION",
                            {"SOLVED": ("oracle_pass",),
                             "SURRENDER": ("unfinished",)})
        monkeypatch.setattr(disposition, "DISPOSITIONS",
                            ("SOLVED", "SURRENDER"))
        assert strategic_action._derive_residual_word() == "SURRENDER"

    def test_declaration_rows_feed_the_disposition_fields(self) -> None:
        """The disposition producer joins the LAST row per claim and
        copies two fields — the declaration shape must flow through the
        same face (declared route onward, the gap as the None face)."""
        declared = strategic_action.build_declaration_row(
            claim="C-1", route="FIGHT", propensity=0.62, declared=True,
            trace_id=None, ts=TS)
        assert strategic_action.disposition_fields(declared) == {
            "strategic_action": "FIGHT", "propensity": 0.62}
        gap = strategic_action.build_declaration_row(
            claim="C-1", route=None, propensity=None, declared=False,
            trace_id=None, ts=TS)
        assert strategic_action.disposition_fields(gap) == {
            "strategic_action": None, "propensity": None}


# ---------- the sampler reconciliation face ----------

class TestReconciliationPrefersTheDeclarationRow:
    RECONCILED_VIEW = {"sampled_family": "static-decompile",
                       "propensity": 0.4, "prior_source": "history",
                       "deviates": False, "sampled_propensity": 0.4,
                       "round_lead": None}

    @classmethod
    def _patch_reconcile(cls, monkeypatch) -> None:
        import rlvr.strategy_store as strategy_store
        monkeypatch.setattr(
            strategy_store, "reconcile_declaration",
            lambda ws_, declared_: dict(cls.RECONCILED_VIEW))

    def test_the_row_is_the_preferred_declared_face(
            self, tmp_path, monkeypatch) -> None:
        self._patch_reconcile(monkeypatch)
        _append_row(tmp_path, route="FIGHT", declared=True,
                    propensity=0.62)
        view = sinks._sample_reconciliation(tmp_path, "static-decompile")
        assert view["declared_route"] == "FIGHT"
        assert view["declared_propensity"] == 0.62
        assert view["declared_source"] == STAMP
        # the method-family reconciliation face rides unchanged
        assert view["sampled_family"] == "static-decompile"
        assert view["propensity"] == 0.4

    def test_no_row_keeps_the_fallback_face_byte_identical(
            self, tmp_path, monkeypatch) -> None:
        self._patch_reconcile(monkeypatch)
        view = sinks._sample_reconciliation(tmp_path, "static-decompile")
        assert "declared_route" not in view
        assert view["sampled_family"] == "static-decompile"

    def test_undeclared_with_a_row_still_surfaces_the_declaration(
            self, tmp_path, monkeypatch) -> None:
        _append_row(tmp_path, route="INVEST", declared=True,
                    propensity=0.25)
        view = sinks._sample_reconciliation(tmp_path, None)
        assert view["declared_route"] == "INVEST"
        assert view["sampled_family"] is None

    def test_cold_gap_stays_the_honest_all_none_view(
            self, tmp_path, monkeypatch) -> None:
        view = sinks._sample_reconciliation(tmp_path, None)
        assert view == {"sampled_family": None, "propensity": None,
                        "prior_source": None, "deviates": False,
                        "sampled_propensity": None, "round_lead": None}

    def test_reader_outage_fails_open_to_the_fallback(
            self, tmp_path, monkeypatch) -> None:
        self._patch_reconcile(monkeypatch)

        def _boom(_ws, _claim=None):
            raise RuntimeError("reader outage")

        monkeypatch.setattr(strategic_action, "latest_declaration", _boom)
        view = sinks._sample_reconciliation(tmp_path, "static-decompile")
        assert "declared_route" not in view
        # fail-open keeps the method-family reconciliation face: only the
        # strategic declared face degrades (one rate-limited warn)
        assert view["sampled_family"] == "static-decompile"


# ---------- liveness: the registered stamp ----------

class TestLivenessCountsTheWriter:
    def test_the_stamp_is_a_native_experience_schema(self) -> None:
        assert STAMP in consolidated_ledger.NATIVE_SCHEMAS["experience"]

    def test_a_dead_writer_reads_zero_never_absent(self, tmp_path) -> None:
        """An unregistered stamp is invisible; a registered one reads a
        countable face. The cold workspace reads an empty list, never an
        error."""
        assert consolidated_ledger.read(
            tmp_path, "experience", schema_prefix=STAMP) == []


# ---------- import hygiene (the facade-neutral pin) ----------

def test_the_test_imports_are_facade_neutral():
    """This module itself must never become a facade consumer: the rlvr
    faces are imported by module path (``import rlvr.x as x``), never
    through a ``from rlvr import ...`` re-export bind."""
    import ast
    import tests.test_strategic_declaration_1005 as this_module
    tree = ast.parse(
        Path(this_module.__file__).read_text(encoding="utf-8"))
    facade_binds = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
        and (node.module or "").split(".")[0] == "rlvr"]
    assert facade_binds == []
