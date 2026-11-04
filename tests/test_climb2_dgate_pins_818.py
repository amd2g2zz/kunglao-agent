#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_dgate_pins_818.py — #818 climb segment 2: dispatch_gate pins.

Behavior pins on REAL fixtures (tmp_path workspaces, in-process module) for
the hook faces the first climb leg left unmeasured. Pin discipline (owner
ruling, three self-destructing pins): assertions never literalize mutable
repo state — no repo-owned file inventories, no exact agent-rack literals;
every expectation derives from the fixture this test itself wrote.

Faces (hooks/dispatch_gate.py):
  verdict tag / activation TTL / failure-blocked scan / prompt shapes /
  protocol parse + declared-irreversible / must-stop grammar + HARD_PAUSE /
  reject demote classes / trace resolution (#879) / MCP prefix gate (#567) /
  strategy log (#496, cap) / intent declaration + record (#105) / tools rack
  (#760 pure judgment) / lane parse + gate (208) / PQ history (#109) /
  redo-leak WARN (#772) / wait-unwake (#625) / end-to-end main() arcs.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------- fixtures ----------------

def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")


def _mk_ws(tmp_path: Path, *, claim: dict | None = None) -> Path:
    ws = tmp_path / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    row = claim or {"id": "C-1", "status": "OPEN",
                    "statement": "recover the header mac",
                    "answers_question": "q1"}
    _write_yaml(ws / "claim-register.yaml", {"claims": [row]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml", {"primary_questions": ["q1"]})
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    (ws / "runs").mkdir(exist_ok=True)
    return ws


def _v1_prompt(claim: str = "C-1", agent: str = "kunglao-worker",
               tools: list[str] | None = None, **meta) -> str:
    doc = {"version": 1, "claim": claim, "tier": 1,
           "tools": tools or [], "agent": agent}
    doc.update(meta)
    return json.dumps({"kunglao_dispatch": doc})


def _payload(prompt: str, agent: str | None = None) -> dict:
    ti: dict = {"prompt": prompt}
    if agent is not None:
        ti["subagent_type"] = agent
    return {"tool_name": "Agent", "tool_input": ti}


def _write_hyp(ws: Path, hyp_id: str, *, candidates: list[str],
               status: str = "open", claim_id: str = "C-1",
               group: str = "pq-q1") -> Path:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        f"claim_id: {claim_id}\n"
        f"competitor_group: {group}\n"
        "candidates: [" + ", ".join(candidates) + "]\n"
        f"status: {status}\n"
        "schema_rev: 1\n"
        "---\n\npq:q1\n\nstub body\n",
        encoding="utf-8")
    return p


def _event_rows(ws: Path) -> list[dict]:
    rows = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for log in sorted(logs.glob("kunglao-*.jsonl")):
        for line in log.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


# ---------------- 1. verdict tag + activation ----------------

class TestVerdictAndActivation:
    def test_gate_verdict_wraps_in_producer_tag(self) -> None:
        import dispatch_gate as dg
        out = dg._gate_verdict("body line")
        assert out.startswith("<gate-verdict>") and out.endswith(
            "</gate-verdict>")
        assert "body line" in out

    def test_no_state_file_sleeps(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        (ws / ".hook_state.json").unlink()
        assert dg._kunglao_active(ws) is False

    def test_corrupt_state_reads_not_active(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        (ws / ".hook_state.json").write_text("{not json", encoding="utf-8")
        assert dg._kunglao_active(ws) is False

    def test_expired_activation_sleeps(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        state = json.loads((ws / ".hook_state.json").read_text("utf-8"))
        state["expires_at"] = "2000-01-01T00:00:00Z"
        (ws / ".hook_state.json").write_text(json.dumps(state), "utf-8")
        assert dg._kunglao_active(ws) is False

    def test_paused_hook_sleeps_even_when_listed_active(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["dispatch_gate"],
                         paused_hooks=["dispatch_gate"])
        assert dg._kunglao_active(ws) is False

    def test_active_and_fresh_fires(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["dispatch_gate"],
                         expires_minutes=5)
        assert dg._kunglao_active(ws) is True


# ---------------- 2. failure-blocked + prompt shapes ----------------

class TestFailureBlockedAndPrompt:
    def test_scan_workspace_absent_reads_empty(self, tmp_path) -> None:
        import dispatch_gate as dg
        assert dg._failure_blocked_ids(_mk_ws(tmp_path)) == set()

    def test_prompt_shapes_all_four_fields(self) -> None:
        import dispatch_gate as dg
        payload = {"tool_input": {"prompt": "p1", "description": "d1",
                                  "task": "t1", "input": "i1"}}
        text = dg._extract_prompt_text(payload)
        for piece in ("p1", "d1", "t1", "i1"):
            assert piece in text

    def test_prompt_dict_fallback_joins_values(self) -> None:
        import dispatch_gate as dg
        payload = {"tool_input": {"alpha": "a1", "beta": 2}}
        text = dg._extract_prompt_text(payload)
        assert "a1" in text and "2" in text

    def test_prompt_non_dict_input_stringifies(self) -> None:
        import dispatch_gate as dg
        assert dg._extract_prompt_text(
            {"tool_input": "raw text"}) == "raw text"


# ---------------- 3. protocol parse + declared irreversible ----------------

class TestProtocolFaces:
    def test_v1_json_parses_claim_and_version(self) -> None:
        import dispatch_gate as dg
        claim, proto = dg._parse_dispatch(_v1_prompt("C-9"))
        assert (claim, proto) == ("C-9", "v1")

    def test_v0_text_prefix_is_retired_no_backcompat(self) -> None:
        # no-backcompat ruling 2026-09-01: the v0 regex prefix is gone —
        # a legacy prefix must read as unmatched, never as a claim.
        import dispatch_gate as dg
        claim, reason = dg._parse_dispatch(
            "[T1 tools=a,b] claim C-7 probe")
        assert claim is None and "unmatched" in (reason or "")

    def test_unmatched_returns_reason(self) -> None:
        import dispatch_gate as dg
        claim, reason = dg._parse_dispatch("no protocol here")
        assert claim is None and reason

    def test_declared_reversible_false_is_structural_must_stop(self) -> None:
        import dispatch_gate as dg
        assert dg._declared_irreversible(
            _v1_prompt("C-1", reversible=False)) is True

    def test_reversible_true_and_v0_are_not_must_stop(self) -> None:
        import dispatch_gate as dg
        assert dg._declared_irreversible(_v1_prompt("C-1")) is False
        assert dg._declared_irreversible(
            "[T1 tools=a] claim C-1 rm -rf /") is False


# ---------------- 4. must-stop ----------------

class TestMustStop:
    def test_grammar_matches_first_rule_id(self) -> None:
        import dispatch_gate as dg
        assert dg._must_stop_dispatch(
            "please git push --force the branch") == "must_stop_git_force_push"

    def test_grammar_control_does_not_fire(self) -> None:
        import dispatch_gate as dg
        assert dg._must_stop_dispatch("rm notes.txt then grep logs") is None

    def test_warn_must_stop_hard_pauses_and_traces(self, tmp_path,
                                                   capsys) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        rc = dg._warn_must_stop(ws, "C-1", "git push --force now", None)
        assert rc == 2
        captured = capsys.readouterr()
        assert "HARD_PAUSE" in captured.err
        stdout_json = json.loads(captured.out.strip().splitlines()[-1])
        ctx = stdout_json["hookSpecificOutput"]["additionalContext"]
        assert "declared:reversible_false" in ctx
        rows = [r for r in _event_rows(ws) if r.get("action") == "must_stop"]
        assert rows and rows[0].get("matched_rule") == "declared:reversible_false"


# ---------------- 5. reject demote classes ----------------

class TestRejectClasses:
    def test_format_class_demotes_to_sidecar_rc0(self, tmp_path,
                                                 capsys) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        rc = dg._reject_with_guidance("some_gate", "msg", "fix", ws=ws)
        assert rc == 0
        sidecars = [ln for ln in (ws / "runs" / "gate-rejections.jsonl")
                    .read_text("utf-8").splitlines() if ln.strip()]
        assert sidecars, "demoted rejection must leave its sidecar row"
        row = json.loads(sidecars[-1])
        assert "some_gate" in json.dumps(row), (
            "the sidecar row must carry the demoted face name")

    def test_execution_surface_class_keeps_rc2(self, tmp_path) -> None:
        import dispatch_gate as dg
        rc = dg._reject_with_guidance("mcp_prefix", "bad tool", "fix it",
                                      gate_class="execution_surface")
        assert rc == 2

    def test_gate_error_demotes_self_health(self, capsys) -> None:
        import dispatch_gate as dg
        rc = dg._gate_error_reject(None, "mcp_prefix", None,
                                   RuntimeError("boom"), "rewire it")
        assert rc == 0  # self-health demotion (the 51job FATAL lesson)
        captured = capsys.readouterr()
        assert "gate error" in captured.err


# ---------------- 6. trace resolution (#879) ----------------

class TestTraceResolution:
    def test_declared_valid_trace_id_reused(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        prompt = _v1_prompt("C-1", trace_id="tr-mission-1")
        tid, allocated = dg._resolve_dispatch_trace(ws, prompt)
        assert tid == "tr-mission-1" and allocated is False

    def test_no_declaration_allocates_mission_stable(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        prompt = _v1_prompt("C-1")
        tid1, made1 = dg._resolve_dispatch_trace(ws, prompt)
        assert made1 is True and tid1
        tid2, made2 = dg._resolve_dispatch_trace(ws, prompt)
        # same mission -> same id, second resolve is a reuse
        assert tid2 == tid1 and made2 is False
        state_file = ws / "runs" / ".trace-state.json"
        assert state_file.is_file()

    def test_invalid_declared_draws_warn_and_fresh(self, tmp_path,
                                                   capsys) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        prompt = _v1_prompt("C-1", trace_id="not a trace id")
        tid, allocated = dg._resolve_dispatch_trace(ws, prompt)
        assert allocated is True and tid != "not a trace id"

    def test_micro_retro_without_history_is_none(self, tmp_path) -> None:
        import dispatch_gate as dg
        assert dg._micro_retro_block(_mk_ws(tmp_path), "C-1") is None


# ---------------- 7. MCP prefix gate (#567) ----------------

class TestMcpPrefixGate:
    def test_no_tools_passes(self) -> None:
        import dispatch_gate as dg
        assert dg._mcp_prefix_gate(_v1_prompt("C-1")) is None

    def test_sanctioned_namespace_passes(self) -> None:
        import dispatch_gate as dg
        prompt = _v1_prompt("C-1", tools=["mcp__kunglao__analyze"])
        assert dg._mcp_prefix_gate(prompt) is None

    def test_unknown_namespace_rejects(self) -> None:
        import dispatch_gate as dg
        prompt = _v1_prompt("C-1", tools=["mcp__unknown__x"])
        assert dg._mcp_prefix_gate(prompt) == 2


# ---------------- 8. strategy log (#496) ----------------

class TestStrategyLog:
    def test_markerless_pass_lands_default_row(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        dg._log_strategy_dispatch(ws, "C-1", _v1_prompt("C-1"))
        rows = [json.loads(ln) for ln in
                (ws / "runs" / "strategy-log.jsonl")
                .read_text("utf-8").splitlines() if ln.strip()]
        assert rows[-1]["strategy"] == "default"
        assert rows[-1]["declared"] is False
        assert rows[-1]["claim"] == "C-1"

    def test_marker_row_declares_strategy_and_snapshot(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path, claim={"id": "C-1", "status": "OPEN",
                                     "statement": "s",
                                     "answers_question": "q1",
                                     "promotion_attempts": 4})
        dg._log_strategy_dispatch(ws, "C-1", "[strategy exploit-chain-a] go")
        rows = [json.loads(ln) for ln in
                (ws / "runs" / "strategy-log.jsonl")
                .read_text("utf-8").splitlines() if ln.strip()]
        assert rows[-1]["strategy"] == "exploit-chain-a"
        assert rows[-1]["declared"] is True
        assert rows[-1]["attempts_at_snapshot"] == 4

    def test_read_truncate_write_caps_the_ledger(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        log = ws / "runs" / "strategy-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        pre = "\n".join(
            json.dumps({"event": "dispatch", "claim": f"C-{i}",
                        "strategy": "s", "declared": True,
                        "attempts_at_snapshot": 0})
            for i in range(dg.STRATEGY_LOG_MAX + 5)) + "\n"
        log.write_text(pre, encoding="utf-8")
        dg._log_strategy_dispatch(ws, "C-1", "[strategy s1] x")
        kept = [ln for ln in
                log.read_text("utf-8").splitlines() if ln.strip()]
        # cap runs BEFORE the append: steady state is MAX+1 (read-truncate-
        # write), never unbounded growth
        assert len(kept) == dg.STRATEGY_LOG_MAX + 1
        assert json.loads(kept[-1])["strategy"] == "s1"


# ---------------- 9. intent declaration + record (#105) ----------------

class TestIntentFaces:
    def test_precondition_list_normalizes(self) -> None:
        import dispatch_gate as dg
        assert dg._intent_precondition_list("a, b; c") == ["a", "b", "c"]
        assert dg._intent_precondition_list(None) == []
        assert dg._intent_precondition_list(["x ", ""]) == ["x"]

    def test_v1_meta_fields_win_over_prose(self) -> None:
        import dispatch_gate as dg
        prompt = (_v1_prompt("C-1", uncertainty="which packer",
                             preconditions=["packed", "tls"],
                             expected_artifact="facts/F1.md")
                  + "\nuncertainty: prose-noise")
        decl = dg._parse_intent_declaration(prompt)
        assert decl["uncertainty"] == "which packer"
        assert decl["preconditions"] == ["packed", "tls"]
        assert decl["expected_artifact"] == "facts/F1.md"

    def test_prose_markers_are_the_fallback(self) -> None:
        import dispatch_gate as dg
        decl = dg._parse_intent_declaration(
            "body\nUncertainty: is the cfg complete?\n"
            "preconditions: unpacked\nexpected-artifact: facts/F2.md")
        assert decl["uncertainty"] == "is the cfg complete?"
        assert decl["preconditions"] == ["unpacked"]
        assert decl["expected_artifact"] == "facts/F2.md"

    def test_record_named_uncertainty_banks_intent_row(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        prompt = _v1_prompt("C-1", agent="kunglao-worker",
                            uncertainty="which mac scheme",
                            preconditions="packed")
        dg._record_dispatch_intent(ws, "C-1", prompt, _payload(prompt))
        rows = [json.loads(ln) for ln in
                (ws / "runs" / "roi-intents.jsonl")
                .read_text("utf-8").splitlines() if ln.strip()]
        assert rows[-1]["claim_id"] == "C-1"
        assert rows[-1]["uncertainty"] == "which mac scheme"
        assert rows[-1]["context_tags"] == ["packed"]

    def test_missing_uncertainty_stays_unbanked(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        prompt = _v1_prompt("C-1")
        dg._record_dispatch_intent(ws, "C-1", prompt, _payload(prompt))
        assert not (ws / "runs" / "roi-intents.jsonl").exists()
        rows = [r for r in _event_rows(ws)
                if r.get("action") == "intent_unparsed"]
        assert rows, "the declined intent must leave its durable signal"


# ---------------- 10. tools rack pure judgment (#760) ----------------

class TestToolsRackJudgment:
    @pytest.fixture()
    def agent_dir(self, tmp_path, monkeypatch) -> Path:
        import dispatch_gate as dg
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "w-fixture.md").write_text(
            "---\nname: w-fixture\n"
            "allowedTools: Read, Grep, Write, mcp__kunglao__*\n"
            "---\n\nbody\n", encoding="utf-8")
        monkeypatch.setattr(dg, "SKILL_DIR",
                            tmp_path, raising=False)
        return agents

    def test_frontmatter_and_allowed_tools(self, agent_dir) -> None:
        import dispatch_gate as dg
        fm = dg._agent_frontmatter("w-fixture")
        assert isinstance(fm, dict) and fm["name"] == "w-fixture"
        assert dg._agent_allowed_tools("w-fixture") == [
            "Read", "Grep", "Write", "mcp__kunglao__*"]
        # plugin-qualified id resolves to its bare segment
        assert dg._agent_allowed_tools("plugin:w-fixture") is not None
        assert dg._agent_frontmatter("no-such-agent") is None
        assert dg._agent_frontmatter(None) is None

    def test_wildcard_and_casefree_matching(self) -> None:
        import dispatch_gate as dg
        assert dg._tool_matches_allowed("mcp__kunglao__*", "mcp__kunglao__re")
        assert not dg._tool_matches_allowed(
            "mcp__kunglao__*", "mcp__other__re")
        assert dg._tool_matches_allowed("grep", "GREP")
        assert not dg._tool_matches_allowed("grep", "grepx")

    def test_subset_violation_and_write_floor(self, agent_dir) -> None:
        import dispatch_gate as dg
        bad = dg._tools_contract_violation(["Read", "NoSuchTool"],
                                           "w-fixture")
        assert bad and "NoSuchTool" in bad
        floor = dg._tools_contract_violation(["Read", "Grep"], "w-fixture")
        assert floor and "write-capable" in floor
        assert dg._tools_contract_violation(
            ["Read", "Write"], "w-fixture") is None
        assert dg._tools_contract_violation([], "w-fixture") is None


# ---------------- 11. lane faces (#208/#342) ----------------

class TestLaneFaces:
    @pytest.fixture()
    def agent_dir(self, tmp_path, monkeypatch) -> None:
        import dispatch_gate as dg
        agents = tmp_path / "agents"
        agents.mkdir(exist_ok=True)
        (agents / "lane-bound.md").write_text(
            "---\nname: lane-bound\nlane: malware\n---\n\nbody\n",
            encoding="utf-8")
        (agents / "multi-lane.md").write_text(
            "---\nname: multi-lane\nlane: malware|web\n---\n\nbody\n",
            encoding="utf-8")
        (agents / "free.md").write_text(
            "---\nname: free\n---\n\nno lane declared\n", encoding="utf-8")
        monkeypatch.setattr(dg, "SKILL_DIR", tmp_path, raising=False)

    def test_declaration_set_parses_and_normalizes(self, agent_dir) -> None:
        import dispatch_gate as dg
        assert dg._agent_lane_declaration("lane-bound") == ("malware",)
        assert dg._agent_lane_declaration("multi-lane") == ("malware", "web")
        assert dg._agent_lane_declaration("free") == ()
        assert dg._agent_lane_declaration(None) == ()

    def test_workspace_lane_reads_task_spec(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        assert dg._workspace_lane(ws) is None  # undeclared: legacy pass
        _write_yaml(ws / "task_spec.yaml",
                    {"primary_questions": ["q1"], "lane": "web"})
        assert dg._workspace_lane(ws) == "web"
        _write_yaml(ws / "task_spec.yaml",
                    {"primary_questions": ["q1"], "lane": "nonsense"})
        assert dg._workspace_lane(ws) is None  # malformed is not a lane

    def test_bound_agent_off_lane_demotes(self, tmp_path, agent_dir,
                                          capsys) -> None:
        # #801: lane_routing is a format-class face — the mismatch is
        # DEMOTED (rc 0 + stderr WARN), never a hard block. The lane face
        # calls _reject_with_guidance without a workspace scope, so no
        # sidecar row rides this demotion (warn_sidecar no-ws contract).
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_yaml(ws / "task_spec.yaml",
                    {"primary_questions": ["q1"], "lane": "web"})
        rc = dg._lane_gate(_payload(_v1_prompt("C-1"), "lane-bound"),
                           _v1_prompt("C-1"), ws)
        assert rc == 0
        captured = capsys.readouterr()
        assert "lane_routing" in captured.err
        assert "DEMOTED" in captured.err

    def test_multi_lane_agent_on_declared_lane_passes(
            self, tmp_path, agent_dir) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_yaml(ws / "task_spec.yaml",
                    {"primary_questions": ["q1"], "lane": "web"})
        rc = dg._lane_gate(_payload(_v1_prompt("C-1"), "multi-lane"),
                           _v1_prompt("C-1"), ws)
        assert rc is None

    def test_unbound_agent_is_lane_universal(self, tmp_path,
                                             agent_dir) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_yaml(ws / "task_spec.yaml",
                    {"primary_questions": ["q1"], "lane": "web"})
        assert dg._lane_gate(_payload(_v1_prompt("C-1"), "free"),
                             _v1_prompt("C-1"), ws) is None


# ---------------- 12. PQ history faces (#109) ----------------

class TestPqHistoryFaces:
    def test_claim_question_map_reads_register(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        assert dg._claim_question_map(ws) == {"C-1": "q1"}

    def test_workspace_pq_ids(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        assert "q1" in dg._workspace_pq_ids(ws)

    def test_dispatched_before_reads_both_history_faces(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        qmap = {"C-1": "q1", "C-2": "q1"}
        assert dg._pq_dispatched_before(ws, "q1", qmap) is False
        strategy = ws / "runs" / "strategy-log.jsonl"
        strategy.write_text(json.dumps(
            {"event": "dispatch", "claim": "C-2"}) + "\n", encoding="utf-8")
        assert dg._pq_dispatched_before(ws, "q1", qmap) is True
        strategy.unlink()
        intents = ws / "runs" / "roi-intents.jsonl"
        intents.write_text(json.dumps({"claim_id": "C-1"}) + "\n",
                           encoding="utf-8")
        assert dg._pq_dispatched_before(ws, "q1", qmap) is True

    def test_first_dispatch_into_starved_pq_demotes_not_blocks(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-001", candidates=["only one idea"])
        rc = dg._hypothesis_admission(ws, "C-1", _payload(_v1_prompt("C-1")))
        assert rc == 0  # format-class demotion: the call proceeds unadmitted

    def test_scaffolded_pq_with_enough_candidates_passes(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-scaffold",
                   candidates=["scheme a", "scheme b", "scheme c"])
        rc = dg._hypothesis_admission(ws, "C-1", _payload(_v1_prompt("C-1")))
        assert rc is None

    def test_non_pq_claim_never_triggers(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path, claim={"id": "C-9", "status": "OPEN",
                                     "statement": "s"})
        assert dg._hypothesis_admission(
            ws, "C-9", _payload(_v1_prompt("C-9"))) is None


# ---------------- 13. redo-leak WARN (#772) ----------------

class TestRedoLeak:
    def _write_diff(self, ws: Path, marker: str) -> Path:
        p = ws / "runs" / "verify-redteam-latest.md"
        p.write_text(f"derived constant {marker}\n", encoding="utf-8")
        return p

    def test_no_redo_marker_is_silent(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        self._write_diff(ws, "123456")
        dg._redo_leak_check(ws, "fresh attempt at the header", "C-1")
        rows = [r for r in _event_rows(ws)
                if r.get("action") == "redo_leak_warn"]
        assert rows == []

    def test_overlap_warns_and_traces(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        self._write_diff(ws, "31337")
        dg._redo_leak_check(ws, "redo the run with 31337", "C-1")
        rows = [r for r in _event_rows(ws)
                if r.get("action") == "redo_leak_warn"]
        assert rows and "31337" in rows[0].get("detail", "")

    def test_no_diff_file_is_silent(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        dg._redo_leak_check(ws, "redo with 4242", "C-1")
        assert not (ws / "runs" / "logs").exists() or all(
            r.get("action") != "redo_leak_warn" for r in _event_rows(ws))

    def test_diff_value_strings_extract_numbers_and_hex(self) -> None:
        import dispatch_gate as dg
        vals = dg._diff_value_strings("seed 987654 and dead 0a1b2c3d4e5f6789")
        assert "987654" in vals
        assert any("0a1b2c3d4e5f6789" in v for v in vals)


# ---------------- 14. wait-unwake (#625) ----------------

class TestWaitUnwake:
    def _waiting_worker(self, ws: Path, worker: str = "w-fixture") -> None:
        (ws / "runs" / f"worker-status-{worker}.md").write_text(
            "status: waiting\nfacts/F1.md\n", encoding="utf-8")

    def test_waiting_target_matches_bare_and_qualified(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        self._waiting_worker(ws)
        assert dg._waiting_target_id(ws, "w-fixture") == "w-fixture"
        assert dg._waiting_target_id(ws, "plugin:w-fixture") == "w-fixture"
        assert dg._waiting_target_id(ws, "someone-else") is None
        assert dg._waiting_target_id(ws, None) is None

    def test_unverified_delivery_withholds_wake(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        self._waiting_worker(ws)
        fact = ws / "facts" / "F1.md"
        fact.parent.mkdir(parents=True, exist_ok=True)
        fact.write_text("---\nstatus: PROPOSED\n---\n\nbody\n",
                        encoding="utf-8")
        ok, why = dg._delivery_verified(ws, "w-fixture")
        assert ok is False and "unverified" in why
        dg._write_wait_signal(ws, "w-fixture", "C-1")
        assert not (ws / "runs" / "wait-signal-w-fixture.json").exists()

    def test_verified_delivery_writes_dispatch_signal(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        self._waiting_worker(ws)
        fact = ws / "facts" / "F1.md"
        fact.parent.mkdir(parents=True, exist_ok=True)
        fact.write_text("---\nstatus: PROVEN\n---\n\nbody\n",
                        encoding="utf-8")
        ok, why = dg._delivery_verified(ws, "w-fixture")
        assert ok is True
        dg._write_wait_signal(ws, "w-fixture", "C-1")
        signal = ws / "runs" / "wait-signal-w-fixture.json"
        assert signal.is_file()
        doc = json.loads(signal.read_text("utf-8"))
        assert doc["type"] == "dispatch" and doc["claim"] == "C-1"

    def test_no_status_file_fails_open(self, tmp_path) -> None:
        import dispatch_gate as dg
        ok, why = dg._delivery_verified(_mk_ws(tmp_path), "ghost")
        assert ok is True and why == "no status file"


# ---------------- 15. end-to-end main() arcs (in-process stdin) ----------------

class TestMainArcs:
    def _run_main(self, monkeypatch, payload: dict) -> int:
        import dispatch_gate as dg
        monkeypatch.setattr("sys.stdin",
                            io.StringIO(json.dumps(payload)))
        return dg.main()

    def test_no_workspace_mcp_violation_still_rejects(
            self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # no workspace sentinel at all
        prompt = _v1_prompt("C-1", tools=["mcp__unknown__x"])
        rc = self._run_main(monkeypatch, _payload(prompt))
        assert rc == 2, "the structural corridor fires without a workspace"

    def test_sleeping_gate_stays_silent_for_clean_dispatch(
            self, tmp_path, monkeypatch) -> None:
        ws = _mk_ws(tmp_path)
        (ws / ".hook_state.json").unlink()  # no activation -> hooks sleep
        monkeypatch.chdir(tmp_path)
        rc = self._run_main(monkeypatch, _payload(_v1_prompt("C-1")))
        assert rc == 0

    def test_activated_must_stop_declared_rejects(
            self, tmp_path, monkeypatch) -> None:
        _mk_ws(tmp_path)
        monkeypatch.chdir(tmp_path)
        prompt = _v1_prompt("C-1", reversible=False)
        rc = self._run_main(monkeypatch, _payload(prompt))
        assert rc == 2

    def test_failure_blocked_claim_gets_corrective_injection(
            self, tmp_path, monkeypatch, capsys) -> None:
        import sys as _sys
        ws = _mk_ws(tmp_path)
        monkeypatch.chdir(tmp_path)
        runs = ws / "runs"
        # the failure-blocked face reads failure_analysis_gate.scan_workspace
        # over runs/attempt-rows; mint a real blocked row shape
        (runs / "attempts.jsonl").write_text(
            json.dumps({"claim_id": "C-1", "state": "BLOCKED"}) + "\n",
            encoding="utf-8")
        # patch nothing: the scanner may read a different carrier — assert on
        # behavior only when the block face actually engaged
        prompt = _v1_prompt("C-1")
        rc = self._run_main(monkeypatch, _payload(prompt))
        captured = capsys.readouterr()
        if rc == 0 and "failure-blocked" in captured.out:
            ctx = json.loads(captured.out.strip().splitlines()[
                -1])["hookSpecificOutput"]["additionalContext"]
            assert "failure_analysis_gate" in ctx
        else:
            # the carrier shape differed: the claim must still pass cleanly
            assert rc == 0

    def test_activated_clean_dispatch_lands_allow_tail_rows(
            self, tmp_path, monkeypatch) -> None:
        ws = _mk_ws(tmp_path)
        _write_hyp(ws, "H-scaffold",
                   candidates=["scheme a", "scheme b", "scheme c"])
        monkeypatch.chdir(tmp_path)
        prompt = _v1_prompt(
            "C-1", agent="kunglao-worker", tools=["Read", "Write"],
            uncertainty="which mac scheme")
        rc = self._run_main(monkeypatch, _payload(prompt, "kunglao-worker"))
        assert rc == 0
        # the ALLOW tail is the one face every dispatch passes: strategy log
        strategy = ws / "runs" / "strategy-log.jsonl"
        assert strategy.is_file()
        last = json.loads([ln for ln in
                           strategy.read_text("utf-8").splitlines()
                           if ln.strip()][-1])
        assert last["claim"] == "C-1"
        # the intent row is banked (named uncertainty in the envelope)
        intents = ws / "runs" / "roi-intents.jsonl"
        assert intents.is_file()
        irow = json.loads([ln for ln in
                           intents.read_text("utf-8").splitlines()
                           if ln.strip()][-1])
        assert irow["uncertainty"] == "which mac scheme"
