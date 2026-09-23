# -*- coding: utf-8 -*-
"""tests/test_eval_native_332.py — #332 eval-ladder v1.1 NATIVE half.

The release-tier contract for the native families (arm-native-kdf /
win-pe-kdf / smc-x86 / mod-crypto-native) and the mod-crypto mutation core
they all consume. Pure Python only: no subprocess, no native toolchain —
every face here runs on committed bytes and generator models (the mint is
the only toolchain consumer; its structured toolchain-skip is tested as a
pure discovery function).

Faces:
  (a) REGISTRY — four native families registered, twelve release-tier
      units (base rungs L0/L1/L2, win +L2p, mod variants L1/L2), one seed
      per family;
  (b) MOD-CRYPTO CORE (eval_crypto.py): seeded mutation of AES-128 (S-box =
      standard S-box composed with a seeded permutation; mutated Rcon) and
      SHA-256 (mutated H/K) — bijective S-box, FIPS-197/FIPS-180 vector
      pins on STANDARD parameters, anti-standard divergence on mutated
      parameters (a stock-AES / hashlib candidate is wrong by construction);
  (c) MODELS/WIRES — ground truth by construction: reference-model cross
      check, published vs checker-minted probe faces disjoint, wire
      encoding round shapes, self-check reference source equals the model;
  (d) LANDED CORPUS — every release unit validates, backward-compat with
      smoke (eval-v1), schema enums extended, committed artifacts carry
      their graded constants and anti-debug (addition-B) signatures as raw
      bytes where deterministic, magic headers, the <200KB size budget,
      UPX/SMC ground-truth records where the artifact is
      nondeterministic/encrypted;
  (e) VERSIONING — the eval-v1.1 additive bump (VERSION file stays
      eval-v1; new units mint eval-v1.1; changelog + README record the
      release tier).
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import eval_native_sources as src
import eval_crypto as xc
import eval_dataset as ds
import eval_native_targets as ntg
import eval_targets as tg

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "eval-task-v1.json"
RELEASE = ROOT / "eval" / "v1" / "tasks" / "release"
SMOKE = ROOT / "eval" / "v1" / "tasks" / "smoke"
ARTIFACT_BUDGET = 200 * 1024
M32 = 0xFFFFFFFF

FAMILY_BY_TASK = {u["task_id"]: u for u in ntg.UNITS}


def _fmt_const(value: int) -> str:
    """The constant-carrying forms the static face accepts (hex-first)."""
    return f"HEX = 0x{value:08x}"


# ---------------------------------------------------------------- (a) registry
class TestNativeRegistry:
    def test_four_native_families_registered(self):
        for family in ("arm-native-kdf", "win-pe-kdf", "smc-x86",
                       "mod-crypto-native"):
            assert family in ntg.FAMILIES, f"{family} missing from registry"
            assert family in ntg.FAMILY_SEEDS
            assert family in ntg.NATIVE_FAMILIES

    def test_family_seeds_pinned(self):
        assert ntg.FAMILY_SEEDS == {
            "arm-native-kdf": 33201,
            "win-pe-kdf": 33202,
            "smc-x86": 33203,
            "mod-crypto-native": 33204,
        }
        # one seed per family, disjoint from every other registered
        # family's pinned seed (#299 smoke pins family-level seeds; the
        # #332b web/net families seed per unit, so no family-level key)
        other_seeds = {m["seed"] for m in tg.FAMILIES.values()
                       if m.get("seed") is not None}
        assert other_seeds.isdisjoint(set(ntg.FAMILY_SEEDS.values()))

    def test_twelve_release_units_with_rungs(self):
        assert len(ntg.UNITS) == 12
        rungs = {}
        for u in ntg.UNITS:
            rungs.setdefault(u["family"], []).append(u["rung"])
        assert sorted(rungs["arm-native-kdf"]) == ["l0", "l1", "l2"]
        assert sorted(rungs["win-pe-kdf"]) == ["l0", "l1", "l2", "l2p"]
        assert sorted(rungs["smc-x86"]) == ["l0", "l1", "l2"]
        assert sorted(rungs["mod-crypto-native"]) == ["l1", "l2"]

    def test_task_ids_wellformed_and_unique(self):
        ids = [u["task_id"] for u in ntg.UNITS]
        assert len(ids) == len(set(ids))
        for tid in ids:
            assert tid.replace("-", "").isalnum() and tid == tid.lower()

    def test_minted_variants_diverge_from_stock_crypto(self):
        """The anti-memorization property: every family's mutated SHA-256
        diverges from hashlib on the same input (a standard-lib candidate
        is wrong by construction)."""
        for seed in ntg.FAMILY_SEEDS.values():
            digest = xc.mod_sha256(seed, b"kunglao")
            assert digest != hashlib.sha256(b"kunglao").digest()


# ---------------------------------------------------------- (b) mod-crypto core
class TestModCryptoCore:
    def test_sbox_is_bijective_and_standard_at_seed_zero(self):
        assert xc.mutated_sbox(0) == xc.STANDARD_SBOX
        for seed in (33201, 33202, 33203, 33204, 1):
            sbox = xc.mutated_sbox(seed)
            assert sorted(sbox) == list(range(256)), "S-box must be a bijection"
            assert sbox != xc.STANDARD_SBOX, "mutated S-box must diverge"

    def test_fips197_aes128_vector_on_standard_parameters(self):
        # FIPS-197 Appendix C.1: AES-128 key 000102...0f, plaintext
        # 00112233445566778899aabbccddeeff -> cipher 69c4e0d86a7b0430...
        key = bytes(range(16))
        pt = bytes.fromhex("00112233445566778899aabbccddeeff")
        ct = xc.aes128_block(0, pt, key)
        assert ct == bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

    def test_fips180_sha256_vector_on_standard_parameters(self):
        assert (xc.mod_sha256(0, b"abc").hex() ==
                "ba7816bf8f01cfea414140de5dae2223"
                "b00361a396177a9cb410ff61f20015ad")

    def test_mutated_aes_rcon_and_sbox_diverge(self):
        rcon = xc.mutated_rcon(33201)
        assert rcon != xc.STANDARD_RCON and all(rcon) and len(rcon) == 10
        assert xc.mutated_rcon(0) == xc.STANDARD_RCON

    def test_mutated_h_k_diverge_but_keep_shape(self):
        h, k = xc.mutated_h(33201), xc.mutated_k(33201)
        assert len(h) == 8 and len(k) == 64
        assert h != xc.STANDARD_H and k != xc.STANDARD_K
        assert xc.mutated_h(0) == xc.STANDARD_H
        assert xc.mutated_k(0) == xc.STANDARD_K

    def test_deterministic_across_calls(self):
        a = xc.mod_sha256(33203, b"probe")
        b = xc.mod_sha256(33203, b"probe")
        assert a == b
        assert xc.payload_transform(33203, b"x" * 32) == \
            xc.payload_transform(33203, b"x" * 32)

    def test_kdf_counter_mode_shape(self):
        out = xc.kdf_sha(33201, b"seed-input", 2)
        assert len(out) == 64
        assert out[:32] == xc.mod_sha256(33201, b"seed-input" + (0).to_bytes(4, "little"))
        assert out[32:] == xc.mod_sha256(33201, b"seed-input" + (1).to_bytes(4, "little"))


# -------------------------------------------------------------- (c) models/wires
class TestModelsAndWires:
    def test_constants_exposed_per_family(self):
        for family in ntg.NATIVE_FAMILIES:
            cfg = ntg.derive_cfg(family, ntg.FAMILY_SEEDS[family])
            consts = ntg.constants_public(family, cfg)
            assert consts and all(isinstance(v, int) for v in consts.values())

    def test_model_output_matches_direct_core(self):
        for family in ("arm-native-kdf", "win-pe-kdf"):
            cfg = ntg.derive_cfg(family, ntg.FAMILY_SEEDS[family])
            data = bytes(range(32))
            assert ntg.model_output(family, cfg, 0, list(data)) == \
                xc.kdf_sha(ntg.FAMILY_SEEDS[family], data).hex()
        for family in ("smc-x86", "mod-crypto-native"):
            cfg = ntg.derive_cfg(family, ntg.FAMILY_SEEDS[family])
            data = bytes(range(32))
            assert ntg.model_output(family, cfg, 0, list(data)) == \
                xc.payload_transform(ntg.FAMILY_SEEDS[family], data).hex()

    def test_published_and_minted_faces_disjoint(self):
        for family in ntg.NATIVE_FAMILIES:
            seed = ntg.FAMILY_SEEDS[family]
            pub = ntg.published_pairs(family, seed, count=8)
            minted = ntg.minted_probes(family, seed, count=8)
            assert [p["i"] for p in pub] == list(range(8))
            assert [p["i"] for p in minted] == list(range(100, 108))
            pub_inputs = {tuple(p["input"]) for p in pub}
            mint_inputs = {tuple(p["input"]) for p in minted}
            assert pub_inputs.isdisjoint(mint_inputs)
            # checker recomputes the same minted stream (stored nowhere)
            again = ntg.minted_probes(family, seed, count=8)
            assert again == minted

    def test_wire_shape_roundtrip(self):
        """32-byte input -> hex output on every family's wire."""
        for family in ntg.NATIVE_FAMILIES:
            seed = ntg.FAMILY_SEEDS[family]
            pairs = ntg.published_pairs(family, seed, count=3)
            for p in pairs:
                assert len(p["input"]) == 32
                assert isinstance(p["out"], str) and len(p["out"]) in (32, 128)
                bytes.fromhex(p["out"])  # must be hex


# ------------------------------------------------------------- (d) landed corpus
class TestLandedCorpus:
    def test_every_release_unit_validates(self):
        dirs = ds.iter_task_dirs(tier="release")
        # the merged #332 inventory: 12 native (this lane) + 15 web/net
        # (#332b: web-pack-sign x5, mod-crypto-js x4, req-sign x3,
        # net-verify-license x3) = one 27-unit release ladder
        assert len(dirs) == 27
        landed_ids = {d.name for d in dirs}
        assert {u["task_id"] for u in ntg.UNITS} <= landed_ids
        for tdir in dirs:
            task = ds.load_task(tdir)
            ok, errors = ds.validate_task(task)
            assert ok, f"{tdir.name}: {errors}"

    def test_smoke_backward_compat(self):
        for tdir in ds.iter_task_dirs(tier="smoke"):
            task = ds.load_task(tdir)
            ok, errors = ds.validate_task(task)
            assert ok, f"{tdir.name}: {errors}"
            assert task["eval_version"] == "eval-v1"

    def test_schema_enums_extended(self):
        """The enum ladder is additive: the release additions from this
        card stay, later tiers append (misdirection at eval-v1.2,
        toolflex at eval-v1.3); the earlier entries never move."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        tiers = set(schema["properties"]["tier"]["enum"])
        assert {"smoke", "release"} <= tiers
        assert set(schema["properties"]["eval_version"]["enum"]) >= \
            {"eval-v1", "eval-v1.1"}
        assert list(schema["properties"]["eval_version"]["enum"])[:2] == \
            ["eval-v1", "eval-v1.1"]

    def test_release_units_stamp_v11(self):
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            assert task["eval_version"] == "eval-v1.1"
            assert task["tier"] == "release"
            assert task["source"] == "constructed"

    def test_native_artifact_magic_and_budget(self):
        """Deterministic artifacts commit as real bytes with the right
        magic; win-pe commits source + build record (PE > budget, see
        ground-truth build_record)."""
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            family = task["family"]
            gt = json.loads(
                (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            for f in task["workspace_scaffold"]["files"]:
                path = tdir / f
                assert path.is_file(), f"{tdir.name}: missing {f}"
                assert path.stat().st_size <= ARTIFACT_BUDGET, \
                    f"{tdir.name}/{f}: over the 200KB artifact budget"
                blob = path.read_bytes()
                if family in ("arm-native-kdf", "mod-crypto-native") \
                        and f.endswith(".so"):
                    assert blob[:4] == b"\x7fELF"
                if family == "smc-x86" and f.endswith((".elf",)):
                    assert blob[:4] == b"\x7fELF"
                if family == "win-pe-kdf" and f.endswith(".go"):
                    assert b"package main" in blob
                    record = gt["build_record"]
                    assert record["magic"] == "MZ"
                    assert record["goos"] == "windows"
                    assert record["goarch"] == "amd64"
                    assert "sha256" in record and "size" in record

    def test_committed_binaries_carry_graded_constants(self):
        """The static-face ground truth: deterministic committed artifacts
        carry their graded constants as raw bytes (L2p/SMC units verify via
        records instead — UPX compresses, SMC encrypts)."""
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            gt = json.loads(
                (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            if gt.get("constants_record_mode") != "raw-bytes":
                continue
            blob = b"".join(
                (tdir / f).read_bytes()
                for f in task["workspace_scaffold"]["files"])
            for name, value in gt["constants"].items():
                forms = [f"{value:08x}".encode(), str(value).encode(),
                         (value & M32).to_bytes(4, "little"),
                         (value & M32).to_bytes(4, "big")]
                if value < 256:
                    forms.append(bytes([value]))
                assert any(form in blob for form in forms), \
                    f"{tdir.name}: graded constant {name} absent from bytes"

    def test_anti_debug_signatures_in_artifacts(self):
        """Addition B is ground truth: every family's artifact (for the
        win face: its committed source) carries the anti-debug signature
        bytes; the mechanical scan is byte-exact."""
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            if task["family"] not in ntg.NATIVE_FAMILIES:
                continue  # addition B is the native lane's ground truth;
                # the #332b web/net units carry their own stamp contracts
                # (pinned by tests/test_eval_release_332.py)
            gt = json.loads(
                (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            ad = gt["anti_debug"]
            assert ad["response"] == "silent-corruption"
            blob = b"".join((tdir / f).read_bytes()
                            for f in task["workspace_scaffold"]["files"])
            found = ntg.anti_debug_face(task["family"], gt, blob)
            assert found, f"{tdir.name}: no anti-debug signature found"

    def test_smc_ground_truth_records_decrypted_payload(self):
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            if task["family"] != "smc-x86":
                continue
            gt = json.loads(
                (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            rec = gt["smc_record"]
            payload = bytes.fromhex(rec["payload_hex"])
            key = bytes.fromhex(rec["xor_key"])
            clear = bytes(b ^ key[i % len(key)] for i, b in enumerate(payload))
            assert hashlib.sha256(clear).hexdigest() == rec["decrypted_sha256"]
            # the artifact's own byte scan (raw .rodata tables) covers the
            # graded constants; this face pins the SMC payload integrity
            blob = b"".join((tdir / f).read_bytes()
                            for f in task["workspace_scaffold"]["files"])
            assert payload in blob, \
                "the encrypted payload bytes must be embedded in the artifact"

    def test_upx_l2p_record_verifies_by_unpacking(self):
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name.endswith("l2p"))
        task = ds.load_task(tdir)
        gt = json.loads(
            (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
        rec = gt["upx_record"]
        assert rec["packed"] is True
        assert rec["test_ok"] is True
        assert rec["unpack_ok"] is True
        assert rec["nondeterminism"] == "pe-timestamp"
        assert rec["unpacked_sha256"]
        # unpacked image carries the graded constants (the pack hides them)
        hits = rec["unpacked_constant_hits"]
        assert hits and all(hits.values()), \
            f"unpacked image must carry constants: {hits}"
        assert rec["packed_size"] < rec["unpacked_size"]

    def test_committed_artifacts_hash_stable(self):
        """Every committed binary artifact's sha256 is pinned in its ground
        truth (deterministic re-mint: byte-identical rebuild)."""
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            gt = json.loads(
                (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            for f in task["workspace_scaffold"]["files"]:
                if f.endswith((".so", ".elf")):
                    digest = hashlib.sha256(
                        (tdir / f).read_bytes()).hexdigest()
                    assert gt["artifact_sha256"][f] == digest


# ---------------------------------------------------------- (e) versioning
class TestVersioning:
    def test_version_file_stays_eval_v1(self):
        assert (ROOT / "eval" / "v1" / "VERSION").read_text().strip() == \
            "eval-v1"

    def test_changelog_records_release_tier(self):
        text = (ROOT / "eval" / "v1" / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "eval-v1.1" in text and "release" in text

    def test_eval_readme_records_release_tier(self):
        text = (ROOT / "eval" / "README.md").read_text(encoding="utf-8")
        assert "release" in text

    def test_tier_version_map(self):
        assert ds.EVAL_TIER_VERSION["smoke"] == "eval-v1"
        assert ds.EVAL_TIER_VERSION["release"] == "eval-v1.1"

    def test_guess_baseline_arithmetic(self):
        for tdir in ds.iter_task_dirs(tier="release"):
            task = ds.load_task(tdir)
            p = ds.guess_pass_p(task["ground_truth"]["space_bits"])
            assert 0 < p < 1e-32


# ----------------------------------------------- cheat regressions (checker)
class TestCheatRegressions:
    """Per-family cheat faces, graded by the REAL checker on the landed
    corpus with checker-minted probes."""

    def _check(self, task_id: str, candidate: Path, tmp_out: Path):
        import subprocess
        import sys
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_checker.py"),
             "--task", task_id, "--candidate", str(candidate),
             "--out", str(tmp_out), "--tier", "release"],
            capture_output=True, text=True, timeout=240, cwd=str(ROOT))

    def _unit_dir(self, task_id: str) -> Path:
        hits = [d for d in ds.iter_task_dirs(tier="release")
                if d.name == task_id]
        assert hits, f"release unit {task_id} not landed"
        return hits[0]

    def _reference(self, task_id: str) -> Path:
        return self._unit_dir(task_id) / "reference.py"

    def test_reference_self_check_passes_all_l1_families(self, tmp_path: Path):
        """The minutes-scale L1 face: every family's L1 unit greens on its
        reference candidate through the real checker."""
        for task_id in ("arm-kdf-l1", "win-kdf-l1", "smc-x86-l1",
                        "mod-crypto-l1"):
            proc = self._check(task_id, self._reference(task_id), tmp_path)
            assert "VERDICT PASS" in proc.stdout, \
                f"{task_id}: {proc.stdout[-400:]}"

    def test_constants_copy_only_fails(self, tmp_path: Path):
        """A candidate carrying every graded constant but no algorithm
        must green the static face and FAIL the pair face."""
        tdir = self._unit_dir("arm-kdf-l1")
        gt = json.loads((tdir / "ground_truth.json").read_text(encoding="utf-8"))
        lines = [f"# cheat: constants only\n{_fmt_const(v)}\n"
                 for v in gt["constants"].values()]
        cand = tmp_path / "cheat_constants.py"
        cand.write_text("\n".join(lines), encoding="utf-8")
        proc = self._check("arm-kdf-l1", cand, tmp_path)
        assert "VERDICT FAIL" in proc.stdout
        assert "PAIR_MISMATCH" in proc.stdout

    def test_digest_table_fails_on_minted_probes(self, tmp_path: Path):
        """Hardcoding the published pairs (a digest-table candidate) must
        fail on the checker-minted probes."""
        tdir = self._unit_dir("win-kdf-l1")
        gt = json.loads((tdir / "ground_truth.json").read_text(encoding="utf-8"))
        cand = tmp_path / "cheat_table.py"
        cand.write_text(
            "import json\n_TABLE = " + json.dumps(
                {str(p["i"]): p["out"] for p in gt["published_pairs"]}) + "\n"
            "def kdf_derive(data):\n"
            "    return '00' * 64 if len(data) != 32 else _TABLE.get('0', '00' * 64)\n",
            encoding="utf-8")
        proc = self._check("win-kdf-l1", cand, tmp_path)
        assert "VERDICT FAIL" in proc.stdout
        assert "PAIR_MISMATCH" in proc.stdout

    def test_standard_lib_candidate_fails_everywhere(self, tmp_path: Path):
        """The mod-crypto anti-standard regression: hashlib / stock-shape
        candidates must fail every native family (mutated H/K diverge on
        the first block, so even one probe cannot pass)."""
        stock_by_family = {
            "arm-kdf-l1": (
                "import hashlib\n"
                "def kdf_derive(data):\n"
                "    return hashlib.sha256(data).digest().hex() * 2\n"),
            "win-kdf-l1": (
                "import hashlib\n"
                "def kdf_derive(data):\n"
                "    return hashlib.sha256(data).digest().hex() * 2\n"),
            "smc-x86-l1": (
                "import hashlib\n"
                "def payload_derive(data):\n"
                "    return hashlib.sha256(data).digest()[:16].hex()\n"),
            "mod-crypto-l1": (
                "import hashlib\n"
                "def mod_kdf(data):\n"
                "    return hashlib.sha256(data).digest()[:16].hex()\n"),
        }
        for task_id, stock in stock_by_family.items():
            cand = tmp_path / f"cheat_stdlib_{task_id}.py"
            cand.write_text(stock, encoding="utf-8")
            proc = self._check(task_id, cand, tmp_path)
            assert "VERDICT FAIL" in proc.stdout, f"{task_id} went green"


# --------------------------------- artifact==model dynamic regressions (r2)
class TestArtifactEqualsModel:
    """The FIX-1 bug class: the checker's replay face never executes the
    native binaries, so an artifact that silently disagrees with its seed
    model would pass unnoticed. These faces compile the generated C for
    the HOST and execute it against the model (same source the NDK
    compiles; the corpus re-mints byte-identically), plus the native
    ctypes face where the committed .so is loadable."""

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_native_targets.py"),
             *args], capture_output=True, text=True, timeout=240, cwd=str(ROOT))

    def test_arm_c_hashes_the_model_message(self):
        """Static face: the C's message construction must be exactly the
        model's (n data bytes + 4-byte LE counter = 36 bytes for the 32B
        wire) — no uninitialized buffer bytes, no wrong hash length."""
        cfg = ntg.derive_cfg("arm-native-kdf",
                             ntg.FAMILY_SEEDS["arm-native-kdf"])
        text = src.render_arm_c(cfg)
        assert "mod_sha256(cat, n + 4u, dig)" in text
        assert "mod_sha256(cat, 64" not in text
        assert "cat[n] = (unsigned char)blk;" in text
        assert "cat[60] =" not in text
        model_msg = 32 + 4
        assert len(b"x" * 32 + (0).to_bytes(4, "little")) == model_msg

    def test_host_compiled_c_matches_model_all_c_families(self):
        """Dynamic face: for every C family and the L1/L2 rungs, the
        generated source is compiled for the host and executed; outputs
        must equal the seed model byte-exact (this is the check that
        catches artifact != model)."""
        have_cc = shutil.which("clang") or shutil.which("cc")
        if not have_cc:
            pytest.skip("no host C compiler")
        for task_id in ("arm-kdf-l1", "arm-kdf-l2", "mod-crypto-l1",
                        "mod-crypto-l2", "smc-x86-l1", "smc-x86-l2"):
            proc = self._cli("--self-check", task_id)
            assert "VERDICT PASS" in proc.stdout, \
                f"{task_id}: {proc.stdout[-300:]}"

    def test_committed_arm_so_matches_model_when_native(self):
        """The REAL committed artifact face: on linux/arm64 the committed
        .so is loaded via ctypes and executed against the model.
        Structured SKIP everywhere else (this host cannot execute arm64)."""
        if not (sys.platform == "linux"
                and platform.machine() in ("aarch64", "arm64")):
            pytest.skip("committed .so execution needs linux/arm64")
        for task_id in ("arm-kdf-l1", "arm-kdf-l2"):
            proc = self._cli("--self-check", task_id)
            assert "native-ctypes" in proc.stdout
            assert "VERDICT PASS" in proc.stdout

    def test_l2_flattening_dispatcher_present_in_shape(self):
        """FIX-2 face: the L2 dispatcher must SURVIVE compilation — the
        entry function's disassembly carries the case compares (cmpl
        against state 1 and 2) that the clean L1 shape lacks."""
        have_cc = shutil.which("clang") or shutil.which("cc")
        if not have_cc:
            pytest.skip("no host C compiler")
        for task_id in ("arm-kdf-l1", "arm-kdf-l2", "smc-x86-l1",
                        "smc-x86-l2", "mod-crypto-l1", "mod-crypto-l2"):
            proc = self._cli("--flatten-check", task_id)
            assert "VERDICT PASS" in proc.stdout, \
                f"{task_id}: {proc.stdout[-300:]}"

    def test_flattened_text_size_grows_where_stable(self):
        """Size regression on the families where codegen is stable
        (arm/smc committed .text, win recorded PE .text). mod's size is
        noisy under -Os (documented) — its flattening presence is pinned
        by the shape check above instead."""
        def gt(task_id):
            return json.loads((RELEASE / task_id / "ground_truth.json")
                              .read_text(encoding="utf-8"))
        for l1, l2 in (("arm-kdf-l1", "arm-kdf-l2"),
                       ("smc-x86-l1", "smc-x86-l2")):
            t1 = gt(l1)["artifact_text_size"]
            t2 = gt(l2)["artifact_text_size"]
            assert t2["target/libkdf.so" if "arm" in l1
                      else "target/smc_payload.elf"] > \
                t1["target/libkdf.so" if "arm" in l1
                   else "target/smc_payload.elf"], f"{l1} vs {l2}"
        assert gt("win-kdf-l2")["build_record"]["pe_text_size"] > \
            gt("win-kdf-l1")["build_record"]["pe_text_size"]

    def test_toolchain_absent_is_structured_skip_not_fail(self):
        """The mint-side toolchain discovery reports structured SKIP rows
        (never a false FAIL) when a toolchain is absent."""
        rows = ntg.toolchain_report({})  # no toolchain names resolvable
        by_name = {r["toolchain"]: r for r in rows}
        for name in ("ndk-arm64", "go", "clang", "upx"):
            assert by_name[name]["status"] == "TOOLCHAIN_MISSING"

    def test_dynamic_proof_skips_off_linux(self, capsys):
        """The documented local dynamic proof is Linux-only (ptrace
        wrapper); everywhere else it degrades to a structured SKIP."""
        rc = ntg.run_dynamic_proof("smc-x86-l0")
        captured = capsys.readouterr().out
        assert rc in (0, 3)
        if rc == 3:
            assert "SKIP" in captured
