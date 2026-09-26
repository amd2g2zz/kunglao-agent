# -*- coding: utf-8 -*-
"""tests/test_eval_smoke_299.py — smoke tier end to end (checker + runner).

Toolchain faces run the REAL mechanical oracles through subprocesses:
the py face always runs (python is the runtime), the js and go faces
self-skip when node/go are absent (CI may lack them — the tier degrades
to SKIP signals, never false FAILs).

Pins the autoresearch.sh pattern end to end:
  - METRIC <name>=<value> lines on stdout,
  - arithmetic verdict (VERDICT PASS/FAIL/SKIP, exit code contract),
  - evidence auto-archive (runs/eval/<task_id>/...),
  - structured failure signals (FAILURE code=... detail=...),
  - mutation-can-redden: a deliberately-wrong candidate FAILS,
  - anti-digest-table: hardcoding the published pairs FAILS on the
    checker-minted probes,
  - the tier runner aggregates evidence-bar-shaped results rows and finishes in
    minutes (wall ceiling asserted at 300s; the real thing runs in ~10s).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHECKER = SCRIPTS / "eval_checker.py"
RUNNER = SCRIPTS / "eval_smoke_runner.py"
TASKS = ROOT / "eval" / "v1" / "tasks" / "smoke"

GO_AVAILABLE = shutil.which("go") is not None
NODE_AVAILABLE = shutil.which("node") is not None


def _checker(task: str, candidate: Path, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CHECKER), "--task", task, "--candidate", str(candidate),
         "--out", str(out)],
        capture_output=True, text=True, timeout=240, cwd=str(ROOT))


def _runner(out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), "--out", str(out), *extra],
        capture_output=True, text=True, timeout=300, cwd=str(ROOT))


def _task_dir(task_id: str) -> Path:
    hits = sorted(TASKS.glob(f"*/{task_id}")) or sorted(TASKS.glob(task_id))
    assert hits, f"task dir not found for {task_id}"
    return hits[0]


# ------------------------------------------------------------------ py face
class TestPyDeriveFace:
    TASK = "py-derive-v1"

    def _target(self) -> Path:
        return _task_dir(self.TASK) / "target" / "derive.py"

    def test_self_check_passes_with_metric_lines_and_evidence(self, tmp_path: Path):
        proc = _checker(self.TASK, self._target(), tmp_path)
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert "VERDICT PASS" in proc.stdout
        for name in ("ttc_seconds", "dispatch_count", "pass_at_k_contribution", "converged"):
            assert f"METRIC {name}=" in proc.stdout, f"missing METRIC {name}"
        evidence = list(Path(tmp_path).rglob("evidence-*.json"))
        assert evidence, "evidence JSON not archived"
        doc = json.loads(evidence[0].read_text(encoding="utf-8"))
        assert doc["schema"] == "kunglao-eval-evidence/1"
        assert doc["verdict"] == "PASS"
        assert doc["task_id"] == self.TASK

    def test_mutated_candidate_reddens(self, tmp_path: Path):
        """Mutation-can-redden: one flipped constant in the target must
        turn the oracle red — a checker that greens anything is a stamp."""
        src = self._target().read_text(encoding="utf-8")
        marker = "OFFSET = "
        i = src.index(marker)
        j = src.index("\n", i)
        old = int(src[i + len(marker):j], 16)
        mutated = src[:i] + marker + hex((old ^ 0x1) & ((1 << 64) - 1)) + src[j:]
        assert mutated != src
        cand = tmp_path / "derive.py"
        cand.write_text(mutated, encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, f"mutated candidate must FAIL: {proc.stdout}"
        assert "VERDICT FAIL" in proc.stdout
        assert "FAILURE code=" in proc.stdout

    def test_digest_table_candidate_fails_on_minted_probes(self, tmp_path: Path):
        """Anti-memorization: a candidate hardcoding the PUBLISHED pairs
        passes those but fails the checker-minted probes (replay oracle
        defeats digest-table copying by construction)."""
        gt = json.loads(
            (_task_dir(self.TASK) / "ground_truth.json").read_text(encoding="utf-8"))
        table = {tuple(p["input"]): p["out"] for p in gt["published_pairs"]}
        cand = tmp_path / "derive.py"
        cand.write_text(
            "def derive(data):\n"
            f"    return {table!r}[tuple(data)]\n",
            encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "digest-table candidate must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_bad_candidate_path_is_structured_refusal(self, tmp_path: Path):
        proc = _checker(self.TASK, tmp_path / "nope.py", tmp_path / "out")
        assert proc.returncode == 2
        assert "BAD_CANDIDATE" in proc.stdout


# ------------------------------------------------------------------ js face
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestJsSignFace:
    TASK = "js-sign-v1"

    def test_self_check_passes(self, tmp_path: Path):
        target = _task_dir(self.TASK) / "target" / "sign_bundle.js"
        proc = _checker(self.TASK, target, tmp_path)
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert "VERDICT PASS" in proc.stdout

    def test_mutated_candidate_reddens(self, tmp_path: Path):
        target = _task_dir(self.TASK) / "target" / "sign_bundle.js"
        src = target.read_text(encoding="utf-8")
        i = src.index("var C1 = ")
        j = src.index(";", i)
        old = int(src[i + len("var C1 = "):j], 16)
        mutated = src[:i] + "var C1 = " + hex((old ^ 0x10) & 0xFFFFFFFF) + src[j:]
        cand = tmp_path / "sign_bundle.js"
        cand.write_text(mutated, encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1
        assert "VERDICT FAIL" in proc.stdout


# ------------------------------------------------------------------ go face
@pytest.mark.skipif(not GO_AVAILABLE, reason="go toolchain not available")
class TestGoArxFace:
    TASK = "go-arx-v1"

    def test_self_check_passes_constant_hit_and_pair_match(self, tmp_path: Path):
        target = _task_dir(self.TASK) / "target" / "sample_kdf.go"
        proc = _checker(self.TASK, target, tmp_path)
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert "VERDICT PASS" in proc.stdout
        assert "METRIC pass_at_k_contribution=1" in proc.stdout

    def test_stock_sha1_constants_score_zero_hits(self, tmp_path: Path):
        """Memorization is useless: a re-implementation carrying the
        CANONICAL SHA-1 constants fails the static face."""
        target = _task_dir(self.TASK) / "target" / "sample_kdf.go"
        src = target.read_text(encoding="utf-8")
        # swap the first embedded constant (k0, the const block's head)
        # for the canonical SHA-1 round constant the family is known by
        mutated = re.sub(r"uint32 = 0x[0-9a-fA-F]+",
                         "uint32 = 0x5A827999", src, count=1)
        assert mutated != src
        cand = tmp_path / "sample_kdf.go"
        cand.write_text(mutated, encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "stock-constant candidate must FAIL"
        assert "CONSTANT_MISS" in proc.stdout

    def test_mutated_pipeline_fails_pair_match(self, tmp_path: Path):
        """Right constants, wrong ARX pipeline: static face greens, replay
        face reddens — the pair-match oracle is the reproduction anchor."""
        target = _task_dir(self.TASK) / "target" / "sample_kdf.go"
        src = target.read_text(encoding="utf-8")
        mutated = src.replace("^ k0", "+ k0")  # xor -> add: same constants, wrong algo
        assert mutated != src
        cand = tmp_path / "sample_kdf.go"
        cand.write_text(mutated, encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1
        assert "PAIR_MISMATCH" in proc.stdout

    def test_digest_table_candidate_fails_on_minted_probes(self, tmp_path: Path):
        """The reviewer-cheat regression: real constants + the 16 published
        pairs as a literal table, ZERO derivation — passes the published
        face, fails the checker-minted stdin probes (inputs stored nowhere,
        recomputed from the seed model). Must never reach VERDICT PASS."""
        gt = json.loads(
            (_task_dir(self.TASK) / "ground_truth.json").read_text(encoding="utf-8"))
        c = gt["constants"]
        entries = ",\n".join(
            f'{p["input"][0]}: {p["out"]}' for p in gt["published_pairs"])
        cheat = f'''package main

import (
\t"bufio"
\t"encoding/json"
\t"fmt"
\t"os"
)

const (
\tk0      uint32 = 0x{c["k0"]:08x}
\tz       uint32 = 0x{c["z"]:08x}
\trotBase uint32 = 0x{c["rot_base"]:08x}
)

var table = map[uint32]uint32{{
{entries},
}}

func main() {{
\tsc := bufio.NewScanner(os.Stdin)
\tw := bufio.NewWriter(os.Stdout)
\tdefer w.Flush()
\tfor sc.Scan() {{
\t\tvar req struct {{
\t\t\tI  int    `json:"i"`
\t\t\tIn uint32 `json:"in"`
\t\t}}
\t\tif err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
\t\t\tcontinue
\t\t}}
\t\tout := table[req.In] // digest lookup, no derivation
\t\tfmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": %d}}\\n", req.I, req.In, out)
\t}}
}}
'''
        cand = tmp_path / "cheat_kdf.go"
        cand.write_text(cheat, encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "constants+table cheat must FAIL"
        assert "VERDICT FAIL" in proc.stdout
        assert "PAIR_MISMATCH" in proc.stdout


# ------------------------------------------------------------------- runner
class TestSmokeRunner:
    def test_py_only_run_is_minutes_scale_and_295_shaped(self, tmp_path: Path):
        started = time.time()
        proc = _runner(tmp_path, "--tasks", "py-derive-v1")
        wall = time.time() - started
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert wall < 300, f"single-task run took {wall:.1f}s — tier must be minutes-scale"
        assert "VERDICT PASS" in proc.stdout
        results = list(Path(tmp_path).rglob("eval-results-*.json"))
        assert results, "results JSON not written"
        doc = json.loads(results[0].read_text(encoding="utf-8"))
        assert doc["schema"] == "kunglao-eval-results/1"
        assert doc["eval_version"] == "eval-v1"
        assert doc["tier"] == "smoke"
        assert doc["arm"] == "self-check"
        row = doc["rows"][0]
        assert row["task_id"] == "py-derive-v1"
        assert set(row["metrics"]) == {
            "ttc_seconds", "dispatch_count", "pass_at_k_contribution", "converged"}
        assert doc["summary"]["pass"] >= 1

    def test_baselines_append_guess_rows(self, tmp_path: Path):
        proc = _runner(tmp_path, "--tasks", "py-derive-v1", "--baselines")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        results = list(Path(tmp_path).rglob("eval-results-*.json"))
        doc = json.loads(results[0].read_text(encoding="utf-8"))
        arms = {r["arm"] for r in doc["rows"]}
        assert "guess-1ofk" in arms
        guess_row = next(r for r in doc["rows"] if r["arm"] == "guess-1ofk")
        assert guess_row["guess_pass_p"] < 1e-28  # 2^-space_bits arithmetic
        assert guess_row["verdict"] in ("EXPECTED-FAIL",)

    def test_full_smoke_tier_completes(self, tmp_path: Path):
        """The release-train gate face: the whole smoke tier runs in one
        invocation; every task lands PASS or a structured SKIP (toolchain
        absent), never a silent hole."""
        started = time.time()
        proc = _runner(tmp_path)
        wall = time.time() - started
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert wall < 300, f"smoke tier took {wall:.1f}s — must stay minutes-scale"
        results = list(Path(tmp_path).rglob("eval-results-*.json"))
        doc = json.loads(results[0].read_text(encoding="utf-8"))
        task_ids = {r["task_id"] for r in doc["rows"] if r["arm"] == "self-check"}
        landed = {d.name for d in TASKS.iterdir() if d.is_dir()}
        assert task_ids == landed, f"tier coverage hole: {landed - task_ids}"
        for row in doc["rows"]:
            if row["arm"] != "self-check":
                continue
            assert row["verdict"] in ("PASS", "FAIL", "SKIP"), row
            assert row["evidence_ref"], "evidence bar: every row archives evidence"

    def test_unknown_task_is_refusal(self, tmp_path: Path):
        proc = _runner(tmp_path, "--tasks", "no-such-task")
        assert proc.returncode == 2

    def test_skip_never_reads_as_clean_pass(self, tmp_path: Path):
        """FIX (tier-gate skip semantics): with skip>0 the final verdict
        token must be PARTIAL, rc stays 0 (a SKIP is legal), and the
        summary carries the skip reasons — no consumer can mistake a
        skipped task for an executed one."""
        proc = _runner(tmp_path, "--arm", "bare-llm")  # no candidates -> all SKIP
        assert proc.returncode == 0
        assert "VERDICT PARTIAL" in proc.stdout
        assert "VERDICT PASS" not in proc.stdout
        results = list(Path(tmp_path).rglob("eval-results-*.json"))
        doc = json.loads(results[0].read_text(encoding="utf-8"))
        assert doc["summary"]["skip"] == 3
        reasons = doc["summary"]["skips"]
        assert len(reasons) == 3
        assert all(r["reason"] for r in reasons)

    def test_failure_detail_with_spaces_survives_aggregation(self):
        """FIX (row fidelity): FAILURE detail is split on the detail=
        marker only — the aggregated row must carry the full detail text,
        not the first word."""
        import eval_smoke_runner as rnr
        parsed = rnr._parse_output(
            "FAILURE code=PAIR_MISMATCH detail=pairs 16/26 match "
            "(threshold 20 at ratio 0.75)\nVERDICT FAIL\n")
        assert parsed["failures"][0]["code"] == "PAIR_MISMATCH"
        assert parsed["failures"][0]["detail"] == \
            "pairs 16/26 match (threshold 20 at ratio 0.75)"
