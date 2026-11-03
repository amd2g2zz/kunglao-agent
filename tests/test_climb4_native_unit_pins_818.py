#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_native_unit_pins_818.py — #818 climb segment 4I.

Behavior pins for the eval_native_targets faces that need NO toolchain —
the toolchain-independent half of the "dynamic-proof" route (the native
build faces stay behind their TOOLCHAIN_MISSING guards; those guards are
pinned too, skipped honestly where the tool exists — they run on CI):

  derive_cfg (mutated parameter set + anti-debug thresholds), the
  constants registry's two family groups, the probe/pair registries
  (disjoint i spaces, deterministic, anti-digest-table), the anti-debug
  ground truth (win vs elf signatures, the seed-masked needle, the
  mechanical artifact scan), build_task_unit's task + ground_truth
  shape, and the reference renderer PROOF: the rendered pure-python
  reference compiles, executes in-process, and byte-matches the seeded
  model on a checker-minted probe — the perfect-candidate contract
  without any compiler.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_native_targets as ent  # noqa: E402


class TestDeriveCfg:
    def test_unknown_family_refuses(self) -> None:
        with pytest.raises(ValueError, match="unknown native family"):
            ent.derive_cfg("no-such-native", 1)

    def test_cfg_carries_the_mutated_set(self) -> None:
        cfg = ent.derive_cfg("smc-x86", 33203)
        assert len(cfg["h"]) == 8 and len(cfg["k"]) == 64
        assert len(cfg["sbox"]) == 256 and len(cfg["rcon"]) >= 1
        assert 1 <= cfg["needle_key"] <= 0xFF  # never 0 (the `or 0x5A`)
        assert cfg["timing_iters"] >= 1000
        assert cfg["timing_ns"] >= 2_000_000_000
        assert cfg["timing_tsc"] >= 200_000_000
        assert len(cfg["smc_key"]) == 16
        assert cfg["seed"] == 33203

    def test_cfg_is_seed_deterministic_and_seed_sensitive(self) -> None:
        a = ent.derive_cfg("arm-native-kdf", 33201)
        b = ent.derive_cfg("arm-native-kdf", 33201)
        c = ent.derive_cfg("arm-native-kdf", 33202)
        assert a == b and a["h"] != c["h"]


class TestRegistries:
    def test_constants_public_groups(self) -> None:
        elf_cfg = ent.derive_cfg("arm-native-kdf", 33201)
        assert set(ent.constants_public("arm-native-kdf", elf_cfg)) == {
            "h0_0", "h0_1", "h0_2", "h0_3", "k_0"}
        assert set(ent.constants_public("win-pe-kdf", elf_cfg)) == {
            "h0_0", "h0_1", "h0_2", "h0_3", "k_0"}
        mod_cfg = ent.derive_cfg("mod-crypto-native", 33204)
        assert set(ent.constants_public("mod-crypto-native", mod_cfg)) == {
            "sbox_0", "sbox_255", "h0_0", "h0_1", "rcon_0"}

    def test_probe_spaces_never_alias(self) -> None:
        seed = 33201
        published = ent.published_pairs("arm-native-kdf", seed, 3)
        minted = ent.minted_probes("arm-native-kdf", seed, 3)
        assert [row["i"] for row in published] == [0, 1, 2]
        assert [row["i"] for row in minted] == [100, 101, 102]
        # the minted face XORs the seed — a digest table built from the
        # published inputs answers none of the checker's probes
        assert ({tuple(row["input"]) for row in published}
                .isdisjoint({tuple(row["input"]) for row in minted}))

    def test_model_output_is_deterministic_hex(self) -> None:
        cfg = ent.derive_cfg("arm-native-kdf", 33201)
        probe = ent._probe_input(33201, 1)
        out = ent.model_output("arm-native-kdf", cfg, 0, probe)
        assert out == ent.model_output("arm-native-kdf", cfg, 0, probe)
        int(out, 16)  # hex face
        # published pairs carry the same model answer
        row = ent.published_pairs("arm-native-kdf", 33201, 1)[0]
        assert row["out"] == ent.model_output(
            "arm-native-kdf", cfg, 0, row["input"])


class TestAntiDebugGt:
    def test_win_face_scans_pe_api_names(self) -> None:
        cfg = ent.derive_cfg("win-pe-kdf", 33202)
        gt = ent._anti_debug_gt("win-pe-kdf", cfg)
        assert gt["response"] == "silent-corruption"
        assert "IsDebuggerPresent" in gt["signatures"]
        assert all(isinstance(h, str) for h in gt["scan_hex"])
        assert "CORRUPT_MASK" in gt["dynamic_proof"]

    def test_elf_face_masks_the_needle_with_the_seed(self) -> None:
        cfg = ent.derive_cfg("arm-native-kdf", 33201)
        gt = ent._anti_debug_gt("arm-native-kdf", cfg)
        assert gt["needle_masked_at"] == "source-level"
        needle = bytes(b ^ cfg["needle_key"] for b in b"TracerPid:")
        assert gt["needle_hex"] == needle.hex()
        # the raw needle never ships: the scan face records the status path
        assert bytes.fromhex(gt["scan_hex"][0]) == b"/proc/self/status"

    def test_mechanical_scan_finds_recorded_patterns_only(self) -> None:
        # the scan rides the GROUND-TRUTH record (gt["anti_debug"]), the
        # shape the checker actually consumes
        gt = ent.build_task_unit("win-pe-kdf", "l0")["ground_truth"]
        blob = (b"padding" + b"IsDebuggerPresent" + b"more padding")
        assert ent.anti_debug_face("win-pe-kdf", gt, blob) == [
            "IsDebuggerPresent"]
        assert ent.anti_debug_face("win-pe-kdf", gt, b"clean bytes") == []


class TestTaskUnit:
    def test_unit_shape_and_answer_source(self) -> None:
        unit = ent.build_task_unit("arm-native-kdf", "l1")
        task = unit["task"]
        gt = unit["ground_truth"]
        assert task["tier"] == "release"
        assert task["checker"]["entrypoint"] == "checker.py"
        assert task["checker"]["self_check_candidate"] == "reference.py"
        assert task["workspace_scaffold"]["files"] == ["target/libkdf.so"]
        assert gt["rung"] == "l1"
        assert len(gt["published_pairs"]) == ent.PUBLISHED_COUNT
        assert gt["minted_probe_count"] == ent.MINTED_COUNT
        assert "anti_debug" in gt
        assert gt["constants_record_mode"] == "raw-bytes"

    def test_win_unit_omits_the_raw_bytes_note(self) -> None:
        gt = ent.build_task_unit("win-pe-kdf", "l0")["ground_truth"]
        assert "constants_record_mode" not in gt

    def test_custom_task_id_wins(self) -> None:
        unit = ent.build_task_unit("smc-x86", "l2", task_id="custom-id")
        assert unit["task"]["task_id"] == "custom-id"


class TestReferenceRendererProof:
    def test_reference_compiles_and_byte_matches_the_model(self) -> None:
        for family in ("arm-native-kdf", "smc-x86"):
            seed = ent.FAMILY_SEEDS[family]
            cfg = ent.derive_cfg(family, seed)
            src = ent.render_reference_py(family, cfg)
            # self-contained: no imports in the reference source
            assert "import " not in src
            namespace: dict = {}
            exec(compile(src, "<reference.py>", "exec"), namespace)
            entry = ent.FAMILIES[family]["entry"]
            probe = ent._probe_input(seed ^ 0x5EED, 7)  # checker-minted
            got = namespace[entry](bytes(probe))
            want = ent.model_output(family, cfg, 0, probe)
            assert got == want, f"{family} reference drifted from the model"

    def test_reference_is_seed_parametrized(self) -> None:
        a = ent.render_reference_py(
            "arm-native-kdf", ent.derive_cfg("arm-native-kdf", 33201))
        b = ent.render_reference_py(
            "arm-native-kdf", ent.derive_cfg("arm-native-kdf", 33202))
        assert a != b


class TestToolchainGuards:
    """The build faces refuse loudly WITHOUT a toolchain. Skipped where
    the tool exists (this workstation) — they execute on the CI leg where
    the toolchain is genuinely absent, keeping the guard honest."""

    @pytest.mark.skipif(ent.find_ndk_clang() is not None,
                        reason="ndk present — the guard face is CI-only")
    def test_arm_build_refuses_without_the_ndk(self, tmp_path) -> None:
        cfg = ent.derive_cfg("arm-native-kdf", 33201)
        with pytest.raises(RuntimeError, match="TOOLCHAIN_MISSING"):
            ent.build_arm_so(cfg, "l0", tmp_path / "libkdf.so")

    @pytest.mark.skipif(ent.find_ndk_clang() is not None,
                        reason="ndk present — the guard face is CI-only")
    def test_mod_build_refuses_without_the_ndk(self, tmp_path) -> None:
        cfg = ent.derive_cfg("mod-crypto-native", 33204)
        with pytest.raises(RuntimeError, match="TOOLCHAIN_MISSING"):
            ent.build_mod_so(cfg, "l1", tmp_path / "libmodcrypto.so")

    @pytest.mark.skipif(ent._which("clang") is not None
                        and ent.find_lld() is not None,
                        reason="clang+lld present — CI-only guard face")
    def test_smc_build_refuses_without_clang_or_lld(self, tmp_path) -> None:
        cfg = ent.derive_cfg("smc-x86", 33203)
        with pytest.raises(RuntimeError, match="TOOLCHAIN_MISSING"):
            ent.build_smc_elf(cfg, "l0", tmp_path / "smc")

    @pytest.mark.skipif(ent._which("go") is not None,
                        reason="go present — the guard face is CI-only")
    def test_win_build_refuses_without_go(self, tmp_path) -> None:
        cfg = ent.derive_cfg("win-pe-kdf", 33202)
        with pytest.raises(RuntimeError, match="TOOLCHAIN_MISSING"):
            ent.build_win(cfg, "l0", tmp_path / "src.go", {})
