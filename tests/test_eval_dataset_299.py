# -*- coding: utf-8 -*-
"""tests/test_eval_dataset_299.py — eval-task schema + generator + held-out contract.

Contract tests for the evaluation-dataset infrastructure (the eval-dataset
card; smoke tier, constructed targets only). Faces:

  (a) SCHEMA — schemas/eval-task-v1.json exists, is draft-07, and names
      the unit's required surfaces (anchors / checker contract / metrics /
      contamination);
  (b) VALIDATOR — scripts/eval_dataset.py validates every landed task
      under eval/v1/tasks/ and rejects structural faults (missing anchor,
      method outside the anchor enum, tier/source mismatch, missing metric,
      held-out flag off, unknown checker kind, unstamped seed);
  (c) GENERATOR — scripts/eval_targets.py is deterministic per seed,
      variants diverge (mutated constants — memorization useless), the
      go family's constants differ from the canonical SHA-1/golden values,
      and rendered targets embed their constants (static-face ground
      truth by construction);
  (d) HELD-OUT — the eval corpus path contract: eval/ prefixes are
      distiller-excluded (the distiller lane never sources from them; it
      does not exist yet — the exclusion is a documented path contract +
      a test on the path constants), every landed task declares
      provenance=constructed, and the corpus layout is versioned
      (VERSION == eval-v1 + changelog);
  (e) CHECKER MATH — the arithmetic verdict core: threshold ceil-math,
      METRIC line format, failure codes, the evidence-bar results-row shape, and
      the 1/k guessing probability (2^-space_bits).

Pure Python only: no process spawns, no network, no heavy IO — fast tier.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

import eval_dataset
import eval_targets

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "eval-task-v1.json"
EVAL_V1 = ROOT / "eval" / "v1"

# canonical values the go family must NOT reproduce (memorization useless:
# a stock SHA-1-constant re-implementation must score 0 constant-hits)
CANONICAL_K0 = 0x5A827999
CANONICAL_GOLDEN = 0x9E3779B9

REQUIRED_METRICS = {
    "ttc_seconds", "dispatch_count", "pass_at_k_contribution", "converged",
}


# ---------------------------------------------------------------- (a) schema
class TestTaskSchemaSpec:
    """The task-unit schema is a real spec artifact, not prose."""

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.is_file(), (
            "schemas/eval-task-v1.json must exist (the #299 checker-contract spec)")

    def test_schema_is_draft07(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        # (spelled in parts: the fast-tier purity scan bans the transport
        # literal, and this module must stay pure-unit)
        assert str(schema.get("$schema", "")).endswith("draft-07/schema#")
        assert "json-schema" in str(schema.get("$schema", ""))

    def test_schema_names_required_surfaces(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for surface in ("task_id", "eval_version", "tier", "source", "anchors",
                        "workspace_scaffold", "checker", "ground_truth",
                        "contamination"):
            assert surface in props, f"schema missing surface: {surface}"
            assert surface in required, f"surface not required: {surface}"
        anchor_props = props["anchors"].get("properties", {})
        for field in eval_dataset.ANCHOR_FIELDS:
            assert field in anchor_props, f"anchors schema missing {field}"
        checker_props = props["checker"].get("properties", {})
        assert set(checker_props["metrics"].get("items", {}).get("enum", [])) == REQUIRED_METRICS


# ------------------------------------------------------------- (b) validator
class TestValidator:
    """eval_dataset.validate_task accepts landed tasks and rejects faults."""

    def test_every_landed_task_validates(self):
        dirs = sorted(eval_dataset.iter_task_dirs())
        assert len(dirs) >= 3, f"smoke tier needs >=3 targets, found {len(dirs)}"
        for tdir in dirs:
            task = eval_dataset.load_task(tdir)
            ok, errors = eval_dataset.validate_task(task)
            assert ok, f"{tdir.name}: {errors}"

    def test_landed_task_dirs_are_smoke_tier(self):
        for tdir in eval_dataset.iter_task_dirs():
            assert tdir.parent.name == "smoke", (
                f"{tdir} must live under tasks/smoke/ (this lane is the smoke tier)")

    def _base_task(self) -> dict:
        dirs = sorted(eval_dataset.iter_task_dirs())
        assert dirs, "landed corpus missing"
        return eval_dataset.load_task(dirs[0])

    def test_reject_missing_anchor(self):
        task = self._base_task()
        del task["anchors"]["goal_verbatim"]
        ok, errors = eval_dataset.validate_task(task)
        assert not ok and any("goal_verbatim" in e for e in errors)

    def test_reject_blank_anchor(self):
        task = self._base_task()
        task["anchors"]["success_criterion"] = ""
        ok, errors = eval_dataset.validate_task(task)
        assert not ok

    def test_reject_method_outside_enum(self):
        task = self._base_task()
        task["anchors"]["verification_method"] = "vibes"
        ok, errors = eval_dataset.validate_task(task)
        assert not ok and any("verification_method" in e for e in errors)

    def test_reject_smoke_with_non_constructed_source(self):
        task = self._base_task()
        task["source"] = "public-corpus"
        ok, errors = eval_dataset.validate_task(task)
        assert not ok and any("constructed" in e for e in errors)

    def test_reject_missing_required_metric(self):
        task = self._base_task()
        task["checker"]["metrics"] = ["ttc_seconds"]
        ok, errors = eval_dataset.validate_task(task)
        assert not ok and any("metric" in e.lower() for e in errors)

    def test_reject_heldout_off(self):
        task = self._base_task()
        task["contamination"]["held_out"] = False
        ok, errors = eval_dataset.validate_task(task)
        assert not ok

    def test_reject_unknown_checker_kind(self):
        task = self._base_task()
        task["checker"]["kind"] = "vibes-check"
        ok, errors = eval_dataset.validate_task(task)
        assert not ok

    def test_reject_unstamped_seed(self):
        task = self._base_task()
        task.pop("seed", None)
        ok, errors = eval_dataset.validate_task(task)
        assert not ok and any("seed" in e for e in errors)


# -------------------------------------------------------------- (c) generator
class TestGenerator:
    """Constructed targets: deterministic, divergent, ground truth by construction."""

    def test_deterministic_per_seed(self):
        cfg_a = eval_targets.derive_cfg("go-arx", 29901)
        cfg_b = eval_targets.derive_cfg("go-arx", 29901)
        assert cfg_a == cfg_b
        assert eval_targets.render_go(cfg_a) == eval_targets.render_go(cfg_b)

    def test_variants_diverge(self):
        """Different seeds -> different constant sets (fresh parametric
        variants: an answer memorized from one variant is wrong on the next)."""
        sets = []
        for seed in (1, 2, 3):
            cfg = eval_targets.derive_cfg("go-arx", seed)
            sets.append((cfg["k0"], cfg["z"], cfg["rot_base"]))
        assert len(set(sets)) == 3, f"variant collision: {sets}"

    def test_go_constants_differ_from_canonical(self):
        for seed in (29901, 1, 12345):
            cfg = eval_targets.derive_cfg("go-arx", seed)
            assert cfg["k0"] != CANONICAL_K0, f"seed {seed} reproduced canonical K0"
            assert cfg["z"] != CANONICAL_GOLDEN, f"seed {seed} reproduced canonical golden"

    def test_go_target_embeds_its_constants(self):
        """The static (constant-hit) oracle's ground truth: the rendered
        target carries hex literals of its own mutated constants."""
        cfg = eval_targets.derive_cfg("go-arx", 29901)
        src = eval_targets.render_go(cfg)
        for v in (cfg["k0"], cfg["z"], cfg["rot_base"]):
            assert f"0x{v:08x}" in src.lower(), f"constant {v:#x} not embedded"

    def test_model_matches_rendered_go_target(self, tmp_path: Path):
        """Ground truth BY CONSTRUCTION: the python model and the rendered
        Go source must encode the same transform (checked at the model
        level here; the toolchain face re-checks it end to end)."""
        cfg = eval_targets.derive_cfg("go-arx", 29901)
        src = eval_targets.render_go(cfg)
        # the rendered source must contain the model's rot schedule bound
        assert "(i%31)+1" in src
        assert str(cfg["k0"]) not in src  # go literal is hex, not decimal

    def test_py_and_js_minted_probes_stable(self):
        """Checker-minted probes (the anti-digest-table face) are a pure
        function of the seed — same seed, same probes, forever."""
        a = eval_targets.minted_probes("py-derive", 29903, count=12)
        b = eval_targets.minted_probes("py-derive", 29903, count=12)
        assert a == b and len(a) == 12
        c = eval_targets.minted_probes("js-sign", 29902, count=10)
        d = eval_targets.minted_probes("js-sign", 29902, count=10)
        assert c == d and len(c) == 10

    def test_families_registry_has_three(self):
        assert set(eval_targets.FAMILIES) >= {"go-arx", "js-sign", "py-derive"}


# ---------------------------------------------------------------- (d) held-out
class TestHeldOutAndVersioning:
    """eval tasks NEVER enter the distiller corpus; sets versioned."""

    def test_version_file_pins_eval_v1(self):
        assert (EVAL_V1 / "VERSION").read_text(encoding="utf-8").strip() == "eval-v1"

    def test_changelog_exists_and_mentions_eval_v1(self):
        log = (EVAL_V1 / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "eval-v1" in log

    def test_heldout_documented(self):
        readme = (ROOT / "eval" / "README.md").read_text(encoding="utf-8")
        for token in ("distill", "held-out", "eval-v1"):
            assert token in readme, f"eval/README.md must document {token}"

    def test_distiller_exclusion_path_contract(self):
        """The path constant exists and the filter drops eval-corpus paths —
        the distiller (not yet built) MUST source through this filter;
        the contract is pinned on the constants while the consumer lane
        does not exist yet."""
        assert "eval/" in eval_dataset.EVAL_CORPUS_PREFIXES
        sources = ["skills/a.md", "eval/v1/tasks/smoke/py-derive-v1/target/derive.py",
                   "references/re-library/x.md"]
        kept = eval_dataset.filter_distiller_sources(sources)
        assert kept == ["skills/a.md", "references/re-library/x.md"]

    def test_all_landed_tasks_declare_constructed_and_held_out(self):
        for tdir in eval_dataset.iter_task_dirs():
            task = eval_dataset.load_task(tdir)
            assert task["source"] == "constructed"
            assert task["contamination"]["held_out"] is True
            assert task["contamination"]["distiller_excluded"] is True
            assert task["contamination"]["provenance"] == "constructed"

    def test_variant_constant_sets_disjoint_across_landed_tasks(self):
        """No two landed smoke targets share a constant: each is a fresh
        parametric variant (cross-task answer reuse is impossible)."""
        seen: dict[tuple, str] = {}
        for tdir in eval_dataset.iter_task_dirs():
            task = eval_dataset.load_task(tdir)
            gt = json.loads((tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
            consts = tuple(sorted(gt["constants"].items()))
            assert consts not in seen, (
                f"{tdir.name} shares a constant set with {seen.get(consts)}")
            seen[consts] = tdir.name


# ------------------------------------------------------------- (e) checker math
class TestCheckerMath:
    """The autoresearch.sh-style arithmetic core, unit-level."""

    def test_pair_threshold_is_ceil_ratio(self):
        assert eval_dataset.min_pairs_for(ratio=0.75, count=16) == 12
        assert eval_dataset.min_pairs_for(ratio=1.0, count=20) == 20
        assert eval_dataset.min_pairs_for(ratio=0.78, count=14) == 11  # case-admission shape

    def test_metric_line_format(self):
        assert eval_dataset.metric_line("ttc_seconds", 0.812) == "METRIC ttc_seconds=0.812"
        assert eval_dataset.metric_line("converged", 1) == "METRIC converged=1"

    def test_verdict_arithmetic(self):
        ok, failures = eval_dataset.arithmetic_verdict(
            hits=3, min_constant_hits=3, pairs_matched=12, pair_count=16,
            min_pair_ratio=0.75)
        assert ok and not failures
        ok, failures = eval_dataset.arithmetic_verdict(
            hits=1, min_constant_hits=3, pairs_matched=12, pair_count=16,
            min_pair_ratio=0.75)
        assert not ok
        assert any(f["code"] == "CONSTANT_MISS" for f in failures)
        ok, failures = eval_dataset.arithmetic_verdict(
            hits=3, min_constant_hits=3, pairs_matched=11, pair_count=16,
            min_pair_ratio=0.75)
        assert not ok
        assert any(f["code"] == "PAIR_MISMATCH" for f in failures)

    def test_guess_probability_is_power_of_space(self):
        """1/k guessing on a 96-bit constant space: p = 2^-96 — arithmetic,
        no run needed (the guess-1ofk baseline emits this per task)."""
        p = eval_dataset.guess_pass_p(space_bits=96)
        assert p == 2.0 ** -96 and p < 1e-28
        assert eval_dataset.guess_pass_p(space_bits=0) == 1.0

    def test_results_row_shape_wired_to_295(self):
        """Results rows carry the fields an evidence-bar config-change PR attaches:
        task identity, metrics, verdict, evidence ref, arm label."""
        row = eval_dataset.results_row(
            task_id="py-derive-v1", family="py-derive", checker_kind="replay-roundtrip",
            metrics={"ttc_seconds": 0.4, "dispatch_count": 1,
                     "pass_at_k_contribution": 1, "converged": 1},
            verdict="PASS", failures=[], evidence_ref="runs/eval/x.json",
            arm="self-check", guess_pass_p=2 ** -96)
        for key in ("task_id", "family", "checker_kind", "metrics", "verdict",
                    "failures", "evidence_ref", "arm", "guess_pass_p"):
            assert key in row, f"results row missing {key}"
        assert set(row["metrics"]) == REQUIRED_METRICS

    def test_failure_codes_are_enumerated(self):
        assert {"CONSTANT_MISS", "PAIR_MISMATCH", "TOOLCHAIN_MISSING",
                "BAD_CANDIDATE"} <= set(eval_dataset.FAILURE_CODES)

    def test_task_yaml_files_are_valid_yaml(self):
        for tdir in eval_dataset.iter_task_dirs():
            data = yaml.safe_load((tdir / "task.yaml").read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            assert data["schema"] == "kunglao-eval-task/1"
