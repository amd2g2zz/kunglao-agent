# -*- coding: utf-8 -*-
"""Tests for outcome_capture.py — external-checker verdicts -> ledger OUTCOME rows (#35).

RED phase of the outcome-capture-r6 change (GitHub #35). These tests pin the
contract before implementation:

- capture() reads runs/*.md verify-note / red-team verdicts and appends
  independent {"type":"outcome",...} rows to .convergence_ledger.jsonl.
- capture() is idempotent (same claim_id|checker|result not double-counted).
- read_outcome_rows() returns only OUTCOME rows (SNAPSHOT rows ignored).
- aggregate_reward() is a pure function: passes/CONFIRMED=1.0,
  partial/UNVERIFIED=0.5, fails/REFUTED=0.0; no data -> None (neutral, not 0.0).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_capture as oc  # noqa: E402


LEDGER = oc.LEDGER_NAME


def _ledger_rows(workspace: Path, rows: list[dict]) -> None:
    """Seed the ledger with raw rows (no capture), for additive-compat tests."""
    (workspace / LEDGER).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


# ---------- capture: verify-note ----------

def test_capture_writes_outcome_row(tmp_path):
    """verify-note passes -> ledger outcome row (independent type, aggregable)."""
    # Arrange
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "2026-08-11T00-00-00-verify-01-draft.md").write_text(
        "---\nclaim_id: C-1\nverify_status: passes\n---\n\n"
        "## Overall verdict\npasses\n",
        encoding="utf-8")

    # Act
    added = oc.capture(tmp_path)
    rows = oc.read_outcome_rows(tmp_path)

    # Assert
    assert added == 1
    assert len(rows) == 1
    assert rows[0]["type"] == "outcome"
    assert rows[0]["result"] == "passes"
    assert rows[0]["checker"] == "verify-note"
    assert rows[0]["claim_id"] == "C-1"
    assert "ts" in rows[0]


def test_capture_partial_and_fails_verdicts(tmp_path):
    """partial / fails values are extracted (tolerant of blank lines)."""
    # Arrange
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "a-verify-02.md").write_text(
        "## Overall verdict\n\npartial\n", encoding="utf-8")
    (runs / "b-verify-03.md").write_text(
        "## Overall verdict\n\n   fails\n", encoding="utf-8")

    # Act
    added = oc.capture(tmp_path)
    rows = oc.read_outcome_rows(tmp_path)

    # Assert
    assert added == 2
    results = sorted(r["result"] for r in rows)
    assert results == ["fails", "partial"]


# ---------- capture: red-team ----------

def test_capture_redteam_confirmed(tmp_path):
    """red-team CONFIRMED -> checker=red-team, claim_id extracted from body C-NNN."""
    # Arrange
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "verify-redteam-C-7.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\n\ntarget: C-7\n", encoding="utf-8")

    # Act
    added = oc.capture(tmp_path)
    rows = oc.read_outcome_rows(tmp_path)

    # Assert
    assert added == 1
    assert rows[0]["type"] == "outcome"
    assert rows[0]["result"] == "CONFIRMED"
    assert rows[0]["checker"] == "red-team"
    assert rows[0]["claim_id"] == "C-7"


def test_capture_redteam_unverified_with_gap(tmp_path):
    """UNVERIFIED-WITH-GAP variant is matched (scores 0.5)."""
    # Arrange
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "verify-redteam-C-8.md").write_text(
        "RED-TEAM VERDICT: UNVERIFIED-WITH-GAP\nclaim: C-8\n", encoding="utf-8")

    # Act
    oc.capture(tmp_path)
    rows = oc.read_outcome_rows(tmp_path)

    # Assert
    assert len(rows) == 1
    assert rows[0]["result"] == "UNVERIFIED-WITH-GAP"
    assert rows[0]["checker"] == "red-team"


# ---------- idempotency ----------

def test_dedup_same_claim_checker(tmp_path):
    """Duplicate verify is not double-counted (idempotent across two captures)."""
    # Arrange — both files fall back to filename as claim_id (no frontmatter);
    # same checker + result -> one row total even though two files + two calls.
    runs = tmp_path / "runs"
    runs.mkdir()
    for name in ("a-verify-01-draft.md", "b-verify-01-draft.md"):
        (runs / name).write_text("## Overall verdict\npasses\n", encoding="utf-8")

    # Act
    oc.capture(tmp_path)
    oc.capture(tmp_path)  # second call — idempotent

    # Assert
    rows = oc.read_outcome_rows(tmp_path)
    # Two distinct claim_ids (filenames) but same checker+result -> two rows
    # (claim_id differs). Idempotency holds per (claim_id, checker, result):
    # calling capture twice did NOT double either row.
    assert len(rows) == 2
    # Re-running capture must not add anything.
    oc.capture(tmp_path)
    assert len(oc.read_outcome_rows(tmp_path)) == 2


def test_dedup_same_claim_id_not_double_counted(tmp_path):
    """Same claim_id (from frontmatter) + same checker + same result -> ONE row."""
    # Arrange — two verify files sharing claim_id C-1, both passes.
    runs = tmp_path / "runs"
    runs.mkdir()
    fm = "---\nclaim_id: C-1\n---\n\n## Overall verdict\npasses\n"
    (runs / "a-verify-01.md").write_text(fm, encoding="utf-8")
    (runs / "b-verify-01.md").write_text(fm, encoding="utf-8")

    # Act
    oc.capture(tmp_path)

    # Assert
    rows = oc.read_outcome_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["claim_id"] == "C-1"


def test_changed_result_records_second_row(tmp_path):
    """Same claim + checker but result changed (partial->passes) -> two rows."""
    # Arrange — filename uses the real verify-note convention (<prefix>-verify-<id>.md)
    runs = tmp_path / "runs"
    runs.mkdir()
    vfile = runs / "2026-08-11T00-00-00-verify-01.md"
    vfile.write_text("## Overall verdict\npartial\n", encoding="utf-8")

    # Act
    oc.capture(tmp_path)  # records partial
    vfile.write_text("## Overall verdict\npasses\n", encoding="utf-8")
    oc.capture(tmp_path)  # records passes (different result -> new row)

    # Assert
    rows = oc.read_outcome_rows(tmp_path)
    assert len(rows) == 2
    assert sorted(r["result"] for r in rows) == ["partial", "passes"]


# ---------- aggregate_reward (pure) ----------

def test_aggregate_reward_values():
    """passes=1.0 / partial=0.5 / fails=0.0 / CONFIRMED=1.0 -> mean."""
    # Arrange
    rows = [
        {"type": "outcome", "claim_id": "C-1", "result": "passes", "checker": "verify-note"},
        {"type": "outcome", "claim_id": "C-2", "result": "partial", "checker": "verify-note"},
        {"type": "outcome", "claim_id": "C-3", "result": "fails", "checker": "verify-note"},
        {"type": "outcome", "claim_id": "C-4", "result": "CONFIRMED", "checker": "red-team"},
    ]

    # Act
    reward = oc.aggregate_reward(rows)

    # Assert
    assert reward == (1.0 + 0.5 + 0.0 + 1.0) / 4


def test_aggregate_reward_redteam_values():
    """CONFIRMED=1.0 / REFUTED=0.0 / UNVERIFIED=0.5."""
    # Arrange
    rows = [
        {"type": "outcome", "claim_id": "C-1", "result": "CONFIRMED", "checker": "red-team"},
        {"type": "outcome", "claim_id": "C-2", "result": "REFUTED", "checker": "red-team"},
        {"type": "outcome", "claim_id": "C-3", "result": "UNVERIFIED", "checker": "red-team"},
    ]

    # Act
    reward = oc.aggregate_reward(rows)

    # Assert
    assert reward == (1.0 + 0.0 + 0.5) / 3


def test_no_data_neutral():
    """No data -> None (neutral, not a false 0.0 signal)."""
    assert oc.aggregate_reward([]) is None


def test_aggregate_reward_pure_same_input_same_output():
    """Pure function: same input -> same output across calls."""
    # Arrange
    rows = [
        {"type": "outcome", "claim_id": "C-1", "result": "passes", "checker": "verify-note"},
        {"type": "outcome", "claim_id": "C-2", "result": "fails", "checker": "verify-note"},
    ]

    # Act / Assert
    assert oc.aggregate_reward(rows) == oc.aggregate_reward(rows)


# ---------- additive compatibility ----------

def test_snapshot_rows_ignored(tmp_path):
    """Snapshot rows (no type) do not participate in aggregation."""
    # Arrange
    _ledger_rows(tmp_path, [
        {"ts": "2026-08-11T00:00:00Z", "decision": "DISPATCH", "open_count": 3},
        {"type": "snapshot", "ts": "2026-08-11T00:01:00Z", "open_count": 2},
    ])

    # Act
    rows = oc.read_outcome_rows(tmp_path)
    reward = oc.aggregate_reward(rows)

    # Assert
    assert rows == []
    assert reward is None


def test_aggregate_reward_ignores_snapshot_rows():
    """aggregate_reward, even handed the full ledger, only aggregates OUTCOME."""
    # Arrange
    rows = [
        {"type": "outcome", "claim_id": "C-1", "result": "passes", "checker": "verify-note"},
        {"ts": "2026-08-11T00:00:00Z", "open_count": 3},  # SNAPSHOT (no type)
        {"type": "snapshot", "open_count": 2},
    ]

    # Act
    reward = oc.aggregate_reward(rows)

    # Assert — only the one outcome row counts -> 1.0
    assert reward == 1.0


# ---------- robustness ----------

def test_missing_runs_no_crash(tmp_path):
    """runs/ absent -> capture returns 0 (no crash)."""
    assert oc.capture(tmp_path) == 0
    assert oc.read_outcome_rows(tmp_path) == []


def test_malformed_ledger_lines_skipped(tmp_path):
    """Malformed (JSONDecodeError) and blank lines are skipped, not fatal."""
    # Arrange — ledger with junk + one valid outcome row
    (tmp_path / LEDGER).write_text(
        "\n"
        "not json\n"
        + json.dumps({"type": "outcome", "claim_id": "C-1",
                      "result": "passes", "checker": "verify-note"}) + "\n"
        "{broken\n",
        encoding="utf-8")

    # Act / Assert
    rows = oc.read_outcome_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["result"] == "passes"
