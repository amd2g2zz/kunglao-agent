# -*- coding: utf-8 -*-
"""tests/test_difficulty_thresholds_16.py — #16 difficulty-gated thresholds.

Issue #16: promotion requirements are currently FLAT — every claim needs the
same verify pass regardless of sample resistance. This module pins:

  1. the per-tier policy table (easy/medium/hard/max) with easy EXACTLY at
     today's behavior (owner ruling: simple samples must NOT be complexified);
  2. the fail-closed default — unknown/missing difficulty tier resolves to
     hard, never silently down-grades to easy;
  3. enforcement: PROVEN promotion of a hard/max claim needs
     required_independent_verifications DISTINCT verifier records
     (claim_migrator + the hook backstop face);
  4. guidance: the red-team depth line appears on the orchestrator guidance
     surface only when the tier carries associated_task_consistency.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import difficulty_thresholds as dt  # noqa: E402

TIERS = ("easy", "medium", "hard", "max")
FIELDS = ("required_independent_verifications", "redteam_rounds",
          "associated_task_consistency", "heuristic_first_allowed")

VALID_SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w2
      refute_attempt: "tried grep for alt-config; not found - claim holds"
      sign_off_at: 2026-09-04T02:00:00Z
      verdict: CONFIRMED
    ```
    """)


# ---------- fixtures ----------

def _proven_ws(tmp_path: Path, status_before: str = "VERIFIED") -> tuple[Path, Path]:
    """The canonical promotion workspace (test_framework_rigidity_57 shape):
    non-inferential claim + fact file with a valid verifier_sign_off, so the
    promotion reaches PROVEN-candidate and only the depth gate can block."""
    from _factories import write_claims_register
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "analysis_state.txt").write_text("[current_task]\n", encoding="utf-8")
    reg = write_claims_register(ws, [{
        "id": "C-001", "status": status_before,
        "statement": "imports resolved at runtime",
    }])
    (ws / "facts" / "C-001.md").write_text(
        "---\nid: F001\ntype: fact\ntitle: t\nstatus: INFERRED\n"
        "created: 2026-09-04\nlast_reviewed: 2026-09-04\nclaim_id: C-001\n"
        "claim: imports resolved at runtime\nboundary_type: observation\n"
        "source: static-decompile\nconfidence: medium\n"
        "verify_status: partial\nreproduce: python runs/verify.py\n"
        "expected: pending\nverified: pending\nprovenance:\n"
        "  - {role: decompiled_c, path: evidence/x.c}\n---\n\n"
        "## Status\nINFERRED\n\n" + VALID_SIGNOFF, encoding="utf-8")
    return ws, reg


def _second_diff(ws: Path, claim: str = "C-001") -> Path:
    """A second, DISTINCT red-team DIFF record naming the claim."""
    p = ws / "runs" / f"verify-redteam-{claim}-round2.md"
    p.write_text(
        f"# Red-team verification round 2: {claim}\n\n"
        "## My independent derivation\n"
        "re-derived the layout from the disassembly; anchors hold.\n\n"
        "RED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
    return p


def _dispatch_row(ws: Path, claim: str = "C-001") -> None:
    """Append one verifier-class dispatch row to the unified log."""
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    target = sorted(logs.glob("kunglao-*.jsonl"))
    p = target[-1] if target else logs / "kunglao-2026-09-05.jsonl"
    row = {"ts": "2026-09-05T01:00:00Z", "actor": "hook:worker_budget",
           "action": "dispatch", "claim": claim,
           "detail": f"tier=1 tools=grep agent=kunglao-redteam (verifier for {claim})"}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _register_status(ws: Path, claim: str = "C-001") -> str:
    doc = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return next(c["status"] for c in doc["claims"] if c["id"] == claim)


# =====================================================================
# 1. policy table: all four tiers, easy == legacy behavior
# =====================================================================

class TestPolicyTable:
    def test_all_four_tiers_queryable(self):
        for tier in TIERS:
            th = dt.get_thresholds(tier)
            assert th["tier"] == tier
            for field in FIELDS:
                assert field in th, (tier, field)

    def test_easy_is_exactly_legacy_behavior(self):
        """Owner ruling: simple samples must NOT be complexified — easy keeps
        today's single-verification, single-round flow, no extra sweeps."""
        th = dt.get_thresholds("easy")
        assert th["required_independent_verifications"] == 1
        assert th["redteam_rounds"] == 1
        assert th["associated_task_consistency"] is False
        assert th["heuristic_first_allowed"] is False

    def test_suggested_shape_per_issue(self):
        """The 1/1/2/2 + F/F/T/T policy shape from the #16 plan."""
        assert [dt.get_thresholds(t)["required_independent_verifications"]
                for t in TIERS] == [1, 1, 2, 2]
        assert [dt.get_thresholds(t)["redteam_rounds"]
                for t in TIERS] == [1, 1, 1, 2]
        assert [dt.get_thresholds(t)["associated_task_consistency"]
                for t in TIERS] == [False, False, True, True]
        assert [dt.get_thresholds(t)["heuristic_first_allowed"]
                for t in TIERS] == [False, False, True, True]

    def test_hard_and_max_demand_two_verifications(self):
        for tier in ("hard", "max"):
            assert dt.get_thresholds(tier)["required_independent_verifications"] == 2

    def test_unknown_tier_fails_closed_to_hard(self):
        """Never silently down-grade to easy: an unknown tier is hard."""
        th = dt.get_thresholds("ludicrous")
        assert th["tier"] == "hard"
        assert th["required_independent_verifications"] == 2
        assert "fail-closed" in th["source"]
        assert "ludicrous" in th["note"]

    def test_none_and_empty_tier_fail_closed(self):
        for bad in (None, "", "  "):
            assert dt.get_thresholds(bad)["tier"] == "hard"


# =====================================================================
# 2. thresholds_for_workspace: feed resolution + fail-closed default
# =====================================================================

class TestWorkspaceResolution:
    def test_missing_difficulty_json_is_hard_with_source(self, tmp_path):
        th = dt.thresholds_for_workspace(tmp_path)
        assert th["tier"] == "hard"
        assert th["required_independent_verifications"] == 2
        assert "fail-closed" in th["source"], th
        assert th["note"], "the fail-closed posture must carry a source note"

    def test_feed_tier_resolved_with_source(self, tmp_path):
        from _factories import seed_difficulty
        seed_difficulty(tmp_path, "max")
        th = dt.thresholds_for_workspace(tmp_path)
        assert th["tier"] == "max"
        assert th["source"] == "evidence/difficulty.json"
        assert th["required_independent_verifications"] == 2
        assert th["redteam_rounds"] == 2

    def test_task_spec_difficulty_key_fallback(self, tmp_path):
        """PR #80 mounts the same doc into task_spec.yaml; a workspace that
        lost evidence/ still resolves its tier from the mounted key."""
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump({"task": "t",
                            "difficulty": {"schema": "difficulty-calibration/1",
                                           "tier": "hard"}}),
            encoding="utf-8")
        th = dt.thresholds_for_workspace(tmp_path)
        assert th["tier"] == "hard"
        assert th["source"] == "task_spec.yaml:difficulty"

    def test_corrupt_feed_fails_closed(self, tmp_path):
        ev = tmp_path / "evidence"
        ev.mkdir()
        (ev / "difficulty.json").write_text("{not json", encoding="utf-8")
        th = dt.thresholds_for_workspace(tmp_path)
        assert th["tier"] == "hard"
        assert "fail-closed" in th["source"]

    def test_unknown_tier_in_feed_fails_closed(self, tmp_path):
        from _factories import seed_difficulty
        seed_difficulty(tmp_path, "absurd")
        th = dt.thresholds_for_workspace(tmp_path)
        assert th["tier"] == "hard"
        assert "absurd" in th.get("note", "")

    def test_never_raises_on_nonexistent_path(self):
        th = dt.thresholds_for_workspace("/nonexistent/ws-16")
        assert th["tier"] == "hard"


# =====================================================================
# 3. enforcement: PROVEN promotion depth (claim_migrator face)
# =====================================================================

class TestClaimMigratorDepth:
    def test_max_tier_blocked_with_one_verification(self, tmp_path):
        """max needs 2 DISTINCT verifier records; one DIFF is not enough and
        the register stays unmodified (fail closed)."""
        from _factories import seed_difficulty, seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "max")
        seed_verifier_dispatch(ws, "C-001")
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok is False, msg
        assert "VERIFIER DEPTH" in msg, msg
        assert _register_status(ws) == "VERIFIED", "register must stay unmodified"

    def test_max_tier_passes_with_two_verifications(self, tmp_path):
        from _factories import seed_difficulty, seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "max")
        seed_verifier_dispatch(ws, "C-001")
        _second_diff(ws)
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok, msg
        assert _register_status(ws) == "PROVEN"

    def test_max_tier_dispatch_rows_accumulate(self, tmp_path):
        """The DIFF path is fixed per claim (rounds overwrite); accumulated
        dispatch rows are the other counting kind (max over kinds)."""
        from _factories import seed_difficulty, seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "max")
        seed_verifier_dispatch(ws, "C-001")
        _dispatch_row(ws)
        _dispatch_row(ws)
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok, msg

    def test_missing_feed_fails_closed_blocks_single_verification(self, tmp_path):
        """No difficulty feed = unknown tier = hard posture: the legacy
        single-DIFF promotion is NOT silently allowed."""
        from _factories import seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_verifier_dispatch(ws, "C-001")
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok is False, msg
        assert "VERIFIER DEPTH" in msg, msg
        assert _register_status(ws) == "VERIFIED"

    def test_easy_tier_legacy_flow_unchanged(self, tmp_path):
        """Regression pin: tier easy == exactly today's promotion flow — one
        DIFF still promotes, no depth demand, no sweep language."""
        from _factories import seed_difficulty, seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "easy")
        seed_verifier_dispatch(ws, "C-001")
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok, msg
        assert "VERIFIER DEPTH" not in msg, msg
        assert _register_status(ws) == "PROVEN"

    def test_hard_tier_depth_gate_names_tier(self, tmp_path):
        from _factories import seed_difficulty, seed_verifier_dispatch
        from kunglao_record import claim_migrator
        ws, _reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "hard")
        seed_verifier_dispatch(ws, "C-001")
        ok, msg = claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
        assert ok is False
        assert "hard" in msg, msg


# =====================================================================
# 4. enforcement: hook backstop face (compare_register_change_proven_gate)
# =====================================================================

class TestBackstopDepth:
    def _gate(self, ws: Path, reg: Path):
        import worker_budget_gates as wbg
        before = {"C-001": "VERIFIED"}
        reg.write_text(reg.read_text(encoding="utf-8").replace(
            "status: VERIFIED", "status: PROVEN"), encoding="utf-8")
        return wbg.compare_register_change_proven_gate(
            reg, before, "orchestrator", ws / "facts")

    def test_max_tier_blocked_with_one_record(self, tmp_path):
        from _factories import seed_difficulty, seed_verifier_dispatch
        ws, reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "max")
        seed_verifier_dispatch(ws, "C-001")
        ok, reason = self._gate(ws, reg)
        assert ok is False, reason
        assert "VERIFIER DEPTH" in reason, reason

    def test_max_tier_passes_with_two_records(self, tmp_path):
        from _factories import seed_difficulty, seed_verifier_dispatch
        ws, reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "max")
        seed_verifier_dispatch(ws, "C-001")
        _second_diff(ws)
        ok, reason = self._gate(ws, reg)
        assert ok, reason

    def test_easy_tier_single_record_still_passes(self, tmp_path):
        from _factories import seed_difficulty, seed_verifier_dispatch
        ws, reg = _proven_ws(tmp_path)
        seed_difficulty(ws, "easy")
        seed_verifier_dispatch(ws, "C-001")
        ok, reason = self._gate(ws, reg)
        assert ok, reason


# =====================================================================
# 5. guidance surface: difficulty-aware red-team line
# =====================================================================

class TestGuidance:
    def test_guidance_line_present_for_max(self, tmp_path):
        from _factories import seed_difficulty
        from heartbeat_loop_prompt import build_prompt
        seed_difficulty(tmp_path, "max")
        prompt = build_prompt(str(tmp_path))
        assert "difficulty max" in prompt
        assert "consistency sweep of associated tasks" in prompt
        assert "2 red-team rounds" in prompt

    def test_guidance_line_absent_for_easy(self, tmp_path):
        """No complexification: an easy workspace carries NO difficulty line."""
        from _factories import seed_difficulty
        from heartbeat_loop_prompt import build_prompt
        seed_difficulty(tmp_path, "easy")
        prompt = build_prompt(str(tmp_path))
        assert "difficulty easy" not in prompt
        assert "consistency sweep of associated tasks" not in prompt

    def test_guidance_unit_easy_is_empty(self, tmp_path):
        from _factories import seed_difficulty
        seed_difficulty(tmp_path, "easy")
        assert dt.guidance_line(tmp_path) == ""

    def test_guidance_unit_max_names_rounds(self, tmp_path):
        from _factories import seed_difficulty
        seed_difficulty(tmp_path, "max")
        line = dt.guidance_line(tmp_path)
        assert "max" in line and "2 red-team rounds" in line
        assert "consistency sweep of associated tasks" in line


# =====================================================================
# 6. policy joins + record counting internals
# =====================================================================

class TestPolicyJoins:
    def test_required_for_terminal_state_names_depth_gate(self):
        from kunglao_record import REQUIRED_FOR_TERMINAL_STATE
        assert "blind_gate:check_verifier_depth_evidence" in REQUIRED_FOR_TERMINAL_STATE
        assert "blind_gate:check_verifier_dispatch_evidence" in REQUIRED_FOR_TERMINAL_STATE

    def test_count_distinct_diffs(self, tmp_path):
        from _factories import seed_verifier_dispatch
        seed_verifier_dispatch(tmp_path, "C-001")
        _second_diff(tmp_path)
        counts = dt.count_verifications(tmp_path, "C-001")
        assert counts == 2

    def test_count_is_max_over_kinds_not_sum(self, tmp_path):
        """One round emits BOTH a DIFF and a dispatch row — the sum would
        double-count one engagement; the count is the max over kinds."""
        from _factories import seed_verifier_dispatch
        seed_verifier_dispatch(tmp_path, "C-001")
        _dispatch_row(tmp_path)
        assert dt.count_verifications(tmp_path, "C-001") == 1
        _dispatch_row(tmp_path)
        assert dt.count_verifications(tmp_path, "C-001") == 2

    def test_count_claim_scoped(self, tmp_path):
        from _factories import seed_verifier_dispatch
        seed_verifier_dispatch(tmp_path, "C-002")
        assert dt.count_verifications(tmp_path, "C-001") == 0

    def test_count_empty_workspace_zero(self, tmp_path):
        assert dt.count_verifications(tmp_path, "C-001") == 0
