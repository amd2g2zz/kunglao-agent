# -*- coding: utf-8 -*-
"""tests/test_eval_control_arm_236.py — bare-LLM control arm + A/B face (#236).

The capture-refusal incident class needs a CONTROL: what does a bare LLM
(prompt-only: goal_verbatim + success_criterion + the task's input
surface, no claim economy / gates / oracle machinery) score on the same
mechanical oracles the framework arm is graded by? Faces pinned here:

  (a) DEFINITIONS — premature-closure and false-PROVEN as pure functions
      (the two rates the incident class feeds): a claimed-converged task
      whose checker later FAILs on re-run or minted probes is a premature
      closure; a checker PASS on a candidate that fails the minted-probe
      subset is a false PROVEN. Rates are guarded (0.0 on empty
      denominators — never ZeroDivisionError, never invented mass);
  (b) LEAKAGE — the bare prompt carries anchors + candidate contract +
      the observable target source ONLY: no ground-truth answers,
      no thresholds/oracles/checker vocabulary (the target's own
      constants are legitimately visible input — the framework arm sees
      them too — but published-pair OUTPUTS must never appear);
  (c) DRIVER — manifest-driven orchestration end to end through the REAL
      #299 checker/runner subprocesses (stub executor stands in for the
      model call; the model-call face itself is the bench convention
      `claude -p` and is never invoked from tests);
  (d) REGRADE — minted-only probe grade reuses the checker's replay
      machinery (published pairs stripped): the anti-digest-table probe
      set alone decides false-PROVEN;
  (e) A/B — one command runs both arms, emits per-arm kunglao-eval-
      results/1 docs plus a kunglao-eval-ab/1 comparison summary with the
      five metrics per arm and a stdout table (#295 evidence-bar shape).

Integration tier: real checker subprocesses (py face always runs; go/js
self-skip when toolchains are absent — the 299 degradation contract).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TASKS = ROOT / "eval" / "v1" / "tasks" / "smoke"

import eval_control_arm as ca
import eval_dataset as ds


def _task_dir(task_id: str) -> Path:
    hits = sorted(TASKS.glob(f"*/{task_id}")) or sorted(TASKS.glob(task_id))
    assert hits, f"task dir not found for {task_id}"
    return hits[0]


def _target_text(tdir: Path) -> str:
    task = ds.load_task(tdir)
    return (tdir / task["workspace_scaffold"]["entry"]).read_text(encoding="utf-8")


def _stub_executor(text: str):
    """Executor seam: stands in for the `claude -p` model call."""

    def _exec(prompt: str, timeout_s: float = ca.DEFAULT_TIMEOUT_S):
        return {"text": text, "returncode": 0, "wall_s": 0.01,
                "tokens_in": 11, "tokens_out": 22, "timed_out": False,
                "stderr": ""}

    return _exec


PY = "py-derive-v1"


# ---------------------------------------------------------------- (a) rates
class TestMetricDefinitions:
    def test_answer_rate_and_guards(self):
        assert ca.answer_rate(1, 2) == 0.5
        assert ca.answer_rate(3, 3) == 1.0
        assert ca.answer_rate(0, 0) == 0.0, "empty tier: rate 0.0, no crash"

    def test_proven_with_evidence_rate(self):
        assert ca.proven_with_evidence_rate(2, 4) == 0.5
        assert ca.proven_with_evidence_rate(0, 0) == 0.0

    def test_is_false_proven(self):
        # checker PASS on a candidate that fails the minted-probe subset
        assert ca.is_false_proven("PASS", (10, 12)) is True
        assert ca.is_false_proven("PASS", (12, 12)) is False
        assert ca.is_false_proven("FAIL", (0, 12)) is False
        # ungradeable (toolchain absent) can never be accused
        assert ca.is_false_proven("PASS", None) is False

    def test_false_proven_rate_denominator_is_proven_mass(self):
        assert ca.false_proven_rate(1, 4) == 0.25
        assert ca.false_proven_rate(0, 0) == 0.0, "no PASS rows: rate 0.0"

    def test_is_premature_closure(self):
        # claimed-converged, later falsified on re-run
        assert ca.is_premature_closure(True, "FAIL", (12, 12)) is True
        assert ca.is_premature_closure(True, "REFUSED", None) is True
        # claimed-converged, falsified on minted probes only
        assert ca.is_premature_closure(True, "PASS", (11, 12)) is True
        # claimed and verified: not premature
        assert ca.is_premature_closure(True, "PASS", (12, 12)) is False
        assert ca.is_premature_closure(True, "PASS", None) is False
        # never claimed: a later FAIL is just a FAIL, not a closure
        assert ca.is_premature_closure(False, "FAIL", (0, 12)) is False

    def test_premature_closure_rate_denominator_is_claimed_mass(self):
        assert ca.premature_closure_rate(1, 2) == 0.5
        assert ca.premature_closure_rate(0, 0) == 0.0, "no claims: rate 0.0"

    def test_arm_metrics_five_keys(self):
        tdir = _task_dir(PY)
        doc = {"arm": "bare-llm", "rows": [ds.results_row(
            task_id=PY, family="py-derive", checker_kind="replay-roundtrip",
            metrics={"ttc_seconds": 0.5, "converged": 1},
            verdict="PASS", failures=[], evidence_ref="ev.json",
            arm="bare-llm")]}
        m = ca.arm_metrics(doc, {PY: "PASS"}, {PY: (12, 12)}, wall_s=1.5)
        for key in ("tasks", "answer_rate", "proven_with_evidence_rate",
                    "premature_closure_rate", "false_proven_rate", "budget"):
            assert key in m, f"five-metric block missing {key}"
        assert m["answer_rate"] == 1.0
        assert m["proven_with_evidence_rate"] == 1.0
        assert m["premature_closure_rate"] == 0.0
        assert m["false_proven_rate"] == 0.0
        assert m["budget"]["wall_s"] == 1.5
        assert m["budget"]["ttc_seconds_sum"] == 0.5

    def test_arm_metrics_skip_is_not_an_answer(self):
        doc = {"arm": "bare-llm", "rows": [ds.results_row(
            task_id=PY, family="py-derive", checker_kind="replay-roundtrip",
            metrics={}, verdict="SKIP",
            failures=[{"code": "BAD_CANDIDATE", "detail": "no candidate"}],
            evidence_ref="", arm="bare-llm")]}
        m = ca.arm_metrics(doc, set(), {})
        assert m["answer_rate"] == 0.0
        assert m["proven_with_evidence_rate"] == 0.0


# -------------------------------------------------------------- (b) prompt
class TestBarePrompt:
    def test_prompt_carries_anchors_contract_and_target(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = ca.build_bare_prompt(tdir, task)
        assert task["anchors"]["goal_verbatim"] in prompt
        assert task["anchors"]["success_criterion"] in prompt
        assert task["workspace_scaffold"]["candidate_contract"] in prompt
        assert _target_text(tdir) in prompt, "the observable input surface"

    def test_prompt_leakage_guard(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        gt = json.loads((tdir / "ground_truth.json").read_text(encoding="utf-8"))
        prompt = ca.build_bare_prompt(tdir, task)
        # the owner-authored anchors are the GOAL statement — words inside
        # them (e.g. "checker-minted" in a success criterion) are not
        # machinery leakage; everything the DRIVER adds is under guard
        driver_prose = prompt
        for anchor_text in (task["anchors"]["goal_verbatim"],
                            task["anchors"]["success_criterion"],
                            task["workspace_scaffold"]["candidate_contract"]):
            driver_prose = driver_prose.replace(anchor_text, "")
        for banned in ("ground_truth", "minted", "min_pair", "threshold",
                       "published_pairs", "oracles", "checker"):
            assert banned not in driver_prose.lower(), \
                f"oracle machinery leaked: {banned}"
        for pair in gt["published_pairs"]:
            assert str(pair["out"]) not in prompt, "published OUTPUT leaked"

    def test_prompt_names_every_task_family(self):
        for task_id in ("go-arx-v1", "js-sign-v1", PY):
            tdir = _task_dir(task_id)
            prompt = ca.build_bare_prompt(tdir, ds.load_task(tdir))
            assert prompt.strip(), task_id


# --------------------------------------------------------- (c) extraction
class TestExtractCandidate:
    def test_strips_code_fences(self):
        text = "Here you go:\n```python\nprint(1)\n```\ndone"
        assert ca.extract_candidate(text) == "print(1)\n" or \
            ca.extract_candidate(text) == "print(1)"

    def test_empty_response_is_a_refusal(self):
        with pytest.raises(ValueError):
            ca.extract_candidate("   \n  ")
        with pytest.raises(ValueError):
            ca.extract_candidate("```python\n```")


# ------------------------------------------------------------ (d) manifest
class TestCandidatesManifest:
    def test_text_and_path_candidates(self, tmp_path: Path):
        side = tmp_path / "cand.py"
        side.write_text("x = 1", encoding="utf-8")
        man = tmp_path / "m.json"
        man.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "bare-llm",
            "candidates": {PY: {"text": "y = 2"},
                           "js-sign-v1": {"path": str(side)}}}), encoding="utf-8")
        known = {PY, "js-sign-v1"}
        cands = ca.load_manifest(man, known)
        assert cands[PY] == "y = 2"
        assert cands["js-sign-v1"] == side

    def test_bad_schema_refused(self, tmp_path: Path):
        man = tmp_path / "m.json"
        man.write_text(json.dumps({"schema": "nope", "candidates": {}}),
                       encoding="utf-8")
        with pytest.raises(ValueError):
            ca.load_manifest(man, {PY})

    def test_unknown_task_refused(self, tmp_path: Path):
        man = tmp_path / "m.json"
        man.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "bare-llm",
            "candidates": {"no-such": {"text": "z"}}}), encoding="utf-8")
        with pytest.raises(ValueError):
            ca.load_manifest(man, {PY})


# -------------------------------------------------- (e) minted-only regrade
class TestMintedRegrade:
    def test_real_target_passes_minted_subset(self, tmp_path: Path):
        tdir = _task_dir(PY)
        gt = json.loads((tdir / "ground_truth.json").read_text(encoding="utf-8"))
        grade = ca.minted_only_grade("py-derive", tdir, gt,
                                    tdir / "target/derive.py", tmp_path)
        assert grade is not None
        matched, total = grade
        assert total == gt["minted_probe_count"] > 0
        assert matched == total, "the constructed target must green its probes"

    def test_mutated_candidate_fails_minted_subset(self, tmp_path: Path):
        tdir = _task_dir(PY)
        gt = json.loads((tdir / "ground_truth.json").read_text(encoding="utf-8"))
        bad = tmp_path / "bad.py"
        # mutate a LOW bit of FOLD: the multiply is masked with & 2^64-1,
        # so a high-bit insert (0x1_00ff...) would be an arithmetic no-op
        bad.write_text(_target_text(tdir).replace("f3e2a8a3", "f3e2a8a2"),
                       encoding="utf-8")
        grade = ca.minted_only_grade("py-derive", tdir, gt, bad, tmp_path)
        assert grade is not None and grade[0] < grade[1]


# ------------------------------------------------------- (f) bare-arm driver
class TestBareArmDriver:
    def test_manifest_run_end_to_end(self, tmp_path: Path):
        tdir = _task_dir(PY)
        man = tmp_path / "bare.json"
        man.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "bare-llm",
            "candidates": {PY: {"text": _target_text(tdir)}}}),
            encoding="utf-8")
        rc, doc, records = ca.run_bare_arm([PY], "smoke", tmp_path / "run",
                                           manifest=man)
        assert rc == 0, "a bare-arm PASS row is a measurement, not a failure"
        assert doc["arm"] == "bare-llm"
        row = doc["rows"][0]
        assert row["verdict"] == "PASS"
        assert row["evidence_ref"], "evidence bar holds for the bare arm"
        cand = Path(records[0]["candidate_path"])
        assert cand.is_file() and cand.suffix == ".py"
        assert records[0]["executor"]["returncode"] == 0

    def test_executor_failure_is_structured_not_silent(self, tmp_path: Path):
        def dead(prompt: str, timeout_s: float = 1.0):
            return {"text": "", "returncode": 1, "wall_s": 0.0,
                    "tokens_in": None, "tokens_out": None,
                    "timed_out": False, "stderr": "boom"}
        rc, doc, records = ca.run_bare_arm([PY], "smoke", tmp_path / "run",
                                           executor=dead)
        assert rc == 0, "an unanswered task is a SKIP row, not a run failure"
        row = doc["rows"][0]
        assert row["verdict"] == "SKIP"
        assert row["failures"][0]["code"] == "BAD_CANDIDATE"

    def test_live_executor_is_the_bench_claude_face(self, monkeypatch):
        """Behavioral pin: the live model-call face is the repo's bench
        convention — the claude CLI in print mode (`claude -p`, as
        bench_runner.py shells it). The subprocess is intercepted; tests
        never invoke the real CLI."""
        seen: dict = {}

        class _FakeProc:
            stdout = "candidate source"
            stderr = ""
            returncode = 0

        def _fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return _FakeProc()

        monkeypatch.setattr(ca.subprocess, "run", _fake_run)
        rec = ca.claude_prompt_executor("solve this")
        assert seen["cmd"][:2] == ["claude", "-p"], seen["cmd"]
        assert "solve this" in seen["cmd"]
        assert rec["text"] == "candidate source"
        assert rec["timed_out"] is False


# --------------------------------------------------------------- (g) A/B
class TestAbFace:
    def test_ab_manifest_dry_run(self, tmp_path: Path):
        tdir = _task_dir(PY)
        target = _target_text(tdir)
        bare = tmp_path / "bare.json"
        bare.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "bare-llm",
            "candidates": {PY: {"text": target}}}), encoding="utf-8")
        fw = tmp_path / "fw.json"
        fw.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "framework",
            "candidates": {PY: {"text": target}}}), encoding="utf-8")
        rc, cmp_doc = ca.run_ab([PY], "smoke", tmp_path / "ab",
                                bare_manifest=bare, framework_manifest=fw,
                                baselines=True)
        assert rc == 0
        assert cmp_doc["schema"] == "kunglao-eval-ab/1"
        for arm in ("framework", "bare-llm"):
            inner = cmp_doc["results"][arm]
            assert inner["schema"] == ds.RESULTS_SCHEMA
            assert inner["arm"] == arm
            m = cmp_doc["arms"][arm]
            assert m["answer_rate"] == 1.0
            assert m["proven_with_evidence_rate"] == 1.0
        arms = {r["arm"] for arm_doc in cmp_doc["results"].values()
                for r in arm_doc["rows"]}
        assert "guess-1ofk" in arms, "the 1/k floor travels with the A/B"

    def test_ab_cli_one_command(self, tmp_path: Path):
        tdir = _task_dir(PY)
        bare = tmp_path / "bare.json"
        bare.write_text(json.dumps({
            "schema": ca.SCHEMA_CANDIDATES, "arm": "bare-llm",
            "candidates": {PY: {"text": _target_text(tdir)}}}),
            encoding="utf-8")
        rc = ca.main(["--ab", "--manifest", str(bare),
                      "--tasks", PY, "--out", str(tmp_path / "cli")])
        assert rc == 0
        docs = list((tmp_path / "cli").glob("ab-compare-*.json"))
        assert docs, "comparison doc not written"

    def test_ab_without_bare_candidates_still_structured(self, tmp_path: Path):
        rc, cmp_doc = ca.run_ab([PY], "smoke", tmp_path / "ab")
        assert rc == 0
        assert cmp_doc["arms"]["bare-llm"]["answer_rate"] == 0.0
        assert cmp_doc["arms"]["bare-llm"]["tasks"] == 1


# ------------------------------------------- (f) native-tier runnability
# The v0.1.6 bare-arm campaign ran the driver across the release tier and
# found three pre-native-ladder gaps: the candidate suffix map keyed by
# TARGET language (KeyError on every native family), a prompt face that
# UnicodeDecodeErrors on binary targets, and a response-language face
# that named the target language ("c/arm64") where the checker grades a
# .py candidate. These pins keep all three honest.

class TestCandidateSuffixParity:
    def _tier_families(self, tier: str) -> dict:
        return {ds.load_task(d)["family"]: d
                for d in ds.iter_task_dirs(tier=tier)}

    def test_tier_families_mapped_and_checker_accepted(self, tmp_path):
        """_cand_suffix mirrors eval_checker._validate_candidate exactly:
        for EVERY tier's families, the mapped suffix is one the checker
        itself accepts (drift between the two maps = failure). Both now
        consume the single-source contract (issue 352), TF families
        included (issue 356 union)."""
        import eval_checker as chk

        for tier in ds.TIERS:
            families = self._tier_families(tier)
            assert families, f"{tier} tier has no families"
            for family, tdir in sorted(families.items()):
                suffix = ca._cand_suffix(ds.load_task(tdir))
                cand = tmp_path / f"{tier}-{family}-probe{suffix}"
                cand.write_text("# probe\n", encoding="utf-8")
                chk._validate_candidate(cand, family)  # raises on drift

    def test_native_families_grade_python_candidates(self):
        for family in ("arm-native-kdf", "win-pe-kdf", "smc-x86",
                       "mod-crypto-native"):
            assert ca.CAND_SUFFIX[family] == ".py"

    def test_response_language_matches_candidate_contract(self):
        """The prompt's response-language face follows the candidate
        artifact the checker grades, never the target's implementation
        language (native units ship c/arm64 targets, grade .py)."""
        release = {d.name: d for d in ds.iter_task_dirs(tier="release")}
        for tid in ("arm-kdf-l0", "win-kdf-l0"):  # native: python out
            prompt = ca.build_bare_prompt(release[tid], ds.load_task(release[tid]))
            assert "complete Python source file" in prompt
        for tid in ("web-pack-sign-l0-v1", "req-sign-l1a-v1"):  # js out
            prompt = ca.build_bare_prompt(release[tid], ds.load_task(release[tid]))
            assert "complete JavaScript source file" in prompt


class TestBinarySurfaceFace:
    def test_build_bare_prompt_survives_binary_entry(self):
        """arm-kdf-l0's scaffold entry is an ELF .so: the prompt face must
        render it (not UnicodeDecodeError) and disclose the rendering."""
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name == "arm-kdf-l0")
        task = ds.load_task(tdir)
        assert (tdir / task["workspace_scaffold"]["entry"]).read_bytes()[:4] \
            == b"\x7fELF", "pin expects the binary target"
        prompt = ca.build_bare_prompt(tdir, task)
        assert "text rendering of the binary target" in prompt
        assert "GOAL:" in prompt and "DELIVERABLE:" in prompt

    def test_binary_render_truncation_is_recorded(self, monkeypatch):
        """A cap-busted rendering must carry the truncation marker in the
        text itself — never silent."""
        class _BigProc:
            stdout = "x" * (ca.BINARY_RENDER_CAP + 1000)
            returncode = 0

        monkeypatch.setattr(ca.subprocess, "run",
                            lambda *a, **k: _BigProc())
        out = ca.render_binary_surface(Path("/nonexistent"))
        assert len(out) == ca.BINARY_RENDER_CAP + len(
            f"\n[truncated at {ca.BINARY_RENDER_CAP} chars]")
        assert f"[truncated at {ca.BINARY_RENDER_CAP} chars]" in out

    def test_binary_render_tool_absence_is_disclosed(self, monkeypatch):
        """Hosts without binutils (CI runners) must get an honest
        disclosure in the text — the prompt stays gradeable, no crash."""
        def _no_tool(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(ca.subprocess, "run", _no_tool)
        out = ca.render_binary_surface(Path("/nonexistent"))
        assert "[objdump unavailable on this host]" in out
        assert "[strings unavailable on this host]" in out
