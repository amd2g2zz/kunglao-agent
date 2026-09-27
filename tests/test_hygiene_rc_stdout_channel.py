#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_hygiene_rc_stdout_channel.py — tier C (record-only batch):
stdout hygiene.

Progress/diagnostic lines moved off stdout (stdout is contract output:
parse streams like `^VERDICT ` grep faces and NOT FOUND verifiers must
never see human-facing chatter). Pins per site:
  - devkit/quality_gates.py: the five [fail] import-error lines go to
    stderr, text unchanged
  - scripts/refutation_propagate.py: semantic-face-unavailable line to
    stderr
  - scripts/kunglao_export.py: NOT FOUND line to stderr
  - scripts/eval_loop_runner.py: the VERDICT ... SKIP (init_failed)
    line STAYS on stdout (autoresearch.sh greps ^VERDICT from the
    unit's stdout file for the pass@k arithmetic — parsed downstream
    face) and is mirrored to stderr as a WARN
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_quality_gates():
    spec = importlib.util.spec_from_file_location(
        "devkit_quality_gates_hygiene", REPO / "devkit" / "quality_gates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        result = fn(*a, **k)
    return result, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# devkit/quality_gates.py — [fail] progress lines belong on stderr
# ---------------------------------------------------------------------------

def test_gate_import_failures_go_to_stderr(monkeypatch):
    mod = _load_quality_gates()
    gates = [
        ("subagent_review", mod._gate5_subagent_review),
        ("agents_lint", mod._gate6_agents_contract),
        ("doc_sync", mod._gate7_doc_sync),
        ("governance_binding", mod._gate8_governance_binding),
        ("discovery_gate", mod._gate9_discovery_face),
    ]
    for module_name, gate_fn in gates:
        monkeypatch.setitem(sys.modules, module_name, None)
        result, out, err = _capture(gate_fn)
        assert result is False, module_name
        assert f"[fail] {module_name} import error" in err, module_name
        assert out == "", f"{module_name}: stdout must stay clean"


# ---------------------------------------------------------------------------
# scripts/refutation_propagate.py — semantic-face diagnostic to stderr
# ---------------------------------------------------------------------------

def test_refutation_semantic_face_line_on_stderr(tmp_path, monkeypatch):
    import refutation_propagate as rp
    (tmp_path / "claim-register.yaml").write_text("claims: []\n",
                                                  encoding="utf-8")
    (tmp_path / "claim_deps.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "plan_epistemics", None)
    marked, out, err = _capture(rp.mark_dependents, tmp_path)
    assert marked == []  # behavior unchanged: structural walk only
    assert "semantic face unavailable" in err
    assert "semantic face unavailable" not in out


# ---------------------------------------------------------------------------
# scripts/kunglao_export.py — NOT FOUND diagnostic to stderr
# ---------------------------------------------------------------------------

def test_export_not_found_line_on_stderr(tmp_path):
    import kunglao_export as ke
    archive = tmp_path / "exp.tgz"
    # entry carries `path` but no `sha256`: the in-try KeyError lands the
    # NOT FOUND branch (an entry without `path` would raise before the
    # try — member_name is resolved outside it)
    manifest = {"version": 1, "workspace": "ws", "include_scratch": False,
                "zones": {"carrier": [{"path": "code/missing.txt"}]}}
    with tarfile.open(archive, "w:gz") as tar:
        data = json.dumps(manifest).encode()
        import io as _io
        info = tarfile.TarInfo("MANIFEST.json")
        info.size = len(data)
        tar.addfile(info, _io.BytesIO(data))
    rc, out, err = _capture(ke.verify_manifest, archive)
    assert rc != 0
    assert "NOT FOUND:" in err
    assert "NOT FOUND:" not in out


# ---------------------------------------------------------------------------
# scripts/eval_loop_runner.py — VERDICT SKIP stays on stdout, mirrors to
# stderr (parsed downstream face: autoresearch.sh pass@k arithmetic)
# ---------------------------------------------------------------------------

def test_loop_task_init_failed_verdict_on_stdout_and_mirrored(
        tmp_path, monkeypatch):
    import eval_loop_runner as lr

    monkeypatch.setattr(lr.ds, "resolve_task_dir",
                        lambda _ref: tmp_path / "task")
    # the SKIP row build reads task["family"] and task["checker"]["kind"]
    monkeypatch.setattr(lr.ds, "load_task",
                        lambda _tdir: {"family": "f",
                                       "checker": {"kind": "mechanical"}})
    monkeypatch.setattr(lr, "_candidate_suffix", lambda _task: ".md")
    monkeypatch.setattr(lr, "prompt_injection_blocks",
                        lambda _tdir, _task: ("", ""))

    def _boom(*a, **k):
        raise RuntimeError("init exploded")

    monkeypatch.setattr(lr, "init_workspace", _boom)

    row, out, err = _capture(lr.run_loop_task, "unit-x", tmp_path / "out")
    assert row["verdict"] == "SKIP"
    assert row["loop"]["status"] == "init_failed"  # frozen row shape
    # stdout keeps the parsed verdict line (autoresearch.sh contract)
    assert "VERDICT task SKIP (loop: init_failed)" in out
    # stderr carries the mirrored diagnostics warn
    assert "verdict_skip_init_failed" in err
    assert "task" in err
