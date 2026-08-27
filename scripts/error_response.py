#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""error_response.py — 动作错误强制响应分类(issue #448,机械优先层)。

Single source of truth: references/error-response-taxonomy.md. 该模块是分类
表的承载层 — 命令行/vmrun/init exit code/签名匹配,文法可枚举。LLM 兜底
漏召回见 references/error-response-taxonomy.md"未分类"行。

Usage:
  uv run python scripts/error_response.py classify \\
    --kind vmrun --stderr "操作被取消/已取消"

  uv run python scripts/error_response.py classify \\
    --kind init-exit --exit-code 4

  # Library:
  from error_response import classify_stderr, classify_init_exit
  cls = classify_stderr("vmrun", "操作被取消...")
  print(cls)  # ErrorClass.CONFIG_CHANGE_REQUIRED

Exit codes (CLI):
  0 = classification returned
  1 = usage error
  2 = unclassified (LLM backstop recommended; per taxonomy policy ASK)

Output schema (JSON when --json):
  {
    "kind": "vmrun",
    "input": "操作被取消",
    "class": "CONFIG_CHANGE_REQUIRED",
    "response": "ASK",
    "charter_state": "must-ask",
    "rationale": "vmrun cancel signal — config change required (issue #448 table)",
    "allowed_actions": ["ask_user"],
    "forbidden_actions": ["change_config_silently", "retry", "try_alternate_method"]
  }
"""
from __future__ import annotations

import argparse
from typing import NamedTuple
import json
import re
import sys
from dataclasses import dataclass
from enum import Enum


class ErrorClass(str, Enum):
    HUMAN_EVENT_REFUSE = "HUMAN-EVENT-REFUSE"
    CONFIG_CHANGE_REQUIRED = "CONFIG-CHANGE-REQUIRED"
    IDENTITY_AMBIGUITY = "IDENTITY-AMBIGUITY"
    TRANSIENT_LOCK = "TRANSIENT-LOCK"
    TRANSIENT_TIMEOUT = "TRANSIENT-TIMEOUT"
    CHANNEL_FAILURE = "CHANNEL-FAILURE"
    PENDING_DECISIONS = "PENDING-DECISIONS"
    TOOL_INSTALL_HARD_FAIL = "TOOL-INSTALL-HARD-FAIL"
    UNCLASSIFIED = "UNCLASSIFIED"  # LLM backstop — default to ASK


class Response(str, Enum):
    STOP = "STOP"
    RETRY_ONCE = "RETRY-ONCE"
    ASK = "ASK"
    ESCALATE = "ESCALATE"


# Mechanical classification (signals are command/exit signatures, finite).
# Per doctrine (#447 + user correction "优先靠机械"): this is the load-bearing
# layer. LLM is backstop for UNCLASSIFIED.

# vmrun / vmware-cli signatures (Chinese + English). Commands have a finite
# grammar so enumeration is bounded.
_VMRUN_CANCEL_RE = re.compile(
    r"(操作被取消|已取消|已被取消|canceled|cancelled|operation\s+cancelled)",
    re.IGNORECASE,
)
_VMRUN_LOCK_RE = re.compile(
    r"(文件正在使用|正在使用中|被占用|in\s+use|locked|busy|file\s+is\s+locked)",
    re.IGNORECASE,
)
_VMRUN_TIMEOUT_RE = re.compile(
    r"(超时|timeout|connection\s+(?:reset|closed|refused)|timed\s+out)",
    re.IGNORECASE,
)
_VMRUN_CHANNEL_RE = re.compile(
    r"(通道挂死|channel\s+(?:hung|stuck|dead)|no\s+response\s+from\s+guest|"
    r"runProgramInGuest\s+(?:hang|timeout))",
    re.IGNORECASE,
)
_VMRUN_IDENTITY_RE = re.compile(
    r"(多个\s*(?:vm|VMs|vms)|multiple\s+(?:vm|VMs|vms)\s+matched)",
    re.IGNORECASE,
)

# init exit code -> ErrorClass. init exit codes are documented in
# scripts/kunglao-init.py:RC_* constants.
_INIT_EXIT_MAP = {
    3: ErrorClass.HUMAN_EVENT_REFUSE,    # RC_FLAG_REJECT (Phase 0 agent-teams flag)
    4: ErrorClass.HUMAN_EVENT_REFUSE,    # RC_TOOLCHAIN_REFUSE (human must install)
    7: ErrorClass.PENDING_DECISIONS,     # legacy (#455 schema) PENDING_DECISIONS
    8: ErrorClass.PENDING_DECISIONS,     # #455 RC_PENDING_DECISIONS
}

# toolchain_install degrade_report HARD item
_TOOL_INSTALL_HARD_RE = re.compile(
    r"(degraded.*HARD|HARD\s+(?:item|check).*?(?:failed|stays))",
    re.IGNORECASE,
)

# review-gate BLOCKED
_REVIEW_GATE_BLOCKED_RE = re.compile(
    r"REVIEW\s+GATE\s+BLOCKED|review[_-]gate[_\s]blocked",
    re.IGNORECASE,
)


class Classification(NamedTuple):
    """#581: collapsed from dataclass to NamedTuple view — same surface."""
    kind: str
    input: str
    klass: ErrorClass

    @property
    def response(self) -> Response:
        return _RESPONSE_MAP[self.klass]

    @property
    def charter_state(self) -> str:
        return _CHARTER_STATE[self.klass]

    @property
    def rationale(self) -> str:
        return _RATIONALE[self.klass]

    @property
    def allowed_actions(self) -> list[str]:
        return _ALLOWED[self.klass]

    @property
    def forbidden_actions(self) -> list[str]:
        return _FORBIDDEN[self.klass]


# Pure tables (single source — any change goes through #448 openspec):
#
# F-class decision-surface anchor (#446): the three-state vocabulary below
# is DERIVED from the charter, never invented here. Mutual lockstep is
# asserted mechanically by tests/test_decision_surface_anchor.py
# (charter executor table names this module back; symbolic anchors, no
# line numbers — #446 acceptance requires symbol references).
CHARTER_SOURCE = "references/agent-three-state-charter.md"
CHARTER_STATES = ("allowed", "must-ask", "must-stop")
_RESPONSE_MAP: dict[ErrorClass, Response] = {
    ErrorClass.HUMAN_EVENT_REFUSE: Response.STOP,
    ErrorClass.CONFIG_CHANGE_REQUIRED: Response.ASK,
    ErrorClass.IDENTITY_AMBIGUITY: Response.ASK,
    ErrorClass.TRANSIENT_LOCK: Response.RETRY_ONCE,
    ErrorClass.TRANSIENT_TIMEOUT: Response.RETRY_ONCE,
    ErrorClass.CHANNEL_FAILURE: Response.ESCALATE,
    ErrorClass.PENDING_DECISIONS: Response.ASK,
    ErrorClass.TOOL_INSTALL_HARD_FAIL: Response.STOP,
    ErrorClass.UNCLASSIFIED: Response.ASK,  # default safest
}
_CHARTER_STATE: dict[ErrorClass, str] = {
    ErrorClass.HUMAN_EVENT_REFUSE: "must-stop",
    ErrorClass.CONFIG_CHANGE_REQUIRED: "must-ask",
    ErrorClass.IDENTITY_AMBIGUITY: "must-ask",
    ErrorClass.TRANSIENT_LOCK: "allowed -> ask on second failure",
    ErrorClass.TRANSIENT_TIMEOUT: "allowed -> ask on second failure",
    ErrorClass.CHANNEL_FAILURE: "must-ask (escalate via Type D)",
    ErrorClass.PENDING_DECISIONS: "must-ask",
    ErrorClass.TOOL_INSTALL_HARD_FAIL: "must-stop",
    ErrorClass.UNCLASSIFIED: "must-ask (LLM backstop)",
}
_RATIONALE: dict[ErrorClass, str] = {
    ErrorClass.HUMAN_EVENT_REFUSE: (
        "review-gate BLOCKED / init exit 3-4 (issue #304): human-event "
        "refuse; agent MUST NOT proxy-repair. Hard priority over the "
        "'default allowed' rule — see taxonomy doc priority section."
    ),
    ErrorClass.CONFIG_CHANGE_REQUIRED: (
        "vmrun cancel / VPMC power-on failure: config change required "
        "(issue #448 T2); identity-ambiguity + config-change dual "
        "must-ask. Agent MUST NOT silently modify .vmx."
    ),
    ErrorClass.IDENTITY_AMBIGUITY: (
        "multiple VMs / toolchains matched (issue #448 evidence 2): "
        "identity must-ask per three-state charter."
    ),
    ErrorClass.TRANSIENT_LOCK: (
        "file-in-use / lock (issue #448 T3): one-shot retry then ask; "
        "agent MUST NOT delete the lock without confirmation."
    ),
    ErrorClass.TRANSIENT_TIMEOUT: (
        "network timeout / connection reset: one-shot retry then ask."
    ),
    ErrorClass.CHANNEL_FAILURE: (
        "guest channel hung / MCP bridge drop (issue #448 T4): "
        "escalate to channel-level failure; agent MUST NOT switch to "
        "alternate method (that's the documented anti-pattern)."
    ),
    ErrorClass.PENDING_DECISIONS: (
        "init exit 7/8 (pending decisions): the must-ask surface at "
        "intake; agent MUST ask, never self-resolve identity/scope."
    ),
    ErrorClass.TOOL_INSTALL_HARD_FAIL: (
        "toolchain_install HARD item stays FAIL (issue #408): agent "
        "MUST NOT degrade-and-continue."
    ),
    ErrorClass.UNCLASSIFIED: (
        "no mechanical signal matched; LLM backstop recommended. "
        "Default to ASK (safest) — never silently continue."
    ),
}
_ALLOWED: dict[ErrorClass, list[str]] = {
    ErrorClass.HUMAN_EVENT_REFUSE: ["stop_path", "report_to_human"],
    ErrorClass.CONFIG_CHANGE_REQUIRED: ["ask_user"],
    ErrorClass.IDENTITY_AMBIGUITY: ["ask_user"],
    ErrorClass.TRANSIENT_LOCK: ["retry_same_method_once", "ask_user_on_2nd_failure"],
    ErrorClass.TRANSIENT_TIMEOUT: ["retry_same_method_once", "ask_user_on_2nd_failure"],
    ErrorClass.CHANNEL_FAILURE: ["escalate_channel_failure", "stop_work_dependent_on_channel"],
    ErrorClass.PENDING_DECISIONS: ["ask_user"],
    ErrorClass.TOOL_INSTALL_HARD_FAIL: ["stop_path", "report_install_instructions"],
    ErrorClass.UNCLASSIFIED: ["ask_user"],
}
_FORBIDDEN: dict[ErrorClass, list[str]] = {
    ErrorClass.HUMAN_EVENT_REFUSE: ["proxy_repair", "continue_silently", "try_alternate_method"],
    ErrorClass.CONFIG_CHANGE_REQUIRED: ["change_config_silently", "retry", "try_alternate_method"],
    ErrorClass.IDENTITY_AMBIGUITY: ["self_select", "self_continue"],
    ErrorClass.TRANSIENT_LOCK: ["delete_lock", "change_config_silently", "retry_more_than_once"],
    ErrorClass.TRANSIENT_TIMEOUT: ["change_method", "retry_more_than_once"],
    ErrorClass.CHANNEL_FAILURE: ["switch_tool", "switch_script", "pretend_channel_ok"],
    ErrorClass.PENDING_DECISIONS: ["self_select_defaults", "skip_decision"],
    ErrorClass.TOOL_INSTALL_HARD_FAIL: ["degrade_and_continue", "mark_pass_silently"],
    ErrorClass.UNCLASSIFIED: ["continue_silently", "try_alternate_method", "self_resolve"],
}


def classify_vmrun(stderr: str) -> Classification:
    """Classify a vmrun / vmware-cli stderr line.

    English-only + Chinese-command-grammar signatures. vmrun's CLI grammar
    is finite (a handful of cancel / lock / timeout / channel phrases) so
    enumeration IS bounded — this is the kind of place regex works."""
    text = stderr or ""
    if _REVIEW_GATE_BLOCKED_RE.search(text):
        return Classification("vmrun", text, ErrorClass.HUMAN_EVENT_REFUSE)
    if _VMRUN_CHANNEL_RE.search(text):
        return Classification("vmrun", text, ErrorClass.CHANNEL_FAILURE)
    if _VMRUN_IDENTITY_RE.search(text):
        return Classification("vmrun", text, ErrorClass.IDENTITY_AMBIGUITY)
    if _VMRUN_CANCEL_RE.search(text):
        return Classification("vmrun", text, ErrorClass.CONFIG_CHANGE_REQUIRED)
    if _VMRUN_LOCK_RE.search(text):
        return Classification("vmrun", text, ErrorClass.TRANSIENT_LOCK)
    if _VMRUN_TIMEOUT_RE.search(text):
        return Classification("vmrun", text, ErrorClass.TRANSIENT_TIMEOUT)
    return Classification("vmrun", text, ErrorClass.UNCLASSIFIED)


def classify_init_exit(exit_code: int, stderr: str = "") -> Classification:
    """Classify a kick- exit code. The exit code is structured, so this
    is the cheapest signal — keys in _INIT_EXIT_MAP."""
    text = stderr or ""
    if exit_code in _INIT_EXIT_MAP:
        cls = _INIT_EXIT_MAP[exit_code]
        return Classification(f"init-exit:{exit_code}", text, cls)
    return Classification(f"init-exit:{exit_code}", text, ErrorClass.UNCLASSIFIED)


def classify_tool_install(stderr: str) -> Classification:
    text = stderr or ""
    if _TOOL_INSTALL_HARD_RE.search(text):
        return Classification("tool-install", text, ErrorClass.TOOL_INSTALL_HARD_FAIL)
    return Classification("tool-install", text, ErrorClass.UNCLASSIFIED)


def _classification_to_dict(c: Classification) -> dict:
    return {
        "kind": c.kind,
        "input": c.input,
        "class": c.klass.value,
        "response": c.response.value,
        "charter_state": c.charter_state,
        "rationale": c.rationale,
        "allowed_actions": list(c.allowed_actions),
        "forbidden_actions": list(c.forbidden_actions),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    cl = sub.add_parser("classify", help="classify a stderr/exit signature")
    cl.add_argument("--kind", choices=["vmrun", "init-exit", "tool-install"],
                    required=True)
    cl.add_argument("--stderr", default="")
    cl.add_argument("--exit-code", type=int, default=None)
    cl.add_argument("--json", action="store_true",
                    help="JSON output (default: human-readable)")
    args = p.parse_args(argv)

    if args.cmd == "classify":
        if args.kind == "vmrun":
            c = classify_vmrun(args.stderr)
        elif args.kind == "init-exit":
            c = classify_init_exit(
                args.exit_code if args.exit_code is not None else 0,
                args.stderr)
        elif args.kind == "tool-install":
            c = classify_tool_install(args.stderr)
        else:  # pragma: no cover
            print(f"unknown kind: {args.kind}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(_classification_to_dict(c), ensure_ascii=False))
        else:
            d = _classification_to_dict(c)
            for k, v in d.items():
                print(f"{k}: {v}")
        if c.klass is ErrorClass.UNCLASSIFIED:
            return 2  # LLM backstop recommended
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())