# -*- coding: utf-8 -*-
"""blind_gate — independent-verifier (BLIND) sign-off gate for PROVEN promotions.

PRD verified-convergence M1: every claim promoted to PROVEN must carry an
independent verifier sign-off (verifier_sign_off block in the claim's fact
file). Without it, the claim is STAMP (claimed-but-unverified), not PROVEN.

This module is pure (no I/O side effects): callers pass in fact text or a
facts directory, and the functions return a verdict. Wiring into
kunglao_record.claim_migrator (the formal promotion entry point) and
hooks/worker_budget.compare_register_change (the bypass-catcher) lives in
those modules.

verifier_sign_off block format (extracted by extract_verifier_signoff below):
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

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

# STAMP = "claimed-but-unverified". NOT a terminal status — the claim can
# later be promoted to PROVEN (after obtaining sign-off) or REFUTED.
STAMP = "STAMP"

# Required fields in a verifier_sign_off block. #53: verdict is REQUIRED —
# the "default to CONFIRMED" shim for pre-verdict blocks was removed
# (no-backcompat ruling 2026-09-01, #863 Package 2 discipline): a
# verdict-less block is an invalid sign-off, not an implicit CONFIRMED.
_REQUIRED_FIELDS = ("verifier_id", "refute_attempt", "sign_off_at", "verdict")

# ---- inference-scope gate (issue #48, a2b5e25c problem 2) ----
# A claim is *inferential* when its statement or fact text carries
# routing/causal patterns: the BLIND sign-off must then cover the inference
# itself (independent static evidence), not just byte anchors.
INFERENTIAL_PATTERNS = (
    r"routing", r"\broute\b", r"not on .* path", r"not on path",
    r"correction", r"corrects F-?\d+", r"\bgate\b",
    r"\b0 hits\b", r"\b0 occurrences\b",
)
# ---- #56: NEGATIVE-existence conclusions are inferential too ----
# A "does not exist"/"absent"/"not present" conclusion drawn from a dynamic
# miss must reach the environmental-negative-evidence diagnostic instead of
# short-circuiting as non-inferential. Scoped to NEGATIVE conclusions — a
# positive existence claim ("Foo exists at 0x...") is NOT flagged (no false
# positives). Word-boundaried to avoid matching "absentee" / "present[ation]".
_NEGATIVE_EXISTENCE_PATTERNS = (
    r"does not exist", r"\babsent\b", r"\bnot present\b",
    r"不存在", r"未发现",
)
# ---- #56: environmental-negative-evidence BASIS vocabulary ----
# #48 recognized only `0 hits`/`0 occurrences`; the F040 incident's
# the CJK "no call captured" trigger and sibling phrasings also indicate
# a dynamic miss under env fault. Used by the env-fault diagnostic.
_ENV_NEGATIVE_BASIS_PATTERNS = (
    r"\b0 hits\b", r"\b0 occurrences\b",
    r"no call captured", r"no calls observed", r"\bnever called\b",
    r"无调用捕获", r"未触发",
)
_ENV_FAULT_PATTERNS = (r"stalled", r"never reconnected", r"\breconnect",
                       r"未触发", r"timeout")
_STATIC_MARKERS = (r"\bxref", r"disasm", r"decompile", r"capstone", r"ghidra",
                   r"\bida\b", r"call graph", r"callsite")
_ORCH_CAPTURED = r"orchestrator[- ]captured"


def extract_self_caveat(fact_text: str) -> str | None:
    """Extract self_caveat value from YAML frontmatter.

    Returns the self_caveat string if present and non-empty, else None.
    Guardrails SS1b: worker marks self_caveat when verifier is runtime-unavailable.
    """
    if not fact_text or "self_caveat" not in fact_text:
        return None
    # Frontmatter is between --- delimiters at the start
    fm = re.match(r"^---\s*\n(.*?)\n---", fact_text, re.DOTALL)
    if not fm:
        return None
    fm_text = fm.group(1)
    m = re.search(r"^self_caveat:\s*(.+)$", fm_text, re.MULTILINE)
    if not m:
        return None
    val = m.group(1).strip().strip('"').strip("'")
    return val if val else None


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
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    # #98: self_caveat check before sign-off (guardrails SS1b)
    self_caveat = extract_self_caveat(fact_text)
    if self_caveat is not None:
        return (False, STAMP,
                f"self_caveat: {self_caveat} "
                f"(guardrails SS1b: verifier runtime-unavailable, "
                f"claim {claim_id} cannot be PROVEN without independent BLIND verification)")
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
    verdict = str(signoff["verdict"]).upper()  # _REQUIRED_FIELDS guarantees presence
    if verdict == "REFUTE":
        return (False, STAMP,
                f"BLIND verifier REFUTED claim {claim_id}: {signoff.get('refute_attempt', '')}")
    return (True, "PROVEN",
            f"BLIND verified by {signoff.get('verifier_id', '?')} "
            f"at {signoff.get('sign_off_at', '?')}")


# =====================================================================
# Verifier-DISPATCH evidence gate (issue #57, gate 5)
# =====================================================================
# A claim may not reach PROVEN-candidate unless a verifier was EVER
# dispatched for it. This composes with (does not replace) check_proven_gate:
# the sign-off block says "a verifier approved"; this gate says "a verifier
# was dispatched through the corridor at all" (maker-checker §1b/§6.3 — a
# maker's self-declared result is STAMP-not-PROVEN until an independent
# adversarial agent fails to refute it, and "dispatched" is observable).
# NOT a verdict-quality judgment — verdicts stay with the existing BLIND /
# contradiction / inference / provenance gates.

# Verifier-class agents (agents/): the unified adversarial checker and the
# verdict scorer. A dispatch row counts as verifier evidence when its actor
# or detail names one of these (worker_budget's dispatch lifecycle writes
# `agent=<name>` into the row detail, #461).
VERIFIER_AGENT_MARKERS = ("kunglao-redteam", "verdict-scorer")

# The kunglao-redteam write contract (its ONLY artifact): the DIFF at
# runs/verify-redteam-<target>.md naming the claim.
REDTEAM_DIFF_GLOB = "verify-redteam-*.md"


def _dispatch_row_is_verifier(row: dict, claim_id: str) -> bool:
    """One kunglao_log row: a dispatch-shaped row attributed to THIS claim
    from a verifier-class actor/agent."""
    if str(row.get("claim") or "") != claim_id:
        return False
    if "dispatch" not in str(row.get("action") or ""):
        return False
    actor = str(row.get("actor") or "")
    detail = str(row.get("detail") or "")
    return (actor.startswith("verifier:")
            or any(m in actor or m in detail for m in VERIFIER_AGENT_MARKERS))


def _verifier_dispatch_rows(ws: Path, claim_id: str) -> list[tuple[str, int]]:
    """Distinct verifier-class dispatch rows for the claim, as (log, line)
    identities — counted by the #16 depth gate, sensed by the #57 gate."""
    rows: list[tuple[str, int]] = []
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for log in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            lines = log.read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            if not line.strip() or claim_id not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and _dispatch_row_is_verifier(
                    row, claim_id):
                rows.append((log.name, idx))
    return rows


def _log_has_verifier_dispatch_row(ws: Path, claim_id: str) -> bool:
    """Scan runs/logs/kunglao-*.jsonl for a verifier-class dispatch row."""
    return bool(_verifier_dispatch_rows(ws, claim_id))


def check_verifier_dispatch_evidence(ws: Path, claim_id: str) -> tuple[bool, str]:
    """Was a verifier EVER dispatched for this claim? (issue #57, gate 5)

    Evidence (any one suffices, all read-only, claim-scoped):
      1. the red-team write contract — a runs/verify-redteam-*.md DIFF whose
         text names the claim;
      2. a unified-log dispatch row — runs/logs/kunglao-*.jsonl with
         action=dispatch, claim=<claim_id>, and a verifier-class agent named
         in the actor or detail (or a `verifier:`-prefixed actor).

    Returns (ok, reason). ok=False means the PROVEN promotion is BLOCKED and
    `reason` carries the concrete repair path (dispatch the verifier first).
    Missing records are NOT fail-open: a promotion without a dispatched
    verifier is exactly the protocol failure this gate exists to stop.
    """
    ws = Path(ws)
    runs = ws / "runs"
    if runs.is_dir():
        try:
            for diff in sorted(runs.glob(REDTEAM_DIFF_GLOB)):
                try:
                    if claim_id in diff.read_text(
                            encoding="utf-8", errors="replace"):
                        return (True,
                                f"verifier dispatched (red-team DIFF "
                                f"{diff.name} names {claim_id})")
                except OSError:
                    continue
        except OSError:
            pass
    if _log_has_verifier_dispatch_row(ws, claim_id):
        return (True, f"verifier dispatched (dispatch row in "
                      f"runs/logs/ for {claim_id})")
    return (False,
            f"no verifier dispatch evidence for {claim_id} (verifier-dispatch "
            f"gate, #57 gate 5: a claim cannot reach PROVEN-candidate without "
            f"a dispatched verifier). Fix: dispatch the verifier FIRST — e.g. "
            f"`[T1 tools=Read,Grep,Write] claim {claim_id}` to agent "
            f"kunglao-redteam (kunglao-redteam --target claim {claim_id}); "
            f"its DIFF lands at runs/verify-redteam-{claim_id}.md and the "
            f"dispatch row lands in runs/logs/ — then re-run the promotion.")


# =====================================================================
# Verifier-DEPTH evidence gate (issue #16) — difficulty-gated PROVEN bar
# =====================================================================
# Same record vocabulary as gate 5, COUNTED: a hard/max sample (its tier
# resolved by difficulty_thresholds from the #15 feed) must show more than one
# DISTINCT verifier engagement before PROVEN. The #57 gate asks "was a
# verifier ever dispatched"; this gate asks "were there ENOUGH independent
# engagements". Not a verdict-quality judgment — verdicts stay with the
# existing BLIND / contradiction / inference / provenance gates.

def count_claim_verifier_records(ws: Path, claim_id: str) -> dict:
    """Count DISTINCT verifier engagement records for one claim (#16).

    Two record kinds, both read-only and claim-scoped (the #57 shapes):
      - red-team DIFFs: runs/verify-redteam-*.md whose text names the claim;
      - verifier-class dispatch rows in runs/logs/kunglao-*.jsonl.
    One engagement normally emits BOTH, but the DIFF path is fixed per claim
    (re-rounds overwrite it) while dispatch rows accumulate — neither kind
    alone upper-bounds the engagement count and their SUM double-counts one
    round. The engagement count is therefore the MAX over kinds. worker_death
    outcome records (PR #72) stay visible to the orchestrator but a death is
    not a verification — they never count toward depth.
    """
    ws = Path(ws)
    diff_names: set[str] = set()
    runs = ws / "runs"
    if runs.is_dir():
        for diff in sorted(runs.glob(REDTEAM_DIFF_GLOB)):
            try:
                if claim_id in diff.read_text(
                        encoding="utf-8", errors="replace"):
                    diff_names.add(diff.name)
            except OSError:
                continue
    rows = _verifier_dispatch_rows(ws, claim_id)
    n_diffs, n_rows = len(diff_names), len(rows)
    return {"diffs": n_diffs, "dispatch_rows": n_rows,
            "verifications": max(n_diffs, n_rows)}


def check_verifier_depth_evidence(ws: Path, claim_id: str,
                                  required: int) -> tuple[bool, str]:
    """Enough DISTINCT verifier records for the difficulty tier? (issue #16)

    required <= 1 -> trivially satisfied whenever gate 5 would be (legacy
    single-verification behavior — easy/medium never complexify). required > 1
    fails closed: the reason names the count, the requirement, and the
    concrete repair (dispatch another independent verifier round).
    """
    required = max(1, int(required))
    counts = count_claim_verifier_records(ws, claim_id)
    got = counts["verifications"]
    if got >= required:
        return (True, f"verifier depth ok for {claim_id} ({got} distinct "
                      f"record(s) >= required {required})")
    return (False, f"verifier depth insufficient for {claim_id}: {got} "
                   f"distinct verifier record(s) < required {required} "
                   f"(difficulty depth gate, #16). Fix: dispatch another "
                   f"INDEPENDENT verifier round — each round must land its own "
                   f"dispatch row in runs/logs/ and its own DIFF at "
                   f"runs/verify-redteam-*.md naming {claim_id} — then re-run "
                   f"the promotion.")


# =====================================================================
# Inference-scope gate (issue #48) — D1-D4
# =====================================================================

def is_inferential_claim(statement: str, fact_text: str) -> bool:
    """True when the claim statement or fact text (first 4000 chars, mirroring
    find_fact_file's scan window) carries inferential/routing/causal patterns.

    D1: patterns are the mechanical contract (issue keywords verbatim);
    `0 hits` / `0 occurrences` count as inferential as path evidence.
    #56: NEGATIVE-existence conclusions (`does not exist`/`absent`/`not
    present`) are inferential too, so they reach the environmental-negative-
    evidence diagnostic instead of short-circuiting as non-inferential.
    """
    hay = " ".join([statement or "", (fact_text or "")[:4000]]).lower()
    if any(re.search(p, hay) for p in INFERENTIAL_PATTERNS):
        return True
    return any(re.search(p, hay) for p in _NEGATIVE_EXISTENCE_PATTERNS)


def _has_env_negative_basis(text: str) -> bool:
    """#56 — broadened environmental-negative-evidence basis: BP 0 hits /
    0 occurrences / no call captured / no calls observed (CJK variant included). The
    F040 incident's self-report vocabulary extends beyond literal `0 hits`."""
    return any(re.search(p, text.lower()) for p in _ENV_NEGATIVE_BASIS_PATTERNS)


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
    # #98: self_caveat check before sign-off (guardrails SS1b)
    self_caveat = extract_self_caveat(fact_text)
    if self_caveat is not None:
        return (False, STAMP,
                f"INFERENCE gate: self_caveat: {self_caveat} "
                f"(guardrails SS1b: verifier runtime-unavailable)")
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
    verdict = str(signoff["verdict"]).upper()  # _REQUIRED_FIELDS guarantees presence
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
    if _has_env_negative_basis(fact_text) and _has_env_fault(fact_text):
        # RED4 / a2b5e25c F040 (#56 generalization): a dynamic miss — BP 0
        # hits / no call captured / no calls observed — while the debuggee
        # self-reports an env fault cannot establish a routing OR existence
        # conclusion. Independent static xref is mandatory.
        return (False, STAMP,
                f"INFERENCE gate: environmental negative evidence cannot establish "
                f"routing or existence ({claim_id}) — dynamic miss observed while "
                f"provenance self-reports env fault; require independent static xref")
    return (False, STAMP,
            f"INFERENCE gate: byte-anchor sign-off insufficient for inferential "
            f"claim {claim_id} — require independent static evidence "
            f"(xref/disasm/decompile)")
