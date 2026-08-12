"""tests/test_eval_harness.py — eval harness oracle 自检 (issue #4, plan §7).

RED: oracle 10/10 (确定性核心); 三臂配置; 故障注入骨架。
#81: 真实 bounded episodes + evaluator-owned receipts (executable L2 evaluation)。
"""
from __future__ import annotations

import json
from pathlib import Path

import kunglao_eval as ke


def test_oracle_selfcheck_10_10():
    """oracle 自检 10/10: 10 个已知答案例全过。"""
    results = ke.oracle_selfcheck()
    assert len(results) == 10, f"应有 10 个 oracle case, 实际 {len(results)}"
    failures = [r for r in results if not r["passed"]]
    assert not failures, f"oracle 失败: {[r['name'] + ': ' + r['reason'] for r in failures]}"


def test_oracle_cases_cover_core_behaviors():
    """oracle 覆盖核心行为 (leverage/discriminator/novelty/cost/dispatchable)。"""
    names = {r["name"] for r in ke.oracle_selfcheck()}
    must = [
        "terminal_leverage_zero", "downstream_leverage_high",
        "competitor_group_disc_top", "answers_question_disc_mid", "else_disc_floor",
        "tier_cost_penalty", "saturated_novelty_low", "fresh_novelty_high",
        "impossible_claim_excluded", "deterministic_pure",
    ]
    missing = [m for m in must if m not in names]
    assert not missing, f"oracle 缺 case: {missing}"


def test_arm_configs_defined():
    """三臂 A/B/C 配置存在且机制开关互斥。"""
    a = ke.ARM_CONFIGS["A"]
    b = ke.ARM_CONFIGS["B"]
    c = ke.ARM_CONFIGS["C"]
    assert a["mechanisms_enabled"] is True
    assert b["mechanisms_enabled"] is False
    assert c["single_agent"] is True


def test_arm_config_unknown_rejected():
    try:
        ke.run_arm("D")
        assert False, "未知 arm 应报错"
    except (ValueError, KeyError):
        pass


def test_fault_injection_types_defined():
    """五类故障注入类型定义 (plan §7)。"""
    for ftype in ("throttle", "implicit_fail", "explicit_fail", "impossible", "adversarial"):
        assert ftype in ke.FAULT_TYPES, f"缺故障类型: {ftype}"


def test_impossible_fault_detected():
    """impossible 故障: 无证据路径的 claim 被排除出 top_actions。"""
    result = ke.inject_fault("impossible")
    assert result["applied"] is True
    assert "no dispatchable path" in result["effect"].lower() or "excluded" in result["effect"].lower()


# =====================================================================
# #81 — executable, evaluator-owned L2 red-team evaluation
# =====================================================================

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "eval" / "fixtures"


def _case(case_id: str) -> dict:
    return json.loads((FIXTURES / case_id / "case.json").read_text(encoding="utf-8"))


def _oracle(case_id: str) -> dict:
    return json.loads((FIXTURES / case_id / "oracle.json").read_text(encoding="utf-8"))


def test_fixture_corpus_three_safe_cases():
    """#81: ≥3 safe synthetic fixtures, each with public case.json + hidden oracle.json."""
    for cid in ("decode-flag", "impossible-task", "adversarial-evidence"):
        case = _case(cid)
        oracle = _oracle(cid)
        assert case["synthetic"] is True, f"{cid} must be synthetic-only (no malware)"
        assert case["case_id"] == cid
        assert oracle["case_id"] == cid
        assert "expected_verdicts" in oracle
        assert "transcript" in case


def test_decode_episode_runs_and_writes_receipt(tmp_path):
    """#81: decode-flag arm A no-fault runs end to end; receipts carry digests/transcript hash/budgets/cleanup."""
    result, (jp, mp) = ke.run_fixture("decode-flag", "A", None, outdir=tmp_path, seed=1)
    assert result["case_id"] == "decode-flag" and result["arm"] == "A"
    assert result["claims_final"]["C-FLAG"]["status"] == "PROVEN"
    assert result["oracle"]["overall"] == "PASS"
    assert jp.exists() and mp.exists()
    rec = json.loads(jp.read_text(encoding="utf-8"))
    assert set(rec["digests"]) == {"case", "oracle", "code", "env"}
    assert rec["transcript_hash"]
    assert "wall_ms" in rec and "budgets" in rec
    assert rec["cleanup"]["reset"] == "ok"
    assert "failure_taxonomy" in rec


def test_repeated_trials_replayable(tmp_path):
    """#81: same (case, arm, fault, seed) → identical receipt digests (wall time excluded)."""
    case = _case("decode-flag")
    r1 = ke.run_episode(case, "A", None, seed=7)
    r2 = ke.run_episode(case, "A", None, seed=7)
    assert r1["receipt_digest"] == r2["receipt_digest"]
    assert r1["transcript_hash"] == r2["transcript_hash"]
    r3 = ke.run_episode(case, "A", None, seed=8)
    assert r1["receipt_digest"] != r3["receipt_digest"] or r1["transcript_hash"] != r3["transcript_hash"]


def test_three_arms_same_loop(tmp_path):
    """#81: arms A/B/C all run the same loop; same case digest; each produces a valid receipt."""
    case = _case("decode-flag")
    runs = {a: ke.run_episode(case, a, None, seed=3) for a in "ABC"}
    assert len({r["digests"]["case"] for r in runs.values()}) == 1
    for a, r in runs.items():
        assert r["arm"] == a and r["policy"]
        assert r["claims_final"]["C-FLAG"]["status"] == "PROVEN"
    for a, r in runs.items():
        scored = ke.score_episode(case, _oracle("decode-flag"), r)
        assert scored["oracle"]["overall"] == "PASS", f"arm {a} should pass decode-flag"


def test_arms_differ_on_impossible(tmp_path):
    """#81: impossible claim — arm A (VoI on) never dispatches; arm C (naive) does → invalid work → FAIL."""
    case = _case("impossible-task")
    ra = ke.run_episode(case, "A", None, seed=3)
    rc = ke.run_episode(case, "C", None, seed=3)
    assert all(d["claim_id"] != "C-IMP" for d in ra["transcript"]["dispatches"]), \
        "arm A must never dispatch the impossible claim"
    assert any(d["claim_id"] == "C-IMP" for d in rc["transcript"]["dispatches"]), \
        "arm C naive policy dispatches regardless"
    sa = ke.score_episode(case, _oracle("impossible-task"), ra)
    sc = ke.score_episode(case, _oracle("impossible-task"), rc)
    assert sa["oracle"]["dimensions"]["invalid_work"]["count"] == 0
    assert sa["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE"), "impossible → non-success"
    assert sc["oracle"]["dimensions"]["invalid_work"]["count"] >= 1
    assert sc["oracle"]["overall"] == "FAIL"


def test_fault_throttle_budget_exhausted(tmp_path):
    """#81: throttle alters the episode → budget_exhausted transition + non-success verdict."""
    case = _case("decode-flag")
    res = ke.run_episode(case, "A", "throttle", seed=2, throttle_after=0)
    assert any(t["type"] == "budget_exhausted" for t in res["state_transitions"]), \
        "throttle must produce a measurable state transition"
    assert res["claims_final"]["C-FLAG"]["status"] != "PROVEN"
    scored = ke.score_episode(case, _oracle("decode-flag"), res)
    assert scored["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE"), "never green on throttle"


def test_fault_implicit_fail_no_evidence_no_conclusion(tmp_path):
    """#81: implicit_fail (tool returns empty, no exception) → recognize non-conclusion, no overclaim."""
    case = _case("decode-flag")
    res = ke.run_episode(case, "A", "implicit_fail", seed=2, fail_after=1)
    assert any(t["type"] == "implicit_fail_recognized" for t in res["state_transitions"])
    assert res["claims_final"]["C-FLAG"]["status"] != "PROVEN"
    scored = ke.score_episode(case, _oracle("decode-flag"), res)
    assert scored["oracle"]["dimensions"]["overclaims"]["count"] == 0
    assert scored["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE")
    # a candidate that DOES conclude from the empty result overclaims → FAIL
    res_bad = ke.run_episode(case, "A", "implicit_fail", seed=2,
                             fail_after=1, assessor="naive")
    scored_bad = ke.score_episode(case, _oracle("decode-flag"), res_bad)
    assert scored_bad["oracle"]["dimensions"]["overclaims"]["count"] >= 1
    assert scored_bad["oracle"]["overall"] == "FAIL"


def test_fault_explicit_fail_not_redispatch(tmp_path):
    """#81: explicit_fail raises → claim DEFERRED, no re-dispatch of the same claim (arm A)."""
    case = _case("decode-flag")
    res = ke.run_episode(case, "A", "explicit_fail", seed=2, fail_after=1)
    assert any(t["type"] == "explicit_fail_deferred" for t in res["state_transitions"])
    assert res["claims_final"]["C-FLAG"]["status"] == "DEFERRED"
    n = sum(1 for d in res["transcript"]["dispatches"] if d["claim_id"] == "C-FLAG")
    assert n == 1, "arm A must not re-dispatch after explicit failure"
    scored = ke.score_episode(case, _oracle("decode-flag"), res)
    assert scored["oracle"]["dimensions"]["invalid_work"]["count"] == 0
    assert scored["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE")


def test_fault_impossible_excluded_and_never_dispatched(tmp_path):
    """#81: impossible fault — real priority_ratio excludes; claim stays OPEN; non-success verdict."""
    case = _case("impossible-task")
    res = ke.run_episode(case, "A", "impossible", seed=2)
    assert all(d["claim_id"] != "C-IMP" for d in res["transcript"]["dispatches"])
    assert res["claims_final"]["C-IMP"]["status"] == "OPEN"
    scored = ke.score_episode(case, _oracle("impossible-task"), res)
    assert scored["oracle"]["dimensions"]["invalid_work"]["count"] == 0
    assert scored["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE")


def test_fault_adversarial_decoy_overclaim(tmp_path):
    """#81: adversarial — anchored path passes; concluding from decoys overclaims → FAIL."""
    case = _case("adversarial-evidence")
    res_ok = ke.run_episode(case, "A", "adversarial", seed=2, assessor="anchored")
    assert res_ok["claims_final"]["C-DECOY"]["status"] == "OPEN"
    assert res_ok["claims_final"]["C-REAL"]["status"] == "PROVEN"
    scored_ok = ke.score_episode(case, _oracle("adversarial-evidence"), res_ok)
    assert scored_ok["oracle"]["dimensions"]["overclaims"]["count"] == 0
    assert scored_ok["oracle"]["overall"] == "PASS"
    res_bad = ke.run_episode(case, "A", "adversarial", seed=2, assessor="naive")
    scored_bad = ke.score_episode(case, _oracle("adversarial-evidence"), res_bad)
    assert scored_bad["oracle"]["dimensions"]["overclaims"]["count"] >= 1
    assert scored_bad["oracle"]["overall"] == "FAIL"


def test_l2_non_evidence_never_passes(tmp_path):
    """#81: NOT-RUN / UNKNOWN / failed injection / missing dispatcher never contribute to a passing score."""
    # missing dispatcher → NOT-RUN → non-evidence
    l2_none = ke.l2_redteam_capability("C-FLAG", tmp_path, dispatcher=None)
    assert l2_none["verdict"] == "NOT-RUN" and l2_none["evidence"] is False
    assert l2_none["dimension"] in ("FAIL", "INCONCLUSIVE")

    # dispatcher returning an invalid/UNKNOWN verdict → UNVERIFIED-WITH-GAP → non-evidence
    def bad_dispatch(claim_id, ws):
        return ("UNKNOWN", ["made up"])
    l2_bad = ke.l2_redteam_capability("C-FLAG", tmp_path, dispatcher=bad_dispatch)
    assert l2_bad["evidence"] is False and l2_bad["dimension"] in ("FAIL", "INCONCLUSIVE")

    # failed injection (dispatcher raises) → UNVERIFIED-WITH-GAP → non-evidence
    def raise_dispatch(claim_id, ws):
        raise RuntimeError("injection failure")
    l2_fail = ke.l2_redteam_capability("C-FLAG", tmp_path, dispatcher=raise_dispatch)
    assert l2_fail["evidence"] is False and l2_fail["dimension"] in ("FAIL", "INCONCLUSIVE")

    # real recorded dispatcher → CONFIRMED → evidence → dimension PASS
    rec = ke.RecordedDispatcher(
        {"C-FLAG": [{"tool": "xxd", "args": {"path": "blob.bin"},
                     "result": {"ok": True, "payload": {"facts": [
                         {"fact_id": "F-R", "conclusion": "ok",
                          "anchors": [{"cmd": "xxd blob.bin", "expected": "0c 46"}]}]}}}]},
        ke.RecordedToolAdapter(ke.Budget(max_calls=10, max_tokens=1000)))
    l2_ok = ke.l2_redteam_capability("C-FLAG", tmp_path, dispatcher=rec)
    assert l2_ok["evidence"] is True and l2_ok["dimension"] == "PASS"

    # capability receipt: non-evidence L2 → overall never green; evidence L2 + PASS episode → green
    case = _case("decode-flag")
    res = ke.run_episode(case, "A", None, seed=1)
    cap = ke.capability_score(case, _oracle("decode-flag"), res, l2_result=l2_none)
    assert cap["oracle"]["overall"] in ("FAIL", "INCONCLUSIVE")
    cap2 = ke.capability_score(case, _oracle("decode-flag"), res, l2_result=l2_ok)
    assert cap2["oracle"]["overall"] == "PASS"


def test_oracle_selfcheck_still_10_10_separate(tmp_path):
    """#81: oracle self-check stays 10/10 and is reported separately, never folded into capability dims."""
    results = ke.oracle_selfcheck()
    assert len(results) == 10 and all(r["passed"] for r in results)
    case = _case("decode-flag")
    res = ke.run_episode(case, "A", None, seed=1)
    cap = ke.capability_score(case, _oracle("decode-flag"), res, selfcheck=results)
    assert cap["oracle_selfcheck"]["passed"] == 10
    assert cap["oracle_selfcheck"]["kept_separate"] is True
    assert "oracle_selfcheck" not in cap["oracle"]["dimensions"]


def test_inject_without_run_fails_loud(capsys):
    """#81: --inject alone must not emit a scaffold receipt — exits 2 with guidance."""
    rc = ke.main(["--inject", "throttle"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "episode" in err
