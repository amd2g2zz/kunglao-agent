# -*- coding: utf-8 -*-
"""tests/test_devkit_feedback_loop_772.py — the development mechanism's
feedback edge, as executable acceptance (issue #772).

Covers: the fingerprint spec's shape, the liveness gate in both
directions (a LIVE fixture workspace passes; an empty workspace — the
ctf-1 2026-10-18 shape, zero admissions and zero posterior movement —
must read RED), the verification and deferral gates' verdicts, the
escape-rate partition math, the invariant registry's cross-references,
and Gate 10's registration.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEVKIT = ROOT / "devkit"
for p in (str(ROOT), str(DEVKIT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, DEVKIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def lg():
    return _load("liveness_gate")


def _live_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    (ws / "runs" / "strategy-log.jsonl").write_text(
        json.dumps({"event": "dispatch", "strategy": "sampled",
                    "claim": "C-001"}) + "\n", encoding="utf-8")
    (logs / "kunglao-2026-10-18.jsonl").write_text(
        json.dumps({"action": "dispatch", "admitted": ["dispatch/C-001"],
                    "claim": "C-001"}) + "\n" +
        json.dumps({"action": "task_terminal_settlement",
                    "claim": "C-001"}) + "\n" +
        # issue 805: the closure battery's T2 + distill faces ride the
        # unified stream as their fired evidence
        json.dumps({"action": "t2_queue_built", "queued": 1}) + "\n" +
        json.dumps({"action": "distill_attempt", "phase": "triggered"})
        + "\n", encoding="utf-8")
    (ws / "runs" / "posterior-store.jsonl").write_text(
        json.dumps({"schema": "posterior-store/1", "arm": "method:static"})
        + "\n", encoding="utf-8")
    (ws / "runs" / "plan-receipts.jsonl").write_text(
        json.dumps({"schema": "plan-receipt/1", "claim": "C-001",
                    "admitted": ["dispatch/C-001"],
                    "chosen": "dispatch/C-001"}) + "\n", encoding="utf-8")
    # #769: the round close projects the policy-state surface — the
    # live-workspace contract grew the policy-state-fresh fingerprint.
    (ws / "runs" / "policy-state.json").write_text(
        json.dumps({"schema": "policy-state/1", "round": 1,
                    "claim": "C-001", "candidates": {},
                    "admitted": ["dispatch/C-001"],
                    "chosen": "dispatch/C-001",
                    "posterior": {}, "ts": "2026-10-18T00:00:00Z"})
        + "\n", encoding="utf-8")
    # issue-802: the live-workspace contract grew the
    # blind-settlement-wired fingerprint — a settlement-wire/1 row
    # carrying the settler identity (the blind face fired)
    (ws / "runs" / "settlement.jsonl").write_text(
        json.dumps({"schema": "settlement-wire/1",
                    "ts": "2026-10-24T00:00:00Z", "claim": "C-001",
                    "identity": "kunglao-settler", "settled": True})
        + "\n", encoding="utf-8")
    cases = ws / "oracle" / "cases"
    cases.mkdir(parents=True)
    (cases / "case-001.yaml").write_text(
        "channel: repl\nhypothesis_ref: H-001\nupdate_map: {}\n",
        encoding="utf-8")
    # issue 805: the live-workspace contract grew the HOOK battery
    # faces — ONE worker_battery pass row (every registered dispatch
    # check) is the per-check fingerprints' evidence; the closure
    # faces prove themselves on their own artifacts.
    checks = ",".join(sorted(
        ["stepsettled", "workers", "max_retries", "cap", "branchbudget",
         "tools", "hostchan", "deadline", "envelope", "tiercons", "tier",
         "selfcap", "heartbeat", "drift", "health", "envfresh",
         "envpremise", "backtrack", "zerooutput", "plan", "granularity",
         "toolfirst", "toolsearch", "handroll", "agenttype", "rotation",
         "methodfamily", "priority", "snapshot"]))
    (ws / "runs" / "gate-telemetry.jsonl").write_text(
        json.dumps({"gate": "worker_battery", "rc": 0, "msg": checks})
        + "\n", encoding="utf-8")
    (ws / "runs" / "step-ledger.jsonl").write_text(
        json.dumps({"schema": "step-record/2", "claim_ref": "C-001",
                    "outcome": "completed"}) + "\n", encoding="utf-8")
    strategy = ws / "runs" / "round-strategy"
    strategy.mkdir(parents=True)
    (strategy / "tick-0001.yaml").write_text(
        "schema: round-strategy/1\ntick: 1\n", encoding="utf-8")
    (ws / "runs" / ".rl-digest.json").write_text(
        json.dumps({"schema": "rl-digest/1", "round": 1,
                    "lead": None}) + "\n", encoding="utf-8")
    return ws


def test_fingerprints_schema_and_seeds():
    fps = json.loads(
        (DEVKIT / "liveness_fingerprints.json").read_text(encoding="utf-8"))
    assert fps["schema"] == "liveness-fingerprints/1"
    assert len(fps["fingerprints"]) >= 5
    ids = {f["id"] for f in fps["fingerprints"]}
    assert {"rl-sampler-exit", "rl-admission-consumed",
            "rl-posterior-moved"} <= ids


def test_liveness_ledger_green_on_live_fixture(lg, tmp_path):
    rc = lg.run_ledger(_live_ws(tmp_path))
    assert rc == 0


def test_liveness_ledger_red_on_decorative_workspace(lg, tmp_path):
    """The ctf-1 2026-10-18 shape: ledgers exist but zero admissions,
    zero posterior movement, default strategy — the gate MUST read
    this as RED (exit 1), never as a silent skip."""
    ws = tmp_path / "ws"
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    (ws / "runs" / "strategy-log.jsonl").write_text(
        json.dumps({"event": "dispatch", "strategy": "default",
                    "claim": "C-001"}) + "\n", encoding="utf-8")
    (logs / "kunglao-2026-10-18.jsonl").write_text(
        json.dumps({"action": "tick"}) + "\n", encoding="utf-8")
    rc = lg.run_ledger(ws)
    assert rc == 1


def test_posterior_sentinel_is_family_level(lg, tmp_path):
    """INV-003 is a FAMILY-level signal (the liveness upgrade card).

    The production-broadcast shape (both 2026-10 runs: settlement rows
    with arm=NULL broadcast same-value mass to case cells) must NOT
    satisfy rl-posterior-moved — key-less posterior movement is exactly
    the decorative case the sentinel exists to catch. The same store
    with ONE arm-keyed row passes: family attribution is the signal.
    """
    spec = next(f for f in lg.load_fingerprints()["fingerprints"]
                if f["id"] == "rl-posterior-moved")

    def _ws(name: str, rows: list[dict]) -> Path:
        ws = tmp_path / name
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "posterior-store.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return ws

    # case-level movement: rows exist but carry NO arm attribution
    bare = _ws("bare", [
        {"schema": "posterior-store/1", "arm_key": "", "method_family": "",
         "credit": 1.0, "claim": "C-001"},
        {"schema": "posterior-store/1", "arm": None, "state": "sig",
         "gamma": 0.8, "outcome": 1, "alpha_add": 1, "beta_add": 0},
    ])
    ok, detail = lg.evaluate_fingerprint(bare, spec)
    assert not ok, f"key-less rows satisfied the sentinel: {detail}"

    # the identical store, one row arm-keyed: family-level movement
    keyed = _ws("keyed", [
        {"schema": "posterior-store/1", "arm_key": "", "method_family": "",
         "credit": 1.0, "claim": "C-001"},
        {"schema": "posterior-store/1", "arm_key": "static",
         "method_family": "static", "credit": 1.0, "claim": "C-002"},
    ])
    ok, detail = lg.evaluate_fingerprint(keyed, spec)
    assert ok, f"arm-keyed movement did not pass: {detail}"


def test_liveness_missing_ledger_is_fail_not_skip(lg, tmp_path):
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    rc = lg.run_ledger(ws)
    assert rc == 1


def test_verification_gate_verdicts():
    vg = _load("verification_gate")
    good = vg.check_body("## Summary\nx\n\n## Verification\n\n```\n"
                         "uv run pytest tests/x.py\n```\n")
    assert good[0]
    bad = vg.check_body("## Summary\nno verification section\n")
    assert not bad[0] and "Verification" in bad[1]
    empty = vg.check_body("## Verification\n\nnothing fenced\n")
    assert not empty[0] and "fenced" in empty[1]


def test_verification_gate_fence_output_comments_are_not_headings():
    """Regression (first live body): an output comment like
    '# 10 passed' inside the fence must not terminate the section."""
    vg = _load("verification_gate")
    body = ("## Verification\n\n```\nuv run pytest tests/x.py -q\n"
            "# 10 passed in 0.38s\n```\n")
    ok, why = vg.check_body(body)
    assert ok, why


def test_deferral_guard_verdicts():
    dg = _load("deferral_guard")
    ok_none = dg.check_body("a plain body", [])
    assert ok_none[0]
    bad = dg.check_body("the executor lands later in a follow-up", [])
    assert not bad[0] and "linked issue" in bad[1]
    ok_linked = dg.check_body("the executor lands later",
                              ["#773"])
    assert ok_linked[0]


def test_escape_rate_partition():
    er = _load("escape_rate")
    issues = [
        {"createdAt": "2026-10-17T10:00:00Z", "number": 1},
        {"createdAt": "2026-10-19T10:00:00Z", "number": 2},
        {"createdAt": "2026-10-01T10:00:00Z", "number": 3},
    ]
    r = er.compute_rate(issues, "2026-10-18", since="2026-10-15")
    assert r == {"release_total": 2, "pre": 1, "post": 1,
                 "escape_rate": 50.0, "escaped_issues": [2]}


def test_invariant_registry_cross_references():
    inv = json.loads((DEVKIT / "invariants" / "registry.json")
                     .read_text(encoding="utf-8"))
    assert inv["schema"] == "invariants/1"
    assert len(inv["invariants"]) >= 8
    fps = json.loads((DEVKIT / "liveness_fingerprints.json")
                     .read_text(encoding="utf-8"))
    fp_ids = {f["id"] for f in fps["fingerprints"]}
    for i in inv["invariants"]:
        if i.get("fingerprint") is not None:
            assert i["fingerprint"] in fp_ids, i["id"]


def test_gate10_registered_in_gates():
    qg = _load("quality_gates")
    assert 10 in qg.GATES
    assert qg.GATES[10][0] == "Liveness"


def test_spec_coverage_flags_open_change_without_contract(
        tmp_path, monkeypatch):
    sc = _load("spec_coverage")
    changes = tmp_path / "changes" / "issue-900-example"
    changes.mkdir(parents=True)
    (changes / "tasks.md").write_text("- [ ] do the thing\n",
                                      encoding="utf-8")
    (changes / "proposal.md").write_text(
        "a proposal citing INV-001 but no contract section\n",
        encoding="utf-8")
    violations = sc.check_change(changes, {"INV-001"})
    assert any("Integration contract" in v for v in violations)
    assert not any("invariant citation" in v for v in violations)
