# -*- coding: utf-8 -*-
"""Issue #952 containment + topology faces — tests.

Behaviour pins for the two repo-side construction defenses on the loop
harness (written against the #334/#888 conventions: tmp-path
workspaces, the session-cmd seam, structured-row assertions):

  FACE A  leak scan   KUNGLAO_GRADING_ROOT set -> the run_loop_task row
          carries leak_scan; a hit lands excluded_from_performance=true
          + an ORACLE_LEAK failure while the checker's verdict stands
          untouched (the marker, not a verdict rewrite, disqualifies
          the row). Unset = the face is OFF entirely (no key, no scan
          I/O).
  FACE B  topology    loop arm + dispatch_count == 0 ->
          topology_compliant=false + a loud stderr note; dispatch_count
          > 0 -> true; cc arms carry no key at all. The flag is the
          contract — consumers decide exclusion, this face never sets
          excluded_from_performance.
  FACE C  sandbox     KUNGLAO_SANDBOX_PROFILE set -> launch_session
          wraps the session argv (sandbox-exec -f <profile> ...);
          unset = argv untouched; a missing sandbox-exec launches
          UNWRAPPED with one loud stderr WARN and
          sandbox_wrap_failed=true (the row marker travels through
          run_loop_task's session block).

Fully hermetic: units are synthesized in tmp_path (the eval corpus is
local-only material, never tracked — the TestWorkspaceReuse888 pattern),
sessions run through the documented test seam, and the fake
sandbox-exec is a tmp-path shell stub on a scoped PATH.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

import eval_loop_runner as lr  # noqa: E402  (pytest pythonpath: scripts)


# ------------------------------------------------------------ helpers ----

UNIT_YAML = """\
schema: kunglao-eval-task/1
task_id: unit-952-containment-pin-v1
eval_version: eval-v1
tier: smoke
source: constructed
family: py-derive
seed: 7
material_class: source-readable
anchors:
  goal_verbatim: "derive the 64-bit mix output for a given seed"
  success_criterion: "checker PASS on the published pair set"
  verification_method: reproduction
workspace_scaffold:
  language: python
  files:
  - target/derive.py
  - toolbox/README.txt
  - probes/stock-behavior.json
  entry: target/derive.py
  candidate_contract: "ONE python module exposing derive(seed) -> hex str"
checker:
  kind: pair-match
  oracles: [pair-match]
  entrypoint: checker.py
  metrics: [ttc_seconds, dispatch_count, pass_at_k_contribution, converged]
  thresholds:
    min_pair_ratio: 1.0
ground_truth:
  file: ground_truth.json
  space_bits: 32
contamination:
  held_out: true
  distiller_excluded: true
  provenance: constructed
"""


def _make_unit(tmp_path: Path) -> Path:
    """The synthesized py-derive unit (the TestWorkspaceReuse888
    pattern): self-contained, no eval corpus on disk required."""
    unit = tmp_path / "unit-952-containment-pin-v1"
    (unit / "target").mkdir(parents=True)
    (unit / "toolbox").mkdir()
    (unit / "probes").mkdir()
    (unit / "target" / "derive.py").write_text(
        "def derive(seed: int) -> str:\n"
        "    return format((seed * 0x9E3779B97F4A7C15)"
        " & ((1 << 64) - 1), '016x')\n",
        encoding="utf-8")
    (unit / "toolbox" / "README.txt").write_text(
        "probes\n", encoding="utf-8")
    (unit / "probes" / "stock-behavior.json").write_text(
        "{}\n", encoding="utf-8")
    (unit / "task.yaml").write_text(UNIT_YAML, encoding="utf-8")
    (unit / "ground_truth.json").write_text(json.dumps({
        "schema": "kunglao-eval-ground-truth/1",
        "task_id": "unit-952-containment-pin-v1",
        "family": "py-derive",
        "seed": 7,
        "eval_version": "eval-v1",
        "space_bits": 32,
        "published_pairs": [],
        "minted_probe_count": 0,
        "constants": {},
    }), encoding="utf-8")
    return unit


def _prepared_workspace(tmp_path: Path, unit: Path,
                        *, armed: bool = True) -> Path:
    """A prepared kunglao workspace on the #888 reuse contract: init +
    PQ spine + preflight (read-only) + optional heartbeat arming."""
    from heartbeat import heartbeat_register, mark_loop_registered
    from rlvr.liveness import append_tick_log

    ws = lr.init_workspace(unit, tmp_path / "workspaces")
    task = lr.ds.load_task(unit)
    lr.seed_question_spine(ws, task)
    ok, reasons = lr.preflight(ws)
    assert ok, reasons
    if armed:
        heartbeat_register(ws)
        mark_loop_registered(ws)
        append_tick_log(ws, "tick", origin="cron")
    return ws


def _stub_launch(workspace, prompt, **kwargs):
    return {"returncode": 0, "wall_s": 1.0, "timed_out": False,
            "session_cost": None}


def _seed_dispatches(ws: Path, count: int = 2) -> None:
    """Dispatch-bearing factor vectors so harvest's dispatch_count face
    reads > 0 (the loop arm's solo-only defect is the zero face)."""
    vec = {"round": 1, "v_norm": 0.5,
           "events": {"dispatch": count, "verify": 1,
                      "confirmed_with_diff": 1, "toss": 0},
           "cost_tokens": 120.0, "cost_rounds": 1, "signals_rows": 3}
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump({"mission": {"history": [vec]}}), encoding="utf-8")


def _plant_leak(ws: Path, grading_root: Path) -> None:
    """The round-1 forgery shape: the cold arm's own F001 cites the
    co-located checker."""
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    (facts / "F001.md").write_text(
        f"the checker lives at {grading_root}/checker.py:23-45 "
        f"and computes the token from {grading_root}/ground_truth\n",
        encoding="utf-8")


def _run(unit: Path, tmp_path: Path, monkeypatch, **kwargs) -> dict:
    """One run_loop_task pass over the reuse contract with the session
    stubbed at the lr.launch_session seam."""
    monkeypatch.setattr(lr, "launch_session", _stub_launch)
    kwargs.setdefault("budget_usd", 1.0)
    kwargs.setdefault("wall_cap_s", 60.0)
    kwargs.setdefault("session_cmd", "stub-seam")  # the seam: never gated
    kwargs.setdefault("workspace", _prepared_workspace(tmp_path, unit))
    return lr.run_loop_task(str(unit), tmp_path, **kwargs)


# ------------------------------------------------- Face A: leak scan ----

class TestLeakScanCore:
    """The reusable scan core: substring contract, cap, normalization."""

    def test_hit_lists_the_planted_file(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        grading_root = tmp_path / "grading"
        _plant_leak(ws, grading_root)
        out = lr.leak_scan(ws, grading_root)
        assert out["hit"] is True
        assert out["root"] == str(grading_root)
        assert out["files"] == ["facts/F001.md"]

    def test_clean_workspace_misses(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        out = lr.leak_scan(ws, tmp_path / "grading")
        assert out == {"hit": False}

    def test_covers_notes_and_scratch(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "notes").mkdir(parents=True)
        (ws / "scratch" / "deep").mkdir(parents=True)
        grading_root = tmp_path / "grading"
        (ws / "notes" / "n1.md").write_text(
            f"see {grading_root}/checker.py\n", encoding="utf-8")
        (ws / "scratch" / "deep" / "s1.txt").write_text(
            f"path {grading_root} inline\n", encoding="utf-8")
        out = lr.leak_scan(ws, grading_root)
        assert out["hit"] is True
        assert out["files"] == ["notes/n1.md", "scratch/deep/s1.txt"]

    def test_oversized_artifacts_are_skipped(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        grading_root = tmp_path / "grading"
        big = ws / "facts" / "big.bin"
        big.write_bytes(
            (b"x" * 100 + str(grading_root).encode("utf-8")
             + b"\n") * (lr.LEAK_SCAN_FILE_CAP_BYTES // 100 + 1))
        assert big.stat().st_size > lr.LEAK_SCAN_FILE_CAP_BYTES
        (ws / "facts" / "small.md").write_text(
            f"leak: {grading_root}\n", encoding="utf-8")
        out = lr.leak_scan(ws, grading_root)
        assert out["hit"] is True
        assert out["files"] == ["facts/small.md"], \
            "the oversized artifact must not be reported (and not crash)"

    def test_root_normalization_trailing_slash(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        grading_root = tmp_path / "grading"
        (ws / "facts" / "F001.md").write_text(
            f"cite {grading_root}/checker.py\n", encoding="utf-8")
        out = lr.leak_scan(ws, f"{grading_root}/")
        assert out["hit"] is True, \
            "a trailing-slash env value must still match the planted " \
            "unterminated path string"

    def test_binary_bytes_never_crash_the_scan(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "notes").mkdir(parents=True)
        (ws / "notes" / "blob.bin").write_bytes(bytes(range(256)) * 8)
        assert lr.leak_scan(ws, tmp_path / "grading") == {"hit": False}


class TestRunLoopTaskLeakScan:
    """Face A end-to-end: the row marker on the reuse contract."""

    def test_hit_marks_row_and_keeps_the_verdict(self, tmp_path,
                                                 monkeypatch):
        grading_root = tmp_path / "grading"
        unit = _make_unit(tmp_path)
        ws = _prepared_workspace(tmp_path, unit)
        _plant_leak(ws, grading_root)
        monkeypatch.setenv(lr.ENV_GRADING_ROOT, str(grading_root))
        row = _run(unit, tmp_path, monkeypatch, workspace=ws)
        assert row["leak_scan"]["hit"] is True
        assert row["leak_scan"]["root"] == str(grading_root)
        assert row["leak_scan"]["files"] == ["facts/F001.md"]
        assert row["excluded_from_performance"] is True
        codes = [f["code"] for f in row["failures"]]
        assert "ORACLE_LEAK" in codes
        assert codes[0] == "BAD_CANDIDATE", \
            "the marker APPENDS a failure; the checker's own face stands"
        # the verdict itself is NOT rewritten — a control run with the
        # face off grades identically on the verdict
        monkeypatch.delenv(lr.ENV_GRADING_ROOT)
        control = lr.run_loop_task(
            str(unit), tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd="stub-seam", workspace=ws)
        assert control["verdict"] == row["verdict"]

    def test_miss_records_hit_false(self, tmp_path, monkeypatch):
        unit = _make_unit(tmp_path)
        ws = _prepared_workspace(tmp_path, unit)
        monkeypatch.setenv(lr.ENV_GRADING_ROOT,
                           str(tmp_path / "elsewhere"))
        row = _run(unit, tmp_path, monkeypatch, workspace=ws)
        assert row["leak_scan"] == {"hit": False}
        assert "ORACLE_LEAK" not in [f["code"] for f in row["failures"]]

    def test_env_unset_is_face_off(self, tmp_path, monkeypatch):
        unit = _make_unit(tmp_path)
        ws = _prepared_workspace(tmp_path, unit)
        monkeypatch.delenv(lr.ENV_GRADING_ROOT, raising=False)

        def _no_scan(*a, **k):
            raise AssertionError("leak_scan ran with the env unset — "
                                 "the face is not off")

        monkeypatch.setattr(lr, "leak_scan", _no_scan)
        row = lr.run_loop_task(
            str(unit), tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd="stub-seam", workspace=ws)
        assert "leak_scan" not in row
        assert "ORACLE_LEAK" not in [f["code"] for f in row["failures"]]


# -------------------------------------------- Face B: topology marker ----

class TestTopologyMarker:
    """Face B: dispatch_count is the orchestrator-economy contract."""

    def test_zero_dispatch_is_noncompliant(self, tmp_path, monkeypatch,
                                           capsys):
        unit = _make_unit(tmp_path)
        ws = _prepared_workspace(tmp_path, unit)  # no ledger: 0 dispatches
        row = _run(unit, tmp_path, monkeypatch, workspace=ws)
        assert row["topology_compliant"] is False
        # the exclusion a spine-dead stub row carries rides the
        # PRE-EXISTING #523 harness class (dispatch=0 + no q-cells),
        # never the topology face — the marker adds no exclusion of its
        # own
        assert row["governance"]["harness_failure"] is True
        err = capsys.readouterr().err
        assert "TOPOLOGY solo-only run" in err
        assert "orchestrator-economy read" in err

    def test_positive_dispatch_is_compliant(self, tmp_path, monkeypatch,
                                            capsys):
        unit = _make_unit(tmp_path)
        ws = _prepared_workspace(tmp_path, unit)
        _seed_dispatches(ws, count=3)
        row = _run(unit, tmp_path, monkeypatch, workspace=ws)
        assert row["topology_compliant"] is True
        assert row["excluded_from_performance"] is False, \
            "a compliant run stays in the capability read"
        assert "TOPOLOGY solo-only run" not in capsys.readouterr().err

    def test_cc_arm_has_no_topology_key(self, tmp_path, monkeypatch,
                                        capsys):
        unit = _make_unit(tmp_path)
        row = lr.run_loop_task(
            str(unit), tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd="stub-seam", arm="cc-default")
        assert "topology_compliant" not in row
        assert "TOPOLOGY" not in capsys.readouterr().err


# ------------------------------------------------- Face C: sandbox wrap --

class TestSandboxWrap:
    """Face C: the opt-in seatbelt wrap at the launch adapter."""

    def test_env_set_wraps_the_argv(self, tmp_path, monkeypatch):
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake = fake_bin / "sandbox-exec"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        profile = tmp_path / "profile.sb"
        profile.write_text("(version 1)\n", encoding="utf-8")
        monkeypatch.setenv(lr.ENV_SANDBOX_PROFILE, str(profile))
        rec = lr.launch_session(tmp_path, "P", budget_usd=1.0,
                                wall_cap_s=30.0)
        assert rec["argv"][:3] == ["sandbox-exec", "-f", str(profile)]
        assert rec["argv"][3] == "claude", \
            "the wrapped binary is the production face's own argv"
        assert rec["sandbox_wrap_failed"] is False

    def test_env_unset_leaves_argv_untouched(self, tmp_path, monkeypatch,
                                             capsys):
        monkeypatch.delenv(lr.ENV_SANDBOX_PROFILE, raising=False)
        rec = lr.launch_session(
            tmp_path, "P", budget_usd=1.0, wall_cap_s=30.0,
            session_cmd=f'"{sys.executable}" -c "pass"')
        assert rec["argv"][0] == sys.executable
        assert rec["sandbox_wrap_failed"] is False
        assert "sandbox" not in capsys.readouterr().err.lower()

    def test_missing_binary_is_loud_and_unwrapped(self, tmp_path,
                                                  monkeypatch, capsys):
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        profile = tmp_path / "profile.sb"
        profile.write_text("(version 1)\n", encoding="utf-8")
        monkeypatch.setenv(lr.ENV_SANDBOX_PROFILE, str(profile))
        rec = lr.launch_session(
            tmp_path, "P", budget_usd=1.0, wall_cap_s=30.0,
            session_cmd=f'"{sys.executable}" -c "pass"')
        assert rec["argv"][0] == sys.executable, \
            "the session launches UNWRAPPED, never a crash"
        assert rec["sandbox_wrap_failed"] is True
        err = capsys.readouterr().err
        assert "sandbox-exec" in err
        assert "UNWRAPPED" in err

    def test_row_carries_sandbox_wrap_failed(self, tmp_path, monkeypatch):
        """The row marker travels: env set + no sandbox-exec on PATH ->
        run_loop_task's session block carries sandbox_wrap_failed=true
        while the (seamed) session still completes and grades."""
        unit = _make_unit(tmp_path)
        # prepare the workspace BEFORE stripping PATH — init's toolchain
        # gate needs the real environment (this test only scopes PATH for
        # the launch adapter's sandbox-exec probe)
        ws = _prepared_workspace(tmp_path, unit, armed=False)
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        profile = tmp_path / "profile.sb"
        profile.write_text("(version 1)\n", encoding="utf-8")
        monkeypatch.setenv(lr.ENV_SANDBOX_PROFILE, str(profile))
        stub = tmp_path / "s952_stub.py"
        stub.write_text("import sys\n", encoding="utf-8")
        row = lr.run_loop_task(
            str(unit), tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=f'"{sys.executable}" "{stub}"', workspace=ws)
        assert row["loop"]["session"]["sandbox_wrap_failed"] is True
        assert row["verdict"] == "SKIP"  # no deliverable: honest grade


# --------------------------------------------------- template contract ---

class TestSandboxTemplate:
    """Face C's shipped TEMPLATE: slots + deny-reads + the operator
    contract header (the runner never materializes a profile)."""

    def test_template_ships_with_slots_and_deny_reads(self):
        tmpl = ROOT / "templates" / "sandbox-denying-units.sb.tmpl"
        assert tmpl.is_file()
        text = tmpl.read_text(encoding="utf-8")
        assert "@KUNGLAO_GRADING_ROOT@" in text
        assert "@KUNGLAO_UNITS_ROOT@" in text
        assert text.count("deny file-read*") >= 2
        assert "(allow default)" in text
        assert "TEMPLATE ONLY" in text
        assert "NEVER writes a profile" in text
        assert "sandbox-exec -f <profile>" in text


# ---- review round 1 (2026-11-02): the three fixes -------------------------

class TestReviewRound1Fixes:
    """The independent review's HIGH + both MEDIUMs, pinned."""

    def test_template_denies_writes_on_both_trees(self):
        tmpl = ROOT / "templates" / "sandbox-denying-units.sb.tmpl"
        text = tmpl.read_text(encoding="utf-8")
        # the session KNOWS the grading root (the env rides child_env):
        # read-only denial leaves write-forgery of the ground truth open
        assert text.count("deny file-write*") >= 2

    def test_scan_covers_deliverables_and_analyses(self, tmp_path):
        """The deliverable is the MOST likely leak carrier (a forged PASS
        citing the grader path in a comment) — facts/notes/scratch alone
        were a silent hole."""
        ws = tmp_path / "ws"
        (ws / "runs" / "deliverables").mkdir(parents=True)
        (ws / "analyses").mkdir()
        grading_root = tmp_path / "grading"
        (ws / "runs" / "deliverables" / "candidate.py").write_text(
            f"# formula from {grading_root}/checker.py\n",
            encoding="utf-8")
        (ws / "analyses" / "a.md").write_text(
            f"grader: {grading_root}/ground_truth\n", encoding="utf-8")
        out = lr.leak_scan(ws, grading_root)
        assert out["hit"] is True
        assert set(out["files"]) == {
            "runs/deliverables/candidate.py", "analyses/a.md"}

    def test_unreadable_subdirectory_degrades_not_dies(self, tmp_path):
        """A session chmod-000ing a subtree must degrade THAT subtree to
        a warn — the containment tripwire must never kill a paid task."""
        ws = tmp_path / "ws"
        (ws / "facts" / "sub").mkdir(parents=True)
        grading_root = tmp_path / "grading"
        _plant_leak(ws, grading_root)
        locked = ws / "facts" / "sub" / "locked.bin"
        locked.write_bytes(b"\x00\x01")
        os.chmod(ws / "facts" / "sub", 0o000)
        try:
            out = lr.leak_scan(ws, grading_root)
        finally:
            os.chmod(ws / "facts" / "sub", 0o755)
        assert out["hit"] is True
        assert out["files"] == ["facts/F001.md"]

    def test_child_env_strips_the_grading_root(self, tmp_path, monkeypatch):
        """The sandbox-wrapped session must not be TOLD where the oracle
        lives — the fake wrapper dumps the session env for the assert."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        dump = tmp_path / "env-dump.txt"
        fake = fake_bin / "sandbox-exec"
        fake.write_text(f"#!/bin/sh\nenv > {dump}\nexit 0\n",
                        encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", str(fake_bin))
        monkeypatch.setenv("KUNGLAO_GRADING_ROOT",
                           str(tmp_path / "grading"))
        profile = tmp_path / "profile.sb"
        profile.write_text("(version 1)\n", encoding="utf-8")
        monkeypatch.setenv(lr.ENV_SANDBOX_PROFILE, str(profile))
        lr.launch_session(tmp_path, "P", budget_usd=1.0, wall_cap_s=30.0)
        env_dump = dump.read_text(encoding="utf-8", errors="replace")
        assert "KUNGLAO_GRADING_ROOT" not in env_dump
