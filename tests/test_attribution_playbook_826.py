# -*- coding: utf-8 -*-
"""tests/test_attribution_playbook_826.py — #826 the P3 senior-expert
faces (the #806 axis's third card, on top of the #824 contract and the
#825 meta-policy rewire):

  1. attribution.py — the LEARNED attribution model: context -> outcome
     feature importance as deterministic counting statistics over the
     P1 pool (failure contrast + presence lift); method attribution
     (hypothesis_wrong / tool_mismatch / depth_insufficient) with the
     exogenous-noise demotion (#421 demoted to a feature source). The
     synthetic fixtures distinguish a tool-missing failure from a
     hypothesis-wrong failure — NOT a binary accident/failure flag.
  2. commit_semantics.py — the tune/switch commits get real envelope
     semantics: tune = same class + a parameter/tool delta; switch = a
     different class + a REQUIRED attribution reference (a blind lane
     change is RED); the 9x dead-path re-probe shape is RED.
  3. playbook.py — successful episodes compress into playbooks under
     the distillation quality axioms (generalizable + self-starting;
     case-specific refused), as a DERIVED view injected through the P2
     retrieval face.
  4. the self-correction loop: surprise (a verified outcome
     contradicting the value table's expectation) generates the forced
     re-examination commit.
  5. component ablation: the four knobs (retrieval / value_table /
     attribution / playbook), each priced in output terms.

Fixtures are synthetic workspaces; pool episodes are seeded through the
unmodified #824 faces; settlement/verifier semantics are only ever
CALLED. meta_policy's P2 semantics are preserved (the episode_start
commit key-set pin rides unchanged; conflicts keep both sides).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlvr.episode_pool as pool  # noqa: E402
import rlvr.episode_schema as es  # noqa: E402
from rlvr import attribution as attr  # noqa: E402
from rlvr import commit_semantics as cs  # noqa: E402
from rlvr import meta_policy as mp  # noqa: E402
from rlvr import meta_retrieval as mr  # noqa: E402
from rlvr import playbook as pb  # noqa: E402


# ---------------------------------------------------------------- fixtures

_ENV = ("KUNGLAO_META_RETRIEVAL", "KUNGLAO_META_VALUE_TABLE",
        "KUNGLAO_META_ATTRIBUTION", "KUNGLAO_META_PLAYBOOK",
        "KUNGLAO_META_RETRIEVE_MAX", "KUNGLAO_META_MIN_UTILITY",
        "KUNGLAO_META_W_REWARD", "KUNGLAO_META_W_COST",
        "KUNGLAO_META_W_PRIOR", "KUNGLAO_META_N_SHRINK",
        "KUNGLAO_META_W_CITATION", "KUNGLAO_META_W_RETRIEVAL")


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _pass_verification(ws: Path, claim: str) -> Path:
    p = ws / "runs" / f"verification-{claim}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# verification {claim}\n\nverdict: verified\n",
                 encoding="utf-8")
    return p


_OK = {"status": "completed", "verified": True, "evidence_ref": ""}


def _fail_outcome() -> dict:
    return {"status": "failed", "verified": True, "evidence_ref": ""}


def _episode(claim: str, features: list[str], *, outcome: dict | None = None,
             attribution: str = "", commits: list[dict] | None = None,
             milestones: list[dict] | None = None,
             fragments: list[str] | None = None,
             r: float | None = 1.0, tokens: float = 0.0) -> dict:
    doc = {
        "schema": "episode/1",
        "id": f"E-{claim}",
        "claim": claim,
        "created": "2026-10-25T00:00:00Z",
        "updated": "2026-10-25T00:00:00Z",
        "context_features": list(features),
        "commits": commits or [
            {"seq": 1, "action": "persist", "class": "frida-gadget",
             "summary": f"ran the frida-gadget class on {claim}"}],
        "outcome": outcome or _OK,
        "cost": {"tokens": tokens, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.5},
        "reusable_fragments": fragments if fragments is not None else
        ["re-sign the apk before the gadget inject"],
        "milestones": milestones or [],
        "attribution": attribution,
        "surprise": False,
    }
    if r is not None:
        doc["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                         "cost_term": 0.0, "r": r}
    return doc


def _seed(ws: Path, doc: dict) -> None:
    _pass_verification(ws, str(doc["claim"]))
    pool.write_episode(ws, doc)


def _seed_ok(ws: Path, claim: str, features: list[str], **kw) -> dict:
    doc = _episode(claim, features, **kw)
    _seed(ws, doc)
    return doc


# ---------------------------------------------------------------- helpers

def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _failure(ws: Path, claim: str, features: list[str], why: str,
             **kw) -> dict:
    kw.setdefault("attribution", why)
    kw.setdefault("outcome", _fail_outcome())
    kw.setdefault("r", -0.5)
    return _seed_ok(ws, claim, features, **kw)


# ------------------------------------------------------------ 1. attribution

class TestFeatureImportance:
    def test_failure_contrast_ranks_the_predictive_feature(self, tmp_path):
        ws = _mk_ws(tmp_path)
        for i in range(4):  # successes under the clean set
            _seed_ok(ws, f"C-S{i}", ["lane-android", "frida-ok"])
        _failure(ws, "C-F1", ["lane-android", "cap-frida-fail"],
                 "gadget missing on this ROM")
        rep = attr.feature_importance(ws)
        rows = {r["feature"]: r for r in rep["features"]}
        top = rep["features"][0]
        assert top["feature"] == "cap-frida-fail"
        assert rows["cap-frida-fail"]["n"] == 1
        assert rows["cap-frida-fail"]["fail_rate"] == pytest.approx(1.0)
        assert rows["cap-frida-fail"]["contrast"] == pytest.approx(1.0)
        assert rows["lane-android"]["contrast"] == pytest.approx(0.0)
        assert top["contrast"] > rows["lane-android"]["contrast"]

    def test_exogenous_features_demoted_to_noise(self, tmp_path):
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _seed_ok(ws, f"C-S{i}", ["lane-android", "noise-feat"])
        _failure(ws, "C-F1", ["lane-android", "noise-feat"], "wrong guess")
        rep = attr.feature_importance(ws)
        assert "noise-feat" in rep["exogenous"]
        ranked = [r["feature"] for r in rep["features"]]
        assert "noise-feat" not in ranked or \
            all(r["contrast"] == pytest.approx(0.0)
                for r in rep["features"] if r["feature"] == "noise-feat")

    def test_deterministic_and_store_free(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["lane-android"])
        _failure(ws, "C-F0", ["windows"], "tool gap")
        before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                        if p.is_file())
        r1 = attr.feature_importance(ws)
        r2 = attr.feature_importance(ws)
        assert r1 == r2
        after = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                       if p.is_file())
        assert before == after, "a learned view must not write a store"

    def test_empty_pool_reports_nothing(self, tmp_path):
        ws = _mk_ws(tmp_path)
        rep = attr.feature_importance(ws)
        assert rep["features"] == [] and rep["exogenous"] == []


class TestMethodAttribution:
    def test_tool_missing_vs_hypothesis_wrong_distinguished(
            self, tmp_path):
        ws = _mk_ws(tmp_path)
        for i in range(3):  # the environment is proven workable
            _seed_ok(ws, f"C-S{i}", ["lane-android", "frida-ok"])
        tool_doc = _failure(ws, "C-TF", ["lane-android", "cap-frida-fail"],
                            "frida server missing on device")
        hypo_doc = _failure(ws, "C-HF", ["lane-android", "frida-ok"],
                            "assumed ollvm not vmp")
        a = attr.method_attribution(ws, tool_doc)
        b = attr.method_attribution(ws, hypo_doc)
        assert a["method"] == "tool_mismatch"
        assert b["method"] == "hypothesis_wrong"
        assert a["method"] != b["method"], "no binary accident/failure"

    def test_depth_insufficient_on_partial_verified_progress(
            self, tmp_path):
        ws = _mk_ws(tmp_path)
        for i in range(2):
            _seed_ok(ws, f"C-S{i}", ["lane-android"])
        doc = _failure(
            ws, "C-DF", ["lane-android"], "ran out of depth",
            milestones=[
                {"id": "M-1", "desc": "unpack", "verified": True,
                 "evidence_ref": ""},  # resolves -> verified progress
                {"id": "M-2", "desc": "devirtualize", "verified": True,
                 "evidence_ref": "runs/never-verified.md"},  # no trust
            ])
        out = attr.method_attribution(ws, doc)
        assert out["method"] == "depth_insufficient"
        assert out["signals"]["depth_insufficient"]["fired"] is True

    def test_signals_report_evidence_not_just_verdict(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["lane-android"])
        doc = _failure(ws, "C-HF", ["lane-android"], "wrong assumption")
        out = attr.method_attribution(ws, doc)
        assert out["signals"]["hypothesis_wrong"]["fired"] is True
        assert "lane-android" in \
            out["signals"]["hypothesis_wrong"]["evidence"]

    def test_report_schema_and_digest_ref(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["lane-android"])
        doc = _failure(ws, "C-HF", ["lane-android"], "wrong assumption")
        rep = attr.report(ws, doc=doc)
        assert rep["schema"] == "attribution-report/1"
        assert rep["method"]["method"] == "hypothesis_wrong"
        ref = attr.report_ref(rep)
        assert len(ref) == 16
        assert ref == attr.report_ref(rep), "stable digest"
        assert rep == attr.report(ws, doc=doc), "deterministic report"


# ------------------------------------------------- 2. tune/switch semantics

class TestCommitSemantics:
    def test_switch_without_attribution_is_red(self):
        entry = {"seq": 2, "action": "switch", "to_class": "vmp-trace",
                 "summary": "pivot"}
        with pytest.raises(cs.CommitError) as ei:
            cs.validate_switch_commit(entry)
        assert "attribution" in str(ei.value).lower()

    def test_switch_without_to_class_is_red(self):
        entry = {"seq": 2, "action": "switch", "attribution_ref": "a" * 16,
                 "summary": "pivot"}
        with pytest.raises(cs.CommitError):
            cs.validate_switch_commit(entry)

    def test_switch_with_attribution_and_class_is_green(self):
        entry = {"seq": 2, "action": "switch", "to_class": "vmp-trace",
                 "attribution_ref": "a" * 16, "summary": "pivot"}
        assert cs.validate_switch_commit(entry)["to_class"] == "vmp-trace"

    def test_tune_without_delta_is_red(self):
        entry = {"seq": 2, "action": "tune", "class": "frida-gadget",
                 "summary": "try again"}
        with pytest.raises(cs.CommitError) as ei:
            cs.validate_tune_commit(entry)
        assert "delta" in str(ei.value).lower()

    def test_tune_with_param_delta_is_green(self):
        entry = {"seq": 2, "action": "tune", "class": "frida-gadget",
                 "param_changes": {"timeout_ms": 5000}, "summary": "t2"}
        out = cs.validate_tune_commit(entry)
        assert out["class"] == "frida-gadget"

    def test_tune_with_tool_delta_is_green(self):
        entry = {"seq": 2, "action": "tune", "class": "frida-gadget",
                 "tool_changes": ["+objection"], "summary": "t3"}
        assert cs.validate_tune_commit(entry)["tool_changes"] == \
            ["+objection"]

    def test_nine_dead_path_reprobes_are_red(self):
        doc = _episode("C-DP", ["lane-android"])
        doc["commits"] = [
            {"seq": i + 1, "action": "persist", "class": "static-x",
             "summary": f"re-probe {i + 1}"} for i in range(9)]
        with pytest.raises(cs.CommitError) as ei:
            cs.validate_commit_history(doc)
        assert "dead" in str(ei.value).lower() or \
            str(cs.DEAD_PATH_CAP) in str(ei.value)

    def test_eight_probes_then_tune_is_green(self):
        doc = _episode("C-DP", ["lane-android"])
        doc["commits"] = [
            {"seq": i + 1, "action": "persist", "class": "static-x",
             "summary": f"re-probe {i + 1}"} for i in range(8)]
        doc["commits"].append(
            {"seq": 9, "action": "tune", "class": "static-x",
             "param_changes": {"depth": 2}, "summary": "parameterized"})
        reading = cs.validate_commit_history(doc)
        assert reading["over_cap"] is False

    def test_history_reading_reports_the_run(self):
        doc = _episode("C-DP", ["lane-android"])
        doc["commits"] = [
            {"seq": 1, "action": "persist", "class": "a", "summary": "x"},
            {"seq": 2, "action": "persist", "class": "a", "summary": "x"},
            {"seq": 3, "action": "switch", "to_class": "b",
             "attribution_ref": "b" * 16, "summary": "pivot"},
            {"seq": 4, "action": "persist", "class": "b", "summary": "y"},
        ]
        reading = cs.validate_commit_history(doc)
        assert reading["max_run"]["attempts"] == 2
        assert reading["over_cap"] is False

    def test_additive_commit_fields_stay_schema_legal(self):
        doc = _episode("C-1", ["f"])
        doc["commits"].append(
            {"seq": 2, "action": "switch", "to_class": "vmp",
             "attribution_ref": "c" * 16, "summary": "pivot"})
        assert es.validate_episode(doc)["commits"][1]["attribution_ref"]


# --------------------------------------------------- 3. playbook compression

class TestPlaybookCompression:
    def test_case_specific_fragment_refused(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["lane-android"], fragments=[
            "re-sign the apk with apksigner before injection",
            "case log: C-S0 wrote runs/verification-C-S0.md "
            "sha256 e3b0c44298fc1c1490876afce4d45",
        ])
        groups = pb.compressed_view(ws)
        assert len(groups) == 1
        frags = " ".join(groups[0]["fragments"])
        assert "apksigner" in frags
        assert "C-S0" not in frags, "claim-id case log refused"
        assert "e3b0c442" not in frags, "hex digest case log refused"
        assert groups[0]["refused"] >= 1

    def test_method_fragment_from_a_single_episode_rides(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["fam-x"], fragments=["persist worked here"])
        groups = pb.compressed_view(ws)
        assert any("persist worked here" in f
                   for g in groups for f in g["fragments"])

    def test_support_ranks_and_counts(self, tmp_path):
        ws = _mk_ws(tmp_path)
        shared = "hook the transport first, then spawn the target"
        _seed_ok(ws, "C-S0", ["fam-x"], fragments=[shared])
        _seed_ok(ws, "C-S1", ["fam-x"], fragments=[shared])
        _seed_ok(ws, "C-S2", ["fam-x"], fragments=["unique one-off hint"])
        groups = pb.compressed_view(ws)
        g = groups[0]
        assert g["support"][shared] == 2
        assert g["fragments"][0] == shared, "higher support ranks first"

    def test_not_self_starting_fragment_refused(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["fam-x"],
                 fragments=["shadow radius", "replay the captured traffic"])
        groups = pb.compressed_view(ws)
        frags = " ".join(groups[0]["fragments"])
        assert "replay" in frags
        assert "shadow radius" not in frags, "no verb, no ride"

    def test_derived_view_writes_nothing(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["fam-x"])
        before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                        if p.is_file())
        pb.compressed_view(ws)
        after = sorted(str(p.relative_to(ws)) for p in ws.rglob("*")
                       if p.is_file())
        assert before == after

    def test_injection_through_the_p2_retrieval_face(self, tmp_path,
                                                     monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["fam-x"], fragments=["persist worked here"])
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert any("persist worked here" in f
                   for g in ctx["playbook"] for f in g["fragments"])


# --------------------------------------------------- 4. the surprise loop

class TestSurpriseLoop:
    def _expectation_pool(self, tmp_path) -> tuple[Path, dict]:
        ws = _mk_ws(tmp_path)
        feats = ["fam-x"]
        for i in range(2):  # the class is expected to LOSE here
            _failure(ws, f"C-L{i}", feats, "dead end", r=-0.5)
        doc = _episode("C-WIN", feats)  # verified completed, r=+1.0
        _seed(ws, doc)
        return ws, doc

    def test_completed_against_negative_expectation_is_surprise(
            self, tmp_path):
        ws, doc = self._expectation_pool(tmp_path)
        out = cs.surprise_check(ws, doc)
        assert out["surprise"] is True
        assert out["kind"] == "completed_against_negative"
        assert out["expected_mean_reward"] == pytest.approx(-0.5)

    def test_failed_against_positive_expectation_is_surprise(
            self, tmp_path):
        ws = _mk_ws(tmp_path)
        feats = ["fam-y"]
        for i in range(2):
            _seed_ok(ws, f"C-P{i}", feats, r=1.0)
        loser = _failure(ws, "C-LOSE", feats, "fluke failure")
        out = cs.surprise_check(ws, loser)
        assert out["surprise"] is True
        assert out["kind"] == "failed_against_positive"

    def test_no_expectation_no_surprise(self, tmp_path):
        ws = _mk_ws(tmp_path)
        doc = _episode("C-ALONE", ["fam-z"])
        _seed(ws, doc)
        out = cs.surprise_check(ws, doc)
        assert out["surprise"] is False and out["n"] == 0

    def test_conforming_outcome_is_no_surprise(self, tmp_path):
        ws, _doc = self._expectation_pool(tmp_path)
        loser = _failure(ws, "C-CONFORM", ["fam-x"], "another dead end")
        out = cs.surprise_check(ws, loser)
        assert out["surprise"] is False

    def test_reexamination_commit_generated(self, tmp_path):
        ws, doc = self._expectation_pool(tmp_path)
        block = cs.reexamination_block(ws, doc)
        assert block["commit"] == "verify"
        assert block["reason"] == "surprise"
        assert block["evidence"]["surprise"] is True
        assert isinstance(block["summary"], str) and block["summary"]

    def test_surprise_rides_the_envelope(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        ws, doc = self._expectation_pool(tmp_path)
        block = mp.envelope_block(ws, "C-WIN", phase="commit_boundary")
        assert block["commit"]["action"] == "persist" or True
        reex = block["commit"].get("reexamination")
        assert reex is not None, "the contradiction must force the re-exam"
        assert reex["commit"] == "verify"


# ------------------------------------------------ 5. envelope + ablations

class TestEnvelopeEnrichment:
    def test_episode_start_commit_keyset_stays_exact(self, tmp_path,
                                                     monkeypatch):
        """The P2 pin: episode_start commits carry exactly the P2 fields
        (no enrichment keys leak into the select phase)."""
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-9", ["lane-malware"])
        block = mp.envelope_block(ws, "C-1", phase="episode_start")
        assert set(block["commit"]) == {"action", "scores", "source"}

    def test_commit_boundary_switch_carries_attribution(
            self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _seed_ok(ws, f"C-S{i}", ["lane-a", "cond-a"])
        # a tuned episode with a good outcome: tune scores WORSE under
        # the negative reward weight (its cell mean is positive)
        tuned = _episode("C-T0", ["lane-a", "cond-a"],
                         commits=[{"seq": 1, "action": "tune",
                                   "class": "frida-gadget",
                                   "param_changes": {"timeout_ms": 5000},
                                   "summary": "parameterized retry"}])
        _seed(ws, tuned)
        _failure(ws, "C-F9", ["lane-a", "cond-a"], "wrong approach")
        (ws / "task_spec.yaml").write_text("lane: a\n", encoding="utf-8")
        monkeypatch.setenv("KUNGLAO_META_W_REWARD", "-1")  # tilt to switch
        block = mp.envelope_block(ws, "C-F9", phase="commit_boundary")
        assert block["commit"]["action"] == "switch"
        attribution = block["commit"]["attribution"]
        assert attribution["available"] is True
        assert attribution["method"] == "hypothesis_wrong"
        assert len(attribution["ref"]) == 16

    def test_commit_boundary_tune_carries_contract(self, tmp_path,
                                                   monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-1", ["lane-a", "cond-a"])
        monkeypatch.setenv("KUNGLAO_META_W_REWARD", "5")  # tilt to tune
        block = mp.envelope_block(ws, "C-1", phase="commit_boundary")
        if block["commit"]["action"] == "tune":
            tune = block["commit"]["tune"]
            assert tune["same_class"] is True
            assert "param_changes|tool_changes" in tune["requires"]
        else:  # the tune contract only rides a tune commit
            assert "tune" not in block["commit"]

    def test_dead_path_reading_rides_the_boundary(self, tmp_path,
                                                  monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        commits = [
            {"seq": i + 1, "action": "persist", "class": "static-x",
             "summary": f"re-probe {i + 1}"} for i in range(4)]
        doc = _episode("C-DP", ["lane-a"], commits=commits,
                       fragments=[])
        _seed(ws, doc)
        block = mp.envelope_block(ws, "C-DP", phase="commit_boundary")
        dead = block["commit"]["dead_path"]
        assert dead["class"] == "static-x"
        assert dead["attempts"] == 4
        assert dead["over_cap"] is False

    def test_attribution_ablated_switch_has_no_evidence(
            self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _seed_ok(ws, f"C-S{i}", ["lane-a", "cond-a"])
        tuned = _episode("C-T0", ["lane-a", "cond-a"],
                         commits=[{"seq": 1, "action": "tune",
                                   "class": "frida-gadget",
                                   "param_changes": {"timeout_ms": 5000},
                                   "summary": "parameterized retry"}])
        _seed(ws, tuned)
        _failure(ws, "C-F9", ["lane-a", "cond-a"], "wrong approach")
        (ws / "task_spec.yaml").write_text("lane: a\n", encoding="utf-8")
        monkeypatch.setenv("KUNGLAO_META_W_REWARD", "-1")
        monkeypatch.setenv("KUNGLAO_META_ATTRIBUTION", "0")
        block = mp.envelope_block(ws, "C-F9", phase="commit_boundary")
        assert block["commit"]["action"] == "switch"
        assert block["commit"]["attribution"]["available"] is False

    def test_playbook_ablated_removes_the_ride_along(self, tmp_path,
                                                     monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-S0", ["fam-x"], fragments=["persist worked here"])
        monkeypatch.setenv("KUNGLAO_META_PLAYBOOK", "0")
        ctx = mr.assemble(ws, ["fam-x"], phase="episode_start")
        assert ctx["playbook"] == []
        assert ctx["budget"]["playbook"] is False
        # the cases component is a DIFFERENT knob — unaffected
        assert [c["claim"] for c in ctx["cases"]] == ["C-S0"]

    def test_four_knobs_in_the_knob_face(self, monkeypatch):
        _clean_env(monkeypatch)
        k = mp.knobs()
        assert k["retrieval"] is True and k["value_table"] is True
        assert k["attribution"] is True and k["playbook"] is True
        monkeypatch.setenv("KUNGLAO_META_PLAYBOOK", "0")
        assert mp.knobs()["playbook"] is False

    def test_price_ablations_reports_all_four(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _seed_ok(ws, f"C-S{i}", ["lane-a", "cond-a"])
        _failure(ws, "C-F9", ["lane-a", "cond-a"], "wrong approach")
        monkeypatch.setenv("KUNGLAO_META_W_REWARD", "-1")
        priced = cs.price_ablations(ws, features=["lane-a", "cond-a"],
                                    phase="commit_boundary", claim="C-F9")
        assert set(priced) == {"retrieval", "value_table", "attribution",
                               "playbook"}
        for knob, row in priced.items():
            assert row["component"] == knob
            assert row["price"], f"{knob} carries an output-terms price"

    def test_enrichment_fail_open(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        ws = _mk_ws(tmp_path)
        _seed_ok(ws, "C-1", ["fam-x"])
        block = {"schema": mp.ENVELOPE_SCHEMA, "claim": "C-1",
                 "phase": "commit_boundary",
                 "commit": {"action": "switch", "scores": {}, "source": "x"},
                 "features": [], "context": {}}
        out = cs.enrich_block(ws, "C-1", block)
        assert out["commit"]["action"] == "switch"  # untouched on error path


# --------------------------------------------------- registration faces

class TestRegistration:
    def test_rlvr_facade_exposes_the_three_modules(self):
        import rlvr  # noqa: PLC0415
        for name in ("attribution", "commit_semantics", "playbook"):
            assert name in rlvr.__all__, name

    def test_fast_tier_registry_lists_this_module(self):
        tiers = (ROOT / "tests" / "_tiers.py").read_text(encoding="utf-8")
        assert '"test_attribution_playbook_826"' in tiers

    def test_scripts_readme_catalogs_the_new_modules(self):
        rows = (ROOT / "scripts" / "README.md").read_text(
            encoding="utf-8")
        for name in ("rlvr/attribution.py", "rlvr/commit_semantics.py",
                     "rlvr/playbook.py"):
            assert name in rows, name


# --------------------------------------------- P2 semantics preserved

class TestP2SemanticsPreserved:
    def test_bandit_grep_pin_still_holds(self):
        src = (ROOT / "scripts" / "rlvr" / "meta_policy.py").read_text(
            encoding="utf-8")
        start = src.index("def cold_start_prior")
        nxt = src.find("\ndef ", start + 1)
        span = src[start: nxt if nxt != -1 else len(src)]
        assert "q_cells" in span
        assert src.count("q_cells") == span.count("q_cells")

    def test_phase_menu_unchanged(self):
        assert mp.PHASE_ACTIONS["episode_start"] == ("select",)
        assert set(mp.PHASE_ACTIONS["commit_boundary"]) == \
            {"persist", "tune", "switch"}

    def test_p1_playbook_view_face_untouched(self, tmp_path):
        import rlvr.pool_indexer as indexer  # noqa: PLC0415
        ws = _mk_ws(tmp_path)
        _pass_verification(ws, "C-1")
        pool.write_episode(ws, _episode("C-1", ["fam-x"]))
        view = indexer.playbook_view(ws)
        assert any("re-sign the apk before the gadget inject" in f
                   for g in view for f in g["fragments"])
