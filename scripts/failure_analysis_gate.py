#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""failure_analysis_gate.py - force method reasoning after a failed attempt (v1.9.3).

THE PROBLEM THIS SOLVES (user's exact words):
  "目前我们要分析 c2 的网络协议,但是目前失败了,你能说没有网络协议行为,
   然后不分析吗?但是之前的分析办法可能存在问题,这个就需要分析,然后优化"

A failed analysis attempt is NOT evidence the behavior is absent. It is evidence
the METHOD failed — possibly. The orchestrator must NOT collapse "method failed"
into "sample doesn't do X". Before re-dispatching OR concluding NEGATIVE, it must
reason about WHY the method failed.

This gate does NOT give a fixed taxonomy of failure types (that would be a
checklist the agent picks from without thinking). It forces THREE QUESTIONS whose
answers the agent must generate from the specific situation:

  1. method_assumption   — what did the failed method assume would happen?
  2. assumption_validity — is that assumption justified given what we know?
                           (if not → method failed, not behavior absent)
  3. next_method         — what DIFFERENT method tests a different assumption?
                           (literal "retry the same thing" is forbidden here)

Only if the agent can argue assumption_validity = "justified, method was adequate"
may the claim be marked NEGATIVE — and even then it carries single-method
confidence (a different method can overturn it later).

Enforcement: a claim with a prior failed attempt (promotion_attempts > 0, status
non-terminal) that has NO current failure_analysis → BLOCKED. The orchestrator
cannot re-dispatch through the normal flow until the analysis is recorded.

Each failed attempt needs its own analysis (covers_attempt versioning) — you can't
coast on the reasoning from attempt 1 when attempt 3 also fails.

Usage:
  # check mode — which claims need analysis?
  python scripts/failure_analysis_gate.py <workspace>

  # check one claim
  python scripts/failure_analysis_gate.py <workspace> <C-NN>

  # record an analysis (unblocks re-dispatch or NEGATIVE conclusion)
  python scripts/failure_analysis_gate.py <workspace> <C-NN> --record \
      --assumption "what the failed method assumed" \
      --validity "not-justified | justified-adequate" \
      --next-method "what different method to try (or 'method was adequate' for true negative)"

  # fill the outcome at claim closure (adds --outcome/--what-happened to the
  # recorded analysis; prior assumption/validity/next_method are preserved)
  python scripts/failure_analysis_gate.py <workspace> <C-NN> --record \
      --outcome "PROVEN | VERIFIED | REFUTED | NEGATIVE" \
      --what-happened "free text: what actually happened"

  # aggregate closed-loop analyses into the global lessons library (#41)
  python scripts/failure_analysis_gate.py <workspace> --lessons \
      [--library DIR] [--reflect-queue FILE]

  # search the lessons library by keywords/claim-tag (no embeddings)
  python scripts/failure_analysis_gate.py --search "frida vm" [--library DIR]

Exit codes:
  0 = OK (no failed attempt pending, or analysis covers it)
  1 = BLOCKED (failed attempt, analysis missing or stale)
  2 = claim not found or terminal (no analysis needed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import TERMINAL

ANALYSES_DIR = "analyses"

# #41: aggregation reads the #35 ledger OUTCOME rows to decide whether a
# NEGATIVE survived red-team (checker=red-team, result=CONFIRMED).
LEDGER_NAME = ".convergence_ledger.jsonl"

# Closed-loop outcomes eligible for the lessons library. Tuple constant on
# purpose — no status-set literal here (test_status_defs grep guard).
OUTCOME_VALUES = ("PROVEN", "VERIFIED", "REFUTED", "NEGATIVE")

# #41: the lessons library is GLOBAL (cross-sample), never per-workspace —
# default <skill>/references/lessons/ next to case-book.md. --library and
# --reflect-queue override both paths so tests run entirely against tmp.
LESSONS_DIR_DEFAULT = Path.home() / ".claude" / "skills" / "kunglao-agent" / "references" / "lessons"
REFLECT_QUEUE_DEFAULT = Path.home() / ".claude" / "learnings-queue.json"
REFLECT_ITEM_TYPE = "failure-lesson-candidate"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _resolve_ws(arg) -> Path:
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def _load_claims(workspace: Path):
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], None
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg


def _analysis_path(workspace: Path, claim_id: str) -> Path:
    return workspace / ANALYSES_DIR / f"failure-{claim_id}.yaml"


def _load_analysis(workspace: Path, claim_id: str):
    p = _analysis_path(workspace, claim_id)
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def _needs_analysis(claim: dict) -> bool:
    """A claim needs failure analysis if it was attempted (promotion_attempts > 0)
    but hasn't reached terminal status — a dispatch happened and didn't close it."""
    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return False
    return int(claim.get("promotion_attempts") or 0) > 0


def _analysis_covers(analysis: dict, claim: dict) -> bool:
    """Does the recorded analysis cover the latest failed attempt?
    covers_attempt must match (or exceed) the claim's current promotion_attempts."""
    if not analysis:
        return False
    covers = int(analysis.get("covers_attempt") or 0)
    attempts = int(claim.get("promotion_attempts") or 0)
    return covers >= attempts


def check_claim(workspace: Path, claim_id: str, library: Path | None = None) -> dict:
    claims, _ = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"state": "NOT_FOUND", "claim_id": claim_id}

    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return {"state": "TERMINAL", "claim_id": claim_id, "status": status}

    if not _needs_analysis(claim):
        return {"state": "OK_NO_PRIOR_FAILURE", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts")}

    analysis = _load_analysis(workspace, claim_id)
    if _analysis_covers(analysis, claim):
        return {"state": "OK_COVERED", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts"),
                "analysis": analysis}

    return {
        "state": "BLOCKED",
        "claim_id": claim_id,
        "status": status,
        "promotion_attempts": claim.get("promotion_attempts"),
        "evidence_tier_attempted": claim.get("evidence_tier_attempted"),
        "statement": (claim.get("statement") or "")[:200],
        "evidence": claim.get("evidence") or [],
        "stale_analysis": analysis,
        # #41: guide the orchestrator with up to 3 similar lessons from the
        # global library (keyword overlap on statement + claim id).
        "similar_lessons": _score_lessons(
            f"{(claim.get('statement') or '')} {claim_id}",
            Path(library) if library else LESSONS_DIR_DEFAULT),
    }


def scan_workspace(workspace: Path, library: Path | None = None) -> list:
    """Return all claims that currently BLOCK (failed attempt, no current analysis)."""
    claims, _ = _load_claims(workspace)
    blocked = []
    for c in claims:
        if not _needs_analysis(c):
            continue
        analysis = _load_analysis(workspace, c.get("id"))
        if not _analysis_covers(analysis, c):
            blocked.append(check_claim(workspace, c.get("id"), library=library))
    return blocked


def record_analysis(workspace: Path, claim_id: str, assumption: str,
                    validity: str, next_method: str,
                    outcome: str | None = None,
                    what_happened: str | None = None) -> dict:
    claims, _ = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"recorded": False, "reason": f"claim {claim_id} not found"}

    validity = (validity or "").strip().lower()

    # #41 claim-closure backfill: when the caller only supplies the outcome
    # (--outcome/--what-happened), preserve the failure-time analysis fields —
    # closure must not clobber what was recorded at failure time.
    prior = _load_analysis(workspace, claim_id) or {}
    if not (assumption or "").strip():
        assumption = prior.get("method_assumption", "")
    if not validity:
        validity = (prior.get("assumption_validity") or "").strip().lower()
    if not (next_method or "").strip():
        next_method = prior.get("next_method", "")

    if validity not in ("not-justified", "justified-adequate"):
        return {"recorded": False,
                "reason": "--validity must be 'not-justified' or 'justified-adequate'"}

    # not-justified REQUIRES a real different next_method (not "adequate" hand-wave)
    if validity == "not-justified":
        if not next_method or not next_method.strip():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a --next-method (the different method to try)"}
        if "adequate" in next_method.lower() or "retry" == next_method.strip().lower():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a DIFFERENT method, not 'adequate' or bare 'retry'"}

    # #41 outcome: optional; both-or-neither; one of OUTCOME_VALUES (normalized).
    outcome_norm = None
    if outcome or what_happened:
        if not (outcome and (what_happened or "").strip()):
            return {"recorded": False,
                    "reason": "--outcome and --what-happened must be provided together"}
        outcome_norm = (outcome or "").strip().upper()
        if outcome_norm not in OUTCOME_VALUES:
            return {"recorded": False,
                    "reason": f"--outcome must be one of {', '.join(OUTCOME_VALUES)}"}
        what_happened = what_happened.strip()

    adir = workspace / ANALYSES_DIR
    adir.mkdir(parents=True, exist_ok=True)
    entry = {
        "claim": claim_id,
        "covers_attempt": int(claim.get("promotion_attempts") or 0),
        "method_assumption": assumption,
        "assumption_validity": validity,
        "next_method": next_method,
        "analyzed_at": prior.get("analyzed_at") or utc_now_iso(),
    }
    if outcome_norm:
        entry["outcome"] = outcome_norm
        entry["what_happened"] = what_happened
    _analysis_path(workspace, claim_id).write_text(
        yaml.safe_dump(entry, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"recorded": True, "entry": entry}


# ===================== #41 failure-lessons library =====================
# Closed-loop outcomes (PROVEN/VERIFIED, or NEGATIVE that survived red-team)
# aggregate into lesson files under a GLOBAL library (cross-sample); everything
# else lands in the /reflect human queue. Retrieval is plain keyword overlap
# (no embeddings — the corpus is dozens of entries).

def _claim_topic(claim: dict | None, claim_id: str) -> str:
    """Claim topic for the failure signature: `topic` field, else the
    normalized statement (first 120 chars), else the claim id."""
    if claim:
        topic = (claim.get("topic") or "").strip()
        if topic:
            return topic
        stmt = (claim.get("statement") or "").strip()
        if stmt:
            return " ".join(stmt.split())[:120]
    return claim_id


def _signature(method_assumption: str, next_method: str, claim_topic: str) -> str:
    """Failure signature = method + assumption + claim topic (issue #41)."""
    norm = lambda s: " ".join((s or "").lower().split())
    return f"{norm(method_assumption)} || {norm(next_method)} || {norm(claim_topic)}"


def _lesson_slug(signature: str) -> str:
    """Deterministic file identity: same signature -> same slug -> idempotent."""
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10]


def _lesson_filename(signature: str) -> str:
    return f"lesson-{_lesson_slug(signature)}.md"


def _write_lesson(lib: Path, signature: str, topic: str,
                  entries: list[tuple[str, dict]]) -> Path:
    """One lesson file per signature group, listing every source claim."""
    fm = {
        "type": "lesson",
        "signature": signature,
        "slug": _lesson_slug(signature),
        "method_assumption": entries[0][1].get("method_assumption", ""),
        "assumption_validity": entries[0][1].get("assumption_validity", ""),
        "next_method": entries[0][1].get("next_method", ""),
        "claim_topic": topic,
        "outcome": ", ".join(sorted({e.get("outcome", "") for _, e in entries})),
        "sources": sorted(cid for cid, _ in entries),
        "created_at": utc_now_iso(),
    }
    lines = ["---", yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip(), "---", ""]
    lines.append(f"# Lesson — {topic}")
    lines.append("")
    lines.append("## 失败签名 (failure signature)")
    lines.append(f"- method_assumption: {fm['method_assumption']}")
    lines.append(f"- assumption_validity: {fm['assumption_validity']}")
    lines.append(f"- next_method: {fm['next_method']}")
    lines.append(f"- claim topic: {topic}")
    lines.append("")
    lines.append("## 已验证结论 (what actually happened)")
    for cid, entry in sorted(entries):
        lines.append(f"- {cid} ({entry.get('outcome', '')}): {entry.get('what_happened', '')}")
    lines.append("")
    path = lib / _lesson_filename(signature)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _reflect_reason(outcome: str | None, redteam_ok: bool) -> str:
    """Why an entry is NOT library-eligible; '' means it is closed-loop."""
    if outcome is None:
        return "no-outcome"
    if outcome == "REFUTED":
        return "refuted"
    if outcome == "NEGATIVE" and not redteam_ok:
        return "negative-unverified"
    return ""


def _append_reflect_queue(queue_path: Path, entries: list[dict]) -> int:
    """Append items to the claude-reflect learnings queue (JSON array, plugin
    schema + failure fields); idempotent on claim_id|reason."""
    items: list = []
    if queue_path.exists():
        try:
            loaded = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                items = loaded
        except (json.JSONDecodeError, OSError):
            items = []
    seen = {f"{i.get('claim_id')}|{i.get('reason')}" for i in items}
    added = 0
    for e in entries:
        key = f"{e['claim_id']}|{e['reason']}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "type": REFLECT_ITEM_TYPE,
            "message": e.get("message", ""),
            "timestamp": utc_now_iso(),
            "project": str(Path.cwd()),
            "claim_id": e["claim_id"],
            "outcome": e.get("outcome"),
            "reason": e["reason"],
            "next_method": e.get("next_method", ""),
            "method_assumption": e.get("method_assumption", ""),
        })
        added += 1
    if added:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return added


def aggregate_lessons(workspace: Path, library: Path | None = None,
                      reflect_queue: Path | None = None) -> dict:
    """Aggregate analyses/failure-*.yaml into the global lessons library.

    Closed-loop only: PROVEN/VERIFIED always; NEGATIVE only when the #35
    ledger carries a red-team CONFIRMED OUTCOME row for the claim. Every
    other entry goes to the /reflect queue (reason: refuted /
    negative-unverified / no-outcome). Idempotent: an existing lesson file
    for the signature is skipped; queue items dedup on claim_id|reason.
    """
    lib = Path(library) if library else LESSONS_DIR_DEFAULT
    queue = Path(reflect_queue) if reflect_queue else REFLECT_QUEUE_DEFAULT
    claims, _ = _load_claims(workspace)
    claims_by_id = {c.get("id"): c for c in claims}
    try:
        from outcome_capture import read_outcome_rows  # sibling in scripts/
        redteam_ok = {r.get("claim_id") for r in read_outcome_rows(workspace)
                      if r.get("checker") == "red-team" and r.get("result") == "CONFIRMED"}
    except ImportError:
        redteam_ok = set()

    groups: dict[str, list[tuple[str, dict]]] = {}
    topics: dict[str, str] = {}
    queued: list[dict] = []
    adir = workspace / ANALYSES_DIR
    if adir.exists():
        for p in sorted(adir.glob("failure-*.yaml")):
            try:
                entry = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                continue  # unreadable / malformed analysis — skip, no crash
            if not isinstance(entry, dict):
                continue
            cid = entry.get("claim") or p.name.removeprefix("failure-").removesuffix(".yaml")
            claim = claims_by_id.get(cid)
            outcome = entry.get("outcome")
            if outcome in ("PROVEN", "VERIFIED") or (
                    outcome == "NEGATIVE" and cid in redteam_ok):
                topic = _claim_topic(claim, cid)
                sig = _signature(entry.get("method_assumption", ""),
                                 entry.get("next_method", ""), topic)
                groups.setdefault(sig, []).append((cid, entry))
                topics[sig] = topic
            else:
                reason = _reflect_reason(outcome, cid in redteam_ok)
                if reason:
                    queued.append({
                        "claim_id": cid, "reason": reason, "outcome": outcome,
                        "next_method": entry.get("next_method", ""),
                        "method_assumption": entry.get("method_assumption", ""),
                        "message": (
                            f"failure analysis for claim {cid} did not close a "
                            f"verified loop (reason={reason}); "
                            f"what happened: {entry.get('what_happened', '')}"),
                    })

    written = skipped = 0
    lib.mkdir(parents=True, exist_ok=True)
    for sig, entries in sorted(groups.items()):
        if (lib / _lesson_filename(sig)).exists():
            skipped += 1
            continue
        _write_lesson(lib, sig, topics[sig], entries)
        written += 1
    queue_added = _append_reflect_queue(queue, queued)
    return {"lessons_written": written, "lessons_skipped": skipped,
            "queue_added": queue_added}


TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")


def _tokens(text: str) -> set:
    return set(TOKEN_RE.findall((text or "").lower()))


def _lesson_meta(path: Path) -> dict:
    """Frontmatter + full text of a lesson file; tolerant parse."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    parts = text.split("---", 2)
    meta: dict = {}
    if len(parts) >= 3:
        try:
            parsed = yaml.safe_load(parts[1])
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}
    return {"path": path, "text": text,
            "outcome": str(meta.get("outcome", "")),
            "next_method": str(meta.get("next_method", "")),
            "claim_topic": str(meta.get("claim_topic", ""))}


def _score_lessons(query: str, library: Path, limit: int = 3) -> list[dict]:
    """Top-N lessons by keyword/token overlap with the query (no embeddings)."""
    q = _tokens(query)
    if not q or not library.exists():
        return []
    scored = []
    for p in sorted(library.glob("lesson-*.md")):
        meta = _lesson_meta(p)
        score = len(q & _tokens(meta["text"]))
        if score:
            scored.append({"file": p.name, "score": score,
                           "outcome": meta["outcome"],
                           "next_method": meta["next_method"],
                           "claim_topic": meta["claim_topic"]})
    scored.sort(key=lambda s: (-s["score"], s["file"]))
    return scored[:limit]


def search_lessons(query: str, library: Path | None = None, limit: int = 3) -> list[dict]:
    """CLI search over the lessons library (keywords/claim-tag, no embeddings)."""
    return _score_lessons(query, Path(library) if library else LESSONS_DIR_DEFAULT, limit)


def _print_blocked(d: dict) -> None:
    cid = d["claim_id"]
    print(f"=== BLOCKED: {cid} (status={d.get('status')}, attempts={d.get('promotion_attempts')}) ===")
    print(f"claim: {d.get('statement','')}")
    if d.get("evidence"):
        print(f"evidence so far: {d['evidence']}")
    if d.get("stale_analysis"):
        print(f"stale analysis (covers attempt {d['stale_analysis'].get('covers_attempt')}): update it")
    print()
    print("Before re-dispatching OR concluding NEGATIVE, answer three questions")
    print("(reason from THIS specific failure — do not pick from a fixed menu):")
    print()
    print("  1. method_assumption   — what did the failed method assume would happen?")
    print("  2. assumption_validity — is that assumption justified given the evidence?")
    print("                           if NOT justified -> the METHOD failed, not the behavior absent")
    print("  3. next_method         — what DIFFERENT method tests a different assumption?")
    print("                           (literal retry is forbidden; 'method was adequate' only if Q2=justified)")
    print()
    print("Record with:")
    print(f"  python scripts/failure_analysis_gate.py <ws> {cid} --record \\")
    print(f"      --assumption \"...\" --validity not-justified|justified-adequate --next-method \"...\"")
    sim = d.get("similar_lessons") or []
    if sim:
        print()
        print("Similar lessons from the failure-lessons library (keyword match, #41):")
        for s in sim:
            print(f"  - {s['file']} (score {s['score']}, outcome {s['outcome']}): "
                  f"{s['claim_topic']} — next: {s['next_method']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent failure-analysis gate — reason before re-dispatch or NEGATIVE")
    parser.add_argument("workspace", nargs="?", default=None, help="workspace root (omit: cwd or ./malware-analysis-workspace)")
    parser.add_argument("claim_id", nargs="?", default=None, help="claim to check (omit to scan all)")
    parser.add_argument("--record", action="store_true", help="record a failure analysis")
    parser.add_argument("--assumption", default=None, help="what the failed method assumed")
    parser.add_argument("--validity", default=None, help="not-justified | justified-adequate")
    parser.add_argument("--next-method", default=None, help="the different method to try next")
    parser.add_argument("--outcome", default=None,
                        help="claim-closure result (#41): PROVEN|VERIFIED|REFUTED|NEGATIVE")
    parser.add_argument("--what-happened", default=None,
                        help="free text: what actually happened (#41, required with --outcome)")
    parser.add_argument("--lessons", action="store_true",
                        help="aggregate analyses into the global lessons library (#41)")
    parser.add_argument("--search", metavar="KEYWORDS", default=None,
                        help="search the lessons library by keywords/claim-tag (#41)")
    parser.add_argument("--library", default=None,
                        help="lessons library dir (default: ~/.claude/skills/kunglao-agent/references/lessons)")
    parser.add_argument("--reflect-queue", default=None,
                        help="/reflect human queue file (default: ~/.claude/learnings-queue.json)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    workspace = _resolve_ws(args.workspace)

    if args.lessons:
        r = aggregate_lessons(workspace, library=args.library, reflect_queue=args.reflect_queue)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print(f"lessons written: {r['lessons_written']} "
                  f"(skipped existing: {r['lessons_skipped']}); "
                  f"/reflect queue new entries: {r['queue_added']}")
        return 0

    if args.search:
        hits = search_lessons(args.search, library=args.library)
        if args.json:
            print(json.dumps(hits, indent=2, ensure_ascii=False))
        elif hits:
            for h in hits:
                print(f"{h['file']} (score {h['score']}, outcome {h['outcome']}): "
                      f"{h['claim_topic']} — next: {h['next_method']}")
        else:
            print("no matching lessons")
        return 0

    if args.record:
        if not args.claim_id:
            print("FAIL: --record requires a claim_id", file=sys.stderr)
            return 64
        r = record_analysis(workspace, args.claim_id, args.assumption or "",
                           args.validity or "", args.next_method or "",
                           args.outcome, args.what_happened)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print("RECORDED" if r.get("recorded") else f"REJECTED: {r.get('reason')}")
            if r.get("entry"):
                print(yaml.safe_dump(r["entry"], allow_unicode=True, sort_keys=False))
        return 0 if r.get("recorded") else 1

    if args.claim_id:
        # #41 fix (orchestrator verification): forward --library so BLOCKED
        # guidance includes similar_lessons — previously dropped here, so the
        # acceptance criterion "BLOCKED 输出含 3 相似 lesson" failed via CLI.
        r = check_claim(workspace, args.claim_id, library=args.library)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            if r["state"] == "BLOCKED":
                _print_blocked(r)
            elif r["state"] == "OK_COVERED":
                print(f"OK: {args.claim_id} — analysis covers attempt {r.get('promotion_attempts')}")
            elif r["state"] == "TERMINAL":
                print(f"OK: {args.claim_id} — terminal ({r.get('status')}), no analysis needed")
            elif r["state"] == "OK_NO_PRIOR_FAILURE":
                print(f"OK: {args.claim_id} — no prior failed attempt (attempts={r.get('promotion_attempts')})")
            else:
                print(f"FAIL: claim {args.claim_id} not found")
        return 1 if r["state"] == "BLOCKED" else (2 if r["state"] == "NOT_FOUND" else 0)

    # scan mode
    # #41 fix: forward --library (same regression as the single-claim path).
    blocked = scan_workspace(workspace, library=args.library)
    if args.json:
        print(json.dumps({"blocked": blocked, "count": len(blocked)}, indent=2, ensure_ascii=False))
    elif blocked:
        print(f"=== {len(blocked)} claim(s) BLOCKED (failed attempt, no current analysis) ===\n")
        for d in blocked:
            _print_blocked(d)
            print()
    else:
        print("OK: no claims need failure analysis right now.")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
