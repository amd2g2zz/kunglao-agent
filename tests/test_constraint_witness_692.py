# -*- coding: utf-8 -*-
"""Constraint-witness contract tests — every not_done counterexample
carries a mechanical witness, and the oracle verdict is

    verdict = witness AND outcome

Fixture shape: a pure-algorithm offline task whose not_done forbids a
browser / JSRPC runtime. A degraded solution whose outcome checker stays
green must still turn RED at the oracle because the witness check trips.
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

import goal_operationalization as go  # noqa: E402
from e2e import constraint_witness as cw  # noqa: E402

TS = "2026-10-14T00:00:00Z"

ROW_BROWSER = ("a runtime depending on a browser, JS RPC or remote "
               "execution does not count as done")
ROW_FACTS = ("parameters asserted without a fact file and evidence "
             "pointer do not count as done")

# the witness probe: the constraint holds iff no browser dependency
# artifact sits in the workspace (exit 0 = holds, non-zero = violation)
CHECK_BROWSER = "test ! -e browser.dep"


def _doc(**over) -> dict:
    """A fully-witnessed operationalization; `constraint_witness` can be
    popped by callers that need the bare / partial shapes."""
    doc = {
        "schema": go.SCHEMA_ID,
        "verbatim_ref": "task-oracle.yaml",
        "declared_ts": TS,
        "generalization": "required",
        "deliverables": ["a pure-algorithm offline capture pipeline"],
        "acceptance": ["fresh-input probe accepted with the runtime offline"],
        "not_done": [ROW_BROWSER, ROW_FACTS],
        "diff_vs_verbatim": ["adds: offline is operationalized as no "
                             "browser/JSRPC runtime dependency"],
        "probe_cases": ["fresh-input: capture for an input never seen"],
        "constraint_witness": {
            "schema": go.WITNESS_SCHEMA,
            "witnesses": {
                ROW_BROWSER: {"check": CHECK_BROWSER},
                ROW_FACTS: {"none": "fact-file presence is priced by the "
                                    "promotion gate, not separable here"},
            },
        },
        "oracle_behavior_acknowledged": True,
    }
    doc.update(over)
    return doc


def _write(tmp_path: Path, doc: dict) -> Path:
    return go.dump(tmp_path / "goal-operationalization.yaml", doc)


def _workspace(tmp_path: Path, name: str, doc: dict) -> Path:
    ws = tmp_path / name
    ws.mkdir()
    go.dump(ws / "goal-operationalization.yaml", doc)
    return ws


# ---------------------------------------------------------------------------
# lint: a not_done entry with no witness is refused (non-zero exit)
# ---------------------------------------------------------------------------

def test_not_done_without_witness_is_refused_at_lint(tmp_path, capsys):
    # (a) no constraint_witness block at all
    bare = _doc()
    bare.pop("constraint_witness")
    path = _write(tmp_path, bare)
    rc = go.main([str(path)])
    assert rc != 0, "a not_done list with no witness block must not lint clean"
    report = json.loads(capsys.readouterr().out)
    assert any("witness" in e for e in report["errors"]), report

    # (b) partial coverage: one row unwitnessed stays refused
    partial = _doc()
    partial["constraint_witness"]["witnesses"].pop(ROW_BROWSER)
    path2 = _write(tmp_path, partial)
    rc2 = go.main([str(path2)])
    assert rc2 != 0, "an unwitnessed not_done row must fail the lint"
    report2 = json.loads(capsys.readouterr().out)
    assert any("witness" in e for e in report2["errors"]), report2

    # (c) full coverage — check: and none: both legal — exits zero
    path3 = _write(tmp_path, _doc())
    assert go.main([str(path3)]) == 0, capsys.readouterr().out

    # stamping follows the same refusal: no witness, no dispatch freeze
    with pytest.raises(go.GoalOpError):
        go.stamp_dispatch(bare, TS)


# ---------------------------------------------------------------------------
# oracle: a violating deliverable is RED even when the outcome is green
# ---------------------------------------------------------------------------

def test_degraded_solution_with_green_outcome_fails_oracle(tmp_path):
    # the degraded solution left a browser-in-the-loop dependency behind
    # its accepted-request path; the outcome checker would stay green
    degraded = _workspace(tmp_path, "degraded", _doc())
    (degraded / "browser.dep").write_text("playwright\n", encoding="utf-8")

    witness = cw.evaluate(degraded, repo=tmp_path)
    assert witness["status"] == cw.FAIL, witness
    violated = [e["constraint"] for e in witness["entries"]
                if e["verdict"] == "violation"]
    assert ROW_BROWSER in violated, witness
    holds = [e["constraint"] for e in witness["entries"]
             if e["verdict"] in ("holds", "declared-none")]
    assert ROW_FACTS in holds, witness
    # green outcome (checker PASS) must NOT rescue the violated row
    assert cw.joint("PASS", witness["status"]) == cw.FAIL

    # control: the same document over a clean workspace stays green
    clean = _workspace(tmp_path, "clean", _doc())
    assert cw.evaluate(clean, repo=tmp_path)["status"] == cw.PASS


# ---------------------------------------------------------------------------
# joint verdict: witness AND outcome, fail-open on an undeclared workspace
# ---------------------------------------------------------------------------

def test_joint_verdict_requires_witness_and_outcome(tmp_path):
    # truth table: only witness PASS + outcome PASS yields PASS
    assert cw.joint("PASS", "PASS") == "PASS"
    assert cw.joint("PASS", "FAIL") == "FAIL"
    assert cw.joint("FAIL", "PASS") == "FAIL"
    assert cw.joint("FAIL", "FAIL") == "FAIL"

    # fail-open + warn: a pre-contract workspace (no goal-op file, no
    # witness block) evaluates to UNDECLARED with warnings and never
    # blocks the outcome leg
    bare = tmp_path / "bare-ws"
    bare.mkdir()
    result = cw.evaluate(bare, repo=tmp_path)
    assert result["status"] == cw.UNDECLARED, result
    assert result["warnings"], "the undeclared posture must warn loudly"
    assert cw.joint("PASS", result["status"]) == "PASS"

    blockless = _doc()
    blockless.pop("constraint_witness")
    ws = _workspace(tmp_path, "blockless", blockless)
    result2 = cw.evaluate(ws, repo=tmp_path)
    assert result2["status"] == cw.UNDECLARED, result2
    assert result2["warnings"]
