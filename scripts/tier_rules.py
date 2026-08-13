# -*- coding: utf-8 -*-
"""tier_rules.py — mechanical tier assignment from claim features (#241).

worker_budget.check_tier_gate() enforces that a dispatch tier needs open
claims at evidence_tier_attempted >= tier-1 — but NOTHING decides what tier a
claim SHOULD be worked at. C-012 case: a claim whose verification intent was
dynamic (run the sample in the VM) got DEFERRED "waiting for authorization"
instead of dispatched T3, because tier judgment had no mechanical standard.

tier_for_claim(claim: dict) -> int
  - T3: VM / dynamic / execution / injection / runtime verification intent
  - T2: static-depth analysis (disassembly / decoding / API analysis)
  - T1: everything else (default — strings/metadata scans stay T1)

Conservative by design (宁低勿高): a miss costs one cheap static pass; an
over-assignment costs a full VM cycle. Signals are substring matches on the
claim's intent text (statement / verification_intent / promotion_gate /
boundary_type / summary / task).

Consumer note: this rule (what tier a claim SHOULD be worked at) and
worker_budget.check_tier_gate (attempt-history gate: evidence_tier_attempted
>= tier-1) are complementary axes. Wiring tier_for_claim into dispatch gating
is deferred to the follow-up that touches worker_budget — #241 delivers the
rule + tests.
"""
from __future__ import annotations

# Strong signals: the claim REQUIRES running/observing the sample (VM is the
# only place execution is allowed, per workspace constraints). Bare
# "execute"/"执行" is deliberately NOT here — "静态梳理执行流程" is static
# control-flow analysis and must not escalate to a VM cycle.
T3_SIGNALS = (
    # english — tool / runtime / dynamic intent
    "x64dbg", "frida", "debugger", "breakpoint", "attach", " vm",
    "inject", "injection", "runtime", "dynamic", "sandbox",
    "trace", "dump", "hook", "run the sample", "sample execution",
    "execute the sample", "executing the sample", "emulat",
    # chinese — 动态执行/注入/调试/沙箱/转储/挂钩/执行链
    "动态", "运行", "注入", "调试", "沙箱", "转储", "挂钩", "执行链",
)

# Static-depth signals: analysis performed on the artifact without executing
# it. Present only upgrades to T2 — never to T3. Plain strings/metadata
# scans (floss, die, pefile basics) stay T1 per the workspace tier contract.
T2_SIGNALS = (
    "反汇编", "反编译", "解码", "解密", "pe结构", "pe 结构",
    "disassemble", "decompile", "decode", "decrypt",
    "import table", "iat", "api analysis", "api call", "api 分析", "api 调用",
    "导出表",
)

_CLAIM_TEXT_KEYS = (
    "statement", "verification_intent", "promotion_gate",
    "boundary_type", "summary", "task",
)


def _claim_text(claim: dict) -> str:
    """Concatenated intent text of the claim (lowercased for EN matching;
    Chinese is case-insensitive by nature)."""
    parts: list[str] = []
    for key in _CLAIM_TEXT_KEYS:
        v = claim.get(key) if isinstance(claim, dict) else None
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
    return " ".join(parts).lower()


def tier_for_claim(claim: dict) -> int:
    """Conservative claim-feature -> tier mapping.

    T3 only on strong dynamic/VM signals; T2 on static-depth signals; T1
    otherwise (when unsure, prefer the cheap tier).
    """
    if not isinstance(claim, dict):
        return 1
    text = _claim_text(claim)
    if any(s in text for s in T3_SIGNALS):
        return 3
    if any(s in text for s in T2_SIGNALS):
        return 2
    return 1
