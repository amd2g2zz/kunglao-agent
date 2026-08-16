# -*- coding: utf-8 -*-
"""TDD RED — issue #241: mechanical tier assignment (tier_rules).

worker_budget.check_tier_gate() enforces that a dispatch tier requires open
claims at evidence_tier_attempted >= tier-1 — but NOTHING decides what tier a
claim SHOULD be worked at. The C-012 incident: a claim whose verification
intent was dynamic (run the sample in the VM) got DEFERRED "waiting for
authorization" instead of dispatched as T3, because tier judgment had no
mechanical standard.

tier_for_claim(claim: dict) -> int:
  - VM / dynamic / execution / injection / runtime verification intent -> T3
  - static-depth analysis (disassembly / decoding / API analysis)      -> T2
  - everything else                                                     -> T1
Rules are deliberately conservative (better low than high): a miss costs one cheap static
pass; an over-assignment costs a full VM cycle.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from tier_rules import tier_for_claim  # noqa: E402


def claim(**overrides) -> dict:
    c = {
        "id": "C-001",
        "statement": "determine the sample's network behavior",
        "boundary_type": "observation",
    }
    c.update(overrides)
    return c


# ---------- RED 1-3: intent -> tier mapping table ----------

# (statement, expected_tier): VM/dynamic -> 3, static-depth -> 2, plain -> 1.
INTENT_TIERS = [
    ("在 VM 中动态执行样本, 观察注入后的内存变化", 3),
    ("use x64dbg to trace the sample's runtime behavior on the VM", 3),
    ("frida inject into the process and hook the decrypt function", 3),
    ("验证样本运行时行为: 沙箱中执行, 调试挂钩点", 3),
    ("反汇编入口函数, 分析调用链", 2),
    ("decode the embedded config and analyze the import table / API calls", 2),
    ("扫描样本字符串与 PE 元数据", 1),
]


def test_intent_maps_to_tier():
    for statement, expected in INTENT_TIERS:
        assert tier_for_claim(claim(statement=statement)) == expected, statement


def test_missing_intent_defaults_t1():
    assert tier_for_claim(claim()) == 1


def test_empty_claim_defaults_t1():
    assert tier_for_claim({}) == 1


# ---------- RED 4: no false escalation on ambiguous execution-flow wording ----------

def test_static_execution_flow_stays_low():
    # "执行流程" in a STATIC analysis context must not escalate to T3
    assert tier_for_claim(claim(statement="静态梳理主函数的执行流程与分支")) in (1, 2)
