# -*- coding: utf-8 -*-
"""#478 PR2: adaptive retention + analogy transfer + landing wiring.
Spec scenarios pinned one-to-one (PR1 style)."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import distill_spine as ds  # noqa: E402


def _playbook(**over):
    pb = {"schema": "playbook/1", "name": "hardened-so-static",
          "problem_signature": ["arm64", "ollvm"],
          "steps": [{"n": 1, "tool_ref": "ghidra-light",
                     "expected_evidence": "symbols-mapped"},
                    {"n": 2, "tool_ref": "replay",
                     "expected_evidence": "byte-exact"}]}
    pb.update(over)
    return pb


#: every safety signal green (strong verification, earned trust, exercised)
_FULL = {"verification_strength": "byte-exact", "source_trust": 0.9,
         "reconstruction_telemetry": {"retrievals": 1}}


_MILESTONES = {"milestones_reached": ["symbols-mapped", "byte-exact"]}


class TestRetention:
    def test_first_of_kind_stays_rich(self):
        r = ds.retention(_playbook(), dict(_FULL))
        assert r["detail_level"] == "rich"
        assert r["actions"] == []

    def test_pure_and_deterministic(self):
        prod = _playbook(corroboration=2)
        prod["form"] = {"kind": "code", "script": "x.py", "prose": "p"}
        before = copy.deepcopy(prod)
        r_a = ds.retention(prod, dict(_FULL))
        r_b = ds.retention(prod, dict(_FULL))
        assert r_a == r_b
        assert prod == before  # the call itself never mutates

    def test_corroboration_compresses_to_skeleton(self):
        prod = _playbook(corroboration=2)
        prod["form"] = {"kind": "code", "script": "x.py", "prose": "p"}
        r = ds.retention(prod, dict(_FULL))
        assert r["detail_level"] == "skeleton"
        assert r["actions"] == ["drop:form.prose"]
        snap = r["signals_snapshot"]
        assert snap["corroboration"] == 2
        assert snap["verification_strength"] == "byte-exact"
        assert snap["source_trust"] == 0.9
        assert snap["reconstruction_telemetry"] == {"rederive_events": 0,
                                                    "retrievals": 1}

    def test_weak_verification_never_compresses(self):
        sig = dict(_FULL, verification_strength="weak")
        assert ds.retention(_playbook(corroboration=2), sig)[
            "detail_level"] == "rich"

    def test_unknown_trust_blocks_compression(self):
        sig = dict(_FULL, source_trust=None)
        assert ds.retention(_playbook(corroboration=2), sig)[
            "detail_level"] == "rich"

    def test_low_trust_blocks_compression(self):
        sig = dict(_FULL, source_trust=0.2)
        assert ds.retention(_playbook(corroboration=2), sig)[
            "detail_level"] == "rich"

    def test_never_retrieved_tightens(self):
        sig = dict(_FULL, reconstruction_telemetry={})
        assert ds.retention(_playbook(corroboration=2), sig)[
            "detail_level"] == "rich"

    def test_rederive_events_loosen_first_of_kind(self):
        sig = dict(_FULL, reconstruction_telemetry={"rederive_events": 1})
        assert ds.retention(_playbook(corroboration=1), sig)[
            "detail_level"] == "skeleton"

    def test_tpass_stamps_retention_new_and_merged(self):
        existing = []
        r1 = ds.tpass("playbook", _playbook(), provenance={"source": "S1"},
                      fixture=dict(_MILESTONES), existing=existing,
                      signals=dict(_FULL))
        assert r1["action"] == "new"
        assert r1["product"]["retention"]["detail_level"] == "rich"
        existing.append(r1["product"])
        r2 = ds.tpass("playbook", _playbook(name="another"),
                      provenance={"source": "S2"}, fixture=dict(_MILESTONES),
                      existing=existing, signals=dict(_FULL))
        assert r2["action"] == "merged"
        assert r2["product"] is existing[0]  # the merged-into prior rides
        # the merge is recorded (PR1) and retention recomputed on it
        assert existing[0]["corroboration"] == 2
        assert existing[0]["retention"]["detail_level"] == "skeleton"
        assert existing[0]["retention"]["signals_snapshot"][
            "corroboration"] == 2

    def test_documented_flow_merge_compresses(self, tmp_path):
        """signals_for -> tpass (the documented producer flow): a merge
        keeps the PRIOR's own-source signals, refreshes corroboration,
        and can drop to skeleton; the snapshot never attributes the
        incoming source's trust to the merged product."""
        logs = tmp_path / "runs" / "logs"
        logs.mkdir(parents=True)
        (logs / "kunglao-2026-10-02.jsonl").write_text(
            json.dumps({"action": "recall_injected", "tool": None,
                        "artifact": None,
                        "detail": "files:runs/distill-products/"
                                  "hardened-so-static.json"})
            + "\n", encoding="utf-8")
        ds.trust_event(tmp_path, "S1", landed=True)
        ds.trust_event(tmp_path, "S2", landed=True)
        existing = []
        r1 = ds.tpass("playbook", _playbook(), provenance={"source": "S1"},
                      fixture=dict(_MILESTONES), existing=existing,
                      signals=ds.signals_for(
                          tmp_path, _playbook(provenance={"source": "S1"}),
                          verification_strength="byte-exact"))
        existing.append(r1["product"])
        assert r1["product"]["retention"]["detail_level"] == "rich"
        r2 = ds.tpass("playbook", _playbook(name="another"),
                      provenance={"source": "S2"}, fixture=dict(_MILESTONES),
                      existing=existing,
                      signals=ds.signals_for(
                          tmp_path, _playbook(provenance={"source": "S2"}),
                          verification_strength="weak"))
        assert r2["action"] == "merged"
        snap = existing[0]["retention"]["signals_snapshot"]
        assert existing[0]["retention"]["detail_level"] == "skeleton"
        assert snap["corroboration"] == 2
        assert snap["source_trust"] == 1.0   # S1's, not S2's assembly
        assert snap["verification_strength"] == "byte-exact"


class TestSignalsFor:
    def test_signals_for_reads_ledger_and_audit_stream(self, tmp_path):
        logs = tmp_path / "runs" / "logs"
        logs.mkdir(parents=True)
        rows = [
            {"action": "tool_call", "tool": "replay"},
            {"action": "tool_call", "tool": "replay"},
            {"action": "recall_injected", "tool": None,
             "artifact": None, "detail": "files:runs/distill-products/"
                                        "hardened-so-static.json"},
        ]
        (logs / "kunglao-2026-10-02.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        ds.trust_event(tmp_path, "S1", landed=True)  # earns a trust entry
        sig = ds.signals_for(tmp_path,
                             _playbook(provenance={"source": "S1"}),
                             verification_strength="byte-exact")
        assert sig["source_trust"] == 1.0
        assert sig["reconstruction_telemetry"] == {"rederive_events": 2,
                                                   "retrievals": 1}

    def test_signals_for_unknown_source_is_none(self, tmp_path):
        sig = ds.signals_for(tmp_path, _playbook(provenance={"source": "X"}))
        assert sig["source_trust"] is None


class TestAnalogy:
    def test_mismatch_dims_become_holes(self):
        r = ds.analogy_layers(_playbook(),
                              {"target_tokens": ["arm64", "strip"]})
        assert r["kept"] == ["methodology"]  # technique-family dropped
        assert r["holes"] == ["ollvm"]
        assert r["aligned_dims"] == ["arm64"]
        assert r["similarity"] == pytest.approx(1 / 3)

    def test_aligned_features_keep_technique_family(self):
        r = ds.analogy_layers(_playbook(),
                              {"target_tokens": ["arm64", "ollvm"]})
        assert r["kept"] == ["methodology", "technique-family"]
        assert r["holes"] == []

    def test_similarity_reuses_feature_prior_jaccard(self):
        from rlvr.feature_prior import jaccard

        r = ds.analogy_layers(_playbook(), {"target_tokens": ["arm64"]})
        assert r["similarity"] == jaccard(frozenset({"arm64", "ollvm"}),
                                          frozenset({"arm64"}))

    def test_decision_entry_signature_tokens(self):
        src = {"schema": ds.DECISION_SCHEMA, "signature_tokens":
               ["hmac", "sha256"], "method_family": "kdf",
               "applicability": "arm", "failure_modes": []}
        r = ds.analogy_layers(src, {"target_tokens": ["sha256", "aes"]})
        assert r["holes"] == ["hmac"]
        assert r["aligned_dims"] == ["sha256"]


class TestTransferHypothesis:
    def test_plan_written_run_local_with_unverified_holes(self, tmp_path):
        p = ds.transfer_hypothesis(tmp_path, _playbook(),
                                   feature_match={"target_tokens":
                                                  ["arm64", "strip"]})
        assert p.is_file()
        assert p.relative_to(tmp_path).parts[:2] == ("runs",
                                                    "distill-hypotheses")
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert doc["schema"] == "playbook/1"
        assert ds.validate_product("playbook", doc) == []
        assert all(s.get("unverified") is True for s in doc["steps"])
        assert all(s.get("holes") == ["ollvm"] for s in doc["steps"])
        assert doc["hypothesis"]["status"] == "HYPOTHESIS"
        assert doc["hypothesis"]["layers_kept"] == ["methodology"]
        assert doc["hypothesis"]["transferred_from"] == "hardened-so-static"

    def test_transfer_without_adjudication_raises(self, tmp_path):
        with pytest.raises(ds.SpineOrderError):
            ds.transfer_hypothesis(tmp_path, _playbook())


class TestLanding:
    def test_landing_goes_through_474_api(self, tmp_path):
        script = tmp_path / "scripts-local" / "hardened-so-static.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('ok')\n", encoding="utf-8")
        r = ds.tpass("playbook", _playbook(),
                     provenance={"source": "S1",
                                 "script_path":
                                 "scripts-local/hardened-so-static.py"},
                     fixture=dict(_MILESTONES))
        out = ds.land(tmp_path, "playbook", r["product"])
        assert out["landed"] is True
        assert out["tool_landing"] == "landed"
        tool = tmp_path / "tools-local" / "hardened-so-static.py"
        assert tool.is_file()
        manifest = json.loads(
            (tmp_path / "tools-local" / "hardened-so-static.manifest.json")
            .read_text(encoding="utf-8"))
        assert manifest["schema"] == "distill-manifest/1"
        assert manifest["oracle"]["satisfied"] is True
        assert (tmp_path / "runs" / "distill-products"
                / "hardened-so-static.json").is_file()
        ledger = json.loads(
            (tmp_path / "runs" / "distill-budget.json")
            .read_text(encoding="utf-8"))
        assert ledger["global"]["landed"] == 1  # #474's own counter face
        assert ds.load_trust(tmp_path)["sources"]["S1"]["landed"] == 1

    def test_prose_product_lands_store_only(self, tmp_path):
        r = ds.tpass("playbook", _playbook(), provenance={"source": "S1"},
                     fixture=dict(_MILESTONES))
        out = ds.land(tmp_path, "playbook", r["product"])
        assert out["landed"] is True
        assert out["tool_path"] is None
        assert out["tool_landing"] == "skipped-no-code-form"
        assert not (tmp_path / "tools-local").exists()
        ledger = json.loads(
            (tmp_path / "runs" / "distill-budget.json")
            .read_text(encoding="utf-8"))
        assert ledger["global"]["landed"] == 1  # still #474's face

    def test_corrupt_budget_ledger_refuses(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir(parents=True)
        (runs / "distill-budget.json").write_text("{garbage",
                                                 encoding="utf-8")
        out = ds.land(tmp_path, "playbook",
                      _playbook(provenance={"source": "S1"}))
        assert out["landed"] is False
        assert out["reason"] == "budget_ledger_unreadable"
        assert not (tmp_path / "tools-local").exists()
        assert not (tmp_path / "runs" / "distill-products").exists()

    def test_blacklisted_source_refuses(self, tmp_path):
        ds.trust_event(tmp_path, "S1", landed=False)
        ds.trust_event(tmp_path, "S1", landed=False)
        assert ds.blacklisted(tmp_path, "S1")
        out = ds.land(tmp_path, "playbook",
                      _playbook(provenance={"source": "S1"}))
        assert out["landed"] is False
        assert out["reason"] == "source-blacklisted"
        assert not (tmp_path / "tools-local").exists()

    def test_unknown_kind_refuses(self, tmp_path):
        out = ds.land(tmp_path, "poem", {"schema": "x"})
        assert out["landed"] is False
        assert "unknown-kind" in out["reason"]

    def test_corrupt_trust_ledger_refuses(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir(parents=True)
        (runs / "distill-trust.json").write_text("{garbage",
                                                 encoding="utf-8")
        out = ds.land(tmp_path, "playbook",
                      _playbook(provenance={"source": "S1"}))
        assert out["landed"] is False
        assert out["reason"] == "trust-ledger-unreadable"

    def test_script_outside_workspace_never_copied(self, tmp_path):
        outside = tmp_path.parent / "outside-478.py"
        outside.write_text("print('escape')\n", encoding="utf-8")
        r = ds.tpass("playbook", _playbook(),
                     provenance={"source": "S1",
                                 "script_path": "../outside-478.py"},
                     fixture=dict(_MILESTONES))
        out = ds.land(tmp_path, "playbook", r["product"])
        outside.unlink()
        assert out["landed"] is True  # the product itself is sound
        assert out["tool_landing"] == "script-outside-workspace"
        assert not (tmp_path / "runs" / "distill-attempts").exists()
        assert not (tmp_path / "tools-local").exists()

    def test_code_form_empty_script_labeled(self, tmp_path):
        prod = _playbook(provenance={"source": "S1"})
        prod["form"] = {"kind": "code", "script": ""}
        out = ds.land(tmp_path, "playbook", prod)
        assert out["landed"] is True
        assert out["tool_landing"] == "code-form-no-script"

    def test_hashless_products_collision_and_idempotent(self, tmp_path):
        """Direct-caller products without a tpass _hash: the content
        hash fallback keeps idempotency AND collision detection (a
        _hash-less None == None must never read as 'same product')."""
        first = ds.land(tmp_path, "playbook",
                        _playbook(provenance={"source": "S1"}))
        assert first["landed"] is True
        again = ds.land(tmp_path, "playbook",
                        _playbook(provenance={"source": "S1"}))
        assert again["tool_landing"] == "already-landed"
        other = _playbook(
            steps=[{"n": 1, "tool_ref": "other",
                    "expected_evidence": "other-e"}],
            provenance={"source": "S1"})
        out = ds.land(tmp_path, "playbook", other)
        assert out["landed"] is False
        assert out["reason"] == "store-name-collision"

    def test_reland_same_product_is_idempotent(self, tmp_path):
        r = ds.tpass("playbook", _playbook(), provenance={"source": "S1"},
                     fixture=dict(_MILESTONES))
        first = ds.land(tmp_path, "playbook", r["product"])
        assert first["tool_landing"] == "skipped-no-code-form"
        again = ds.land(tmp_path, "playbook", r["product"])
        assert again["landed"] is True
        assert again["tool_landing"] == "already-landed"
        ledger = json.loads(
            (tmp_path / "runs" / "distill-budget.json")
            .read_text(encoding="utf-8"))
        assert ledger["global"]["landed"] == 1  # never double-counted
        assert ds.load_trust(tmp_path)["sources"]["S1"]["landed"] == 1

    def test_store_name_collision_refuses(self, tmp_path):
        r = ds.tpass("playbook", _playbook(), provenance={"source": "S1"},
                     fixture=dict(_MILESTONES))
        assert ds.land(tmp_path, "playbook", r["product"])["landed"] is True
        other = ds.tpass("playbook",
                         _playbook(steps=[{"n": 1, "tool_ref": "other",
                                           "expected_evidence": "other-e"}]),
                         provenance={"source": "S1"},
                         fixture={"milestones_reached": ["other-e"]})
        out = ds.land(tmp_path, "playbook", other["product"])
        assert out["landed"] is False
        assert out["reason"] == "store-name-collision"


class TestToolchain:
    """The complete-toolchain closing: distill -> verify -> land ->
    REGISTER -> discoverable-by-consumer (owner challenge 2026-10-02)."""

    @staticmethod
    def _run_tool_search(*args):
        import subprocess

        tool = Path(__file__).resolve().parents[1] / "tools" / "tool-search.py"
        return subprocess.run(
            [sys.executable, str(tool), *args],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")

    @staticmethod
    def _land_code_form(ws):
        script = ws / "scripts-local" / "hardened-so-static.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("print('ok')\n", encoding="utf-8")
        r = ds.tpass("playbook", _playbook(),
                     provenance={"source": "S1",
                                 "script_path":
                                 "scripts-local/hardened-so-static.py"},
                     capability="static:unpack",
                     fixture=dict(_MILESTONES))
        return ds.land(ws, "playbook", r["product"])

    def test_usage_metadata_rides_the_manifest(self, tmp_path):
        out = self._land_code_form(tmp_path)
        assert out["tool_landing"] == "landed"
        manifest = json.loads(out["manifest_path"].read_text(encoding="utf-8"))
        usage = manifest.get("usage")
        assert isinstance(usage, dict)
        assert usage["invoke"].startswith(
            "python tools-local/hardened-so-static.py")
        assert "oracle" in usage["verified"]  # verified behavior rides too

    def test_next_worker_discovers_the_landed_tool(self, tmp_path):
        self._land_code_form(tmp_path)
        r = self._run_tool_search("--find", "hardened,unpack",
                                  "--ws", str(tmp_path), "--json")
        assert r.returncode == 0, r.stderr
        hits = json.loads(r.stdout)["tools"]
        hit = next((h for h in hits
                    if h.get("name") == "hardened-so-static"), None)
        assert hit is not None, f"landed tool not surfaced: {hits}"
        assert hit["kind"] == "run-local"
        assert hit["type"] == "tool"
        assert hit["consume"] == "invoke"
        assert hit["source"] == "tools-local/hardened-so-static.py"
        assert hit["capability"] == "static:unpack"
        assert hit["usage"].startswith("python tools-local/")

    def test_worker_citation_ritual_parses_the_hit(self, tmp_path):
        import instrument_menu

        self._land_code_form(tmp_path)
        line = "tool-search: hardened,unpack -> hardened-so-static"
        cites = instrument_menu.tool_search_citations(line)
        assert cites == [{"keywords": "hardened,unpack",
                          "result": "hardened-so-static"}]
        assert instrument_menu.citation_defects(
            "I will write a new script to unpack it. " + line) == []

    def test_no_workspace_no_runlocal_hits(self, tmp_path):
        empty = tmp_path / "not-a-ws"
        empty.mkdir()
        r = self._run_tool_search("--find", "hardened",
                                  "--ws", str(empty), "--json")
        assert r.returncode == 0, r.stderr
        hits = json.loads(r.stdout)["tools"]
        assert not [h for h in hits if h.get("kind") == "run-local"]
