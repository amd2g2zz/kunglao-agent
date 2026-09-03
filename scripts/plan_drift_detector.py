# -*- coding: utf-8 -*-
"""plan_drift_detector.py - detect when plan files lag behind reality.

User pain point (verbatim, in Chinese): "实际进度状态和计划与文件里面的不匹配 - 比如开始规划的时候
有15个任务，但是随着推进出现重新规划 任务分解 任务废弃，相关文件没跟上"
("actual progress state and the plan disagree with the files — e.g. 15 tasks
at planning time, but re-planning/decomposition/obsolescence as work
progressed while the files never caught up")

6 drift types detected:
  1. ORPHAN_CLAIM: claim in claim-register.yaml but NOT in global_plan.txt
     (mid-iteration discovery not logged in plan)
  2. STALE_PLAN_ENTRY: global_plan.txt lists claim that no longer exists
     in claim-register.yaml (abandoned/decomposed, not removed)
  3. MISSING_DEP_LINK: claim has parent_claim but claim_deps.yaml doesn't
     link it (decomposition not reflected in DAG)
  4. UNANSWERED_QUESTION: primary_question in task_spec has no PROVEN
     claim answering it (plan assumes answer that won't come)
  5. STALE_NEXT_STEP: global_plan.txt "next steps" section references
     claim with terminal status (plan still thinks claim is OPEN)
  6. UNVERIFIED_EVIDENCE (#241): claim is status: PROVEN but has no
     runs/verify-redteam-*.md reality check, or its supporting fact
     (facts/F*.md with claim_id frontmatter) carries a low confidence
     tier — the first 5 classes are all "file A vs file B" consistency;
     this one asks whether the STATE FILE itself is wrong (files agree
     but reality was never verified)
  7. STALE_PLAN_ON_NEW_EVIDENCE (#497, WARN-only): new evidence (a
     #495 failure_analysis record, a promoted obstacle claim) landed
     AFTER the last plan update while the plan was never re-derived —
     the whitelist-inverted drift (the plan is a derived view of the
     model per #498: model changed + plan unchanged = drift). Printed
     as WARN (observe-first), NEVER counted toward the exit codes.

Usage:
  python plan_drift_detector.py <workspace> [--apply]
  python plan_drift_detector.py <workspace> [--auto]
Exit codes:
  0 = no drift (WARN-only output still exits 0 — observation, not a gate)
  1 = drift detected (B1o blocker)
  2 = HARD_PAUSE: 3+ drift warnings in same session
Auto-integration mode (issue #602, --auto flag):
  Used by hooks/dispatch_gate.py L621 as a PreToolUse wire-up. Maps drift
  severity to a gate exit code so the dispatch path can BLOCK / SATURATE
  on plan-evidence disagreement WITHOUT changing the operator-facing CLI
  semantics (--auto is purely an integration face, NOT a new behavior
  layer; operator --apply / no-flag still returns 1 / 2 for the script's
  exit-table consumers).
  --auto exit codes:
    0  = no drift                                  -> dispatch proceeds
    3  = WARN-only (STALE_PLAN_ON_NEW_EVIDENCE, observe-first) -> SATURATED
    2  = 1+ non-WARN drift                         -> BLOCKED (hard REJECT)
"""
from __future__ import annotations
import gate_telemetry as _gt
from status_defs import TERMINAL
from harness_common import utc_now_z as utc_now  # noqa: F401 — #863 Family F contract (863g mechanical check)

import argparse
import hashlib
import re
import sys
from pathlib import Path

import yaml

TERMINAL_STATUSES = TERMINAL  # #34: single source of truth (was a 6-value literal here)

# #241: a PROVEN claim is only as good as its reality check. Confidence tiers
# below even odds (ICD-203 7-tier ladder) mean
# the fact is not reality-verified evidence; "suspected" is the legacy name
# mapping to roughly_even. literal "low" accepted for 3-tier legacy facts.
LOW_CONFIDENCE = frozenset({
    "low", "roughly_even", "unlikely", "very_unlikely", "almost_no_chance",
    "suspected",
})

# #241: only maker-stamped PROVEN claims are checked — VERIFIED means an
# independent checker already ran; REFUTED/NEGATIVE are closed by definition.
UNVERIFIED_CHECK_STATUSES = frozenset({"PROVEN"})




def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _read_text(p):
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def extract_claim_ids_from_plan(plan_path: Path) -> set:
    if not plan_path.exists():
        return set()
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"C-\d+", text))


def extract_claim_ids_from_deps(deps_path: Path) -> set:
    if not deps_path.exists():
        return set()
    deps = _load_yaml(deps_path)
    out = set()
    for child, parents in (deps or {}).get("depends_on", {}).items():
        out.add(child)
        for p in (parents or []):
            out.add(p)
    return out


def extract_next_step_claims(plan_path: Path) -> set:
    if not plan_path.exists():
        return set()
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    in_next = False
    out = set()
    for line in text.splitlines():
        if re.search(r"^##\s*(next step|next:|next iter|next claim)", line, re.IGNORECASE):
            in_next = True
            continue
        if in_next and line.startswith("## "):
            in_next = False
        if in_next:
            out.update(re.findall(r"C-\d+", line))
    return out


def _normalize_cid(raw: str) -> str:
    """Normalize any claim-id spelling to canonical C-NNN form.

    Register ids are C-NNN (dashed) but verify/plan file names spell ids
    both ways — runs/verify-redteam-C335.md (undashed, real workspace),
    verify-redteam-C001.md, verify-redteam-C-7.md. Comparison happens in
    canonical form so all three count as the same claim.
    """
    m = re.search(r"C-?(\d+)", raw or "")
    return f"C-{m.group(1)}" if m else (raw or "")


def _read_frontmatter(p: Path) -> dict:
    """YAML frontmatter of a facts/F*.md file; {} when absent/unparseable."""
    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def extract_verified_claim_ids(runs_dir: Path) -> set:
    """Claim ids covered by runs/verify-redteam-*.md files (canonical form).

    A redteam verify run is the independent reality check behind a PROVEN
    claim (maker-checker: worker=maker, verifier=checker). #827: existence
    + claim-id-in-filename was the entire check, and a 265ms burst of 8
    byte-identical substitution templates defeated it — existence is NOT
    verification. Files must survive the #827 content-level screening
    (:func:`credible_redteam_files`); the verdict CONTENT remains
    outcome_capture.py's business.
    """
    out = set()
    if not runs_dir.exists():
        return out
    for p in credible_redteam_files(runs_dir):
        m = re.search(r"C-?\d+", p.name)
        if m:
            out.add(_normalize_cid(m.group(0)))
    return out


# --- #827: redteam-file credibility screening (anti batch-template) -------

_VERDICT_MARKER_RE = re.compile(r"red[-_ ]?team", re.IGNORECASE)
_VERDICT_WORD_RE = re.compile(
    r"\b(CONFIRMED|REFUTED|UNVERIFIED|GAP|verdict)\b", re.IGNORECASE)
_BURST_MIN_FILES = 3
_BURST_WINDOW_S = 5.0


def _template_hash(text: str) -> str:
    """id-打码归一化体 hash：claim/fact id → §，空白折叠，大小写归一。"""
    collapsed = re.sub(
        r"\s+", " ", _REDACT_IDS_RE.sub("§", text)).strip().lower()
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


_REDACT_IDS_RE = re.compile(r"C-?\d+|F-?\d+")


def credible_redteam_files(runs_dir: Path) -> list:
    """#827 反模板筛选层：verify-redteam-*.md → 可信文件列表。

    两条内容级规则（cheap hardening 层；#825 dispatch ledger 落地后由其
    接管为身份级修复）：
      (b) 授权标记：body 须含 redteam 词 + verdict 词——canonical 生产者
          词表（"RED-TEAM VERDICT:" / "## redteam <fid>\nverdict:"），事故
          模板（"KEEP status: PROVEN"）不命中
      (a) 爆发簇：≥3 个 marker 通过的文件归一化体全同（id 打码后 sha256
          相等）且 mtime 跨度 ≤5s → 整簇排除（模板 fan-out 特征；独立于
          (b)，marker 齐全的同构簇同样死）
    结构门语义（fail-closed on 判定）；不可读文件跳过。既有语义保留：
    1-2 个同构文件（<3）与 mtime 分散的同构文件不触发簇排除。
    """
    if not runs_dir.exists():
        return []
    passing: list = []
    for p in sorted(runs_dir.glob("verify-redteam-*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if (_VERDICT_MARKER_RE.search(text)
                and _VERDICT_WORD_RE.search(text)):
            passing.append(p)
    groups: dict = {}
    for p in passing:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            mtime = p.stat().st_mtime
        except OSError:
            continue
        groups.setdefault(_template_hash(text), []).append((p, mtime))
    out: list = []
    for group in groups.values():
        if len(group) >= _BURST_MIN_FILES:
            times = sorted(t for _, t in group)
            if times[-1] - times[0] <= _BURST_WINDOW_S:
                continue
        out.extend(p for p, _ in group)
    return sorted(out)


def extract_low_confidence_claim_ids(facts_dir: Path) -> set:
    """Claim ids whose fact files carry low-confidence frontmatter.

    A fact is facts/F<NNN>*.md with YAML frontmatter (id/status/confidence/
    claim_id). A supporting fact at or below even odds means the claim is
    PROVEN on shaky ground — file-level consistency says nothing about it.
    """
    out = set()
    if not facts_dir.exists():
        return out
    for p in sorted(facts_dir.glob("F*.md")):
        fm = _read_frontmatter(p)
        cid = fm.get("claim_id")
        conf = fm.get("confidence")
        if cid and conf and str(conf).strip().lower() in LOW_CONFIDENCE:
            out.add(_normalize_cid(str(cid)))
    return out


def find_stale_plan_on_new_evidence(workspace: Path, plan_path, claims: list) -> list:
    """#497: stale-plan-on-new-evidence — the whitelist-inverted drift.

    The first 6 classes ask whether the plan files AGREE; none asks whether
    the plan was RE-DERIVED after the world model changed (#498: the plan is
    a derived view — model changed + plan unchanged is the real drift, while
    deviating from a stale plan after new evidence is the NORM). Mechanical
    proxy, mtime-anchored and namespace-independent:
      - any analyses/failure-*.yaml (#495 failure_analysis) newer than the
        plan -> new failure knowledge the plan never saw;
      - claim-register.yaml carrying a promoted obstacle claim
        (origin: failure-obstacle) and newer than the plan -> a new DAG
        node the plan never absorbed.
    Deliberately WARN-level (observe-first per issue #497 What 4): callers
    print these but NEVER count them toward the drift exit codes. Strictly
    greater-than comparison — equal mtimes mean the plan already saw the
    evidence (fail-open to no warning)."""
    warns = []
    if not plan_path or not plan_path.exists():
        return warns
    try:
        plan_mtime = plan_path.stat().st_mtime
    except OSError:
        return warns
    adir = workspace / "analyses"
    if adir.exists():
        for p in sorted(adir.glob("failure-*.yaml")):
            try:
                if p.stat().st_mtime > plan_mtime:
                    warns.append({
                        "type": "STALE_PLAN_ON_NEW_EVIDENCE",
                        "claim_id": p.stem.removeprefix("failure-"),
                        "fix": (f"analyses/{p.name} landed after the last plan "
                                f"update — re-derive {plan_path.name} on the new "
                                f"evidence (#497)"),
                    })
            except OSError:
                continue
    reg_path = workspace / "claim-register.yaml"
    has_obstacle = any(c.get("origin") == "failure-obstacle" for c in claims)
    if has_obstacle and reg_path.exists():
        try:
            if reg_path.stat().st_mtime > plan_mtime:
                warns.append({
                    "type": "STALE_PLAN_ON_NEW_EVIDENCE",
                    "claim_id": "claim-register",
                    "fix": ("obstacle claim promoted (#495) after the last plan "
                            f"update — re-derive {plan_path.name} on the new "
                            "evidence (#497)"),
                })
        except OSError:
            pass
    return warns


def _print_stale_plan_warns(warns: list) -> None:
    """WARN block for stale-plan-on-new-evidence (observation, not a gate)."""
    if not warns:
        return
    print(f"WARN (observe-only): {len(warns)} STALE_PLAN_ON_NEW_EVIDENCE item(s) —")
    print("  new evidence landed after the last plan update; the plan is a derived")
    print("  view and should be re-derived (model changed -> re-plan is the")
    print("  norm; only an information-free pivot is not):")
    for w in warns[:5]:
        print(f"    - {w['claim_id']}: {w['fix']}")
    if len(warns) > 5:
        print(f"    ... and {len(warns) - 5} more")


def _emit_stale_plan_warns(workspace: Path, warns: list) -> None:
    """#459 observability: class-7 WARN face -> unified event log, one event
    per item (claim carries the warn's claim_id so a tail can filter). The
    warn is observe-only on stdout and never changes the exit code — neither
    may the emit (fail-open, kunglao_record posture)."""
    for w in warns:
        try:
            from kunglao_log import emit
            emit(workspace, actor="orchestrator",
                 action="stale_plan_on_new_evidence",
                 claim=w.get("claim_id"), detail=w.get("fix"))
        except Exception:
            pass


@_gt.telemetry('plan_drift_detector')
def check(workspace: Path, active_only: bool = False) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    claim_ids = {c.get("id") for c in claims if c.get("id")}

    # --active-only: check the current plan file only; otherwise all plan
    # candidates. (Phase-level plans that use a different claim-id namespace
    # are handled by `plan_refers_to_register` below, not by globbing.)
    if active_only:
        plan_path_candidates = [workspace / "global_plan.txt"]
    else:
        plan_path_candidates = [
            workspace / "global_plan.txt",
            workspace / "global_plan.yaml",
            workspace / "plan.md",
        ]
    plan_path = next((p for p in plan_path_candidates if p.exists()), None)
    plan_ids = extract_claim_ids_from_plan(plan_path) if plan_path else set()
    next_step_ids = extract_next_step_claims(plan_path) if plan_path else set()

    # v1.9.29: a plan that shares NO claim-id namespace with the register is a
    # phase-level / legacy plan — ORPHAN_CLAIM and STALE_PLAN_ENTRY would be
    # structural false positives (e.g. plan cites C-07 while register uses
    # C-200+). Plan-level drift is only meaningful when plan and register
    # reference the same claim ids.
    plan_refers_to_register = bool(plan_ids & claim_ids)

    deps_path = workspace / "claim_deps.yaml"
    extract_claim_ids_from_deps(deps_path)

    tspec = _load_yaml(workspace / "task_spec.yaml")
    primary_questions = tspec.get("primary_questions", []) or []

    drifts = []

    if plan_refers_to_register:
        for c in claims:
            cid = c.get("id")
            if cid and plan_path and cid not in plan_ids:
                drifts.append({
                    "type": "ORPHAN_CLAIM",
                    "claim_id": cid,
                    "fix": f"add claim {cid} to {plan_path.name} (mid-iteration discovery not logged)",
                })

    if plan_path and plan_refers_to_register:
        for cid in plan_ids:
            if cid not in claim_ids:
                drifts.append({
                    "type": "STALE_PLAN_ENTRY",
                    "claim_id": cid,
                    "fix": f"remove claim {cid} from {plan_path.name} (no longer in claim-register)",
                })

    for c in claims:
        cid = c.get("id")
        parent = c.get("parent_claim")
        if cid and parent and deps_path.exists():
            deps = _load_yaml(deps_path)
            depends_on = (deps or {}).get("depends_on", {}) or {}
            if parent not in depends_on.get(cid, []):
                drifts.append({
                    "type": "MISSING_DEP_LINK",
                    "claim_id": cid,
                    "fix": f"add '{parent}' to depends_on[{cid}] in {deps_path.name} (decomposition not in DAG)",
                })

    for q in primary_questions:
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid:
            continue
        # a primary question is ANSWERED when an answering claim reached any
        # terminal status — PROVEN/VERIFIED confirm, REFUTED/NEGATIVE answer
        # "no", DEFERRED/STALE record a dead-end. (v1.9.29: TERMINAL_STATUSES
        # already includes REFUTED/NEGATIVE; previously only PROVEN/VERIFIED
        # counted, so a yes/no question answered "no" flagged as unanswered.)
        answered = any(c.get("answers_question") == qid and (c.get("status") or "").upper() in TERMINAL_STATUSES for c in claims)
        if not answered:
            drifts.append({
                "type": "UNANSWERED_QUESTION",
                "claim_id": qid,
                "fix": f"primary question {qid} has no terminal-status answering claim",
            })

    if plan_path and plan_refers_to_register:
        for cid in next_step_ids:
            c = next((c for c in claims if c.get("id") == cid), None)
            if c is None:
                continue
            status = (c.get("status") or "").upper()
            if status in TERMINAL_STATUSES:
                drifts.append({
                    "type": "STALE_NEXT_STEP",
                    "claim_id": cid,
                    "fix": f"remove claim {cid} from 'next step' section (status={status})",
                })

    # #241: UNVERIFIED_EVIDENCE — the first 5 classes check whether the PLAN
    # files agree with each other; none asks whether the REGISTER itself is
    # wrong. A claim at status: PROVEN is drift when its reality check never
    # happened (no runs/verify-redteam-*.md on disk) or when its supporting
    # facts carry low confidence (PROVEN on shaky ground).
    verified_ids = extract_verified_claim_ids(workspace / "runs")
    low_confidence_ids = extract_low_confidence_claim_ids(workspace / "facts")
    for c in claims:
        cid = c.get("id")
        if (c.get("status") or "").upper() not in UNVERIFIED_CHECK_STATUSES:
            continue
        if cid not in verified_ids:
            drifts.append({
                "type": "UNVERIFIED_EVIDENCE",
                "claim_id": cid,
                "fix": f"claim {cid} is PROVEN but has no runs/verify-redteam-*.md file (reality check missing)",
            })
        if cid in low_confidence_ids:
            drifts.append({
                "type": "UNVERIFIED_EVIDENCE",
                "claim_id": cid,
                "fix": f"claim {cid} is PROVEN but a supporting fact carries low confidence",
            })

    # #497: stale-plan-on-new-evidence — WARN-level by design (observe-first):
    # collected here, printed below, NEVER counted toward the exit codes.
    stale_plan_warns = find_stale_plan_on_new_evidence(workspace, plan_path, claims)
    # #459: the class-7 WARN also reaches the unified event log (the Orient
    # layer should not have to re-derive mtimes to see the drift).
    _emit_stale_plan_warns(workspace, stale_plan_warns)

    if not drifts:
        print("OK: no plan drift detected")
        _print_stale_plan_warns(stale_plan_warns)
        return 0

    by_type = {}
    for d in drifts:
        by_type.setdefault(d["type"], []).append(d)

    print(f"REJECT: {len(drifts)} plan-drift(s) detected (B1o plan-drift blocker):")
    for dtype, items in sorted(by_type.items()):
        print(f"\n  {dtype} ({len(items)}):")
        for d in items[:5]:
            print(f"    - {d['claim_id']}: {d['fix']}")
        if len(items) > 5:
            print(f"    ... and {len(items) - 5} more")
    _print_stale_plan_warns(stale_plan_warns)
    # v1.9.29: 3+ drift warnings in the same run = HARD_PAUSE (exit 2),
    # per the docstring contract that the implementation previously lacked.
    # (#497: STALE_PLAN_ON_NEW_EVIDENCE warns are NOT drift warnings for
    # this threshold — they never enter `drifts`.)
    return 2 if len(drifts) >= 3 else 1


def check_auto(workspace: Path, active_only: bool = False) -> int:
    """#602: integration face for hooks/dispatch_gate.py L621 wire-up.

    Re-runs check() and remaps its exit code to the dispatch-gate contract:
      - no drift                          -> 0 (proceed, no BLOCKED/SATURATED)
      - WARN-only (STALE_PLAN_ON_NEW_EVIDENCE observe-first) -> 3 (SATURATED)
      - 1+ non-WARN drift (ORPHAN_CLAIM / STALE_PLAN_ENTRY / MISSING_DEP_LINK /
        UNANSWERED_QUESTION / STALE_NEXT_STEP / UNVERIFIED_EVIDENCE) -> 2 (BLOCKED)

    The remapping is informational ONLY — it does not change what `check()`
    reports (the drift types and counts) and does not change the
    operator-facing CLI exit codes (those stay 0/1/2). Auto mode is the
    integration face for the dispatch gate; the operator-facing contract
    stays byte-identical.

    Output ordering with the underlying check():
      - The underlying check() prints its full report (REJECT/WARN/OK).
      - check_auto() prints ONE summary line classifying the severity
        ("DRIFT_AUTO: ok / warn-only / blocked") so the operator tail
        can grep for it; it does NOT suppress the underlying report.
    """
    drifts_rc = check(workspace, active_only=active_only)
    # check() prints to stdout; we add one classification line below.
    if drifts_rc == 0:
        # no drift at all — distinguish "no drift at all" from "WARN-only
        # exit 0". check() collapses both to rc=0; the STALE_PLAN_ON_NEW_
        # EVIDENCE warns are surfaced only as WARN lines in stdout.
        # If we already saw WARN output above we are in the WARN-only path.
        # Cheap heuristic: a WARN-only run prints "WARN" to stdout.
        # check() already consumed stdout; we cannot read what it wrote.
        # Instead, peek at the workspace ourselves for evidence-newer-than-plan
        # signals and surface the WARN-only classification here. This is the
        # SAME mtime comparison check() runs — duplicated here only to
        # decide the auto exit code, not to print anything new.
        try:
            warns = find_stale_plan_on_new_evidence(
                workspace,
                _first_existing_plan(workspace),
                _load_yaml(workspace / "claim-register.yaml").get("claims", []) or [],
            )
        except Exception:
            warns = []
        if warns:
            print("DRIFT_AUTO: warn-only (STALE_PLAN_ON_NEW_EVIDENCE) -> SATURATED")
            return 3
        print("DRIFT_AUTO: ok -> proceed")
        return 0
    # 1 or 2 from underlying check() — both mean "non-WARN drift detected"
    # (1 = drift detected, 2 = HARD_PAUSE / 3+ warnings which IS a non-WARN
    # drift event from the gate's perspective).
    print(f"DRIFT_AUTO: drift-severe (check rc={drifts_rc}) -> BLOCKED")
    return 2


def _first_existing_plan(workspace: Path):
    """Return the first existing plan-path candidate, or None. Mirrors
    check()'s plan-path resolution so check_auto() can ask the same
    question when classifying WARN-only output. Internal helper, not
    part of the public surface."""
    for name in ("global_plan.txt", "global_plan.yaml", "plan.md"):
        p = workspace / name
        if p.exists():
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect plan files drifting behind reality")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--active-only", action="store_true",
                        help="check only the current plan file (global_plan.txt), not all candidates")
    parser.add_argument("--auto", action="store_true",
                        help="integration face: remap exit codes to "
                             "0=no-drift / 3=WARN-only(SATURATED) / 2=blocked "
                             "for hooks/dispatch_gate.py L621 wire-up")
    args = parser.parse_args()
    if args.auto:
        return check_auto(Path(args.workspace), active_only=args.active_only)
    return check(Path(args.workspace), active_only=args.active_only)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())