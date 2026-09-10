# -*- coding: utf-8 -*-
"""register_proven_gate.py — claim-register →PROVEN evidence gate (#819).

豆包 pathology (#819 v2): the register's →PROVEN migration had no evidence
predicate — whoever edited claim-register.yaml to PROVEN "was" the settlement,
verify results never participated. Fail-closed: a →PROVEN transition requires
  (a) latest verify-note outcome == passes, AND
  (b) red-team ran for the claim AND its latest result != REFUTED,
or a waiver runs/proven-waiver-<claim>.md with non-empty justify.

Evidence source: runs/*.md under the outcome_capture conventions
("-verify-" / "verify-redteam" in name), parsed with outcome_capture's own
regexes; latest = max mtime. Posture: fail-closed (structure gate).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

import verifier_identity as vi  # noqa: F401  (#825)
from outcome_capture import _parse_run
from status_defs import TERMINAL  # single source (#34, #95)

PROVEN = "PROVEN"
WAIVER_PREFIX = "proven-waiver-"
WAIVER_JUSTIFY_RE = re.compile(r"^\s*justify:\s*(\S.*)$", re.M)

# #880: negative-sample terminal statuses — the settlement face burns the
# claim's lesson lineage here (see emit_settlements).
NEGATIVE_SETTLEMENTS = {"REFUTED", "NEGATIVE", "DEAD"}

# ---------------- evidence classes (issue 215) -------------------------------
#
# The wbtest field run proved algorithm-recovery claims with unzip+grep
# string facts. The claim side is identified from the register's own text
# (statement/title) — a new scope field nothing writes would be
# self-declaration, the trust posture issue 819 exists to reject — and the
# evidence side from the FACT frontmatter's declared class. Deliberately
# NOT the `source` enum: triage string facts carry `static-decompile`
# there, which is exactly the masquerade this closes.
ALGO_SCOPE_KEYWORDS = (
    "key_schedule", "key schedule", "key expansion",
    "crypto_constant", "crypto constant", "crypto constants",
    "state_machine", "state machine",
    "algorithm_verify", "algorithm verify", "algorithm verification",
    "algorithm recovery", "algorithm-recovery",
)

_SEP_RE = re.compile(r"[-_]+")


def _fold_separators(text: str) -> str:
    """Lowercase with _ / - folded to spaces: the same word break whatever
    the spelling (key_schedule == key-schedule == key schedule)."""
    return _SEP_RE.sub(" ", text.lower())


TRIAGE_GRADE_CLASS = "triage"
VALID_EVIDENCE_CLASSES = (TRIAGE_GRADE_CLASS, "decompile", "dynamic")
# Classes that can carry an algorithm-recovery claim: decompiled source /
# decompiler-grade index or taint, and runtime observation. Triage-grade
# string facts alone cannot.
ALGO_GRADE_CLASSES = ("decompile", "dynamic")


def _load_claims(text: str) -> dict:
    """claim-id -> the claim mapping; {} when the text is not a parsable
    register."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for c in data.get("claims") or []:
        if isinstance(c, dict):
            cid = str(c.get("id", "") or "").strip()
            if cid:
                out[cid] = c
    return out


def _load_statuses(text: str) -> dict:
    """claim-id -> status (uppercased); {} when not a parsable register."""
    return {cid: str(c.get("status", "") or "").strip().upper()
            for cid, c in _load_claims(text).items()}


def _fact_claim_refs(fm: dict) -> list:
    """Every claim id a fact cites: claim_id / claim_ids / claims.

    The extension-layer `claim` field is deliberately NOT read — it is the
    claim STATEMENT (free text), not a reference (same rule as issue 532)."""
    refs: list = []
    for key in ("claim_id", "claim_ids", "claims"):
        value = fm.get(key)
        if isinstance(value, str):
            refs.append(value.strip())
        elif isinstance(value, (list, tuple)):
            refs.extend(str(v).strip() for v in value)
    return [r for r in refs if r]


def _evidence_class(fm: dict) -> str:
    """The fact's declared evidence class, defaulting to the WEAKEST one.

    Fail-closed: absent or unrecognized reads as triage, never as a claim
    of strength (an undeclared class is not evidence of decompilation)."""
    value = str(fm.get("evidence_class") or "").strip().lower()
    return value if value in VALID_EVIDENCE_CLASSES else TRIAGE_GRADE_CLASS


def facts_by_claim(ws: Path) -> dict:
    """claim-id -> [fact frontmatter dicts] from facts/*.md.

    Single-parser rule: lint_facts owns the frontmatter dialect (PyYAML
    plus the tolerant subset fallback) and this gate consumes it rather
    than growing a second parser. An unreadable or unparsable fact is
    skipped — it carries no class, and the register-side predicates still
    gate its claim."""
    out: dict = {}
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return out
    try:
        from lint_facts import _load_fact
    except ImportError:
        return out
    for p in sorted(facts_dir.glob("*.md")):
        try:
            fm = _load_fact(p)
        except Exception:  # noqa: BLE001 — a broken fact never blocks the gate
            continue
        if not isinstance(fm, dict):
            continue
        for ref in _fact_claim_refs(fm):
            out.setdefault(ref, []).append(fm)
    return out


def algorithm_scope(claim: dict) -> str | None:
    """The matched scope keyword when the claim reads as algorithm-recovery
    (issue 215), else None.

    Read from the register's own text; the KEEP list is the four classes
    the issue names, in snake_case and prose spellings. Separator spelling
    is folded before matching (_ / - / space are the same word break), so
    `key-schedule` is not a scope escape hatch."""
    text = " ".join(str(claim.get(k) or "")
                    for k in ("statement", "title", "answers_question"))
    folded = _fold_separators(text)
    for keyword in ALGO_SCOPE_KEYWORDS:
        if _fold_separators(keyword) in folded:
            return keyword
    return None


def evidence_class_violation(claim_id: str, claim: dict,
                             facts: list) -> str | None:
    """The evidence-class admission reason (issue 215), None when admitted.

    Boundary: a claim with NO fact file has no fact-frontmatter class to
    read, so the issue 819 verify/redteam predicates govern it alone — the rule
    here is exactly the issue's "triage cannot ALONE prove an algorithm
    claim", which needs facts to be meaningful."""
    scope = algorithm_scope(claim)
    if scope is None or not facts:
        return None
    classes = sorted({_evidence_class(fm) for fm in facts})
    if any(c in ALGO_GRADE_CLASSES for c in classes):
        return None
    return (f"{claim_id}: evidence-class — algorithm-recovery claim (scope "
            f"keyword {scope!r}) reaches PROVEN on {classes} evidence only "
            f"({len(facts)} fact(s)); a triage-grade string fact cannot "
            f"alone prove an algorithm claim — attach decompile-grade "
            f"evidence (jadx source / dexdc index or taint) or declare the "
            f"fact's evidence_class")


def _runs_outcomes(ws: Path) -> list:
    """[(mtime, row, fname)] for every verify/redteam runs/*.md (mtime=recency)."""
    out = []
    runs = ws / "runs"
    if not runs.is_dir():
        return out
    for p in sorted(runs.glob("*.md")):
        name = p.name
        if "-verify-" not in name and "verify-redteam" not in name:
            continue
        entry = _parse_run(p)
        if entry is None:
            continue
        try:
            key = p.stat().st_mtime
        except OSError:
            continue
        out.append((key, entry, p.name))
    return out


def _outcomes_for(ws: Path, claim_id: str) -> list:
    return [(k, r, n) for k, r, n in _runs_outcomes(ws)
            if str(r.get("claim_id", "") or "").strip() == claim_id]


def latest_evidence(ws: Path, claim_id: str) -> dict:
    """Latest verify-note / red-team outcome per claim (mtime order).

    Row dicts gain a `source` key with the runs/ file name (None if absent)."""
    rows = _outcomes_for(ws, claim_id)

    def _last(checker):
        sub = [(k, r, n) for k, r, n in rows if r.get("checker") == checker]
        if not sub:
            return None
        _k, r, n = sub[-1]
        r = dict(r)
        r["source"] = n
        return r

    return {"verify_note": _last("verify-note"), "redteam": _last("red-team")}


def evidence_refs(ws: Path, claim_id: str) -> dict:
    """Ledger-facing evidence summary for the sweep wording (#819 item 2)."""
    ev = latest_evidence(ws, claim_id)
    wv = _waiver(ws, claim_id)
    return {
        "verify_note": (ev["verify_note"] or {}).get("source"),
        "redteam": (ev["redteam"] or {}).get("source"),
        "waiver": (wv or {}).get("justify"),
    }


def _waiver(ws: Path, claim_id: str) -> dict | None:
    p = ws / "runs" / f"{WAIVER_PREFIX}{claim_id}.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = WAIVER_JUSTIFY_RE.search(text)
    return {"claim_id": claim_id,
            "justify": (m.group(1).strip() if m else "")}


def _record_identity(ws: Path, source: str | None) -> str | None:
    """#825: verifier-identity header from a runs/ record's raw text."""
    if not source:
        return None
    try:
        text = (ws / "runs" / source).read_text(encoding="utf-8",
                                                errors="replace")
    except OSError:
        return None
    return vi.extract_from_md(text)


def check_register_transitions(ws: Path, new_text: str,
                               old_text: str | None = None) -> dict:
    """Fail-closed →PROVEN evidence gate. Returns {ok, violations, waivers}.

    old_text=None means the register is new — every PROVEN claim counts as a
    transition (fresh registers cannot mint PROVEN without evidence either)."""
    old = _load_statuses(old_text or "")
    new = _load_statuses(new_text)
    claims = _load_claims(new_text)
    violations: list = []
    waivers: list = []
    if not new:
        return {"ok": True, "violations": violations, "waivers": []}
    facts: dict | None = None
    for cid, st in new.items():
        if st != PROVEN:
            continue
        if old.get(cid) == PROVEN:
            continue  # already PROVEN — not a transition
        wv = _waiver(ws, cid)
        if wv is not None:
            if not wv["justify"]:
                violations.append(
                    f"{cid}: waiver exists but justify is empty — an exemption "
                    f"without a stated reason is not an exemption")
            else:
                waivers.append(wv)
            continue
        # issue 215: evidence-class admission (algorithm-recovery claims).
        # Checked at ADMISSION, ahead of the runs/ predicates, so the named
        # reason is the evidence grade the claim actually failed on.
        if facts is None:
            facts = facts_by_claim(ws)
        ec = evidence_class_violation(cid, claims.get(cid) or {},
                                      facts.get(cid) or [])
        if ec:
            violations.append(ec)
            continue
        ev = latest_evidence(ws, cid)
        vn, rt = ev["verify_note"], ev["redteam"]
        if vn is None or str(vn.get("result", "")).lower() != "passes":
            violations.append(
                f"{cid}: no latest verify-note = passes in runs/ "
                f"(got: {vn.get('result') if vn else 'none'})")
            continue
        if rt is None:
            violations.append(
                f"{cid}: red-team (L2) never ran for this claim — run it or "
                f"write runs/{WAIVER_PREFIX}{cid}.md with a non-empty justify:")
            continue
        if str(rt.get("result", "")).upper() == "REFUTED":
            violations.append(
                f"{cid}: latest red-team verdict REFUTED — PROVEN over a live "
                f"refutation is the exact #819 pathology")
            continue
        # #825: verifier identity machine-binding + maker/checker collapse +
        # provenance ordering + append-only anchor on accept
        ident = _record_identity(ws, rt.get("source"))
        vn_ident = _record_identity(ws, vn.get("source"))
        if not ident:
            violations.append(
                f"{cid}: redteam record {rt.get('source')} has no "
                f"verifier-identity header (#825) - an unattributed verdict "
                f"is not independent verification")
            continue
        if vn_ident and ident == vn_ident:
            violations.append(
                f"{cid}: redteam record {rt.get('source')} carries the same "
                f"verifier identity as verify-note {vn.get('source')} - "
                f"maker/checker collapse (#825)")
            continue
        try:
            rt_m = (ws / "runs" / rt["source"]).stat().st_mtime
            vn_m = (ws / "runs" / vn["source"]).stat().st_mtime
            if rt_m < vn_m:
                violations.append(
                    f"{cid}: redteam record {rt.get('source')} predates "
                    f"maker verify-note {vn.get('source')} (#825 provenance)")
                continue
        except OSError:
            pass
        try:
            vi.anchor(ws, cid, rt["source"], ident)
        except OSError:
            pass  # anchor is audit-grade, never a block reason
    ok = not violations
    return {"ok": ok, "violations": violations, "waivers": waivers}


# ---------------- #880: settlement rows at claim transitions -----------------

def _last_dispatch_row(ws: Path, claim_id: str) -> dict | None:
    """The claim's most recent `dispatch` event from the unified ledger
    (kunglao_log). None when the ledger is absent/unreadable — the settlement
    row then honestly carries tools=[] / duration_ms=None."""
    try:
        from kunglao_log import _all_rows
        rows = [r for r in _all_rows(Path(ws))
                if r.get("action") == "dispatch"
                and str(r.get("claim") or "") == claim_id]
        return rows[-1] if rows else None
    except Exception:  # noqa: BLE001 — settlement must never block the write
        return None


def _lesson_lineage_slug(ws: Path, claim_id: str) -> str | None:
    """The lesson slug the claim's method lineage references, from
    analyses/failure-<claim>.yaml (next_method_source == lesson-hit,
    candidates from the _score_lessons ladder). None without that shape."""
    p = ws / "analyses" / f"failure-{claim_id}.yaml"
    if not p.is_file():
        return None
    try:
        entry = yaml.safe_load(p.read_text(encoding="utf-8",
                                           errors="replace")) or {}
    except yaml.YAMLError:
        return None
    if str(entry.get("next_method_source") or "").strip().lower() != "lesson-hit":
        return None
    candidates = entry.get("candidates") or []
    if not candidates:
        return None
    fname = str(candidates[0].get("file") or "")
    if not fname.startswith("lesson-") or not fname.endswith(".md"):
        return None
    return fname.removeprefix("lesson-").removesuffix(".md")


def _burn_lesson_lineage(ws: Path, claim_id: str) -> None:
    """#880 pre-ruling: record_burn hangs at the NEGATIVE-SAMPLE settlement
    point — the lesson's method was consumed (next_method_source=lesson-hit)
    and the closed loop ended negative. Fail-open, never blocks settlement."""
    slug = _lesson_lineage_slug(ws, claim_id)
    if not slug:
        return
    try:
        from lessons_telemetry import record_burn
        record_burn(None, slug, workspace=ws)
    except Exception:  # noqa: BLE001 — lessons counting never blocks the gate
        pass


def _parse_dispatch_ts(ts) -> int | None:
    """Ledger ts (ISO8601 Z) -> epoch ms; None on any parse failure."""
    try:
        return int(datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError, OSError):
        return None


def emit_settlements(ws, new_text: str, old_text: str | None = None) -> int:
    """#880: settlement rows for claim status transitions (the issue's
    "claim 状态转换（register_proven_gate 钩子）发结算行").

    Called from write_guard's register-carrier ALLOW path — the write has
    passed every gate and WILL land, so the settlement is real. Only
    `to ∈ status_defs.TERMINAL` transitions settle (OPEN→IN_PROGRESS is
    churn, not a settlement). Row shape (all existing kunglao_log fields,
    zero schema change):

      action="claim_settled"  actor="hook:write_guard"  claim=C-NN
      trace_id=<mission-stable id (allocate_trace_id reuse face)>
      duration_ms=<now − the claim's latest dispatch event ts, ledger-measured>
      detail=JSON {"from", "to", "tools", "outcome"}

    Negative samples additionally burn the claim's lesson lineage (see
    _burn_lesson_lineage). Fail-open: returns the emitted-row count; any
    failure inside one settlement never blocks the write (the write_guard
    ALLOW decision was already made)."""
    ws = Path(ws)
    old = _load_statuses(old_text or "")
    new = _load_statuses(new_text)
    if not new:
        return 0
    from kunglao_log import allocate_trace_id
    try:
        trace_id = allocate_trace_id(ws)[0]
    except Exception:  # noqa: BLE001 — identity is best-effort
        trace_id = None
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    import json as _json
    count = 0
    for cid, to in new.items():
        if to not in TERMINAL:
            continue
        frm = old.get(cid)
        if frm == to:
            continue  # not a transition (already in this terminal state)
        dispatch_row = _last_dispatch_row(ws, cid)
        tools: list = []
        duration_ms = None
        if dispatch_row:
            detail = str(dispatch_row.get("detail") or "")
            m = re.search(r"\btools=([^;\s]+)", detail)
            if m:
                tools = [t for t in m.group(1).split(",") if t]
            ts_ms = _parse_dispatch_ts(dispatch_row.get("ts"))
            if ts_ms is not None:
                duration_ms = max(now_ms - ts_ms, 0)
        try:
            from kunglao_log import emit
            emit(ws, "hook:write_guard", "claim_settled", claim=cid,
                 trace_id=trace_id, duration_ms=duration_ms,
                 detail=_json.dumps({"from": frm, "to": to, "tools": tools,
                                     "outcome": to}, ensure_ascii=False))
            count += 1
        except Exception:  # noqa: BLE001 — logging never breaks the gate
            pass
        # #882 settlement retro: index the settlement (micro-retro O(1) read
        # face + backlog lag) and replay the claim's trace subgraph locally
        # (runs/<ts>-retro-<claim>.md). Fail-open, never blocks settlement —
        # same posture as the lesson burn below.
        try:
            from backtrack_loop import record_settlement, settlement_retro
            record_settlement(ws, cid, to, tools=tools, outcome=to,
                              trace_id=trace_id)
            settlement_retro(ws, cid, to=to, frm=frm, trace_id=trace_id)
        except Exception:  # noqa: BLE001 — backtrack never blocks settlement
            pass
        if to in NEGATIVE_SETTLEMENTS:
            _burn_lesson_lineage(ws, cid)
    return count
