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
  - Type D (must-ask, #447): identity ambiguity / authorization boundary /
    scope change — MUST HARD_PAUSE for user confirmation
  - Type S (must-stop, #447): irreversible action (delete VM / push --force
    / public release) — MUST HARD_PAUSE + block

#497 Decision grammar v2 — TWO fixes on top (see references/
agent-three-state-charter.md "变更记录"):
  - charter calibration: an in-authorization-boundary new hard error
    (the `new blocker|encountered blocker` tripwire) is ALLOWED + forced
    onto the ladder, NOT must-ask — must-ask deadlocks hard-prohibition #1
    (never ask mid-iteration) and the only win-win exit was rewording the
    blocker as a death verdict that silenced BOTH gates. Only
    tools/resources EXHAUSTED (ladder climbed — #495 failure_analysis
    record with empty candidates on a claim with promotion_attempts >= 3)
    stays must-ask (HARD_PAUSE rc=2); otherwise rc=1 with climb-the-ladder
    guidance.
  - declarative-sentence gates: v0.1.1's two recurring misbehaviours were
    NOT questions, so the interrogative layer never saw them:
      * Type E (death declaration): "这条路走不通" / "dead end" / "cannot
        proceed" — rejected (rc=1, forced ladder re-eval) unless backed by
        structured evidence (obstacle claim REFUTED per #495, or a
        failure_analysis outcome REFUTED = capability falsified);
      * plan-stall (Type B equivalent): "下一步:" / "next step:" declaration
        with no subsequent tool action in the self_redirects event stream —
        rc=1, "execute the declared step or declare the blocker".

Allowed only when kunglao-agent state indicates C0-C7 convergence reached.
Otherwise: REJECT (rc=1) + log "B1k orchestrator-self-redirect", force rewrite.
Type D / Type S → HARD_PAUSE (rc=2) regardless of state.

#459 observability: every INTERCEPTION (rc 1/2) mirrors one event to the
unified log (kunglao_log.emit; action words ask_back / must_stop / must_ask /
ladder_required / death_verdict_rejected / plan_stall — all registered in
event_taxonomy.EMIT_ACTIONS; exit carries the rc). Fail-open: a log write
failure never changes the verdict. Clean passes emit nothing (zero noise).

Declaration over inference (#447 doctrine): prose patterns here are
TRIPWIRES, never load-bearing. Natural-language enumeration is unfinishable
in any language; the load-bearing must-stop enforcement is structural and
language-free — the v1 dispatch protocol `"reversible": false` field (the
agent declares it) and command grammar in hooks/dispatch_gate.py
(vmrun delete / git push --force are commands, a finite grammar). Tripwire
lists cover the languages sessions actually produce (zh + en here) and are
explicitly non-exhaustive. The #497 additions follow the same doctrine:
the death/blocker verdicts are tripwires, the LADDER-EXHAUSTION and
DEATH-EVIDENCE preconditions are structural (#495 fields on disk).

Usage:
  python ask_for_direction_gate.py <workspace> "<orchestrator_output_text>"
  cat orchestrator_output.txt | python ask_for_direction_gate.py <workspace>
Exit codes:
  0 = clean (no violation) OR Type C with convergence flag present
  1 = Type A/B violation OR #497 downgrade (ladder-required blocker /
      unevidenced death verdict / plan-stall) — orchestrator must self-redirect
  2 = HARD_PAUSE: Type D (must-ask) OR Type S (must-stop) OR 3+ self-redirects
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

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

# #447 Type D (must-ask): identity ambiguity / scope change. MUST trigger
# HARD_PAUSE (rc=2) — orchestrator cannot self-resolve.
# Single source: references/agent-three-state-charter.md. Tripwire layer (non-exhaustive);
# load-bearing equivalents are structural (see doctrine note above).
TYPE_D_PATTERNS = [
    # identity ambiguity
    r"\bmultiple\s+(?:vm|VMs|vms|toolchain|toolchains)\s+(?:found|discovered|matched)\b",
    r"\bidentity\s+ambigu(?:ity|ous)\b",
    # authorization boundary (scope wording only — the new-hard-error family
    # moved to TYPE_D_BLOCKER_PATTERNS per #497 charter v2)
    r"\b(?:out[-\s]?of[-\s]?scope|not\s+in\s+original\s+scope)\b",
    r"\b(?:scope\s+change|scope\s+expansion|task\s+boundary\s+expansion)\b",
    # scope change
    r"\bnot\s+covered\s+by\s+the\s+task\b",
]

# #497 charter v2: in-authorization-boundary new hard errors are ALLOWED +
# forced onto the ladder (method-ladder / env-ladder), NOT must-ask — the
# pre-v2 routing deadlocked hard-prohibition #1 and made rewording a blocker
# into a death verdict the only quiet exit. HARD_PAUSE survives ONLY with a
# ladder-exhaustion marker on disk (find_ladder_exhaustion, #495 fields);
# otherwise this degrades to rc=1 climb-the-ladder guidance.
TYPE_D_BLOCKER_PATTERNS = [
    r"\b(?:new\s+hard\s+error|new\s+blocker|encountered\s+blocker)\b",
]

# #497 Type E (death declaration, declarative-sentence gate): a death
# verdict is the grammar that silently killed v0.1.1 trajectory 1 — it asks
# no question, so neither the ask-back gate nor the must-ask gate fired.
# Legal terminal ONLY with structured evidence (find_death_evidence);
# otherwise rc=1 = forced ladder re-eval, never a terminal.
# Tripwire layer (zh+en, non-exhaustive).
TYPE_E_PATTERNS = [
    r"走不通",
    r"行不通",
    r"此路不通",
    r"无法继续",
    r"卡死",
    r"\bdead\s+end\b",
    r"\bcannot\s+proceed\b",
    r"\bno\s+viable\s+path\b",
]

# #497 plan-stall (declarative Type B equivalent): a next-step DECLARATION
# with no subsequent tool action is letter-compliant but spirit-violating
# (v0.1.1 trajectory 2: milestone summary + "下一步: ..." then waiting).
# The colon is load-bearing for the tripwire: narrative uses ("下一步是")
# are not declarations, and markdown heading lines are skipped separately
# (F3: a plan-file header "## next step:" is a title, not a declaration).
PLAN_STALL_DECL_PATTERNS = [
    r"下一步\s*[:：]",
    r"\bnext\s+step\s*[:：]",
]

# #497/F3: ATX markdown heading line (1-6 '#' + space). Headings are titles
# — a colon inside one is structure, not a stall declaration.
MARKDOWN_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")

# #497: execution-narrative markers. Only texts WITHOUT a next-step
# declaration are scanned — a declaration's own verbs are intent
# ("下一步: dispatch C-2"), not execution; same-text self-clearing would
# kill the detector. Tripwire, non-exhaustive.
TOOL_ACTION_PATTERNS = [
    r"\bdispatch(?:ing|ed)?\b",
    r"派发",
    r"\bspawn(?:ing|ed)?\b",
    r"\brun(?:ning)?\b",
    r"运行",
    r"执行",
    r"\buv\s+run\b",
    r"\bpython\s+\S",
]

# #497 ladder-exhaustion precondition: a claim with this many failed
# attempts AND a candidate-less failure_analysis is "tools/resources
# exhausted (ladder climbed)" — the only blocker flavor that stays must-ask.
LADDER_EXHAUSTION_MIN_ATTEMPTS = 3

# #497/F1 plan-stall clearing window: a next-step declaration opens a
# BOUNDED window of the next PLAN_STALL_WINDOW_EVENTS stream events; only
# a tool-action INSIDE that window clears it. Pre-declaration history is
# never clearing evidence (actions before the declaration did not execute
# the DECLARED step), and an action after the window has closed does not
# retroactively clear it.
PLAN_STALL_WINDOW_EVENTS = 8

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


def _emit_interception(workspace: Path, action: str, detail: str, rc: int) -> None:
    """#459 observability: mirror an interception to the structured event
    log (action words from event_taxonomy.EMIT_ACTIONS; exit carries the rc
    so a tail can reconstruct the verdict timeline). Guarded — logging must
    never change the gate's verdict (fail-open, kunglao_record posture)."""
    try:
        from kunglao_log import emit
        emit(workspace, actor="orchestrator", action=action,
             detail=detail, exit=rc)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# #497 workspace state (fail-open reads: absent/unreadable -> empty).
# Consumes ONLY #495-landed structures — no new vocabulary, no new files:
#   claim-register.yaml claims   (promotion_attempts / origin / status)
#   analyses/failure-*.yaml      (candidates / outcome / claim)
# ---------------------------------------------------------------------------

def _load_claims(workspace: Path) -> list:
    """claim-register.yaml claims; [] when absent/unreadable."""
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return []
    try:
        reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return []
    claims = reg.get("claims") if isinstance(reg, dict) else None
    return claims if isinstance(claims, list) else []


def _load_analyses(workspace: Path) -> list:
    """#495 failure_analysis records (analyses/failure-*.yaml); tolerant."""
    adir = workspace / "analyses"
    if not adir.exists():
        return []
    out = []
    for p in sorted(adir.glob("failure-*.yaml")):
        try:
            entry = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def find_ladder_exhaustion(workspace: Path) -> list:
    """#497: ladder-exhaustion marker — the structural precondition for a
    blocker signal to stay must-ask ("tools/resources exhausted, ladder
    climbed"). Uses ONLY #495-landed fields: a failure_analysis record whose
    method ladder recorded NO candidates (empty/absent — the mechanical
    lessons rung ran and produced nothing) on a claim whose
    promotion_attempts >= LADDER_EXHAUSTION_MIN_ATTEMPTS (three distinct
    attempts already failed). Returns the qualifying claim ids."""
    claims = {str(c.get("id")): c for c in _load_claims(workspace)}
    out = []
    for entry in _load_analyses(workspace):
        cid = str(entry.get("claim") or "")
        claim = claims.get(cid)
        if claim is None:
            continue
        attempts = int(claim.get("promotion_attempts") or 0)
        candidates = entry.get("candidates") or []
        if attempts >= LADDER_EXHAUSTION_MIN_ATTEMPTS and not candidates:
            out.append(cid)
    return out


def find_death_evidence(workspace: Path) -> list:
    """#497 Type E: structured evidence that makes a death declaration a
    legal terminal. Two forms, both #495-landed:
      - a promoted obstacle claim (origin: failure-obstacle) whose status is
        REFUTED;
      - a failure_analysis record with outcome REFUTED (capability
        falsified — the disproven method/claim is formally recorded).
    Fail-closed: missing/unreadable files = no evidence = verdict rejected."""
    out = []
    for c in _load_claims(workspace):
        if (c.get("origin") == "failure-obstacle"
                and str(c.get("status") or "").upper() == "REFUTED"):
            out.append(f"obstacle claim {c.get('id')} REFUTED")
    for entry in _load_analyses(workspace):
        if str(entry.get("outcome") or "").upper() == "REFUTED":
            out.append(f"failure analysis for {entry.get('claim')} outcome=REFUTED")
    return out


# ---------------------------------------------------------------------------
# #497 declarative-sentence finders (tripwire layer).
# ---------------------------------------------------------------------------

def find_death_declarations(text: str) -> list:
    """#497 Type E tripwire: death-verdict phrases (zh+en, non-exhaustive).
    Returns list of (pattern, match) tuples."""
    out = []
    for pat in TYPE_E_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append((pat, m.group(0)))
    return out


def find_next_step_declaration(text: str):
    """#497 plan-stall tripwire: a next-step DECLARATION (colon required).
    Markdown heading lines are skipped first (F3: '## next step:' is a
    plan-file title, not a declaration). Returns the re.Match, or None."""
    body = "\n".join(line for line in text.splitlines()
                     if not MARKDOWN_HEADING_LINE.match(line))
    for pat in PLAN_STALL_DECL_PATTERNS:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            return m
    return None


def find_action_markers(text: str) -> bool:
    """#497: execution-narrative markers in a text that carries NO next-step
    declaration (caller enforces that precondition — see
    TOOL_ACTION_PATTERNS)."""
    return any(re.search(pat, text, re.IGNORECASE)
               for pat in TOOL_ACTION_PATTERNS)


# ---------------------------------------------------------------------------
# Event stream (SELF_REDIRECT_LOG). #497 adds bookkeeping event kinds;
# only VIOLATION-class events count toward the legacy 3-strike HARD_PAUSE.
# ---------------------------------------------------------------------------

# Bookkeeping prefixes that must NOT inflate the 3-strike redirect counter.
EVENT_KINDS_NON_VIOLATION = ("tool-action:", "plan-stall-decl:")


def _append_event(workspace: Path, text_excerpt: str, kind: str) -> None:
    """Append one event to the self_redirects stream (violation or
    bookkeeping — the kind prefix decides)."""
    path = workspace / SELF_REDIRECT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    ev = {
        "ts": utc_now(),
        "violation": kind,
        "excerpt": text_excerpt[:200],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _read_events(workspace: Path) -> list:
    """All parseable events as (epoch_ts, event_dict), in file order."""
    path = workspace / SELF_REDIRECT_LOG
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            t = datetime.strptime(
                e["ts"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc).timestamp()
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
        out.append((t, e))
    return out


def _action_since_last_declaration(workspace: Path) -> bool:
    """#497/F1 plan-stall window: has a tool-action event been recorded
    INSIDE the bounded window of the PLAN_STALL_WINDOW_EVENTS stream
    events AFTER the most recent next-step declaration? Compared by STREAM
    ORDER, not wall-clock ts (utc_now is second-granular — same-second
    rounds would otherwise never clear). No prior declaration -> NOT
    cleared: pre-declaration history is not evidence the declared step was
    executed (a warm action history must not grandfather a fresh
    declaration through)."""
    events = _read_events(workspace)
    last_decl_idx = None
    for i, (_t, ev) in enumerate(events):
        if str(ev.get("violation") or "").startswith("plan-stall-decl:"):
            last_decl_idx = i
    if last_decl_idx is None:
        return False
    window = events[last_decl_idx + 1:
                    last_decl_idx + 1 + PLAN_STALL_WINDOW_EVENTS]
    return any(str(ev.get("violation") or "").startswith("tool-action:")
               for _t, ev in window)


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

    Per references/agent-three-state-charter.md v2: identity ambiguity /
    scope change. (The new-hard-error family lives in
    find_blocker_signals — #497 downgraded it to allowed+ladder.)
    Returns list of (pattern, match) tuples."""
    out = []
    for pat in TYPE_D_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append((pat, m.group(0)))
    return out


def find_blocker_signals(text: str) -> list:
    """#497 charter v2: in-authorization-boundary new-hard-error signals.
    HARD_PAUSE only with a ladder-exhaustion marker on disk
    (find_ladder_exhaustion); otherwise rc=1 climb-the-ladder guidance.
    Returns list of (pattern, match) tuples."""
    out = []
    for pat in TYPE_D_BLOCKER_PATTERNS:
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
    """Append a self-redirect event; return count of VIOLATION-class events
    in last 1-hour window. #497: bookkeeping kinds (tool-action /
    plan-stall-decl) share the stream but never count — the 3-strike
    HARD_PAUSE semantics are untouched."""
    _append_event(workspace, text_excerpt, violation)
    one_hour_ago = datetime.now(tz=timezone.utc).timestamp() - 3600
    n = 0
    for t, ev in _read_events(workspace):
        v = str(ev.get("violation") or "")
        if v.startswith(EVENT_KINDS_NON_VIOLATION):
            continue
        if t >= one_hour_ago:
            n += 1
    return n


def check(workspace: Path, text: str) -> int:
    # #447 Type S (must-stop) takes precedence over everything — irreversible
    # actions MUST HARD_PAUSE regardless of any other state.
    must_stop = find_must_stop_signals(text)
    if must_stop:
        excerpt = text[:300].replace("\n", " ")
        print(f"HARD_PAUSE Type S (must-stop): {len(must_stop)} irreversible-action signal(s):")
        for pat, match in must_stop[:5]:
            print(f"  '{match}' (pattern: {pat})")
        print()
        print("Per references/agent-three-state-charter.md, irreversible actions MUST be")
        print("explicitly approved by the user. The orchestrator MUST NOT proceed")
        print("without confirmation. Refusing to continue.")
        print()
        print(f"Excerpt: {excerpt}")
        append_redirect(workspace, excerpt, "must-stop:" + must_stop[0][1])
        _emit_interception(workspace, "must_stop",
                           f"type=S match={must_stop[0][1]!r}", 2)
        return 2

    # #447 Type D (must-ask) also HARD_PAUSE — identity ambiguity / scope change.
    must_ask = find_must_ask_signals(text)
    if must_ask:
        excerpt = text[:300].replace("\n", " ")
        print(f"HARD_PAUSE Type D (must-ask): {len(must_ask)} ambiguity / scope signal(s):")
        for pat, match in must_ask[:5]:
            print(f"  '{match}' (pattern: {pat})")
        print()
        print("Per references/agent-three-state-charter.md, these events MUST be confirmed")
        print("by the user. The orchestrator MUST NOT self-resolve identity /")
        print("scope / authorization questions.")
        print()
        print(f"Excerpt: {excerpt}")
        append_redirect(workspace, excerpt, "must-ask:" + must_ask[0][1])
        _emit_interception(workspace, "must_ask",
                           f"type=D match={must_ask[0][1]!r}", 2)
        return 2

    # #497 charter v2 — Type D blocker family: an in-authorization-boundary
    # new hard error is ALLOWED + forced onto the ladder (method-ladder /
    # env-ladder), NOT must-ask. HARD_PAUSE survives only with the
    # ladder-exhaustion marker on disk (#495 fields: candidate-less
    # failure_analysis on a 3+ attempt claim = tools/resources exhausted).
    blockers = find_blocker_signals(text)
    if blockers:
        excerpt = text[:300].replace("\n", " ")
        exhausted = find_ladder_exhaustion(workspace)
        if exhausted:
            print(f"HARD_PAUSE Type D (must-ask): blocker signal "
                  f"'{blockers[0][1]}' with ladder EXHAUSTED on "
                  f"{', '.join(exhausted[:3])}:")
            print()
            print("Per references/agent-three-state-charter.md v2, tools/resources")
            print("exhausted (ladder climbed: no candidates, 3+ attempts) stays")
            print("must-ask. The orchestrator MUST NOT self-resolve further.")
            print()
            print(f"Excerpt: {excerpt}")
            append_redirect(workspace, excerpt, "must-ask:" + blockers[0][1])
            _emit_interception(
                workspace, "must_ask",
                f"type=D ladder-exhausted on {', '.join(exhausted[:3])} "
                f"match={blockers[0][1]!r}", 2)
            return 2
        print(f"REJECT Type D-blocker (charter v2): '{blockers[0][1]}' is an")
        print("in-authorization-boundary hard error -> allowed + FORCED LADDER,")
        print("not must-ask (climb the ladder, then re-evaluate / 走梯后复评):")
        print("  1. method-ladder: python scripts/failure_analysis_gate.py <ws> <C-NN>")
        print("       --record --assumption ... --validity not-justified")
        print("       --next-method ... --validated-capability ...")
        print("       --identified-obstacle ... --source lesson-hit")
        print("  2. env-ladder: self-recovery L1 same-tool different mode ->")
        print("       L2 owning skill setup.sh -> L3 env-fix worker")
        print("  3. re-evaluate after the ladder; only exhaustion (no candidates,")
        print("       3+ attempts) escalates back to must-ask")
        print()
        print(f"Excerpt: {excerpt}")
        append_redirect(workspace, excerpt, "ladder-required:" + blockers[0][1])
        _emit_interception(workspace, "ladder_required",
                           f"type=D-blocker match={blockers[0][1]!r}", 1)
        return 1

    # #497 Type E (death declaration, declarative gate): a death verdict
    # without obstacle-REFUTED / capability-falsified evidence is NOT a
    # terminal — forced ladder re-eval (v0.1.1 trajectory 1 replay class).
    death = find_death_declarations(text)
    if death:
        excerpt = text[:300].replace("\n", " ")
        evidence = find_death_evidence(workspace)
        if not evidence:
            print(f"REJECT Type E (death declaration): {len(death)} verdict signal(s):")
            for pat, match in death[:5]:
                print(f"  '{match}' (pattern: {pat})")
            print()
            print("A death verdict is the grammar that silently kills a task: it asks")
            print("no question, so neither the ask-back gate nor the must-ask gate")
            print("fires. Without evidence it is NOT a terminal. The orchestrator")
            print("MUST climb the ladder and re-evaluate (走梯复评), or produce the")
            print("evidence:")
            print("  - record failure_analysis with the three artifacts")
            print("    (validated_capability / identified_obstacle / --source) —")
            print("    the obstacle auto-promotes to a claim;")
            print("  - a legal terminal requires the obstacle claim REFUTED or a")
            print("    capability-falsified analysis outcome (none found here).")
            print()
            print(f"Excerpt: {excerpt}")
            append_redirect(workspace, excerpt, "death-declaration:" + death[0][1])
            _emit_interception(workspace, "death_verdict_rejected",
                               f"type=E match={death[0][1]!r}", 1)
            return 1
        print(f"OK: death declaration backed by evidence "
              f"({'; '.join(evidence[:3])}) — legal terminal")
        # fall through to Type A/B checks

    # #497 plan-stall (declarative Type B equivalent): a next-step
    # declaration with no tool action inside the bounded window AFTER the
    # previous declaration (F1: pre-declaration history never clears —
    # first declaration in a warm stream is judged exactly like a cold
    # one). Window bookkeeping: declarations and tool actions are events
    # in the self_redirects stream; only violation events count toward
    # 3-strike.
    decl = find_next_step_declaration(text)
    if decl is not None:
        excerpt = text[:300].replace("\n", " ")
        if not _action_since_last_declaration(workspace):
            _append_event(workspace, excerpt, "plan-stall-decl:")
            print("REJECT plan-stall (Type B equivalent): next-step declaration")
            print(f"  '{decl.group(0)}' with NO tool action after the previous declaration.")
            print()
            print("ORCHESTRATOR MUST execute the declared step or declare the blocker")
            print("(执行该下一步,或声明阻塞原因 — waiting is not an option, per")
            print("section 6d.1 / Type B):")
            print("  - execute: dispatch / run the declared step now;")
            print("  - or record the blocker via failure_analysis, then the")
            print("    ladder applies.")
            print()
            print(f"Excerpt: {excerpt}")
            append_redirect(workspace, excerpt, "plan-stall:" + decl.group(0))
            _emit_interception(workspace, "plan_stall",
                               f"declaration={decl.group(0)!r}", 1)
            return 1
        _append_event(workspace, excerpt, "plan-stall-decl:")
        # action happened since the last declaration -> preceded by
        # execution; fall through to Type A/B checks
    elif find_action_markers(text):
        _append_event(workspace, text[:300].replace("\n", " "),
                      "tool-action:")

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
    rc = 2 if n_redirects >= 3 else 1
    _emit_interception(
        workspace, "ask_back",
        f"types={[v[0] for v in violations[:5]]} redirects={n_redirects}", rc)
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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())