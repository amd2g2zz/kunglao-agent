#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_supply_admission_794.py — #794 admission with teeth.

The dispatch-gate eligibility face: a claim cannot reach dispatch without
>= 1 OPEN hypothesis linked to it (claim_id map face, or the register's
hypothesis_ref face) carrying >= 1 non-empty candidate.

Teeth scope (owner task directive 2026-10-24 — the panel's Phase-1
advisory is superseded for THIS face):
  store READABLE + no linked open hypothesis -> REJECT (exit 2,
  evidence-class charter face) with guidance naming the fix;
  store UNREADABLE -> fail-open (WARN + hypothesis_supply_fail_open trace),
  the #103/#801 scope retained for outages only.

Sleeping faces: hypotheses/ carrier absent (pre-#538 workspace), claim not
in the register, verifier-remediation dispatches (#237 D2 honest path).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------- fixtures ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")


def _write_hyp(ws: Path, hyp_id: str, *, candidates: list[str],
               status: str = "open", claim_id: str = "C-1",
               group: str = "pq-q1", body_marker: str | None = "pq:q1",
               hyp_ref_field: bool = False) -> Path:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = (f"\n{body_marker}\n\nstub body\n" if body_marker
            else "\nstub body\n")
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        f"claim_id: {claim_id}\n"
        f"competitor_group: {group}\n"
        "candidates: [" + ", ".join(candidates) + "]\n"
        f"status: {status}\n"
        "schema_rev: 1\n"
        "---\n" + body,
        encoding="utf-8")
    return p


def _mk_ws(root: Path, *, scaffold: bool = True,
           claim: dict | None = None) -> Path:
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    row = claim or {"id": "C-1", "status": "OPEN",
                    "statement": "recover the header mac",
                    "answers_question": "q1"}
    _write_yaml(ws / "claim-register.yaml", {"claims": [row]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml", {"primary_questions": ["q1"]})
    if scaffold:
        (ws / "hypotheses").mkdir(exist_ok=True)
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    (ws / "runs").mkdir(exist_ok=True)
    return ws


def _payload() -> dict:
    return {"tool_input": {"prompt": json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1,
        "tools": ["Read", "Write"], "agent": "kunglao-worker"}})
        + "\nprobe the header mac path"}}


# ---------- 1. the teeth ----------

class TestSupplyTeeth:
    def test_hypothesis_less_claim_rejects(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)  # scaffolded carrier, zero hypotheses
        rc = dg._supply_admission(ws, "C-1", _payload())
        assert rc == 2, "a hypothesis-less claim must NOT reach dispatch"
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "hypothesis_supply_reject"]
        assert rows and rows[0].get("claim") == "C-1"

    def test_open_linked_hypothesis_with_candidate_passes(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=["stated mac scheme"])
        assert dg._supply_admission(ws, "C-1", _payload()) is None

    def test_refuted_hypothesis_does_not_satisfy(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=["stated mac scheme"],
                   status="refuted")
        assert dg._supply_admission(ws, "C-1", _payload()) == 2

    def test_empty_candidates_stub_does_not_satisfy(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=[])
        assert dg._supply_admission(ws, "C-1", _payload()) == 2

    def test_hypothesis_for_another_claim_does_not_satisfy(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=["stated mac scheme"],
                   claim_id="C-OTHER")
        assert dg._supply_admission(ws, "C-1", _payload()) == 2

    def test_register_hypothesis_ref_family_arm_passes(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path, claim={
            "id": "C-1", "status": "OPEN", "statement": "arm",
            "origin": "hypothesis-arm", "hypothesis_ref": "H-FAM"})
        # the family hypothesis names the PARENT claim (the #252 shape) —
        # the arm reaches it through the register's hypothesis_ref face.
        _write_hyp(ws, "H-FAM", candidates=["arm candidate"],
                   claim_id="C-PARENT")
        assert dg._supply_admission(ws, "C-1", _payload()) is None

    def test_reject_guidance_names_the_fix(self, tmp_path, capsys) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        dg._supply_admission(ws, "C-1", _payload())
        captured = capsys.readouterr()
        blob = captured.out + captured.err
        assert "hypothesis_supply" in blob
        assert "hypothesis_bridge" in blob or "hypothesis_store" in blob


# ---------- 2. fail-open retained ONLY for the unreadable carrier -------

class TestSupplyFailOpen:
    def test_store_read_failure_fails_open(self, tmp_path,
                                           monkeypatch) -> None:
        import hypothesis_store as hs
        import dispatch_gate as dg

        def _boom(self):
            raise OSError("hypotheses/ unreadable")

        monkeypatch.setattr(hs.HypothesisStore, "list_all", _boom)
        ws = _mk_ws(tmp_path)
        rc = dg._supply_admission(ws, "C-1", _payload())
        assert rc is None, "a store outage must not block the dispatch"
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "hypothesis_supply_fail_open"]
        assert rows and "OSError" in str(rows[0].get("detail"))


# ---------- 3. sleeping faces ----------

class TestSupplySleeps:
    def test_unscaffolded_workspace_sleeps(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path, scaffold=False)
        assert dg._supply_admission(ws, "C-1", _payload()) is None

    def test_unknown_claim_sleeps(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        assert dg._supply_admission(ws, "C-404", _payload()) is None

    def test_verifier_remediation_dispatch_skips(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        assert dg._supply_admission(ws, "C-1", _payload(),
                                    verifier_remediation=True) is None


# ---------- 4. the wiring: the full gate blocks end-to-end --------------

def _run_gate(root: Path, ws: Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "tool_input": {"prompt": prompt, "subagent_type": "kunglao-worker"},
    })
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=90,
        cwd=str(REPO_ROOT), errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
    )


def _event_rows(ws: Path) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def test_full_gate_rejects_hypothesis_less_dispatch(tmp_path) -> None:
    root = tmp_path
    ws = _mk_ws(root)
    prompt = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1,
        "tools": ["Read", "Write"], "agent": "kunglao-worker"}})
    proc = _run_gate(root, ws, prompt + "\nprobe")
    assert proc.returncode == 2, (
        f"RED (#794) wiring: the full gate let a hypothesis-less dispatch "
        f"through (rc={proc.returncode}) err={proc.stderr[-400:]}")
    assert "hypothesis_supply" in proc.stderr


def test_full_gate_allows_stubbed_dispatch(tmp_path) -> None:
    root = tmp_path
    ws = _mk_ws(root)
    _write_hyp(ws, "H-001", candidates=["stated mac scheme"])
    prompt = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1,
        "tools": ["Read", "Write"], "agent": "kunglao-worker"}})
    proc = _run_gate(root, ws, prompt + "\nprobe")
    assert proc.returncode == 0, (
        f"a stubbed claim must dispatch: rc={proc.returncode} "
        f"err={proc.stderr[-400:]}")


# ---------- 5. vocabulary registration -----------------------------------

@pytest.mark.parametrize("word", ["hypothesis_supply_reject",
                                  "hypothesis_supply_fail_open"])
def test_supply_words_are_registered_emit_actions(word: str) -> None:
    import event_taxonomy as et
    assert word in et.EMIT_ACTIONS


def test_register_ref_counts_open_drained_family(tmp_path) -> None:
    """The #252 arm shape: an arm claim's family hypothesis is a DRAINED
    scaffold (candidates=[]) — the arm claim itself is the candidate, so
    the hypothesis_ref face counts the family on OPEN alone."""
    import dispatch_gate as dg
    ws = _mk_ws(tmp_path, claim={
        "id": "C-1", "status": "OPEN", "statement": "arm",
        "origin": "hypothesis-arm", "hypothesis_ref": "H-FAM"})
    _write_hyp(ws, "H-FAM", candidates=[], claim_id="C-PARENT")
    assert dg._supply_admission(ws, "C-1", _payload()) is None
