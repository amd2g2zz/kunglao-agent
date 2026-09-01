#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_trace_identity_879.py — trace identity layer (#879).

Anchors the four #879 acceptance faces:

  1. same-mission full-chain join: dispatch -> worker -> settlement rows all
     carry the SAME trace_id (format `tr-<mission>-<seq>`);
  2. un-attributed rate is computable (rows missing trace_id as a fraction);
  3. SUPERSEDED claims have a followable edge (supersedes / superseded_by /
     derived_from round-trip + carrier_consistency (g) validation);
  4. illegal actor values are mechanically queryable (strict vocabulary +
     LEGACY_ACTORS adoption + repo-wide literal anchor).

Additive discipline: every change is null-default / extra-key tolerant —
old emit rows, old registers, old worker-status files, old dispatch
prompts stay byte-green.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kunglao_log  # noqa: E402
from kunglao_log import (  # noqa: E402
    allocate_trace_id,
    emit,
    log_path,
    new_trace_id,
    validate_actor,
    validate_trace_id,
)

# hooks/lib_kunglao.py has a namesake in scripts/ — load by path (same
# convention as tests/test_dispatch_protocol.py).
def _load_hooks_lib():
    spec = importlib.util.spec_from_file_location(
        "_hooks_lib_kunglao_for_879",
        REPO_ROOT / "hooks" / "lib_kunglao.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LK = _load_hooks_lib()

TRACE_STATE = Path("runs") / ".trace-state.json"


# ---------- shared fixtures ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _make_ws(root: Path) -> Path:
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write_yaml(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "statement": "work"},
    ]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml", {"primary_questions": [],
                                        "mission": "demo-mission"})
    # kunglao-agent ACTIVE (30-min TTL discipline, mirrors #496 fixtures)
    (ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate"],
        "paused_hooks": [],
        "expires_at": "2099-12-31T23:59:59Z",
    }), encoding="utf-8")
    return ws


def _run_gate(root: Path, ws: Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt},
    })
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )


def _event_rows(ws: Path) -> list[dict]:
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


def _envelope(trace_id: str | None = None, claim: str = "C-1") -> str:
    payload: dict = {"version": 1, "claim": claim, "tier": 1,
                     "tools": ["Read", "Write", "Grep"],
                     "agent": "kunglao-worker"}
    if trace_id is not None:
        payload["trace_id"] = trace_id
    return json.dumps({"kunglao_dispatch": payload})


# ---------- 1.1 trace_id format (pinned) -------------------------------

class TestTraceIdFormat:
    def test_new_trace_id_shape(self):
        assert new_trace_id("demo-mission", 7) == "tr-demo-mission-0007"

    def test_format_regex_pinned(self):
        ok = re.compile(r"^tr-[a-z0-9][a-z0-9._-]*-\d+$")
        for tid in ["tr-demo-mission-0007", "tr-m-0001", "tr-a-1"]:
            assert ok.match(tid), tid
            assert validate_trace_id(tid), tid
        for bad in ["", "tr-", "tr-demo-mission", "demo-mission-0007",
                    "tr--0001", "TR-M-1", "tr-demo-mission-x"]:
            assert not validate_trace_id(bad), bad

    def test_mission_sanitized(self):
        tid = new_trace_id("Weird Mission!! (v2)", 2)
        assert tid == "tr-weird-mission-v2-0002"

    def test_seq_padded_to_four(self):
        assert new_trace_id("m", 12345) == "tr-m-12345"


# ---------- 1.2 actor vocabulary ----------------------------------------

class TestActorVocabulary:
    def test_five_legal_forms(self):
        for actor in ["orchestrator", "worker:kunglao-worker",
                      "verifier:kunglao-redteam", "hook:dispatch_gate",
                      "subagent:general-purpose"]:
            ok, why = validate_actor(actor)
            assert ok, f"{actor}: {why}"

    def test_illegal_values_fail(self):
        for actor in ["", "hook:", "worker:", "some random string",
                      "hook:bad name!", "HOOK:x"]:
            ok, why = validate_actor(actor)
            assert not ok, actor
            assert why, "rejection must carry a reason"

    def test_emit_accepts_any_actor_but_rows_are_queryable(self, tmp_path):
        # emit NEVER rejects (logging must never break analysis) — the
        # mechanical gate is the query face, not a write gate.
        emit(tmp_path, actor="legacy-script-name", action="verify")
        rows = _event_rows(tmp_path)
        assert rows[0]["actor"] == "legacy-script-name"


# ---------- 1.3 lineage edges round-trip ---------------------------------

class TestLineageEdges:
    def test_register_round_trip(self, tmp_path):
        reg = {"claims": [
            {"id": "C-1", "status": "SUPERSEDED",
             "statement": "old", "superseded_by": "C-2"},
            {"id": "C-2", "status": "OPEN", "statement": "new",
             "supersedes": ["C-1"], "derived_from": []},
        ]}
        p = tmp_path / "claim-register.yaml"
        _write_yaml(p, reg)
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        c1, c2 = loaded["claims"]
        assert c1["superseded_by"] == "C-2"
        assert c2["supersedes"] == ["C-1"]
        assert c2["derived_from"] == []

    def test_carrier_gate_accepts_lineage_fields(self, tmp_path):
        """Additive tolerance: register WITH the new fields passes the
        strictest register consumer (carrier_consistency)."""
        from carrier_consistency import check
        ws = tmp_path
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "SUPERSEDED", "statement": "old",
             "superseded_by": "C-2"},
            {"id": "C-2", "status": "OPEN", "statement": "new",
             "supersedes": ["C-1"], "derived_from": []},
        ]})
        result = check(ws)
        assert not [v for v in result["violations"] if v.startswith("(g)")], (
            result["violations"])

    def test_carrier_gate_dangling_and_self_loop(self, tmp_path):
        from carrier_consistency import check
        ws = tmp_path
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "OPEN", "statement": "x",
             "supersedes": ["C-404"]},                      # dangling
            {"id": "C-2", "status": "OPEN", "statement": "x",
             "supersedes": ["C-2"]},                        # self-loop
            {"id": "C-3", "status": "OPEN", "statement": "x",
             "derived_from": ["no-such-claim"]},            # dangling
        ]})
        result = check(ws)
        g = [v for v in result["violations"] if v.startswith("(g)")]
        assert len(g) >= 3, result["violations"]
        assert any("C-404" in v for v in g)
        assert any("C-2" in v and "itself" in v for v in g)

    def test_carrier_gate_cycle_detection(self, tmp_path):
        from carrier_consistency import check
        ws = tmp_path
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "OPEN", "statement": "x",
             "supersedes": ["C-2"]},
            {"id": "C-2", "status": "OPEN", "statement": "x",
             "supersedes": ["C-1"]},
        ]})
        result = check(ws)
        g = [v for v in result["violations"] if v.startswith("(g)")]
        assert any("cycle" in v.lower() for v in g), result["violations"]

    def test_retract_claim_superseded_by_writes_both_edges(self, tmp_path):
        """The mechanical SUPERSEDED writer records the edge on BOTH sides."""
        ws = tmp_path
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "PROVEN", "statement": "old"},
            {"id": "C-2", "status": "OPEN", "statement": "replacement"},
        ]})
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "retract_claim.py"),
             str(ws), "C-1", "--reason", "superseded",
             "--superseded-by", "C-2", "--by", "facts/F001.md"],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT), errors="replace")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        claims = {c["id"]: c for c in
                  yaml.safe_load((ws / "claim-register.yaml")
                                 .read_text(encoding="utf-8"))["claims"]}
        assert claims["C-1"]["superseded_by"] == "C-2"
        assert claims["C-2"]["supersedes"] == ["C-1"]


# ---------- 1.4 same-mission join (acceptance) ---------------------------

class TestSameMissionJoin:
    def test_dispatch_worker_settlement_rows_share_trace_id(self, tmp_path):
        tid = new_trace_id("demo-mission", 1)
        emit(tmp_path, actor="hook:dispatch_gate", action="dispatch",
             claim="C-1", trace_id=tid)
        emit(tmp_path, actor="worker:kunglao-worker", action="verify",
             claim="C-1", trace_id=tid)
        emit(tmp_path, actor="orchestrator", action="converge",
             trace_id=tid)
        rows = _event_rows(tmp_path)
        assert len(rows) == 3
        assert {r["trace_id"] for r in rows} == {tid}, (
            f"all three rows must join on one trace_id; got "
            f"{[r.get('trace_id') for r in rows]}")

    def test_rows_without_trace_stay_null_not_absent(self, tmp_path):
        emit(tmp_path, actor="orchestrator", action="converge")
        row = _event_rows(tmp_path)[0]
        assert row["trace_id"] is None  # explicit null key, stable schema


# ---------- 1.5 un-attributed rate ---------------------------------------

class TestUnattributedRate:
    def test_all_unattributed(self, tmp_path):
        emit(tmp_path, actor="orchestrator", action="converge")
        emit(tmp_path, actor="orchestrator", action="verify")
        stats = kunglao_log.unattributed_rate(tmp_path)
        assert stats["rows"] == 2 and stats["unattributed"] == 2
        assert stats["rate"] == 1.0

    def test_partial(self, tmp_path):
        emit(tmp_path, actor="orchestrator", action="converge",
             trace_id="tr-m-0001")
        emit(tmp_path, actor="orchestrator", action="verify")
        stats = kunglao_log.unattributed_rate(tmp_path)
        assert stats["rows"] == 2 and stats["unattributed"] == 1
        assert stats["rate"] == 0.5

    def test_empty_ledger(self, tmp_path):
        stats = kunglao_log.unattributed_rate(tmp_path)
        assert stats == {"rows": 0, "attributed": 0, "unattributed": 0,
                         "rate": 0.0}


# ---------- 1.6 actor literal CI anchor ----------------------------------

class TestActorLiteralAnchor:
    def test_every_actor_literal_in_scripts_and_hooks_is_registered(self):
        """Repo-wide anchor: every actor literal in scripts/*.py +
        hooks/*.py must be IN the strict vocabulary OR adopted into
        kunglao_log.LEGACY_ACTORS (the #459 EMIT_ACTIONS adoption
        discipline). An unknown literal turns the suite red."""
        violations = kunglao_log.scan_actor_literals(REPO_ROOT)
        assert not violations, (
            f"unregistered actor literals (extend validate_actor vocabulary "
            f"or LEGACY_ACTORS in scripts/kunglao_log.py): {violations}")

    def test_anchor_detects_unknown_actor_literal(self, tmp_path):
        sub = tmp_path / "scripts"
        sub.mkdir()
        (sub / "fake.py").write_text(
            'kunglao_log.emit(ws, actor="mystery_actor", action="verify")\n',
            encoding="utf-8")
        violations = kunglao_log.scan_actor_literals(tmp_path)
        assert "scripts/fake.py" in violations
        assert "mystery_actor" in violations["scripts/fake.py"]


# ---------- 1.7 dispatch_gate allocation / reuse faces --------------------

class TestDispatchGateTrace:
    def test_envelope_trace_id_is_reused(self, tmp_path):
        ws = _make_ws(tmp_path / "r1")
        r = _run_gate(tmp_path / "r1", ws,
                      _envelope("tr-demo-mission-0001") + " do work")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        rows = _event_rows(ws)
        # reuse face: the linkage dispatch row is worker_budget's face; the
        # gate itself must NOT allocate nor emit trace_allocated here
        assert not [x for x in rows if x["action"] == "trace_allocated"]
        assert "tr-demo-mission-0001" not in r.stderr

    def test_missing_trace_id_allocates_mission_stable(self, tmp_path):
        ws = _make_ws(tmp_path / "r2")
        r1 = _run_gate(tmp_path / "r2", ws, _envelope() + " do work")
        assert r1.returncode == 0, f"stderr={r1.stderr!r}"
        rows = _event_rows(ws)
        alloc = [x for x in rows if x["action"] == "trace_allocated"]
        assert len(alloc) == 1, [x["action"] for x in rows]
        tid1 = alloc[0]["trace_id"]
        assert tid1 and tid1.startswith("tr-demo-mission-")
        # mission-stable: the state file carries it, second dispatch reuses
        r2 = _run_gate(tmp_path / "r2", ws, _envelope() + " more work")
        assert r2.returncode == 0
        alloc = [x for x in _event_rows(ws)
                 if x["action"] == "trace_allocated"]
        assert len(alloc) == 1, "reuse must NOT re-allocate"
        state = json.loads((ws / TRACE_STATE).read_text(encoding="utf-8"))
        assert state["trace_id"] == tid1
        assert state["mission"] == "demo-mission"

    def test_invalid_declared_trace_warns_and_reallocates(self, tmp_path):
        ws = _make_ws(tmp_path / "r3")
        r = _run_gate(tmp_path / "r3", ws, _envelope("not-a-trace") + " work")
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        assert "WARN" in r.stderr and "trace" in r.stderr.lower()
        rows = _event_rows(ws)
        alloc = [x for x in rows if x["action"] == "trace_allocated"]
        assert len(alloc) == 1
        assert alloc[0]["trace_id"] != "not-a-trace"
        assert validate_trace_id(alloc[0]["trace_id"])

    def test_inactive_gate_untouched(self, tmp_path):
        ws = _make_ws(tmp_path / "r4")
        (ws / ".hook_state.json").unlink()
        r = _run_gate(tmp_path / "r4", ws, _envelope() + " work")
        assert r.returncode == 0
        assert not (ws / TRACE_STATE).exists(), (
            "inactive gate must not allocate (hooks sleep)")


# ---------- 1.8 worker echo channels --------------------------------------

class TestWorkerEcho:
    def test_worker_status_trace_token_does_not_break_parsing(self):
        base = ("[10:00] step: started C-1 | status: in-progress\n"
                "[10:05] step: grep sweep | status: in-progress | "
                "trace: tr-m-0001\n"
                "[10:10] step: done | status: done | trace: tr-m-0001 | "
                "artifacts: facts/F001.md\n")
        tokens = _LK.parse_worker_status_tokens(base)
        assert tokens == ["in-progress", "in-progress", "done"]
        assert _LK.parse_worker_status(base) == "done"

    def test_fact_frontmatter_trace_id_passes_lint(self, tmp_path):
        from lint_facts import lint_workspace
        ws = tmp_path
        (ws / "facts").mkdir(parents=True)
        fm = {
            "id": "F001-demo", "type": "fact", "schema_rev": 2,
            "title": "demo", "status": "OPEN", "created": "2026-09-01",
            "last_reviewed": "2026-09-01", "source": "static-decompile",
            "claim_id": "C-1", "boundary_type": "observation",
            "promotion_gate": "some gate", "provenance": [
                {"role": "sample_raw", "path": "bins/x",
                 "content_sha256": "a" * 64, "credibility": "A1"}],
            "claim": "demo", "reproduce": "echo hi", "expected": "hi",
            "verified": "pending", "trace_id": "tr-demo-mission-0001",
        }
        body = ("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n"
                + "## Claim\n\ndemo\n\n## Status\n\nOPEN\n")
        (ws / "facts" / "F001-demo.md").write_text(body, encoding="utf-8")
        issues = lint_workspace(ws)
        unknown = [i for i in issues
                   if i[1] == "UNKNOWN_KEY" and "trace_id" in i[2]]
        assert not unknown, issues


# ---------- 1.9 plan_review structural diff -------------------------------

class TestPlanReviewDiff:
    def test_replan_detail_carries_stages_diff(self, tmp_path):
        import plan_stages
        ws = tmp_path
        old = [
            {"id": "s1", "name": "n1", "goal": "g", "claims": ["C-1"],
             "expected_evidence": ["e"], "exit_criteria": ["x"],
             "status": "done"},
            {"id": "s2", "name": "n2", "goal": "g", "claims": ["C-2"],
             "expected_evidence": ["e"], "exit_criteria": ["x"],
             "status": "pending"},
        ]
        new = [
            {"id": "s1", "name": "n1", "goal": "g", "claims": ["C-1"],
             "expected_evidence": ["e"], "exit_criteria": ["x"],
             "status": "done"},
            {"id": "s3", "name": "n3", "goal": "g", "claims": ["C-2"],
             "expected_evidence": ["e"], "exit_criteria": ["x"],
             "status": "pending"},
        ]
        plan_stages.write_stages(ws, old)
        res = plan_stages.review(ws, "replan", "s1", reason="pivot",
                                 new_stages=new)
        assert res.get("ok"), res
        rows = _event_rows(ws)
        pr = [r for r in rows if r["action"] == "plan_review"]
        assert len(pr) == 1
        detail = json.loads(pr[0]["detail"])
        assert detail["stages_diff"] == {
            "added": ["s3"], "removed": ["s2"], "changed": []}

    def test_maintain_has_no_diff(self, tmp_path):
        import plan_stages
        ws = tmp_path
        stage = {"id": "s1", "name": "n1", "goal": "g", "claims": ["C-1"],
                 "expected_evidence": ["e"], "exit_criteria": ["x"],
                 "status": "active"}
        plan_stages.write_stages(ws, [stage])
        res = plan_stages.review(ws, "maintain", "s1", reason="ok")
        assert res.get("ok"), res
        pr = [r for r in _event_rows(ws) if r["action"] == "plan_review"]
        detail = json.loads(pr[0]["detail"])
        assert detail.get("stages_diff") is None
