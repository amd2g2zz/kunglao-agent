# -*- coding: utf-8 -*-
"""tests/test_decompat_804.py — #804 full-collapse de-compat pins.

Every pin here states the NEW loud gap where a compatibility fallback
used to serve the old behavior (mandate 2026-10-25: no compatibility,
migration = regeneration, old fallback -> new loud gap):

  1. q_cells fold: rows without an ``arm_key`` add NO posterior mass
     and NO pending count — they are counted in ``Fold.unkeyed`` (the
     un-attributed rate signal, mirroring kunglao_log's null-actor gap).
     The pre-#804 dual-write tolerance (fallback to the bare
     ``method_family`` cell) is retired.
  2. q_cells cell_posterior: the #539/#545 legacy tolerance (pooling the
     bare-family cell into a keyed local read) is retired — a keyed read
     sees ONLY its own cell as local mass.
  3. q_cells declared_family: the v0 prose marker fallback (``method-family:``
     in the prompt text) is retired — the envelope meta field is the only
     declaration face.
  4. kunglao_log actor vocabulary: LEGACY_ACTORS words whose emitters were
     migrated to strict shapes no longer validate bare (the adopted set
     only shrinks, #879 + #804).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import q_cells  # noqa: E402


def _row(sig: str, fam: str, credit, *, arm_key=None, source="settlement"):
    row = {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-25T00:00:00Z",
           "source": source, "signature_hash": sig, "method_family": fam,
           "credit": credit}
    if arm_key is not None:
        row["arm_key"] = arm_key
    return row


# ------------------------------------------------ 1. fold: unkeyed gap

def test_unkeyed_settled_row_banks_no_mass_and_counts_the_gap():
    """The old log tolerance is retired: a settled row without arm_key
    folds NOWHERE (no success/failure mass in any cell) and is counted
    in Fold.unkeyed — the loud un-attributed gap."""
    rows = [_row("aaaa00000000", "static-symbolic", 1.0)]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    assert fold.cells == {} or all(
        c.success == 0.0 and c.failure == 0.0 for c in fold.cells.values())
    assert fold.unkeyed == 1


def test_unkeyed_pending_row_banks_no_pending_count():
    rows = [_row("bbbb00000000", "static-symbolic", None,
                 source="dispatch")]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    assert all(c.n_pending == 0 for c in fold.cells.values())
    assert fold.unkeyed == 1


def test_keyed_row_still_folds_exactly():
    """Regression guard: the keyed (arm_key-carrying) consumption face is
    unchanged — the same row WITH the key banks full mass."""
    rows = [_row("cccc00000000", "static-symbolic", 1.0,
                 arm_key="static-symbolic|facts_snapshot|none|0")]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    cell = fold.cells[("cccc00000000",
                       "static-symbolic|facts_snapshot|none|0")]
    assert cell.success == pytest.approx(1.0)
    assert cell.failure == pytest.approx(0.0)
    assert fold.unkeyed == 0


def test_unkeyed_rows_stay_in_the_gamma_chain():
    """The unkeyed row is a real outcome — the γ schedule must OBSERVE
    it (the adaptive γ after a success differs from after a failure),
    even though no cell mass banks. If the fold dropped unkeyed rows
    from the chain, both streams' keyed masses would be identical."""
    def _stream(unkeyed_credit):
        return [
            _row("dddd00000000", "fam", unkeyed_credit),      # unkeyed (first)
            _row("eeee00000000", "fam", 1.0,
                 arm_key="fam|facts_snapshot|none|0"),        # keyed
            _row("ffff00000000", "fam", 1.0,
                 arm_key="fam|facts_snapshot|none|0"),        # keyed (last)
        ]

    after_success = q_cells.fold(
        q_cells.InMemoryStore(_stream(1.0))).cells[
            ("eeee00000000", "fam|facts_snapshot|none|0")]
    after_failure = q_cells.fold(
        q_cells.InMemoryStore(_stream(0.0))).cells[
            ("eeee00000000", "fam|facts_snapshot|none|0")]
    # the γ after the unkeyed outcome decays the middle keyed row (< 1.0)
    assert after_success.success < 1.0
    # and the schedule FELT the unkeyed outcome (success vs failure move
    # the adaptive γ differently -> different decayed masses)
    assert after_success.success != after_failure.success


# --------------------------------- 2. cell_posterior: no legacy pooling

def test_keyed_local_read_never_pools_the_bare_family_cell():
    """The #539/#545 tolerance pooled the bare (sig, family) cell into a
    keyed local read. Retired: local mass = the keyed cell ONLY; the
    bare-family cell (wherever it came from) stays in the leave-one-out
    anchor, never in local."""
    bare = q_cells.CellCounts("aaaaaaaa0000", "fam",
                              success=10.0, failure=0.0)
    keyed = q_cells.CellCounts("aaaaaaaa0000", "fam|facts_snapshot|none|0",
                               success=2.0, failure=1.0)
    fold_view = q_cells.Fold(cells={
        ("aaaaaaaa0000", "fam"): bare,
        ("aaaaaaaa0000", "fam|facts_snapshot|none|0"): keyed,
    })
    # local = the keyed cell only (2,1); anchor = family mass (12,1)
    # minus local = (10,0); m = (1+10)/(2+10), w = min(8, 10) = 8.
    # Exact posterior under the retired-pooling law:
    a, b = q_cells.cell_posterior(
        fold_view, "aaaaaaaa0000", "fam",
        arm_key="fam|facts_snapshot|none|0")
    assert a == pytest.approx(1.0 + 8.0 * (11.0 / 12.0) + 2.0)
    assert b == pytest.approx(1.0 + 8.0 * (1.0 / 12.0) + 1.0)
    # the OLD pooling face returned (13.0, 2.0) — the bare cell rode local.
    assert (a, b) != (13.0, 2.0)


# --------------------------------- 3. declared_family: envelope only

def test_declared_family_envelope_field_is_the_only_face():
    assert q_cells.declared_family(
        {"method_family": "static-symbolic"}, "junk") == "static-symbolic"


def test_declared_family_prose_marker_is_no_longer_a_declaration():
    """The v0 prose marker (dead since #432 went universal) is retired:
    a prompt carrying `method-family: X` without the envelope field is
    the undeclared honest gap."""
    out = q_cells.declared_family(None, "do things\nmethod-family: ")
    assert out is None
    assert q_cells.declared_family(None, "x\nmethod-family: dynamic-tr\n") \
        is None


# --------------------------------- 4. observe(): the keyed bank face

def test_observe_accepts_an_explicit_arm_key(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    q_cells.observe(ws, "abcdabcdabcd", "static-symbolic", 0.5,
                    arm_key="static-symbolic|full_recall|none|0")
    rows = q_cells.JSONLQStore(ws).observations()
    assert rows[0]["arm_key"] == "static-symbolic|full_recall|none|0"


# --------------------------------- 5. the actor vocabulary only shrinks

def test_migrated_hook_actors_no_longer_validate_bare():
    """#804 wave-1: four hook-file emitters migrated to the strict
    ``hook:<name>`` form — the bare legacy words are no longer adopted
    (the strict forms still validate)."""
    import kunglao_log
    for bare, strict in (
            ("bash_fact_guard", "hook:bash_fact_guard"),
            ("violation_capture", "hook:violation_capture"),
            ("recall_inject", "hook:recall_inject"),
            ("completion_gate", "hook:completion_gate")):
        ok_bare, _why = kunglao_log.validate_actor(bare)
        ok_strict, _why2 = kunglao_log.validate_actor(strict)
        assert not ok_bare, f"{bare} must no longer be adopted"
        assert ok_strict, f"{strict} is the strict form"


def test_legacy_actor_set_shrinks_below_the_pre_collapse_count():
    """The adoption set is one-way: #804 wave-1 deleted the 36 dead words
    (no producer left in scripts/ or hooks/) plus the 4 migrated words —
    96 -> 56. The pin freezes the CEILING so the set cannot silently
    regrow (new emitters must use strict shapes)."""
    import kunglao_log
    assert len(kunglao_log.LEGACY_ACTORS) <= 56


# ------------------------- 6. the v1-envelope posture is loud, not silent

def test_branch_budget_malformed_retries_warns_loud(monkeypatch):
    """#804 de-compat: a DECLARED but malformed branch_budget.retries is
    a loud emitter defect (one rate-limited warn) while the dim stays
    unconstrained (absence is unconstrained, never zero — #690). The
    former silent fail-open posture is retired."""
    import importlib.util as ilu
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]
    spec = ilu.spec_from_file_location(
        "wbg_804", root / "hooks" / "worker_budget_gates.py")
    wbg = ilu.module_from_spec(spec)
    spec.loader.exec_module(wbg)
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(wbg, "warn", lambda op, why: seen.append((op, why)))
    for bad in ({"retries": True}, {"retries": "many"}, {"retries": [2]}):
        seen.clear()
        ok, msg = wbg.check_branch_budget({"workspace": "unused"},
                                          "C-1", bad)
        assert (ok, msg) == (True, ""), \
            "the dim stays unconstrained on a malformed value"
        assert seen and "loud emitter defect" in seen[0][1], (bad, seen)
    # schema-legal shapes never warn
    seen.clear()
    for good in ({}, {"retries": None}, {"retries": 0}, {"retries": 3}):
        wbg.check_branch_budget({"workspace": "unused"}, "C-1", good)
    assert seen == [], "legal shapes are silent"


# ------------------------- 7. the posterior twins are renamed apart

def test_bare_import_posteriors_is_unambiguous():
    """#804 (original task 2): the import-name twins — scripts/posteriors.py
    (the #106 CASE posterior) vs scripts/rlvr/posteriors.py (the DTS
    store) — made a bare ``import posteriors`` binding depend on
    sys.path order. The case twin is renamed posteriors_case; the probe
    pins the new binding: the bare name resolves to NOTHING anymore
    (every consumer names its face), the case face binds only under its
    new name, and the DTS store is package-qualified only."""
    import importlib
    import sys
    root = str(Path(__file__).resolve().parents[1] / "scripts")
    saved_path = sys.path[:]
    saved_mod = {k: v for k, v in sys.modules.items()
                 if k.startswith("posteriors")}
    sys.path.insert(0, root)
    try:
        for m in [k for k in sys.modules if k.startswith("posteriors")]:
            del sys.modules[m]
        try:
            importlib.import_module("posteriors")
            raise AssertionError("bare 'import posteriors' still binds — "
                                 "the twin rename regressed")
        except ImportError:
            pass
        case = importlib.import_module("posteriors_case")
        assert hasattr(case, "PosteriorLedger"), "the #106 case face moved"
        dts = importlib.import_module("rlvr.posteriors")
        assert dts.__name__ == "rlvr.posteriors", "the DTS store is qualified"
    finally:
        sys.path[:] = saved_path
        for k in [k for k in sys.modules if k.startswith("posteriors")]:
            del sys.modules[k]
        sys.modules.update(saved_mod)


# ------------- 8. the usage ledger merges into the dispatch obs row
# (#804 named follow-up, wave-2: one substrate per write event — the
# usage-ledger columns (tier / tools / propensity / sampled_family /
# prior_source) ride the dispatch observation row additively; the read
# faces project it; the old usage write face closes.)

_V1_DECL = '{"kunglao_dispatch": {"method_family": "static-symbolic"}}'
_USAGE_COLS = ("tier", "tools", "propensity", "sampled_family",
               "prior_source")


def _record_usage_merged(ws, **kw):
    out = q_cells.record_dispatch_observation(
        ws, _V1_DECL, envelope_meta={"method_family": "static-symbolic"},
        claim="C-804", agent="w-test", **kw)
    assert out["appended"] is True, out
    return q_cells.JSONLQStore(ws).observations()[-1]


def test_dispatch_row_carries_the_usage_columns(tmp_path):
    """R1 (additive): the dispatch observation row carries the usage-
    ledger columns — one substrate per dispatch, not two parallel write
    faces for the same event."""
    row = _record_usage_merged(
        tmp_path, tier=2, tools=["grep", "bash"],
        sampler_view={"sampled_family": "dynamic-trace", "propensity": 0.4,
                      "prior_source": "history"})
    assert row["tier"] == 2
    assert row["tools"] == ["grep", "bash"]
    assert row["propensity"] == 0.4
    assert row["sampled_family"] == "dynamic-trace"
    assert row["prior_source"] == "history"


def test_usage_columns_absent_when_not_supplied(tmp_path):
    """The additive-column discipline: a dispatch recorded without the
    usage view keeps the pre-merge row shape — absent keys, never null
    padding (byte-identity for every pre-merge writer)."""
    row = _record_usage_merged(tmp_path)
    for k in _USAGE_COLS:
        assert k not in row, f"{k} must stay absent when not supplied"


def test_sampler_triple_rides_together_or_not_at_all(tmp_path):
    """Partial material still emits the WHOLE triple (explicit nulls
    inside — the #695 recipe-triple precedent); defaults (tier 0, empty
    tools) never pad the row."""
    row = _record_usage_merged(
        tmp_path, tier=0, tools=[],
        sampler_view={"sampled_family": "static-symbolic"})
    assert row["sampled_family"] == "static-symbolic"
    assert row["propensity"] is None
    assert row["prior_source"] is None
    assert "tier" not in row and "tools" not in row


def test_bad_propensity_degrades_to_null_at_the_boundary(tmp_path):
    """The #691 boundary semantics survive the move: a non-numeric /
    out-of-range propensity degrades to null with a warn, never a
    raise into the producer."""
    row = _record_usage_merged(tmp_path,
                               sampler_view={"propensity": "not-a-number"})
    assert row["propensity"] is None
    row = _record_usage_merged(tmp_path, sampler_view={"propensity": 1.5})
    assert row["propensity"] is None


def test_allow_threads_the_usage_view_into_the_dispatch_row(
        tmp_path, capsys, monkeypatch):
    """The hook's ALLOW tail records ONE row carrying the usage view —
    the gate's reconciliation result lands on the dispatch observation
    (tier/tools from the dispatch shape, the sampler triple from the
    #691 view), not on a side ledger."""
    import json as _json
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        import worker_budget_sinks as sinks
    finally:
        sys.path.pop(0)
    ws = tmp_path / "ws"
    ws.mkdir()
    paths = {"workspace": str(ws), "state": ws / "analysis_state.txt",
             "register": ws / "claim-register.yaml",
             "deps": ws / "claim_deps.yaml",
             "task_spec": ws / "task_spec.yaml"}
    monkeypatch.setattr(
        sinks, "_sample_reconciliation",
        lambda ws_, declared: {"sampled_family": "static-decompile",
                               "propensity": 0.75,
                               "prior_source": "history",
                               "deviates": False})
    prompt = (_json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-804", "tier": 1, "tools": ["grep"],
        "agent": "w-test", "method_family": "static-decompile"}})
        + "\nfacts-snapshot: 1 facts")
    rc = sinks.pre_check(
        {"tool_input": {"name": "w-test", "description": "",
                        "prompt": prompt}}, paths)
    assert rc == 0, capsys.readouterr().err[-400:]
    rows = [r for r in q_cells.JSONLQStore(ws).observations()
            if r.get("claim") == "C-804" and r.get("source") == "dispatch"]
    assert len(rows) == 1, "one dispatch, one observation row"
    row = rows[0]
    assert row["tier"] == 1
    assert row["tools"] == ["grep"]
    assert row["propensity"] == 0.75
    assert row["sampled_family"] == "static-decompile"
    assert row["prior_source"] == "history"
