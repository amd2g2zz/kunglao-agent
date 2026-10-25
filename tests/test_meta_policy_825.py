# -*- coding: utf-8 -*-
"""tests/test_meta_policy_825.py — #825 the meta-policy rewire (P2).

The unified RL model's second card (#806 axis, after the #824 contract):
  1. context features assembled from REAL sources (task_spec.yaml,
     evidence/die.json + apkid.json, the #812 capability facts — read-
     only, a feature face never executes a probe);
  2. commit selection conditions on the context vector — the value
     table (P1 derived view) scored with overlap weighting and
     n-shrinkage toward the cold-start prior; the family bandit
     (q_cells) consult is confined to the prior face (the demotion is
     grep-pinned);
  3. pool retrieval at the decision points (episode_start +
     commit_boundary) feeding the executor context through the SINGLE
     dispatch interface (envelope block meta-policy/1) wired into
     build_dispatch_context fail-open;
  4. exactly three learnable knob groups (value-table weights /
     utility-score weights / retrieval threshold+count) and the two
     component-ablation switches;
  5. the utility chain retrieved -> cited -> improved, measured on the
     episode.

Fixtures are synthetic workspaces; pool episodes are seeded through the
unmodified #824 faces. No real probes, no telemetry, no settlement/
verifier semantics touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))

import rlvr.episode_pool as pool  # noqa: E402
import rlvr.episode_schema as es  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import meta_context as mc  # noqa: E402
from rlvr import meta_policy as mp  # noqa: E402
from rlvr import meta_retrieval as mr  # noqa: E402
import dispatch_context as dc  # noqa: E402


# ---------------------------------------------------------------- fixtures

_META_ENV = ("KUNGLAO_META_RETRIEVAL", "KUNGLAO_META_VALUE_TABLE",
             "KUNGLAO_META_RETRIEVE_MAX", "KUNGLAO_META_MIN_UTILITY",
             "KUNGLAO_META_W_REWARD", "KUNGLAO_META_W_COST",
             "KUNGLAO_META_W_PRIOR", "KUNGLAO_META_N_SHRINK",
             "KUNGLAO_META_W_CITATION", "KUNGLAO_META_W_RETRIEVAL")


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "evidence").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _pass_verification(ws: Path, claim: str = "C-1") -> Path:
    p = ws / "runs" / f"verification-{claim}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# verification {claim}\n\nverdict: verified\n",
                 encoding="utf-8")
    return p


def _episode(claim: str, features: list[str], action: str, *,
             r: float | None = 1.0, tokens: float = 0.0,
             fragments: list[str] | None = None) -> dict:
    doc = {
        "schema": "episode/1",
        "id": f"E-{claim}",
        "claim": claim,
        "created": "2026-10-25T00:00:00Z",
        "updated": "2026-10-25T00:00:00Z",
        "context_features": features,
        "commits": [
            {"seq": 1, "action": action, "summary": f"ran {action}"},
        ],
        "outcome": {"status": "completed", "verified": True,
                    "evidence_ref": ""},
        "cost": {"tokens": tokens, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.5},
        "reusable_fragments": fragments or [f"{action} worked here"],
        "milestones": [],
        "attribution": "",
        "surprise": False,
    }
    if r is not None:
        doc["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                         "cost_term": 0.0, "r": r}
    return doc


def _seed(ws: Path, doc: dict) -> None:
    _pass_verification(ws, str(doc["claim"]))
    pool.write_episode(ws, doc)


def _bandit_row(family: str, credit: float, sig: str = "sig") -> dict:
    # #804 regen: keyed shape — the fold banks arm_key-carrying rows only
    return {"schema": "q-cell-obs/1", "signature_hash": sig,
            "method_family": family, "credit": credit,
            "credit_kind": "solve", "source": "dispatch",
            "arm_key": f"{family}|facts_snapshot|none|0"}


# ------------------------------------------------- 1. feature sources

class TestFeatureSources:
    def test_task_spec_features(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(yaml.safe_dump({
            "lane": "malware",
            "verification_method": "replay-evidence",
            "depth": "deep",
            "primary_questions": [
                {"id": "q1", "q": "family?", "need": "model_selection",
                 "candidates": ["vidar", "wingo"]},
            ],
            "constraints": {"dynamic_re": "forbidden"},
        }), encoding="utf-8")
        feats = mc.assemble(ws)
        for tok in ("lane-malware", "dyn-forbidden", "depth-deep",
                    "verif-replay-evidence", "fam-vidar", "fam-wingo"):
            assert tok in feats, f"missing {tok} in {feats}"

    def test_die_and_apkid_protection_features(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "derived": {"detected_packer": "UPX",
                        "section_table": [{"entropy": 7.6}]},
        }), encoding="utf-8")
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "status": "ok",
            "summary": {"packer": [], "obfuscator": ["DexGuard"]},
        }), encoding="utf-8")
        feats = mc.assemble(ws)
        assert "packer-upx" in feats
        assert "obf-dexguard" in feats
        assert "entropy-high" in feats

    def test_capability_features_are_read_only(self, tmp_path,
                                               monkeypatch):
        ws = _mk_ws(tmp_path)
        (ws / "runs" / "env-state.json").write_text(json.dumps({
            "per_capability": {"host_frida": {"status": "ok"},
                               "device_root": {"status": "fail"}},
        }), encoding="utf-8")
        executed: list[str] = []

        def _recorder(name):
            def _probe(*a, **k):
                executed.append(name)
                return {"status": "ok", "detail": ""}
            return _probe

        monkeypatch.setattr("capability_probe.PROBES",
                            {k: _recorder(k) for k in
                             ("host_frida", "device_root")})
        feats = mc.assemble(ws)
        assert "cap-host-frida-ok" in feats
        assert "cap-device-root-fail" in feats
        assert executed == [], "the feature face must never probe"

    def test_absent_sources_degrade_and_cap(self, tmp_path):
        ws = _mk_ws(tmp_path)  # nothing but the register
        assert mc.assemble(ws) == []
        ws2 = _mk_ws(tmp_path, "ws2")
        (ws2 / "task_spec.yaml").write_text(yaml.safe_dump({
            "primary_questions": [
                {"id": f"q{i}", "need": "model_selection",
                 "candidates": [f"fam-{i}" for i in range(30)]}
                for i in range(5)
            ]}), encoding="utf-8")
        feats2 = mc.assemble(ws2)
        assert len(feats2) <= es._FEATURE_MAX
        assert all(len(f) <= es._FEATURE_TOKEN_MAX for f in feats2)
        assert feats2 == sorted(feats2)

    def test_deterministic(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "evidence" / "die.json").write_text(json.dumps(
            {"derived": {"detected_packer": "UPX"}}), encoding="utf-8")
        assert mc.assemble(ws) == mc.assemble(ws)


# ------------------------------------- 2. context-conditional selection

_COMBOS = [(f"fam-{i}", f"ca-{i}", f"cb-{i}") for i in range(17)]


class TestCommitSelection:
    @pytest.mark.parametrize("fam,ca,cb", _COMBOS)
    def test_same_family_different_context_different_commit(
            self, tmp_path, monkeypatch, fam, ca, cb):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-A", [fam, ca], "persist"))
        _seed(ws, _episode("C-B", [fam, cb], "switch"))
        a = mp.select_commit(ws, [fam, ca])
        b = mp.select_commit(ws, [fam, cb])
        assert a["action"] == "persist", a
        assert b["action"] == "switch", b
        assert a["source"] == "value_table"
        assert b["source"] == "value_table"

    def test_cold_start_empty_pool_rides_prior(self, tmp_path,
                                               monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        out = mp.select_commit(ws, ["lane-malware"])
        assert out["source"] == "prior"
        assert out["action"] == "select"  # canonical tie-break on zeroes

    def test_prior_reads_bandit_family_stats(self, tmp_path,
                                             monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        assert cl.append(ws, "experience", _bandit_row("fam-x", 1.0))
        prior = mp.cold_start_prior(ws, ["lane-malware"], family="fam-x")
        # a winning family favors persisting over switching
        assert prior["persist"] > prior["switch"]
        out = mp.select_commit(ws, ["lane-malware"], family="fam-x",
                               actions=("persist", "tune", "switch"))
        assert out["action"] == "persist"
        assert out["source"] == "prior"

    def test_prior_exogenous_dynamic_constraint(self, tmp_path,
                                                monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        base = mp.cold_start_prior(ws, ["lane-malware"])
        dyn = mp.cold_start_prior(ws, ["lane-malware", "dyn-forbidden"])
        assert dyn["tune"] < base["tune"] == base["switch"]

    def test_cost_weight_is_a_knob(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-A", ["fam-x"], "persist", tokens=9000.0))
        _seed(ws, _episode("C-B", ["fam-x"], "switch", tokens=1000.0))
        menu = ("persist", "switch")
        out = mp.select_commit(ws, ["fam-x"], actions=menu)
        assert out["action"] == "switch"  # cheaper at equal reward
        monkeypatch.setenv("KUNGLAO_META_W_COST", "0")
        out2 = mp.select_commit(ws, ["fam-x"], actions=menu)
        assert out2["action"] == "persist"  # cost ignored: canonical tie

    def test_deterministic_repeat(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-A", ["fam-x", "ca"], "persist"))
        a1 = mp.select_commit(ws, ["fam-x", "ca"])
        a2 = mp.select_commit(ws, ["fam-x", "ca"])
        assert a1 == a2

    def test_phase_action_vocabulary(self):
        assert mp.PHASE_ACTIONS["episode_start"] == ("select",)
        assert set(mp.PHASE_ACTIONS["commit_boundary"]) == \
            {"persist", "tune", "switch"}


# --------------------------------------- 3. retrieval at decision points

class TestRetrievalAssembly:
    def test_cases_at_both_phases(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["fam-x", "ca"], "persist"))
        for phase in ("episode_start", "commit_boundary"):
            ctx = mr.assemble(ws, ["fam-x", "ca"], phase=phase)
            ids = [c["claim"] for c in ctx["cases"]]
            assert "C-9" in ids, (phase, ctx)

    def test_budget_cap_and_threshold_knobs(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["fam-x"], "persist"))
        _seed(ws, _episode("C-2", ["fam-x"], "switch"))
        monkeypatch.setenv("KUNGLAO_META_RETRIEVE_MAX", "1")
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert len(ctx["cases"]) == 1
        monkeypatch.setenv("KUNGLAO_META_MIN_UTILITY", "0.9")
        ctx2 = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx2["cases"] == []
        assert ctx2["budget"]["min_utility"] == pytest.approx(0.9)

    def test_utility_weights_rank_cases(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        c1 = _episode("C-1", ["fam-x"], "persist")
        c1["utility"] = {"retrievals": 1, "citations": 3, "utility": 0.5}
        c2 = _episode("C-2", ["fam-x"], "switch")
        c2["utility"] = {"retrievals": 9, "citations": 0, "utility": 0.5}
        _seed(ws, c1)
        _seed(ws, c2)
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx["cases"][0]["claim"] == "C-1"
        monkeypatch.setenv("KUNGLAO_META_W_CITATION", "0")
        ctx2 = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx2["cases"][0]["claim"] == "C-2"

    def test_playbook_rides_the_context(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["fam-x"], "persist"))
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx["playbook"], "playbook view must attach"
        assert any("persist worked here" in f
                   for g in ctx["playbook"] for f in g["fragments"])

    def test_blocked_phase_is_legal(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["fam-x"], "switch"))
        ctx = mr.assemble(ws, ["fam-x"], phase="blocked")
        assert [c["claim"] for c in ctx["cases"]] == ["C-1"]

    def test_illegal_phase_refused(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        with pytest.raises(pool.ReadRefused):
            mr.assemble(ws, ["fam-x"], phase="mid_execution")


# ----------------------------------------- 4. the single dispatch interface

class TestEnvelopeInterface:
    def test_envelope_block_shape(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text("lane: malware\n",
                                           encoding="utf-8")
        _seed(ws, _episode("C-9", ["lane-malware", "ca"], "persist"))
        block = mp.envelope_block(ws, "C-1", phase="episode_start")
        assert block["schema"] == "meta-policy/1"
        assert block["claim"] == "C-1"
        assert block["phase"] == "episode_start"
        assert set(block["commit"]) == {"action", "scores", "source"}
        assert block["commit"]["action"] == "select"  # the phase menu
        assert "C-9" in [c["claim"] for c in block["context"]["cases"]]
        assert "max_cases" in block["context"]["budget"]

    def test_render_block_names_commit_and_cases(self, tmp_path,
                                                 monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text("lane: malware\n",
                                           encoding="utf-8")
        _seed(ws, _episode("C-9", ["lane-malware", "ca"], "persist"))
        text = mp.render_block(
            mp.envelope_block(ws, "C-1", phase="episode_start"))
        assert "kunglao meta-policy" in text
        assert "select" in text
        assert "C-9" in text

    def test_dispatch_context_carries_meta_block(self, tmp_path,
                                                 monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["lane-malware", "ca"], "persist"))
        (ws / "task_spec.yaml").write_text("lane: malware\n",
                                           encoding="utf-8")
        ctx = dc.build_dispatch_context(ws=ws, claim_id="C-1", tier=1,
                                        tools=[], agent_name="x")
        meta = ctx.get("meta_policy")
        assert meta and meta["schema"] == "meta-policy/1"
        assert meta["commit"]["action"] == "select"  # the phase menu
        assert "C-9" in [c["claim"] for c in meta["context"]["cases"]]

    def test_episode_phase_rule(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        assert mp.episode_phase(ws, "C-1") == "episode_start"
        _seed(ws, _episode("C-1", ["fam-x"], "persist"))
        assert mp.episode_phase(ws, "C-1") == "commit_boundary"
        assert mp.episode_phase(ws, "C-2") == "episode_start"

    def test_claim_with_episode_is_at_commit_boundary(self, tmp_path,
                                                      monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text("lane: malware\n",
                                           encoding="utf-8")
        _seed(ws, _episode("C-1", ["lane-malware"], "persist"))
        _seed(ws, _episode("C-9", ["lane-malware"], "switch"))
        ctx = dc.build_dispatch_context(ws=ws, claim_id="C-1", tier=1,
                                        tools=[], agent_name="x")
        meta = ctx.get("meta_policy")
        assert meta["phase"] == "commit_boundary"
        assert set(meta["commit"]["scores"]) == \
            {"persist", "tune", "switch"}
        ids = [c["claim"] for c in meta["context"]["cases"]]
        assert "C-9" in ids and "C-1" in ids

    def test_dispatch_context_meta_is_fail_open(self, tmp_path,
                                                monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)

        def _boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(mp, "envelope_block", _boom)
        ctx = dc.build_dispatch_context(ws=ws, claim_id="C-1", tier=1,
                                        tools=[], agent_name="x")
        assert "meta_policy" not in ctx


# ------------------------------------------------- 5. the three knobs

class TestKnobs:
    def test_documented_defaults(self, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        k = mp.knobs()
        assert k["retrieve_max"] == 3
        assert k["min_utility"] == pytest.approx(0.0)
        assert k["w_reward"] == pytest.approx(1.0)
        assert k["retrieval"] is True
        assert k["value_table"] is True

    def test_env_overrides(self, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("KUNGLAO_META_RETRIEVE_MAX", "7")
        monkeypatch.setenv("KUNGLAO_META_MIN_UTILITY", "0.25")
        monkeypatch.setenv("KUNGLAO_META_W_PRIOR", "0.5")
        k = mp.knobs()
        assert k["retrieve_max"] == 7
        assert k["min_utility"] == pytest.approx(0.25)
        assert k["w_prior"] == pytest.approx(0.5)


# --------------------------------------------- 6. component ablations

class TestAblations:
    def test_retrieval_off_removes_component(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["fam-x"], "persist"))
        monkeypatch.setenv("KUNGLAO_META_RETRIEVAL", "0")
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx["cases"] == [] and ctx["playbook"] == []
        assert ctx["budget"]["retrieval"] is False
        doc, _body = es.read_episode_file(pool.episode_path(ws, "C-9"))
        assert doc["utility"]["retrievals"] == 0, \
            "ablated retrieval must not bump pool counters"

    def test_value_table_off_removes_contextual_term(self, tmp_path,
                                                     monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-A", ["fam-x", "ca"], "persist"))
        _seed(ws, _episode("C-B", ["fam-x", "cb"], "switch"))
        monkeypatch.setenv("KUNGLAO_META_VALUE_TABLE", "0")
        a = mp.select_commit(ws, ["fam-x", "ca"])
        b = mp.select_commit(ws, ["fam-x", "cb"])
        assert a["action"] == b["action"]
        assert a["source"] == "prior_ablated"


# --------------------------------------------- 7. the bandit demotion pin

class TestBanditDemotion:
    @staticmethod
    def _src(rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_q_cells_confined_to_the_prior_face(self):
        src = self._src("scripts/rlvr/meta_policy.py")
        start = src.index("def cold_start_prior")
        nxt = src.find("\ndef ", start + 1)
        span = src[start: nxt if nxt != -1 else len(src)]
        assert "q_cells" in span, "the prior must consult the bandit"
        assert src.count("q_cells") == span.count("q_cells"), \
            "no meta-policy face other than the prior may consult it"

    @pytest.mark.parametrize("rel", [
        "scripts/rlvr/meta_retrieval.py",
        "scripts/dispatch_context.py",
        "hooks/dispatch_gate.py",
    ])
    def test_no_bandit_consult_off_the_prior(self, rel):
        src = self._src(rel)
        for needle in ("q_cells", "sample_method_family", "meta_arms"):
            assert needle not in src, f"{rel} consults {needle}"


# ------------------------------------------------ 8. the utility chain

class TestUtilityChain:
    def test_retrieved_cited_improved(self, tmp_path, monkeypatch):
        for name in _META_ENV:
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text("lane: malware\n",
                                           encoding="utf-8")
        _seed(ws, _episode("C-9", ["lane-malware"], "persist"))
        block = mp.envelope_block(ws, "C-1", phase="episode_start")
        case_ids = [c["claim"] for c in block["context"]["cases"]]
        doc = _episode("C-1", ["fam-x"], "persist")
        doc = mp.stamp_retrieved(doc, case_ids)
        doc = mp.record_citation(doc, 1, ["C-9"])
        doc["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                         "cost_term": 0.0, "r": 1.0}
        chain = mp.utility_chain(doc)
        assert chain["retrieved"] == 1
        assert chain["cited"] == 1
        assert chain["cited_from_retrieved"] == 1
        assert chain["improved"] is True

    def test_additive_fields_stay_schema_legal(self):
        doc = _episode("C-1", ["fam-x"], "persist")
        doc = mp.record_citation(mp.stamp_retrieved(doc, ["C-9"]), 1,
                                 ["C-9"])
        assert es.validate_episode(doc)["commits"][0]["cited"] == ["C-9"]

    def test_record_citation_unknown_seq_refuses(self):
        with pytest.raises(ValueError):
            mp.record_citation(_episode("C-1", ["f"], "persist"), 99,
                               ["C-9"])

    def test_no_reward_is_not_improved(self):
        doc = _episode("C-1", ["f"], "persist", r=None)
        assert mp.utility_chain(doc)["improved"] is False


# ------------------------------------------------- 9. registration faces

class TestRegistration:
    def test_rlvr_facade_exposes_the_three_modules(self):
        import rlvr  # noqa: PLC0415
        for name in ("meta_context", "meta_policy", "meta_retrieval"):
            assert name in rlvr.__all__, name
            assert getattr(rlvr, name) is not None

    def test_fast_tier_registry_lists_this_module(self):
        tiers = (ROOT / "tests" / "_tiers.py").read_text(encoding="utf-8")
        assert '"test_meta_policy_825"' in tiers

    def test_scripts_readme_catalogs_the_new_modules(self):
        rows = (ROOT / "scripts" / "README.md").read_text(
            encoding="utf-8")
        for name in ("rlvr/meta_context.py", "rlvr/meta_policy.py",
                     "rlvr/meta_retrieval.py"):
            assert name in rows, name
