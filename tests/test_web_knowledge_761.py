# -*- coding: utf-8 -*-
"""tests/test_web_knowledge_761.py — issue #761 web 知识与认知层 (J 组 7 项).

Issue #761 + two comment rulings (2026-08-27): J6 无头优先 / J7 调试插桩一等能力.

Acceptance map:
  J1  web-risk-control.md + web-crawler-engineering.md exist, indexed in
      references/_INDEX.md (+ per-domain indexes + repinned _INDEX.yaml),
      recalled by dictionary hits (a web risk-control claim dispatch actually
      injects them through recall_inject), and carry the J6 escalation chain
      (headless first -> fingerprint emulation -> headful last resort) and the
      J7 debug/instrumentation execution column (CDP breakpoints, injection,
      cookie/storage DOM listeners).
  J2  sequentialthinking contract in kunglao-worker (complex-reasoning
      authoritative source cited by #759 THINK seat) + kunglao-redteam attack
      path enumeration; derivation persistence of thinking traces.
  J3  planning state machine (plan frontmatter status/revision) +
      scripts/plan_reviser.py three mechanical triggers (--check suggests,
      rc=3) + append-only `## revision-N` incremental revisions.
  J4  recall feedback loop: DONE-line `recall_useful:` verdict (+ optional
      term scope) parsed at the lib_kunglao single parse point, accumulated
      into runs/.recall-stats.json per dictionary term, demotion SUGGESTIONS
      after 3 consecutive misleading (never auto-editing), red-team dispatch
      injection timing, and the --joint query construction for #759 THINK.
  J5  LEARN ladder becomes internal-first two-tier (re-library recall ->
      WebSearch external) with evidence discipline (URL + retrieval date in
      derivation; WebSearch results cannot directly back PROVEN until the
      verifier blind-checks).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
# the canonical worker-status parse point lives in hooks/ (#444 AC-1); insert
# BEFORE scripts so `import lib_kunglao` binds the hooks copy, not the
# same-named scripts-side drift library
sys.path.insert(0, str(SCRIPTS))

import references_recall as rr  # noqa: E402


def _real_index():
    return rr.build_index(rr.default_index_path())


# ===========================================================================
# J1 — knowledge base documents, indexing, dictionary recall
# ===========================================================================

RISK_DOC = ROOT / "references" / "re-library" / "web-risk-control.md"
CRAWLER_DOC = ROOT / "references" / "re-library" / "web-crawler-engineering.md"


class TestJ1Documents:
    def test_both_docs_exist_with_body(self) -> None:
        for p, min_lines in ((RISK_DOC, 120), (CRAWLER_DOC, 90)):
            assert p.is_file(), f"missing knowledge doc: {p}"
            n = len(p.read_text(encoding="utf-8").splitlines())
            assert n >= min_lines, f"{p.name} too thin ({n} lines)"

    def test_risk_control_section_skeleton(self) -> None:
        text = RISK_DOC.read_text(encoding="utf-8")
        for anchor in (
            "风控信号分类学",       # signal taxonomy
            "设备指纹",
            "canvas",
            "audio",
            "行为特征",
            "输入节奏",
            "环境一致性",
            "时区",
            "协议层挑战",
            "nonce",
            "device_id",
            "对抗决策树",           # adversarial decision tree
            "风控栈识别",           # stack identification
            "瑞数",
            "加速乐",
            "检测点定位",           # detection-point localization loop
        ):
            assert anchor in text, f"web-risk-control.md missing anchor: {anchor}"

    def test_risk_control_signal_locate_respond_columns(self) -> None:
        """Doctrine format: every doctrine section carries the practical
        three-column shape (signal -> locate command -> response)."""
        text = RISK_DOC.read_text(encoding="utf-8")
        assert "信号" in text and ("定位" in text or "观察点" in text)
        assert "应对" in text
        assert text.count("| ") >= 30, "doctrine must be table-heavy, not essay"

    def test_j6_headless_first_escalation_chain(self) -> None:
        """User ruling 2026-08-27: 浏览器 mcp 尽量用无头，除非风控太厉害了可以启用
        headfull — the decision tree carries the upgrade chain: headless is the
        DEFAULT; detected anti-headless fingerprint signals escalate FIRST to
        fingerprint emulation (Path B), and ONLY THEN to headful."""
        text = RISK_DOC.read_text(encoding="utf-8")
        assert "默认 headless" in text
        # signals that decide the upgrade are listed as decidable checklist items
        assert "navigator.webdriver" in text.lower()
        # escalation ORDER inside the upgrade-chain section:
        # fingerprint emulation must precede headful-as-last-resort
        anchor = text.index("无头优先与升级链")
        chain = text[anchor:].lower()
        i_emul, i_headful_resort = chain.find("指纹仿真"), chain.find("最后手段")
        assert -1 not in (i_emul, i_headful_resort)
        assert i_emul < i_headful_resort, "emulation must precede the headful resort"
        assert "headful 最后手段" in chain

    def test_j7_instrumentation_is_first_class(self) -> None:
        """User ruling 2026-08-27: camoufox-mcp 是可以调试和插桩的 — the
        localization loop binds observation steps to camoufox debug channel
        operations, and CDP behavior holds identically under headless."""
        text = RISK_DOC.read_text(encoding="utf-8")
        low = text.lower()
        assert "cdp" in low
        assert "evaluateonnewdocument" in low
        for step in ("触发", "观察", "归因"):
            assert step in text, f"trigger->observe->attribute loop missing: {step}"
        assert "diff" in low, "parameter diff between pass/fail pairs required"


class TestJ1CrawlerDoc:
    def test_crawler_section_skeleton(self) -> None:
        text = CRAWLER_DOC.read_text(encoding="utf-8")
        for anchor in (
            "会话维持",
            "cookie",
            "登录态",
            "频率伪装",
            "IP 策略",
            "住宅",
            "机房",
            "验证码",
            "滑块",
            "点选",
            "re-challenge",
        ):
            assert anchor in text, f"web-crawler-engineering.md missing: {anchor}"


class TestJ1IndexedAndRecalled:
    def test_domain_table_and_catalog_rows(self) -> None:
        idx = _real_index()
        paths = {e.path for e in idx.entries}
        assert "re-library/web-risk-control.md" in paths
        assert "re-library/web-crawler-engineering.md" in paths
        doms = {d.name for d in idx.domains.values()}
        assert {"web-risk-control", "web-crawler-engineering"} <= doms

    def test_per_domain_index_files_exist(self) -> None:
        for f in ("_index-web-risk-control.md", "_index-web-crawler-engineering.md"):
            p = ROOT / "references" / f
            assert p.is_file(), f"missing per-domain index: {f}"

    def test_recall_hits_risk_control_by_dictionary(self) -> None:
        """A web risk-control query recalls the NEW doc as the top hit."""
        idx = _real_index()
        entries, scenes = list(idx.entries), list(idx.scenes)
        res = rr.recall(entries, scenes, "risk control")
        assert res.files, "risk control must recall something"
        assert res.files[0] == "re-library/web-risk-control.md", res.files[:5]

    def test_recall_hits_crawler_by_cjk_dictionary(self) -> None:
        idx = _real_index()
        entries, scenes = list(idx.entries), list(idx.scenes)
        res = rr.recall(entries, scenes, "爬虫")
        assert "re-library/web-crawler-engineering.md" in res.files[:3], res.files[:5]

    def test_scenario_map_routes_antibot(self) -> None:
        idx = _real_index()
        labels = " ".join(s.label for s in idx.scenes)
        assert "风控" in labels or "anti-bot" in labels.lower()

    def test_yaml_pins_cover_new_docs(self) -> None:
        yaml_text = (ROOT / "references" / "_INDEX.yaml").read_text(encoding="utf-8")
        assert "references/re-library/web-risk-control.md:" in yaml_text
        assert "references/re-library/web-crawler-engineering.md:" in yaml_text


WEB_CLAIM = (
    "[T2 tools=camoufox] claim C-901 recover the sign parameter for the "
    "--type web target; the request is blocked by 反爬 challenge, 风控 "
    "returns a slider captcha page"
)


class TestJ1RecallInjectDictionary:
    def test_web_signals_extend_queries(self) -> None:
        from recall_inject import queries_for_features

        q = queries_for_features(WEB_CLAIM, tier=2)
        assert q[0] == "risk control", q
        assert "crawler" in q
        # existing defaults survive the extension (append-only semantics)
        assert q[-1] == "static analysis"

    def test_non_web_claim_gets_no_web_query(self) -> None:
        from recall_inject import queries_for_features

        plain = "[T2 tools=ghidra] claim C-102 disassemble and decode the sample"
        assert "risk control" not in queries_for_features(plain, tier=2)

    def test_web_risk_claim_injects_new_doc(self, tmp_path) -> None:
        """Fixture walks the real references_recall subprocess (the actual
        injection path): a web 风控 claim must surface web-risk-control.md."""
        from recall_inject import evaluate

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(
            "claims:\n- id: C-901\n  status: OPEN\n", encoding="utf-8")
        payload = {
            "hookEventName": "PreToolUse",
            "tool_name": "Agent",
            "cwd": str(ws),
            "tool_input": {"prompt": WEB_CLAIM},
        }
        rc, stderr, ctx = evaluate(payload)
        assert rc == 0 and stderr == ""
        assert ctx, "web risk-control claim must receive recall guidance"
        assert "web-risk-control.md" in ctx


# ===========================================================================
# J2 — sequentialthinking integration contract (authoritative source)
# ===========================================================================

WORKER_MD = ROOT / "agents" / "kunglao-worker.md"
REDTEAM_MD = ROOT / "agents" / "kunglao-redteam.md"


class TestJ2SequentialThinkingContract:
    def test_worker_contract_marker_and_authority(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "<!-- contract: sequential-thinking -->" in text
        assert "#761 J2" in text
        # single-source duty cited by the #759 THINK seat
        assert "唯一权威源" in text and "#759" in text

    def test_worker_names_real_tool_and_triggers(self) -> None:
        """Ruling 2026-08-27: seqthink 正名 — contract uses the real MCP tool
        name, never a nickname; all four trigger classes are enumerated."""
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "mcp__sequential-thinking__sequentialthinking" in text
        for trigger in ("签名算法推导", "加密参数溯源", "风控对抗决策树遍历", "多步假设链"):
            assert trigger in text, f"worker seqthink contract missing trigger: {trigger}"
        assert "必须走结构化思考链" in text

    def test_worker_trace_digest_into_derivation(self) -> None:
        """Thought-trajectory summaries must land in fact derivation (auditable);
        full thought dump is NOT required nor wanted."""
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "derivation" in text
        assert "摘要" in text, "trace DIGEST (not full dump) into derivation required"

    def test_redteam_attack_path_enumeration_contract(self) -> None:
        text = REDTEAM_MD.read_text(encoding="utf-8")
        assert "<!-- contract: sequential-thinking -->" in text
        assert "mcp__sequential-thinking__sequentialthinking" in text
        for anchor in ("枚举攻击面", "逐路径假设", "反证"):
            assert anchor in text, f"redteam enumeration contract missing: {anchor}"

    def test_tool_is_declared_in_allowed_tools(self) -> None:
        """The contract teaches usage of an already-allowed tool — keep the two
        facts consistent if either drifts."""
        for agent_md in (WORKER_MD, REDTEAM_MD):
            fm = agent_md.read_text(encoding="utf-8").split("---")[1]
            assert "mcp__sequential-thinking__sequentialthinking" in fm, agent_md


# ===========================================================================
# J3 — planning state machine + incremental replanning (plan_reviser)
# ===========================================================================

import plan_reviser as pr  # noqa: E402


def _plan_ws(tmp_path: Path, plan_body: str | None = None,
             name: str = "ws") -> tuple[Path, Path]:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    plan = ws / "runs" / "plan-C001.md"
    plan.write_text(plan_body or (
        "---\nstatus: in-flight\nrevision: 0\n---\n"
        "goal: recover the license check\n"
        "assumptions:\n"
        "- response body uses AES-256 encryption\n"
        "steps:\n"
        "1. hook JSON.parse boundary\n"), encoding="utf-8")
    return ws, plan


class TestJ3PlanStateMachine:
    def test_parse_header_with_defaults(self) -> None:
        assert pr.parse_plan_header("goal: x") == {
            "status": "pending", "revision": 0}
        assert pr.parse_plan_header("status: blocked\nrevision: 3") == {
            "status": "blocked", "revision": 3}

    def test_worker_contract_declares_state_machine(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        for anchor in ("status:", "pending", "in-flight", "blocked",
                       "superseded", "revision:", "## revision-N"):
            assert anchor in text
        assert "#761 J3" in text

    def test_skill_carries_suggest_revision_contract(self) -> None:
        """SKILL contract: suggest_revision (rc=3) REQUIRES a revision segment;
        'no change' is also recorded — silence is not an outcome."""
        skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
            encoding="utf-8")
        assert "plan_reviser.py --check" in skill
        assert "suggest_revision" in skill
        assert "--apply" in skill


class TestJ3Triggers:
    def test_blocker_trigger_fires_on_newer_blocker(self, tmp_path) -> None:
        import os as _os
        ws, plan = _plan_ws(tmp_path)
        bdir = ws / "blockers"
        bdir.mkdir()
        (bdir / "C-001.md").write_text("stuck: no license string", encoding="utf-8")
        old = plan.stat().st_mtime - 120
        _os.utime(plan, (old, old))
        hits = pr.detect_blocker_trigger(ws)
        assert len(hits) == 1 and hits[0]["claim"] == "C-001"
        assert hits[0]["trigger"] == "blocker" and hits[0]["suggest_revision"]

    def test_blocker_trigger_silent_when_blocker_older(self, tmp_path) -> None:
        import os as _os
        ws, plan = _plan_ws(tmp_path)
        bdir = ws / "blockers"
        bdir.mkdir()
        b = bdir / "C-001.md"
        b.write_text("old news", encoding="utf-8")
        past = plan.stat().st_mtime - 500
        _os.utime(b, (past, past))
        assert pr.detect_blocker_trigger(ws) == []
        # and a claim with NO blocker file at all
        assert pr.detect_blocker_trigger(_plan_ws(tmp_path, name="ws2")[0]) == []

    def test_assumption_conflict_on_newer_proven_fact(self, tmp_path) -> None:
        import os as _os
        ws, plan = _plan_ws(tmp_path)
        facts = ws / "facts"
        facts.mkdir()
        f = facts / "F001.md"
        f.write_text(
            "---\nstatus: PROVEN\nstatement: response body uses AES-256 "
            "encryption with static IV\n---\nbody text\n", encoding="utf-8")
        old = plan.stat().st_mtime - 120
        _os.utime(plan, (old, old))
        hits = pr.detect_assumption_conflict(ws)
        assert len(hits) == 1
        assert hits[0]["fact"] == "F001" and hits[0]["trigger"] == "assumption"

    def test_assumption_conflict_conservative_negatives(self, tmp_path) -> None:
        import os as _os
        ws, plan = _plan_ws(tmp_path)
        facts = ws / "facts"
        facts.mkdir()
        # overlap < MIN_TOKEN_OVERLAP -> silent
        weak = facts / "F002.md"
        weak.write_text("---\nstatus: PROVEN\nstatement: encryption key "
                        "rotates hourly\n---\nx", encoding="utf-8")
        # overlapping but NOT PROVEN (STAMP only) -> silent
        unproven = facts / "F003.md"
        unproven.write_text("---\nstatus: STAMP\nstatement: response body "
                            "uses AES-256 encryption mode CBC\n---\nx",
                            encoding="utf-8")
        old = plan.stat().st_mtime - 120
        for p in (weak, unproven):
            _os.utime(p, (old - 10,) * 2)
        _os.utime(plan, (old,) * 2)
        # make weak/unproven NEWER than plan too — they must still stay silent
        now = old + 400
        for p in (weak, unproven):
            _os.utime(p, (now, now))
        hits = pr.detect_assumption_conflict(ws)
        assert hits == [], hits

    def test_cost_trigger_reads_cost_gate_signal(self, tmp_path) -> None:
        ws, _ = _plan_ws(tmp_path)
        assert pr.detect_cost_trigger(ws) == []
        runs = ws / "runs"
        (runs / "cost_advice.json").write_text(
            json.dumps({"tier": "advisory", "count": 2}), encoding="utf-8")
        hits = pr.detect_cost_trigger(ws)
        assert len(hits) == 1 and hits[0]["trigger"] == "cost"
        (runs / "cost_advice.json").write_text(
            json.dumps({"tier": "none", "count": 0}), encoding="utf-8")
        assert pr.detect_cost_trigger(ws) == []


class TestJ3CheckApplyCli:
    def test_check_reports_all_three_and_exits_3(self, tmp_path) -> None:
        import os as _os
        ws, plan = _plan_ws(tmp_path)
        blockers = ws / "blockers"
        blockers.mkdir(parents=True)
        (blockers / "C-001.md").write_text("blocked on gpu", encoding="utf-8")
        facts = ws / "facts"
        facts.mkdir()
        (facts / "F009.md").write_text(
            "---\nstatus: PROVEN\nstatement: payload uses AES-256 "
            "encryption wrapping\n---\nx", encoding="utf-8")
        (ws / "runs" / "cost_advice.json").write_text(
            json.dumps({"tier": "advisory"}), encoding="utf-8")
        old = plan.stat().st_mtime - 60
        _os.utime(plan, (old, old))

        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_reviser.py"),
             "--check", str(ws)],
            capture_output=True, text=True, timeout=30)
        assert r.returncode == 3
        payload = json.loads(r.stdout)
        got = sorted(s["trigger"] for s in payload["suggestions"])
        assert got == ["assumption", "blocker", "cost"], payload
        assert "MUST produce a ## revision-N segment" in payload["contract"]

    def test_check_clean_workspace_exits_zero(self, tmp_path) -> None:
        ws, _ = _plan_ws(tmp_path)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_reviser.py"),
             "--check", str(ws)],
            capture_output=True, text=True, timeout=30)
        assert r.returncode == 0
        assert json.loads(r.stdout)["suggestions"] == []

    def test_apply_appends_audit_diff_without_rewrite(self, tmp_path) -> None:
        """Audit contract: the ONLY in-place change is the frontmatter revision
        counter; the appended revision segment is fresh suffix; earlier revision
        segments stay byte-identical."""
        ws, plan = _plan_ws(tmp_path)
        orig = plan.read_text(encoding="utf-8")
        orig_body = orig.split("\n---\n", 1)[1]  # body after the header fence

        r1 = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_reviser.py"),
             "--apply", str(ws), str(plan), "--trigger", "blocker",
             "--steps", "pause step 1; add preflight re-scan of strings",
             "--reason", "C-001 blocker: license string absent"],
            capture_output=True, text=True, timeout=30)
        assert r1.returncode == 0
        res = json.loads(r1.stdout)
        assert res["ok"] and res["revision"] == 1

        snap1 = plan.read_text(encoding="utf-8")
        seg1_start = snap1.index("## revision-1")
        seg1 = snap1[seg1_start:]
        assert "- trigger: blocker" in seg1
        assert "license string absent" in seg1
        # everything before revision-1 equals the original file except the
        # single bumped revision counter
        snap_body = snap1.split("\n---\n", 1)[1]
        head_body = snap_body.split("\n## revision-1", 1)[0]
        assert head_body == orig_body.replace(
            "revision: 0", "revision: 1"), "only the counter may change"
        _ = seg1_start

        # second apply increments; revision-1 stays byte-for-byte intact
        r2 = subprocess.run(
            [sys.executable, str(SCRIPTS / "plan_reviser.py"),
             "--apply", str(ws), str(plan), "--trigger", "cost",
             "--steps", "no change to steps", "--reason",
             "cost advisory kept: reduced dispatch verbosity only"],
            capture_output=True, text=True, timeout=30)
        assert r2.returncode == 0
        final = plan.read_text(encoding="utf-8")
        assert pr.parse_plan_header(final)["revision"] == 2
        assert seg1 in final, "earlier revision block must be byte-preserved"
        assert "## revision-2" in final.split("trigger:", 1)[-1] or \
            final.index("## revision-1") < final.index("## revision-2")


# ===========================================================================
# J4 — recall feedback loop (verdict -> stats -> demotion suggestions)
# ===========================================================================

import importlib.util as _ilu

_spec_lk = _ilu.spec_from_file_location(
    "kunglao_hooks_lib_test", ROOT / "hooks" / "lib_kunglao.py")
lk = _ilu.module_from_spec(_spec_lk)
_spec_lk.loader.exec_module(lk)
# load by explicit file path: a same-named scripts/lib_kunglao.py (drift
# lib) may already occupy sys.modules from earlier-collected test modules,
# and `sys.modules` caching would hand back the WRONG grammar module.

class TestJ4ParseFeedback:
    def test_parse_verdict_whitelist_last_wins(self) -> None:
        text = ("[09:00] step: x | status: in-progress\n"
                "[10:00] step: closed | status: done | artifacts: a.md "
                "| recall_useful: yes | notes: n.md")
        assert lk.parse_declared_recall_useful(text) == "yes"
        both = text.replace("recall_useful: yes",
                            "recall_useful: misleading(risk control)\n"
                            "[11:00] add | recall_useful: no")
        assert lk.parse_declared_recall_useful(both) == "no"

    def test_parse_rejects_unknown_and_missing(self) -> None:
        assert lk.parse_declared_recall_useful("recall_useful: maybe") is None
        assert lk.parse_declared_recall_useful("status: done") is None

    def test_feedback_terms_scoped_in_parens(self) -> None:
        verdict, terms = lk.parse_recall_feedback(
            "| status: done | recall_useful: misleading(Risk Control, memory-layout, risk control)")
        assert verdict == "misleading"
        assert terms == ["risk control", "memory-layout"]  # deduped, order kept
        v2, t2 = lk.parse_recall_feedback("| recall_useful: yes")
        assert (v2, t2) == ("yes", [])

    def test_iter_worker_states_exposes_recall_useful(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        runs = ws / "runs"
        runs.mkdir(parents=True)
        (runs / "worker-status-a.md").write_text(
            "[09:00] started c | status: in-progress\n"
            "[10:00] done | status: done | artifacts: facts/F001.md "
            "| recall_useful: misleading(crawler)\n", encoding="utf-8")
        rows = lk.iter_worker_states(ws)
        assert len(rows) == 1
        assert rows[0]["recall_useful"] == "misleading"

    def test_worker_done_template_documents_the_field(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "recall_useful: yes|no|misleading" in text
        assert "misleading(" in text  # term-scoping form shown by example


class TestJ4StatsAndDemotion:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        return ws

    def test_record_streak_and_demotion_boundary(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        for i in range(3):
            written = rr.record_feedback(ws, [("risk control", "misleading")])
            assert written == 1
        assert rr.demotion_suggestions(ws) == [("risk control", 3)]
        stats = rr.load_stats(ws)
        e = stats["terms"]["risk control"]
        assert (e["misleading"], e["streak"]) == (3, 3)

    def test_reset_on_non_misleading(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        rr.record_feedback(ws, [("crawler", "misleading")] * 2)
        rr.record_feedback(ws, [("crawler", "yes")])
        rr.record_feedback(ws, [("crawler", "misleading")])
        assert rr.demotion_suggestions(ws) == []
        e = rr.load_stats(ws)["terms"]["crawler"]
        assert e["streak"] == 1 and e["yes"] == 1

    def test_unknown_verdict_ignored_and_stats_isolated_to_runs(self, tmp_path):
        ws = self._ws(tmp_path)
        assert rr.record_feedback(ws, [("x", "bogus"), ("", "yes")]) == 0
        assert not (ws / "runs" / ".recall-stats.json").exists()

    def test_harvest_parses_status_files_via_lib_parser(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        (ws / "runs" / "worker-status-c001.md").write_text(
            "[09:00] started | status: in-progress\n"
            "[10:00] done | status: done | recall_useful: "
            "misleading(crawler, risk control)\n", encoding="utf-8")
        # a file without scope attaches to nothing (never counts toward
        # term demotion)
        (ws / "runs" / "worker-status-c002.md").write_text(
            "[09:00] done | status: done | recall_useful: misleading\n",
            encoding="utf-8")
        written, scanned = rr.harvest_feedback(ws)
        assert scanned == 2 and written == 2
        terms = {t for t, _ in rr.load_stats(ws)["terms"].items()}
        assert terms == {"crawler", "risk control"}

    def test_stats_cli_prints_suggestions_not_edits(self, tmp_path, capsys) -> None:
        ws = self._ws(tmp_path)
        rr.record_feedback(ws, [("risk control", "misleading")] * 3)
        rc = rr.main(["references_recall.py", "--feedback-stats", str(ws)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "DEMOTION SUGGESTIONS" in out
        assert "risk control = consecutive_misleading:3" in out
        # the skill dictionary itself must be untouched by the feedback face
        before = (ROOT / "references" / "_INDEX.yaml").read_bytes()
        rr.main(["references_recall.py", "--record-feedback", str(ws),
                 "risk control=misleading"])
        capsys.readouterr()
        assert (ROOT / "references" / "_INDEX.yaml").read_bytes() == before


class TestJ4RedteamAndJointTiming:
    def test_redteam_query_mapping(self) -> None:
        from recall_inject import queries_for_redteam

        base = "[T2 tools=python] verify-redteam target C-055 license claim"
        assert queries_for_redteam(base) == ["failure analysis"]
        web = "[T2 tools=camoufox] red-team the sign parameter claim of a --type web 风控 target"
        q = queries_for_redteam(web)
        assert q[0] == "failure analysis" and "risk control" in q

    def test_redteam_dispatch_gets_failure_modes_injection(self, tmp_path) -> None:
        from recall_inject import evaluate

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(
            "claims:\n- id: C-055\n  status: STAMP\n", encoding="utf-8")
        prompt = ("red-team checker dispatch: verify-redteam the license "
                  "algorithm claim C-055 with >=2 independent derivation paths")
        payload = {"hookEventName": "PreToolUse", "tool_name": "Agent",
                   "cwd": str(ws), "tool_input": {"prompt": prompt}}
        rc, stderr, ctx = evaluate(payload)
        assert rc == 0 and stderr == ""
        assert ctx, "red-team dispatch must receive adversarial knowledge"
        assert "failure-modes" in ctx or "failure_analysis" in ctx or \
            "failure-modes-lifecycle.md" in ctx

    def test_non_dispatch_non_redteam_stays_silent(self, tmp_path) -> None:
        from recall_inject import evaluate

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text("claims:\n- id: C-1\n", encoding="utf-8")
        payload = {"hookEventName": "PreToolUse", "tool_name": "Agent",
                   "cwd": str(ws),
                   "tool_input": {"prompt": "please summarize the report"}}
        rc, _, ctx = evaluate(payload)
        assert rc == 0 and ctx is None


class TestJ4JointQueryForThink:
    def test_build_joint_query_dedupes_and_caps(self) -> None:
        claims = "go binary symbol recovery from stripped binary"
        titles = ["F001 | PARTIAL | C-1 | go symbol table recovered partially",
                  "F002 | PROVEN   | C-1 | stripped layout confirmed",
                  "", "junk line counted once too many fine"] * 3
        q = rr.build_joint_query(claims, titles, max_titles=5, max_len=80)
        toks = q.split(" ")
        assert len(toks) == len(set(toks)), q
        assert len(q) <= 80 + 4  # hard cap honored

    def test_joint_cli_end_to_end(self, tmp_path, capsys) -> None:
        import yaml as y

        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(y.safe_dump(
            {"claims": [{"id": "C-7", "status": "OPEN",
                         "statement": "go binary symbol recovery needed"}]},
            allow_unicode=True, sort_keys=False), encoding="utf-8")
        (ws / "facts" / "_INDEX.md").write_text(
            "F001 | PARTIAL | C-7 | go runtime structures located\n",
            encoding="utf-8")
        rc = rr.main(["references_recall.py", "--joint", str(ws)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "# joint query:" in out
        assert "languages-go.md" in out, out

    def test_joint_cli_empty_inputs_exit_one(self, tmp_path, capsys) -> None:
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        rc = rr.main(["references_recall.py", "--joint", str(ws)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "joint query: (empty inputs)" in out


# ===========================================================================
# J5 — WebSearch as LEARN tier 2 + evidence discipline
# ===========================================================================

OPS_MD = ROOT / "references" / "operational-mechanics.md"


class TestJ5WebSearchLadder:
    def test_worker_learn_is_internal_first_two_tier(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "#761 J5" in text
        # order enforced INSIDE the ladder section (WebSearch legitimately
        # appears earlier in the file: allowedTools, plan preflight)
        seg = text[text.index("#761 J5"):text.index("2. **TRY**")]
        i_internal, i_external = seg.find("先查内部"), seg.find("WebSearch")
        assert -1 not in (i_internal, i_external)
        assert i_internal < i_external, "internal recall must precede WebSearch"
        for anchor in ("同族先例", "已知解法", "报错特征"):
            assert anchor in text, f"tier-2 search intent missing: {anchor}"

    def test_worker_evidence_discipline_url_and_date_in_derivation(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "URL" in text and "检索日期" in text
        # both rules present, near the ladder (same section)
        seg = text[text.index("#761 J5"):text.index("2. **TRY**")]
        assert "derivation" in seg
        assert "PROVEN" in seg and ("blind-check" in seg or "盲验" in seg)

    def test_ops_mechanics_ladder_mirrors_contract(self) -> None:
        """The mechanical face carries the same two-tier shape so hook-side
        prose never re-teaches the old 'WebSearch first' habit."""
        text = OPS_MD.read_text(encoding="utf-8")
        seg = text[text.index("## Worker self-drive"):]
        assert "INTERNAL first" in seg
        assert "references_recall.py" in seg and "re-library/" in seg
        assert "OUTWARD to `WebSearch`" in seg
        assert "URL + retrieval date" in seg
        assert "may not directly back PROVEN" in seg
        assert "blind-check" in seg
