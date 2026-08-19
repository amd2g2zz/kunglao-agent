# -*- coding: utf-8 -*-
"""ask_for_direction_gate.py — orchestrator self-avoidance + 3-state charter enforcement (#447).

User pain point (English summary): when hitting a problem, the orchestrator
should solve it itself instead of stopping to ask the user. Examples:
- "Should I dispatch W-8 or wait?" (ask-back, violates section 6d.1)

#447 Three-state charter — THIS gate is one of three execution surfaces
(see references/agent-three-state-charter.md):
  - Type A (BAD ask-back/question): "should I", "do you want", "what should I",
    "can you confirm", "please confirm", "confirm continuation",
    "let me know", "want me to"
  - Type B (BAD boundary): "just finished X, should I move to Y?" —
    completion = dispatch-next per priority.py, never ask
  - Type C (OK convergence sign-off): "C0-C7 all pass, confirm convergence" —
    legitimate per section 8 (only allowed after explicit convergence check)
  - Type D (must-ask, #447 NEW): identity ambiguity / authorization boundary /
    scope change — MUST HARD_PAUSE for user confirmation
  - Type S (must-stop, #447 NEW): irreversible action (delete VM / push --force
    / public release) — MUST HARD_PAUSE + block

Allowed only when kunglao-agent state indicates C0-C7 convergence reached.
Otherwise: REJECT (rc=1) + log "B1k orchestrator-self-redirect", force rewrite.
Type D / Type S → HARD_PAUSE (rc=2) regardless of state.

Declaration over inference (#447 doctrine): prose patterns here are
TRIPWIRES, never load-bearing. Natural-language enumeration is unfinishable
in any language; the load-bearing must-stop enforcement is structural and
language-free — the v1 dispatch protocol `"reversible": false` field (the
agent declares it) and command grammar in hooks/dispatch_gate.py
(vmrun delete / git push --force are commands, a finite grammar). Tripwire
lists cover the languages sessions actually produce (zh + en here) and are
explicitly non-exhaustive.

Usage:
  python ask_for_direction_gate.py <workspace> "<orchestrator_output_text>"
  cat orchestrator_output.txt | python ask_for_direction_gate.py <workspace>
Exit codes:
  0 = clean (no violation) OR Type C with convergence flag present
  1 = Type A/B violation detected (orchestrator must self-redirect)
  2 = HARD_PAUSE: Type D (must-ask) OR Type S (must-stop) OR 3+ self-redirects
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SELF_REDIRECT_LOG = "self_redirects.jsonl"

# ---------------------------------------------------------------------------
# #447 doctrine — declaration over inference.
#
# These prose pattern lists are TRIPWIRES, not enforcement. Natural-language
# enumeration is unfinishable in ANY language (English no less than Chinese),
# so nothing load-bearing may depend on these lists. The load-bearing
# enforcement for must-ask / must-stop is structural and language-free:
#   - v1 dispatch protocol field `"reversible": false` (agent DECLARES it)
#   - command grammar (vmrun delete / git push --force — commands, not prose;
#     a finite grammar IS enumerable) in hooks/dispatch_gate.py
#   - structured state (claim-register / decision_pending / .hook_state.json)
#
# Because these are tripwires, they cover the languages sessions actually
# produce — this project's sessions are Chinese + English mixed, so both are
# listed. The lists are explicitly NON-EXHAUSTIVE; extending them is routine,
# never a contract change.
# ---------------------------------------------------------------------------

# Type A: blatant ask-back/question phrases that should NEVER appear.
TYPE_A_PATTERNS = [
    # English
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
    # Chinese (tripwire; non-exhaustive). No \b anchors — CJK chars are all
    # \w, so a boundary only exists at punctuation/edges and mid-sentence
    # phrases would never match.
    r"等用户决定",
    r"等待 direction",
    r"要我.{0,12}吗",
    r"是否继续",
]

# Type B: completion-then-ask pattern (also BAD).
TYPE_B_PATTERNS = [
    # English
    r"\bjust finished\b.*\bshould I\b",
    r"\bcompleted\b.*\bshould I\b",
    r"\bdone\b.*\bshould I\b",
    # Chinese (tripwire; non-exhaustive; no \b anchors, see above)
    r"任务做完了[\s\S]{0,20}要做下一个吗",
    r"刚完成[\s\S]{0,20}接下来",
]

# Type C: legitimate convergence sign-off request (only allowed near C0-C7)
TYPE_C_PATTERNS = [
    r"\bC0-C7\b.*\bconverge",
    r"\bconverge\b.*\bconfirm",
    r"\ball claims terminal\b.*\bconfirm",
]

# #447 Type D (must-ask): identity ambiguity / authorization boundary / scope
# change. MUST trigger HARD_PAUSE (rc=2) — orchestrator cannot self-resolve.
# Single source: references/agent-three-state-charter.md. Tripwire layer (non-exhaustive);
# load-bearing equivalents are structural (see doctrine note above).
TYPE_D_PATTERNS = [
    # identity ambiguity
    r"\bmultiple\s+(?:vm|VMs|vms|toolchain|toolchains)\s+(?:found|discovered|matched)\b",
    r"\bidentity\s+ambigu(?:ity|ous)\b",
    # authorization boundary
    r"\b(?:out[-\s]?of[-\s]?scope|not\s+in\s+original\s+scope)\b",
    r"\b(?:scope\s+change|scope\s+expansion|task\s+boundary\s+expansion)\b",
    r"\b(?:new\s+hard\s+error|new\s+blocker|encountered\s+blocker)\b",
    # scope change
    r"\bnot\s+covered\s+by\s+the\s+task\b",
]

# #447 Type S (must-stop): irreversible action. MUST HARD_PAUSE + block.
TYPE_S_PATTERNS = [
    # VM / snapshot destruction
    r"\b(?:rm|delete|remove|destroy)\s+(?:vm|VM|vmx|snapshot)\b",
    r"\b(?:snapshot\s+delete|snapshot\s+revert|vmrun\s+delete)\b",
    # destructive git
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fd\b",
    # public publish
    r"\b(?:public\s+publish|public\s+release|publish\s+to\s+pypi|publish\s+to\s+npm)\b",
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


def find_must_ask_signals(text: str) -> list:
    """#447 Type D: events that MUST trigger HARD_PAUSE (must-ask).

    Per references/agent-three-state-charter.md: identity ambiguity / authorization
    boundary / scope change. Returns list of (pattern, match) tuples."""
    out = []
    for pat in TYPE_D_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append((pat, m.group(0)))
    return out


def find_must_stop_signals(text: str) -> list:
    """#447 Type S: events that MUST trigger HARD_PAUSE + block (must-stop).

    Per references/agent-three-state-charter.md: irreversible action (VM destroy /
    git --force / public publish / etc.). Returns list of (pattern, match)."""
    out = []
    for pat in TYPE_S_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append((pat, m.group(0)))
    return out


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
    # #447 Type S (must-stop) takes precedence over everything — irreversible
    # actions MUST HARD_PAUSE regardless of any other state.
    must_stop = find_must_stop_signals(text)
    if must_stop:
        excerpt = text[:300].replace("\n", " ")
        print(f"HARD_PAUSE Type S (must-stop, #447): {len(must_stop)} irreversible-action signal(s):")
        for pat, match in must_stop[:5]:
            print(f"  '{match}' (pattern: {pat})")
        print()
        print("Per references/agent-three-state-charter.md, irreversible actions MUST be")
        print("explicitly approved by the user. The orchestrator MUST NOT proceed")
        print("without confirmation. Refusing to continue.")
        print()
        print(f"Excerpt: {excerpt}")
        append_redirect(workspace, excerpt, "must-stop:" + must_stop[0][1])
        return 2

    # #447 Type D (must-ask) also HARD_PAUSE — identity ambiguity / scope change.
    must_ask = find_must_ask_signals(text)
    if must_ask:
        excerpt = text[:300].replace("\n", " ")
        print(f"HARD_PAUSE Type D (must-ask, #447): {len(must_ask)} ambiguity / scope signal(s):")
        for pat, match in must_ask[:5]:
            print(f"  '{match}' (pattern: {pat})")
        print()
        print("Per references/agent-three-state-charter.md, these events MUST be confirmed")
        print("by the user. The orchestrator MUST NOT self-resolve identity /")
        print("scope / authorization questions.")
        print()
        print(f"Excerpt: {excerpt}")
        append_redirect(workspace, excerpt, "must-ask:" + must_ask[0][1])
        return 2

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
    print("  - Just decide per the existing contract (priority_ratio.py, section 8, section 9)")
    print("  - On completion: dispatch next per priority_ratio.py (no question)")
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