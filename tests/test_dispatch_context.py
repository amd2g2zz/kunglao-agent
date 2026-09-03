#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_context.py — issue #527 派单 context 块机械化.

Covers:
- build_dispatch_context() shapes a structured context block from claim + workspace
- context block carries: claim_id, tier, tools, priority context, evidence slice,
  validated_capability, fact_count, plan_ref, sibling-claim hints
- context injection happens at the worker_budget pre_check lifecycle point
- context shape validation against dispatch_context schema (mandatory keys +
  value constraints)
- context integrates with dispatch_linkage (same lifecycle event but context
  is an ADDITIONAL artifact, not a replacement)

Issue #527: 派单 context 块机械化 — the worker channel MUST receive a
structured context block on every passing dispatch. Pre-#527 the worker got
the raw dispatch prompt alone; structural context (evidence snapshot,
priority state, validated capability) had to be re-derived by the worker.
Now: the orchestrator builds the block at the pre_check point (alongside
dispatch_linkage, #461) and the worker consumes the block directly.

RED phase: these tests fail against baseline (no dispatch_context module).
GREEN phase: implement scripts/dispatch_context.py + integration in
worker_budget.pre_check.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# ---- loader: dispatch_context is a fresh module — load it explicitly ----

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dc = _load("_dispatch_context_for_test",
            SCRIPTS_DIR / "dispatch_context.py")


# ---------- fixture helpers ----------

@pytest.fixture
def tmp_ws(tmp_path: Path) -> Path:
    """Build a minimal workspace with claim_register + facts dir + plan."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    claims_yaml = (
        "claims:\n"
        "- id: C-001\n"
        "  status: OPEN\n"
        "  boundary_type: positive_observation\n"
        "  evidence_tier_attempted: 1\n"
        "  promotion_attempts: 0\n"
        "  statement: verify PE file is signed\n"
        "- id: C-002\n"
        "  status: OPEN\n"
        "  boundary_type: positive_observation\n"
        "  evidence_tier_attempted: 0\n"
        "  promotion_attempts: 0\n"
        "  obstacle_for: C-001\n"
        "  statement: enumerate imports\n"
        "  depends_on: []\n"
    )
    (ws / "claim-register.yaml").write_text(claims_yaml, encoding="utf-8")
    facts = ws / "facts"
    facts.mkdir()
    (facts / "F001.md").write_text("# fact 1\n", encoding="utf-8")
    (facts / "F002.md").write_text("# fact 2\n", encoding="utf-8")
    (facts / "F003.md").write_text("# fact 3\n", encoding="utf-8")
    (ws / "facts").joinpath("_INDEX.md").write_text(
        "# _INDEX\n\n- F001: signed PE\n- F002: imports\n- F003: strings\n",
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "constraints:\n  vm_detonation: allowed\n",
        encoding="utf-8")
    plan = (
        "goal: verify the PE signature\n"
        "preflight: tools available\n"
        "steps:\n"
        "  - read peheader\n"
        "  - check signature\n"
        "fallback: try certutil\n"
    )
    (ws / "runs" / "plan-C001.md").write_text(plan, encoding="utf-8")
    return ws


# ---------- A: context block shape ----------

class TestContextBlockShape:
    def test_returns_dict_with_required_keys(self, tmp_ws: Path) -> None:
        """The context block MUST carry the #527 contract: claim_id, tier,
        tools, dispatch_ts, workspace_ref, priority_context, fact_snapshot,
        validated_capability, plan_ref, sibling_claims. Missing keys = the
        worker has to re-derive them — the regression we are closing."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws,
            claim_id="C-001",
            tier=1,
            tools=["pe_analyze"],
            agent_name="kunglao-worker",
        )
        assert isinstance(ctx, dict)
        required = {
            "claim_id", "tier", "tools", "agent", "dispatch_ts",
            "workspace_ref", "priority_context", "fact_snapshot",
            "validated_capability", "plan_ref", "sibling_claims",
        }
        missing = required - set(ctx.keys())
        assert not missing, f"context missing required keys: {missing}"

    def test_claim_id_round_trip(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        assert ctx["claim_id"] == "C-001"

    def test_tier_round_trip(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=2, tools=["x"],
            agent_name="kunglao-worker")
        assert ctx["tier"] == 2

    def test_tools_round_trip(self, tmp_ws: Path) -> None:
        tools = ["pe_analyze", "strings-classify", "grep"]
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=tools,
            agent_name="kunglao-worker")
        assert ctx["tools"] == tools

    def test_agent_round_trip(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="ghidra-light")
        assert ctx["agent"] == "ghidra-light"

    def test_dispatch_ts_is_iso_utc(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        # ISO-8601 with Z suffix (UTC)
        ts = ctx["dispatch_ts"]
        assert isinstance(ts, str)
        assert ts.endswith("Z")
        # roundtrip parse
        from datetime import datetime
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed is not None

    def test_workspace_ref_is_string(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        assert isinstance(ctx["workspace_ref"], str)
        assert "ws" in ctx["workspace_ref"]  # path string


# ---------- B: fact_snapshot pulls from facts/ ----------

class TestFactSnapshot:
    def test_fact_snapshot_counts_facts(self, tmp_ws: Path) -> None:
        """The #527 contract: worker sees HOW MANY facts are present at
        dispatch time. facts-snapshot marker (worker_budget) is the liveness
        cue; the context block is the structured form."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        snap = ctx["fact_snapshot"]
        assert isinstance(snap, dict)
        assert snap["count"] == 3  # F001, F002, F003
        assert "files" in snap
        assert sorted(snap["files"]) == ["F001.md", "F002.md", "F003.md"]

    def test_fact_snapshot_handles_empty(self, tmp_ws: Path) -> None:
        empty = tmp_ws / "facts"
        for f in empty.glob("F0*.md"):
            f.unlink()
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        assert ctx["fact_snapshot"]["count"] == 0
        assert ctx["fact_snapshot"]["files"] == []

    def test_fact_snapshot_handles_missing_facts_dir(self, tmp_ws: Path) -> None:
        import shutil
        shutil.rmtree(tmp_ws / "facts")
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        # FAIL_OPEN: missing facts dir -> empty snapshot, NOT crash
        assert ctx["fact_snapshot"]["count"] == 0


# ---------- C: priority_context ----------

class TestPriorityContext:
    def test_priority_context_carries_top_claim(self, tmp_ws: Path) -> None:
        """priority_context tells the worker which claim is the ranked #1
        (for context — they were not dispatched, but it's the audit anchor)."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        pc = ctx["priority_context"]
        assert isinstance(pc, dict)
        # keys: dispatched, top_rank, ratio (FAIL_OPEN -> no scorer -> None)
        assert "dispatched" in pc
        assert pc["dispatched"] == "C-001"

    def test_priority_context_handles_no_scorer(self, tmp_ws: Path) -> None:
        """If the priority scorer is unavailable, the context must still
        build — priority_context ratio is None, never raises."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        pc = ctx["priority_context"]
        # ratio is None OR a numeric — both legal
        assert pc.get("ratio") is None or isinstance(pc["ratio"], (int, float))


# ---------- D: validated_capability ----------

class TestValidatedCapability:
    def test_returns_empty_when_no_evidence(self, tmp_ws: Path) -> None:
        """No validated capability -> empty dict (FAIL_OPEN — worker still
        runs, the absence of capability is itself a signal)."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        assert isinstance(ctx["validated_capability"], dict)


# ---------- E: plan_ref ----------

class TestPlanRef:
    def test_plan_ref_points_to_runs_plan(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        assert ctx["plan_ref"] == "runs/plan-C001.md"

    def test_plan_ref_none_when_missing(self, tmp_ws: Path) -> None:
        (tmp_ws / "runs" / "plan-C001.md").unlink()
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        # None means "no plan" — the worker knows to ask for one
        assert ctx["plan_ref"] is None


# ---------- F: sibling_claims ----------

class TestSiblingClaims:
    def test_sibling_includes_obstacle_for(self, tmp_ws: Path) -> None:
        """C-002 has obstacle_for=C-001 — the context block for C-001 must
        list C-002 as a sibling (the parent obstacle is in flight)."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        sibs = ctx["sibling_claims"]
        assert isinstance(sibs, list)
        ids = [s.get("id") for s in sibs]
        # C-002 obstacle_for=C-001 means C-002 IS a sibling of C-001
        assert "C-002" in ids


# ---------- G: schema validation ----------

class TestShapeValidation:
    def test_valid_block_passes(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        # validate_context returns None on success, raises on failure
        assert _dc.validate_context_shape(ctx) is None

    def test_missing_claim_id_fails(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        ctx.pop("claim_id")
        with pytest.raises(Exception):
            _dc.validate_context_shape(ctx)

    def test_bad_tier_fails(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        ctx["tier"] = 9  # not in {1,2,3}
        with pytest.raises(Exception):
            _dc.validate_context_shape(ctx)

    def test_bad_claim_id_format_fails(self, tmp_ws: Path) -> None:
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        ctx["claim_id"] = "claim-1"  # not C-NN
        with pytest.raises(Exception):
            _dc.validate_context_shape(ctx)


# ---------- H: dispatch_inject — serializes for prompt ----------

class TestDispatchInject:
    def test_inject_emits_structured_block(self, tmp_ws: Path) -> None:
        """dispatch_inject returns a string suitable for prompt injection —
        the worker can grep it from the prompt."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["pe_analyze"],
            agent_name="kunglao-worker")
        injected = _dc.dispatch_inject(ctx)
        assert isinstance(injected, str)
        # MUST contain a marker the worker greps for
        assert "KUNGLAO_DISPATCH_CONTEXT" in injected
        # MUST contain the JSON payload (the context itself)
        assert "C-001" in injected
        assert "pe_analyze" in injected


# ---------- I: lifecycle integration (dispatch_linkage, #461) ----------

class TestLifecycleIntegration:
    def test_apply_dispatch_context_persists_to_runs(self, tmp_ws: Path) -> None:
        """#527: the dispatch context artifact is written next to
        .hook_state.json — runs/dispatch-context-C<NN>.json — so the
        worker's status file can reference it (state-loss redundancy).

        Integration with #461 dispatch_linkage: the linkage call does NOT
        itself write the context block; the dedicated writer does, but BOTH
        are invoked from the worker_budget pre_check lifecycle point."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        path = _dc.apply_dispatch_context(tmp_ws, ctx)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["claim_id"] == "C-001"
        # file naming convention
        assert path.name == "dispatch-context-C001.json"

    def test_apply_dispatch_context_is_fail_open(self, tmp_ws: Path) -> None:
        """A bad ctx (missing required keys) must NOT raise in
        apply_dispatch_context — that's a validator concern, the writer is
        fail-open (pre-#527 dispatch gate stays usable on context failure)."""
        bad_ctx = {"claim_id": "C-001"}  # missing everything else
        # Should NOT raise — validate_context_shape is the strict face;
        # apply_dispatch_context is the lenient writer.
        path = _dc.apply_dispatch_context(tmp_ws, bad_ctx)
        # Either written verbatim or normalized — never raises.
        assert path is not None