"""blind_gate — independent-verifier (BLIND) sign-off gate for PROVEN promotions.

PRD verified-convergence M1: every claim promoted to PROVEN must carry an
independent verifier sign-off (verifier_sign_off block in the claim's fact
file). Without it, the claim is STAMP (claimed-but-unverified), not PROVEN.

This module is pure (no I/O side effects): callers pass in fact text or a
facts directory, and the functions return a verdict. Wiring into
kunglao_record.claim_migrator (the formal promotion entry point) and
hooks/worker_budget.compare_register_change (the bypass-catcher) lives in
those modules.

verifier_sign_off block format (reused from doubt_checker.py L70-84):
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w2
      refute_attempt: "tried X, Y, Z to break; held"
      sign_off_at: 2026-08-10T14:00:00Z
      verdict: CONFIRMED   # CONFIRMED | REFUTE
    ```

Self-stamp guard: verifier_id == claim's worker_id → NOT independent → STAMP
(maker-checker §1b: the maker cannot self-certify).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

# STAMP = "claimed-but-unverified". NOT a terminal status — the claim can
# later be promoted to PROVEN (after obtaining sign-off) or REFUTED.
STAMP = "STAMP"

# Required fields in a verifier_sign_off block. verdict defaults to CONFIRMED
# for backward compat with blocks written before verdict was added.
_REQUIRED_FIELDS = ("verifier_id", "refute_attempt", "sign_off_at")

# ---- inference-scope gate (issue #48, a2b5e25c problem 2) ----
# A claim is *inferential* when its statement or fact text carries
# routing/causal patterns: the BLIND sign-off must then cover the inference
# itself (independent static evidence), not just byte anchors.
INFERENTIAL_PATTERNS = (
    r"routing", r"\broute\b", r"not on .* path", r"not on path",
    r"correction", r"corrects F-?\d+", r"\bgate\b",
    r"\b0 hits\b", r"\b0 occurrences\b",
)
_ZERO_HITS_PATTERNS = (r"\b0 hits\b", r"\b0 occurrences\b")
_ENV_FAULT_PATTERNS = (r"stalled", r"never reconnected", r"\breconnect",
                       r"未触发", r"timeout")
_STATIC_MARKERS = (r"\bxref", r"disasm", r"decompile", r"capstone", r"ghidra",
                   r"\bida\b", r"call graph", r"callsite")
_ORCH_CAPTURED = r"orchestrator[- ]captured"


def extract_verifier_signoff(fact_text: str) -> dict | None:
    """Parse the verifier_sign_off block from fact text.

    Returns the fields dict, or None if no valid block found.
    Handles both fenced (```yaml ... ```) and bare yaml forms.
    """
    if not fact_text or "verifier_sign_off" not in fact_text:
        return None
    # Try fenced yaml block first
    m = re.search(r"```yaml\s*(verifier_sign_off:\s*.*?)```", fact_text, re.DOTALL)
    if m:
        try:
            parsed = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            parsed = None
        if parsed and "verifier_sign_off" in parsed:
            return _validate_fields(parsed["verifier_sign_off"])
    # Fallback: bare yaml form
    m = re.search(r"verifier_sign_off:\s*\n(.*?)(?:\n\n|\n```|\Z)", fact_text, re.DOTALL)
    if m:
        try:
            parsed = yaml.safe_load("verifier_sign_off:\n" + m.group(1)) or {}
        except yaml.YAMLError:
            return None
        if parsed and "verifier_sign_off" in parsed:
            return _validate_fields(parsed["verifier_sign_off"])
    return None


def _validate_fields(fields: dict) -> dict | None:
    """Return fields if all required keys are present and non-empty, else None."""
    if not isinstance(fields, dict):
        return None
    missing = [f for f in _REQUIRED_FIELDS if not fields.get(f)]
    if missing:
        return None
    # YAML parses ISO timestamps into datetime objects; normalize to string
    soa = fields.get("sign_off_at")
    if isinstance(soa, datetime):
        fields = {**fields, "sign_off_at": soa.strftime("%Y-%m-%dT%H:%M:%SZ")}
    # verdict defaults to CONFIRMED (backward compat)
    if "verdict" not in fields:
        fields = {**fields, "verdict": "CONFIRMED"}
    return fields


def record_dissent(
    fact_path: Path,
    verifier_id: str,
    finding: str,
    evidence_path: str,
    ts: str | None = None,
) -> None:
    """Append a structured dissent block to a fact file (ICD-203 #8).

    Called when a BLIND verifier returns REFUTE — the dissent record
    ensures the disagreement is formally documented, not silently dropped.

    The dissent is written as a fenced ```dissent yaml block at the end
    of the fact file, preserving all existing content.
    """
    if ts is None:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    block = (
        f"\n```dissent\n"
        f"verifier_id: {verifier_id}\n"
        f"finding: {finding!r}\n"
        f"evidence_path: {evidence_path}\n"
        f"ts: {ts}\n"
        f"```\n"
    )
    existing = fact_path.read_text(encoding="utf-8", errors="replace")
    fact_path.write_text(existing + block, encoding="utf-8")


def extract_dissent(fact_text: str) -> list[dict]:
    """Extract all ```dissent blocks from fact text.

    Returns a list of dicts (one per dissent block), ordered by appearance.
    Returns empty list if no dissent blocks found.
    """
    if not fact_text or "```dissent" not in fact_text:
        return []
    results = []
    for m in re.finditer(r"```dissent\s*\n(.*?)```", fact_text, re.DOTALL):
        block_text = m.group(1).strip()
        fields: dict[str, str] = {}
        for line in block_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            # Remove surrounding quotes if present (yaml-style repr)
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if key:
                fields[key] = val
        if fields:
            results.append(fields)
    return results


def find_fact_file(facts_dir: Path, claim_id: str) -> Path | None:
    """Locate the fact file for a claim: facts/<claim_id>.md, or any *.md
    whose first 2000 chars contain the claim_id."""
    if not facts_dir.exists():
        return None
    direct = facts_dir / f"{claim_id}.md"
    if direct.exists():
        return direct
    for p in facts_dir.glob("*.md"):
        if p.name.startswith("_"):
            continue
        try:
            if claim_id in p.read_text(encoding="utf-8", errors="replace")[:2000]:
                return p
        except OSError:
            continue
    return None


def check_proven_gate(
    claim_id: str,
    facts_dir: Path,
    worker_id: str | None = None,
) -> tuple[bool, str, str]:
    """Determine whether a claim may be promoted to PROVEN.

    Returns (allowed, effective_status, reason):
      - allowed=True, effective='PROVEN'  → BLIND sign-off is valid
      - allowed=False, effective='STAMP'  → downgrades (see reason)

    The caller (claim_migrator) writes effective_status to the register.

    Parameters:
      claim_id:   the claim being promoted (e.g. 'C-42')
      facts_dir:  path to facts/ directory
      worker_id:  optional — the claim's assigned worker. If provided and
                  equals verifier_id, the sign-off is a self-stamp (rejected).
    """
    fact_path = find_fact_file(facts_dir, claim_id)
    if fact_path is None:
        return (False, STAMP, f"no fact file for {claim_id}")
    fact_text = fact_path.read_text(encoding="utf-8", errors="replace")
    signoff = extract_verifier_signoff(fact_text)
    if signoff is None:
        return (False, STAMP,
                f"verifier_sign_off missing in {fact_path.name} — "
                f"claim {claim_id} cannot be PROVEN without independent BLIND verification")
    # self-stamp: verifier_id == worker_id → not independent (maker-checker §1b)
    if worker_id and signoff.get("verifier_id") == worker_id:
        return (False, STAMP,
                f"self-stamp rejected: verifier_id={signoff['verifier_id']!r} "
                f"== worker_id={worker_id!r} (maker-checker §1b: maker cannot self-certify)")
    verdict = (signoff.get("verdict") or "CONFIRMED").upper()
    if verdict == "REFUTE":
        return (False, STAMP,
                f"BLIND verifier REFUTED claim {claim_id}: {signoff.get('refute_attempt', '')}")
    return (True, "PROVEN",
            f"BLIND verified by {signoff.get('verifier_id', '?')} "
            f"at {signoff.get('sign_off_at', '?')}")


# =====================================================================
# Inference-scope gate (issue #48) — D1-D4
# =====================================================================

def is_inferential_claim(statement: str, fact_text: str) -> bool:
    """True when the claim statement or fact text (first 4000 chars, mirroring
    find_fact_file's scan window) carries inferential/routing/causal patterns.

    D1: patterns are the mechanical contract (issue keywords verbatim);
    `0 hits` / `0 occurrences` count as inferential as path evidence.
    """
    hay = " ".join([statement or "", (fact_text or "")[:4000]]).lower()
    return any(re.search(p, hay) for p in INFERENTIAL_PATTERNS)


def _has_zero_hits(text: str) -> bool:
    return any(re.search(p, text.lower()) for p in _ZERO_HITS_PATTERNS)


def _has_env_fault(text: str) -> bool:
    return any(re.search(p, text.lower()) for p in _ENV_FAULT_PATTERNS)


def _signoff_evidence_text(signoff: dict) -> str:
    """D2: sign-off evidence = evidence_path + refute_attempt + finding."""
    parts = []
    for key in ("evidence_path", "refute_attempt", "finding"):
        val = signoff.get(key)
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def _has_static_evidence(text: str) -> bool:
    """D2.2: ≥1 independent static-evidence marker → coverage."""
    low = text.lower()
    return any(re.search(p, low) for p in _STATIC_MARKERS)


def _claim_statement(register_text: str, claim_id: str) -> str:
    """Parse the `statement:` field for a claim from register text.

    Splits the yaml into per-claim blocks (`- id:` / `id:` line starts a new
    block), matches the target claim, returns its statement (unquoted) or "".
    """
    if not register_text:
        return ""
    cid = claim_id.strip()
    blocks = re.split(r"\n(?=\s*-?\s*id:)", register_text)
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        if re.search(r"\bid:\s*" + re.escape(cid) + r"\s*$", lines[0], re.IGNORECASE):
            m = re.search(r"^\s*statement:\s*(.+)$", block, re.MULTILINE)
            if m:
                return m.group(1).strip().strip('"').strip("'")
            return ""
    return ""


def check_inference_blind_scope(
    claim_id: str,
    facts_dir: Path,
    register_text: str,
    worker_id: str | None = None,
) -> tuple[bool, str, str]:
    """Inference-scope gate for PROVEN promotions (a2b5e25c problem 2, #48).

    Inferential/routing/causal claims need independent static sign-off
    coverage — byte anchors or orchestrator-captured evidence do not cover
    the inference. Mirrors check_proven_gate's standalone checks (fact /
    signoff / self-stamp / REFUTE) so this gate is complete on its own and
    usable by the register-write backstop.

    D4 check order: fact exists → signoff exists → self-stamp → REFUTE →
    orchestrator-captured → static markers → env-fault diagnostic.

    Returns (allowed, effective_status, reason) — same contract as
    check_proven_gate; every failure reason carries uppercase "INFERENCE".
    """
    fact_path = find_fact_file(facts_dir, claim_id)
    if fact_path is None:
        return (False, STAMP, f"INFERENCE gate: no fact file for {claim_id}")
    fact_text = fact_path.read_text(encoding="utf-8", errors="replace")
    statement = _claim_statement(register_text, claim_id)
    if not is_inferential_claim(statement, fact_text):
        # RED3: non-inferential claims are outside this gate's scope — the
        # BLIND gate (check_proven_gate, always run first at both wire points)
        # governs sign-off existence for them.
        return (True, "PROVEN",
                f"INFERENCE gate: non-inferential claim {claim_id} — "
                f"BLIND byte-anchor sign-off suffices")
    signoff = extract_verifier_signoff(fact_text)
    if signoff is None:
        return (False, STAMP,
                f"INFERENCE gate: verifier_sign_off missing in {fact_path.name} — "
                f"claim {claim_id} cannot be PROVEN without independent BLIND verification")
    if worker_id and signoff.get("verifier_id") == worker_id:
        return (False, STAMP,
                f"INFERENCE gate: self-stamp rejected: "
                f"verifier_id={signoff['verifier_id']!r} == worker_id={worker_id!r} "
                f"(maker-checker §1b: maker cannot self-certify)")
    verdict = (signoff.get("verdict") or "CONFIRMED").upper()
    if verdict == "REFUTE":
        return (False, STAMP,
                f"INFERENCE gate: BLIND verifier REFUTED claim {claim_id}: "
                f"{signoff.get('refute_attempt', '')}")

    evidence_text = _signoff_evidence_text(signoff)
    if re.search(_ORCH_CAPTURED, evidence_text, re.IGNORECASE):
        # RED1: orchestrator-captured evidence is not independent coverage
        return (False, STAMP,
                f"INFERENCE gate: orchestrator-captured evidence cannot cover an "
                f"inferential claim ({claim_id}) — require independent static xref")
    if _has_static_evidence(evidence_text):
        # RED2 / RED4b: independent static evidence covers the inference
        return (True, "PROVEN",
                f"INFERENCE gate: {claim_id} inference covered by independent "
                f"static evidence: {evidence_text[:120]}")
    if _has_zero_hits(fact_text) and _has_env_fault(fact_text):
        # RED4 / a2b5e25c F040: 0-hits observed while the debuggee self-reports
        # an env fault — the dynamic miss cannot establish a routing conclusion
        return (False, STAMP,
                f"INFERENCE gate: environmental negative evidence cannot establish "
                f"routing ({claim_id}) — 0-hits observed while provenance self-reports "
                f"env fault; require independent static xref")
    return (False, STAMP,
            f"INFERENCE gate: byte-anchor sign-off insufficient for inferential "
            f"claim {claim_id} — require independent static evidence "
            f"(xref/disasm/decompile)")
