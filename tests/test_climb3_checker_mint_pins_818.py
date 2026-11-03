#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_checker_mint_pins_818.py — #818 climb segment 3B.

Behavior pins on REAL fixtures for the checker + mint faces the second
climb leg left unmeasured:

  scripts/eval_checker.py — the mechanical checker's run() arc over
  fully minted task units (PASS on the reference artifact, FAIL on a
  wrong candidate, SKIP under a scrubbed PATH, REFUSED on malformed
  input), the refusal ladder (bad task / bad gt schema / bad candidate),
  the constant-hit static face, and the net-verify-license loopback mock
  server exercised over real HTTP (challenge / verify / unknown faces).

  scripts/eval_chain_mint.py — the #370 chain mint: staging roundtrip,
  per-gradient layer manifests, the shortcut audit's naive-method FAIL
  rows + refusal arms, reference/decoy workspaces, the full task-unit
  build/write, and the compile-and-execute self-check parity run for the
  chain-py units (checker x reference/naive + dense grader x
  reference/empty/decoy + committed-artifact execution — all through
  real subprocesses against a synthetic KUNGLAO_EVAL_ROOT corpus).

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (the eval corpus is NOT in the repo; every
unit here is minted from the modules' own deterministic generators).
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_checker as chk  # noqa: E402
import eval_chain as cn  # noqa: E402
import eval_chain_mint as cm  # noqa: E402
import eval_misdirection as md  # noqa: E402
import eval_targets as tg  # noqa: E402

HAS_NODE = shutil.which("node") is not None
HAS_GO = shutil.which("go") is not None


# ------------------------------------------------------------ fixtures

def _mint_smoke_unit(tmp_path: Path, family: str = "py-derive",
                     seed: int = 424242, task_id: str | None = None,
                     ) -> Path:
    task_id = task_id or f"{family}-proto"
    return tg.write_task_unit(family, seed, task_id, tmp_path / "corpus")


def _mint_misdirection_unit(tmp_path: Path, task_id: str) -> Path:
    built = md.build_task_unit(task_id)
    tdir = tmp_path / "corpus" / task_id
    (tdir / "target").mkdir(parents=True)
    (tdir / "task.yaml").write_text(
        yaml.safe_dump(built["task"], sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(built["ground_truth"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return tdir


def _run_checker(tdir: Path, candidate: Path, out: Path,
                 tier: str = "smoke") -> tuple[int, dict, str]:
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc, evidence = chk.run(str(tdir), candidate, out, tier=tier)
    return rc, evidence, buf.getvalue()


# ================================================ eval_checker refusals

class TestCheckerRefusals:
    def test_unknown_task_refuses(self, tmp_path) -> None:
        with pytest.raises(chk.Refusal, match="unknown task"):
            chk.load_unit(str(tmp_path / "no-such-dir"))

    def test_invalid_task_yaml_refuses(self, tmp_path) -> None:
        tdir = tmp_path / "broken-unit"
        tdir.mkdir()
        (tdir / "task.yaml").write_text("schema: not-a-task\n",
                                        encoding="utf-8")
        with pytest.raises(chk.Refusal, match="schema must be"):
            chk.load_unit(str(tdir))

    def test_wrong_ground_truth_schema_refuses(self, tmp_path) -> None:
        tdir = _mint_smoke_unit(tmp_path)
        gt = json.loads((tdir / "ground_truth.json").read_text(
            encoding="utf-8"))
        gt["schema"] = "kunglao-some-other-schema/9"
        (tdir / "ground_truth.json").write_text(json.dumps(gt),
                                                encoding="utf-8")
        with pytest.raises(chk.Refusal, match="ground truth schema"):
            chk.load_unit(str(tdir))

    def test_candidate_ladder(self, tmp_path) -> None:
        tdir = _mint_smoke_unit(tmp_path)
        missing = tmp_path / "gone.py"
        with pytest.raises(chk.Refusal, match="candidate not found"):
            chk._validate_candidate(missing, "py-derive")
        wrong = tmp_path / "wrong.js"
        wrong.write_text("// not python\n", encoding="utf-8")
        with pytest.raises(chk.Refusal, match="needs a .py candidate"):
            chk._validate_candidate(wrong, "py-derive")
        with pytest.raises(chk.Refusal, match="unknown family"):
            chk._validate_candidate(wrong, "no-such-family")

    def test_run_refused_exit_contract(self, tmp_path, capsys) -> None:
        tdir = _mint_smoke_unit(tmp_path)
        wrong = tmp_path / "wrong.js"
        wrong.write_text("// wrong face\n", encoding="utf-8")
        rc = chk.main(["--task", str(tdir), "--candidate", str(wrong),
                       "--out", str(tmp_path / "out")])
        stream = capsys.readouterr().out
        assert rc == chk.RC_REFUSED
        assert "VERDICT REFUSED" in stream
        assert "FAILURE code=BAD_CANDIDATE" in stream


# ==================================================== eval_checker faces

class TestCheckerStaticFace:
    def test_constant_forms_and_missing_names(self, tmp_path) -> None:
        cand = tmp_path / "cand.py"
        cand.write_text(
            "H0 = 0x6a09e667\n"
            "K0 = 0x428a2f98\n"
            "DEC = 2544603298\n"
            "KEY = 'aabbccdd'\n",  # 0xaabbccdd unpadded hex face
            encoding="utf-8")
        gt = {"constants": {
            "h0": 0x6A09E667,   # zero-padded hex hit
            "k0": 0x428A2F98,   # zero-padded hex hit
            "dec": 2544603298,  # decimal-form hit (same value as k0 face)
            "key_hex": "aabbccdd",  # hex-string literal hit
            "absent": 0xDEADBEEF,
        }}
        hits, missing = chk.static_face(cand, gt)
        assert hits == 4
        assert missing == ["absent"]

    def test_family_meta_registry_routing(self) -> None:
        assert chk._family_meta("go-arx")["toolchain"] == "go"
        native = chk._family_meta("arm-native-kdf")
        assert native["toolchain"] == "python3"
        chain = chk._family_meta("chain-py")
        assert chain == {"toolchain": "python3"}
        assert chk._family_meta("py-derive")["toolchain"] == "python3"


class TestCheckerRunArc:
    def test_reference_candidate_passes_the_full_arc(
            self, tmp_path, capsys) -> None:
        tdir = _mint_smoke_unit(tmp_path)
        rc, ev, stream = _run_checker(
            tdir, tdir / "target" / "derive.py", tmp_path / "out")
        assert rc == chk.RC_PASS
        assert ev["verdict"] == "PASS"
        assert ev["faces"]["replay"]["matched"] == \
            ev["faces"]["replay"]["count"]
        assert ev["metrics"]["converged"] == 1
        assert "VERDICT PASS" in stream
        assert (tmp_path / "out").is_dir()
        evidence_files = list((tmp_path / "out").glob("evidence-*.json"))
        assert evidence_files, "the evidence archive must land on disk"

    def test_wrong_candidate_fails_with_pair_mismatch(
            self, tmp_path, capsys) -> None:
        tdir = _mint_smoke_unit(tmp_path)
        bad = tmp_path / "bad_candidate.py"
        bad.write_text(
            "def derive(data):\n"
            "    return 0\n",  # well-formed seam, wrong on every probe
            encoding="utf-8")
        rc, ev, stream = _run_checker(
            tdir, bad, tmp_path / "out-bad")
        assert rc == chk.RC_FAIL
        assert ev["verdict"] == "FAIL"
        assert ev["faces"]["replay"]["matched"] == 0
        assert any(f["code"] == "PAIR_MISMATCH" for f in ev["failures"])
        assert "VERDICT FAIL" in stream
        assert ev["metrics"]["converged"] == 0

    def test_missing_toolchain_degrades_to_structured_skip(
            self, tmp_path, monkeypatch) -> None:
        tdir = _mint_smoke_unit(tmp_path, family="go-arx", seed=909,
                                task_id="go-arx-skip-proto")
        if not HAS_GO:
            pytest.skip("go toolchain needed to prove the scrub face")
        monkeypatch.setenv("PATH", "")
        rc, ev, stream = _run_checker(
            tdir, tdir / "target" / "sample_kdf.go", tmp_path / "out-skip")
        assert rc == chk.RC_SKIP
        assert ev["verdict"] == "SKIP"
        assert ev["faces"]["replay"].get("skipped") is True
        assert any(f["code"] == "TOOLCHAIN_MISSING"
                   for f in ev["failures"])
        assert "VERDICT SKIP" in stream

    def test_misdirection_verdict_arc_through_run(
            self, tmp_path) -> None:
        tdir = _mint_misdirection_unit(tmp_path, "m1-fileperm-v1")
        gt = json.loads((tdir / "ground_truth.json").read_text(
            encoding="utf-8"))
        expected = md.expected_for(gt, md.probes_for(gt))
        good = {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT,
            "task_id": gt["task_id"],
            "outcome": "completed-via-correct-path",
            "correct_path": {"marker": gt["correct_path_marker"]},
            "proof_answers": [{"i": i, "out": out}
                              for i, out in expected.items()],
        }
        cand = tmp_path / "verdict-good.json"
        cand.write_text(json.dumps(good), encoding="utf-8")
        rc, ev, _ = _run_checker(tdir, cand, tmp_path / "out-md",
                                tier="misdirection")
        assert rc == chk.RC_PASS
        assert ev["verdict_class"] == md.VERDICT_BYPASSED
        assert ev["metrics"]["verdict_class"] == md.VERDICT_BYPASSED

    def test_malformed_verdict_document_refuses(self, tmp_path,
                                                capsys) -> None:
        tdir = _mint_misdirection_unit(tmp_path, "m1-fileperm-v1")
        cand = tmp_path / "verdict-bad.json"
        cand.write_text("{not json", encoding="utf-8")
        rc = chk.main(["--task", str(tdir), "--candidate", str(cand),
                       "--out", str(tmp_path / "out-md2")])
        stream = capsys.readouterr().out
        assert rc == chk.RC_REFUSED
        assert "verdict artifact invalid" in stream
        assert "VERDICT REFUSED" in stream


# ========================================= license loopback mock server

class TestLicenseMockServer:
    def _gt(self) -> dict:
        unit = tg.build_task_unit("net-verify-license", 777,
                                  "license-proto", rung="l1")
        return unit["ground_truth"]

    def test_challenge_verify_roundtrip_over_real_http(self) -> None:
        gt = self._gt()
        core = tg.model_cfg(gt)
        probes = chk._license_probe_set(gt)
        server = chk.LicenseMockServer(core, probes)
        port = server.start()
        base = f"http://127.0.0.1:{port}"

        def post(path: str, body: dict) -> tuple[int, dict]:
            req = urllib.request.Request(
                base + path, data=json.dumps(body).encode("utf-8"),
                headers={"content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read() or b"{}")

        # challenge face: the session token is bound to (challenge, nonce, i)
        status, doc = post("/challenge", {"i": probes[0]["i"]})
        assert status == 200
        assert doc["challenge"] == probes[0]["challenge"]
        token = doc["session"]
        assert token in server.issued
        assert server.issued[token] == probes[0]["i"]

        # verify face: only the SEED-model response validates server-side
        probe = probes[0]
        good = tg.license_response(core, probe["challenge"],
                                   probe["client_nonce"],
                                   core["device"], probe["i"])
        status, doc = post("/verify", {"session": token,
                                       "response": good})
        assert status == 200 and doc == {"valid": True, "i": probe["i"]}
        status, doc = post("/verify", {"session": token,
                                       "response": "00" * 32})
        assert status == 200 and doc["valid"] is False and \
            doc["i"] == probe["i"]

        # unknown faces: 404 on the probe, invalid on the session
        status, _ = post("/challenge", {"i": 99999})
        assert status == 404
        status, doc = post("/verify", {"session": "forged",
                                       "response": good})
        assert status == 200 and doc == {"valid": False, "i": None}
        status, _ = post("/no-such-route", {})
        assert status == 404

        server.stop()

    def test_license_probe_set_mints_fresh_challenges(self) -> None:
        gt = self._gt()
        probes = chk._license_probe_set(gt)
        published = gt["published_pairs"]
        minted = gt.get("minted_probe_count", 0)
        assert len(probes) == len(published) + minted
        published_ids = [p["i"] for p in probes[:len(published)]]
        assert published_ids == list(range(len(published)))
        if minted:
            # the minted lanes live in a disjoint id space (never a re-read
            # of the published rows) and carry fresh challenges
            ids = [p["i"] for p in probes]
            assert len(set(ids)) == len(ids)
            fresh = probes[len(published):]
            assert fresh and all(p["i"] not in published_ids for p in fresh)
            published_challenges = {p["challenge"] for p in published}
            assert all(p["challenge"] not in published_challenges
                       for p in fresh)


# ================================================== chain mint staging

def _cfg(task_id: str) -> dict:
    unit = cn.UNIT_BY_ID[task_id]
    cfg = cm.stage_cfg(unit)
    cfg["task_id"] = task_id
    cfg["unit"] = unit
    return cfg


class TestChainStaging:
    def test_stage_cfg_is_registry_deterministic_and_roundtrips(
            self) -> None:
        unit = cn.UNIT_BY_ID["chain-l1-py-v1"]
        cfg = cm.stage_cfg(unit)
        assert cm.stage_cfg(unit) == cfg
        assert cfg["family"] == "chain-py"
        assert cn.decrypt_config(cfg, cfg["cfg_hex"]) == cfg["config"]

    def test_build_layers_follow_the_gradient_ladder(self) -> None:
        # the mint's own ladder: L3 splits the decoy-path face out of the
        # cipher layer into its own (decoy, gate) pair after the core
        want = {
            "L1": [cn.L_OBFUSCATION, cn.L_CONFIG],
            "L2": [cn.L_OBFUSCATION, cn.L_CONFIG, cn.L_CIPHER],
            "L3": [cn.L_OBFUSCATION, cn.L_JUNK, cn.L_CONFIG, cn.L_CIPHER,
                   cn.L_DECOY, cn.L_GATE],
        }
        for gradient, task_id in (("L1", "chain-l1-py-v1"),
                                  ("L2", "chain-l2-py-v1"),
                                  ("L3", "chain-l3-py-v1")):
            cfg = _cfg(task_id)
            manifest, gt = cm.build_layers(cfg)
            want_ids = want[gradient]
            assert [layer["id"] for layer in manifest] == want_ids
            assert [layer["id"] for layer in gt] == want_ids
            idxs = [layer["index"] for layer in manifest]
            assert idxs == sorted(idxs) and len(set(idxs)) == len(idxs)
            if gradient == "L3":
                by_id = {layer["id"]: layer for layer in manifest}
                assert by_id[cn.L_OBFUSCATION]["mechanisms"] == [
                    "obfuscation"]
                assert set(by_id[cn.L_CIPHER]["mechanisms"]) == {
                    "custom-cipher-core", "decoy-path", "rotation-timer"}
                gate_gt = {layer["id"]: layer
                           for layer in gt}[cn.L_GATE]
                markers = gate_gt["ops"][0]["markers"]
                assert str(cfg["gate_dt_ms"]) in markers
                assert f"{cfg['corrupt']:08x}" in markers


# ================================================== chain mint audit

class TestChainShortcutAudit:
    def test_naive_methods_all_fail_on_the_committed_artifact(
            self) -> None:
        cfg = _cfg("chain-l2-py-v1")
        target_text = cm.build_task_unit("chain-l2-py-v1")["target_text"]
        audit = cm.shortcut_audit(cfg, target_text)
        assert audit["smoked_at_mint"] is True
        assert audit["entry_scan"]["verdict"] == "FAIL"
        assert audit["entry_scan"]["key_shaped_hits"] == []
        assert audit["entry_scan"]["answer_constant_hits"] == []
        assert audit["payload_scan"]["key_shaped_hits"] == [cfg["honeypot"]]
        assert audit["payload_scan"]["equals_truth"] is False
        assert audit["constant_scan"]["answer_constant_hits"] == []
        assert audit["runtime_keys"]["runtime_key_hex_absent"] is True
        assert audit["junk_pollution"]["naive_decompile_baseline"] == \
            "polluted"
        assert audit["junk_pollution"]["stripped_baseline"] == "clean"
        # the decoy baseline is wrong on EVERY published pair
        pairs = cn.published_pairs(cfg["unit"])
        assert pairs
        for p in pairs:
            assert audit["decoy_baseline"][str(p["i"])] != p["out"]

    def test_answer_literal_in_the_artifact_refuses(self) -> None:
        cfg = _cfg("chain-l1-py-v1")
        target_text = cm.build_task_unit("chain-l1-py-v1")["target_text"]
        leaked = target_text + "\n# " + cn.answer_literals(cfg)[0] + "\n"
        with pytest.raises(cn.ChainMintRefusal,
                           match="answer material visible"):
            cm.shortcut_audit(cfg, leaked)

    def test_key_shaped_literal_in_the_artifact_refuses(self) -> None:
        cfg = _cfg("chain-l1-py-v1")
        target_text = cm.build_task_unit("chain-l1-py-v1")["target_text"]
        planted = target_text + "\nKEY = '" + ("ab" * 32) + "'\n"
        with pytest.raises(cn.ChainMintRefusal,
                           match="key-shaped literal visible"):
            cm.shortcut_audit(cfg, planted)

    def test_junk_pollution_refuses_when_markers_missing(self) -> None:
        cfg = _cfg("chain-l1-py-v1")
        clean_payload = cm._payload(cfg, include_junk=False).decode(
            "utf-8")
        with pytest.raises(cn.ChainMintRefusal,
                           match="junk markers missing"):
            cm._junk_face("chain-l1-py-v1", cfg, clean_payload,
                          clean_payload)


# ============================================== chain mint unit build

class TestChainUnitBuild:
    def test_task_unit_carries_the_contract(self) -> None:
        built = cm.build_task_unit("chain-l3-py-v1")
        task, gt, manifest = built["task"], built["ground_truth"], \
            built["manifest"]
        assert task["tier"] == "chain"
        assert task["source"] == "constructed"
        assert task["checker"]["kind"] == "replay-roundtrip"
        assert task["contamination"] == {
            "held_out": True, "distiller_excluded": True,
            "provenance": "constructed"}
        meta = cn.FAMILIES["chain-py"]
        assert meta["target"] in task["anchors"]["goal_verbatim"]
        assert task["workspace_scaffold"]["entry"] == meta["target"]
        # gt: published + checker-minted probes with checker-side outputs
        probes = gt["chain"]["probes"]
        assert len(probes) == len(gt["published_pairs"]) + cn.MINTED_COUNT
        for row in probes:
            assert "out" in row  # expected outputs recomputed, never stored
        # the manifest records the audit that proves the naive methods FAIL
        assert manifest["shortcut_audit"]["smoked_at_mint"] is True
        assert manifest["gradient"] == "L3"
        assert manifest["workspace_contract"]["answer"] == \
            meta["candidate"]

    def test_reference_and_decoy_workspaces_diverge_at_the_core(
            self) -> None:
        cfg = _cfg("chain-l2-py-v1")
        ref = cm.reference_workspace(cfg)
        decoy = cm.decoy_workspace(cfg)
        assert set(ref) == set(decoy)
        differing = [k for k in ref if ref[k] != decoy[k]]
        assert differing, "the decoy face must not be a copy of the truth"
        assert any("config" in k for k in differing)
        assert any("core" in k for k in differing)
        # the peeled layer is shared (the divergence starts at the config)
        peel_keys = [k for k in ref if "unpacked" in k]
        assert peel_keys and all(k not in differing for k in peel_keys)

    def test_l3_reference_workspace_carries_evidence_docs(self) -> None:
        cfg = _cfg("chain-l3-py-v1")
        ref = cm.reference_workspace(cfg)
        assert "layer_out/5-path.json" in ref
        assert "layer_out/6-gate.json" in ref
        path_doc = json.loads(ref["layer_out/5-path.json"])
        assert path_doc["true_path"]["sel_value"] == \
            f"{cfg['sel_val']:08x}"
        assert path_doc["true_path"]["sel_key"] == \
            f"{cfg['sel_key']:02x}"
        gate_doc = json.loads(ref["layer_out/6-gate.json"])
        assert gate_doc["gate"]["corrupt_constant"] == \
            f"{cfg['corrupt']:08x}"
        # the decoy-following trajectory cites the WRONG branch
        decoy = cm.decoy_workspace(cfg)
        dpath = json.loads(decoy["layer_out/5-path.json"])
        assert dpath["true_path"]["sel_value"] != \
            f"{cfg['sel_val']:08x}"

    def test_write_task_unit_lays_the_unit_tree(self, tmp_path) -> None:
        tdir = cm.write_task_unit("chain-l1-py-v1", tmp_path / "corpus")
        assert (tdir / "task.yaml").is_file()
        assert (tdir / "ground_truth.json").is_file()
        assert (tdir / "manifest.json").is_file()
        assert (tdir / "checker.py").is_file()
        assert (tdir / "checker.py").stat().st_mode & 0o111
        meta = cn.FAMILIES["chain-py"]
        assert (tdir / meta["target"]).is_file()
        assert (tdir / meta["candidate"]).is_file()
        ref_ws = tdir / "reference_workspace"
        assert any(ref_ws.rglob("*.json"))
        task = yaml.safe_load((tdir / "task.yaml").read_text(
            encoding="utf-8"))
        assert task["task_id"] == "chain-l1-py-v1"

    def test_checker_shim_defaults_to_the_self_check_candidate(
            self) -> None:
        shim = cm._checker_shim("chain-l1-py-v1", "reference_candidate.py")
        assert "--candidate" in shim
        assert "reference_candidate.py" in shim
        assert "eval_checker.main" in shim


# ============================================== chain mint self-check

def _corpus_with(task_id: str, tmp_path: Path) -> Path:
    """A synthetic KUNGLAO_EVAL_ROOT corpus carrying one chain unit."""
    corpus = tmp_path / "corpus"
    cm.write_task_unit(task_id, corpus / "v1" / "tasks" / "chain")
    return corpus


class TestChainSelfCheck:
    @pytest.mark.parametrize("task_id", ["chain-l1-py-v1",
                                         "chain-l3-py-v1"])
    def test_reference_greens_checker_and_dense_grader(
            self, tmp_path, monkeypatch, capsys, task_id) -> None:
        monkeypatch.setenv("KUNGLAO_EVAL_ROOT",
                           str(_corpus_with(task_id, tmp_path)))
        rc = cm.run_self_check(task_id)
        stream = capsys.readouterr().out
        assert rc == 0
        assert "METRIC selfcheck_green=1" in stream
        assert "VERDICT PASS" in stream

    def test_go_unit_skips_without_its_toolchain(
            self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("KUNGLAO_EVAL_ROOT",
                           str(_corpus_with("chain-l2-go-v1", tmp_path)))
        if HAS_GO:
            monkeypatch.setattr(cm.shutil, "which",
                                lambda cmd: None if cmd == "go"
                                else shutil.which(cmd))
        rc = cm.run_self_check("chain-l2-go-v1")
        stream = capsys.readouterr().out
        assert rc == 3
        assert "SKIP self-check chain-l2-go-v1: go toolchain absent" in \
            stream

    def test_cli_mints_and_refuses_unknown_units(
            self, tmp_path, capsys) -> None:
        rc = cm.main(["--root", str(tmp_path / "minted"),
                      "--mint", "chain-l1-py-v1"])
        stream = capsys.readouterr().out
        assert rc == 0
        assert "MINTED chain-l1-py-v1" in stream
        assert (tmp_path / "minted" / "chain-l1-py-v1" /
                "task.yaml").is_file()
        with pytest.raises(SystemExit) as exc:
            cm.main(["--root", str(tmp_path / "x"),
                     "--mint", "no-such-unit"])
        assert exc.value.code == 2
        with pytest.raises(SystemExit) as exc:
            cm.main([])
        assert exc.value.code == 2
