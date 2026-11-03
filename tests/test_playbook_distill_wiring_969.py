#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_playbook_distill_wiring_969.py — the #969 WRITE-side wiring pin.

issue #969: scripts/rlvr/playbook_distill.py shipped with ZERO callers
in the eval topology — the READ side (eval_loop_runner's playbook_
injection_block) was wired, the WRITE side (distill at the session
terminal) was not, so KUNGLAO_PLAYBOOK=1 spent zero distill calls
across three smoke rounds. Pinned here, through lr.playbook_distill_face —
the seam run_loop_task calls ONCE per session terminal, in the verdict-
row assembly region:

  W1  the seam: with the env on, the face reaches the distill through
      the module-level executor seam (playbook_distill.default_executor —
      what an unkeyed distill() call resolves at call time) — exactly
      ONE call, the family rides the prompt, the ws terminal material
      rides the prompt, and the gated patch lands as <family>.md under
      KUNGLAO_PLAYBOOK_ROOT
  W2  gate parity with the read side: env unset or non-"1" -> zero
      executor calls, no store write (byte-identical to the pre-#969
      shape); a family-less task skips silently (the cold shape)
  W3  fail-open: an executor fault -> the loud playbook_distill WARN on
      stderr, no raise, the store file byte-untouched, and a verdict
      row built around the face is untouched; a fault that escapes
      distill entirely (store-write OSError) -> the runner's rate-
      limited _boot WARN, no raise, face returns None
  W4  budget posture: one call per terminal — a faulting executor is
      called exactly once per face call, no retries

stdlib + pytest only (house eval-script rule).
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

import eval_dataset as ds  # noqa: E402
from rlvr import family_playbook as fpb  # noqa: E402
from rlvr import playbook_distill as pd  # noqa: E402

import eval_loop_runner as lr  # noqa: E402

# the #969 issue's example family key
FAMILY = "tf-hardwall-beacon"


@pytest.fixture(autouse=True)
def _playbook_env(monkeypatch, tmp_path):
    """Isolated playbook root + the playbook env OFF (tests opt IN
    explicitly), and fresh warn-dedup state on BOTH warn modules — the
    tests/ conftest resets kunglao_log only; _warn_fail_open warns
    through _boot, whose process-wide dedup would otherwise suppress a
    repeated (op, reason) across tests."""
    monkeypatch.setenv("KUNGLAO_PLAYBOOK_ROOT", str(tmp_path / "pbooks"))
    monkeypatch.delenv(lr.ENV_PLAYBOOK, raising=False)
    try:
        import _boot
        monkeypatch.setattr(_boot, "_WARN_LAST", {}, raising=False)
    except ImportError:  # pragma: no cover
        pass


def _seed_ws(tmp: Path) -> Path:
    """A minimal terminal workspace: one fact + one probe reading — the
    citable evidence surface the mechanical gate verifies against."""
    (tmp / "facts").mkdir(parents=True, exist_ok=True)
    (tmp / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp / "facts" / "F001-headless-cgevent.md").write_text(
        "F001 the hardwall beacon fires before the KDF loop\n",
        encoding="utf-8")
    (tmp / "evidence" / "probe-001.json").write_text(
        json.dumps({"schema": "kunglao-probe-reading/1", "scalar": 0.5}),
        encoding="utf-8")
    return tmp


_ADD_PATCH = [{"op": "add", "section": "when the beacon pre-fires",
               "text": "read the beacon latch before arming the KDF arm",
               "evidence_refs": ["facts/F001-headless-cgevent.md"]}]


def _stub_executor(prompts: list[str], patch=None):
    """The deterministic executor stub. Installed ON pd.default_executor
    — the module-level seam an unkeyed pd.distill() call resolves at
    call time, i.e. exactly the seam the runner's call path uses."""
    def _exec(prompt: str) -> str:
        prompts.append(prompt)
        if isinstance(patch, str):
            return patch
        return json.dumps(patch if patch is not None else _ADD_PATCH)
    return _exec


def _row_snapshot() -> dict:
    """A verdict row in the run_loop_task shape — the row the terminal
    face must never disturb."""
    return ds.results_row(
        task_id="unit-969", family=FAMILY, checker_kind="selfcheck",
        metrics={m: 0 for m in ds.REQUIRED_METRICS}, verdict="FAIL",
        failures=[{"code": "GAP", "detail": "d"}], evidence_ref="",
        arm="loop")


# ---- W1: the seam, once, right family, patch lands -------------------------
class TestSeam:
    def test_env_on_one_call_right_family_patch_lands(
            self, monkeypatch, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        prompts: list[str] = []
        monkeypatch.setattr(pd, "default_executor", _stub_executor(prompts))
        summary = lr.playbook_distill_face(ws, FAMILY)
        assert summary is not None
        assert summary["applied"] is True
        # (a) invoked exactly ONCE, with the right family and the ws
        # terminal material riding the prompt
        assert summary["calls"] == 1
        assert len(prompts) == 1
        assert f"'{FAMILY}'" in prompts[0]
        assert "--- facts/F001-headless-cgevent.md ---" in prompts[0]
        # (b) the produced patch lands in the playbook root as <family>.md
        path = fpb.playbook_path(FAMILY)
        assert path is not None and path.is_file()
        doc = fpb.parse(path.read_text(encoding="utf-8"))
        assert [e.situation for e in doc.entries] == \
            ["when the beacon pre-fires"]
        cap = capsys.readouterr()
        assert cap.out == "", "no stdout pollution — the row's stdout faces"
        assert f"family={FAMILY}" in cap.err  # the applied-side trace


# ---- W2: gate parity with the read side ------------------------------------
class TestGate:
    def test_env_unset_zero_calls_no_write(self, monkeypatch, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        prompts: list[str] = []
        monkeypatch.setattr(pd, "default_executor", _stub_executor(prompts))
        assert lr.playbook_distill_face(ws, FAMILY) is None
        assert prompts == []
        path = fpb.playbook_path(FAMILY)
        assert path is not None and not path.exists()

    def test_env_other_value_zero_calls(self, monkeypatch, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "0")
        prompts: list[str] = []
        monkeypatch.setattr(pd, "default_executor", _stub_executor(prompts))
        assert lr.playbook_distill_face(ws, FAMILY) is None
        assert prompts == []

    def test_familyless_silent_skip(self, monkeypatch, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        prompts: list[str] = []
        monkeypatch.setattr(pd, "default_executor", _stub_executor(prompts))
        assert lr.playbook_distill_face(ws, None) is None
        assert lr.playbook_distill_face(ws, "   ") is None
        assert prompts == []
        assert capsys.readouterr().err == ""


# ---- W3: fail-open — the verdict row survives any distill fault ------------
class TestFailOpen:
    def test_executor_fault_loud_warn_store_untouched_row_intact(
            self, monkeypatch, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        path = fpb.playbook_path(FAMILY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# playbook: {FAMILY}\n", encoding="utf-8")
        before = path.read_bytes()
        row = _row_snapshot()
        row_snapshot = json.loads(json.dumps(row))

        def boom(_prompt: str) -> str:
            raise pd.DistillExecutorError("distill-call rc=1: boom")

        monkeypatch.setattr(pd, "default_executor", boom)
        # the face must NOT raise — the run's terminal face continues
        summary = lr.playbook_distill_face(ws, FAMILY)
        assert summary is not None
        assert summary["applied"] is False
        assert summary["patch"] == []
        assert summary["calls"] == 1  # the ONE budgeted call was spent
        assert summary["reason"].startswith("executor-fault")
        assert path.read_bytes() == before, "store file byte-untouched"
        cap = capsys.readouterr()
        assert "playbook_distill" in cap.err, "the loud WARN fired"
        # the verdict row built around the face is untouched
        assert row == row_snapshot
        assert _row_snapshot()["verdict"] == "FAIL"

    def test_escape_past_distill_boot_warned_no_raise(
            self, monkeypatch, tmp_path, capsys):
        """The wrapper's own face: a fault that escapes pd.distill (e.g.
        a store-write OSError) is one rate-limited _boot WARN, no raise,
        and the face returns None."""
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")

        def explode(_ws, _family, *_a, **_k):
            raise OSError("store write exploded")

        monkeypatch.setattr(pd, "distill", explode)
        assert lr.playbook_distill_face(ws, FAMILY) is None  # no raise
        cap = capsys.readouterr()
        assert "_boot WARN (fail-open): playbook_distill" in cap.err
        assert "store write exploded" in cap.err


# ---- W4: the budget posture — one call per terminal, no retries ------------
class TestBudget:
    def test_faulting_executor_called_once_per_terminal(
            self, monkeypatch, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        calls: list[str] = []

        def boom(_prompt: str) -> str:
            calls.append(_prompt)
            raise pd.DistillExecutorError("distill-call rc=1")

        monkeypatch.setattr(pd, "default_executor", boom)
        lr.playbook_distill_face(ws, FAMILY)
        lr.playbook_distill_face(ws, FAMILY)  # a second terminal
        assert len(calls) == 2, "one call per terminal — no retries"
