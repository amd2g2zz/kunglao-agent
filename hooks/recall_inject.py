#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recall_inject.py - PreToolUse runtime knowledge recall injection (#268).

WHY: the kunglao knowledge base (references/_INDEX.md + references_recall.py +
the re-library) was NEVER recalled at runtime — the hooks injected status /
gates / failures but 0 knowledge. Workers were dispatched for claims with no
idea that languages-go.md or tools-dynamic.md existed. This hook closes the
gap at the ONE point every claim enters the loop: the Agent dispatch.

Design (mirrors dispatch_gate / env_check_gate, inject-only):
  - PreToolUse hook on Agent. Reads the dispatch description from the tool
    input (prompt / description / task / input — the same shapes dispatch_gate
    accepts). Matches the dispatch format `[T<N> tools=...] claim C-NN`.
  - Claim features -> tier via scripts/tier_rules.tier_for_claim (single
    source for T3 VM/dynamic vs T2 static-depth signals), then -> recall
    queries: go signals -> "go" (languages-go.md); tier 3 -> "vm" + "dynamic"
    (dynamic-debugging scene / verify-static-vs-dynamic.md); tier 2 + default ->
    "static analysis" (disasm/static-analysis scene — "disasm" itself matches nothing
    in the index).
  - Each query runs `python scripts/references_recall.py <query>` as a
    subprocess (timeout 5s). FAIL_OPEN at every layer: any failure -> no
    injection, exit 0 pass-through — recall must NEVER block dispatch.
  - On a match it emits the hookSpecificOutput.additionalContext JSON shape
    (same as dispatch_gate.py:137-142 / env_check_gate main()) with a
    "Before dispatching, read: <files>" guidance. rc is ALWAYS 0: this hook
    injects knowledge, it never rejects.
  - Fires only in a kunglao workspace (claim-register.yaml present), so the
    globally-wired hook stays silent in unrelated projects. NO activation
    check: recall injection is knowledge, not enforcement — it helps whether
    or not the enforcement hooks are activated.

Wiring (in .claude/settings.json PreToolUse, Agent matcher — registered
idempotently by scripts/wire_up_settings.py alongside dispatch_gate):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/recall_inject.py"}]}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
RECALL_SCRIPT = SKILL_DIR / "scripts" / "references_recall.py"
RECALL_TIMEOUT = 5.0          # recall must never hold dispatch hostage
FILES_PER_QUERY = 3           # top hits only — guidance stays compact
# NOTE (#357): ranking below is token-overlap scoring, which is
# language-sensitive — translating a recall data source (references/_INDEX.md,
# references/_index-<domain>.md) shifts scores. Guarded by
# tests/test_recall_inject.py + tests/test_vm_claim_injects_recall_guidance.py
# (the recall-ranking pin); move data source and pin in the same commit.
MAX_FILES = 8                 # global cap across all queries

# dispatch_gate's exact claim-dispatch shape — mirror it so the hook fires on
# the same dispatches the other gates police.
DISPATCH_RE = re.compile(
    r"\[T\s*([123])\s+tools\s*=\s*([^\]]*)\]\s*claim\s+([A-Z]+-\d+)",
    re.IGNORECASE,
)

# Go-binary signals (tier_rules has no go signals — those live here). Substring
# matches; "go" alone is too noisy ("goal", "google", "cargo") so signals are
# compound or language-typed.
GO_SIGNALS = (
    "golang", "go binary", "go 二进制", "go 程序", "go 语言",
    "go runtime", "go symbol", "go function", "go 1.",
)

# tier_rules is the single source for T3/T2 feature detection (#241).
sys.path.insert(0, str(SKILL_DIR / "scripts"))
from tier_rules import tier_for_claim  # noqa: E402


def _resolve_workspace(payload: dict) -> Path | None:
    """Same resolution as dispatch_gate.py: cwd -> malware-analysis-workspace."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists():
            return base
    return None


def _dispatch_text(payload: dict) -> str | None:
    """Extract the dispatch description (prompt / description / task / input
    field; falls back to the first string value). Mirrors dispatch_gate."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("prompt", "description", "task", "input"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            return v
    for v in tool_input.values():
        if isinstance(v, str) and v.strip():
            return v
    return None


def queries_for_features(prompt_text: str, tier: int) -> list[str]:
    """Deterministic claim-feature -> recall query mapping (#268).

    go signals -> "go" (languages-go.md is the top hit); tier 3 (VM/dynamic
    intent, via tier_rules) -> "vm" + "dynamic" (dynamic-debugging scene +
    verify-static-vs-dynamic.md); tier 2 (static-depth/disasm) and the tier 1
    default -> "static analysis" (disasm/static-analysis scene — "disasm" itself
    matches nothing in the layered index).
    """
    text = prompt_text.lower()
    queries: list[str] = []
    if any(s in text for s in GO_SIGNALS):
        queries.append("go")
    if tier == 3:
        queries.extend(("vm", "dynamic"))
    else:
        queries.append("static analysis")
    return queries


def _parse_files(stdout: str) -> tuple[str, ...]:
    """File paths from references_recall.py stdout (scored and scene formats
    both print rows as `<path> | <category> | ...`; dedup, order-preserving)."""
    files: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if " | " not in line:
            continue
        candidate = line.split(" | ", 1)[0].strip()
        if candidate.endswith(".md") and candidate not in seen:
            seen.add(candidate)
            files.append(candidate)
    return tuple(files)


def _run_recall(query: str, cwd: Path | None = None) -> tuple[int, str]:
    """One recall query as a subprocess. Returns (rc, stdout). Any failure
    (missing script, timeout, unreadable index) -> (rc != 0, '')."""
    try:
        r = subprocess.run(
            [sys.executable, str(RECALL_SCRIPT), query],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(cwd) if cwd else None, timeout=RECALL_TIMEOUT,
        )
        return r.returncode, r.stdout or ""
    except Exception:  # noqa: BLE001 — recall must NEVER block dispatch
        return 1, ""


def recall_files(query: str, cwd: Path | None = None,
                 recall_runner=None) -> tuple[str, ...]:
    """Matched reference files for one query (empty on any failure). Public so
    siblings (failure_analysis_gate #268 item 3) reuse the same recall path."""
    runner = recall_runner if recall_runner is not None else _run_recall
    try:
        rc, stdout = runner(query)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at every layer
        return ()
    if rc != 0 or not stdout:
        return ()
    return _parse_files(stdout)


def _guidance(queries: list[str], files: list[str]) -> str:
    return (
        f"recall_inject: claim dispatch knowledge recall (#268) — "
        f"queries: {', '.join(queries)}\n"
        f"Before dispatching, read: {', '.join(files)}"
    )


def evaluate(payload: dict, recall_runner=None) -> tuple[int, str, str | None]:
    """Hook decision for a PreToolUse(Agent) claim-dispatch payload (#268).

    Returns (exit_code, stderr_text, additional_context_or_None):
      - (0, "", None) — not a kunglao workspace / not a claim dispatch /
        recall failed or matched nothing (FAIL_OPEN: dispatch proceeds)
      - (0, "", ctx)  — recall matched: guidance naming the reference files
    rc is ALWAYS 0 — this hook injects knowledge, never rejects.
    """
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0, "", None
    prompt_text = _dispatch_text(payload)
    if not prompt_text or not DISPATCH_RE.search(prompt_text):
        return 0, "", None  # not a claim dispatch — silent

    tier = tier_for_claim({"statement": prompt_text})
    queries = queries_for_features(prompt_text, tier)
    files: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for f in recall_files(query, cwd=ws, recall_runner=recall_runner)[:FILES_PER_QUERY]:
            if f not in seen:
                seen.add(f)
                files.append(f)
    if not files:
        return 0, "", None  # no knowledge to inject
    return 0, "", _guidance(queries, files[:MAX_FILES])


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    rc, stderr_text, context = evaluate(payload)
    if stderr_text:
        print(stderr_text, file=sys.stderr)
    if context:
        # mirror dispatch_gate.py:137-142 / env_check_gate main() — the model
        # receives the recall guidance before the dispatch is processed
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
