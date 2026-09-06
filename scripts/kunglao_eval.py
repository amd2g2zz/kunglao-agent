#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_eval.py — eval harness module (issue #4, plan §7, design-spec §6.7.6).

Deterministic core: oracle 10/10 self-check (reported separately, not
merged into the capability score).
#81: executable, evaluator-owned L2 red-team evaluation — real bounded
episodes run on the injectable dispatcher/tool-adapter boundary (recorded
transcript; real tools/real samples never run), five fault-injection
classes that actually change the episode and capture state transitions,
an evaluator-controlled oracle scoring independently, and replayable
receipts (JSON + MD; same input → same receipt_digest).
CLI entry: scripts/kunglao-eval.py (thin wrapper).
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
          "desc": "all refactoring mechanisms on (priority_ratio VoI + gates + digest + verify)"},
    "B": {"mechanisms_enabled": False, "single_agent": False,
          "desc": "all-off baseline (legacy additive weights + no gate) — the control"},
    "C": {"mechanisms_enabled": False, "single_agent": True,
          "desc": "single agent, no orchestration (direct LLM run) — lower-bound control"},
    # #823 A5: AB-VALUE N-arm — the synthetic-shadow face of the value algo.
    # Since #51 the env switch is gone (the value algo is the only path);
    # the in-process harness honors mechanisms_enabled only.
    "N": {"mechanisms_enabled": True, "single_agent": False,
          "desc": "#823 N-arm: value algo P1-P3 (always-on since #51)"},
}

FAULT_TYPES = {
    "throttle": {"desc": "throttling: tool-call quota exhausted → the orchestrator must switch paths"},
    "implicit_fail": {"desc": "implicit failure: tool returns empty/error without raising → must be recognized as non-conclusive"},
    "explicit_fail": {"desc": "explicit failure: tool raises → needs failure_analysis, no re-dispatch"},
    "impossible": {"desc": "impossible: claim has no evidence path → must be excluded from top_actions"},
    "adversarial": {"desc": "adversarial: decoy strings/anti-analysis → must be recognized as neither benign nor a real IOC"},
}

# #81: arm → deterministic candidate policy
POLICY_NAMES = {"A": "voi", "B": "legacy", "C": "naive", "N": "voi"}
# fault injection blocks completion → non-completion is not a candidate-correctness error (INCONCLUSIVE, not FAIL)
FAULT_BLOCKING = ("throttle", "implicit_fail", "explicit_fail", "impossible")


def run_arm(arm: str) -> dict:
    if arm not in ARM_CONFIGS:
        raise ValueError(f"unknown arm: {arm}; valid: {list(ARM_CONFIGS)}")
    return ARM_CONFIGS[arm]


def inject_fault(ftype: str) -> dict:
    """Fault definition/verification functions. impossible is excluded via real priority_ratio verification (historical behavior).

    The other four fault classes, post-#81, must be injected inside a real
    episode (run_episode fault=...) — a standalone call returning a label
    is exactly the scaffold behavior #81 removed, so it fails loud.
    """
    if ftype not in FAULT_TYPES:
        raise ValueError(f"unknown fault type: {ftype}; valid: {list(FAULT_TYPES)}")
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

    # #107 Thompson rebuild: the known-answer cases now pin the candidate
    # filter, the deterministic Thompson sampling, the flip-potential
    # diagnostics and the #759 worth channel (the L/D/N terms are deleted
    # with the weighted formula — owner ruling "之前的不要了").
    out = pr.priority_ratio([_C("C-1", status="PROVEN"), _C("C-2")], {}, pr.EvidenceView())
    check("terminal_claim_excluded", [a.claim_id for a in out] == ["C-2"],
          f"got {[a.claim_id for a in out]}")

    out = pr.priority_ratio([_C("P"), _C("CHILD")],
                            {"depends_on": {"CHILD": ["P"]}}, pr.EvidenceView())
    check("dependency_gate_blocks_unproven_parent",
          [a.claim_id for a in out] == ["P"], f"got {[a.claim_id for a in out]}")

    out = pr.priority_ratio([_C("P"), _C("CHILD")],
                            {"depends_on": {"CHILD": ["P"]}},
                            pr.EvidenceView(terminal_fact_claims=frozenset({"P"})))
    check("dependency_gate_allows_terminal_fact_parent",
          {a.claim_id for a in out} == {"P", "CHILD"}, f"got {[a.claim_id for a in out]}")

    out = pr.priority_ratio([_C("OK"), _C("RETRY3", promotion_attempts=3)],
                            {}, pr.EvidenceView())
    check("attempts_cap_third_retry_excluded",
          [a.claim_id for a in out] == ["OK"], f"got {[a.claim_id for a in out]}")

    o1 = pr.priority_ratio([_C("A"), _C("B")], {}, pr.EvidenceView())
    o2 = pr.priority_ratio([_C("A"), _C("B")], {}, pr.EvidenceView())
    check("deterministic_pure",
          [a.to_dict() for a in o1] == [a.to_dict() for a in o2], "two runs differ")

    fp = o1[0].feeds.get("case_flip_potential", "")
    check("flip_potential_fallback_03", "0.3" in fp,
          f"feeds={o1[0].feeds}")

    dec = pr.priority_ratio([_C("DECAYED", promotion_attempts=2)], {}, pr.EvidenceView())[0]
    check("flip_potential_decays_with_attempts",
          "P(flip)=0.167" in dec.feeds.get("case_flip_potential", ""),
          f"feeds={dec.feeds}")

    cheap = pr.priority_ratio([_C("CHEAP", evidence_tier_attempted=0),
                               _C("DEEP", evidence_tier_attempted=2)], {}, pr.EvidenceView())
    by = {a.claim_id: a for a in cheap}
    check("tier_cost_field_diagnostic", by["CHEAP"].cost < by["DEEP"].cost,
          f"CHEAP={by['CHEAP'].cost} DEEP={by['DEEP'].cost}")

    out = pr.priority_ratio([_C("IMP")], {"depends_on": {"IMP": ["MISSING"]}}, pr.EvidenceView())
    check("impossible_claim_excluded", len(out) == 0, f"got {len(out)} actions")

    worth = pr.priority_ratio([_C("RCE", statement="rce chain")], {}, pr.EvidenceView(
        value_class_weights={"rce": 4.0}))[0]
    plain = pr.priority_ratio([_C("RCE", statement="rce chain")], {}, pr.EvidenceView())[0]
    check("worth_weight_multiplier",
          worth.weight == 4.0 and worth.score == round(plain.score * 4.0, 6),
          f"worth={worth.score} plain={plain.score} weight={worth.weight}")

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
    """code digest = bytes of this module + the core modules the episode really calls."""
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
    """Tool-call budget (calls = call count, tokens = deterministic token estimate)."""
    max_calls: int
    max_tokens: int


@dataclass
class ToolResult:
    tool: str
    args: dict
    ok: bool
    payload: dict | None = None
    error: str | None = None
    empty: bool = False  # implicit-failure fingerprint: ok but no evidence (no exception)


class ToolError(Exception):
    """Explicit failure: exception raised by a tool call."""


class BudgetExhausted(ToolError):
    """throttle: budget exhausted."""


@dataclass
class DispatchResult:
    claim_id: str
    ok: bool
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None
    failed_kind: str = "none"  # none | implicit | explicit | budget


class ToolAdapter:
    """Tool boundary (product = MCP tools; #81 harness = recorded, real tools never run)."""

    def call(self, name: str, args: dict, recorded: ToolResult | None = None) -> ToolResult:
        raise NotImplementedError


class RecordedToolAdapter(ToolAdapter):
    """Deterministic recorded tool boundary: budget accounting + fault hooks;
    results come from the dispatcher's recorded transcript. Real
    tools/samples are never executed (host-safe)."""

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
            # tool "succeeded" but returned empty — no exception, no evidence (implicit-failure fingerprint)
            return ToolResult(name, args, ok=True, payload={"facts": []}, empty=True)
        return recorded if recorded is not None else ToolResult(
            name, args, ok=False, payload=None, error="no recorded result")


class Dispatcher:
    """Worker dispatch boundary (product = Agent tool dispatching subagents; #81 = recorded transcript)."""

    def dispatch(self, claim_id: str, task: dict | None = None) -> DispatchResult:
        raise NotImplementedError

    def __call__(self, claim_id: str, ws=None) -> tuple[str, list[str]]:
        """l2_redteam dispatcher shape: (verdict, gaps)."""
        raise NotImplementedError


class RecordedDispatcher(Dispatcher):
    """Replays the fixture's recorded transcript (per-claim tool script) → deterministic evidence.

    dispatch raising BudgetExhausted/ToolError → fault-classified result;
    the returned evidence is decided by the adapter-accounted transcript.
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
        except Exception as exc:  # injected failure
            return ("UNVERIFIED-WITH-GAP", [f"recorded dispatch failed: {exc}"])
        if d.ok and d.evidence:
            return ("CONFIRMED", [])
        if d.ok:
            return ("UNVERIFIED-WITH-GAP", ["recorded dispatch produced no evidence"])
        return ("UNVERIFIED-WITH-GAP", [d.error or "dispatch not ok"])


class EpisodeState:
    """In-memory episode state (fresh per trial — reset is real behavior, no shared mutable state)."""

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
        if cid in dispatched:  # no-repeat: a dispatched-but-unconcluded claim is not re-dispatched (premature/redundant guard)
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
    """legacy additive weights (control): no VoI, no dispatchability gate, no no-repeat."""
    best: str | None = None
    best_score = -1.0
    for c in state.claims.values():
        if not pr.is_open(c):
            continue
        cid = c["id"]
        out_deg = len((state.deps.get("depends_on", {}) or {}).get(cid, []) or [])
        score = (0.4 * out_deg + 0.3 * (1.0 / pr.action_cost(c))
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
    """Turn a dispatch result into a state transition; returning True means the episode should stop immediately."""
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
            # overclaiming candidate: treating an "empty result" as success → empty-evidence conclusion (scorer records an overclaim)
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
        concluded = True  # naive: any "successful" dispatch concludes
    if concluded:
        ids = [f.get("fact_id", f"fact-{i}") for i, f in enumerate(supporting)]
        state.conclude(cid, ids)
    return False


def _apply_fault_injection(case: dict, state: EpisodeState, transcript: dict,
                           fault: str | None, claim_order: list[str]) -> list[str]:
    """Actually inject the fault into the episode (state transitions observable, not a label).

    - impossible: inject an unsatisfiable parent on the first claim → real
      priority_ratio exclusion (fixtures whose claim already carries an
      unsatisfiable parent are not injected again)
    - adversarial: prepend a decoy fact (an unanchored strings hit) to the
      first claim's recorded transcript → the scorer treats it as a decoy
      (injected_facts)
    - throttle/implicit_fail/explicit_fail: triggered at call time by the
      adapter's budget/fault hooks
    Returns the list of injected fact ids (injected_facts).
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
    """Run one real bounded episode (deterministic, replayable).

    case:   the fixture's public case.json (claims/deps/evidence_seed/transcript/budget)
    arm:    A (VoI) / B (legacy) / C (naive) — same loop, only the policy differs
    fault:  one of the five fault classes, actually changing the episode (budget/tool behavior), not a label
    """
    if arm not in ARM_CONFIGS:
        raise ValueError(f"unknown arm: {arm}; valid: {list(ARM_CONFIGS)}")
    if fault is not None and fault not in FAULT_TYPES:
        raise ValueError(f"unknown fault: {fault}; valid: {list(FAULT_TYPES)}")
    if assessor not in ("anchored", "naive"):
        raise ValueError(f"unknown assessor: {assessor}; valid: anchored|naive")

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
        except Exception as exc:  # unexpected crash → explicit-failure handling
            dispatch = DispatchResult(cid, ok=False, evidence=[],
                                      error=f"dispatch crashed: {exc}", failed_kind="explicit")
        state.record_dispatch(cid, dispatch)
        if _apply_dispatch(state, cid, dispatch, assessor):
            break

    wall_ms = int((time.time() - started) * 1000)
    transcript = {"dispatches": state.dispatches, "tool_calls": adapter.calls}
    # #309: collect symbol/type recovery claims from symbol_recovery facts so
    # score_episode can add naming/type quality dimensions (additive — cases
    # without such facts carry empty dicts, unchanged receipt otherwise).
    recovered_symbols: dict[str, str] = {}
    recovered_types: dict[str, dict] = {}
    for facts in state.evidence.values():
        for f in facts or []:
            for k, v in (f.get("symbols") or {}).items():
                recovered_symbols[str(k)] = v
            for k, v in (f.get("types") or {}).items():
                recovered_types[str(k)] = dict(v) if isinstance(v, dict) else v
    result = {
        "schema": "kunglao-episode-result/1",
        "case_id": case.get("case_id", "?"),
        "arm": arm,
        "fault": fault,
        "policy": POLICY_NAMES[arm],
        "seed": seed,
        "assessor": assessor,
        "injected_facts": injected_facts,
        "recovered_symbols": recovered_symbols,
        "recovered_types": recovered_types,
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
    """Stable fields for receipt_digest: excludes wall_ms/timestamps/its own digest/nested time_ms
    → same input, same digest (replayable; wall time is recorded but not part of the digest)."""
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
    # no_action_available → impossible only when the fixture itself is
    # unsolvable (normal convergence of a solvable one / a decoy staying OPEN
    # does not count as impossible)
    if completion == "impossible" and ("no_action_available" in types
                                       or "impossible_dep_injected" in types):
        tax.add("impossible")
    if "adversarial_decoy_injected" in types:
        tax.add("adversarial")
    return sorted(tax)


def score_episode(case: dict, oracle: dict, result: dict) -> dict:
    """Evaluator-controlled oracle scoring (independent of the candidate; hidden oracle input)."""
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
    # injection observability: an injected fault must produce a state transition, otherwise the trial is not green (anti-scaffold-impersonation)
    fault_effects = {
        "throttle": "budget_exhausted" in types,
        "implicit_fail": bool({"implicit_fail_recognized", "implicit_fail_misread_as_success"} & types),
        "explicit_fail": "explicit_fail_deferred" in types,
        "impossible": "no_action_available" in types or "impossible_dep_injected" in types,
        "adversarial": "adversarial_decoy_injected" in types,
    }
    injection_observed = fault is None or fault_effects.get(fault, True)
    dims: dict = {}

    # correctness: per-claim status vs oracle; fault-blocked completion → exempted (not a candidate error)
    mismatches = []
    for cid, want in expected.items():
        got = final.get(cid, {}).get("status")
        if got != want and not (fault_blocked and want == "PROVEN" and got in ("OPEN", "DEFERRED")):
            mismatches.append(f"{cid}: want {want} got {got}")
    dims["correctness"] = {"pass": not mismatches,
                           "detail": "; ".join(mismatches) or "all claims match oracle"}

    # invalid / redundant work: re-dispatch after terminal / forced dispatch of a non-dispatchable claim
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

    # overclaims: empty-evidence conclusions / conclusions built on decoy facts
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

    # misses: without a fault, dispatchable claims the oracle expected PROVEN but left unconcluded
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

    # #309: naming/type recovery quality dimensions — present only when the
    # oracle carries expected_symbols/expected_types (backward compatible:
    # oracles without them keep the pre-change dimension set).
    if oracle.get("expected_symbols"):
        from recov_metrics import naming_dimension
        dims["naming_quality"] = naming_dimension(
            oracle["expected_symbols"], result.get("recovered_symbols", {}) or {})
    if oracle.get("expected_types"):
        from recov_metrics import type_dimension
        dims["type_quality"] = type_dimension(
            oracle["expected_types"], result.get("recovered_types", {}) or {})

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
    """L2 capability dimension using the real l2_redteam + an injected dispatcher (#81).

    NOT-RUN / UNKNOWN (invalid verdict) / injected failure / missing
    dispatcher = non-evidence, never a passing capability score.
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
    """capability receipt aggregation: episode dimensions + the L2 capability dimension (non-evidence → never green)."""
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
    """End-to-end: episode → oracle scoring → real l2_redteam (with injected recorded dispatcher)
    → capability receipt (JSON + MD) written to disk. label_suffix lets --repeat distinguish reruns of the same seed."""
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
                        # same seed repeated → same receipt_digest (CLI-level replayability proof)
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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
