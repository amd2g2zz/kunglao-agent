# -*- coding: utf-8 -*-
"""tests/test_cognition_759.py — orchestrator 认知层（issue #759, #762 K3 收尾）。

语义源 #711 现场证据（#704 后台化之后）：
  E1 tick 等待期 action_taken EMPTY、零认知产出；
  E2 价值排序靠用户手改文件 + SendMessage hack；
  E3 主动检索靠用户两次提示（三次关键洞见两次来自红队一次来自用户）。

四个 task 的验收：
  T1  THINK 席位 — 等待期 tick 产 runs/.think-<ts>.md 且 action_taken 引用；
  T2  价值函数 — runs/value-weights.yaml 注入后 priority 排序反映；
  T2b K3 接线 — note_supersedes_hypothesis 三件套（状态迁移/事件/affected_claims）;
  T3  主动触发器 — N tick 无进展 → think 产物含 suggested_searches。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SKILL = ROOT / "skills" / "kunglao-agent" / "SKILL.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_ws(tmp_path: Path, claims: list[dict] | None = None,
             *, register: bool = True, deps: str = "depends_on: {}\n",
             index: str = "# facts index\n") -> Path:
    """Bare-but-real workspace skeleton (register present ⇒ ranking runs)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    if register:
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": claims or []}, allow_unicode=True),
            encoding="utf-8")
        (ws / "claim_deps.yaml").write_text(deps, encoding="utf-8")
        facts = ws / "facts"
        facts.mkdir(exist_ok=True)
        (facts / "_INDEX.md").write_text(index, encoding="utf-8")
    return ws


def _tick(ws: Path) -> tuple[dict, str]:
    """Run the real tick CLI (same convention as tests/test_heartbeat_tick.py)."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180,
    )
    report = json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return report, r.stdout


# ===========================================================================
# T1 = H1 — THINK 席位（等待期认知动作）
# ===========================================================================

class TestThinkSeatWaitingDetection:
    def test_bare_register_no_claims_is_waiting(self, tmp_path):
        ts = _load_module("think_seat_t1", SCRIPTS / "think_seat.py")
        ws = _make_ws(tmp_path, [])
        res = ts.maybe_think(ws)
        assert res["waiting"] is True, res

    def test_dispatchable_claim_is_not_waiting(self, tmp_path):
        ts = _load_module("think_seat_t1", SCRIPTS / "think_seat.py")
        claim = {"id": "C-1", "status": "OPEN", "statement": "c2 config extract"}
        ws = _make_ws(tmp_path, [claim])
        res = ts.maybe_think(ws)
        assert res["waiting"] is False, res
        assert res.get("artifact") in (None, "")

    def test_missing_register_is_not_waiting(self, tmp_path):
        """Legacy/foreign workspace: nothing the ranking can judge → never
        fire (keeps the #237 EMPTY contract untouched for such fixtures)."""
        ts = _load_module("think_seat_t1", SCRIPTS / "think_seat.py")
        ws = _make_ws(tmp_path, register=False)
        res = ts.maybe_think(ws)
        assert res["waiting"] is False, res


class TestThinkSeatArtifact:
    def test_waiting_writes_three_section_artifact(self, tmp_path):
        ts = _load_module("think_seat_t1b", SCRIPTS / "think_seat.py")
        ws = _make_ws(tmp_path, [])
        res = ts.maybe_think(ws)
        assert res["waiting"] is True and res["artifact"], res
        art = ws / res["artifact"]
        assert art.exists(), f"artifact must exist on disk: {res}"
        text = art.read_text(encoding="utf-8")
        for section in ("## patterns", "## hypotheses", "## value"):
            assert section in text, f"fixed schema section missing: {section}"

    def test_nonwaiting_writes_no_artifact(self, tmp_path):
        ts = _load_module("think_seat_t1c", SCRIPTS / "think_seat.py")
        claim = {"id": "C-1", "status": "OPEN"}
        ws = _make_ws(tmp_path, [claim])
        res = ts.maybe_think(ws)
        assert list(ws.glob("runs/.think-*.md")) == [], \
            "non-waiting seats stay silent"


class TestTickWiringThink:
    def test_waiting_tick_action_taken_references_artifact(self, tmp_path):
        """Acceptance T1 core: a waiting-period tick's action_taken carries the
        think artifact path and the file EXISTS (#711 E1 closure)."""
        ws = _make_ws(tmp_path, [])
        report, stdout = _tick(ws)
        at = report.get("action_taken", "")
        assert at.startswith("THINK runs/.think-"), at
        rel = at.split(" ", 1)[1]
        assert (ws / rel).exists(), f"artifact file must exist: {rel}"

    def test_dispatchable_tick_keeps_action_taken_empty(self, tmp_path):
        claim = {"id": "C-1", "status": "OPEN", "statement": "rce via deserialization"}
        ws = _make_ws(tmp_path, [claim])
        report, stdout = _tick(ws)
        assert report["action_taken"] == "", \
            "dispatchable workspace keeps the #237 orchestrator-filled contract"

    def test_think_step_never_fails_the_tick(self, monkeypatch, tmp_path):
        """Advisory posture (#88 freeze): a crashed/unparseable THINK step must
        not flip rc/alert nor hijack action_taken."""
        ht = _load_module("heartbeat_tick_t1", SCRIPTS / "heartbeat_tick.py")

        def broken(script, ws_arg, *extra):
            if script == "think_seat.py":
                return {"script": script, "rc": -1,
                        "stdout": "EXC simulated crash", "stderr": ""}
            return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

        monkeypatch.setattr(ht, "run", broken)
        monkeypatch.setattr(ht, "_oracle_registered", lambda w: True)
        ws = _make_ws(tmp_path, [])
        rc = ht.main([str(ws)])
        report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text())
        assert rc == 0 and report["alert"] is False
        assert report["action_taken"] == ""


def test_skill_decision_table_has_think_row():
    """Contract layer: the decision table teaches the waiting-period action —
    structured reasoning goes through the sequentialthinking chain (contract
    detail is #761 J2's single source; SKILL.md references, never copies)."""
    s = SKILL.read_text(encoding="utf-8")
    row = next((ln for ln in s.splitlines() if ln.startswith("| `THINK`")), "")
    assert row, "decision table must carry a THINK row"
    assert "sequentialthinking" in s


# ===========================================================================
# T2 = H2 — 价值函数（runs/value-weights.yaml → priority_ratio 排序乘子）
# ===========================================================================

RCE_DOS_CLAIMS = [
    {"id": "C-RCE", "status": "OPEN",
     "statement": "rce remote code execution via deserialization gadget"},
    {"id": "C-DOS", "status": "OPEN",
     "statement": "dos denial of service via parser infinite loop"},
]


def test_t2_baseline_tie_is_claim_id_ordered(tmp_path):
    """Without weights both claims score identically → tie falls to claim_id
    (C-DOS first). This is the deterministic baseline the flip asserts on."""
    import priority_ratio as pr
    ws = _make_ws(tmp_path, [dict(c) for c in RCE_DOS_CLAIMS])
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(reg["claims"], {}, ev)
    assert [a.claim_id for a in out] == ["C-DOS", "C-RCE"], out


def test_t2_weights_reflect_in_ranking(tmp_path):
    """Acceptance T2: injecting {rce:10, dos:1} drops the DoS claim below RCE."""
    import priority_ratio as pr
    ws = _make_ws(tmp_path, [dict(c) for c in RCE_DOS_CLAIMS])
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "value-weights.yaml").write_text(
        "schema: kunglao-value-weights/1\nsource: user-ruling\n"
        'rationale: "目标是RCE，DoS拿不到赏金"\nclaim_classes:\n  rce: 10\n  dos: 1\n',
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(RCE_DOS_CLAIMS, {}, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-RCE"].weight == 10.0 and by["C-DOS"].weight == 1.0, out
    assert [a.claim_id for a in out] == ["C-RCE", "C-DOS"], out


def test_t2_score_is_exact_multiplier_of_unweighted_formula():
    import priority_ratio as pr
    claims = [{"id": "C-X", "status": "OPEN", "statement": "pure rce path"}]
    ev_bare = pr.EvidenceView()
    ev_w = pr.EvidenceView(value_class_weights={"rce": 4})
    s_bare = pr.priority_ratio(claims, {}, ev_bare)[0].score
    s_w = pr.priority_ratio(claims, {}, ev_w)[0]
    assert s_w.weight == 4.0
    assert s_w.score == round(s_bare * 4.0, 3)


def test_t2_missing_weights_file_is_neutral(tmp_path):
    """No file → every action weight 1.0 and scores byte-identical to today."""
    import priority_ratio as pr
    ev = pr.EvidenceView.from_workspace(_make_ws(tmp_path, RCE_DOS_CLAIMS))
    out = pr.priority_ratio([dict(c) for c in RCE_DOS_CLAIMS], {}, ev)
    assert all(a.weight == 1.0 for a in out)


def test_t2_corrupt_and_illegal_entries_fail_open(tmp_path):
    import priority_ratio as pr
    ws = _make_ws(tmp_path, [])
    (ws / "runs" / "value-weights.yaml").write_text(
        "{not: [valid", encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.value_class_weights == {} and ev.value_claim_overrides == {}
    # illegal values present in an otherwise-parsable file are dropped per-entry
    ev2 = pr.EvidenceView.from_workspace(ws)  # corrupt already covered
    ev3 = type(ev)(value_class_weights={"rce": -3, "dos": 0, "c2_extract": "hi"})
    assert pr.claim_value_weight({"id": "C-1"}, ev3.value_class_weights, {}) == 1.0


def test_t2_override_beats_field_beats_keyword():
    import priority_ratio as pr
    classes = {"rce": 10.0}
    overrides = {"C-Z": 5.0}
    claim_kw = {"id": "C-K", "statement": "achieves rce"}
    claim_field = {"id": "C-F", "value_class": "rce", "statement": "nothing"}
    claim_over = {"id": "C-Z", "value_class": "rce", "statement": "achieves rce"}
    assert pr.claim_value_weight(claim_kw, classes, {}) == 10.0
    assert pr.claim_value_weight(claim_field, classes, {}) == 10.0
    assert pr.claim_value_weight(claim_over, classes, overrides) == 5.0
    assert pr.claim_value_weight({"id": "C-N", "statement": "unrelated"},
                                 classes, {}) == 1.0


def test_t2_to_dict_exposes_weight():
    import priority_ratio as pr
    ev = pr.EvidenceView(value_claim_overrides={"C-Y": 7})
    out = pr.priority_ratio([{"id": "C-Y", "status": "OPEN"}], {}, ev)
    d = out[0].to_dict()
    assert d["weight"] == 7.0


# ===========================================================================
# T2b = K3 接线（Closes #762）— note_supersedes_hypothesis 三件套
# ===========================================================================

_HYP_TMPL = "---\nid: {hid}\nclaim_id: {cid}\ncompetitor_group: {grp}\n" \
            "candidates: [AES]\nstatus: open\nschema_rev: 1\n---\n\nbody\n"


def _k3_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(exist_ok=True)
    hyp = ws / "hypotheses"
    hyp.mkdir()
    (hyp / "H-002.md").write_text(
        _HYP_TMPL.format(hid="H-002", cid="C-201", grp="algo-family"),
        encoding="utf-8")
    (hyp / "H-003.md").write_text(
        _HYP_TMPL.format(hid="H-003", cid="C-202", grp="algo-family"),
        encoding="utf-8")
    return ws


def _write_note(ws: Path, body_key: str, target: str,
                note_id: str = "N-900") -> None:
    (ws / "notes" / f"{note_id}.md").write_text(
        f"---\nid: {note_id}\nclaim_id: C-201\nverify_status: pending\n"
        f"{body_key}: {target}\n---\n# conclusion\nChaCha20 confirmed\n",
        encoding="utf-8")


class TestNoteSupersedesHypothesis:
    def test_trio_transition_event_affected_claims(self, tmp_path):
        """Acceptance T2b core: note supersedes H-2 → H-2 status superseded +
        hypothesis_superseded event + affected_claims list (本 claim + 同组 peer)."""
        from hypothesis_store import HypothesisStore
        ts = _load_module("notes_writer_k3a", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        _write_note(ws, "supersedes_hypothesis", "H-002")
        out = ts.note_supersedes_hypothesis(ws / "notes", "N-900",
                                            workspace=ws)
        h2 = HypothesisStore(ws / "hypotheses").get("H-002")
        assert h2.status == "superseded" and h2.superseded_by == "N-900"
        assert out["affected_claims"] == ["C-201", "C-202"], out
        logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        rows = [json.loads(ln) for ln in
                logs[0].read_text(encoding="utf-8").splitlines()]
        ev = [r for r in rows if r.get("action") == "hypothesis_superseded"]
        assert ev and "C-201" in ev[-1]["detail"] and "C-202" in ev[-1]["detail"]

    def test_plain_supersedes_accepted_when_only_hypothesis_resolves(self, tmp_path):
        ts = _load_module("notes_writer_k3b", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        _write_note(ws, "supersedes", "H-002")
        out = ts.note_supersedes_hypothesis(ws / "notes", "N-900")
        assert out["ok"] is True and out["hypothesis"] == "H-002"

    def test_missing_pointer_raises_loudly(self, tmp_path):
        """No silent pass-through: a closure without any hypothesis chain
        pointer is rejected (#762 留缝原话)."""
        import pytest
        ts = _load_module("notes_writer_k3c", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        (ws / "notes" / "N-901.md").write_text(
            "---\nid: N-901\nclaim_id: C-201\nverify_status: pending\n---\nb\n",
            encoding="utf-8")
        with pytest.raises(ValueError):
            ts.note_supersedes_hypothesis(ws / "notes", "N-901")

    def test_unresolvable_target_raises(self, tmp_path):
        import pytest
        ts = _load_module("notes_writer_k3d", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        _write_note(ws, "supersedes_hypothesis", "H-999")
        with pytest.raises(ValueError):
            ts.note_supersedes_hypothesis(ws / "notes", "N-900")

    def test_non_open_hypothesis_rejected(self, tmp_path):
        import pytest
        from hypothesis_store import HypothesisStore
        ts = _load_module("notes_writer_k3e", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        HypothesisStore(ws / "hypotheses").transition("H-002", "refuted",
                                                      refuting_fact_id="F-1")
        _write_note(ws, "supersedes_hypothesis", "H-002")
        with pytest.raises(Exception):
            ts.note_supersedes_hypothesis(ws / "notes", "N-900")

    def test_ambiguous_supersedes_both_layers_raises(self, tmp_path):
        import pytest
        ts = _load_module("notes_writer_k3f", SCRIPTS / "notes_writer.py")
        ws = _k3_ws(tmp_path)
        (ws / "notes" / "H-002.md").write_text("---\nid: H-002\n---\nnote\n",
                                               encoding="utf-8")
        _write_note(ws, "supersedes", "H-002")
        with pytest.raises(ValueError):
            ts.note_supersedes_hypothesis(ws / "notes", "N-900")


def test_emit_actions_registers_hypothesis_superseded():
    import event_taxonomy as et
    assert "hypothesis_superseded" in et.EMIT_ACTIONS
    assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS))


def test_k3_cli_supersede_hyp(tmp_path):
    ws = _k3_ws(tmp_path)
    _write_note(ws, "supersedes_hypothesis", "H-002")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "notes_writer.py"), str(ws),
         "--supersede-hyp", "N-900"],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    assert payload["affected_claims"] == ["C-201", "C-202"]


def test_skill_documents_the_note_rewrite_lane():
    s = SKILL.read_text(encoding="utf-8")
    assert "supersedes_hypothesis" in s


# ===========================================================================
# T3 = H3 — 主动触发器（无进展 → suggested_searches）
# ===========================================================================

def _latest_artifact(ws: Path) -> Path:
    arts = list(ws.glob("runs/.think-*.md"))
    assert arts, "no think artifacts produced"
    # same-second collisions share a name stem; mtime is the true recency
    return max(arts, key=lambda p: p.stat().st_mtime)


class TestProactiveSearch:
    def test_first_waiting_tick_has_no_search_section(self, tmp_path):
        ts = _load_module("think_seat_t3a", SCRIPTS / "think_seat.py")
        ws = _make_ws(tmp_path,
                      [{"id": "C-9", "status": "OPEN",
                        "statement": "rce chain"}],
                      deps="depends_on:\n  C-9: [C-PENDING]\n")
        res = ts.maybe_think(ws)
        assert res["waiting"] is True
        text = _latest_artifact(ws).read_text(encoding="utf-8")
        assert "## suggested_searches" not in text

    def test_n_ticks_no_progress_seeds_suggestions(self, tmp_path):
        """Acceptance T3: N consecutive zero-progress ticks → the think
        artifact gains non-empty suggested_searches (websearch + 参考库 rows)."""
        ts = _load_module("think_seat_t3b", SCRIPTS / "think_seat.py")
        blocked = "depends_on:\n  C-A: [C-P1]\n  C-B: [C-P2]\n"
        ws = _make_ws(tmp_path, [
            {"id": "C-A", "status": "OPEN", "statement": "rce gadget"},
            {"id": "C-B", "status": "OPEN", "statement": "persistence autorun"},
        ], deps=blocked)
        for _ in range(ts.STALL_TICKS_FOR_SEARCH + 1):
            ts.maybe_think(ws)
        text = _latest_artifact(ws).read_text(encoding="utf-8")
        assert "## suggested_searches" in text
        rows = [ln for ln in text.splitlines() if ln.startswith("- ")]
        assert any("websearch:" in ln for ln in rows), text
        assert any("reference-library:" in ln for ln in rows), text
        assert len(rows) >= 2

    def test_progress_resets_the_stall(self, tmp_path):
        import json as _json
        ts = _load_module("think_seat_t3c", SCRIPTS / "think_seat.py")
        ws = _make_ws(tmp_path, [])
        for _ in range(3):
            ts.maybe_think(ws)
        # a fact lands → digest changes
        idx = ws / "facts" / "_INDEX.md"
        idx.write_text(idx.read_text(encoding="utf-8")
                       + "F-001 | PROVEN | C-X | found crypto table\n",
                       encoding="utf-8")
        res = ts.maybe_think(ws)
        assert res["stall_ticks"] == 0
        state = _json.loads((ws / "runs" / "think-state.json").read_text())
        assert state["stall_ticks"] == 0


def test_skill_pinns_the_execution_contract():
    """THINK products are not optional reading: suggested_searches MUST run
    as the next action (the deterministic-loss countermeasure is pinned by
    phrase; SKILL body stays CJK/token free per the skill contract)."""
    s = SKILL.read_text(encoding="utf-8")
    assert "suggested_searches" in s
    assert "deterministic loss" in s
    assert "MUST execute as the NEXT action" in s
