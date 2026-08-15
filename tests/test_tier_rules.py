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


# ---------- RED 1: VM/dynamic intent -> T3 ----------

def test_vm_execution_intent_is_t3():
    assert tier_for_claim(claim(statement="在 VM 中动态执行样本, 观察注入后的内存变化")) == 3


def test_x64dbg_runtime_trace_intent_is_t3():
    assert tier_for_claim(claim(statement="use x64dbg to trace the sample's runtime behavior on the VM")) == 3


def test_frida_injection_intent_is_t3():
    assert tier_for_claim(claim(statement="frida inject into the process and hook the decrypt function")) == 3


def test_chinese_dynamic_keywords_t3():
    assert tier_for_claim(claim(statement="验证样本运行时行为: 沙箱中执行, 调试挂钩点")) == 3


# ---------- RED 2: static-depth intent -> T2 ----------

def test_disassembly_intent_is_t2():
    assert tier_for_claim(claim(statement="反汇编入口函数, 分析调用链")) == 2


def test_decode_api_analysis_intent_is_t2():
    assert tier_for_claim(claim(statement="decode the embedded config and analyze the import table / API calls")) == 2


# ---------- RED 3: plain static / metadata -> T1 (default, conservative) ----------

def test_strings_scan_is_t1():
    assert tier_for_claim(claim(statement="扫描样本字符串与 PE 元数据")) == 1


def test_missing_intent_defaults_t1():
    assert tier_for_claim(claim()) == 1


def test_empty_claim_defaults_t1():
    assert tier_for_claim({}) == 1


# ---------- RED 4: no false escalation on ambiguous execution-flow wording ----------

def test_static_execution_flow_stays_low():
    # "执行流程" in a STATIC analysis context must not escalate to T3
    assert tier_for_claim(claim(statement="静态梳理主函数的执行流程与分支")) in (1, 2)
