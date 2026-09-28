# -*- coding: utf-8 -*-
"""tests/test_eval_rust_so_crack.py — the rust-so-crack-v1 release unit.

The rust arm64 android .so family (owner directive 2026-09-29: 复杂加密 +
高级反调试/反分析, the E2E end-to-end target): mutated ChaCha20 KDF +
AES-shaped SPN (affine sbox variant + shifted rcon) + magic/checksum
double match, with stacked anti-analysis faces whose response is silent
keystream corruption.

Faces under test:
  - task unit validates against the shared contract (28-unit ladder);
  - committed artifact is a real ELF arm64 shared object under budget,
    exporting the two C-ABI seams;
  - ground truth: three graded constants, published pairs carry both
    verify==0 arms (real license + decoy fake success);
  - reference.py reproduces every published probe byte-exact (host
    cross-check: crackme_host replay agrees with reference.py);
  - checker self-check PASSES on reference.py; a wrong-constant candidate
    FAILS (probe mismatch + constant miss); a hidden host oracle degrades
    to a structured SKIP (rc 3, VERDICT SKIP);
  - determinism: crackme_host replay is byte-identical across runs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
UNIT = ROOT / "eval" / "v1" / "tasks" / "release" / "rust-so-crack-v1"
CHECKER = UNIT / "checker.py"
HOST = UNIT / "target" / "crackme_host"

sys.path.insert(0, str(SCRIPTS))

import eval_dataset as ds  # noqa: E402
from e2e import model  # noqa: E402

HOST_AVAILABLE = HOST.is_file() and HOST.stat().st_mode & 0o111


# ------------------------------------------------------------- unit/contract
class TestUnitContract:
    def test_task_validates(self):
        task = ds.load_task(UNIT)
        ok, errors = ds.validate_task(task)
        assert ok, errors
        assert task["tier"] == "release"
        assert task["eval_version"] == "eval-v1.1"
        assert task["source"] == "constructed"
        anchors = task["anchors"]
        assert anchors["verification_method"] == "reproduction"
        for key in ("goal_verbatim", "success_criterion"):
            assert anchors[key].strip()

    def test_release_ladder_counts_the_rust_unit(self):
        dirs = ds.iter_task_dirs(tier="release")
        assert UNIT.name in {d.name for d in dirs}
        assert len(dirs) == 28

    def test_artifact_is_elf_arm64_under_budget(self):
        so = UNIT / "target" / "libcrackme.so"
        assert so.is_file()
        assert so.stat().st_size <= 200 * 1024
        assert so.read_bytes()[:4] == b"\x7fELF"
        # the two C-ABI seams are exported dynamic symbols
        out = subprocess.run(
            ["nm", "-D", str(so)], capture_output=True, text=True)
        if out.returncode == 0:
            names = out.stdout
            assert "crackme_verify" in names
            assert "crackme_probe" in names

    def test_held_out_oracle_not_in_scaffold(self):
        task = ds.load_task(UNIT)
        files = task["workspace_scaffold"]["files"]
        assert "target/libcrackme.so" in files
        assert "crackme_host" not in json.dumps(files)
        cont = task["contamination"]
        assert cont["held_out"] is True
        assert cont["distiller_excluded"] is True


# ------------------------------------------------------------- ground truth
class TestGroundTruth:
    def test_three_graded_constants(self):
        gt = json.loads((UNIT / "ground_truth.json").read_text(
            encoding="utf-8"))
        consts = gt["constants"]
        assert len(consts) == 3
        # the graded constants must NOT be stock crypto values
        assert consts["sigma_constant"] != 0x61707865
        assert consts["sbox_seed"] not in (0, 1)
        assert gt["space_bits"] >= 128
        assert ds.guess_pass_p(gt["space_bits"]) < 1e-38

    def test_published_pairs_carry_both_success_arms(self):
        gt = json.loads((UNIT / "ground_truth.json").read_text(
            encoding="utf-8"))
        pairs = gt["published_pairs"]
        assert len(pairs) == 10
        zeros = [p for p in pairs if p["verify"] == 0]
        assert len(zeros) == 2, "real-lane + decoy-lane success arms"
        assert any(p["input"][0] == 0x44 and p["input"][1] == 0x45
                   for p in zeros), "decoy lane exercised"
        assert gt["minted_probe_count"] >= 4

    def test_anti_debug_response_is_silent_corruption(self):
        gt = json.loads((UNIT / "ground_truth.json").read_text(
            encoding="utf-8"))
        ad = gt["anti_debug"]
        assert ad["response"] == "silent-corruption"
        faces = " ".join(ad["faces"]).lower()
        for needle in ("traceme", "tracerpid", "clock", "brk", "frida"):
            assert needle in faces, f"face missing: {needle}"


# --------------------------------------------------- reference / host oracle
def _run_host_replay(inputs: list[bytes]):
    stdin = "".join(
        json.dumps({"i": i, "input": list(b)}) + "\n"
        for i, b in enumerate(inputs))
    proc = subprocess.run([str(HOST), "replay"], input=stdin,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


class TestReferenceAndHost:
    def test_reference_reproduces_published_probes(self):
        sys.path.insert(0, str(UNIT))
        import reference  # noqa: E402
        gt = json.loads((UNIT / "ground_truth.json").read_text(
            encoding="utf-8"))
        for p in gt["published_pairs"]:
            data = bytes(p["input"])
            assert reference.verify(data) == p["verify"], f"i={p['i']}"
            assert reference.probe(data) == p["probe"], f"i={p['i']}"

    @pytest.mark.skipif(not HOST_AVAILABLE, reason="crackme_host absent")
    def test_host_agrees_with_reference_on_fresh_inputs(self):
        sys.path.insert(0, str(UNIT))
        import reference  # noqa: E402
        # inputs OUTSIDE the published set: the mint lane shape
        fresh = [
            bytes(range(60, 76)),
            bytes((j * 31 + 7) & 0xFF for j in range(19)),
            b"\x44\x45" + bytes(range(0x30, 0x40)),
            bytes([0xC0] * 23),
        ]
        rows = _run_host_replay(fresh)
        for row, data in zip(rows, fresh):
            assert row["verify"] == reference.verify(data)
            assert row["probe"] == reference.probe(data)

    @pytest.mark.skipif(not HOST_AVAILABLE, reason="crackme_host absent")
    def test_host_deterministic_across_runs(self):
        inputs = [bytes(range(0x10, 0x30)), bytes([0x5A] * 17)]
        first = _run_host_replay(inputs)
        second = _run_host_replay(inputs)
        assert first == second

    @pytest.mark.skipif(not HOST_AVAILABLE, reason="crackme_host absent")
    def test_host_selftest_green(self):
        proc = subprocess.run([str(HOST), "selftest"],
                              capture_output=True, text=True, timeout=180)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        doc = json.loads(proc.stdout.strip().splitlines()[-1])
        assert doc["ok"] is True
        assert doc["fips197_aes128"] is True, \
            "stock face must be real AES-128 (FIPS-197 vector)"


# ------------------------------------------------------------------- checker
def _run_checker(candidate: Path | None, tmp_path: Path):
    argv = [sys.executable, str(CHECKER),
            "--out", str(tmp_path / "ev")]
    if candidate is not None:
        argv += ["--candidate", str(candidate)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=300)


class TestCheckerFaces:
    def test_self_check_passes_and_parses(self, tmp_path):
        proc = _run_checker(None, tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        parsed = model.parse_checker_output(proc.stdout)
        assert parsed["verdict"] == "PASS"
        assert parsed["metrics"]["pass_at_k_contribution"] == 1
        assert parsed["evidence_path"]
        ev = json.loads(Path(parsed["evidence_path"]).read_text(
            encoding="utf-8"))
        replay = ev["faces"]["replay"]
        # 10 published + 8 checker-minted probes, all reproduced
        assert replay["matched"] == replay["count"] == 18

    def test_wrong_constant_candidate_fails(self, tmp_path):
        src = (UNIT / "reference.py").read_text(encoding="utf-8")
        wrong = tmp_path / "wrong_sigma.py"
        wrong.write_text(
            src.replace("SIGMA_MUT = 0x5BD1B3C1",
                        "SIGMA_MUT = 0x61707865"),
            encoding="utf-8")
        proc = _run_checker(wrong, tmp_path)
        assert proc.returncode == 1
        parsed = model.parse_checker_output(proc.stdout)
        assert parsed["verdict"] == "FAIL"
        assert any("PAIR_MISMATCH" in f for f in parsed["failures"])
        assert any("CONSTANT_MISS" in f for f in parsed["failures"])

    def test_stock_crypto_candidate_fails(self, tmp_path):
        """The family's anti-standard regression: stock ChaCha sigma +
        stock-AES-shaped sbox/rcon + unrelated magic reproduces nothing."""
        src = (UNIT / "reference.py").read_text(encoding="utf-8")
        stock = tmp_path / "stock_crypto.py"
        stock.write_text(
            src.replace("SIGMA_MUT = 0x5BD1B3C1", "SIGMA_MUT = 0x61707865")
               .replace("SBOX_SEED = 0x2F6E8D1B", "SBOX_SEED = 0x00000001")
               .replace(
                   'MAGIC = bytes.fromhex('
                   '"8ca637c14ed29b6021fa8d3c770eb954")',
                   'MAGIC = bytes.fromhex('
                   '"00112233445566778899aabbccddeeff")'),
            encoding="utf-8")
        proc = _run_checker(stock, tmp_path)
        assert proc.returncode == 1
        parsed = model.parse_checker_output(proc.stdout)
        assert parsed["verdict"] == "FAIL"
        ev = json.loads(Path(parsed["evidence_path"]).read_text(
            encoding="utf-8"))
        assert ev["faces"]["replay"]["matched"] == 0

    def test_hidden_host_oracle_degrades_to_skip(self, tmp_path,
                                                 monkeypatch):
        if not HOST_AVAILABLE:
            pytest.skip("crackme_host absent")
        hidden = tmp_path / "crackme_host"
        shutil.move(str(HOST), str(hidden))
        try:
            proc = _run_checker(None, tmp_path)
        finally:
            shutil.move(str(hidden), str(HOST))
        assert proc.returncode == 3
        parsed = model.parse_checker_output(proc.stdout)
        assert parsed["verdict"] == "SKIP"
        assert any("TOOLCHAIN_MISSING" in f for f in parsed["failures"])

    def test_bad_candidate_suffix_refused(self, tmp_path):
        blob = tmp_path / "candidate.js"
        blob.write_text("// not a python candidate\n", encoding="utf-8")
        proc = _run_checker(blob, tmp_path)
        assert proc.returncode == 2
        assert "VERDICT REFUSED" in proc.stdout
