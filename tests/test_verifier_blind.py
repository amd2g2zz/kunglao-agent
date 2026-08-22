#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_verifier_blind.py — issue #527 verifier BLIND 硬排除.

Covers:
- build_dispatch_context() NEVER leaks the dispatch context to a verifier
  caller (the verifier gets BLIND: only the artifact under test, no
  orchestrator-side context)
- verifier_dispatch_view(workspace, claim_id) returns the BLIND slice —
  facts + plan, no priority_context / dispatch_ts / agent hints
- verifier-dispatch isolation is ENFORCED structurally (the verifier path
  imports a dedicated entry, not build_dispatch_context)
- the dispatched-context writer writes to runs/, never to verifier-visible
  paths (fact dir / claim register)
- verifier cannot accidentally discover the dispatch context artifact

#527 verifier BLIND 硬排除: verifier is the gate to PROVEN status. If the
verifier sees the orchestrator's dispatch context (priority rankings, sibling
hints, agent assignments) it can pattern-match the orchestrator's expectations
rather than the artifact under test — that is the gate's failure mode. The
structural fix: verifier_dispatch_view returns ONLY the BLIND slice. The
context block itself lives in runs/ (a verifier-inaccessible path by
convention), and the verifier never imports build_dispatch_context.

RED phase: no verifier_dispatch_view exists. These tests must fail.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dc = _load("_dispatch_context_for_blind_test",
            SCRIPTS_DIR / "dispatch_context.py")


# ---------- fixtures ----------

@pytest.fixture
def tmp_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n  evidence_tier_attempted: 1\n"
        "  statement: verify PE\n",
        encoding="utf-8",
    )
    facts = ws / "facts"
    facts.mkdir()
    (facts / "F001.md").write_text("# fact\n", encoding="utf-8")
    (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    plan = (
        "goal: verify\n"
        "preflight: ok\n"
        "steps:\n- run\n"
        "fallback: retry\n"
    )
    (ws / "runs" / "plan-C001.md").write_text(plan, encoding="utf-8")
    return ws


# ---------- A: BLIND slice shape ----------

class TestVerifierBlindSlice:
    def test_returns_blind_keys_only(self, tmp_ws: Path) -> None:
        """The verifier slice MUST carry ONLY facts + plan. The orchestrator
        context (priority, agent, dispatch_ts, sibling_claims,
        validated_capability) MUST be excluded — these are the orchestrator's
        expectations the verifier must not pattern-match against."""
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        assert isinstance(blind, dict)
        # required keys
        assert "facts" in blind or "fact_snapshot" in blind
        assert "plan_ref" in blind
        # forbidden keys (orchestrator-side context)
        forbidden = {
            "priority_context", "agent", "dispatch_ts", "sibling_claims",
            "validated_capability", "tools", "tier",
        }
        leaked = forbidden & set(blind.keys())
        assert not leaked, f"verifier slice leaked: {leaked}"

    def test_does_not_include_agent_assignment(self, tmp_ws: Path) -> None:
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        # 'agent' would tell the verifier which worker handled this claim
        assert "agent" not in blind
        # no string anywhere with 'kunglao-' or 'ghidra-' agent names
        text = str(blind)
        assert "ghidra-light" not in text
        assert "kunglao-worker" not in text

    def test_does_not_include_priority(self, tmp_ws: Path) -> None:
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        assert "priority_context" not in blind
        # no string with priority scores
        text = str(blind)
        assert "ratio" not in text  # priority_ratio vocab leaks priorities


# ---------- B: BLIND slice contents ----------

class TestBlindContents:
    def test_facts_present(self, tmp_ws: Path) -> None:
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        # Either shape is acceptable (count-only or full list)
        snap = blind.get("fact_snapshot") or blind.get("facts")
        assert snap is not None
        if isinstance(snap, dict):
            assert snap.get("count", 0) >= 1
        elif isinstance(snap, list):
            assert len(snap) >= 1

    def test_plan_ref_present(self, tmp_ws: Path) -> None:
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        assert blind["plan_ref"] == "runs/plan-C001.md"


# ---------- C: structural isolation ----------

class TestStructuralIsolation:
    def test_verifier_dispatch_view_is_separate_function(self) -> None:
        """#527 contract: verifier entry is a DEDICATED function. Importing
        build_dispatch_context into a verifier module would re-introduce the
        context surface; this test pins the two functions as distinct
        importable symbols."""
        assert hasattr(_dc, "verifier_dispatch_view")
        assert hasattr(_dc, "build_dispatch_context")
        # they are DIFFERENT functions
        assert _dc.verifier_dispatch_view is not _dc.build_dispatch_context

    def test_blind_slice_is_subset_of_full_block(self, tmp_ws: Path) -> None:
        """If the full block has key K, the blind slice MAY have K iff K is
        on the safe allow-list (fact_snapshot, plan_ref). This pins the
        contract: blind slice = full_block filtered by safe_keys."""
        full = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        safe_keys = {"fact_snapshot", "facts", "plan_ref", "claim_id"}
        for k in blind.keys():
            assert k in safe_keys, (
                f"verifier slice key {k!r} is not on the safe allow-list")

    def test_safe_keys_list_is_explicit(self) -> None:
        """The verifier safe-key set MUST be an explicit allow-list
        constant (no dynamic 'all keys except N' which silently widens)."""
        assert hasattr(_dc, "VERIFIER_SAFE_KEYS")
        safe = _dc.VERIFIER_SAFE_KEYS
        # It is a frozenset (immutable)
        assert isinstance(safe, frozenset)
        # and it does NOT include any orchestrator-side keys
        forbidden = {
            "agent", "priority_context", "dispatch_ts", "sibling_claims",
            "validated_capability", "tools", "tier",
        }
        assert not (safe & forbidden)


# ---------- D: artifact location isolation ----------

class TestArtifactLocationIsolation:
    def test_dispatch_context_lives_under_runs(self, tmp_ws: Path) -> None:
        """The dispatch context artifact MUST live in runs/ (verifier-
        inaccessible by convention) — never in facts/, claim-register.yaml,
        or anywhere the verifier reads."""
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        path = _dc.apply_dispatch_context(tmp_ws, ctx)
        # Path is under runs/, not facts/
        assert "runs" in path.parts
        # NEVER under facts/
        assert "facts" not in path.parts

    def test_verifier_view_does_not_read_runs_dispatch_context(
            self, tmp_ws: Path) -> None:
        """Even if runs/dispatch-context-C001.json exists, the verifier
        MUST NOT see it — verifier_dispatch_view scans facts/ and plan/, not
        runs/dispatch-context-*.json."""
        # Write a sentinel dispatch context with a unique string
        ctx = _dc.build_dispatch_context(
            ws=tmp_ws, claim_id="C-001", tier=1, tools=["x"],
            agent_name="kunglao-worker")
        path = _dc.apply_dispatch_context(tmp_ws, ctx)
        sentinel = "ORCHESTRATOR_ONLY_SECRET_KEY"
        # Inject sentinel into the persisted file
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8"))
        data["sentinel"] = sentinel
        path.write_text(_json.dumps(data), encoding="utf-8")
        # Verifier slice MUST NOT see the sentinel
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        text = _json.dumps(blind)
        assert sentinel not in text


# ---------- E: cannot import build_dispatch_context via verifier path -------

class TestVerifierCannotReachContextBuilder:
    def test_verifier_dispatch_view_does_not_carry_full_block(self,
                                                              tmp_ws: Path) -> None:
        """The verifier view is a STRUCTURAL slice — it must not be the full
        block with secret fields hidden. The slice is hand-rolled from facts/
        + plan/ only."""
        blind = _dc.verifier_dispatch_view(tmp_ws, "C-001")
        # An orchestrator-key block would be a violation:
        for k in ("tier", "tools", "agent", "dispatch_ts",
                  "priority_context", "sibling_claims",
                  "validated_capability"):
            assert k not in blind, (
                f"verifier slice must NOT carry orchestrator key {k!r}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))  # noqa: F821