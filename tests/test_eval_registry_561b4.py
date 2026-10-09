# -*- coding: utf-8 -*-
"""Registry-map parity pins for the eval-driver family dispatch.

The per-family if/elif chains in the eval drivers moved to registry maps;
these pins hold the contracts the chains used to carry inline: the exact
unknown-family refusal messages, the silent py-face fallthrough of the
probe faces, the registry coverage of the family set, and the group
structure of the misdirection probe faces.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_targets as tg  # noqa: E402
import eval_misdirection as md  # noqa: E402


class TestUnknownFamilyRefusals:
    """The refusal messages are part of the operator surface: the maps
    must reject exactly what the chains rejected, with the same words."""

    def test_derive_cfg_refuses_with_the_valid_list(self):
        with pytest.raises(ValueError) as exc:
            tg.derive_cfg("nope", 1)
        assert str(exc.value) == (
            "unknown family: nope; valid: " + str(sorted(tg.FAMILIES)))

    def test_model_output_refuses_unknown_family(self):
        with pytest.raises(ValueError) as exc:
            tg.model_output("nope", {}, 0, b"")
        assert str(exc.value) == "unknown family: nope"

    def test_license_family_has_no_model_face(self):
        """Parity with the old chain: the license family is absent from
        the model dispatch (the checker hosts its server side instead)."""
        with pytest.raises(ValueError, match="unknown family"):
            tg.model_output("net-verify-license", {}, 0, b"")

    def test_release_seam_refuses_unknown_family(self):
        cfg = tg.derive_cfg("web-pack-sign", 33210)
        with pytest.raises(ValueError) as exc:
            tg._render_release_js("nope", 33210, cfg, "l1")
        assert str(exc.value) == "unknown release family: nope"


class TestDefaultFaceParity:
    """The probe faces never refused an unknown family: the py face was
    the fallthrough. The registry default keeps that contract."""

    def test_published_pairs_unknown_family_takes_the_py_face(self):
        cfg = {"offset": 1, "prime": 3, "fold": 5}
        assert tg.published_pairs("nope", cfg, 3) == \
            tg.published_pairs("py-derive", cfg, 3)

    def test_minted_probes_unknown_family_takes_the_py_face(self):
        assert tg.minted_probes("nope", 7, 3) == \
            tg.minted_probes("py-derive", 7, 3)


class TestRegistryCoverage:
    def test_every_family_has_a_cfg_builder(self):
        assert set(tg._CFG_BUILDERS) == set(tg.FAMILIES)

    def test_model_registry_covers_all_but_the_license_family(self):
        assert set(tg._MODEL_OUTPUTS) == set(tg.FAMILIES) - {
            "net-verify-license"}

    def test_release_seam_registry_is_exactly_the_release_families(self):
        release = {name for name, meta in tg.FAMILIES.items()
                   if meta.get("tier") == "release"}
        assert set(tg._RELEASE_SEAM_FACES) == release

    def test_probe_row_registries_key_on_known_families(self):
        assert set(tg._MINTED_PROBE_ROWS) <= set(tg.FAMILIES)
        assert set(tg._PUBLISHED_BUILDERS) <= set(tg.FAMILIES)

    def test_public_constant_registries_key_on_known_families(self):
        assert set(tg._PUBLIC_CONSTANTS) <= set(tg.FAMILIES)


class TestMisdirectionProbeFaces:
    """One builder per deception face-group: the two families of a group
    must share the same callable (that sharing IS the dedup)."""

    GROUPS = (("env-misattr-js", "env-misattr-net"),
              ("key-rotation-js", "key-rotation-net"))

    def test_grouped_families_share_one_builder(self):
        for group in self.GROUPS:
            first, second = group
            assert md._MISDIRECTION_PUBLISHED[first] \
                is md._MISDIRECTION_PUBLISHED[second]
            assert md._MISDIRECTION_MINTED[first] \
                is md._MISDIRECTION_MINTED[second]
            assert md._MISDIRECTION_EXPECTED[first] \
                is md._MISDIRECTION_EXPECTED[second]

    def test_registry_keys_are_manifest_families(self):
        families = {u["family"] for u in md.UNIT_BY_ID.values()}
        assert set(md._MISDIRECTION_PUBLISHED) <= families
        assert set(md._MISDIRECTION_MINTED) <= families
        assert set(md._MISDIRECTION_EXPECTED) <= families

    def test_go_face_is_the_sole_default(self):
        """Exactly one manifest family rides the default (go) face."""
        families = {u["family"] for u in md.UNIT_BY_ID.values()}
        assert families - set(md._MISDIRECTION_PUBLISHED) \
            == {"decoy-marker-go"}
