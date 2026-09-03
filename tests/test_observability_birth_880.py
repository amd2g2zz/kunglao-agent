#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_observability_birth_880.py — #880 observability birth faces.

Covers the wiring the card adds on top of the double-ended emit gate:
  - toolfirst dual-face ledger rows: the tool-first gate emits BOTH faces
    (pass/reject) with the structured (keyword->tool) attribution payload the
    pass path used to discard (RC2), in the dual_gate._emit mirror shape
    (detail=JSON);
  - operation label: the attribution persists as claim attributes
    (operation: / operation_tool:) with a round-trip pin ("XOR jiami" is NOT
    "PE nixiang" — attribution granularity scene -> scene x operation);
  - tool_call birth (RC1): the word gets a real production emitter at the
    Agent PostToolUse face (claim-granularity v1 per the card);
  - claim_settled settlement rows at the register-carrier ALLOW face.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import worker_budget_gates as wbg  # noqa: E402


# ---------- shared seam: capture kunglao_log.emit in-process ----------------

@pytest.fixture
def events(monkeypatch):
    """Capture every kunglao_log.emit call (same convention as
    test_event_stream_adoption's fixture — lazy imports hit the module attr)."""
    import kunglao_log

    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


def _ws(tmp: Path) -> Path:
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    promotion_attempts: 0\n"
        "  - id: C-002\n"
        "    status: OPEN\n"
        "    promotion_attempts: 0\n",
        encoding="utf-8")
    return ws


# ---------- toolfirst dual-face rows (RC2) -----------------------------------

_KEYWORDS = {"crypto": "crypto-tool", "xor": "crypto-tool",
             "disasm": "disasm-tool"}


@pytest.fixture
def keywords(monkeypatch):
    monkeypatch.setattr(wbg, "_load_tool_index_keywords",
                        lambda root: dict(_KEYWORDS))


class TestToolfirstDualEmit:
    def test_matched_pass_emits_attribution_payload(self, tmp, events, keywords):
        """THE RC2 face: the pass path that computed keyword-to-tool mapping
        used to drop it. The pass row now carries the payload (detail=JSON,
        the dual_gate._emit mirror shape) — emitted at the APPROVAL point via
        toolfirst_pass_record."""
        ws = _ws(tmp)
        assert wbg.toolfirst_pass_record(
            {'workspace': str(ws)}, "C-001", "decode the crypto blob",
            "tool-catalog: crypto-tool") is True
        rows = [e for e in events if e["action"] == "toolfirst_pass"]
        assert rows, "pass face must emit toolfirst_pass"
        payload = json.loads(rows[-1]["detail"])
        assert payload["mode"] == "matched"
        assert payload["tool"] == "crypto-tool"
        # keywords present in the TEXT that map to the cited tool
        assert set(payload["keywords"]) == {"crypto"}
        assert rows[-1]["actor"] == "hook:worker_budget"
        assert rows[-1]["claim"] == "C-001"

    def test_reject_face_emits_keyword_tool_payload(self, tmp, events, keywords):
        ws = _ws(tmp)
        ok, _reason = wbg.check_tool_first(
            {'workspace': str(ws)}, "decode the crypto blob", "")
        assert ok is False
        rows = [e for e in events if e["action"] == "toolfirst_reject"]
        assert rows, "reject face must emit toolfirst_reject"
        payload = json.loads(rows[-1]["detail"])
        # mode is the FINE-GRAINED face: missing_marker (no marker) vs
        # self_attestation (dishonest marker) — both reject the dispatch
        assert payload["mode"] == "missing_marker"
        assert payload["tool"] == "crypto-tool"
        assert payload["keywords"]
        assert rows[-1]["actor"] == "hook:worker_budget"

    def test_gate_pass_face_stays_silent_before_approval(self, tmp, events, keywords):
        """#754 coexistence pin: check_tool_first itself must NOT emit a pass
        row — it runs before gates that may still reject the dispatch
        (test_heartbeat_bootstrap pins the zero-noise reject)."""
        ws = _ws(tmp)
        ok, _reason = wbg.check_tool_first(
            {'workspace': str(ws)}, "decode the crypto blob",
            "tool-catalog: crypto-tool")
        assert ok is True
        assert not [e for e in events if e["action"] == "toolfirst_pass"]

    def test_optout_pass_emits_mode_optout(self, tmp, events, keywords):
        ws = _ws(tmp)
        assert wbg.toolfirst_pass_record(
            {'workspace': str(ws)}, "C-001", "decode the crypto blob",
            "tool-catalog: none (reasoning: sample too small)") is True
        rows = [e for e in events if e["action"] == "toolfirst_pass"]
        assert rows and json.loads(rows[-1]["detail"])["mode"] == "optout"

    def test_no_match_pass_emits_mode_no_match(self, tmp, events, keywords):
        ws = _ws(tmp)
        assert wbg.toolfirst_pass_record(
            {'workspace': str(ws)}, "C-001", "totally unrelated prose",
            "") is True
        rows = [e for e in events if e["action"] == "toolfirst_pass"]
        assert rows and json.loads(rows[-1]["detail"])["mode"] == "no_match"

    def test_emit_failure_never_moves_gate_rc(self, tmp, keywords, monkeypatch):
        """Fail-open contract (#459): observability must not gate decisions."""
        import kunglao_log
        ws = {'workspace': str(_ws(tmp))}

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        ok_pass, _r1 = wbg.check_tool_first(ws, "decode the crypto blob",
                                            "tool-catalog: crypto-tool")
        ok_rej, _r2 = wbg.check_tool_first(ws, "decode the crypto blob", "")
        rec = wbg.toolfirst_pass_record(ws, "C-001", "decode the crypto blob",
                                        "tool-catalog: crypto-tool")
        assert ok_pass is True and ok_rej is False and rec is False, (
            "gate decisions identical with the emit crashed")

    def test_ws_none_stays_silent(self, events, keywords):
        """Gate callers without a workspace (existing #630 tests pass an empty
        paths dict) — no ws, no emit, same decisions."""
        ok, _reason = wbg.check_tool_first({}, "decode the crypto blob",
                                           "tool-catalog: crypto-tool")
        assert ok is True
        assert wbg.toolfirst_pass_record({}, "C-001", "decode the crypto blob",
                                         "tool-catalog: crypto-tool") is False
        assert not [e for e in events if e["action"].startswith("toolfirst")]


# ---------- operation label (claim attribute) --------------------------------

class TestOperationLabel:
    def test_label_round_trip_xor_vs_pe(self, tmp):
        """Acceptance pin: the label round-trips through claim-register and
        distinguishes operations — the XOR case is not the PE case."""
        ws = _ws(tmp)
        assert wbg.set_claim_operation(ws, "C-001", ["xor", "crypto"],
                                       "crypto-tool") is True
        assert wbg.set_claim_operation(ws, "C-002", ["pe", "disasm"],
                                       "disasm-tool") is True
        import yaml
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
        c1 = next(c for c in reg["claims"] if c["id"] == "C-001")
        c2 = next(c for c in reg["claims"] if c["id"] == "C-002")
        assert c1["operation"] == "xor,crypto"
        assert c1["operation_tool"] == "crypto-tool"
        assert c2["operation"] == "pe,disasm"
        assert c2["operation_tool"] == "disasm-tool"
        assert c1["operation"] != c2["operation"], (
            "operation labels must distinguish the two operations")

    def test_label_update_replaces_not_duplicates(self, tmp):
        ws = _ws(tmp)
        wbg.set_claim_operation(ws, "C-001", ["xor"], "crypto-tool")
        assert wbg.set_claim_operation(ws, "C-001", ["disasm"],
                                       "disasm-tool") is True
        text = (ws / "claim-register.yaml").read_text(encoding="utf-8")
        assert "operation: xor" not in text
        assert text.count("operation: disasm") == 1
        assert text.count("operation_tool:") == 1

    def test_label_failopen_on_missing_register(self, tmp):
        ws = tmp / "nowhere"
        ws.mkdir(parents=True)
        assert wbg.set_claim_operation(ws, "C-001", ["xor"],
                                       "crypto-tool") is False

    def test_label_writer_wired_to_attribution(self, tmp, keywords, events):
        """The approval-facing writer: a MATCHED dispatch persists the label;
        other modes leave the register byte-identical (a no_match pass still
        emits its pass row — that is the gate observation, not the label)."""
        ws = _ws(tmp)
        paths = {'workspace': str(ws)}
        assert wbg.toolfirst_pass_record(
            paths, "C-001", "decode the crypto blob",
            "tool-catalog: crypto-tool") is True
        text = (ws / "claim-register.yaml").read_text(encoding="utf-8")
        assert "operation: crypto" in text
        n_rows = len([e for e in events if e["action"] == "toolfirst_pass"])
        assert wbg.toolfirst_pass_record(
            paths, "C-001", "totally unrelated prose", "") is True
        after = (ws / "claim-register.yaml").read_text(encoding="utf-8")
        assert after == text  # non-matched mode writes no label
        assert len([e for e in events
                    if e["action"] == "toolfirst_pass"]) == n_rows + 1


# ---------- tool_call birth (RC1, claim granularity v1) ----------------------

class TestToolCallEmitter:
    def _fixture(self, tmp: Path):
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        dispatched_at = int(time.time()) - 90
        (ws / "analysis_state.txt").write_text(
            "[active_workers]\n"
            "worker_id=w-test | claim_id=C-001 | dispatched_at=%d | tier=1 | tools=grep\n" % dispatched_at +
            "[/active_workers]\n", encoding="utf-8")
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
        paths = {
            'workspace': str(ws),
            'state': ws / 'analysis_state.txt',
            'register': ws / 'claim-register.yaml',
            'deps': ws / 'claim_deps.yaml',
            'task_spec': ws / 'task_spec.yaml',
        }
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
                  '"tier": 1, "tools": ["grep"], "agent": "w-test", '
                  '"trace_id": "tr-m-0001"}}\n'
                  'facts-snapshot: 1 facts')
        payload = {'tool_input': {'name': 'w-test', 'description': '',
                                  'prompt': prompt},
                   'tool_result': 'used mcp__ghidra__decompile and grep; done'}
        return ws, paths, payload

    def test_worker_tools_emitted_as_tool_call_rows(self, tmp, events):
        import worker_budget_sinks
        ws, paths, payload = self._fixture(tmp)
        rc = worker_budget_sinks.post_check(payload, paths)
        assert rc == 0
        rows = [e for e in events if e["action"] == "tool_call"]
        tools = {r["tool"] for r in rows}
        assert "mcp__ghidra__decompile" in tools
        assert rows[0]["claim"] == "C-001"
        assert rows[0]["actor"] == "hook:worker_budget"
        assert rows[0]["trace_id"] == "tr-m-0001"

    def test_no_worker_entry_no_rows(self, tmp, events):
        import worker_budget_sinks
        ws, paths, payload = self._fixture(tmp)
        (ws / "analysis_state.txt").write_text(
            "[active_workers]\n[/active_workers]\n", encoding="utf-8")
        worker_budget_sinks.post_check(payload, paths)
        assert not [e for e in events if e["action"] == "tool_call"]

    def test_no_tools_observed_no_rows(self, tmp, events):
        import worker_budget_sinks
        ws, paths, payload = self._fixture(tmp)
        payload = dict(payload)
        payload['tool_result'] = 'no tool names in this transcript'
        worker_budget_sinks.post_check(payload, paths)
        assert not [e for e in events if e["action"] == "tool_call"]

    def test_tool_call_gate_admits_it(self):
        """RC1 acceptance: the word is registered AND has a real emitter —
        both directions of the double-ended gate hold for it."""
        import emit_gate
        import event_taxonomy as et
        assert "tool_call" in et.EMIT_ACTIONS
        assert emit_gate.emitter_files(REPO_ROOT, "tool_call")

    def test_toolfirst_words_have_emitters(self):
        import emit_gate
        import event_taxonomy as et
        for word in ("toolfirst_pass", "toolfirst_reject", "claim_settled"):
            assert word in et.EMIT_ACTIONS, word
            assert emit_gate.emitter_files(REPO_ROOT, word), word


# ---------- claim_settled settlement row -------------------------------------

class TestSettlementRow:
    """#880: settlement rows land at claim status transitions (issue
    acceptance: "转换模拟 → 账本断言行存在且字段齐")."""

    def _reg(self, status: str) -> str:
        import yaml
        return yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": status}]}, sort_keys=False)

    def _seed_dispatch_row(self, ws: Path) -> None:
        import kunglao_log
        kunglao_log.emit(ws, "hook:worker_budget", "dispatch", claim="C-1",
                         detail="tier=2 tools=ghidra,grep agent=w1")

    def _ledger_rows(self, ws: Path) -> list:
        import json
        logs = ws / "runs" / "logs"
        rows = []
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def test_settlement_row_lands_with_all_fields(self, tmp):
        from register_proven_gate import emit_settlements
        ws = tmp / "ws"
        ws.mkdir()
        old_text = self._reg("OPEN")
        (ws / "claim-register.yaml").write_text(old_text, encoding="utf-8")
        self._seed_dispatch_row(ws)
        new_text = self._reg("REFUTED")
        n = emit_settlements(ws, new_text, old_text)
        assert n == 1
        rows = [r for r in self._ledger_rows(ws)
                if r["action"] == "claim_settled"]
        assert len(rows) == 1
        row = rows[0]
        assert row["claim"] == "C-1"
        assert row["actor"] == "hook:write_guard"
        assert row["trace_id"], "settlement must carry the mission trace_id"
        assert isinstance(row["duration_ms"], int) and row["duration_ms"] >= 0
        payload = json.loads(row["detail"])
        assert payload["from"] == "OPEN" and payload["to"] == "REFUTED"
        assert payload["tools"] == ["ghidra", "grep"]
        assert payload["outcome"] == "REFUTED"

    def test_non_terminal_transition_settles_nothing(self, tmp):
        from register_proven_gate import emit_settlements
        ws = tmp / "ws"
        ws.mkdir()
        n = emit_settlements(ws, self._reg("IN_PROGRESS"), self._reg("OPEN"))
        assert n == 0

    def test_same_terminal_state_is_not_a_transition(self, tmp):
        from register_proven_gate import emit_settlements
        ws = tmp / "ws"
        ws.mkdir()
        n = emit_settlements(ws, self._reg("PROVEN"), self._reg("PROVEN"))
        assert n == 0


# ---------- lessons wiring: citation + burn counters move --------------------

def _write_lesson(lib: Path, slug: str = "xor-decode-trap") -> Path:
    lib.mkdir(parents=True, exist_ok=True)
    p = lib / f"lesson-{slug}.md"
    p.write_text(
        "---\n"
        f"slug: {slug}\n"
        "outcome: NEGATIVE\n"
        "stage: draft\n"
        "---\n\n"
        "The xor decode trap: crypto blob decode via spawn times out. "
        "Use listen mode instead of spawn.\n",
        encoding="utf-8")
    return p


def _frontmatter(p: Path) -> dict:
    import yaml
    parts = p.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(parts[1]) or {}


class TestLessonWiring:
    def test_citation_counter_bumps_on_lesson_hit_record(self, tmp):
        """record_citation 挂点 = record_analysis 的 lesson-hit 面（预裁决）。
        A record declaring next_method_source=lesson-hit bumps the cited
        lesson's citation_count (the counter MOVES — issue acceptance)."""
        import failure_analysis_gate as fag
        import yaml
        lib = tmp / "lessons"
        lesson = _write_lesson(lib)
        ws = tmp / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": "OPEN",
                         "promotion_attempts": 1}]}, sort_keys=False),
            encoding="utf-8")
        r = fag.record_analysis(
            ws, "C-1",
            assumption="spawn decode of the xor crypto blob",
            validity="not-justified",
            next_method="listen mode instead of spawn",
            source="lesson-hit", library=lib)
        assert r["recorded"], r
        assert _frontmatter(lesson).get("citation_count") == 1

    def test_burn_counter_bumps_on_negative_settlement(self, tmp, monkeypatch):
        """record_burn 挂点 = 结算负样本点（预裁决）：REFUTED settlement of a
        claim whose method lineage is lesson-hit bumps burn_count."""
        import yaml
        import lessons_telemetry as lt
        import register_proven_gate as rpg
        lib = tmp / "lessons"
        lesson = _write_lesson(lib)
        monkeypatch.setattr(lt, "_resolve_library", lambda library=None: lib)
        ws = tmp / "ws"
        ws.mkdir()
        (ws / "analyses").mkdir()
        (ws / "analyses" / "failure-C-1.yaml").write_text(yaml.safe_dump({
            "claim": "C-1", "next_method_source": "lesson-hit",
            "candidates": [{"file": "lesson-xor-decode-trap.md",
                            "score": 3}]}, sort_keys=False),
            encoding="utf-8")
        old_text = yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": "OPEN"}]}, sort_keys=False)
        new_text = yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": "REFUTED"}]}, sort_keys=False)
        n = rpg.emit_settlements(ws, new_text, old_text)
        assert n == 1
        assert _frontmatter(lesson).get("burn_count") == 1

    def test_positive_settlement_does_not_burn(self, tmp, monkeypatch):
        import yaml
        import lessons_telemetry as lt
        import register_proven_gate as rpg
        lib = tmp / "lessons"
        lesson = _write_lesson(lib)
        monkeypatch.setattr(lt, "_resolve_library", lambda library=None: lib)
        ws = tmp / "ws"
        ws.mkdir()
        (ws / "analyses").mkdir()
        (ws / "analyses" / "failure-C-1.yaml").write_text(yaml.safe_dump({
            "claim": "C-1", "next_method_source": "lesson-hit",
            "candidates": [{"file": "lesson-xor-decode-trap.md",
                            "score": 3}]}, sort_keys=False),
            encoding="utf-8")
        old_text = yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": "OPEN"}]}, sort_keys=False)
        new_text = yaml.safe_dump(
            {"claims": [{"id": "C-1", "status": "PROVEN"}]}, sort_keys=False)
        rpg.emit_settlements(ws, new_text, old_text)
        assert "burn_count" not in _frontmatter(lesson)

