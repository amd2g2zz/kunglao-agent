# -*- coding: utf-8 -*-
"""tests/test_signal_arrival_1005.py — the signal-arrival probe (slice N0).

``scripts/rlvr/signal_arrival.py <workspace>`` is a READ-ONLY report on a
workspace: seven counts that say how far a learning signal travelled
(candidates -> staged dispatch decisions -> ledger rows -> settlement ->
credit -> posterior), each a number or the explicit string ``no data``.
Three defect classes sit behind the tests:

  - a count reading 0 where nothing was ever recorded: 0 and ``no data``
    are different facts, and reading "no settlement" off a file that does
    not exist is the error this report exists to prevent;
  - a "read-only" report that writes: the canonical ``warn`` appends a row
    to the run log of whatever workspace it finds from the cwd
    (scripts/kunglao_log.py:138-182), and the ledger faces touch lock
    files, so a report built on those readers is not read-only;
  - a malformed line crashing the report, or being swallowed unreported.

Workspaces are built through the public faces production calls:
``claims_store.begin_dispatch`` + ``q_cells.record_dispatch_observation``
write the dispatch rows, ``q_cells.observe_settlement`` / ``amend_settlement``
/ ``observe_step_credit`` the credit rows and — with the warn workspace
pinned through ``kunglao_log.set_warn_workspace`` — the real unmatched warn
row in the run log; ``priors.seed_intake_prior`` the intake prior;
``compose.write_seam`` the strategy seam; ``policy_state.run_face`` the
policy-state projection. Two artifacts have no public writer and are
written in their production shape: the staged decision receipt
(hooks/worker_budget_sinks.py:740-749) and the plan receipt
(hooks/dispatch_gate.py:1022-1029).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _rl_e2e as H
import claims_store
import kunglao_log
import policy_state
from rlvr import compose, consolidated_ledger, priors, q_cells, strategy_store

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rlvr" / "signal_arrival.py"

#: the seven counts, in the order the slice spec lists them.
COUNT_NAMES = (
    "candidate_families",
    "dispatch_decisions",
    "settlement",
    "credit_rows",
    "posterior",
    "hypothesis_resolution_rows",
    "method_lead",
)

LEDGER = "runs/experience.jsonl"
DISPATCH_LEDGER = "runs/dispatch-ledger.jsonl"
DECISIONS = "runs/.dispatch-decisions"

#: 2020-01-01T00:00:00Z — older than any write a test or the report makes.
FROZEN_MTIME = 1_577_836_800

FAMILIES = ("static-triage", "dynamic-trace")

_STRATEGY_WITH_LEAD = {
    "schema": "round-strategy/1", "tick": 3,
    "dispatch": {"method_lead": "static-triage", "anti_hints": [],
                 "budget_hint": None},
    "loop": {"monitor_focus": [], "ping_policy": "n/a", "stall_rules": []},
    "hooks": {"cards": []}, "amendments": [],
    "debt": {"D": 0.0, "slope": None, "top": None},
    "refutation": {"rate": 0.0, "multiplier": 1.0},
}


# --------------------------------------------------------------- workspace

def _dispatch(ws: Path, claim: str, family: str, *, sampler_view=None) -> str:
    """The production dispatch transaction plus the q-cell dispatch row —
    the shape of ``_rl_e2e.dispatch_round``, threading the sampler view the
    dispatch gate passes. Returns the dispatch id."""
    meta = {"method_family": family, "action_type": "dispatch", "tier": 1}
    prompt = ("# dispatch\n\n```json\n"
              + json.dumps({"kunglao_dispatch": meta}) + "\n```\n")
    intent = claims_store.begin_dispatch(
        ws, claim, actor="e2e-orchestrator", tier=1, prompt=prompt,
        method_family=family, branch_budget={"wall_s": 600, "retries": 1})
    assert intent.ok, f"begin_dispatch refused: {intent.reason}"
    commit = claims_store.commit_dispatch(ws, claim)
    assert commit.ok, f"commit_dispatch refused: {commit.reason}"
    observed = q_cells.record_dispatch_observation(
        ws, prompt, envelope_meta=meta, claim=claim,
        dispatch_id=commit.journal_id, sampler_view=sampler_view)
    assert observed["appended"], f"q-cell dispatch row not appended: {observed}"
    return str(commit.journal_id)


def _write_lines(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()]


def _plan_receipt(claim: str, dispatch_cell: tuple[float, float], ts: str) -> dict:
    """One plan-receipt/1 row in the gate's shape (hooks/dispatch_gate.py)."""
    return {
        "schema": "plan-receipt/1", "ts": ts, "claim": claim,
        "state_signature": "44480d5e686b",
        "admitted": [f"dispatch/{claim}"], "chosen": f"dispatch/{claim}",
        "candidates": {
            f"dispatch/{claim}": {"action_kind": "dispatch", "cost": 1.0,
                                 "ratio": 1.0, "theta": 0.5,
                                 "alpha": dispatch_cell[0],
                                 "beta": dispatch_cell[1]},
            f"park/{claim}": {"action_kind": "park", "cost": 0.0, "ratio": 0.0,
                              "theta": 0.5, "alpha": 1.0, "beta": 1.0},
        },
    }


def _stage_receipt(ws: Path, dispatch_id: str, candidates: dict) -> Path:
    """One staged decision receipt in the hook's shape
    (hooks/worker_budget_sinks.py:740-749)."""
    call_key = "d" * 64
    path = ws / DECISIONS / f"{dispatch_id}-{call_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "tool_call_key": call_key, "input_sha256": "e" * 64,
        "claim": "C-004", "agent": "kunglao-redteam", "dispatch_id": dispatch_id,
        "tier": 1, "tools": ["Read"],
        "sampler_view": {"actual_method_family": "static-triage",
                         "sampled_family": "static-triage",
                         "candidates": candidates},
        "signature": "44480d5e686b",
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _arrived(tmp_path: Path, *, first_dispatch_receipt: bool = True) -> dict:
    """A workspace where the signal travelled, stalled and missed:

    - C-001 dispatched with a two-candidate sampling receipt, credited 1.0,
      then amended to 0.5;
    - C-002 dispatched without a recorded receipt, credited 0.3;
    - C-003 dispatched, never settled (pending forever);
    - C-777 never dispatched, yet credited through the pool bridge;
    - C-009 and C-010 settled with no pending dispatch row (unmatched);
    - C-888 the same miss on the step-credit face (a sibling warning);
    - one staged receipt, two hypothesis-resolution rows, a strategy seam
      with a lead, two plan receipts whose dispatch cells differ.
    """
    ws = H.build_workspace(tmp_path, seed=0, n_claims=4)
    kunglao_log.set_warn_workspace(ws)  # warns land in THIS run log
    priors.seed_intake_prior(ws, families=FAMILIES)
    view = strategy_store.method_decision(
        {"family": "static-triage",
         "candidates": {"static-triage": {"weight": 0.6},
                        "dynamic-trace": {"weight": 0.4}}}, None)
    ids = {
        "C-001": _dispatch(ws, "C-001", "static-triage",
                           sampler_view=view if first_dispatch_receipt else None),
        "C-002": _dispatch(ws, "C-002", "dynamic-trace"),
        "C-003": _dispatch(ws, "C-003", "static-triage"),
    }
    assert q_cells.observe_settlement(ws, ids["C-001"], 1.0)["appended"]
    assert q_cells.observe_settlement(ws, ids["C-002"], 0.3)["appended"]
    assert q_cells.amend_settlement(ws, ids["C-001"], 0.5)["appended"]
    bridged = q_cells.observe_step_credit(ws, "C-777", 0.3,
                                          method_family="static-triage")
    assert bridged["reason"] == "bridged", bridged
    assert q_cells.observe_settlement(ws, "C-009", 1.0)["reason"] == "unmatched"
    assert q_cells.observe_settlement(ws, "C-010", 1.0)["reason"] == "unmatched"
    assert q_cells.observe_step_credit(ws, "C-888", 0.3)["reason"] == "unmatched"
    for hypothesis in ("H-001", "H-002"):
        assert consolidated_ledger.append(ws, "experience", {
            "schema": "hypothesis-resolution/1", "ts": "2026-11-01T00:00:00Z",
            "hypothesis": hypothesis, "claim_ref": "C-001",
            "evidence_kind": "verified-fact", "evidence_ref": "F-001",
            "dphi": 0.1, "credit": 0.1, "band": "NEUTRAL"})
    assert compose.write_seam(ws, _STRATEGY_WITH_LEAD)["written"]
    _write_lines(ws / "runs" / "plan-receipts.jsonl", [
        _plan_receipt("C-001", (1.0, 1.0), "2026-11-01T00:00:00Z"),
        _plan_receipt("C-002", (2.0, 1.0), "2026-11-01T00:00:01Z"),
    ])
    assert policy_state.run_face(ws)
    staged = _stage_receipt(ws, "c" * 12,
                            {"static-triage": {"weight": 1.0}})
    # staged BEFORE the ledger row of the same dispatch, as the hook does
    old = FROZEN_MTIME - 86_400
    os.utime(staged, (old, old))
    return {"ws": ws, "ids": ids}


@pytest.fixture
def build(tmp_path):
    """Build arrived workspaces under tmp_path; the pinned warn workspace
    (a process-global slot) is released after the test."""
    def _make(**options) -> dict:
        return _arrived(tmp_path, **options)
    yield _make
    kunglao_log.set_warn_workspace(None)


@pytest.fixture
def arrived(build) -> dict:
    return build()


# ------------------------------------------------------------------ the CLI

def _run(workspace=None, *, cwd=None, env=None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPT)]
    if workspace is not None:
        argv.append(str(workspace))
    return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          cwd=cwd, env=env)


def _report(workspace) -> dict:
    proc = _run(workspace)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def _counts(report: dict) -> dict:
    assert report["schema"] == "signal-arrival/1", report.get("schema")
    return report["counts"]


def _leaf(report: dict, path: str) -> dict:
    """One count leaf by dotted path: ``_leaf(report, "settlement.unmatched")``."""
    node = _counts(report)
    for part in path.split("."):
        node = node[part]
    return node


def _leaves(node, path: str = "counts"):
    """Every count leaf ({``value``: ...}) under ``node`` with its dotted path."""
    if not isinstance(node, dict):
        return
    if "value" in node:
        yield path, node
        return
    for key, value in node.items():
        yield from _leaves(value, f"{path}.{key}")


def _blanks(node, path: str = "counts"):
    """Dotted paths of blank fields under ``node``: None, an empty string,
    an empty list."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _blanks(value, f"{path}.{key}")
    elif isinstance(node, list):
        if not node:
            yield path
        for index, value in enumerate(node):
            yield from _blanks(value, f"{path}[{index}]")
    elif node is None or node == "":
        yield path


#                                                     the command line

def test_command_prints_one_json_report_with_the_seven_counts(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert tuple(_counts(report)) == COUNT_NAMES


def test_missing_workspace_is_a_usage_error_not_an_empty_report(tmp_path):
    # Act
    proc = _run(tmp_path / "nowhere")

    # Assert
    # a typo'd path printed as "every count: no data" would read as a workspace
    assert proc.returncode == 64, (proc.returncode, proc.stderr)
    assert proc.stdout == ""


def test_missing_workspace_argument_is_a_usage_error():
    # Act
    proc = _run()

    # Assert
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "usage:" in proc.stderr, proc.stderr


def test_a_home_relative_workspace_path_is_read_not_reported_empty(tmp_path):
    # Arrange
    home = tmp_path / "home"
    ws = home / "ws"
    ws.mkdir(parents=True)
    _write_lines(ws / LEDGER,
                 [{"schema": "hypothesis-resolution/1", "ts": "2026-11-01T00:00:00Z"}])
    env = {**os.environ, "HOME": str(home)}

    # Act
    proc = _run("~/ws", env=env)

    # Assert
    # an unexpanded "~" resolves no file: every count would read "no data"
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert _leaf(json.loads(proc.stdout),
                 "hypothesis_resolution_rows")["value"] == 1


#                                                     the blank-free contract

@pytest.mark.parametrize("count", COUNT_NAMES)
def test_every_count_is_explicit_on_an_empty_workspace(tmp_path, count):
    # Arrange
    ws = tmp_path / "empty"
    ws.mkdir()

    # Act
    report = _report(ws)

    # Assert
    section = _counts(report)[count]
    leaves = dict(_leaves(section, count))
    assert leaves, f"{count}: the empty workspace carries no count at all"
    # "no data" always names why — never a blank, never a bare 0
    assert not list(_blanks(section, count)), list(_blanks(section, count))
    numbered = [path for path, leaf in leaves.items()
                if leaf["value"] != "no data"]
    assert numbered == [], f"an empty workspace reported a number: {numbered}"
    assert all(leaf.get("reason") for leaf in leaves.values())
    for field in ("coverage", "moved"):
        if field in section:
            assert section[field] == "no data", f"{count}.{field}"


def test_no_field_of_any_count_is_blank_on_a_populated_workspace(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert not list(_blanks(_counts(report))), list(_blanks(_counts(report)))
    assert not list(_blanks(report["workspace_build"], "workspace_build"))


#                              1. candidate families at the first dispatch

def test_first_dispatch_candidates_are_read_from_the_sampling_receipt(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    first = _leaf(report, "candidate_families.first_dispatch")
    assert first["value"] == 2, first
    assert first["families"] == sorted(FAMILIES), first
    # the ledger row outranks the older staged receipt (1 candidate)
    assert first["source"] == "ledger dispatch row", first


def test_intake_prior_families_are_counted_on_their_own(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    prior = _leaf(report, "candidate_families.llm_prior")
    assert prior["value"] == 2, prior
    assert prior["families"] == sorted(FAMILIES), prior


def test_first_dispatch_without_a_recorded_receipt_is_no_data_not_zero(build):
    # Arrange
    arrived = build(first_dispatch_receipt=False)  # a row older than the candidates column

    # Act
    report = _report(arrived["ws"])

    # Assert
    first = _leaf(report, "candidate_families.first_dispatch")
    assert first["value"] == "no data", first
    assert "sampling receipt" in first["reason"], first


def test_candidates_come_from_the_earliest_staged_receipt_while_no_row_landed(
        tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    later = _stage_receipt(ws, "b" * 12, {"static-triage": {"weight": 1.0}})
    first = _stage_receipt(
        ws, "a" * 12, {"static-triage": {"weight": 0.5},
                       "dynamic-trace": {"weight": 0.5},
                       "crypto-core-identification": {"weight": 0.5}})
    os.utime(first, (FROZEN_MTIME, FROZEN_MTIME))
    os.utime(later, (FROZEN_MTIME + 60, FROZEN_MTIME + 60))

    # Act
    report = _report(ws)

    # Assert
    staged = _leaf(report, "candidate_families.first_dispatch")
    assert staged["value"] == 3, staged
    assert staged["source"] == "staged receipt", staged


#                         2. staged receipts and ledger dispatch rows

def test_staged_receipts_and_ledger_dispatch_rows_are_counted_apart(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "dispatch_decisions.staged_receipts")["value"] == 1
    assert _leaf(report, "dispatch_decisions.ledger_dispatch_rows")["value"] == 3


def test_deferred_credit_files_are_not_counted_as_staged_receipts(arrived):
    # Arrange
    deferred = arrived["ws"] / DECISIONS / "z999.credit.json"
    deferred.write_text('{"dispatch_id": "z999"}', encoding="utf-8")

    # Act
    report = _report(arrived["ws"])

    # Assert
    # the directory holds two kinds; a blind "*.json" count would say 2
    assert _leaf(report, "dispatch_decisions.staged_receipts")["value"] == 1
    assert _leaf(report, "settlement.deferred_credit_files")["value"] == 1


def test_dispatch_rows_are_joined_to_the_dispatch_ledger_by_id(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "dispatch_decisions.rows_reachable_by_dispatch_id")["value"] == 3
    assert _leaf(report, "dispatch_decisions.rows_without_dispatch_id")["value"] == 0


def test_dispatch_rows_are_unreachable_when_the_two_ledgers_hold_different_ids(
        arrived):
    # Arrange
    # an older build's shape, seen on a real workspace: the q-cell row and
    # the dispatch ledger carry two different ids for the same dispatch
    ledger = arrived["ws"] / DISPATCH_LEDGER
    rows = _read_lines(ledger)
    for row in rows:
        row["dispatch_id"] = "0" * 12
    _write_lines(ledger, rows)

    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "dispatch_decisions.rows_reachable_by_dispatch_id")["value"] == 0


def test_dispatch_rows_of_an_older_build_carry_no_dispatch_id(arrived):
    # Arrange
    # an older build's shape, seen on a real workspace: dispatch rows
    # keyed by claim only
    ledger = arrived["ws"] / LEDGER
    rows = _read_lines(ledger)
    for row in rows:
        if row.get("source") == "dispatch":
            row["dispatch_id"] = None
    _write_lines(ledger, rows)

    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "dispatch_decisions.rows_without_dispatch_id")["value"] == 3
    assert _leaf(report, "dispatch_decisions.rows_reachable_by_dispatch_id")["value"] == 0


#                    3. settlement attempts and the unmatched ones

def test_attempts_are_the_settlement_banks_plus_the_unmatched_warn_rows(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    # observe_settlement ran four times in this workspace: C-001 and C-002
    # matched a pending dispatch row (two ledger rows), C-009 and C-010
    # found none (two warn rows). The ledger holds four credit rows; the
    # other two are not settlement attempts (the test below)
    assert _leaf(report, "settlement.banked")["value"] == 2
    assert _leaf(report, "settlement.unmatched")["value"] == 2
    assert _leaf(report, "settlement.attempts")["value"] == 4


def test_credit_rows_of_other_faces_are_not_settlement_attempts(arrived):
    # Arrange
    # the ledger already holds one amendment (C-001) and one bridged step
    # credit (C-777); add the claim-terminal calibration of C-003
    calibrated = q_cells.observe_step_calibration(arrived["ws"], "C-003", 0.1)
    assert calibrated["appended"], calibrated

    # Act
    report = _report(arrived["ws"])

    # Assert
    # three credit rows that no call of observe_settlement wrote: each is
    # counted under its own face
    assert _leaf(report, "settlement.other_credit_rows")["value"] == {
        "step": 1, "step_calibration": 1, "credit_amendment": 1}


def test_unmatched_counts_the_settlement_face_only_not_its_siblings(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    # C-888's "no pending dispatch row" comes from observe_step_credit
    unmatched = _leaf(report, "settlement.unmatched")
    assert unmatched["dispatch_ids"] == ["C-009", "C-010"], unmatched


def test_a_repeated_unmatched_warning_stays_one_dispatch_id(arrived):
    # Arrange
    # a later process re-settles C-009 and warns again (per-process dedupe)
    kunglao_log.emit(arrived["ws"], "telemetry", "warn", detail=(
        "q_cells: q_cells.observe_settlement: no pending dispatch row for "
        "'C-009' — credit not banked (the honest gap)"))

    # Act
    report = _report(arrived["ws"])

    # Assert
    unmatched = _leaf(report, "settlement.unmatched")
    assert unmatched["value"] == 3, unmatched
    assert unmatched["dispatch_ids"] == ["C-009", "C-010"], unmatched


def test_an_unmatched_settlement_called_with_an_empty_id_is_listed_by_a_word(
        arrived):
    # Arrange
    # what observe_settlement does when called with an empty id: no row
    # matches, and its warn text carries the empty id between the quotes
    called = q_cells.observe_settlement(arrived["ws"], "", 1.0)
    assert called["reason"] == "unmatched", called

    # Act
    report = _report(arrived["ws"])

    # Assert
    # the row is real and is listed; no field under counts is an empty string
    unmatched = _leaf(report, "settlement.unmatched")
    assert unmatched["dispatch_ids"] == ["(no dispatch id)", "C-009", "C-010"], unmatched


#                                           4. credit rows by dispatch id

def test_credit_rows_are_booked_under_their_dispatch_id(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "credit_rows.booked")["value"] == 4
    assert _leaf(report, "credit_rows.by_dispatch_id")["value"] == {
        arrived["ids"]["C-001"]: 2, arrived["ids"]["C-002"]: 1, "C-777": 1}


def test_credit_whose_dispatch_row_never_arrived_is_listed_apart(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "credit_rows.ids_with_dispatch_row")["value"] == 2
    orphan = _leaf(report, "credit_rows.ids_without_dispatch_row")
    assert orphan["value"] == 1, orphan
    assert orphan["dispatch_ids"] == ["C-777"], orphan


def test_no_credit_rows_is_the_number_zero_with_an_empty_breakdown(arrived):
    # Arrange
    ledger = arrived["ws"] / LEDGER
    kept = [row for row in _read_lines(ledger)
            if not (row.get("schema") == "q-cell-obs/1"
                    and isinstance(row.get("credit"), (int, float)))]
    _write_lines(ledger, kept)

    # Act
    report = _report(arrived["ws"])

    # Assert
    # 0 rows booked is a fact about a ledger that exists; not "no data"
    assert _leaf(report, "credit_rows.booked")["value"] == 0
    assert _leaf(report, "credit_rows.by_dispatch_id")["value"] == {}
    # a list that names nothing is left out, never printed empty
    without_row = _leaf(report, "credit_rows.ids_without_dispatch_row")
    assert without_row["value"] == 0, without_row
    assert "dispatch_ids" not in without_row, without_row


#                                       5. posterior before and after

def test_posterior_is_reported_first_recorded_state_versus_last(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    posterior = _counts(report)["posterior"]
    assert posterior["coverage"] == "first-vs-last", posterior
    assert posterior["before"]["value"]["dispatch"] == {"alpha": 1.0, "beta": 1.0}
    assert posterior["after"]["value"]["dispatch"] == {"alpha": 2.0, "beta": 1.0}
    assert posterior["moved"] is True, posterior


def test_a_posterior_that_never_moved_reads_as_not_moved(arrived):
    # Arrange
    receipts = arrived["ws"] / "runs" / "plan-receipts.jsonl"
    rows = _read_lines(receipts)
    for row in rows:
        for cell in row["candidates"].values():
            cell["alpha"], cell["beta"] = 1.0, 1.0
    _write_lines(receipts, rows)

    # Act
    report = _report(arrived["ws"])

    # Assert
    posterior = _counts(report)["posterior"]
    assert posterior["moved"] is False, posterior
    assert posterior["coverage"] == "first-vs-last", posterior


def test_posterior_with_one_recorded_state_says_only_the_current_state_exists(
        arrived):
    # Arrange
    receipts = arrived["ws"] / "runs" / "plan-receipts.jsonl"
    receipts.write_text(receipts.read_text(encoding="utf-8").splitlines()[0] + "\n",
                        encoding="utf-8")

    # Act
    report = _report(arrived["ws"])

    # Assert
    posterior = _counts(report)["posterior"]
    assert posterior["coverage"] == "current-state-only", posterior
    assert posterior["before"]["value"] == posterior["after"]["value"]
    assert posterior["moved"] is False, posterior


def test_posterior_falls_back_to_the_policy_state_projection(arrived):
    # Arrange
    (arrived["ws"] / "runs" / "plan-receipts.jsonl").unlink()

    # Act
    report = _report(arrived["ws"])

    # Assert
    posterior = _counts(report)["posterior"]
    assert posterior["source"] == "runs/policy-state.json", posterior
    assert posterior["coverage"] == "current-state-only", posterior
    assert posterior["after"]["value"]["dispatch"] == {"alpha": 2.0, "beta": 1.0}


#                                   6. hypothesis-resolution rows

def test_hypothesis_resolution_rows_equal_the_canonical_liveness_count(arrived):
    # Arrange
    # the canonical reader itself: the report parses the ledger on its own
    # because this reader reaches kunglao_log.warn on a degraded path
    canonical = consolidated_ledger.liveness(arrived["ws"])[
        "experience:hypothesis-resolution/1"]

    # Act
    report = _report(arrived["ws"])

    # Assert
    # a consolidated-layout move must not make the two readers disagree
    assert _leaf(report, "hypothesis_resolution_rows")["value"] == canonical


def test_ledger_dispatch_rows_equal_the_canonical_dispatch_rows(arrived):
    # Arrange
    # the canonical reader itself (see the test above)
    canonical = len(q_cells.dispatch_rows(arrived["ws"]))

    # Act
    report = _report(arrived["ws"])

    # Assert
    # a consolidated-layout move must not make the two readers disagree
    assert _leaf(report, "dispatch_decisions.ledger_dispatch_rows")["value"] == canonical


def test_zero_hypothesis_resolution_rows_is_zero_when_the_ledger_exists(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_lines(ws / LEDGER,
                 [{"schema": "transition/1", "ts": "2026-11-01T00:00:00Z"}])

    # Act
    report = _report(ws)

    # Assert
    # 0 rows in a ledger that exists is a fact; "no data" would hide it
    assert _leaf(report, "hypothesis_resolution_rows")["value"] == 0


#                               7. the method lead in the strategy seam

def test_method_lead_is_read_from_the_strategy_seam(arrived):
    # Act
    report = _report(arrived["ws"])

    # Assert
    lead = _leaf(report, "method_lead")
    assert lead["value"] == 1, lead
    assert lead["lead"] == "static-triage", lead


def test_a_strategy_seam_without_a_lead_section_carries_no_lead(arrived):
    # Arrange
    seam = arrived["ws"] / "runs" / "round-strategy.json"
    seam.write_text(json.dumps({"schema": "round-strategy/1", "round": 4,
                                "sections": []}), encoding="utf-8")

    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "method_lead")["value"] == 0


#                         missing sources and damaged files

_MISSING = (
    ("dispatch_decisions.staged_receipts", DECISIONS),
    ("dispatch_decisions.rows_reachable_by_dispatch_id", DISPATCH_LEDGER),
    ("candidate_families.llm_prior", "runs/llm-prior.json"),
    ("settlement.unmatched", "runs/logs"),
    ("settlement.attempts", "runs/logs"),
    ("settlement.deferred_credit_files", DECISIONS),
    ("method_lead", "runs/round-strategy.json"),
)


def _without_sources(ws: Path) -> Path:
    """Take the sources of _MISSING off the workspace."""
    for rel in (DISPATCH_LEDGER, "runs/llm-prior.json", "runs/round-strategy.json"):
        (ws / rel).unlink()
    for rel in ("runs/logs", DECISIONS):
        shutil.rmtree(ws / rel)
    return ws


def test_a_missing_source_reads_no_data_and_names_it(arrived):
    # Arrange
    ws = _without_sources(arrived["ws"])

    # Act
    report = _report(ws)

    # Assert
    # a source that is not on disk is "no data" and names the source
    for path, source in _MISSING:
        leaf = _leaf(report, path)
        assert leaf["value"] == "no data", (path, leaf)
        assert source in leaf["reason"], (path, leaf)


def test_sources_still_on_disk_keep_their_numbers_beside_a_missing_one(arrived):
    # Arrange
    ws = _without_sources(arrived["ws"])

    # Act
    report = _report(ws)

    # Assert
    # what is still on disk is still counted — nothing is invented
    assert _leaf(report, "dispatch_decisions.ledger_dispatch_rows")["value"] == 3
    assert _leaf(report, "credit_rows.booked")["value"] == 4
    assert _leaf(report, "settlement.banked")["value"] == 2


def test_a_malformed_ledger_line_is_reported_and_the_other_rows_still_counted(
        arrived):
    # Arrange
    with (arrived["ws"] / LEDGER).open("a", encoding="utf-8") as stream:
        stream.write("{not json\n")

    # Act
    report = _report(arrived["ws"])

    # Assert
    assert _leaf(report, "hypothesis_resolution_rows")["value"] == 2
    assert report["files"][LEDGER]["malformed"] == 1, report["files"][LEDGER]


def test_a_ledger_of_malformed_lines_only_reads_no_data(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    (ws / LEDGER).parent.mkdir(parents=True)
    (ws / LEDGER).write_text("{not json\nnot json either\n", encoding="utf-8")

    # Act
    report = _report(ws)

    # Assert
    for path in ("hypothesis_resolution_rows",
                 "dispatch_decisions.ledger_dispatch_rows"):
        leaf = _leaf(report, path)
        assert leaf["value"] == "no data", leaf
        assert "unparsable" in leaf["reason"], leaf


@pytest.mark.parametrize("where, path", [
    ("ledger line", "hypothesis_resolution_rows"),
    ("strategy seam", "method_lead")])
def test_json_nested_past_the_decoder_limit_reads_unparsable_not_a_crash(
        tmp_path, where, path):
    # Arrange
    # valid JSON nested far past the decoder's recursion limit: the decoder
    # gives up with RecursionError, which is not a ValueError. No production
    # writer makes it — every row is one flat object
    nested = "[" * 1_000_000 + "]" * 1_000_000
    if where == "ledger line":
        rel, text = LEDGER, '{"schema": "transition/1", "x": ' + nested + "}\n"
    else:
        rel, text = ("runs/round-strategy.json",
                     '{"schema": "round-strategy/1", "x": ' + nested + "}\n")
    target = tmp_path / "ws" / rel
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")

    # Act
    report = _report(tmp_path / "ws")

    # Assert
    # what the decoder cannot read is "unparsable", like a line that is not JSON
    leaf = _leaf(report, path)
    assert leaf["value"] == "no data", leaf
    assert "unparsable" in leaf["reason"], leaf


@pytest.mark.parametrize("bad_id", [["C-1", "C-2"], {"id": "C-1"}],
                         ids=["list", "object"])
def test_a_dispatch_row_whose_id_is_not_a_string_is_reported_not_a_crash(
        tmp_path, bad_id):
    # Arrange
    # valid JSON of the wrong type: no production writer makes it, and a
    # set membership test on it raises
    ws = tmp_path / "ws"
    _write_lines(ws / LEDGER, [{
        "schema": "q-cell-obs/1", "source": "dispatch", "claim": "C-1",
        "dispatch_id": bad_id, "credit": None}])
    _write_lines(ws / DISPATCH_LEDGER, [{"dispatch_id": "abcdefabcdef"}])

    # Act
    report = _report(ws)

    # Assert
    # the row is still a dispatch row; it carries no usable id, so no
    # dispatch-ledger row can carry it
    assert _leaf(report, "dispatch_decisions.ledger_dispatch_rows")["value"] == 1
    assert _leaf(report, "dispatch_decisions.rows_without_dispatch_id")["value"] == 1
    assert _leaf(report, "dispatch_decisions.rows_reachable_by_dispatch_id")["value"] == 0


def _wrong_kind(ws: Path, source: str) -> None:
    """Put the wrong kind of entry where a source is read: a directory in
    place of a file, a file in place of a directory. Reading it raises
    OSError without any permission change, so the test needs none."""
    if source == "ledger":
        (ws / LEDGER).unlink()
        (ws / LEDGER).mkdir()
    elif source == "run log":
        shutil.rmtree(ws / "runs" / "logs")
        (ws / "runs" / "logs").write_text("not a directory", encoding="utf-8")
    else:
        shutil.rmtree(ws / DECISIONS)
        (ws / DECISIONS).write_text("not a directory", encoding="utf-8")


@pytest.mark.parametrize("source, leaves", [
    ("ledger", ("hypothesis_resolution_rows", "dispatch_decisions.ledger_dispatch_rows",
                "settlement.banked", "credit_rows.booked")),
    ("run log", ("settlement.unmatched", "settlement.attempts")),
    ("decisions", ("dispatch_decisions.staged_receipts",
                   "settlement.deferred_credit_files")),
])
def test_a_source_of_the_wrong_kind_reads_no_data_saying_unreadable(
        arrived, source, leaves):
    # Arrange
    _wrong_kind(arrived["ws"], source)

    # Act
    report = _report(arrived["ws"])

    # Assert
    # an entry that exists but cannot be read is "no data" with that
    # reason — never 0, never a crash
    for path in leaves:
        leaf = _leaf(report, path)
        assert leaf["value"] == "no data", (path, leaf)
        assert "unreadable" in leaf["reason"], (path, leaf)


#                                                         read-only

def _snapshot(root: Path) -> dict:
    """The root (key ``"."``) and every entry under it: kind, sha256 (files)
    and mtime_ns — of files, and of directories, because a file created and
    deleted under a directory moves that directory's mtime."""
    out = {".": ("dir", root.stat().st_mtime_ns)}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                out[rel] = ("symlink", os.readlink(path))
            elif path.is_dir():
                out[rel] = ("dir", path.stat().st_mtime_ns)
            else:
                out[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest(),
                            path.stat().st_mtime_ns)
    return out


def _freeze_mtimes(root: Path) -> None:
    """Pin the mtime of every file and of every directory (the root's too)
    to a fixed old instant, so neither a same-bytes rewrite (mtime -> now)
    nor a file created and deleted under a directory (the directory's mtime
    -> now) can pass as untouched. Symlinks are left alone: their target
    may be outside the workspace."""
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        if path.is_file() or path.is_dir():
            os.utime(path, (FROZEN_MTIME, FROZEN_MTIME))


@pytest.mark.parametrize("shape", ["populated", "bare"])
def test_report_leaves_every_file_untouched_and_creates_none(build, tmp_path, shape):
    # Arrange
    if shape == "populated":
        ws = build()["ws"]
        with (ws / LEDGER).open("a", encoding="utf-8") as stream:
            stream.write("{not json\n")
    else:
        ws = tmp_path / "bare"
        ws.mkdir()
    _freeze_mtimes(ws)
    before = _snapshot(ws)
    # worst case for the repo's warn ledger face: it resolves a workspace by
    # walking up from the cwd, and an outside store override makes the
    # knowledge-family resolver warn
    env = {**os.environ,
           "KUNGLAO_POSTERIOR_STORE": str(tmp_path / "outside-store")}

    # Act
    proc = _run(ws, cwd=ws, env=env)
    after = _snapshot(ws)

    # Assert
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    # exit 0, and a workspace that is what it was: every file's bytes and
    # mtime, every directory's mtime, no entry added or removed
    assert (proc.returncode == 0 and not (added or removed or changed)), {
        "exit": proc.returncode, "stderr": proc.stderr,
        "added": added, "removed": removed, "changed": changed}


def test_report_imports_only_the_standard_library():
    # Arrange
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    # Act / Assert
    # invariant of the read-only contract: no import edge to the repo means
    # no path to kunglao_log.warn's ledger face (scripts/kunglao_log.py:138-182)
    assert imported <= set(sys.stdlib_module_names), sorted(
        imported - set(sys.stdlib_module_names))


#                         which build the workspace ran on

def test_report_names_the_build_the_workspace_ran_on(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / ".init-report.json").write_text(
        json.dumps({"skill_version": "0.1.6-rc1"}), encoding="utf-8")
    # two checkouts wrote this run log; the first wrote twice
    for version in ("a" * 40, "a" * 40, "b" * 40):
        assert kunglao_log.emit(ws, "orchestrator", "dispatch", version=version)

    # Act
    report = _report(ws)

    # Assert
    build = report["workspace_build"]
    assert build["init_skill_version"] == {"value": "0.1.6-rc1"}, build
    assert build["run_log_versions"] == {"value": {
        "first": "a" * 40, "last": "b" * 40, "distinct": 2,
        "rows": {"a" * 40: 2, "b" * 40: 1}}}, build


def test_the_build_block_says_why_a_build_fact_is_no_data(tmp_path):
    # Arrange
    ws = tmp_path / "empty"
    ws.mkdir()

    # Act
    report = _report(ws)

    # Assert
    # numbers are labelled with their build; a label that is missing says
    # what is missing, where it stands
    build = report["workspace_build"]
    assert build["init_skill_version"] == {
        "value": "no data", "reason": "runs/.init-report.json: file missing"}, build
    assert build["run_log_versions"] == {
        "value": "no data", "reason": "runs/logs: directory missing"}, build
