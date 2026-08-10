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
