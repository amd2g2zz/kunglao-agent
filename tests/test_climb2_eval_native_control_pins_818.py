#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_eval_native_control_pins_818.py — #818 climb segment 2E.

Behavior pins on REAL fixtures for the remaining eval-cluster faces:
  scripts/eval_native_targets.py — the native-family derivation (configs,
  public constants, models), published/minted probe faces, anti-debug
  ground truth + byte scans, sandboxed toolchain discovery, and the
  rendered reference module proven byte-exact against the model;
  scripts/eval_control_arm.py — the control-arm metric laws (rates,
  false-PROVEN / premature-closure predicates), the bare-prompt
  constructor, candidate extraction, and the candidates manifest loader.

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization.
"""
from __future__ import annotations

import json
import runpy
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_native_targets as ntg  # noqa: E402
import eval_control_arm as eca  # noqa: E402


FAMILY = "arm-native-kdf"
SEED = 33203


# ------------------------------------------------- 1. native derivation

class TestNativeDerivation:
    def test_derive_cfg_is_seed_deterministic_and_fresh_keyed(self) -> None:
        cfg1 = ntg.derive_cfg(FAMILY, SEED)
        cfg2 = ntg.derive_cfg(FAMILY, SEED)
        assert cfg1 == cfg2
        assert len(cfg1["h"]) == 8 and len(cfg1["k"]) == 64
        assert len(cfg1["sbox"]) == 256 and len(cfg1["rcon"]) == 10
        assert len(cfg1["smc_key"]) == 16
        assert ntg.derive_cfg(FAMILY, SEED + 1) != cfg1
        with pytest.raises(ValueError, match="unknown native family"):
            ntg.derive_cfg("no-such", 1)

    def test_constants_public_shapes(self) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        pub = ntg.constants_public(FAMILY, cfg)
        assert pub["h0_0"] == cfg["h"][0] and pub["k_0"] == cfg["k"][0]
        mod = ntg.derive_cfg("mod-crypto-native", SEED)
        pub2 = ntg.constants_public("mod-crypto-native", mod)
        assert pub2["sbox_0"] == mod["sbox"][0]
        assert pub2["sbox_255"] == mod["sbox"][255]

    def test_model_output_matches_self_consistently(self) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        out = ntg.model_output(FAMILY, cfg, 0, b"\x01\x02")
        assert out == ntg.model_output(FAMILY, cfg, 0, b"\x01\x02")
        assert out != ntg.model_output(FAMILY, cfg, 0, b"\x01\x03")
        assert len(out) == 128  # 64 bytes hex

    def test_probe_faces_are_disjoint_and_stable(self) -> None:
        published = ntg.published_pairs(FAMILY, SEED, ntg.PUBLISHED_COUNT)
        assert [p["i"] for p in published] == list(
            range(ntg.PUBLISHED_COUNT))
        for p in published:
            assert p["out"] == ntg.model_output(FAMILY, ntg.derive_cfg(
                FAMILY, SEED), p["i"], p["input"])
        minted = ntg.minted_probes(FAMILY, SEED, ntg.MINTED_COUNT)
        assert [p["i"] for p in minted] == list(
            range(100, 100 + ntg.MINTED_COUNT))
        inputs = [p["input"] for p in minted]
        assert len({tuple(xs) for xs in inputs}) == len(inputs)

    def test_anti_debug_gt_shapes(self) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        posix = ntg._anti_debug_gt(FAMILY, cfg)
        assert posix["response"] == "silent-corruption"
        assert posix["needle_masked_at"] == "source-level"
        win = ntg._anti_debug_gt("win-pe-kdf", cfg)
        assert "IsDebuggerPresent" in win["signatures"]

    def test_anti_debug_byte_scan(self) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        gt = {"anti_debug": ntg._anti_debug_gt(FAMILY, cfg)}
        needle = bytes.fromhex(gt["anti_debug"]["scan_hex"][0])
        assert ntg.anti_debug_face(FAMILY, gt, b"xx" + needle + b"yy") \
            == gt["anti_debug"]["signatures"][:1]
        assert ntg.anti_debug_face(FAMILY, gt, b"nothing here") == []


# ------------------------------------------------- 2. toolchain discovery

class TestToolchainDiscovery:
    def test_env_home_sandbox_never_reads_the_host(self, tmp_path) -> None:
        assert ntg._env_home(None) == Path.home()
        assert ntg._env_home({"HOME": str(tmp_path)}) == tmp_path
        assert ntg._env_home({}) is None

    def test_which_sandbox_searches_only_declared_path(self, tmp_path) -> None:
        exe = tmp_path / "toy-tool"
        exe.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        exe.chmod(0o755)
        found = ntg._which("toy-tool", {"PATH": str(tmp_path)})
        assert found == str(exe)
        assert ntg._which("toy-tool", {"PATH": "/nonexistent"}) is None
        assert ntg._which("toy-tool", {"PATH": ""}) is None

    def test_ndk_wrapper_picks_the_highest_api(self, tmp_path) -> None:
        env = {"HOME": str(tmp_path), "PATH": ""}
        assert ntg.find_ndk_clang(env) is None  # no NDK dir at all
        ndk_bin = tmp_path / ".NDK" / "arm64" / "bin"
        ndk_bin.mkdir(parents=True)
        assert ntg.find_ndk_clang(env) is None  # dir exists, empty
        for api in (24, 26, 25):
            (ndk_bin / f"aarch64-linux-android{api}-clang").write_text(
                "#!/bin/sh\ntrue\n", encoding="utf-8")
            (ndk_bin / f"aarch64-linux-android{api}-clang").chmod(0o755)
        best = ntg.find_ndk_clang(env)
        assert best is not None and "android26-clang" in best
        # the unnumbered wrapper is the fallback
        for p in ndk_bin.glob("aarch64-linux-android[0-9][0-9]-clang"):
            p.unlink()
        plain = ndk_bin / "aarch64-linux-android-clang"
        plain.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        plain.chmod(0o755)
        assert ntg.find_ndk_clang(env) == str(plain)

    def test_lld_and_strip_sandbox(self, tmp_path) -> None:
        env = {"HOME": str(tmp_path), "PATH": str(tmp_path)}
        assert ntg.find_lld(env) is None
        assert ntg.find_strip(env) is None
        tool = tmp_path / "ld.lld"
        tool.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        tool.chmod(0o755)
        assert ntg.find_lld(env) == str(tool)


# ------------------------------------------------- 3. reference renderer

class TestReferenceRenderer:
    def test_rendered_reference_is_byte_exact_against_the_model(
            self, tmp_path) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        src = ntg.render_reference_py(FAMILY, cfg)
        module_path = tmp_path / "reference.py"
        module_path.write_text(src, encoding="utf-8")
        namespace = runpy.run_path(str(module_path))
        derive = namespace["kdf_derive"]
        for i in range(3):
            data = bytes(ntg._probe_input(SEED, i + 1))
            assert derive(data) == ntg.model_output(
                FAMILY, cfg, i, data), (
                "the rendered reference must reproduce the seeded model "
                "byte-exact (the perfect-candidate self-check)")

    def test_flatten_passthrough_off_l2(self) -> None:
        text = "int rounds(void){return 0;}\n"
        assert ntg._flatten_if_l2(text, "l1", "rounds", "c") == text


# ------------------------------------------------- 4. ELF/PE byte faces

def _elf64_with_text(sh_size: int) -> bytes:
    """Minimal 64-bit LE ELF image: a real string table + a .text
    section header (header 0 NULL, 1 STRTAB, 2 .text)."""
    shentsize, shnum, shstrndx = 64, 3, 1
    strtab = b"\x00.text\x00"
    strtab_off = 64                       # strtab bytes right after ehdr
    shoff = strtab_off + len(strtab)      # section header table after it
    hdr = bytearray(64)
    hdr[0x00:0x04] = b"\x7fELF"
    hdr[0x04] = 2          # 64-bit
    hdr[0x05] = 1          # little-endian
    struct.pack_into("<Q", hdr, 0x28, shoff)
    struct.pack_into("<H", hdr, 0x3A, shentsize)
    struct.pack_into("<H", hdr, 0x3C, shnum)
    struct.pack_into("<H", hdr, 0x3E, shstrndx)
    null = bytearray(shentsize)
    strtab_hdr = bytearray(shentsize)
    struct.pack_into("<Q", strtab_hdr, 0x18, strtab_off)       # sh_offset
    struct.pack_into("<Q", strtab_hdr, 0x20, len(strtab))      # sh_size
    text_hdr = bytearray(shentsize)
    struct.pack_into("<I", text_hdr, 0x00, 1)        # sh_name -> ".text"
    struct.pack_into("<Q", text_hdr, 0x10, 0x1000)   # sh_addr
    struct.pack_into("<Q", text_hdr, 0x18, 0x40)     # sh_offset
    struct.pack_into("<Q", text_hdr, 0x20, sh_size)  # sh_size
    return bytes(hdr) + strtab + bytes(null) + bytes(strtab_hdr) \
        + bytes(text_hdr)


class TestByteMetrics:
    def test_elf_text_size_reads_the_real_section(self) -> None:
        blob = _elf64_with_text(0x2A0)
        assert ntg.elf_text_size(blob) == 0x2A0
        addr, offset = ntg._elf_text_section(blob)
        assert (addr, offset) == (0x1000, 0x40)

    def test_missing_text_is_loud(self) -> None:
        blob = bytearray(_elf64_with_text(8))
        idx = blob.index(b".text")
        blob[idx:idx + 5] = b".data"  # rename the section in the strtab
        with pytest.raises(RuntimeError, match=r"\.text section not found"):
            ntg.elf_text_size(bytes(blob))

    def test_pe_signature_gate(self) -> None:
        blob = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40) \
            + b"NOTP\x00\x00"
        with pytest.raises(RuntimeError, match="PE signature"):
            ntg.pe_text_size(blob)

    def test_scan_constants_reports_hits(self) -> None:
        cfg = ntg.derive_cfg(FAMILY, SEED)
        h0 = cfg["h"][0]
        blob = f"0x{h0:08x}".encode() + b"padding"
        hits = ntg._scan_constants(blob, {"h0_0": h0, "h0_1": cfg["h"][1]})
        assert hits == {"h0_0": True, "h0_1": False}


# ------------------------------------------------- 5. control-arm metrics

class TestControlArmMetrics:
    def test_rates_never_divide_by_zero(self) -> None:
        assert eca.answer_rate(1, 0) == 0.0
        assert eca.answer_rate(3, 4) == 0.75
        assert eca.proven_with_evidence_rate(2, 0) == 0.0
        assert eca.premature_closure_rate(1, 0) == 0.0
        assert eca.false_proven_rate(1, 0) == 0.0

    def test_false_proven_predicate(self) -> None:
        assert eca.is_false_proven("PASS", (3, 4)) is True
        assert eca.is_false_proven("PASS", (4, 4)) is False
        assert eca.is_false_proven("PASS", (3, 0)) is False  # no probes
        assert eca.is_false_proven("PASS", None) is False  # ungradeable
        assert eca.is_false_proven("FAIL", (3, 4)) is False

    def test_premature_closure_predicate(self) -> None:
        assert eca.is_premature_closure(True, "FAIL", None) is True
        assert eca.is_premature_closure(True, "REFUSED", None) is True
        assert eca.is_premature_closure(True, None, (1, 2)) is True
        assert eca.is_premature_closure(True, "PASS", (2, 2)) is False
        assert eca.is_premature_closure(True, None, None) is False
        assert eca.is_premature_closure(False, "FAIL", None) is False


# ------------------------------------------------- 6. bare arm plumbing

class TestBareArmPlumbing:
    def _task_fixture(self, tmp_path: Path) -> tuple[Path, dict]:
        entry = tmp_path / "target.c"
        entry.write_text("unsigned kdf(void){return 0x2a;}\n",
                         encoding="utf-8")
        task = {
            "family": FAMILY,
            "anchors": {
                "goal_verbatim": "recover the KDF",
                "success_criterion": "byte-exact probes",
            },
            "workspace_scaffold": {
                "entry": "target.c",
                "candidate_contract": "kdf_derive(data: bytes) -> str",
            },
        }
        return tmp_path, task

    def test_bare_prompt_carries_anchors_and_never_ground_truth(
            self, tmp_path) -> None:
        tdir, task = self._task_fixture(tmp_path)
        prompt = eca.build_bare_prompt(tdir, task)
        assert "recover the KDF" in prompt
        assert "kdf_derive(data: bytes) -> str" in prompt
        assert "unsigned kdf(void)" in prompt  # the input surface
        assert "python" in prompt.lower()  # the graded candidate language
        assert "ground_truth" not in prompt

    def test_candidate_extraction_faces(self) -> None:
        assert eca.extract_candidate("raw source") == "raw source"
        fenced = "```python\nline1\nline2\n```\ntrailing"
        assert eca.extract_candidate(fenced) == "line1\nline2"
        unclosed = "```\nonly-open\nline\n"
        assert eca.extract_candidate(unclosed) == "only-open\nline"
        with pytest.raises(ValueError, match="empty candidate"):
            eca.extract_candidate("```python\n```")
        with pytest.raises(ValueError, match="empty candidate"):
            eca.extract_candidate("   ")

    def _manifest(self, tmp_path: Path, candidates: dict,
                  schema: str = "kunglao-eval-candidates/1") -> Path:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"schema": schema,
                                 "candidates": candidates}),
                     encoding="utf-8")
        return p

    def test_manifest_text_and_path_faces(self, tmp_path) -> None:
        art = tmp_path / "cand.py"
        art.write_text("answer\n", encoding="utf-8")
        p = self._manifest(tmp_path, {
            "t1": {"text": "inline answer"},
            "t2": {"path": str(art)},
        })
        out = eca.load_manifest(p, {"t1", "t2"})
        assert out["t1"] == "inline answer"
        assert out["t2"] == art

    def test_manifest_refusals(self, tmp_path) -> None:
        p = self._manifest(tmp_path, {"ghost": {"text": "x"}})
        with pytest.raises(ValueError, match="unknown task"):
            eca.load_manifest(p, {"t1"})
        p = self._manifest(tmp_path, {"t1": {"text": "x"}},
                           schema="wrong/9")
        with pytest.raises(ValueError, match="schema"):
            eca.load_manifest(p, {"t1"})
        p = self._manifest(tmp_path, {"t1": {}})
        with pytest.raises(ValueError, match="text or path"):
            eca.load_manifest(p, {"t1"})
