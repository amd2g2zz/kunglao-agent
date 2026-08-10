"""RED tests for CONVERGED completeness gate (issue #17, PRD M2).

TDD: these tests exercise _orphan_terminal_claims, _unverified_primary_questions,
and the SPINNING flatline guard — functions that do NOT exist yet → RED.

Covers:
  RED1: orphan claim terminal → NOT CONVERGED (downgrade with reason)
  RED2: primary_question with STAMP/unverified answering claim → NOT CONVERGED
  RED3: SPINNING real flatline → detected (not falsely dedup'd away)
  RED4: all primary_q PROVEN + zero orphan → CONVERGED (regression, happy path)
"""
from __future__ import annotations

import json
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from convergence_check import decide, _open_claims
from convergence_health import assess, _dedup_consecutive, _flatline_run


# ---------- helpers ----------

VALID_SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w2
      refute_attempt: "tried X, Y, Z to break; held"
      sign_off_at: 2026-08-10T14:00:00Z
      verdict: CONFIRMED
    ```
    """)


def _make_ws(tmp_path: Path, claims: list[dict], primary_questions: list | None = None,
             facts: dict[str, str] | None = None) -> Path:
    """Build a synthetic workspace with claim-register + task_spec + facts."""
    ws = tmp_path / f"ws-{len(list(tmp_path.iterdir()))}"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()

    # claim-register.yaml
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        for k, v in c.items():
            if k != "id":
                if isinstance(v, str):
                    lines.append(f"  {k}: {v}")
                elif isinstance(v, bool):
                    lines.append(f"  {k}: {str(v).lower()}")
                elif isinstance(v, list):
                    lines.append(f"  {k}: {json.dumps(v)}")
                else:
                    lines.append(f"  {k}: {v}")
    (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # task_spec.yaml with primary_questions
    ts_lines = []
    if primary_questions:
        ts_lines.append("primary_questions:")
        for q in primary_questions:
            if isinstance(q, dict):
                qid = list(q.keys())[0]
                ts_lines.append(f"  - {qid}: {q[qid]}")
            else:
                ts_lines.append(f"  - {q}")
    else:
        ts_lines.append("primary_questions: []")
    (ws / "task_spec.yaml").write_text("\n".join(ts_lines) + "\n", encoding="utf-8")

    # facts/_INDEX.md (empty)
    fdir = ws / "facts"
    fdir.mkdir(exist_ok=True)
    (fdir / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")

    # write fact files if provided
    if facts:
        for claim_id, body in facts.items():
            (fdir / f"{claim_id}.md").write_text(body, encoding="utf-8")

    return ws


# =====================================================================
# RED1: orphan claim terminal → NOT CONVERGED
# =====================================================================

def test_orphan_terminal_blocks_converged(tmp_path):
    """RED1: a terminal claim with no answers_question is an orphan;
    its presence must block CONVERGED."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
            {"id": "C-2", "status": "PROVEN"},  # terminal but NO answers_question = orphan
        ],
        primary_questions=[{"q1": "sample family"}],
    )
    from convergence_check import _orphan_terminal_claims
    orphans = _orphan_terminal_claims(
        yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    )
    assert len(orphans) == 1, f"expected 1 orphan, got {orphans}"
    assert orphans[0]["id"] == "C-2"

    d = decide(ws)
    assert d["decision"] != "CONVERGED", \
        "orphan terminal claim must block CONVERGED"
    assert "orphan" in d["action"].lower() or "orphan" in json.dumps(d).lower(), \
        "action should mention orphan"


def test_orphan_terminal_with_blocked_converged_downgrade(tmp_path):
    """RED1 edge: orphan terminal → CONVERGED downgrades to a non-CONVERGED state."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
            {"id": "C-99", "status": "VERIFIED"},  # orphan terminal
        ],
        primary_questions=[{"q1": "family"}],
    )
    d = decide(ws)
    assert d["decision"] in ("SATURATED", "BLOCKED"), \
        f"orphan terminal should downgrade CONVERGED to SATURATED/BLOCKED, got {d['decision']}"
    assert d["exit_code"] != 0, "must not exit 0 (CONVERGED)"


# =====================================================================
# RED2: primary_question with STAMP/unverified → NOT CONVERGED
# =====================================================================

def test_stamp_answering_claim_blocks_converged(tmp_path):
    """RED2: primary_question answered only by STAMP claim → NOT CONVERGED."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "STAMP", "answers_question": "q1"},
        ],
        primary_questions=[{"q1": "sample family"}],
    )
    from convergence_check import _unverified_primary_questions
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    ts = yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))
    unverified = _unverified_primary_questions(reg, ts)
    assert len(unverified) == 1, f"expected q1 unverified, got {unverified}"
    assert unverified[0]["question"] == "q1"

    d = decide(ws)
    # STAMP is non-terminal (not in TERMINAL set), so it's an open claim → DISPATCH or similar
    # But even if all claims were terminal, STAMP answering a primary_q should block CONVERGED
    assert d["decision"] != "CONVERGED", \
        "primary_question answered only by STAMP must block CONVERGED"


def test_unverified_answering_claim_blocks_converged(tmp_path):
    """RED2 edge: primary_question answered by NEGATIVE (terminal but not PROVEN)
    → still NOT CONVERGED (question not affirmatively answered)."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "NEGATIVE", "answers_question": "q1"},
        ],
        primary_questions=[{"q1": "sample family"}],
    )
    from convergence_check import _unverified_primary_questions
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    ts = yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))
    unverified = _unverified_primary_questions(reg, ts)
    # NEGATIVE is terminal but not PROVEN — the question is not affirmatively answered
    assert len(unverified) == 1, \
        f"NEGATIVE answering claim should not satisfy primary_q, got {unverified}"

    d = decide(ws)
    assert d["decision"] != "CONVERGED", \
        "primary_question answered only by NEGATIVE must block CONVERGED"


# =====================================================================
# RED3: SPINNING real flatline → detected (not dedup'd away)
# =====================================================================

def test_spinning_flatline_not_hidden_by_dedup():
    """RED3: a real flatline (same open_count across many minutes) must NOT
    be collapsed by _dedup_consecutive into too few entries to trigger SPINNING.

    Simulates: orchestrator calls convergence_check every ~60s for 10 minutes,
    all with the same open_count=3. _dedup_consecutive should keep enough
    entries for _flatline_run >= SPINNING_FLATLINE (8).
    """
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    ledger = []
    for i in range(10):
        ledger.append({
            "ts": (base + timedelta(minutes=i)).isoformat(),
            "decision": "DISPATCH",
            "open_count": 3,
            "open_ids": ["C-1", "C-2", "C-3"],
            "partial_count": 0,
            "active_workers": 1,
            "blockers": [],
            "facts_total": 5,
        })
    # The raw ledger has 10 entries, all same state
    assert len(ledger) == 10

    deduped = _dedup_consecutive(ledger)
    # Each entry is 60s apart, which is < SAME_TURN_WINDOW_SEC (120s)
    # So they might all collapse to 1! That's the bug.
    # After fix: entries >= 60s apart should NOT be collapsed as "same turn"
    # because they represent DIFFERENT orchestrator turns.
    assert len(deduped) >= 5, \
        f"10 snapshots 60s apart should NOT collapse to {len(deduped)} — " \
        f"that hides the flatline. Expected >= 5 after fix."

    # The real test: assess() should detect SPINNING
    result = assess(ledger)
    assert result["verdict"] == "SPINNING", \
        f"10 rounds of same open_count=3, 60s apart must be SPINNING, got {result['verdict']}"


def test_spinning_flatline_30s_apart():
    """RED3 edge: even 30s apart, 15+ snapshots with same state should
    eventually trigger SPINNING (not all collapsed as same-turn noise)."""
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    ledger = []
    for i in range(15):
        ledger.append({
            "ts": (base + timedelta(seconds=30 * i)).isoformat(),
            "decision": "DISPATCH",
            "open_count": 2,
            "open_ids": ["C-1", "C-2"],
            "partial_count": 0,
            "active_workers": 1,
            "blockers": [],
            "facts_total": 3,
        })
    result = assess(ledger)
    # 15 snapshots * 30s = 450s = 7.5 min of flatline
    # Should be STALLED at minimum, SPINNING if enough survive dedup
    assert result["verdict"] in ("SPINNING", "STALLED"), \
        f"15 rounds of same state should be STALLED or SPINNING, got {result['verdict']}"


def test_same_turn_rapid_calls_still_dedup():
    """RED3 regression: rapid same-turn calls (3 within 5s) SHOULD still dedup.
    The fix must not break the legitimate same-turn dedup."""
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    ledger = []
    for i in range(3):
        ledger.append({
            "ts": (base + timedelta(seconds=2 * i)).isoformat(),
            "decision": "DISPATCH",
            "open_count": 3,
            "open_ids": ["C-1", "C-2", "C-3"],
            "partial_count": 0,
            "active_workers": 1,
            "blockers": [],
            "facts_total": 5,
        })
    deduped = _dedup_consecutive(ledger)
    assert len(deduped) == 1, \
        f"3 snapshots 2s apart = same turn, should dedup to 1, got {len(deduped)}"


# =====================================================================
# RED4: all primary_q PROVEN + zero orphan → CONVERGED (happy path)
# =====================================================================

def test_all_proven_zero_orphan_converged(tmp_path):
    """RED4: all primary_questions have PROVEN answering claims, zero orphan
    terminal claims → CONVERGED (regression: happy path must not break)."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
            {"id": "C-2", "status": "PROVEN", "answers_question": "q2"},
        ],
        primary_questions=[{"q1": "family"}, {"q2": "C2 config"}],
    )
    d = decide(ws)
    assert d["decision"] == "CONVERGED", \
        f"all PROVEN + zero orphan → must be CONVERGED, got {d['decision']}"
    assert d["exit_code"] == 0


def test_converged_includes_completeness_fields(tmp_path):
    """RED4 bonus: CONVERGED decision includes completeness diagnostic fields."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
        ],
        primary_questions=[{"q1": "family"}],
    )
    d = decide(ws)
    assert d["decision"] == "CONVERGED"
    # New completeness fields should be present
    assert "orphan_claims" in d, "decide() output must include orphan_claims"
    assert "unverified_primary_qs" in d, "decide() output must include unverified_primary_qs"
    assert d["orphan_claims"] == [], "no orphans in happy path"
    assert d["unverified_primary_qs"] == [], "no unverified primary_qs in happy path"


def test_no_primary_questions_still_converged(tmp_path):
    """RED4 edge: workspace with no primary_questions (empty task_spec)
    → CONVERGED still works (backward compat)."""
    ws = _make_ws(tmp_path,
        claims=[
            {"id": "C-1", "status": "PROVEN", "answers_question": None},
        ],
        primary_questions=None,
    )
    # No primary_questions = nothing to verify, so no orphan check applies
    # to claims that answer nothing (there are no questions to answer)
    d = decide(ws)
    assert d["decision"] == "CONVERGED", \
        f"no primary_questions + all terminal → CONVERGED, got {d['decision']}"
