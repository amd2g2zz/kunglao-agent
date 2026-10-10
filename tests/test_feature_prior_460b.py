# -*- coding: utf-8 -*-
"""tests/test_feature_prior_460b.py — #460 Part B RED-first pins.

Spec scenarios are the tests (openspec change issue-460-predict-before-try):

  1. flag-gated inertness — KUNGLAO_PREDICT_BEFORE_TRY default off;
     flag on without a table = flag off; receipts byte-identical.
  2. similarity — Jaccard over canonical feature tokens; null fields
     emit no tokens; empty union scores 0.0.
  3. feature pool — the second anchor source under the one SHRINK_CAP:
     outcome mapping, similarity weighting, explicit exclude_run
     (the replay split — no fuzzy run join), zero pool = bit-identical.
  4. probe-arm ranking — cold start probes first; all-known categories
     demote; deterministic pure function.
  5. #669 retirement — uniform direct-fact prescan (no per-type
     "probe set" note anywhere in the promise), flag-gated obligation
     note, capability checks untouched.

The issue-420 wall (tests/test_rlvr_bitexact.py) is never edited; the
no-pool kernel identity is re-pinned here against the old formula's
exact fractions (the test_q_cells_429 shrinkage pins).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlvr import feature_prior as fp  # noqa: E402
from rlvr import q_cells  # noqa: E402
import feature_mining  # noqa: E402
import intake_promise  # noqa: E402


# ------------------------------------------------------------- helpers

def _features(**over) -> dict:
    """A well-formed feature-table/1 features object (Part A shape)."""
    base = {
        "lane": "static",
        "project_type": "linux",
        "target_kind": {"language": "javascript", "entry_suffix": ".js"},
        "packer_flags": {
            "packing": False, "obfuscation": False, "anti_analysis": False,
            "surface_reduction": False,
            "detected_packers": [], "detected_obfuscators": [],
        },
        "difficulty_factors": None,
        "probe_outputs": {
            "die": {"prescan_state": None, "usable": False,
                    "detected_packer": None, "entropy_max": None},
            "apkid": {"prescan_state": None, "usable": False,
                      "packers": [], "obfuscators": []},
        },
    }
    base.update(over)
    return base


def _table_row(run_id: str, features: dict, outcomes: list[dict],
               family: str = "release", task_id: str = "t-1") -> dict:
    row = {
        "schema": feature_mining.SCHEMA,
        "run_id": run_id,
        "family": family,
        "task_id": task_id,
        "signature_hash": feature_mining.signature_hash(features),
        "features": features,
        "outcomes": outcomes,
    }
    assert feature_mining.validate_row(row) == [], feature_mining.validate_row(row)
    return row


def _outcome(family: str, act_result: str = "landed",
             settled: bool = False, credit=None) -> dict:
    return {"claim": "C-1", "method_family_or_claim_source": family,
            "act_result": act_result, "settled": settled, "credit": credit}


def _write_table(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "runs" / "feature-table.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def _set_flag(value: str | None, monkeypatch):
    if value is None:
        monkeypatch.delenv(fp.FLAG_ENV, raising=False)
    else:
        monkeypatch.setenv(fp.FLAG_ENV, value)


# --------------------------------------------- 1. flag-gated inertness

def test_flag_defaults_on(monkeypatch):
    """WS3 (#544) contract change: default ON — the cold-start anchor
    engages whenever a table + features exist. The explicit opt-out is
    KUNGLAO_PREDICT_BEFORE_TRY == "0" (exact; everything else is the
    default-on face)."""
    _set_flag(None, monkeypatch)
    assert fp.enabled() is True


def test_flag_off_is_exact_zero(monkeypatch):
    _set_flag("1", monkeypatch)
    assert fp.enabled() is True
    _set_flag("0", monkeypatch)
    assert fp.enabled() is False
    _set_flag("yes", monkeypatch)
    assert fp.enabled() is True


def test_flag_off_receipt_is_byte_identical(tmp_path, monkeypatch):
    """Spec R1 (WS3 form): flag off via the explicit "0" opt-out (or on
    without a table) = the pre-change kernel, byte-identical receipts
    for the same store + seed."""
    store = q_cells.InMemoryStore([
        {"schema": q_cells.OBS_SCHEMA, "ts": "t", "source": "settlement",
         "signature_hash": "5e5e5e5e5e5e", "method_family": "fam-a",
         "claim": None, "agent": None, "credit": 1.0}])
    table = _write_table(tmp_path, [
        _table_row("r-1", _features(),
                   [_outcome("fam-a", settled=True, credit=1.0)])])
    _set_flag("0", monkeypatch)
    r1 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store,
        features=_features(), feature_table=table, rng=None)
    r2 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store, rng=None)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_flag_on_without_table_stays_inert(tmp_path, monkeypatch):
    _set_flag("1", monkeypatch)
    store = q_cells.InMemoryStore([])
    r1 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store,
        features=_features(), feature_table=tmp_path / "absent.jsonl",
        rng=None)
    r2 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store, rng=None)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# ------------------------------------------------------ 2. similarity

def test_similarity_identical_features_is_one():
    f = _features()
    assert fp.similarity(f, json.loads(json.dumps(f))) == 1.0


def test_similarity_disjoint_is_zero():
    a = _features(lane="static", project_type="linux")
    b = _features(lane="algorithm", project_type="android",
                  target_kind={"language": "python", "entry_suffix": ".py"})
    assert fp.similarity(a, b) == 0.0


def test_similarity_empty_union_is_zero():
    assert fp.similarity({}, {}) == 0.0


def test_similarity_degraded_evidence_never_fabricates_distance():
    """Spec R2: missing evidence reduces similarity via fewer shared
    tokens, never via invented opposing tokens — partial overlap stays
    strictly inside (0, 1)."""
    packed = _features(packer_flags={
        "packing": True, "obfuscation": True, "anti_analysis": True,
        "surface_reduction": False,
        "detected_packers": ["UPX"], "detected_obfuscators": ["DexGuard"]})
    same_task_unprobed = _features()  # identical lane/ptype/lang/entry
    s = fp.similarity(packed, same_task_unprobed)
    assert 0.0 < s < 1.0
    # and the un-probed twin is MORE similar to the un-probed original
    # than the packed variant is (shared identity tokens count)
    assert fp.similarity(same_task_unprobed, _features()) == 1.0


def test_similarity_null_fields_emit_no_tokens():
    """A null lane and an absent lane agree on nothing — absence never
    scores, so two null-lane vectors do not gain a shared token for
    the nullity itself."""
    a = _features(lane=None)
    b = _features(lane=None)
    assert fp.similarity(a, b) == 1.0  # every PRESENT token shared
    c = _features(lane=None, project_type="android")
    assert 0.0 < fp.similarity(a, c) < 1.0


def test_similarity_is_symmetric_and_deterministic():
    a = _features()
    b = _features(lane="dynamic")
    assert fp.similarity(a, b) == fp.similarity(b, a)
    assert fp.similarity(a, b) == fp.similarity(a, b)


# ------------------------------------------------------ 3. feature pool

def test_pool_outcome_mapping():
    """Spec R3 outcome rule: settled credit when non-null (split
    (c, 1−c)); else landed=1.0 / timeout|blocked=0.0; unknown
    excluded."""
    feats = _features()
    table = [
        _table_row("r-1", feats, [
            _outcome("fam-a", settled=True, credit=0.75),   # (.75, .25)
            _outcome("fam-a", act_result="landed"),         # (1, 0)
            _outcome("fam-a", act_result="timeout"),        # (0, 1)
            _outcome("fam-a", act_result="unknown"),        # excluded
        ]),
    ]
    pool = fp.pool_for(table, feats, "fam-a")
    assert pool.success == pytest.approx(0.75 + 1.0)
    assert pool.failure == pytest.approx(0.25 + 1.0)
    assert pool.rows == 3


def test_pool_is_similarity_weighted():
    """A row at similarity 0.5 contributes half mass (identical
    features = 1.0 similarity reference)."""
    same = _features()
    near = _features(lane="dynamic")  # shares ptype/lang/entry only
    s_near = fp.similarity(same, near)
    assert 0.0 < s_near < 1.0
    table = [
        _table_row("r-near", near, [_outcome("fam-a", act_result="landed")]),
    ]
    pool = fp.pool_for(table, same, "fam-a")
    assert pool.success == pytest.approx(s_near)
    assert pool.failure == pytest.approx(0.0)


def test_pool_excludes_other_families_and_honors_exclude_run():
    feats = _features()
    other = _features(lane="dynamic")
    table = [
        _table_row("r-1", feats, [_outcome("fam-a", act_result="landed"),
                                  _outcome("fam-b", act_result="landed")]),
        _table_row("r-2", feats, [_outcome("fam-a", act_result="landed")]),
    ]
    pool_a = fp.pool_for(table, feats, "fam-a")
    assert pool_a.success == pytest.approx(2.0)
    pool_b = fp.pool_for(table, feats, "fam-b")
    assert pool_b.success == pytest.approx(1.0)
    # the replay split: the held-out run excluded by EXPLICIT run id
    pool_ex = fp.pool_for(table, feats, "fam-a", exclude_run="r-1")
    assert pool_ex.success == pytest.approx(1.0)
    assert pool_ex.rows == 1


def test_pool_unknown_only_outcome_is_empty():
    table = [_table_row("r-1", _features(),
                        [_outcome("fam-a", act_result="unknown")])]
    pool = fp.pool_for(table, _features(), "fam-a")
    assert pool.success == 0.0 and pool.failure == 0.0 and pool.rows == 0


def _shrink_store():
    """The test_q_cells_429 shrinkage fixture shape (γ=1 exact masses):
    anchor-family: 10 successes at aaaa + 1 good at bbbb."""
    rows = [
        {"schema": q_cells.OBS_SCHEMA, "ts": "t", "source": "settlement",
         "signature_hash": "aaaaaaaaaaaa", "method_family": "anchor-family",
         "claim": None, "agent": None, "credit": 1.0}] * 10
    rows += [{"schema": q_cells.OBS_SCHEMA, "ts": "t",
              "source": "settlement", "signature_hash": "bbbbbbbbbbbb",
              "method_family": "anchor-family",
              "claim": None, "agent": None, "credit": 1.0}]
    return q_cells.InMemoryStore(rows)


def test_cell_posterior_no_pool_is_the_pinned_formula():
    """The no-pool path stays bit-identical to the pre-change kernel
    (this store: family = 11 successes; bbbb cell = 1 local success →
    LOO anchor 10s → m = 11/12, w = 8 → alpha = 1 + 8·(11/12) + 1,
    beta = 1 + 8·(1/12))."""
    fold = q_cells.fold(_shrink_store(), gamma=1.0)
    a, b = q_cells.cell_posterior(fold, "bbbbbbbbbbbb", "anchor-family")
    assert a == pytest.approx(28.0 / 3.0, abs=1e-9)
    assert b == pytest.approx(5.0 / 3.0, abs=1e-9)


def test_cell_posterior_zero_pool_is_bit_identical():
    fold = q_cells.fold(_shrink_store(), gamma=1.0)
    a0, b0 = q_cells.cell_posterior(fold, "bbbbbbbbbbbb", "anchor-family")
    a1, b1 = q_cells.cell_posterior(
        fold, "bbbbbbbbbbbb", "anchor-family",
        feature_pool=fp.FeaturePool(success=0.0, failure=0.0, rows=0))
    assert (a0, b0) == (a1, b1)


def test_pool_tilts_the_anchor_strictly():
    fold = q_cells.fold(_shrink_store(), gamma=1.0)
    a0, b0 = q_cells.cell_posterior(fold, "cccccccccccc", "anchor-family")
    a1, b1 = q_cells.cell_posterior(
        fold, "cccccccccccc", "anchor-family",
        feature_pool=fp.FeaturePool(success=4.0, failure=0.0, rows=4))
    assert a1 / (a1 + b1) > a0 / (a0 + b0)


def test_pool_shares_the_one_shrink_cap():
    """A huge feature pool cannot push the anchor weight past
    SHRINK_CAP: the observable bound is alpha + beta = 2 + w + local,
    capped at 2 + SHRINK_CAP for a cold cell (w = SHRINK_CAP exactly
    once the anchor mass exceeds it)."""
    fold = q_cells.fold(_shrink_store(), gamma=1.0)
    huge = fp.FeaturePool(success=1000.0, failure=0.0, rows=1000)
    a, b = q_cells.cell_posterior(fold, "000000000000", "anchor-family",
                                  feature_pool=huge)
    assert a + b == pytest.approx(2.0 + q_cells.SHRINK_CAP, abs=1e-9)
    # sanity: without the pool the same cell also sits at the cap
    # (family mass 11 > 8 already caps)
    a0, b0 = q_cells.cell_posterior(fold, "000000000000", "anchor-family")
    assert a0 + b0 == pytest.approx(2.0 + q_cells.SHRINK_CAP, abs=1e-9)
    # and the cap is real: a 20-mass pool and a 1000-mass pool produce
    # DIFFERENT anchor means (mass shifts m, never the borrowed weight)
    mid = fp.FeaturePool(success=20.0, failure=0.0, rows=20)
    a2, b2 = q_cells.cell_posterior(fold, "000000000000", "anchor-family",
                                    feature_pool=mid)
    assert a2 != a and (a2 + b2) == pytest.approx(
        2.0 + q_cells.SHRINK_CAP, abs=1e-9)


def test_sampler_threads_the_pool_when_flag_on(tmp_path, monkeypatch):
    """Flag on + table + features: the receipt's candidates carry the
    additive feature_prior block and the pool changes the posterior."""
    _set_flag("1", monkeypatch)
    feats = _features()
    table = _write_table(tmp_path, [
        _table_row("r-1", feats, [
            _outcome("fam-a", act_result="landed")] * 6),
        _table_row("r-2", feats, [
            _outcome("fam-b", act_result="timeout")] * 6),
    ])
    store = q_cells.InMemoryStore([])
    r = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store,
        features=feats, feature_table=table, rng=None)
    cand = r["candidates"]["fam-a"]
    assert cand["feature_prior"]["rows"] == 6
    assert cand["feature_prior"]["pool_success"] == pytest.approx(6.0)
    # empty store: anchor = pool alone -> m = 7/8, w = 6 -> alpha =
    # 1 + 6*(7/8) = 6.25, beta = 1 + 6*(1/8) = 1.75
    assert cand["alpha"] == pytest.approx(6.25, abs=1e-9)
    assert cand["beta"] == pytest.approx(1.75, abs=1e-9)
    # fam-b: the identical-features pool of failures mirrors it
    assert r["candidates"]["fam-b"]["alpha"] == pytest.approx(
        1.75, abs=1e-9)
    assert r["candidates"]["fam-b"]["beta"] == pytest.approx(
        6.25, abs=1e-9)
    # the receipt's top-level keys stay additive-compatible (schema
    # unchanged; no key removed)
    assert r["schema"] == q_cells.SAMPLE_SCHEMA


def test_flag_on_without_matching_rows_receipt_stays_identical(
        tmp_path, monkeypatch):
    """Flag on, table present, but NO row matches any candidate
    family: zero-row pools never ride the receipt and the receipt is
    byte-identical to flag-off (the receipt-level inertness pin)."""
    _set_flag("1", monkeypatch)
    feats = _features()
    table = _write_table(tmp_path, [
        _table_row("r-other", _features(lane="dynamic"),
                   [_outcome("unrelated-family", act_result="landed")])])
    store = q_cells.InMemoryStore([])
    r1 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store,
        features=feats, feature_table=table, rng=None)
    _set_flag(None, monkeypatch)
    r2 = q_cells.sample_method_family(
        "5e5e5e5e5e5e", {"fam-a": 0.5, "fam-b": 0.5}, store, rng=None)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert "feature_prior" not in r1["candidates"]["fam-a"]


# ------------------------------------------------- 4. probe-arm ranking

def test_cold_start_ranks_probes_above_methods():
    order = fp.rank_arms(_features(),
                         method_scores={"static-decompile": 0.0,
                                        "crypto-core-identification": 0.0})
    names = [a["arm"] for a in order]
    assert set(fp.PROBE_ARMS) <= set(names[:2])
    assert all(a["kind"] == "probe" for a in order[:2])


def test_known_categories_demote_the_probe():
    feats = _features(packer_flags={
        "packing": True, "obfuscation": True, "anti_analysis": True,
        "surface_reduction": False,
        "detected_packers": ["UPX"], "detected_obfuscators": ["DexGuard"]},
        probe_outputs={
            "die": {"prescan_state": "available", "usable": True,
                    "detected_packer": "UPX", "entropy_max": 7.1},
            "apkid": {"prescan_state": "available", "usable": True,
                      "packers": ["UPX"], "obfuscators": ["DexGuard"]}})
    order = fp.rank_arms(feats,
                         method_scores={"static-decompile": 3.0})
    probes = [a for a in order if a["kind"] == "probe"]
    assert all(a["gain"] == 0.0 for a in probes)
    assert order[0]["kind"] == "method"  # informative method outranks


def test_probe_gain_partial_knowledge():
    feats = _features()  # lang/entry known; no packer knowledge
    die = next(a for a in fp.rank_arms(feats, {}) if a["arm"] == "die-probe")
    assert 0.0 < die["gain"] < 1.0


def test_rank_arms_is_a_pure_deterministic_function():
    feats = _features()
    ms = {"static-decompile": 0.0, "crypto-core-identification": 3.0}
    o1 = fp.rank_arms(feats, ms)
    o2 = fp.rank_arms(json.loads(json.dumps(feats)), dict(ms))
    assert o1 == o2


# ------------------------------------------- 5. #669 retirement (B2)

def _report(*items):
    return SimpleNamespace(items=list(items))


def _item(name, status, fix=None):
    return SimpleNamespace(name=name, status=status, fix=fix)


def test_no_per_project_type_probe_set_note_anywhere():
    """The grep-proof pin: the retired phrase never appears in the
    promise output for ANY report shape."""
    ws = Path("/nonexistent-ws")
    for rep in (_report(_item("jadx", "PASS")),
                _report(_item("die", "WARN")),
                _report()):
        p = intake_promise.build(rep, None, ws)
        assert "project_type's probe set" not in json.dumps(p)
        for tool in ("apkid", "die"):
            assert tool in p["prescan"]  # both tools recorded, always


def test_prescan_direct_fact_chain(tmp_path, monkeypatch):
    """Item absent from the report (per-type membership rule deleted):
    direct presence facts decide — which() found, else evidence file,
    else missing. Host-independent via injected probes."""
    ws = tmp_path / "ws"
    ws.mkdir()
    rep = _report(_item("jadx", "PASS"))  # no apkid/die items at all
    monkeypatch.setattr(intake_promise, "_which_tool",
                        lambda tool: "/usr/bin/fake" if tool == "apkid"
                        else None)
    p = intake_promise.build(rep, None, ws)
    assert p["prescan"]["apkid"]["state"] == "available"
    assert p["prescan"]["die"]["state"] == "missing"
    # evidence presence upgrades die: the artifact exists, fact holds
    # (#460 intake battery fold: the artifact must be USABLE — a
    # surviving data block — a parseable-but-empty file is an absence)
    (ws / "evidence").mkdir()
    (ws / "evidence" / "die.json").write_text(
        '{"detects": [{"values": [{"name": "UPX", "type": "packer"}]}],'
        ' "derived": {"detected_packer": "upx"}}', encoding="utf-8")
    p2 = intake_promise.build(rep, None, ws)
    assert p2["prescan"]["die"]["state"] == "available"


def test_prescan_report_item_still_wins(tmp_path):
    """Capability facts from the toolchain report keep their authority
    when present (PASS→available / WARN→degraded / FAIL→missing)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    rep = _report(_item("apkid", "FAIL", fix="pip install apkid"))
    p = intake_promise.build(rep, None, ws)
    assert p["prescan"]["apkid"]["state"] == "missing"
    rep2 = _report(_item("apkid", "WARN"))
    p2 = intake_promise.build(rep2, None, ws)
    assert p2["prescan"]["apkid"]["state"] == "degraded"


def test_obligation_flag_off_is_status_quo(tmp_path, monkeypatch):
    _set_flag(None, monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("lane: malware\n",
                                       encoding="utf-8")
    p = intake_promise.build(_report(), {"lane": "malware"}, ws)
    ob = p["prescan_obligation"]
    assert ob["lane"] == "malware"
    assert ob["required"] == list(intake_promise.OBLIGATION)
    assert "#669" in ob["note"]


def test_obligation_flag_on_is_probes_as_arms(tmp_path, monkeypatch):
    _set_flag("1", monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("lane: malware\n",
                                       encoding="utf-8")
    p = intake_promise.build(_report(), {"lane": "malware"}, ws)
    ob = p["prescan_obligation"]
    assert ob["required"] == []
    assert "ranked" in ob
    # the ranked order IS the prior's ranking over the SAME workspace
    # features (cold ws here: every probe category unknown)
    expected = fp.rank_arms(fp.features_from_workspace(ws), {})
    assert ob["ranked"] == expected
    assert all(a["kind"] == "probe" for a in ob["ranked"])


def test_capability_checks_surface_untouched():
    """The retirement touches only the promise face: the toolchain
    CHECK_SETS contract (capability facts) is imported and unchanged."""
    import toolchain  # noqa: PLC0415
    assert "apkid" in toolchain.CHECK_SETS["android"]
    assert "die" in toolchain.CHECK_SETS["windows"]


# --------------------------------------------- 6. workspace adapter

def test_features_from_workspace_degrades_task_kind(tmp_path):
    """Live face has no corpus task_dir: target_kind degrades to nulls,
    everything else extracts from the live task_spec/evidence."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("lane: static\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text("project_type=linux\n",
                                           encoding="utf-8")
    feats = fp.features_from_workspace(ws)
    assert feats["lane"] == "static"
    assert feats["project_type"] == "linux"
    assert feats["target_kind"]["language"] is None
    assert feature_mining.validate_row({
        "schema": feature_mining.SCHEMA, "run_id": "x", "family": "f",
        "task_id": "t", "signature_hash": feature_mining.signature_hash(feats),
        "features": feats, "outcomes": []}) == []


def test_default_table_path_is_the_mined_location(tmp_path):
    assert fp.default_table_path(tmp_path) == \
        tmp_path / "runs" / "feature-table.jsonl"
