#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_eval_release_render_pins_818.py — #818 climb segment 4G.

Behavior pins on REAL constructed artifacts for the eval_targets release
renderer faces the third climb leg left unmeasured:

  render_release's rung dispatch (unknown-rung refusal; the l0 readable
  digest core, the l1 decoy block + hex-id minify, the l3 stack-VM core),
  the seam registry (exactly the release families; every artifact carries
  its family's contract seam; the req-sign sort flag follows the cfg; the
  license handshake folds the cfg rounds), the l1 minify transform
  (comment strip + hex renames + determinism), the constants block
  embedding the cfg words, and the seeded wrong-out poison.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_targets as et  # noqa: E402

SEED = 5150


# ------------------------------------------------- rung dispatch faces

class TestRungDispatch:
    def test_unknown_rung_refuses_with_the_valid_list(self) -> None:
        with pytest.raises(ValueError, match="unknown rung"):
            et.render_release("req-sign", SEED, "l9")

    def test_l0_is_readable_with_the_plain_digest_core(self) -> None:
        src = et.render_release("req-sign", SEED, "l0")
        assert "rung l0" in src
        assert "function _vmRun" not in src   # no VM core on l0
        assert "var _0xd1" not in src         # no decoy block
        assert "_unhex(KX)" in src            # plain seam keying

    def test_l1_carries_decoys_and_hex_ids_without_comments(self) -> None:
        src = et.render_release("req-sign", SEED, "l1")
        assert "var _0xd1" in src             # decoys ride the l1 face
        assert "_0x51(KX)" in src             # the renamed seam keying
        assert "_unhex(KX)" not in src
        assert not any(line.lstrip().startswith("//")
                       for line in src.splitlines())
        assert et.render_release("req-sign", SEED, "l1") == src

    def test_l3_swaps_the_digest_core_for_the_stack_vm(self) -> None:
        src = et.render_release("req-sign", SEED, "l3")
        assert "rung l3" in src
        assert "function _vmRun" in src
        assert "var _P = [" in src
        # every interpreter case is present, addressed by seeded opcodes
        op = et._vm_opcode_table(SEED ^ 0x7A33)
        for name in et._VM_OPS:
            assert f"case {op[name]}:" in src

    def test_rungs_of_one_seed_share_the_constants(self) -> None:
        l0 = et.render_release("req-sign", SEED, "l0")
        l3 = et.render_release("req-sign", SEED, "l3")
        cfg = et.derive_cfg("req-sign", SEED, "l0")
        for word in (cfg["key_hex"], f"0x{cfg['k'][0]:08x}",
                     f"0x{cfg['h'][0]:08x}"):
            assert word in l0 and word in l3


# --------------------------------------------------------- seam faces

class TestSeamFaces:
    def test_seam_registry_is_exactly_the_release_families(self) -> None:
        assert set(et._RELEASE_SEAM_FACES) == set(et.RELEASE_FAMILIES)

    @pytest.mark.parametrize("family,seam", [
        ("mod-crypto-js", "function sign("),
        ("web-pack-sign", "function sign("),
        ("req-sign", "function signRequest("),
        ("net-verify-license", "async function handshake("),
    ])
    def test_every_release_artifact_carries_its_seam(
            self, family, seam) -> None:
        src = et.render_release(family, SEED, "l0")
        assert seam in src
        assert "module.exports" in src

    def test_req_sign_sort_flag_follows_the_cfg(self) -> None:
        cfg = et.derive_cfg("req-sign", SEED, "l0")
        src = et.render_release("req-sign", SEED, "l0")
        flag = "true" if cfg.get("sort_headers") else "false"
        assert f"if ({flag})" in src

    def test_license_handshake_folds_the_cfg_rounds(self) -> None:
        cfg = et.derive_cfg("net-verify-license", SEED, "l0")
        src = et.render_release("net-verify-license", SEED, "l0")
        assert f"r < {int(cfg.get('rounds', 2))}" in src

    def test_unknown_release_family_has_no_seam_face(self) -> None:
        # the registry lookup is a .get: an unknown family renders no seam
        assert et._RELEASE_SEAM_FACES.get("no-such-family") is None
        with pytest.raises(KeyError):
            et._RELEASE_SEAM_FACES["no-such-family"]


# ---------------------------------------------- minify + helper pieces

class TestMinifyAndHelpers:
    def test_minify_strips_comments_and_renames_identifiers(self) -> None:
        src = "// a comment\nfunction _bytesOf(x) {\n  return x;\n}\n"
        out = et._minify_l1(src, SEED)
        assert "// a comment" not in out
        assert "_bytesOf" not in out and "_0x4a" in out
        assert out == et._minify_l1(src, SEED)  # deterministic

    def test_constants_block_embeds_the_cfg_words(self) -> None:
        cfg = et.derive_cfg("mod-crypto-js", SEED, "l0")
        block = et._js_constants_block(cfg)
        assert cfg["key_hex"] in block
        assert f"0x{cfg['k'][0]:08x}" in block
        assert f"0x{cfg['h'][0]:08x}" in block
        assert f"0x{cfg['sep_code']:02x}" in block or \
            str(cfg["sep_code"]) in block

    def test_wrong_out_embeds_the_seeded_poison(self) -> None:
        poison = et._u32(SEED, 91)
        out = et._js_wrong_out(SEED)
        assert f"0x{poison:08x}" in out
        assert out == et._js_wrong_out(SEED)
        assert out != et._js_wrong_out(SEED + 1)
