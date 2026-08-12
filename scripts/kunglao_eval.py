#!/usr/bin/env python3
"""kunglao_eval.py — eval harness module (issue #4, plan §7, design-spec §6.7.6).

确定性核心: oracle 10/10 自检 (单独报告, 不并入 capability score)。
#81: executable, evaluator-owned L2 red-team evaluation — 真实 bounded episodes
跑在 injectable dispatcher/tool-adapter 边界上 (recorded transcript, 不跑真工具/
真实样本), 五类故障注入实际改变 episode 并捕获状态迁移, evaluator 控制的 oracle
独立打分, 收据 (JSON + MD) 可重放 (同输入 → 同 receipt_digest)。
CLI 入口: scripts/kunglao-eval.py (薄包装)。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import priority_ratio as pr
from status_defs import TERMINAL

ARM_CONFIGS = {
    "A": {"mechanisms_enabled": True, "single_agent": False,
          "desc": "所有重构机制全开 (priority_ratio VoI + gates + digest + verify)"},
    "B": {"mechanisms_enabled": False, "single_agent": False,
          "desc": "全关基线 (legacy 加法权重 + 无 gate) — 对照"},
    "C": {"mechanisms_enabled": False, "single_agent": True,
          "desc": "单 agent 无编排 (直接 LLM 跑) — 下界对照"},
}

FAULT_TYPES = {
    "throttle": {"desc": "限流: 工具调用配额耗尽 → orchestrator 须换路"},
    "implicit_fail": {"desc": "隐式失败: 工具返回空/错误但无异常 → 须识别非结论"},
    "explicit_fail": {"desc": "显式失败: 工具抛异常 → 须 failure_analysis 不重派"},
    "impossible": {"desc": "不可能: claim 无证据路径 → 须排除出 top_actions"},
    "adversarial": {"desc": "对抗: 诱饵串/反分析 → 须识别非 benign 也非真 IOC"},
}

# #81: arm → 确定性 candidate policy
POLICY_NAMES = {"A": "voi", "B": "legacy", "C": "naive"}
# fault 注入会阻止完成 → 非完成不算 candidate correctness 错 (INCONCLUSIVE 而非 FAIL)
FAULT_BLOCKING = ("throttle", "implicit_fail", "explicit_fail", "impossible")


def run_arm(arm: str) -> dict:
    if arm not in ARM_CONFIGS:
        raise ValueError(f"未知 arm: {arm}; 合法: {list(ARM_CONFIGS)}")
    return ARM_CONFIGS[arm]


def inject_fault(ftype: str) -> dict:
    """故障定义/验证函数。impossible 用真实 priority_ratio 验证排除 (历史行为)。

    其余四类故障在 #81 后必须在真实 episode 里注入 (run_episode fault=...) —
    单独调用返回标签正是 #81 要消除的 scaffold 行为, 故 fail loud。
    """
    if ftype not in FAULT_TYPES:
        raise ValueError(f"未知故障类型: {ftype}; 合法: {list(FAULT_TYPES)}")
    if ftype == "impossible":
        claims = [{"id": "IMP", "status": "OPEN", "statement": "impossible claim"}]
        deps = {"depends_on": {"IMP": ["BLOCKED-FOREVER"]}}
        out = pr.priority_ratio(claims, deps, pr.EvidenceView())
        applied = len(out) == 0
        effect = "impossible claim excluded from top_actions (no dispatchable path)"
    else:
        raise ValueError(
            f"{ftype} requires an episode — use run_episode(fault=...) or the CLI "
            "--run/--all flags (injection alters a real episode, never a label)")
    return {"type": ftype, "applied": applied, "effect": effect}


def _C(cid, **kw):
    c = {"id": cid, "status": "OPEN", "evidence_tier_attempted": 0,
         "promotion_attempts": 0, "statement": cid}
    c.update(kw)
    return c


def oracle_selfcheck() -> list[dict]:
    results = []
    def check(name, cond, reason):
        results.append({"name": name, "passed": bool(cond), "reason": reason if not cond else "ok"})

    out = pr.priority_ratio([_C("C-1"), _C("C-2")], {"depends_on": {"C-2": ["C-1"]}},
                            pr.EvidenceView(terminal_fact_claims=frozenset({"C-1"})))
    by = {a.claim_id: a for a in out}
    check("terminal_leverage_zero", by["C-1"].leverage == 0.0, f"L={by['C-1'].leverage}")

    out = pr.priority_ratio([_C("HUB"), _C("LA"), _C("LB"), _C("ORPH")],
                            {"depends_on": {"LA": ["HUB"], "LB": ["HUB"]}}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("downstream_leverage_high", by["HUB"].leverage > by["ORPH"].leverage,
          f"HUB={by['HUB'].leverage} ORPH={by['ORPH'].leverage}")

    out = pr.priority_ratio([_C("CA", competitor_group="q1"), _C("CB", competitor_group="q1")],
                            {"competitor_groups": {"q1": ["CA", "CB"]}}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("competitor_group_disc_top", by["CA"].discriminator == 1.0, f"D={by['CA'].discriminator}")

    out = pr.priority_ratio([_C("C", answers_question="q")], {}, pr.EvidenceView())
    check("answers_question_disc_mid", out[0].discriminator == 0.5, f"D={out[0].discriminator}")

    out = pr.priority_ratio([_C("C")], {}, pr.EvidenceView())
    check("else_disc_floor", out[0].discriminator == 0.2, f"D={out[0].discriminator}")

    out = pr.priority_ratio([_C("CHEAP", evidence_tier_attempted=0), _C("DEEP", evidence_tier_attempted=2)],
                            {}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("tier_cost_penalty", by["CHEAP"].cost < by["DEEP"].cost,
          f"CHEAP={by['CHEAP'].cost} DEEP={by['DEEP'].cost}")

    claims = [_C("C1", statement="c2 mpd"), _C("C2", statement="c2 pegasus")]
    o_sat = pr.priority_ratio(claims, {}, pr.EvidenceView(fact_count_by_category={"c2_config_extract": 3}))
    o_fr = pr.priority_ratio(claims, {}, pr.EvidenceView(fact_count_by_category={"c2_config_extract": 0}))
    check("saturated_novelty_low", o_sat[0].novelty < o_fr[0].novelty,
          f"sat={o_sat[0].novelty} fresh={o_fr[0].novelty}")
    check("fresh_novelty_high", o_fr[0].novelty == 1.0, f"N={o_fr[0].novelty}")

    out = pr.priority_ratio([_C("IMP")], {"depends_on": {"IMP": ["MISSING"]}}, pr.EvidenceView())
    check("impossible_claim_excluded", len(out) == 0, f"got {len(out)} actions")

    claims = [_C("A", statement="c2"), _C("B", statement="家族 vidar")]
    deps = {"depends_on": {"B": ["A"]}}
    o1 = pr.priority_ratio(claims, deps, pr.EvidenceView())
    o2 = pr.priority_ratio(claims, deps, pr.EvidenceView())
    check("deterministic_pure",
          [a.to_dict() for a in o1] == [a.to_dict() for a in o2], "two runs differ")

    return results


# =====================================================================
# #81 — executable, evaluator-owned L2 red-team evaluation
# =====================================================================

FIXTURES_DIR = ROOT / "eval" / "fixtures"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_digest() -> str:
    """code digest = 本模块 + 被 episode 真实调用的核心模块字节."""
    parts = []
    for name in ("kunglao_eval.py", "priority_ratio.py", "kunglao_verify.py"):
        p = SCRIPT_DIR / name
        parts.append(p.read_bytes() if p.exists() else b"")
    return hashlib.sha256(b"|".join(parts)).hexdigest()


def env_digest() -> str:
    return _sha256(f"{platform.python_implementation()}|{sys.version}|{platform.platform()}")


def _token_estimate(args: dict) -> int:
    return len(_canonical(args)) // 3 + 8


@dataclass(frozen=True)
class Budget:
    """工具调用预算 (calls = 调用数, tokens = 确定性估算 token)."""
    max_calls: int
    max_tokens: int


@dataclass
class ToolResult:
    tool: str
    args: dict
    ok: bool
    payload: dict | None = None
    error: str | None = None
    empty: bool = False  # 隐式失败指纹: ok 但无证据 (无异常)


class ToolError(Exception):
    """显式失败: 工具调用抛出的异常."""


class BudgetExhausted(ToolError):
    """throttle: 预算耗尽."""


@dataclass
class DispatchResult:
    claim_id: str
    ok: bool
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None
    failed_kind: str = "none"  # none | implicit | explicit | budget


class ToolAdapter:
    """工具边界 (产品 = MCP 工具; #81 harness = recorded, 不跑真工具)."""

    def call(self, name: str, args: dict, recorded: ToolResult | None = None) -> ToolResult:
        raise NotImplementedError


class RecordedToolAdapter(ToolAdapter):
    """确定性 recorded 工具边界: 预算记账 + 故障钩子; 结果由 dispatcher 的
    recorded transcript 提供. 永不执行真实工具/样本 (host-safe)."""

    def __init__(self, budget: Budget, *, fault: str | None = None,
                 fail_after: int | None = None, seed: int = 0):
        self.budget = budget
        self.fault = fault
        self.fail_after = fail_after
        self.seed = seed
        self.calls: list[dict] = []
        self.used_calls = 0
        self.used_tokens = 0

    def call(self, name: str, args: dict, recorded: ToolResult | None = None) -> ToolResult:
        self.calls.append({"tool": name, "args": args})
        self.used_calls += 1
        self.used_tokens += _token_estimate(args)
        if self.used_calls > self.budget.max_calls or self.used_tokens > self.budget.max_tokens:
            raise BudgetExhausted(
                f"tool budget exhausted: calls {self.used_calls}/{self.budget.max_calls} "
                f"tokens {self.used_tokens}/{self.budget.max_tokens}")
        if self.fault == "explicit_fail" and self.fail_after is not None and self.used_calls == self.fail_after:
            raise ToolError(f"explicit fault at tool call {self.used_calls}")
        if self.fault == "implicit_fail" and self.fail_after is not None and self.used_calls == self.fail_after:
            # 工具"成功"但返回空 — 无异常, 无证据 (隐式失败指纹)
            return ToolResult(name, args, ok=True, payload={"facts": []}, empty=True)
        return recorded if recorded is not None else ToolResult(
            name, args, ok=False, payload=None, error="no recorded result")


class Dispatcher:
    """worker 派发边界 (产品 = Agent tool 派发 subagent; #81 = recorded transcript)."""

    def dispatch(self, claim_id: str, task: dict | None = None) -> DispatchResult:
        raise NotImplementedError

    def __call__(self, claim_id: str, ws=None) -> tuple[str, list[str]]:
        """l2_redteam dispatcher 形状: (verdict, gaps)."""
        raise NotImplementedError


class RecordedDispatcher(Dispatcher):
    """重放 fixture 的 recorded transcript (per claim 的 tool 脚本) → 确定性证据.

    dispatch 抛 BudgetExhausted/ToolError → 故障分类结果; 返回的 evidence
    由 adapter 记账后的 transcript 决定.
    """

    def __init__(self, transcript: dict, adapter: RecordedToolAdapter):
        self.transcript = transcript or {}
        self.adapter = adapter

    def dispatch(self, claim_id: str, task: dict | None = None) -> DispatchResult:
        script = self.transcript.get(claim_id, []) or []
        evidence: list[dict] = []
        for step in script:
            result = step.get("result", {}) or {}
            rec = ToolResult(
                tool=str(step.get("tool", "")),
                args=step.get("args", {}) or {},
                ok=bool(result.get("ok", True)),
                payload=result.get("payload") or {},
                error=result.get("error"))
            try:
                r = self.adapter.call(rec.tool, rec.args, recorded=rec)
            except BudgetExhausted as exc:
                return DispatchResult(claim_id, ok=False, evidence=[], error=str(exc),
                                      failed_kind="budget")
            except ToolError as exc:
                return DispatchResult(claim_id, ok=False, evidence=[], error=str(exc),
                                      failed_kind="explicit")
            if r.empty or not r.ok:
                return DispatchResult(claim_id, ok=False, evidence=[],
                                      error=r.error or "tool returned empty/not-ok without exception",
                                      failed_kind="implicit")
            evidence.extend((r.payload or {}).get("facts", []) or [])
        return DispatchResult(claim_id, ok=True, evidence=evidence, failed_kind="none")

    def __call__(self, claim_id: str, ws=None) -> tuple[str, list[str]]:
        try:
            d = self.dispatch(claim_id, ws if isinstance(ws, dict) else None)
        except Exception as exc:  # 注入失败
            return ("UNVERIFIED-WITH-GAP", [f"recorded dispatch failed: {exc}"])
        if d.ok and d.evidence:
            return ("CONFIRMED", [])
        if d.ok:
            return ("UNVERIFIED-WITH-GAP", ["recorded dispatch produced no evidence"])
        return ("UNVERIFIED-WITH-GAP", [d.error or "dispatch not ok"])


class EpisodeState:
    """episode 内存状态 (per-trial fresh — reset 是真实行为, 无共享可变状态)."""

    def __init__(self, claims: dict[str, dict], deps: dict):
        self.claims = claims
        self.deps = deps or {}
        self.evidence: dict[str, list[dict]] = {}
        self.evidence_fact_ids: dict[str, list[str]] = {}
        self.fact_ids: set[str] = set()
        self.terminal_claims: set[str] = set()
        self.fact_count_by_category: dict[str, int] = {}
        self.step = 0
        self.dispatches: list[dict] = []
        self.transitions: list[dict] = []
        self.explicit_incomplete = False

    def dispatchable(self, claim: dict) -> bool:
        parents = (self.deps.get("depends_on", {}) or {}).get(claim["id"], []) or []
        return all(p in self.terminal_claims for p in parents)

    def evidence_view(self) -> pr.EvidenceView:
        return pr.EvidenceView(
            terminal_fact_claims=frozenset(self.terminal_claims),
            verified_fact_count=len(self.fact_ids),
            fact_count_by_category=dict(self.fact_count_by_category))

    def set_status(self, claim_id: str, status: str) -> None:
        self.claims[claim_id]["status"] = status
        if status in TERMINAL:
            self.terminal_claims.add(claim_id)

    def record_dispatch(self, claim_id: str, dispatch: DispatchResult) -> None:
        self.dispatches.append({"claim_id": claim_id, "step": self.step,
                                "status_before": self.claims[claim_id].get("status"),
                                "failed_kind": dispatch.failed_kind})

    def add_evidence(self, claim_id: str, facts: list[dict]) -> None:
        self.evidence.setdefault(claim_id, []).extend(facts)
        for f in facts:
            fid = f.get("fact_id")
            if fid:
                self.fact_ids.add(fid)
            cat = f.get("category", "evidence_collection")
            self.fact_count_by_category[cat] = self.fact_count_by_category.get(cat, 0) + 1

    def conclude(self, claim_id: str, evidence_ids: list[str]) -> None:
        self.set_status(claim_id, "PROVEN")
        self.evidence_fact_ids[claim_id] = list(evidence_ids)
        self.transitions.append({"type": "claim_concluded", "claim_id": claim_id,
                                 "evidence_fact_ids": list(evidence_ids)})

    def claims_final(self) -> dict:
        return {cid: {"status": c.get("status"),
                      "evidence_fact_ids": list(self.evidence_fact_ids.get(cid, []))}
                for cid, c in sorted(self.claims.items())}


def _eligible_voi(state: EpisodeState, dispatched: set[str]) -> list[dict]:
    out = []
    for c in state.claims.values():
        cid = c["id"]
        if not pr.is_open(c):
            continue
        if int(c.get("promotion_attempts", 0)) >= 3:
            continue
        if cid in dispatched:  # no-repeat: 已派发未结论的 claim 不重复派 (premature/redundant 防护)
            continue
        out.append(c)
    return out


def _policy_voi(state: EpisodeState, dispatched: set[str]) -> str | None:
    eligible = _eligible_voi(state, dispatched)
    if not eligible:
        return None
    actions = pr.priority_ratio(eligible, state.deps, state.evidence_view())
    if not actions:
        return None
    return actions[0].claim_id


def _policy_legacy(state: EpisodeState, dispatched: set[str]) -> str | None:
    """legacy 加法权重 (对照): 无 VoI, 无 dispatchability gate, 无 no-repeat."""
    best: str | None = None
    best_score = -1.0
    for c in state.claims.values():
        if not pr.is_open(c):
            continue
        cid = c["id"]
        out_deg = len((state.deps.get("depends_on", {}) or {}).get(cid, []) or [])
        score = (0.4 * out_deg + 0.3 * pr.cheapness(c)
                 + 0.3 * (1.0 - 0.1 * int(c.get("promotion_attempts", 0))))
        if best is None or score > best_score or (score == best_score and cid < best):
            best, best_score = cid, score
    return best


def _policy_naive(state: EpisodeState, dispatched: set[str], claim_order: list[str]) -> str | None:
    for cid in claim_order:
        c = state.claims.get(cid)
        if c and pr.is_open(c) and cid not in dispatched:
            return cid
    return None


def _apply_dispatch(state: EpisodeState, cid: str, dispatch: DispatchResult,
                    assessor: str) -> bool:
    """把派发结果落为状态迁移; 返回 True 表示 episode 应立即停止."""
    if dispatch.failed_kind == "budget":
        state.transitions.append({"type": "budget_exhausted", "claim_id": cid,
                                  "detail": dispatch.error})
        state.explicit_incomplete = True
        return True
    if dispatch.failed_kind == "explicit":
        state.transitions.append({"type": "explicit_fail_deferred", "claim_id": cid,
                                  "detail": dispatch.error})
        state.set_status(cid, "DEFERRED")
        return False
    if dispatch.failed_kind == "implicit":
        if assessor == "naive":
            # overclaiming 候选: 把"空结果"当成功 → 空证据结论 (scorer 记 overclaim)
            state.transitions.append({"type": "implicit_fail_misread_as_success", "claim_id": cid})
            state.conclude(cid, [])
        else:
            state.transitions.append({"type": "implicit_fail_recognized", "claim_id": cid})
        return False
    # ok
    if dispatch.evidence:
        state.add_evidence(cid, dispatch.evidence)
    if assessor == "anchored":
        supporting = [f for f in dispatch.evidence if f.get("anchors")]
        concluded = bool(supporting)
    else:
        supporting = dispatch.evidence
        concluded = True  # naive: 只要有"成功"派发就结论
    if concluded:
        ids = [f.get("fact_id", f"fact-{i}") for i, f in enumerate(supporting)]
        state.conclude(cid, ids)
    return False


def _apply_fault_injection(case: dict, state: EpisodeState, transcript: dict,
                           fault: str | None, claim_order: list[str]) -> list[str]:
    """把 fault 实际注入 episode (状态迁移可测, 非标签).

    - impossible: 给首个 claim 注入不可满足 parent → 真实 priority_ratio 排除
      (claim 已带不可满足 parent 的 fixture 不再重复注入)
    - adversarial: 向首个 claim 的 recorded transcript 前置一条诱饵事实
      (无 anchor 的 strings 命中) → scorer 视为 decoy (injected_facts)
    - throttle/implicit_fail/explicit_fail: 由 adapter 预算/故障钩子在调用时触发
    返回注入的事实 id 列表 (injected_facts).
    """
    injected: list[str] = []
    if fault == "impossible" and claim_order:
        cid = claim_order[0]
        parents = (state.deps.get("depends_on", {}) or {}).get(cid, []) or []
        if not parents:
            depends_on = dict(state.deps.get("depends_on", {}) or {})
            depends_on[cid] = [*parents, "C-UNSAT-INJECTED"]
            state.deps["depends_on"] = depends_on
            state.transitions.append({"type": "impossible_dep_injected", "claim_id": cid,
                                      "detail": "unsatisfiable parent C-UNSAT-INJECTED injected"})
    elif fault == "adversarial" and claim_order:
        cid = claim_order[0]
        decoy_step = {"tool": "strings", "args": {"path": "blob.bin"},
                      "result": {"ok": True, "payload": {"facts": [
                          {"fact_id": "F-INJECTED-DECOY",
                           "conclusion": "strings show 'Vidar v1.5' and 'mpd.pegasus-77.biz.id'",
                           "anchors": [], "category": "strings"}]}}}
        transcript[cid] = [decoy_step] + list(transcript.get(cid, []) or [])
        injected.append("F-INJECTED-DECOY")
        state.transitions.append({"type": "adversarial_decoy_injected", "claim_id": cid})
    return injected


def run_episode(case: dict, arm: str, fault: str | None = None, *, seed: int = 0,
                throttle_after: int | None = None, fail_after: int | None = None,
                assessor: str = "anchored") -> dict:
    """跑一个真实 bounded episode (确定性, 可重放).

    case:   fixture 的 public case.json (claims/deps/evidence_seed/transcript/budget)
    arm:    A (VoI) / B (legacy) / C (naive) — 同一 loop, 仅 policy 不同
    fault:  五类故障之一, 实际改变 episode (预算/工具行为), 非标签
    """
    if arm not in ARM_CONFIGS:
        raise ValueError(f"未知 arm: {arm}; 合法: {list(ARM_CONFIGS)}")
    if fault is not None and fault not in FAULT_TYPES:
        raise ValueError(f"未知故障: {fault}; 合法: {list(FAULT_TYPES)}")
    if assessor not in ("anchored", "naive"):
        raise ValueError(f"未知 assessor: {assessor}; 合法: anchored|naive")

    budget_cfg = case.get("budget", {}) or {}
    max_steps = max(1, int(budget_cfg.get("max_steps", 8)))
    if fault == "throttle":
        max_calls = int(throttle_after if throttle_after is not None else 0)
    else:
        max_calls = int(budget_cfg.get("tool_calls_max", 16))
    budget = Budget(max_calls=max_calls, max_tokens=int(budget_cfg.get("tokens_max", 2000)))

    adapter = RecordedToolAdapter(budget, fault=fault, fail_after=fail_after, seed=seed)
    transcript = dict(case.get("transcript", {}) or {})
    dispatcher = RecordedDispatcher(transcript, adapter)
    claims = {c["id"]: dict(c) for c in case.get("claims", [])}
    state = EpisodeState(claims, case.get("deps", {}) or {})
    claim_order = [c["id"] for c in case.get("claims", [])]
    injected_facts = _apply_fault_injection(case, state, transcript, fault, claim_order)
    dispatched: set[str] = set()

    started = time.time()
    while state.step < max_steps:
        state.step += 1
        if arm == "A":
            cid = _policy_voi(state, dispatched)
        elif arm == "B":
            cid = _policy_legacy(state, dispatched)
        else:
            cid = _policy_naive(state, dispatched, claim_order)
        if cid is None:
            open_ids = sorted(c["id"] for c in state.claims.values() if pr.is_open(c))
            if open_ids:
                disp_open = sorted(cid2 for cid2 in open_ids if state.dispatchable(state.claims[cid2]))
                state.transitions.append({"type": "no_action_available", "step": state.step,
                                          "open": open_ids, "dispatchable_open": disp_open})
            else:
                state.transitions.append({"type": "converged", "step": state.step})
            break
        dispatched.add(cid)
        try:
            dispatch = dispatcher.dispatch(cid, case.get("task", {}))
        except Exception as exc:  # 意外崩溃 → 显式失败处理
            dispatch = DispatchResult(cid, ok=False, evidence=[],
                                      error=f"dispatch crashed: {exc}", failed_kind="explicit")
        state.record_dispatch(cid, dispatch)
        if _apply_dispatch(state, cid, dispatch, assessor):
            break

    wall_ms = int((time.time() - started) * 1000)
    transcript = {"dispatches": state.dispatches, "tool_calls": adapter.calls}
    result = {
        "schema": "kunglao-episode-result/1",
        "case_id": case.get("case_id", "?"),
        "arm": arm,
        "fault": fault,
        "policy": POLICY_NAMES[arm],
        "seed": seed,
        "assessor": assessor,
        "injected_facts": injected_facts,
        "digests": {"case": _sha256(_canonical(case)),
                    "code": code_digest(),
                    "env": env_digest()},
        "transcript": transcript,
        "transcript_hash": _sha256(_canonical(transcript)),
        "state_transitions": state.transitions,
        "claims_final": state.claims_final(),
        "terminal_claims": sorted(state.terminal_claims),
        "budgets": {"tool_calls_used": adapter.used_calls,
                    "tool_calls_max": adapter.budget.max_calls,
                    "tokens_used": adapter.used_tokens,
                    "tokens_max": adapter.budget.max_tokens,
                    "steps_used": state.step,
                    "steps_max": max_steps},
        "wall_ms": wall_ms,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "explicit_incomplete": state.explicit_incomplete,
        "cleanup": {"reset": "ok",
                    "detail": "episode state is in-memory, fresh per trial; no temp files created"},
    }
    result["receipt_digest"] = _sha256(_canonical(_stable_fields(result)))
    return result


def _stable_fields(result: dict) -> dict:
    """receipt_digest 的稳定字段: 排除 wall_ms/timestamps/自身 digest/嵌套 time_ms
    → 同输入同 digest (可重放; wall time 仅记录不参与摘要)."""
    out = copy.deepcopy(result)
    for k in ("wall_ms", "started_at", "finished_at", "receipt_digest"):
        out.pop(k, None)
    dims = (out.get("oracle") or {}).get("dimensions")
    if isinstance(dims, dict):
        dims.pop("time_ms", None)
    return out


def _recovery(result: dict, fault: str | None, oracle: dict | None = None) -> tuple[bool, str]:
    final = result.get("claims_final", {})
    transitions = result.get("state_transitions", [])
    types = {t.get("type") for t in transitions}
    if fault is None:
        return True, "no fault injected"
    if fault == "throttle":
        ok = "budget_exhausted" in types and result.get("explicit_incomplete") is True
        detail = ("budget_exhausted + explicit_incomplete" if ok
                  else f"missing budget_exhausted/complete marker (types={sorted(types)})")
        return ok, detail
    if fault == "explicit_fail":
        deferred = [cid for cid, f in final.items() if f.get("status") == "DEFERRED"]
        if not deferred:
            return False, "no claim deferred after explicit failure"
        cid = deferred[0]
        n = sum(1 for d in result.get("transcript", {}).get("dispatches", [])
                if d.get("claim_id") == cid)
        ok = n == 1
        return ok, f"claim {cid} deferred, {n} dispatch(s)"
    if fault == "implicit_fail":
        recognized = "implicit_fail_recognized" in types
        return recognized, ("recognized non-conclusion"
                            if recognized else "treated empty result as evidence")
    if fault == "impossible":
        ok = "no_action_available" in types
        return ok, ("impossible claim excluded (no_action_available)"
                    if ok else "no no_action_available transition")
    if fault == "adversarial" and oracle is not None:
        bad = [cid for cid, want in (oracle.get("expected_verdicts", {}) or {}).items()
               if want == "OPEN" and final.get(cid, {}).get("status") == "PROVEN"]
        ok = not bad
        return ok, ("decoy claims not concluded" if ok else f"concluded decoy claims {bad}")
    return True, f"fault {fault} applied (no specific recovery check)"


def _failure_taxonomy(result: dict, fault: str | None, completion: str = "solvable") -> list[str]:
    types = {t.get("type") for t in result.get("state_transitions", [])}
    tax = set()
    if fault:
        tax.add(fault)
    if "budget_exhausted" in types:
        tax.add("throttle")
    if "explicit_fail_deferred" in types:
        tax.add("explicit_fail")
    if "implicit_fail_recognized" in types or "implicit_fail_misread_as_success" in types:
        tax.add("implicit_fail")
    # no_action_available → impossible 仅当 fixture 本身不可完成 (solvable 的正常
    # 收敛/decoy 停留 OPEN 不算 impossible)
    if completion == "impossible" and ("no_action_available" in types
                                       or "impossible_dep_injected" in types):
        tax.add("impossible")
    if "adversarial_decoy_injected" in types:
        tax.add("adversarial")
    return sorted(tax)


def score_episode(case: dict, oracle: dict, result: dict) -> dict:
    """evaluator 控制的 oracle 打分 (独立于 candidate; hidden oracle 输入)."""
    expected = oracle.get("expected_verdicts", {}) or {}
    injected = set(result.get("injected_facts", []) or [])
    decoys = set(oracle.get("decoy_fact_ids", []) or []) | injected
    completion = oracle.get("completion", "solvable")
    fault = result.get("fault")
    final = result.get("claims_final", {})
    deps = (case.get("deps", {}) or {}).get("depends_on", {}) or {}
    terminal = set(result.get("terminal_claims", []))
    fault_blocked = fault in FAULT_BLOCKING
    types = {t.get("type") for t in result.get("state_transitions", [])}
    # 注入可观测性: 注入的 fault 必须产生状态迁移, 否则 trial 非绿 (防 scaffold 冒充)
    fault_effects = {
        "throttle": "budget_exhausted" in types,
        "implicit_fail": bool({"implicit_fail_recognized", "implicit_fail_misread_as_success"} & types),
        "explicit_fail": "explicit_fail_deferred" in types,
        "impossible": "no_action_available" in types or "impossible_dep_injected" in types,
        "adversarial": "adversarial_decoy_injected" in types,
    }
    injection_observed = fault is None or fault_effects.get(fault, True)
    dims: dict = {}

    # correctness: 逐 claim 状态 vs oracle; fault 阻止完成 → 豁免 (非 candidate 错)
    mismatches = []
    for cid, want in expected.items():
        got = final.get(cid, {}).get("status")
        if got != want and not (fault_blocked and want == "PROVEN" and got in ("OPEN", "DEFERRED")):
            mismatches.append(f"{cid}: want {want} got {got}")
    dims["correctness"] = {"pass": not mismatches,
                           "detail": "; ".join(mismatches) or "all claims match oracle"}

    # invalid / redundant work: terminal 后重派 / 非 dispatchable claim 强派
    invalid = []
    for d in result.get("transcript", {}).get("dispatches", []):
        cid = d.get("claim_id")
        if d.get("status_before") in TERMINAL:
            invalid.append(f"{cid}: re-dispatch after terminal ({d.get('status_before')})")
        parents = deps.get(cid, []) or []
        if parents and not any(p in terminal for p in parents):
            invalid.append(f"{cid}: dispatch of non-dispatchable claim (dep {parents} never terminal)")
    dims["invalid_work"] = {"count": len(invalid), "pass": not invalid,
                            "detail": "; ".join(invalid) or "no invalid work"}

    # overclaims: 空证据结论 / 用诱饵事实结论
    overclaims = []
    for cid, info in final.items():
        if info.get("status") != "PROVEN":
            continue
        ids = info.get("evidence_fact_ids", [])
        if not ids:
            overclaims.append(f"{cid}: concluded with zero evidence facts")
        hit = sorted(set(ids) & decoys)
        if hit:
            overclaims.append(f"{cid}: concluded using decoy facts {hit}")
    dims["overclaims"] = {"count": len(overclaims), "pass": not overclaims,
                          "detail": "; ".join(overclaims) or "no overclaims"}

    # misses: 无 fault 时 dispatchable 且 oracle 期望 PROVEN 却未结论
    misses = []
    if not fault_blocked:
        for cid, want in expected.items():
            got = final.get(cid, {}).get("status")
            if want == "PROVEN" and got in ("OPEN", "DEFERRED"):
                misses.append(f"{cid}: left {got}")
    dims["misses"] = {"count": len(misses), "pass": not misses,
                      "detail": "; ".join(misses) or "no misses"}

    if fault is not None and not injection_observed:
        dims["recovery"] = {"pass": True,
                            "detail": f"fault {fault} had no observable effect — recovery not exercised"}
        dims["injection"] = {"observed": False,
                             "detail": f"fault {fault} applied but produced no state transition — non-green"}
    else:
        recovery_pass, recovery_detail = _recovery(result, fault, oracle)
        dims["recovery"] = {"pass": recovery_pass, "detail": recovery_detail}

    budgets = result.get("budgets", {})
    dims["time_ms"] = result.get("wall_ms", 0)
    dims["tool_calls"] = budgets.get("tool_calls_used", 0)
    dims["tokens"] = budgets.get("tokens_used", 0)

    fails = [n for n, d in dims.items() if isinstance(d, dict) and d.get("pass") is False]
    uncompleted = [cid for cid, want in expected.items()
                   if want == "PROVEN" and final.get(cid, {}).get("status") != "PROVEN"]
    if fails:
        overall = "FAIL"
    elif fault is not None and not injection_observed:
        overall = "INCONCLUSIVE"
    elif completion == "impossible" or (fault_blocked and uncompleted) or (not fault_blocked and misses):
        overall = "INCONCLUSIVE"
    else:
        overall = "PASS"
    return {"oracle": {"overall": overall, "dimensions": dims},
            "failure_taxonomy": _failure_taxonomy(result, fault, completion)}


def l2_redteam_capability(claim_id: str, ws, dispatcher=None) -> dict:
    """真实 l2_redteam + 注入 dispatcher 的 L2 能力维度 (#81).

    NOT-RUN / UNKNOWN(无效 verdict) / 注入失败 / 缺 dispatcher = 非证据,
    永不构成 passing capability score.
    """
    from kunglao_verify import l2_redteam
    try:
        verdict, gaps = l2_redteam(claim_id, Path(ws) if ws is not None else None,
                                   dispatcher=dispatcher)
    except Exception as exc:
        return {"verdict": "UNVERIFIED-WITH-GAP", "gaps": [f"l2_redteam call failed: {exc}"],
                "evidence": False, "dimension": "FAIL", "detail": "l2_redteam raised"}
    if verdict not in ("CONFIRMED", "REFUTED"):
        if verdict == "NOT-RUN":
            return {"verdict": verdict, "gaps": list(gaps or []), "evidence": False,
                    "dimension": "INCONCLUSIVE",
                    "detail": "L2 not run (no dispatcher) — non-evidence"}
        return {"verdict": verdict, "gaps": list(gaps or []), "evidence": False,
                "dimension": "FAIL",
                "detail": f"L2 produced no valid verdict {verdict!r} — non-evidence"}
    return {"verdict": verdict, "gaps": list(gaps or []), "evidence": True,
            "dimension": "PASS", "detail": f"real L2 verdict {verdict}"}


def capability_score(case: dict, oracle: dict, episode_result: dict,
                     l2_result: dict | None = None, selfcheck: list[dict] | None = None) -> dict:
    """capability receipt 聚合: episode 各维度 + L2 能力维度 (非证据 → 永不绿)."""
    scored = score_episode(case, oracle, episode_result)
    dims = dict(scored["oracle"]["dimensions"])
    if l2_result is None:
        l2_result = {"verdict": "NOT-RUN", "gaps": ["missing dispatcher"],
                     "evidence": False, "dimension": "INCONCLUSIVE",
                     "detail": "no L2 dispatcher supplied — non-evidence"}
    dims["l2_capability"] = {"pass": bool(l2_result.get("evidence")),
                             "verdict": l2_result.get("verdict"),
                             "gaps": l2_result.get("gaps", []),
                             "dimension": l2_result.get("dimension", "INCONCLUSIVE")}
    rec = dict(episode_result)
    rec.update({"oracle": {"overall": None, "dimensions": dims},
                "failure_taxonomy": scored["failure_taxonomy"]})
    fails = [n for n, d in dims.items() if isinstance(d, dict) and d.get("pass") is False]
    l2_dim = dims["l2_capability"].get("dimension")
    if fails:
        overall = "FAIL"
    elif l2_dim != "PASS" or scored["oracle"]["overall"] == "INCONCLUSIVE":
        overall = "INCONCLUSIVE"
    else:
        overall = "PASS"
    rec["oracle"]["overall"] = overall
    if selfcheck:
        rec["oracle_selfcheck"] = {"passed": sum(1 for r in selfcheck if r.get("passed")),
                                   "cases": len(selfcheck), "kept_separate": True}
    rec["receipt_digest"] = _sha256(_canonical(_stable_fields(rec)))
    return rec


def load_case(case_id: str) -> dict:
    p = FIXTURES_DIR / case_id / "case.json"
    if not p.exists():
        raise FileNotFoundError(f"fixture case not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_oracle(case_id: str) -> dict:
    p = FIXTURES_DIR / case_id / "oracle.json"
    if not p.exists():
        raise FileNotFoundError(f"fixture oracle not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def fixture_ids() -> list[str]:
    return sorted(d.name for d in FIXTURES_DIR.iterdir()
                  if d.is_dir() and (d / "case.json").exists() and (d / "oracle.json").exists())


def _receipt_md(receipt: dict, label: str) -> str:
    lines = [f"# kunglao eval receipt — {label}", ""]
    lines.append(f"- case: {receipt.get('case_id')} / arm {receipt.get('arm')} / "
                 f"fault {receipt.get('fault')} / policy {receipt.get('policy')}")
    lines.append(f"- overall: **{receipt.get('oracle', {}).get('overall')}**")
    d = receipt.get("digests", {})
    lines.append(f"- digests: case={d.get('case', '')[:12]}… code={d.get('code', '')[:12]}… "
                 f"env={d.get('env', '')[:12]}… oracle={d.get('oracle', '')[:12]}…")
    lines.append(f"- transcript_hash: {receipt.get('transcript_hash', '')[:16]}…")
    lines.append(f"- wall_ms: {receipt.get('wall_ms')}  "
                 f"budgets: {receipt.get('budgets')}")
    lines.append(f"- failure_taxonomy: {receipt.get('failure_taxonomy')}")
    lines.append(f"- cleanup: {receipt.get('cleanup')}")
    lines.append(f"- receipt_digest: {receipt.get('receipt_digest')}")
    lines.append("")
    lines.append("## claims_final")
    for cid, info in (receipt.get("claims_final", {}) or {}).items():
        lines.append(f"- {cid}: {info.get('status')} evidence={info.get('evidence_fact_ids')}")
    lines.append("")
    lines.append("## oracle dimensions")
    for name, dim in (receipt.get("oracle", {}).get("dimensions", {}) or {}).items():
        if isinstance(dim, dict):
            extra = ""
            if "verdict" in dim:
                extra = f" verdict={dim.get('verdict')} ({dim.get('dimension')})"
            lines.append(f"- {name}: pass={dim.get('pass')}{extra} — {dim.get('detail', '')}")
        else:
            lines.append(f"- {name}: {dim}")
    if "oracle_selfcheck" in receipt:
        sc = receipt["oracle_selfcheck"]
        lines.append(f"\n## oracle selfcheck (separate, deterministic): "
                     f"{sc.get('passed')}/{sc.get('cases')} kept_separate={sc.get('kept_separate')}")
    lines.append("\n## state transitions")
    for t in receipt.get("state_transitions", []):
        lines.append(f"- {t}")
    return "\n".join(lines) + "\n"


def write_receipts(receipt: dict, outdir: Path, label: str) -> tuple[Path, Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    jp = outdir / f"receipt-{label}.json"
    mp = outdir / f"receipt-{label}.md"
    jp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    mp.write_text(_receipt_md(receipt, label), encoding="utf-8")
    return jp, mp


def run_fixture(case_id: str, arm: str, fault: str | None = None, *, outdir=None,
                seed: int = 0, label_suffix: str = "", **kwargs) -> tuple[dict, tuple[Path, Path]]:
    """端到端: episode → oracle 打分 → 真实 l2_redteam (注入 recorded dispatcher)
    → capability receipt (JSON + MD) 落盘. label_suffix 供 --repeat 区分同 seed 复跑."""
    case = load_case(case_id)
    oracle = load_oracle(case_id)
    result = run_episode(case, arm, fault, seed=seed, **kwargs)
    l2 = l2_redteam_capability(
        case["claims"][0]["id"], ROOT,
        dispatcher=RecordedDispatcher(case.get("transcript", {}) or {},
                                      RecordedToolAdapter(Budget(max_calls=16, max_tokens=2000))))
    cap = capability_score(case, oracle, result, l2_result=l2, selfcheck=oracle_selfcheck())
    cap["digests"]["oracle"] = _file_sha256(FIXTURES_DIR / case_id / "oracle.json")
    cap["digests"]["case"] = _file_sha256(FIXTURES_DIR / case_id / "case.json")
    out = Path(outdir) if outdir else ROOT / "eval" / "receipts"
    label = f"{case_id}-{arm}-{fault or 'none'}-{seed}{label_suffix}"
    jp, mp = write_receipts(cap, out, label)
    return cap, (jp, mp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kunglao-eval.py", description="eval harness")
    ap.add_argument("--oracle-selfcheck", action="store_true",
                    help="deterministic oracle 10/10 self-check (reported separately)")
    ap.add_argument("--arm", default=None, choices=list(ARM_CONFIGS))
    ap.add_argument("--inject", default=None, choices=list(FAULT_TYPES),
                    help="fault injected into a real episode (requires --run/--all)")
    ap.add_argument("--run", metavar="CASE_ID", default=None,
                    help="run one fixture end to end and write receipts")
    ap.add_argument("--all", action="store_true",
                    help="all fixtures × arms × faults × --repeat")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    if args.oracle_selfcheck:
        results = oracle_selfcheck()
        passed = sum(r["passed"] for r in results)
        print(f"oracle selfcheck: {passed}/{len(results)}")
        for r in results:
            mark = "OK" if r["passed"] else "FAIL"
            print(f"  [{mark}] {r['name']}: {r['reason']}")
        return 0 if passed == len(results) else 1

    if args.arm and not (args.run or args.all):
        print(f"arm {args.arm}: {run_arm(args.arm)}")
        return 0

    if args.inject and not (args.run or args.all):
        print("error: --inject <fault> requires --run <case-id> or --all — injection "
              "alters a real episode; it is never a standalone label", file=sys.stderr)
        return 2

    outdir = Path(args.outdir) if args.outdir else ROOT / "eval" / "receipts"

    if args.run:
        try:
            result, (jp, mp) = run_fixture(args.run, args.arm or "A", args.inject,
                                           outdir=outdir, seed=args.seed)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"trial {result['case_id']} arm={result['arm']} fault={result.get('fault')}: "
              f"{result['oracle']['overall']} → {jp}")
        return 0

    if args.all:
        for case_id in fixture_ids():
            for arm in "ABC":
                for fault in [None] + list(FAULT_TYPES):
                    for i in range(max(1, args.repeat)):
                        # 同一 seed 重复 → 同一 receipt_digest (可重放性 CLI 实证)
                        result, (jp, _mp) = run_fixture(case_id, arm, fault,
                                                        outdir=outdir,
                                                        seed=args.seed,
                                                        label_suffix=f"-r{i}")
                        print(f"trial {result['case_id']} arm={arm} fault={fault} "
                              f"[{i}] {result['oracle']['overall']} digest="
                              f"{result['receipt_digest'][:12]} → {jp.name}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
