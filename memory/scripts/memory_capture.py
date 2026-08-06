"""F1 + F3 — Active capture hook + auto-distill trigger.

This hook is registered as PostToolUse on Edit|Write|Agent|MultiEdit. It:

  F1 (capture): when an event matches a known correction/failure/dispatch-reject
      pattern, write a staging entry to memory/staging/<date>-<tag>.md.
  F3 (auto-distill): after any staging write, check len(staging) >= 10;
      if so, invoke distill.py atomically.

Hook protocol: stdin = JSON payload from Claude Code. stdout/stderr per
the Claude Code hook contract.

Event sources:
  - tool_name=Edit / Write / MultiEdit + file path under SKILL.md
    -> orchestrator self-correction
  - tool_name=Agent + tool_result containing "blocked"/"error" status
    -> worker failure
  - tool_name=Agent + tool_result containing "REJECT" from worker_budget.py
    -> dispatch rejection (any of the 5 gates)

Capture pattern matching is intentionally conservative (high precision, may
miss some signals) — false positives pollute staging more than missed
signals hurt.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path(r"C:/Users/hr/.claude/skills/kunglao-agent/memory")
STAGING_DIR = MEMORY_DIR / "staging"
LONGTERM_DIR = MEMORY_DIR / "longterm"
DISTILL_SCRIPT = MEMORY_DIR / "scripts" / "distill.py"
THRESHOLD = 10

KONG_SKILL_PATH_RE = re.compile(r"\.claude[/\\]skills[/\\]kunglao-agent[/\\]", re.IGNORECASE)
WORKER_FAILURE_RE = re.compile(r"\b(blocked|error)\b\s*[:\s]", re.IGNORECASE)
DISPATCH_REJECT_RE = re.compile(r"\bREJECT\b", re.IGNORECASE)
SELF_CAP_RE = re.compile(r"\bself-cap detected\b", re.IGNORECASE)
PROVEN_INITIAL_RE = re.compile(r"\bconfidence_band\s*[:=]\s*PROVEN-INITIAL\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_date() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def classify_event(payload: dict) -> tuple | None:
    """Return (tag, context) if the event should be captured, else None."""
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    tool_result = payload.get("tool_result", "") or ""

    if tool_name in ("Edit", "Write", "MultiEdit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if KONG_SKILL_PATH_RE.search(str(file_path)):
            return "self-correction", {"file_path": file_path, "tool": tool_name}

    if tool_name == "Agent":
        result_str = str(tool_result)
        if DISPATCH_REJECT_RE.search(result_str):
            return "dispatch-reject", {"reason_match": DISPATCH_REJECT_RE.search(result_str).group(0)}
        if SELF_CAP_RE.search(result_str):
            return "self-cap", {"reason": "self-cap detected in dispatch"}
        if WORKER_FAILURE_RE.search(result_str):
            return "worker-failure", {"status": WORKER_FAILURE_RE.search(result_str).group(0)}
        if PROVEN_INITIAL_RE.search(result_str):
            return "proven-initial-misuse", {"reason": "PROVEN-INITIAL used as terminal"}

    return None


def write_staging_entry(tag: str, context: dict) -> Path:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{utc_date()}-{tag}-{datetime.now(tz=timezone.utc).strftime('%H%M%S')}"
    out = STAGING_DIR / f"{slug}.md"
    fm = (
        "---\n"
        f"name: {slug}\n"
        f"description: Auto-captured from PostToolUse hook ({tag})\n"
        "metadata:\n"
        "  node_type: memory\n"
        f"  type: {'failure' if tag in ('worker-failure', 'dispatch-reject', 'self-cap', 'proven-initial-misuse') else 'discovery'}\n"
        "  originSessionId: auto-capture\n"
        f"  modified: {utc_now()}\n"
        "  auto_source: posttooluse\n"
        f"  auto_tag: {tag}\n"
        "---\n"
    )
    body = (
        "## Symptom\n"
        f"Auto-captured from `{context.get('tool', 'unknown')}` tool result matching tag `{tag}`.\n"
        f"Context: `{json.dumps(context, ensure_ascii=False)}`\n\n"
        "## Repro\n"
        "(See raw hook payload in worker_status log; auto-captured.)\n\n"
        "## Fix applied\n"
        "(Pending - captured for human review before distill.)\n"
    )
    out.write_text(fm + body, encoding="utf-8")
    return out


def maybe_auto_distill() -> int:
    if not STAGING_DIR.exists():
        return 0
    entries = [p for p in STAGING_DIR.iterdir()
               if p.is_file() and p.name not in {"INDEX.md", ".distill.lock"}
               and not p.name.startswith(".snapshot")]
    if len(entries) < THRESHOLD:
        return 0
    proc = subprocess.run(
        ["python", str(DISTILL_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8"
    )
    print(proc.stdout, end="")
    print(proc.stderr, file=sys.stderr, end="")
    return proc.returncode


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    cls = classify_event(payload)
    if cls is None:
        return 0
    tag, context = cls
    path = write_staging_entry(tag, context)
    print(f"captured: {path.name} ({tag})")

    rc = maybe_auto_distill()
    return rc


if __name__ == "__main__":
    sys.exit(main())