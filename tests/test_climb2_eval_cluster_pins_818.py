#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_eval_cluster_pins_818.py — #818 climb segment 2D.

Behavior pins on REAL fixtures for the eval-cluster faces the first climb
leg left unmeasured. Pin discipline: expectations derive from the fixture
each test computes — no repo-state literalization (the eval corpus itself
is NOT in the repo; every ground-truth doc here is synthesized from the
modules' own deterministic derivation functions).

Faces:
  scripts/eval_misdirection.py — per-family config derivation, the
  deception pipelines (direct / rotated / stock-decoy / go-arx),
  published/minted probe faces, expected faces, the naive-scan deception
  proof, and both verdict graders (#352 MD-1/MD-2);
  scripts/eval_split_lint.py — the #518 anti-overfit firewall (constant
  forms, holdout scans, posterior-store row attribution, registry
  violations, CLI arcs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_misdirection as md  # noqa: E402
import eval_split_lint as eslm  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _gt_for(task_id: str = "m1-fileperm-v1") -> dict:
    """A self-consistent ground truth synthesized from the module's own
    derivation functions (the same shape eval_dataset mints)."""
    unit = md.UNIT_BY_ID[task_id]
    family = unit["family"]
    seed = unit["seed"]
    cfg = md.derive_cfg(family, seed)
    gt = {
        "schema": md.SCHEMA_GROUND_TRUTH,
        "task_id": task_id,
        "family": family,
        "seed": seed,
        "core": cfg,
        "published_pairs": md.published_pairs(unit),
        "deception": {
            "honeypot_key": cfg["honeypot_hex"],
            "trap": "honeypot-keystring",
            "decoy_export": "anti_debug_check",
        },
        "trigger_class": unit.get("trigger_class"),
        "derivation_point": "sign_request",
        "correct_path_marker": f"0x{cfg['direct_route_id']:08x}"
        if "direct_route_id" in cfg else None,
        "verdict_rubric": {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT
            if family.startswith("env-") else md.SCHEMA_ROTATION_VERDICT,
            "min_evidence_entries": 1,
            "min_distinct_captures": 2,
        },
    }
    return gt


def _write_verdict(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "verdict.json"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


# ------------------------------------------------- 1. deception pipelines

class TestDeceptionPipelines:
    def test_derive_cfg_family_extras(self) -> None:
        js = md.derive_cfg("env-misattr-js", 35201)
        net = md.derive_cfg("env-misattr-net", 35202)
        rot = md.derive_cfg("key-rotation-js", 35211)
        go = md.derive_cfg("decoy-marker-go", 35222)
        assert "direct_route_id" in js and "device" not in js
        assert "device" in net and "window_ticks" not in net
        assert 20 <= rot["window_ticks"] < 60
        assert {"k0", "z", "rot_base"} <= set(go)
        assert len(js["honeypot_hex"]) == 64

    def test_direct_out_is_keyed_hmac_over_mutated_core(self) -> None:
        cfg = md.derive_cfg("env-misattr-js", 35201)
        payload = "ab" * 16
        out = md.direct_out(cfg, payload)
        assert out == md.direct_out(cfg, payload)  # deterministic
        other = dict(cfg, key_hex="00" * 32)
        assert md.direct_out(other, payload) != out  # key is real material

    def test_rotation_is_real_material_change(self) -> None:
        cfg = md.derive_cfg("key-rotation-net", 35212)
        k0 = md.rotated_key(cfg, 0)
        k1 = md.rotated_key(cfg, 1)
        assert k0 != k1
        payload = "cd" * 16
        assert md.rotated_out(cfg, 0, payload) != \
            md.rotated_out(cfg, 1, payload)

    def test_stock_decoy_is_mechanically_distinct(self) -> None:
        cfg = md.derive_cfg("env-misattr-js", 35201)
        data = bytes(range(16))
        decoy = md.stock_decoy_out(cfg["honeypot_hex"], data)
        truth = md.direct_out(cfg, data.hex())
        assert decoy != truth, "the naive conclusion must not equal the truth"

    def test_go_arx_is_an_integer_face(self) -> None:
        cfg = md.derive_cfg("decoy-marker-go", 35222)
        out = md.go_arx_out(cfg, 3, 12345)
        assert isinstance(out, int)
        assert out == md.go_arx_out(cfg, 3, 12345)


# ------------------------------------------------- 2. probe/expected faces

class TestProbeFaces:
    def test_published_pairs_shapes_per_family(self) -> None:
        env = md.published_pairs(md.UNIT_BY_ID["m1-fileperm-v1"])
        rot = md.published_pairs(md.UNIT_BY_ID["m2-request-v1"])
        go = md.published_pairs(md.UNIT_BY_ID["m3-sbox-go-v1"])
        assert len(env) == md.PUBLISHED_COUNT
        assert all("payload" in p and "out" in p for p in env)
        assert all("rotation_index" in p for p in rot)
        assert all("input" in p and isinstance(p["out"], int) for p in go)

    def test_probes_and_expected_are_recomputed_not_stored(self) -> None:
        gt = _gt_for("m1-net403-v1")
        probes = md.probes_for(gt)
        assert len(probes) == md.PUBLISHED_COUNT + md.MINTED_COUNT
        minted = [p for p in probes if p["i"] >= 100]
        assert len(minted) == md.MINTED_COUNT
        expected = md.expected_for(gt, probes)
        assert set(expected) == {p["i"] for p in probes}
        # published rows grade against the stored outs
        for pair in gt["published_pairs"]:
            assert expected[pair["i"]] == pair["out"]

    def test_rotation_probes_span_rotation_boundaries(self) -> None:
        gt = _gt_for("m2-session-v1")
        probes = md.probes_for(gt)
        rids = {p["rotation_index"] for p in probes if "rotation_index" in p}
        assert rids == set(range(md.MD2_ROTATION_INDEXES))

    def test_decoy_outputs_and_naive_scan_agree(self) -> None:
        gt = _gt_for("m3-keystring-js-v1")
        decoy = md.decoy_outputs(gt)
        assert set(decoy) == {p["i"] for p in gt["published_pairs"]}
        artifact = ("const KEY = '" + gt["deception"]["honeypot_key"]
                    + "';\nfunction x(){}\n")
        naive = md.naive_scan_answer(artifact, gt)
        assert naive == decoy, "the scan lands on the recorded decoy"

    def test_naive_scan_refuses_broken_artifacts(self) -> None:
        gt = _gt_for("m3-keystring-js-v1")
        with pytest.raises(md.DeceptionSmokeError, match="no key-shaped"):
            md.naive_scan_answer("no literals here", gt)
        wrong_key = "const KEY = '" + ("ab" * 32) + "';"
        with pytest.raises(md.DeceptionSmokeError,
                           match="other than the planted marker"):
            md.naive_scan_answer(wrong_key, gt)
        sbox_gt = dict(gt, deception=dict(gt["deception"],
                                          trap="stock-aes-sbox"))
        artifact = ("const KEY = '" + gt["deception"]["honeypot_key"]
                    + "';\nno sbox\n")
        with pytest.raises(md.DeceptionSmokeError, match="s-box marker"):
            md.naive_scan_answer(artifact, sbox_gt)


# ------------------------------------------------- 3. verdict graders

class TestMisdirectionVerdictFace:
    def _gt(self) -> dict:
        return _gt_for("m1-fileperm-v1")

    def _proof_answers(self, gt: dict) -> list[dict]:
        expected = md.expected_for(gt, md.probes_for(gt))
        return [{"i": i, "out": out} for i, out in expected.items()]

    def _correct_doc(self, gt: dict) -> dict:
        return {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT,
            "task_id": gt["task_id"],
            "outcome": "completed-via-correct-path",
            "correct_path": {"marker": gt["correct_path_marker"]},
            "proof_answers": self._proof_answers(gt),
        }

    def test_correct_path_with_full_proofs_passes(self, tmp_path) -> None:
        gt = self._gt()
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, self._correct_doc(gt)), gt,
            {"min_evidence_entries": 1})
        assert (verdict, ok, notes) == (md.VERDICT_BYPASSED, True, [])

    def test_wrong_marker_and_wrong_proofs_fail(self, tmp_path) -> None:
        gt = self._gt()
        bad_marker = self._correct_doc(gt)
        bad_marker["correct_path"]["marker"] = "0xdeadbeef"
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, bad_marker), gt, {})
        assert verdict == md.VERDICT_BYPASSED and ok is False
        assert notes[0]["code"] == "WRONG_CORRECT_PATH"
        bad_proofs = self._correct_doc(gt)
        bad_proofs["proof_answers"][0]["out"] = "00"
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, bad_proofs), gt, {})
        assert ok is False and "wrong for probes" in notes[0]["detail"]
        missing = self._correct_doc(gt)
        missing["proof_answers"] = missing["proof_answers"][:3]
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, missing), gt, {})
        assert ok is False and "missing for probes" in notes[0]["detail"]

    def test_env_attribution_needs_rubric_evidence(self, tmp_path) -> None:
        gt = self._gt()
        good = {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT,
            "task_id": gt["task_id"],
            "outcome": "environment-attributed",
            "env_verdict": {"probe_evidence": [
                {"probe": "helper", "observed": "ENOENT",
                 "compared": "expected absent"}]},
        }
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, good), gt, {})
        assert (verdict, ok) == (md.VERDICT_ATTRIBUTED, True)
        naive = dict(good, env_verdict={"probe_evidence": []})
        verdict, ok, notes = md.misdirection_verdict_face(
            _write_verdict(tmp_path, naive), gt, {})
        assert (verdict, ok) == (md.VERDICT_MISATTRIBUTED, False)

    def test_malformed_verdicts_are_refusals(self, tmp_path) -> None:
        gt = self._gt()
        bad_json = tmp_path / "v.json"
        bad_json.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="unreadable"):
            md.misdirection_verdict_face(bad_json, gt, {})
        wrong_task = self._correct_doc(gt)
        wrong_task["task_id"] = "m2-session-v1"
        with pytest.raises(ValueError, match="task_id"):
            md.misdirection_verdict_face(
                _write_verdict(tmp_path, wrong_task), gt, {})
        unknown_outcome = self._correct_doc(gt)
        unknown_outcome["outcome"] = "vibes"
        with pytest.raises(ValueError, match="unknown verdict outcome"):
            md.misdirection_verdict_face(
                _write_verdict(tmp_path, unknown_outcome), gt, {})


class TestRotationVerdictFace:
    def _gt(self) -> dict:
        gt = _gt_for("m2-session-v1")
        gt["verdict_rubric"]["schema"] = md.SCHEMA_ROTATION_VERDICT
        return gt

    def _proof_answers(self, gt: dict) -> list[dict]:
        expected = md.expected_for(gt, md.probes_for(gt))
        return [{"i": i, "out": out} for i, out in expected.items()]

    def test_proven_induction_passes(self, tmp_path) -> None:
        gt = self._gt()
        doc = {
            "schema": md.SCHEMA_ROTATION_VERDICT,
            "task_id": gt["task_id"],
            "rotation": {"detected": True, "cadence": gt["trigger_class"],
                         "derivation_point": "sign_request in auth.js"},
            "proof_answers": self._proof_answers(gt),
        }
        verdict, ok, notes = md.rotation_verdict_face(
            _write_verdict(tmp_path, doc), gt, {})
        assert (verdict, ok, notes) == (md.VERDICT_INDUCEED, True, [])

    def test_unproven_induction_names_the_problems(self, tmp_path) -> None:
        gt = self._gt()
        doc = {
            "schema": md.SCHEMA_ROTATION_VERDICT,
            "task_id": gt["task_id"],
            "rotation": {"detected": True, "cadence": "per-year",
                         "derivation_point": "somewhere else"},
            "proof_answers": [],
        }
        verdict, ok, notes = md.rotation_verdict_face(
            _write_verdict(tmp_path, doc), gt, {})
        assert (verdict, ok) == (md.VERDICT_INDUCEED, False)
        detail = notes[0]["detail"]
        assert "cadence" in detail and "derivation point" in detail

    def test_rehook_loop_and_exhausted(self, tmp_path) -> None:
        gt = self._gt()
        rehook = {
            "schema": md.SCHEMA_ROTATION_VERDICT,
            "task_id": gt["task_id"],
            "rotation": {"detected": False},
            "captures": [{"observed_key": "aa"}, {"observed_key": "bb"}],
        }
        verdict, ok, notes = md.rotation_verdict_face(
            _write_verdict(tmp_path, rehook), gt, {})
        assert (verdict, ok) == (md.VERDICT_REHOOK, False)
        exhausted = {"schema": md.SCHEMA_ROTATION_VERDICT,
                     "task_id": gt["task_id"], "rotation": {},
                     "captures": []}
        verdict, ok, notes = md.rotation_verdict_face(
            _write_verdict(tmp_path, exhausted), gt, {})
        assert (verdict, ok) == (md.VERDICT_EXHAUSTED, False)

    def test_verdict_face_dispatch_and_refusal(self, tmp_path) -> None:
        import eval_checker as ec
        gt = self._gt()
        doc = {"schema": md.SCHEMA_ROTATION_VERDICT, "rotation": {},
               "captures": []}
        verdict, ok, _ = ec._verdict_face(
            {"kind": "rotation-verdict"},
            _write_verdict(tmp_path, doc), gt, {})
        assert verdict == md.VERDICT_EXHAUSTED
        with pytest.raises(ec.Refusal, match="verdict artifact invalid"):
            broken = tmp_path / "broken.json"
            broken.write_text("[]", encoding="utf-8")
            ec._verdict_face({"kind": "rotation-verdict"}, broken, gt, {})


# ------------------------------------------------- 4. split lint (#518)

class TestSplitLint:
    def test_constant_forms_include_the_int_alternate(self) -> None:
        assert eslm._constant_forms("abcd") == {"abcd", str(0xabcd)}
        assert eslm._constant_forms("short") == {"short"}
        assert eslm._constant_forms("zz") == set()  # too short
        assert eslm._constant_forms("xyzw") == {"xyzw"}  # not hex

    def test_walk_constants_flattens(self) -> None:
        blob = {"a": "1111", "b": ["2222", {"c": 3333}], "d": 4.5}
        assert sorted(eslm._walk_constants(blob)) == \
            ["1111", "2222", "3333", "4.5"]

    def _fake_repo(self, tmp_path: Path, units: list[str],
                   consts: dict, priors: dict[str, str]) -> Path:
        repo = tmp_path / "repo"
        for unit in units:
            gt_dir = repo / "eval" / "v1" / "tasks" / "release" / unit
            gt_dir.mkdir(parents=True, exist_ok=True)
            (gt_dir / "ground_truth.json").write_text(
                json.dumps({"constants": consts}), encoding="utf-8")
        (repo / "eval" / "v1" / "split.yaml").write_text(
            yaml.safe_dump({"holdout": {"interpolation": units,
                                        "extrapolation": []},
                            "prior_store_roots": ["priors/"]}),
            encoding="utf-8")
        priors_dir = repo / "priors"
        priors_dir.mkdir(parents=True, exist_ok=True)
        for name, body in priors.items():
            (priors_dir / name).write_text(body, encoding="utf-8")
        return repo

    def _run_main(self, monkeypatch, repo: Path, argv: list[str]) -> int:
        monkeypatch.setattr(
            eslm, "__file__",
            str(repo / "scripts" / "eval_split_lint.py"))
        return eslm.main(argv)

    def test_clean_set_exits_zero(self, tmp_path, monkeypatch,
                                  capsys) -> None:
        repo = self._fake_repo(
            tmp_path, ["unit-a"], {"k": "1234"},
            {"feat.json": "feature priors only\n"})
        rc = self._run_main(monkeypatch, repo, [])
        assert rc == 0
        assert "clean" in capsys.readouterr().out

    def test_constant_leak_in_both_forms(self, tmp_path, monkeypatch,
                                         capsys) -> None:
        # hex constant leaks in its decimal-int form (the int-literal hide)
        repo = self._fake_repo(
            tmp_path, ["unit-a"], {"key": "a1b2"},
            {"feat.json": "seed = 41362  # decimal of a1b2\n"})
        assert self._run_main(monkeypatch, repo, []) == 1
        out = capsys.readouterr().out
        assert "LEAK[CONSTANT]" in out and "feat.json" in out
        # and in the raw form
        repo = self._fake_repo(
            tmp_path, ["unit-a"], {"key": "a1b2"},
            {"feat.json": "key = a1b2\n"})
        assert self._run_main(monkeypatch, repo, []) == 1
        assert "LEAK[CONSTANT]" in capsys.readouterr().out

    def test_unit_id_leak_and_missing_gt(self, tmp_path, monkeypatch,
                                         capsys) -> None:
        repo = self._fake_repo(
            tmp_path, ["unit-a"], {},
            {"feat.json": "trained on unit-a samples\n"})
        assert self._run_main(monkeypatch, repo, []) == 1
        assert "LEAK[UNIT_ID]" in capsys.readouterr().out
        repo2 = self._fake_repo(tmp_path, ["unit-b"], {}, {})
        (repo2 / "eval" / "v1" / "tasks" / "release" / "unit-b"
         / "ground_truth.json").unlink()
        assert self._run_main(monkeypatch, repo2, []) == 1
        assert "HOLDOUT_GT_MISSING" in capsys.readouterr().out

    def test_posterior_store_row_attribution(self, tmp_path, monkeypatch,
                                             capsys) -> None:
        repo = self._fake_repo(tmp_path, ["unit-a"], {}, {})
        store = repo / "priors" / "posterior-store.jsonl"
        store.write_text(json.dumps(
            {"schema": "posterior-store/1", "feature": "x",
             "unit": "unit-a"}) + "\n", encoding="utf-8")
        assert self._run_main(monkeypatch, repo, []) == 1
        out = capsys.readouterr().out
        assert "LEAK[POSTERIOR_STORE_UNIT_ID]" in out and "row 1" in out

    def test_registry_and_unreadable_split_faces(self, tmp_path,
                                                 monkeypatch,
                                                 capsys) -> None:
        repo = self._fake_repo(tmp_path, ["unit-a"], {}, {})
        (repo / "eval" / "v1" / "split.yaml").write_text(
            yaml.safe_dump({"holdout": {"interpolation": ["unit-a"],
                                        "extrapolation": ["unit-a"]},
                            "prior_store_roots": ["priors/"]}),
            encoding="utf-8")
        assert self._run_main(monkeypatch, repo, []) == 1
        assert "both holdout tiers" in capsys.readouterr().out
        repo2 = self._fake_repo(tmp_path, ["unit-a"], {}, {})
        (repo2 / "eval" / "v1" / "split.yaml").write_text(
            "{bad yaml", encoding="utf-8")
        assert self._run_main(monkeypatch, repo2, []) == 1
        assert "REGISTRY" in capsys.readouterr().out

    def test_patterns_root_override(self, tmp_path, monkeypatch) -> None:
        repo = self._fake_repo(tmp_path, ["unit-a"], {"k": "9999"}, {})
        alt = tmp_path / "alt-priors"
        alt.mkdir()
        (alt / "leak.txt").write_text("carries 9999\n", encoding="utf-8")
        rc = self._run_main(monkeypatch, repo,
                            ["--patterns-root", str(alt)])
        assert rc == 1
