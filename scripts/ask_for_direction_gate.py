# -*- coding: utf-8 -*-
"""ask_for_direction_gate.py - block orchestrator self-avoidance / asking-for-direction output.

User pain point (verbatim, in Chinese): "kunglao-agent 遇到问题不自己解决而是停下来询问或者反问"
("kunglao-agent, when hitting a problem, solves it itself instead of
stopping to ask or ask back")
- "刚才任务做完了，我要做下一个吗?" ("just finished the task — should I do
the next one?") (ask-back, violates section 9 rule 5)
- "Should I dispatch W-8 or wait?" (ask-back, violates section 6d.1)

This gate scans orchestrator output text for violation patterns:
  - Type A (BAD ask-back/question): "should I", "do you want", "what should I",
    "can you confirm", "please confirm", "confirm continuation",
    "let me know", "want me to", "等用户决定" ("wait for the user to decide")
  - Type B (BAD boundary): "just finished X, should I move to Y?" —
    completion = dispatch-next per priority.py, never ask
  - Type C (OK convergence sign-off): "C0-C7 all pass, confirm convergence" —
    legitimate per section 8 (only allowed after explicit convergence check)

Allowed only when kunglao-agent state indicates C0-C7 convergence reached.
Otherwise: REJECT (rc=1) + log "B1k orchestrator-self-redirect", force rewrite.

Usage:
  python ask_for_direction_gate.py <workspace> "<orchestrator_output_text>"
  cat orchestrator_output.txt | python ask_for_direction_gate.py <workspace>
Exit codes:
  0 = clean (no violation) OR Type C with convergence flag present
  1 = Type A/B violation detected (orchestrator must self-redirect)
  2 = HARD_PAUSE: 3+ self-redirects in this session (orchestrator must ask user)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SELF_REDIRECT_LOG = "self_redirects.jsonl"

# Type A: blatant ask-back/question phrases that should NEVER appear
TYPE_A_PATTERNS = [
    r"\bshould I\b",
    r"\bdo you want\b",
    r"\bdo you want me\b",
    r"\bwhat should I\b",
    r"\bcan you confirm\b",
    r"\bplease confirm\b",
    r"\bconfirm continuation\b",
    r"\blet me know\b",
    r"\bwant me to\b",
    r"\bplease advise\b",
    r"\bshall I\b",
    r"\b等用户决定\b",
    r"\b等待 direction\b",
]

# Type B: completion-then-ask pattern (also BAD)
TYPE_B_PATTERNS = [
    r"\bjust finished\b.*\bshould I\b",
    r"\bcompleted\b.*\bshould I\b",
    r"\bdone\b.*\bshould I\b",
    r"\b任务做完了\b.*\b要做下一个吗\b",
    r"\b刚完成\b.*\b接下来\b",
    r"任务做完了[\s\S]*?要做下一个吗",
]

# Type C: legitimate convergence sign-off request (only allowed near C0-C7)
TYPE_C_PATTERNS = [
    r"\bC0-C7\b.*\bconverge",
    r"\bconverge\b.*\bconfirm",
    r"\ball claims terminal\b.*\bconfirm",
]


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_violations(text: str) -> list:
    """Return list of (type, pattern, match) tuples for any violations found."""
    out = []
    for pat in TYPE_A_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append(("A", pat, m.group(0)))
    for pat in TYPE_B_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append(("B", pat, m.group(0)))
    return out


def find_convergence_signal(text: str) -> bool:
    """Return True if orchestrator output contains a Type C (convergence sign-off) signal."""
    for pat in TYPE_C_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def append_redirect(workspace: Path, text_excerpt: str, violation: str) -> int:
    """Append a self-redirect event; return count of events in last 1-hour window."""
    path = workspace / SELF_REDIRECT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    ev = {
        "ts": utc_now(),
        "violation": violation,
        "excerpt": text_excerpt[:200],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    if not path.exists():
        return 0
    one_hour_ago = datetime.now(tz=timezone.utc).timestamp() - 3600
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            t = datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if t >= one_hour_ago:
                n += 1
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
    return n


def check(workspace: Path, text: str) -> int:
    violations = find_violations(text)

    if violations and find_convergence_signal(text):
        print(f"OK: violations found but Type C convergence signal present; allowed")
        return 0

    if not violations:
        print("OK: no self-avoidance violations detected")
        return 0

    excerpt = text[:300].replace("\n", " ")
    print(f"REJECT: {len(violations)} self-avoidance violation(s) detected:")
    for vtype, pat, match in violations[:5]:
        print(f"  Type {vtype}: '{match}' (pattern: {pat})")
    print()
    print("ORCHESTRATOR MUST self-redirect (per section 9 rule 5 + section 6d.1):")
    print("  - DO NOT ask 'should I' / 'do you want' / 'can you confirm'")
    print("  - Just decide per the existing contract (priority.py, section 8, section 9)")
    print("  - On completion: dispatch next per priority.py (no question)")
    print("  - On C0-C7 all pass: convergence signal Type C is allowed")
    print()
    print(f"Excerpt: {excerpt}")
    n_redirects = append_redirect(workspace, excerpt, violations[0][1])
    if n_redirects >= 3:
        print()
        print(f"HARD_PAUSE: {n_redirects} self-redirects in last hour.")
        print("  Orchestrator has been re-redirected 3+ times.")
        print("  Per section 9 rule 5 (convergence check): user sign-off is REQUIRED.")
        print("  Emit Type C signal explicitly and ask user to confirm convergence.")
        return 2
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask-for-direction gate (orchestrator self-avoidance)")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("text", nargs="?", help="orchestrator output text (or pipe via stdin)")
    args = parser.parse_args()

    if args.text:
        text = args.text
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("NOOP: empty text")
        return 0

    return check(Path(args.workspace), text)


if __name__ == "__main__":
    sys.exit(main())