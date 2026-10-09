# -*- coding: utf-8 -*-
"""register_proven_gate.py — claim-register →PROVEN evidence gate (#819).

豆包 pathology (#819 v2): the register's →PROVEN migration had no evidence
predicate — whoever edited claim-register.yaml to PROVEN "was" the settlement,
verify results never participated. Fail-closed: a →PROVEN transition requires
  (a) latest verify-note outcome == passes, AND
  (b) red-team ran for the claim AND its latest result != REFUTED,
or a waiver runs/proven-waiver-<claim>.md with non-empty justify:
that carries the orchestrator stamp (5-F6 — the bare justify:
line was a one-file self-service PROVEN; an unstamped waiver reads
as ABSENT and the verify/red-team legs stay enforced; mint via
  python scripts/register_proven_gate.py stamp-waiver <ws> <claim-id>).

Evidence source: runs/*.md under the outcome_capture conventions
("-verify-" / "verify-redteam" in name), parsed with outcome_capture's own
regexes; latest = max mtime. Posture: fail-closed (structure gate).
"""
from __future__ import annotations
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace — the canonical kunglao_log.warn.
from kunglao_log import warn  # canonical warn: ONE implementation (process-wide dedupe + ledger face)
import hashlib
import hmac
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import verifier_identity as vi  # noqa: F401  (#825)
from review_gate import parse_frontmatter  # stdlib-only stamp dialect
from outcome_capture import _parse_run
from status_defs import TERMINAL  # single source (#34, #95)

PROVEN = "PROVEN"
WAIVER_PREFIX = "proven-waiver-"
WAIVER_JUSTIFY_RE = re.compile(r"^\s*justify:\s*(\S.*)$", re.M)

# ---------------- 5-F6: the waiver orchestrator stamp -------------------
#
# The waiver file lives in runs/ — act-writable — so its bare existence with
# a non-empty justify: line was a one-file self-service PROVEN. A waiver now
# counts only when its frontmatter carries the orchestrator stamp: the
# review_gate canonical-stamp shape adapted to the minimal form (HMAC-SHA256
# digest over domain\0<claim-id>\0<ts>, hex). The key derives from the
# documented per-run constant below. Trust posture = review_gate's own
# (stated in its header): this is a deliberate-marking mechanism that makes
# honest-workflow compliance mechanical — the stamp material is documented,
# so forging one requires deliberately computing the documented stamp, which
# converts the accidental self-service waiver into explicit forgery. No
# heavyweight crypto, no new deps.
WAIVER_STAMP_DOMAIN = "kunglao/proven-waiver/1"
WAIVER_STAMP_PHRASE = "rc1-hardening-601:proven-waiver-orchestrator-authority"


def waiver_stamp(claim_id: str, ts) -> str:
    """The canonical waiver stamp: HMAC-SHA256 over domain \0 cid \0 ts."""
    payload = "\0".join([WAIVER_STAMP_DOMAIN, str(claim_id), str(ts)])
    key = hashlib.sha256(WAIVER_STAMP_PHRASE.encode("utf-8")).digest()
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def stamp_waiver(ws, claim_id: str, ts: int | None = None) -> dict:
    """Orchestrator mint face: stamp runs/proven-waiver-<cid>.md in place
    with the canonical (claim-id, ts) digest. Fail-closed: a missing file or
    a missing non-empty justify: line refuses the stamp — an exemption
    without a stated reason is not an exemption, and the gate enforces that
    face even under a valid stamp."""
    p = Path(ws) / "runs" / f"{WAIVER_PREFIX}{claim_id}.md"
    if not p.is_file():
        return {"ok": False, "error": f"no waiver file: {p}"}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = WAIVER_JUSTIFY_RE.search(text)
    if not m or not m.group(1).strip():
        return {"ok": False,
                "error": f"{p.name} has no non-empty justify: line — "
                         f"refusing to stamp a reason-less exemption"}
    ts = int(ts) if ts is not None else int(
        datetime.now(timezone.utc).timestamp())
    body = text
    fm: dict = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = parse_frontmatter(text)
            body = parts[2]
    fm["claim_id"] = claim_id
    fm["ts"] = str(ts)
    fm["stamp"] = waiver_stamp(claim_id, ts)
    fm_text = "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items())
    p.write_text(fm_text + "---\n" + body.lstrip("\n"), encoding="utf-8")
    return {"ok": True, "file": str(p), "ts": ts, "stamp": fm["stamp"]}

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
    """The stamped waiver for the claim; None when absent OR unstamped.

    5-F6: the waiver is orchestrator authority — without a valid
    frontmatter stamp (waiver_stamp over the file's own claim id, so a
    stamp lifted onto another claim's file fails) the file reads as
    ABSENT: loud warn, the verify/red-team legs stay enforced."""
    p = ws / "runs" / f"{WAIVER_PREFIX}{claim_id}.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = parse_frontmatter(text)
    ts = str(fm.get("ts") or "").strip()
    stamp = str(fm.get("stamp") or "").strip()
    fm_cid = str(fm.get("claim_id") or "").strip()
    expect = waiver_stamp(claim_id, ts) if ts else ""
    if (not ts or not stamp
            or not hmac.compare_digest(stamp, expect)
            or (fm_cid and fm_cid != claim_id)):
        warn("_waiver", f"runs/{p.name} carries no valid orchestrator "
             f"stamp (#601 5-F6) — the waiver reads as absent; "
             f"verify/red-team legs stay enforced")
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
    # #516: fail-closed on an unparseable NEW text — "cannot read" is not
    # "no transitions". The wt1 combat corruption (ScannerError line 44,
    # evidence prose carrying `): `) reached this gate as {} and sailed
    # through the empty-map early return below. Only the NEW side is
    # fail-closed: an unparseable OLD text is a repair case, and the
    # canonical-writer leg in write_guard adjudicates what lands.
    try:
        new_doc = yaml.safe_load(new_text)
    except yaml.YAMLError:
        new_doc = None
    if not isinstance(new_doc, dict):
        return {"ok": False,
                "violations": ["register-writer: the new register text "
                               "does not parse as a YAML mapping "
                               "(fail-closed, #516 — mutate via "
                               "scripts/ws_yaml.py)"],
                "waivers": []}
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
        except OSError as exc:
            warn("check_register_transitions", f"{type(exc).__name__}: {exc}")
        try:
            vi.anchor(ws, cid, rt["source"], ident)
        except OSError as exc:
            warn("check_register_transitions_2", f"{type(exc).__name__}: {exc}")
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
    except Exception as exc:  # noqa: BLE001 — lessons counting never blocks the gate
        warn("_burn_lesson_lineage", f"{type(exc).__name__}: {exc}")


def _parse_dispatch_ts(ts) -> int | None:
    """Ledger ts (ISO8601 Z) -> epoch ms; None on any parse failure."""
    try:
        return int(datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError, OSError):
        return None


def _claim_hypothesis_ref(ws: Path, claim_id: str) -> tuple[str | None,
                                                           str | None]:
    """The claim's most recent hypothesis id (the settlement's structural
    companion), with its honesty face: (ref, reason). The "latest" order is
    the NUMERIC id sequence (the H-NNN suffix parsed and compared as an
    integer — a string max would silently return H-999 over H-1000 once
    ids cross the zero-padding width), unparseable ids sort last. Faces:
    the store read failing (or the store root existing but not being a
    directory) is ``(None, "hypothesis_store_unreadable")``; a readable
    store with no hypothesis for the claim is ``(None, "no_hypothesis")``;
    a found reference carries reason None. Fail-open overall: a settlement
    never blocks on this face."""
    try:
        from hypothesis_store import HypothesisStore
        root = Path(ws) / "hypotheses"
        if root.exists() and not root.is_dir():
            return None, "hypothesis_store_unreadable"
        hyps = [h for h in HypothesisStore(root).list_all()
                if h.claim_id == claim_id]
    except Exception:  # noqa: BLE001 — settlement must never block on this
        return None, "hypothesis_store_unreadable"
    if not hyps:
        return None, "no_hypothesis"

    def _seq(h) -> int:
        digits = "".join(c for c in h.id if c.isdigit())
        return int(digits) if digits else -1

    return max(hyps, key=_seq).id, None


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
            ref, h_reason = _claim_hypothesis_ref(ws, cid)
            emit(ws, "hook:write_guard", "claim_settled", claim=cid,
                 trace_id=trace_id, duration_ms=duration_ms,
                 hypothesis_ref=ref,
                 null_reasons=({"hypothesis_ref": h_reason}
                               if h_reason else None),
                 detail=_json.dumps({"from": frm, "to": to, "tools": tools,
                                     "outcome": to}, ensure_ascii=False))
            count += 1
        except Exception as exc:  # noqa: BLE001 — logging never breaks the gate
            warn("emit_settlements", f"{type(exc).__name__}: {exc}")
        # #882 settlement retro: index the settlement (micro-retro O(1) read
        # face + backlog lag) and replay the claim's trace subgraph locally
        # (runs/<ts>-retro-<claim>.md). Fail-open, never blocks settlement —
        # same posture as the lesson burn below.
        try:
            from backtrack_loop import record_settlement, settlement_retro
            record_settlement(ws, cid, to, tools=tools, outcome=to,
                              trace_id=trace_id)
            settlement_retro(ws, cid, to=to, frm=frm, trace_id=trace_id)
        except Exception as exc:  # noqa: BLE001 — backtrack never blocks settlement
            warn("emit_settlements_2", f"{type(exc).__name__}: {exc}")
        if to in NEGATIVE_SETTLEMENTS:
            _burn_lesson_lineage(ws, cid)
        # #244 settle→dispose: a claim that settled TERMINAL must dispose
        # its bound waiting pool in the SAME beat — REFUTED re-arms with the
        # sanitized gap-only redo signal, every other terminal sends stop.
        # 傻等 (a worker waiting past its claim's settlement) is a contract
        # violation. Fire-and-forget: disposal never moves the settlement.
        try:
            from wait_dispose import dispose_waiting_pool
            dispose_waiting_pool(ws, cid, to)
        except Exception as exc:  # noqa: BLE001 — disposal never blocks settle
            warn("dispose_waiting_pool", f"{type(exc).__name__}: {exc}")
        # the promotion write-back: a PROVEN settlement syncs the citing
        # facts' frontmatter with the register IN THE SAME SETTLE (register
        # PROVEN while facts read INFERRED recomputed the completion
        # transaction dirty and starved the completion gate). One
        # mechanical write, fail-open, fully named skips — never moves a
        # falsified or judgment-sourced fact.
        if to == "PROVEN":
            try:
                from fact_status_sync import promote_citing_facts
                sync = promote_citing_facts(ws, cid)
                if sync.get("synced") or sync.get("skipped"):
                    from kunglao_log import emit
                    emit(ws, "hook:write_guard", "fact_status_synced",
                         claim=cid,
                         detail=_json.dumps(sync, ensure_ascii=False,
                                            sort_keys=True))
            except Exception as exc:  # noqa: BLE001 — sync never blocks settle
                warn("promote_citing_facts", f"{type(exc).__name__}: {exc}")
    # issue 304 (satellite D4): guard liveness at the settlement beat —
    # a guarded fix whose check has zero fire records across the window
    # is flagged guard_dormant (WARN-level finding, ledger-deduped,
    # never a blocker; the acceptance that rejected the settlement lives
    # in fix_guard.evaluate_guard via failure_analysis_gate).
    try:
        from fix_guard import flag_dormant_guards
        flag_dormant_guards(ws)
    except Exception as exc:  # noqa: BLE001 — liveness never blocks settlement
        warn("emit_settlements_guard", f"{type(exc).__name__}: {exc}")
    return count


# ---------------- orchestrator mint face (CLI) -------------------------------

def main(argv: list[str] | None = None) -> int:
    """stamp-waiver <ws> <claim-id> — stamp runs/proven-waiver-<cid>.md
    with the canonical orchestrator digest (5-F6). Exit 0 minted /
    2 refused."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "stamp-waiver":
        print("usage: register_proven_gate.py stamp-waiver <ws> <claim-id>",
              file=sys.stderr)
        return 2
    res = stamp_waiver(argv[1], argv[2])
    if res.get("ok"):
        print(f"stamp OK: {res['file']} (ts={res['ts']})")
        return 0
    print(f"stamp REFUSED: {res.get('error')}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
