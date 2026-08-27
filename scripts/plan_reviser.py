# -*- coding: utf-8 -*-
"""plan_reviser.py — planning state machine + trigger-based incremental replanning (#761 J3).

Root cause: `runs/plan-C*.md` was one-shot static. The plan gate (#239/#294)
only checks existence/content BEFORE dispatch; plan_drift_detector (#602)
compares plan-vs-reality AFTER the fact; nothing in between DETECTS that a
plan should be revised while the worker is still inside it, and nothing
records HOW a plan changed (re-planning used to silently rewrite history).

State machine (frontmatter of every plan):
  status: pending | in-flight | blocked | superseded
  revision: N          # bumped by every recorded revision, starts at 0

Three mechanical triggers (--check; each is decidable without an LLM):

  blocker     a blockers/<claim>.md landed AFTER the claim's plan mtime
              (claim escalation — SKILL contract: orchestrator must react)
  assumption  a facts/F*.md with frontmatter `status: PROVEN` shares >=2
              significant tokens with a plan `assumptions:` line AND is newer
              than the plan — keyword-level, CONSERVATIVE: this is a
              suggest_revision only, the orchestrator decides whether the
              assumption really died
  cost        runs/cost_advice.json carries tier == "advisory" (the
              cost_gate.py signal file)

Posture: --check NEVER gates (exit 0 clean / exit 3 suggestions found — the
SATURATED-style observation face of #602, output is a suggestion stream for
the orchestrator/THINK product). Actual revision is applied via --apply which
is INCREMENTAL ONLY: append a `## revision-N` segment (timestamp / trigger /
changed steps / reason) and bump the frontmatter revision counter. Earlier
content including earlier revision segments is byte-preserved — the diff IS
the audit trail.

SKILL.md contract: receiving any suggest_revision REQUIRES the orchestrator
to produce a revision segment (`--apply`); it may decide NOT to change steps,
but then the revision segment records "no change" + reason instead of silence.

Usage:
  python plan_reviser.py --check <workspace>
  python plan_reviser.py --apply <workspace> <plan-path> \
      --trigger <blocker|assumption|cost|manual> --steps "<text>" --reason "<text>"
Exit codes: 0 = ok/clean; 2 = usage error; 3 = suggestions exist (--check only).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VALID_PLAN_STATUSES = ("pending", "in-flight", "blocked", "superseded")
MIN_TOKEN_OVERLAP = 2          # assumption-conflict conservatism knob
SIGNIFICANT_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
REV_HEADING_RE = re.compile(r"^##\s+revision-(\d+)\s*$", re.MULTILINE)
STATUS_LINE_RE = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)
REVISION_LINE_RE = re.compile(r"^revision:\s*(\d+)\s*$", re.MULTILINE)
COST_ADVICE_REL = Path("runs") / "cost_advice.json"

USAGE = (
    "Usage:\n"
    "  python plan_reviser.py --check <workspace>\n"
    "  python plan_reviser.py --apply <ws> <plan> --trigger T "
    "--steps TEXT --reason TEXT\n"
    "Plan state machine + incremental revision (issue #761 J3).\n"
)


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- plan header parsing ----------

def parse_plan_header(text: str) -> dict:
    """Read the loose plan header: first ``status:``/``revision:`` line wins.

    Missing fields normalize to the protocol defaults (status=pending,
    revision=0) so pre-J3 plans are valid inputs."""
    m = STATUS_LINE_RE.search(text)
    status = m.group(1).lower() if m else "pending"
    if status not in VALID_PLAN_STATUSES:
        status = "pending"
    m = REVISION_LINE_RE.search(text)
    revision = int(m.group(1)) if m else 0
    return {"status": status, "revision": revision}


# ---------- trigger A: blocker escalation ----------

def claim_id_from_plan(plan_path: Path) -> str | None:
    """plan-C001*.md / plan-c001-something.md -> C-001 (mirrors the worker
    budget gate's uppercase/lowercase naming tolerance)."""
    m = re.match(r"plan-([A-Za-z]+)(\d+)", plan_path.name)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else None


def detect_blocker_trigger(ws: Path, now: datetime | None = None) -> list[dict]:
    """Fresh blockers/<claim>.md for a planned claim = the plan's environment
    escalated. Freshness = blocker mtime strictly newer than the plan file."""
    out: list[dict] = []
    runs = ws / "runs"
    if not runs.is_dir():
        return out
    plans = sorted(p for p in runs.iterdir()
                   if p.name.lower().startswith("plan-c"))
    for plan in plans:
        cid = claim_id_from_plan(plan)
        if not cid:
            continue
        blocker = ws / "blockers" / f"{cid}.md"
        try:
            if not blocker.exists():
                continue
            if blocker.stat().st_mtime <= plan.stat().st_mtime:
                continue
        except OSError:
            continue
        out.append({
            "trigger": "blocker",
            "claim": cid,
            "detail": f"{blocker.relative_to(ws)} newer than {plan.name}",
            "suggest_revision": True,
            "ts": utc_now(),
        })
    return out


# ---------- trigger B: PROVEN fact vs plan assumption ----------

def _tokens(text: str) -> set[str]:
    return set(SIGNIFICANT_TOKEN_RE.findall(text.lower()))


def _assumption_lines(plan_text: str) -> list[str]:
    """Lines belonging to the plan's assumptions block: the `assumptions:`
    line plus following `- ` bullets until a non-bullet non-empty line."""
    lines = plan_text.splitlines()
    out: list[str] = []
    idx = next((i for i, ln in enumerate(lines)
                if ln.strip().lower().startswith("assumptions:")), None)
    if idx is None:
        return out
    rest = lines[idx].split(":", 1)[1].strip()
    if rest and not rest.startswith(("#", "-")):
        out.append(rest)
    for ln in lines[idx + 1:]:
        s = ln.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s:
            break
    return out


def detect_assumption_conflict(ws: Path) -> list[dict]:
    """Keyword-level conservative check: >=2 shared significant tokens between
    a NEWER PROVEN fact statement and an assumption line => suggest_revision.
    Never asserts the fact value contradicts the text — overlap-only (the
    semantic call belongs to the orchestrator)."""
    out: list[dict] = []
    runs, facts = ws / "runs", ws / "facts"
    if not runs.is_dir() or not facts.is_dir():
        return out
    for plan in sorted(p for p in runs.iterdir()
                       if p.name.lower().startswith("plan-c")):
        try:
            plan_text = plan.read_text(encoding="utf-8", errors="replace")
            plan_mtime = plan.stat().st_mtime
        except OSError:
            continue
        for assumption in _assumption_lines(plan_text):
            asum_toks = _tokens(assumption)
            if not asum_toks:
                continue
            for fact in sorted(facts.glob("F*.md")):
                try:
                    head = fact.read_text(encoding="utf-8", errors="replace")[:2048]
                    fact_mtime = fact.stat().st_mtime
                except OSError:
                    continue
                if "status: PROVEN" not in head[:400]:
                    continue
                if fact_mtime <= plan_mtime:
                    continue  # only NEWER proven facts can invalidate a plan
                m = re.search(r"^statement:\s*(.+)$", head, re.MULTILINE)
                statement = m.group(1) if m else ""
                overlap = asum_toks & _tokens(statement)
                if len(overlap) >= MIN_TOKEN_OVERLAP:
                    out.append({
                        "trigger": "assumption",
                        "claim": claim_id_from_plan(plan),
                        "fact": fact.stem,
                        "detail": (
                            f"{fact.name} (PROVEN, newer than plan) overlaps "
                            f"assumption tokens {sorted(overlap)}: "
                            f"'{assumption[:60]}'"),
                        "suggest_revision": True,
                        "ts": utc_now(),
                    })
                    break  # one conflict per assumption line is enough signal
    return out


# ---------- trigger C: cost over threshold ----------

def detect_cost_trigger(ws: Path) -> list[dict]:
    """The cost_gate advisory file is the mechanical 'cost 超阈' signal."""
    advice = ws / COST_ADVICE_REL
    if not advice.is_file():
        return []
    try:
        data = json.loads(advice.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return []
    if (data or {}).get("tier") != "advisory":
        return []
    return [{
        "trigger": "cost",
        "claim": None,
        "detail": f"{COST_ADVICE_REL} tier=advisory ({data.get('count')} warnings)",
        "suggest_revision": True,
        "ts": utc_now(),
    }]


def run_checks(ws: Path) -> list[dict]:
    """All three triggers, deterministic order: blocker, assumption, cost."""
    ws = Path(ws)
    suggestions: list[dict] = []
    suggestions.extend(detect_blocker_trigger(ws))
    suggestions.extend(detect_assumption_conflict(ws))
    suggestions.extend(detect_cost_trigger(ws))
    return suggestions


# ---------- incremental revision application ----------

def append_revision(plan_path: Path, trigger: str, changed_steps: str,
                    reason: str, ts: str | None = None) -> dict:
    """Append-only revision record. Returns {"revision": N, "appended": block}.

    Byte-prefix guarantee: the pre-existing file content is never rewritten;
    the new segment starts as a fresh suffix (earlier revision segments stay
    untouched so `git diff` shows one append)."""
    plan_path = Path(plan_path)
    ts = ts or utc_now()
    text = plan_path.read_text(encoding="utf-8", errors="replace") \
        if plan_path.exists() else ""
    prior = parse_plan_header(text)
    existing = [int(m.group(1)) for m in REV_HEADING_RE.finditer(text)]
    n = max([*existing, prior["revision"]]) + 1
    if text and not text.endswith("\n"):
        text += "\n"
    block = (
        f"\n## revision-{n}\n\n"
        f"- ts: {ts}\n"
        f"- trigger: {trigger}\n"
        f"- changed_steps: {changed_steps}\n"
        f"- reason: {reason}\n"
    )
    out = text + block
    # bump/insert the frontmatter revision counter (first occurrence only)
    if REVISION_LINE_RE.search(out):
        out = REVISION_LINE_RE.sub(f"revision: {n}", out, count=1)
    elif out.startswith("---"):
        pass  # frontmatter without revision: header stays, block owns the count
    else:
        out = f"---\nstatus: pending\nrevision: {n}\n---\n" + out
    plan_path.write_text(out, encoding="utf-8", newline="\n")
    return {"revision": n, "appended": block.strip("\n")}


# ---------- CLI ----------

def main(argv: list[str]) -> int:
    if "--check" in argv:
        args = argv[argv.index("--check") + 1:]
        if not args or not Path(args[0]).is_dir():
            print(USAGE, file=sys.stderr)
            return 2
        ws = Path(args[0])
        suggestions = run_checks(ws)
        payload = {
            "workspace": str(ws),
            "checked_at": utc_now(),
            "suggestions": suggestions,
            "contract": (
                "orchestrator MUST produce a ## revision-N segment per "
                "suggestion (use --apply); deciding 'no change' still "
                "requires a recorded no-change revision"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3 if suggestions else 0
    if "--apply" in argv:
        rest = argv[argv.index("--apply") + 1:]
        if len(rest) < 2 or not Path(rest[0]).is_dir():
            print(USAGE, file=sys.stderr)
            return 2
        plan = Path(rest[1])
        if not plan.is_file():
            print(f"error: plan not found: {plan}", file=sys.stderr)
            return 2

        def flag(name: str) -> str:
            j = rest.index(name) if name in rest else -1
            if j < 0:
                return ""
            v = rest[j + 1] if j + 1 < len(rest) else ""
            return "" if v.startswith("--") else v

        res = append_revision(plan, trigger=flag("--trigger") or "manual",
                              changed_steps=flag("--steps"),
                              reason=flag("--reason"))
        print(json.dumps({"ok": True, "plan": str(plan), **res},
                         ensure_ascii=False))
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
