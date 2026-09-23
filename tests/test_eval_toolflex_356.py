# -*- coding: utf-8 -*-
"""tests/test_eval_toolflex_356.py — the TF (tool-combination flexibility)
eval family: chain-necessity units + blocked-path variants (#356).

The issue is the contract. Faces pinned here:

  (a) TIER WIRING — the toolflex tier is registered additively: TIERS,
      EVAL_VERSIONS (eval-v1.3), the TIER_EVAL_VERSION map AND its
      EVAL_TIER_VERSION alias (both tier-version consumers pinned), and
      the schemas/eval-task-v1.json enums;
  (b) UNITS — >= 3 landed TF units covering K=2/3/4; every landed unit
      validates through ds.validate_task; every unit carries a
      kunglao-eval-tf-manifest/1 manifest declaring roles (each with >= 2
      implementers), the minimum required set, >= 2 valid combinations,
      a minimal chain of length K, and >= 2 blocked variants (one per
      minimal-chain tool);
  (c) CHAIN NECESSITY — the manifest records a FAILING single-tool
      baseline for EVERY toolbox tool (a unit whose baselines don't all
      fail never ships — proven by the refusal test on a tampered
      checker);
  (d) BLOCKED VARIANTS — the manifest records mint-time shadow
      verification (marker + nonzero rc) and a PASSING re-route chain per
      variant; one variant re-verified LIVE for the smallest unit;
  (e) CROSS-IMPL PARITY — every declared valid combination of the K=2
      unit produces the ground-truth answer (the combos are real, not
      decorative);
  (f) HELD-OUT — session-visible scaffold files never include
      ground_truth.json / checker.py / manifest.json;
  (g) DETERMINISM — re-rendering a family's unit files is
      byte-identical (re-mintable corpus rule);
  (h) SHARED-CONTRACT COORDINATION — the #352 single-source family
      contract (scripts/eval_contract.py) may or may not be on the base
      this branch is built from; the conformance face is adaptive —
      while absent the union note must be recorded, and the test turns
      STRICT the moment the module is present (TF rows must be
      registered there — additive union, noted in the manifest).

stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import eval_dataset as ds
import eval_toolflex as tf
import eval_tf_shadow as sh

ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "eval" / "v1" / "tasks" / "toolflex"
SCHEMA_PATH = ROOT / "schemas" / "eval-task-v1.json"


def _landed_units() -> list[Path]:
    return sorted(d for d in TF_DIR.iterdir()
                  if d.is_dir() and (d / "task.yaml").is_file())


def _manifest(tdir: Path) -> dict:
    return json.loads((tdir / "manifest.json").read_text(encoding="utf-8"))


def _task(tdir: Path) -> dict:
    return yaml.safe_load((tdir / "task.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------- (a) wiring
class TestTierWiring:
    def test_tier_registered(self):
        assert "toolflex" in ds.TIERS

    def test_eval_version_registered(self):
        assert "eval-v1.3" in ds.EVAL_VERSIONS
        assert ds.TIER_EVAL_VERSION["toolflex"] == "eval-v1.3"

    def test_both_tier_version_consumers_pinned(self):
        """TIER_EVAL_VERSION is the #334 loop runner's consumer surface;
        EVAL_TIER_VERSION is the release-tier alias kept for the native
        lane — both must carry the toolflex tier (one map, two names)."""
        assert ds.EVAL_TIER_VERSION is ds.TIER_EVAL_VERSION
        assert ds.EVAL_TIER_VERSION.get("toolflex") == "eval-v1.3"

    def test_schema_enums_extended(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert "eval-v1.3" in props["eval_version"]["enum"]
        assert "toolflex" in props["tier"]["enum"]

    def test_landed_units_use_tier_version(self):
        for tdir in _landed_units():
            task = _task(tdir)
            assert task["tier"] == "toolflex"
            assert task["eval_version"] == "eval-v1.3"


# ----------------------------------------------------------------- (b) units
class TestUnits:
    def test_at_least_three_units_k234_coverage(self):
        units = {d.name: _task(d) for d in _landed_units()}
        assert len(units) >= 3
        ks = {u["toolflex"]["k"] for u in units.values()}
        assert {2, 3, 4} <= ks, "K=2/3/4 must each exist at least once"

    def test_every_landed_unit_validates(self):
        for tdir in _landed_units():
            ok, errors = ds.validate_task(_task(tdir))
            assert ok, f"{tdir.name}: {errors}"

    def test_manifest_schema_and_declared_surface(self):
        for tdir in _landed_units():
            m = _manifest(tdir)
            assert m["schema"] == tf.SCHEMA_MANIFEST
            assert m["k"] == len(m["minimal_chain"])
            assert len(m["valid_combinations"]) >= 2
            assert len(m["blocked_variants"]) >= 2
            for role in m["roles"]:
                assert len(role["implements"]) >= 2, \
                    "every load-bearing role needs an alternate (re-route face)"
            required = m["minimum_required_set"]
            assert set(required) == {r["role"] for r in m["roles"]}
            blocked_tools = {v["blocked_tool"] for v in m["blocked_variants"]}
            assert blocked_tools == set(m["minimal_chain"]), \
                "one blocked variant per load-bearing tool of the minimal chain"

    def test_toolbox_on_disk_matches_manifest(self):
        for tdir in _landed_units():
            m = _manifest(tdir)
            declared = sorted(t for r in m["roles"] for t in r["implements"])
            on_disk = sorted(p.name for p in (tdir / "toolbox").iterdir())
            assert declared == on_disk
            for name in declared:
                tool = tdir / "toolbox" / name
                assert os.access(tool, os.X_OK), f"{name} must be executable"


# ---------------------------------------------------- (c) chain necessity
class TestChainNecessity:
    def test_every_tool_has_a_failing_baseline_recorded(self):
        for tdir in _landed_units():
            m = _manifest(tdir)
            tools = {t for r in m["roles"] for t in r["implements"]}
            baselines = {b["tool"]: b for b in m["chain_necessity"]}
            assert set(baselines) == tools, "baseline for EVERY tool"
            for tool, b in baselines.items():
                assert b["verdict"] == "FAIL", \
                    f"{tdir.name}/{tool}: single-tool baseline must FAIL"
                assert b["failure_codes"], "the failing face is recorded"

    def test_mint_refuses_when_a_baseline_passes(self, tmp_path):
        """The gate is real: with a checker that would green anything, the
        single-tool baselines PASS and mint must REFUSE the unit."""
        unit = tf.build_unit("tf-chain2", "tf-chain2-py-v1", 35601)
        stage = tmp_path / "staged" / "tf-chain2-py-v1"
        stage.mkdir(parents=True)
        for rel, payload in unit["files"].items():
            p = stage / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload, encoding="utf-8")
            if rel.startswith("toolbox/") or rel == "checker.py":
                p.chmod(0o755)  # tools must be executable for the gates
        # tamper: a checker that greens any answer (the unit is now
        # solvable by a single tool run + naive completion)
        (stage / "checker.py").write_text(
            "import json, sys\n"
            "print('METRIC pass_at_k_contribution=1')\n"
            "print('VERDICT PASS')\n"
            "sys.exit(0)\n", encoding="utf-8")
        with pytest.raises(tf.MintRefusal, match="chain-necessity"):
            tf.mint_staged_unit(stage, unit["task"], tmp_path / "staged")


# ------------------------------------------------- (d) blocked variants
class TestBlockedVariants:
    def test_mint_time_evidence_recorded(self):
        for tdir in _landed_units():
            m = _manifest(tdir)
            for v in m["blocked_variants"]:
                assert v["shadow_verified"]["rc"] != 0
                assert v["shadow_verified"]["marker"] is True
                assert v["reroute_verdict"] == "PASS"
                assert v["reroute_chain"], "the alternate route is recorded"
                alt_tools = set(v["reroute_chain"])
                assert v["blocked_tool"] not in alt_tools

    def test_live_reverification_smallest_unit(self, tmp_path):
        """The recorded evidence is reproducible NOW: rebuild the
        block-peek shadow, watch peek fail honestly, run the re-route
        chain (probe -> fold), watch the checker PASS."""
        tdir = TF_DIR / "tf-chain2-py-v1"
        m = _manifest(tdir)
        variant = next(v for v in m["blocked_variants"]
                       if v["variant"] == "block-peek")
        shadow = sh.build_shadow(tmp_path / "shadow",
                                 {"peek": "block-peek"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        env["TF_TOOLBOX"] = str(tdir / "toolbox")
        report = sh.verify_shadow("peek", shadow, env)
        assert report["rc"] != 0 and report["marker"] is True
        answer = tmp_path / "answer.txt"
        rc = tf.solve_chain(tdir, variant["reroute_chain"], answer, env=env)
        assert rc == 0, "the re-route chain solves with peek blocked"
        checker_rc, _ = tf.run_checker(tdir, answer, tmp_path)
        assert checker_rc == 0


# ------------------------------------------------- (e) cross-impl parity
class TestChainEnvOrdering:
    """PATH resolution for harness-side chain runs: shadow belt > toolbox
    > system. A tool name that collides with a system binary (the
    /usr/bin/fold class) must still resolve to the toolbox tool."""

    def test_toolbox_beats_system_same_named_binary(self, tmp_path):
        """'fold' is coreutils: pin that a same-named toolbox tool wins
        over the system PATH (and that the shadow still beats both)."""
        tdir = TF_DIR / "tf-chain2-py-v1"
        real = tdir / "toolbox" / "fold64"
        if not real.is_file():
            pytest.skip("landed corpus missing (mint first)")
        shadow = sh.build_shadow(tmp_path / "shadow", {"fold64": "b-x"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        merged = tf._chain_env(tdir, env)
        entries = merged["PATH"].split(os.pathsep)
        assert entries.index(str(shadow)) < entries.index(
            str((tdir / "toolbox").resolve())), "shadow outranks toolbox"
        assert entries.index(str((tdir / "toolbox").resolve())) < min(
            (i for i, e in enumerate(entries)
             if e.startswith("/usr") or e.startswith("/bin")),
            default=len(entries)), "toolbox outranks the system PATH"

    def test_no_tool_name_collides_with_coreutils(self):
        """TF tool names must not reuse common system binary names — a
        collision turns every un-shadowed invocation into a coin flip
        depending on PATH wiring."""
        blocklist = {"fold", "head", "tail", "sort", "uniq", "cut", "tr",
                     "wc", "seq", "test", "find", "join", "paste", "split",
                     "tsort", "sum", "hash", "sign", "verify"}
        for meta in tf.TF_FAMILIES.values():
            for role in meta["roles"]:
                clash = blocklist.intersection(role["impls"])
                assert not clash, \
                    f"tool name(s) {sorted(clash)} collide with system " \
                    "binaries — rename"


# ------------------------------------------------- (f) held-out
class TestCrossImplParity:
    def test_every_valid_combination_reproduces_ground_truth(self, tmp_path):
        """K=2 unit: all four declared combos produce the same answer the
        ground truth carries — the 'multiple valid combinations' claim is
        executed, not asserted."""
        tdir = TF_DIR / "tf-chain2-py-v1"
        m = _manifest(tdir)
        gt = json.loads((tdir / "ground_truth.json").read_text("utf-8"))
        want = [p["out"] for p in gt["published_pairs"]]
        env = dict(os.environ)
        env["TF_TOOLBOX"] = str(tdir / "toolbox")
        for combo in m["valid_combinations"]:
            answer = tmp_path / f"answer-{'-'.join(combo)}.txt"
            rc = tf.solve_chain(tdir, combo, answer, env=env)
            assert rc == 0, f"{combo} must solve"
            got = answer.read_text(encoding="utf-8").splitlines()
            assert got == want, f"{combo} must reproduce ground truth"


# ---------------------------------------------------------- (f) held-out
class TestHeldOut:
    def test_scaffold_never_carries_harness_files(self):
        for tdir in _landed_units():
            files = _task(tdir)["workspace_scaffold"]["files"]
            for rel in files:
                assert not rel.startswith("ground_truth")
                assert rel != "checker.py"
                assert rel != "manifest.json"

    def test_probes_and_toolbox_are_session_visible(self):
        tdir = TF_DIR / "tf-chain2-py-v1"
        files = _task(tdir)["workspace_scaffold"]["files"]
        assert any(f.startswith("toolbox/") for f in files)
        assert any(f.startswith("probes/") for f in files)


# ------------------------------------------------------- (g) determinism
class TestDeterminism:
    def test_rerender_is_byte_identical(self):
        unit = tf.build_unit("tf-chain2", "tf-chain2-py-v1", 35601)
        tdir = TF_DIR / "tf-chain2-py-v1"
        for rel, payload in unit["files"].items():
            landed = (tdir / rel).read_text(encoding="utf-8")
            assert payload == landed, f"{rel} must re-mint byte-identical"

    def test_tool_output_deterministic(self, tmp_path):
        tdir = TF_DIR / "tf-chain2-py-v1"
        tool = tdir / "toolbox" / "peek"
        outs = []
        for _ in range(2):
            proc = subprocess.run(
                [sys.executable, str(tool), str(tdir / "target" / "blob.enc")],
                capture_output=True, text=True, timeout=60)
            assert proc.returncode == 0, proc.stderr
            outs.append(proc.stdout)
        assert outs[0] == outs[1]


# --------------------------------------- (h) shared-contract coordination
class TestSharedContractCoordination:
    """Adaptive conformance face: the #352 single-source family contract
    (scripts/eval_contract.py) may or may not be on the base this branch
    is built from. While absent, the coordination note must be recorded
    (manifest + module docstring); the moment the module is present (the
    dev merge-sync unions it), the STRICT face activates — every TF
    family must have a contract row."""

    def test_contract_union_recorded_while_module_absent(self):
        module = ROOT / "scripts" / "eval_contract.py"
        if module.is_file():
            pytest.skip("eval_contract.py present: strict face applies")
        m = _manifest(TF_DIR / "tf-chain2-py-v1")
        assert "eval_contract" in m.get("shared_contract_note", "")
        src = (ROOT / "scripts" / "eval_toolflex.py").read_text("utf-8")
        assert "eval_contract" in src

    @pytest.mark.skipif(
        not (ROOT / "scripts" / "eval_contract.py").is_file(),
        reason="eval_contract.py lands with the #352 union")
    def test_tf_families_registered_in_shared_contract(self):
        """STRICT face: every TF family must have a contract row."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import eval_contract  # noqa: F401
        for family in ("tf-chain2", "tf-chain3", "tf-chain4"):
            row = eval_contract.require_family(family)
            assert row["suffix"] == ".txt"
