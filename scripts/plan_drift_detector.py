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
  4. UNANSWERED_QUESTION: primary_question in task_spec with no answering
     claim — terminal answer = answered (#34 statuses); answering claim at
     any non-terminal status, or an OPEN claim_deps chain walking to an
     answerer, is IN-PROGRESS and not drift (#237 D1 liveness fix: mid-run
     the terminal claim cannot exist yet while sub-question claims are
     still being worked)
  5. STALE_NEXT_STEP: global_plan.txt "next steps" section references
     claim with terminal status (plan still thinks claim is OPEN)
  6. UNVERIFIED_EVIDENCE (#241): claim is status: PROVEN but has no
     runs/verify-redteam-*.md reality check, or its supporting fact
     (facts/F*.md with claim_id frontmatter) carries a low confidence
     tier — the first 5 classes are all "file A vs file B" consistency;
     this one asks whether the STATE FILE itself is wrong (files agree
     but reality was never verified). #237 D3: a record counts only when
     it survives the #827 content screen AND the unified log corroborates
     a hook-attributed verifier dispatch for the claim (advisory
     maker!=checker pin — a process bar, not authenticity; fail-closed)
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


# issue 275 batch-3 fail-open tracer — single home in _scriptlib (issue 292);
# the per-module copy (message token + rate-limit state) is the factory's
# per-tag binding, byte-identical to the former private def.
from _scriptlib import make_warn

warn = make_warn("plan_drift_detector")
import gate_telemetry as _gt
from status_defs import TERMINAL
from harness_common import utc_now_z as utc_now  # noqa: F401 — #863 Family F contract (863g mechanical check)

import argparse
import hashlib
import json
import os
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


# --- D1 (in-progress credit) via the claim_deps dependency chain ----------

def _depends_on_edges(claims: list, deps_path: Path) -> dict:
    """child -> [ancestors] edge map for the in-progress chain walk.

    Union of the claim_deps.yaml DAG (the MISSING_DEP_LINK owner — depends_on
    maps child to its parents) and the register's per-claim depends_on
    fields, so workspaces that never materialized the deps file still credit.
    """
    edges: dict = {}
    deps = _load_yaml(deps_path)
    for child, parents in ((deps or {}).get("depends_on", {}) or {}).items():
        edges[str(child)] = [str(p) for p in (parents or [])]
    for c in claims:
        cid = c.get("id")
        if not cid:
            continue
        own = edges.setdefault(str(cid), [])
        for p in (c.get("depends_on") or []):
            if str(p) not in own:
                own.append(str(p))
    return edges


def _transitive_ancestors(cid: str, edges: dict) -> set:
    """All ancestors of cid via the edges map (cycle-safe, visited-set)."""
    seen: set = set()
    stack = list(edges.get(cid, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    seen.discard(cid)
    return seen


def question_progress(qid: str, claims: list, deps_path: Path) -> str:
    """D1: is primary question qid answered, in-flight, or abandoned?

    Returns one of:
      "terminal"     an answering claim reached a TERMINAL status (the
                     pre-existing rule; REFUTED/NEGATIVE dead-ends answer
                     "no" and count);
      "in-progress"  an answering claim exists at a non-terminal status, OR
                     an OPEN claim's transitive claim_deps ancestors include
                     a qid-answering claim — the decomposition chain is
                     being worked and the answer is pending, not missing
                     (mid-run the terminal claim cannot exist yet while
                     sub-question claims are still OPEN);
      "none"         nothing answers qid and no open chain reaches an
                     answerer — the plan assumes an answer no claim targets
                     (the only drift state).

    Because the direct branch credits an answering claim at ANY status, a
    registered answerer is always credited directly; the chain walk carries
    the "walk to sub-question claims" semantics for register shapes where
    the answering claim appears only as a deps ancestor.
    """
    answerers = [c for c in claims if c.get("answers_question") == qid]
    if any((c.get("status") or "").upper() in TERMINAL_STATUSES
           for c in answerers):
        return "terminal"
    if answerers:
        return "in-progress"
    edges = _depends_on_edges(claims, deps_path)
    by_id = {str(c.get("id")): c for c in claims if c.get("id")}
    for c in claims:
        if (c.get("status") or "").upper() in TERMINAL_STATUSES:
            continue
        cid = str(c.get("id"))
        for anc in _transitive_ancestors(cid, edges):
            anc_claim = by_id.get(anc)
            if anc_claim is not None and anc_claim.get("answers_question") == qid:
                return "in-progress"
    return "none"


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


# --- D3 (verify-record provenance): log corroboration, maker!=checker -----

# Verifier-class agents (the blind_gate VERIFIER_AGENT_MARKERS set;
# mirrored — scripts/ is the private-API boundary the other direction).
VERIFIER_AGENT_MARKERS = ("kunglao-redteam", "verdict-scorer")

_DISPATCH_LOG_GLOB = "kunglao-*.jsonl"


def _load_dispatch_rows(workspace: Path) -> list:
    """All parseable unified-log rows under runs/logs/ (raw JSONL read).

    stdlib json over the day files — the detector stays import-light and
    read-only; corrupt lines are skipped, unreadable files degrade the
    corroboration set (fail-closed: missing evidence is not evidence).
    """
    logs = workspace / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows: list = []
    for log in sorted(logs.glob(_DISPATCH_LOG_GLOB)):
        try:
            lines = log.read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _corroborating_dispatch_claims(rows: list) -> set:
    """Claim ids whose verify evidence the unified log corroborates.

    A row corroborates claim C iff ALL hold (D3):
      - action contains 'dispatch' (the dispatch-lifecycle face —
        a hook WARN/trace row naming an agent is not dispatch evidence);
      - row claim == C in canonical form (_normalize_cid);
      - hook-attributed: actor starts with 'hook:' — a self-attested row
        (actor worker:* / verifier:*) does not corroborate the record.
        ADVISORY, NOT AUTHENTICITY: `emit()` takes the actor as free text
        (kunglao_log never gates on validate_actor at runtime) and runs/
        is a worker-writable surface, so a hand-crafted `hook:`-actor row
        also corroborates. The pin is a process bar — it raises adversary
        effort from trivial file creation to deliberate audit-row forgery
        and catches lazy/accidental self-minting — against exactly the
        adversary class this card names. Deliberately stricter than the
        blind_gate contract, which also accepts verifier: actors;
      - a verifier-class agent is named in the actor or detail.

    Fail-closed on every missing piece: no log, no rows, no match -> the
    record does not count. The honest path (dispatch the verifier through
    the gate) writes the corroboration itself. Row-record AUTHENTICITY
    binding is filed as follow-up (temporal-ordering item extension).
    """
    out: set = set()
    for row in rows:
        if "dispatch" not in str(row.get("action") or ""):
            continue
        actor = str(row.get("actor") or "")
        if not actor.startswith("hook:"):
            continue
        detail = str(row.get("detail") or "")
        if not any(m in actor or m in detail for m in VERIFIER_AGENT_MARKERS):
            continue
        claim = row.get("claim")
        if claim:
            out.add(_normalize_cid(str(claim)))
    return out


def corroborated_verified_ids(workspace: Path) -> set:
    """Claim ids whose verify-redteam record actually counts (D3).

    Intersection of the content screen (:func:`extract_verified_claim_ids`
    — semantics untouched; write_gate and the anti-template tests
    pin it) with log-corroborated claim ids. A verify record that no
    hook-attributed verifier dispatch stands behind is self-minted — the
    field-incident surface this class closes.
    """
    screened = extract_verified_claim_ids(workspace / "runs")
    if not screened:
        return set()
    return screened & _corroborating_dispatch_claims(
        _load_dispatch_rows(workspace))


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
        except OSError as exc:
            warn("find_stale_plan_on_new_evidence", f"{type(exc).__name__}: {exc}")
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
        except Exception as exc:
            warn("_emit_stale_plan_warns", f"{type(exc).__name__}: {exc}")


# --- issue-281: bounded-window plan-repair verification --------------------
#
# The plan-drift REJECT instructs a repair ("update global_plan.txt ...")
# that, before this face, nothing verified — the same dead-lock class the
# issue-249 remedy verification closed on the STALLED face ("knows the
# error but the next step doesn't move"). Mirror of that split: the drift
# REJECT itself still gates dispatch; this face adds ONLY visibility and
# escalation around the repair loop (plan_repair_verified closes it, a
# plan_repair_overdue escalation fires on un-repaired drift).

# The repair window, in DETECTION ROUNDS (named constant per the issue).
# The counter is FINGERPRINT-INDEPENDENT (review round 1, HIGH): every
# drift round advances it — a workspace whose drift set ROTATES between
# disjoint shapes accumulates rounds exactly like one with a stable
# fingerprint, so rotation can never reset the window. `rounds` reaching a
# multiple of the window re-escalates (cadence, not once-forever). The
# sinks drift guidance prose and templates/CLAUDE.md.base.tmpl carry the
# same number as a literal — cross-face sync pinned by
# tests/test_plan_repair_verify_281.py (this module is the single source).
PLAN_REPAIR_WINDOW_ROUNDS = 3

PLAN_REPAIR_STATE_FILE = "runs/plan-repair-state.json"
PLAN_REPAIR_OPEN = "open"
PLAN_REPAIR_VERIFIED = "verified"
PLAN_REPAIR_OVERDUE_ACTION = "plan_repair_overdue"
PLAN_REPAIR_VERIFIED_ACTION = "plan_repair_verified"


def repair_fingerprint(drifts: list) -> dict:
    """Canonical episode fingerprint: one item per (drift class, claim).

    `TYPE:claim_id` items describe the CURRENT drift shape for telemetry;
    they are deliberately NOT the verification unit (review round 1:
    disjointness is not repair) — the window advances on ANY drift round
    and verified fires only on a genuinely clean round.
    """
    return {
        "items": sorted({f"{d['type']}:{d.get('claim_id')}" for d in drifts}),
        "classes": sorted({d["type"] for d in drifts}),
    }


def _write_repair_state(state_path: Path, state: dict) -> None:
    """Fail-open state write (telemetry never breaks the check). tmp +
    os.replace so a concurrent reader sees the old or the new file, never
    a torn one (review round 1, LOW)."""
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_name(state_path.name + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        os.replace(tmp, state_path)
    except OSError as exc:
        print(f"[kunglao-agent] plan-repair state write skipped: {exc!r}",
              file=sys.stderr)


def _repair_episode_detail(state: dict) -> dict:
    fp = state.get("fingerprint") or {}
    return {"items": fp.get("items") or [], "classes": fp.get("classes") or [],
            "rounds": state.get("rounds") or 0,
            "window": PLAN_REPAIR_WINDOW_ROUNDS}


def _close_repair_episode(state: dict) -> dict:
    return {**state, "status": PLAN_REPAIR_VERIFIED, "closed": utc_now()}


def _repair_emit(workspace: Path, action: str, detail: dict) -> None:
    """Fail-open event face (kunglao_record posture — same as the class-7
    WARN emit above)."""
    try:
        from kunglao_log import emit
        emit(workspace, actor="orchestrator", action=action,
             detail=json.dumps(detail, ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — observability is best-effort,
        # never silent (the annotated form the silent-except ratchet wants)
        print(f"[kunglao-agent] plan-repair telemetry skipped: {exc!r}",
              file=sys.stderr)


def _plan_repair_tick(workspace: Path, drifts: list) -> dict | None:
    state_path = Path(workspace) / PLAN_REPAIR_STATE_FILE
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # fail-open, annotated: an unreadable episode never blocks or
            # crashes the detector — verification skips for this round.
            print("[kunglao-agent] plan-repair state unreadable - repair "
                  "verification skipped (fail-open)", file=sys.stderr)
            return None
    if not drifts:
        if not state or state.get("status") != PLAN_REPAIR_OPEN:
            return None  # no open episode: clean rounds write nothing
        # verified means REPAIR, not rotation (review round 1, HIGH): the
        # only face that closes an episode positively is a genuinely
        # clean round — the plan files actually agree with the register.
        detail = _repair_episode_detail(state)
        _repair_emit(workspace, PLAN_REPAIR_VERIFIED_ACTION, detail)
        print(f"PLAN_REPAIR_VERIFIED: workspace drift-free after "
              f"{detail['rounds']} drift round(s) - amendment verified "
              f"(issue-281)")
        closed = _close_repair_episode(state)
        _write_repair_state(state_path, closed)
        return closed
    fp = repair_fingerprint(drifts)
    if state and state.get("status") == PLAN_REPAIR_OPEN:
        rounds = int(state.get("rounds") or 0) + 1
        # a CHANGED fingerprint supersedes the recorded shape silently —
        # same episode, no event, the cumulative window does not reset
        # (the workspace has been drifting continuously either way).
        state = {**state, "fingerprint": fp, "rounds": rounds,
                 "updated": utc_now()}
    else:
        # first drift round of an episode: open silently (no output
        # change — the REJECT report is the whole operator face), the
        # round itself counts (rounds starts at 1).
        state = {"status": PLAN_REPAIR_OPEN, "fingerprint": fp,
                 "rounds": 1, "opened": utc_now(), "updated": utc_now()}
    if state["rounds"] % PLAN_REPAIR_WINDOW_ROUNDS == 0:
        # escalation cadence: fires at rounds == WINDOW, 2*WINDOW, ... —
        # once per window of continued drift, never permanently silent
        # (review round 1, LOW: post-overdue silence), never spam.
        detail = _repair_episode_detail(state)
        _repair_emit(workspace, PLAN_REPAIR_OVERDUE_ACTION, detail)
        print(f"PLAN_REPAIR_OVERDUE: drift persisted for "
              f"{state['rounds']} detection round(s) "
              f"(window={PLAN_REPAIR_WINDOW_ROUNDS}) - the plan amendment "
              f"did not land; escalate to the operator (issue-281)",
              file=sys.stderr)
    _write_repair_state(state_path, state)
    return state


def plan_repair_tick(workspace: Path, drifts: list) -> dict | None:
    """issue-281: the bounded-window amendment check (the plan-drift
    mirror of the issue-249 remedy verification), run by check() on EVERY
    detection round — operator CLI, --auto dispatch-gate face and the
    hooks gate subprocess all advance the same episode state; one source.

    Episode semantics (state file runs/plan-repair-state.json):
      - a drift round with no open episode OPENS one (rounds=1) —
        silently; the REJECT report is the whole operator face;
      - EVERY drift round advances the cumulative `rounds` counter,
        regardless of fingerprint (a rotating drift shape cannot reset
        the window — review round 1 HIGH); a changed fingerprint
        supersedes the recorded shape in place, with no event;
      - at every multiple of PLAN_REPAIR_WINDOW_ROUNDS a
        plan_repair_overdue event + stderr escalation fires (cadence —
        re-escalates each window of continued drift); never a new block
        (the drift REJECT itself still gates dispatch);
      - ONLY a genuinely clean round closes the episode, as verified
        (plan_repair_verified event) — drift changing shape is not
        evidence of repair;
      - a clean round with no open episode writes nothing.

    Fail-open: the tick never alters check()'s verdict. Unreadable state
    skips verification (annotated); any unexpected error is caught by the
    wrapper and reported on stderr. STALE_PLAN_ON_NEW_EVIDENCE warns never
    enter `drifts` and can never open an episode (observe-first stays
    observe-only). Adversarial-write acceptance: runs/ is a worker surface
    (write_guard's contract covers the four carriers only), so the state
    file is forgeable — accepted, the face is additive observability and
    the REJECT verdict never depends on it (design.md, review round 1
    MEDIUM).
    """
    try:
        return _plan_repair_tick(workspace, drifts)
    except Exception as exc:  # noqa: BLE001 — verification must never break
        # the detector (annotated fail-open, silent-except ratchet form)
        print(f"[kunglao-agent] plan-repair verification skipped: {exc!r}",
              file=sys.stderr)
        return None


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
        # D1: UNANSWERED_QUESTION is a liveness-drift only when nothing
        # is IN FLIGHT toward the answer. A terminal answering claim answers
        # the question (PROVEN/VERIFIED confirm; REFUTED/NEGATIVE answer
        # "no"; DEFERRED/STALE record a dead-end — v1.9.29). An answering
        # claim at any non-terminal status, or an OPEN claim_deps chain
        # walking to an answerer, is in-progress: mid-run the terminal
        # claim cannot exist yet while sub-question claims are still OPEN.
        progress = question_progress(qid, claims, deps_path)
        if progress in ("terminal", "in-progress"):
            continue
        drifts.append({
            "type": "UNANSWERED_QUESTION",
            "claim_id": qid,
            "fix": (f"primary question {qid} has no terminal-status "
                    "answering claim and no in-progress answering chain"),
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
    # D3: a record counts only when the unified log corroborates a
    # hook-attributed verifier dispatch for the claim (advisory maker!=
    # checker pin — a process bar, not authenticity; fail-closed).
    # File existence + content screening alone was the
    # forgery surface the 2026-09-12 wbtest incident walked through.
    verified_ids = corroborated_verified_ids(workspace)
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
        plan_repair_tick(workspace, drifts)  # issue-281: repair-window face
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
    plan_repair_tick(workspace, drifts)  # issue-281: repair-window face
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
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())