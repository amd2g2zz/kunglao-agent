#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_specialist_contract_expansion.py — issue #494: the 7 specialist
contract spans must carry REAL contract substance, not the #492 minimal stub.

#492 landed the structural markers (Gate 6, devkit/agents_lint.py) plus a
2-4 line minimal block per agent — a lint placeholder, not a runtime
contract. #494 expands each span into the full 3-element contract
kunglao-worker already carries (12 plan + 6 status + 2 tool-reuse entries):
plan-first status file, #444 canonical liveness vocabulary + W-15 artifacts
declaration, and the #462 tool-discovery duty (pre-work checklist +
registered tool names + no self-invention).

Channel discipline (design.md D3): these tests do NOT enumerate prose
clauses. They pin (a) load-bearing tokens inside each structurally declared
span — the marker grammar itself stays Gate 6's job — and (b) that every
tool name a span advertises RESOLVES to a real toolshelf entry
(tools/_INDEX.yaml) or scripts/ CLI. Fabricated tool names are the
definition-layer twin of the #462 self-invention incident (#494 design D2).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVKIT_DIR = REPO_ROOT / "devkit"

sys.path.insert(0, str(DEVKIT_DIR))
import agents_lint as al  # noqa: E402  (devkit is not a package; sibling of test_agents_lint)

# The 7 specialists #494 expands. kunglao-worker is the TEMPLATE (already at
# 12+6+2) and is deliberately out of scope.
SPECIALISTS = (
    "ghidra-light",
    "go-symbols",
    "floss-filter",
    "pefile-signature",
    "verdict-scorer",
    "kunglao-init-worker",
    "kunglao-redteam",
)

# RE-domain specialists point their third discovery check at
# references/re-library/; the two non-RE roles (init / verdict) use the
# references/ root channel instead (design.md D3).
RE_SPECIALISTS = (
    "ghidra-light",
    "go-symbols",
    "floss-filter",
    "pefile-signature",
    "kunglao-redteam",
)

# One domain-language anchor per agent — the minimal pin for "each agent in
# its own domain language" (issue text), NOT a clause enumeration.
DOMAIN_PLAN_TOKENS = {
    "ghidra-light": "pseudo-C",
    "go-symbols": "unstrip",
    "floss-filter": "top-K",
    "pefile-signature": "Authenticode",
    "verdict-scorer": "primary_question",
    "kunglao-init-worker": "toolchain",
    "kunglao-redteam": "REFUTED",
}

# The canonical #444 liveness vocabulary (hooks/lib_kunglao.py
# WORKER_STATUS_MAP / event_taxonomy.WORKER_STATUS_MAP) — the only status
# tokens a worker-status file may carry; last token wins.
CANONICAL_STATUS_VOCAB = ("in-progress", "done", "blocked")

# M7 survivor pin (fault-inject R2, .review/FAULT-INJECT.md): checker-role
# spans must advertise NO maker write-paths. Positive token pins (#492/#494)
# cannot see a span that ADDS a forbidden clause — the injected "Efficiency
# shortcut" told the checker to append `verify_status: passes` to
# facts/F<NNN>.md and stamp the claim-register PROVEN itself, and 149 tests
# stayed green. This pins the negative space in the same
# structural-declaration channel: a checker's write roots are a finite
# closed set (`runs/`), so forbidding the complement is mechanically
# parseable — it does NOT enumerate natural-language prose clauses.
CHECKER_SPECIALISTS = ("kunglao-redteam",)
# kunglao-redteam is the only checker seat among the 7 (its own frontmatter:
# "RED-TEAM CHECKER ... You are the ATTACKER, not the endorser"). The other
# six are makers/init roles — verdict-scorer WRITES evidence/verdict.json
# (its BLIND checker is verdict-redteam, outside this suite's 7) — and
# legitimately carry non-runs/ write roots in their spans.

# Maker-side write targets a checker span must never declare as its own
# writes: the maker's fact file, the verification-stamp field, and the
# claim promotion the orchestrator owns (maker-checker §1b — a checker
# stamping PROVEN itself is exactly the self-verification the rule forbids).
FORBIDDEN_WRITE_TARGETS = ("facts/F", "verify_status", "PROVEN")

# Read references stay legal ("never READ facts/F<NNN>..." is a legitimate
# BLIND clause); write declarations do not. A line carrying one of these
# verbs is judged a write-declaration line (#494 R2 M7 fix contract).
_WRITE_VERB_RE = re.compile(r"\b(?:writ\w*|写入|updat\w*|set)\b", re.IGNORECASE)

# Rooted path literal: >=1 directory component + file-ish suffix. Slashless
# bare filenames carry no root (exempt); prose like "status/plan" or
# "canonical / W-15" has no suffix (not matched).
_PATH_TOKEN_RE = re.compile(
    r"(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-<>]+\.(?:md|py|ya?ml|json|txt)"
)

# The one non-runs/ rooted path a status span may legitimately reference:
# the #444 canonical parse point — positively required by
# test_canonical_parse_point_referenced, so this allowlist cannot rot
# silently (drop it there and the positive pin goes red first).
STATUS_SPAN_READ_ALLOWLIST = frozenset({"hooks/lib_kunglao.py"})

# The single canonical tool-name line every tool-discovery span carries.
# Names are backticked; the test resolves each against the real toolshelf.
TOOL_LINE_RE = re.compile(r"^\s*Registered domain tools[^\n]*?:\s*([^\n]+)$", re.M)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _span_text(agent: str, element: str) -> str:
    """Content between the element's marker and the next marker / EOF.

    Reuses the #492 lint's own span logic (_marker_spans + _COMMENT_RE) —
    zero second parse point; substance semantics identical to Gate 6
    (HTML-comment lines stripped before assertions).
    """
    path = REPO_ROOT / "agents" / f"{agent}.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    markers = al._marker_spans(lines)
    starts = [i for i, e in markers if e == element]
    assert starts, (
        f"{agent}.md missing <!-- contract: {element} --> — Gate 6's job to "
        f"flag; this suite assumes the #492 markers are present"
    )
    start = starts[0]
    later = [i for i, _ in markers if i > start]
    end = min(later) if later else len(lines)
    return "\n".join(al._COMMENT_RE.sub("", ln) for ln in lines[start + 1:end])


def _declared_tool_names(span: str) -> list[str]:
    m = TOOL_LINE_RE.search(span)
    assert m, (
        "tool-discovery span must carry one canonical line "
        "'Registered domain tools (...): `name`, `name`, ...'"
    )
    return _BACKTICK_RE.findall(m.group(1))


def _resolvable_tool_names() -> set[str]:
    """Every name a contract span may advertise: registered toolshelf
    (tools/_INDEX.yaml) plus real scripts/ + tools/ files. Anything else a
    span names is a fabricated tool reference and must fail the suite."""
    names: set[str] = set()
    index = yaml.safe_load(
        (REPO_ROOT / "tools" / "_INDEX.yaml").read_text(encoding="utf-8"))
    for tool in index["tools"]:
        names.add(tool["name"])
    names |= {p.name for p in (REPO_ROOT / "scripts").glob("*.py")}
    names |= {p.name for p in (REPO_ROOT / "tools").rglob("*.py")}
    return names


# ---- plan-to-execute span ------------------------------------------------

class TestPlanSpan:
    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_plan_lives_in_named_status_file(self, agent: str) -> None:
        span = _span_text(agent, "plan-to-execute")
        assert f"runs/worker-status-{agent}" in span, (
            f"{agent}: plan-to-execute span must name its plan's home "
            f"runs/worker-status-{agent}-<id>.md as the FIRST action "
            f"(issue #494 ①)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_plan_states_expected_artifacts_and_done_criterion(self, agent: str) -> None:
        span = _span_text(agent, "plan-to-execute").lower()
        keywords = ("plan", "expected", "done", DOMAIN_PLAN_TOKENS[agent].lower())
        for keyword in keywords:
            assert keyword in span, (
                f"{agent}: plan-to-execute span missing keyword {keyword!r} "
                f"(将做什么 / 预期产物 / 判定完成标准 + the agent's own "
                f"domain language — issue #494 ①)"
            )


# ---- status-sync span -----------------------------------------------------

class TestStatusSpan:
    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_status_file_named_and_append_only(self, agent: str) -> None:
        span = _span_text(agent, "status-sync")
        assert f"runs/worker-status-{agent}" in span, (
            f"{agent}: status-sync span must reference "
            f"runs/worker-status-{agent}-<id>.md (the #444 canonical scan "
            f"surface is runs/)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_canonical_444_vocabulary(self, agent: str) -> None:
        span = _span_text(agent, "status-sync")
        for token in CANONICAL_STATUS_VOCAB:
            assert token in span, (
                f"{agent}: status-sync span must commit to the #444 "
                f"canonical vocabulary token {token!r} (hooks/lib_kunglao.py "
                f"WORKER_STATUS_MAP — no other value is parsed)"
            )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_w15_artifacts_declaration(self, agent: str) -> None:
        span = _span_text(agent, "status-sync")
        assert "artifacts:" in span, (
            f"{agent}: status-sync span missing the W-15 artifacts "
            f"declaration duty (`status: done` line carries "
            f"`artifacts: <file list>`; scan_done_artifact_violations "
            f"re-verifies the paths exist)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_heartbeat_response_duty(self, agent: str) -> None:
        span = _span_text(agent, "status-sync").lower()
        assert "heartbeat" in span, (
            f"{agent}: status-sync span missing the heartbeat response duty "
            f"(reply to the orchestrator's ping immediately — never let "
            f"'working' be mistaken for 'stuck'; the stall watchdog is "
            f"time-based, `STUCK_MINUTES=20` without a status-file update)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_canonical_parse_point_referenced(self, agent: str) -> None:
        span = _span_text(agent, "status-sync")
        assert "lib_kunglao" in span, (
            f"{agent}: status-sync span must point at the #444 single "
            f"canonical parse point (hooks/lib_kunglao.py), not restate the "
            f"protocol"
        )


# ---- tool-discovery span ---------------------------------------------------

class TestToolSpan:
    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_prework_checklist(self, agent: str) -> None:
        span = _span_text(agent, "tool-discovery")
        assert "scripts/re" in span, (
            f"{agent}: tool-discovery span missing the workspace RE-tool "
            f"check (`ls scripts/re` — the #462 incident: 25+ tools "
            f"available, worker hand-wrote 385 lines anyway)"
        )
        assert "_INDEX.yaml" in span, (
            f"{agent}: tool-discovery span missing the toolshelf grep "
            f"(tools/_INDEX.yaml category/capability match)"
        )

    @pytest.mark.parametrize("agent", RE_SPECIALISTS)
    def test_re_library_domain_check(self, agent: str) -> None:
        span = _span_text(agent, "tool-discovery")
        assert "re-library" in span, (
            f"{agent}: RE specialist must check the matching "
            f"references/re-library/ domain file before acting"
        )

    @pytest.mark.parametrize("agent", ("kunglao-init-worker", "verdict-scorer"))
    def test_non_re_reference_channel(self, agent: str) -> None:
        span = _span_text(agent, "tool-discovery")
        assert "references/" in span, (
            f"{agent}: non-RE role must still name its reference channel "
            f"(references/ root — tool-inventory / methodology docs)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_no_self_invention_clause(self, agent: str) -> None:
        span = _span_text(agent, "tool-discovery").lower()
        assert "issue" in span, (
            f"{agent}: tool-discovery span missing the upstreaming rule "
            f"(missing tool = file an issue to upstream it into tools/)"
        )
        assert "shim" in span, (
            f"{agent}: tool-discovery span missing the one-off shim rule "
            f"(label disposable, drop after the run — #462 original text)"
        )

    @pytest.mark.parametrize("agent", SPECIALISTS)
    def test_tool_names_line_resolves(self, agent: str) -> None:
        span = _span_text(agent, "tool-discovery")
        names = _declared_tool_names(span)
        assert len(names) >= 3, (
            f"{agent}: tool-discovery span lists only {len(names)} domain "
            f"tool(s) — issue #494 ③ requires 3-5 real names"
        )
        resolvable = _resolvable_tool_names()
        unresolvable = [n for n in names if n not in resolvable]
        assert not unresolvable, (
            f"{agent}: contract advertises tool names that resolve to "
            f"nothing real (tools/_INDEX.yaml ∪ scripts/*.py): "
            f"{unresolvable} — fabricated names are the definition-layer "
            f"twin of the #462 self-invention incident"
        )


# ---- M7 survivor pin: checker BLIND write-path red-line --------------------

class TestCheckerBlindWritePathPins:
    """Negative pins for checker-role spans (fault-inject M7, #494 R2).

    The #492/#494 channel pins only POSITIVE tokens; nothing guarded the
    negative space, so a checker span could advertise maker write-paths
    (facts/F<NNN>.md, verify_status, self-stamped PROVEN) and no test
    noticed. Read references remain allowed — the prohibition is judged
    per line and fires only on write-declaration lines.
    """

    @pytest.mark.parametrize("agent", CHECKER_SPECIALISTS)
    @pytest.mark.parametrize(
        "element", ("plan-to-execute", "status-sync", "tool-discovery"))
    def test_no_maker_write_target_on_write_line(
            self, agent: str, element: str) -> None:
        span = _span_text(agent, element)
        for lineno, line in enumerate(span.splitlines(), 1):
            if not _WRITE_VERB_RE.search(line):
                continue  # read / negative references are legal BLIND clauses
            for target in FORBIDDEN_WRITE_TARGETS:
                assert target not in line, (
                    f"{agent}: {element} span line {lineno} declares writing "
                    f"maker-side target {target!r} — a checker writes only "
                    f"its own runs/ report; facts/F<NNN>.md, verify_status "
                    f"and the PROVEN stamp belong to the maker/orchestrator "
                    f"(BLIND + maker-checker §1b red-line, M7 survivor)"
                )

    @pytest.mark.parametrize("agent", CHECKER_SPECIALISTS)
    def test_status_span_write_paths_closed_set(self, agent: str) -> None:
        span = _span_text(agent, "status-sync")
        rooted = set(_PATH_TOKEN_RE.findall(span))
        bad = sorted(
            t for t in rooted
            if not t.startswith("runs/") and t not in STATUS_SPAN_READ_ALLOWLIST
        )
        assert not bad, (
            f"{agent}: status-sync span carries path literal(s) outside the "
            f"checker's closed write set (runs/ + the canonical parse "
            f"point): {bad} — a checker's only writes are its own runs/ "
            f"files; no positive pin notices an ADDED write path (M7)"
        )
