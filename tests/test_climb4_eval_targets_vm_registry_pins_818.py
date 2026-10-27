#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_eval_targets_vm_registry_pins_818.py — #818 seg 4B.

Behavior pins on REAL constructed artifacts for the eval_targets faces the
third climb leg left unmeasured:

  the mod-SHA core (seed-mutated constants repaired away from stock;
  deterministic digests; seed sensitivity), the l3 stack-VM pipeline
  (seeded opcode permutation, compiled-stream legality, and the
  bytecode == model parity proof across the SHA padding boundaries),
  the license challenge/response KDF (rounds-folded session key, HMAC
  response, nonce sensitivity), the registry faces (published/minted
  count tables, public-constant projection, model outputs), the
  build_task_unit shape for smoke and release-ladder rungs, the
  write_task_unit on-disk mint contract (idempotent, checker exec-bit,
  the structured l2 SKIP when npx is absent), and the CLI mint specs.

No toolchain is needed: every pin is either pure arithmetic or mints into
tmp_path; the npx-gated l2 obfuscation face is honestly skipped when npx
is present (the SKIP contract only exists in the toolchain-absent world).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_targets as et  # noqa: E402


# ------------------------------------------------------- mod-SHA core

class TestModShaCore:
    def test_cfg_constants_repaired_away_from_stock(self) -> None:
        cfg = et.mod_sha_cfg(33203)
        assert len(cfg["h"]) == 8 and len(cfg["k"]) == 64
        # the repair loop holds for EVERY word, not just on average: a
        # stock constant surviving would mint a stock-lookalike artifact
        assert all(h != s for h, s in zip(cfg["h"], et.STOCK_SHA256_H))
        assert all(k != s for k, s in zip(cfg["k"], et.STOCK_SHA256_K))

    def test_digest_is_deterministic_and_seed_sensitive(self) -> None:
        a1 = et.mod_sha256(et.mod_sha_cfg(7), b"payload")
        a2 = et.mod_sha256(et.mod_sha_cfg(7), b"payload")
        b = et.mod_sha256(et.mod_sha_cfg(8), b"payload")
        assert a1 == a2
        assert a1 != b
        assert len(a1) == 32

    def test_pad_boundaries_shape_the_message(self) -> None:
        # 55 bytes -> single block; 56 -> two blocks; the length suffix
        # must land big-endian in the final 8 bytes either way
        for n in (55, 56, 119, 120):
            msg = et._sha_pad(b"x" * n)
            assert len(msg) % 64 == 0
            assert msg[len(b"x" * n)] == 0x80
            assert int.from_bytes(msg[-8:], "big") == n * 8

    def test_mod_hmac_differs_from_the_bare_digest(self) -> None:
        cfg = et.mod_sha_cfg(99)
        key = b"k" * 32
        msg = b"canonical"
        mac = et.mod_hmac(cfg, key, msg)
        assert mac != et.mod_sha256(cfg, msg)
        assert mac == et.mod_hmac(cfg, key, msg)


# ----------------------------------------------------- l3 stack VM face

class TestStackVm:
    def test_opcode_table_is_a_seed_pinned_permutation(self) -> None:
        t1 = et._vm_opcode_table(11)
        t1b = et._vm_opcode_table(11)
        t2 = et._vm_opcode_table(12)
        assert set(t1) == set(et._VM_OPS)
        assert sorted(t1.values()) == list(range(len(et._VM_OPS)))
        assert t1 == t1b          # deterministic per seed
        assert t1 != t2           # the seed mutates the bytecode alphabet

    def test_compiled_stream_is_legal_bytecode(self) -> None:
        cfg = et.mod_sha_cfg(33203)
        seed = 33203
        op = et._vm_opcode_table(seed ^ 0x7A33)
        prog = et._vm_compile_sha(cfg, seed)
        assert prog
        # walk the stream the way the interpreter decodes it: every opcode
        # position must be in the seeded alphabet and the argument-bearing
        # ops must leave a full program (no unknown opcode, no truncated
        # tail) — the l3 artifact's JS loop rides this exact shape
        arg_ops = {"load", "store", "push", "rotr", "shr"}
        name_of = {v: k for k, v in op.items()}
        pc = 0
        while pc < len(prog):
            assert prog[pc] in name_of, f"unknown opcode at {pc}"
            pc += 2 if name_of[prog[pc]] in arg_ops else 1
        assert pc == len(prog)

    def test_vm_matches_the_model_across_padding_boundaries(self) -> None:
        cfg = et.mod_sha_cfg(33203)
        for data in (b"", b"abc", b"x" * 55, b"y" * 56,
                     b"z" * 119, b"q" * 128):
            assert et._vm_sha256(cfg, 33203, data) == et.mod_sha256(cfg, data)

    def test_named_self_test_passes(self) -> None:
        # a drift here would mint a lying artifact — the guard must hold
        assert et._vm_self_test(et.mod_sha_cfg(33203), 33203) is None
        assert et._vm_self_test(et.mod_sha_cfg(4242), 4242) is None

    def test_vm_rejects_an_out_of_alphabet_opcode(self) -> None:
        op = et._vm_opcode_table(5)
        bogus = max(op.values()) + 100
        with pytest.raises(KeyError):
            et._vm_step([bogus], op, [0] * 8)


# ------------------------------------------------ license KDF + models

class TestLicenseAndModels:
    def _lic_cfg(self) -> dict:
        return et.derive_cfg("net-verify-license", 4242, "l1")

    def test_session_key_folds_rounds_over_secret_and_challenge(self) -> None:
        cfg = self._lic_cfg()
        k1 = et.license_session_key(cfg, "aabbccdd")
        k2 = et.license_session_key(cfg, "aabbccdd")
        assert k1 == k2 and len(k1) == 32
        assert k1 != et.license_session_key(cfg, "eeff0011")

    def test_response_is_hmac_over_the_canonical_payload(self) -> None:
        cfg = self._lic_cfg()
        r1 = et.license_response(cfg, "aabbccdd", "nonce-1", "dev-1", 3)
        r2 = et.license_response(cfg, "aabbccdd", "nonce-1", "dev-1", 3)
        assert r1 == r2
        assert len(r1) == 64 and int(r1, 16) >= 0  # 32-byte hex mac
        # any canonical-field change moves the response
        assert r1 != et.license_response(cfg, "aabbccdd", "nonce-2", "dev-1", 3)
        assert r1 != et.license_response(cfg, "aabbccdd", "nonce-1", "dev-1", 4)

    def test_model_registry_shapes(self) -> None:
        go_cfg = et.derive_cfg("go-arx", 77)
        out = et.model_output("go-arx", go_cfg, 3, 1234)
        assert isinstance(out, int) and 0 <= out <= et.M32
        js_cfg = et.derive_cfg("js-sign", 77)
        hexout = et.model_output("js-sign", js_cfg, 0, b"abcd")
        assert isinstance(hexout, str) and len(hexout) == 8
        int(hexout, 16)
        py_cfg = et.derive_cfg("py-derive", 77)
        assert isinstance(et.model_output("py-derive", py_cfg, 0, b"abcd"),
                          int)

    def test_probe_and_pair_registries_carry_the_declared_counts(self) -> None:
        for family in ("go-arx", "js-sign", "py-derive", "web-pack-sign",
                       "req-sign", "net-verify-license", "mod-crypto-js"):
            seed = 909
            if family in et.RELEASE_FAMILIES:
                cfg = et.derive_cfg(family, seed, "l1")
            else:
                cfg = et.derive_cfg(family, seed)
            published = et.published_pairs(family, cfg,
                                           et._published_count(family))
            minted = et.minted_probes(family, seed, et._minted_count(family))
            assert len(published) == et._published_count(family)
            assert len(minted) == et._minted_count(family)
            # published rows answer at i = 0..N-1; checker-minted probes
            # live at i >= 100 — the two faces never alias a key
            assert all(row["i"] == k for k, row in enumerate(published))
            assert all(row["i"] >= 100 for row in minted)
            # every published row carries its model answer under "out"
            assert all("out" in row for row in published)

    def test_public_constant_projection_keys_on_the_family(self) -> None:
        assert set(et._constants_public("go-arx",
                                        et.derive_cfg("go-arx", 5))) == {
            "k0", "z", "rot_base"}
        assert set(et._constants_public("js-sign",
                                        et.derive_cfg("js-sign", 5))) == {
            "c1", "c2"}
        assert set(et._constants_public("req-sign",
                                        et.derive_cfg("req-sign", 5,
                                                      "l1"))) == {
            "key_hex", "sep_code"}
        # the py face is the fallthrough for families without a projection
        assert set(et._constants_public("py-derive",
                                        et.derive_cfg("py-derive", 5))) == {
            "offset", "prime", "fold"}


# --------------------------------------------- task-unit build + mint

class TestTaskUnitFaces:
    def test_smoke_unit_shape(self) -> None:
        unit = et.build_task_unit("go-arx", 31337, "t-smoke")
        task = unit["task"]
        assert task["tier"] == "smoke"
        assert task["eval_version"] == "eval-v1"
        assert task["task_id"] == "t-smoke"
        assert task["ground_truth"]["file"] == "ground_truth.json"
        assert task["checker"]["kind"] == "pair-match"

    def test_release_unit_carries_the_rung_contract(self) -> None:
        unit = et.build_task_unit("req-sign", 31337, "t-l3", rung="l3")
        task = unit["task"]
        assert task["tier"] == "release"
        assert task["rung"] == "l3"
        assert task["checker"]["oracles"] == list(et.RUNG_ORACLES["l3"])
        assert task["tooling"]["packaging"] == "vm-bytecode"
        assert task["anti_debug"]["self_defending"] == "generator-native"

    def test_rung_is_ignored_for_smoke_families(self) -> None:
        unit = et.build_task_unit("py-derive", 1, "t-r", rung="l3")
        assert unit["task"]["tier"] == "smoke"
        assert "rung" not in unit["task"]

    def test_unknown_family_refuses(self) -> None:
        with pytest.raises(KeyError):
            et.build_task_unit("no-such-family", 1, "t-x")

    def test_write_mint_is_idempotent_with_an_executable_checker(
            self, tmp_path) -> None:
        d1 = et.write_task_unit("js-sign", 606, "unit-a", tmp_path)
        assert (d1 / "task.yaml").is_file()
        assert (d1 / "ground_truth.json").is_file()
        checker = d1 / "checker.py"
        assert checker.is_file() and checker.stat().st_mode & 0o111
        target = d1 / "target"
        assert target.is_dir() and any(target.iterdir())
        first = (d1 / "task.yaml").read_text(encoding="utf-8")
        d2 = et.write_task_unit("js-sign", 606, "unit-a", tmp_path)
        assert d1 == d2
        assert (d2 / "task.yaml").read_text(encoding="utf-8") == first

    @pytest.mark.skipif(shutil.which("npx") is not None,
                        reason="the structured-SKIP contract only exists "
                               "when the obfuscator toolchain is absent")
    def test_l2_mint_without_npx_is_a_structured_skip(
            self, tmp_path, capsys) -> None:
        d = et.write_task_unit("req-sign", 707, "unit-l2", tmp_path,
                               rung="l2")
        assert "SKIP" in capsys.readouterr().out
        assert not (d / "task.yaml").exists()


class TestCliMint:
    def test_three_and_four_piece_specs_mint(self, tmp_path) -> None:
        root = tmp_path / "corpus"
        rc = et.main(["--root", str(root),
                      "--mint", "go-arx:11:cli-a",
                      "--mint", "req-sign:22:cli-b:l0"])
        assert rc == 0
        assert (root / "cli-a" / "task.yaml").is_file()
        assert (root / "cli-b" / "task.yaml").is_file()
        task_b = yaml.safe_load(
            (root / "cli-b" / "task.yaml").read_text(encoding="utf-8"))
        assert task_b["rung"] == "l0"

    def test_bad_spec_count_is_a_usage_error(self, tmp_path) -> None:
        with pytest.raises(SystemExit) as exc:
            et.main(["--root", str(tmp_path), "--mint", "go-arx:11"])
        assert exc.value.code == 2

    def test_no_mint_flag_is_a_usage_error(self, tmp_path) -> None:
        with pytest.raises(SystemExit) as exc:
            et.main(["--root", str(tmp_path)])
        assert exc.value.code == 2
