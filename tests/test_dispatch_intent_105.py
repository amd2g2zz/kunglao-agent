# -*- coding: utf-8 -*-
"""#105 — dispatch_gate is THE roi-intents producer (audit A8, prerequisite
for #50).

#49 shipped the value spine inert by construction: record_intent had zero
production callers, so runs/roi-intents.jsonl was never written,
outcome_capture._settle_new never saw has_intent True, and settlements were
structurally empty. This file pins the one minimal producer: the dispatch
gate records the intent row on its ALLOW path — after the #496 teeth, at
the main-flow tail, before the worker starts.

Row contract (roi_settlement.record_intent schema, #49 frozen):
    claim_id       — the dispatched claim
    uncertainty    — the DECLARED uncertainty this dispatch aims to eliminate
                     (issue wording: "declared uncertainty")
    context_tags   — the applicability PRECONDITIONS parsed from the prompt
                     (ruling 1's context dimension: value = method x context
                     x outcome — preconditions ARE the applicability context)
    ts             — record timestamp

Declaration faces parsed from the dispatch prompt (#97 owns the prompt
FIELD contract; this issue only lands the writer):
    v1 structured — kunglao_dispatch meta keys uncertainty / preconditions /
                    expected_artifact
    prose         — `uncertainty:` / `preconditions:` / `expected_artifact:`
                    markers, case-insensitive

Fail-open discipline: a missing declaration, a declaration-parse failure or
a record-write failure NEVER blocks the dispatch — the face degrades to an
`intent_unparsed` event (kunglao_log unified log, registered word) and rc
stays 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import roi_settlement as roi
from _factories import write_hook_state

ROOT = Path(__file__).resolve().parents[1]

_UNCERTAINTY = "which config builder reconstructs the header"
_PRECONDITIONS = ["vm", "ghidra"]


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _mk_ws(root: Path) -> Path:
    """Minimal activated workspace whose single claim C-1 IS the top-1, so a
    plain dispatch reaches the ALLOW tail unchanged (same shape as the #902
    harness)."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN",
         "statement": "background work"}]})
    _write(ws / "claim_deps.yaml",
           {"depends_on": {}, "competitor_groups": {}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    (ws / "runs").mkdir()
    return ws


def _run_gate(root: Path, ws: Path, prompt: str,
              agent: str = "kunglao-worker") -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "tool_input": {"prompt": prompt, "subagent_type": agent},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=90,
        cwd=str(ROOT), errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
    )


def _intent_rows(ws: Path) -> list[dict]:
    p = roi.intents_path(ws)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _event_rows(ws: Path) -> list[dict]:
    """All rows from the unified event log (runs/logs/kunglao-*.jsonl)."""
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_PROMPT_WITH_INTENT = (
    "[T1 tools=Read,Write] claim C-1 background sweep\n"
    f"uncertainty: {_UNCERTAINTY}\n"
    "preconditions: vm, ghidra\n"
    "expected_artifact: recon-map"
)


class TestDispatchWritesIntent:
    """AC 1: synthetic dispatch flow -> observable row in
    runs/roi-intents.jsonl (claim id + declared uncertainty +
    preconditions + ts)."""

    def test_dispatch_pass_writes_intent_row(self, tmp_path) -> None:
        root = tmp_path
        ws = _mk_ws(root)
        r = _run_gate(root, ws, _PROMPT_WITH_INTENT)
        assert r.returncode == 0, (
            f"a legal dispatch must still ALLOW; stderr={r.stderr!r}")
        rows = _intent_rows(ws)
        assert len(rows) == 1, f"expected exactly one intent row; {rows=}"
        row = rows[0]
        assert row["claim_id"] == "C-1"
        # declared uncertainty — the ruling-3 "WHICH uncertainty" face
        assert row["uncertainty"] == _UNCERTAINTY
        # applicability preconditions ride the ruling-1 context dimension
        assert row["context_tags"] == _PRECONDITIONS
        assert row["ts"], "the row must carry a record timestamp"
        # the method dimension: the dispatched agent identity
        assert row["method"] == "kunglao-worker"

    def test_identical_redispatch_is_idempotent(self, tmp_path) -> None:
        """Re-dispatching the SAME declaration -> still one ledger line
        (record_intent idempotency survives the producer)."""
        root = tmp_path
        ws = _mk_ws(root)
        assert _run_gate(root, ws, _PROMPT_WITH_INTENT).returncode == 0
        assert _run_gate(root, ws, _PROMPT_WITH_INTENT).returncode == 0
        assert len(_intent_rows(ws)) == 1

    def test_corrected_redispatch_lands_new_declaration(self, tmp_path) -> None:
        """A re-declared (corrected) intent appends; latest wins at
        settlement — the #49 contract, exercised through the producer."""
        root = tmp_path
        ws = _mk_ws(root)
        assert _run_gate(root, ws, _PROMPT_WITH_INTENT).returncode == 0
        second = _PROMPT_WITH_INTENT.replace(_UNCERTAINTY,
                                             "does the FQA list match strings")
        assert _run_gate(root, ws, second).returncode == 0
        rows = _intent_rows(ws)
        assert len(rows) == 2
        assert rows[-1]["uncertainty"] == "does the FQA list match strings"

    def test_v1_structured_meta_declaration_recorded(self, tmp_path) -> None:
        """The v1 JSON envelope may carry the declaration structurally —
        the face #97's dispatch contract will formalize."""
        root = tmp_path
        ws = _mk_ws(root)
        prompt = (
            '{"kunglao_dispatch": {"version": 1, "claim": "C-1", "tier": 1,'
            ' "tools": ["Read", "Write"], "agent": "kunglao-worker",'
            f' "uncertainty": "{_UNCERTAINTY}",'
            ' "preconditions": ["vm", "ghidra"],'
            ' "expected_artifact": "recon-map"}}'
            " background sweep"
        )
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = _intent_rows(ws)
        assert len(rows) == 1, f"rows={rows}"
        assert rows[0]["uncertainty"] == _UNCERTAINTY
        assert rows[0]["context_tags"] == _PRECONDITIONS


class TestIntentUnparsedFailOpen:
    """AC 2: unparseable/missing declaration -> dispatch proceeds +
    `intent_unparsed` event recorded; nothing blocks, nothing crashes."""

    def test_no_uncertainty_dispatch_proceeds_with_intent_unparsed(
            self, tmp_path) -> None:
        root = tmp_path
        ws = _mk_ws(root)
        r = _run_gate(root, ws, "[T1 tools=Read,Write] claim C-1 sweep")
        assert r.returncode == 0, (
            f"a declaration-less dispatch must still ALLOW; stderr={r.stderr!r}")
        # the ruling-3 gate declined the row — nothing written
        assert _intent_rows(ws) == []
        events = [e for e in _event_rows(ws)
                  if e.get("action") == "intent_unparsed"]
        assert events, "intent_unparsed event must be recorded"
        assert events[0].get("claim") == "C-1"

    def test_record_failure_never_blocks_dispatch(self, tmp_path,
                                                  monkeypatch) -> None:
        """A record_intent WRITE failure degrades to the intent_unparsed
        event — the dispatch face itself must never break (fail-open)."""
        import dispatch_gate as dg

        def _boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(roi, "record_intent", _boom)
        ws = _mk_ws(tmp_path)
        # must not raise
        dg._record_dispatch_intent(ws, "C-1", _PROMPT_WITH_INTENT,
                                   {"tool_input": {"subagent_type":
                                                   "kunglao-worker"}})
        events = [e for e in _event_rows(ws)
                  if e.get("action") == "intent_unparsed"]
        assert events, "write failure must surface as intent_unparsed"
        assert "disk full" in str(events[0].get("detail"))

    def test_declaration_parse_failure_never_raises(self, tmp_path,
                                                    monkeypatch) -> None:
        """A parser crash (malformed meta) lands in the same fail-open
        event face instead of blocking the gate."""
        import dispatch_gate as dg
        monkeypatch.setattr(dg, "_parse_intent_declaration",
                            lambda _t: (_ for _ in ()).throw(
                                ValueError("bad declaration")))
        ws = _mk_ws(tmp_path)
        dg._record_dispatch_intent(ws, "C-1", _PROMPT_WITH_INTENT, {})
        events = [e for e in _event_rows(ws)
                  if e.get("action") == "intent_unparsed"]
        assert events, "parse failure must surface as intent_unparsed"


class TestGateSleepsWhenInactive:
    """The producer rides the ACTIVATED ALLOW tail — no activation, no
    hook, no row (v1.9.7 hooks-sleep discipline)."""

    def test_inactive_gate_writes_nothing(self, tmp_path) -> None:
        root = tmp_path
        ws = _mk_ws(root)
        # v1.9.7 hooks-sleep discipline: gate not in active_hooks -> no row
        write_hook_state(ws, active_hooks=[])
        r = _run_gate(root, ws, _PROMPT_WITH_INTENT)
        assert r.returncode == 0
        assert _intent_rows(ws) == []


@pytest.mark.parametrize("word", ["intent_unparsed"])
def test_intent_unparsed_is_a_registered_emit_action(word: str) -> None:
    """The fail-open face's event word lives in the controlled vocabulary
    (#459 anchor sibling)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import event_taxonomy as et
    assert word in et.EMIT_ACTIONS
