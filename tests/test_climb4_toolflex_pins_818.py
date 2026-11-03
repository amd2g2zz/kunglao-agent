#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_toolflex_pins_818.py — #818 climb segment 4M.

Behavior pins for scripts/eval_toolflex.py — the #356 tool-flex unit
generator (20.5% measured): the registry invariants, the stage-kind
mapping, the per-tool argv usage templates, the seeded config, the
pipeline math (composition identity, the tool-lib mirror proof), the
payload/params material, and build_unit's in-memory inventory with the
blob roundtrip proof.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_targets as tg  # noqa: E402
import eval_toolflex as tf  # noqa: E402


class TestRegistry:
    def test_registry_invariants_hold(self) -> None:
        tf._validate_registry()  # re-runs the import-time gate
        assert set(tf.TF_FAMILIES) == {"tf-chain2", "tf-chain3",
                                       "tf-chain4"}
        for family, meta in tf.TF_FAMILIES.items():
            assert len(meta["roles"]) == meta["k"]
            assert all(len(r["impls"]) == 2 for r in meta["roles"])

    def test_stage_kind_mapping(self) -> None:
        assert tf._stage_kind(4, 0) == "extract"
        assert tf._stage_kind(4, 1) == "mix"
        assert tf._stage_kind(4, 2) == "expand"
        assert tf._stage_kind(4, 3) == "final"
        assert tf._stage_kind(2, 1) == "final"
        with pytest.raises(ValueError, match="no stage for role"):
            tf._stage_kind(3, 3)  # beyond the chain: no stage exists

    def test_usage_templates_cover_every_impl(self, tmp_path) -> None:
        usage = tf.tool_usage("tf-chain3")
        assert set(usage) == {"xtract", "scan", "mix", "blend",
                              "emit64", "reemit64"}
        assert usage["xtract"] == "{tool} {blob}"
        assert usage["scan"] == "{tool} --blob {blob}"
        # the final-stage flag follows the K-dependent input name (k=3 key)
        assert "--key {state} --payload {payload}" in usage["reemit64"]


class TestPipelineMath:
    def test_cfg_is_seeded_and_deterministic(self) -> None:
        a = tf.derive_tf_cfg("tf-chain2", 35601)
        b = tf.derive_tf_cfg("tf-chain2", 35601)
        c = tf.derive_tf_cfg("tf-chain2", 35602)
        assert a == b
        assert a["p"] != c["p"] and a["k1_hex"] != c["k1_hex"]
        assert len(a["p"]) == 4
        assert len(bytes.fromhex(a["k1_hex"])) == 32  # the blob key

    def test_stage_digest_is_the_pipeline_composition(self) -> None:
        cfg = tf.derive_tf_cfg("tf-chain2", 35601)
        w0, w1 = tf.expand_stage(tf.mix_stage(cfg["p"]))
        for data in (b"", b"payload", b"x" * 55):
            assert tf.stage_digest(cfg, data) == tf.final_stage(w0, w1,
                                                                data)

    def test_digest_is_deterministic_and_data_sensitive(self) -> None:
        cfg = tf.derive_tf_cfg("tf-chain2", 35601)
        assert tf.stage_digest(cfg, b"a") == tf.stage_digest(cfg, b"a")
        assert tf.stage_digest(cfg, b"a") != tf.stage_digest(cfg, b"b")
        out = tf.stage_digest(cfg, b"a")
        assert 0 <= out <= tf.M64

    def test_expand_halves_are_masked_and_deterministic(self) -> None:
        a = tf.expand_stage(123456789)
        b = tf.expand_stage(123456789)
        assert a == b
        assert all(0 <= half <= tf.M64 for half in a)
        assert a != tf.expand_stage(987654321)

    def test_tool_math_lib_is_a_true_mirror(self) -> None:
        # the shipped tool source's math lib must agree with the model
        namespace: dict = {}
        exec(compile(tf._TOOL_MATH_LIB, "<tool-math>", "exec"), namespace)
        for key in ([(1, 2, 3), (0, 0, 0), (7, 9, 1 << 40)]):
            p = list(key)
            assert namespace["stage_mix"](p) == tf.mix_stage(p)
            assert namespace["stage_expand"](12345) == \
                tf.expand_stage(12345)
            assert namespace["stage_final"](5, 7, b"abc") == \
                tf.final_stage(5, 7, b"abc")


class TestMaterial:
    def test_payload_text_shape_and_determinism(self) -> None:
        t1 = tf._payload_text(35601, 0)
        t2 = tf._payload_text(35601, 0)
        t3 = tf._payload_text(35601, 1)
        assert t1 == t2 and t1 != t3
        lines = t1.splitlines()
        assert len(lines) == 2  # two u64 words per payload
        assert all(len(l) == 32 and int(l, 16) >= 0 for l in lines)

    def test_blob_roundtrips_through_the_extract_math(self) -> None:
        # the extract tool's job: mod-crypto counter-mode keyed by K1
        seed = 35601
        cfg = tf.derive_tf_cfg("tf-chain2", seed)
        blob_hex = tf._encrypt_params(cfg, seed).strip()
        blob = bytes.fromhex(blob_hex)
        key = tf._k1_bytes(seed)
        cfg_sha = tg.mod_sha_cfg(seed)
        stream = bytearray()
        counter = 0
        while len(stream) < len(blob):
            stream += tg.mod_sha256(cfg_sha,
                                    key + counter.to_bytes(4, "big"))
            counter += 1
        plain = bytes(a ^ b for a, b in zip(blob, stream))
        assert json.loads(plain.decode("utf-8"))["p"] == cfg["p"]


class TestBuildUnit:
    def test_unit_inventory_and_ground_truth(self) -> None:
        unit = tf.build_unit("tf-chain3", "tf-chain3-js-v1", 35602)
        files = unit["files"]
        assert "target/blob.enc" in files
        assert "target/payload.bin" in files
        assert len(files["target/README.txt"]) > 0
        tools = [f for f in files if f.startswith("toolbox/")]
        assert len(tools) == 6  # k=3 roles x 2 impls
        # ground truth ships as a unit file AND is the model's own digest
        gt = json.loads(files["ground_truth.json"])
        assert len(gt["published_pairs"]) == tf.PROBE_COUNT + 1
        cfg = tf.derive_tf_cfg("tf-chain3", 35602)
        for pair in gt["published_pairs"]:
            text = files[pair["file"]]
            assert pair["out"] == f"{tf.stage_digest(cfg, text.encode()):016x}"

    def test_rebuild_is_byte_identical(self) -> None:
        one = tf.build_unit("tf-chain2", "u", 35601)
        two = tf.build_unit("tf-chain2", "u", 35601)
        assert one["files"] == two["files"]
        assert one["task"] == two["task"]
