# -*- coding: utf-8 -*-
"""tests/test_probe_features_581.py — the epistemic probe-feature pins.

The state signature's feature key is structural, not epistemic: two
targets with identical {lane, project_type, target_kind} share one
Q-cell no matter how differently they look to a 5-second probe. These
pins fold the cheap probe outputs the loop already produces (the die
face's entropy + packer verdict, the floss survivor-set's embedded-
constant density) into the canonical feature vocabulary, wire them
through the state-signature build, and pin the tolerance faces:

  1. vocabulary — ent:/fc:/die:verdict= tokens over present evidence
     only (absence never scores); banding is fixed-edge, float-free.
  2. feature-table/1 additive bump — legacy rows keep validating;
     rows with floss evidence carry the optional third probe face.
  3. state-signature wiring — differing probe results on structurally
     identical targets produce differing signatures; the same target
     re-probed produces the same signature (content reads only — no
     mtime/ordering dependence).
  4. discovery novelty — probe tokens are first-class tokens.
  5. tolerant fold — the warm posterior store folds by family, never
     by feature key, so richer keys cold-start through pooling.

No difficulty/tier flag exists anywhere in the dispatch faces — the
discriminator is evidence; the readout tier slice is read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import feature_prior as fp  # noqa: E402
from rlvr import meta_arms  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr import strategy_store  # noqa: E402
from rlvr import state as rlvr_state  # noqa: E402
import feature_mining  # noqa: E402


def _features(**overrides) -> dict:
    """A fully-populated features vector (the mined shape) with probe
    overrides applied per call."""
    feats = {
        "lane": "malware",
        "project_type": "beacon",
        "target_kind": {"language": "rust/arm64-android",
                        "entry_suffix": ".apk"},
        "packer_flags": {"packing": False, "obfuscation": False,
                         "anti_analysis": False, "surface_reduction": False,
                         "detected_packers": [], "detected_obfuscators": []},
        "difficulty_factors": None,
        "probe_outputs": {
            "die": {"prescan_state": "available", "usable": True,
                    "detected_packer": None, "entropy_max": 4.2},
            "apkid": {"prescan_state": "available", "usable": False,
                      "packers": [], "obfuscators": []},
        },
    }
    for key, value in overrides.items():
        if value is None:
            feats.pop(key)
        else:
            feats[key] = value
    return feats


def _tokens(feats: dict) -> frozenset[str]:
    return fp.feature_tokens(feats)


# ---------------------------------------------------------------------------
# 1. vocabulary — the probe token categories
# ---------------------------------------------------------------------------

class TestEntropyTokens:
    @pytest.mark.parametrize("entropy,band", [
        (1.2, "ent:low"), (2.99, "ent:low"), (3.0, "ent:mid"),
        (4.2, "ent:mid"), (5.49, "ent:mid"), (5.5, "ent:high"),
        (6.9, "ent:high"), (7.0, "ent:saturated"), (7.9, "ent:saturated"),
    ])
    def test_fixed_edge_bands(self, entropy, band):
        feats = _features()
        feats["probe_outputs"]["die"]["entropy_max"] = entropy
        assert band in _tokens(feats)

    @pytest.mark.parametrize("entropy", [None, "7.0", True])
    def test_absent_or_non_numeric_entropy_emits_nothing(self, entropy):
        feats = _features()
        feats["probe_outputs"]["die"]["entropy_max"] = entropy
        assert not any(t.startswith("ent:") for t in _tokens(feats))

    def test_missing_die_face_emits_nothing(self):
        feats = _features(probe_outputs={"apkid": {
            "prescan_state": None, "usable": False, "packers": [],
            "obfuscators": []}})
        assert not any(t.startswith("ent:") for t in _tokens(feats))


class TestConstantDensityTokens:
    def _floss(self, survivors, constants):
        feats = _features()
        feats["probe_outputs"]["floss"] = {"survivors": survivors,
                                           "constants": constants}
        return feats

    @pytest.mark.parametrize("survivors,constants,band", [
        (1000, 10, "fc:sparse"),      # 0.010
        (1000, 19, "fc:sparse"),      # 0.019
        (1000, 20, "fc:moderate"),    # 0.020 — the edge goes up
        (1000, 50, "fc:moderate"),    # 0.050
        (1000, 99, "fc:moderate"),    # 0.099
        (1000, 100, "fc:dense"),      # 0.100 — the edge goes up
        (1000, 400, "fc:dense"),      # 0.400
    ])
    def test_fixed_edge_density_bands(self, survivors, constants, band):
        assert band in _tokens(self._floss(survivors, constants))

    @pytest.mark.parametrize("survivors,constants", [
        (None, None), (None, 10), (0, 10), (1000, None), (-5, 3),
    ])
    def test_absence_never_scores(self, survivors, constants):
        assert not any(t.startswith("fc:")
                       for t in _tokens(self._floss(survivors, constants)))

    def test_legacy_shape_carries_no_density_token(self):
        assert not any(t.startswith("fc:") for t in _tokens(_features()))


class TestDieVerdictTokens:
    def test_packed_when_a_packer_is_detected(self):
        feats = _features()
        feats["probe_outputs"]["die"]["detected_packer"] = "upx"
        assert "die:verdict=packed" in _tokens(feats)

    def test_clean_when_usable_without_a_packer(self):
        assert "die:verdict=clean" in _tokens(_features())

    def test_no_verdict_when_die_unusable(self):
        feats = _features()
        feats["probe_outputs"]["die"]["usable"] = False
        assert not any(t.startswith("die:verdict=")
                       for t in _tokens(feats))


class TestProbeTokenSubset:
    def test_probe_subset_is_exactly_the_epistemic_prefixes(self):
        tokens = fp.probe_feature_tokens(_features())
        assert tokens
        assert all(t.startswith(fp.PROBE_TOKEN_PREFIXES) for t in tokens)
        assert all(not t.startswith(("lane=", "ptype=", "lang=", "entry="))
                   for t in tokens)

    def test_difficulty_labels_never_ride_the_probe_face(self):
        """The red line: the discriminator is evidence, never a label —
        the probe face carries no tier/difficulty token even when the
        mined calibration block is present."""
        feats = _features(difficulty_factors={
            "tier": "hard", "score": 0.7, "dominant_factor": "packing",
            "factors": {}, "families": {}, "coverage": {"die": True,
                                                        "apkid": False}})
        assert "tier=hard" in _tokens(feats)  # mined vocabulary, unchanged
        assert not any(t.startswith(("tier=", "dom="))
                       for t in fp.probe_feature_tokens(feats))

    def test_empty_features_give_empty_subset(self):
        assert fp.probe_feature_tokens({}) == frozenset()
        assert fp.probe_feature_tokens(None) == frozenset()


class TestSimilarityFaces:
    def test_structurally_identical_different_probes_differ(self):
        a = _features()
        b = _features()
        b["probe_outputs"]["die"]["entropy_max"] = 7.6
        b["probe_outputs"]["floss"] = {"survivors": 500, "constants": 100}
        assert 0.0 < fp.similarity(a, b) < 1.0

    def test_identical_probes_score_one(self):
        assert fp.similarity(_features(), _features()) == 1.0

    def test_all_probes_absent_matches_legacy_tokens(self):
        legacy = _features()
        legacy["probe_outputs"]["die"]["entropy_max"] = None
        assert _tokens(legacy) == _tokens(_features()) - {"ent:mid"}


# ---------------------------------------------------------------------------
# 2. feature-table/1 additive vocabulary bump
# ---------------------------------------------------------------------------

class TestFeatureTableAdditiveBump:
    def _row(self, probe_outputs) -> dict:
        return {
            "schema": "feature-table/1", "run_id": "r1", "family": "release",
            "task_id": "unit-1", "signature_hash": "a" * 12,
            "features": _features(probe_outputs=probe_outputs),
            "outcomes": [],
        }

    def test_legacy_row_still_validates(self):
        assert feature_mining.validate_row(self._row({
            "die": {"prescan_state": None, "usable": False,
                    "detected_packer": None, "entropy_max": None},
            "apkid": {"prescan_state": None, "usable": False,
                      "packers": [], "obfuscators": []}})) == []

    def test_row_with_floss_face_validates(self):
        assert feature_mining.validate_row(self._row({
            "die": {"prescan_state": None, "usable": False,
                    "detected_packer": None, "entropy_max": None},
            "apkid": {"prescan_state": None, "usable": False,
                      "packers": [], "obfuscators": []},
            "floss": {"survivors": 1200, "constants": 34}})) == []

    @pytest.mark.parametrize("floss", [
        {"survivors": 1},
        {"survivors": 1, "constants": 1, "extra": 2},
        {"survivors": -1, "constants": 1},
        {"survivors": True, "constants": 1},
        {"survivors": 1.5, "constants": 1},
        {"survivors": 1, "constants": "3"},
        "not-a-dict",
    ])
    def test_malformed_floss_face_rejected(self, floss):
        po = {"die": {"prescan_state": None, "usable": False,
                      "detected_packer": None, "entropy_max": None},
              "apkid": {"prescan_state": None, "usable": False,
                        "packers": [], "obfuscators": []},
              "floss": floss}
        assert feature_mining.validate_row(self._row(po)) != []

    def test_unknown_probe_faces_rejected(self):
        po = {"die": {"prescan_state": None, "usable": False,
                      "detected_packer": None, "entropy_max": None},
              "apkid": {"prescan_state": None, "usable": False,
                        "packers": [], "obfuscators": []},
              "virustotal": {"verdict": "clean"}}
        assert feature_mining.validate_row(self._row(po)) != []


# ---------------------------------------------------------------------------
# mining — the floss face enters the mined features
# ---------------------------------------------------------------------------

def _write_die(ws: Path, entropy: float, packer: str | None = None) -> None:
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    doc = {"derived": {"detected_packer": packer,
                       "section_table": [{"name": ".text",
                                          "entropy": entropy}]}}
    (ev / "die.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_floss(ws: Path, survivors: int, constants: int) -> None:
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    doc = {
        "_meta": {"source": "floss-filter", "schema_version": "v6",
                  "queried_at": "1970-01-01T00:00:00Z"},
        "input_stats": {"total_lines": 99, "total_non_empty": survivors + 7,
                        "total_after_denoise": survivors},
        "string_inventory": {"per_category_counts": {
            "urls": 1, "paths": 2, "registry": 0, "emails": 0,
            "base64_candidates": constants // 2, "stack_strings": 0,
            "high_entropy_blobs": constants - constants // 2,
            "family_keyword_hits": 0, "other": 0}},
    }
    (ev / "floss-filtered.json").write_text(json.dumps(doc),
                                            encoding="utf-8")


class TestMiningFlossFace:
    def test_salients_over_a_full_artifact(self, tmp_path):
        _write_floss(tmp_path, 1200, 34)
        sal = feature_mining._floss_salients(
            tmp_path / "evidence" / "floss-filtered.json")
        assert sal == {"survivors": 1200, "constants": 34}

    def test_absent_artifact_degrades_to_nones(self, tmp_path):
        sal = feature_mining._floss_salients(
            tmp_path / "evidence" / "floss-filtered.json")
        assert sal == {"survivors": None, "constants": None}

    def test_error_class_doc_degrades_to_nones(self, tmp_path):
        p = tmp_path / "evidence" / "floss-filtered.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(
            {"_meta": {"source": "floss-filter",
                       "error": "floss output too small",
                       "error_class": "input_too_small"}}), encoding="utf-8")
        assert feature_mining._floss_salients(p) == {
            "survivors": None, "constants": None}

    def test_missing_category_counts_degrade_constants(self, tmp_path):
        p = tmp_path / "evidence" / "floss-filtered.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"input_stats": {
            "total_after_denoise": 500}}), encoding="utf-8")
        assert feature_mining._floss_salients(p) == {
            "survivors": 500, "constants": None}

    def test_probe_outputs_emit_floss_only_with_evidence(self, tmp_path):
        """The additive-bump face: no floss artifact -> the mined
        probe_outputs keep the legacy two-face shape (byte-identical
        mining for floss-less workspaces); with an artifact the third
        face rides."""
        _write_die(tmp_path, 4.0)
        legacy = feature_mining._probe_outputs(None, tmp_path / "evidence")
        assert "floss" not in legacy
        _write_floss(tmp_path, 800, 90)
        rich = feature_mining._probe_outputs(None, tmp_path / "evidence")
        assert rich["floss"] == {"survivors": 800, "constants": 90}

    def test_mine_is_deterministic_across_remines(self, tmp_path):
        _write_die(tmp_path, 6.2)
        _write_floss(tmp_path, 640, 77)
        out1, out2 = tmp_path / "t1.jsonl", tmp_path / "t2.jsonl"
        ws_state = tmp_path / "runs" / "e2e" / "r1"
        ws_state.mkdir(parents=True)
        (ws_state / "run-state.json").write_text(json.dumps(
            {"run_id": "r1", "family": "release", "unit": "u-1",
             "ws": str(tmp_path), "task_dir": str(tmp_path)}),
            encoding="utf-8")
        feature_mining.mine([tmp_path], out1)
        feature_mining.mine([tmp_path], out2)
        assert out1.read_bytes() == out2.read_bytes()
        row = json.loads(out1.read_text(encoding="utf-8").splitlines()[0])
        assert row["features"]["probe_outputs"]["floss"] == {
            "survivors": 640, "constants": 77}

    def test_floss_difference_changes_the_instance_signature(self, tmp_path):
        _write_die(tmp_path, 6.2)
        hashes = []
        for survivors, constants in ((640, 77), (640, 300)):
            _write_floss(tmp_path, survivors, constants)
            feats = feature_mining._features({"type": "beacon"},
                                             tmp_path, tmp_path)
            hashes.append(feature_mining.signature_hash(feats))
        assert hashes[0] != hashes[1]


# ---------------------------------------------------------------------------
# 3. state-signature wiring
# ---------------------------------------------------------------------------

class TestStateSignatureProbeFace:
    def test_probe_face_over_a_probed_workspace(self, tmp_path):
        _write_die(tmp_path, 7.6, packer="upx")
        _write_floss(tmp_path, 500, 100)
        (tmp_path / "task_spec.yaml").write_text("lane: malware\n",
                                                 encoding="utf-8")
        face = rlvr_state.probe_face(tmp_path)
        assert face == sorted(fp.probe_feature_tokens(
            fp.features_from_workspace(tmp_path)))
        assert "ent:saturated" in face
        assert "die:verdict=packed" in face
        assert "fc:dense" in face

    def test_bare_workspace_face_is_empty(self, tmp_path):
        assert rlvr_state.probe_face(tmp_path) == []

    def test_snapshot_document_carries_the_probe_tokens(self, tmp_path):
        _write_die(tmp_path, 4.2)
        snap = rlvr_state.snapshot(tmp_path)
        assert snap["probe"] == {"tokens": ["die:usable", "die:verdict=clean",
                                            "ent:mid"]}

    def test_pf_segment_sits_before_the_reserved_tail(self, tmp_path):
        _write_die(tmp_path, 4.2)
        sig = rlvr_state.signature_str(rlvr_state.snapshot(tmp_path))
        assert sig.endswith("|pf=die:usable,die:verdict=clean,ent:mid|sd=-")
        assert sig.startswith("state-sig/2|")

    def test_bare_signature_keeps_the_absent_idiom(self, tmp_path):
        sig = rlvr_state.signature_str(rlvr_state.snapshot(tmp_path))
        assert "|pf=-|sd=-" in sig

    def test_structurally_identical_probes_differ_split_the_key(self, tmp_path
                                                                ):
        """The acceptance pin: two structurally identical targets with
        different probe results produce different state signatures —
        different Q-cells, per the issue-386 key form."""
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        for ws, entropy in ((ws_a, 3.0), (ws_b, 7.6)):
            ws.mkdir()
            _write_die(ws, entropy)
        snap_a = rlvr_state.snapshot(ws_a)
        snap_b = rlvr_state.snapshot(ws_b)
        for dim in ("facts", "claims", "budget", "chain", "phase",
                    "obstacles", "sides"):
            assert snap_a[dim] == snap_b[dim], \
                "the fixtures must be structurally identical"
        assert snap_a["probe"] != snap_b["probe"]
        assert rlvr_state.signature_hash(snap_a) \
            != rlvr_state.signature_hash(snap_b)

    def test_same_target_reprobes_to_the_same_signature(self, tmp_path):
        """Determinism: content reads only — re-probing the same target
        (same bytes, fresh timestamps) yields the same signature."""
        _write_die(tmp_path, 5.0)
        _write_floss(tmp_path, 900, 100)
        first = rlvr_state.signature_hash(rlvr_state.snapshot(tmp_path))
        import os
        for p in sorted(tmp_path.rglob("*")):
            os.utime(p, (0, 0))  # wipe every mtime
        second = rlvr_state.signature_hash(rlvr_state.snapshot(tmp_path))
        assert first == second
        assert first == rlvr_state.signature_hash(
            rlvr_state.snapshot(tmp_path))

    def test_replay_of_a_legacy_snapshot_document_is_stable(self):
        """Recorded pre-bump snapshot docs (no probe key) re-sign to
        their recorded string — the append-only streams never re-key."""
        legacy_state = {"schema": "state-sig/2",
                        "facts": {"count": 0, "verified": 0, "bucket": 0},
                        "claims": {"pattern": ""},
                        "budget": {"fraction": 0.0, "bucket": 0,
                                   "present": False},
                        "chain": None, "phase": None,
                        "obstacles": {"present": False, "count": 0,
                                      "kinds": ""},
                        "sides": {}}
        assert rlvr_state.signature_str(legacy_state) == (
            "state-sig/2|fc=0|fv=0|cp=-|bg=0|ch=-|ph=-|ob=-|pf=-|sd=-")


# ---------------------------------------------------------------------------
# 4. discovery novelty — probe tokens are first-class
# ---------------------------------------------------------------------------

class TestDiscoveryNovelty:
    def test_probe_only_difference_reads_novel(self):
        existing = [_features()]
        hyp = _features()
        hyp["probe_outputs"]["die"]["entropy_max"] = 7.7
        hyp["probe_outputs"]["floss"] = {"survivors": 300, "constants": 90}
        assert fp.jaccard(fp.feature_tokens(hyp),
                          fp.feature_tokens(existing[0])) < 1.0

    def test_renamed_arm_with_identical_probes_stays_dead(self):
        feats = _features()
        assert fp.jaccard(fp.feature_tokens(feats),
                          fp.feature_tokens(_features())) == 1.0


# ---------------------------------------------------------------------------
# 5. the tolerant fold — richer keys never hard-break warm start
# ---------------------------------------------------------------------------

class TestTolerantFold:
    def test_feature_key_moves_with_the_vocabulary(self):
        """The feature key is a digest of the token set: richer probe
        evidence moves the key. Nothing keys hard on it — this pin
        documents the movement the fold must tolerate."""
        bare = strategy_store.feature_key_of.__module__  # import sanity
        del bare
        a = fp.feature_tokens(_features())
        b = fp.feature_tokens(_features(probe_outputs={
            "die": {"prescan_state": "available", "usable": True,
                    "detected_packer": None, "entropy_max": 7.7},
            "apkid": {"prescan_state": "available", "usable": False,
                      "packers": [], "obfuscators": []},
            "floss": {"survivors": 300, "constants": 90}}))
        assert a != b

    def test_warm_pools_fold_by_family_not_by_feature_key(self, tmp_path,
                                                          monkeypatch):
        """Old-store rows written under pre-bump feature keys still warm
        the new-key workspace: the store read face is family-keyed, so
        the richer key cold-starts through pooling (the deliberate
        compat face), never through a key match that can no longer
        hit."""
        store = tmp_path / "store"
        monkeypatch.setenv(strategy_store.STORE_ENV, str(store))
        for credit in (1.0, 0.0):
            assert strategy_store.append_store_row(
                tmp_path / "ws-old", method_family="static-decompile",
                status="settled", credit=credit,
                feature_key="legacy-key-0000")["appended"] is True
        # a workspace whose mined features carry the new probe tokens
        _write_die(tmp_path / "ws-new", 7.6)
        pools = strategy_store.warm_pools(tmp_path / "ws-new",
                                          ["static-decompile"])
        assert "static-decompile" in pools
        assert pools["static-decompile"].rows == 2

    def test_cell_posterior_at_a_fresh_probe_signature_pools_the_family(
            self):
        """A probe-split signature has no local cell; the anchor falls
        back through the family aggregate (cold start via pooling, not
        the bare uniform)."""
        rows = []
        for i, credit in enumerate((1.0, 0.0, 1.0, 1.0)):
            rows.append({"schema": q_cells.OBS_SCHEMA,
                         "signature_hash": f"{'a' * 11}{i}",
                         "method_family": "static-decompile",
                         "credit": credit})
        store = q_cells.InMemoryStore(rows)
        fold_view = q_cells.fold(store, gamma=1.0)
        fresh = "b" * 12  # no row ever recorded at this signature
        alpha, beta = q_cells.cell_posterior(fold_view, fresh,
                                             "static-decompile")
        assert alpha > q_cells.BASE_ALPHA and beta > q_cells.BASE_BETA
        flat = q_cells.cell_posterior(
            q_cells.fold(q_cells.InMemoryStore([]), gamma=1.0), fresh,
            "static-decompile")
        assert (alpha, beta) != (flat[0], flat[1])

    def test_meta_pool_absorbs_probe_fragmentation(self):
        """More keys mean sparser cells; the meta-arm hierarchical pool
        is the absorption face — same-meta arms pool their evidence no
        matter which probe-split signatures the rows came from."""
        rows = [{"method_family": "static-decompile", "credit": 1.0,
                 "fingerprint": "sig-ent-high"},
                {"method_family": "structural-anchoring", "credit": 0.0,
                 "fingerprint": "sig-ent-low"}]
        out = meta_arms.hierarchical_prior(
            rows, ["static-decompile", "structural-anchoring"],
            current_fp="sig-ent-mid")
        # both arms sit in structural-probing; each pools the other's
        # tempered meta evidence on top of its own
        for fam in out:
            assert 0.05 <= out[fam] <= 1.0
