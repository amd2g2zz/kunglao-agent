# -*- coding: utf-8 -*-
"""verifier_integrity — the verification-record resolver + per-verifier
calibration faces (the verifier-integrity card).

The trust hole this module closes: verification records were RECORDED
(runs/verification-*.md, verify-notes, red-team artifacts) but never
BOUND — a settlement could mint PROVEN with a failing, missing, or
not-yet-arrived verifier, and a verifier that rejects 100% of a corpus
kept its seat. Two faces restore the binding:

resolve_verification
    The settlement face's checker: a verification reference (an
    explicit workspace-relative path, else the canonical surfaces for
    the claim) must resolve to an existing record whose verdict word
    classifies as PASSED. Fail-closed everywhere: absence, a path that
    escapes the workspace, unparseable content, and unknown verdict
    words are all NOT a pass — PROVEN's credibility is the product.

calibration_check
    The anti-surrender floor raised from per-verdict to per-verifier:
    a verifier whose records are 100% one-sided (all-REJECT or
    all-PASS) over at least CALIBRATION_MIN_SAMPLE verdicts is BROKEN.
    One loud `verifier_calibration_broken` event per scan occurrence,
    bounded PER VERIFIER by the Standard 11 rule — occurrences count,
    the occurrence AT the limit escalates (the verifier's trust is
    burned: `escalated: true`), and beyond the limit the emit degrades
    to bounded silence while the audit keeps counting. Fail-open
    telemetry: never raises into the caller.

Identity comes from the verifier-identity header discipline (the
extractor module); records without one fall into the explicit
`unattributed` bucket — an unattributed all-reject corpus is still a trust hole worth
naming.

ZERO LEARNING POSTURE: no model call, no fitted parameter. The sample
floor and the repeat limit are documented policy constants.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_VERDICT_RE = re.compile(r"^verdict:\s*(\S+)", re.MULTILINE)
_OVERALL_RE = re.compile(r"^##\s+Overall verdict\s*\n(\S+)", re.MULTILINE)

#: verdict words that count as a PASSED independent check (case-folded)
PASS_VERDICTS = frozenset(
    {"verified", "confirmed", "pass", "passed", "passes"})

#: verdict words that count as a FAILED independent check (case-folded)
FAIL_VERDICTS = frozenset(
    {"refuted", "rejected", "reject", "fail", "failed", "falsified"})

#: the identity bucket for records without a verifier-identity header
UNATTRIBUTED = "unattributed"

#: the sample floor: below this many classifiable verdicts a verifier
#: says nothing about calibration (a single reject is legitimate)
CALIBRATION_MIN_SAMPLE = 3

#: Standard 11: a BROKEN verifier emits at most this many events — the
#: occurrence AT the limit escalates (trust burned), beyond it the emit
#: degrades to bounded silence while the audit keeps counting
CALIBRATION_REPEAT_LIMIT = 3

#: the per-verifier occurrence ledger (the claims-store audit face)
CALIBRATION_AUDIT_REL = Path("runs") / ".verifier-calibration-audit.json"

_EMIT_ACTION = "verifier_calibration_broken"
_ACTOR = "verifier:calibration"


# ------------------------------------------------------- the record faces

def canonical_records(claim: str) -> tuple[str, ...]:
    """The claim's canonical verification-record surfaces, in decisive
    order (the first existing surface wins)."""
    claim = str(claim or "")
    return (f"runs/verification-{claim}.md",
            f"runs/{claim}-verify-note.md",
            f"runs/verify-redteam-{claim}.md",
            "evidence/verdict.json")


def _safe_ws_path(ws: Path, rel: str) -> Path | None:
    """Resolve a workspace-relative reference with a containment guard:
    the resolved path must stay inside the workspace (no `..` escape,
    no absolute alias). None = outside."""
    try:
        ws_root = Path(ws).resolve()
        resolved = (ws_root / rel).resolve()
        if resolved == ws_root:
            return None
        if ws_root not in resolved.parents:
            return None
        return resolved
    except (OSError, ValueError):
        return None


def _record_verdict_word(path: Path, claim: str) -> tuple[bool, str]:
    """(found, word) for one record file. md faces carry a `verdict:`
    line (the verify-note mirror carries the `## Overall verdict`
    section word instead); json faces carry a claims list with per-claim
    verdict words. A backtick/quote wrapper is stripped — the value,
    not its wrapping, is the word."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (False, "")
    if path.suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError:
            return (False, "")
        if not isinstance(doc, dict):
            return (False, "")
        claims = doc.get("claims")
        if isinstance(claims, list):
            for entry in claims:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("id") or "") != str(claim or ""):
                    continue
                word = str(entry.get("verdict")
                           or entry.get("status") or "").strip()
                if word:
                    return (True, word.strip("`\"'").lower())
                return (False, "")
            return (False, "")
        word = str(doc.get("verdict") or "").strip()
        return (True, word.strip("`\"'").lower()) if word else (False, "")
    m = _VERDICT_RE.search(text)
    if m is None:
        m = _OVERALL_RE.search(text)
    if m is None:
        return (False, "")
    return (True, m.group(1).strip().strip("`\"'").lower())


def resolve_verification(ws, claim: str,
                         reference: str) -> tuple[bool, str, str]:
    """Resolve a settlement's verification reference to a PASSED
    record. Returns (passed, verdict_word, detail). Fail-closed: any
    absence, escape, parse miss, or unknown word is not a pass."""
    ws = Path(ws)
    ref = str(reference or "").strip()
    explicit = bool(ref) and ("/" in ref or ref.endswith((".md", ".json")))
    candidates = (ref,) if explicit else canonical_records(claim)
    for rel in candidates:
        p = _safe_ws_path(ws, rel)
        if p is None:
            if explicit:
                return (False, "", f"{rel} escapes the workspace")
            continue
        if not p.is_file():
            continue
        found, word = _record_verdict_word(p, claim)
        if not found:
            return (False, "", f"{rel} carries no parseable verdict word")
        if word in PASS_VERDICTS:
            return (True, word, str(rel))
        if word in FAIL_VERDICTS:
            return (False, word, f"{rel} verdict={word}")
        return (False, word, f"{rel} unknown verdict word '{word}'")
    return (False, "", "no verification record found on any canonical "
                       "surface for " + str(claim))


# ------------------------------------------------------- the calibration

def _scan_records(ws: Path) -> dict[str, dict[str, int]]:
    """identity -> {"pass": n, "fail": n} over the runs/ verification
    record families. Unreadable or unclassifiable records contribute
    nothing (fail-open read, never a fabricated verdict)."""
    counts: dict[str, dict[str, int]] = {}
    runs = Path(ws) / "runs"
    if not runs.is_dir():
        return counts
    for pattern in ("verification-*.md", "verify-redteam-*.md"):
        for p in sorted(runs.glob(pattern)):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = _VERDICT_RE.search(text)
            if m is None:
                continue
            word = m.group(1).strip().strip("`\"'").lower()
            if word in PASS_VERDICTS:
                cls = "pass"
            elif word in FAIL_VERDICTS:
                cls = "fail"
            else:
                continue
            import verifier_identity as vident
            identity = vident.extract_from_md(text) or UNATTRIBUTED
            bucket = counts.setdefault(identity, {"pass": 0, "fail": 0})
            bucket[cls] += 1
    return counts


def _audit_state_load(ws: Path) -> dict:
    p = Path(ws) / CALIBRATION_AUDIT_REL
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _audit_state_save(ws: Path, state: dict) -> None:
    p = Path(ws) / CALIBRATION_AUDIT_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        from kunglao_log import warn
        warn("calibration-audit-save", f"{type(exc).__name__}: {exc}")


def calibration_check(ws) -> list:
    """Scan, flag, emit. Returns one row per BROKEN verifier (the full
    audit face — occurrences count even past the emit limit). Fail-open
    telemetry: a broken scan degrades to an empty list with a warn,
    never a raise."""
    ws = Path(ws)
    try:
        counts = _scan_records(ws)
        state = _audit_state_load(ws)
        rows: list[dict] = []
        for identity, bucket in sorted(counts.items()):
            total = bucket["pass"] + bucket["fail"]
            one_sided = bucket["pass"] == 0 or bucket["fail"] == 0
            if total < CALIBRATION_MIN_SAMPLE or not one_sided:
                continue
            occurrence = int(state.get(identity, 0)) + 1
            state[identity] = occurrence
            row = {"identity": identity, "pass": bucket["pass"],
                   "fail": bucket["fail"], "sample": total,
                   "occurrence": occurrence, "broken": True,
                   "escalated": occurrence == CALIBRATION_REPEAT_LIMIT}
            rows.append(row)
            if occurrence > CALIBRATION_REPEAT_LIMIT:
                continue  # bounded silence post-escalation; audit keeps counting
            try:
                from kunglao_log import emit
                emit(ws, actor=_ACTOR, action=_EMIT_ACTION,
                     detail=json.dumps(
                         {"reason": "verifier_one_sided",
                          "identity": identity,
                          "pass": bucket["pass"], "fail": bucket["fail"],
                          "sample": total, "occurrence": occurrence,
                          "escalated": row["escalated"],
                          "sample_floor": CALIBRATION_MIN_SAMPLE},
                         sort_keys=True, ensure_ascii=False))
            except Exception as exc:  # loud face, never the scan
                from kunglao_log import warn
                warn("calibration-emit", f"{type(exc).__name__}: {exc}")
        _audit_state_save(ws, state)
        return rows
    except Exception as exc:  # noqa: BLE001 — telemetry, never the caller
        # kunglao_log.warn is no-raise by contract (the ONE logging
        # implementation); its own failure face keeps the trace without
        # a raw stderr print (the logging-arch rule).
        from kunglao_log import warn
        warn("calibration-scan", f"{type(exc).__name__}: {exc}")
        return []
