# -*- coding: utf-8 -*-
"""tests/test_eval_chain_370.py — the multi-layer decryption-chain tier.

Owner directive 2026-09-24: the ladder needs units where pass REQUIRES
peeling 2-5 nested protection stages (each layer's output feeds the
next) with a dense per-layer score (0..N), and where the anti-shortcut
construction is auditable: runtime-derived keys, planted decoys, and a
recorded naive-scan baseline that FAILS to yield the answer (the
win-kdf-l1 lesson: a pass reachable by constant-lookup has zero
discrimination).

Faces under test:
  (a) tier wiring — TIERS / EVAL_VERSIONS / TIER_EVAL_VERSION / schema
      enums registered additively (the #356 pattern);
  (b) landed units — validate, carry gradient + >= 3 distinct
      mechanisms, contract rows consumed single-source;
  (c) anti-shortcut audits — the recorded naive baselines are re-run
      LIVE against the committed artifacts and must FAIL to shortcut;
  (d) mint gates — a unit whose audit would pass is refused;
  (e) self-check — reference greens, naive fails, dense scores correct
      on reference / empty / decoy workspaces.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHAIN_TASKS = ROOT / "eval" / "v1" / "tasks" / "chain"
SCHEMA_PATH = ROOT / "schemas" / "eval-task-v1.json"

sys.path.insert(0, str(SCRIPTS))

import eval_dataset as ds  # noqa: E402
import eval_chain as ch  # noqa: E402
import eval_chain_mint as mint_mod  # noqa: E402
import eval_chain_grader  # noqa: E402

NODE_AVAILABLE = shutil.which("node") is not None
GO_AVAILABLE = shutil.which("go") is not None


EXPECTED_TASK_IDS = {
    "chain-l1-js-v1", "chain-l1-py-v1",
    "chain-l2-js-v1", "chain-l2-py-v1", "chain-l2-go-v1",
    "chain-l3-js-v1", "chain-l3-py-v1",
}

GRADIENTS = {
    "chain-l1-js-v1": "L1", "chain-l1-py-v1": "L1",
    "chain-l2-js-v1": "L2", "chain-l2-py-v1": "L2",
    "chain-l2-go-v1": "L2",
    "chain-l3-js-v1": "L3", "chain-l3-py-v1": "L3",
}


def _tdir(task_id: str) -> Path:
    d = CHAIN_TASKS / task_id
    assert d.is_dir(), f"chain unit missing: {d}"
    return d


def _task(task_id: str) -> dict:
    return yaml.safe_load((_tdir(task_id) / "task.yaml").read_text("utf-8"))


def _gt(task_id: str) -> dict:
    return json.loads(
        (_tdir(task_id) / "ground_truth.json").read_text("utf-8"))


def _manifest(task_id: str) -> dict:
    return json.loads((_tdir(task_id) / "manifest.json").read_text("utf-8"))


def _ch():
    import eval_chain
    return eval_chain


# --------------------------------------------------------------- (a) wiring
class TestChainTierWiring:
    def test_tier_registered(self):
        assert "chain" in ds.TIERS

    def test_eval_version_registered(self):
        assert "eval-v1.4" in ds.EVAL_VERSIONS
        assert ds.TIER_EVAL_VERSION["chain"] == "eval-v1.4"

    def test_both_tier_version_consumers_pinned(self):
        """TIER_EVAL_VERSION is the #334 loop runner's consumer surface;
        EVAL_TIER_VERSION is the release-lane alias — both carry chain."""
        assert ds.EVAL_TIER_VERSION is ds.TIER_EVAL_VERSION
        assert ds.EVAL_TIER_VERSION.get("chain") == "eval-v1.4"

    def test_schema_enums_extended(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert "eval-v1.4" in props["eval_version"]["enum"]
        assert "chain" in props["tier"]["enum"]

    def test_contract_rows_single_source(self):
        """The chain families consume the #352 single-source contract —
        no local suffix map anywhere in the chain modules."""
        import eval_contract as ec
        for family in ("chain-js", "chain-py", "chain-go"):
            assert family in ec.FAMILY_CONTRACT
        assert ec.candidate_suffix("chain-js") == ".js"
        assert ec.candidate_suffix("chain-py") == ".py"
        assert ec.candidate_suffix("chain-go") == ".go"
        assert ec.target_surface("chain-js") == "text"

    def test_drivers_derive_chain_suffixes_from_contract(self):
        import eval_contract as ec
        import eval_loop_runner as lr
        import eval_control_arm as ca
        for family in ("chain-js", "chain-py", "chain-go"):
            want = ec.candidate_suffix(family)
            assert lr._candidate_suffix({"family": family}) == want
            assert ca._cand_suffix({"family": family}) == want


# --------------------------------------------------------------- (b) units
class TestChainUnits:
    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_expected_units_present_and_validate(self):
        landed = {d.name for d in ds.iter_task_dirs(tier="chain")}
        assert EXPECTED_TASK_IDS <= landed
        for task_id in EXPECTED_TASK_IDS:
            task = _task(task_id)
            ok, errors = ds.validate_task(task)
            assert ok, f"{task_id}: {errors}"
            assert task["tier"] == "chain"
            assert task["eval_version"] == "eval-v1.4"
            assert task["source"] == "constructed"

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_gradient_and_layer_counts(self):
        for task_id in EXPECTED_TASK_IDS:
            m = _manifest(task_id)
            assert m["schema"] == _ch().SCHEMA_MANIFEST
            assert m["gradient"] == GRADIENTS[task_id]
            n_layers = len(m["layers"])
            assert n_layers == {"L1": 2, "L2": 3, "L3": 6}[m["gradient"]]
            mechanisms = set()
            for layer in m["layers"]:
                mechanisms.update(layer["mechanisms"])
            assert len(mechanisms) >= 3, f"{task_id}: < 3 distinct mechanisms"

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_language_platform_mix(self):
        langs = {_manifest(t)["language"] for t in EXPECTED_TASK_IDS}
        assert {"javascript", "python", "go"} <= langs

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_l3_combines_junk_decoy_and_gate(self):
        for task_id in ("chain-l3-js-v1", "chain-l3-py-v1"):
            mechanisms = set()
            for layer in _manifest(task_id)["layers"]:
                mechanisms.update(layer["mechanisms"])
            assert {"junk-code", "decoy-path", "anti-debug-gate"} <= mechanisms


# ---------------------------------------------------- (b2) corpus deep face
class TestChainUnitsDeep:
    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_shortcut_audit_recorded_in_manifest(self):
        for task_id in EXPECTED_TASK_IDS:
            audit = _manifest(task_id)["shortcut_audit"]
            assert audit["smoked_at_mint"] is True
            assert audit["entry_scan"]["verdict"] == "FAIL"
            assert audit["payload_scan"]["verdict"] == "FAIL"
            assert audit["constant_scan"]["verdict"] == "FAIL"
            assert audit["runtime_keys"]["runtime_key_hex_absent"] is True
            assert audit["decoy_baseline"]

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_layer_checkpoints_present_per_gradient(self):
        counts = {"L1": 2, "L2": 3, "L3": 6}
        for task_id in EXPECTED_TASK_IDS:
            gt = _gt(task_id)["chain"]
            assert len(gt["layers"]) == counts[_manifest(task_id)["gradient"]]
            ops = [op for layer in gt["layers"] for op in layer["ops"]]
            kinds = {op["op"] for op in ops}
            assert kinds <= {"digest", "exec", "markers", "clean"}
            assert len(gt["probes"]) == 16  # 8 published + 8 minted

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_junk_and_decoy_checkpoints_in_l3(self):
        for task_id in ("chain-l3-js-v1", "chain-l3-py-v1"):
            gt = _gt(task_id)["chain"]
            by_id = {l["id"]: l for l in gt["layers"]}
            clean_ops = [op["op"] for op in by_id["junk-code"]["ops"]]
            assert "clean" in clean_ops and "exec" in clean_ops
            cipher_ops = [op["op"] for op in by_id["custom-cipher-core"]["ops"]]
            assert "exec" in cipher_ops
            assert "markers" in [op["op"] for op in by_id["decoy-path"]["ops"]]
            assert "markers" in [op["op"] for op in by_id["anti-debug-gate"]["ops"]]
            assert by_id["decoy-path"]["mechanisms"] == ["decoy-path"]
            assert "rotation-timer" in by_id["anti-debug-gate"]["mechanisms"]

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_replay_face_available_for_every_unit(self):
        """The checker resolves every chain unit and arms the replay
        face (single-source contract suffix on the reference)."""
        import eval_contract as ec
        for task_id in EXPECTED_TASK_IDS:
            tdir = _tdir(task_id)
            task = _task(task_id)
            want = ec.candidate_suffix(task["family"])
            ref = tdir / task["checker"]["self_check_candidate"]
            assert ref.suffix == want, task_id
            assert ref.is_file(), task_id


# ------------------------------------------- (c) anti-shortcut LIVE re-run
class TestAntiShortcutLive:
    """The recorded audit is re-run LIVE against the committed files:
    the naive methods must FAIL to yield the answer right now."""

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_entry_scan_finds_no_answer_material(self):
        for task_id in EXPECTED_TASK_IDS:
            unit = ch.UNIT_BY_ID[task_id]
            cfg = mint_mod.stage_cfg(unit)
            target = (_tdir(task_id) / ch.FAMILIES[unit["family"]]["target"]
                      ).read_text(encoding="utf-8")
            assert ch.constant_scan(target, ch.answer_constants(cfg)) == []
            assert ch.naive_key_hit(target) is None, task_id

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_payload_scan_lands_on_honeypot_only(self):
        for task_id in EXPECTED_TASK_IDS:
            unit = ch.UNIT_BY_ID[task_id]
            cfg = mint_mod.stage_cfg(unit)
            payload = mint_mod.tt.payload_bytes(cfg, True).decode("utf-8")
            assert ch.constant_scan(payload, ch.answer_constants(cfg)) == []
            assert ch.naive_key_hit(payload) == cfg["honeypot"]
            for p in ch.published_pairs(unit):
                assert ch.honeypot_out(cfg, p["payload"]) != p["out"]
                assert ch.decoy_out(cfg, p["payload"], p["lane"]) != p["out"]

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_runtime_key_never_a_literal(self):
        for task_id in EXPECTED_TASK_IDS:
            unit = ch.UNIT_BY_ID[task_id]
            cfg = mint_mod.stage_cfg(unit)
            tdir = _tdir(task_id)
            for f in tdir.rglob("*"):
                if not f.is_file() or f.name in ("ground_truth.json",
                                                 "manifest.json"):
                    continue
                text = f.read_text(encoding="utf-8", errors="replace").lower()
                for w in ch._words(bytes.fromhex(cfg["rt_key"])):
                    assert f"{w:08x}" not in text, f"{task_id}/{f.name}"

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_decoy_baseline_recorded_and_wrong(self):
        for task_id in EXPECTED_TASK_IDS:
            unit = ch.UNIT_BY_ID[task_id]
            cfg = mint_mod.stage_cfg(unit)
            audit = _manifest(task_id)["shortcut_audit"]
            for p in ch.published_pairs(unit):
                assert (f"{p['out']}" !=
                        audit["decoy_baseline"][str(p["i"])])


# ------------------------------------------------- (d) mint gate is real
class TestMintGate:
    def test_refusal_when_answer_constant_is_visible(self):
        unit = ch.UNIT_BY_ID["chain-l1-js-v1"]
        cfg = mint_mod.stage_cfg(unit)
        cfg["task_id"] = unit["task_id"]
        cfg["unit"] = unit
        from eval_chain_targets import render_js_target
        target = render_js_target(cfg)
        # a candidate-side key literal must trip the gate
        leak = target + f"\nvar LEAK = '{cfg['config']['mac_key']}';\n"
        with pytest.raises(ch.ChainMintRefusal, match="answer material"):
            mint_mod.shortcut_audit(cfg, leak)

    def test_refusal_when_key_shaped_literal_visible(self):
        unit = ch.UNIT_BY_ID["chain-l2-js-v1"]
        cfg = mint_mod.stage_cfg(unit)
        cfg["task_id"] = unit["task_id"]
        cfg["unit"] = unit
        from eval_chain_targets import render_js_target
        target = render_js_target(cfg)
        # a 64-hex literal in the committed artifact breaks the
        # "honeypot is the only key-shaped literal" property
        leak = target + "\nvar LICENSE_SECRET = '" + ("ab" * 32) + "';\n"
        with pytest.raises(ch.ChainMintRefusal, match="key-shaped"):
            mint_mod.shortcut_audit(cfg, leak)

    def test_rebuild_matches_committed_units(self):
        """Deterministic re-mint: the committed corpus is byte-stable
        (targets + ground truth digests)."""
        for task_id in EXPECTED_TASK_IDS:
            built = mint_mod.build_task_unit(task_id)
            committed = (_tdir(task_id) /
                         ch.FAMILIES[built["unit"]["family"]]["target"]
                         ).read_text(encoding="utf-8")
            assert built["target_text"] == committed, task_id


# ------------------------------------------------------------- (e) grader
class TestChainGrader:
    def _ref_ws(self, tmp_path, task_id):
        unit = ch.UNIT_BY_ID[task_id]
        cfg = mint_mod.stage_cfg(unit)
        cfg["task_id"] = task_id
        cfg["unit"] = unit
        ws = tmp_path / f"ws-{task_id}"
        for rel, data in mint_mod.reference_workspace(cfg).items():
            f = ws / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        return ws

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_reference_workspace_scores_full(self, tmp_path):
        gr = eval_chain_grader
        rc, scores = gr.grade("chain-l1-js-v1", self._ref_ws(tmp_path, "chain-l1-js-v1"))
        assert rc == gr.RC_PASS
        assert scores["layers_completed"] == scores["layers_total"] == 2
        assert scores["dense_score"] == 1.0

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_empty_workspace_scores_zero(self, tmp_path):
        gr = eval_chain_grader
        ws = tmp_path / "empty"
        ws.mkdir()
        rc, scores = gr.grade("chain-l1-js-v1", ws)
        assert rc == gr.RC_FAIL
        assert scores["layers_completed"] == 0
        assert scores["dense_score"] == 0.0

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_partial_workspace_partial_credit(self, tmp_path):
        """A workspace with only the peel artifact scores exactly the
        layers it completed (dense, not binary)."""
        gr = eval_chain_grader
        unit = ch.UNIT_BY_ID["chain-l1-js-v1"]
        cfg = mint_mod.stage_cfg(unit)
        ws = tmp_path / "partial"
        (ws / "layer_out").mkdir(parents=True)
        (ws / "layer_out" / "1-unpacked.js").write_bytes(
            mint_mod.tt.payload_bytes(cfg, True))
        rc, scores = gr.grade("chain-l1-js-v1", ws)
        assert scores["layers_completed"] == 1
        assert scores["layers_total"] == 2
        assert scores["dense_score"] == 0.5

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_decoy_workspace_partial_and_true_layers_fail(self, tmp_path):
        """The decoy-following trajectory: peeled layers still credit;
        the decoy-keyed layers fail (the cost trap is visible in the
        score)."""
        gr = eval_chain_grader
        unit = ch.UNIT_BY_ID["chain-l3-js-v1"]
        cfg = mint_mod.stage_cfg(unit)
        cfg["task_id"] = "chain-l3-js-v1"
        cfg["unit"] = unit
        ws = tmp_path / "decoy"
        for rel, data in mint_mod.decoy_workspace(cfg).items():
            f = ws / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        rc, scores = gr.grade("chain-l3-js-v1", ws)
        assert rc == gr.RC_FAIL
        assert 0 < scores["layers_completed"] < scores["layers_total"]
        done = {l["id"] for l in scores["layers"] if l["completed"]}
        assert ch.L_OBFUSCATION in done
        assert ch.L_CIPHER not in done
        assert ch.L_DECOY not in done

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_digest_op_detects_tampering(self, tmp_path):
        gr = eval_chain_grader
        ws = self._ref_ws(tmp_path, "chain-l1-js-v1")
        cfg_path = ws / "layer_out" / "2-config.json"
        cfg_path.write_bytes(cfg_path.read_bytes() + b" ")  # 1-byte drift
        rc, scores = gr.grade("chain-l1-js-v1", ws)
        assert rc == gr.RC_FAIL
        assert scores["layers_completed"] == 1

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_markers_op_requires_true_path_evidence(self, tmp_path):
        gr = eval_chain_grader
        ws = self._ref_ws(tmp_path, "chain-l3-js-v1")
        path_doc = ws / "layer_out" / "5-path.json"
        doc = json.loads(path_doc.read_text())
        doc["true_path"]["sel_value"] = "00000000"
        path_doc.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        rc, scores = gr.grade("chain-l3-js-v1", ws)
        assert rc == gr.RC_FAIL
        layer = {l["id"]: l for l in scores["layers"]}["decoy-path"]
        assert layer["completed"] is False

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_clean_op_fails_on_polluted_strip(self, tmp_path):
        """Handing in the POLLUTED payload as the "stripped" artifact
        fails the junk-strip checkpoint (junk markers present) even
        though it still executes correctly."""
        gr = eval_chain_grader
        unit = ch.UNIT_BY_ID["chain-l3-js-v1"]
        cfg = mint_mod.stage_cfg(unit)
        cfg["task_id"] = "chain-l3-js-v1"
        cfg["unit"] = unit
        ref = mint_mod.reference_workspace(cfg)
        ws = tmp_path / "polluted"
        for rel, data in ref.items():
            f = ws / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        (ws / "layer_out" / "2-clean.js").write_bytes(
            mint_mod.tt.payload_bytes(cfg, True))  # polluted, not stripped
        rc, scores = gr.grade("chain-l3-js-v1", ws)
        assert rc == gr.RC_FAIL
        layer = {l["id"]: l for l in scores["layers"]}["junk-code"]
        assert layer["completed"] is False
        clean_ops = [o for o in layer["ops"] if o["op"] == "clean"]
        assert clean_ops and clean_ops[0]["pass"] is False

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_refusal_on_missing_workspace(self, tmp_path):
        gr = eval_chain_grader
        with pytest.raises(gr.Refusal):
            gr.grade("chain-l1-js-v1", tmp_path / "does-not-exist")

    @pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
    def test_refusal_on_bad_task(self, tmp_path):
        gr = eval_chain_grader
        with pytest.raises(gr.Refusal):
            gr.grade("no-such-unit", tmp_path)


# ------------------------------------------------- (f) self-check (CI face)
@pytest.mark.skipif(not CHAIN_TASKS.is_dir(), reason="corpus lands with the mint commit")
class TestSelfCheck:
    def _self_check(self, task_id):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "eval_chain_mint.py"),
             "--self-check", task_id],
            capture_output=True, text=True, timeout=600, cwd=str(ROOT))

    @pytest.mark.skipif(NODE_AVAILABLE is False, reason="node toolchain absent")
    def test_js_units_self_check_green(self):
        for task_id in ("chain-l1-js-v1", "chain-l2-js-v1",
                        "chain-l3-js-v1"):
            proc = self._self_check(task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout[-400:]}"

    @pytest.mark.skipif(NODE_AVAILABLE is False, reason="node toolchain absent")
    def test_py_units_self_check_green(self):
        for task_id in ("chain-l1-py-v1", "chain-l2-py-v1",
                        "chain-l3-py-v1"):
            proc = self._self_check(task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout[-400:]}"

    @pytest.mark.skipif(GO_AVAILABLE is False, reason="go toolchain absent")
    def test_go_unit_self_check_green(self):
        proc = self._self_check("chain-l2-go-v1")
        assert proc.returncode == 0, f"chain-l2-go-v1: {proc.stdout[-400:]}"
